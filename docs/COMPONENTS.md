# Two components: sessions and scheduled jobs

`std/session.sta` and `std/jobs.sta`. These are the two things every back
office needs, that nobody should write twice, and that are easy to get
subtly wrong.

Both were lifted out of `apps/orders`, which already had a working sign-in —
a throttle on password guessing, a CSRF token, a session that expires, a
write lock — and a hand-rolled sweep inside its accept loop. All of it lived
in the application, so the next service built here would have had to get the
same things right again from nothing. The parts that are not about orders
are in `std/` now.

`apps/orders` has **not** been changed to use them. That is a separate piece
of work with its own risk, and it is listed at the end.

---

## What you need to know before you start

**Fixed file paths.** `load` and `save` take a string literal, not a
variable, so neither module can be told where to keep its data. The paths
are relative and the program must be started from the directory that owns
its `data/`, which is how `apps/orders` already works:

```text
data/auth_users.tsv       accounts and their password hashes
data/auth_sessions.tsv    live sessions
data/auth_attempts.tsv    failed sign-ins, for the throttle
data/jobs.tsv             the jobs and their state
data/jobs.lock            held for the moment a claim or a result is written
data/jobs.runner          held for as long as a runner is running
data/.lock                the service's own write lock, if it has one
```

`data/` must exist before the first save. The files need not.

**Table names.** The tables are `AuthUser`, `AuthSession`, `AuthAttempt`,
`AuthGrant` and `ScheduledJob`. A table name is global in Strata, so an
application that already declares its own `User` or `Session` can still
import these.

---

# std/session.sta

## What it does

| | |
|---|---|
| `auth_load()` | read all three tables. Call it at the top of a request, inside the lock |
| `auth_save_users()` / `auth_save_sessions()` / `auth_save_attempts()` / `auth_save_all()` | write them. Each returns whether the write actually happened |
| `auth_add_user(who, secret, role)` | a new account; the id, or 0 if the name is taken or either field is empty |
| `auth_set_password(id, secret)` | change a password |
| `auth_user_id_of(who)`, `auth_username_of(id)`, `auth_role_of(id)` | look an account up |
| `auth_sign_in(who, secret, from_where, when)` | the cookie token, or `""` |
| `auth_start_session(id, when)` | a session for an account that has already proved who it is |
| `auth_user_of_token(token, when)` | whose session this is, or 0 |
| `auth_user_of_request(request, when)` | the same question asked of a raw HTTP request |
| `auth_session_remaining(token, when)` | seconds left, or 0 |
| `auth_sign_out(token)` | remove this session |
| `auth_sign_out_everywhere(id)` | remove all of this account's sessions |
| `auth_prune_sessions(when)` / `auth_prune_attempts(when)` | housekeeping; both return how many rows went |
| `auth_csrf_for(token)` | the form token this session's pages must carry |
| `auth_csrf_ok(token, supplied)` | whether a form carried the right one |
| `auth_cookie_header(token)` / `auth_cookie_header_secure(token)` / `auth_clear_cookie_header()` | ready-made `Set-Cookie` lines |
| `auth_grant(role, action)` | let a role do a named thing; `"*"` means everything |
| `auth_may(id, action)` / `auth_role_may(role, action)` / `auth_session_may(token, action, when)` | ask |
| `auth_locked_for(who, from_where, when)` | seconds left on a throttle, or 0 |

The dials are `AUTH_SESSION_SECONDS` (8 hours), `AUTH_LOCKOUT_AFTER` (5) and
`AUTH_LOCKOUT_SECONDS` (300).

## A worked example

A service with two accounts, one page that needs a session, one page that
needs a permission, and one write path. This is the whole of it.

