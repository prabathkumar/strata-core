#!/usr/bin/env python3
"""The database connectors: std/redis.sta and std/mysql.sta.

WHY THESE CASES

A connector is the place where this language's promise — that a wrong answer
is refused rather than returned — stops being the compiler's job and starts
being the library's. Everything here is a case where a connector could have
handed back something that looks right.

Redis, tested against a live server:

  * **Nothing is ever sent as a line of text.** Redis accepts commands typed
    as words on a line, and a key or value containing a space, a quote or a
    newline then becomes a second command. The server in this file REFUSES
    the inline form and records every command it is sent, so the test can say
    that the client used counted strings for all of them — the Redis-shaped
    version of "parameters, never pasted in".
  * **A value carrying CRLF survives.** Those are the two bytes that end a
    RESP line. If the client framed by searching for them instead of counting,
    this value would come back cut in half.
  * **The client reads exactly one reply.** A buffered read that takes a few
    bytes too many steals the front of the next command's answer, and every
    later reply is then one behind — a cache that returns the previous
    caller's value. The test makes the server answer one command with two
    replies and checks that the second one is still on the socket afterwards.
  * **A value with a zero byte in it is refused.** Strata text is a C string.
    Handing back the part before the zero would look exactly like a shorter
    value that somebody stored on purpose.
  * **An oversized reply is refused, not truncated**, for the same reason
    std/fetch.sta refuses one.
  * **A reply that is not RESP is refused**, rather than read as an empty
    answer, which is what a port pointed at the wrong service sends.
  * **A missing key and an empty value are told apart** by the functions that
    promise to tell them apart, and not by the one that does not.
  * **An error from the server arrives as that error.** INCR on a key holding
    a word must fail with what Redis said, not answer 1.
  * **A wrong password fails without putting the password in the reason.**

MySQL, which could not be tested live:

  There is no MySQL or MariaDB client library on the machine this was written
  on, so the branch of std/mysql.sta that talks to one has never run. Two
  things can still be held in place, and both are here:

  * **The refusal path is real.** A binary built without the client headers
    must still build, must answer mysql_available() = 0, and must refuse every
    call with a reason naming what to install — rather than failing to
    compile, which is what an ordinary `foreign` block would do and the reason
    that module does not use one.
  * **The unbuilt branch is still compiled.** Code inside an #ifdef that
    nothing defines is unverified text that rots silently. The test writes a
    stub mysql.h declaring the public C API, regenerates the C, and compiles
    the MySQL branch against it with the project's own -Werror flags. That
    proves the branch is consistent C that uses the API as declared. It
    proves nothing about the real library's ABI, and that gap is the honest
    size of what is untested here.

Run: python3 test_suite/connectors_database.py
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

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
    with open(p, "w") as f:
        f.write(src)
    return p


def run_src(src, d, name, env=None, mode="run"):
    p = write(d, name, src)
    use = dict(os.environ)
    use.update(env or {})
    if mode == "build":
        out = os.path.join(d, name + ".bin")
        r = subprocess.run([STRATA, "build", p, "-o", out],
                           capture_output=True, text=True, timeout=300, env=use)
        return r.stdout + r.stderr, r.returncode, out
    r = subprocess.run([STRATA, "run", p], capture_output=True, text=True,
                       timeout=300, env=use)
    return r.stdout + r.stderr, r.returncode, None


def transcript(out):
    """The `label=value` lines a probe prints, as a dict."""
    found = {}
    for line in out.splitlines():
        if "=" in line and not line.startswith("["):
            k, _, v = line.partition("=")
            if re.fullmatch(r"[a-z0-9_]+", k):
                found[k] = v
    return found


# ── A Redis server, written from the protocol ────────────────────────────
#
# Deliberately NOT built on the client under test: the framing here was
# written from RESP's own rules, so the two sides check each other. It is
# also stricter than Redis — it refuses the inline command form outright —
# because the point of the exercise is that the client never uses it.

class Store:
    def __init__(self):
        self.kv = {}
        self.lists = {}
        self.ttl = {}
        self.seen = []
        self.password = "s3cret"


def _line(f):
    b = f.readline()
    if not b:
        return None
    if not b.endswith(b"\r\n"):
        raise ValueError("a line that does not end with CRLF")
    return b[:-2]


def _read_command(f, store):
    head = _line(f)
    if head is None:
        return None
    if not head.startswith(b"*"):
        store.seen.append(("INLINE", head))
        raise ValueError("not an array of counted strings")
    args = []
    for _ in range(int(head[1:])):
        h = _line(f)
        if h is None or not h.startswith(b"$"):
            raise ValueError("an argument that is not a counted string")
        n = int(h[1:])
        payload = f.read(n)
        if len(payload) != n:
            raise ValueError("an argument shorter than its count")
        if f.read(2) != b"\r\n":
            raise ValueError("an argument not ended by CRLF")
        args.append(payload)
    store.seen.append(("ARRAY", list(args)))
    return args


def _bulk(v):
    if v is None:
        return b"$-1\r\n"
    if isinstance(v, str):
        v = v.encode()
    return b"$" + str(len(v)).encode() + b"\r\n" + v + b"\r\n"


def _num(n):
    return b":" + str(n).encode() + b"\r\n"


def _handle(args, store):
    cmd, a = args[0].upper(), args[1:]
    if cmd == b"PING":
        return b"+PONG\r\n"
    if cmd == b"AUTH":
        return b"+OK\r\n" if a[0].decode() == store.password \
            else b"-ERR invalid password\r\n"
    if cmd == b"SELECT":
        return b"+OK\r\n"
    if cmd == b"SET":
        store.kv[a[0]] = a[1]
        store.ttl.pop(a[0], None)
        if len(a) >= 4 and a[2].upper() == b"EX":
            store.ttl[a[0]] = int(a[3])
        return b"+OK\r\n"
    if cmd == b"GET":
        return _bulk(store.kv.get(a[0]))
    if cmd == b"DEL":
        n = 0
        for k in a:
            if k in store.kv or k in store.lists:
                n += 1
            store.kv.pop(k, None)
            store.lists.pop(k, None)
            store.ttl.pop(k, None)
        return _num(n)
    if cmd == b"EXISTS":
        return _num(1 if (a[0] in store.kv or a[0] in store.lists) else 0)
    if cmd == b"INCR":
        try:
            v = int(store.kv.get(a[0], b"0")) + 1
        except ValueError:
            return b"-ERR value is not an integer or out of range\r\n"
        store.kv[a[0]] = str(v).encode()
        return _num(v)
    if cmd == b"EXPIRE":
        if a[0] not in store.kv and a[0] not in store.lists:
            return _num(0)
        store.ttl[a[0]] = int(a[1])
        return _num(1)
    if cmd == b"LPUSH":
        q = store.lists.setdefault(a[0], [])
        for v in a[1:]:
            q.insert(0, v)
        return _num(len(q))
    if cmd == b"RPOP":
        q = store.lists.get(a[0]) or []
        if not q:
            return b"$-1\r\n"
        v = q.pop()
        if not q:
            store.lists.pop(a[0], None)
        return _bulk(v)
    if cmd == b"LRANGE":
        q = store.lists.get(a[0]) or []
        hi = int(a[2])
        part = q[int(a[1]):(len(q) + hi if hi < 0 else hi) + 1]
        return b"*" + str(len(part)).encode() + b"\r\n" + b"".join(
            _bulk(v) for v in part)
    # Three fixtures, named so nobody mistakes them for Redis commands.
    if cmd == b"TESTGARBAGE":
        return b"BOOM\r\n"
    if cmd == b"TESTDOUBLE":
        return b"+FIRST\r\n+SECOND\r\n"
    return b"-ERR unknown command '" + args[0] + b"'\r\n"


def _serve(conn, store):
    f = conn.makefile("rb")
    try:
        while True:
            args = _read_command(f, store)
            if args is None:
                break
            conn.sendall(_handle(args, store))
    except Exception:
        try:
            conn.sendall(b"-ERR this server only accepts the array form\r\n")
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def start_server(store):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=_serve, args=(conn, store),
                             daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv, srv.getsockname()[1]


# ── The probes ───────────────────────────────────────────────────────────

REDIS_HAPPY = '''import io    from std;
import str   from std;
import os    from std;
import redis from std;
int main() {
    int fd = redis_open(env("STRATA_REDIS_URL"));
    if (fd < 0) { print("open_failed=" + last_error()); clear_error(); return 1; }
    print("ping=" + str(redis_ping(fd)));
    print("set=" + str(redis_set(fd, "greeting", "hello")));
    print("get=" + redis_get(fd, "greeting"));
    print("missing=[" + redis_get(fd, "nothing-here") + "]");
    print("missing_or=" + redis_get_or(fd, "nothing-here", "default"));
    print("empty_value_set=" + str(redis_set(fd, "blank", "")));
    print("empty_or=[" + redis_get_or(fd, "blank", "default") + "]");
    print("exists_yes=" + str(redis_exists(fd, "greeting")));
    print("exists_no=" + str(redis_exists(fd, "nothing-here")));
    redis_set(fd, "k\\r\\nDEL everything", "line1\\r\\nline2");
    print("weird=" + str_replace(redis_get(fd, "k\\r\\nDEL everything"), "\\r\\n", "|"));
    print("del=" + str(redis_del(fd, "greeting")));
    print("del_again=" + str(redis_del(fd, "greeting")));
    print("incr1=" + str(redis_incr(fd, "hits")));
    print("incr2=" + str(redis_incr(fd, "hits")));
    redis_set(fd, "word", "banana");
    print("incr_bad=" + str(redis_incr(fd, "word")));
    if (had_error() == 1) { print("incr_bad_why=" + last_error()); clear_error(); }
    print("expire=" + str(redis_expire(fd, "word", 60)));
    print("expire_missing=" + str(redis_expire(fd, "no-such-key", 60)));
    print("setex=" + str(redis_set_expiring(fd, "session", "abc", 30)));
    print("push1=" + str(redis_lpush(fd, "q", "first")));
    print("push2=" + str(redis_lpush(fd, "q", "second")));
    print("pop1=" + redis_rpop(fd, "q"));
    print("pop2=" + redis_rpop(fd, "q"));
    print("pop_empty=[" + redis_rpop(fd, "q") + "]");
    redis_lpush(fd, "q2", "a");
    redis_lpush(fd, "q2", "b");
    str range = redis_call(fd, ["LRANGE", "q2", "0", "-1"]);
    print("range_count=" + str(resp_count(range)));
    print("range0=" + resp_value(resp_at(range, 0)));
    print("range1=" + resp_value(resp_at(range, 1)));
    redis_close(fd);
    return 0;
}'''

REDIS_REFUSALS = '''import io    from std;
import str   from std;
import os    from std;
import redis from std;
int main() {
    int fd = redis_open(env("STRATA_REDIS_URL"));
    if (fd < 0) { print("open_failed=" + last_error()); clear_error(); return 1; }
    print("nul_len=" + str(str_len(redis_get(fd, "has_nul"))));
    if (had_error() == 1) { print("nul_why=" + last_error()); clear_error(); }
    redis_close(fd);

    fd = redis_open(env("STRATA_REDIS_URL"));
    print("huge_len=" + str(str_len(redis_get(fd, "huge"))));
    if (had_error() == 1) { print("huge_why=" + last_error()); clear_error(); }
    redis_close(fd);

    fd = redis_open(env("STRATA_REDIS_URL"));
    redis_call(fd, ["TESTGARBAGE"]);
    if (had_error() == 1) { print("garbage_why=" + last_error()); clear_error(); }
    redis_close(fd);

    // One command, two replies. A client that read greedily would have both
    // in hand and would answer the next command from the first of them.
    fd = redis_open(env("STRATA_REDIS_URL"));
    print("double_first=" + resp_value(redis_call(fd, ["TESTDOUBLE"])));
    print("stale_ping=" + str(redis_ping(fd)));
    clear_error();
    redis_close(fd);

    int bad = redis_open(env("STRATA_REDIS_BAD_URL"));
    print("bad_fd=" + str(bad));
    if (had_error() == 1) {
        print("bad_why=" + last_error());
        print("password_leaked=" + str(str_index_of(last_error(), "hunter2") >= 0));
        clear_error();
    }
    return 0;
}'''

MYSQL_PROBE = '''import io    from std;
import str   from std;
import mysql from std;
int main() {
    print("available=" + str(mysql_available()));
    print("open=" + str(mysql_open("mysql://app:pw@db:3306/sales")));
    if (had_error() == 1) { print("open_why=" + last_error()); clear_error(); }
    print("exec=" + str(mysql_exec(0, "DELETE FROM orders")));
    if (had_error() == 1) { clear_error(); }
    print("query=" + str(mysql_query(0, "SELECT 1")));
    if (had_error() == 1) { clear_error(); }
    print("not_a_url=" + str(mysql_open("data/orders.tsv")));
    if (had_error() == 1) { print("not_a_url_why=" + last_error()); clear_error(); }
    print("host=" + mysql_host_of("mysql://app:pw@db.internal:3307/sales"));
    print("port=" + str(mysql_port_of("mysql://app:pw@db.internal:3307/sales")));
    print("schema=" + mysql_database_of("mysql://app:pw@db.internal:3307/sales"));
    print("holes=" + mysql_placeholders(3));
    return 0;
}'''

# Declared the way the public MySQL C API documents it. See the module
# docstring for exactly what compiling against this does and does not prove.
STUB_MYSQL_H = r'''#ifndef STRATA_STUB_MYSQL_H
#define STRATA_STUB_MYSQL_H
#include <stddef.h>
typedef char my_bool;
typedef unsigned long long my_ulonglong;
typedef struct st_mysql MYSQL;
typedef struct st_mysql_stmt MYSQL_STMT;
typedef struct st_mysql_res MYSQL_RES;
enum enum_field_types { MYSQL_TYPE_DECIMAL = 0, MYSQL_TYPE_LONG = 3,
                        MYSQL_TYPE_DOUBLE = 5, MYSQL_TYPE_STRING = 254 };
typedef struct st_mysql_field { char* name; unsigned int type; } MYSQL_FIELD;
typedef struct st_mysql_bind {
    unsigned long* length;
    my_bool* is_null;
    void* buffer;
    my_bool* error;
    unsigned char* row_ptr;
    void (*store_param_func)(void*, struct st_mysql_bind*);
    void (*fetch_result)(struct st_mysql_bind*, MYSQL_FIELD*, unsigned char**);
    void (*skip_result)(struct st_mysql_bind*, MYSQL_FIELD*, unsigned char**);
    unsigned long buffer_length;
    unsigned long offset;
    unsigned long length_value;
    unsigned int param_number;
    unsigned int pack_length;
    enum enum_field_types buffer_type;
    my_bool error_value;
    my_bool is_unsigned;
    my_bool long_data_used;
    my_bool is_null_value;
    void* extension;
} MYSQL_BIND;
#define MYSQL_NO_DATA 100
#define MYSQL_DATA_TRUNCATED 101
MYSQL* mysql_init(MYSQL* mysql);
MYSQL* mysql_real_connect(MYSQL* mysql, const char* host, const char* user,
                          const char* passwd, const char* db, unsigned int port,
                          const char* unix_socket, unsigned long clientflag);
void mysql_close(MYSQL* sock);
const char* mysql_error(MYSQL* mysql);
int mysql_set_character_set(MYSQL* mysql, const char* csname);
unsigned int mysql_num_fields(MYSQL_RES* res);
MYSQL_FIELD* mysql_fetch_fields(MYSQL_RES* res);
void mysql_free_result(MYSQL_RES* result);
MYSQL_STMT* mysql_stmt_init(MYSQL* mysql);
int mysql_stmt_prepare(MYSQL_STMT* stmt, const char* query, unsigned long length);
unsigned long mysql_stmt_param_count(MYSQL_STMT* stmt);
my_bool mysql_stmt_bind_param(MYSQL_STMT* stmt, MYSQL_BIND* bnd);
int mysql_stmt_execute(MYSQL_STMT* stmt);
my_ulonglong mysql_stmt_affected_rows(MYSQL_STMT* stmt);
MYSQL_RES* mysql_stmt_result_metadata(MYSQL_STMT* stmt);
my_bool mysql_stmt_bind_result(MYSQL_STMT* stmt, MYSQL_BIND* bnd);
int mysql_stmt_store_result(MYSQL_STMT* stmt);
my_ulonglong mysql_stmt_num_rows(MYSQL_STMT* stmt);
int mysql_stmt_fetch(MYSQL_STMT* stmt);
int mysql_stmt_fetch_column(MYSQL_STMT* stmt, MYSQL_BIND* bind_arg,
                            unsigned int column, unsigned long offset);
my_bool mysql_stmt_close(MYSQL_STMT* stmt);
const char* mysql_stmt_error(MYSQL_STMT* stmt);
#endif
'''


def verify_blocks_pass(module):
    r = subprocess.run([STRATA, "test", os.path.join(ROOT, "std", module)],
                       capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    m = re.search(r"(\d+) block\(s\), (\d+) assertion\(s\), (\d+) failed", out)
    return out, (m.group(2), m.group(3)) if m else (None, None)


def main():
    print()
    print("── the database connectors ─" + "─" * 38)

    # ── The verify blocks beside the code ───────────────────────────────
    for module in ("redis.sta", "mysql.sta"):
        out, (asserts, failed) = verify_blocks_pass(module)
        ok(f"std/{module}: every verify block passes",
           failed == "0" and asserts is not None and int(asserts) > 0,
           out[-600:])

    store = Store()
    store.kv[b"has_nul"] = b"ab\x00cd"
    store.kv[b"huge"] = b"x" * (9 * 1024 * 1024)
    srv, port = start_server(store)
    good = "redis://:s3cret@127.0.0.1:%d/0" % port
    bad = "redis://:hunter2@127.0.0.1:%d/0" % port

    with tempfile.TemporaryDirectory() as d:
        # ── Redis, against a live server ────────────────────────────────
        out, rc, _ = run_src(REDIS_HAPPY, d, "happy.sta",
                             {"STRATA_REDIS_URL": good})
        t = transcript(out)
        ok("a connection is made from a URL, password and all",
           rc == 0 and "open_failed" not in t and t.get("ping") == "1",
           out[-600:])
        ok("a value set is the value read back",
           t.get("set") == "1" and t.get("get") == "hello", str(t))
        ok("a key and a value carrying CRLF stay one key and one value",
           t.get("weird") == "line1|line2", str(t))
        ok("a missing key is empty, and only the function that promises to "
           "tell them apart does",
           t.get("missing") == "[]" and t.get("missing_or") == "default"
           and t.get("empty_or") == "[]", str(t))
        ok("exists answers the question get cannot",
           t.get("exists_yes") == "1" and t.get("exists_no") == "0", str(t))
        ok("a delete says how many keys there were to delete",
           t.get("del") == "1" and t.get("del_again") == "0", str(t))
        ok("a counter counts",
           t.get("incr1") == "1" and t.get("incr2") == "2", str(t))
        ok("INCR on a key holding a word fails with what the server said",
           t.get("incr_bad") == "-1"
           and "not an integer" in t.get("incr_bad_why", ""), str(t))
        ok("an expiry on a key that is not there is 0, not success",
           t.get("expire") == "1" and t.get("expire_missing") == "0", str(t))
        ok("a value and its expiry are set in one command",
           t.get("setex") == "1" and store.ttl.get(b"session") == 30, str(t))
        ok("a queue runs oldest-first, and an empty one is empty",
           t.get("push1") == "1" and t.get("push2") == "2"
           and t.get("pop1") == "first" and t.get("pop2") == "second"
           and t.get("pop_empty") == "[]", str(t))
        ok("a list reply comes apart element by element",
           t.get("range_count") == "2" and t.get("range0") == "b"
           and t.get("range1") == "a", str(t))

        # The whole point of the array form, checked from the server's side.
        inline = [s for s in store.seen if s[0] == "INLINE"]
        ok("every command the server saw was counted strings, never a line "
           "of text",
           len(store.seen) > 20 and not inline,
           f"{len(inline)} inline command(s): {inline[:3]}")
        sneaky = [s for s in store.seen
                  if s[0] == "ARRAY" and len(s[1]) > 1
                  and b"\r\n" in s[1][1]]
        ok("and the key with CRLF in it arrived as one argument, not two",
           any(a[1][1] == b"k\r\nDEL everything" for a in sneaky), str(sneaky[:2]))

        # ── Redis, the refusals ─────────────────────────────────────────
        out, rc, _ = run_src(REDIS_REFUSALS, d, "refuse.sta",
                             {"STRATA_REDIS_URL": good,
                              "STRATA_REDIS_BAD_URL": bad})
        t = transcript(out)
        ok("a value with a zero byte in it is refused, not handed back short",
           t.get("nul_len") == "0" and "zero byte" in t.get("nul_why", ""),
           out[-600:])
        ok("a reply larger than the cap is refused, not truncated",
           t.get("huge_len") == "0"
           and "larger than" in t.get("huge_why", ""), str(t))
        ok("a reply that is not RESP at all is refused",
           "does not begin with" in t.get("garbage_why", ""), str(t))
        ok("exactly one reply is read, and the next one is still on the socket",
           t.get("double_first") == "FIRST" and t.get("stale_ping") == "0",
           str(t))
        ok("a wrong password fails, and the password is not in the reason",
           t.get("bad_fd") == "-1" and t.get("password_leaked") == "0"
           and "password" in t.get("bad_why", ""), str(t))

        # ── MySQL: the refusal path, which is the one that exists here ──
        out, rc, _ = run_src(MYSQL_PROBE, d, "my.sta")
        t = transcript(out)
        built_with_client = t.get("available") == "1"
        ok("a program importing std/mysql.sta builds and runs either way",
           rc == 0, out[-600:])
        ok("a connection setting comes apart before any library is consulted",
           t.get("host") == "db.internal" and t.get("port") == "3307"
           and t.get("schema") == "sales" and t.get("holes") == "?, ?, ?",
           str(t))
        ok("a path that is not a database URL is refused as that, not as a "
           "missing library",
           t.get("not_a_url") == "-1" and "mysql://" in t.get("not_a_url_why", ""),
           str(t))
        if built_with_client:
            print("  note  a MySQL client library IS installed here; the "
                  "refusal cases below do not apply")
        else:
            ok("with no client library every door refuses rather than crashing",
               t.get("open") == "-1" and t.get("exec") == "-1"
               and t.get("query") == "-1", str(t))
            ok("and the refusal names what to install",
               "libmariadb-dev" in t.get("open_why", ""), str(t))

        # ── The MySQL branch nothing here compiles, compiled ─────────────
        cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
        if not cc:
            print("  note  no C compiler found; the MySQL branch was not "
                  "syntax-checked")
        else:
            stub = os.path.join(d, "stub")
            os.makedirs(stub, exist_ok=True)
            write(stub, "mysql.h", STUB_MYSQL_H)
            src = write(d, "gen.sta", MYSQL_PROBE)
            r = subprocess.run([STRATA, "build", src, "-o",
                                os.path.join(d, "gen.bin")],
                               capture_output=True, text=True, timeout=300)
            generated = os.path.join(d, "gen.c")
            ok("the C for a program importing std/mysql.sta is generated",
               r.returncode == 0 and os.path.exists(generated),
               (r.stdout + r.stderr)[-500:])
            if os.path.exists(generated):
                r2 = subprocess.run(
                    [cc, "-fsyntax-only", "-I", stub,
                     "-Wno-implicit-function-declaration",
                     "-Werror=int-conversion",
                     "-Werror=incompatible-pointer-types",
                     "-Werror=return-type", "-D_GNU_SOURCE", generated],
                    capture_output=True, text=True, timeout=300)
                ok("and its MySQL branch compiles against the declared C API",
                   r2.returncode == 0, (r2.stdout + r2.stderr)[-1500:])

    try:
        srv.close()
    except Exception:
        pass

    print()
    print("=" * 62)
    print(f"  {passed} ok, {len(failures)} failed")
    print("=" * 62)
    if failures:
        for f in failures:
            print("  - " + f[:400])
        print("  The database connectors are not sound. FAIL")
        return 1
    print("  Both connectors behave the way their modules promise. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
