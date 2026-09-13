#!/usr/bin/env python3
"""Differential test: compiler/lexer.sta against compiler/lexer.py.

The Python lexer is the oracle. The Strata lexer is correct when it produces a
byte-identical token stream over the whole corpus — not when its output "looks
right". This is the discipline that makes bootstrapping safe: at every stage of
self-hosting there is a working implementation to diff against, so a divergence
is located precisely rather than discovered later as a mysterious miscompile.

Canonical format, one token per line:

    KIND<TAB>value<TAB>line<TAB>col

with newline, tab and backslash escaped in `value` so a token never spans lines.

Usage:  python3 test_suite/lexer_diff.py [files...]
        (defaults to the whole corpus: std/, examples/, test_suite/)
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STRATA_LEXER_SRC = os.path.join(ROOT, "compiler", "lexer.sta")
STRATA_LEXER_BIN = os.path.join(ROOT, "build", "strata-lexer-sta")


def escape(v):
    return (v.replace("\\", "\\\\").replace("\n", "\\n")
             .replace("\t", "\\t").replace("\r", "\\r"))


def oracle_dump(path):
    """Token stream from the Python lexer, in canonical form."""
    from compiler.lexer import tokenise_file
    out = []
    for t in tokenise_file(path):
        out.append(f"{t.type.name}\t{escape(str(t.value))}\t{t.line}\t{t.col}")
    return "\n".join(out)


def build_strata_lexer():
    """Compile compiler/lexer.sta with the bootstrap compiler."""
    os.makedirs(os.path.dirname(STRATA_LEXER_BIN), exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "bootstrap", "stage0.py"),
                        STRATA_LEXER_SRC, "-o", STRATA_LEXER_BIN],
                       capture_output=True, text=True, cwd=ROOT)
    return r.returncode == 0, (r.stderr or r.stdout)


def candidate_dump(path):
    r = subprocess.run([STRATA_LEXER_BIN, path], capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stderr or "").strip()[:200]
    return r.stdout.rstrip("\n"), ""


def corpus():
    files = []
    for d in ("std", "examples", "test_suite"):
        full = os.path.join(ROOT, d)
        if os.path.isdir(full):
            files += [os.path.join(full, f) for f in sorted(os.listdir(full))
                      if f.endswith(".sta")]
    return files


def first_divergence(a, b):
    al, bl = a.split("\n"), b.split("\n")
    for i in range(max(len(al), len(bl))):
        x = al[i] if i < len(al) else "<missing>"
        y = bl[i] if i < len(bl) else "<missing>"
        if x != y:
            return i + 1, x, y
    return None, "", ""


def main():
    if not os.path.exists(STRATA_LEXER_SRC):
        print(f"No {STRATA_LEXER_SRC} yet — nothing to compare.")
        return 0

    ok, err = build_strata_lexer()
    if not ok:
        print("Strata lexer failed to compile:\n" + err[:600])
        return 1

    files = sys.argv[1:] or corpus()
    passed = failed = skipped = 0

    print(f"\n── Lexer differential ({len(files)} files) ──────────────────────")
    for f in files:
        rel = os.path.relpath(f, ROOT)
        try:
            want = oracle_dump(f)
        except Exception as e:
            print(f"  SKIP  {rel} — oracle cannot lex it: {str(e)[:60]}")
            skipped += 1
            continue
        got, err = candidate_dump(f)
        if got is None:
            print(f"  FAIL  {rel} — strata lexer errored: {err}")
            failed += 1
            continue
        if got == want:
            print(f"  PASS  {rel} ({len(want.splitlines())} tokens)")
            passed += 1
        else:
            n, x, y = first_divergence(want, got)
            print(f"  FAIL  {rel} — first divergence at token {n}")
            print(f"          oracle: {x}")
            print(f"          strata: {y}")
            failed += 1

    print("\n" + "=" * 62)
    print(f"  {passed} identical, {failed} divergent, {skipped} skipped")
    print("=" * 62)
    if failed:
        print("  The Strata lexer does not match the oracle.")
        return 1
    print("  Token streams are byte-identical. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
