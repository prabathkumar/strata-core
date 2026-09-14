# Strata — Where the project stands, and what comes next

Every claim below was verified by running code. The figures come from the
suites in `test_suite/`, which run on every commit; where a number appears here
it is because something printed it.

The previous version of this file described a repo with no loops, no assignment
statement, twelve stub tools in `bin/`, and self-hosting that "cannot begin".
All of that is done. It was understating the project by roughly three months.

---

## Part 1 — What is real

| Component | State |
|---|---|
| Language core | Loops, assignment, indexing, module-level state. A bubble sort compiles and runs. |
| Self-hosted front end | `compiler/*.sta` — lexer, parser, type checker, code generator, ~5,000 lines of Strata, 2% `native` C. |
| The fixpoint | `stage0 → gen1.c → strata1 → gen2.c → strata2 → gen3.c`, and `gen1 == gen2 == gen3`. The Python bootstrap can be retired without changing a byte of output. |
| Differential testing | Four suites compare the Strata implementation against the Python oracle: tokens, syntax trees, diagnostics, and generated C byte for byte. 47 files, 0 divergent. |
| Error taxonomy | E001–E007, with `--json` diagnostics carrying a classification, a severity and a remediation strategy. E007 is the first advisory: reported without stopping the build. |
| Cross-tier contract | A column renamed in a `database` block fails the build at the line of UI that used it. Tested: `layout_renamed_column_breaks_ui`. |
| `layout` / UI tier | Compiles to a function that writes HTML. Server-rendered. |
| WebAssembly target | `--target wasm` emits freestanding C; clang builds a module exporting every top-level function. No libc. |
| Database | In-memory tables, typed queries as expressions, `save`/`load` to tab-separated text **with schema migration** — columns match by name, a type change is refused. |
| `report` / `render` | Runs its datasource, evaluates metrics against `rows`, writes Markdown. |
| `model` / `predict` | A stack of dense layers with relu/sigmoid activations. Inference only. |
| `stream` | Cooperative dispatch: publish to a channel, drain the queue, handlers may publish mid-drain. Not fibers. |
| `verify` blocks | `strata test` builds and runs them, reporting each failed assertion with its line. |
| FFI | `foreign` blocks: include a header, name the library, declare signatures checked at call sites. |
| Repair loop | `ai_self_repair.py` compiles, reads the JSON diagnostics, patches, recompiles. 40 checks in CI, including the payload contract it depends on. |
| Undefined function calls | **E002.** Imports resolve before the type check in both implementations, so a typo names the typo instead of failing at the C linker. Name existence only — signatures across a module boundary are still unchecked. |
| Standard library | Eight modules that compile, link and run. A suite builds a program against each one and executes it. Five modules and six examples that stand on a runtime that was never built are quarantined in `unimplemented/` directories. |
| Unresolved imports | Reported as E007, an advisory: the build continues, but the import is no longer silent. It is a `--json` diagnostic, so the repair loop sees it. |
| Formatter | `strata fmt`, written in Strata. Canonical indentation, with comments and `native` blocks preserved. AST-preservation and idempotence tested over every file; CI gates the repo on it. |
| CI | Eleven suites, plus both gcc and clang, plus a clean-checkout export so nothing passes only because of an untracked file. |

## Part 2 — What is not

