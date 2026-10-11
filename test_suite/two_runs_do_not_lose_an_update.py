#!/usr/bin/env python3
"""Two programs writing the same table at the same time.

A cron job overlapping a manual run is an ordinary Monday. Both load, both
change a row, both save -- and the second save simply replaced the first
one's work. Both exited 0. Nothing anywhere said a write had been thrown
away, which is the quietest way a system loses data.

There is no lock held across the read and the write, and a lock is not the
answer: it either blocks a batch job behind a person or deadlocks. What this
checks is that the loss is NOTICED. The file's identity is recorded when the
table is read, and a save that finds a different one refuses -- the rows it
would write never saw whatever arrived in between.

The two halves of that have to be one step. Checking "has this changed?" and
then renaming are two, and two runs could both pass the check before either
renamed. They happen under a lock file held for microseconds now, so:

    saves that succeeded == increments in the file

is exact, however many runs there are.
"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

RUNS = 16

failures = []
passed = 0


def ok(label, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}")
        failures.append(f"{label}: {detail}")


PROGRAM = """import io from std;

database Counter { int id; int n; }

int main() {
    load Counter from "c.tsv";
    list[Counter] all = Counter <- [id > 0];
    for C in all { C.n = C.n + 1; }
    int s = save Counter to "c.tsv";
    if (s == 0) { print("refused"); clear_error(); }
    return 0;
}
"""

START = "#strata\tCounter\tid:i\tn:i\n1\t0\n"


def counter_in(path):
    rows = [r for r in open(path).read().split("\n") if r and not r.startswith("#")]
    return int(rows[-1].split("\t")[1])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "bump.sta")
        open(src, "w").write(PROGRAM)
        binary = os.path.join(tmp, "bump")
        r = subprocess.run([STRATA, "build", src, "-o", binary],
                           capture_output=True, text=True, cwd=tmp, timeout=600)
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-400:])
            print("  Could not build the program. FAIL")
            return 1

        print("\n── one run at a time ───────────────────────────────────")
        open(os.path.join(tmp, "c.tsv"), "w").write(START)
        refused = 0
        for _ in range(RUNS):
            p = subprocess.run([binary], cwd=tmp, capture_output=True,
                               text=True, timeout=300)
            if "refused" in p.stdout:
                refused += 1
        ok("nothing is refused when nothing overlaps", refused == 0,
           f"{refused} of {RUNS}")
        ok("and every run counted",
           counter_in(os.path.join(tmp, "c.tsv")) == RUNS,
           str(counter_in(os.path.join(tmp, "c.tsv"))))

        print("\n── one run reads, another writes, the first saves ──────")
        # Deterministic rather than hopeful. The slow program loads, then
        # waits for a file to appear before it saves; in between, a second
        # program loads and saves. A test that relies on winning a race
        # passes on a quiet machine and proves nothing.
        slow = os.path.join(tmp, "slow.sta")
        open(slow, "w").write(
            'import io from std;\n\n'
            'database Counter { int id; int n; }\n\n'
            'int main() {\n'
            '    load Counter from "c.tsv";\n'
            '    list[Counter] all = Counter <- [id > 0];\n'
            '    for C in all { C.n = C.n + 100; }\n'
            '    print("loaded");\n'
            '    while (file_exists("go") == 0) { }\n'
            '    int s = save Counter to "c.tsv";\n'
            '    if (s == 0) { print("refused"); clear_error(); }\n'
            '    return 0;\n}\n')
        slow_bin = os.path.join(tmp, "slow")
        r = subprocess.run([STRATA, "build", slow, "-o", slow_bin],
                           capture_output=True, text=True, cwd=tmp, timeout=600)
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-400:])
            print("  Could not build the second program. FAIL")
            return 1

        open(os.path.join(tmp, "c.tsv"), "w").write(START)
        held = subprocess.Popen([slow_bin], cwd=tmp, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        # Wait until it has read the file, so the write below is strictly
        # after its read.
        waited = 0.0
        while waited < 30.0:
            line = held.stdout.readline()
            if "loaded" in line:
                break
            waited += 0.05
            time.sleep(0.05)
        subprocess.run([binary], cwd=tmp, capture_output=True, text=True,
                       timeout=300)
        open(os.path.join(tmp, "go"), "w").write("")
        out = held.communicate(timeout=300)[0]
        ok("the save that would discard the other run is refused",
           "refused" in out, out[-200:])
        ok("and the other run's work is what is in the file",
           counter_in(os.path.join(tmp, "c.tsv")) == 1,
           str(counter_in(os.path.join(tmp, "c.tsv"))))

        print("\n── all at once ─────────────────────────────────────────")
        open(os.path.join(tmp, "c.tsv"), "w").write(START)
        procs = [subprocess.Popen([binary], cwd=tmp, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
                 for _ in range(RUNS)]
        outs = [p.communicate(timeout=300)[0] for p in procs]
        refused = sum(1 for o in outs if "refused" in o)
        saved = RUNS - refused
        final = counter_in(os.path.join(tmp, "c.tsv"))
        print(f"  {RUNS} runs: {saved} saved, {refused} refused, "
              f"file says {final}")
        # The whole point. Every save that was allowed is in the file, and
        # every one that was not said so.
        ok("every save that succeeded is in the file", saved == final,
           f"{saved} saved, file says {final}")
        # Not "some must be refused": whether these overlap depends on the
        # machine, and a test that demands a race is a test that fails on a
        # quiet morning. The invariant above is the real claim, and the
        # deterministic case above proves the refusal happens.
        ok("no scratch file is left behind",
           not any(n.endswith(".strata-tmp") for n in os.listdir(tmp)),
           str(os.listdir(tmp)))
        ok("no lock file is left behind",
           not any(n.endswith(".strata-lock") for n in os.listdir(tmp)),
           str(os.listdir(tmp)))

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  An update can still be lost in silence. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  A write that would discard another run's is refused, not taken. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
