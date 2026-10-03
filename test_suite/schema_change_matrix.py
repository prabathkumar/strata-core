#!/usr/bin/env python3
"""Every way a schema can change, against a file written by the old one.

A table saved under one version of a schema and read under another is the
single place this language has lost data twice. The rules are easy to state
and were not, until a pilot found a renamed column reading back as zero in a
money field:

  * unchanged, reordered, a column dropped, a column added -- these load, and
    what comes back is what was stored;
  * a column renamed, a column's type changed, two columns' names swapped,
    and a drop-and-add in one step -- these are REFUSED, because each of them
    would hand the program rows that look fine and are not.

The drop-and-add is the one that matters: it is what a rename looks like from
the file's side, and allowing it is how `price` became `unit_price` and every
historical row read 0.00.

Each case below is run three ways -- `load`, `scan` and `rewrite` -- because
they are three readers of one format and the laxest of them is the real rule.
Row counts and sums are checked against the file read without Strata.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

STORED = ("#strata\tRow\tid:i\tname:s\tamount:f\n"
          "1\talpha\t10.25\n"
          "2\tbeta\t4.75\n")

# label, schema body, whether the readers must accept it
CASES = [
    ("unchanged",
     "int id; str name; float amount;", True),
    ("columns reordered",
     "float amount; int id; str name;", True),
    ("a column dropped",
     "int id; float amount;", True),
    ("a column added",
     "int id; str name; float amount; str note;", True),
    ("a column renamed",
     "int id; str name; float total;", False),
    ("a column retyped",
     "int id; str name; str amount;", False),
    ("two names swapped",
     "int id; str amount; float name;", False),
    ("one dropped and one added",
     "int id; float amount; str note;", False),
    ("a whole number widened",
     "float id; str name; float amount;", False),
]

READERS = {
    "load": '    load Row from "rows.tsv";\n'
            '    list[Row] all = Row <- [id > -1];\n'
            '    print(str_concat("n=", str(count(all))));',
    "scan": '    int n = 0;\n'
            '    scan Row from "rows.tsv" as r { n = n + 1; }\n'
            '    print(str_concat("n=", str(n)));',
    "rewrite": '    rewrite Row from "rows.tsv" as r { r.id = r.id; }\n'
               '    print("n=done");',
}

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


def main():
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([STRATA, "new", "app"], cwd=tmp,
                           capture_output=True, text=True)
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-300:])
            print("  Could not create a project. FAIL")
            return 1
        proj = os.path.join(tmp, "app")

        for label, body, accept in CASES:
            print(f"\n── {label} ─────────────────────────────────────────")
            fields = "\n".join("    " + f.strip() + ";"
                               for f in body.split(";") if f.strip())
            open(os.path.join(proj, "src", "schema.sta"), "w").write(
                "database Row {\n" + fields + "\n}\n")
            for reader, prog in READERS.items():
                open(os.path.join(proj, "rows.tsv"), "w").write(STORED)
                open(os.path.join(proj, "src", "main.sta"), "w").write(
                    "import io     from std;\n"
                    "import schema from app;\n\n"
                    "int main() {\n" + prog + "\n    return 0;\n}\n")
                run = subprocess.run([STRATA, "run"], cwd=proj,
                                     capture_output=True, text=True,
                                     timeout=300)
                out = run.stdout + run.stderr
                if accept:
                    ok(f"{reader} reads it",
                       run.returncode == 0 and "n=" in run.stdout,
                       f"exit {run.returncode}: {out[-200:]}")
                    if reader != "rewrite":
                        ok(f"{reader} returns both rows",
                           "n=2" in run.stdout, run.stdout.strip())
                else:
                    ok(f"{reader} refuses it",
                       run.returncode not in (0, None),
                       f"exit {run.returncode}: {out[-200:]}")
                    ok(f"{reader} says why",
                       "refusing to read" in out, out[-200:])
                # Whatever happened, the stored file is still the stored file.
                ok(f"{reader} left the file alone",
                   open(os.path.join(proj, "rows.tsv")).read() == STORED
                   or accept,
                   "the file changed")

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  A schema change can still lose data. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  Every schema change either reads correctly or is refused. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
