# Changelog

## Unreleased

### The same rules run on the server and on a phone

The rules compile for a phone's processor, and — run under emulation — give
byte-identical answers to the server build. That is the check worth having:
"it compiles for ARM" and "it gives the same answers on ARM" are different
statements and only the second one matters.

One definition of "an order over 1000 gets 5% off", running on the server, the
website and the handset. The classic source of "the app says one price, the
site says another" is not a bug in either — it is the same rule implemented
twice. There is only one implementation here.

### A phone screen, described in Strata and drawn by Strata

`std/ui.sta`. A screen is an ordinary Strata table of things to draw:
rectangles, runs of text, regions that answer to a finger. Being a table means
the host can read a screen with the same queries as any other data, and
`strata test` can assert what a screen contains with no phone anywhere near it.

`apps/orders_mobile` is the orders list, against the same `Order` table the web
service uses. `journey_mobile.py` asserts the display list, where taps land —
including that a tap on nothing is nothing — and the actual pixels of the
painted image.

**Screens are drawn, not borrowed**, and that is the decision the whole thing
rests on. Asking each platform for its own widgets means two binding layers of
thousands of functions each, sharing nothing, one of them (Apple's) not
designed to be driven from C at all: two projects that never finish and never
quite match. Painting means one implementation plus a shell per platform small
enough to read in a sitting. It is what Flutter does, and why a Flutter screen
looks the same on both.

The rasteriser is a `native` block rather than a compiler target. A new output
target has to be written twice, once in each code generator, and kept
byte-identical — the right price for a language feature and the wrong one for
finding out whether an idea works.

### What has not happened

Nothing has run on a handset. `apps/orders_mobile/android/` holds 96 lines of
Kotlin that open a canvas, paint the display list and forward taps; it is
written against the documented APIs and has never been built with the Android
SDK. Reviewed design, not tested code, and its README says so. iOS has no
shell at all.

One screen is not an app. Scrolling lists, text input, keyboards, navigation
and a layout engine are all missing, and that is the work that turns this into
something a business app can be built with.

### A colour that was wrong

The language has no hex literal, so every colour in the mobile app is a
hand-converted decimal. The first one was wrong — `0x1F4E62` became `2050146`
rather than `2051682` — and the screen rendered green instead of teal. The
pixel check in `journey_mobile.py` caught it; nobody looking at the picture
did. Hex literals are now on the roadmap.

### A failed save used to look exactly like a successful one

`save` and `load` were statements with no value. The machinery underneath has
always known whether the write happened — it returns success or failure — and
the language threw the answer away.

Pointed at a database that was not there, a program logged the connection
error, printed "order recorded", and exited 0. In the orders service that
meant a customer saw "order created", the order was nowhere, and only the log
knew.

All three storage words answer now:

```
if (save Order to url) { ... } else { ... }
int pruned = delete Session <- [expires_at < now];
```

`save` and `load` give 1 when the store matches memory and 0 when it does not.
`delete` gives the number of rows removed, because a delete that matched
nothing is not a failure, it is a zero.

They remain statements where the answer is not wanted, so every existing
program is unchanged and every existing syntax tree is identical. The
statement and expression forms are parsed by one function in each parser, so
the two shapes cannot drift apart.

`apps/orders` uses it: a create or close whose write did not happen now
answers 503 saying the order was not created, rather than redirecting as
though it had been. `journey_operate` proves this against a store that
genuinely cannot be written — the first attempt used a read-only file and
proved nothing, because these suites can run as root and root writes through
a read-only bit.

### An expression the generator had no rule for became the literal `0`

Found immediately, by the change above: the first version of
`if (save Order to url)` compiled to `if (0)`. No diagnostic, no warning — the
branch was simply always false.

Statements have raised on an unhandled node since the `for ... in` incident.
Expressions now do the same, in both generators. `str ok = save T to "p";` is
also E001 now, because the type checkers know these are int.

### A table stopped storing rows at 4,096 and said nothing

Every `database` block kept its rows in a fixed array of 4,096. An insert past
the end was skipped — no error, no message, exit status zero — and a load of a
larger file dropped the remainder on the floor. A program asked to store five
thousand rows held four thousand and ninety-six and reported success.

This was data loss with no symptom. A service would run correctly for months
and then quietly stop recording anything, and the first anyone would know is a
customer asking where their order went. It also made the PostgreSQL backend
largely pointless: connecting to a database is not much use if the program can
only ever see four thousand rows of it.

Tables grow now, by doubling, and the only limit is memory. Running out of
memory with a row in hand stops the program with a message naming the table,
because the caller asked for the row to be stored and it is not stored, and
returning quietly is the bug this replaces.

Three conformance tests cover it, deliberately just over the old limit so that
a reintroduced cap of any size is caught rather than only an obvious one.

### A load can fetch part of a table

```
load Order from "$DATABASE_URL" <- [status == "OPEN" && region == "apac"];
```

The same query syntax the language already uses, now allowed on a load.
Against a database it becomes a `WHERE` clause and only matching rows cross
the wire; against a file the rows are read and then dropped. The program means
the same thing either way, which is the property worth protecting.

Only conditions that mean the same thing in both places are translated:
comparisons between a column and an integer or string literal, joined by `&&`
and `||`. Anything else falls back to loading and filtering in memory. Float
literals are declined on purpose — this generator holds the parsed number and
the one written in Strata holds the text it was written as, and there is no
representation both are guaranteed to print identically, so `1.50` and `1.5`
would have been two different WHERE clauses from one source file.

`save` takes no filter. A partial save would mean the store no longer matches
memory, which is the one thing `save` promises.

Found while building it, by a fixture written specifically so the differential
would cover the new syntax: a filtered load left the table claiming to hold
the whole file, so the next unfiltered load decided it had nothing to do and
returned the filtered rows. The stamp is cleared after a filtered load now.

### A save writes only what changed

A save emptied the Postgres table and wrote every row back. Change one order
in fifty thousand and fifty thousand rows were written, which is not something
anyone would deploy.

`save` still means what it always meant — make the store match memory. What
changed is that the store is now told only the difference. Each table
remembers, per row, its key and a fingerprint of its values as they stood at
the last read or write. A row whose fingerprint still matches is not sent, a
key that has gone from memory is deleted, and everything else is an upsert,
all inside one transaction.

Measured by a trigger inside the database counting every write the table
actually receives — seeding 200 rows, re-saving unchanged, changing one row,
removing one row:

| | before | now |
|---|---|---|
| inserts | 800 | 200 |
| updates | 0 | 1 |
| deletes | 600 | 1 |

The sharp edge, stated rather than left to be found: a save that follows a
load writes the difference; a save with **no** prior load from that URL
replaces the table, because a process that has not read the table cannot know
what else is in it, and quietly leaving other people's rows behind would make
`save` mean different things depending on history. Both halves are checked.

The first column is the key when it is an integer — the convention every
`database` block in this repository already follows. A table whose first
column is not an integer keeps the whole-table replace rather than having the
compiler guess at a key. A table created by the previous version has no
primary key, so one is added when the table is next written; doing it in SQL
keeps it idempotent and one round trip.

### One connection per process, not one per query

Every save and every load opened its own connection: a TCP connect, a password
exchange and a teardown around a query taking under a millisecond.

The connection is now opened once and kept. The process id is part of its
identity, and that is not a detail — a service that forks per request would
otherwise have parent and child writing down the same socket, which corrupts
the protocol for both. A child finds the pid does not match, abandons the
inherited handle without speaking on it, and opens its own.

Seventeen saves and loads now open one connection, counted by PostgreSQL's own
session tally rather than a stopwatch.

A transaction left open by a failed save used to hold its locks until the
process exited; every path out of a save that is not a commit now rolls back.

### A table can live in PostgreSQL

Strata stored data in tab-separated files. That is honest for one small
service on one machine, and it is the first thing anyone evaluating the
language asks about, so the answer could not stay "files".

Importing one module is the whole switch:

```
import postgres from std;
...
save Order to "data/orders.tsv";      // a file
save Order to "$DATABASE_URL";        // a table in PostgreSQL
```

The path decides which store is used. The schema, the queries, the aggregates
and the pages are untouched, and the compiler still checks every column name
against the `database` block — which is the property the whole language is
built around, now holding across two different stores.

Three decisions worth stating rather than leaving to be inferred:

**No new syntax.** A program moves between a file and a database by editing a
string. Adding `database Order backed by postgres { ... }` would have made the
storage part of the schema, and then moving a table would mean changing the
declaration every query is checked against.

**`$NAME` in a path is an environment variable.** Without it the only path a
program could give was a string literal, so a Postgres URL — password included
— would be compiled into the binary and committed. It applies to file paths
too.

**Postgres is compiled in only when asked for.** Importing the module is what
links libpq, and linking libpq is what defines `STRATA_POSTGRES`, which is
what turns on the database branch inside every generated `save` and `load`. A
program that does not import it carries no libpq dependency and no dead code.
`journey_postgres.py` runs `ldd` on both kinds of binary rather than asserting
this from the source.

Values are sent as parameters, not concatenated into SQL. A customer called
O'Brien is a customer.

### What this is not

A save replaces the whole table inside one transaction; a load reads all of
it. That is exactly what `save` and `load` have always meant in Strata, and
keeping the meaning identical across stores matters more than the cost — but
it is right for thousands of rows, not millions. Per-row writes are a language
change, not a driver change. Each save or load opens its own connection; there
is no pool. And the load-skip added earlier does not apply to a database,
because a file has a modification time to compare against and a query does
not.

CI now runs a real PostgreSQL 16 as a service container. The journey skips its
database half when `STRATA_TEST_DB` is unset rather than passing quietly, so
the skip cannot become the normal result without somebody noticing.

### Somebody else can install it

`tools/install.sh` copies a self-contained toolchain into `~/.strata` and puts
a `strata` on `~/.local/bin`. Until now, using Strata meant cloning the
repository and running `./bin/strata` from inside it — fine for whoever wrote
it, and not a thing you can ask a team to do: no command on their machine, no
version to pin in a Dockerfile, no way to have two versions on one box.

The install does not point back at the checkout. `journey_install.py` deletes
the source tree it installed from and builds a project again, because an
install that quietly depends on the clone is an install that breaks the first
time somebody tidies up.

The installer checks for a C compiler before copying anything, and finishes by
creating and building a throwaway project outside the source tree. If that
fails it exits non-zero instead of printing "installed".

Three things that check found, in the order it found them:

  - `strata new` had an unquoted heredoc delimiter, so bash ran the backticked
    `` `src/schema.sta` `` in the README template as a command. Every project
    ever created printed an error and got a README with its backticks eaten.
  - The first installer shipped `fmt.sta` but not the compiler's other Strata
    sources, so `strata fmt` on an installed toolchain could not build its own
    formatter.
  - `strata fmt` cached that formatter under the install root, which a user
    who did not run the installer cannot write to. It falls back to the user's
    cache directory now.

### The editor shows what the compiler knows

`editor/vscode-strata`: syntax highlighting for `.sta`, and the compiler's
diagnostics underlined where they happened, as you type.

It is not a language server, on purpose. `strata check` is fast and is the
same check CI runs, so the extension runs the real compiler rather than
reimplementing the rules in JavaScript — a second implementation would be the
first thing to drift out of step with the first. If the editor and the build
disagree, the extension is wrong.

Inside a query a bare name is a column, not a variable, and the grammar
colours it differently. That is the difference between reading
`[token == token]` as a comparison and seeing it for the bug it is. E007 is
painted as information rather than an error, because an editor that paints
advisories red teaches people to ignore red.

The parser that turns compiler output into diagnostics is a separate file with
no dependency on the editor API, so it is tested by running node — against
output the compiler produces during the test run, not a pasted sample.

### The formatting check runs before the commit, not after the email

Commit `f424196` went up with an unformatted `std/metrics.sta` and turned CI
red. Eighteen test suites had passed first, because none of them check that
the files in the repository are formatted — `test_suite/fmt.py` checks that
formatting preserves meaning, which is a different question.

`tools/git_checkin.sh` now refuses a commit whose staged `.sta` files are not
canonically formatted, and names them. A check that only exists in CI is a
check that finds things after somebody has already been emailed about it.

### A service can be asked how it is doing

Until now a Strata service printed one line per request and nothing else. If
it was slow, or answering some requests wrongly, or turning people away, the
only way to find out was to read every line as it went past. That is not
something anyone can run a business on.

`std/metrics.sta` is new: counters for requests answered, split by outcome,
how long they took in buckets, the slowest one seen, connections refused, and
uptime. The orders service answers two pages from them, neither of which needs
a sign-in:

    /health    ok, uptime, request count
    /metrics   the counters, one `name value` per line

The format is what Prometheus scrapes and also what a person can read over
someone's shoulder, which is why it was picked over JSON.

The interesting part is where the counters live. The service forks a process
for every connection, so a counter in an ordinary variable would be added to
by a child that then exits — every reading would be zero. These live in a page
of memory mapped `MAP_SHARED` before the first fork, so every child adds to the
same numbers. The additions are atomic: without that, two children finishing
at the same instant lose one of the two counts, rarely enough to look correct
in testing and wrong in production.

Connections refused because every slot was taken are counted separately from
5xx responses. One is running out of capacity, the other is a handler getting
something wrong, and a single number for both hides the first behind the
second.

If the shared page cannot be mapped, every call returns zero and the service
carries on serving. A watcher that can take the service down with it is worse
than no watcher.

### Failed requests are written where someone will find them

A request that returns 400 or worse now also writes one line to stderr:

    ERROR ts=1789461532 method=POST path=/orders status=403 took_ms=4

stdout is a stream somebody watches; stderr is where a container runtime, a log
collector and a person reading a crash all look first. A failure buried in a
thousand successful lines is a failure nobody finds. `key=value` because a log
search can filter on it without anyone writing a parser, and it still reads
fine without one.

`journey_operate` grew from 23 checks to 34. Among them: the counters keep
climbing across the process that did the work, the latency buckets add up to
the total, a refused write produces a failure line, and a request that worked
produces none.

### What this still is not

The counters are in memory in one process tree. They start at zero when the
service restarts, and two copies behind a load balancer each report their own.
Nothing stores or graphs them. That is a scrape target, not a monitoring
system, and it is stated here rather than discovered later.

### A table no longer re-reads a file it has already read

`load` used to open, parse and rebuild the whole table every time it was
called. The orders service calls it on every request, so the cost of answering
a page grew with the amount of data on disk even for pages that show none of
it — a dashboard with no orders on it still paid for two thousand rows.

Each table now remembers which file it last read and that file's modification
time (to the nanosecond) and size. If both still match, `load` returns
immediately. A service that forks per connection inherits the parent's tables,
so the reload becomes one `stat()` — and `save` records the same stamp, because
a process that just wrote the rows does not need to read them back.

Measured on the same machine, 2000 orders on disk: 220 → 742 req/s with one
client, 801 → 2368 req/s with four. The file, not a timer, decides: another
process writing the table changes its modification time and size, and the next
`load` sees that and re-reads.

The limit, stated rather than discovered later: this is right for one service
on one machine. Two machines writing the same file over a network share, where
metadata lags, can leave a stale table in memory.

### The performance numbers I published were the test client's, not the service's

The repository said concurrent throughput came out *below* sequential, and
explained it by the reload above. Both halves were wrong. The load generator
was eight Python threads sharing one interpreter and one HTTP library; it
capped near 400 requests a second no matter what the service did, and that cap
was written down as a fact about Strata. And the reload, once actually timed,
cost 0.09 ms at 20 rows and 2.8 ms at 2000 — real, but not what the figure was
measuring.

`journey_survive` now drives load from separate processes on raw sockets, and
the sequential figure is labelled as what it is: one Python client's round
trip, turned round. README, PLAN and STAGES are corrected where they made the
claim.

### E008 was reported twice, and I had said why wrongly

`[token == token]` — the shape that made the rule necessary, because it
compares a column with itself and matches every row — has the ambiguous name on
**both** sides. The check walks both sides of a comparison, so it reported the
same mistake twice.

I had written that this was "a diagnostic from an imported module is reported
twice". That was wrong, and I had not checked it. An error in an imported
module is reported once; the duplication had nothing to do with imports. The
claim is corrected where it was made rather than quietly dropped.

Reported once per name per position now, in both type checkers. Two different
ambiguous names on one line still give two diagnostics, which is right.

### `const` — the language has named constants

```
const int   LOCKOUT_AFTER   = 5;
const float TOLERANCE       = 0.005;
const str   SERVICE_NAME    = "orders";
```

Every constant in this repository used to be a function returning a literal —
`int lockout_after() { return 5; }` — because there was nowhere else to put
one. That works and reads like an apology, and I wrote it twice while building
the two applications.

Deliberately a constant and not a module-level variable: it cannot be assigned
to (E001), so it cannot become shared mutable state in a service that serves
each connection in its own process. Its value is checked against its declared
type at the declaration rather than at the first use, it may be written in
terms of a constant above it, and it crosses a module boundary like any other
name — the constant belongs in the module that owns it, which is where anyone
would put it.

Constants are emitted before every other declaration, so a layout written above
one still sees it. "It depends where you put it in the file" is not a rule
anyone should have to learn.

`apps/orders` and `apps/ledger` use them now: the lockout window, the
connection cap, the session length, the request timeout and the money
tolerance are all named values instead of functions or repeated literals.

`const` is contextual, like `save` and `delete`, so it remains usable as an
ordinary identifier.

### The first hour

What a developer runs before deciding whether to keep going, made to work.

**`strata check` did not resolve imports.** `strata build` compiled
`apps/orders/src/rules.sta` without complaint while `strata check` reported
sixteen errors for it, because it checked the file with no idea what a
`database Order` was. A checker that disagrees with the compiler is worse than
no checker: the first thing a newcomer runs told them their code was broken
when it was not. It now resolves imports exactly as the build does, and treats
E007 as the advisory the taxonomy says it is rather than a failure.

**`strata new` generated a project whose tests said "0 passed"** — it generated
no tests. It now writes `tests/items_test.sta` with two blocks that pass, and a
README listing the six commands, every one of which is checked to exist.

Fixing the checker immediately found four examples importing modules
`from hub`, a registry that has never existed. Because an unresolvable import
disarms the undefined-call rule, the fake import was also hiding a call to
`extract_json_int`, which nothing defined — for as long as the two stood next
to each other. The imports are gone, and `std/json.sta` gained the one reader
it needs: pull an integer field out of a flat envelope, absent meaning zero,
with its limits written down.

`test_suite/first_hour.py` runs all of it — 22 checks, including that renaming
a column in a freshly generated schema breaks the build at the line that used
it.

### The claims audit

Every document, config and stub in this repository was read and checked
against something that runs. What could not be backed is gone.

**The lockfile was the worst of it.** `Strata.lock` declared dependencies
`crypto 2.4.1` and `telemetry 0.9.5` from a `registry+hub` that was never
built, with checksums reading `UNVERIFIED-no-checksum-has-been-computed` — and
spliced into the middle of the file, a shell script that appended a fake
package manager to `bin/strata`, printing "Fetching package 'crypto' v2.4.1
from corporate hub" and "Dependencies successfully locked, verified, and
extracted" while doing nothing. The root `Strata.toml` already said the
registry did not exist, contradicting its own lockfile.

Also removed: a submodule gitlink with no `.gitmodules`, so a clone got an
empty directory; a Kubernetes manifest deploying an image that was never
published, commented "Strata runs on 4KB Fibers"; Terraform never applied; two
deploy scripts and a test runner that printed success without working; twelve
tools in `bin/unimplemented/` that did the same; a stub service with a
fabricated `Strata.toml`; and four manuals describing a 5-year LTS programme,
a C-level architecture board and a one-day workshop, for a language whose
first application was written the day before.

**`LANGUAGE_SPECIFICATION.md` is rewritten against the grammar the compiler
actually has.** The old one described `stream` as an asynchronous channel on a
fiber — it is an entry in a dispatch table, and the syntax given for it did not
parse — `layout` as compiling to WebAssembly Text when it writes HTML, `render`
as producing PDF when it writes Markdown, and `assert` as a compile-time check
when it runs at run time. It now ends with what the language does **not** have,
because the absence of module-level variables, a date type, grouping, and a
package manager is load-bearing. Examples compiled by CI went from 11 to 15.

**`strata repair` now exists.** The README's opening example — the first code
block anyone reads — showed a command the toolchain did not have. Adding it was
the better fix than deleting the example.

Smaller corrections: version strings reconciled (`v1.0.0` to `0.4.0-alpha`),
`Strata.toml` stripped of keys nothing reads, the README's stale rows brought
up to date, `RELEASE_NOTES.md` regenerated from live runs (it still claimed
conformance 64/64; it is 182/182), `NEXT_STEPS.md` retired for claiming
module-level state the language does not have, and the editor grammar taught
the rest of the keywords.

**A CI step, `No Unbacked Claims`, fails if any of this comes back.** It caught
two things on its first run: this changelog's own predecessor text quoting the
old specification verbatim, and a quarantined example. The quarantine
directories are excluded — their READMEs say plainly that nothing in them
works, which is the honest way to keep code that describes a runtime nobody
built.

### `delete`, and a repair loop that needs no API key

**`delete T <- [cond];`** — the write the language did not have. Contextual
like `save` and `load`, so the word stays available as an identifier. The
condition is a query condition and is checked as one: a column that does not
exist is E004 here too, and a bare name that is also a variable in scope is
E008. Parser, both type checkers, both code generators, with the emitted C
still byte-identical between them.

Rows are moved down and the count reduced; the row itself is not freed,
because a list a query returned a moment ago points at the same rows and this
language has no way to know. A leak is a better bug than a dangling pointer.

`apps/orders` uses it: signing out removes the session row instead of setting
`expires_at` to 0 and leaving it forever, and expired sessions are pruned
whenever a new one is created. Every sign-out used to grow that table by a row
nothing would ever read again.

**The repair loop can use a Claude subscription.**
`ai_self_repair.py --backend claude` drives `claude -p`, the non-interactive
mode of the CLI a developer already has signed in. No API key to provision,
store or rotate — which is the difference between a demo that gets run and one
that does not.

It has now been run, which the model-backed path never had been. On E008 — the
auth bypass, where `Session <- [token == token]` matches every row — the
deterministic backend produced no change and stopped, correctly, because the
fix is judgement rather than a lookup. The Claude backend renamed the parameter
and its use; the program built and a forged token stopped authenticating.

Running it found a hole in the backend: a CLI that is installed but not signed
in prints a sentence and exits 0, and the loop wrote that sentence over the
file and called it a repair. An answer that is not a program is a failed call
now, for both model-backed backends.

### The serialisers generated invalid C, and only some compilers said so

CI failed at the parser differential on a commit whose suites were all green
locally. The cause: `save` and `load` are generated for **every** table, and
they assumed every column is a scalar. `database P { TokVec toks; ... }` — the
parser's own state — produced

    case 0: r->toks = (strata_int)atoll(buf); break;

an integer assigned to a pointer. gcc 11 warns. clang 16+ and gcc 14 reject
it, so the compiler built on the development machine and failed on the runner.

Two fixes, and the second matters more:

- **Only scalar columns are written and read.** A record-typed column is a
  pointer into this process and means nothing in a file, so it is not in the
  header and not in the loader.
- **The C flags now make the strict compilers' errors errors everywhere**:
  `-Werror=int-conversion`, `-Werror=incompatible-pointer-types`,
  `-Werror=return-type`. The backend C compiler is part of the toolchain, and
  the toolchain must not depend on which one happens to be installed. The
  development machine has gcc 11 and no clang; the runner has clang. That is
  the whole reason this reached CI, and it is why "all suites green" needs to
  mean the same thing in both places.

### Stage 10 closed: the service can be operated

Four things it could not do, and now can.

**It says what it is doing.** One line per request on stdout, as it happens:
`GET /login 200 3ms`. No levels, no format to configure — a service nobody can
see is worse than one with a format somebody dislikes. Every response helper
returns its status code rather than 1, because a log line needs the status the
handler actually chose.

**A form from somewhere else is refused.** Each session carries a second random
token that is never sent as a cookie; every form renders it and every write
checks it. A signed-in operator's browser could be made to post to this service
by any page on the web, and nothing distinguished a form this service rendered
from one that merely pointed at it. `journey_orders` now reads the token off
the page the way a browser does — a test that could still post without one
would have meant the protection was not real.

**Guessing a password stops working.** Five failures lock an account for five
minutes. The lockout is checked before the password and answers identically
whatever was typed, so it does not tell an attacker which usernames exist. It
lives on the user row rather than in a table of attempts, because the language
has no `delete` and a table of attempts would grow for as long as someone was
attacking it.

**A flood is refused rather than forked.** 64 connections at once; the 65th is
answered 503. That meant counting children, which meant taking `SIGCHLD` back
from `SIG_IGN` — and that brought zombies back, because the parent only reaped
when the next connection arrived, which is never while idle. The listening
socket now has a one-second timeout and the loop reaps at the top of each pass.

A module-level `int LOCKOUT_AFTER = 5;` in the rules module does not parse and
took the rest of the file with it. Constants are functions here, which is the
existing gap rather than a new one.

### Stage 9 closed: the real image builds outside CI

`strata-orders:real` — 216 MB, Ubuntu 24.04, both stages of the actual
Dockerfile: apt installs the toolchain, the service is compiled, `strata test`
runs **inside the image that ships**, and the runtime stage carries the binary,
its data and libcrypt. It runs as uid 10001, logs its startup line, serves the
sign-in page, signs in, creates an order, and redirects a signed-out request.

The base moved from `debian:bookworm-slim` to `ubuntu:24.04`, because no
container registry is reachable from the development environment and an Ubuntu
root filesystem can be bootstrapped from the archive and imported under that
tag — `deploy/bootstrap_base_image.sh`. A Dockerfile only CI can build is a
Dockerfile nobody has read. The bootstrapped base is the same release from the
same archive rather than Canonical's published image bit for bit, so CI stays
the authority on the published base.

The first build failed on something real: **`stage0.py -o build/orders` did
not create `build/`**. The linker's error for a missing output directory is
"cannot open output file", which reads like a permissions problem and is not
one. `strata build` had a `mkdir -p` of its own, so the compiler was only ever
missing it when invoked directly — which is exactly what a Dockerfile does.

### A second application, and what it cost

`apps/ledger` — invoices and what has been paid against them. A command-line
tool that also answers JSON: no pages, no forms, no session, no HTML, a
`report` block, and an import that reads a file rather than a request. It
exists to answer one question: is this a general-purpose language, or a
language shaped by `apps/orders`?

It works. `test_suite/journey_ledger.py` walks 19 steps. Five things had to be
built or fixed first, and all five were invisible from the first application:

- **`std/cli.sta`.** A Strata program could not read its own arguments. Every
  tool in this repository, the compiler included, opens `main` with a `native`
  block declaring `extern char** __strata_argv` and then works in C. That is
  not a language with command-line programs; it is C with Strata in it.
- **`for Row in rows` in a function body.** It parsed only inside a layout,
  and the code generator had no rule for it anywhere else — so it emitted
  nothing, and the loop compiled, linked, ran and silently did nothing.
  Fixed in the parser and both back ends. **An unhandled statement is now an
  error**: silence is the worst answer a compiler can give.
- **`std/json.sta`.** Escaping for JSON is not escaping for C — a literal
  newline is invalid inside a JSON string, and so is any control character.
- **`char_from_code` moved from `std/http.sta` to `std/str.sta`**, so writing
  JSON no longer means importing an HTTP server to get at a string helper.
- **`render X to "path"` takes a literal, not an expression.** Recorded
  rather than worked around: `ledger report` does not take a filename,
  because it cannot honour one.

E008 caught the same mistake twice in new code within a minute of it being
written — a query comparing a column with a parameter of the same name.

Two smaller things this turned up and did not fix: `strata check <file>` does
not resolve imports the way `strata build` does, and a diagnostic from an
imported module is reported twice.

*(Corrected on 15 September: the second half of that sentence was wrong. An
error in an imported module is reported once. What was duplicated was E008
specifically, and for a different reason — see below.)*

### The image has now been built and run

`deploy/build_scratch_image.sh` compiles the service, collects exactly what
`ldd` says it links against, builds a `FROM scratch` image, runs it, and asks
the container for a page. It is 5.35 MB, it serves `/login`, and a sign-in and
an order both work through it.

This exists because no container registry is reachable from the development
environment, so the two-stage Dockerfile at the repo root — which pulls
`debian:bookworm-slim` — is built by CI and could not be built here. The
script proves the half that does not need a registry: the binary, its data and
three shared libraries are enough to serve.

Running it found something reading it could not. **`docker logs` was empty.**
A C program whose stdout is a pipe gets a 4KB block buffer, so the line the
service prints at startup sat in libc and would have stayed there until the
process exited — a service that looks dead to anyone watching it. The runtime
preamble line-buffers stdout and unbuffers stderr from before `main` now, and
`journey_survive.py` asserts that the startup line reaches a pipe.

### Journey C: the service survives contact

The server served one connection at a time, had no timeout, and died on
SIGPIPE. A client that opened a socket and said nothing held every other
client indefinitely; a client that closed its browser mid-response terminated
the process.

- **A process per connection.** `http_fork` after `http_accept`; the child
  serves and `_exit`s. `http_reap_children` keeps them from accumulating as
  zombies, and `http_ignore_broken_pipes` keeps an abandoned page load from
  taking the service with it.
- **A receive timeout**, 5s. A request that never finishes arriving now comes
  back as an empty string and is answered 408. It used to come back as
  whatever bytes had arrived, which looked like a real request with a strange
  path.
- **`lock_shared` and `lock_exclusive`.** The children share nothing but the
  filesystem. A GET takes the shared lock and is served in parallel; anything
  that can write takes the exclusive one, across reading, changing and saving
  the table.

The lock is not a precaution. With it removed, ten concurrent creates against
a thousand-row table leave **856 rows, hundreds of them all-zero** — two
processes writing the same file at once. The test was written first against an
empty table, where it passed without the lock and proved nothing; a thousand
rows is what makes the window wide enough to observe.

**Measured, on a 4-core development machine:** dashboard p50 2.2 ms / p95
2.6 ms over 20 rows, 15 ms over 2000; ~445 req/s sequential; ~380 req/s and
p95 32 ms over 8 concurrent clients.

Concurrent throughput below sequential is the finding, not a rounding error.
It is not the lock — reads take a shared one. Every request forks and reloads
all three tables from disk. What the process per connection buys is that one
slow or hostile client cannot hold the others.

`test_suite/journey_survive.py` walks 18 steps and prints the numbers rather
than claiming them.

### Journey B: a developer can change the system

A schema change is the most common change there is, and it did not break the
build. Adding a column to a `database` compiled fine, and every insert in the
program wrote the new column as a zero or an empty string, in every row, with
nothing to say so. **E009** is that error: an insert must name every column.
It is what gives "add a column" a build failure to be repaired.

It found one on the way in. `std/telemetry.sta` had been omitting `trace_id`
since it was written, so every snapshot it recorded carried trace 0.

Everything else in this entry exists because the journey needed it:

- **The repair loop works over a project.** `ai_self_repair.py --project DIR`
  reads the `file` field the compiler already put on every diagnostic and
  edits that file. Repairing only the entry point was an assumption in the
  loop, not in the compiler.
- **`strata test` works over a project.** With no argument inside a project it
  compiles every `.sta` under it from the project root, so a test can
  `import x from app` and open the data files by the same relative paths the
  service uses. Before this, an application had no way to be tested.
- **`import x from app` also looks in a sibling `src/`.** A test does not sit
  beside the module it tests.
- **`apps/orders/src/rules.sta`** holds the business rules, apart from HTTP.
  The handlers are adapters now: read the form, call a rule, choose a status
  code. `apps/orders/tests/rules_test.sta` is the application's first test —
  5 blocks, 14 assertions, no socket.
- **A Dockerfile that has been built.** The previous one cloned
  `https://github.com`, patched CPython's importlib to accept `.sta` files and
  renamed the python binary to `strata`; CI checked that the file existed. The
  new one builds the compiler's dependencies, compiles the service, runs its
  tests, and ships the binary with libcrypt and its data. CI builds the image
  and asks the container for a page.

`test_suite/journey_change.py` walks the whole thing — 19 steps, from an
export of HEAD — and the data written before the change still loads after it.

### Forms: data flows inward

The UI tier could render data and not collect any, so an application could
show a list and never add to it. `layout` gains `form` and `field`, and
element properties can now be HTML attributes rather than only CSS — an
unrecognised one is still emitted as a `data-` attribute rather than dropped.

`std/http.sta` gains `http_body`, `http_form_value` (percent-decoded),
`http_redirect` (303, so a refresh does not resubmit) and `http_bad_request`.
`str_to_float` was missing from `std/io.sta` — a form field arrives as text,
so a service that takes input needs it.

`apps/orders` has a form. A post is validated, assigned an id, inserted,
persisted and redirected; a missing required field is a 400.

Two bugs this turned up, neither of which a unit test would have found:

**The server only ever read once.** `http_read_request` did a single `read()`
and assumed the whole request arrived. That is true of curl, which puts a small
request in one packet, and false of any client that writes headers and body
separately — the body arrived after the read returned, every posted field
looked absent, and every form submission was a 400. It now reads until the
headers are complete and then reads exactly `Content-Length` bytes.

**`strcasestr` needs `_GNU_SOURCE`.** Without it the implicit declaration
truncates the returned pointer, `Content-Length` parsed as zero, and the body
was never read — the same 400, one layer down. Replaced with an explicit scan.
The implicit-declaration warning that would have said so is suppressed by the
`-Wno-implicit-function-declaration` the build passes to gcc.

### String literals survive code generation

The lexer decodes escapes, so by code generation `\r` is a real carriage
return. Only backslash, quote and newline were re-escaped: a tab went through
raw — legal inside a C literal, by luck — and a carriage return ended the
line. `"\r\n"` failed to compile with *missing terminating " character*,
pointing at generated code the author never wrote.


### The cross-tier contract reaches every file

Only the file being compiled had its bodies checked. So renaming a column in
`schema.sta` failed the build at `main.sta` and sailed straight past
`views.sta` — the UI tier, which is the tier the cross-tier claim is actually
about. The break surfaced later as a C compiler error naming a C symbol.

The project's own modules are checked now. `std` and `compiler` are not: they
are dependencies with their own suite, and re-checking them on every
application build would put their diagnostics in every user's output.

Diagnostics carry the file they are in, because a line number against the
wrong file is worse than no line number:

    [E004] Field 'amount' not in 'Order' (src/views.sta:line 21, col 30)

`file` is in the `--json` payload too — the repair loop patches a file, and in
a multi-file project the diagnostic is usually not in the one being compiled.
The type checker differential compares the file as part of each diagnostic, so
an error attributed to the wrong file is a divergence rather than something
nobody notices.


### A project is the unit of building

`Strata.toml` existed and nothing read it. `strata build` took a file path, so
there was no such thing as a Strata application — only a set of files someone
compiled by hand, which is why the one directory shaped like a service held a
six-line hello world.

`strata build` with no arguments now builds the project the current directory
belongs to: it walks up for `Strata.toml` and reads `main` and `output`.
`strata run` builds and runs it. `strata new` scaffolds a project with a
schema and an entry point that builds unedited. A single file still compiles
with `strata build <file.sta>`.

The reader is deliberately small — it takes two keys and ignores the rest. It
is not a TOML parser, and a key it does not understand is not silently
honoured.

`cmd_build` also ran its own type check in an inline Python block that did not
resolve imports, so it printed "TypeCheck OK" for files the compiler then
rejected. Removed; `stage0` is the only thing that decides.

`test_suite/project_build.py` covers it, ending with the real service: build
`apps/orders` as a project, start it, and read `/summary` back over HTTP —
including that the numbers are right after a load from disk, which is the case
that caught the string-comparison bug.


### String equality was comparing pointers

    str a = "OPEN";
    str b = strata_concat("OP", "EN");
    a == b        // false

`==` on strings compiled to C's `==`, which compares addresses. It looked
correct whenever both sides were literals in the same binary — which was every
test that existed, including `db_query_by_string` — and failed the moment one
side came from a file or was built at runtime.

The integration found it, not a test: the orders service showed two open
orders when seeded in memory and zero after a restart that loaded the same
rows from disk. `status == "OPEN"` matched nothing, because the loaded strings
were fresh allocations.

`==` and `!=` now compare contents when either side is a str. Five conformance
tests cover it, including the one that found it — a string query after a round
trip through disk.

### The self-hosted compiler builds the service

`render` as an expression, `app` imports and imported declarations are in the
Strata parser, type checker and code generator, so `compiler/*.sta` compiles
`apps/orders` to byte-identical C. All four differentials now walk directories
rather than listing them, which is what lets them see an application that
keeps its sources in `src/`.

Found while porting: `load X from "p"` printed a spurious parse error from the
Strata parser on every file that used it. `from` lexes as a keyword and the
parser expected it as an identifier. The error was recoverable, so the syntax
tree was right and the tree-comparing differential never saw it.


### `len()` was returning garbage

    len([1, 2, 3])       -> 5
    len([5, 7])          -> 7
    len(["a", "b", "c"]) -> 5

`list[T]` compiled to a bare C array with no length stored anywhere, and
`strata_len` walked memory until it found a zero — so it returned whatever
happened to follow the array on the stack. This was wrong for every list of
scalars, for as long as lists have existed.

Nothing caught it. The bubble-sort conformance test passes its own `n = 3`,
and the aggregates test only asserted that `len` was not *undefined*, never
what it returned.

A list now carries its element count in the machine word before its data.
NULL-termination cannot work here: 0 is a valid int and `""` a valid str, so
no element value is free to act as a terminator. List literals and query
results both allocate through `strata_list_new`, and `for R in rows` iterates
by length rather than walking to the first NULL — which was wrong for scalars
and became wrong for query results too.

### Aggregation

`sum`, `avg`, `min`, `max` and `count` were reserved names that type-checked
and then emitted a call to a C function that did not exist, so any program
using one failed at the linker.

A column is projected with `rows.column`, and the projection is checked against
the schema: rename a column and the build fails at the aggregate, the same way
it already failed at a query or in a layout. That contract is the reason
aggregation belongs in the language rather than in a library.

`sum`, `min` and `max` keep the column's own type — summing ints gives an int.
`avg` is always float, `count` always int and takes the rows rather than a
column. A plain `list[int]` needs no projection. An empty result aggregates to
zero rather than failing or producing a NaN, because a report over a filter
that matched nothing should render zeroes.

One runtime function serves every schema: for a projection it is handed the
byte offset of the column inside the row, so it reads the field without
knowing which record type it came from.

No `GROUP BY`, no `HAVING`, no aggregate inside a query condition.


### `strata fmt`

The premise is that AI writes the code and developers review it. A reviewer
cannot do that if half of every diff is whitespace, so the formatter is not a
nicety here — it is what makes review possible at all.

Written in Strata, in `compiler/fmt.sta`. It rewrites lines, not tokens, and
that is deliberate: the lexer discards comments, so a pretty-printer over the
token stream would silently delete every comment in the repository. Only
leading whitespace changes. The contents of a `native "..."` block — C the code
generator emits verbatim — pass through byte for byte.

It indents by brace depth at four spaces, strips trailing whitespace,
collapses runs of blank lines to one, and ends the file with exactly one
newline. It does not re-wrap lines, normalise spacing around operators, or
sort anything.

Two properties are checked over all 59 source files rather than a few samples:
the formatted file parses to an identical syntax tree, and formatting twice
changes nothing more than formatting once. Without the first a formatter is
worse than none, because it alters meaning silently and at scale; without the
second a repository never converges. Comment counts and native-block contents
are checked too.

Sixteen files were not in canonical form; they are now. CI fails if any
tracked source drifts out of it.

Worth recording, because it bit three times while writing this: Strata has no
`else if`, so a chain of `if` statements reads state an earlier branch already
changed. The scanner snapshots `in_string` and `in_block` per character for
exactly that reason — reading them live means the quote that closes a string
immediately opens a new one, and every line after the first string literal in
a file is treated as being inside it.


### E007: unresolved imports are reported, and the taxonomy has advisories

An import naming a module with no local checkout printed a line on stderr and
the compiler carried on. It never reached `--json`, so the repair loop was
blind to it — the same shape of gap the undefined-call work closed.

It matters more than it looks. An unresolvable import also disarms the
undefined-call check, because the compiler cannot know what that module makes
reachable. The effect, seen while quarantining the broken `std` modules, is
that moving a broken module out of the way makes everything importing it stop
reporting anything at all.

`E007` is the taxonomy's first `ADVISORY`. E001–E006 are `CRITICAL_HALT` and
stop the build; an unresolved import does not, because a dependency provided
at link time is legitimate and failing on one would make external modules
unusable. The JSON payload separates the two: `error_count` and `ok` count
only halting diagnostics, `advisory_count` the rest — so a repair loop does not
spend every pass trying to fix something it cannot.

Reported only for the file's own imports, where there is a line to point at;
a transitive one still goes to stderr, since no line of this file names it.


### The standard library compiles

`stdlib_parses.py` reported "13 parse, 0 fail" for as long as it had existed.
Seven of those thirteen also called functions that exist nowhere in the
project, so anything importing them failed at the C linker. Parsing was never
the claim worth making.

`std/core.sta` is real now: `print_line` and `convert_int_to_str` called
`native_sys_write` and `native_sys_itoa`, which do not exist, and are ordinary
`native` blocks the way `std/io.sta` writes its primitives. `telemetry` and
`testing` imported `core.io` — which resolves to `io.sta` — while calling
`print_line`, which lives in `core.sta`; they import `core` now.

Five modules moved to `std/unimplemented/`: `runtime`, `stdlib`, `tls`,
`pkg_system`, `pkg_manager`. They describe POSIX syscall wrappers, an HTTP
client, a TLS 1.3 handshake with AES-NI acceleration and a cryptographic
package resolver — none of which exist. Six examples built on them moved to
`examples/unimplemented/` for the same reason.

`test_suite/stdlib_compiles.py` replaces the parse check. Per module it
requires a clean type-check AND a program that imports it, calls into it,
links and runs — because a module can type-check and still fail to link, which
is precisely how this went unnoticed. It also asserts no live module imports a
quarantined one.

Worth naming: quarantining the TLS and runtime modules made the three examples
importing them **stop reporting errors**, because the undefined-call rule
disarms when an import cannot be resolved. Moving a broken module out of the
way makes its broken callers look clean. That is why those examples are
quarantined rather than left in place.


### Calls to undefined functions are caught

`undefined_thing(1)` type-checked clean and failed at the C linker:

    undefined reference to `undefined_thing'

A C symbol name, from a tool the developer never invoked, pointing at no line
of Strata — and invisible to `--json`, so the repair loop could not see it
either.

The cause was structural, not a missing rule: the type checker ran on one file
with no import graph, and an unknown name is indistinguishable from a call into
`std/`. `resolve_imports()` now runs *before* the check in both
implementations, and module resolution moved from the code generator into the
parser so the type checker can reach it. A file importing a module with no
local checkout disarms the rule rather than guessing.

The check is name-existence only. Argument count and type across a module
boundary are still unchecked; that is a separate change with its own risk.

The rule rests on a hand-written list of names the runtime provides, held in
both implementations. Three conformance checks guard it: the list must cover
everything the code generator can emit, the two copies must agree, and a
program calling a builtin must compile. Removing one name from either list
fails all three.

Turning it on found real breakage that had never been visible: seven `std`
modules and five examples call functions that do not exist anywhere, mostly
`print_line` (which lives in `std/core.sta` while those files import `io`).
Those modules only ever *parsed* — `stdlib_parses.py` checks exactly that and
no more. Recorded in NEXT_STEPS rather than fixed here.


### The repair loop has tests

`ai_self_repair.py` is the project's headline claim and it was the last major
component with no executable check — nothing in `test_suite/` or the CI
workflow referenced it. It worked, but every change to a diagnostic's shape
was a chance to break it silently: the loop reads specific keys out of
`--json`, and a renamed key sends it down its E999 fallback, where it repairs
nothing and reports that nothing was possible. That failure looks exactly like
success on a file that needed no repair.

`test_suite/self_repair.py` adds 40 checks in three groups: the JSON payload
contract (every key the loop reads, present and correctly typed, for a type
error, a parse error and a clean file); the loop itself (converges on E001 and
E004, handles two errors in sequence, stops on the first pass when a repair
needs judgement, `--dry-run` restores the original byte for byte, a clean file
is not rewritten, a missing file exits without a traceback); and the `llm`
backend declining out loud when its key is absent rather than looking like a
successful no-op. It runs in CI and its result is now a row in the generated
release notes.

Writing it surfaced a gap: a call to an undefined function type-checks clean
and fails at the C linker, so it never reaches `--json` and the repair loop
cannot see it. That is recorded in the README roadmap rather than fixed here.


### Saved tables migrate

`save` wrote bare tab-separated rows in declaration order and `load` read them
back positionally. Adding a column to a `database` block silently corrupted
every row in every file already on disk, and nothing could notice.

A saved file now carries a header naming each column and its type. Columns are
matched by name: one that has since been dropped is skipped, a new one keeps
its zero value (`""` for a str, so a new column cannot crash a printf), field
order is no longer the contract, and a column whose type changed is refused
with a message rather than misread. A file written before headers existed is
also refused, saying to re-save it.

### A model is a stack of layers

`model` declared an input shape and an output shape, and `predict` ran exactly
one dense layer. There was nowhere to put a hidden layer and no activation, so
nothing non-linear was expressible.

    model Scorer {
        input:  tensor[float, 1, 2];
        hidden: 3 relu;
        hidden: 2 relu;
        output: tensor[float, 1, 1];
    }

`relu`, `sigmoid` and `none` are the activations the runtime has, and the
output layer is linear. `hidden` and the activation names are contextual, so a
variable may still be called `relu`. Weights are laid out layer by layer and a
file with the wrong count is refused rather than loaded in part — it used to
return 0 silently. A model with no hidden layers is one dense layer, exactly as
before, so nothing that already ran changed.

Freestanding WebAssembly has no libm, so `exp` is implemented in the wasm
prelude by range reduction and a Taylor series; it agrees with libm to about
1e-15 relative across the range it is used on.

This is inference. There is no training, no autograd, no convolution or
attention, and no accelerator.


### `report` renders

`report` parsed and type-checked its datasource and then generated a function
body that printed one heading. Worse, the code generator emitted
`Name_render` while the `render` statement called `Name_generate`, so a program
using `render` did not link at all — there were two dead `RenderStmt` branches
in the same if-chain and the unreachable one was the correct one.

A report now runs its datasource, evaluates its metrics with `rows` bound to
the result, and writes Markdown: the title, each metric, the matching rows as a
table, and a row count. Metrics are type-checked for the first time — E001 on a
mismatch — and the datasource carries the E004 column contract. The Strata type
checker had no report checking whatsoever; it does now.

Metrics see `rows`, not the columns of a row: there is no aggregation, so
`sum(col)` cannot be evaluated and naming a bare column in a metric is an
error. One conformance test had asserted that exactly such a report was clean;
it was not, and nothing had been checking.


### A query is an expression

`Source <- [cond]` parsed in exactly one place: the right of a declaration.
Anywhere else it was a parse error, so counting matching rows meant declaring a
variable nobody wanted. It is now an ordinary primary expression and composes
like one — as a call argument, passed to a function, compared. In expression
position it yields `list[T]` and generates a scan that collects the matching
rows, and the E004 column contract fires at the query's own line and column.

Previously the code generator had a branch for a query in expression position
that emitted `NULL`, which would have been a silently wrong answer had the
parser ever produced one. It does now, and it generates the scan.

Ported to both implementations — all four differentials agree on the new
`examples/query_expression.sta`, and the fixpoint still holds. Six new
conformance tests cover a query as a call argument, an empty result, a query
passed to a function, agreement with the declaration form, a bad column and an
unknown table.


### `stream` blocks dispatch

A `stream` block compiled its body and then never called it. It now has a
runtime. Each handler registers under its own name as a channel;
`strata_publish(channel, message)` enqueues, `strata_run()` drains the queue
and returns how many messages were delivered, and a handler may publish while
the drain is in progress. Messages to a channel with no handler are dropped.

This is a cooperative single-threaded loop, not a fiber scheduler: no separate
stacks, no preemption, no parallelism, no I/O integration. Virtual Event Fibers
remain design only.

Ported to both implementations — the code generator differential stayed
byte-identical and the fixpoint still holds. Three new conformance tests
(103/103) cover ordered delivery across channels, an unknown channel, and a
handler publishing mid-drain.


## v0.4.0-alpha — 2026-09-13

**Self-hosting reached for the front end.** The fixpoint holds.

```
stage0 (Python)  --C-->  gen1.c  --cc-->  strata1
strata1          --C-->  gen2.c  --cc-->  strata2
strata2          --C-->  gen3.c

gen1 == gen2 == gen3      4,757 lines      sha b2275d15b160467d
```

`compiler/strata_cli.sta` lexes, parses, type checks and emits C. Built from
Python-generated C it produces `gen2.c`; rebuilt from `gen2.c` it produces
`gen3.c`, and the three are identical. Compiling the compiler again changes
nothing, so the Python bootstrap can be retired without changing output.

### Code generator

`compiler/codegen.sta` emits C byte-identical to the generator in
`bootstrap/stage0.py` across 32 files, including the compiler's own sources —
3,722 lines of C for `codegen.sta` alone. The runtime prelude moved to
`compiler/runtime_preamble.c` so both implementations emit the same bytes by
construction rather than by two copies staying in step.

The self-hosted front end is 3,250 lines of Strata, 102 of them (3%) `native`
C, all allocation primitives.

### Bugs this stage exposed

- **Borrowed scalar parameters never dereferenced.** `def bump(int &n) { n = n + 1; }`
  compiled to pointer arithmetic on `strata_int*` and silently did nothing —
  no diagnostic, wrong answer. Every use of a borrowed scalar now dereferences.
- **Two modules could not define the same function name.** Deduplication meant
  for the diamond-import case silently discarded one definition, so calls
  reached a function with a different signature. A genuine collision is now a
  link error naming both modules.
- **`--emit-c` ignored imports**, emitting only the root unit and producing C
  that could not link.
- Float literals were emitted verbatim, so `0.90` reached C as `0.90` where the
  oracle prints `0.9`.

## v0.3.0-alpha — 2026-09-13

Three of the four self-hosting stages are complete, and the project's claims
now have executable checks behind them.

### Self-hosting

`compiler/lexer.sta`, `compiler/parser.sta` and `compiler/typechecker.sta` are
written in Strata — 2,313 lines, of which 93 (4%) are `native` C blocks
confined to allocation primitives. Each is verified against its Python
counterpart by a differential test that runs in CI:

| Stage | Oracle comparison | Result |
|---|---|---|
| Lexer | byte-identical token streams | 32 files identical |
| Parser | identical syntax trees | 31 files identical |
| Type checker | identical diagnostics, in order | 43 files identical |

All three also process their own source. **Self-hosting is not yet complete** —
`codegen.sta` and the stage1/stage2 fixpoint remain.

### Language core

Strata previously had no loops, no assignment statement and no array indexing:
`int i = 0;` was legal but `i = 5;` was not. Added `while`, `for`, `break`,
`continue`, assignment to variables, record fields and list elements, and list
and string indexing — with E001 on assigning a conflicting type, E001 on a
non-integer index and E003 on indexing a non-list. A bubble sort compiles and
sorts.

Also added: dotted module paths (`import core.io from std;`), imports resolved
from `compiler/` as well as `std/`, and the write form of the `<-` operator
(`Table <- [col = value]`) with the same E004 column validation as queries.

### Correctness fixes

- **The compiler never ran the type checker.** E001–E006 existed only in
  `strata check`; the build path was parse → codegen → cc, so a type error
  reached the user as a C compiler diagnostic. Now checked before codegen.
- **Imports were parsed and discarded.** No module was ever located, compiled
  or linked, so every symbol in `std/` was an undefined reference.
- **Generated C relied on implicit function declarations** — legal under gcc,
  rejected by clang 16+. Every clang toolchain, including macOS, was affected.
- **E005 fired on any string concatenation with an imported call**, flagging
  this project's own standard library.
- **Arguments to any unknown callee skipped type checking entirely**, which
  meant every call into `std/`.
- **C keyword collisions are now mangled.** A function named `register` emitted
  invalid C pointing at generated source the user never wrote.
- `print` was both a compiler builtin and a stdlib function, so `std/io.sta`
  could not parse its own definition. It is now an ordinary library function.
- Records are consistently references in generated C; a single-record query
  previously emitted a value initialised from a pointer.
- A unit with no `main()` is a library and compiles to an object file.

### Standard library

All 13 `std/*.sta` modules parse, up from 4. `std/io.sta`, `std/mem.sta` and
`std/str.sta` compile and link; `StringBuilder` works end to end from Strata.

### Verification

- Conformance suite: 63 tests, from a suite that reported "32/32" while failing
  30/31 with a segfault.
- `test_suite/doc_examples.py` compiles every fenced code block in `README.md`
  and `LANGUAGE_SPECIFICATION.md` on every commit, and fails both when an
  example breaks and when a roadmap example starts working.
- `test_suite/typecheck_cases/` holds twelve deliberately broken programs, one
  per rule.
- CI runs under gcc and clang, and rejects unimplemented tools returning to
  `bin/` or forged checksums returning to `Strata.lock`.

### Honesty

- Twelve of fifteen tools in `bin/` printed success without doing the work they
  claimed, including one reporting healthy production pods that did not exist
  and one writing the SHA-256 of the empty string into `Strata.lock` as a build
  signature. They are quarantined in `bin/unimplemented/` with a record of what
  each faked.
- Unmeasured figures removed: 15 KB WASM bundles, 4 KB fibers, 1,000,000
  pipelines, a 14.8 KB binary. No benchmark produced any of them, and no fiber
  scheduler exists.
- `README.md` rewritten to separate what runs from what is planned. WebAssembly
  has no direct DOM access, so "zero JavaScript runtime overhead" for a UI was
  not achievable as written; the roadmap says so.
- `ai_self_repair.py` previously grepped source text for the literal string
  "E001" and never invoked the compiler. It now compiles, reads structured
  diagnostics, patches and recompiles until clean.
- `strata build --json` emits machine-readable diagnostics carrying the
  taxonomy classification and remediation strategy for each error.
- Version corrected from 1.0.0, and fabricated registry dependencies removed
  from `Strata.toml`.
