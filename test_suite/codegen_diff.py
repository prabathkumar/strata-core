#!/usr/bin/env python3
"""Differential test: compiler/codegen.sta against the code generator in stage0.

Stage 4 of self-hosting, and the strictest comparison of the four: generated C
is compared byte for byte. A token stream or a syntax tree has some freedom in
how it is represented; emitted code has none, because the next tool in the
chain is a C compiler that will notice any difference.

Both implementations read the runtime prelude from compiler/runtime_preamble.c,
so a divergence here is always about code generation rather than about two
copies of the same 76 lines of C drifting apart.

Usage:  python3 test_suite/codegen_diff.py [files...]
"""
import difflib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CODEGEN_SRC = os.path.join(ROOT, "compiler", "codegen_cli.sta")
CODEGEN_BIN = os.path.join(ROOT, "build", "strata-codegen-sta")


def oracle(path):
    from bootstrap.stage0 import CodeGen, parse_file, resolve_imports
    ast = parse_file(path)
    modules, _, _ = resolve_imports(ast, path)
    return CodeGen(ast, path, modules).generate()


def build():
    os.makedirs(os.path.dirname(CODEGEN_BIN), exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "bootstrap", "stage0.py"),
                        CODEGEN_SRC, "-o", CODEGEN_BIN],
                       capture_output=True, text=True, cwd=ROOT)
    return r.returncode == 0, (r.stderr or r.stdout)


def candidate(path):
    r = subprocess.run([CODEGEN_BIN, path], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        return None, (r.stderr or "").strip()[:200]
    return r.stdout, ""


def corpus():
    files = []
    for d in ("std", "examples", "test_suite", "compiler"):
        full = os.path.join(ROOT, d)
        if os.path.isdir(full):
            files += [os.path.join(full, f) for f in sorted(os.listdir(full))
                      if f.endswith(".sta")]
    return files


def first_diff(want, got):
    wl, gl = want.splitlines(), got.splitlines()
    for i in range(max(len(wl), len(gl))):
        w = wl[i] if i < len(wl) else "<missing>"
        g = gl[i] if i < len(gl) else "<missing>"
        if w != g:
            return i + 1, w, g
    return None, "", ""


def main():
    if not os.path.exists(CODEGEN_SRC):
        print(f"No {os.path.relpath(CODEGEN_SRC, ROOT)} yet — nothing to compare.")
        return 0
    ok, err = build()
    if not ok:
        print("Strata code generator failed to compile:\n" + err[:600])
        return 1

    files = sys.argv[1:] or corpus()
    passed = failed = skipped = 0
    print(f"\n── Code generator differential ({len(files)} files) ─────────────")
    for f in files:
        rel = os.path.relpath(f, ROOT)
        try:
            want = oracle(f)
        except BaseException as e:
            print(f"  SKIP  {rel} — oracle cannot generate: {str(e)[:52]}")
            skipped += 1
            continue
        got, err = candidate(f)
        if got is None:
            print(f"  FAIL  {rel} — {err}")
            failed += 1
            continue
        if got.rstrip("\n") == want.rstrip("\n"):
            print(f"  PASS  {rel} ({len(want.splitlines())} lines of C)")
            passed += 1
        else:
            n, w, g = first_diff(want, got)
            print(f"  FAIL  {rel} — first divergence at line {n}")
            print(f"          oracle: {w[:88]}")
            print(f"          strata: {g[:88]}")
            failed += 1

    print("\n" + "=" * 62)
    print(f"  {passed} identical, {failed} divergent, {skipped} skipped")
    print("=" * 62)
    if failed:
        print("  The Strata code generator does not match the oracle.")
        return 1
    print("  Generated C is byte-identical. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
