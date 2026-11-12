#!/usr/bin/env python3
"""The messaging connectors, run against something that answers back.

`std/smtp.sta`, `std/notify.sta` and `std/webhook.sta` each carry `verify`
blocks for the parts that are pure text — dot-stuffing, header assembly,
base64, signature computation, redaction. Those run here too, because a
module whose own checks have stopped passing is not a module to then test
over a socket.

What this file adds is the half a `verify` block cannot reach: a real mail
server on the other end of a real socket, and a real HTTP client posting at a
real receiver. Every case below is here because it is a way these three go
wrong in production and look fine in a unit test.

  SMTP — a conversation, not a function call
  * The message that arrives is byte for byte the message that was meant.
    A body line that is a single full stop ENDS the message in SMTP, so the
    client doubles it and the server undoubles it. If the client forgets, the
    server accepts a truncated message and reports success: everything
    downstream is happy and the last half of the mail is gone. This is the
    single most common defect in hand-written mail code and it cannot be seen
    without a server to send to.
  * A multi-line EHLO reply is read whole. A client that stops at the first
    line puts its next command into the middle of the server's answer and the
    session desynchronises, which surfaces three commands later as something
    that makes no sense.
  * AUTH PLAIN really does carry NUL-separated fields. A Strata `str` ends at
    its first NUL, so this is the one thing in the module that cannot be
    built in Strata at all — and if it were built wrongly, the server would
    see an empty user and refuse a login that looked correct from here.
  * A refused login does not put the password anywhere. The whole output of
    the program is searched for it.
  * STARTTLS is taken when offered, and the certificate is CHECKED. The
    negative case matters more than the positive one: pointed at a server
    whose certificate it has no reason to trust, the client must refuse. A
    STARTTLS that does not verify looks encrypted in a log and anybody on the
    path can sit in the middle of it.

  WEBHOOK — the refusals are the feature
  * A correctly signed POST is accepted AND reaches the handler. Verifying
    and then dropping the payload is the worst outcome available: the sender
    believes it was delivered and will not send it again.
  * An unsigned POST is refused. This is the request anybody who learns the
    URL can send, and it is the entire reason the endpoint has a secret.
  * A POST whose body was changed after signing is refused. The signature is
    still well-formed; it is simply not a signature for these bytes. A
    receiver that checks the header is present, or checks a prefix, passes
    this and is wide open.
  * A POST signed with a different secret is refused.
  * A GET is answered 405 and not 401, because the method is checked first:
    telling a scanner "your signature is missing" on a GET says more than it
    needs to.
  * Uppercase hex verifies, because the sender's spelling of hex is not a
    forgery and a refusal there looks exactly like a wrong secret.
  * A verified delivery with no handler registered answers 500, not 202.
  * In every refusal, the handler file must NOT appear. An endpoint that
    refuses with 401 and processes the payload anyway has refused nothing.

  NOTIFY — built, not sent
  * The JSON is checked, and the URL guard and the redaction are checked.
    NOTHING IS POSTED: no request leaves this machine from these cases, to
    Slack, to Teams or to anywhere else. The module's dry-run switch is the
    same function production calls with one argument changed, so what is
    exercised here is the real path and not a parallel one written for a
    test.

Run: python3 test_suite/connectors_messaging.py
"""
import base64
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def note(text):
    print(f"        {text}")


def child_env():
    env = dict(os.environ)
    env["STRATA_ROOT"] = ROOT
    return env


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def build(d, name, src, env=None):
    """Compile one Strata source. Returns (binary path, compiler output)."""
    path = os.path.join(d, name + ".sta")
    with open(path, "w") as f:
        f.write(src)
    out = os.path.join(d, name)
    r = subprocess.run([sys.executable, STAGE0, path, "-o", out],
                       cwd=ROOT, env=env or child_env(),
                       capture_output=True, text=True, timeout=600)
    return out, r.stdout + r.stderr


