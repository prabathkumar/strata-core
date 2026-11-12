# Messaging and notification connectors

Three modules, for the three ways a program tells somebody that something
happened and the one way it is told back.

| | |
|---|---|
| `std/smtp.sta` | Send one plain-text mail to one recipient, by speaking SMTP. |
| `std/notify.sta` | Post a message into a Slack or Microsoft Teams channel through an incoming webhook. |
| `std/webhook.sta` | **Receive** a webhook: accept a POST, verify its signature, and refuse it if it does not verify. |

They need nothing but a socket and OpenSSL. There is no broker, no SDK, no
daemon and no library to install.

A fourth thing people expect here — Kafka and AMQP — is **not** in this
repository, and the reason is at the bottom of this page.

---

## Before anything: OpenSSL

All three lean on OpenSSL, through the same `foreign` door `std/tls.sta`
uses. The build turns it on when `pkg-config --exists openssl` answers yes,
and leaves it off otherwise.

Without it:

* `std/smtp.sta` still sends mail, and **cannot** do STARTTLS. A server that
  offers STARTTLS is talked to in the clear, and a password is then refused
  rather than sent — see below.
* `std/webhook.sta` cannot compute an HMAC, so it **refuses every delivery**
  with `503`. It does not accept them unchecked. Ask `webhook_can_verify()`
  at startup and log the answer; the module also says so on stderr the first
  time `webhook_serve` runs.
* `std/notify.sta` cannot post at all, because a webhook URL must go over
  HTTPS.

On Debian and Ubuntu that is `libssl-dev`; on a Mac, `brew install openssl@3`
and a `PKG_CONFIG_PATH` that points at it.

---

## `std/smtp.sta` — sending mail

```text
import io   from std;
import str  from std;
import os   from std;
import smtp from std;

int main() {
    int sent = smtp_send_mail(
        "smtp.example.com", 587,     // host and port
        "batch.example.com",         // what to put in EHLO
        "ops@example.com",           // user
        env("SMTP_PASSWORD"),        // password — a parameter, never read here
        "ops@example.com",           // sender
        "finance@example.com",       // recipient
        "Batch 41 finished",
        "All 1,204 rows posted.\nNothing was rejected.\n");
    if (sent == 0) {
        print(last_error());
        clear_error();
        return 1;
    }
    return 0;
}
```

It connects, reads the greeting, says `EHLO`, takes STARTTLS if the server
offers it, authenticates if a password was given, then `MAIL FROM`,
`RCPT TO`, `DATA`, `QUIT`.

**What it gets right that hand-written SMTP usually does not.**

* **A body line beginning with a full stop is escaped.** In SMTP a line
  holding one full stop ends the message, so a quoted paragraph, an ASCII
  table or a line of leaders truncates the mail — and the server still
  answers `250`, so the sending program reports success. `smtp_dot_stuff` is
  the fix and `test_suite/connectors_messaging.py` sends such a body through
  a real server and compares what arrives byte for byte.
* **Line endings are normalised to CRLF**, whichever kind the program built.
* **A header value carrying a CR or LF is refused before a socket is opened.**
  A subject somebody typed, carrying a line ending and a `Bcc:` of their own,
  is header injection and there is no escaping that makes it safe.
* **A subject that is not ASCII is RFC 2047 encoded**; one that is ASCII is
  left readable.
* **The certificate is verified on STARTTLS, and checked against the host.**
  There is no flag to turn either off. The capability list is asked for again
  after the upgrade, because the first one arrived in the clear and anybody
  on the path could have edited it.
* **A password is never sent over an unencrypted connection** unless the
  server is this machine. It is never logged and never appears in an error
  message: a refused login reports the server's code and the host, and
  nothing else.

**What it does not do.**

* One recipient. No Cc, no Bcc, no multiple `RCPT TO`.
* Plain text. No attachments, no HTML, no multipart.
* No implicit TLS on port 465 — STARTTLS on 587 or 25 is what it speaks.
* No connection reuse, no queue, no retry, no bounce handling, no DKIM
  signing, no SMTPUTF8, no `AUTH CRAM-MD5` or `XOAUTH2`.
* **A body line longer than 998 bytes is refused**, not sent. A server is
  entitled to truncate it and some do. Wrap the text first.
* **A `Message-ID` is not generated.** Most relays add one; a few do not, and
  a mail without one is more likely to be filed as spam.
* A body that is not plain ASCII is refused unless the server offered
  `8BITMIME`, because sending it anyway is how a message arrives with every
  accented letter replaced.

---

## `std/notify.sta` — posting to a chat channel

```text
import io     from std;
import str    from std;
import os     from std;
import notify from std;

int main() {
    str hook = env("STRATA_CHAT_WEBHOOK");
    int posted = notify_text(hook, "Batch 41 finished: 1,204 rows posted.", 0);
    if (posted == 0) {
        // Safe to log: the message names the host and never the URL.
        print(last_error());
        clear_error();
        return 1;
    }
    return 0;
}
```

The last argument is a **dry run**. Pass `1` and everything is built and
checked and no socket is opened — which is how a program is tested end to end
without posting into a channel full of people. It is the same function
production calls, so what a test exercises is the real path.

`notify_block(url, title, text, dry_run)` sends `{"title": ..., "text": ...}`.

> **Teams renders the title as a heading. Slack ignores it.** Slack reads
> only `text` from a payload this simple. That is not worked around by also
> pushing the title into the text, because Teams would then show it twice. If
> a line has to be seen on both, put it in the text.

