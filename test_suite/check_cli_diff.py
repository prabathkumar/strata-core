#!/usr/bin/env python3
"""`strata check` says exactly what it said when it was a Python script.

The check itself has been Strata for a while; the reporting around it was a
Python script embedded in the toolchain, which meant a second implementation
of "which diagnostics stop a build" and therefore a second thing to get wrong.
It had been wrong: it treated the E007 advisory as an error, the opposite of
what the taxonomy says.

This pins the replacement to the original, character for character, over every
.sta file in the tree -- stdout, stderr and exit status.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")
SKIP_DIRS = {".git", "build", "node_modules", "Claude outputs", "_to_delete",
             "unimplemented", "repair_cases", ".strata"}

ORACLE = r'''
import sys, os
sys.path.insert(0, os.environ["STRATA_ROOT"])
from compiler.lexer import LexError
from compiler.parser import ParseError
from bootstrap.stage0 import parse_file, resolve_imports
from compiler.typechecker import TypeChecker

f = sys.argv[1]
try:
    ast = parse_file(f)
    modules, _, root_unresolved, app_modules = resolve_imports(ast, f)
    errs = TypeChecker(ast, filename=f,
                       modules=None if root_unresolved else modules,
                       unresolved_imports=root_unresolved,
                       project_modules=app_modules).check()
except (LexError, ParseError) as e:
    print(str(e), file=sys.stderr); sys.exit(1)

ADVISORY_CODES = {"E007"}
advisories = [e for e in errs if e.code in ADVISORY_CODES]
hard = [e for e in errs if e.code not in ADVISORY_CODES]
for e in advisories:
    print(f"[Strata Check] advisory: {e}")
if hard:
    print(f"[Strata Check] {len(hard)} error(s) found:", file=sys.stderr)
    for e in hard:
        print(f"  {e}", file=sys.stderr)
    sys.exit(1)
print(f"  {len(ast.imports)} imports, {len(modules)} resolved module(s), "
      f"{len(ast.declarations)} decls, {len(ast.functions)} functions")
print("[Strata Check] No errors. OK")
'''


def sources():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.endswith(".sta"):
                yield os.path.relpath(os.path.join(dirpath, name), ROOT)


def oracle(rel):
    env = dict(os.environ, STRATA_ROOT=ROOT)
    head = f"[Strata Check] Analysing '{rel}'...\n"
    r = subprocess.run([sys.executable, "-c", ORACLE, rel], cwd=ROOT,
                       capture_output=True, text=True, env=env)
    return head + r.stdout, r.stderr, r.returncode


def actual(rel):
    r = subprocess.run([STRATA, "check", rel], cwd=ROOT,
                       capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode


def main():
    checked = same = 0
    divergent = []
    for rel in sources():
        want = oracle(rel)
        got = actual(rel)
        checked += 1
        if want == got:
            same += 1
        else:
            divergent.append((rel, want, got))

    print("=" * 62)
    for rel, want, got in divergent[:6]:
        print(f"  {rel}")
        for label, w, g in zip(("stdout", "stderr", "exit"), want, got):
            if w != g:
                print(f"    {label} was:  {w!r}")
                print(f"    {label} is:   {g!r}")
    if len(divergent) > 6:
        print(f"  ... and {len(divergent) - 6} more")
    print(f"  {same}/{checked} identical, {len(divergent)} divergent")
    print("=" * 62)
    if divergent:
        print("  strata check no longer says what it said. FAIL")
        return 1
    print("  strata check is unchanged, and no longer needs Python. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
