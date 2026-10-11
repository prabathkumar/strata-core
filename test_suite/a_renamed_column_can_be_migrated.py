#!/usr/bin/env python3
"""Changing a stored table, and the claim a migration makes.

Renaming a column used to be the end of the road for a table that already had
rows in it. The loader refuses a file whose header says `price` when the
schema says `cost` -- correctly, because every row would otherwise read as
empty in a money column -- and there was nothing a developer could do about
it: one program cannot declare two versions of the same table, so the only
route was editing the stored file by hand. The eleventh pilot called this the
thing that would stop their team adopting the language.

A migration is how you say "yes, I meant that" in a form the compiler can
check:

    migrate Item { rename price to cost; }

What is checked here:

  * a file still carrying the old column name loads, with its values intact;
  * saving writes the new shape, so one ordinary run migrates the file;
  * a migration naming a column that does not exist is a build error, and so
    is one naming a column that is still there -- a migration is a claim about
    stored data, and a false claim would be acted on;
  * `scan` agrees with `load`, because the laxest reader is the real rule;
  * without the migration, the same file is still refused.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

failures = []
passed = 0

STORED = ("#strata\tItem\tid:i\tname:s\tprice:f\n"
          "1\talpha\t10.25\n"
          "2\tbeta\t4.75\n")


def ok(label, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}")
        failures.append(f"{label}: {detail}")


def run(proj, schema, main, stored=STORED):
    open(os.path.join(proj, "src", "schema.sta"), "w").write(schema)
    open(os.path.join(proj, "src", "main.sta"), "w").write(main)
    open(os.path.join(proj, "rows.tsv"), "w").write(stored)
    r = subprocess.run([STRATA, "run"], cwd=proj, capture_output=True,
                       text=True, timeout=300)
    return r, r.stdout + r.stderr


SCHEMA_WITH = ("database Item {\n"
               "    int   id;\n"
               "    str   name;\n"
               "    float cost;\n"
               "}\n"
               "\n"
               "migrate Item {\n"
               "    rename price to cost;\n"
               "}\n")

SCHEMA_WITHOUT = ("database Item {\n"
                  "    int   id;\n"
                  "    str   name;\n"
                  "    float cost;\n"
                  "}\n")

HEAD = ("import io     from std;\n"
        "import schema from app;\n\n")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([STRATA, "new", "app"], cwd=tmp,
                           capture_output=True, text=True)
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-300:])
            print("  Could not create a project. FAIL")
            return 1
        proj = os.path.join(tmp, "app")
        tsv = os.path.join(proj, "rows.tsv")

        print("\n── a file still using the old name ──────────────────────")
        res, out = run(proj, SCHEMA_WITH, HEAD +
                       'int main() {\n'
                       '    load Item from "rows.tsv";\n'
                       '    list[Item] all = Item <- [id > 0];\n'
                       '    print(str_concat("n=", str(count(all))));\n'
                       '    print(str_concat("sum=", str(sum(all.cost))));\n'
                       '    return 0;\n}\n')
        ok("it loads", res.returncode == 0, out[-300:])
        ok("every row is there", "n=2" in res.stdout, res.stdout.strip())
        ok("with the values it stored", "sum=15.0" in res.stdout,
           res.stdout.strip())

        print("\n── and saving writes the new shape ──────────────────────")
        res, out = run(proj, SCHEMA_WITH, HEAD +
                       'int main() {\n'
                       '    load Item from "rows.tsv";\n'
                       '    int s = save Item to "rows.tsv";\n'
                       '    print(str_concat("save=", str(s)));\n'
                       '    return 0;\n}\n')
        after = open(tsv).read()
        ok("the save is allowed", "save=1" in res.stdout, out[-300:])
        ok("the header now says the new name", "cost:f" in after.split("\n")[0],
           after.split("\n")[0])
        ok("and the rows are unchanged",
           "10.25" in after and "4.75" in after, after)

        print("\n── scan agrees with load ────────────────────────────────")
        res, out = run(proj, SCHEMA_WITH, HEAD +
                       'int main() {\n'
                       '    int n = 0;\n'
                       '    scan Item from "rows.tsv" as r { n = n + 1; }\n'
                       '    print(str_concat("n=", str(n)));\n'
                       '    return 0;\n}\n')
        ok("a scan reads the old shape too", "n=2" in res.stdout,
           out[-300:])

        print("\n── without the migration, still refused ─────────────────")
        res, out = run(proj, SCHEMA_WITHOUT, HEAD +
                       'int main() {\n'
                       '    load Item from "rows.tsv";\n'
                       '    return 0;\n}\n')
        ok("the loader refuses it", res.returncode != 0, out[-200:])
        ok("and says why", "renamed" in out, out[-300:])
        ok("and the file is untouched", open(tsv).read() == STORED,
           open(tsv).read())

        print("\n── dropping a column, on purpose ───────────────────────")
        # Deleting a field from the schema is currently a dead end: reading
        # the file skips the column, and the next save is refused to protect
        # the data it would delete. That refusal is right by default and
        # wrong once somebody has said, in the source, that they meant it.
        with_note = ("#strata\tItem\tid:i\tname:s\tcost:f\tnote:s\n"
                     "1\talpha\t10.25\tkeep\n")
        dropped = ("database Item {\n"
                   "    int   id;\n"
                   "    str   name;\n"
                   "    float cost;\n"
                   "}\n"
                   "\n"
                   "migrate Item {\n"
                   "    drop note;\n"
                   "}\n")
        res, out = run(proj, dropped, HEAD +
                       'int main() {\n'
                       '    load Item from "rows.tsv";\n'
                       '    int s = save Item to "rows.tsv";\n'
                       '    print(str_concat("save=", str(s)));\n'
                       '    return 0;\n}\n', with_note)
        ok("the save is allowed", "save=1" in res.stdout, out[-300:])
        after = open(tsv).read()
        ok("and the column is gone from the file", "note" not in after, after)
        ok("the rows that remain are intact", "10.25" in after, after)

        print("\n── widening a whole number to a decimal ────────────────")
        # A column stored as a whole number, declared as a decimal now. The
        # loader refuses a type change, correctly, because the stored values
        # are the other type -- unless a migration says this one was widened,
        # which loses nothing.
        whole = ("#strata\tItem\tid:i\tname:s\tcost:i\n"
                 "1\talpha\t10\n2\tbeta\t5\n")
        widened = ("database Item {\n"
                   "    int   id;\n"
                   "    str   name;\n"
                   "    float cost;\n"
                   "}\n"
                   "\n"
                   "migrate Item {\n"
                   "    retype cost to float;\n"
                   "}\n")
        res, out = run(proj, widened, HEAD +
                       'int main() {\n'
                       '    load Item from "rows.tsv";\n'
                       '    list[Item] all = Item <- [id > 0];\n'
                       '    print(str_concat("sum=", str(sum(all.cost))));\n'
                       '    int s = save Item to "rows.tsv";\n'
                       '    print(str_concat("save=", str(s)));\n'
                       '    return 0;\n}\n', whole)
        ok("the stored whole numbers read as decimals",
           "sum=15.0" in res.stdout, out[-300:])
        ok("and the file is written in the new shape",
           "cost:f" in open(tsv).read().split("\n")[0],
           open(tsv).read().split("\n")[0])

        print("\n── a file that carries both names ───────────────────────")
        # The migration says price became cost, and here they are side by
        # side: either the migration is stale -- nothing tells you to remove
        # one once the files are migrated -- or this file is from somewhere
        # else. Mapping one onto the other would silently drop whichever lost.
        both = ("#strata\tItem\tid:i\tname:s\tprice:f\tcost:f\n"
                "1\talpha\t10.25\t4.75\n")
        res, out = run(proj, SCHEMA_WITH, HEAD +
                       'int main() {\n'
                       '    load Item from "rows.tsv";\n'
                       '    int s = save Item to "rows.tsv";\n'
                       '    print(str_concat("save=", str(s)));\n'
                       '    clear_error();\n'
                       '    return 0;\n}\n', both)
        ok("the read is refused", "carries both" in out, out[-300:])
        ok("the save is refused too", "save=0" in res.stdout,
           res.stdout.strip())
        ok("and neither column is lost", open(tsv).read() == both,
           open(tsv).read())

        print("\n── a migration that is not true ─────────────────────────")
        for label, body, expect in (
            ("a column that does not exist",
             "migrate Item {\n    rename price to total;\n}\n",
             "does not exist"),
            ("a column that is still there",
             "migrate Item {\n    rename cost to cost;\n}\n",
             "still a column"),
            ("a table that is not declared",
             "migrate Nothing {\n    rename a to b;\n}\n",
             "not declared"),
            ("a column dropped that is still there",
             "migrate Item {\n    drop cost;\n}\n",
             "has not been dropped"),
            ("a narrowing retype",
             "migrate Item {\n    retype id to float;\n}\n",
             "can only be widened"),
        ):
            open(os.path.join(proj, "src", "schema.sta"), "w").write(
                SCHEMA_WITHOUT + "\n" + body)
            open(os.path.join(proj, "src", "main.sta"), "w").write(
                HEAD + "int main() { return 0; }\n")
            r = subprocess.run([STRATA, "run"], cwd=proj, capture_output=True,
                               text=True, timeout=300)
            out = r.stdout + r.stderr
            ok(f"{label} is a build error",
               r.returncode != 0 and "E004" in out, out[-200:])
            ok(f"{label} says what is wrong", expect in out, out[-200:])
            # And names the file the migration is actually in. It lives in
            # schema.sta; it was being reported against main.sta, with the
            # right line and the wrong file.
            ok(f"{label} names the file it is in",
               "src/schema.sta:" in out, out[-200:])

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  A stored table still cannot be changed. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  A renamed column can be migrated, and a false claim cannot. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