```text
import io      from std;
import str     from std;
import mem     from std;
import http    from std;
import time    from std;
import session from std;

int seed() {
    auth_load();
    if (auth_user_id_of("boss") == 0) {
        auth_add_user("boss", "letmein", "manager");
        auth_add_user("clerk", "pencil", "clerk");
        auth_save_all();
    }
    return 1;
}

// Which address changes stored data. ONE function, asked by both the lock
// and the CSRF check, so the two cannot disagree about what a request is.
int is_write_path(str path) {
    if (str_eq(path, "/close") == 1) { return 1; }
    if (str_eq(path, "/logout") == 1) { return 1; }
    return 0;
}

int do_login(int conn, str body, int when) {
    str who = http_form_value(body, "username");
    str where_from = http_peer_ip(conn);
    str token = auth_sign_in(who, http_form_value(body, "password"),
                             where_from, when);
    auth_save_users();
    auth_save_attempts();
    if (str_len(token) == 0) {
        // The person is told the same thing either way; only the status
        // differs, so a watchdog can see a throttle happening.
        if (auth_locked_for(who, where_from, when) > 0) {
            return http_respond(conn, 429, "text/html", "<p>too many</p>");
        }
        return http_respond(conn, 401, "text/html", "<p>no</p>");
    }
    // A session that was not stored is not a session. Saying otherwise
    // signs somebody in who will be signed out by the next request.
    if (auth_save_sessions() == 0) {
        return http_respond(conn, 503, "text/html", "<p>not stored</p>");
    }
    return http_redirect_with(conn, "/", auth_cookie_header(token));
}

int handle(int conn, str request) {
    int when   = now();
    str method = http_method(request);
    str path   = http_path(request);
    str sid    = http_cookie(request, "sid");
    int who    = auth_user_of_token(sid, when);

    if (str_eq(path, "/login") == 1) {
        if (str_eq(method, "POST") == 1) { return do_login(conn, http_body(request), when); }
        return http_ok(conn, "<form method=post action=/login>...</form>");
    }

    if (who == 0) {
        if (str_eq(method, "GET") == 1) { return http_redirect(conn, "/login"); }
        return http_forbidden(conn);
    }

    // The METHOD is refused first, before the token is looked at. Checking
    // the token first means a write reached with GET is answered "your
    // token is missing", which is a sentence about the wrong problem, and
    // the route below would still have run.
    if (is_write_path(path) == 1) {
        if (str_eq(method, "POST") == 0) {
            return http_respond(conn, 405, "text/html", "<p>405</p>");
        }
        if (auth_csrf_ok(sid, http_form_value(http_body(request), "_csrf")) == 0) {
            return http_respond(conn, 403, "text/html", "<p>403</p>");
        }
    }

    if (str_eq(path, "/close") == 1) {
        // A good token is not permission. The token says the request came
        // from a page we rendered; the role says this person may do it.
        if (auth_may(who, "orders.close") == 0) {
            return http_respond(conn, 403, "text/html", "<p>403</p>");
        }
        return http_ok(conn, "<p>closed</p>");
    }
    return http_not_found(conn);
}

// The request is read BEFORE the lock is taken, so a slow client delays
// nobody but itself. The tables are loaded INSIDE it, because a child
// forked ten minutes ago inherited a copy that is now wrong. The lock is
// taken from the same answer the CSRF check uses, so the two cannot
// disagree about whether a request is a write.
int serve(int conn) {
    http_set_timeout(conn, 5);
    str request = http_read_request(conn);
    if (str_len(request) == 0) { http_request_timeout(conn); http_close(conn); return 1; }
    int lock = 0 - 1;
    if (is_write_path(http_path(request)) == 1) { lock = lock_exclusive("data/.lock"); }
    else { lock = lock_shared("data/.lock"); }
    auth_load();
    handle(conn, request);
    unlock(lock);
    http_close(conn);
    return 1;
}

int main() {
    // Grants are code, not data — see "what it does not do" below.
    auth_grant("manager", "*");
    auth_grant("clerk", "orders.read");
    seed();
    int fd = http_listen(8080);
    if (fd < 0) { eprint("could not bind port 8080"); return 1; }
    http_ignore_broken_pipes();
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
```

Put the form token in every form on a page:

