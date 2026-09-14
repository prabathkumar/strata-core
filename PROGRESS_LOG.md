# Progress log

One entry per unattended run. Each records what was attempted, what the
verification suites said, and anything deliberately not done. A run that
achieved nothing still writes an entry — a silent night is indistinguishable
from a night that failed.

---

## 2026-09-13 — session (attended)

Landed: stream dispatch; queries as expressions; `report` rendering; schema
migration for `save`/`load`; multi-layer models with relu/sigmoid; tests and a
CI gate for the repair loop; `NEXT_STEPS.md` rewritten.

All eleven suites green. Conformance 126/126. Code generator byte-identical
across 47 files. Fixpoint reached. Committed as 55b6c8b.

Not done, and why:
- **Undefined function calls are still not caught.** The type checker runs
  per-file without the resolved import graph, so it cannot tell an undefined
  call from an imported one. Recorded as the first item in NEXT_STEPS Part 3.
- Fibers remain design only. Part 4 of NEXT_STEPS has the breakdown and the
  1–2 week coroutine scope that is worth taking instead.


_(check-in path verified: two consecutive commits from the bridge.)_

## 2026-09-14 — session (attended)

NEXT_STEPS item 1: calls to undefined functions are now E002.

The cause was structural. The type checker ran on one file with no import
graph, so an unknown name could not be told apart from a call into `std/`.
`resolve_imports()` now runs before the check in both implementations, and
module resolution (`module_path`, `collect_modules`) moved from the code
generator into the parser so the checker can reach it. An import with no local
checkout disarms the rule.

All eleven suites green. Conformance 136/136. Type checker differential 63
files identical — that suite is now the false-positive guard for this rule,
since both sides resolve imports. Code generator byte-identical, fixpoint
reached.

Found and NOT fixed: seven `std` modules and five examples call functions that
do not exist, mostly `print_line` (in `std/core.sta`, while those files import
`io`). They have never compiled. `stdlib_parses.py` only checks that they
parse. This is now item 1 in NEXT_STEPS Part 3, with the exit criterion being
a suite that compiles every std module rather than parsing it.

## 2026-09-14 — session (attended), second item

NEXT_STEPS item 1: the standard library compiles.

`std/core.sta` made real (`print_line`, `convert_int_to_str` were calling
natives that do not exist). `telemetry` and `testing` imported `core.io`,
which resolves to `io.sta`, while calling `print_line` from `core.sta`; fixed.
Five modules — `runtime`, `stdlib`, `tls`, `pkg_system`, `pkg_manager` —
quarantined to `std/unimplemented/`, and six examples built on them to
`examples/unimplemented/`.

`test_suite/stdlib_compiles.py` replaces `stdlib_parses.py`: per module a clean
type-check AND a program that imports it, links and runs. Eight modules,
17/17 checks. All eleven suites green, conformance 136/136, fixpoint reached,
all 18 remaining examples compile.

Found while doing it, and NOT fixed: quarantining a broken module makes its
broken callers go SILENT, because the undefined-call rule disarms on an
unresolvable import. The compiler prints `[STRATA IMPORT]` on stderr but emits
no diagnostic, so it never reaches `--json`. That is now item 1 in Part 3.

## 2026-09-14 — session (attended), third item

E007: unresolved imports are reported, and the taxonomy has advisories.

An import with no local checkout printed to stderr and the compiler carried
on, so it never reached `--json` or the repair loop. It also disarms the
undefined-call check, which is how quarantining the broken std modules made
their callers go silent.

E007 is the first ADVISORY severity: reported, build continues. The payload
now separates `error_count`/`ok` (halting only) from `advisory_count`, so the
repair loop does not spend passes on something it cannot fix.

All eleven suites green. Conformance 140/140, self-repair 46/46 (six new
checks covering the advisory contract), type checker differential 54 files
identical, fixpoint reached.

Not done: a call INTO an unresolved import is still unchecked. Knowing the
module is missing is not knowing what it declares. Recorded in Part 2.

## 2026-09-14 — session (attended), fourth item

`strata fmt`, written in Strata (`compiler/fmt.sta`, `compiler/fmt_cli.sta`).

Rewrites lines, not tokens: the lexer discards comments, so a pretty-printer
over the token stream would delete every comment in the repo. Only leading
whitespace changes, so `native "..."` blocks pass through byte for byte.

