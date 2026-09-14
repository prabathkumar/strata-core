#!/usr/bin/env python3
"""Journey C — the service meets more than one person.

Two clients at once, a slow client, a client that walks away, a malformed
request, ten writes arriving together, a restart with live data, and a list
long enough to hurt — with the numbers printed rather than claimed.

What it found on the way in:

  - The accept loop served one connection at a time. A client that opened a
    socket and said nothing held every other client for as long as it liked.
  - There was no timeout, so "as long as it liked" meant forever.
  - A client that disconnected mid-response raised SIGPIPE and the default
    action for SIGPIPE is to terminate the process. One abandoned page load
    took the service down.
  - A truncated request came back as whatever bytes had arrived, so a
    half-sent request looked like a real one with a strange path.
  - Once connections were served in child processes, two orders created at
    the same moment each wrote a whole table from their own copy of it. Run
    with the lock removed, this journey does not merely lose a row: ten
    concurrent creates against a thousand-row table leave 856 rows, hundreds
    of them all-zero, because two processes were writing the same file. That
    is what `lock_exclusive` is for, and the thousand rows in that step are
    there so the window is wide enough to prove it.

Usage:  python3 test_suite/journey_survive.py
"""
import os
import shutil
import socket
import statistics
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
NUMBERS = []


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def measure(name, value):
    NUMBERS.append((name, value))
    print(f"  ....  {name}: {value}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Service:
    """The built service, on a port of its own, in a copy of the app."""

    def __init__(self, app, port):
        self.app, self.port, self.proc = app, port, None

    def start(self):
        self.proc = subprocess.Popen([os.path.join(self.app, "build", "orders")],
                                     cwd=self.app, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        for _ in range(100):
            time.sleep(0.1)
            try:
                urllib.request.urlopen(self.url("/login"), timeout=2).read()
                return self
            except urllib.error.HTTPError:
                return self
            except Exception:
                continue
        return self

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
            self.proc = None


def signed_in(svc):
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))
    opener.open(svc.url("/login"), b"username=manager&password=strata", timeout=10)
    return opener


