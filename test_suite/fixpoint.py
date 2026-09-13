#!/usr/bin/env python3
"""The self-hosting fixpoint.

Passing a differential test proves the Strata code generator agrees with the
Python one. It does not prove the Strata generator can reproduce itself, which
is the property that actually retires the bootstrap.

    stage0 (Python)  --C-->  gen1.c  --cc-->  strata1
    strata1          --C-->  gen2.c  --cc-->  strata2
    strata2          --C-->  gen3.c

strata1 is the Strata code generator built from Python-generated C. strata2 is
the same generator built from C that it generated itself. If gen2 and gen3 are
identical, the compiler is a fixed point of its own translation: compiling it
again changes nothing, so the Python bootstrap can be removed without changing
the output.

gen1 == gen2 is checked too. It is the stronger statement — that the Strata
generator agrees with the oracle on its own source — and it is what makes the
bootstrap's removal safe rather than merely stable.
"""
import hashlib
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "build", "fixpoint")
SOURCE = os.path.join("compiler", "strata_cli.sta")   # lex + parse + check + emit


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kw)


def cc(c_path, out_path):
    compiler = os.environ.get("STRATA_CC")
    candidates = [compiler] if compiler else ["clang", "gcc", "cc"]
    for c in candidates:
        if run(["which", c]).returncode == 0:
            r = run([c, "-O2", "-Wno-implicit-function-declaration",
                     "-o", out_path, c_path, "-lm"])
            return r.returncode == 0, r.stderr
    return False, "no C compiler found"


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)

    print("\n── Self-hosting fixpoint ────────────────────────────────────────")
    print(f"  source: {SOURCE}\n")

    gen1 = os.path.join(WORK, "gen1.c")
    r = run([sys.executable, "bootstrap/stage0.py", SOURCE, "--emit-c"])
    if r.returncode != 0:
        print("  stage0 could not emit C:\n" + r.stderr[:400]); return 1
    open(gen1, "w").write(r.stdout)
    print(f"  stage0  -> gen1.c   {sha(gen1)}  ({len(r.stdout.splitlines())} lines)")

    strata1 = os.path.join(WORK, "strata1")
    ok, err = cc(gen1, strata1)
    if not ok:
        print("  gen1.c did not compile:\n" + err[:400]); return 1
    print(f"  cc      -> strata1")

    gen2 = os.path.join(WORK, "gen2.c")
    r = run([strata1, SOURCE])
    if r.returncode != 0:
        print("  strata1 could not emit C:\n" + r.stderr[:400]); return 1
    open(gen2, "w").write(r.stdout)
    print(f"  strata1 -> gen2.c   {sha(gen2)}  ({len(r.stdout.splitlines())} lines)")

    strata2 = os.path.join(WORK, "strata2")
    ok, err = cc(gen2, strata2)
    if not ok:
        print("  gen2.c did not compile:\n" + err[:400]); return 1
    print(f"  cc      -> strata2")

    gen3 = os.path.join(WORK, "gen3.c")
    r = run([strata2, SOURCE])
    if r.returncode != 0:
        print("  strata2 could not emit C:\n" + r.stderr[:400]); return 1
    open(gen3, "w").write(r.stdout)
    print(f"  strata2 -> gen3.c   {sha(gen3)}  ({len(r.stdout.splitlines())} lines)")

    a, b, c = open(gen1).read(), open(gen2).read(), open(gen3).read()
    print()
    ok = True
    if b == c:
        print("  gen2 == gen3   the generator reproduces itself exactly")
    else:
        print("  gen2 != gen3   NOT a fixed point")
        ok = False
    if a == b:
        print("  gen1 == gen2   and it agrees with the Python bootstrap")
    else:
        print("  gen1 != gen2   diverges from the bootstrap on its own source")
        ok = False

    print("\n" + "=" * 64)
    if ok:
        print("  FIXPOINT REACHED — the bootstrap can be retired.")
    else:
        print("  Fixpoint not reached.")
    print("=" * 64)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
