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
import re
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
        # The second half: a step that TOUCHES a project with a path
        # dependency must link it first. Two steps did not, and both were
        # green on every development machine and red on a fresh clone for as
        # long as they had existed, because every machine they were written
        # on had run `strata deps` at some point. This reads the workflow and
        # insists, rather than waiting for the next person to notice.
        wf = os.path.join(ROOT, ".github", "workflows", "build-check.yml")
        if os.path.isfile(wf):
            text = open(wf).read()
            steps = re.split(r"\n    - name: ", text)
            bad = []
            for st in steps[1:]:
                title = st.splitlines()[0].strip()
                for proj in ("apps/orders_mobile", "apps/payables_mobile"):
                    if proj not in st:
                        continue
                    # A step that only runs a test script is fine: the script
                    # is responsible for its own scratch tree.
                    if f"strata deps {proj}" in st:
                        continue
                    if "bin/strata" not in st:
                        continue
                    bad.append(f"{title} uses {proj} without linking it")
            if bad:
                print()
                for b in bad:
                    print("  FAIL  " + b)
                print()
                print("=" * 62)
                print("  A CI step would fail on a fresh clone. FAIL")
                print("  Add `bin/strata deps <project>` before it, which is")
                print("  what FOR_DEVELOPERS.md tells a developer to do.")
                return 1
            print("  every CI step that touches a project with a path "
                  "dependency links it first")

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
