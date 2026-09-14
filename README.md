# Strata

**The compiler is the code reviewer.**

Strata is a systems language for a world where most code is written by machines.
Describe what you want, let a model write it, and let the compiler — not a tired
human on a Friday afternoon — prove the pieces actually fit. When it doesn't fit,
Strata hands the model a structured diagnostic and the model fixes it. Often
before you look.

```
$ strata build ledger.sta
  [E004] Column 'sec_tier' does not exist in 'UserProfile' (line 5, col 5)
  Hint: Valid columns: ['user_id', 'security_tier']

$ strata repair ledger.sta
  pass 1: E004 Database Schema Selector Violation (line 5)
    patch applied, recompiling
  clean after 1 repair(s).
```

That loop is real and runs today. Most of what surrounds it does not yet — see
[Roadmap](#roadmap), which is exhaustive and blunt.

> **Status: pre-release, under active development.** The compiler works and is
> covered by a conformance suite. Several components described under
> [Roadmap](#roadmap) are designed but not yet built, and are marked as such.
> Nothing in this document is claimed to work unless it is in
> [What works today](#what-works-today). Every code example below is compiled
> on every commit by `test_suite/doc_examples.py`.

---

## 1. Why another language

Most code will soon be written by machines and reviewed by people. That inverts
what a compiler is for.

When a human writes code, the compiler is a safety net for mistakes the author
already half-knows they might make. When a model writes code, the failure mode
is different: the output is *fluent and plausible and wrong*. It compiles, it
reads well, and the schema it queries has a column that does not exist. A
reviewer skims it, sees idiomatic code, and approves.

The languages we have were designed for the first case. Strata is designed for
the second. The premise is that **the compiler, not the reviewer, should be the
thing that catches it** — and that the compiler's output should be structured
well enough for a machine to act on without a human in the middle.

That leads to two design commitments:

**Contracts across tier boundaries are checked at build time.** A database
column, a network packet layout, a tensor shape — these are places where one
part of a system makes an assumption about another. In most stacks those
assumptions are strings, ORMs, or conventions, and they fail at runtime. In
Strata they are declarations the compiler checks.

**Diagnostics are data, not prose.** Every error carries a taxonomy code, a
location, a hint, and a remediation strategy, emitted as JSON. A repair agent
reads the diagnostic and patches the source without parsing human-readable
compiler text.

Strata is intended to be written by AI, read by AI, and reviewed by developers —
with the compiler as the arbiter that makes that division of labour safe.

---

## 2. What works today

### Compile-time database contracts

A `database` block is a schema the compiler knows about. Queries against it are
checked when you build, not when you deploy.

```text
import io from std;

database TransactionLedger {
    int   transaction_id;
    str   client_uuid;
    float capital_delta;
    str   compliance_status;
}

list[TransactionLedger] rejected_transactions() {
    list[TransactionLedger] violations = TransactionLedger <- [compliance_status == "REJECTED"];
    return violations;
}

int main() { print("audit ready"); return 0; }
```

Misspell `compliance_status` and the build stops with `E004`, naming the valid
columns. The same check applies to the write form of the operator:

```text
import io from std;
database AuditTrail { int event_id; str actor; str action; }
def record(int id, str who, str what) {
    AuditTrail <- [event_id = id, actor = who, action = what];
}
int main() { record(1, "prabath", "deploy"); return 0; }
```

An insert must name every column: leave one out and the build stops with
`E009`, because the alternative is writing it as a zero in every row the
statement creates, with nothing to show it was forgotten.

### Zero-copy structural casts

A `protocol` describes a byte layout. The `::` operator reinterprets a buffer as
that layout with no copy and no parse, and the compiler rejects a cast to a type
that was never declared.

```text
import io from std;
protocol NetworkPacketHeader { int packet_id; str target_routing_node; int data_payload_bytes; }
def handle(str socket) {
    NetworkPacketHeader header = current_raw_buffer() :: NetworkPacketHeader;
    if (header.data_payload_bytes > 32768) { print("oversized packet dropped"); }
}
```

### Explicit types and structure

Strata has no type inference and no dynamic coercion. Every declaration carries
its type, every block is brace-delimited, every statement is semicolon-
terminated.

```text
import io from std;
int risk_band(int score) { if (score > 850) { return 2; } return 1; }
int main() { int total = 400 + 500; print(str(risk_band(total))); return 0; }
```

This is a deliberate choice for machine authorship. Significant whitespace makes
a generated edit's meaning depend on invisible characters; explicit delimiters
make a patch unambiguous to apply and unambiguous to verify. Readability here
comes from explicit structure, not from resembling English — English is
ambiguous, and ambiguity is the thing being engineered out.

### WebAssembly

`--target wasm` builds a freestanding module — no libc, no runtime to ship —
exporting every top-level function:

```
$ strata build scoring.sta --target wasm -o scoring.wasm
```

Running it from a host:

```
exports: ['memory', 'classify', 'label', 'checksum', 'score_of']
classify(900) -> PRIME      label -> tier: PRIME
classify(100) -> SUBPRIME   label -> tier: SUBPRIME
```

Measured sizes, from the modules above rather than from an estimate: a module
of four string-handling functions is **595 bytes** (436 gzipped); two integer
functions are **136 bytes**. Strings and allocation work — `label` concatenates
through a bump allocator built into the prelude.

The trade-offs are real and worth stating. There is no `free`, so a
long-running module exhausts its heap; there is no file I/O; floats format to
six decimals rather than shortest-round-trip, because that needs `snprintf`.
This suits computation, not a server. And WebAssembly cannot touch the DOM, so
a UI still needs a JavaScript shim — the `layout` tier is server-rendered
instead.

### Model inference

A `model` declares a tensor contract the compiler enforces, and `predict` runs
it:

```text
import io from std;

model RiskScorer {
    input:  tensor[float, 1, 3];
    output: tensor[float, 1, 2];
}

int main() {
    tensor[float, 1, 3] features = strata_tensor(3);
    strata_tensor_set(features, 0, 2.0);
    strata_tensor_set(features, 1, 3.0);
    strata_tensor_set(features, 2, 4.0);

    strata_model_load(RiskScorer, "examples/risk_weights.txt");

    tensor[float, 1, 2] scores = predict RiskScorer(features);
    print(str(strata_tensor_get(scores, 0)));
    return 0;
}
```

Pass a tensor of the wrong shape and the build stops:

```
[E006] Tensor shape mismatch for 'RiskScorer': expected [1,3], got [1,32]
```

**The runtime is one dense layer** — `output = input x W + b`, weights read
from a whitespace-separated text file. No hidden layers, no activations beyond
the identity, no training, no GPU, no interop with existing frameworks. An
untrained model predicts zeros rather than garbage. This is enough for a linear
model to run and for the shape contract to mean something; it is not a machine
learning framework and is not meant to be read as one.

### Tests in the language

A `verify` block is a test. `strata test` builds and runs them:

```
$ strata test test_suite/verify_cases
  doubling
  halving
    FAIL  line 12: half(...) == 4

  2 block(s), 5 assertion(s), 1 failed
```

A failing assertion reports its line and a rendering of the expression, and
does not stop the rest of the block — one broken assertion should not hide the
others. The process exits non-zero if anything failed.

No fixtures, no setup and teardown, no parallelism, no filtering.

### Persistence

Tables are written as tab-separated text, with serialisers generated from the
schema:

```text
import io from std;
database Account { int id; str holder; float balance; }

int main() {
    load Account from "accounts.tsv";
    list[Account] existing = Account <- [id > 0];
    print(str(len(existing)));

    Account <- [id = 1, holder = "alpha", balance = 1250.75];
    save Account to "accounts.tsv";
    return 0;
}
```

Text rather than a binary format, so a table is inspectable with the tools
everyone already has. Tabs, newlines and backslashes in string fields are
escaped.

What this is not: there is no schema versioning, no migration, no locking, no
index and no transaction. A file written under one schema will mis-parse under
another, and two writers will corrupt it. It is enough for one process to keep
state across restarts.

### Calling existing C libraries

A `foreign` block declares what a library provides. The signatures are
registered like any other function, so the boundary is checked rather than
trusted.

```text
import io from std;

foreign "math.h" link "m" {
    float sqrt(float x);
    float pow(float base, float exponent);
}

int main() {
    print(str(sqrt(144.0)));
    print(str(pow(2.0, 10.0)));
    return 0;
}
```

Pass a `str` where the library expects a `float` and the build stops with
`E005` — Boundary Perimeter Contamination — rather than producing undefined
behaviour at runtime.

### Machine-readable diagnostics

```
$ strata build ledger.sta --json
```
```json
{
  "file": "ledger.sta",
  "stage": "typecheck",
  "ok": false,
  "error_count": 1,
  "diagnostics": [
    {
      "code": "E004",
      "classification": "Database Schema Selector Violation",
      "severity": "CRITICAL_HALT",
      "message": "Column 'sec_tier' does not exist in 'UserProfile'",
      "line": 5,
      "column": 5,
      "hint": "Valid columns: ['user_id', 'security_tier']",
      "remediation_strategy": "Audit database table block schemas, match column property name spellings inside query bracket filters."
    }
  ]
}
```

### The repair loop

`ai_self_repair.py` compiles, reads the diagnostics, patches, and recompiles
until the file is clean or no further progress is possible:

```
[Strata Repair] target: ledger.sta   backend: rules

  pass 1: 2 diagnostic(s) at stage 'typecheck'
    E001 Variable Mutation Mismatch (line 4): Type mismatch: 'request_count' declared as 'int' but assigned 'str'
    patch applied, recompiling

  pass 2: 1 diagnostic(s) at stage 'typecheck'
    E004 Database Schema Selector Violation (line 5): Column 'sec_tier' does not exist in 'UserProfile'
    patch applied, recompiling

[Strata Repair] clean after 2 repair(s).
```

`test_suite/self_repair.py` runs on every commit. It checks the loop — that it
converges, that it stops rather than spinning when a repair needs judgement,
that `--dry-run` restores the file byte for byte — and, more importantly, the
JSON contract the loop depends on. Every key the loop reads is asserted
present and correctly typed, because renaming one would not break the loop
loudly; it would make it repair nothing and report that nothing was possible.


Repair backends are pluggable. `rules` is deterministic and offline. `llm` sends
the diagnostic and source to a language model and needs no prior knowledge of
Strata, because the classification and remediation strategy travel with the
error.

### Error taxonomy

| Code | Classification | Raised when |
|------|----------------|-------------|
| `E001` | Variable Mutation Mismatch | assigned value conflicts with the declared type |
| `E002` | Function Return Contract Breach | a return path breaks the signature |
| `E003` | Generic Collection Pollution | mixed types enter a homogeneous list |
| `E004` | Database Schema Selector Violation | a query or insert names a column that does not exist |
| `E005` | Boundary Perimeter Contamination | untyped data crosses a type boundary |
| `E006` | Tensor Dimension Drift | a tensor does not match its declared shape |
| `E007` | Unresolved Module Import | an import names a module with no local checkout |

`E001`–`E006` are `CRITICAL_HALT`: they stop the build. `E007` is `ADVISORY` —
it is reported and the build continues, because a dependency provided at link
time is legitimate. The JSON payload separates them: `error_count` and `ok`
count only halting diagnostics, `advisory_count` the rest, so a repair loop
does not burn passes on something it cannot fix.

Defined in `ERROR_TAXONOMY.json`, which is the contract repair agents consume.

---

## 3. Toolchain

```
strata build <file.sta>          compile to a native binary
strata build <file.sta> --json   compile, emitting diagnostics as JSON
strata build <file.sta> --test   build a runner for the file's verify blocks
strata check <file.sta>          type-check without generating code
strata test <dir>                build and run every verify block in <dir>
```

The bootstrap compiler is written in Python and generates C, which is then
compiled to a native binary. This is how most languages begin — Rust's first
compiler was written in OCaml, Go's in C, and C++ shipped for years as a
preprocessor that emitted C. Self-hosting is on the roadmap below. Users write
only `.sta` files; the implementation language is not part of the programming
model.

---

## 4. Adoption

**One file, one command.** A Strata program is a `.sta` file. `strata build`
turns it into a native binary. There is no project scaffold to generate, no
build system to configure, no dependency manifest to satisfy before hello world.

**Nothing to learn that you don't already know.** Braces, semicolons, explicit
types, C-family control flow. A developer reading Strata for the first time is
reading something familiar on purpose — the novelty is in what the compiler
checks, not in the syntax you have to memorise.

**The error tells you the fix.** Every diagnostic carries the valid alternatives,
not just the complaint. `Column 'sec_tier' does not exist` is followed by
`Valid columns: ['user_id', 'security_tier']`. That is what makes the repair loop
possible, and it is also just a better developer experience.

---

### The cross-tier contract

A column is declared once, queried in the middle tier, and rendered on screen.
Rename it in the `database` block and the build fails at the line of UI that
used it.

```text
database ServiceMetric { int id; str service_name; str operational_status; }

layout OperationsConsole() {
    window "Service Health" [width = 1200] {
        list[ServiceMetric] degraded = ServiceMetric <- [operational_status == "DEGRADED"];
        for Row in degraded {
            row [padding = 10] { text Row.service_name [color = "#ffffff"]; }
        }
    }
}
```

Rename `service_name` to `svc_name` and:

```
[E004] Field 'service_name' not in 'ServiceMetric' (line 6, col 30)
Hint: Valid fields: ['id', 'svc_name', 'operational_status']
```

Not a runtime 500 in front of a user — a build error, before anything ships.
The loop variable carries the row type from the query to the screen, which is
what a library cannot do and a compiler can.

`examples/cross_tier_contract.sta` runs this end to end: rows are inserted,
the query filters them, and the layout renders HTML containing the two matching
services. The table runtime is in memory only — no persistence, no index, no
transactions (see [Roadmap](#roadmap)).

---

## 5. Where this is going

**Everything in this section is direction, not shipped behaviour.** It is here so
the intent is legible. The [Roadmap](#roadmap) table states what actually exists.

**Self-healing builds.** The repair loop exists today with a deterministic
backend. The intended shape is a build that repairs itself: the compiler halts,
an agent reads the structured diagnostic, patches, and rebuilds — with the
developer reviewing a diff rather than hunting a stack trace. Because the
taxonomy travels with every error, the agent needs no prior knowledge of Strata.

**Types that reach the screen.** The goal is a contract checked from the database
index all the way onto the client: rename a column in a `database` block, and the
build fails on the line of UI that rendered it. Not a runtime 500 — a build
error, before anything ships. This is the reason Strata exists as a language
rather than a library.

**Migration as a mechanical act.** If contracts are explicit and compiler-checked,
translating an existing Java or C# service becomes something a model performs and
a compiler verifies, instead of a rewrite a team has to take on faith. The
compiler is what makes the translation trustworthy.

**Models as declarations.** `model` blocks already declare tensor shapes and the
compiler already enforces them (`E006`). What does not exist is an inference
runtime. The intent is that a shape mismatch is a build error rather than a
production exception — the same argument as the database contract, applied to ML.

### Loops, assignment and indexing

Landed in Phase 1. A bubble sort is a reasonable smoke test for a language core:

```text
import io from std;

int main() {
    list[int] data = [37, 5, 91, 12, 68, 4, 23];
    int n = 7;

    for (int i = 0; i < n - 1; i = i + 1) {
        for (int j = 0; j < n - i - 1; j = j + 1) {
            if (data[j] > data[j + 1]) {
                int tmp = data[j];
                data[j] = data[j + 1];
                data[j + 1] = tmp;
            }
        }
    }

    for (int k = 0; k < n; k = k + 1) { print(str(data[k])); }
    return 0;
}
```

`while`, `for`, `break`, `continue`, assignment and list indexing all work.
Assigning the wrong type to an existing binding is `E001`; indexing with a
non-integer, or indexing something that is not a list, is caught at build time.

---

## 6. Roadmap

Designed, specified, and **not yet built**. Listed here so the boundary between
what runs and what is planned is unambiguous.

| Area | Status |
|------|--------|
| Loops (`while`, `for`), assignment statements, array indexing | **Done.** Phase 1. Declaration without an initialiser (`int n;`) zeroes rather than leaving the stack's contents. |
| Self-hosting compiler (`compiler/*.sta`) | **Done for the front end.** Lexer, parser, type checker and code generator are written in Strata — 3,250 lines, 3% `native`. Each matches its Python counterpart exactly, and the fixpoint holds: the front end rebuilt from C it generated itself reproduces that C byte for byte. |
| `layout` blocks and the UI tier | **Checked and rendering.** A field rendered in a `layout` resolves against the database schema at build time, and layouts compile to a function that writes HTML. Server-rendered; no client-side interactivity. |
| WebAssembly target | **Working for computation.** `--target wasm` emits freestanding C that clang builds into a module exporting every top-level function. No libc: a bump allocator, no file I/O, and `print` goes through one imported host function. Not a UI story — WebAssembly has no direct DOM access, so any UI needs a JavaScript interop shim, as it does for every WASM framework. |
| `verify` blocks | **Done.** `strata test` builds and runs them, reporting each failed assertion with its line and source. Nested `assert "label" { ... }` groups are supported. No fixtures, no setup/teardown, no parallelism. |
| Queries (`Source <- [cond]`) | **An expression.** A query parses anywhere a value is expected — an argument, a function call, a comparison — not only on the right of a declaration, where it used to be the only place it parsed. It yields `list[T]` of the matching rows, and the E004 column contract holds at the query line wherever it appears. Conditions compare a column against a value; there are no joins, no ordering, no aggregation and no index — a query is a scan. |
| Aggregation | **`sum`, `avg`, `min`, `max`, `count`.** A column is projected with `rows.column` and checked against the schema, so renaming a column fails the build at the aggregate. `sum`/`min`/`max` keep the column's own type; `avg` is float; `count` takes the rows. An empty result aggregates to zero. No `GROUP BY`, no `HAVING`, and no aggregate inside a query condition — an aggregate reads a list that already exists. |
| Lists | A list carries its element count in the word before its data. NULL-termination cannot work, because 0 is a valid int and `""` a valid str — which is why `len([1,2,3])` used to return whatever followed the array in memory. |
| Database persistence | **`save` / `load` to tab-separated text, with schema migration.** The file carries a header naming each column and its type, so a table saved by one version of a schema loads under another: a dropped column is skipped, a new one keeps its zero value, columns match by name rather than position, and a column whose type changed is refused rather than misread. A file written before headers existed is refused with a message saying to re-save it. Still no locking, no index, no transactions and no SQL backend — two writers will corrupt it. |
| `model` / `predict` execution | **A stack of dense layers.** A model declares hidden layers between its input and output, each with an activation — `relu`, `sigmoid` or `none`; the output layer is linear. `predict` runs the forward pass with weights loaded from a text file, laid out layer by layer, and a file with the wrong weight count is refused rather than loaded in part. Inference only: no training, no autograd, no convolution or attention, no accelerator, no framework interop. The WebAssembly target has no libm, so `exp` is implemented in the prelude; it agrees with libm to about 1e-15 relative. |
| `report` / `render` | **Renders.** A report runs its datasource, evaluates its metrics with `rows` bound to the result, and writes Markdown: the title, each metric, the matching rows as a table, and a row count. Metrics are type-checked (E001) and the datasource gets the E004 column contract. Metrics see `rows`, not the columns of a row — there is no aggregation, so `sum(col)` does not exist. Markdown only; no other output format, no charts, no templates. |
| `stream` blocks | **Dispatching.** Each `stream` handler registers under its own name as a channel; `strata_publish(channel, message)` enqueues and `strata_run()` drains the queue, returning the number delivered. Handlers may publish while the queue drains. This is a cooperative single-threaded loop: no separate stacks, no preemption, no parallelism, no I/O integration. Messages to an unknown channel are dropped. |
| Virtual Event Fibers | Design only. No scheduler exists — `stream` dispatch above is a queue drain, not fibers. |
| FFI | **Done.** A `foreign` block includes a C header, names the library to link, and declares signatures that are checked at call sites. No callbacks from C into Strata, no struct marshalling. |
| Calls to undefined functions | **Caught as E002.** Imports are resolved before the type check, so the set of reachable names is known and a typo names the typo rather than a C symbol at link time. It is a `--json` diagnostic, so the repair loop can see it. The rule disarms for a file importing a module with no local checkout — that picture is incomplete. It checks that a name exists, not its signature: argument count and types are still unchecked across a module boundary. |
| `E009` | An insert that does not name every column of the table. The unnamed ones would be written as a zero or an empty string in every row the statement creates, so adding a column to a schema used to break nothing and quietly corrupt everything. It is the error that makes a schema change a build failure. |
| `E007` / `E008` | E007 is the first advisory: an import with no local checkout is reported without stopping the build. E008 catches a bare name inside a query that is also a variable in scope — the column wins silently, so `Session <- [token == token]` compares the column with itself and matches every row. |
| Sessions and passwords | `std/auth.sta`: SHA-512 `crypt(3)` with a random salt over FFI, and session tokens from `/dev/urandom`. No rate limiting, no lockout, no password policy, no reset flow, no CSRF protection. |
| Formatter (`strata fmt`) | **Canonical indentation.** Written in Strata. Re-indents by brace depth, strips trailing whitespace, collapses blank runs, ends the file with one newline. It rewrites only leading whitespace, so comments survive and the inside of a `native` block is byte-identical — the lexer discards comments, so anything reprinting from tokens would delete them. It does **not** re-wrap lines, normalise spacing around operators, or sort anything. Two properties are tested over every file in the repo: the syntax tree is unchanged, and formatting is idempotent. CI fails if any tracked source is not canonical. |
| Standard library | **Eight modules that compile, link and run** — `io`, `core`, `mem`, `str`, `ml`, `simd_math`, `telemetry`, `testing`. Five more (`runtime`, `stdlib`, `tls`, `pkg_system`, `pkg_manager`) are quarantined in `std/unimplemented/`: they describe POSIX syscalls, an HTTP client and a TLS 1.3 handshake that were never built, and call functions that exist nowhere. Six examples built on them are quarantined too. |
| Migration tooling (Java/C# → Strata) | Direction, not yet a project. |

No performance numbers are published, because none have been measured. Figures
will appear here when there is a benchmark behind them.

---

## 7. Verification

```
python3 test_suite/conformance.py     # language conformance, E001-E007 + end-to-end
python3 test_suite/doc_examples.py    # compiles every code block in this file
```

Both run in CI on every push, alongside a check that every standard library
module parses. The documentation suite exists because this README previously
described an example that did not compile, and the error had already propagated
into the example programs before anyone noticed. Documentation that cannot be
compiled is documentation that will drift.

---

## 8. Direction

The long-term goal is that a requirement goes in, a working system comes out,
and developers review rather than type. That is only responsible if the compiler
can prove the parts fit together — which is why the verification work comes
before the language surface grows.

A second goal follows from the first: if contracts are explicit and checkable,
translating an existing Java or C# service into Strata becomes a mechanical task
a model can perform and a compiler can check, rather than a rewrite a team has
to trust. That is a direction, not a shipped feature.
