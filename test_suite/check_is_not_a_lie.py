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
    """Compiled, not linked.

    The invariant is about the C the compiler generates being valid C. A
    missing symbol at link time is a different thing and not something a type
    checker can know: `foreign` names a function in somebody else's library,
    and a module that declares what another module defines is not a program
    on its own. Compiling to an object tests the claim and nothing else.
    """
    r = subprocess.run([sys.executable, "bootstrap/stage0.py", path, "-o", out],
                       cwd=ROOT, capture_output=True, text=True)
    out_text = r.stdout + r.stderr
    if r.returncode != 0 and ("undefined reference" in out_text
                              or "ld returned" in out_text
                              or "Undefined symbols" in out_text):
        return True, out_text          # linked, not compiled: not this claim
    return r.returncode == 0, out_text


# Programs, not libraries: a module with no main() is not meant to link.
def corpus():
    """Every program in the tree, found rather than listed.

    This used to be two directories and two named files -- 27 of the 130
    `.sta` files here -- while the README said "every source in the
    repository". An audit found the gap, and a hand-maintained list is
    exactly the thing that goes stale, so the list is gone: anything with a
    `main()` is a program and gets checked.
    """
    out = []
    skip = (".git", "build", ".strata", "node_modules", ".trash")
    for dirpath, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in sorted(files):
            if not f.endswith(".sta"):
                continue
            full = os.path.join(dirpath, f)
            try:
                src = open(full, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            # A module with no entry point is not meant to link on its own.
            if re.search(r"^\s*(int|void)\s+main\s*\(", src, re.M):
                out.append(os.path.relpath(full, ROOT))
    return sorted(out)


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
        ok(f"no file passes the check and then fails to compile "
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
                # A parse error IS a Strata diagnostic, but it has to be one:
                # counting "the checker produced nothing I could read" as a
                # pass is how this test told itself what it wanted to hear.
                r = subprocess.run(
                    [sys.executable, "bootstrap/stage0.py", path],
                    cwd=ROOT, capture_output=True, text=True)
                out = r.stdout + r.stderr
                ok(label, "PARSE ERROR" in out.upper() and r.returncode != 0,
                   "no JSON and no parse error either: " + out[-200:])
                continue
            if is_clean:
                built, out = builds(path, os.path.join(tmp, "m"))
                ok(label, False,
                   "checker said clean; the build "
                   + ("also passed — the mistake was not caught at all"
                      if built else f"then failed in C: {out[-300:]}"))
            else:
                # A code, and one the taxonomy knows. "Not clean" was too weak
                # a thing to assert about an error a repair agent has to act
                # on.
                known = set(json.load(
                    open(os.path.join(ROOT, "ERROR_TAXONOMY.json")))["taxonomy"])
                unknown = [c for c in codes if c not in known]
                ok(label, bool(codes) and not unknown,
                   f"codes={codes} not in taxonomy: {unknown}")

        print("\n── and the CLI, over the whole tree ────────────────────────────")
        # Everything above drives bootstrap/stage0.py. A developer runs
        # `strata check` and `strata build`, which go through the SELF-HOSTED
        # compiler -- and the bug this test exists for was the two of them
        # disagreeing, which means checking only the oracle cannot find it.
        #
        # The first attempt at this ran the nine mutations through the CLI and
        # asserted they agreed. All nine fail `strata check`, so the build was
        # never reached and the assertion could not fail: an audit measured it
        # at 0 of 9. A test that cannot fail is worse than no test, because it
        # is counted.
        #
        # So the corpus is used instead. These are programs that are MEANT to
        # build, which is what makes the question real: if `strata check`
        # passes one and `strata build` then refuses it, the two compilers
        # disagree and a developer meets it as C.
        strata = os.path.join(ROOT, "bin", "strata")
        reached = 0
        divergent = []
        for rel in corpus():
            c = subprocess.run([strata, "check", rel], cwd=ROOT,
                               capture_output=True, text=True)
            if c.returncode != 0:
                continue
            reached += 1
            b = subprocess.run(
                [strata, "build", rel, "-o", os.path.join(tmp, "cli.bin")],
                cwd=ROOT, capture_output=True, text=True)
            out = b.stdout + b.stderr
            if b.returncode != 0 and not ("undefined reference" in out
                                          or "ld returned" in out
                                          or "Undefined symbols" in out):
                divergent.append((rel, out[-200:]))
        # The count is asserted too: if a change ever makes `strata check`
        # refuse everything, this must go red rather than quietly pass by
        # examining nothing. That is the failure it just had.
        ok(f"strata check and strata build agree ({reached} programs reached "
           f"the build)",
           reached > 20 and not divergent,
           f"reached={reached}; "
           + "; ".join(f"{r}: {o}" for r, o in divergent))

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
