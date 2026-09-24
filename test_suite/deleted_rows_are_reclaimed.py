#!/usr/bin/env python3
"""A table that is emptied and refilled must not grow, and must not lose data.

Two things are checked here because they were found together, and the second
was caused by fixing the first.

`delete` used to drop a row from its table and leave the memory: a query
result might still point at it, and the language had no way to know. That cost
about 34 bytes a row, so a screen rebuilding its rows every frame grew for as
long as it ran. The arena gives a safe moment to reclaim them -- a query result
is arena memory, so when the arena goes, nothing can be pointing at a deleted
row.

Freeing rows then exposed something that had been harmless: an insert stored a
str column's pointer without copying it. A literal was fine, since literals are
static, but a COMPUTED string pointed into the arena, and the table was left
holding freed memory after the next reset. It read as an empty string -- data
loss with no error and no crash. Inserts now copy, and this is the test that
would have caught it.
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

CHURN = """
import io  from std;
import mem from std;
import str from std;

database Item { int id; str text; }

int main() {
    int f = 0;
    while (f < %(rounds)d) {
        delete Item <- [id > 0];
        int i = 0;
        while (i < 20) {
            Item <- [id = i + 1, text = str_concat("row ", str(i))];
            i = i + 1;
        }
        scratch_reset();
        f = f + 1;
    }
    print(str_concat("rows ", str(count(Item <- [id > 0]))));
    return 0;
}
"""

SURVIVES = """
import io  from std;
import mem from std;
import str from std;

database Item { int id; str text; }

int main() {
    Item <- [id = 1, text = str_concat("computed ", "value")];
    scratch_reset();
    list[Item] r = Item <- [id == 1];
    print(str_concat("kept ", r[0].text));
    return 0;
}
"""


def build_run(tmp, name, src, measure=False):
    path = os.path.join(tmp, name + ".sta")
    with open(path, "w") as f:
        f.write(src)
    binary = os.path.join(tmp, name)
    b = subprocess.run([STRATA, "build", path, "-o", binary],
                       capture_output=True, text=True, cwd=tmp)
    if b.returncode != 0:
        return None, None, (b.stderr or b.stdout)
    cmd = ["/usr/bin/time", "-v", binary] if measure else [binary]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)
    if r.returncode != 0:
        return None, r.stdout, f"the program exited {r.returncode}"
    kb = None
    if measure:
        m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", r.stderr)
        kb = int(m.group(1)) if m else None
    return kb, r.stdout, None


def main():
    print("=" * 64)
    print("  Deleted rows are reclaimed, and stored strings are kept")
    print("=" * 64)
    failures = []

    if not os.path.exists("/usr/bin/time"):
        print("  /usr/bin/time is not here; cannot measure. SKIP")
        print("=" * 64)
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        # A stored string must outlive the reset. This is the data-loss case:
        # it fails silently, with an empty string rather than a crash.
        _, out, err = build_run(tmp, "survives", SURVIVES)
        if err:
            failures.append(f"the survival program failed: {err.strip()[:120]}")
        elif "kept computed value" not in out:
            failures.append(
                f"a computed string stored in a table did not survive a reset: "
                f"got {out.strip()!r} -- the table is holding arena memory")
        else:
            print("  stored string survives a reset:  yes")

        # Twice the work must not cost more memory.
        kb1, out1, err1 = build_run(tmp, "churn_1x", CHURN % {"rounds": 20000}, True)
        kb2, out2, err2 = build_run(tmp, "churn_2x", CHURN % {"rounds": 40000}, True)

        for err in (err1, err2):
            if err:
                failures.append(f"the churn program failed: {err.strip()[:120]}")

        if not failures:
            if "rows 20" not in out1 or "rows 20" not in out2:
                failures.append(
                    f"the table did not hold 20 rows at the end: "
                    f"{out1.strip()!r} / {out2.strip()!r}")
            print(f"  400,000 insert/delete cycles:    {kb1:>6} KB peak")
            print(f"  800,000 insert/delete cycles:    {kb2:>6} KB peak")
            # Linear growth was the bug: 13.7 MB then 26.2 MB. Allow a little
            # slack for allocator differences, but not a second helping.
            if kb2 > kb1 * 1.5:
                failures.append(
                    f"twice the churn cost {kb2} KB against {kb1} KB: deleted "
                    f"rows are not being reclaimed")
            if kb1 > 8000:
                failures.append(
                    f"400,000 cycles held {kb1} KB; before reclamation this was "
                    f"13,700 KB, so this looks like the old behaviour")

    if failures:
        for f in failures:
            print(f"  {f}")
        print("=" * 64)
        print("  Rows are still leaking, or strings are being lost. FAIL")
        return 1

    print("=" * 64)
    print("  Twice the churn, the same memory, nothing lost. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
