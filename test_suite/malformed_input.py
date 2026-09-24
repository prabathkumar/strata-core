#!/usr/bin/env python3
"""Break valid programs on purpose and see whether the compiler behaves.

Four bugs this week were the same shape: the happy path tested, the error
path not. A parse error that did not stop the parse. A checker exemption for
a feature that did not exist. A query form that crashed when it matched
nothing. A git dependency whose refusal was tested and whose success was not.

So rather than wait for the fifth, this goes looking. It takes real programs,
deletes a token, doubles a token, or cuts the file off mid-declaration, and
asserts two things about every result:

  * the compiler does not die by signal -- a crash has no line, no column and
    nothing for a person to act on;
  * the two compilers agree on whether the program is acceptable.

It does NOT assert what the diagnostic says. Mutations land in strange places
and the two front ends are allowed to describe the same wreckage differently;
what they may not do is disagree about whether it IS wreckage.

The seed is fixed, so this is a regression test and not a lottery.
"""
import os
import random
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from driver_path import driver_path
DRIVER = driver_path(ROOT)
SEED = 20260920
SEEDS = [
    "examples/quickstart.sta",
    "examples/aggregation.sta",
    "examples/query_expression.sta",
    "examples/report_rendering.sta",
    "examples/schema_migration.sta",
    "apps/orders/src/rules.sta",
]
TOKEN = re.compile(
    r'"[^"]*"|//[^\n]*|\s+|[A-Za-z_][A-Za-z0-9_]*|[0-9]+\.[0-9]+|[0-9]+'
    r'|<-|==|!=|<=|>=|.', re.S)
PER_FILE = {"delete": 10, "double": 6, "truncate": 5}


def mutations(src, rng):
    parts = TOKEN.findall(src)
    live = [i for i, x in enumerate(parts) if x.strip() and not x.startswith("//")]
    if not live:
        return []
    out = []
    for i in rng.sample(live, min(PER_FILE["delete"], len(live))):
        out.append((f"delete {parts[i]!r}", "".join(parts[:i] + parts[i + 1:])))
    for i in rng.sample(live, min(PER_FILE["double"], len(live))):
        out.append((f"double {parts[i]!r}",
                    "".join(parts[:i] + [parts[i], parts[i]] + parts[i + 1:])))
    for i in rng.sample(live, min(PER_FILE["truncate"], len(live))):
        out.append((f"cut before {parts[i]!r}", "".join(parts[:i])))
    return out


def main():
    if not os.path.isfile(DRIVER):
        b = subprocess.run(
            [sys.executable, "bootstrap/stage0.py", "compiler/driver.sta",
             "-o", DRIVER], cwd=ROOT, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr)
            print("  Could not build the driver. FAIL")
            return 1

    rng = random.Random(SEED)
    tried = 0
    crashes = []
    disagreements = []

    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "m.sta")
        for seed in SEEDS:
            original = open(os.path.join(ROOT, seed)).read()
            for label, text in mutations(original, rng):
                tried += 1
                open(src_path, "w").write(text)
                try:
                    d = subprocess.run(
                        [DRIVER, src_path, "-o", os.path.join(tmp, "d")],
                        cwd=ROOT, capture_output=True, text=True, timeout=120)
                    b = subprocess.run(
                        [sys.executable, "bootstrap/stage0.py", src_path,
                         "-o", os.path.join(tmp, "b")],
                        cwd=ROOT, capture_output=True, text=True, timeout=120)
                except subprocess.TimeoutExpired:
                    crashes.append((seed, label, "the compiler did not finish"))
                    continue

                if d.returncode < 0 or d.returncode == 139:
                    crashes.append((seed, label,
                                    f"driver died (exit {d.returncode})"))
                    continue
                if (d.returncode == 0) != (b.returncode == 0):
                    disagreements.append(
                        (seed, label,
                         f"driver exited {d.returncode}, bootstrap {b.returncode}"))

    print("=" * 64)
    for seed, label, detail in (crashes + disagreements)[:10]:
        print(f"  {seed} [{label}]")
        print(f"    {detail}")
    extra = len(crashes) + len(disagreements) - 10
    if extra > 0:
        print(f"  ... and {extra} more")
    print(f"  {tried} malformed programs, {len(crashes)} crashes, "
          f"{len(disagreements)} disagreements")
    print("=" * 64)
    if crashes or disagreements:
        print("  The compiler does not handle malformed input. FAIL")
        return 1
    print("  Malformed input is rejected, not crashed on. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
