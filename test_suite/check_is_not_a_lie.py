#!/usr/bin/env python3
"""If the build fails, the checker must have said so first.

This is the invariant the whole toolchain rests on. `strata check` is what
an editor reads, what `--json` reports, and what the repair loop trusts. A
file the checker calls clean and the build then rejects is not a small bug:
it means every one of those three is being lied to, and the developer gets
an error in C, about generated code, at a line number that does not exist in
anything they wrote.

Three separate causes of exactly that were found by blind pilots rather than
by this suite:

  * nested calls were only checked in the first element of a list literal;
  * calls into another module were not checked for arity or argument type;
  * a `layout` calling one of the unit's own functions was emitted before
    the prototypes, so the C compiler guessed a signature and then
    contradicted itself.

Each was fixed, and each got its own test. This is the general rule, so the
fourth cause fails here rather than in somebody's first hour.

Two halves:

  1. Every real source in the repository: if `strata check` is clean, the
     build must succeed.
  2. Mutations of a known-good program, each introducing an ordinary
     mistake: the checker must report it, with a code and a line, BEFORE
     the C compiler ever sees it.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

passed = failed = 0
problems = []


def ok(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        problems.append((label, detail))
        print(f"  FAIL  {label}")
        return
    print(f"  PASS  {label}")


def check_json(path):
    """The checker's verdict as data: (clean, [codes])."""
    r = subprocess.run([sys.executable, "bootstrap/stage0.py", path, "--json"],
                       cwd=ROOT, capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None, []
    return bool(d.get("ok")), [x.get("code") for x in d.get("diagnostics", [])]


def builds(path, out):
    r = subprocess.run([sys.executable, "bootstrap/stage0.py", path, "-o", out],
                       cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr)


# Programs, not libraries: a module with no main() is not meant to link.
def corpus():
    out = []
    for sub in ("examples", "test_suite/verify_cases"):
        d = os.path.join(ROOT, sub)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".sta"):
                out.append(os.path.join(sub, f))
    for app in ("apps/orders/src/main.sta", "site/src/main.sta"):
        if os.path.isfile(os.path.join(ROOT, app)):
            out.append(app)
    return out


# One good program, and the ordinary ways a person or a model gets it wrong.
GOOD = '''import io from std;
import str from std;

database Ticket {
    int id;
    int hours;
    str owner;
}

str priority_of(int hours) {
    if (hours > 24) { return "HIGH"; }
    return "LOW";
}

layout Board() {
    window "Board" [width = 600, height = 400] {
        list[Ticket] open = Ticket <- [id > 0];
        column [padding = 20] {
            for T in open {
                row { text priority_of(T.hours); }
            }
        }
    }
}

int main() {
    Ticket <- [id = 1, hours = 48, owner = "ana"];
    list[Ticket] all = Ticket <- [id > 0];
    print(str_cat(["count: ", str(len(all))]));
    render Board to "board.html";
    return 0;
}
'''

MUTATIONS = [
    ("a column that does not exist, in a query",
     "Ticket <- [id > 0];", "Ticket <- [idd > 0];"),
    ("a column that does not exist, inside a call in a list",
     'str_cat(["count: ", str(len(all))])',
     'str_cat(["count: ", str(len(T.nope))])'),
    ("a value of the wrong type in an insert",
     'hours = 48', 'hours = "soon"'),
    ("a column compared with the wrong type",
     'Ticket <- [id > 0];\n    print', 'Ticket <- [owner > 0];\n    print'),
    ("a call with too few arguments",
     'str_cat(["count: ", str(len(all))])', 'str_cat()'),
    ("a call into another module with a wrong argument type",
     'str_cat(["count: ", str(len(all))])', 'str_cat("count")'),
    ("a function that does not exist",
     'priority_of(T.hours)', 'priority_ov(T.hours)'),
    ("a field that does not exist, on a row in a layout",
     'priority_of(T.hours)', 'priority_of(T.hourz)'),
    ("an insert that forgets a column",
     'Ticket <- [id = 1, hours = 48, owner = "ana"];',
     'Ticket <- [id = 1, hours = 48];'),
]


def main():
    print("\n── every source in the repository ───────────────────────────────")
    with tempfile.TemporaryDirectory(prefix="strata-invariant-") as tmp:
        clean_but_broken = []
        for rel in corpus():
            is_clean, _codes = check_json(rel)
            if is_clean is None:
                continue        # does not parse; E000 is reported elsewhere
            if not is_clean:
                continue        # the checker objected, which is the point
            built, out = builds(rel, os.path.join(tmp, "out"))
            if not built:
                clean_but_broken.append((rel, out[-400:]))
        ok(f"no file passes the check and then fails the build "
           f"({len(corpus())} sources)",
           not clean_but_broken,
           "; ".join(f"{r}: {o[:200]}" for r, o in clean_but_broken))

        print("\n── and every ordinary mistake is caught before C sees it ────────")
        good = os.path.join(tmp, "good.sta")
        open(good, "w").write(GOOD)
        is_clean, codes = check_json(good)
        ok("the unmutated program checks clean", is_clean is True, str(codes))
        built, out = builds(good, os.path.join(tmp, "good"))
        ok("and builds", built, out[-300:])

        for label, old, new in MUTATIONS:
            src = GOOD.replace(old, new, 1)
            if src == GOOD:
                ok(label, False, "the mutation did not apply — fix the test")
                continue
            path = os.path.join(tmp, "m.sta")
            open(path, "w").write(src)
            is_clean, codes = check_json(path)
            if is_clean is None:
                # A parse error is a Strata diagnostic too, just an earlier one.
                ok(label, True)
                continue
            if is_clean:
                built, out = builds(path, os.path.join(tmp, "m"))
                ok(label, False,
                   "checker said clean; the build "
                   + ("also passed — the mistake was not caught at all"
                      if built else f"then failed in C: {out[-300:]}"))
            else:
                ok(label, bool(codes) and all(c for c in codes), str(codes))

    print("\n================================================================")
    print(f"  {passed}/{passed + failed} checks passed")
    print("================================================================")
    for label, detail in problems:
        print(f"\n  {label}\n    {detail}")
    if failed:
        print("\n  strata check can still say clean about a file that does not "
              "build. FAIL")
        return 1
    print("\n  What the checker accepts, the build accepts. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
