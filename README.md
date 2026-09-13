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
def record(str who, str what) { AuditTrail <- [actor = who, action = what]; }
int main() { record("prabath", "deploy"); return 0; }
```

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

Defined in `ERROR_TAXONOMY.json`, which is the contract repair agents consume.

---

## 3. Toolchain

```
strata build <file.sta>          compile to a native binary
strata build <file.sta> --json   compile, emitting diagnostics as JSON
strata check <file.sta>          type-check without generating code
strata test                      run the conformance suite
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
| Loops (`while`, `for`), assignment statements, array indexing | **Done.** Phase 1. |
| Self-hosting compiler (`compiler/*.sta`) | **Lexer, parser and type checker done** — 2,313 lines of Strata, 4% of it `native`. Each produces output identical to its Python counterpart across the corpus and on its own source: byte-identical token streams, identical syntax trees, identical diagnostics. Code generator remains, then the stage1/stage2 fixpoint. |
| `layout` blocks and the UI tier | Specified in the grammar, not implemented. |
| WebAssembly target | Planned via clang from the existing C output. Note that WebAssembly has no direct DOM access; a JavaScript interop shim is required for any UI, as it is for every WASM UI framework. |
| `model` / `predict` execution | Declarations and shape checking work. There is no inference runtime — `strata_predict` is not yet implemented. |
| `report` / `render` | Parsed; emits a title only. No aggregation or document generation. |
| Virtual Event Fibers | Design only. No scheduler exists. |
| FFI | Not started. Required for adoption. |
| Migration tooling (Java/C# → Strata) | Direction, not yet a project. |

No performance numbers are published, because none have been measured. Figures
will appear here when there is a benchmark behind them.

---

## 7. Verification

```
python3 test_suite/conformance.py     # language conformance, E001-E006 + end-to-end
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