`test_suite/fmt.py`: 15/15 checks over 59 files. The two that matter are AST
preservation and idempotence. Sixteen files were not canonical; all are now,
including the compiler's own sources — fixpoint re-verified afterwards.
CI gates the repo on `strata fmt --check`.

All twelve suites green. Conformance 140/140, fixpoint reached, generated C
byte-identical.

Found while writing it: Strata has no `else if`, so a chain of `if` statements
reads state an earlier branch already changed. Caused three bugs in one file,
each of which looked right. Recorded in NEXT_STEPS Part 2 — it is sugar, not
semantics, and worth fixing in the parser.

## 2026-09-14 — session (attended), fifth item

Aggregation — and the `len()` bug underneath it.

`len()` returned garbage for every list of scalars: `list[T]` was a bare C
array with no length and `strata_len` walked to the first zero, so
`len([1,2,3])` was 5 and `len([5,7])` was 7. Nothing caught it because the
bubble-sort test passes its own `n`. A list now carries its count in the word
before its data; list literals and query results both allocate through
`strata_list_new`, and `for R in rows` iterates by length.

Then `sum`/`avg`/`min`/`max`/`count`, over a list or a `rows.column`
projection. The projection is checked against the schema, so a renamed column
fails at the aggregate. sum/min/max keep the column's type, avg is float,
count takes the rows. Empty aggregates to zero.

All twelve suites green. Conformance 160/160 (twenty new tests), fixpoint
reached, generated C byte-identical, repo still canonically formatted.

Not done: no GROUP BY, no HAVING, no aggregate inside a query condition.

## 2026-09-14 — approach changed: structure and integration first

Prabath's call, and it was right: the compiler was in good shape and there was
no system. `client-ledger-service` was a six-line hello world that did not
compile, `Strata.toml` was ignored, `deploy/` deployed nothing, and there was
no HTTP server anywhere — so the "no JS/React split" claim had no way to serve
a page.

Target agreed: a service that runs and serves.

Built a walking skeleton rather than another language feature. `apps/orders`
is a multi-file project that loads persisted rows, serves a layout-rendered
dashboard at `/`, aggregates at `/summary`, and 404s otherwise. It runs.

Needed along the way, each found by the integration rather than guessed at:
  - `render L` as an expression (a layout that can only be written to a file
    cannot answer a request) — open_memstream behind it
  - `app` as a module source, so a project can be more than one file
  - imported `database`/`model` declarations registered in the checker

`std/http.sta` is written in Strata over the existing FFI — no compiler change
was needed for the server, which dropped it from a week to an afternoon.

DEBT, recorded in ARCHITECTURE.md: the three compiler additions above exist in
the Python oracle only. The self-hosted compiler cannot build this app until
they are ported, and no repo file exercises them, so the differentials do not
cover them yet. That is the next thing.

All twelve suites green, fixpoint reached.

## 2026-09-14 — step 0 of PLAN.md

Self-hosted port finished: the Strata compiler builds apps/orders to
byte-identical C. All four differentials now walk directories rather than
listing them, so they cover an app with sources in src/.

Two bugs found by the integration, neither by a test:
  - `==` on strings compared POINTERS. The service showed 2 open orders when
    seeded and 0 after a restart that loaded the same rows from disk.
  - `load X from "p"` printed a spurious parse error from the Strata parser on
    every file using it; recoverable, so the AST was right and the differential
    never saw it.

All twelve suites green, conformance 165/165, fixpoint reached.

## 2026-09-14 — step 1 of PLAN.md

`strata build` reads Strata.toml. A project is the unit: build with no
arguments from anywhere inside it, `strata run` to run it, `strata new` to
scaffold one that builds unedited.

Removed the duplicate type check inside cmd_build — it skipped import
resolution and printed "TypeCheck OK" for files stage0 then rejected.

test_suite/project_build.py, 14 checks, ending by starting the real service
and reading /summary over HTTP.

All thirteen suites green.

## 2026-09-14 — step 2 of PLAN.md

Imported project modules are type-checked. A renamed column now breaks the UI
tier at build time, naming src/views.sta and its line — previously it sailed
past and became a C compiler error.

Diagnostics carry their file, in the human output, in --json (for the repair
loop, which has to know which file to patch), and in the type checker
differential, so a misattributed error is a divergence.

std and compiler modules are deliberately not checked on every app build.

All thirteen suites green. Conformance 168/168.

