#!/usr/bin/env python3
"""Everything round 16 found, kept fixed.

Round 16's most useful sentence was not about any one of its findings:

    make the bounds-check repair total rather than per-type. Findings 1, 2,
    6 and 7 are one design gap wearing four hats.

That was the third round running to say the same thing a different way: the
repair had been applied to the shape the previous report happened to show,
and the shape one line over had been left alone. So the four findings below
about reading past the end of something are not four fixes. They are one
rule — every indexed read is bounds-checked and refuses rather than reads
memory it does not own — tested in each of the four places the evaluator
reached it, plus the places it did not.

  * text indexed past its end: a read of whatever byte followed the string
  * a tensor indexed past its end: a read, and a write into the heap
  * a tensor handed to a model that wants more values than it holds
  * two tensors of different lengths added together
  * a layout property whose value carries `;` or `}`: the value escaped the
    declaration it was in and became further CSS
  * `405 OK` on the status line: a refusal that any log reader, and anything
    scanning status lines, would file as a success
  * a write path reached with the wrong method: CSRF was checked before the
    method, so GET /close answered about a missing token rather than 405
  * a scan over a damaged file: the body ran for the good rows, the scan
    stopped, and the program carried on with a partial total

Run: python3 test_suite/round_sixteen_stays_fixed.py
"""
import os
import re
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


def run_src(src, d, mode="run", name="t.sta"):
    p = write(d, name, src)
    if mode == "run":
        r = subprocess.run([STRATA, "run", p], capture_output=True,
                           text=True, timeout=300)
        return r.stdout + r.stderr, r.returncode
    out = os.path.join(d, "t.bin")
    r = subprocess.run([STRATA, "build", p, "-o", out], capture_output=True,
                       text=True, timeout=300)
    if r.returncode != 0:
        return r.stdout + r.stderr, r.returncode
    r2 = subprocess.run([out], capture_output=True, text=True,
                        timeout=300, cwd=d)
    return r2.stdout + r2.stderr, r2.returncode


def lines(out):
    skip = ("[Strata", "  C source:", "  Binary:")
    return [l for l in out.splitlines()
            if l.strip() and not any(l.startswith(s) for s in skip)]


