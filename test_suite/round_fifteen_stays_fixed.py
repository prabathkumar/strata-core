#!/usr/bin/env python3
"""Everything round 15 found, kept fixed.

Round 15's most useful finding was not a bug. It was this:

    the signature table was patched name-by-name after the last evaluation,
    which is why a third of the builtins are still open: the design is a
    deny-list of known holes, not a type system. The single thing that would
    change my answer: make an un-typed construct a hard error rather than a
    pass.

Three rounds in a row had each found a builtin with no signature, each one
was signed, and the next round found another. The repair for that is
`test_suite/every_builtin_is_signed.py`, which makes the two lists agree by
force rather than by diligence. This file holds the rest.

  * a list index past the end: a segfault from a list literal and a constant
    index, with no exotic feature in it at all
  * a tensor index past the end: a segfault for a read, a silent heap write
    for a write
  * `int(some_text)`: a pointer cast that printed a heap address, different
    every run
  * a layout property whose value is computed: silently dropped from the
    page, so the demonstrator's own red "this is late" marker never appeared
  * and the demonstrator's own six, which are in journey_payables.py because
    they are steps of its journey rather than separate cases
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


def check_src(src, d):
    p = write(d, "c.sta", src)
    r = subprocess.run([STRATA, "check", p], capture_output=True,
                       text=True, timeout=300)
    return r.stdout + r.stderr, r.returncode


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


def lines(out):
    skip = ("[Strata", "  C source:", "  Binary:")
    return [l for l in out.splitlines()
            if l.strip() and not any(l.startswith(s) for s in skip)]


def main():
    print()
    print("── round fifteen stays fixed ─" + "─" * 36)

    with tempfile.TemporaryDirectory() as d:
        # ── A list index past the end ────────────────────────────────────
        src = '''import io from std;
int main() {
    list[int] xs = [1, 2, 3];
    print(str(xs[1]));
    print(str(xs[100000000]));
    if (had_error() == 1) { print("REFUSED"); clear_error(); }
    print(str(xs[99]));
    if (had_error() == 1) { print("REFUSED"); clear_error(); }
    print(str(xs[0 - 1]));
    if (had_error() == 1) { print("REFUSED"); clear_error(); }
    return 0;
}'''
        for mode in ("run", "build"):
            out, rc = run_src(src, d, mode)
            got = lines(out)
            ok(f"reading past the end of a list refuses, not crashes ({mode})",
               rc == 0 and got.count("REFUSED") == 3 and "2" in got
               and "Segmentation" not in out, out[-400:])

        # A program that does NOT look still cannot carry on with the answer.
        quiet = '''import io from std;
int main() { list[int] xs = [1, 2, 3]; print(str(xs[50])); return 0; }'''
        out, rc = run_src(quiet, d, "build")
        ok("and a program that ignores it exits non-zero rather than 0",
           rc != 0 and "Segmentation" not in out, f"rc={rc} {out[-200:]}")

        # In-range indexing still works, including the last element.
        fine = '''import io from std;
int main() {
    list[int] xs = [10, 20, 30];
    print(str(xs[0]));
    print(str(xs[2]));
    if (had_error() == 1) { print("UNEXPECTED"); }
    return 0;
}'''
        out, rc = run_src(fine, d)
        ok("and indexing inside the list is untouched",
           lines(out) == ["10", "30"], out)

        # ── A tensor index past the end ──────────────────────────────────
        tsrc = '''import io from std;
int main() {
    tensor[float, 1, 4] t = strata_tensor(4);
    strata_tensor_set(t, 0, 3.75);
    print(str(strata_tensor_get(t, 0)));
    float v = strata_tensor_get(t, 100000000);
    if (had_error() == 1) { print("REFUSED READ"); clear_error(); }
    strata_tensor_set(t, 100000000, 1.0);
    if (had_error() == 1) { print("REFUSED WRITE"); clear_error(); }
    return 0;
}'''
        for mode in ("run", "build"):
            out, rc = run_src(tsrc, d, mode)
            got = lines(out)
            ok(f"a tensor index past the end refuses both ways ({mode})",
               "REFUSED READ" in got and "REFUSED WRITE" in got
               and "Segmentation" not in out, out[-400:])
        ok("and a tensor still holds what was put in it",
           "3.75" in "\n".join(lines(out)), out)

        # ── int(text) ────────────────────────────────────────────────────
        cast = '''import io from std;
int main() { str s = "123abc"; int x = int(s); print(str(x)); return 0; }'''
        cout, crc = check_src(cast, d)
        ok("int() of text is refused rather than casting a pointer",
           crc != 0 and "E012" in cout, cout[-300:])
        ok("and the message names the function that can say no",
           "str_to_int" in cout, cout[-300:])
        bout, brc = run_src(cast, d, "build")
        ok("and the build refuses it too", brc != 0, bout[-200:])

        # Converting between numbers is untouched.
        numbers = '''import io from std;
int main() {
    float f = 3.75;
    print(str(int(f)));
    print(str(float(3)));
    return 0;
}'''
        out, rc = run_src(numbers, d)
        ok("converting between numbers still works",
           lines(out) == ["3", "3.0"], out)

        # ── A computed layout property ───────────────────────────────────
        page = '''import io from std;
str pick(int n) { if (n > 5) { return "#ff0000"; } return "#00ff00"; }
layout P() {
    window "W" {
        text "hot" [color = pick(9)];
        text "cool" [color = pick(1)];
        text "lit" [color = "#0000ff"];
    }
}
int main() { print(render P()); return 0; }'''
        for mode in ("run", "build"):
            out, rc = run_src(page, d, mode)
            body = "\n".join(lines(out))
            ok(f"a computed colour reaches the page ({mode})",
               'style="color:#ff0000">hot' in body
               and 'style="color:#00ff00">cool' in body, body[:500])
            ok(f"and a literal one still does ({mode})",
               'style="color:#0000ff">lit' in body, body[:500])

        # A computed property beside a literal one keeps both, in order,
        # with one separator between them.
        mixed = '''import io from std;
str hue() { return "#123456"; }
layout P() { window "W" { text "x" [padding = 4, color = hue()]; } }
int main() { print(render P()); return 0; }'''
        out, rc = run_src(mixed, d)
        body = "\n".join(lines(out))
        ok("a computed property sits beside a literal one correctly",
           'style="padding:4px;color:#123456">x' in body, body[:400])

        # ── Every builtin is signed ──────────────────────────────────────
        # The structural repair has its own suite; this is the case that
        # started it.
        tensor_arity = '''import io from std;
int main() { str t = strata_tensor(2, 2); print(t); return 0; }'''
        cout, crc = check_src(tensor_arity, d)
        ok("a builtin called with the wrong number of arguments is E012",
           crc != 0 and "E012" in cout, cout[-300:])

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  Something round 15 found has come back. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  Everything round 15 found is still fixed. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
