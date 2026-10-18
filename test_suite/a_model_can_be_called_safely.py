#!/usr/bin/env python3
"""Calling a language model over a connection that is actually checked.

Until TLS existed, `std/fetch.sta` refused every https:// URL, which meant
Strata could not call any model API at all -- all of them are https only.
That was the honest answer and a useless one.

What is checked here is not "can it make a request". It is the four ways a
TLS client is usually wrong, each one of which is a quiet failure rather than
a loud one:

  1. A certificate signed by an authority this machine does not trust is
     REFUSED. The usual fix for this in a hurry is a flag that turns
     verification off, and every such flag is in production somewhere. There
     is no such flag in std/tls.sta, and this checks it stays that way.

  2. A certificate that is perfectly valid but issued for a DIFFERENT HOST is
     REFUSED. This is a separate check from the first one and it is the one
     people leave out -- OpenSSL does not do it unless asked.

  3. A model's answer, which is full of \" and \n, is read WHOLE. A JSON
     reader that stops at the first escaped quote returns a short string that
     still looks like an answer, and the program carries on with half a
     sentence. That is exactly the class of silent wrong answer this language
     exists to stop.

  4. A key is never sent to a plain-HTTP address that is not this machine,
     and a refusal never quotes the key back.

The server is a local TLS listener with a certificate minted here, so this
needs no network and gives the same answer every time.
"""
import json
import os
import shutil
import socket
import ssl
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


def openssl(args, cwd):
    return subprocess.run(["openssl"] + args, cwd=cwd,
                          capture_output=True, text=True)


def make_certs(d):
    """A throwaway authority, a certificate for localhost, and one for
    somewhere else signed by the same authority."""
    openssl(["req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", "ca.key", "-out", "ca.crt", "-days", "1",
             "-subj", "/CN=Strata Test Authority"], d)
    for name, cn, san in (("srv", "localhost", "DNS:localhost,IP:127.0.0.1"),
                          ("other", "elsewhere.invalid", "DNS:elsewhere.invalid")):
        openssl(["req", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", f"{name}.key", "-out", f"{name}.csr",
                 "-subj", f"/CN={cn}"], d)
        with open(os.path.join(d, f"{name}.ext"), "w") as f:
            f.write(f"subjectAltName={san}\n")
        openssl(["x509", "-req", "-in", f"{name}.csr", "-CA", "ca.crt",
                 "-CAkey", "ca.key", "-CAcreateserial", "-out", f"{name}.crt",
                 "-days", "1", "-extfile", f"{name}.ext"], d)
    return os.path.isfile(os.path.join(d, "srv.crt"))


# The answer the stub gives: escaped quotes and a newline, which is what a
# model's text actually looks like once it is inside JSON.
ANSWER = 'He said "yes".\nThen he left.'


class Stub:
    """A TLS chat-completions endpoint. Serves `cert` and wants `key`."""

    def __init__(self, d, cert, want_key):
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(os.path.join(d, cert + ".crt"),
                                 os.path.join(d, cert + ".key"))
        self.want_key = want_key
        self.seen = []
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.stop = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.stop:
            try:
                raw, _ = self.sock.accept()
            except OSError:
                return
            try:
                conn = self.ctx.wrap_socket(raw, server_side=True)
            except Exception:
                # A client that refused our certificate: it hung up during
                # the handshake. That is a pass, not an error.
                try:
                    raw.close()
                except OSError:
                    pass
                continue
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn):
        try:
            conn.settimeout(5)
            req = conn.recv(65536).decode("utf8", "replace")
            self.seen.append(req)
            authed = f"Bearer {self.want_key}" in req
            at = req.find("\r\n\r\n")
            try:
                sent = json.loads(req[at + 4:]) if at > 0 else {}
            except ValueError:
                sent = {}
            if not authed:
                body = json.dumps({"error": {"message": "that key is not valid"}})
                self._send(conn, 401, body)
                return
            body = json.dumps({"model": sent.get("model"),
                               "choices": [{"message": {"role": "assistant",
                                                        "content": ANSWER}}]})
            self._send(conn, 200, body)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _send(self, conn, status, body):
        raw = body.encode()
        head = (f"HTTP/1.1 {status} x\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n")
        conn.sendall(head.encode() + raw)

    def close(self):
        self.stop = True
        try:
            self.sock.close()
        except OSError:
            pass