def run_verify_blocks(d, module):
    """Build and run one std module's own verify blocks."""
    out = os.path.join(d, "verify_" + module)
    r = subprocess.run([sys.executable, STAGE0,
                        os.path.join("std", module + ".sta"), "--test", "-o", out],
                       cwd=ROOT, env=child_env(),
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return None, r.stdout + r.stderr
    r2 = subprocess.run([out], cwd=d, capture_output=True, text=True, timeout=300)
    return r2.returncode, r2.stdout + r2.stderr


# ── A mail server that answers, and remembers what it was told ───────────
#
# Hand-written rather than Python's own, because what is being tested is the
# wire: this records the bytes of the DATA block before and after undoing the
# dot-stuffing, which is the one thing a higher-level server would hide.

class FakeSMTP(threading.Thread):
    def __init__(self, user="ops@example.com", password="hunter2",
                 offer_starttls=False, certfile=None, keyfile=None,
                 mechanisms=("PLAIN", "LOGIN"), offer_8bitmime=True):
        super().__init__(daemon=True)
        self.user = user
        self.password = password
        self.offer_starttls = offer_starttls
        self.certfile = certfile
        self.keyfile = keyfile
        self.mechanisms = mechanisms
        self.offer_8bitmime = offer_8bitmime
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.port = self.listener.getsockname()[1]
        self.commands = []
        self.auth_attempts = []
        self.messages = []        # undone dot-stuffing: what was meant
        self.raw_data = []        # the bytes on the wire: what was sent
        self.secure_at_data = []
        self.errors = []
        self.stopping = False

    def stop(self):
        self.stopping = True
        try:
            self.listener.close()
        except OSError:
            pass

    def run(self):
        while not self.stopping:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            try:
                self.session(conn)
            except Exception as exc:          # recorded, never raised here
                self.errors.append(repr(exc))
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def session(self, conn):
        sock = [conn]
        reader = [conn.makefile("rb")]
        secure = [False]

        def send(text):
            sock[0].sendall(text.encode("utf-8"))

        def readline():
            return reader[0].readline()

        send("220 fake.example ESMTP ready\r\n")
        while True:
            line = readline()
            if not line:
                return
            command = line.decode("utf-8", "replace").rstrip("\r\n")
            self.commands.append(command)
            upper = command.upper()

            if upper.startswith("EHLO") or upper.startswith("HELO"):
                caps = ["250-fake.example"]
                if self.offer_8bitmime:
                    caps.append("250-8BITMIME")
                if self.offer_starttls and not secure[0]:
                    caps.append("250-STARTTLS")
                if self.mechanisms:
                    caps.append("250-AUTH " + " ".join(self.mechanisms))
                caps.append("250 HELP")
                send("\r\n".join(caps) + "\r\n")

            elif upper == "STARTTLS":
                send("220 ready to start TLS\r\n")
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(self.certfile, self.keyfile)
                sock[0] = context.wrap_socket(sock[0], server_side=True)
                reader[0] = sock[0].makefile("rb")
                secure[0] = True

            elif upper.startswith("AUTH PLAIN"):
                parts = command.split(" ", 2)
                if len(parts) == 3:
                    argument = parts[2]
                else:
                    send("334 \r\n")
                    argument = readline().decode().strip()
                raw = base64.b64decode(argument)
                fields = raw.split(b"\0")
                user = fields[1].decode() if len(fields) > 1 else ""
                password = fields[2].decode() if len(fields) > 2 else ""
                self.auth_attempts.append(("PLAIN", user, password))
                if user == self.user and password == self.password:
                    send("235 2.7.0 Authentication successful\r\n")
                else:
                    send("535 5.7.8 Authentication credentials invalid\r\n")

            elif upper == "AUTH LOGIN":
                send("334 " + base64.b64encode(b"Username:").decode() + "\r\n")
                user = base64.b64decode(readline().strip()).decode()
                send("334 " + base64.b64encode(b"Password:").decode() + "\r\n")
                password = base64.b64decode(readline().strip()).decode()
                self.auth_attempts.append(("LOGIN", user, password))
                if user == self.user and password == self.password:
                    send("235 2.7.0 Authentication successful\r\n")
                else:
                    send("535 5.7.8 Authentication credentials invalid\r\n")

            elif upper.startswith("MAIL FROM"):
                send("250 2.1.0 sender ok\r\n")

            elif upper.startswith("RCPT TO"):
                send("250 2.1.5 recipient ok\r\n")

            elif upper == "DATA":
                send("354 End data with <CR><LF>.<CR><LF>\r\n")
                raw_lines = []
                while True:
                    chunk = readline()
                    if not chunk:
                        return
                    if chunk == b".\r\n":
                        break
                    raw_lines.append(chunk)
                self.raw_data.append(b"".join(raw_lines))
                # Undoing the transparency rule, which is the server's half
                # of it: a line that arrives with two leading full stops was
                # sent with one.
                undone = []
                for raw in raw_lines:
                    if raw.startswith(b".."):
                        undone.append(raw[1:])
                    else:
                        undone.append(raw)
                self.messages.append(b"".join(undone))
                self.secure_at_data.append(secure[0])
                send("250 2.0.0 Ok: queued as ABC123\r\n")

            elif upper == "QUIT":
                send("221 2.0.0 Bye\r\n")
                return

            elif upper == "RSET":
                send("250 2.0.0 Ok\r\n")

            else:
                send("502 5.5.2 Error: command not recognized\r\n")


def make_certificate(d, name, common_name):
    """A self-signed certificate, for a server to present and a client to
    refuse. Returns (certificate, key) or (None, None) when openssl is not
    on this machine."""
    cert = os.path.join(d, name + "-cert.pem")
    key = os.path.join(d, name + "-key.pem")
    r = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
         "-days", "1", "-nodes", "-keyout", key, "-out", cert,
         "-subj", "/CN=" + common_name,
         "-addext", "subjectAltName=DNS:" + common_name],
        capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not os.path.exists(cert):
        return None, None
    return cert, key


