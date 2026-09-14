#!/usr/bin/env python3
"""Journey A — an operations manager runs the orders desk.

This walks the whole journey rather than its parts: sign in, look, create,
close, sign out, and be refused afterwards. Feature-by-feature checks each
passed while the journey as a whole did not, which is the reason this file
exists.

What it found on the way in, none of which a unit test would have:

  - `crypt(3)` returns a buffer libc reuses, so the stored hash and a
    freshly computed one were the SAME POINTER and every password matched.
  - `random_hex` returned a `static char[]`, so two session tokens were the
    same pointer and every session was the same session.
  - `Session <- [token == token]` compares the column with itself, because
    inside a query a bare name is always the column. A lookup for a token
    that does not exist returned every row. That is E008 now.
  - a `link` in an imported module was dropped, so linking failed.

Usage:  python3 test_suite/journey_orders.py
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "apps", "orders")
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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 303 is a result to assert on, not something to follow."""
    def redirect_request(self, *a, **kw):
        return None


def main():
    port_probe = socket.socket()
    port_probe.bind(("127.0.0.1", 0))
    port = port_probe.getsockname()[1]
    port_probe.close()

    src = os.path.join(APP, "src", "main.sta")
    data = os.path.join(APP, "data")
    original_src = open(src).read()
    saved = {}
    for name in ("orders.tsv", "users.tsv", "sessions.tsv"):
        p = os.path.join(data, name)
        saved[name] = open(p).read() if os.path.exists(p) else None

    open(src, "w").write(
        original_src.replace("http_listen(8080)", f"http_listen({port})"))
    proc = None
    try:
        r = subprocess.run([STRATA, "build"], cwd=APP, capture_output=True,
                           text=True, timeout=300)
        ok("the service builds", r.returncode == 0, (r.stdout + r.stderr)[-300:])
        if r.returncode != 0:
            return

        proc = subprocess.Popen([os.path.join(APP, "build", "orders")], cwd=APP,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            time.sleep(0.1)
            try:
                urllib.request.urlopen(base + "/health", timeout=2).read()
                break
            except Exception:
                continue

        jar = CookieJar()
        session = urllib.request.build_opener(
            NoRedirect, urllib.request.HTTPCookieProcessor(jar))

        def go(path, data=None, method=None):
            req = urllib.request.Request(base + path, data=data, method=method)
            try:
                r = session.open(req, timeout=5)
                return r.status, r.read().decode(), dict(r.headers)
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode(), dict(e.headers)

        print("\n── Signed out ───────────────────────────────────────────────────")
        code, _, headers = go("/")
        ok("the dashboard is not reachable", code == 303,
           f"got {code}")
        ok("and it points at the sign-in page",
           headers.get("Location", "").endswith("/login"), headers.get("Location"))

        code, body, _ = go("/login")
        ok("the sign-in page is reachable", code == 200, f"got {code}")
        ok("and carries a sign-in form", '<form action="/login"' in body)

        print("\n── Signing in ───────────────────────────────────────────────────")
        code, body, _ = go("/login", b"username=manager&password=wrong", "POST")
        ok("a wrong password is refused", "Wrong username or password" in body,
           body[:120])
        ok("and sets no session cookie", not any(c.name == "sid" for c in jar))

        code, _, headers = go("/login", b"username=manager&password=strata", "POST")
        ok("the right password signs in", code == 303, f"got {code}")
        ok("a session cookie is set", any(c.name == "sid" for c in jar))
        token = next((c.value for c in jar if c.name == "sid"), "")
        ok("the token is not guessable", len(token) == 64, f"len {len(token)}")

        print("\n── Working ──────────────────────────────────────────────────────")
        code, body, _ = go("/")
        ok("the dashboard is reachable now", code == 200, f"got {code}")
        ok("it offers the actions of the job",
           "Add order" in body and "Close" in body and "Sign out" in body)
        ok("each row carries its own id",
           'name="id" type="hidden" value="1"' in body, body[-400:])

        code, body, _ = go("/summary")
        ok("two orders are open", "open orders: 2" in body, body[:160])

        code, _, _ = go("/orders",
                        b"customer=wayne+ent&region=apac&amount=450.25", "POST")
        ok("an order is created", code == 303, f"got {code}")
        code, body, _ = go("/summary")
        ok("three orders are open now", "open orders: 3" in body, body[:160])
        ok("and the value went up", "2040.75" in body, body[:160])
        ok("the row reached disk, percent-decoded",
           "wayne ent" in open(os.path.join(data, "orders.tsv")).read())

        code, _, _ = go("/close", b"id=1", "POST")
        ok("an order is closed", code == 303, f"got {code}")
        code, body, _ = go("/summary")
        ok("two orders are open again", "open orders: 2" in body, body[:160])

        print("\n── Signing out ──────────────────────────────────────────────────")
        code, _, _ = go("/logout", b"", "POST")
        ok("signing out redirects", code == 303, f"got {code}")

        code, _, headers = go("/")
        ok("the dashboard is refused again", code == 303, f"got {code}")
        ok("and points at the sign-in page",
           headers.get("Location", "").endswith("/login"))
        code, _, _ = go("/orders", b"customer=x&amount=1", "POST")
        ok("and so is a write", code == 403, f"got {code}")

        # The session was ended, not merely forgotten by the client: replaying
        # the old cookie must not work either.
        replay = urllib.request.build_opener(NoRedirect)
        req = urllib.request.Request(base + "/summary")
        req.add_header("Cookie", f"sid={token}")
        try:
            code = replay.open(req, timeout=5).status
        except urllib.error.HTTPError as e:
            code = e.code
        ok("replaying the old session token does not work", code == 303,
           f"got {code}")
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        open(src, "w").write(original_src)
        for name, content in saved.items():
            p = os.path.join(data, name)
            if content is not None:
                open(p, "w").write(content)
        subprocess.run([STRATA, "build"], cwd=APP, capture_output=True, timeout=300)


main()
total = PASS + FAIL
print("\n" + "=" * 64)
print(f"  {PASS}/{total} steps of the journey passed")
print("=" * 64)
if FAIL == 0:
    print("  An operations manager can run the orders desk. OK")
    sys.exit(0)
print(f"  {FAIL} FAILED")
sys.exit(1)