## 2026-09-14 — step 3 of PLAN.md

Forms and POST. layout gains form/field and HTML attribute properties;
std/http.sta gains body, form value, redirect; std/io.sta gains str_to_float.
apps/orders creates an order from the page: validated, persisted, 303.

Two bugs found by the test, not by hand:
  - http_read_request did ONE read(). True of curl, false of urllib, which
    writes headers and body separately — every form post was a 400.
  - strcasestr without _GNU_SOURCE truncates its pointer, so Content-Length
    parsed as zero. The warning that would have said so is suppressed by
    -Wno-implicit-function-declaration.
  - and separately: "\r\n" in a string literal did not compile at all.

All thirteen suites green. Conformance 175/175, project_build 21/21.

## 2026-09-14 — Journey A closed

Sign in → dashboard → create → close → sign out → refused. 25 steps, walked by
test_suite/journey_orders.py on every commit.

Four bugs, every one found by the journey and none reachable by a unit test:
  - crypt(3) returns a buffer libc reuses, so the stored hash and a fresh one
    were the same pointer and EVERY PASSWORD MATCHED.
  - random_hex returned a static char[], so two session tokens were the same
    pointer — every session was the same session.
  - `Session <- [token == token]` compares the column with itself: a lookup for
    a token that does not exist returned every row. Any cookie authenticated.
    Now E008.
  - a `link` in an imported module was dropped, because dedup keyed nameless
    declarations as None and the first one marked every later one emitted.

Built along the way because the journey needed them: layout parameters (there
are no module-level variables — they do not parse, despite NEXT_STEPS claiming
Phase 1 delivered them), computed HTML attributes, cookies, query strings,
headers, 303/403.

Not built: delete does not exist in the language. Sign-out expires a session
rather than removing it, and nothing prunes the table.

All fourteen suites green. Conformance 182/182, journey 25/25.

## 2026-09-14 — Journey B closed (attended)

Landed: **E009** (an insert must name every column), the repair loop over a
project, `strata test` over a project, `app` imports reachable from `tests/`,
`apps/orders/src/rules.sta` and the application's first tests, a Dockerfile
that has been built, and `test_suite/journey_change.py` — 19 steps from an
export of HEAD.

Every suite green: conformance 182/182, documentation 11/11, all four
differentials identical, fixpoint reached, stdlib 19/19, project 14/14,
journey A 25/25, journey B 19/19, repair loop 48/48.

Found by the journey, not by the unit suites:
- Adding a column to a schema was an error nowhere. Every insert wrote it as
  a zero, in every row, silently.
- `std/telemetry.sta` had been omitting `trace_id` since it was written.
- The repair loop assumed one file, though the compiler had been reporting
  which file each diagnostic was in all along.
- `strata test` could not see an application, so `apps/orders` had no tests.
- A `tests/` directory could not import the modules it tests.

Corrected rather than quietly fixed: the plan said the build would fail in
three files. It fails in two — the two that insert rows. The view was
unaffected, because displaying a new column is a choice, not a contract.

Not done:
- **Docker is not installed on this machine**, so the deploy step is skipped
  locally and verified in CI on every push. The image has therefore never been
  built here; the first real evidence will be the next CI run.
- `delete` still does not exist in the language, so sessions expire rather
  than being removed and nothing prunes the table.
- The region filter still reaches the view without being applied to the query.

## 2026-09-14 — Journey C closed (attended)

Landed: a process per connection, a 5s receive timeout, SIGPIPE ignored,
children reaped, shared and exclusive file locks in `std/http.sta`, an
incomplete request reported as empty, and `test_suite/journey_survive.py` —
18 steps with the numbers printed.

Every suite green: conformance 182/182, documentation 11/11, four
differentials identical, fixpoint reached, stdlib 19/19, project 14/14,
journey A 25/25, journey B 19/19, journey C 18/18, repair loop 48/48.

First published performance figures, on a 4-core development machine:
dashboard p50 2.2 ms / p95 2.6 ms over 20 rows, 15 ms over 2000 rows,
~445 req/s sequential, ~380 req/s and p95 32 ms over 8 concurrent clients.

Found by the journey:
- A client that disconnected mid-response terminated the service. SIGPIPE's
  default action, and nothing in the code said so.
- A half-sent request came back as the bytes that had arrived, so a truncated
  request looked like a real one.
