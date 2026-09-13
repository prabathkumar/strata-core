#!/usr/bin/env python3
"""Differential test: compiler/parser.sta against compiler/parser.py.

Stage 2 of self-hosting, and the same discipline as the lexer differential:
the Python parser is the oracle, and the Strata parser is correct when it
produces an identical abstract syntax tree — not a similar-looking one.

Trees are compared as parsed JSON rather than as text, so key ordering and
whitespace are irrelevant and only structure counts. On a mismatch the harness
reports the path to the first differing node (e.g.
`functions[0].body[2].value.op`) rather than dumping two trees, because on a
tree of this size a diff is unreadable and a path is actionable.

Usage:  python3 test_suite/parser_diff.py [files...]
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PARSER_SRC = os.path.join(ROOT, "compiler", "parser_cli.sta")
PARSER_BIN = os.path.join(ROOT, "build", "strata-parser-sta")


def oracle_ast(path):
    from compiler.lexer import tokenise_file
    from compiler.parser import Parser
    return Parser(tokenise_file(path)).parse().to_dict()


def build():
    os.makedirs(os.path.dirname(PARSER_BIN), exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "bootstrap", "stage0.py"),
                        PARSER_SRC, "-o", PARSER_BIN],
                       capture_output=True, text=True, cwd=ROOT)
    return r.returncode == 0, (r.stderr or r.stdout)


def candidate_ast(path):
    r = subprocess.run([PARSER_BIN, path], capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stderr or "").strip()[:200]
    try:
        return json.loads(r.stdout), ""
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"


def diff_path(a, b, path="$"):
    """First structural difference between two trees, as a path string."""
    if type(a) is not type(b):
        return f"{path}: oracle {type(a).__name__}, strata {type(b).__name__}"
    if isinstance(a, dict):
        for k in a:
            if k not in b:
                return f"{path}.{k}: missing in strata"
            d = diff_path(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        for k in b:
            if k not in a:
                return f"{path}.{k}: unexpected in strata"
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: oracle has {len(a)} items, strata has {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = diff_path(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    if a != b:
        return f"{path}: oracle {a!r}, strata {b!r}"
    return None


def corpus():
    files = []
    for d in ("std", "examples", "test_suite", "compiler"):
        full = os.path.join(ROOT, d)
        if os.path.isdir(full):
            files += [os.path.join(full, f) for f in sorted(os.listdir(full))
                      if f.endswith(".sta")]
    return files


def main():
    if not os.path.exists(PARSER_SRC):
        print(f"No {os.path.relpath(PARSER_SRC, ROOT)} yet — nothing to compare.")
        return 0
    ok, err = build()
    if not ok:
        print("Strata parser failed to compile:\n" + err[:600])
        return 1

    files = sys.argv[1:] or corpus()
    passed = failed = skipped = 0
    print(f"\n── Parser differential ({len(files)} files) ─────────────────────")
    for f in files:
        rel = os.path.relpath(f, ROOT)
        try:
            want = oracle_ast(f)
        except Exception as e:
            print(f"  SKIP  {rel} — oracle cannot parse it: {str(e)[:60]}")
            skipped += 1
            continue
        got, err = candidate_ast(f)
        if got is None:
            print(f"  FAIL  {rel} — {err}")
            failed += 1
            continue
        d = diff_path(want, got)
        if d is None:
            print(f"  PASS  {rel}")
            passed += 1
        else:
            print(f"  FAIL  {rel}\n          {d}")
            failed += 1

    print("\n" + "=" * 62)
    print(f"  {passed} identical, {failed} divergent, {skipped} skipped")
    print("=" * 62)
    if failed:
        print("  The Strata parser does not match the oracle.")
        return 1
    print("  Syntax trees are identical. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
