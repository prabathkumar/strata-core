#!/usr/bin/env python3
"""A Strata function may be called anything, including what libc calls things.

The generated C had no namespace, so a Strata function and a C library
function with the same name were the same symbol. A program with a function
called `send` compiled and ran for as long as it imported nothing that pulled
in <sys/socket.h>. The day it imported `std/fetch`, the C compiler reported
conflicting types for `send` at line 10919 of a 417-kilobyte generated file,
naming no Strata line at all -- and `strata check` had said the program was
fine, which is the one thing it must never say about a program that will not
build.

The repair is a prefix on every function a program defines, not a list of
names to avoid. A list would have to know which symbols the emitted includes
declare, which depends on what the program imports, differs between platforms
and libc versions, and grows without anybody being told. Four review rounds
running have said that patching the instance leaves the same bug one name
over.

So this file does not test `send`. It tests a sample of names across several
headers, and -- the part that matters -- it tests the names this project has
never heard of by checking the RULE: the emitted C defines no function under
a name the program wrote, except `main`.

Run: python3 test_suite/a_name_cannot_collide_with_c.py
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

# One per header a real program is likely to drag in. `index` and `remove`
# are the quiet ones: both are in the C standard and neither looks like a
# system call.
NAMES = ["send", "connect", "read", "write", "index", "remove", "link",
         "time", "signal", "open", "close", "stat", "div", "exit"]

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


def main():
    print()
    print("── a name cannot collide with C ──" + "─" * 30)

    with tempfile.TemporaryDirectory() as d:
        for name in NAMES:
            src = f'''import io from std;
import fetch from std;
import os from std;
import time from std;
def {name}(str message) {{ print(message); }}
int main() {{ {name}("ran"); return 0; }}'''
            p = os.path.join(d, f"{name}.sta")
            open(p, "w").write(src)
            out = os.path.join(d, f"{name}.bin")
            r = subprocess.run([STRATA, "build", p, "-o", out],
                               capture_output=True, text=True, timeout=600)
            text = r.stdout + r.stderr
            if r.returncode != 0:
                ok(f"a function called '{name}' builds", False, text[-300:])
                continue
            r2 = subprocess.run([out], capture_output=True, text=True,
                                timeout=120)
            ok(f"a function called '{name}' builds and runs",
               r2.returncode == 0 and "ran" in r2.stdout,
               f"rc={r2.returncode} {(r2.stdout + r2.stderr)[-200:]}")

        # The rule itself, over this repository's own code. Every function
        # defined in the generated C under a name the Strata source wrote
        # would be a collision waiting for the right import.
        probe = '''import io from std;
import fetch from std;
int helper_one(int a) { return a + 1; }
def helper_two(str s) { print(s); }
int main() { print(str(helper_one(1))); helper_two("x"); return 0; }'''
        p = os.path.join(d, "probe.sta")
        open(p, "w").write(probe)
        c_out = os.path.join(d, "probe_c")
        subprocess.run([sys.executable,
                        os.path.join(ROOT, "bootstrap", "stage0.py"),
                        p, "-o", c_out, "--emit-c"],
                       capture_output=True, text=True, timeout=600)
        gen = None
        for cand in (os.path.join(d, "probe.c"), c_out + ".c"):
            if os.path.isfile(cand):
                gen = open(cand).read()
                break
        if gen is None:
            r = subprocess.run([sys.executable,
                                os.path.join(ROOT, "bootstrap", "stage0.py"),
                                p, "-o", os.path.join(d, "probe.bin")],
                               capture_output=True, text=True, timeout=600)
            cand = os.path.join(d, "probe.c")
            gen = open(cand).read() if os.path.isfile(cand) else ""

        ok("the generated C does not define the name the program wrote",
           gen and not re.search(r"^\w[\w \*]*\bhelper_one\s*\(", gen, re.M),
           "a function is emitted under its Strata name, so it is one import "
           "away from colliding with a C library symbol")
        ok("it defines the prefixed name instead",
           gen and "st_helper_one" in gen and "st_helper_two" in gen,
           "the prefix is gone; see fname() in stage0.py")
        ok("and main keeps its name, because the C runtime looks for it",
           gen and re.search(r"\bint main\s*\(", gen) is not None,
           "main was renamed, so nothing will start the program")

    print()
    print("=" * 62)
    print(f"  {passed} ok, {len(failures)} failed")
    print("=" * 62)
    if failures:
        for f in failures:
            print("  - " + f[:300])
        print("  A Strata name can collide with a C one again. FAIL")
        return 1
    print("  A Strata function may be called anything. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
