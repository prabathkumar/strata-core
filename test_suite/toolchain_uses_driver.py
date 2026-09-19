#!/usr/bin/env python3
"""`strata build` runs the self-hosted driver, not the bootstrap.

Proving the driver equivalent is not the same as using it. This checks the
toolchain actually reaches for compiler/driver.sta, that the escape hatch back
to the bootstrap works, that a stale driver is rebuilt rather than silently
reused, and that both paths produce the same binary.

The escape hatch matters as much as the default. If the driver is ever wrong,
whoever hits it needs a way past without editing the toolchain.
"""
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")
DRIVER = os.path.join(ROOT, "build", "strata-build")
SOURCE = "examples/aggregation.sta"

failures = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def build(out, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([STRATA, "build", SOURCE, "-o", out],
                          cwd=ROOT, capture_output=True, text=True, env=env)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        driver_out = os.path.join(tmp, "by_driver")
        boot_out = os.path.join(tmp, "by_bootstrap")

        r = build(driver_out)
        check("strata build succeeds", r.returncode == 0, r.stderr[-300:])
        check("the driver binary exists after a build", os.path.isfile(DRIVER))
        # The bootstrap announces itself; the driver does not.
        check("the build did not go through the bootstrap",
              "[Strata Stage 0]" not in r.stdout, r.stdout[-200:])

        r = build(boot_out, {"STRATA_BOOTSTRAP": "1"})
        check("STRATA_BOOTSTRAP=1 still works", r.returncode == 0, r.stderr[-300:])
        check("and it really is the bootstrap",
              "[Strata Stage 0]" in r.stdout, r.stdout[-200:])

        if os.path.isfile(driver_out) and os.path.isfile(boot_out):
            check("both paths produce the same binary",
                  filecmp.cmp(driver_out, boot_out, shallow=False))
        else:
            check("both paths produce a binary", False)

        # A driver older than the compiler must be rebuilt, or editing the
        # compiler and running a build would use yesterday's driver.
        if os.path.isfile(DRIVER):
            stale = time.time() - 3600
            os.utime(DRIVER, (stale, stale))
            before = os.path.getmtime(DRIVER)
            r = build(os.path.join(tmp, "after_touch"))
            after = os.path.getmtime(DRIVER)
            check("a driver older than the compiler is rebuilt",
                  after > before and r.returncode == 0)

        # A directory is not a source file, and saying so beats crashing.
        r = subprocess.run([DRIVER, "apps/orders"], cwd=ROOT,
                           capture_output=True, text=True)
        check("a directory gets a diagnostic, not a crash",
              r.returncode == 1 and "directory" in r.stderr,
              f"exit {r.returncode}: {r.stderr[-200:]}")

    print("=" * 62)
    if failures:
        for f in failures:
            print(f"  {f}")
        print("  The toolchain is not using the driver as intended. FAIL")
        return 1
    print("  strata build runs the self-hosted driver. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