# ── The Strata programs these cases drive ────────────────────────────────

SENDER_SRC = r'''// Built by test_suite/connectors_messaging.py. Not part of the project.
import io   from std;
import str  from std;
import cli  from std;
import smtp from std;

int main() {
    str host     = arg(1);
    int port     = str_to_int(arg(2));
    str user     = arg(3);
    str password = arg(4);
    str subject  = arg(5);

    // A body with the three shapes that end a message early if the
    // transparency rule is not applied: a line of leaders, a line that is a
    // single full stop, and an ordinary sentence after both of them.
    str body = str_cat(["Totals follow.\n",
    "..... 12,400\n",
    ".\n",
    "Signed off by Finance\n"]);

    int sent = smtp_send_mail(host, port, "localhost", user, password,
    "ops@example.com", "finance@example.com", subject, body);
    if (sent == 1) { print("SENT"); return 0; }
    print(str_cat(["FAILED: ", last_error()]));
    clear_error();
    return 0;
}
'''

RECEIVER_SRC = r'''// Built by test_suite/connectors_messaging.py. Not part of the project.
import io      from std;
import str     from std;
import cli     from std;
import webhook from std;

// The handler writes to a file rather than printing, so that a case can tell
// "the payload reached the handler" from "the process had buffered output
// when it was killed".
stream OnPush(str payload) {
    file_write("received.txt", payload);
}

int main() {
    str secret  = arg(1);
    int port    = str_to_int(arg(2));
    str channel = arg(3);
    webhook_serve(port, secret, channel, 0);
    return 0;
}
'''

