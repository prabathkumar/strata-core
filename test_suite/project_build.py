#!/usr/bin/env python3
"""A Strata project builds and runs as a project.

`Strata.toml` existed for months and nothing read it: `strata build` took a
file path, so there was no such thing as "a Strata application" — only a
collection of files someone compiled by hand. This checks the unit is the
project.

What is checked, in the order a developer meets it:

  1. `strata new` scaffolds something that builds and runs without editing.
  2. `strata build` with no arguments builds the project the current
     directory belongs to, including from a subdirectory.
  3. `Strata.toml` actually drives it — change `output` and the binary moves.
  4. Outside a project it says so, rather than doing something surprising.
  5. `apps/orders`, the real service, builds this way and serves.

Usage:  python3 test_suite/project_build.py
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def run(args, cwd, timeout=180):
    return subprocess.run([STRATA] + args, cwd=cwd, capture_output=True,
                          text=True, timeout=timeout)


print("\n── strata new ───────────────────────────────────────────────────")

work = tempfile.mkdtemp()
try:
    r = run(["new", "widgets"], work)
    proj = os.path.join(work, "widgets")
    ok("scaffolds a project", r.returncode == 0 and os.path.isdir(proj),
       (r.stdout + r.stderr)[-200:])
    ok("with a Strata.toml", os.path.isfile(os.path.join(proj, "Strata.toml")))
    ok("with more than one source file",
       {"main.sta", "schema.sta"} <= set(os.listdir(os.path.join(proj, "src"))),
       str(os.listdir(os.path.join(proj, "src"))))
    ok("refuses to overwrite an existing directory",
       run(["new", "widgets"], work).returncode != 0)

    r = run(["build"], proj)
    ok("the scaffold builds unedited", r.returncode == 0,
       (r.stdout + r.stderr)[-300:])
    ok("the binary lands where Strata.toml says",
       os.path.isfile(os.path.join(proj, "build", "widgets")))

    r = run(["run"], proj)
    ok("and it runs", r.returncode == 0 and "items: 1" in r.stdout,
       (r.stdout + r.stderr)[-200:])

    print("\n── the project is the unit ──────────────────────────────────────")

    r = run(["build"], os.path.join(proj, "src"))
    ok("building from a subdirectory finds the project", r.returncode == 0,
       (r.stdout + r.stderr)[-200:])

    # Strata.toml drives it: if it does not, moving `output` changes nothing.
    toml = os.path.join(proj, "Strata.toml")
    text = open(toml).read().replace('output = "build/widgets"',
                                     'output = "build/renamed"')
    open(toml, "w").write(text)
    r = run(["build"], proj)
    ok("changing `output` moves the binary",
       r.returncode == 0 and os.path.isfile(os.path.join(proj, "build", "renamed")),
       (r.stdout + r.stderr)[-200:])

    text = open(toml).read().replace('main = "src/main.sta"',
                                     'main = "src/nothing_here.sta"')
    open(toml, "w").write(text)
    r = run(["build"], proj)
    ok("a `main` that does not exist is an error, named",
       r.returncode != 0 and "nothing_here" in (r.stdout + r.stderr),
       (r.stdout + r.stderr)[-200:])

    r = run(["build"], work)
    ok("outside a project it says so",
       r.returncode != 0 and "Strata.toml" in (r.stdout + r.stderr),
       (r.stdout + r.stderr)[-200:])
finally:
    shutil.rmtree(work, ignore_errors=True)


print("\n── the real service ─────────────────────────────────────────────")

orders = os.path.join(ROOT, "apps", "orders")
if not os.path.isdir(orders):
    ok("apps/orders is present", False)
else:
    r = run(["build"], orders)
    ok("apps/orders builds as a project", r.returncode == 0,
       (r.stdout + r.stderr)[-300:])

    # A free port, so the suite does not fight whatever is already running.
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    src = os.path.join(orders, "src", "main.sta")
    original = open(src).read()
    open(src, "w").write(original.replace("http_listen(8080)", f"http_listen({port})"))
    proc = None
    try:
        r = run(["build"], orders)
        if r.returncode != 0:
            ok("the service builds on a test port", False, (r.stdout + r.stderr)[-200:])
        else:
            proc = subprocess.Popen([os.path.join(orders, "build", "orders")],
                                    cwd=orders, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            body = ""
            for _ in range(40):
                time.sleep(0.1)
                try:
                    body = urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/summary", timeout=2).read().decode()
                    break
                except Exception:
                    continue
            # The numbers come from data/orders.tsv, read back through a load,
            # which is what made the pointer-comparison bug visible.
            ok("it serves the summary", "open orders:" in body, body[:160])
            ok("the aggregates are right, after a load from disk",
               "open orders: 2" in body and "1590.5" in body, body[:200])
    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=10)
        open(src, "w").write(original)
        run(["build"], orders)

total = PASS + FAIL
print("\n" + "=" * 62)
print(f"  {PASS}/{total} checks passed")
print("=" * 62)
if FAIL == 0:
    print("  A project is the unit of building, and the service serves. OK")
    sys.exit(0)
print(f"  {FAIL} FAILED")
sys.exit(1)
