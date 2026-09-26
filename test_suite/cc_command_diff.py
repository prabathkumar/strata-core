#!/usr/bin/env python3
"""The two compilers build the same C compiler command.

Generating C is half a build. The other half is a set of decisions about the
machine it is being built on: which C compiler is installed, whether this unit
is a program or a library, which portability flags keep clang and gcc
agreeing, where this distribution keeps the Postgres headers. The bootstrap
made those in Python. compiler/build.sta makes them in Strata.

They have to agree exactly, and the failure mode if they do not is nasty:
these flags are the ones that make a bug fail on CI's clang and build cleanly
on a developer's older gcc. A driver that quietly dropped -Werror=return-type
would look perfect until the day it let a real bug through.

Every .sta file in the tree, as a native build, a wasm build, and a test build.
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "build", "cc_cli")
SKIP_DIRS = {".git", "build", "node_modules", "Claude outputs", "_to_delete",
             "unimplemented", "repair_cases", "typecheck_cases", "verify_cases"}
CC_LINE = re.compile(r"^  CC: (.*)$", re.M)


def sources():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.endswith(".sta"):
                yield os.path.join(dirpath, name)


def bootstrap_command(path, out, target, test_mode):
    cmd = [sys.executable, "bootstrap/stage0.py", os.path.relpath(path, ROOT),
           "-o", out, "--target", target, "-v"]
    if test_mode:
        cmd.append("--test")
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    m = CC_LINE.search(r.stdout)
    return m.group(1) if m else None


def driver_command(path, out, target, test_mode):
    r = subprocess.run(
        [CLI, ROOT, os.path.relpath(path, ROOT), out, target,
         "1" if test_mode else "0"],
        cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip()


def a_pinned_compiler_may_carry_flags():
    """STRATA_CC is taken as written by both compilers, flags and all.

    Retargeting the phone object at the iOS Simulator is

        STRATA_CC="clang -target arm64-apple-ios26.0-simulator -isysroot ..."

    The driver handed that to a shell and it worked. The bootstrap ran `which`
    over the whole string, decided it was not a command name and stopped with
    "No C compiler found" -- so the same environment variable meant different
    things depending on whether the self-hosted driver happened to be built for
    your machine. That is the divergence these tests exist for, and nothing was
    checking how the two read the environment rather than the source.
    """
    import tempfile
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "pinned.sta")
        with open(src, "w") as f:
            f.write("import io from std;\nint helper() { return 7; }\n")
        env = dict(os.environ, STRATA_CC="cc -DSTRATA_PINNED_FLAG=1")

        b = subprocess.run([sys.executable,
                            os.path.join(ROOT, "bootstrap", "stage0.py"),
                            src, "-o", os.path.join(tmp, "boot")],
                           capture_output=True, text=True, cwd=ROOT, env=env)
        if b.returncode != 0:
            problems.append("the bootstrap rejected a STRATA_CC carrying flags: "
                            + (b.stderr or b.stdout).strip()[-140:])

        d = subprocess.run([os.path.join(ROOT, "bin", "strata"), "build", src,
                            "-o", os.path.join(tmp, "drv")],
                           capture_output=True, text=True, cwd=ROOT, env=env)
        if d.returncode != 0:
            problems.append("the driver rejected a STRATA_CC carrying flags: "
                            + (d.stderr or d.stdout).strip()[-140:])
    return problems


def main():
    if not os.path.isfile(CLI):
        print(f"  building {os.path.relpath(CLI, ROOT)}")
        os.makedirs(os.path.dirname(CLI), exist_ok=True)
        b = subprocess.run(
            [sys.executable, "bootstrap/stage0.py", "compiler/cc_cli.sta",
             "-o", CLI], cwd=ROOT, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("  Could not build the Strata side. FAIL")
            return 1

    modes = [("native", False), ("wasm", False), ("native", True)]
    checked = same = skipped = 0
    divergent = []
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out")
        for path in sources():
            rel = os.path.relpath(path, ROOT)
            for target, test_mode in modes:
                expected = bootstrap_command(path, out, target, test_mode)
                if expected is None:
                    # The bootstrap did not get as far as invoking cc -- a
                    # fixture it is meant to reject, or a unit wasm cannot
                    # build. Not this test's business.
                    skipped += 1
                    continue
                actual = driver_command(path, out, target, test_mode)
                checked += 1
                if expected == actual:
                    same += 1
                else:
                    label = f"{rel} [{target}{', test' if test_mode else ''}]"
                    divergent.append((label, expected, actual))

    print("=" * 62)
    for label, expected, actual in divergent[:10]:
        print(f"  {label}")
        print(f"    bootstrap: {expected}")
        print(f"    strata:    {actual}")
    if len(divergent) > 10:
        print(f"  ... and {len(divergent) - 10} more")
    print(f"  {same}/{checked} agree, {len(divergent)} divergent, {skipped} skipped")

    pinned = a_pinned_compiler_may_carry_flags()
    for p in pinned:
        print(f"  {p}")
    print(f"  a pinned compiler may carry flags: "
          f"{'yes' if not pinned else 'NO'}")
    print("=" * 62)
    if divergent or pinned:
        print("  The two compilers disagree about how to invoke cc. FAIL")
        return 1
    print("  Both compilers invoke the C compiler identically. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
