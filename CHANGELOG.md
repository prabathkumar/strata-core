# Changelog

## Unreleased

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
