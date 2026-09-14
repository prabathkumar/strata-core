#!/usr/bin/env python3
"""The second application — does the language generalise?

Everything built so far was one application: a signed-in operator, forms,
pages, HTML. A language shaped by its only program is not a general-purpose
language, and there was no way to tell which of the two Strata was.

`apps/ledger` is deliberately the other shape: a command-line tool that also
answers JSON. No pages, no forms, no session, no HTML, a `report` block, and
an import that reads a file rather than a request.

Building it found five things, none of which the orders desk could have:

  1. **The command line was reachable only by writing C.** Every tool in the
     repository, the compiler included, opens `main` with a `native` block
     declaring `extern char** __strata_argv`. `std/cli.sta` is the fix.
  2. **`for Row in rows` generated nothing in a function body.** It parsed
     only inside a layout, and the generator had no rule for it elsewhere —
     so the loop compiled, linked, ran and silently did nothing. The
     generator raises on an unhandled statement now rather than emitting
     nothing.
  3. **There was no way to write JSON.** `std/json.sta` escapes what JSON
     requires, which is not what C requires.
  4. **`char_from_code` lived in std/http.sta**, so writing JSON meant
     importing an HTTP server to get at a string helper. It is in std/str.sta.
  5. **`render X to "path"` takes a literal, not an expression**, so a
     program cannot choose at run time where a report goes. Recorded rather
     than worked around: `ledger report` does not take a filename.

And E008 — the rule the orders desk's auth bypass produced — caught the same
mistake twice in new code within a minute of it being written.

Usage:  python3 test_suite/journey_ledger.py
"""
import json
import os
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


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    tmp = tempfile.mkdtemp(prefix="strata-ledger-")
    work = os.path.join(tmp, "work")
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
        ".git", "build", "__pycache__", "_to_delete"))
    app = os.path.join(work, "apps", "ledger")
    strata = os.path.join(work, "bin", "strata")
    port = free_port()
    proc = None

    def run(args, timeout=600):
        return subprocess.run(args, cwd=app, capture_output=True, text=True,
                              timeout=timeout)

    try:
        os.chmod(strata, 0o755)
        print("\n── It builds and tests like any project ─────────────────────────")
        r = run([strata, "build"])
        ok("the ledger builds", r.returncode == 0, (r.stdout + r.stderr)[-400:])
        if r.returncode != 0:
            return 1
        r = run([strata, "test"])
        ok("its rules pass without a socket or a file", r.returncode == 0,
           (r.stdout + r.stderr)[-400:])

        ledger = os.path.join(app, "build", "ledger")

        # A client name chosen to break a JSON writer that escapes like C.
        nasty = 'O\'Neil "&" Co\tLtd'
        with open(os.path.join(app, "data", "invoices.tsv"), "w") as f:
            f.write("#strata\tInvoice\tid:i\tclient:s\tissued_day:i"
                    "\tamount:f\tsettled:f\tstate:s\n")
            f.write("1\tacme\t100\t1250.00\t0.0\tOPEN\n")
            f.write("2\tglobex\t101\t340.50\t0.0\tOPEN\n")
            f.write("3\tinitech\t102\t980.75\t0.0\tOPEN\n")
            # The tab is the field separator, so it cannot appear in a value;
            # the quote and the ampersand can.
            f.write('4\tO\'Neil "&" Co\t103\t500.00\t0.0\tOPEN\n')
        with open(os.path.join(app, "data", "payments.tsv"), "w") as f:
            f.write("#strata\tPayment\tid:i\tinvoice_id:i"
                    "\treceived_day:i\tamount:f\n")

        print("\n── A command-line tool, in the language ─────────────────────────")
        r = run([ledger])
        ok("run bare, it says what it does", "ledger import" in r.stdout,
           r.stdout[:120])

        pay = os.path.join(tmp, "pay.tsv")
        open(pay, "w").write("1\t110\t1250.00\n"        # exactly
                             "2\t111\t100.00\n"          # part
                             "3\t112\t1000.00\n"         # over
                             "99\t113\t5.00\n")          # no such invoice
        r = run([ledger, "import", pay])
        ok("it reads its arguments", r.returncode == 0, r.stderr[:200])
        ok("and reports what it took and what it refused",
           "imported 3 payment(s), rejected 1" in r.stdout, r.stdout.strip())

        r = run([ledger, "show"])
        summary = json.loads(r.stdout.strip())
        ok("the summary is valid JSON", isinstance(summary, dict))
        ok("paid, part, over and open are each counted once",
           (summary["paid"], summary["part"], summary["over"],
            summary["open"]) == (1, 1, 1, 1), str(summary))
        ok("and the totals are the invoices', not the payments'",
           abs(summary["billed"] - 3071.25) < 0.005, str(summary["billed"]))

        r = run([ledger, "reconcile"])
        ok("reconciling again changes nothing",
           r.stdout.startswith("0 invoice(s)"), r.stdout.strip())

        print("\n── A report, which nothing else has used ────────────────────────")
        r = run([ledger, "report"])
        report = open(os.path.join(app, "ageing.md")).read()
        ok("the report is written", r.returncode == 0)
        ok("with its title and its metric", "# Outstanding invoices" in report
           and "unpaid: 1" in report, report[:150])
        ok("and a table of the rows that are actually outstanding",
           "| id | client |" in report and "O'Neil" in report, report[-200:])

        print("\n── The same data over HTTP, as JSON ─────────────────────────────")
        proc = subprocess.Popen([ledger, "serve", str(port)], cwd=app,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True)
        base = f"http://127.0.0.1:{port}"
        for _ in range(80):
            time.sleep(0.1)
            try:
                urllib.request.urlopen(base + "/health", timeout=2).read()
                break
            except Exception:
                continue

        body = urllib.request.urlopen(base + "/summary", timeout=5).read().decode()
        api = json.loads(body)
        ok("the API agrees with the command line", api == summary, body[:150])

        body = urllib.request.urlopen(base + "/invoices", timeout=5).read().decode()
        rows = json.loads(body)
        ok("every invoice is there", len(rows) == 4, str(len(rows)))

        body = urllib.request.urlopen(base + "/invoices?client=acme",
                                      timeout=5).read().decode()
        ok("and it can be filtered", [r["id"] for r in json.loads(body)] == [1],
           body[:150])

        # The point of json_str: a value containing a quote must come back
        # through a JSON parser as the same value.
        body = urllib.request.urlopen(base + "/invoices", timeout=5).read().decode()
        names = [r["client"] for r in json.loads(body)]
        ok("a client name with a quote in it survives the round trip",
           'O\'Neil "&" Co' in names, str(names))

        try:
            urllib.request.urlopen(urllib.request.Request(
                base + "/summary", data=b"x=1", method="POST"), timeout=5)
            refused = False
        except urllib.error.HTTPError as e:
            refused = e.code == 400 and b"read-only" in e.read()
        ok("a write is refused — this service is read-only", refused)

        try:
            urllib.request.urlopen(base + "/nope", timeout=5)
            missing = False
        except urllib.error.HTTPError as e:
            missing = e.code == 404 and b"no such resource" in e.read()
        ok("an unknown path is a JSON 404", missing)

        line = proc.stdout.readline().strip()
        ok("and it logs that it started", "answering JSON" in line, repr(line))

    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"  {PASS}/{PASS + FAIL} steps passed")
    print("=" * 64)
    if FAIL:
        print("  The second application does not yet stand up. NOT OK")
        return 1
    print("  A second, differently-shaped application works. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
