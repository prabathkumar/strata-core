#!/usr/bin/env python3
"""Everything round 18 found that destroys data or answers wrongly.

Round 18 was two reviews at once: one on the language, one trying to break
the seven standard-library modules written the week before. The security
review could not get past the session, CSRF, privilege or signature checks,
which is the first good news this project has had from an outsider in a
while. The language review found four things, and all four are the exact
failure the project says it has designed out.

  * `rewrite` had no lock and no stamp check -- just a bare rename -- so a
    `save` that landed while a rewrite was reading was silently thrown away
    and the saving program was told it had succeeded. `save` has had that
    guard for many rounds; the statement next to it did not.
  * two rewrites of one file shared a single hard-coded temp name, opened it
    at the same moment, wrote over each other, and one renamed the torn
    result over the table. 400,000 rows became 698,012 lines of wreckage,
    both programs exiting 0.
  * `str_replace` copied the text between matches one byte at a time, and
    the slice it used refuses to cut a UTF-8 character in half -- so every
    accented character was dropped and the error flag set once per byte.
    "Café Düsseldorf Ltd." came back "Caf Dsseldorf Limited" and went to
    disk that way.
  * `sum`, `min` and `max` over a whole-number column went through a double,
    which stops counting exactly past 2^53. `max` answered a number that was
    not in the table. The documentation tells people to keep money as whole
    minor units, and the limit it quotes is an order of magnitude past where
    a double gives up -- so the recommended way to store money was the way
    to get a wrong total.

Run: python3 test_suite/round_eighteen_stays_fixed.py
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


def build(d, name, src):
    p = os.path.join(d, name + ".sta")
    open(p, "w").write(src)
    out = os.path.join(d, name)
    r = subprocess.run([STRATA, "build", p, "-o", out], capture_output=True,
                       text=True, timeout=900)
    return (out, r) if r.returncode == 0 else (None, r)


TABLE = 'database Order { int id; str status; float amt; }\n'


def main():
    print()
    print("── round eighteen stays fixed ──" + "─" * 32)

    with tempfile.TemporaryDirectory() as d:
        data = os.path.join(d, "big.tsv")
        gen, r = build(d, "gen", "import io from std;\n" + TABLE + f'''
int main() {{
    for (int i = 1; i <= 60000; i = i + 1) {{
        Order <- [id = i, status = "OPEN", amt = 1.5];
    }}
    save Order to "{data}";
    return 0;
}}''')
        if gen is None:
            print("  FAIL  the probe does not build")
            print((r.stdout + r.stderr)[-400:])
            return 1

        rw_src = "import io from std;\n" + TABLE + f'''
int main() {{
    rewrite Order from "{data}" as r {{
        if (str_eq(r.status, "OPEN") == 1) {{ r.status = "%S%"; }}
    }}
    if (had_error() == 1) {{ print("REFUSED"); clear_error(); }}
    else {{ print("done"); }}
    return 0;
}}'''
        rw_a, _ = build(d, "rwa", rw_src.replace("%S%", "C"))
        rw_b, _ = build(d, "rwb", rw_src.replace(
            "%S%", "CANCELLED_WITH_A_VERY_LONG_STATUS_VALUE"))
        add, _ = build(d, "add", "import io from std;\n" + TABLE + f'''
int main() {{
    load Order from "{data}";
    Order <- [id = 999999, status = "IMPORTANT", amt = 9.0];
    int ok = save Order to "{data}";
    print("saved=" + str(ok));
    if (had_error() == 1) {{ print("REFUSED"); clear_error(); }}
    return 0;
}}''')

        # ── A save landing during a rewrite is not thrown away ───────────
        kept = refused = 0
        for _ in range(3):
            if os.path.exists(data):
                os.remove(data)
            subprocess.run([gen], cwd=d, capture_output=True, timeout=300)
            p = subprocess.Popen([rw_a], cwd=d, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
            time.sleep(0.2)
            a = subprocess.run([add], cwd=d, capture_output=True, text=True,
                               timeout=300)
            rout = p.communicate(timeout=300)[0]
            body = open(data).read()
            # Either the row is there, or somebody was told their write did
            # not land. What must never happen is "saved" and no row.
            if "IMPORTANT" in body:
                kept += 1
            elif "REFUSED" in (a.stdout + rout):
                refused += 1
        ok("a save during a rewrite is kept, or the loser is told",
           kept + refused == 3,
           f"{kept} kept, {refused} refused, {3 - kept - refused} silently lost")
        ok("and in practice the row survives",
           kept >= 1, f"kept in {kept} of 3 runs")

        # ── Two rewrites at once do not shred the table ──────────────────
        if os.path.exists(data):
            os.remove(data)
        subprocess.run([gen], cwd=d, capture_output=True, timeout=300)
        pa = subprocess.Popen([rw_a], cwd=d, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
        pb = subprocess.Popen([rw_b], cwd=d, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
        oa = pa.communicate(timeout=600)[0]
        ob = pb.communicate(timeout=600)[0]
        lines = [l for l in open(data).read().splitlines() if l.strip()]
        bad = [l for l in lines[1:] if len(l.split("\t")) != 3]
        statuses = {l.split("\t")[1] for l in lines[1:]}
        ok("two rewrites at once leave the table readable",
           len(bad) == 0, f"{len(bad)} malformed rows, e.g. {bad[:1]}")
        ok("and leave exactly the rows that were there",
           len(lines) == 60001, f"{len(lines)} lines, expected 60001")
        ok("and one consistent answer, not two mixed together",
           len(statuses) == 1, f"statuses present: {sorted(statuses)[:4]}")
        ok("and the one that lost is told so",
           "REFUSED" in (oa + ob), f"a:{oa.strip()} b:{ob.strip()}")

        # A rewrite on its own is untouched by any of that.
        if os.path.exists(data):
            os.remove(data)
        subprocess.run([gen], cwd=d, capture_output=True, timeout=300)
        solo = subprocess.run([rw_a], cwd=d, capture_output=True, text=True,
                              timeout=600)
        body = open(data).read()
        ok("a rewrite with nobody else about still works",
           "done" in solo.stdout and "\tC\t" in body,
           (solo.stdout + solo.stderr)[-200:])

        # ── str_replace keeps every character ────────────────────────────
        rep, _ = build(d, "rep", '''import io from std;
import str from std;
int main() {
    str o = "Caf\\u00e9 D\\u00fcsseldorf Ltd.";
    print("[" + str_replace(o, "Ltd.", "Limited") + "]");
    print("[" + str_replace("h\\u00e9llo w\\u00f6rld", "o", "0") + "]");
    print("err=" + str(had_error()));
    return 0;
}'''.replace("\\u00e9", "é").replace("\\u00fc", "ü")
      .replace("\\u00f6", "ö"))
        rr = subprocess.run([rep], cwd=d, capture_output=True, text=True,
                            timeout=300)
        out = rr.stdout
        ok("str_replace keeps the characters it did not match",
           "[Café Düsseldorf Limited]" in out, out[:300])
        ok("and replaces inside text that has them",
           "[héll0 wörld]" in out, out[:300])
        ok("and sets no error flag doing it",
           "err=0" in out, out[:300])

        # ── Whole-number aggregates stay whole ───────────────────────────
        agg, _ = build(d, "agg", '''import io from std;
database M { int cents; }
int main() {
    M <- [cents = 9007199254740993];
    M <- [cents = 9007199254740993];
    M <- [cents = 9007199254740993];
    list[M] all = M <- [cents > 0];
    print("max=" + str(max(all.cents)));
    print("min=" + str(min(all.cents)));
    print("sum=" + str(sum(all.cents)));
    print("err=" + str(had_error()));
    return 0;
}''')
        ar = subprocess.run([agg], cwd=d, capture_output=True, text=True,
                            timeout=300)
        out = ar.stdout
        ok("max answers a value that is actually in the table",
           "max=9007199254740993" in out, out[:300])
        ok("and min does too", "min=9007199254740993" in out, out[:300])
        ok("and sum is exact, not rounded through a decimal",
           "sum=27021597764222979" in out, out[:300])
        ok("and none of that sets an error flag",
           "err=0" in out, out[:300])

        over, _ = build(d, "over", '''import io from std;
database M { int cents; }
int main() {
    M <- [cents = 9223372036854775807];
    M <- [cents = 1];
    list[M] all = M <- [cents > 0];
    print("sum=" + str(sum(all.cents)));
    if (had_error() == 1) { print("REFUSED"); clear_error(); }
    return 0;
}''')
        orr = subprocess.run([over], cwd=d, capture_output=True, text=True,
                             timeout=300)
        ok("a sum past the limit refuses rather than answering the limit",
           "REFUSED" in orr.stdout and "sum=9223372036854775807" not in orr.stdout,
           orr.stdout[:300])

        # A decimal column still averages as a decimal.
        avg, _ = build(d, "avg", '''import io from std;
database F { float v; }
int main() {
    F <- [v = 1.0];
    F <- [v = 2.0];
    list[F] all = F <- [v > 0.0];
    print("avg=" + str(avg(all.v)));
    print("sum=" + str(sum(all.v)));
    return 0;
}''')
        avr = subprocess.run([avg], cwd=d, capture_output=True, text=True,
                             timeout=300)
        ok("a decimal column is still averaged and summed as a decimal",
           "avg=1.5" in avr.stdout and "sum=3" in avr.stdout,
           avr.stdout[:200])

    print()
    print("=" * 62)
    print(f"  {passed} ok, {len(failures)} failed")
    print("=" * 62)
    if failures:
        for f in failures:
            print("  - " + f[:300])
        print("  Round eighteen has come back. FAIL")
        return 1
    print("  Everything round eighteen found is still fixed. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
