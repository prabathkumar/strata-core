#!/usr/bin/env python3
"""Everything round 17 found, kept fixed.

Round 17 was the first round where both evaluators answered the adoption
question with a straight no, and the first where both independently reached
the same diagnosis without being told the other's:

    the rules about what may be written live in the save emitter, and append
    and rewrite are separate emitters that re-implement a subset. A test per
    instance cannot keep three hand-written emitters in step.

That is the fourth round running to say a version of the same thing, so the
repairs below are rules rather than instances. A row may now only reach a
data file through one function. Every comparison operator on text goes
through one function. Every date goes through one function. The tests here
check the rule at each place it is reachable, and the structural ones check
that the single function still exists -- because a future change that
restores a second write path would pass every behavioural test in this file
on the day it was made and fail a month later.

  * `<` on text compared addresses: `[due < "2026-07-01"]` matched no row
    and `>` matched every row, exit 0, check clean -- while `by due asc`
    sorted the same column correctly, which is what made it believable
  * `append` and `rewrite` wrote a row with an over-long column BLANKED,
    valid file, later read reports nothing, stored value gone
  * two processes appending to one file corrupted it silently
  * a table of more than 64 columns saved cleanly and could never be read
  * a service never ran the unchecked-error rule at all
  * `strata test .` ran nothing and reported success
  * a `save` where the `load` was forgotten wiped the file
  * whole-number overflow wrapped silently
  * `::` from short text read memory it does not own
  * a date far from 1970 produced a corrupt string with exit 0

Run: python3 test_suite/round_seventeen_stays_fixed.py
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


def write(d, name, src):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write(src)
    return p


def run_src(src, d, mode="build", name="t.sta"):
    p = write(d, name, src)
    if mode == "run":
        r = subprocess.run([STRATA, "run", p], capture_output=True,
                           text=True, timeout=300, cwd=d)
        return r.stdout + r.stderr, r.returncode
    out = os.path.join(d, name[:-4] + ".bin")
    r = subprocess.run([STRATA, "build", p, "-o", out], capture_output=True,
                       text=True, timeout=300)
    if r.returncode != 0:
        return r.stdout + r.stderr, r.returncode
    r2 = subprocess.run([out], capture_output=True, text=True,
                        timeout=300, cwd=d)
    return r2.stdout + r2.stderr, r2.returncode


def main():
    print()
    print("── round seventeen stays fixed ─" + "─" * 34)

    with tempfile.TemporaryDirectory() as d:
        # ── Text compares as text, at every operator ────────────────────
        src = '''import io  from std;
import str from std;
database Inv { int id; str sku; str received; }
int main() {
    Inv <- [id=1, sku="AAA", received="2026-01-15"];
    Inv <- [id=2, sku="BBB", received="2026-06-30"];
    Inv <- [id=3, sku="CCC", received="2026-11-02"];
    print("lt " + str(count(Inv <- [received < "2026-07-01"])));
    print("gt " + str(count(Inv <- [received > "2026-07-01"])));
    print("le " + str(count(Inv <- [sku <= "BBB"])));
    print("ge " + str(count(Inv <- [sku >= "BBB"])));
    print("eq " + str(count(Inv <- [sku == "BBB"])));
    print("ne " + str(count(Inv <- [sku != "BBB"])));
    if ("AAA" < "CCC") { print("literal lt TRUE"); }
    return 0;
}'''
        out, rc = run_src(src, d)
        got = out
        ok("a text column filtered by < gives the right rows",
           "lt 2" in got and "gt 1" in got, got[-400:])
        ok("and <= and >= include the row that is equal",
           "le 2" in got and "ge 2" in got, got[-400:])
        ok("and == and != still work as they did",
           "eq 1" in got and "ne 2" in got, got[-400:])
        ok("and two literals compare as text, not as addresses",
           "literal lt TRUE" in got, got[-400:])

        # A value read from a file is where the address comparison showed.
        src = '''import io  from std;
import str from std;
database Inv { int id; str sku; }
int main() {
    Inv <- [id=1, sku="AAA"];
    Inv <- [id=2, sku="ZZZ"];
    save Inv to "inv.tsv";
    return 0;
}'''
        out, rc = run_src(src, d, name="w.sta")
        src = '''import io  from std;
import str from std;
database Inv { int id; str sku; }
int main() {
    load Inv from "inv.tsv";
    print("from file " + str(count(Inv <- [sku < "MMM"])));
    return 0;
}'''
        out, rc = run_src(src, d, name="r.sta")
        ok("and a value read from a file compares the same way",
           "from file 1" in out, out[-300:])

        # ── One write path: an over-long value is refused, not blanked ──
        big = '''import io from std;
import str from std;
database Note { int id; str body; }
str make(int n) { StringBuilder sb = sb_new();
    for (int i = 0; i < n; i = i + 1) { sb_append(&sb, "x"); }
    return sb_to_str(&sb); }
'''
        src = big + '''int main() {
    append Note to "ap.tsv" [id = 1, body = "short"];
    append Note to "ap.tsv" [id = 2, body = make(9000)];
    if (had_error() == 1) { clear_error(); }
    append Note to "ap.tsv" [id = 3, body = "also short"];
    if (had_error() == 1) { clear_error(); }
    print("done");
    return 0;
}'''
        out, rc = run_src(src, d, name="ap.sta")
        rows = []
        p = os.path.join(d, "ap.tsv")
        if os.path.isfile(p):
            rows = [l.rstrip("\n").split("\t")
                    for l in open(p).read().splitlines()[1:] if l.strip()]
        ok("append refuses an over-long row rather than blanking a column",
           all(len(r) == 2 and r[1] for r in rows), f"rows={rows}")
        ok("and the rows around it are written",
           len(rows) == 2 and rows[0][0] == "1" and rows[1][0] == "3",
           f"rows={rows}")

        # rewrite: the stored value survives, the file is untouched
        write(d, "rw.tsv", "#strata\tNote\tid:i\tbody:s\n1\talpha\n2\tbeta\n")
        src = big + '''int main() {
    str huge = make(9000);
    rewrite Note from "rw.tsv" as r {
        if (r.id == 1) { r.body = huge; }
    }
    return 0;
}'''
        out, rc = run_src(src, d, name="rw.sta")
        after = open(os.path.join(d, "rw.tsv")).read()
        ok("rewrite leaves the original file alone when a row is refused",
           "alpha" in after and "beta" in after, after[:200])

        # The structural half: there is ONE function that writes a row.
        pre = open(os.path.join(ROOT, "compiler",
                                "runtime_preamble.c")).read()
        ok("and only one function may put a row in a data file",
           "strata_row_commit" in pre and "strata_row_open" in pre,
           "the single write gate is gone; append and rewrite are free to "
           "re-implement the rules again")
        for gen, name in ((os.path.join(ROOT, "bootstrap", "stage0.py"),
                           "stage0.py"),
                          (os.path.join(ROOT, "compiler", "codegen.sta"),
                           "codegen.sta")):
            text = open(gen).read()
            ok(f"{name} routes its row writers through it",
               text.count("strata_row_commit") >= 2,
               f"{name} has a write path that does not go through the gate")

        # ── Concurrent append ───────────────────────────────────────────
        src = '''import io from std;
import str from std;
import cli from std;
database Ev { int worker; str payload; }
int main() {
    int w = str_to_int(arg(1));
    for (int i = 0; i < 1500; i = i + 1) {
        append Ev to "conc.tsv" [worker = w, payload = "a-normal-short-value"];
    }
    return 0;
}'''
        p = write(d, "conc.sta", src)
        binp = os.path.join(d, "conc.bin")
        b = subprocess.run([STRATA, "build", p, "-o", binp],
                           capture_output=True, text=True, timeout=300)
        tsv = os.path.join(d, "conc.tsv")
        if os.path.exists(tsv):
            os.remove(tsv)
        procs = [subprocess.Popen([binp, str(w)], cwd=d,
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
                 for w in (1, 2, 3)]
        for pr in procs:
            pr.wait(timeout=300)
        bad = total = 0
        for line in open(tsv).read().splitlines()[1:]:
            if not line.strip():
                continue
            total += 1
            parts = line.split("\t")
            if len(parts) != 2 or parts[1] != "a-normal-short-value":
                bad += 1
        ok("three processes appending to one file corrupt nothing",
           bad == 0 and total == 4500, f"{bad} bad of {total}")

        # ── A table too wide to read back is refused at check time ──────
        cols = "\n".join(f"    int c{i};" for i in range(70))
        src = f"import io from std;\ndatabase W {{\n{cols}\n}}\nint main() {{ return 0; }}"
        p = write(d, "wide.sta", src)
        r = subprocess.run([STRATA, "check", p], capture_output=True,
                           text=True, timeout=300)
        text = r.stdout + r.stderr
        ok("a table of more than 64 columns is refused by strata check",
           r.returncode != 0 and "E013" in text and "64" in text,
           text[-300:])

        # 64 is still fine: the limit is the reader's, not an invented one.
        cols = "\n".join(f"    int c{i};" for i in range(64))
        src = f"import io from std;\ndatabase N {{\n{cols}\n}}\nint main() {{ return 0; }}"
        p = write(d, "narrow.sta", src)
        r = subprocess.run([STRATA, "check", p], capture_output=True,
                           text=True, timeout=300)
        ok("and exactly 64 columns is accepted", r.returncode == 0,
           (r.stdout + r.stderr)[-200:])

        # ── A save whose load was forgotten ─────────────────────────────
        write(d, "ord.tsv", "#strata\tOrd\tid:i\tcust:s\n1\ta\n2\tb\n3\tc\n")
        src = '''import io from std;
database Ord { int id; str cust; }
int main() {
    Ord <- [id = 9, cust = "new"];
    save Ord to "ord.tsv";
    print("errflag=" + str(had_error()));
    return 0;
}'''
        out, rc = run_src(src, d, name="ord.sta")
        after = open(os.path.join(d, "ord.tsv")).read()
        ok("a save over a file this program never read is refused",
           "1\ta" in after and "3\tc" in after, after[:200])
        ok("and it says so rather than exiting 0",
           "errflag=1" in out or rc != 0, f"rc={rc} {out[-300:]}")

        # A first save to a path that does not exist is untouched by that.
        src = '''import io from std;
database Ord { int id; str cust; }
int main() {
    Ord <- [id = 1, cust = "first"];
    save Ord to "fresh.tsv";
    print("errflag=" + str(had_error()));
    return 0;
}'''
        out, rc = run_src(src, d, name="fresh.sta")
        ok("but a first save to a new path still works",
           "errflag=0" in out and os.path.isfile(os.path.join(d, "fresh.tsv")),
           out[-300:])

        # ── Whole-number overflow ───────────────────────────────────────
        src = '''import io from std;
int main() {
    int a = 4000000000;
    int b = 4000000000;
    int c = a * b;
    if (had_error() == 1) { print("MUL FLAGGED"); clear_error(); }
    int big = 9223372036854775807;
    int d = big + 1;
    if (had_error() == 1) { print("ADD FLAGGED"); clear_error(); }
    int e = 0 - big - 2;
    if (had_error() == 1) { print("SUB FLAGGED"); clear_error(); }
    print("normal " + str(2 + 3) + " " + str(7 * 6) + " " + str(10 - 4));
    if (had_error() == 1) { print("WRONGLY FLAGGED"); }
    return 0;
}'''
        out, rc = run_src(src, d, name="ov.sta")
        ok("multiplying past the limit is flagged, not wrapped",
           "MUL FLAGGED" in out, out[-300:])
        ok("and so is adding past it, and subtracting past it",
           "ADD FLAGGED" in out and "SUB FLAGGED" in out, out[-300:])
        ok("and ordinary arithmetic is untouched",
           "normal 5 42 6" in out and "WRONGLY FLAGGED" not in out,
           out[-300:])

        # ── A cast from text shorter than the record ────────────────────
        src = '''import io from std;
protocol Hdr { int a; str b; int c; }
int main() {
    str small = "x";
    Hdr h = small :: Hdr;
    print("a=" + str(h.a));
    if (had_error() == 1) { print("REFUSED"); clear_error(); }
    return 0;
}'''
        out, rc = run_src(src, d, name="cast.sta")
        ok("a :: cast from text too short to hold the record refuses",
           "REFUSED" in out and "Segmentation" not in out, out[-300:])

        # ── A date too far from 1970 ────────────────────────────────────
        src = '''import io from std;
import time from std;
int main() {
    int d = date_of(2026, 1, 1);
    print("normal " + date_text(d));
    if (had_error() == 1) { print("WRONGLY FLAGGED"); }
    int far = add_days(d, 400000000000);
    str t = date_text(far);
    if (had_error() == 1) { print("REFUSED"); clear_error(); }
    return 0;
}'''
        out, rc = run_src(src, d, name="tm.sta")
        ok("a date too far from 1970 is refused, not written out corrupt",
           "REFUSED" in out, out[-300:])
        ok("and an ordinary date is unaffected",
           "normal 2026-01-01" in out and "WRONGLY FLAGGED" not in out,
           out[-300:])

    # ── strata test . runs the tests ────────────────────────────────────
    orders = os.path.join(ROOT, "apps", "orders")
    if os.path.isdir(orders):
        r = subprocess.run([STRATA, "test", "."], cwd=orders,
                           capture_output=True, text=True, timeout=600)
        text = r.stdout + r.stderr
        ok("strata test . runs the blocks rather than finding nothing",
           r.returncode == 0 and "0 passed, 0 failed" not in text,
           text[-400:])

    mobile = os.path.join(ROOT, "apps", "orders_mobile")
    if os.path.isdir(mobile):
        r = subprocess.run([STRATA, "test", "."], cwd=mobile,
                           capture_output=True, text=True, timeout=600)
        ok("and a run that finds no blocks exits non-zero",
           r.returncode != 0, (r.stdout + r.stderr)[-300:])

    # ── A service runs the unchecked-error rule ─────────────────────────
    http = open(os.path.join(ROOT, "std", "http.sta")).read()
    ok("a success is refused while an unchecked error is outstanding",
       "strata_err_pending" in http and "$status = 500" in http,
       "std/http.sta can still answer 200 after a refused load")
    ok("and a request that leaves by _exit checks before it goes",
       "strata_error_exit_code" in http,
       "http_exit still skips the unchecked-error rule entirely")

    print()
    print("=" * 62)
    print(f"  {passed} ok, {len(failures)} failed")
    print("=" * 62)
    if failures:
        for f in failures:
            print("  - " + f[:300])
        print("  Round seventeen has come back. FAIL")
        return 1
    print("  Everything round seventeen found is still fixed. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