| Gap | State |
|---|---|
| Virtual Event Fibers | Design only. See Part 4. |
| Concurrency of any kind | The runtime is single-threaded by construction. Seven mutable globals in the prelude, plus a `__rows` array and an `__count` per `database` block. |
| Database durability | No locking, no index, no transactions, no SQL backend. Two writers corrupt the file. |
| Calls into an unresolved import | Still unchecked — knowing the module is missing (E007) is not the same as knowing what it declares. A file with an external import gets the advisory and no call checking. |
| No `else if` | `if`/`else` exist; a chain does not. Code ends up as sequential `if` statements, which read state an earlier branch has already changed. This produced three separate bugs while writing the formatter, each of which looked correct: the quote closing a string immediately opened a new one, so every line after the first string literal was treated as inside it. The workaround is to snapshot state before the chain, which is easy to forget and invisible when forgotten. Worth fixing in the parser — it is sugar, not semantics. |
| Formatting beyond indentation | `strata fmt` rewrites leading whitespace only. It does not re-wrap long lines, normalise spacing around operators or inside argument lists, or align anything. That needs comment-aware tokens, which the lexer does not produce. |
| Aggregation | No `sum`, `avg`, `count` over a query result. A report metric sees `rows`, not columns. |
| Training | `predict` is inference. No autograd, no optimiser, no accelerator. |
| Client-side interactivity | Layouts are server-rendered HTML. WebAssembly has no DOM access without a JS shim, as with every WASM framework. |
| Tooling | Three real tools in `bin/`. Twelve stubs are quarantined in `bin/unimplemented/` and CI rejects them on PATH. No formatter, no LSP, no debugger. |
| Migration tooling (Java/C# → Strata) | Direction, not a project. |

---

## Part 3 — Next, in order

### 1. Aggregation over query results (1 week)

`sum`, `avg`, `min`, `max`, `count` over a `list[T]` and a column. The parser
and type checker already reserve these names and return `float` for them; there
is no evaluation behind it. Report metrics are the obvious consumer, and today
a metric can only count rows.

### 2. Single-threaded coroutines (1–2 weeks) — see Part 4

---

## Part 4 — Fibers: the honest scope

The README promises **Virtual Event Fibers**. What that phrase implies — M:N
scheduling across OS threads with async I/O — is four projects, and the one
everyone expects to be hard is the cheap one.

**Stack switching is days.** `ucontext` works in an afternoon; hand-written
assembly for x86-64 SysV and ARM64 is about a week done properly, with FP and
SIMD register save and stack alignment. If that were the job, it would be two
weeks.

**What it actually costs:**

1. **Without I/O integration you have coroutines, not fibers.** A fiber earns
   its name by suspending when it blocks, which means an event loop — epoll,
   kqueue, IOCP — and non-blocking versions of every blocking call. The
   runtime's blocking calls are file I/O, and regular files do not work with
   epoll at all, so async file I/O means a thread pool or `io_uring`. That
   lands in problem 2 regardless.

2. **The runtime is single-threaded by construction, and this is the dominant
   cost.** `Orders <- [id > 0]` scans a `static Orders* Orders__rows[]` against
   a plain `strata_int Orders__count`. Under M:N that is a data race on every
   query. `__strata_current_message` becomes per-fiber state. The wasm bump
   allocator has no locking. Making this safe is either a lock per table —
   which removes the reason for wanting M:N — or genuine concurrent structures.
   This is a runtime-wide rewrite that fibers force rather than perform.

3. **There is no oracle.** Every feature so far was verified by running two
   implementations over the same input and demanding identical output. A
   scheduler has no oracle: correctness is about interleavings, which are
   nondeterministic. Deterministic seeded scheduling, stress tests and
   ThreadSanitizer are a new testing methodology, and this project's rule is
   that a claim without a failing test is a hope. The methodology has to exist
   before the feature can land.

4. **Colored functions.** If suspension is compiled rather than stack-switched,
   any function that can suspend infects its callers, and that surfaces in the
   type system.

**So the estimate splits:**

- Full M:N with async I/O and a thread-safe runtime: **months**, and most of it
  is problem 2, which is owed whether or not fibers are the reason.
- **Single-threaded stackless coroutines: 1–2 weeks.** This is the increment
  worth taking.

### The 1–2 week version, concretely

Strata owns its own code generator, so suspension can be compiled rather than
switched. A function marked `async` is transformed into a state machine:

- **Parser.** `async` on a function; `await <expr>` as an expression.
- **Type checker.** `await` is only legal inside an `async` function; a new
  diagnostic for calling one without awaiting. This is the colored-function
  rule, stated explicitly rather than discovered.
- **Code generator.** Each `async` function becomes a struct holding its locals
  and a resume point, plus a `step()` function with a `switch` on that point.
  Locals that live across an `await` move into the struct; the rest stay on the
  C stack. Each `await` is a `case` label.
- **Runtime.** The stream dispatch queue already exists and already drains
  cooperatively. A suspended coroutine parks on a channel and is resumed when a
  message arrives on it. `strata_run()` is already the loop.
- **Tests.** Because the schedule is deterministic — single thread, explicit
  resume points — the output is reproducible and the existing conformance
  harness works unchanged. That is the reason this version is tractable and the
  M:N version is not.

What it would **not** be: parallel, preemptive, or integrated with I/O. A
`stream` handler could await a query without blocking the drain. That is worth
having and it is worth saying plainly, the same way the `stream` row does.
The Virtual Event Fibers row stays "design only" until the runtime is
thread-safe.

---

## Part 5 — The pattern worth naming

This project has repeatedly produced things that looked finished and were not:
a commit claiming "32/32 passing" over a suite that was 30/31 and segfaulting;
"Stage 2 self-hosting complete" with a compiler that did not compile; a
self-repair loop that grepped source text instead of running the compiler;
twelve `bin/` tools that printed success and did no work.

It kept happening after those were fixed. A `report` block generated one
`fprintf` of its title and called a function that was never emitted. A query in
expression position had a code-generator branch that emitted `NULL`, unreachable
only because the parser refused to produce one. `save` wrote rows positionally
so that adding a column silently corrupted every file on disk. The repair loop —
the headline claim — had no test at all, and a renamed JSON key would have made
it repair nothing while reporting that nothing was possible.

The countermeasure is mechanical, not motivational: **every claim needs a check
that fails when the claim stops being true, and the check must exercise the path
the way it actually runs.** Not "does it compile" but "read back the file it
rendered" — because a report that emits only its title still runs and still
exits 0.
