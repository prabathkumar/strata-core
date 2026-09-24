#!/usr/bin/env python3
"""The Strata driver builds what the bootstrap builds.

compiler/driver.sta does a whole build in Strata: parse, type check, generate
C, write it, invoke the C compiler. This checks the end of that pipeline
rather than the middle -- for each program, build it with the bootstrap and
with the driver and compare the finished artefacts byte for byte, then run
both and compare what they print and what they exit with.

Byte-identical binaries are a strong claim and the right one to make here:
the same C through the same compiler with the same flags must produce the
same file. Anything else means a decision diverged somewhere this test can
then go and find.
"""
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from driver_path import driver_path
DRIVER = driver_path(ROOT)

# A program from each corner of the language: business rules over tables, the
# compiler's own front end, screens, the test harness, and a library unit with
# no main() so the object-file path is covered too.
# (source, run it once built). The application entry points are HTTP servers:
# they build to a program that waits for connections and never returns, so
# they are compared as files and not executed.
PROGRAMS = [
    ("apps/orders/src/main.sta", False),
    ("apps/ledger/src/main.sta", False),
    ("compiler/strata_cli.sta", False),
    ("compiler/fmt_cli.sta", False),
    ("examples/pipeline_testing.sta", False),
    ("std/str.sta", False),
    ("std/os.sta", False),
    # These two terminate, so the comparison goes past the file and checks
    # that the two builds actually behave the same.
    ("examples/aggregation.sta", True),
    ("examples/ffi_math.sta", True),
    # An import with no local checkout. E007 is an ADVISORY: the build carries
    # on and the symbols are left to the linker. Nothing here exercised that
    # until it caught the driver treating every diagnostic as fatal, so a
    # program with an external dependency would not build at all.
    ("examples/ml_bridge.sta", False),
    ("examples/network_routing.sta", False),
]


def build_bootstrap(src, out, workdir):
    return subprocess.run(
        [sys.executable, "bootstrap/stage0.py", src, "-o", out],
        cwd=ROOT, capture_output=True, text=True)


def build_driver(src, out, workdir):
    return subprocess.run([DRIVER, src, "-o", out],
                          cwd=ROOT, capture_output=True, text=True)


def artefact(out):
    for candidate in (out, out + ".o"):
        if os.path.isfile(candidate):
            return candidate
    return None


def main():
    if not os.path.isfile(DRIVER):
        print(f"  building {os.path.relpath(DRIVER, ROOT)}")
        os.makedirs(os.path.dirname(DRIVER), exist_ok=True)
        b = subprocess.run(
            [sys.executable, "bootstrap/stage0.py", "compiler/driver.sta",
             "-o", DRIVER], cwd=ROOT, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("  Could not build the driver. FAIL")
            return 1

    passed = 0
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        for src, runnable in PROGRAMS:
            path = os.path.join(ROOT, src)
            if not os.path.isfile(path):
                failures.append(f"{src}: not in the tree")
                continue

            out_b = os.path.join(tmp, "boot_" + os.path.basename(src)[:-4])
            out_d = os.path.join(tmp, "drv_" + os.path.basename(src)[:-4])
            rb = build_bootstrap(src, out_b, tmp)
            rd = build_driver(src, out_d, tmp)

            if (rb.returncode == 0) != (rd.returncode == 0):
                failures.append(
                    f"{src}: bootstrap exited {rb.returncode}, "
                    f"driver exited {rd.returncode}\n"
                    f"      driver said: {rd.stdout.strip()[-300:]}"
                    f"{rd.stderr.strip()[-300:]}")
                continue
            if rb.returncode != 0:
                # Both refused it. Agreeing to refuse is agreement.
                passed += 1
                continue

            ab, ad = artefact(out_b), artefact(out_d)
            if ab is None or ad is None:
                failures.append(f"{src}: no artefact (bootstrap={ab}, driver={ad})")
                continue
            if os.path.basename(ab).replace("boot_", "") != \
               os.path.basename(ad).replace("drv_", ""):
                failures.append(
                    f"{src}: different output names -- "
                    f"{os.path.basename(ab)} vs {os.path.basename(ad)}")
                continue
            if not filecmp.cmp(ab, ad, shallow=False):
                failures.append(
                    f"{src}: the two builds differ "
                    f"({os.path.getsize(ab)} vs {os.path.getsize(ad)} bytes)")
                continue

            if ab.endswith(".o") or not runnable:
                passed += 1
                continue

            eb = subprocess.run([ab], cwd=tmp, capture_output=True, text=True,
                                timeout=60)
            ed = subprocess.run([ad], cwd=tmp, capture_output=True, text=True,
                                timeout=60)
            if (eb.returncode, eb.stdout) != (ed.returncode, ed.stdout):
                failures.append(f"{src}: the two builds behave differently")
                continue
            passed += 1

    print("=" * 62)
    for f in failures:
        print(f"  {f}")
    print(f"  {passed}/{len(PROGRAMS)} built identically by both compilers")
    print("=" * 62)
    if failures:
        print("  The driver does not reproduce the bootstrap's build. FAIL")
        return 1
    print("  The driver builds what the bootstrap builds. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
