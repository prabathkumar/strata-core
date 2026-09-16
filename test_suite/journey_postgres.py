#!/usr/bin/env python3
"""A table that lives in PostgreSQL.

Strata stored data in tab-separated files. That is honest for a small service
on one machine and is the first thing a development manager asks about, so the
answer could not stay "files". This journey checks the answer is real:

  - importing `postgres from std` is the whole switch; the path then decides
    whether a table is a file or a database
  - the same schema, queries and pages work either way
  - `$NAME` in a path is an environment variable, so a database URL and its
    password are supplied at deploy time rather than compiled into the binary
  - a customer called O'Brien is a customer, not a syntax error
  - a program that does NOT import the module gains no libpq dependency

Needs a PostgreSQL to talk to. Set STRATA_TEST_DB to a connection URL; without
it the database half is skipped rather than silently passing, because a test
that reports OK when it did nothing is worse than no test.

    STRATA_TEST_DB=postgres://postgres:pw@127.0.0.1:5432/strata_test \\
        python3 test_suite/journey_postgres.py

Usage:  python3 test_suite/journey_postgres.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE0 = os.path.join(ROOT, "bootstrap", "stage0.py")
PASS = FAIL = SKIP = 0

SCHEMA = '''
database Order {
    int   id;
    str   customer;
    float amount;
    str   status;
}
'''


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def skip(name, why):
    global SKIP
    print(f"  SKIP  {name} — {why}")
    SKIP += 1


def build(tmp, source, name):
    src = os.path.join(tmp, name + ".sta")
    out = os.path.join(tmp, name)
    open(src, "w").write(source)
    r = subprocess.run([sys.executable, STAGE0, src, "-o", out],
                       capture_output=True, text=True, cwd=tmp, timeout=600)
    return out, r


def main():
    tmp = tempfile.mkdtemp(prefix="strata-pg-")
    url = os.environ.get("STRATA_TEST_DB", "").strip()
    try:
        print("── A program that does not ask for a database ──────────────────")
        plain = SCHEMA + '''
import io  from std;
import str from std;
import mem from std;

int main() {
    Order <- [id = 1, customer = "acme", amount = 10.0, status = "OPEN"];
    save Order to "orders.tsv";
    load Order from "orders.tsv";
    print(str(count(Order <- [id > 0])));
    return 0;
}
'''
        out, r = build(tmp, plain, "plain")
        ok("it builds", r.returncode == 0, r.stderr[-300:])
        c_src = open(os.path.join(tmp, "plain.c")).read()
        ok("the Postgres code is written but not compiled in",
           "#ifdef STRATA_POSTGRES" in c_src)
        # The point of the #ifdef: no libpq, on a machine that may not have it.
        ldd = subprocess.run(["ldd", out], capture_output=True, text=True)
        ok("and the binary does not link libpq",
           "libpq" not in ldd.stdout, ldd.stdout[:200])
        run = subprocess.run([out], cwd=tmp, capture_output=True, text=True)
        ok("it still stores in a file", run.stdout.strip() == "1",
           run.stdout[:100])
        ok("which is on disk", os.path.exists(os.path.join(tmp, "orders.tsv")))

        print("\n── An unset variable is an error, not an empty path ────────────")
        env_prog = SCHEMA + '''
import io  from std;
import str from std;
import mem from std;

int main() {
    Order <- [id = 1, customer = "acme", amount = 10.0, status = "OPEN"];
    print(str(save Order to "$STRATA_NOT_SET"));
    return 0;
}
'''
        # `save` is a statement, not an expression, so the check is what the
        # program writes rather than what it returns.
        env_prog = env_prog.replace('print(str(save Order to "$STRATA_NOT_SET"));',
                                    'save Order to "$STRATA_NOT_SET";\n    print("done");')
        out, r = build(tmp, env_prog, "envprog")
        ok("it builds", r.returncode == 0, r.stderr[-300:])
        e = dict(os.environ)
        e.pop("STRATA_NOT_SET", None)
        run = subprocess.run([out], cwd=tmp, capture_output=True, text=True, env=e)
        ok("it says which variable is missing",
           "STRATA_NOT_SET" in run.stderr, run.stderr[:200])
        ok("and does not create a file called '$STRATA_NOT_SET'",
           not os.path.exists(os.path.join(tmp, "$STRATA_NOT_SET")))

        print("\n── The same program, against a real database ───────────────────")
        if not url:
            skip("everything below", "STRATA_TEST_DB is not set")
            return 0 if FAIL == 0 else 1

        pg_prog = SCHEMA + '''
import io       from std;
import str      from std;
import mem      from std;
import postgres from std;

int main() {
    print(str_concat("url: ", str(is_database_url("$STRATA_TEST_DB"))));
    Order <- [id = 1, customer = "acme",           amount = 1250.50, status = "OPEN"];
    Order <- [id = 2, customer = "O'Brien & Sons", amount =   99.99, status = "CLOSED"];
    save Order to "$STRATA_TEST_DB";

    delete Order <- [id > 0];
    print(str_concat("emptied: ", str(count(Order <- [id > 0]))));

    load Order from "$STRATA_TEST_DB";
    list[Order] all = Order <- [id > 0];
    print(str_concat("loaded: ", str(count(all))));
    print(str_concat("total: ", str(sum(all.amount))));
    list[Order] two = Order <- [id == 2];
    print(str_concat("quoted: ", two[0].customer));
    list[Order] open_ones = Order <- [status == "OPEN"];
    print(str_concat("open: ", str(count(open_ones))));
    return 0;
}
'''
        out, r = build(tmp, pg_prog, "pgprog")
        ok("a program importing postgres builds", r.returncode == 0,
           r.stderr[-400:])
        if r.returncode != 0:
            return 1
        ldd = subprocess.run(["ldd", out], capture_output=True, text=True)
        ok("and this one does link libpq", "libpq" in ldd.stdout,
           ldd.stdout[:200])

        e = dict(os.environ)
        e["STRATA_TEST_DB"] = url
        run = subprocess.run([out], cwd=tmp, capture_output=True, text=True, env=e)
        lines = dict(
            (ln.split(": ", 1)[0], ln.split(": ", 1)[1])
            for ln in run.stdout.strip().splitlines() if ": " in ln)
        ok("it runs", run.returncode == 0,
           (run.stdout + run.stderr)[-300:])
        ok("a $NAME path is recognised as a database", lines.get("url") == "1",
           str(lines))
        ok("the rows come back after being dropped from memory",
           lines.get("loaded") == "2", str(lines))
        ok("with their numbers intact", lines.get("total") == "1350.49",
           str(lines))
        ok("and a customer called O'Brien is a customer, not an injection",
           lines.get("quoted") == "O'Brien & Sons", str(lines))
        ok("queries work against database-backed rows",
           lines.get("open") == "1", str(lines))
        ok("nothing was written to the log in normal operation",
           "NOTICE" not in run.stderr, run.stderr[:200])
        ok("and no file was created", not os.path.exists(
            os.path.join(tmp, url)))

        print("\n── A save replaces the table, as it always has ─────────────────")
        # Whole-table semantics, same as the file store. Saving one row leaves
        # one row, not three.
        one = pg_prog.replace(
            '    Order <- [id = 2, customer = "O\'Brien & Sons", amount =   99.99, status = "CLOSED"];\n', "")
        out, r = build(tmp, one, "pgone")
        ok("it builds", r.returncode == 0, r.stderr[-300:])
        run = subprocess.run([out], cwd=tmp, capture_output=True, text=True, env=e)
        lines = dict(
            (ln.split(": ", 1)[0], ln.split(": ", 1)[1])
            for ln in run.stdout.strip().splitlines() if ": " in ln)
        ok("the previous contents are gone, not appended to",
           lines.get("loaded") == "1", str(lines))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"  {PASS}/{PASS + FAIL} checks passed"
          + (f", {SKIP} skipped" if SKIP else ""))
    print("=" * 64)
    if FAIL:
        print("  A table cannot be trusted to a database yet. NOT OK")
        return 1
    print("  A table can live in PostgreSQL, and the program does not change. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
