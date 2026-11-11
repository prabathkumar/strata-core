#!/usr/bin/env python3
"""A lock file left by a killed process does not cost every later write.

`save` takes a lock file for the microseconds between asking "has this file
changed since I read it?" and renaming the new one over it, so that two runs
cannot both pass the check and both write. The loop that takes it gives up
after two seconds rather than blocking for ever, and the comment above it
said why: "a lock file left behind by a process somebody killed must not
wedge every run afterwards".

It did, near enough. Killing a test server mid-request left the file behind,
and every write afterwards paid the full two seconds -- twice per request,
because a request takes two locks -- until a person noticed the file and
deleted it. Past a client's timeout that is a service which answers nothing,
from one crash, with no message anywhere saying why.

The file was never the lock. The PROCESS is. So the lock file now records
whose it is, and a run that finds one belonging to a process that no longer
exists removes it and carries on. A file with no owner written in it yet is
either a lock being taken in this very microsecond or rubbish from something
else entirely; the first is newer than two seconds and the second is not.

Run: python3 test_suite/a_crash_does_not_wedge_the_next_run.py
"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

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


SRC = '''import io from std;
database Row { int id; str who; }
int main() {
    if (file_exists("t.tsv") == 1) { load Row from "t.tsv"; }
    Row <- [id = 1, who = "a"];
    save Row to "t.tsv";
    print("saved");
    return 0;
}'''


def main():
    print()
    print("── a crash does not wedge the next run ─" + "─" * 24)

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.sta")
        open(p, "w").write(SRC)
        binary = os.path.join(d, "s.bin")
        b = subprocess.run([STRATA, "build", p, "-o", binary],
                           capture_output=True, text=True, timeout=900)
        if b.returncode != 0:
            print("  FAIL  the probe does not build")
            print((b.stdout + b.stderr)[-500:])
            return 1

        lock = os.path.join(d, "t.tsv.strata-lock")

        def run_timed():
            t0 = time.time()
            r = subprocess.run([binary], cwd=d, capture_output=True,
                               text=True, timeout=120)
            return time.time() - t0, r

        # A clean run, for the baseline.
        clean, r = run_timed()
        ok("a save with no lock in the way works", r.returncode == 0
           and "saved" in r.stdout, (r.stdout + r.stderr)[-200:])
        ok("and does not leave its lock behind", not os.path.exists(lock),
           "the lock file outlived the process that took it")

        # The shape the crash leaves: a lock naming a process that is gone.
        # A pid this large cannot be running.
        open(lock, "w").write("99999999\n")
        held, r = run_timed()
        ok("a lock owned by a process that no longer exists is taken over",
           r.returncode == 0 and "saved" in r.stdout,
           (r.stdout + r.stderr)[-200:])
        ok("and it does not cost two seconds to notice",
           held < 1.0, f"took {held:.2f}s, baseline {clean:.2f}s")
        ok("and the dead lock is gone afterwards", not os.path.exists(lock),
           "a stale lock survived the run that took it over")

        # Rubbish with no owner in it, old enough that it cannot be a lock
        # somebody is taking right now.
        open(lock, "w").write("")
        os.utime(lock, (time.time() - 60, time.time() - 60))
        old, r = run_timed()
        ok("an old lock with no owner written in it is taken over",
           r.returncode == 0 and "saved" in r.stdout,
           (r.stdout + r.stderr)[-200:])
        ok("and that is quick too", old < 1.0, f"took {old:.2f}s")

        # The other direction: a lock being taken RIGHT NOW must be waited
        # for, not stolen. A fresh file with no owner is exactly that, and
        # the run should pay the full wait rather than barge in.
        open(lock, "w").write("")
        fresh, r = run_timed()
        ok("a lock taken in this very moment is waited for, not stolen",
           fresh >= 1.0, f"took {fresh:.2f}s -- it did not wait")
        ok("and the save still completes rather than failing",
           r.returncode == 0 and "saved" in r.stdout,
           (r.stdout + r.stderr)[-200:])
        if os.path.exists(lock):
            os.remove(lock)

        # The data survived all of that.
        rows = [l for l in open(os.path.join(d, "t.tsv")).read().splitlines()[1:]
                if l.strip()]
        # Four runs above, each adding one row to what it loaded. A refused
        # save would show up here as a missing row rather than as a message.
        ok("and every one of the four saves landed",
           len(rows) == 4, f"{len(rows)} rows, expected 4")

    print()
    print("=" * 62)
    print(f"  {passed} ok, {len(failures)} failed")
    print("=" * 62)
    if failures:
        for f in failures:
            print("  - " + f[:300])
        print("  One crash can wedge every write again. FAIL")
        return 1
    print("  A crash does not wedge the next run. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
