#!/usr/bin/env python3
"""Everything round 13 found, kept fixed.

Two blind evaluators were given a clean checkout and one question: could a
development team adopt this? Between them they found nine things. The three
that mattered are the first three here, and all of them have the same shape:
**the program exits 0 and is wrong**, which is the failure this language
exists to prevent.

  1. A .tsv with Windows line endings loaded silently and left an invisible
     carriage return on the end of every text value. `name == "two"` matched
     nothing. Then `save` wrote the carriage return back into the canonical
     file, so the damage outlived the machine that caused it.

  2. One stray quote in a CSV deleted every row after it. No error. That is
     the exact opposite of std/csv.sta's one promise -- one bad row is not a
     bad file -- and the input is a company name typed with an unbalanced ".

  3. `strata check` said "No errors. OK" on programs neither compiler could
     build. The real failure arrived as raw C compiler output about a file
     the developer never wrote. A clean check is load-bearing: the tutorial,
     CI and the repair loop all rely on it.

And the quieter ones:

  4. fetch handed back HTTP chunk framing as part of the body, so a
     hexadecimal length marker landed in the middle of a supplier's name.
  5. fetch returned C's NULL for an over-cap response, and the documented
     `str_len(answer)` on it segfaulted -- a promised refusal delivered as a
     crash.
  6. fetch had no timeout, so a peer that accepted and never answered held
     the program forever with nothing logged.
  7. llm's plain-HTTP guard was a prefix match, so `http://localhost.somebody
     -elses-domain.example` passed it and the key went out in the clear.
  8. money_parse accepted numbers too large to hold and returned a plausible
     wrong amount; money_times and money_rate wrapped.
  9. moment_of refused every date before 1970, because it read a negative
     moment as the "impossible date" sentinel.
 10. date_parse and money_parse both answered -1 for text they could not
     read, and -1 is a legal input to everything downstream -- so a blank
     cell became an invoice 56 years overdue for minus one cent.
 11. A UTF-8 byte-order mark -- every CSV Excel exports -- made the first
     column unfindable by name, silently.
 12. Reading a CSV row by row was super-quadratic: 4,000 rows took 6.7
     seconds and 20,000 never finished.

The CRLF case is checked end to end against a real file. The rest are
checked by running the standard library's own `verify` blocks, which now
carry an assertion for each, plus the cases below that need a program.
"""
import os
import subprocess
import sys
import tempfile
import time

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


