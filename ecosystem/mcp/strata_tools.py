#!/usr/bin/env python3
"""The work behind the MCP server: run the Strata toolchain, answer in JSON.

Kept apart from `server.py` so the protocol and the toolchain can be wrong
independently. `server.py` knows about JSON-RPC and nothing about Strata;
this file knows about Strata and nothing about JSON-RPC, and `test_server.py`
drives the pair of them from outside.

Two rules run through everything here.

The first is that a caller cannot name a path outside the tree the server was
pointed at. An agent asking a question is not the same as a person typing one,
and "../../.ssh/id_rsa" is a perfectly ordinary looking string.

The second is that the caller's own files are never written. `strata check` is
read-only and runs where it stands. `strata build`, `strata run` and
`strata test` all write a `.c` file beside every `.sta` they touch, so those
run against a throwaway copy unless the caller says otherwise -- an agent
exploring a codebase should not leave fingerprints on it.
"""
import json
import os
import re
import subprocess

TIMEOUT = 300

# The tiers this server will name. The point of the language is that one
# change reaches all of them, so an agent being told WHICH tier broke is the
# difference between a list of errors and an answer.
TIER_OF_BLOCK = {
    "database": "data",
    "layout": "web",
    "report": "report",
    "verify": "test",
    "screen": "phone",
    "model": "rules",
}
BLOCK_KEYWORDS = tuple(TIER_OF_BLOCK) + ("foreign", "migrate")


class StrataToolError(Exception):
    """Something the caller asked for cannot be done, and it is their fault."""


# ── where things are ────────────────────────────────────────────────────

def find_root(start):
    """The top of a Strata checkout: the directory holding the toolchain.

    Both markers are required. `bin/strata` alone would match a half-copied
    tree, and the taxonomy is the thing that makes a diagnostic worth more
    than its text, so a tree without it is not one this server can serve.
    """
    d = os.path.realpath(start)
    while True:
        if (os.path.isfile(os.path.join(d, "bin", "strata"))
                and os.path.isfile(os.path.join(d, "ERROR_TAXONOMY.json"))):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise StrataToolError(
                f"no Strata checkout at or above {start!r} "
                "(looked for bin/strata and ERROR_TAXONOMY.json)")
        d = parent


def _is_within(parent, child):
    parent = os.path.realpath(parent)
    child = os.path.realpath(child)
    return child == parent or child.startswith(parent + os.sep)


