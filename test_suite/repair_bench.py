#!/usr/bin/env python3
"""How much can a model actually repair? Measure it, per backend.

The repair loop has four backends: `rules`, which is deterministic and costs
nothing; `local`, a model on your own machine; and `llm`/`claude`, which are
hosted. Which of them can fix what is not a thing to have opinions about, and
the answer decides what a developer should reach for first.

So this runs every case in test_suite/repair_bench/ through a backend and
reports, per diagnostic, whether it was fixed. A case is fixed only when the
compiler is satisfied afterwards -- not when the model says something
plausible.

    python3 test_suite/repair_bench.py                  # rules
    python3 test_suite/repair_bench.py --backend local  # your own model
    STRATA_REPAIR_MODEL=qwen2.5-coder:1.5b \\
        python3 test_suite/repair_bench.py --backend local

Nothing here runs in CI. `rules` is covered by the repair tests; a benchmark
against a model on somebody's laptop is a measurement, not a gate.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(ROOT, "test_suite", "repair_bench")
REPAIR = os.path.join(ROOT, "ai_self_repair.py")
COMPILER = os.path.join(ROOT, "bootstrap", "stage0.py")


def diagnostics(path, cwd):
    r = subprocess.run([sys.executable, COMPILER, path, "--json"],
                       capture_output=True, text=True, cwd=cwd)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    return sorted({x["code"] for x in d.get("diagnostics", [])})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", default="rules",
                    choices=["rules", "local", "llm", "claude"])
    ap.add_argument("--passes", type=int, default=4)
    a = ap.parse_args()

    names = sorted(f for f in os.listdir(CASES) if f.endswith(".sta"))
    if not names:
        print("  no cases in test_suite/repair_bench/")
        return 1

    model = os.environ.get("STRATA_REPAIR_MODEL", "")
    print("=" * 70)
    print(f"  Repair benchmark — backend: {a.backend}"
          + (f", model: {model}" if model and a.backend == "local" else ""))
    print("=" * 70)

    fixed = 0
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            src = os.path.join(tmp, name)
            shutil.copy(os.path.join(CASES, name), src)
            before = diagnostics(name, tmp) or ["?"]

            started = time.time()
            r = subprocess.run(
                [sys.executable, REPAIR, name, "--backend", a.backend,
                 "--max-passes", str(a.passes)],
                capture_output=True, text=True, cwd=tmp)
            took = time.time() - started

            after = diagnostics(name, tmp)
            ok = after == []
            if ok:
                fixed += 1
            rows.append((name, ",".join(before), ok, took,
                         ",".join(after) if after else ""))

    width = max(len(n) for n, *_ in rows)
    print(f"  {'case'.ljust(width)}  was      fixed   took   left")
    for name, before, ok, took, after in rows:
        print(f"  {name.ljust(width)}  {before.ljust(7)}  "
              f"{'yes  ' if ok else 'NO   '}  {took:5.1f}s  {after}")

    print("=" * 70)
    print(f"  {fixed}/{len(rows)} repaired by `{a.backend}`")
    if a.backend == "rules":
        print("  Whatever rules can fix costs nothing and needs no model.")
    else:
        print("  Compare against `rules`: a model is only worth calling for")
        print("  what the deterministic backend cannot do.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
