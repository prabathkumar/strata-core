#!/usr/bin/env python3
"""Differential test: compiler/typechecker.sta against compiler/typechecker.py.

Stage 3 of self-hosting. The oracle is the Python type checker, and the
comparison is the diagnostic list it produces for each file: error code,
location and message, in order. A type checker that agrees on clean files but
disagrees on broken ones has not been tested at all, so the corpus includes
test_suite/ fixtures that are deliberately wrong.

Diagnostics are compared as `CODE line:col message`. Emitting the same set in a
different order is a divergence, because the repair loop consumes the first
diagnostic and order decides which fix an agent attempts first.

Usage:  python3 test_suite/typecheck_diff.py [files...]
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CHECKER_SRC = os.path.join(ROOT, "compiler", "typechecker_cli.sta")
CHECKER_BIN = os.path.join(ROOT, "build", "strata-checker-sta")


def oracle(path):
    from compiler.lexer import tokenise_file
    from compiler.parser import Parser
    from compiler.typechecker import TypeChecker
    from bootstrap.stage0 import resolve_imports
    ast = Parser(tokenise_file(path)).parse()
    # Imports are resolved here for the same reason the compiler resolves them:
    # without the graph the checker cannot tell a typo'd call from a call into
    # std/. Resolving on both sides is also what makes this suite the
    # false-positive guard for that rule, across every file it covers.
    modules, _, root_unresolved, app_modules = resolve_imports(ast, path)
    errs = TypeChecker(ast, filename=path,
                       modules=None if root_unresolved else modules,
                       unresolved_imports=root_unresolved,
                       project_modules=app_modules).check()
    return [f"{e.code} {e.file}:{e.line}:{e.col} {e.message}" if e.file
            else f"{e.code} {e.line}:{e.col} {e.message}" for e in errs]


def build():
    os.makedirs(os.path.dirname(CHECKER_BIN), exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "bootstrap", "stage0.py"),
                        CHECKER_SRC, "-o", CHECKER_BIN],
                       capture_output=True, text=True, cwd=ROOT)
    return r.returncode == 0, (r.stderr or r.stdout)


def candidate(path):
    r = subprocess.run([CHECKER_BIN, path], capture_output=True, text=True)
    if r.returncode not in (0, 1):
        return None, (r.stderr or "").strip()[:200]
    return [l for l in r.stdout.splitlines() if l.strip()], ""


def corpus():
    files = []
    # typecheck_cases/ holds deliberately broken programs, one per rule. A
    # checker compared only against code that passes has not been compared.
    for d in ("std", "examples", "test_suite", "test_suite/typecheck_cases",
              "compiler", "apps"):
        full = os.path.join(ROOT, d)
        if os.path.isdir(full):
            # Walked rather than listed: an application keeps its sources in
            # src/ under its own directory, so a flat listing of apps/ finds
            # nothing. Quarantined trees are skipped — they do not compile.
            for dirpath, dirnames, names in os.walk(full):
                dirnames[:] = [d for d in dirnames if d != "unimplemented"]
                files += [os.path.join(dirpath, n) for n in sorted(names)
                          if n.endswith(".sta")]
    return files


def main():
    if not os.path.exists(CHECKER_SRC):
        print(f"No {os.path.relpath(CHECKER_SRC, ROOT)} yet — nothing to compare.")
        return 0
    ok, err = build()
    if not ok:
        print("Strata type checker failed to compile:\n" + err[:600])
        return 1

    files = sys.argv[1:] or corpus()
    passed = failed = skipped = 0
    print(f"\n── Type checker differential ({len(files)} files) ───────────────")
    for f in files:
        rel = os.path.relpath(f, ROOT)
        try:
            want = oracle(f)
        except Exception as e:
            print(f"  SKIP  {rel} — oracle cannot check it: {str(e)[:55]}")
            skipped += 1
            continue
        got, err = candidate(f)
        if got is None:
            print(f"  FAIL  {rel} — {err}")
            failed += 1
            continue
        if got == want:
            n = len(want)
            print(f"  PASS  {rel} ({n} diagnostic{'' if n == 1 else 's'})")
            passed += 1
        else:
            print(f"  FAIL  {rel}")
            for i in range(max(len(want), len(got))):
                w = want[i] if i < len(want) else "<none>"
                g = got[i] if i < len(got) else "<none>"
                if w != g:
                    print(f"          oracle: {w}")
                    print(f"          strata: {g}")
                    break
            failed += 1

    print("\n" + "=" * 62)
    print(f"  {passed} identical, {failed} divergent, {skipped} skipped")
    print("=" * 62)
    if failed:
        print("  The Strata type checker does not match the oracle.")
        return 1
    print("  Diagnostics are identical. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