```text
sb_append(&sb, "<input type=hidden name=_csrf value=\"");
sb_append(&sb, auth_csrf_for(sid));
sb_append(&sb, "\">");
```

## Where a session id's randomness comes from, honestly

`auth_fresh_token()` calls `new_session_token()` in `std/auth.sta`, which
calls `random_hex(32)`, which **opens `/dev/urandom` and reads 32 bytes**.
That is the kernel's CSPRNG. It is the right source: not `rand()`, not the
clock, not a counter, and not a hash of the username. 32 bytes is 256 bits,
written as 64 hex characters.

Honest qualifications:

- **It is only as good as `/dev/urandom` on the machine.** On Linux and
  macOS that is a well-reviewed generator seeded from hardware entropy, and
  guessing a token is not an attack anybody mounts. In a container built
  without `/dev`, or in a process that has run out of file descriptors, the
  open fails.
- **A failure is refused, not papered over.** `random_hex` answers `""` when
  it cannot read. `auth_fresh_token` checks the shape of what came back and,
  if it is not 64 hex characters, calls `fail()` and returns `""` — and
  `auth_start_session` then creates no session. This matters: a session row
  with an empty token would be matched by every request that sends no
  cookie. The program exits 65 rather than carrying on, unless the caller
  handles the error.
- **The file is readable by whoever can read the file.** The tokens are
  stored in `data/auth_sessions.tsv` in the clear. Anyone who can read that
  file is every session in it. Hashing the stored side would fix that and is
  not done — it is in the list below.
- **It is a bearer token.** Whoever holds it IS the session, which is what
  bearer means. There is no binding to an IP address or a user agent.

## What `std/session.sta` does NOT do

Each of these is an attack it does not stop.

- **No TLS.** `std/http.sta` serves plain HTTP. On an untrusted network
  anybody on the path reads the cookie and is then that person. Put a TLS
  terminator in front and use `auth_cookie_header_secure`. This is the
  biggest one.
- **Stored session tokens are not hashed.** Read access to
  `data/auth_sessions.tsv` — a backup, a log shipper, a path traversal — is
  every live session. Hashing the stored copy and looking up by the hash
  would fix it and is maybe twenty lines.
- **No binding to a device or address.** A cookie copied to another machine
  works there. Nothing is checked beyond the token and the clock.
- **No protection against one source guessing across many usernames.** The
  throttle counts against the pair (account, source), deliberately — so that
  guessing at somebody else's username cannot lock them out. The cost is
  that one attacker can try five passwords against each of a thousand
  accounts without ever being throttled. That needs a rate limit, which this
  is not.
- **No CSRF token on the sign-in form itself.** Login CSRF — where an
  attacker makes your browser sign in as *their* account so your next
  actions are recorded against it — is not stopped.
- **Nothing stops a session being used from two places at once**, and there
  is no "sign out my other devices" beyond `auth_sign_out_everywhere`, which
  the application must decide to call.
- **The password hash comparison is not constant-time**, but it compares
  hashes rather than secrets, so there is nothing useful to learn from it.
  The *username* lookup is time-equalised: an unknown name still pays for a
  full SHA-512 crypt, so the list of real accounts cannot be read with a
  stopwatch.
- **Grants are code, not data.** `auth_grant` writes to a table that is
  never saved, declared before the service starts serving and inherited by
  every forked child. A permission matrix in a file is a permission matrix
  that anybody with any write primitive can edit. The cost is that changing
  who may do what is a deployment.
- **No password policy, no reset flow, no second factor, no account
  lockout an operator can clear, no audit log.**
- **No expiry extension.** A session lasts eight hours from sign-in, whether
  or not it is being used. There is no sliding window.
- **Importing it brings the HTTP server with it**, because `auth_cookie_*`
  and `auth_user_of_request` are about requests. A command-line tool that
  only manages accounts links sockets it never uses.

---

# std/jobs.sta

## What it does

