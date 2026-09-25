#!/usr/bin/env python3
"""Journey B — a developer changes the system.

Clone, run it, add a column, watch the build break, let the repair loop fix
it, run the tests, and check the data written before the change still loads.

This is the journey that makes the language's argument rather than the
service's: the claim is that a change to the data tier is caught everywhere it
matters, at build time, and that an agent can close the loop from the
compiler's own diagnostics. A journey either demonstrates that or exposes that
it is not true.

What it found on the way in:

  - Adding a column was not an error anywhere. Every insert in the program
    would have written the new column as an empty string, in every row,
    silently. That is E009 now, and it is what makes this journey have a
    middle at all.
  - The repair loop assumed a single file. A project's diagnostics arrive
    with the file they are in, and the loop ignored that field.
  - `strata test` could only see `test_suite/*.sta`. An application had no
    way to be tested, which is why apps/orders had none.
  - `import x from app` resolved only beside the importing file, so a test
    in tests/ could not import the module it tests.

Usage:  python3 test_suite/journey_change.py [--worktree]

        --worktree runs against the working tree instead of an export of
        HEAD. Useful while developing the journey; CI runs it without.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def run(args, cwd, timeout=600):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(app, port):
    """Start the built service on `port` and wait for it to answer."""
    proc = subprocess.Popen([os.path.join(app, "build", "orders")], cwd=app,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        time.sleep(0.1)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                   timeout=2).read()
            return proc
        except Exception:
            continue
    return proc


def checkout(worktree):
    tmp = tempfile.mkdtemp(prefix="strata-journey-b-")
    work = os.path.join(tmp, "work")
    if worktree:
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
            ".git", "build", "__pycache__", "_to_delete"))
    else:
        tar = os.path.join(tmp, "head.tar")
        r = run(["git", "archive", "-o", tar, "HEAD"], ROOT)
        if r.returncode != 0:
            raise SystemExit("could not export HEAD: " + r.stderr[:200])
        os.makedirs(work)
        subprocess.run(["tar", "-xf", tar, "-C", work], check=True)
    return tmp, work


def main():
    worktree = "--worktree" in sys.argv
    tmp, work = checkout(worktree)
    strata = os.path.join(work, "bin", "strata")
    app = os.path.join(work, "apps", "orders")
    schema = os.path.join(app, "src", "schema.sta")
    port = free_port()
    proc = None

    try:
        os.chmod(strata, 0o755)
        print("\n── A developer clones and runs it ───────────────────────────────")
        ok("the clone carries the application", os.path.isfile(schema))

        r = run([strata, "build"], app)
        ok("it builds unchanged", r.returncode == 0, (r.stdout + r.stderr)[-300:])
        if r.returncode != 0:
            return

        r = run([strata, "test"], app)
        ok("its own tests pass", r.returncode == 0, (r.stdout + r.stderr)[-400:])
        ok("and they are the application's, not the compiler's",
           "rules_test" in r.stdout, r.stdout[-200:])

        # Bind the service to a free port for the duration.
        main_src = os.path.join(app, "src", "main.sta")
        text = open(main_src).read()
        open(main_src, "w").write(text.replace("http_listen(8080)",
                                               f"http_listen({port})"))
        run([strata, "build"], app)
        proc = serve(app, port)
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/login",
                                      timeout=5).read().decode()
        ok("the service serves", "password" in body, body[:120])
        proc.terminate(); proc.wait(timeout=10); proc = None

        rows_before = open(os.path.join(app, "data", "orders.tsv")).read()
        ok("and there is data on disk from before the change",
           rows_before.count("\n") > 1, rows_before[:120])

        print("\n── The change: orders gain a priority ───────────────────────────")
        s = open(schema).read()
        assert "str   status;" in s
        open(schema, "w").write(s.replace(
            '    str   status;              // "OPEN" or "CLOSED"',
            '    str   status;              // "OPEN" or "CLOSED"\n'
            '    str   priority;            // "normal" or "rush"'))

        r = run([strata, "build"], app)
        ok("the build fails", r.returncode != 0)
        out = r.stdout + r.stderr
        ok("with E009 at every insert that now omits the column",
           out.count("E009") >= 4, out[-400:])
        ok("and names the column that was added", "priority" in out)

        # The failing sites are in more than one file, which is the point of
        # checking the data tier against every tier that uses it.
        diag = run([sys.executable, os.path.join(work, "bootstrap", "stage0.py"),
                    "src/main.sta", "--json"], app)
        import json
        payload = json.loads(diag.stdout)
        files = {d["file"] for d in payload["diagnostics"] if d["code"] == "E009"}
        ok("across both files that insert rows", len(files) >= 2, str(files))

        print("\n── The repair loop refuses this one, and says why ───────────────")
        # It used to close E009 by writing the zero value of the column into
        # every insert, report "clean" and exit 0 -- which is the corruption
        # E009 exists to catch, committed by the tool that exists to fix it.
        # Only the person adding a column knows what rows already written
        # should hold, so there is no safe automatic answer and refusing is
        # the whole point.
        before_repair = {f: open(os.path.join(app, "src", f)).read()
                         for f in ("main.sta", "rules.sta")}
        r = run([sys.executable, os.path.join(work, "ai_self_repair.py"),
                 "--project", app, "--max-passes", "12"], work)
        out_r = r.stdout + r.stderr
        ok("the loop does not claim to have fixed it",
           "clean after" not in r.stdout, out_r[-300:])
        ok("it names E009 and says a default is not an answer",
           "E009" in out_r and "decision" in out_r, out_r[-300:])
        ok("it exits non-zero", r.returncode != 0, str(r.returncode))
        ok("and it changed nothing",
           all(open(os.path.join(app, "src", f)).read() == t
               for f, t in before_repair.items()))

        print("\n── The developer says what the column holds ─────────────────────")
        # What a person does next: decide, and name it at every site. This is
        # the work the compiler insisted on rather than let happen silently.
        for f in ("main.sta", "rules.sta"):
            path = os.path.join(app, "src", f)
            text = open(path).read()
            # Only where the insert ends -- `o.status = "CLOSED";` is a field
            # assignment on a row already in hand, and adding a column to
            # that is a parse error. The compiler caught it; a text edit that
            # looked right did not.
            text = re.sub(r'(status = "(?:OPEN|CLOSED)")\]',
                          r'\1, priority = "normal"]', text)
            open(path, "w").write(text)
        r = run([strata, "build"], app)
        ok("naming it at every site builds", r.returncode == 0,
           (r.stdout + r.stderr)[-300:])

        r = run([strata, "build"], app)
        ok("the build passes", r.returncode == 0, (r.stdout + r.stderr)[-300:])

        r = run([strata, "test"], app)
        ok("the tests still pass", r.returncode == 0, (r.stdout + r.stderr)[-400:])

        r = run([strata, "fmt", os.path.join(app, "src", "rules.sta")], work)
        ok("and the repaired source formats canonically", r.returncode == 0,
           (r.stdout + r.stderr)[-200:])

        print("\n── The data written before the change still loads ───────────────")
        proc = serve(app, port)
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        opener.open(f"http://127.0.0.1:{port}/login",
                    b"username=manager&password=strata", timeout=5)
        page = opener.open(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
        ok("the rows from before the change are on the dashboard",
           "acme" in page and "globex" in page, page[:200])

        # The service requires the session's CSRF token on a write, so the
        # journey reads it off the page it was rendered on, like a browser.
        token = re.search(r'name="_csrf" type="hidden" value="([^"]+)"', page)
        opener.open(f"http://127.0.0.1:{port}/orders",
                    f"_csrf={token.group(1) if token else ''}"
                    f"&customer=wayne&region=amer&amount=99.50".encode(),
                    timeout=5)
        page = opener.open(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
        ok("a new order can still be created", "wayne" in page, page[:200])
        proc.terminate(); proc.wait(timeout=10); proc = None

        after = open(os.path.join(app, "data", "orders.tsv")).read()
        ok("the new column reached the file's header", "priority:s" in after,
           after.splitlines()[0] if after else "")
        ok("and every row carries it",
           all(len(l.split("\t")) == 6 for l in after.splitlines()[1:] if l),
           after[:200])

        print("\n── Deploy ───────────────────────────────────────────────────────")
        if shutil.which("docker") is None:
            print("  SKIP  docker is not installed here; CI builds and runs the "
                  "image on every push")
        else:
            # The service was bound to a free port for the steps above, by
            # rewriting its source. The image must ship the real thing, on
            # 8080, or it listens on a port nothing is mapped to — which is
            # what happened the first time this ran anywhere with Docker
            # installed, and is a defect in this journey rather than in the
            # service.
            bound = open(main_src).read()
            open(main_src, "w").write(
                bound.replace(f"http_listen({port})", "http_listen(8080)"))
            r = run(["docker", "build", "-t", "strata-orders:journey", "."], work,
                    timeout=1800)
            ok("the image builds", r.returncode == 0, (r.stdout + r.stderr)[-500:])
            if r.returncode == 0:
                dport = free_port()
                c = run(["docker", "run", "-d", "-p", f"{dport}:8080",
                         "strata-orders:journey"], work)
                cid = c.stdout.strip()
                served = False
                for _ in range(60):
                    time.sleep(1)
                    try:
                        b = urllib.request.urlopen(
                            f"http://127.0.0.1:{dport}/login", timeout=2).read()
                        served = b"password" in b
                        break
                    except Exception:
                        continue
                if not served:
                    logs = run(["docker", "logs", cid], work)
                    detail = (logs.stdout + logs.stderr)[-300:]
                else:
                    detail = ""
                ok("and the container serves the sign-in page", served, detail)
                run(["docker", "rm", "-f", cid], work)

    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"  {PASS}/{PASS + FAIL} steps of the journey passed")
    print("=" * 64)
    if FAIL:
        print("  A developer cannot yet change the system. NOT OK")
        return 1
    print("  A developer can change the system and deploy it. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
