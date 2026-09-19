#!/usr/bin/env python3
"""Both compilers report the same diagnostics as data.

Human-readable compiler text is compared elsewhere. This compares the --json
payload: the thing editors, CI and the repair agent actually read. A field
that drifts here is invisible to a person reading the terminal and breaks
every automated consumer at once.

Compared as parsed JSON, field by field, so key order and whitespace do not
count -- only the content does.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "build", "json_cli")
CASES = os.path.join(ROOT, "test_suite", "typecheck_cases")
FIELDS = ["code", "file", "classification", "severity", "message", "line",
          "column", "hint", "remediation_strategy"]


def bootstrap_json(rel):
    r = subprocess.run(
        [sys.executable, "bootstrap/stage0.py", rel, "--json"],
        cwd=ROOT, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def driver_json(rel):
    r = subprocess.run([CLI, ROOT, rel], cwd=ROOT, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def compare(rel, want, got):
    problems = []
    for key in ("stage", "ok", "error_count", "advisory_count"):
        if want.get(key) != got.get(key):
            problems.append(f"{key}: bootstrap {want.get(key)!r}, strata {got.get(key)!r}")
    wd, gd = want.get("diagnostics", []), got.get("diagnostics", [])
    if len(wd) != len(gd):
        problems.append(f"{len(wd)} diagnostics from the bootstrap, {len(gd)} from strata")
        return problems
    for i, (w, g) in enumerate(zip(wd, gd)):
        for f in FIELDS:
            if w.get(f) != g.get(f):
                problems.append(
                    f"diagnostic {i} {w.get('code')} field {f}:\n"
                    f"      bootstrap: {w.get(f)!r}\n"
                    f"      strata:    {g.get(f)!r}")
    return problems


def main():
    if not os.path.isfile(CLI):
        print(f"  building {os.path.relpath(CLI, ROOT)}")
        os.makedirs(os.path.dirname(CLI), exist_ok=True)
        b = subprocess.run(
            [sys.executable, "bootstrap/stage0.py", "compiler/json_cli.sta",
             "-o", CLI], cwd=ROOT, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("  Could not build the Strata side. FAIL")
            return 1

    cases = sorted(f for f in os.listdir(CASES) if f.endswith(".sta"))
    agree = skipped = 0
    failures = []
    for name in cases:
        rel = os.path.relpath(os.path.join(CASES, name), ROOT)
        want = bootstrap_json(rel)
        if want is None:
            skipped += 1
            continue
        got = driver_json(rel)
        if got is None:
            failures.append((rel, ["strata produced no JSON"]))
            continue
        problems = compare(rel, want, got)
        if problems:
            failures.append((rel, problems))
        else:
            agree += 1

    print("=" * 62)
    for rel, problems in failures[:12]:
        print(f"  {rel}")
        for p in problems:
            print(f"    {p}")
    if len(failures) > 12:
        print(f"  ... and {len(failures) - 12} more files")
    print(f"  {agree}/{agree + len(failures)} agree, {skipped} skipped")
    print("=" * 62)
    if failures:
        print("  The two compilers report different diagnostics. FAIL")
        return 1
    print("  Machine-readable diagnostics are identical. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
