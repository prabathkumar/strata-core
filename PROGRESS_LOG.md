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
