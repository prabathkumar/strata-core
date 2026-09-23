#!/usr/bin/env python3
"""A program that resets its scratch memory must not grow.

This is the difference between a language for batch jobs and a language for
servers. Strata frees nothing individually: temporaries come from an arena,
and scratch_reset() throws the whole arena away at a boundary the program
chooses. If that works, a server can run for a week. If it quietly does not,
the process grows until something kills it -- at three in the morning, in
production, months after anyone touched the code.

So this measures rather than trusts. The same work is run twice, once with
resets and once without, and the resident set size of each is compared. The
version with resets must stay flat while the version without climbs.
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

PROGRAM = """
import io from std;
import mem from std;
import str from std;

database Note { int id; str body; }

int main() {
    Note <- [id = 1, body = "persistent"];
    int r = 0;
    while (r < %(rounds)d) {
        int j = 0;
        while (j < 2000) {
            str t = str_concat("customer ", str(j));
            t = str_concat(t, " | region apac | amount 1250.50");
            j = j + 1;
        }
%(reset)s
        r = r + 1;
    }
    print(str_concat("held ", str(scratch_used())));
    list[Note] kept = Note <- [id == 1];
    print(str_concat("table ", kept[0].body));
    return 0;
}
"""


def run(tmp, name, rounds, reset):
    src = os.path.join(tmp, name + ".sta")
    with open(src, "w") as f:
        f.write(PROGRAM % {"rounds": rounds,
                           "reset": "        scratch_reset();" if reset else ""})
    binary = os.path.join(tmp, name)
    build = subprocess.run([STRATA, "build", src, "-o", binary],
                           capture_output=True, text=True)
    if build.returncode != 0:
        return None, None, None, build.stderr or build.stdout
    proc = subprocess.run(["/usr/bin/time", "-v", binary],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None, None, None, proc.stderr
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", proc.stderr)
    if not m:
        return None, None, None, "could not read peak memory from /usr/bin/time"
    held = re.search(r"held (\d+)", proc.stdout)
    table = "table persistent" in proc.stdout
    return int(m.group(1)), int(held.group(1)) if held else -1, table, None


def main():
    print("=" * 62)
    print("  Scratch memory is given back")
    print("=" * 62)

    if not os.path.exists("/usr/bin/time"):
        print("  /usr/bin/time is not here; cannot measure. SKIP")
        print("=" * 62)
        return 0

    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        # The same number of temporaries either way: 2000 rounds of 2000 with
        # resets, 500 rounds of 2000 without. The version with resets does
        # four times the work and must still use less memory.
        kb_reset, held_reset, table_reset, err1 = run(tmp, "with_reset", 2000, True)
        kb_leak, held_leak, _, err2 = run(tmp, "no_reset", 500, False)

    for err in (err1, err2):
        if err:
            failures.append(err.strip().splitlines()[-1] if err.strip() else "build failed")

    if not failures:
        print(f"  4,000,000 temporaries, resetting:  {kb_reset:>7} KB peak, "
              f"{held_reset} bytes held")
        print(f"  1,000,000 temporaries, no reset:   {kb_leak:>7} KB peak, "
              f"{held_leak} bytes held")

        if held_reset != 0:
            failures.append(
                f"scratch_reset() left {held_reset} bytes behind; it must leave none")
        if not table_reset:
            failures.append(
                "a row stored in a table did not survive the resets -- a reset "
                "must throw away temporaries only")
        # Four times the work in a tenth of the memory, with room to spare for
        # allocator differences between machines.
        if kb_reset > kb_leak / 4:
            failures.append(
                f"resetting used {kb_reset} KB against {kb_leak} KB for a quarter "
                f"of the work: memory is not being reused")

    if failures:
        for f in failures:
            print(f"  {f}")
        print("=" * 62)
        print("  Scratch memory is not given back. FAIL")
        return 1

    print("=" * 62)
    print("  Four times the work, a fraction of the memory. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
