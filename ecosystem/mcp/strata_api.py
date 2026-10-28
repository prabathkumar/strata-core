#!/usr/bin/env python3
"""The six tools, as plain Python functions returning plain dictionaries.

Each one answers the same way whether it succeeded or not: a dict with an
`ok` flag and, where the toolchain had something to say, a `diagnostics` list
whose entries carry the taxonomy's classification and remediation strategy
alongside the compiler's own. An agent should never have to read prose to
find out what happened.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

from strata_tools import (
    StrataToolError, TIMEOUT, TIER_OF_BLOCK, imports_of,
    top_level_blocks, toml_value,
)


# ── diagnostics ─────────────────────────────────────────────────────────

def _parse_json_output(stdout, stderr, rc):
    """`strata ... --json` promises JSON on stdout. Say so plainly when not.

    A tool that returns half an answer on a bad day is worse than one that
    says it has none, because the agent cannot tell the difference.
    """
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        raise StrataToolError(
            "the toolchain did not answer in JSON "
            f"(exit {rc}); stdout={stdout[:300]!r} stderr={stderr[:300]!r}")


def _diagnostics(tc, payload, default_file=None):
    out = []
    for d in payload.get("diagnostics", []):
        g = tc.enrich(d)
        # The parse stage omits the per-diagnostic `file`, so it is filled in
        # from the file that was asked about. A diagnostic without a file is
        # one an agent cannot act on.
        if not g.get("file") and default_file:
            g["file"] = default_file
        if g.get("file"):
            g["file"] = os.path.abspath(g["file"])
            try:
                g["relative_file"] = os.path.relpath(g["file"], tc.root)
            except ValueError:
                pass
        out.append(g)
    return out


def _unscratch(obj, work, real):
    """Rewrite scratch paths back into the caller's own, everywhere they show.

    A diagnostic naming /tmp/strata-mcp-ab12cd/payables/src/main.sta is true
    and useless: the agent has to open the file the user has, not the copy
    this server made and deleted. The compiler puts the path in the message
    text as well as in the field, so both are rewritten.
    """
    work = os.path.realpath(work)
    real = os.path.realpath(real)
    if isinstance(obj, str):
        return obj.replace(work, real)
    if isinstance(obj, list):
        return [_unscratch(x, work, real) for x in obj]
    if isinstance(obj, dict):
        return {k: _unscratch(v, work, real) for k, v in obj.items()}
    return obj


# ── 1. check ────────────────────────────────────────────────────────────

def strata_check(tc, path):
    """Type-check one file, or a project's entry point, and report structurally.

    Read-only: `strata check` writes nothing, which is why this one is the
    only tool that runs against the caller's own directory.
    """
    p = tc.safe_path(path)
    if os.path.isdir(p):
        proj = p
        main = toml_value(os.path.join(p, "Strata.toml"), "main") or "src/main.sta"
        target = tc.safe_path(main, base=proj)
    else:
        target = p
        proj = tc.project_of(target) or os.path.dirname(target)
    rc, stdout, stderr = tc.run(["check", target, "--json"], cwd=proj)
    payload = _parse_json_output(stdout, stderr, rc)
    diags = _diagnostics(tc, payload, default_file=target)
    return {
        "ok": bool(payload.get("ok")) and rc == 0,
        "file": target,
        "relative_file": os.path.relpath(target, tc.root),
        "project": proj,
        "stage": payload.get("stage"),
        "exit_code": rc,
        "error_count": payload.get("error_count", len([d for d in diags])),
        "advisory_count": payload.get("advisory_count", 0),
        "diagnostics": diags,
    }


# ── a scratch copy, so nothing the caller owns is written ───────────────

def _scratch_copy(tc, project_dir, extra_projects=()):
    """Copy a project, and any sibling that depends on it, into /tmp.

    The sibling matters more than it looks. The phone tier of `apps/payables`
    is a SEPARATE project that takes the schema as a dependency, so a copy of
    `apps/payables` alone would report a rename as breaking five tiers and
    quietly miss the sixth -- which is the exact failure the language exists
    to prevent, reproduced by the tool meant to demonstrate it.
    """
    tmp = tempfile.mkdtemp(prefix="strata-mcp-")
    parent = os.path.dirname(os.path.realpath(project_dir))
    names = [os.path.basename(project_dir)] + [os.path.basename(p) for p in extra_projects]
    copied = {}
    for name in names:
        src = os.path.join(parent, name)
        dst = os.path.join(tmp, name)
        if name in copied:
            continue
        shutil.copytree(src, dst, symlinks=True,
                        ignore=shutil.ignore_patterns("build", ".strata", ".git",
                                                      "_to_delete", "__pycache__"))
        copied[name] = dst
    return tmp, copied


def _dependents_of(tc, project_dir):
    """Sibling projects whose Strata.toml names this one as a path dependency."""
    parent = os.path.dirname(os.path.realpath(project_dir))
    me = os.path.basename(project_dir)
    found = []
    if not os.path.isdir(parent):
        return found
    for name in sorted(os.listdir(parent)):
        d = os.path.join(parent, name)
        toml = os.path.join(d, "Strata.toml")
        if name == me or not os.path.isfile(toml):
            continue
        try:
            text = open(toml).read()
        except OSError:
            continue
        if re.search(rf'^\s*{re.escape(me)}\s*=\s*\{{[^}}]*path\s*=\s*"[^"]*{re.escape(me)}"',
                     text, re.M):
            found.append(d)
    return found


# ── 2. build and run ────────────────────────────────────────────────────

def _project_and_main(tc, path):
    p = tc.safe_path(path)
    if os.path.isdir(p):
        proj = p
        main = toml_value(os.path.join(p, "Strata.toml"), "main") or "src/main.sta"
        return proj, tc.safe_path(main, base=proj)
    proj = tc.project_of(p)
    if proj is None:
        raise StrataToolError(
            f"{path!r} is not inside a project (no Strata.toml at or above it)")
    return proj, p


def strata_build(tc, path, out=None, workspace="scratch"):
    """Compile, and report exit status, both streams and the diagnostics.

    `workspace` defaults to "scratch" because the compiler emits a `.c` file
    beside every `.sta` it reads. An agent asking "does this build?" has not
    asked for ten generated files in the caller's source directory, and on a
    checkout under version control those show up as changes nobody made.

    In "scratch" the binary still survives, in a directory of its own under
    /tmp, because a build whose output you cannot run has not finished. Only
    the copied sources are thrown away.
    """
    proj, main = _project_and_main(tc, path)
    if workspace not in ("scratch", "project"):
        raise StrataToolError('workspace must be "scratch" or "project"')
    if out is not None and (not isinstance(out, str) or "\x00" in out):
        raise StrataToolError("out must be a path")

    tmp = None
    try:
        if workspace == "scratch":
            tmp, copied = _scratch_copy(tc, proj, _dependents_of(tc, proj))
            work = copied[os.path.basename(proj)]
            target = os.path.join(work, os.path.relpath(main, proj))
            # `out` names the FILE, not where it lands: a scratch build that
            # wrote into the copy would be deleted with it, and one that
            # wrote into the caller's tree would defeat the point of a copy.
            keep = tempfile.mkdtemp(prefix="strata-mcp-out-")
            out_path = os.path.join(keep, os.path.basename(out) if out
                                    else os.path.basename(proj))
            out_note = ("built in a throwaway copy of the project; `out` was "
                        "used as a file name only, and the binary is the path "
                        "in `output`. The caller's project was not written to.")
        else:
            work, target = proj, main
            out_path = (tc.safe_path(out, base=proj, must_exist=False) if out
                        else os.path.join(proj, "build", os.path.basename(proj)))
            out_note = ("built in place: a generated .c file was written beside "
                        "every source the compiler read")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        rc, stdout, stderr = tc.run(["build", target, "-o", out_path, "--json"],
                                    cwd=work)
        payload = _parse_json_output(stdout, stderr, rc)
        diags = _diagnostics(tc, payload, default_file=target)
        if workspace == "scratch":
            diags = _unscratch(diags, work, proj)
        built = os.path.isfile(out_path)
        return {
            "ok": bool(payload.get("ok")) and rc == 0 and built,
            "project": proj,
            "file": main,
            "relative_file": os.path.relpath(main, tc.root),
            "workspace": workspace,
            "stage": payload.get("stage"),
            "exit_code": rc,
            "stdout": stdout if not payload else "",
            "stderr": stderr,
            "output": out_path if built else None,
            "output_exists": built,
            "error_count": payload.get("error_count", 0),
            "advisory_count": payload.get("advisory_count", 0),
            "diagnostics": diags,
            "note": out_note,
        }
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def strata_run(tc, path, workspace="scratch", args=None):
    """Build, then run the binary, keeping the two apart.

    `strata run` compiles and executes in one go and prints the compiler's
    progress on the same stream as the program's own output, so a caller
    reading stdout gets "[Strata Stage 0] Compiling..." mixed into the
    answer. Here the build happens first and the binary is executed on its
    own, which is why `stdout` below is the program's and nothing else.

    `args` is a list of strings handed straight to the program as argv. It is
    never joined into a shell string, so a value containing a semicolon is an
    argument containing a semicolon and nothing more.
    """
    proj, main = _project_and_main(tc, path)
    if args is None:
        args = []
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise StrataToolError("args must be a list of strings")
    if any("\x00" in a for a in args):
        raise StrataToolError("an argument cannot contain a null byte")

    tmp = None
    out_dir = None
    try:
        if workspace == "scratch":
            tmp, copied = _scratch_copy(tc, proj, _dependents_of(tc, proj))
            work = copied[os.path.basename(proj)]
            target = os.path.join(work, os.path.relpath(main, proj))
        elif workspace == "project":
            work, target = proj, main
        else:
            raise StrataToolError('workspace must be "scratch" or "project"')

        out_dir = tempfile.mkdtemp(prefix="strata-mcp-run-")
        binary = os.path.join(out_dir, os.path.basename(proj))
        rc, bout, berr = tc.run(["build", target, "-o", binary, "--json"], cwd=work)
        payload = _parse_json_output(bout, berr, rc)
        if not payload.get("ok") or not os.path.isfile(binary):
            return {
                "ok": False,
                "phase": "build",
                "project": proj,
                "file": main,
                "relative_file": os.path.relpath(main, tc.root),
                "workspace": workspace,
                "exit_code": rc,
                "stdout": "",
                "stderr": berr,
                "error_count": payload.get("error_count", 0),
                "diagnostics": (_unscratch(
                    _diagnostics(tc, payload, default_file=target), work, proj)
                    if workspace == "scratch" else
                    _diagnostics(tc, payload, default_file=target)),
                "note": "the program was never run, because it did not build",
            }

        try:
            r = subprocess.run([binary] + args, cwd=work, capture_output=True,
                               text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            raise StrataToolError(
                f"the program did not finish within {TIMEOUT}s")
        return {
            "ok": r.returncode == 0,
            "phase": "run",
            "project": proj,
            "file": main,
            "relative_file": os.path.relpath(main, tc.root),
            "workspace": workspace,
            "args": args,
            "exit_code": r.returncode,
            "stdout": r.stdout,
            "stderr": r.stderr,
            "diagnostics": [],
            "note": ("run in a throwaway copy: anything the program wrote to a "
                     "data file was discarded. Pass workspace=\"project\" to run "
                     "against the real data."
                     if workspace == "scratch" else
                     "run in place against the caller's own data files"),
        }
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        if out_dir:
            shutil.rmtree(out_dir, ignore_errors=True)


# ── 3. schema ───────────────────────────────────────────────────────────

def strata_schema(tc, project_dir):
    """Every `database` block in a project: its columns, their types, where.

    The columns come from `strata ast`, which is the compiler's own reading
    and therefore the one that counts. The line numbers do not -- the AST
    carries none -- so they are found by looking for the declaration in the
    text, and any that could not be found is reported as null rather than
    guessed at.
    """
    proj = tc.safe_path(project_dir)
    if not os.path.isdir(proj):
        raise StrataToolError(f"{project_dir!r} is not a directory")

    tables = []
    unreadable = []
    for f in tc.sta_files(proj):
        rc, stdout, stderr = tc.run(["ast", f], cwd=proj)
        if rc != 0:
            # `strata ast` prints a Python traceback when a file does not
            # parse. There is nothing structured to salvage, so the file is
            # named as unreadable instead of being silently skipped.
            first = (stderr or stdout).strip().splitlines()
            unreadable.append({
                "file": f,
                "relative_file": os.path.relpath(f, tc.root),
                "reason": first[-1] if first else f"strata ast exited {rc}",
            })
            continue
        try:
            unit = json.loads(stdout)
        except json.JSONDecodeError:
            unreadable.append({"file": f,
                               "relative_file": os.path.relpath(f, tc.root),
                               "reason": "strata ast did not answer in JSON"})
            continue
        decls = [d for d in unit.get("declarations", [])
                 if d.get("node") == "DatabaseDecl"]
        if not decls:
            continue
        try:
            src = open(f).read()
        except OSError:
            src = ""
        spans = {b["name"]: b for b in top_level_blocks(src) if b["kind"] == "database"}
        for d in decls:
            name = d.get("name")
            span = spans.get(name)
            cols = []
            for fld in d.get("fields", []):
                col = fld.get("name")
                line = None
                if span and src:
                    lines = src.splitlines()
                    lo = (span["start_line"] or 1) - 1
                    hi = span["end_line"] or len(lines)
                    for n in range(lo, min(hi, len(lines))):
                        if re.search(rf"\b{re.escape(col)}\b\s*;", lines[n]):
                            line = n + 1
                            break
                cols.append({
                    "name": col,
                    "type": (fld.get("type") or {}).get("name"),
                    "line": line,
                })
            tables.append({
                "table": name,
                "file": f,
                "relative_file": os.path.relpath(f, tc.root),
                "line": span["start_line"] if span else None,
                "columns": cols,
            })
    return {
        "ok": True,
        "project": proj,
        "table_count": len(tables),
        "tables": sorted(tables, key=lambda t: (t["relative_file"], t["table"] or "")),
        "unreadable_files": unreadable,
    }


# ── 4. rename impact ────────────────────────────────────────────────────

def _tier_for(path, line, blocks, imports, is_entry_point):
    """Which tier a diagnostic belongs to, and the evidence for saying so.

    The evidence string is not decoration. This is a judgement made from the
    shape of the file rather than from anything the compiler said, so an
    agent -- or a person reading the output -- should be able to see what it
    was made from and disagree with it.
    """
    for b in blocks:
        if b["end_line"] and b["start_line"] <= line <= b["end_line"]:
            tier = TIER_OF_BLOCK.get(b["kind"])
            if tier:
                label = f'{b["kind"]} {b["name"]}'.strip()
                return tier, f"line {line} is inside the `{label}` block"
    if ("ui", "std") in imports:
        return "phone", "the file imports `ui`, which is the phone and screen tier"
    if is_entry_point:
        return "program", "the file is the project's entry point in Strata.toml"
    return "rules", "ordinary program code, outside any block"


def strata_rename_impact(tc, project_dir, table, column, new_name):
    """Rename a column in a copy, then report every place that stops building.

    This is the tool that shows what the language is for. The rename is
    applied to ONE line -- the column's declaration in its `database` block --
    and nothing else is touched, so everything that comes back is a
    consequence the compiler found rather than a change that was made.

    The work happens in /tmp. The caller's project is read and never written,
    and that is checked by `test_server.py` rather than only promised here.
    """
    proj = tc.safe_path(project_dir)
    if not os.path.isdir(proj):
        raise StrataToolError(f"{project_dir!r} is not a directory")
    for label, value in (("table", table), ("column", column), ("new_name", new_name)):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_]\w*", value or ""):
            raise StrataToolError(
                f"{label} must be a plain identifier, got {value!r}")
    if column == new_name:
        raise StrataToolError("the new name is the old name")

    dependents = _dependents_of(tc, proj)
    tmp, copied = _scratch_copy(tc, proj, dependents)
    parent = os.path.dirname(os.path.realpath(proj))

    def as_users_own(path):
        """A path in the copy, named as the path the caller actually has.

        The copy keeps each project under its own name beside its siblings,
        exactly as they sit in the real tree, so this is a substitution
        rather than a guess. An agent handed a /tmp path would go and read a
        file that no longer exists.
        """
        real = os.path.join(parent, os.path.relpath(path, tmp))
        try:
            return os.path.relpath(real, tc.root)
        except ValueError:
            return real

    try:
        work = copied[os.path.basename(proj)]

        # ── find the declaration, in the copy ───────────────────────────
        decl_file = decl_line = None
        for f in tc.sta_files(work):
            src = open(f).read()
            for b in top_level_blocks(src):
                if b["kind"] != "database" or b["name"] != table:
                    continue
                lines = src.splitlines(keepends=True)
                lo, hi = b["start_line"] - 1, (b["end_line"] or len(lines))
                for n in range(lo, min(hi, len(lines))):
                    if re.search(rf"\b{re.escape(new_name)}\b\s*;", lines[n]):
                        raise StrataToolError(
                            f"'{table}' already has a column called '{new_name}'")
                for n in range(lo, min(hi, len(lines))):
                    if re.search(rf"\b{re.escape(column)}\b\s*;", lines[n]):
                        lines[n] = re.sub(rf"\b{re.escape(column)}\b(\s*;)",
                                          new_name + r"\1", lines[n], count=1)
                        decl_file, decl_line = f, n + 1
                        break
                if decl_file:
                    with open(f, "w") as fh:
                        fh.write("".join(lines))
                    break
            if decl_file:
                break
        if decl_file is None:
            raise StrataToolError(
                f"no column '{column}' declared in `database {table}` "
                f"anywhere in {os.path.basename(proj)}")

        # ── resolve dependencies in the copy, then check every file ─────
        for name, path in copied.items():
            if path != work:
                tc.run(["deps"], cwd=path)

        seen = {}
        checked = []
        for name, path in sorted(copied.items()):
            for f in tc.sta_files(path):
                rc, stdout, stderr = tc.run(["check", f, "--json"], cwd=path)
                checked.append(os.path.relpath(f, tmp))
                try:
                    payload = json.loads(stdout)
                except json.JSONDecodeError:
                    continue
                for d in payload.get("diagnostics", []):
                    g = tc.enrich(d)
                    gf = os.path.realpath(g.get("file") or f)
                    key = (gf, g.get("line"), g.get("column"), g.get("code"),
                           g.get("message"))
                    if key in seen:
                        continue
                    g["file"] = gf
                    seen[key] = g

        # ── say which tier each one is ──────────────────────────────────
        cache = {}
        impacts = []
        for key, g in seen.items():
            f = g["file"]
            if f not in cache:
                try:
                    src = open(f).read()
                except OSError:
                    src = ""
                blocks = top_level_blocks(src)
                proj_of = None
                for name, path in copied.items():
                    if f.startswith(os.path.realpath(path) + os.sep):
                        proj_of = path
                        break
                entry = None
                if proj_of:
                    m = toml_value(os.path.join(proj_of, "Strata.toml"), "main")
                    if m:
                        entry = os.path.realpath(os.path.join(proj_of, m))
                cache[f] = (blocks, imports_of(src), f == entry, proj_of)
            blocks, imports, is_entry, proj_of = cache[f]
            tier, why = _tier_for(f, g.get("line") or 0, blocks, imports, is_entry)
            impacts.append({
                "tier": tier,
                "tier_evidence": why,
                "project": os.path.basename(proj_of) if proj_of else None,
                "file": as_users_own(f),
                "line": g.get("line"),
                "column": g.get("column"),
                "code": g.get("code"),
                "message": g.get("message"),
                "hint": g.get("hint"),
                "classification": g.get("classification"),
                "severity": g.get("severity"),
                "ai_remediation_strategy": g.get("ai_remediation_strategy"),
            })
        impacts.sort(key=lambda i: (i["file"], i["line"] or 0))

        by_tier = {}
        for i in impacts:
            by_tier.setdefault(i["tier"], 0)
            by_tier[i["tier"]] += 1
        # The declaration's own tier counts, even though renaming a column
        # cannot make its own declaration fail to compile. A report that said
        # five tiers when six hold the column would be an undercount.
        by_tier.setdefault("data", 0)

        return {
            "ok": True,
            "project": proj,
            "table": table,
            "column": column,
            "new_name": new_name,
            "declaration": {
                "tier": "data",
                "file": as_users_own(decl_file),
                "line": decl_line,
                "note": "the one line that was changed",
            },
            "projects_checked": sorted(copied),
            "files_checked": len(checked),
            "impact_count": len(impacts),
            "tiers_broken": sorted(t for t, n in by_tier.items() if n),
            "tiers_touched": sorted(by_tier),
            "impacts_by_tier": dict(sorted(by_tier.items())),
            "impacts": impacts,
            "note": ("applied to a copy under /tmp and discarded; "
                     "the caller's project was not modified"),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── 5. test ─────────────────────────────────────────────────────────────

_BLOCK_RE = re.compile(r"^  (?!\s)(?P<name>.+?)\s*$")
_FAIL_RE = re.compile(r"^\s{4,}FAIL\s+(?P<detail>.*)$")
_COUNT_RE = re.compile(r"^\s+(\d+) block\(s\), (\d+) assertion\(s\), (\d+) failed")
_VERDICT_RE = re.compile(r"^\s*(PASS|FAIL|BUILD FAIL):\s*(?P<file>\S+)")
_SUMMARY_RE = re.compile(r"\[Strata Test\]\s+(\d+) passed, (\d+) failed")


def strata_test(tc, project_dir, workspace="scratch"):
    """Run a project's `verify` blocks and report pass or fail for each.

    `strata test` prints text and has no `--json`, so this parses its output.
    That parse is the weakest thing in this server and is called out in the
    README: a change to the wording of those lines would quietly turn a
    failing block into an unreported one, which is why the raw output is
    returned alongside the parse for a caller that wants to check the work.
    """
    proj = tc.safe_path(project_dir)
    if not os.path.isdir(proj):
        raise StrataToolError(f"{project_dir!r} is not a directory")

    tmp = None
    try:
        if workspace == "scratch":
            tmp, copied = _scratch_copy(tc, proj, _dependents_of(tc, proj))
            work = copied[os.path.basename(proj)]
        else:
            work = proj
        # `strata test <dir>` resolves the files it finds against the CURRENT
        # directory rather than against <dir>, so pointing it at a project
        # from outside makes it fail to find its own test files. Running from
        # inside with "." is the form that works.
        rc, stdout, stderr = tc.run(["test", "."], cwd=work)

        text = stdout + stderr
        blocks = []
        current = None
        for line in text.splitlines():
            fail = _FAIL_RE.match(line)
            if fail and current:
                current["failures"].append(fail.group("detail").strip())
                current["passed"] = False
                continue
            count = _COUNT_RE.match(line)
            if count:
                continue
            verdict = _VERDICT_RE.match(line.strip())
            if verdict:
                current = None
                continue
            if line.startswith("[Strata Test]"):
                current = None
                continue
            m = _BLOCK_RE.match(line)
            if m and m.group("name") and not line.startswith("    "):
                current = {"block": m.group("name"), "passed": True, "failures": []}
                blocks.append(current)

        files = [{"file": m.group("file"), "result": m.group(1)}
                 for m in (_VERDICT_RE.match(l.strip()) for l in text.splitlines())
                 if m]
        summary = _SUMMARY_RE.search(text)
        return {
            "ok": rc == 0,
            "project": proj,
            "workspace": workspace,
            "exit_code": rc,
            "blocks": blocks,
            "blocks_total": len(blocks),
            "blocks_failed": sum(1 for b in blocks if not b["passed"]),
            "files": files,
            "files_passed": int(summary.group(1)) if summary else None,
            "files_failed": int(summary.group(2)) if summary else None,
            "raw_output": text,
            "note": "parsed from text; `strata test` has no --json. "
                    "raw_output is the authority if the two disagree.",
        }
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


# ── 6. taxonomy ─────────────────────────────────────────────────────────

def strata_taxonomy(tc, code=None):
    """The whole error taxonomy, or one entry of it.

    An agent that meets a code it has not seen should be able to look it up
    rather than guess from the message, and a retired code should still
    resolve -- E005 is in the file precisely so an old stored diagnostic does
    not become unreadable.
    """
    t = tc.taxonomy()
    if code:
        if not re.fullmatch(r"[A-Za-z0-9_]+", code or ""):
            raise StrataToolError(f"{code!r} is not an error code")
        entry = t.get("taxonomy", {}).get(code)
        if entry is None:
            return {"ok": False, "code": code, "known": False,
                    "known_codes": sorted(t.get("taxonomy", {}))}
        return {"ok": True, "code": code, "known": True, "entry": entry,
                "version": t.get("version")}
    return {"ok": True, "version": t.get("version"),
            "standard_authority": t.get("standard_authority"),
            "code_count": len(t.get("taxonomy", {})),
            "taxonomy": t.get("taxonomy", {})}
