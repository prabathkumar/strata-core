#!/usr/bin/env python3
"""A stored table that has been damaged is refused, not misread.

The compiler's error paths are hunted by malformed_input.py; this is the
runtime's, and the wrong answer is worse: a compiler that crashes wastes an
afternoon, a loader that turns a corrupted digit into a zero puts a wrong
number in a ledger and says nothing.

Every case here was run against the loader before it was written down. Three
of them used to pass silently with wrong data.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

PROGRAM = '''import io  from std;
import mem from std;

database Row { int id; str name; float amount; }

int main() {
    load Row from "rows.tsv";
    list[Row] all = Row <- [id > -999999];
    print(str(count(all)));
    for r in all { print(str_concat(str_concat(r.name, "|"), str(r.amount))); }
    return 0;
}
'''

GOOD = (b"#strata\tRow\tid:i\tname:s\tamount:f\n"
        b"1\tAlice\t10.5\n"
        b"2\tBob\t20.25\n")

# (label, bytes, expected first line of stdout, substring required in stderr)
CASES = [
    ("a good file", GOOD, "2", None),
    ("an empty file", b"", "0", None),
    ("a header and no rows", GOOD.split(b"\n")[0] + b"\n", "0", None),
    ("no schema header", b"id\tname\tamount\n1\tA\t1.0\n", "0", "no schema header"),
    ("binary junk", bytes(range(256)) * 4, "0", "no schema header"),
    ("saved from another table",
     GOOD.replace(b"\tRow\t", b"\tOther\t"), "0", "saved from 'Other'"),
    ("none of the columns match",
     b"#strata\tRow\tzzz:i\tqqq:s\twww:f\n1\tA\t1.0\n", "0",
     "none of its columns are in this table"),
    ("a column changed type",
     b"#strata\tRow\tid:s\tname:s\tamount:f\n1\tA\t1.0\n", "0", "changed type"),
    ("text where a whole number belongs",
     b"#strata\tRow\tid:i\tname:s\tamount:f\nnope\tA\t1.0\n", "0",
     "'nope' is not a number"),
    ("text where a decimal belongs",
     b"#strata\tRow\tid:i\tname:s\tamount:f\n1\tA\tnope\n", "0",
     "'nope' is not a number"),
    ("a number too big to hold",
     b"#strata\tRow\tid:i\tname:s\tamount:f\n99999999999999999999999\tA\t1.0\n",
     "0", "is not a number"),
    ("a half-written number",
     b"#strata\tRow\tid:i\tname:s\tamount:f\n12x\tA\t1.0\n", "0",
     "'12x' is not a number"),
    ("a blank line in the middle",
     GOOD.replace(b"\n2\t", b"\n\n2\t"), "0", "is not a number"),
    # Tolerated on purpose, and each for a reason.
    ("windows line endings", GOOD.replace(b"\n", b"\r\n"), "2", None),
    ("no newline at the end", GOOD.rstrip(b"\n"), "2", None),
    ("a dropped column is skipped",
     b"#strata\tRow\tid:i\tname:s\tamount:f\tlegacy:s\n1\tA\t1.0\tx\n", "1", None),
    ("a very long value", b"#strata\tRow\tid:i\tname:s\tamount:f\n1\t"
     + b"x" * 65536 + b"\t1.0\n", "1", None),
]

failures = []
passed = 0


def check(label, ok, detail=""):
    global passed
    if ok:
        passed += 1
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}")
        failures.append(f"{label}: {detail}")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "loader.sta")
        open(src, "w").write(PROGRAM)
        binary = os.path.join(tmp, "loader")
        b = subprocess.run([STRATA, "build", src, "-o", binary],
                           cwd=ROOT, capture_output=True, text=True)
        if b.returncode != 0:
            print((b.stdout + b.stderr)[-500:])
            print("  Could not build the loader. FAIL")
            return 1

        for label, data, want_first, want_err in CASES:
            open(os.path.join(tmp, "rows.tsv"), "wb").write(data)
            try:
                r = subprocess.run([binary], cwd=tmp, capture_output=True,
                                   text=True, timeout=60)
            except subprocess.TimeoutExpired:
                check(label, False, "the program did not finish")
                continue
            if r.returncode < 0 or r.returncode == 139:
                check(label, False, f"it crashed (exit {r.returncode})")
                continue
            first = (r.stdout.strip().split("\n") or [""])[0]
            if first != want_first:
                check(label, False,
                      f"loaded {first!r} rows, expected {want_first!r}")
                continue
            if want_err and want_err not in r.stderr:
                check(label, False,
                      f"said nothing about it: {r.stderr.strip()[:120]!r}")
                continue
            if not want_err and r.stderr.strip():
                check(label, False, f"complained: {r.stderr.strip()[:120]!r}")
                continue
            check(label, True)

    print("=" * 64)
    for f in failures:
        print(f"  {f}")
    print(f"  {passed}/{passed + len(failures)} cases")
    print("=" * 64)
    if failures:
        print("  Damaged data is not handled properly. FAIL")
        return 1
    print("  Damaged data is refused, and says why. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
