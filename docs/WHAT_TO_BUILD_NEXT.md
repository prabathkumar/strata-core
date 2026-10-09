# The ecosystem, and the small projects that prove the language is worth it

Two lists. The first is what a developer needs around the language before they
can get real work done without writing C. The second is small, finishable
projects whose only job is to make someone say "I could not have done that
this cheaply any other way."

None of this blocks Beta. Beta is gated on the pilots being clean, not on this
list. This is the work that comes after, and it is written down now so the
order is argued about before anybody starts.

## Part one: the ecosystem

### Rule one, and it decides everything else

Strata borrows **C**, and it borrows it through `foreign`, which the compiler
already type-checks across the boundary. Strata does **not** embed Python.

Why not, plainly: the one thing that makes Strata worth using is that a single
compiler checks the database, the rules, the web page and the phone screen
together. Embedding a Python interpreter puts an unchecked hole in the middle
of that. Everything that crosses into Python becomes "trust me", and the day
it becomes "trust me" the language is just another framework. CPython also
drags in its own runtime and its global lock, which breaks the one-process-per-
connection model `std/http.sta` uses.

Python still has a place: **at the edges, as a tool, not inside the program.**
A Python script that reads a C header and writes the `foreign` declarations for
you is a good use. A Python script running inside a Strata process is not.

### What already exists (so nobody rebuilds it)

| Piece | State |
|---|---|
| `foreign` blocks, type-checked both sides | Works. This is the door to every C library there is. |
| 17 `std/` modules: http, auth, json, toml, postgres, cli, io, str, mem, os, ui, testing, metrics, telemetry, ml, simd_math, core | Work, with the limits written at the top of each file. |
| `strata deps` with path and git dependencies, `Strata.lock`, duplicate names refused loudly | Works, and is tested on every commit. |
| A test harness (`strata test`), a formatter (`strata fmt`), a repair tool (`strata repair`) | Work. |
| `docs/ECOSYSTEM.md` | A design note for a package registry. Nothing built. |

### What is missing, in the order it hurts

1. **Dates and times.** There is no date type, no parsing, no formatting, no
   time zones. Every business program needs this in its first hour. Today you
   would reach for C's `strftime` through `foreign` and hand-roll the rest.
   This is the single biggest gap. Borrow the C library, wrap it properly, do
   not invent a calendar.
2. **An HTTP *client*.** `std/http.sta` is a server. A program that cannot call
   another service is not an enterprise program. Bind libcurl through
   `foreign`; do not write a client by hand.
3. **TLS.** The server has none, so nothing it serves can face the internet.
   OpenSSL through `foreign`. `std/unimplemented/tls.sta` is a placeholder.
4. **Decimal money.** Today money is a float, and a float cannot hold 0.10
   exactly. A ledger that uses floats will eventually be a penny out and nobody
   will know why. This may want to be a language type, not a library, which
   makes it the one item on this list that touches the compiler.
5. **A C header to `foreign` generator.** A Python script that reads a header
   and writes the declarations. This turns "bind a C library" from a day into a
   minute, and it is the multiplier that makes items 1 to 3 cheap for everyone
   else too.
6. **Crypto beyond `crypt(3)`.** Random bytes, hashing, HMAC, signing. Bind
   libsodium or OpenSSL. Do not write any of it.
7. **Structured logging** that agrees with `std/telemetry.sta`, so a running
   program can be read.
8. **A package index.** Last, not first. A registry with nothing in it is a
   website, not an ecosystem. It is worth building once items 1 to 6 exist and
   somebody outside the project wants to publish the seventh.

### What to deliberately not do

- No ORM. Tables are in the language already; a layer over them is a layer
  over the thing that works.
- No async or green threads. One process per connection is honest, debuggable,
  and enough for the systems this is aimed at.
- No second syntax for configuration, templating or queries. One language was
  the whole promise.

## Part two: the small projects that prove the point

The claim being tested is narrow and should stay narrow: **change one thing in
one place, and the compiler finds every consequence, across the database, the
rules, the web page and the phone, before the program runs.** Every project
below is chosen because it either demonstrates that or it does not belong.

### Already built (use these, do not rewrite them)

- **`apps/orders`** — web, rules, data and an operations journey. The rename
  test on it is the single most convincing thing in the repo: rename a column
  and eight errors appear, naming the three files that cared.
- **`apps/orders_mobile`** — the same model on iPhone and Android.
- **`apps/ledger`** — double-entry with an ageing report.
- The public demo site.

### Worth building, in order of how convincing they are per day of work

1. **Payroll run, one screen and one report.** Rates, hours, deductions,
   payslip, a monthly total. Then change the deduction rule and show that the
   report, the screen and the stored table all refuse to compile until they
   agree. This is the most boring possible program and that is exactly why it
   lands with a development manager.
2. **Stock and reorder.** Items, movements, a reorder level, a page that lists
   what to buy. Demonstrates the thing people get wrong in spreadsheets, and a
   schema change (split one warehouse into two) is a perfect rename test.
3. **An approvals workflow.** A request, a chain of approvers, a state it can
   be in. Add one new state and show the compiler listing every place that has
   to handle it. This is the one that sells the language to an architect,
   because in every other stack adding a state is a grep and a prayer.
4. **A CSV importer that refuses bad data.** Reads a supplier file into a
   table, and the refusal cases are the demo: wrong column, extra column,
   renamed column. The compiler and the loader are already strict about this;
   this project just makes it visible.
5. **A small internal directory with login.** People, teams, a session, a
   password. Proves `std/auth` and `std/http` hold up together, and is the
   smallest thing that looks like a real internal tool.
6. **A read-only dashboard over an existing PostgreSQL database.** Points
   `std/postgres` at a database somebody already has. This is the one that
   answers "do I have to throw away what I've got?" with no.
7. **The reconciliation job.** Two files, one answer, a list of what does not
   match. No UI at all. Proves the language is usable for the batch work that
   is most of what enterprise software actually is.

Numbers 1, 3 and 6 are the three to build first if only three get built. Each
is roughly a day. Each ends with a demonstration that is a single change and a
screen full of errors that are all correct.

### How each one should be presented

Not as a code sample. As a short recording of the same two minutes: here is the
program working; here is one change; here is the compiler listing everything
that change broke, in four files and on a phone; here is the fix; here it works
again. If the recording needs narration to be impressive, the project was the
wrong one.
