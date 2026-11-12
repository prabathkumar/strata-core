#!/usr/bin/env python3
"""std/session.sta and std/jobs.sta: the two components every back office needs.

Both were lifted out of apps/orders, which had a working sign-in and a
hand-rolled sweep inside its accept loop. Lifting them out is only worth
anything if the properties survive the move, so this file is mostly a list
of properties and the single thing that goes wrong when each one breaks.

WHY EACH CASE IS HERE
--------------------

Sessions. Every one of these is an attack somebody has actually run:

  * a protected page served without a cookie is a service with no sign-in
    at all, so the refusal is checked before anything else
  * a session id that can be guessed is a session id that will be. 256 bits
    from /dev/urandom, two sign-ins never alike, and a made-up id is nobody
  * a session that never expires turns one stolen laptop into permanent
    access. The expiry is checked by rewriting `expires_at` in the stored
    file into the past: the ROW is still there, and it must still be refused
  * sign-out that only redirects leaves the cookie working. The same cookie
    is replayed afterwards and must be refused
  * the CSRF token must not be the cookie token (the browser sends the
    cookie by itself; that is the whole problem), must not be another
    session's token, and "no token at all" must not pass — which is the bug
    the obvious spelling `str_eq(form, csrf_for(cookie))` has, because for a
    request with no session both sides are ""
  * the method is checked BEFORE the token on a write path. Round 16 found
    exactly this in apps/orders: `GET /close` answered about a missing token
    instead of 405, which meant a write could be reached by a method the
    CSRF check was never applied to
  * a password guesser is slowed down, and the throttle counts against the
    pair (account, source) so that guessing at somebody else's username
    cannot lock them out
  * a role may do what it was granted and nothing else, or permissions are
    decoration
  * the password is never stored or logged in the clear — checked by
    searching everything the service wrote for it

Jobs. The hard part is not running something on a clock, it is what happens
when it goes wrong and when there are two runners:

  * a job runs
  * a failing job tries again, with a GROWING gap — measured in wall time,
    so a backoff that stopped doubling fails this
  * a failing job GIVES UP rather than retrying for ever
  * a second runner started by accident does not start
  * a job already claimed is not handed out again until its lease expires,
    and IS handed out once it has — which is this module's honest guarantee:
    never two at once, but a body may run twice over the life of the system

Run: python3 test_suite/components_auth_jobs.py
"""
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import http.client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")
STAGE0 = os.path.join(ROOT, "bootstrap", "stage0.py")

failures = []
passed = 0


def ok(label, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}")
        failures.append(f"{label}: {detail}")


def write(d, name, src):
    p = os.path.join(d, name)
    os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(name) else None
    with open(p, "w") as f:
        f.write(src)
    return p


def build(src_path, out_path, cwd):
    r = subprocess.run([STRATA, "build", src_path, "-o", out_path],
                       capture_output=True, text=True, timeout=600, cwd=cwd)
    return r.returncode, r.stdout + r.stderr


def verify_blocks(rel_sta, out_path):
    """Build and run one file's `verify` blocks, the way `strata test` does."""
    r = subprocess.run([sys.executable, STAGE0, rel_sta, "--test", "-o", out_path],
                       capture_output=True, text=True, timeout=600, cwd=ROOT)
    if r.returncode != 0:
        return False, r.stdout + r.stderr
    r2 = subprocess.run([out_path], capture_output=True, text=True,
                        timeout=600, cwd=ROOT)
    return r2.returncode == 0, r2.stdout + r2.stderr


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ── The service under test ───────────────────────────────────────────────
#
# Nothing in it but std/session.sta: two accounts, one page that needs a
# session, one page that needs a permission, one write path, sign-out.