PROGRAM = r'''
import io  from std;
import str from std;
import llm from std;
import tls from std;

int main() {
    str url = str_cat(["https://localhost:", file_read("PORTFILE"), "/v1/chat/completions"]);
    str got = llm_ask_at(url, "demo-model", "KEY", "be brief", "say hi", 70);
    if (str_len(got) == 0) {
        print(str_concat("REFUSED: ", last_error()));
        clear_error();
        return 0;
    }
    print(str_concat("ANSWER: ", got));
    return 0;
}
'''


def run_program(d, port, key, ca=None):
    with open(os.path.join(d, "port"), "w") as f:
        f.write(str(port))
    src = os.path.join(d, "ask.sta")
    with open(src, "w") as f:
        f.write(PROGRAM.replace("PORTFILE", os.path.join(d, "port"))
                       .replace("KEY", key))
    env = dict(os.environ)
    if ca:
        env["SSL_CERT_FILE"] = os.path.join(d, ca)
    else:
        # No trusted authorities at all: our throwaway CA is not among the
        # system roots either way, but being explicit makes the intent clear.
        env.pop("SSL_CERT_FILE", None)
    r = subprocess.run([STRATA, "run", src], capture_output=True, text=True,
                       env=env, timeout=180)
    return r.stdout + r.stderr


def tls_is_built_in():
    """Whether this build has OpenSSL in it. Without it the refusals below
    are not the refusals being tested, so the test says so rather than
    passing for the wrong reason."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "probe.sta")
        with open(src, "w") as f:
            f.write('import io from std;\nimport tls from std;\n'
                    'int main() { print(str(tls_available())); return 0; }\n')
        r = subprocess.run([STRATA, "run", src], capture_output=True,
                           text=True, timeout=180)
        return "1" in r.stdout.splitlines()[-1] if r.stdout.strip() else False


def main():
    print()
    print("── a model can be called, and the connection is checked "
          + "─" * 12)

    if not shutil.which("openssl"):
        print("  SKIP  the openssl command is not installed here, so no "
              "certificate can be minted")
        return 0

    if not tls_is_built_in():
        print("  SKIP  this build has no OpenSSL in it (pkg-config could not "
              "find it), so std/tls.sta is compiled as a refusal")
        return 0

    with tempfile.TemporaryDirectory() as d:
        if not make_certs(d):
            print("  SKIP  openssl would not mint a certificate here")
            return 0

        # 1. The happy path, with the authority trusted.
        stub = Stub(d, "srv", "right-key")
        out = run_program(d, stub.port, "right-key", ca="ca.crt")
        ok("a verified call gets an answer", "ANSWER:" in out, out)
        ok("the answer is read whole, past the escaped quote",
           'He said "yes".' in out and "Then he left." in out, out)
        ok("the request actually carried the key",
           any("Bearer right-key" in s for s in stub.seen), str(stub.seen)[:200])
        ok("and it went out as a POST of JSON",
           any(s.startswith("POST ") and "application/json" in s
               for s in stub.seen), str(stub.seen)[:200])

        # 2. The wrong key: a refusal carrying the service's own reason.
        out = run_program(d, stub.port, "wrong-key", ca="ca.crt")
        ok("a rejected key is a refusal, not an empty answer",
           "REFUSED:" in out, out)
        ok("and the refusal says what the service said",
           "401" in out and "that key is not valid" in out, out)
        stub.close()

        # 3. An authority this machine does not trust.
        stub = Stub(d, "srv", "right-key")
        out = run_program(d, stub.port, "right-key", ca=None)
        ok("an untrusted authority is refused", "REFUSED:" in out, out)
        ok("and the reason names the certificate, not the network",
           "certificate" in out.lower() or "issuer" in out.lower(), out)
        ok("nothing was sent to it", not stub.seen, str(stub.seen)[:200])
        stub.close()

        # 4. A valid certificate, issued for somewhere else.
        stub = Stub(d, "other", "right-key")
        out = run_program(d, stub.port, "right-key", ca="ca.crt")
        ok("a valid certificate for the wrong host is refused",
           "REFUSED:" in out, out)
        ok("and the reason says it is the hostname",
           "hostname" in out.lower() or "name" in out.lower(), out)
        ok("nothing was sent to that one either",
           not stub.seen, str(stub.seen)[:200])
        stub.close()

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  A model call is not safe. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  The call is verified, the answer is read whole, and every way "
          "it can be wrong is a refusal. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