- Once connections forked, concurrent writes corrupted the table outright:
  856 rows from 1000 + 10, hundreds of them all-zero.

Corrected in my own work: the lost-update test was first written against an
empty table, where it passed with the lock removed. A test that passes when
the thing it tests is deleted is not a test. Rewritten against a thousand-row
table, where removing the lock fails it immediately.

Not done:
- **Throughput is capped by forking and reloading all three tables on every
  request.** Concurrent throughput is below sequential and the figure is
  published rather than explained away.
- No CSRF token, no rate limit, no lockout, no connection limit.
- `delete` still does not exist in the language.

## 2026-09-14 — the image, actually built (attended)

I had said the image could not be built because there is no Docker on the
development machine. That was half the story and I should have checked the
other half before saying it: the cloud side of this session has Docker. It
also has no route to any container registry, so the real Dockerfile still
cannot be built outside CI, but a `FROM scratch` image can — and now is, by
`deploy/build_scratch_image.sh`. 5.35 MB, serves `/login`, and a sign-in and
an order both work through the container.

Found by running it: `docker logs` was empty. stdout to a pipe is block
buffered, so the startup line never left libc. The runtime preamble
line-buffers now, and the journey asserts it.

## 2026-09-14 — the second application (attended)

Landed: `apps/ledger` (schema, rules, CLI, JSON API, report, 5 verify blocks),
`std/cli.sta`, `std/json.sta`, `for X in xs` in statement position across the
parser and both code generators, an error for an unhandled statement,
`char_from_code` moved to `std/str.sta`, and
`test_suite/journey_ledger.py` — 19 steps.

Every suite green: conformance 182/182, documentation 11/11, four
differentials identical, fixpoint reached, stdlib 23/23, project 14/14,
journeys 25/25, 19/19, 18/18 and 19/19, repair loop 48/48.

The question was whether the language had been shaped by its only
application. Partly, and now measurably: five gaps, every one of them in the
places `apps/orders` never went — the command line, JSON, iteration outside a
view, and writing a report from a path chosen at run time. The parts that did
hold are the parts the project is actually about: one `database` declaration
checked the ledger's queries, aggregates, report and JSON, and E008 caught a
new instance of the orders desk's auth bug immediately.

The worst of the five is worth stating plainly: **a `for` loop in a function
body emitted no code and said nothing.** A compiler that silently drops a
statement is worse than one that crashes, and the generator had been able to
do that since it was written.

Not done:
- `strata check <file>` does not resolve imports the way `strata build` does.
- A diagnostic from an imported module is reported twice.
- `render X to <expr>` still does not exist.
- `client-ledger-service/` is a leftover stub with a fabricated Strata.toml
  (`target = "wasm"`, `opt_level`), unrelated to `apps/ledger`. It should go.

## 2026-09-14 — stage 9 closed (attended)

The real two-stage Dockerfile now builds outside CI. Base changed to
ubuntu:24.04 so it can be bootstrapped locally with debootstrap and imported
under that tag (`deploy/bootstrap_base_image.sh`); the build installs the
toolchain with apt, compiles the service, runs `strata test` inside the image,
and ships a 216 MB runtime that serves as uid 10001.

Found by the build, first attempt: `stage0.py -o build/orders` did not create
`build/`. `strata build` had its own `mkdir -p`, so the gap only showed when
the compiler was called directly.

Not done: the CI gate has not run on a pushed commit, so Canonical's published
base is still unverified here; and stage 10 has nothing in it but
line-buffered logs.

## 2026-09-14 — stage 10 closed (attended)

Landed: a request log, CSRF tokens on every form and every write, a five-strike
account lockout that does not leak which usernames exist, a 64-connection cap
answering 503, and `test_suite/journey_operate.py` — 21 steps.

All ten stages are now closed, with stage 3 closed on the rules repair backend
alone and stage 9's published base still verified only by CI.

Found on the way in: the service could be made to post by any page on the web;
a password could be guessed as fast as it could answer; counting children to
enforce a cap reintroduced zombies, because a parent that reaps only on the
next connection never reaps while idle.

Corrected in my own work: the first zombie test slept a fixed 2.5s and failed
on timing rather than on the defect. It now waits for the process table to
clear and fails only if it does not.

Not done: no metrics; nothing prunes an expired session; the lockout is per
account rather than per source, so it also lets someone lock an operator out
on purpose.