| | |
|---|---|
| `jobs_every(name, minutes, max_tries, first_gap, when)` | declare a job that runs every N minutes |
| `jobs_daily(name, hour, minute, max_tries, first_gap, when)` | declare one that runs at a time of day, UTC |
| `jobs_runner_lock()` / `jobs_runner_unlock(fd)` | take the runner lock, or -1 if another runner has it |
| `jobs_claim(when, lease_seconds)` | the name of a job to run, or `""` |
| `jobs_done(name, when)` | it worked |
| `jobs_failed(name, why, when)` | it did not. 1 if it will try again, 0 if it has given up |
| `jobs_revive(name, when)` | put a job that gave up back in the schedule |
| `jobs_load()` / `jobs_save()` | read and write the table |
| `jobs_report()` | one line per job, for a page or a log |
| `jobs_last_ok(name)`, `jobs_attempts(name)`, `jobs_given_up(name)`, `jobs_next_due(name)`, `jobs_last_detail(name)`, `jobs_due_count(when)` | ask about one job |
| `jobs_sleep_ms(ms)` | for the idle part of the loop |

`jobs_claim`, `jobs_done`, `jobs_failed`, `jobs_every`, `jobs_daily` and
`jobs_revive` each take `data/jobs.lock` themselves and re-read the file
inside it, so you do not have to.

## The body is not in the row

Strata has no function values, so there is nothing to put in a `body`
column. The runner hands you a **name** and you decide what it means:

```text
int do_job(str name) {
    if (str_eq(name, "sweep-sessions") == 1) { return sweep(); }
    if (str_eq(name, "nightly-report") == 1) { return report(); }
    return 0;
}
```

That is less pretty than passing a function and it is honest about the
language. It also means the dispatch is an ordinary function that
`strata test` can exercise without a scheduler.

## A worked example

```text
import io   from std;
import str  from std;
import time from std;
import jobs from std;

// The dispatch, again, so this block stands on its own.
int do_job(str name) {
    if (str_eq(name, "sweep-sessions") == 1) { return 1; }
    if (str_eq(name, "nightly-report") == 1) { return 1; }
    return 0;
}

int main() {
    int t0 = now();
    // A new interval job is due at once; a new daily job is due at its next
    // occurrence. A job already in the file keeps its state and only its
    // schedule is updated, so a restart does not re-run the nightly report.
    jobs_every("sweep-sessions", 5, 3, 10, t0);
    jobs_daily("nightly-report", 2, 30, 3, 60, t0);

    int lock = jobs_runner_lock();
    if (lock < 0) {
        eprint("another runner holds data/jobs.runner; leaving");
        return 0;
    }

    while (1 == 1) {
        str name = jobs_claim(now(), 300);
        if (str_len(name) == 0) { jobs_sleep_ms(1000); continue; }
        if (do_job(name) == 1) {
            jobs_done(name, now());
        } else {
            // Returns 1 when it will try again, 0 once it has given up.
            jobs_failed(name, last_error(), now());
            clear_error();
        }
    }
    jobs_runner_unlock(lock);
    return 0;
}
```

What that prints over eight seconds, with one job that works, one that fails
twice and then works, and one that never works — all three with
`max_tries = 3` and a one-second first gap:

```text
A runner started
A heartbeat ok
A flaky failed-retry
A doomed failed-retry
A flaky failed-retry        (one second later)
A doomed failed-retry
A flaky ok                  (two seconds after that — the gap doubled)
A doomed failed-gaveup
doomed    last_ok=0 attempts=3 given_up=1 detail=the body said no
flaky     last_ok=1 attempts=0 given_up=0 detail=-
heartbeat last_ok=1 attempts=0 given_up=0 detail=-
```

The retry gap is `first_gap`, then double, then double again, capped at
`JOBS_MAX_GAP` (one hour). Capped because doubling without a limit turns a
job that has been failing all weekend into a job that next tries in four
months, and the first thing anybody does after fixing the cause is wonder
why it has not run.

