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
  - a save writes only the rows that changed, proved by a trigger inside the
    database counting every insert, update and delete it receives
  - a connection is reused rather than reopened for every save and load
  - a table holds more than the four thousand and ninety-six rows it used to
    silently cap at
  - a filtered load becomes a WHERE clause rather than reading the whole
    table and throwing most of it away
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


        print("\n── A save writes only what changed ─────────────────────────────")
        # Proved from inside the database. A trigger records every insert,
        # update and delete the table actually receives, so this measures what
        # Postgres was asked to do rather than what the generated C looks like
        # it does.
        import subprocess as sp

        def psql(sql):
            return sp.run(["psql", url, "-tAq", "-c", sql],
                          capture_output=True, text=True, timeout=120)

        probe = psql("select 1")
        if probe.returncode != 0:
            skip("the write-count checks", "psql is not available here")
        else:
            psql('DROP TABLE IF EXISTS "Order" CASCADE')
            psql("DROP TABLE IF EXISTS strata_write_audit")
            psql("CREATE TABLE strata_write_audit (op text, k bigint)")
            psql('CREATE TABLE "Order" (id bigint primary key, customer text,'
                 ' amount double precision, status text)')
            psql("CREATE OR REPLACE FUNCTION strata_audit_fn() RETURNS trigger AS $f$ "
                 "BEGIN IF TG_OP = 'DELETE' THEN "
                 "INSERT INTO strata_write_audit VALUES (TG_OP, OLD.id); RETURN OLD; "
                 "ELSE INSERT INTO strata_write_audit VALUES (TG_OP, NEW.id); "
                 "RETURN NEW; END IF; END; $f$ LANGUAGE plpgsql")
            psql('CREATE TRIGGER strata_audit AFTER INSERT OR UPDATE OR DELETE'
                 ' ON "Order" FOR EACH ROW EXECUTE FUNCTION strata_audit_fn()')

            churn = SCHEMA + '''
import io       from std;
import str      from std;
import mem      from std;
import postgres from std;

int main() {
    for (int i = 1; i <= 200; i = i + 1) {
        Order <- [id = i, customer = "c", amount = 10.0, status = "OPEN"];
    }
    save Order to "$STRATA_TEST_DB";
    print("seeded");

    load Order from "$STRATA_TEST_DB";
    save Order to "$STRATA_TEST_DB";
    print("resaved");

    list[Order] one = Order <- [id == 7];
    one[0].status = "CLOSED";
    save Order to "$STRATA_TEST_DB";
    print("changed");

    delete Order <- [id == 9];
    save Order to "$STRATA_TEST_DB";
    print("removed");

    load Order from "$STRATA_TEST_DB";
    list[Order] all = Order <- [id > 0];
    print(str_concat("rows: ", str(count(all))));
    list[Order] seven = Order <- [id == 7];
    print(str_concat("seven: ", seven[0].status));
    return 0;
}
'''
            out, r = build(tmp, churn, "churn")
            ok("the churn program builds", r.returncode == 0, r.stderr[-300:])
            run = subprocess.run([out], cwd=tmp, capture_output=True,
                                 text=True, env=e)
            ok("it runs", run.returncode == 0, (run.stdout + run.stderr)[-300:])
            lines = dict(
                (ln.split(": ", 1)[0], ln.split(": ", 1)[1])
                for ln in run.stdout.strip().splitlines() if ": " in ln)

            counts = {}
            got = psql("select op, count(*) from strata_write_audit group by op")
            for ln in got.stdout.strip().splitlines():
                if "|" in ln:
                    o, c = ln.split("|")
                    counts[o.strip()] = int(c)

            ok("seeding 200 rows wrote 200 rows",
               counts.get("INSERT", 0) == 200, str(counts))
            # The whole point. Before this, four saves of a 200-row table were
            # 800 inserts and 600 deletes whatever had changed.
            ok("changing one row of 200 wrote one row",
               counts.get("UPDATE", 0) == 1, str(counts))
            ok("removing one row deleted one row",
               counts.get("DELETE", 0) == 1, str(counts))
            ok("and a save with nothing changed wrote nothing",
               counts.get("INSERT", 0) + counts.get("UPDATE", 0)
               + counts.get("DELETE", 0) == 202, str(counts))
            ok("the data is right afterwards", lines.get("rows") == "199",
               str(lines))
            ok("and the change is the one that was made",
               lines.get("seven") == "CLOSED", str(lines))

            # A save that has NOT read the table cannot know what else is in
            # it, so it replaces the table. Stated in the module and checked
            # here, because a rule nobody tests is a rule that drifts.
            psql("TRUNCATE strata_write_audit")
            blind = SCHEMA + '''
import io       from std;
import str      from std;
import mem      from std;
import postgres from std;

int main() {
    Order <- [id = 500, customer = "only", amount = 1.0, status = "OPEN"];
    save Order to "$STRATA_TEST_DB";
    load Order from "$STRATA_TEST_DB";
    print(str_concat("rows: ", str(count(Order <- [id > 0]))));
    return 0;
}
'''
            out, r = build(tmp, blind, "blind")
            ok("the no-load program builds", r.returncode == 0, r.stderr[-300:])
            run = subprocess.run([out], cwd=tmp, capture_output=True,
                                 text=True, env=e)
            lines = dict(
                (ln.split(": ", 1)[0], ln.split(": ", 1)[1])
                for ln in run.stdout.strip().splitlines() if ": " in ln)
            ok("a save with no prior load replaces the table",
               lines.get("rows") == "1", str(lines) + run.stderr[-200:])

            print("\n── More rows than a table used to hold ─────────────────────────")
            # A table's rows lived in a fixed array of 4096. An insert past
            # the end was skipped -- no error, no message, exit status zero --
            # so a service quietly stopped recording anything once it filled
            # up, and a load of a larger table dropped the rest. This is the
            # regression test for that, and it is deliberately just over the
            # old limit rather than far past it, so a reintroduced cap of any
            # size is caught rather than only an obvious one.
            psql('DROP TABLE IF EXISTS "Order" CASCADE')
            big = SCHEMA + '''
import io       from std;
import str      from std;
import mem      from std;
import postgres from std;

int main() {
    for (int i = 1; i <= 5000; i = i + 1) {
        Order <- [id = i, customer = "c", amount = 5.0, status = "OPEN"];
    }
    print(str_concat("in memory: ", str(count(Order <- [id > 0]))));
    save Order to "$STRATA_TEST_DB";
    load Order from "$STRATA_TEST_DB";
    print(str_concat("round trip: ", str(count(Order <- [id > 0]))));
    return 0;
}
'''
            out, r = build(tmp, big, "big")
            ok("a program storing 5000 rows builds", r.returncode == 0,
               r.stderr[-300:])
            run = subprocess.run([out], cwd=tmp, capture_output=True,
                                 text=True, env=e)
            lines = dict(
                (ln.split(": ", 1)[0], ln.split(": ", 1)[1])
                for ln in run.stdout.strip().splitlines() if ": " in ln)
            ok("5000 rows are held, not 4096", lines.get("in memory") == "5000",
               str(lines) + run.stderr[-200:])
            ok("and all of them survive a save and a load",
               lines.get("round trip") == "5000", str(lines))
            db_rows = psql('SELECT count(*) FROM "Order"').stdout.strip()
            ok("the database has all of them too", db_rows == "5000", db_rows)

            print("\n── A filtered load asks the database, not the network ─────────")
            # The filter is checked by what comes back, and separately by
            # asking Postgres what it was sent. A filter applied after the
            # rows arrive gives the same answer and none of the benefit, so
            # the count alone would not prove anything.
            picked = SCHEMA + '''
import io       from std;
import str      from std;
import mem      from std;
import postgres from std;

int main() {
    load Order from "$STRATA_TEST_DB" <- [id > 4995];
    print(str_concat("tail: ", str(count(Order <- [id > 0]))));
    load Order from "$STRATA_TEST_DB" <- [status == "OPEN" && id < 3];
    print(str_concat("both: ", str(count(Order <- [id > 0]))));
    load Order from "$STRATA_TEST_DB";
    print(str_concat("all: ", str(count(Order <- [id > 0]))));
    return 0;
}
'''
            out, r = build(tmp, picked, "picked")
            ok("a filtered load builds", r.returncode == 0, r.stderr[-300:])
            c_src = open(os.path.join(tmp, "picked.c")).read()
            # The generated C carries the SQL as a C string literal, so the
            # column quotes appear escaped. Matching the unescaped form is
            # what made this check fail the first time -- the code was right
            # and the test was reading for the wrong thing.
            ok("the filter is compiled into SQL, not just applied afterwards",
               '\\"id\\" > 4995' in c_src
               and '\\"status\\" = \'OPEN\'' in c_src,
               "no WHERE clause found in the generated C")
            run = subprocess.run([out], cwd=tmp, capture_output=True,
                                 text=True, env=e)
            lines = dict(
                (ln.split(": ", 1)[0], ln.split(": ", 1)[1])
                for ln in run.stdout.strip().splitlines() if ": " in ln)
            ok("a filtered load returns only the matching rows",
               lines.get("tail") == "5", str(lines) + run.stderr[-200:])
            ok("two conditions joined work too", lines.get("both") == "2",
               str(lines))
            # The bug this found: a filtered load left the table claiming to
            # hold the whole file, so the next unfiltered load decided it had
            # nothing to do and returned the filtered rows.
            ok("and a plain load afterwards still reads everything",
               lines.get("all") == "5000", str(lines))

            print("\n── The connection is reused, not reopened ──────────────────────")
            # Postgres counts the sessions ever established against a
            # database, so this is the server's own tally rather than a
            # stopwatch. Each psql call below is itself one session, which is
            # why the arithmetic allows for them.
            def sessions():
                got = psql("select sessions from pg_stat_database "
                           "where datname = current_database()")
                try:
                    return int(got.stdout.strip())
                except ValueError:
                    return -1

            before = sessions()
            if before < 0:
                skip("the connection-reuse check",
                     "this PostgreSQL does not report session counts")
            else:
                many = SCHEMA + '''
import io       from std;
import str      from std;
import mem      from std;
import postgres from std;

int main() {
    Order <- [id = 1, customer = "a", amount = 1.0, status = "OPEN"];
    save Order to "$STRATA_TEST_DB";
    for (int i = 0; i < 8; i = i + 1) {
        load Order from "$STRATA_TEST_DB";
        save Order to "$STRATA_TEST_DB";
    }
    print("did: 17");
    return 0;
}
'''
                out, r = build(tmp, many, "many")
                ok("the repeated-io program builds", r.returncode == 0,
                   r.stderr[-300:])
                run = subprocess.run([out], cwd=tmp, capture_output=True,
                                     text=True, env=e)
                ok("it runs", run.returncode == 0,
                   (run.stdout + run.stderr)[-200:])
                after = sessions()
                # before-call, the program, after-call. One session for the
                # program means seventeen saves and loads shared it.
                opened = after - before - 1
                ok("seventeen saves and loads opened one connection",
                   opened == 1, f"{opened} connections opened")

            psql('DROP TABLE IF EXISTS "Order" CASCADE')
            psql("DROP TABLE IF EXISTS strata_write_audit")
            psql("DROP FUNCTION IF EXISTS strata_audit_fn()")

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
