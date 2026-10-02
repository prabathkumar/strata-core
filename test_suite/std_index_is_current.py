#!/usr/bin/env python3
"""The self-hosted checker's table of std functions matches std/.

E011 names the module a missing function comes from -- "Add 'import str from
std;'" rather than "import the module that defines it", which was the one
place in a whole evaluation where a pilot got stuck and had to grep.

The oracle works that out by reading std/. The language has no directory
listing, so the self-hosted checker carries a table instead, and a table is a
second copy of a fact: add a function to std/ and the two disagree, silently,
in the direction of a worse diagnostic. This rebuilds the table from std/ and
compares.

When it fails, the fix is mechanical: it prints the line to paste.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def from_std():
    index = {}
    std = os.path.join(ROOT, "std")
    for name in sorted(n for n in os.listdir(std) if n.endswith(".sta")):
        text = open(os.path.join(std, name)).read()
        for m in re.finditer(
                r"^(?:def|[A-Za-z_][\w\[\]]*)\s+([a-z_]\w*)\s*\(", text, re.M):
            index.setdefault(m.group(1), name[:-4])
    return index


def from_strata():
    src = open(os.path.join(ROOT, "compiler", "typechecker.sta")).read()
    m = re.search(r'str STD_INDEX\(\) \{\s*return "([^"]*)";', src)
    if not m:
        return None
    out = {}
    for pair in m.group(1).strip(",").split(","):
        if ":" in pair:
            k, v = pair.split(":", 1)
            out[k] = v
    return out


def main():
    want = from_std()
    got = from_strata()
    print("\n── The std index in both checkers is the same ──────────────────")
    if got is None:
        print("  FAIL  compiler/typechecker.sta has no STD_INDEX() to compare")
        return 1
    missing = {k: v for k, v in want.items() if got.get(k) != v}
    extra = {k: v for k, v in got.items() if k not in want}
    print(f"  the oracle reads {len(want)} names out of std/")
    print(f"  the self-hosted checker carries {len(got)}")
    if not missing and not extra:
        print("  ok    they agree")
        print("=" * 64)
        print("  Both checkers name the same module. OK")
        return 0
    for k, v in sorted(missing.items())[:10]:
        print(f"  FAIL  '{k}' is in std/{v}.sta and the table says "
              f"{got.get(k, '(nothing)')!r}")
    for k in sorted(extra)[:10]:
        print(f"  FAIL  the table has '{k}', which std/ does not declare")
    rebuilt = "," + ",".join(f"{k}:{v}" for k, v in sorted(want.items())) + ","
    print("\n  Paste this as the body of STD_INDEX() in "
          "compiler/typechecker.sta:")
    print(f'    return "{rebuilt}";')
    print("=" * 64)
    print("  The two checkers would give different hints. FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
