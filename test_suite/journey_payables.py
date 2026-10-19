#!/usr/bin/env python3
"""The demonstrator, end to end.

`apps/payables` is the smallest system that still touches every tier: a
supplier file coming in, stored tables, business rules, a web page, a report,
a command line and a phone screen. It exists so that one schema change can be
shown breaking all of them at once, which is the only claim this language
makes that no other language makes.

This journey is what a development manager would do if they sat down with it
for twenty minutes:

  1. Take in a supplier file -- a real one, with a byte-order mark, a comma
     inside a quoted company name, a doubled quote, a currency symbol, a
     blank cell, an impossible date and a supplier nobody has heard of. Five
     rows are good and five are not, and the five that are not come back with
     their LINE NUMBERS and a reason in words.
  2. Ask what is owed and what is late. The amounts are exact, because they
     are whole numbers of cents rather than floats.
  3. Look at the largest five, which needs ordering inside a query.
  4. Serve the web page.
  5. Draw the phone screen -- from the same table, through the same rules,
     with the schema taken as a dependency rather than copied.
  6. Mark one paid, and watch the totals move.
  7. RENAME A COLUMN. Every tier that reads it must fail to build: the
     rules, the import, the web page, the report, the command line and the
     phone. That is the step the other five exist to set up.

Nothing here is mocked. Each step runs the real binaries against real files
in a temporary copy of the tree.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


def run(args, cwd, timeout=300):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       timeout=timeout)
    return r.stdout + r.stderr, r.returncode


def main():
    print()
    print("── the demonstrator: payables, end to end ─" + "─" * 23)

    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "repo")
        os.makedirs(work)
        subprocess.run(["tar", "-cf", os.path.join(tmp, "t.tar"),
                        "--exclude=.git", "--exclude=build",
                        "--exclude=.strata", "--exclude=_to_delete", "."],
                       cwd=ROOT, check=False, timeout=300)
        subprocess.run(["tar", "-xf", os.path.join(tmp, "t.tar"), "-C", work],
                       check=False, timeout=300)
        strata = os.path.join(work, "bin", "strata")
        if not os.path.isfile(strata):
            print("  SKIP  could not export a tree to work in")
            return 0
        os.chmod(strata, 0o755)
        app = os.path.join(work, "apps", "payables")
        phone = os.path.join(work, "apps", "payables_mobile")

        # Nothing carried over from a previous run.
        for stale in ("data/bills.tsv", "data/rejected.tsv", "largest.md"):
            p = os.path.join(app, stale)
            if os.path.exists(p):
                os.remove(p)

        # ── Build ────────────────────────────────────────────────────────
        out, rc = run([strata, "deps"], phone)
        ok("the phone app's dependency resolves", rc == 0, out[-300:])

        out, rc = run([strata, "build", "src/main.sta", "-o", "build/payables"],
                      app)
        ok("the application builds", rc == 0 and
           os.path.isfile(os.path.join(app, "build", "payables")), out[-500:])

        out, rc = run([strata, "build", "src/main.sta",
                       "-o", "build/payables_mobile"], phone)
        ok("the phone app builds", rc == 0 and
           os.path.isfile(os.path.join(phone, "build", "payables_mobile")),
           out[-500:])

        exe = os.path.join(app, "build", "payables")
        phone_exe = os.path.join(phone, "build", "payables_mobile")

        # ── 1. A supplier file, as one actually arrives ──────────────────
        out, rc = run([exe, "import", "data/incoming.csv"], app)
        ok("the import runs", rc == 0, out[-400:])
        ok("it takes the five good rows and sets aside the five bad ones",
           "took 5 bill(s), set aside 5" in out, out)

        out, rc = run([exe, "show"], app)
        ok("a company name with a comma in it survived",
           "Selasih Sdn Bhd" in out, out)
        ok("a byte-order mark did not hide the first column",
           "INV-1001" in out, out)

        # Each rejection names its line and says why, in words.
        for line, why in ((5, "not an amount"),
                          (6, "not a date"),
                          (7, "due date is blank"),
                          (8, "no supplier called")):
            ok(f"line {line} was set aside, and says why",
               re.search(rf"line {line}\b.*{why}", out) is not None, out)

        # ── 2. Exact money ───────────────────────────────────────────────
        # 12500.00 + 840.50 + 97300.00 + 0.10 + 45000.00 = 155640.60, and it
        # is that to the cent however many times it is added up.
        ok("the total is exact to the cent, not a float that nearly is",
           "155640.60 owed" in out, out)
        ok("and some of it is overdue", "overdue" in out, out)

        # ── 3. Ordering ──────────────────────────────────────────────────
        ok("the oldest bill is listed first",
           out.index("INV-1001") < out.index("INV-1003"), out)

        out, rc = run([exe, "report"], app)
        ok("the report writes", rc == 0, out)
        with open(os.path.join(app, "largest.md")) as f:
            rep = f.read()
        ok("and it is the largest five, in order",
           rep.index("INV-1003") < rep.index("INV-1010") < rep.index("INV-1001"),
           rep)

        # ── 4. The web page ──────────────────────────────────────────────
        srv = subprocess.Popen([exe, "serve", "8231"], cwd=app,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
        try:
            page, health = "", ""
            for _ in range(40):
                try:
                    health = urllib.request.urlopen(
                        "http://127.0.0.1:8231/health", timeout=2).read().decode()
                    page = urllib.request.urlopen(
                        "http://127.0.0.1:8231/", timeout=4).read().decode()
                    break
                except (urllib.error.URLError, OSError):
                    time.sleep(0.25)
            ok("the service answers", '"ok":true' in health, health)
            ok("the page shows the bills", "INV-1001" in page, page[:300])
            ok("and the money on it is formatted, not raw minor units",
               "155640.60" in page and "15564060" not in page, page[:400])
            ok("and the rows it set aside are on the page too",
               "not an amount" in page, page[:400])
        finally:
            srv.terminate()
            srv.wait(timeout=30)

        # ── 5. The phone, from the same table ────────────────────────────
        out, rc = run([phone_exe], app)
        ok("the phone screen draws the same five bills",
           rc == 0 and "drew 5 bill(s)" in out, out)

        # ── 6. Marking one paid moves the totals ─────────────────────────
        out, rc = run([exe, "paid", "3"], app)
        ok("a bill can be marked paid", rc == 0, out)
        out, rc = run([exe, "show"], app)
        ok("and the total drops by exactly that bill",
           "58340.60 owed" in out, out)
        out, rc = run([phone_exe], app)
        ok("the phone sees the change, because it is the same table",
           "drew 4 bill(s)" in out, out)

        # ── 7. THE STEP THE OTHERS SET UP ────────────────────────────────
        #
        # Rename one column in one file. Every tier that reads it must stop
        # building. A system where five of six break is worse than useless,
        # because the sixth is the one that ships.
        schema = os.path.join(app, "src", "schema.sta")
        with open(schema) as f:
            src = f.read()
        ok("the schema declares the column about to be renamed",
           "int amount;" in src, "")
        with open(schema, "w") as f:
            f.write(src.replace("int amount;", "int gross;", 1))

        tiers = {
            "the rules": (app, "src/rules.sta"),
            "the import": (app, "src/importer.sta"),
            "the web page": (app, "src/views.sta"),
            "the whole application": (app, "src/main.sta"),
            "the phone screen": (phone, "src/screen.sta"),
            "the whole phone app": (phone, "src/main.sta"),
        }
        for who, (where, path) in tiers.items():
            out, rc = run([strata, "check", path], where)
            ok(f"{who} fails to build after the rename", rc != 0, out[-400:])
            ok(f"and {who} names the column that is gone",
               "amount" in out, out[-400:])

        # And the binary that was already built still runs on the old data --
        # which is the point of catching it at build time rather than at run
        # time.
        out, rc = run([exe, "show"], app)
        ok("the binary built before the rename still runs", rc == 0, out[-200:])

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  The demonstrator does not demonstrate it. FAIL")
        return 1
    print(f"  {passed}/{passed} steps of the journey passed")
    print("=" * 64)
    print("  A file came in, four tiers read it, and one rename broke all of "
          "them. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