SERVICE = '''
import io      from std;
import str     from std;
import mem     from std;
import http    from std;
import time    from std;
import session from std;

const int SVC_PORT = %PORT%;

int seed() {
    auth_load();
    if (auth_user_id_of("boss") == 0) {
        auth_add_user("boss", "letmein", "manager");
        auth_add_user("clerk", "pencil", "clerk");
        auth_save_all();
    }
    return 1;
}

str page(str title, str body) {
    StringBuilder sb = sb_new();
    sb_append(&sb, "<!doctype html><title>");
    sb_append(&sb, title);
    sb_append(&sb, "</title>");
    sb_append(&sb, body);
    return sb_to_str(&sb);
}

str home(int who, str sid) {
    StringBuilder sb = sb_new();
    sb_append(&sb, "<p>signed in as ");
    sb_append(&sb, auth_username_of(who));
    sb_append(&sb, " role ");
    sb_append(&sb, auth_role_of(who));
    sb_append(&sb, "</p><form method=post action=/close><input type=hidden name=_csrf value=\\"");
    sb_append(&sb, auth_csrf_for(sid));
    sb_append(&sb, "\\"></form>");
    return page("home", sb_to_str(&sb));
}

int is_write_path(str path) {
    if (str_eq(path, "/close") == 1) { return 1; }
    if (str_eq(path, "/logout") == 1) { return 1; }
    return 0;
}

int writes_data(str request) {
    if (is_write_path(http_path(request)) == 1) { return 1; }
    if (str_eq(http_path(request), "/login") == 1) {
        if (str_eq(http_method(request), "POST") == 1) { return 1; }
    }
    return 0;
}

int do_login(int conn, str body, int when) {
    str who = http_form_value(body, "username");
    str where_from = http_peer_ip(conn);
    str token = auth_sign_in(who, http_form_value(body, "password"), where_from, when);
    auth_save_users();
    auth_save_attempts();
    if (str_len(token) == 0) {
        if (auth_locked_for(who, where_from, when) > 0) {
            return http_respond(conn, 429, "text/html", page("locked", "<p>too many</p>"));
        }
        return http_respond(conn, 401, "text/html", page("no", "<p>no</p>"));
    }
    if (auth_save_sessions() == 0) {
        return http_respond(conn, 503, "text/html", page("no", "<p>not stored</p>"));
    }
    return http_redirect_with(conn, "/", auth_cookie_header(token));
}

int handle(int conn, str request) {
    int when   = now();
    str method = http_method(request);
    str path   = http_path(request);
    str body   = http_body(request);
    str sid    = http_cookie(request, "sid");
    int who    = auth_user_of_token(sid, when);

    if (str_eq(path, "/health") == 1) { return http_respond(conn, 200, "text/plain", "ok\\n"); }
    if (str_eq(path, "/login") == 1) {
        if (str_eq(method, "POST") == 1) { return do_login(conn, body, when); }
        if (str_eq(method, "GET") == 1) { return http_ok(conn, page("in", "<form></form>")); }
        return http_respond(conn, 405, "text/html", page("no", "<p>405</p>"));
    }
    if (who == 0) {
        if (str_eq(method, "GET") == 1) { return http_redirect(conn, "/login"); }
        return http_forbidden(conn);
    }
    if (is_write_path(path) == 1) {
        if (str_eq(method, "POST") == 0) {
            return http_respond(conn, 405, "text/html", page("no", "<p>405</p>"));
        }
        if (auth_csrf_ok(sid, http_form_value(body, "_csrf")) == 0) {
            return http_respond(conn, 403, "text/html", page("no", "<p>403 csrf</p>"));
        }
    }
    if (str_eq(path, "/logout") == 1) {
        auth_sign_out(sid);
        auth_save_sessions();
        return http_redirect_with(conn, "/login", auth_clear_cookie_header());
    }
    if (str_eq(path, "/close") == 1) {
        if (auth_may(who, "orders.close") == 0) {
            return http_respond(conn, 403, "text/html", page("no", "<p>403 role</p>"));
        }
        return http_ok(conn, page("closed", "<p>closed</p>"));
    }
    if (str_eq(path, "/open") == 1) {
        if (auth_may(who, "orders.read") == 0) {
            return http_respond(conn, 403, "text/html", page("no", "<p>403 role</p>"));
        }
        return http_ok(conn, page("open", "<p>open</p>"));
    }
    if (str_eq(path, "/") == 1) { return http_ok(conn, home(who, sid)); }
    return http_not_found(conn);
}

int serve(int conn) {
    http_set_timeout(conn, 5);
    str request = http_read_request(conn);
    if (str_len(request) == 0) { http_request_timeout(conn); http_close(conn); return 1; }
    int lock = 0 - 1;
    if (writes_data(request) == 1) { lock = lock_exclusive("data/.lock"); }
    else { lock = lock_shared("data/.lock"); }
    auth_load();
    handle(conn, request);
    unlock(lock);
    http_close(conn);
    return 1;
}

int main() {
    auth_grant("manager", "*");
    auth_grant("clerk", "orders.read");
    seed();
    int fd = http_listen(SVC_PORT);
    if (fd < 0) { eprint("could not bind"); return 1; }
    http_ignore_broken_pipes();
    print("ready");
    while (1 == 1) {
        http_reap_finished();
        int conn = http_accept(fd);
        if (conn < 0) { continue; }
        int pid = http_fork();
        if (pid == 0) { http_close(fd); serve(conn); http_exit(0); }
        http_close(conn);
        if (pid < 0) { serve(conn); }
    }
    return 0;
}
'''