**The URL is the credential.** There is no token, no signature and no second
factor: anybody who has that URL can post into the channel as your service
for ever. It arrives looking like an ordinary link, which is how it ends up
in a log line, a stack trace or a screenshot.

So nothing in the module prints it. `notify_redact(url)` is what to log:

```text
https://hooks.slack.com/services/T0/B0/xxxxx  ->  https://hooks.slack.com/<redacted>
```

A post is refused outright if the URL is not HTTPS, unless the host is this
machine. And when a service answers with an error, its message is repeated
back only after being checked for the URL's own path — a service that echoes
your request can otherwise hand the credential straight into your log.

**What it does not do.** No retries, no rate limiting, no queue — a chat
service that is down is down, and a library that retries behind your back
turns one incident into ten identical messages. No Slack Block Kit, no Teams
Adaptive Cards, no attachments, no threading, no mentions, no icon or
username overrides. Those are per-service JSON shapes that change without
notice; build the document yourself and hand it to `notify_post`, which takes
raw JSON for exactly that reason.

---

## `std/webhook.sta` — receiving one

This is the one with teeth. A webhook endpoint is a URL on the public
internet that writes to your data because somebody asked it to, and the only
thing between it and whoever learns the URL is a signature.

```text
import io      from std;
import str     from std;
import os      from std;
import webhook from std;

// The handler. `stream` is the language's named-handler mechanism, and the
// receiver dispatches to it by name — Strata has no function values, so the
// name is how a handler is passed.
stream OnPush(str payload) {
    print(str_cat(["a verified delivery of ", str(str_len(payload)), " bytes"]));
}

int main() {
    // 0 deliveries means "for ever". A positive number serves that many and
    // returns, which is what a test wants.
    webhook_serve(8099, env("HOOK_SECRET"), "OnPush", 0);
    return 0;
}
```

The sender computes HMAC-SHA256 over the request body with the shared secret,
writes it as hex, and sends `X-Hub-Signature-256: sha256=<hex>`. That is
GitHub's shape. The receiver computes the same thing and compares.

**What each request gets back.**

| | |
|---|---|
| `202` | Signed by the holder of the secret, and a handler ran. |
| `401` | No signature, or a signature that does not match these bytes. |
| `405` | Not a POST. Checked **before** the signature, so a scanner doing a `GET` is told the method is wrong rather than told about signatures. |
| `500` | Verified, and no handler is registered for that channel. Answering `202` would tell the sender it was delivered when it was not. |
| `503` | This build cannot verify, or no secret is configured. **Fail closed.** |

**Why the comparison is written the way it is.** `str_eq` stops at the first
difference, so the time it takes says how many leading bytes matched — and a
few thousand requests turn that into a valid signature, one byte at a time,
without the attacker ever learning the secret.
`bytes_equal_constant_time` always reads every byte. The length check is not
hidden and does not need to be: a signature's length is fixed and public.

**Replay.** GitHub's plain shape has **no replay protection**. A request
captured off the wire stays valid for ever, because nothing in what is signed
says when it was signed. That is the sender's format, not a shortcut taken
here, and it is a real gap. For a sender you control, use the other shape:

```text
int fresh = webhook_timestamped_ok(secret, timestamp, body, provided,
                                   now(), 300);
```

The signature covers `timestamp + "." + body`, so a captured request cannot
be re-sent with a fresher timestamp, and anything outside the window — in
either direction — is refused. `webhook_signature_at` is the sending half.

**What it does not do.**

* **No TLS on the listening side.** `std/http.sta` serves plain HTTP. This
  belongs behind something that terminates TLS.
* One connection at a time, no forking. A receiver that writes to a table
  wants its writes serialised anyway.
* **No de-duplication.** A sender that retries will deliver the same payload
  twice and both will verify. A handler that must not act twice needs its own
  idempotency key.
* No body larger than 64KB — that is what `http_read_request` will hold.
* **It does not parse Stripe's `Stripe-Signature` header**, which is
  `t=...,v1=...`. The computation underneath is the same; the header split
  would be the caller's three lines.

---

## Running the tests

```bash
python3 test_suite/connectors_messaging.py
```

It builds all three modules, runs their own `verify` blocks, and then:

* starts a real SMTP server on a socket, sends a message through it, and
  compares what arrives byte for byte — including a body line that is a
  single full stop;
* generates a certificate, has that server offer STARTTLS, and checks both
  that the client upgrades **and** that it refuses a certificate this machine
  has no reason to trust;
* starts the webhook receiver and posts at it with a correct signature, no
  signature, a wrong secret, a changed body, a signature in the wrong header
  and a `GET`, asserting the status of each and that the handler ran in
  exactly one of them;
* checks the chat documents and the URL guard **without posting anything** —
  every `notify` case is a dry run, and no request leaves the machine.

The modules' `verify` blocks also run under `strata test`.

---

## Kafka and AMQP, and why they are not here

Both were considered and both were left out.

`librdkafka` is not on this machine, and `rabbitmq-c` is here only as a
runtime shared object — `librabbitmq.so.4` with no headers, so there is
nothing to compile a `foreign` block against. Neither has a `pkg-config` entry.

A binding written against headers that are not installed cannot be built,
and one written against a broker that cannot be started cannot be tested. It
would compile on somebody's machine one day and be wrong in a way nobody had
run. The three modules above need a socket and nothing else, and every claim
on this page is checked by something that actually ran.

If a Kafka or AMQP connector is wanted, the thing to do first is put
`librdkafka-dev` and `librabbitmq-dev` on the build machines and a broker in
the test environment. The binding itself is an afternoon after that.
