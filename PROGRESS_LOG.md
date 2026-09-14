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
