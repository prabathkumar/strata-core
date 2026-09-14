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
