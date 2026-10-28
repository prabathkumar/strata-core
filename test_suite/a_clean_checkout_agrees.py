#!/usr/bin/env python3
"""The two checkers agree on a tree nobody has run `strata deps` in.

This exists because of how round 17's worst CI failure hid.

`strata check` is implemented twice -- once in Python as the oracle, once in
Strata itself -- and `check_cli_diff.py` compares them over the whole tree on
every commit. It was green on every machine the compiler is developed on and
red on GitHub, and the whole difference was one directory: `.strata/deps`.
Once a developer has run `strata deps` even once, the phone app resolves, the
unfetched-dependency path is never taken, and the two checkers are never
compared on it. On a fresh clone it is the FIRST path taken, and there they
disagreed by twenty-five diagnostics -- the self-hosted one giving advice
that round 14 had already replaced in the oracle.

The comparison itself is not reimplemented here. This copies the tree to a
scratch directory WITHOUT any fetched dependency or build output -- the state
a new developer is in on the day they clone -- and runs the existing
comparator inside the copy. A green result in a working tree therefore says
nothing this one does not also say about a clean one.

Run: python3 test_suite/a_clean_checkout_agrees.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    print()
    print("── a clean checkout agrees ───" + "─" * 36)
    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, "tree")
        # .strata is the fetched dependency; build holds compiled checkers
        # that would otherwise be reused and hide a change to the source.
        shutil.copytree(ROOT, dest, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "build",
                                                      ".strata"))
        for rel in ("apps/orders_mobile", "apps/payables_mobile"):
            d = os.path.join(dest, rel, ".strata")
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
        print(f"  a copy of the tree with no .strata anywhere: {dest}")
        r = subprocess.run([sys.executable,
                            os.path.join("test_suite", "check_cli_diff.py")],
                           cwd=dest, capture_output=True, text=True,
                           timeout=1800)
        out = r.stdout + r.stderr
        tail = [l for l in out.splitlines() if l.strip()][-6:]
        for l in tail:
            print("  " + l)
        print()
        print("=" * 62)
        if r.returncode == 0:
            print("  A fresh clone sees what this tree sees. OK")
            return 0
        print("  A fresh clone would see something this tree cannot. FAIL")
        print("  The run above is the whole comparison, in a copy with no")
        print("  fetched dependencies. Reproduce it by hand with:")
        print("      rm -rf apps/*_mobile/.strata && "
              "python3 test_suite/check_cli_diff.py")
        return 1


if __name__ == "__main__":
    sys.exit(main())
