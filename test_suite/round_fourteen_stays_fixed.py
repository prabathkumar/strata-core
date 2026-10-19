#!/usr/bin/env python3
"""Everything round 14 found, kept fixed.

Round 14 ran against the tree that round 13's repairs had just landed in, and
its sharpest finding was about how those repairs were made:

    "the round-13 repair was applied to the one expression the previous
    report happened to show, and the loop over stmt.props immediately
    underneath it was left alone. Until repairs are made by asking 'what else
    reaches strata_html_escape?' rather than 'what did the report show?',
    each round will keep finding the same bug one line over."

That is the lesson this file exists to hold on to. The checks below are
grouped by the QUESTION each repair should have asked, not by the symptom
each report happened to show.

  What else reaches the page?       A label AND a property value.
  What else has no signature?       Every prelude builtin, not just one.
  What else is a truncated body?    Content-Length, not just chunked.
  What else is a line ending?       CR alone, not just CRLF and LF.

One of the findings was caused BY a round-13 repair: adding the error flag to
money_parse turned the documented ambiguity of -1 into an active false
refusal of "-0.01", an ordinary credit note. That one is first.
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


def run_src(src, d, mode="run"):
    p = write(d, "t.sta", src)
    if mode == "run":
        r = subprocess.run([STRATA, "run", p], capture_output=True,
                           text=True, timeout=300)
        return r.stdout + r.stderr, r.returncode
    out = os.path.join(d, "t.bin")
    r = subprocess.run([STRATA, "build", p, "-o", out], capture_output=True,
                       text=True, timeout=300)
    if r.returncode != 0:
        return r.stdout + r.stderr, r.returncode
    r2 = subprocess.run([out], capture_output=True, text=True, timeout=300)
    return r2.stdout + r2.stderr, r2.returncode


def check_src(src, d):
    p = write(d, "c.sta", src)
    r = subprocess.run([STRATA, "check", p], capture_output=True,
                       text=True, timeout=300)
    return r.stdout + r.stderr, r.returncode


def lines(out):
    skip = ("[Strata", "  C source:", "  Binary:")
    return [l for l in out.splitlines()
            if l.strip() and not any(l.startswith(s) for s in skip)]


def main():
    print()
    print("\u2500\u2500 round fourteen stays fixed \u2500" + "\u2500" * 35)

    with tempfile.TemporaryDirectory() as d:
        # ── Caused by a round-13 repair: minus one cent ──────────────────
        src = '''import io from std; import str from std; import money from std;
int main() {
    int a = money_parse("-0.01");
    print(str_cat(["a=", str(a), " err=", str(had_error()), " text=", money_text(a)]));
    if (had_error() == 1) { clear_error(); }
    print(str_concat("ok(-0.01)=", str(money_parse_ok("-0.01"))));
    print(str_concat("ok(rubbish)=", str(money_parse_ok("rubbish"))));
    int b = money_parse("rubbish");
    print(str_concat("rubbish err=", str(had_error())));
    clear_error();
    return 0;
}'''
        out, rc = run_src(src, d)
        got = lines(out)
        ok("minus one cent is an amount, not a failure",
           "a=-1 err=0 text=-0.01" in got, out)
        ok("and text that cannot be read still is a failure",
           "ok(-0.01)=1" in got and "ok(rubbish)=0" in got
           and "rubbish err=1" in got, out)

        # ── What else is a line ending? CR alone ─────────────────────────
        cr = os.path.join(d, "cr.tsv")
        with open(cr, "wb") as f:
            f.write(b"#strata\tP\tid:i\tname:s\r1\tone\r2\ttwo\r")
        src = f'''import io from std; import str from std;
database P {{ int id; str name; }}
int main() {{
    load P from "{cr}";
    if (had_error() == 1) {{ print("REFUSED"); clear_error(); return 0; }}
    list[P] all = P <- [id > 0 - 100];
    print(str_concat("rows ", str(count(all))));
    return 0;
}}'''
        for mode in ("run", "build"):
            out, rc = run_src(src, d, mode)
            ok(f"a CR-only file is refused, not read as empty ({mode})",
               "REFUSED" in lines(out), out)

        # A header this reader cannot make sense of is refused outright.
        for bad in (b"#strata\tP\tid:i\tname:sGARBAGE\n1\tone\n",
                    b"#strata\tP\tid:integer\tname:s\n1\tone\n",
                    b"#strata\tP\tid\tname:s\n1\tone\n"):
            p = os.path.join(d, "bad.tsv")
            with open(p, "wb") as f:
                f.write(bad)
            src = f'''import io from std; import str from std;
database P {{ int id; str name; }}
int main() {{
    load P from "{p}";
    if (had_error() == 1) {{ print("REFUSED"); clear_error(); return 0; }}
    print("ACCEPTED");
    return 0;
}}'''
            out, rc = run_src(src, d)
            ok(f"a damaged header is refused: {bad.splitlines()[0][:40]!r}",
               "REFUSED" in lines(out), out)

        # ── What else reaches the page? A property value ─────────────────
        prop = '''import io from std;
layout Page() { window "W" { int n = 7; field "id" [type = "hidden", value = n]; } }
int main() { print(render Page()); return 0; }'''
        cout, crc = check_src(prop, d)
        ok("a number in a property is refused by check, not by gcc",
           crc != 0 and "E001" in cout, cout)
        bout, brc = run_src(prop, d, "build")
        ok("and the build refuses it with the same code, not C output",
           brc != 0 and "E001" in bout and ".c:" not in bout, bout[-300:])

        # A literal still works: the generator handles it at compile time.
        lit = '''import io from std;
layout Page() { window "W" { text "a" [size = 14]; } }
int main() { print(render Page()); return 0; }'''
        cout, crc = check_src(lit, d)
        ok("a literal property is still allowed", crc == 0, cout)

        # And so does the str case the label check already covered.
        good = '''import io from std;
layout Page() { window "W" { int n = 7; text str(n) [color = "#ff0000"]; } }
int main() { print(render Page()); return 0; }'''
        cout, crc = check_src(good, d)
        ok("str(...) in a label and a literal colour both pass", crc == 0, cout)

        # ── What else has no signature? Every prelude builtin ────────────
        cases = [
            ('str s = str_len("abc"); print(s);', "a return type"),
            ('print(str_slice("abc", "x", 1));', "an argument type"),
            ('print(str_concat("a"));', "the number of arguments"),
        ]
        for body, what in cases:
            src = ('import io from std;\nimport str from std;\n'
                   'int main() { %s return 0; }\n' % body)
            cout, crc = check_src(src, d)
            bout, brc = run_src(src, d, "build")
            ok(f"a prelude builtin is checked for {what}",
               crc != 0 and brc != 0, cout[-200:] + "|" + bout[-200:])

        # The one that built clean and segfaulted.
        rep = '''import io from std;
database S { int id; float a; }
report R {
    title: "t",
    datasource: S <- [id>0],
    metrics: { str n = strata_len(rows); }
}
int main() { S <- [id=1,a=1.0]; render R to "/dev/null"; return 0; }'''
        cout, crc = check_src(rep, d)
        ok("a report metric that used to segfault is a diagnostic now",
           crc != 0 and "E001" in cout, cout)
        bout, brc = run_src(rep, d, "build")
        ok("and it never reaches a running program",
           brc != 0 and "Segmentation" not in bout, bout[-300:])

        # ── What else is a truncated body? Content-Length ────────────────
        src = '''import io from std; import str from std; import fetch from std;
int main() {
    str short_one = "HTTP/1.1 200 OK\\r\\nContent-Length: 50\\r\\n\\r\\nhello";
    print(str_concat("short=", str(str_len(fetch_body(short_one)))));
    print(str_concat("err=", str(had_error())));
    clear_error();
    str whole = "HTTP/1.1 200 OK\\r\\nContent-Length: 5\\r\\n\\r\\nhello";
    print(str_concat("whole=", fetch_body(whole)));
    str lf = "HTTP/1.1 200 OK\\nTransfer-Encoding: chunked\\n\\n5\\r\\nhello\\r\\n0\\r\\n\\r\\n";
    print(str_concat("lf=", fetch_body(lf)));
    print(str_concat("err2=", str(had_error())));
    return 0;
}'''
        out, rc = run_src(src, d)
        got = lines(out)
        ok("a body shorter than its Content-Length is refused",
           "short=0" in got and "err=1" in got, out)
        ok("a whole one is handed over, and LF-only headers keep their body",
           "whole=hello" in got and "lf=hello" in got and "err2=0" in got, out)

        # ── An escape this language does not have ────────────────────────
        esc = 'import io from std;\nint main() { str b = "C:\\path"; print(b); return 0; }\n'
        cout, crc = check_src(esc, d)
        bout, brc = run_src(esc, d, "build")
        ok("an unknown escape is refused rather than silently dropped",
           crc != 0 and brc != 0 and "not an escape" in (cout + bout),
           cout[-200:] + "|" + bout[-200:])
        okesc = ('import io from std;\n'
                 'int main() { print("a\\tb\\nc\\\\d\\"e"); return 0; }\n')
        cout, crc = check_src(okesc, d)
        ok("and the five escapes it does have still work", crc == 0, cout)

        # ── A report can be ordered ──────────────────────────────────────
        top = '''import io from std;
database Invoice { int id; str who; int amount; }
report Top {
    title: "Largest",
    datasource: Invoice <- [amount > 0] by amount desc first 2,
    metrics: { int shown = strata_len(rows); }
}
int main() {
    Invoice <- [id = 1, who = "ana", amount = 300];
    Invoice <- [id = 2, who = "bo", amount = 900];
    Invoice <- [id = 3, who = "cy", amount = 100];
    render Top to "REPORTPATH";
    print(file_read("REPORTPATH"));
    return 0;
}'''.replace("REPORTPATH", os.path.join(d, "top.md"))
        for mode in ("run", "build"):
            out, rc = run_src(top, d, mode)
            body = "\n".join(lines(out))
            ok(f"the top-N report the spec describes can be written ({mode})",
               "| 2 | bo | 900 |" in body and "| 1 | ana | 300 |" in body
               and "cy" not in body, out[-400:])

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  Something round 14 found has come back. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  Everything round 14 found is still fixed. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