NOTIFY_SRC = r'''// Built by test_suite/connectors_messaging.py. Not part of the project.
import io     from std;
import str    from std;
import notify from std;

int main() {
    print(notify_text_body("batch 41 finished"));
    print(notify_block_body("Batch 41", "1,204 rows posted"));
    print(str(notify_text("https://hooks.slack.example/services/T0/B0/s3cret-part",
    "batch 41 finished", 1)));
    print(str(notify_block("https://example.webhook.office.example/webhookb2/s3cret-part",
    "Batch 41", "1,204 rows posted", 1)));
    int refused = notify_text("http://hooks.slack.example/services/T0/B0/s3cret-part",
    "batch 41 finished", 1);
    print(str(refused));
    print(str_cat(["ERROR: ", last_error()]));
    clear_error();
    print(notify_redact("https://hooks.slack.example/services/T0/B0/s3cret-part"));
    return 0;
}
'''


def post(port, path, body, headers):
    """One HTTP/1.1 POST or GET, written by hand so that a case can send a
    request urllib would not — a missing header, a body that disagrees with
    its signature."""
    method = headers.pop("__method__", "POST")
    lines = [f"{method} {path} HTTP/1.1", "Host: 127.0.0.1", "Connection: close"]
    for name, value in headers.items():
        lines.append(f"{name}: {value}")
    lines.append(f"Content-Length: {len(body)}")
    request = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    s = socket.create_connection(("127.0.0.1", port), timeout=20)
    try:
        s.sendall(request)
        answer = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            answer += chunk
    finally:
        s.close()
    first = answer.split(b"\r\n", 1)[0].decode("utf-8", "replace")
    status = -1
    pieces = first.split(" ")
    if len(pieces) > 1 and pieces[1].isdigit():
        status = int(pieces[1])
    return status, answer


def wait_for_port(port, seconds=20):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1)
            s.close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


