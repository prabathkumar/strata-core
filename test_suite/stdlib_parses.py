#!/usr/bin/env python3
"""Every standard library module must parse with the compiler that ships with it.

This lives in a script rather than inline in the workflow so it can be run
locally exactly as CI runs it. The previous inline version was indented inside
the YAML block, which made Python raise IndentationError on every file — the
check reported failure for reasons that had nothing to do with the stdlib.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bootstrap.stage0 import parse_file  # noqa: E402


def main():
    std = os.path.join(ROOT, "std")
    files = sorted(f for f in os.listdir(std) if f.endswith(".sta"))
    failed = 0
    print(f"\n── Standard library parse ({len(files)} modules) ────────────────")
    for name in files:
        path = os.path.join(std, name)
        try:
            parse_file(path)
            print(f"  PASS  std/{name}")
        except BaseException as e:
            print(f"  FAIL  std/{name} — {str(e)[:70]}")
            print(f"::error file=std/{name}::does not parse")
            failed += 1
    print("\n" + "=" * 62)
    print(f"  {len(files) - failed} parse, {failed} fail")
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
