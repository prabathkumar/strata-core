#!/usr/bin/env python3
"""Generate release notes from git history and live verification results.

Every figure in the output is produced by running the suites at generation
time. Nothing is typed in by hand, which is the point: this project has twice
shipped a claim that was false when written — a commit announcing "32/32
passing" against a suite that was failing, and a "self-hosting complete"
milestone for a compiler that did not compile. A release note that states a
number no tool produced is the same failure in a more visible place.

If a suite fails, its number is reported as FAILING rather than omitted, and
the script exits non-zero. Notes for a broken build should look broken.

Usage:
    python3 tools/release_notes.py --version v0.4.0-alpha
    python3 tools/release_notes.py --version v0.4.0-alpha --since v0.3.0-alpha
    python3 tools/release_notes.py --version v0.4.0-alpha --out NOTES.md
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Conventional-commit prefix -> section heading, in output order.
SECTIONS = [
    ("feat",     "Features"),
    ("fix",      "Fixes"),
    ("perf",     "Performance"),
    ("refactor", "Internal"),
    ("test",     "Verification"),
    ("docs",     "Documentation"),
    ("ci",       "Build and CI"),
    ("chore",    "Housekeeping"),
    ("release",  "Release"),
]

SELF_HOSTED = ["compiler/lexer.sta", "compiler/parser.sta",
               "compiler/typechecker.sta", "compiler/codegen.sta"]


def sh(*args, cwd=ROOT):
    r = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def last_tag(exclude=None):
    """Most recent tag, skipping the version now being released.

    Running this at tag time would otherwise diff a release against itself and
    report zero changes.
    """
    code, out, _ = sh("git", "tag", "--sort=-creatordate")
    if code != 0:
        return None
    for t in out.splitlines():
        t = t.strip()
        if t and t != exclude:
            return t
    return None


def commits(since):
    rng = f"{since}..HEAD" if since else "HEAD"
    code, out, _ = sh("git", "log", rng, "--no-merges", "--pretty=format:%s")
    if code != 0:
        return []
    return [l for l in out.splitlines() if l.strip()]


def group(subjects):
    buckets = {key: [] for key, _ in SECTIONS}
    other = []
    for s in subjects:
        m = re.match(r"^(\w+)(\([^)]*\))?!?:\s*(.+)$", s)
        if m and m.group(1) in buckets:
            scope = (m.group(2) or "").strip("()")
            text = m.group(3)
            buckets[m.group(1)].append(f"**{scope}**: {text}" if scope else text)
        else:
            other.append(s)
    return buckets, other


def run_suite(script):
    """Return (ok, summary_line) for a verification suite."""
    path = os.path.join(ROOT, "test_suite", script)
    if not os.path.exists(path):
        return None, "not present"
    code, out, err = sh(sys.executable, path)
    text = out + "\n" + err
    return code == 0, text


def measure():
    """Collect every published figure by running the thing that produces it."""
    facts = {}
    ok_all = True

    ok, text = run_suite("conformance.py")
    if ok is not None:
        m = re.search(r"Results: (\d+)/(\d+) passed", text)
        facts["conformance"] = (f"{m.group(1)}/{m.group(2)} passing" if m and ok
                                else "FAILING")
        ok_all = ok_all and bool(ok)

    for script, label in (("lexer_diff.py", "Lexer"),
                          ("parser_diff.py", "Parser"),
                          ("typecheck_diff.py", "Type checker")):
        ok, text = run_suite(script)
        if ok is None:
            continue
        m = re.search(r"(\d+) identical, (\d+) divergent, (\d+) skipped", text)
        if m and ok:
            facts[label] = f"{m.group(1)} files identical, {m.group(2)} divergent"
        else:
            facts[label] = "FAILING"
        ok_all = ok_all and bool(ok)

    ok, text = run_suite("doc_examples.py")
    if ok is not None:
        m = re.search(r"(\d+) compiling, (\d+) roadmap/known", text)
        facts["Documentation"] = (f"{m.group(1)} examples compiling, "
                                  f"{m.group(2)} marked roadmap") if m and ok else "FAILING"
        ok_all = ok_all and bool(ok)

    ok, text = run_suite("codegen_diff.py")
    if ok is not None:
        m = re.search(r"(\d+) identical, (\d+) divergent, (\d+) skipped", text)
        facts["Code generator"] = (f"{m.group(1)} files byte-identical" if m and ok
                                   else "FAILING")
        ok_all = ok_all and bool(ok)

    ok, text = run_suite("fixpoint.py")
    if ok is not None:
        facts["Self-hosting fixpoint"] = ("reached — bootstrap can be retired"
                                          if ok else "FAILING")
        ok_all = ok_all and bool(ok)

    ok, text = run_suite("self_repair.py")
    if ok is not None:
        m = re.search(r"(\d+)/(\d+) checks passed", text)
        facts["Repair loop"] = (f"{m.group(1)}/{m.group(2)} checks passing"
                                if m and ok else "FAILING")
        ok_all = ok_all and bool(ok)

    ok, text = run_suite("stdlib_parses.py")
    if ok is not None:
        m = re.search(r"(\d+) parse, (\d+) fail", text)
        facts["Standard library"] = (f"{m.group(1)} modules parse" if m and ok
                                     else "FAILING")
        ok_all = ok_all and bool(ok)

    # Self-hosted source size and how much of it is native C.
    total = native = 0
    present = []
    for rel in SELF_HOSTED:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        present.append(rel)
        inside = False
        for line in open(p):
            total += 1
            stripped = line.strip()
            opened = 'native "' in stripped
            if opened:
                inside = True
            if inside:
                native += 1
            # A one-line native — `int f() { native "..."; }` — closes on the
            # same line and does NOT end with the quote, so look for the
            # terminator anywhere after the opening rather than at line end.
            tail = stripped[stripped.index('native "') + 8:] if opened else stripped
            if inside and '";' in tail:
                inside = False
    if total:
        pct = round(native * 100 / total)
        facts["Self-hosted compiler"] = (
            f"{total:,} lines of Strata across {len(present)} stage"
            f"{'' if len(present) == 1 else 's'}, {native} native ({pct}%)")
    return facts, ok_all


def main():
    ap = argparse.ArgumentParser(description="Generate release notes")
    ap.add_argument("--version", required=True)
    ap.add_argument("--since", default=None,
                    help="previous tag (default: most recent tag)")
    ap.add_argument("--out", default=None, help="write here instead of stdout")
    a = ap.parse_args()

    since = a.since or last_tag(exclude=a.version)
    subjects = commits(since)
    buckets, other = group(subjects)
    facts, ok = measure()

    L = []
    L.append(f"# {a.version}\n")
    if since:
        L.append(f"Changes since `{since}` — {len(subjects)} commit"
                 f"{'' if len(subjects) == 1 else 's'}.\n")

    L.append("## Verified at release time\n")
    L.append("Each figure below was produced by running the suite that measures")
    L.append("it, at the moment these notes were generated.\n")
    L.append("| Check | Result |")
    L.append("|---|---|")
    for k, v in facts.items():
        L.append(f"| {k} | {v} |")
    L.append("")
    if not ok:
        L.append("> **This build is not green.** One or more suites failed; the")
        L.append("> rows above marked FAILING say which.\n")

    for key, heading in SECTIONS:
        if buckets.get(key):
            L.append(f"## {heading}\n")
            for item in buckets[key]:
                L.append(f"- {item}")
            L.append("")
    if other:
        L.append("## Other\n")
        for item in other:
            L.append(f"- {item}")
        L.append("")

    text = "\n".join(L)
    if a.out:
        with open(os.path.join(ROOT, a.out), "w") as f:
            f.write(text)
        print(f"wrote {a.out}")
    else:
        print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