def main():
    print()
    print("── the messaging connectors ──" + "─" * 33)

    with tempfile.TemporaryDirectory() as d:

        # ── Each module's own checks still pass ──────────────────────────
        print("  -- the modules' own verify blocks")
        tls_here = True
        for module in ("smtp", "notify", "webhook"):
            rc, out = run_verify_blocks(d, module)
            ok(f"std/{module}.sta passes its own verify blocks",
               rc == 0 and "0 failed" in out,
               (out or "")[-600:])
            if module == "webhook" and rc == 0:
                # The signature cases skip themselves on a machine with no
                # OpenSSL, and so must the ones below — but the fail-closed
                # behaviour is still asserted either way.
                tls_here = "the HMAC is the HMAC everybody else computes" in out

        sender, compiler_said = build(d, "sender", SENDER_SRC)
        ok("a program that sends mail compiles",
           os.path.exists(sender), compiler_said[-600:])
        receiver, compiler_said = build(d, "receiver", RECEIVER_SRC)
        ok("a webhook receiver compiles",
           os.path.exists(receiver), compiler_said[-600:])
        notifier, compiler_said = build(d, "notifier", NOTIFY_SRC)
        ok("a program that builds chat messages compiles",
           os.path.exists(notifier), compiler_said[-600:])

        # ── SMTP, against a server that answers ──────────────────────────
        print("  -- smtp, against a mail server on a socket")
        server = FakeSMTP()
        server.start()
        r = subprocess.run([sender, "127.0.0.1", str(server.port),
                            "ops@example.com", "hunter2", "Batch 41 finished"],
                           cwd=d, capture_output=True, text=True, timeout=120)
        out = r.stdout + r.stderr
        ok("the server accepts the message and the client says so",
           "SENT" in out, out[-400:])
        ok("exactly one message arrived",
           len(server.messages) == 1, f"{len(server.messages)} messages")

        arrived = server.messages[0].decode("utf-8", "replace") if server.messages else ""
        on_wire = server.raw_data[0].decode("utf-8", "replace") if server.raw_data else ""

        ok("the headers a mail client needs are all there",
           "From: ops@example.com\r\n" in arrived
           and "To: finance@example.com\r\n" in arrived
           and "Subject: Batch 41 finished\r\n" in arrived
           and "Date: " in arrived
           and "MIME-Version: 1.0\r\n" in arrived
           and "Content-Type: text/plain; charset=utf-8\r\n" in arrived,
           arrived[:400])

        body = arrived.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in arrived else ""
        meant = ("Totals follow.\r\n"
                 "..... 12,400\r\n"
                 ".\r\n"
                 "Signed off by Finance\r\n")
        # The whole point. If the client did not stuff, the server stopped
        # reading at the line that is a single full stop and `body` is two
        # lines short — and the client still reported success, because the
        # server still answered 250.
        ok("the body that arrives is byte for byte the body that was meant",
           body == meant, repr(body))
        ok("a line that is a single full stop did not end the message early",
           "Signed off by Finance" in body, repr(body[-120:]))
        ok("and it was stuffed on the wire, not merely intact afterwards",
           "\r\n..\r\n" in on_wire and "\r\n...... 12,400\r\n" in on_wire,
           repr(on_wire))
        ok("an ordinary full stop mid-sentence was left alone",
           "Totals follow.\r\n" in body and "Totals follow..\r\n" not in body,
           repr(body[:60]))

        ok("AUTH PLAIN carried the user and the password the server expected",
           server.auth_attempts == [("PLAIN", "ops@example.com", "hunter2")],
           repr(server.auth_attempts))
        ok("the whole EHLO reply was read, so the session stayed in step",
           server.errors == [] and "QUIT" in server.commands,
           repr(server.errors) + repr(server.commands))
        server.stop()

        # A server that offers only LOGIN. The mechanism is chosen from what
        # was offered, not assumed.
        server = FakeSMTP(mechanisms=("LOGIN",))
        server.start()
        r = subprocess.run([sender, "127.0.0.1", str(server.port),
                            "ops@example.com", "hunter2", "Via LOGIN"],
                           cwd=d, capture_output=True, text=True, timeout=120)
        out = r.stdout + r.stderr
        ok("a server offering only AUTH LOGIN is authenticated to that way",
           "SENT" in out and server.auth_attempts
           and server.auth_attempts[0][0] == "LOGIN"
           and server.auth_attempts[0][2] == "hunter2",
           out[-300:] + repr(server.auth_attempts))
        server.stop()

        # A refused login. What matters is not the refusal but what the
        # program says about it.
        server = FakeSMTP(password="something-else")
        server.start()
        r = subprocess.run([sender, "127.0.0.1", str(server.port),
                            "ops@example.com", "hunter2", "Wrong password"],
                           cwd=d, capture_output=True, text=True, timeout=120)
        out = r.stdout + r.stderr
        ok("a refused login is reported as a failure, with the server's code",
           "FAILED" in out and "535" in out, out[-300:])
        ok("and the password appears nowhere in anything the program printed",
           "hunter2" not in out, out[-300:])
        ok("and no message was sent after the login was refused",
           server.messages == [], repr(server.messages))
        server.stop()

        # ── STARTTLS, and the certificate check behind it ────────────────
        print("  -- starttls, and whether the certificate is really checked")
        cert, key = make_certificate(d, "good", "localhost")
        other_cert, _ = make_certificate(d, "other", "somewhere-else.example")
        if cert is None:
            note("openssl is not on this machine, so STARTTLS was not exercised")
        elif not tls_here:
            note("this build has no OpenSSL, so STARTTLS was not exercised")
        else:
            server = FakeSMTP(offer_starttls=True, certfile=cert, keyfile=key)
            server.start()
            env = child_env()
            env["SSL_CERT_FILE"] = cert
            r = subprocess.run([sender, "localhost", str(server.port),
                                "ops@example.com", "hunter2", "Over TLS"],
                               cwd=d, env=env, capture_output=True,
                               text=True, timeout=120)
            out = r.stdout + r.stderr
            ok("STARTTLS is taken when the server offers it",
               "SENT" in out and "STARTTLS" in server.commands, out[-400:])
            ok("and the message was carried inside the TLS session",
               server.secure_at_data == [True], repr(server.secure_at_data))
            ok("and the capability list was asked for again after the upgrade",
               len([c for c in server.commands if c.upper().startswith("EHLO")]) == 2,
               repr(server.commands))
            ok("and the password went over the encrypted connection, not before it",
               server.commands.index("STARTTLS")
               < [i for i, c in enumerate(server.commands)
                  if c.upper().startswith("AUTH")][0],
               repr(server.commands))
            server.stop()

            # The case that decides whether any of the above means anything:
            # the same server, with this machine trusting a different
            # authority. A client that does not verify sends the password
            # anyway and reports success.
            server = FakeSMTP(offer_starttls=True, certfile=cert, keyfile=key)
            server.start()
            env = child_env()
            env["SSL_CERT_FILE"] = other_cert
            r = subprocess.run([sender, "localhost", str(server.port),
                                "ops@example.com", "hunter2", "Untrusted"],
                               cwd=d, env=env, capture_output=True,
                               text=True, timeout=120)
            out = r.stdout + r.stderr
            ok("a certificate this machine has no reason to trust is refused",
               "SENT" not in out and "FAILED" in out, out[-400:])
            ok("the refusal says it was the certificate",
               "refused the TLS handshake" in out or "certificate" in out.lower(),
               out[-400:])
            ok("and nothing was sent and no password was offered",
               server.messages == [] and server.auth_attempts == [],
               repr(server.messages) + repr(server.auth_attempts))
            ok("and the password is not in the refusal either",
               "hunter2" not in out, out[-300:])
            server.stop()

        # ── The webhook receiver ─────────────────────────────────────────
        print("  -- the webhook receiver, posted at with good and bad signatures")
        if not tls_here:
            note("this build has no OpenSSL, so the receiver can verify "
                 "nothing; only the fail-closed behaviour is checked")
        secret = "the-shared-secret"
        payload = b'{"event":"push","ref":"refs/heads/main"}'

        def signature(body, key=secret):
            import hmac
            import hashlib
            return "sha256=" + hmac.new(key.encode(), body,
                                        hashlib.sha256).hexdigest()

        port = free_port()
        received = os.path.join(d, "received.txt")
        proc = subprocess.Popen([receiver, secret, str(port), "OnPush"],
                                cwd=d, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            ok("the receiver is listening", wait_for_port(port), "never came up")

            def clear():
                if os.path.exists(received):
                    os.remove(received)

            def handled():
                return os.path.exists(received)

            if tls_here:
                clear()
                status, _ = post(port, "/hooks", payload,
                                 {"X-Hub-Signature-256": signature(payload)})
                ok("a correctly signed POST is accepted", status == 202, str(status))
                ok("and the payload reached the handler, byte for byte",
                   handled() and open(received, "rb").read() == payload,
                   repr(open(received, "rb").read() if handled() else None))

                clear()
                status, _ = post(port, "/hooks", payload, {})
                ok("an unsigned POST is refused", status == 401, str(status))
                ok("and an unsigned POST does not reach the handler",
                   not handled(), "the handler ran anyway")

                clear()
                status, _ = post(port, "/hooks", payload,
                                 {"X-Hub-Signature-256": signature(payload, "wrong-secret")})
                ok("a POST signed with the wrong secret is refused",
                   status == 401, str(status))
                ok("and it does not reach the handler", not handled(),
                   "the handler ran anyway")

                clear()
                tampered = b'{"event":"push","ref":"refs/heads/prod"}'
                status, _ = post(port, "/hooks", tampered,
                                 {"X-Hub-Signature-256": signature(payload)})
                ok("a POST whose body changed after signing is refused",
                   status == 401, str(status))
                ok("and the changed body does not reach the handler",
                   not handled(), "the handler ran anyway")

                clear()
                status, _ = post(port, "/hooks", payload,
                                 {"X-Hub-Signature-256": "sha256=" + "0" * 64})
                ok("a well-formed signature that is simply wrong is refused",
                   status == 401, str(status))

                clear()
                status, _ = post(port, "/hooks", payload,
                                 {"X-Hub-Signature-256":
                                  signature(payload)[:-1] + "0"})
                ok("a signature wrong in its last character only is refused",
                   status == 401 or signature(payload).endswith("0"), str(status))

                clear()
                status, _ = post(port, "/hooks", payload,
                                 {"X-Hub-Signature-256":
                                  signature(payload).replace("sha256=", "")})
                ok("a bare digest with no sha256= prefix is refused",
                   status == 401, str(status))

                clear()
                upper = "sha256=" + signature(payload)[7:].upper()
                status, _ = post(port, "/hooks", payload,
                                 {"X-Hub-Signature-256": upper})
                ok("the same signature written in capitals still verifies",
                   status == 202, str(status))

                clear()
                status, _ = post(port, "/hooks", b"",
                                 {"__method__": "GET",
                                  "X-Hub-Signature-256": signature(b"")})
                ok("a GET is answered 405, and not 401 — the method is "
                   "checked first", status == 405, str(status))
                ok("and a GET does not reach the handler", not handled(),
                   "the handler ran anyway")

                clear()
                status, _ = post(port, "/hooks", payload,
                                 {"X-Signature": signature(payload)})
                ok("a signature in the wrong header is no signature",
                   status == 401, str(status))
            else:
                status, _ = post(port, "/hooks", payload,
                                 {"X-Hub-Signature-256": signature(payload)})
                ok("a build that cannot verify refuses everything with 503",
                   status == 503, str(status))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

        # A verified delivery that nobody is listening for must not be
        # answered 202: the sender would record it as delivered and never
        # send it again.
        if tls_here:
            port = free_port()
            proc = subprocess.Popen([receiver, secret, str(port), "NobodyIsListening"],
                                    cwd=d, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            try:
                wait_for_port(port)
                status, _ = post(port, "/hooks", payload,
                                 {"X-Hub-Signature-256": signature(payload)})
                ok("a verified delivery with no handler registered is a 500, "
                   "not a 202", status == 500, str(status))
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()

        # An empty secret: the receiver must refuse everything rather than
        # verify against a key anybody can guess.
        port = free_port()
        proc = subprocess.Popen([receiver, "", str(port), "OnPush"],
                                cwd=d, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            wait_for_port(port)
            status, _ = post(port, "/hooks", payload,
                             {"X-Hub-Signature-256": signature(payload)})
            ok("a receiver with no secret configured refuses with 503",
               status == 503, str(status))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

        # ── notify: what it builds, and nothing posted ───────────────────
        print("  -- notify, built and inspected; nothing is posted anywhere")
        r = subprocess.run([notifier], cwd=d, capture_output=True,
                           text=True, timeout=60)
        out_lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
        ok("a plain message is the document both services accept",
           out_lines and out_lines[0] == '{"text":"batch 41 finished"}',
           repr(out_lines[:1]))
        ok("a titled block carries both fields",
           len(out_lines) > 1
           and out_lines[1] == '{"title":"Batch 41","text":"1,204 rows posted"}',
           repr(out_lines[1:2]))
        ok("a dry run of each reports success and opens no socket",
           len(out_lines) > 3 and out_lines[2] == "1" and out_lines[3] == "1",
           repr(out_lines[2:4]))
        ok("a plain-HTTP webhook URL is refused even in a dry run",
           len(out_lines) > 4 and out_lines[4] == "0", repr(out_lines[4:5]))
        error_line = out_lines[5] if len(out_lines) > 5 else ""
        ok("and the refusal does not contain the secret part of the URL",
           "s3cret-part" not in error_line and "/services/" not in error_line,
           error_line)
        ok("what a caller should log instead keeps the host and drops the path",
           len(out_lines) > 6
           and out_lines[6] == "https://hooks.slack.example/<redacted>",
           repr(out_lines[6:7]))
        note("no request was made to Slack, to Teams, or to any other "
             "service: every notify case above is a dry run.")

    print()
    print("=" * 62)
    print(f"  {passed} ok, {len(failures)} failed")
    print("=" * 62)
    if failures:
        for f in failures:
            print("  - " + f[:300])
        print("  The messaging connectors are not sound. FAIL")
        return 1
    print("  The messaging connectors do what they say. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
