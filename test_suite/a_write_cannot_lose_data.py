#!/usr/bin/env python3
"""What a write is not allowed to do to a file that already exists.

A tenth blind pilot was asked to try to destroy data and did, four ways. Each
one is here, because each one was reachable by following the documentation
rather than by abusing it:

  * a load that was REFUSED leaves the table empty; the tutorial then teaches
    clear_error() to carry on, and the next save wrote that empty table over
    the file -- every stored row gone, exit 0;
  * a value too long to store printed a refusal, wrote the row with that value
    empty, and still answered "saved";
  * a save opened the real file for writing, which empties it, so a crash or a
    kill halfway through left a half-written table and no way back;
  * a column the file carries and the schema no longer declares was dropped by
    the next save or rewrite, permanently and in silence.

And three ways to get a wrong answer rather than a failure: dividing by zero
killed the process with a processor trap and no message, text that is not a
number read as 0 or as its leading digits, and a stored value went into a web
page as markup.

These are guarantees, not behaviours. If one of them has to change, it is a
decision somebody makes on purpose, not something a refactor does quietly.
"""
import os
import subprocess
import sys
import tempfile

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


def run(proj, schema, main, files=None):
    open(os.path.join(proj, "src", "schema.sta"), "w").write(schema)
    open(os.path.join(proj, "src", "main.sta"), "w").write(main)
    for name, body in (files or {}).items():
        open(os.path.join(proj, name), "w").write(body)
    r = subprocess.run([STRATA, "run"], cwd=proj, capture_output=True,
                       text=True, timeout=300)
    return r, r.stdout + r.stderr


PRODUCT = ("database Product {\n    int id;\n    str name;\n"
           "    float price;\n}\n")
