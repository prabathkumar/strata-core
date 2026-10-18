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
| 23 `std/` modules: tls, llm, time, money, csv, fetch, http, auth, json, toml, postgres, cli, io, str, mem, os, ui, testing, metrics, telemetry, ml, simd_math, core | Work, with the limits written at the top of each file. |
| `strata deps` with path and git dependencies, `Strata.lock`, duplicate names refused loudly | Works, and is tested on every commit. |
| A test harness (`strata test`), a formatter (`strata fmt`), a repair tool (`strata repair`) | Work. |
| `docs/ECOSYSTEM.md` | A design note for a package registry. Nothing built. |

### Since built (items 1, 2 and 4 of the list below are done)

- **`std/time.sta`** — dates, borrowed from C's calendar rather than invented.
  A moment is seconds since 1970 UTC. `date_of` refuses the thirtieth of
  February instead of quietly returning the second of March, which is what C
  does on its own. `days_in_month` is worked out, not looked up.
  `start_of_next_month` exists because "add 30 days" is wrong eleven months a
  year. No time zones yet: everything is UTC, and that is written at the top of
  the file rather than left to be discovered.
- **`std/money.sta`** — an amount is a whole number of minor units, so a total
  is exact however many rows it has. Two roundings, because those are the two a
  business makes: a rate (half away from zero) and a split that cannot lose a
  cent (10.00 into three is 3.34, 3.33, 3.33). `money_parse` refuses thousands
  separators, currency symbols and three decimal places rather than guessing.
- **`std/fetch.sta`** — the other half of `http`: calling another service
  rather than answering one. Written rather than borrowed only because libcurl
  headers are not installable on the build machine. It refuses `https://`
  outright instead of pretending, and caps a body at 4 MB by refusing it rather
  than truncating it.
- **`std/tls.sta`** — a verifying TLS client, borrowed from OpenSSL through
  `foreign`. The certificate is checked and separately checked to be for the
  host asked for, and there is no flag to turn either off. A machine without
  OpenSSL's headers still builds everything; `std/tls.sta` compiles to a
  refusal that says why, rather than a link error nobody can act on.
- **`std/llm.sta`** — calling a language model over that connection, and not
  believing it. The pattern that makes this Strata rather than an HTTP client
  is in `docs/CALLING_A_MODEL.md`: ask for JSON, load it into a declared
  table, and a model that renames a field or invents one is refused the same
  way a supplier's CSV is.
- **`std/csv.sta`** — the file a supplier actually sends: quoted commas,
  doubled quotes, embedded newlines, CRLF, no final newline. `csv_row_ok` is
  the point of it — one damaged row is not a damaged file, so the reader says
  which row to set aside and keeps the rest.

### What is missing, in the order it hurts

1. **Sorting rows.** This turned out to be a *language* gap, not a library one.
   There is no `ORDER BY`, and a column cannot be projected out of a result
   except inside an aggregate, so a program cannot show the ten largest
   anything. It is now the biggest remaining gap and it is a syntax decision
   before it is code.
2. **Time zones**, on top of `std/time.sta`. Everything is UTC today.
3. **TLS on the SERVER.** The client has it now, through `std/tls.sta`;
   `std/http.sta` does not, so nothing it serves can face the internet
   without something in front of it. The same OpenSSL binding, the other way
   round: `SSL_accept` rather than `SSL_connect`, and a certificate and key
   to load.
4. **A decimal *type*, in the language.** `std/money.sta` covers the ledger
   case with whole minor units, which is the case that was losing pennies. A
   first-class decimal in the compiler is still the better answer and is still
   unbuilt.
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
