#!/usr/bin/env python3
"""A tool that exits 0 is saying the thing worked.

A sixth pilot -- a developer told to evaluate Strata for their team -- found
three places where that was not true, and one where a tool rewrote their
source and called it a success:

  * `strata test` built only the files that HOLD verify blocks, so deleting
    or renaming the test file made a repository that does not compile report
    "0 passed, 0 failed" and exit 0. Green CI on a tree `strata build`
    refuses.
  * A project with no verify blocks at all reported the same thing and
    exited 0, so an empty run and a passing run looked identical.
  * Run outside a project, `strata test` fell back to a directory called
    `test_suite` -- this repository's own -- printed `find`'s complaint and
    exited 0. `build` and `run` have always refused there.
  * `strata repair` rewrote a developer's file in place with nothing shown
    and nothing kept. Asked to fix `cost_xat` in a table holding `cost_net`
    and `cost_vat`, it picked one, said "clean", and the program printed the
    wrong total.

Each check below is one of those.
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


def new_project(parent, name="app"):
    r = subprocess.run([STRATA, "new", name], cwd=parent,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr)[-300:]
    return os.path.join(parent, name), ""


def run(args, cwd):
    r = subprocess.run([STRATA] + args, cwd=cwd, capture_output=True,
                       text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


def main():
    with tempfile.TemporaryDirectory() as tmp:
        print("\n── strata test does not call a broken tree a pass ──────────────")

        work = os.path.join(tmp, "a")
        os.makedirs(work)
        proj, err = new_project(work)
        ok("a new project is created", proj is not None, err)
        if proj:
            rc, out = run(["test"], proj)
            ok("a healthy project with tests passes", rc == 0, out[-200:])

            os.remove(os.path.join(proj, "tests", "items_test.sta"))
            with open(os.path.join(proj, "src", "main.sta"), "a") as f:
                f.write("int broken( {\n")
            brc, bout = run(["build"], proj)
            trc, tout = run(["test"], proj)
            ok("a project that does not build fails strata build",
               brc != 0, bout[-160:])
            ok("and fails strata test too",
               trc != 0, f"exit {trc}: {tout[-200:]}")
            ok("and says that is what happened",
               "does not compile" in tout, tout[-200:])

        work = os.path.join(tmp, "b")
        os.makedirs(work)
        proj, err = new_project(work)
        ok("a second project is created", proj is not None, err)
        if proj:
            os.remove(os.path.join(proj, "tests", "items_test.sta"))
            rc, out = run(["test"], proj)
            ok("a project with no verify blocks does not pass",
               rc != 0, f"exit {rc}: {out[-200:]}")
            ok("and says nothing was tested",
               "nothing was tested" in out, out[-200:])

        empty = os.path.join(tmp, "nowhere")
        os.makedirs(empty)
        rc, out = run(["test"], empty)
        ok("strata test outside a project refuses, as build does",
           rc != 0, f"exit {rc}: {out[-200:]}")
        ok("and does not leak a shell error",
           "find:" not in out, out[-200:])

        print("\n── strata repair shows its work and keeps what it found ────────")

        work = os.path.join(tmp, "c")
        os.makedirs(work)
        proj, err = new_project(work)
        ok("a third project is created", proj is not None, err)
        if proj:
            open(os.path.join(proj, "src", "schema.sta"), "w").write(
                "database Item {\n"
                "    int   id;\n"
                "    str   name;\n"
                "    float cost_net;\n"
                "    float cost_vat;\n"
                "}\n")
            main_sta = os.path.join(proj, "src", "main.sta")
            body = open(main_sta).read()
            body = body.replace(
                'Item <- [id = 1, name = "first", price = 9.99];',
                'Item <- [id = 1, name = "first", cost_net = 2.0, '
                'cost_vat = 1.0];')
            body = body.replace("sum(all.price)", "sum(all.cost_xat)")
            open(main_sta, "w").write(body)
            before = open(main_sta).read()

            rc, out = run(["repair", "src/main.sta"], proj)
            ok("a typo between two columns is refused, not guessed at",
               rc != 0 and "decision, not a repair" in out,
               f"exit {rc}: {out[-240:]}")
            ok("and the file is exactly as it was",
               open(main_sta).read() == before)

            # One obvious candidate: it repairs, and says what it changed.
            body = before.replace("cost_xat", "cost_nett")
            open(main_sta, "w").write(body)
            rc, out = run(["repair", "src/main.sta"], proj)
            ok("a typo with one obvious candidate is repaired",
               rc == 0 and "cost_net" in open(main_sta).read(),
               f"exit {rc}: {out[-240:]}")
            ok("and the change is printed as a diff",
               "-" in out and "+" in out and "cost_nett" in out,
               out[-300:])
            kept = main_sta + ".before-repair"
            ok("and the file it found is kept beside it",
               os.path.exists(kept))
            ok("with exactly what was there before",
               os.path.exists(kept) and open(kept).read() == body)

        print("\n── a new project does not invite you to commit its output ──────")
        work = os.path.join(tmp, "d")
        os.makedirs(work)
        proj, err = new_project(work)
        ok("a fourth project is created", proj is not None, err)
        if proj:
            gi = os.path.join(proj, ".gitignore")
            ok("strata new writes a .gitignore", os.path.exists(gi))
            if os.path.exists(gi):
                text = open(gi).read()
                ok("it covers the generated C", "*.c" in text, text)
                ok("and the build directory", "build/" in text, text)

        print("\n── strata repair --help is about strata, not about Python ──────")
        rc, out = run(["repair", "--help"], tmp)
        ok("it names the command a developer typed",
           rc == 0 and "usage: strata repair" in out, out[:200])
        ok("and does not name the script behind it",
           "ai_self_repair.py" not in out, out[:200])

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  A tool can still say success when it did not. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  Exit 0 means it worked. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