def run_src(src, mode="run", tmp=None, timeout=300):
    own = tmp is None
    d = tempfile.mkdtemp() if own else tmp
    p = os.path.join(d, "t.sta")
    with open(p, "w") as f:
        f.write(src)
    if mode == "run":
        r = subprocess.run([STRATA, "run", p], capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout + r.stderr, r.returncode
    out = os.path.join(d, "t.bin")
    r = subprocess.run([STRATA, "build", p, "-o", out], capture_output=True,
                       text=True, timeout=timeout)
    if r.returncode != 0:
        return r.stdout + r.stderr, r.returncode
    r2 = subprocess.run([out], capture_output=True, text=True, timeout=timeout)
    return r2.stdout + r2.stderr, r2.returncode


def lines(out):
    skip = ("[Strata", "  C source:", "  Binary:")
    return [l for l in out.splitlines()
            if l.strip() and not any(l.startswith(s) for s in skip)]


def main():
    print()
    print("── round thirteen stays fixed ─" + "─" * 36)

    with tempfile.TemporaryDirectory() as d:
        # ── 1. Windows line endings ──────────────────────────────────────
        crlf = os.path.join(d, "crlf.tsv")
        with open(crlf, "wb") as f:
            f.write(b"#strata\tP\tid:i\tname:s\r\n1\tone\r\n2\ttwo\r\n")
        src = f'''import io from std;
import str from std;
database P {{ int id; str name; }}
int main() {{
    load P from "{crlf}";
    if (had_error() == 1) {{ print(str_concat("REFUSED ", last_error())); clear_error(); return 1; }}
    list[P] all = P <- [id > 0];
    print(str_concat("rows ", str(count(all))));
    for R in all {{ print(str_cat([R.name, " len=", str(str_len(R.name))])); }}
    list[P] m = P <- [name == "two"];
    print(str_concat("match ", str(count(m))));
    return 0;
}}'''
        for mode in ("run", "build"):
            out, rc = run_src(src, mode, d)
            got = lines(out)
            ok(f"a CRLF file loads with its text intact ({mode})",
               "rows 2" in got and "one len=3" in got and "match 1" in got, out)

        # A carriage return that really is IN a value still survives, which is
        # what makes stripping the line-ending one unambiguous rather than a
        # guess.
        rt = os.path.join(d, "rt.tsv")
        src2 = f'''import io from std;
import str from std;
database P {{ int id; str name; }}
int main() {{
    P <- [id = 1, name = str_cat(["a", char_from_code(13), "b"])];
    save P to "{rt}";
    return 0;
}}'''
        run_src(src2, "run", d)
        src3 = f'''import io from std;
import str from std;
database P {{ int id; str name; }}
int main() {{
    load P from "{rt}";
    list[P] all = P <- [id > 0];
    for R in all {{ print(str(str_len(R.name))); }}
    return 0;
}}'''
        out, rc = run_src(src3, "run", d)
        ok("a carriage return inside a value still round-trips",
           lines(out) == ["3"], out)
        with open(rt, "rb") as f:
            raw = f.read()
        ok("and it is written escaped, not raw",
           b"a\\rb" in raw and b"a\rb" not in raw, repr(raw))

        # ── 2. One stray quote ───────────────────────────────────────────
        src4 = '''import io from std; import str from std; import csv from std;
int main() {
    str t = "sku,name,qty\\nA1,bolt,10\\nA2,\\"nut,4\\nA3,washer,7\\nA4,screw,9\\n";
    print(str_concat("rows=", str(csv_rows(t))));
    for (int r = 0; r < csv_rows(t); r = r + 1) {
        print(str_cat(["r", str(r), " ok=", str(csv_row_ok(t, r)), " c0=", csv_cell(t, r, 0)]));
    }
    return 0;
}'''
        for mode in ("run", "build"):
            out, rc = run_src(src4, mode, d)
            got = lines(out)
            ok(f"one stray quote costs one row, not the file ({mode})",
               "rows=5" in got
               and any(l.startswith("r2 ok=0") for l in got)
               and any(l.startswith("r3 ok=1") for l in got)
               and any(l.startswith("r4 ok=1") for l in got), out)
        ok("and the header row is not reported as damaged",
           any(l.startswith("r0 ok=1") for l in lines(out)), out)

        # ── 11. A byte-order mark ────────────────────────────────────────
        bom = os.path.join(d, "bom.csv")
        with open(bom, "wb") as f:
            f.write(b"\xef\xbb\xbfsku,name,qty\nA1,bolt,10\n")
        src5 = f'''import io from std; import str from std; import csv from std;
int main() {{
    str t = file_read("{bom}");
    print(str_concat("col=", str(csv_column_of(t, "sku"))));
    print(str_concat("val=", csv_value(t, 1, "sku")));
    return 0;
}}'''
        out, rc = run_src(src5, "run", d)
        ok("a file from Excel can still be read by column name",
           lines(out) == ["col=0", "val=A1"], out)

        # ── 12. Reading row by row is linear ─────────────────────────────
        big = os.path.join(d, "big.csv")
        with open(big, "w") as f:
            f.write("sku,name,qty\n")
            for i in range(20000):
                f.write(f"S{i},item {i},{i % 97}\n")
        src6 = f'''import io from std; import str from std; import csv from std;
int main() {{
    str t = file_read("{big}");
    int want = csv_columns(t, 0);
    int at = csv_first_row(t);
    at = csv_next_row(t, at);
    int total = 0; int taken = 0;
    while (at >= 0) {{
        if (csv_row_ok_at(t, at, want) == 1) {{
            total = total + str_to_int(csv_cell_at(t, at, 2));
            taken = taken + 1;
        }}
        at = csv_next_row(t, at);
    }}
    print(str_cat(["taken=", str(taken), " total=", str(total)]));
    return 0;
}}'''
        began = time.time()
        out, rc = run_src(src6, "build", d)
        took = time.time() - began
        ok("20,000 rows can be read one by one",
           "taken=20000" in out, out[-300:])
        # Generous: it was over 150 seconds and unfinished, and is now well
        # under one. Thirty seconds includes compiling the program.
        ok(f"and it finishes quickly rather than never ({took:.1f}s incl. build)",
           took < 30, f"{took:.1f}s")

        # ── 3. check is sound for a layout ───────────────────────────────
        src7 = '''import io from std;
import ui from std;
database M { int id; int label; }
layout Page() {
    list[M] rows = M <- [id > 0];
    for R in rows { text R.label; }
}
int main() {
    M <- [id = 1, label = 42];
    render Page to "/dev/null";
    return 0;
}'''
        p7 = os.path.join(d, "layout.sta")
        with open(p7, "w") as f:
            f.write(src7)
        r = subprocess.run([STRATA, "check", p7], capture_output=True,
                           text=True, timeout=300)
        ok("a page drawing a number is refused by check, not by gcc",
           r.returncode != 0 and "E001" in (r.stdout + r.stderr), r.stdout + r.stderr)
        ok("and the message says what to do about it",
           "str(" in (r.stdout + r.stderr), r.stdout + r.stderr)
        out, rc = run_src(src7, "build", d)
        ok("and the build refuses it with the same code, not C compiler output",
           rc != 0 and "E001" in out and ".c:" not in out, out[-400:])

        # ── 10. Two sentinels composing into a wrong invoice ─────────────
        src8 = '''import io from std; import str from std; import csv from std;
import time from std; import money from std;
int main() {
    str t = "ref,due,amount\\nINV1,2025-03-01,10.50\\nINV2,,\\n";
    int today = date_of(2025, 10, 19);
    for (int r = 1; r < csv_rows(t); r = r + 1) {
        int due = date_parse(csv_value(t, r, "due"));
        int amt = money_parse(csv_value(t, r, "amount"));
        if (had_error() == 1) {
            print(str_cat([csv_value(t,r,"ref"), ": SET ASIDE"]));
            clear_error();
            continue;
        }
        print(str_cat([csv_value(t,r,"ref"), ": ", str(days_between(due, today)), " days ", money_text(amt)]));
    }
    return 0;
}'''
        out, rc = run_src(src8, "run", d)
        got = lines(out)
        ok("a blank cell is set aside, not turned into a 56-year-old invoice",
           any(l.startswith("INV2: SET ASIDE") for l in got)
           and any("INV1: 232 days 10.50" in l for l in got), out)

        # ── 9. A date before 1970 ────────────────────────────────────────
        src9 = '''import io from std; import str from std; import time from std;
int main() {
    print(moment_text(moment_of(1965, 3, 2, 9, 0, 0)));
    print(date_text(date_parse("1965-03-02")));
    print(str(date_parse_ok("1965-03-02")));
    print(str(moment_of(2025, 2, 30, 9, 0, 0)));
    if (had_error() == 1) { clear_error(); }
    return 0;
}'''
        out, rc = run_src(src9, "run", d)
        ok("a date of birth before 1970 is a real date",
           lines(out) == ["1965-03-02 09:00:00", "1965-03-02", "1", "-1"], out)

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  Something round 13 found has come back. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  Everything round 13 found is still fixed. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