class Toolchain:
    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.strata = os.path.join(self.root, "bin", "strata")
        if not os.path.isfile(self.strata):
            raise StrataToolError(f"no bin/strata under {self.root}")
        self._taxonomy = None

    # ── paths ───────────────────────────────────────────────────────────

    def safe_path(self, candidate, base=None, must_exist=True):
        """Resolve a caller's path, refusing anything that leaves `base`.

        Resolved with realpath BEFORE the check, so a symlink pointing out of
        the tree is caught rather than followed. A relative path is read
        against `base`, which is the only reading that cannot depend on which
        directory this process happens to be sitting in.
        """
        base = os.path.realpath(base or self.root)
        if not isinstance(candidate, str) or not candidate.strip():
            raise StrataToolError("a path is required")
        if "\x00" in candidate:
            raise StrataToolError("a path cannot contain a null byte")
        p = candidate if os.path.isabs(candidate) else os.path.join(base, candidate)
        p = os.path.realpath(p)
        if not _is_within(base, p):
            raise StrataToolError(
                f"{candidate!r} resolves outside {base} and will not be used")
        if must_exist and not os.path.exists(p):
            raise StrataToolError(f"{candidate!r} does not exist")
        return p

    def project_of(self, path):
        """The nearest directory at or above `path` holding a Strata.toml.

        Module imports (`import rules from app`) are resolved against the
        project, so running the toolchain from anywhere else gives answers
        about a different program than the one the caller asked about.
        """
        d = path if os.path.isdir(path) else os.path.dirname(path)
        while _is_within(self.root, d):
            if os.path.isfile(os.path.join(d, "Strata.toml")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        return None

    # ── running the toolchain ───────────────────────────────────────────

    def run(self, args, cwd, timeout=TIMEOUT):
        """Always an argument list, never a shell string.

        Every value in `args` after the first has been through `safe_path` or
        is a literal written here. Nothing the caller sends is ever handed to
        a shell to re-interpret.
        """
        env = dict(os.environ)
        env.setdefault("PKG_CONFIG_PATH",
                       os.path.join(os.path.expanduser("~"), "osslshim", "pkgconfig"))
        try:
            r = subprocess.run([self.strata] + list(args), cwd=cwd, env=env,
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise StrataToolError(
                f"the toolchain did not finish within {timeout}s: strata {' '.join(args)}")
        return r.returncode, r.stdout, r.stderr

    # ── the taxonomy ────────────────────────────────────────────────────

    def taxonomy(self):
        if self._taxonomy is None:
            with open(os.path.join(self.root, "ERROR_TAXONOMY.json")) as f:
                self._taxonomy = json.load(f)
        return self._taxonomy

    def enrich(self, diag):
        """Add what the taxonomy knows about a code to the compiler's answer.

        The compiler already prints a `remediation_strategy`, and for some
        codes it is NOT the one in ERROR_TAXONOMY.json -- E000 is a plain
        example. Both are kept, under names that say which is which, because
        an agent silently handed the wrong one of two disagreeing answers is
        worse off than one handed both.
        """
        out = dict(diag)
        entry = self.taxonomy().get("taxonomy", {}).get(diag.get("code"))
        if entry:
            out["classification"] = entry.get("classification", out.get("classification"))
            out["severity"] = entry.get("severity", out.get("severity"))
            out["taxonomy_diagnostic"] = entry.get("diagnostic")
            out["ai_remediation_strategy"] = entry.get("ai_remediation_strategy")
            out["taxonomy_known"] = True
        else:
            out["taxonomy_known"] = False
            out["ai_remediation_strategy"] = out.get("remediation_strategy")
        if "remediation_strategy" in out:
            out["compiler_remediation_strategy"] = out.pop("remediation_strategy")
        return out

    # ── reading source ──────────────────────────────────────────────────

    def sta_files(self, project_dir):
        """Every Strata source in a project, ignoring build output and copies.

        `.strata/deps` holds symlinks to other projects. Those are checked in
        their own right when they are themselves copied, so walking into them
        here would report one file twice under two names.
        """
        found = []
        for base, dirs, names in os.walk(project_dir):
            dirs[:] = [d for d in dirs
                       if d not in ("build", ".strata", "_to_delete", ".git",
                                    "android", "ios", "__pycache__")]
            for n in sorted(names):
                if n.endswith(".sta"):
                    found.append(os.path.join(base, n))
        return sorted(found)


# ── a crude but careful reader of block structure ───────────────────────

def top_level_blocks(src):
    """The `database`/`layout`/`report`/`verify` blocks in a file, with spans.

    Written here rather than taken from the compiler because `strata ast`
    carries no line numbers, and the line number is the whole reason this
    exists: it is what turns "views.sta is broken" into "the page is broken".

    Brace counting with comments and string literals skipped. It does not
    need to be a parser -- it only needs to know, for a line number the
    compiler has already given us, which block that line sits in. A file the
    compiler rejects outright never gets this far.
    """
    blocks = []
    depth = 0
    i = 0
    line = 1
    n = len(src)
    pending = None            # a block header seen, waiting for its '{'
    at_line_start = True
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            at_line_start = True
            continue
        if c in " \t":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += src.count("\n", i, j)
            i = j
            at_line_start = False
            continue
        if c == '"':
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == '"':
                    j += 1
                    break
                if src[j] == "\n":
                    line += 1
                j += 1
            i = j
            at_line_start = False
            continue
        if c == "{":
            depth += 1
            if pending and depth == 1:
                pending["open_depth"] = 1
            i += 1
            at_line_start = False
            continue
        if c == "}":
            depth -= 1
            if pending and depth == 0:
                pending["end_line"] = line
                blocks.append(pending)
                pending = None
            i += 1
            at_line_start = False
            continue
        if at_line_start and depth == 0 and (c.isalpha() or c == "_"):
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            if word in BLOCK_KEYWORDS:
                name = ""
                m = re.match(r'\s*(?:"([^"]*)"|([A-Za-z_]\w*))', src[j:])
                if m:
                    name = m.group(1) or m.group(2) or ""
                pending = {"kind": word, "name": name,
                           "start_line": line, "end_line": None}
            i = j
            at_line_start = False
            continue
        i += 1
        at_line_start = False
    return blocks


def imports_of(src):
    return set(re.findall(r"^\s*import\s+(\w+)\s+from\s+(\w+)\s*;", src, re.M))


def toml_value(path, key):
    """One key out of a Strata.toml, without a TOML parser.

    The standard library has `tomllib` only from Python 3.11, and this project
    ships no dependencies, so the two keys actually needed are read by hand.
    """
    try:
        with open(path) as f:
            for raw in f:
                line = raw.split("#", 1)[0].strip()
                m = re.match(rf'^{key}\s*=\s*"([^"]*)"', line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None