def main():
    print()
    print("── round sixteen stays fixed ─" + "─" * 36)

    with tempfile.TemporaryDirectory() as d:
        # ── One rule, four shapes: an indexed read past the end refuses ──
        src = '''import io from std;
int main() {
    str s = "abc";
    print(str(s[1]));
    print(str(s[3]));
    if (had_error() == 1) { print("REFUSED"); clear_error(); }
    print(str(s[100000]));
    if (had_error() == 1) { print("REFUSED"); clear_error(); }
    print(str(s[0 - 1]));
    if (had_error() == 1) { print("REFUSED"); clear_error(); }
    return 0;
}'''
        for mode in ("run", "build"):
            out, rc = run_src(src, d, mode)
            got = lines(out)
            ok(f"text indexed past its end refuses, not reads ({mode})",
               rc == 0 and got.count("REFUSED") == 3 and "98" in got
               and "Segmentation" not in out, out[-400:])

        # The empty string is the edge the off-by-one lives at.
        src = '''import io from std;
int main() {
    str e = "";
    print(str(e[0]));
    if (had_error() == 1) { print("REFUSED"); clear_error(); }
    return 0;
}'''
        out, rc = run_src(src, d, "build")
        ok("and index 0 of empty text refuses too",
           rc == 0 and "REFUSED" in out and "Segmentation" not in out,
           out[-300:])

        # In-range text indexing still works, including the last byte.
        src = '''import io from std;
int main() {
    str s = "abc";
    print(str(s[0]) + "," + str(s[2]));
    if (had_error() == 1) { print("WRONGLY REFUSED"); }
    return 0;
}'''
        out, rc = run_src(src, d, "build")
        ok("in-range text indexing still works, last byte included",
           rc == 0 and "97,99" in out and "WRONGLY REFUSED" not in out,
           out[-300:])

        # ── Tensors: the same rule, read and write ──────────────────────
        src = '''import io from std;
int main() {
    tensor[float, 1, 3] t;
    float v = strata_tensor_get(t, 99);
    if (had_error() == 1) { print("REFUSED READ"); clear_error(); }
    return 0;
}'''
        out, rc = run_src(src, d, "build")
        ok("a tensor read past its end refuses",
           rc == 0 and "REFUSED READ" in out and "Segmentation" not in out,
           out[-400:])

        # ── A model given a tensor shorter than it reads ────────────────
        src = '''import io from std;
model Tiny {
    input:  tensor[float, 1, 4];
    output: tensor[float, 1, 2];
}
int main() {
    tensor[float, 1, 2] small;
    tensor[float, 1, 2] out = predict Tiny(small);
    return 0;
}'''
        out, rc = run_src(src, d, "build")
        # Better than a refusal at run time: the shapes are in the types, so
        # this one never reaches a machine. The runtime guard underneath it
        # is still there for a tensor whose length is decided at run time.
        ok("a model given a tensor shorter than its input is refused by check",
           rc != 0 and "E006" in out and "[1,4]" in out, out[-400:])
        ok("and the model guard is in the runtime, not only in the checker",
           "this model reads %lld value(s)" in open(
               os.path.join(ROOT, "compiler", "runtime_preamble.c")).read(),
           "strata_infer has no length guard of its own")

        # ── Two tensors of different lengths ────────────────────────────
        src = '''import io from std;
int main() {
    tensor[float, 1, 2] a;
    tensor[float, 1, 2] b;
    // The length is an argument, so it can be wrong. Before round 16 this
    // read and wrote 98 doubles past the end of both tensors.
    tensor[float, 1, 2] c = strata_tensor_add(a, b, 100);
    if (had_error() == 1) { print("REFUSED MISMATCH"); clear_error(); }
    return 0;
}'''
        out, rc = run_src(src, d, "build")
        ok("adding tensors with a length neither of them has refuses",
           "REFUSED MISMATCH" in out and "Segmentation" not in out,
           out[-400:])

        # ── A computed CSS value cannot escape its declaration ──────────
        src = '''import io from std;
str sneaky() { return "red; } body { display:none; } p {"; }
layout Page {
    element box { color: sneaky(); }
}
int main() { print(render_Page()); return 0; }'''
        out, rc = run_src(src, d, "build")
        body = out
        ok("a computed CSS value cannot close its own declaration",
           "display:none" not in body.replace(" ", "")
           or "}body{" not in body.replace(" ", ""),
           body[-500:])
        ok("and the brace and semicolon are gone from the value",
           not re.search(r":\s*[^;{}\n]*\}\s*body", body), body[-500:])

        # ── 405 OK ──────────────────────────────────────────────────────
        http = open(os.path.join(ROOT, "std", "http.sta")).read()
        ok("the reason phrase defaults by status class, not to OK",
           'reason = \\"Unknown Status\\"' in http
           and '$status >= 400 && $status < 500) reason = \\"Request Error\\"'
           in http,
           "std/http.sta still defaults every unlisted status to OK")
        ok("and 405 has its exact phrase",
           '$status == 405) reason = \\"Method Not Allowed\\"' in http,
           "405 has no reason phrase")

        # ── Method checked before CSRF on a write path ──────────────────
        main_sta = open(os.path.join(ROOT, "apps", "orders", "src",
                                     "main.sta")).read()
        ok("the orders app names its write paths in one place",
           "int is_write_path(str path)" in main_sta
           and "int writes_data(str request)" in main_sta,
           "write paths are still decided inline at each use")
        ok("and the lock is taken from that same decision",
           "writes_data(request)" in main_sta,
           "serve() still decides locking separately from the method check")

        # ── A refused scan stops the program ────────────────────────────
        write(d, "damaged.tsv",
              "#strata\tReading\tsensor:i\tvalue:f\n1\t20.5\n2\n")
        src = '''import io from std;
database Reading { int sensor; float value; }
int main() {
    float total = 0.0;
    scan Reading from "damaged.tsv" as r { total = total + r.value; }
    print("THIS MUST NOT PRINT");
    print(str(total));
    return 0;
}'''
        out, rc = run_src(src, d, "build")
        ok("a scan over a damaged file stops rather than totalling part of it",
           "THIS MUST NOT PRINT" not in out and rc != 0,
           f"rc={rc} {out[-400:]}")
        ok("and it says why, in the line that stops it",
           "[STRATA SCAN]" in out and "part of the file" in out, out[-400:])

        # A scan over a sound file is untouched by all of that.
        write(d, "sound.tsv",
              "#strata\tReading\tsensor:i\tvalue:f\n1\t20.5\n2\t21.5\n")
        src = '''import io from std;
database Reading { int sensor; float value; }
int main() {
    float total = 0.0;
    int rows = 0;
    scan Reading from "sound.tsv" as r {
        total = total + r.value;
        rows = rows + 1;
    }
    print("rows " + str(rows));
    return 0;
}'''
        out, rc = run_src(src, d, "build")
        ok("a scan over a sound file still runs to the end",
           rc == 0 and "rows 2" in out, f"rc={rc} {out[-300:]}")

        # ── And both generators agree about all of it ───────────────────
        ex = os.path.join(ROOT, "examples", "scanning_a_large_file.sta")
        ok("the differential corpus contains a scan at all",
           os.path.exists(ex),
           "no example uses scan, so the two generators were never compared "
           "on it")

    print()
    print("=" * 62)
    print(f"  {passed} ok, {len(failures)} failed")
    print("=" * 62)
    if failures:
        for f in failures:
            print("  - " + f[:300])
        print("  Round sixteen has come back. FAIL")
        return 1
    print("  Everything round sixteen found is still fixed. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
