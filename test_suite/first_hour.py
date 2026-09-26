#!/usr/bin/env python3
"""The first hour: what a developer runs before they decide to keep going.

Every command the generated README offers is run against a project generated
by `strata new`, and `strata check` is run over the repository's own sources.

What it found on the way in:

  - **`strata check` did not resolve imports.** `strata build` compiled
    `apps/orders/src/rules.sta` without complaint while `strata check`
    reported sixteen errors for it, because it checked the file with no idea
    what a `database Order` was. A checker that disagrees with the compiler is
    worse than no checker: the first thing a newcomer runs told them their
    code was broken when it was not.
  - **It treated E007 as fatal**, though the taxonomy says advisory.
  - **`strata new` produced a project whose tests said "0 passed"** — it
    generated no tests at all.
  - Four examples imported modules `from hub`, a registry that has never
    existed. An unresolvable import disarms the undefined-call rule, so the
    fake import was also hiding a call to `extract_json_int`, which nothing
    defined.

Usage:  python3 test_suite/first_hour.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def run(args, cwd, timeout=600):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


def main():
    print("\n── strata check agrees with strata build ────────────────────────")
    # Every source the compiler builds, the checker must accept. These are
    # files that import their own schema, which is what used to break it.
    for rel in ("apps/orders/src/rules.sta", "apps/orders/src/main.sta",
                "apps/ledger/src/main.sta", "std/http.sta",
                "compiler/typechecker.sta"):
        r = run([STRATA, "check", rel], ROOT)
        ok(f"check accepts {rel}", r.returncode == 0,
           (r.stdout + r.stderr).strip()[-200:])

    print("\n── and it is honest about what it could not resolve ─────────────")
    tmp = tempfile.mkdtemp(prefix="strata-first-hour-")
    try:
        adv = os.path.join(tmp, "advisory.sta")
        open(adv, "w").write("import nothing_here from std;\n"
                             "int main() { return 0; }\n")
        r = run([STRATA, "check", adv], ROOT)
        ok("an unresolvable import is an advisory, not a failure",
           r.returncode == 0 and "advisory" in r.stdout,
           (r.stdout + r.stderr)[-200:])

        bad = os.path.join(tmp, "broken.sta")
        open(bad, "w").write(
            "database Row { int id; }\n"
            "int main() { list[Row] r = Row <- [nope > 0]; return count(r); }\n")
        r = run([STRATA, "check", bad], ROOT)
        ok("a real error still fails", r.returncode != 0 and "E004" in r.stderr,
           (r.stdout + r.stderr)[-200:])

        print("\n── strata new, and everything its README offers ─────────────────")
        work = os.path.join(tmp, "work")
        os.makedirs(work)
        r = run([STRATA, "new", "hello"], work)
        ok("a project is generated", r.returncode == 0, r.stderr[-200:])
        app = os.path.join(work, "hello")

        readme = os.path.join(app, "README.md")
        ok("with a README", os.path.exists(readme))

        r = run([STRATA, "build"], app)
        ok("strata build", r.returncode == 0, (r.stdout + r.stderr)[-200:])

        r = run([STRATA, "run"], app)
        ok("strata run, and it prints its own data",
           r.returncode == 0 and "items: 1" in r.stdout,
           (r.stdout + r.stderr)[-200:])

        r = run([STRATA, "test"], app)
        ok("strata test finds tests and they pass",
           r.returncode == 0 and "1 passed, 0 failed" in r.stdout,
           (r.stdout + r.stderr)[-300:])
        ok("a generated project does not report zero tests",
           "0 passed" not in r.stdout, r.stdout[-200:])

        r = run([STRATA, "check", "src/main.sta"], app)
        ok("strata check on a fresh project", r.returncode == 0,
           (r.stdout + r.stderr)[-200:])

        r = run([STRATA, "fmt", "--check", "src/main.sta", "src/schema.sta",
                 "tests/items_test.sta"], app)
        ok("what strata new writes is already canonically formatted",
           r.returncode == 0, (r.stdout + r.stderr)[-200:])

        # The cross-tier contract, on a project nobody has touched: rename the
        # column and the build must fail at the line that used it.
        schema = os.path.join(app, "src", "schema.sta")
        text = open(schema).read()
        open(schema, "w").write(text.replace("float price;", "float cost;"))
        r = run([STRATA, "build"], app)
        ok("renaming a column in the schema breaks the build",
           r.returncode != 0 and "E004" in (r.stdout + r.stderr),
           (r.stdout + r.stderr)[-200:])
        open(schema, "w").write(text)

        # The README the generator writes tells a newcomer to run
        # `strata repair src/main.sta`. It did nothing: a file inside a
        # project was handed to the compiler from the Strata repository
        # rather than from the project, so neither the file nor its
        # `import schema from app` resolved. The loop saw a compiler failure
        # instead of the E004 that was there and answered "backend produced
        # no change" -- a model that could not help, rather than a loop that
        # never looked. The first thing a newcomer is told to try was the
        # thing that did not work.
        main_sta = os.path.join(app, "src", "main.sta")
        before = open(main_sta).read()
        open(main_sta, "w").write(before.replace("[id > 0]", "[idd > 0]", 1))
        r = run([STRATA, "repair", "src/main.sta"], app)
        out = r.stdout + r.stderr
        ok("repair finds the error in a generated project",
           "E004" in out, out[-200:])
        ok("repair fixes it, with no model involved",
           "[id > 0]" in open(main_sta).read(), out[-200:])
        open(main_sta, "w").write(before)

        # `strata test` printed "BUILD FAIL: <path>" and nothing else, having
        # sent the compiler's output to /dev/null. The diagnostic was right
        # there -- code, line, column and hint -- and a developer had to run
        # `strata check` by hand to see it, from a toolchain whose whole claim
        # is that the error tells you what to do.
        broken = os.path.join(app, "tests", "broken_test.sta")
        open(broken, "w").write(
            "import io from std;\n\n"
            "verify \"it calls something that is not there\" {\n"
            "    assert mystery_function() == 1;\n"
            "}\n")
        r = run([STRATA, "test"], app)
        out = r.stdout + r.stderr
        ok("a test that will not build says why",
           "E011" in out and "mystery_function" in out, out[-250:])
        ok("and says where", "line 4" in out, out[-250:])
        os.remove(broken)

        r = run([STRATA, "test", "--help"], app)
        ok("strata test --help is help, not a filename",
           r.returncode == 0 and "Usage: strata test" in r.stdout,
           (r.stdout + r.stderr)[:160])

        print("\n── every command the README names exists ────────────────────────")
        offered = set(re.findall(r"^    strata (\w+)", open(readme).read(),
                                 re.M))
        usage = run([STRATA], ROOT).stdout
        for cmd in sorted(offered):
            ok(f"strata {cmd} is a real command", f"strata {cmd}" in usage,
               usage[:200])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"  {PASS}/{PASS + FAIL} checks passed")
    print("=" * 64)
    if FAIL:
        print("  The first hour would not go well. NOT OK")
        return 1
    print("  The first hour holds up. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
