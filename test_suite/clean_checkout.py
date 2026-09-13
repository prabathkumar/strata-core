#!/usr/bin/env python3
"""Verify the committed tree builds — not just the working tree.

A file can exist locally, be required by every build, and never reach the
repository. compiler/runtime_preamble.c did exactly that: `.gitignore` carried
`*.c` to exclude generated output, which silently excluded the runtime prelude
the compiler reads on every run. Everything passed locally and every CI step
failed.

This exports HEAD with `git archive` — which contains exactly what a clone
gets — and runs the conformance suite inside it. Anything the build needs but
does not track fails here.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    tmp = tempfile.mkdtemp(prefix="strata-clean-")
    try:
        tar = os.path.join(tmp, "head.tar")
        r = subprocess.run(["git", "archive", "-o", tar, "HEAD"],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            print("  could not export HEAD:", r.stderr.strip()[:200])
            return 1
        work = os.path.join(tmp, "work")
        os.makedirs(work)
        subprocess.run(["tar", "-xf", tar, "-C", work], check=True)

        print("\n── Clean checkout ───────────────────────────────────────────────")
        missing = [f for f in ("compiler/runtime_preamble.c", "bootstrap/stage0.py",
                               "compiler/parser.py", "compiler/typechecker.py")
                   if not os.path.exists(os.path.join(work, f))]
        for f in missing:
            print(f"  MISSING  {f} — required by the build, not tracked")
        if missing:
            print(f"\n  {len(missing)} required file(s) absent from the committed tree.")
            return 1

        r = subprocess.run([sys.executable, "test_suite/conformance.py"],
                           capture_output=True, text=True, cwd=work)
        ok = r.returncode == 0
        tail = [l for l in r.stdout.splitlines() if "Results:" in l]
        print(f"  conformance in a clean export: {tail[0].strip() if tail else 'no output'}")
        if not ok:
            print("\n".join(r.stdout.splitlines()[-12:]))
        print("\n" + "=" * 64)
        print("  The committed tree builds. OK" if ok
              else "  The committed tree does NOT build.")
        print("=" * 64)
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