STORED = ("#strata\tProduct\tid:i\tname:s\tprice:f\n"
          "1\talpha\t10.25\n2\tbeta\t4.75\n")


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

        print("\n── a refused read, then a save ──────────────────────────")
        # The file says price is a whole number; the schema says it is a
        # decimal. The load is refused, the table is empty, and the program
        # does exactly what the tutorial says to do about it.
        bad = ("#strata\tProduct\tid:i\tname:s\tprice:i\n"
               "1\talpha\t10\n2\tbeta\t4\n")
        res, out = run(proj, PRODUCT,
                       'import io     from std;\n'
                       'import schema from app;\n\n'
                       'int main() {\n'
                       '    load Product from "rows.tsv";\n'
                       '    if (had_error() == 1) { clear_error(); }\n'
                       '    Product <- [id = 9, name = "new", price = 1.0];\n'
                       '    int s = save Product to "rows.tsv";\n'
                       '    print(str_concat("save=", str(s)));\n'
                       '    return 0;\n}\n',
                       {"rows.tsv": bad})
        ok("the save is refused", "save=0" in res.stdout, res.stdout.strip())
        ok("clear_error() does not unlock it",
           "last read of this table was refused" in out, out[-200:])
        ok("every stored row is still there",
           open(tsv).read() == bad, open(tsv).read())

        # The same thing, refused for a different reason. A bad VALUE in a
        # row went through its own refusal function, which was the one that
        # did not mark the table -- so this exact sequence came back in the
        # next round of testing.
        badrow = ("#strata\tProduct\tid:i\tname:s\tprice:f\n"
                  "1\talpha\t10.25\nXX\tbeta\t4.75\n")
        res, out = run(proj, PRODUCT,
                       'import io     from std;\n'
                       'import schema from app;\n\n'
                       'int main() {\n'
                       '    load Product from "rows.tsv";\n'
                       '    if (had_error() == 1) { clear_error(); }\n'
                       '    Product <- [id = 9, name = "new", price = 1.0];\n'
                       '    int s = save Product to "rows.tsv";\n'
                       '    print(str_concat("save=", str(s)));\n'
                       '    return 0;\n}\n',
                       {"rows.tsv": badrow})
        ok("a bad value in a row marks the table too",
           "save=0" in res.stdout and
           "last read of this table was refused" in out, out[-200:])
        ok("and the good rows are still there",
           open(tsv).read() == badrow, open(tsv).read())

        print("\n── a value too long to store ────────────────────────────")
        res, out = run(proj, PRODUCT,
                       'import io     from std;\n'
                       'import schema from app;\n\n'
                       'int main() {\n'
                       '    str big = "x";\n'
                       '    int i = 0;\n'
                       '    while (i < 14) { big = str_concat(big, big); '
                       'i = i + 1; }\n'
                       '    Product <- [id = 9, name = big, price = 1.0];\n'
                       '    int s = save Product to "rows.tsv";\n'
                       '    print(str_concat("save=", str(s)));\n'
                       '    clear_error();\n'
                       '    return 0;\n}\n',
                       {"rows.tsv": STORED})
        ok("the save answers that it did not save",
           "save=0" in res.stdout, res.stdout.strip())
        ok("the file is as it was", open(tsv).read() == STORED,
           open(tsv).read())
        ok("no half-written file is left behind",
           not os.path.exists(tsv + ".strata-tmp"))

        print("\n── a column the schema no longer declares ───────────────")
        extra = ("#strata\tProduct\tid:i\tname:s\tprice:f\tnote:s\n"
                 "1\talpha\t10.25\tkeep me\n")
        for verb, body in (
            ("save",
             '    load Product from "rows.tsv";\n'
             '    int s = save Product to "rows.tsv";\n'
             '    print(str_concat("rc=", str(s)));\n'),
            ("rewrite",
             '    rewrite Product from "rows.tsv" as r { r.id = r.id; }\n'
             '    print("rc=0");\n'),
        ):
            res, out = run(proj, PRODUCT,
                           'import io     from std;\n'
                           'import schema from app;\n\n'
                           'int main() {\n' + body +
                           '    clear_error();\n'
                           '    return 0;\n}\n',
                           {"rows.tsv": extra})
            ok(f"{verb} refuses to drop the column",
               "does not declare" in out, out[-200:])
            ok(f"{verb} leaves the column and its data",
               open(tsv).read() == extra, open(tsv).read())

        print("\n── arithmetic that used to kill the process ─────────────")
        res, out = run(proj, PRODUCT,
                       'import io from std;\n\n'
                       'int main() {\n'
                       '    int z = 0;\n'
                       '    print(str(1 / z));\n'
                       '    if (had_error() == 1) { print("caught"); '
                       'clear_error(); }\n'
                       '    print(str(5 % z));\n'
                       '    clear_error();\n'
                       '    return 0;\n}\n')
        ok("dividing by zero does not kill the program",
           res.returncode == 0, f"exit {res.returncode}: {out[-200:]}")
        ok("it is reported, not guessed at", "caught" in res.stdout,
           res.stdout.strip())

        print("\n── text that is not a number ────────────────────────────")
        res, out = run(proj, PRODUCT,
                       'import io from std;\n\n'
                       'int main() {\n'
                       '    int n = str_to_int("12abc");\n'
                       '    if (had_error() == 1) { print("caught"); '
                       'clear_error(); }\n'
                       '    print(str(n));\n'
                       '    return 0;\n}\n')
        ok("reading 12 out of \"12abc\" is reported",
           "caught" in res.stdout, res.stdout.strip())

        print("\n── a stored value going into a page ─────────────────────")
        res, out = run(proj, PRODUCT,
                       'import io     from std;\n'
                       'import schema from app;\n\n'
                       'layout Page() {\n'
                       '    column {\n'
                       '        list[Product] all = Product <- [id > 0];\n'
                       '        for P in all {\n'
                       '            text P.name;\n'
                       '        }\n'
                       '    }\n'
                       '}\n\n'
                       'int main() {\n'
                       '    Product <- [id = 1, '
                       'name = "<script>alert(1)</script>", price = 1.0];\n'
                       '    render Page to "page.html";\n'
                       '    return 0;\n}\n')
        page = ""
        pp = os.path.join(proj, "page.html")
        if os.path.exists(pp):
            page = open(pp).read()
        ok("the markup is escaped", "&lt;script&gt;" in page, page[-200:])
        ok("and does not reach the page as markup",
           "<script>" not in page, page[-200:])

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  A write can still lose data. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  No write destroys what it did not mean to. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