## What the runner actually guarantees about running a job twice

**Never two at once. Possibly twice in total. Bodies must be safe to
repeat.**

Two things hold it, and they are different:

1. **`data/jobs.runner`** is taken with `flock(LOCK_EX | LOCK_NB)` for the
   life of the runner. A second runner cannot take it and **leaves** rather
   than queueing — queueing would mean it starts the moment the first one is
   restarted, and then there are two.
2. **Every claim writes a lease.** `jobs_claim` takes `data/jobs.lock`,
   re-reads the file, picks the oldest job whose `next_due` has passed and
   whose `claimed_until` has run out, writes `claimed_until = now + lease`,
   and saves — all before it returns a name. So even two runners that
   somehow both took a runner lock (different lock paths, a lock file
   deleted underneath them) serialise on the state file and only one is
   given the job.

What that does **not** guarantee:

- **At-most-once is not on offer.** A runner killed between doing the work
  and recording the result leaves a lease that expires; the next runner
  claims the job again and the body runs a second time. Write bodies that
  can be repeated — which is the same discipline every job queue in the
  world asks for.
- **A lease shorter than the job is the one way two bodies run at once.**
  If a job can take ten minutes, do not claim it with a five-minute lease.
  There is no detection for this and no fencing token.
- **It is local.** `flock` is advisory and means nothing between machines
  over NFS. Two runners on two machines sharing a mount will both run
  everything.
- **It is per-`data/` directory.** Two runners started in different working
  directories share nothing and both run everything. The lock is a file, not
  a name in a registry.
- **The clock is the machine's.** A clock stepped backwards makes a lease
  look longer than it is and delays a schedule; a clock stepped forwards
  releases a lease early. Everything is UTC seconds — `std/time.sta` has no
  time zones, so "daily at 02:30" is 02:30 UTC.
- **Nothing runs jobs in parallel.** One runner, one job at a time, in
  order of when they came due. A long job delays every other job.

## What `std/jobs.sta` does NOT do

- **No cron expressions.** Every N minutes, or daily at a time. No weekdays,
  no "last Friday of the month", no sub-minute schedules.
- **No catch-up.** A runner that was down for a day does not run yesterday's
  daily job twice; when it starts, the job is overdue and runs once.
- **No parallelism, no priorities, no queues, no arguments.** A job is a
  name. There is no way to say "run this job for customer 42".
- **No alerting.** A job that gave up sets `given_up = 1` and writes why.
  Something has to look — `jobs_report()` on a `/jobs` page is the cheapest
  version.
- **Giving up is permanent until somebody acts.** `jobs_revive(name, when)`
  puts it back. Nothing does that on its own.
- **A failure message is cut to 200 bytes** before it is stored.
- **A job removed from the program is not removed from the file.** It stays
  in `data/jobs.tsv`, is never claimed because nothing registers it... and
  in fact *is* still claimed, because `jobs_claim` reads the file rather
  than a list of what this program declared. Delete the row, or keep the
  registration.

---

## Running the tests

```bash
strata test std                       # the verify blocks next to the code
python3 test_suite/components_auth_jobs.py
```

The Python suite builds a real service against `std/session.sta` and drives
it over HTTP — sign in, reach a protected page, sign out, find the same
cookie refused — and runs a real job runner for eight seconds to watch a job
fire, a job retry with a growing gap, and a job give up. Every security
property has a case that goes red when the property is removed; three of
them were removed on purpose to check that.

## Not done, and why

- **`apps/orders` has not been moved onto these modules.** It works, it is
  what the journey tests exercise, and its tables are `User`/`Session` while
  these are `AuthUser`/`AuthSession` — so the move needs a migration of its
  stored files, not just an import. It is a clean follow-up and should be
  its own change.
- **Session tokens are stored in the clear.** Hashing the stored side is the
  single highest-value thing left in `std/session.sta`.
- **No `/jobs` page is provided.** `jobs_report()` gives the text; what to
  do with it is the application's.