# ── The runner under test ────────────────────────────────────────────────

RUNNER = '''
import io   from std;
import str  from std;
import mem  from std;
import os   from std;
import time from std;
import jobs from std;

int bump_flaky() {
    int seen = 0;
    if (file_exists("data/flaky.count") == 1) {
        seen = str_to_int(str_trim(file_read("data/flaky.count")));
        if (had_error() == 1) { clear_error(); seen = 0; }
    }
    seen = seen + 1;
    file_write("data/flaky.count", int_to_str(seen));
    return seen;
}

int do_job(str name) {
    if (str_eq(name, "heartbeat") == 1) { return 1; }
    if (str_eq(name, "flaky") == 1) {
        if (bump_flaky() < 3) { return 0; }
        return 1;
    }
    if (str_eq(name, "doomed") == 1) { return 0; }
    return 0;
}

int main() {
    int t0 = now();
    jobs_every("heartbeat", 1, 3, 1, t0);
    jobs_every("flaky", 1, 3, 1, t0);
    jobs_every("doomed", 1, 3, 1, t0);

    str tag = env("JOBS_TAG");
    int lock = jobs_runner_lock();
    if (lock < 0) { print(tag + " refused to start: another runner holds the lock"); return 0; }
    print(tag + " runner started");

    int seconds = 8;
    str asked = env("JOBS_RUN_SECONDS");
    if (str_len(asked) > 0) {
        seconds = str_to_int(asked);
        if (had_error() == 1) { clear_error(); seconds = 8; }
    }
    while (now() - t0 < seconds) {
        int when = now();
        str name = jobs_claim(when, 30);
        if (str_len(name) == 0) { jobs_sleep_ms(100); continue; }
        if (do_job(name) == 1) {
            jobs_done(name, now());
            print(tag + " " + int_to_str(now()) + " " + name + " ok");
        } else {
            int again = jobs_failed(name, "the body said no", now());
            if (again == 1) { print(tag + " " + int_to_str(now()) + " " + name + " failed-retry"); }
            else { print(tag + " " + int_to_str(now()) + " " + name + " failed-gaveup"); }
        }
    }
    jobs_runner_unlock(lock);
    jobs_load();
    print_raw(jobs_report());
    return 0;
}
'''

# A second process that claims a job and holds it without finishing, so the
# lease can be asked about from outside.
CLAIMER = '''
import io   from std;
import str  from std;
import os   from std;
import time from std;
import jobs from std;

int main() {
    str tag = env("JOBS_TAG");
    jobs_every("only-job", 60, 5, 1, now());
    str got = jobs_claim(now(), 3);
    if (str_len(got) == 0) { print(tag + " claimed nothing"); }
    else { print(tag + " claimed " + got); }
    str held = env("JOBS_HOLD_MS");
    if (str_len(held) > 0) {
        int ms = str_to_int(held);
        if (had_error() == 1) { clear_error(); ms = 0; }
        jobs_sleep_ms(ms);
    }
    return 0;
}
'''


