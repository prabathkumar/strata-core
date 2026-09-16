#!/usr/bin/env python3
"""Stage 10 — operating the thing.

Everything up to here proved the service does its job and survives contact.
This asks the different question: could anyone run it? Can they see what it is
doing, and does it refuse the traffic that is not a customer?

  - one line per request, on stdout, as it happens
  - `/health` and `/metrics`, answered without a session, from counters that
    survive the child process that did the work
  - a failed request written to stderr with enough to find it again
  - a form posted from somewhere else is refused
  - guessing a password locks the account, and the lockout does not leak
    which usernames are real
  - a flood of connections is refused rather than forking until the machine
    runs out of processes

What it found on the way in:

  - A signed-in operator's browser could be made to post to this service by
    any page on the web. Nothing distinguished a form this service rendered
    from one that merely pointed at it.
  - Passwords could be guessed as fast as the service could answer, which was
    about 450 a second.
  - `SIGCHLD` was handed to `SIG_IGN`, so the service could not count its own
    children and had no way to refuse the next connection.
  - `strata test` in the module that holds the lockout rules stopped seeing
    them: a module-level `int LOCKOUT_AFTER = 5;` does not parse, and takes
    the rest of the file with it.
(Not a finding, stated so nobody mistakes it for one: the counters were built
on shared memory from the start, because a process-per-connection service
cannot keep them anywhere else. It was reasoned, not discovered the hard way.)

Usage:  python3 test_suite/journey_operate.py
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def main():
    tmp = tempfile.mkdtemp(prefix="strata-operate-")
    work = os.path.join(tmp, "work")
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
        ".git", "build", "__pycache__", "_to_delete"))
    app = os.path.join(work, "apps", "orders")
    port = free_port()
    proc = None
    lines = []
    errs = []

    try:
        src = os.path.join(app, "src", "main.sta")
        text = open(src).read()
        open(src, "w").write(text.replace("http_listen(8080)",
                                          f"http_listen({port})"))
        r = subprocess.run([os.path.join(work, "bin", "strata"), "build"],
                           cwd=app, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-400:])
            ok("the service builds", False)
            return 1

        proc = subprocess.Popen([os.path.join(app, "build", "orders")], cwd=app,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1)

        # Read the log on a thread, so a test can look at what has been written
        # so far without blocking on the next line.
        def pump():
            for line in proc.stdout:
                lines.append(line.strip())
        threading.Thread(target=pump, daemon=True).start()

        # stderr is read separately, because that is where failures go and a
        # test that only watches stdout cannot tell a logged failure from a
        # silent one.
        def pump_err():
            for line in proc.stderr:
                errs.append(line.strip())
        threading.Thread(target=pump_err, daemon=True).start()

        base = f"http://127.0.0.1:{port}"
        for _ in range(80):
            time.sleep(0.1)
            try:
                urllib.request.urlopen(base + "/health", timeout=2).read()
                break
            except Exception:
                continue

        def session():
            return urllib.request.build_opener(
                NoRedirect, urllib.request.HTTPCookieProcessor(CookieJar()))

        def go(opener, path, data=None, method=None):
            req = urllib.request.Request(base + path, data=data, method=method)
            try:
                r = opener.open(req, timeout=10)
                return r.status, r.read().decode(), dict(r.headers)
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode(), dict(e.headers)

        print("\n── Signing out removes the row ──────────────────────────────────")
        # Sessions used to be expired in place, because the language had no
        # delete: every sign-out left a row that would never be read again.
        sessions = os.path.join(app, "data", "sessions.tsv")

        def session_rows():
            if not os.path.exists(sessions):
                return 0
            return len([l for l in open(sessions).read().splitlines()[1:] if l])

        s0 = session()
        go(s0, "/login", b"username=manager&password=strata", "POST")
        _, page0, _ = go(s0, "/")
        m0 = re.search(r'name="_csrf" type="hidden" value="([^"]+)"', page0)
        after_login = session_rows()
        ok("signing in writes a session", after_login >= 1, str(after_login))
        go(s0, "/logout", f"_csrf={m0.group(1) if m0 else ''}".encode(), "POST")
        after_logout = session_rows()
        ok("signing out removes the row rather than expiring it in place",
           after_logout == after_login - 1,
           f"{after_login} -> {after_logout}")

        print("\n── Anyone can see what it is doing ──────────────────────────────")
        ok("it logs that it started",
           any("listening" in l for l in lines), str(lines[:3]))

        before = len(lines)
        s1 = session()
        go(s1, "/login")
        time.sleep(0.4)
        new = lines[before:]
        ok("a request produces a log line", len(new) >= 1, str(new))
        ok("which says what was asked, what it got and how long it took",
           bool(new) and re.match(r"^GET /login 200 \d+ms$", new[-1]),
           str(new[-1:]))

        before = len(lines)
        go(s1, "/nope")
        time.sleep(0.4)
        ok("a signed-out request is logged as the redirect it was",
           any(l.startswith("GET /nope 303") for l in lines[before:]),
           str(lines[before:]))

        print("\n── It can be asked how it is doing ──────────────────────────────")
        # Neither page needs a session. A health check that fails because a
        # cookie expired reports the wrong thing, and whatever is watching a
        # service is a machine, not somebody with a password.
        code, body, _ = go(session(), "/health")
        ok("/health answers without signing in", code == 200, f"got {code}")
        ok("and says how long it has been up",
           "uptime_seconds" in body, repr(body[:80]))

        code, body, _ = go(session(), "/metrics")
        ok("/metrics answers without signing in", code == 200, f"got {code}")
        counters = dict()
        for line in body.splitlines():
            bits = line.split()
            if len(bits) == 2 and not line.startswith("#"):
                counters[bits[0]] = int(bits[1])
        ok("it reports a request count",
           counters.get("strata_requests_total", 0) > 0, str(counters)[:120])

        # The real question about these counters. The service forks a process
        # per connection, so a counter kept in an ordinary variable would be
        # incremented by a child that then exits, and every reading would be
        # zero. They live in a page of memory mapped before the first fork.
        before_total = counters.get("strata_requests_total", 0)
        for _ in range(5):
            go(session(), "/health")
        time.sleep(0.3)
        _, body, _ = go(session(), "/metrics")
        after = dict()
        for line in body.splitlines():
            bits = line.split()
            if len(bits) == 2 and not line.startswith("#"):
                after[bits[0]] = int(bits[1])
        ok("counts survive the process that did the work",
           after.get("strata_requests_total", 0) >= before_total + 5,
           f"{before_total} -> {after.get('strata_requests_total')}")
        ok("successes and failures are counted apart",
           after.get("strata_requests_2xx", 0) > 0
           and "strata_requests_5xx" in after, str(after)[:160])
        ok("slow requests would be visible",
           sum(after.get(f"strata_request_ms_bucket_{b}", 0)
               for b in ("1", "10", "100", "1000", "slower"))
           == after.get("strata_requests_total", -1),
           "the buckets should add up to the total")

        # A failed request is findable afterwards. The per-request log on
        # stdout is for watching; this is for the morning after, when somebody
        # has a complaint and a rough time.
        before_errs = len(errs)
        go(session(), "/orders", b"x=1", "POST")     # no session, no token
        time.sleep(0.4)
        written = errs[before_errs:]
        ok("a refused request writes a failure line", len(written) >= 1,
           str(written))
        ok("with the time, the path, the status and how long it took",
           bool(written) and re.match(
               r"^ERROR ts=\d+ method=POST path=/orders status=403 took_ms=\d+$",
               written[-1]), str(written[-1:]))

        before_errs = len(errs)
        go(session(), "/health")
        time.sleep(0.3)
        ok("a request that worked writes no failure line",
           len(errs) == before_errs, str(errs[before_errs:]))

        print("\n── A form from somewhere else is refused ────────────────────────")
        go(s1, "/login", b"username=manager&password=strata", "POST")
        code, body, _ = go(s1, "/")
        ok("signed in, the dashboard renders", code == 200, f"got {code}")
        m = re.search(r'name="_csrf" type="hidden" value="([^"]+)"', body)
        csrf = m.group(1) if m else ""
        ok("its forms carry a token", len(csrf) == 64, f"len {len(csrf)}")

        code, _, _ = go(s1, "/orders",
                        b"customer=forged&region=apac&amount=1.00", "POST")
        ok("a write with a valid session but no token is refused",
           code == 403, f"got {code}")

        before = len(lines)
        go(s1, "/nope")
        time.sleep(0.4)
        ok("and now that there is a session, a 404 is logged as a 404",
           any(l.startswith("GET /nope 404") for l in lines[before:]),
           str(lines[before:]))

        code, _, _ = go(s1, "/orders",
                        b"_csrf=0000&customer=forged&region=apac&amount=1.00",
                        "POST")
        ok("and a wrong token is refused too", code == 403, f"got {code}")

        code, _, _ = go(s1, "/orders",
                        f"_csrf={csrf}&customer=real&region=apac&amount=1.00"
                        .encode(), "POST")
        ok("the page's own form still works", code == 303, f"got {code}")

        # A second session's token must not work in this one.
        s2 = session()
        go(s2, "/login", b"username=manager&password=strata", "POST")
        _, body2, _ = go(s2, "/")
        m2 = re.search(r'name="_csrf" type="hidden" value="([^"]+)"', body2)
        other = m2.group(1) if m2 else ""
        ok("the two sessions have different tokens", other and other != csrf)
        code, _, _ = go(s1, "/orders",
                        f"_csrf={other}&customer=x&region=apac&amount=1.00"
                        .encode(), "POST")
        ok("another session's token does not work here", code == 403,
           f"got {code}")

        print("\n── Guessing a password stops working ────────────────────────────")
        guesser = session()
        codes = []
        for i in range(5):
            _, b, _ = go(guesser, "/login",
                         f"username=manager&password=wrong{i}".encode(), "POST")
            codes.append("Wrong username or password" in b)
        ok("the first five guesses are simply wrong", all(codes), str(codes))

        code, body, _ = go(guesser, "/login",
                           b"username=manager&password=wrong5", "POST")
        ok("the sixth is refused with 429", code == 429, f"got {code}")
        ok("and says the account is locked", "Too many attempts" in body,
           body[:120])

        code, body, _ = go(guesser, "/login",
                           b"username=manager&password=strata", "POST")
        ok("the real password does not work while locked", code == 429,
           f"got {code}")

        code, body, _ = go(guesser, "/login",
                           b"username=ghost&password=whatever", "POST")
        ok("an account that does not exist answers like a wrong password, "
           "not like a lockout", code == 200
           and "Wrong username or password" in body, f"got {code}")

        print("\n── A flood is refused, not served ───────────────────────────────")
        # Open more connections than the service will serve at once and hold
        # them, so the cap is what answers rather than the speed of the box.
        held = []
        try:
            for _ in range(90):
                c = socket.create_connection(("127.0.0.1", port), timeout=5)
                c.sendall(b"GET /login HTTP/1.1\r\nHost: x\r\n")   # unfinished
                held.append(c)
            time.sleep(1.0)
            busy = 0
            for c in held:
                c.settimeout(2)
                try:
                    if b"503" in c.recv(64):
                        busy += 1
                except Exception:
                    pass
            ok("connections past the cap are answered 503", busy > 0,
               f"{busy} of {len(held)}")
        finally:
            for c in held:
                try:
                    c.close()
                except Exception:
                    pass

        time.sleep(0.5)
        ok("the service is still up", proc.poll() is None)

        # The flood's children are still holding their connections until the
        # read timeout expires, so the cap is still full and the next request
        # is legitimately refused. What matters is that the service comes back
        # on its own, not that it comes back instantly — an earlier version of
        # this check asked once, half a second later, and called a correct 503
        # a failure.
        code = 0
        deadline = time.time() + 20
        while time.time() < deadline:
            code, _, _ = go(session(), "/login")
            if code == 200:
                break
            time.sleep(0.5)
        ok("and serving normally once the flood's connections time out",
           code == 200, f"got {code}")
        ok("the refusals are in the log",
           any(l.startswith("- - 503") for l in lines), str(lines[-3:]))
        # Counted apart from the 5xx. A connection the service never started
        # is a capacity problem; a 500 is a bug. One number for both would
        # have hidden this flood behind what looks like a broken handler.
        _, body, _ = go(session(), "/metrics")
        refused = 0
        for line in body.splitlines():
            if line.startswith("strata_connections_refused"):
                refused = int(line.split()[1])
        ok("and counted as refusals, not as server errors", refused > 0,
           f"{refused} refused")

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
        print("  Nobody could operate this yet. NOT OK")
        return 1
    print("  The service can be watched, and refuses what is not a customer. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