def main():
    tmp = tempfile.mkdtemp(prefix="strata-journey-c-")
    work = os.path.join(tmp, "work")
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
        ".git", "build", "__pycache__", "_to_delete"))
    app = os.path.join(work, "apps", "orders")
    port = free_port()
    svc = Service(app, port)

    try:
        src = os.path.join(app, "src", "main.sta")
        text = open(src).read()
        open(src, "w").write(text.replace("http_listen(8080)", f"http_listen({port})"))
        r = subprocess.run([os.path.join(work, "bin", "strata"), "build"], cwd=app,
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-500:])
            ok("the service builds", False)
            return 1
        # Start from an empty table so the counts below are the journey's own.
        open(os.path.join(app, "data", "orders.tsv"), "w").write(
            "#strata\tOrder\tid:i\tcustomer:s\tregion:s\tamount:f\tstatus:s\n")
        svc.start()
        ok("the service is up", svc.alive())

        print("\n── Two clients at once ──────────────────────────────────────────")
        # A client that opens a socket, sends a partial request and says
        # nothing more. On a serial server this holds everyone behind it.
        slow = socket.create_connection(("127.0.0.1", port), timeout=20)
        slow.sendall(b"GET /login HTTP/1.1\r\nHost: x\r\n")   # no blank line
        time.sleep(0.3)

        start = time.time()
        body = urllib.request.urlopen(svc.url("/login"), timeout=10).read()
        elapsed = time.time() - start
        ok("a second client is served while the first is still talking",
           b"password" in body and elapsed < 2.0, f"{elapsed:.2f}s")
        measure("second client served in", f"{elapsed * 1000:.0f} ms")

        print("\n── A slow client ────────────────────────────────────────────────")
        t0 = time.time()
        slow.settimeout(20)
        answer = b""
        try:
            while True:
                chunk = slow.recv(4096)
                if not chunk:
                    break
                answer += chunk
        except socket.timeout:
            pass
        waited = time.time() - t0
        slow.close()
        ok("it is answered rather than held open forever", b"408" in answer,
           answer[:80].decode(errors="replace"))
        ok("and the timeout is the one configured, not a hang", waited < 15,
           f"{waited:.1f}s")
        measure("slow client released after", f"{waited:.1f} s")
        ok("the service is still up", svc.alive())

        print("\n── A client that walks away ─────────────────────────────────────")
        for _ in range(5):
            s = socket.create_connection(("127.0.0.1", port), timeout=5)
            s.sendall(b"GET /login HTTP/1.1\r\nHost: x\r\n\r\n")
            s.close()          # gone before the response is written
            time.sleep(0.1)
        time.sleep(0.5)
        ok("SIGPIPE does not take the process down", svc.alive())

        print("\n── A malformed request ──────────────────────────────────────────")
        for junk in (b"\x00\x01\x02\r\n\r\n", b"not http at all\r\n\r\n",
                     b"GET\r\n\r\n",
                     b"POST /orders HTTP/1.1\r\nContent-Length: 99999\r\n\r\nx"):
            s = socket.create_connection(("127.0.0.1", port), timeout=12)
            s.sendall(junk)
            try:
                s.recv(256)
            except socket.timeout:
                pass
            s.close()
        ok("garbage is answered and the service survives it", svc.alive())
        body = urllib.request.urlopen(svc.url("/login"), timeout=10).read()
        ok("and it still serves afterwards", b"password" in body)

        print("\n── Ten writes arriving together ─────────────────────────────────")
        # Against an empty table this proves nothing: ten creates that each
        # take five milliseconds barely overlap, and the test passed with the
        # lock removed. A thousand rows make reading, changing and saving the
        # table slow enough that the ten requests are genuinely inside it at
        # the same time — which is the only condition under which a lost
        # update can be observed.
        svc.stop()
        with open(os.path.join(app, "data", "orders.tsv"), "w") as f:
            f.write("#strata\tOrder\tid:i\tcustomer:s\tregion:s\tamount:f\tstatus:s\n")
            for i in range(1, 1001):
                f.write(f"{i}\tseed{i}\tapac\t10.00\tCLOSED\n")
        svc.start()

        def rows_on_disk():
            return [l for l in open(os.path.join(app, "data", "orders.tsv"))
                    .read().splitlines()[1:] if l]

        before = len(rows_on_disk())
        openers = [signed_in(svc) for _ in range(10)]
        errors = []

        def create(i, opener):
            try:
                opener.open(svc.url("/orders"),
                            f"customer=c{i}&region=apac&amount=10.00".encode(),
                            timeout=20)
            except Exception as e:                      # noqa: BLE001
                errors.append(repr(e))

        threads = [threading.Thread(target=create, args=(i, o))
                   for i, o in enumerate(openers)]
        t0 = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        concurrent_writes = time.time() - t0
        ok("every request succeeded", not errors, "; ".join(errors[:2]))

        rows = rows_on_disk()
        ok("all ten rows are on disk — none was lost to a concurrent save",
           len(rows) == before + 10, f"{len(rows)} rows, was {before}")
        ids = [l.split("\t")[0] for l in rows]
        ok("and every one has its own id", len(set(ids)) == len(ids),
           f"{len(ids) - len(set(ids))} duplicate ids, e.g. {ids[:8]}")
        measure("ten concurrent creates took", f"{concurrent_writes * 1000:.0f} ms")

        print("\n── A restart with live data ─────────────────────────────────────")
        svc.stop()
        svc.start()
        ok("it comes back up", svc.alive())
        page = signed_in(svc).open(svc.url("/"), timeout=10).read().decode()
        ok("with the ten orders still there",
           all(f"c{i}" in page for i in range(10)), page[:200])

        print("\n── A list long enough to hurt ───────────────────────────────────")
        svc.stop()
        data = os.path.join(app, "data", "orders.tsv")
        with open(data, "w") as f:
            f.write("#strata\tOrder\tid:i\tcustomer:s\tregion:s\tamount:f\tstatus:s\n")
            for i in range(1, 2001):
                f.write(f"{i}\tcustomer{i}\tapac\t100.50\tOPEN\n")
        svc.start()
        opener = signed_in(svc)
        t0 = time.time()
        page = opener.open(svc.url("/"), timeout=60).read().decode()
        big = time.time() - t0
        ok("2000 rows render", page.count("customer") > 1000, f"{len(page)} bytes")
        measure("dashboard with 2000 rows", f"{big * 1000:.0f} ms, "
                                            f"{len(page) // 1024} KB")

        print("\n── Numbers ──────────────────────────────────────────────────────")
        # Sequential latency over the small page, after the big table is gone.
        svc.stop()
        open(data, "w").write(
            "#strata\tOrder\tid:i\tcustomer:s\tregion:s\tamount:f\tstatus:s\n"
            + "".join(f"{i}\tc{i}\tapac\t10.00\tOPEN\n" for i in range(1, 21)))
        svc.start()
        opener = signed_in(svc)
        samples = []
        for _ in range(100):
            t0 = time.time()
            opener.open(svc.url("/"), timeout=20).read()
            samples.append((time.time() - t0) * 1000)
        samples.sort()
        measure("dashboard, 20 rows, p50", f"{statistics.median(samples):.1f} ms")
        measure("dashboard, 20 rows, p95", f"{samples[94]:.1f} ms")
        measure("sequential throughput", f"{1000 / statistics.mean(samples):.0f} req/s")
        ok("p95 is under a quarter second", samples[94] < 250, f"{samples[94]:.1f} ms")

        # Concurrency: the same work, eight clients at a time.
        lat = []
        lock = threading.Lock()

        def hammer(n):
            o = signed_in(svc)
            for _ in range(n):
                t0 = time.time()
                try:
                    o.open(svc.url("/"), timeout=20).read()
                    d = (time.time() - t0) * 1000
                except Exception:
                    d = -1
                with lock:
                    lat.append(d)

        threads = [threading.Thread(target=hammer, args=(15,)) for _ in range(8)]
        t0 = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.time() - t0
        good = sorted(x for x in lat if x >= 0)
        ok("120 requests over 8 clients all answered", len(good) == 120,
           f"{len(good)}/120")
        measure("concurrent throughput", f"{len(good) / wall:.0f} req/s")
        measure("concurrent p95", f"{good[int(len(good) * 0.95)]:.1f} ms"
                if good else "n/a")
        measure("cores available", str(os.cpu_count()))
        # Recorded rather than explained away: concurrent throughput comes out
        # at or below sequential. It is not the lock — GETs take a shared one.
        # Every request forks a process and reloads all three tables from
        # disk, and that is what the number is measuring. What the process per
        # connection buys is that one slow or hostile client cannot hold the
        # others, which is the thing this journey is about; throughput is the
        # next piece of work, and the honest figure is the one above.

        print("\n── Nothing left behind ──────────────────────────────────────────")
        ps = subprocess.run(["ps", "-o", "stat=,comm=", "--ppid",
                             str(svc.proc.pid)], capture_output=True, text=True)
        zombies = [l for l in ps.stdout.splitlines() if l.strip().startswith("Z")]
        ok("no zombie children after 200-odd requests", not zombies,
           str(zombies[:3]))
        ok("the service is still the same process", svc.alive())

    finally:
        svc.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"  {PASS}/{PASS + FAIL} steps of the journey passed")
    for name, value in NUMBERS:
        print(f"    {name:<40} {value}")
    print("=" * 64)
    if FAIL:
        print("  The service does not yet survive contact. NOT OK")
        return 1
    print("  The service survives contact. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
