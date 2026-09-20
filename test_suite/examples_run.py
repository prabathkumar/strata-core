#!/usr/bin/env python3
"""Every example builds, and the ones that finish, run.

examples/ is what someone reads first, and nothing built it. A file there
could stop compiling — or compile and then crash — and no suite would say so.
That is how `memory_ownership.sta` came to segfault on the one line it was
written to demonstrate, and how three other examples came to stop building
entirely.

A unit with no main() is a library: it is built as an object file and not
run. Everything else is run with a time limit and must exit 0.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")
EXAMPLES = os.path.join(ROOT, "examples")
TIMEOUT = 20

# An example that is meant to be built but not run, with the reason. A file
# lands here because running it is not meaningful, never because it fails.
BUILD_ONLY = {
    "microservice_template.sta": "a server: it waits for connections and does not return",
    "benchmark_dashboard.sta": "a library unit; its report is rendered by a caller",
}

HAS_MAIN = re.compile(r"^\s*(int|void|def)\s+main\s*\(", re.M)


def main():
    names = sorted(f for f in os.listdir(EXAMPLES) if f.endswith(".sta"))
    if not names:
        print("  No examples found. FAIL")
        return 1

    built = ran = skipped = 0
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            src = os.path.join("examples", name)
            out = os.path.join(tmp, name[:-4])
            b = subprocess.run([STRATA, "build", src, "-o", out],
                               cwd=ROOT, capture_output=True, text=True)
            if b.returncode != 0:
                failures.append(
                    f"{src} does not build:\n      "
                    + (b.stdout + b.stderr).strip()[-400:].replace("\n", "\n      "))
                continue
            built += 1

            source = open(os.path.join(EXAMPLES, name)).read()
            if not HAS_MAIN.search(source):
                skipped += 1
                continue
            if name in BUILD_ONLY:
                skipped += 1
                continue

            binary = out if os.path.isfile(out) else out + ".o"
            if binary.endswith(".o"):
                skipped += 1
                continue
            try:
                r = subprocess.run([binary], cwd=tmp, capture_output=True,
                                   text=True, timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                failures.append(
                    f"{src} did not finish in {TIMEOUT}s. If it is not meant "
                    f"to, add it to BUILD_ONLY with the reason.")
                continue
            if r.returncode != 0:
                detail = (r.stderr or r.stdout).strip()[-300:]
                crash = " (killed by a signal — a crash, not an exit)" \
                    if r.returncode < 0 else ""
                failures.append(
                    f"{src} exited {r.returncode}{crash}"
                    + (f":\n      {detail}" if detail else ""))
                continue
            ran += 1

    print("=" * 62)
    for f in failures:
        print(f"  {f}")
    print(f"  {built}/{len(names)} build, {ran} run clean, "
          f"{skipped} built but not run")
    print("=" * 62)
    if failures:
        print("  The examples do not all work. FAIL")
        return 1
    print("  Every example builds, and the ones that finish, run. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