class Service:
    """The demo service, and the three-line HTTP client the cases need."""

    def __init__(self, binary, cwd, port):
        self.port = port
        self.log = open(os.path.join(cwd, "svc.log"), "w+")
        self.proc = subprocess.Popen([binary], cwd=cwd, stdout=self.log,
                                     stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                self.get("/health")
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("the service never came up")

    def request(self, method, path, cookie=None, form=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        body = None
        if cookie:
            headers["Cookie"] = "sid=" + cookie
        if form is not None:
            body = "&".join(f"{k}={v}" for k, v in form.items())
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Content-Length"] = str(len(body))
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        text = r.read().decode("utf-8", "replace")
        out = (r.status, dict(r.getheaders()), text)
        c.close()
        return out

    def get(self, path, cookie=None):
        return self.request("GET", path, cookie=cookie)

    def post(self, path, form=None, cookie=None):
        return self.request("POST", path, cookie=cookie, form=form or {})

    def sign_in(self, who, password):
        status, headers, _ = self.post("/login",
                                       {"username": who, "password": password})
        sid = ""
        m = re.search(r"sid=([0-9a-f]{64})", headers.get("Set-Cookie", ""))
        if m:
            sid = m.group(1)
        return status, headers, sid

    def csrf(self, sid):
        _, _, text = self.get("/", cookie=sid)
        m = re.search(r'value="([0-9a-f]{64})"', text)
        return m.group(1) if m else ""

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.seek(0)
        return self.log.read()


def session_cases(d):
    print()
    print("── sessions ─" + "─" * 48)

    port = free_port()
    src = write(d, "svc.sta", SERVICE.replace("%PORT%", str(port)))
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    rc, out = build(src, os.path.join(d, "svc"), d)
    ok("the demo service builds against std/session.sta", rc == 0, out[-600:])
    if rc != 0:
        return

    svc = Service(os.path.join(d, "svc"), d, port)
    try:
        # ── No session at all ────────────────────────────────────────
        status, headers, _ = svc.get("/")
        ok("a protected page with no cookie is not served",
           status == 303 and headers.get("Location") == "/login",
           f"{status} {headers}")
        status, _, _ = svc.post("/close")
        ok("a write with no cookie is refused, not redirected",
           status == 403, str(status))

        # ── Signing in ───────────────────────────────────────────────
        status, headers, sid = svc.sign_in("boss", "wrong")
        ok("a wrong password hands out no session",
           status == 401 and sid == "" and "Set-Cookie" not in headers,
           f"{status} {headers}")

        status, headers, sid = svc.sign_in("boss", "letmein")
        ok("the right password hands out a session",
           status == 303 and len(sid) == 64, f"{status} {headers}")
        cookie = headers.get("Set-Cookie", "")
        ok("and the cookie is HttpOnly and SameSite, so script cannot read it"
           " and a third-party page does not send it",
           "HttpOnly" in cookie and "SameSite=Lax" in cookie, cookie)

        # ── Unguessable ──────────────────────────────────────────────
        _, _, second = svc.sign_in("boss", "letmein")
        ok("a session id is 256 bits of hex and never the same twice",
           re.fullmatch(r"[0-9a-f]{64}", sid) is not None and second != sid,
           f"{sid} / {second}")
        made_up = "a" * 64
        status, headers, _ = svc.get("/", cookie=made_up)
        ok("an invented session id of the right shape is still nobody",
           status == 303, str(status))

        # ── Reaching a protected page ────────────────────────────────
        status, _, text = svc.get("/", cookie=sid)
        ok("the cookie reaches the protected page",
           status == 200 and "signed in as boss" in text, f"{status} {text[:200]}")

        # ── CSRF ─────────────────────────────────────────────────────
        csrf = svc.csrf(sid)
        ok("a session carries a form token that is not its cookie",
           len(csrf) == 64 and csrf != sid, f"{csrf} / {sid}")
        status, _, _ = svc.post("/close", {"_csrf": csrf}, cookie=sid)
        ok("a write carrying this session's form token is allowed",
           status == 200, str(status))
        status, _, _ = svc.post("/close", {}, cookie=sid)
        ok("a write carrying NO form token is refused — the case the obvious"
           " string comparison lets through",
           status == 403, str(status))
        status, _, _ = svc.post("/close", {"_csrf": sid}, cookie=sid)
        ok("the cookie value is not accepted as the form token",
           status == 403, str(status))
        status, _, _ = svc.post("/close", {"_csrf": "deadbeef"}, cookie=sid)
        ok("a made-up form token is refused", status == 403, str(status))

        _, _, clerk_sid = svc.sign_in("clerk", "pencil")
        clerk_csrf = svc.csrf(clerk_sid)
        status, _, _ = svc.post("/close", {"_csrf": clerk_csrf}, cookie=sid)
        ok("another live session's form token is refused",
           status == 403, str(status))

        # ── Method before token ──────────────────────────────────────
        status, _, _ = svc.get("/close?_csrf=" + csrf, cookie=sid)
        ok("a write path reached with GET is 405, not 403 — the method is"
           " checked before the token, so changing it gets past neither",
           status == 405, str(status))
        status, _, _ = svc.get("/close", cookie=sid)
        ok("and GET with no token at all is still 405, not 403",
           status == 405, str(status))

        # ── Roles ────────────────────────────────────────────────────
        status, _, _ = svc.get("/open", cookie=clerk_sid)
        ok("a clerk may read, which is what the role was granted",
           status == 200, str(status))
        status, _, _ = svc.post("/close", {"_csrf": clerk_csrf}, cookie=clerk_sid)
        ok("a clerk with a perfectly good form token still may not close —"
           " the permission is a separate question from the token",
           status == 403, str(status))

        # ── Sign-out ─────────────────────────────────────────────────
        status, _, _ = svc.post("/logout", {"_csrf": csrf}, cookie=sid)
        ok("sign-out is accepted", status == 303, str(status))
        status, _, _ = svc.get("/", cookie=sid)
        ok("and the same cookie replayed afterwards is nobody",
           status == 303, str(status))
        status, _, _ = svc.post("/close", {"_csrf": csrf}, cookie=sid)
        ok("including on a write path", status == 403, str(status))

        # ── Expiry ───────────────────────────────────────────────────
        #
        # Forged by rewriting the stored expiry into the past. The row is
        # still there and the token is still right: only the clock has
        # moved. A service that checks "is there a row" and not "is it
        # still live" passes everything above and fails here.
        _, _, live = svc.sign_in("boss", "letmein")
        status, _, _ = svc.get("/", cookie=live)
        ok("a fresh session reaches the page before it is aged",
           status == 200, str(status))
        path = os.path.join(d, "data", "auth_sessions.tsv")
        rows = open(path).read().splitlines()
        out_rows = []
        for line in rows:
            parts = line.split("\t")
            if parts[0] == live:
                parts[2] = "1000"          # expires_at, long ago
            out_rows.append("\t".join(parts))
        open(path, "w").write("\n".join(out_rows) + "\n")
        status, _, _ = svc.get("/", cookie=live)
        ok("a session whose expiry has passed is refused even though the row"
           " is still in the table",
           status == 303, str(status))

        # ── Throttling ───────────────────────────────────────────────
        codes = []
        for _ in range(6):
            s, _, _ = svc.sign_in("clerk", "nope")
            codes.append(s)
        ok("guessing is answered 401 and then throttled to 429",
           codes[0] == 401 and codes[-1] == 429, str(codes))
        status, _, locked_sid = svc.sign_in("clerk", "pencil")
        ok("and while it is throttled even the RIGHT password is refused,"
           " so a guesser cannot tell a near miss from a hit",
           status == 429 and locked_sid == "", f"{status} {locked_sid}")

        # ── The password itself ──────────────────────────────────────
        stored = ""
        for name in os.listdir(os.path.join(d, "data")):
            try:
                stored += open(os.path.join(d, "data", name)).read()
            except (OSError, UnicodeDecodeError):
                pass
        ok("no password appears in anything the service stored",
           "letmein" not in stored and "pencil" not in stored,
           stored[:300])
        ok("and a password hash is a crypt hash, salted per account",
           stored.count("$6$") >= 2, stored[:300])
    finally:
        log = svc.stop()
    ok("the service logged no password and left no unchecked error",
       "letmein" not in log and "pencil" not in log
       and "nobody checked" not in log, log[-500:])


def job_cases(d):
    print()
    print("── scheduled jobs ─" + "─" * 43)

    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    rsrc = write(d, "runner.sta", RUNNER)
    rc, out = build(rsrc, os.path.join(d, "runner"), d)
    ok("the demo runner builds against std/jobs.sta", rc == 0, out[-600:])
    if rc != 0:
        return
    csrc = write(d, "claimer.sta", CLAIMER)
    rc2, out2 = build(csrc, os.path.join(d, "claimer"), d)
    ok("the second claimer builds too", rc2 == 0, out2[-600:])
    if rc2 != 0:
        return

    env = dict(os.environ, JOBS_TAG="A", JOBS_RUN_SECONDS="8")
    r = subprocess.run([os.path.join(d, "runner")], cwd=d, env=env,
                       capture_output=True, text=True, timeout=120)
    text = r.stdout + r.stderr
    lines = [l for l in text.splitlines() if l.strip()]

    ok("a job with a working body runs and is recorded as ok",
       any(l.endswith("heartbeat ok") for l in lines), text[-500:])

    doomed = [l for l in lines if " doomed " in l]
    ok("a job with a failing body is tried again rather than forgotten",
       sum(1 for l in doomed if l.endswith("failed-retry")) >= 2, str(doomed))
    ok("and it gives up rather than retrying for ever",
       any(l.endswith("failed-gaveup") for l in doomed), str(doomed))
    ok("it gives up after exactly the stated number of tries",
       len(doomed) == 3, str(doomed))

    # The gap doubles: 1s then 2s. Three attempts therefore span at least
    # three seconds. A backoff that stopped growing would span two.
    stamps = [int(l.split()[1]) for l in doomed]
    ok("the gap between tries grows — the three tries span 3s, not 2s",
       len(stamps) == 3 and stamps[2] - stamps[0] >= 3,
       f"stamps={stamps} spans={stamps[-1] - stamps[0] if stamps else '?'}")

    ok("a job that fails and then works is scheduled normally again",
       any(l.endswith("flaky ok") for l in lines)
       and sum(1 for l in lines if l.endswith("flaky failed-retry")) == 2,
       text[-500:])

    report = [l for l in lines if l.startswith(("doomed ", "flaky ", "heartbeat "))]
    ok("the table says which job gave up and why",
       any(l.startswith("doomed ") and "given_up=1" in l
           and "detail=the body said no" in l for l in report), str(report))

    # ── Two runners ──────────────────────────────────────────────────
    for f in os.listdir(os.path.join(d, "data")):
        os.remove(os.path.join(d, "data", f))
    first = subprocess.Popen([os.path.join(d, "runner")], cwd=d,
                             env=dict(os.environ, JOBS_TAG="A",
                                      JOBS_RUN_SECONDS="4"),
                             stdout=subprocess.PIPE, text=True)
    time.sleep(0.5)
    second = subprocess.run([os.path.join(d, "runner")], cwd=d,
                            env=dict(os.environ, JOBS_TAG="B",
                                     JOBS_RUN_SECONDS="4"),
                            capture_output=True, text=True, timeout=60)
    first_out = first.communicate(timeout=60)[0]
    ok("a second runner started by accident refuses to start",
       "refused to start" in second.stdout, second.stdout[:300])
    ok("and the first one carried on",
       "A runner started" in first_out, first_out[:200])

    # ── The lease, with the runner lock deliberately out of the way ──
    #
    # Two processes that each took their own runner lock would still both
    # claim, so the lease is what actually stops a job running twice. Both
    # of these hold the runner lock in turn — the first exits before the
    # second starts — so only the lease is under test.
    for f in os.listdir(os.path.join(d, "data")):
        os.remove(os.path.join(d, "data", f))
    holder = subprocess.Popen([os.path.join(d, "claimer")], cwd=d,
                              env=dict(os.environ, JOBS_TAG="first",
                                       JOBS_HOLD_MS="1500"),
                              stdout=subprocess.PIPE, text=True)
    time.sleep(0.5)
    other = subprocess.run([os.path.join(d, "claimer")], cwd=d,
                           env=dict(os.environ, JOBS_TAG="second",
                                    JOBS_HOLD_MS="0"),
                           capture_output=True, text=True, timeout=60)
    held = holder.communicate(timeout=60)[0]
    ok("the first claimer gets the job", "first claimed only-job" in held, held)
    ok("a second claimer is given NOTHING while the lease is live — this is"
       " what stops two runners running one job at the same moment",
       "second claimed nothing" in other.stdout, other.stdout)

    time.sleep(3.2)
    third = subprocess.run([os.path.join(d, "claimer")], cwd=d,
                           env=dict(os.environ, JOBS_TAG="third",
                                    JOBS_HOLD_MS="0"),
                           capture_output=True, text=True, timeout=60)
    ok("once the lease has run out the job is offered again — which is why"
       " this is at-least-once and a job body must be safe to repeat",
       "third claimed only-job" in third.stdout, third.stdout)


def unit_cases():
    print()
    print("── the verify blocks next to the code ─" + "─" * 23)
    with tempfile.TemporaryDirectory() as d:
        good, out = verify_blocks("std/session.sta", os.path.join(d, "s"))
        ok("every verify block in std/session.sta passes", good, out[-800:])
        m = re.search(r"(\d+) block\(s\), (\d+) assertion\(s\), (\d+) failed", out)
        ok("and there are real assertions in them, not an empty run",
           m is not None and int(m.group(2)) > 50 and int(m.group(3)) == 0,
           out[-300:])
        good, out = verify_blocks("std/jobs.sta", os.path.join(d, "j"))
        ok("every verify block in std/jobs.sta passes", good, out[-800:])


def main():
    print()
    print("── two components, and the properties that make them worth"
          " reusing ──")
    unit_cases()
    with tempfile.TemporaryDirectory() as d:
        session_cases(d)
    with tempfile.TemporaryDirectory() as d:
        job_cases(d)

    print()
    print("=" * 62)
    print(f"  {passed} ok, {len(failures)} failed")
    print("=" * 62)
    if failures:
        for f in failures:
            print("  - " + f[:300])
        print("  A component property is broken. FAIL")
        return 1
    print("  Sessions and jobs still keep their promises. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
