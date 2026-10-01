#!/usr/bin/env python3
"""What `load` gives you is what the file holds.

A table is kept in memory and reloaded only when the file it came from has
changed. That skip asked one question -- has the FILE changed -- and so it
was wrong about every way the TABLE could change instead. An audit found
three separate silent wrong answers behind it: insert then load, the same in
a loop, and append then load, each returning rows that were not in the file
the program had just named, with exit 0 and no error.

Clearing a flag in `delete` fixed one of them. This file exists because that
was a patch and not a fix: the condition now asks whether the table still
agrees with its file, and these cases are the class rather than the three
instances somebody happened to report.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

HEAD = '''import io from std;
database T { int id; str name; }
int main() {
'''
TAIL = '''    return 0;
}
'''

# name, body, what the last `rows:` line must say
CASES = [
    ("save then load",
     '''    T <- [id = 1, name = "a"];
    T <- [id = 2, name = "b"];
    save T to "f.tsv";
    load T from "f.tsv";
''', 2),
    ("insert after save, then load",
     '''    T <- [id = 1, name = "a"];
    T <- [id = 2, name = "b"];
    save T to "f.tsv";
    T <- [id = 3, name = "c"];
    load T from "f.tsv";
''', 2),
    ("delete after save, then load",
     '''    T <- [id = 1, name = "a"];
    T <- [id = 2, name = "b"];
    save T to "f.tsv";
    delete T <- [id > 0];
    load T from "f.tsv";
''', 2),
    ("insert and load in a loop",
     '''    T <- [id = 1, name = "a"];
    save T to "f.tsv";
    int i = 0;
    while (i < 3) {
        T <- [id = 100 + i, name = "x"];
        load T from "f.tsv";
        i = i + 1;
    }
''', 1),
    ("append then load the appended file",
     '''    append T to "f.tsv" [id = 7, name = "g"];
    append T to "f.tsv" [id = 8, name = "h"];
    load T from "f.tsv";
''', 2),
    ("save, append to the same file, then load",
     '''    T <- [id = 1, name = "a"];
    save T to "f.tsv";
    append T to "f.tsv" [id = 9, name = "z"];
    load T from "f.tsv";
''', 2),
    ("a filtered load then a full one",
     '''    T <- [id = 1, name = "a"];
    T <- [id = 2, name = "b"];
    save T to "f.tsv";
    load T from "f.tsv" <- [id == 1];
    load T from "f.tsv";
''', 2),
]

passed = failed = 0


def ok(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label} — {detail}")


def main():
    print("\n── a table agrees with the file it was loaded from ──────────────")
    for label, body, expected in CASES:
        with tempfile.TemporaryDirectory(prefix="strata-agree-") as tmp:
            src = os.path.join(tmp, "p.sta")
            open(src, "w").write(
                HEAD + body
                + '    print(str_concat("rows: ", str(count(T <- [id > 0]))));\n'
                + TAIL)
            r = subprocess.run([STRATA, "run", src], cwd=tmp,
                               capture_output=True, text=True)
            out = r.stdout + r.stderr
            line = [l for l in out.splitlines() if l.startswith("rows: ")]
            if not line:
                ok(label, False, f"no answer. exit={r.returncode} {out[-200:]}")
                continue
            got = int(line[-1].split()[-1])
            # And what the file itself holds, counted without Strata.
            f = os.path.join(tmp, "f.tsv")
            on_disk = 0
            if os.path.isfile(f):
                on_disk = sum(1 for l in open(f)
                              if l.strip() and not l.startswith("#strata"))
            ok(label, got == expected == on_disk,
               f"program says {got}, file holds {on_disk}, expected {expected}")

    print("\n================================================================")
    print(f"  {passed}/{passed + failed} checks passed")
    print("================================================================")
    if failed:
        print("  A load can still answer with something the file does not "
              "hold. FAIL")
        return 1
    print("  What load gives you is what the file holds. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
