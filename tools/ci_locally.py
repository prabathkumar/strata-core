#!/usr/bin/env python3
"""Run exactly what CI runs, in CI's order, on this machine.

Three times in this project a change went green locally and red in CI,
because the tests to run were chosen by what the change *looked like* it
touched. A compiler change that "obviously" did not affect the install
journey broke the install journey. A type-checking change that "obviously"
did not affect the verify blocks broke the verify blocks.

So the list is not maintained here. It is read out of
.github/workflows/build-check.yml, which means it cannot drift: a step added
to CI is a step this runs, with no second place to remember.

    python3 tools/ci_locally.py              # the Linux gate
    python3 tools/ci_locally.py --list       # show the steps, run nothing
    python3 tools/ci_locally.py --from 12    # resume at step 12
    python3 tools/ci_locally.py --from 1 --until 20   # run a slice
    python3 tools/ci_locally.py --job first-run-on-a-mac
    python3 tools/ci_locally.py --jobs       # every job in every workflow

Steps needing root, or a tool this machine does not have, are reported as
SKIP with the reason rather than quietly passing. A skip is not a pass: the
summary says how many there were, and CI still runs them.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = os.path.join(ROOT, ".github", "workflows")


def all_jobs():
    """Every job in every workflow, as {job name: (workflow file, job)}.

    This read one file, build-check.yml, and so had a blind spot the exact
    size of every other workflow. The site workflow has a gate of its own --
    one rename, eight failures, across the data, the rules, the web page and
    the phone screen -- and it counted diagnostics by the shape they were
    printed in. The day every diagnostic gained a filename, that gate went
    red in CI for a change that had been green here, because here never ran
    it. A runner that covers one workflow tells you about one workflow.
    """
    found = {}
    for name in sorted(os.listdir(WORKFLOWS)):
        if not name.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(WORKFLOWS, name)) as fh:
            wf = yaml.safe_load(fh) or {}
        for job, body in (wf.get("jobs") or {}).items():
            found[job] = (name, body)
    return found


def steps_of(job_name):
    jobs = all_jobs()
    if job_name not in jobs:
        print(f"  no job '{job_name}' in any workflow. Jobs: {list(jobs)}")
        sys.exit(2)
    _file, job = jobs[job_name]
    jobs = {job_name: job}
    out = []
    for step in jobs[job_name].get("steps", []):
        run = step.get("run")
        if not run:
            continue  # a `uses:` action — checkout, setup-python, and so on
        out.append((step.get("name", "(unnamed)"), run.strip(), step.get("env") or {}))
    return out


def why_skip(cmd):
    """A reason this machine cannot honestly run the step, or None."""
    if "sudo " in cmd or "apt-get" in cmd:
        return "needs root; CI installs this itself"
    for tool in ("clang", "aarch64-linux-gnu-gcc", "qemu-aarch64-static", "docker"):
        if tool in cmd and shutil.which(tool) is None:
            return f"{tool} is not installed here"
    # The Postgres journey compiles against libpq, which step 2 installs with
    # apt and this machine therefore skips. Without the header the step fails
    # for a reason that has nothing to do with the change being tested.
    if "journey_postgres" in cmd and not any(
            os.path.exists(os.path.join(d, "libpq-fe.h"))
            for d in ("/usr/include", "/usr/include/postgresql",
                      "/usr/local/include", "/opt/homebrew/include")):
        return "libpq-fe.h is not installed here (step 2 installs it in CI)"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", default="validate-conformance")
    ap.add_argument("--jobs", action="store_true",
                    help="list every job in every workflow, run nothing")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--until", dest="until", type=int, default=0,
                    help="stop after this step; for running in slices")
    args = ap.parse_args()

    if args.jobs:
        print("\n── Every job CI runs ───────────────────────────────────────")
        for job, (wf, body) in sorted(all_jobs().items()):
            runs = sum(1 for st in (body.get("steps") or []) if st.get("run"))
            print(f"  {job:<34} {wf:<22} {runs} step(s)")
        print("\n  python3 tools/ci_locally.py --job <name>")
        return 0
    steps = steps_of(args.job)
    if args.list:
        for i, (name, cmd, _env) in enumerate(steps, 1):
            first = cmd.splitlines()[0]
            tail = " …" if len(cmd.splitlines()) > 1 else ""
            print(f"  {i:3d}  {name}\n       {first}{tail}")
        return 0

    print(f"\n── {args.job}, as CI runs it ──────────────────────────────────")
    passed = failed = skipped = 0
    failures = []
    began = time.time()

    for i, (name, cmd, env) in enumerate(steps, 1):
        if i < args.start:
            continue
        if args.until and i > args.until:
            break
        reason = why_skip(cmd)
        if reason:
            skipped += 1
            print(f"  SKIP  {i:3d}  {name} — {reason}")
            continue
        started = time.time()
        merged = dict(os.environ)
        merged.update({k: str(v) for k, v in env.items()})
        r = subprocess.run(["bash", "-c", cmd], cwd=ROOT, env=merged,
                           capture_output=True, text=True)
        took = time.time() - started
        if r.returncode == 0:
            passed += 1
            print(f"  PASS  {i:3d}  {name}  ({took:.0f}s)")
        else:
            failed += 1
            failures.append((i, name, (r.stdout + r.stderr)[-1500:]))
            print(f"  FAIL  {i:3d}  {name}  ({took:.0f}s)")

    print("\n================================================================")
    print(f"  {passed} passed, {failed} failed, {skipped} skipped "
          f"in {time.time() - began:.0f}s")
    print("================================================================")
    for i, name, out in failures:
        print(f"\n── step {i}: {name} ─────────────────────────────────────")
        print(out)
    if failed:
        print("\n  CI would be red. Resume after a fix with "
              f"--from {failures[0][0]}")
        return 1
    if skipped:
        print(f"\n  Green here. {skipped} step(s) only CI can run — a skip is "
              "not a pass.")
        return 0
    print("\n  Green, with nothing skipped. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
