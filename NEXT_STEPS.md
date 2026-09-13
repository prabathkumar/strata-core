# Strata — Audit and Next Steps

Full read of the repository. Every claim below was verified by running code, not
by reading comments.

---

## Part 1 — What is real

| Component | State |
|---|---|
| `compiler/lexer.py`, `parser.py`, `typechecker.py` | Real. 1,442 lines. The type checker genuinely implements E001–E006. |
| `bootstrap/stage0.py` | Real. Parses, type-checks, generates C, invokes the C compiler. The only working compile path. |
| `std/*.sta` | 13 modules, all parse. Written in Strata. |
| `test_suite/conformance.py` | Real. 43 tests, all passing. |
| `test_suite/doc_examples.py` | Real. Compiles every documentation example on every commit. |
| `ai_self_repair.py` | Real. Compiles, reads JSON diagnostics, patches, recompiles. |
| `bin/strata`, `bin/strata-lexer`, `bin/strata-parser` | Real wrappers over the above. |

## Part 2 — What is not

**12 of the 15 tools in `bin/` are stubs that print success without doing work.**

| Tool | Finding |
|---|---|
| `strata-checker` | Does not call the type checker. Two `grep -q` matches fake E001/E004; everything else prints "Semantic evaluation cleared safely" and exits 0 — **including for files that do not exist**. |
| `strata-codegen` | A single `echo` of a fixed 5-line WAT module. Ignores its input entirely. |
| `strata-compiler` | Prints "COMPILATION SUCCESSFUL — dist/production_bundle.wasm (14.8 KB)" and "settled in 42.15 ms". Writes zero bytes. No `dist/` is ever created. |
| `strata-test` | "Validates" codegen by checking the stub's own hardcoded output. Contains `echo -p`, an invalid flag. Currently exits 1. |
| `strata-debug` | Pure echo. Hardcoded breakpoint line, fake hex addresses, identical output for any input. |
| `strata-bench` | 100% hardcoded numbers. No timing code exists. |
| `strata-lsp` | No JSON-RPC framing, no stdout responses. Cannot function as an LSP. |
| `strata-bindgen` | Ignores the header file. Writes a fixed heredoc regardless of input. |
| `strata-deploy` | Reports three healthy liveness probes on production IP `104.22.41.82`. Nothing is deployed. |
| `strata-sync` | Writes `sha256:e3b0c442...b855` into `Strata.lock` — the SHA-256 of the **empty string** — alongside a fake "upload SUCCESS". |
| `strata-stage1` | A prebuilt macOS Mach-O binary committed to the repo. Cannot run on Linux/CI. |
| `strata-errors` | A formatter only. Its sole caller is the grep-based checker. |

**Two of these are actively dangerous in an evaluation:**

1. `strata-deploy` tells a viewer that production pods are healthy. They do not exist.
2. `strata-sync` forges a checksum into a tracked file. `Strata.lock` contains that
   empty-string hash **twice**, plus a second value that is not even valid hex length.
   Nothing in the lockfile can be trusted.

**Language gaps blocking everything else:**

- No `while`, no `for`, no loops of any kind.
- No assignment statement — `int i = 0;` is legal, `i = 5;` is not.
- No array indexing — `a[0]` does not parse.
- No module-level variables.

These are why `compiler/lexer.sta` is 92 lines of constants containing no lexer:
scanning characters requires iteration, mutation and indexing. **Self-hosting
cannot begin until these land.**

Other findings: `strata-core/` is a nested git repository inside the repo.
`ARCHITECTURAL_MANUAL.md` still carries the unmeasured performance figures that
were removed from the README.

---

## Part 3 — Next steps

### Phase 0 — Stop the bleeding (1 day)

The stub tools are the single biggest risk to your evaluation, because a
developer will run one, believe it, and then discover it was theatre.

1. Delete or move to `bin/experimental/` every stub tool, or rewrite each to print
   `not implemented` and exit non-zero. **Do this before any developer sees the repo.**
2. Purge the forged checksums from `Strata.lock`. Regenerate or empty it.
3. Remove `bin/strata-stage1` — a committed macOS binary cannot be verified or run in CI.
4. Remove the nested `strata-core/.git`.
5. Strip the unmeasured figures from `ARCHITECTURAL_MANUAL.md`.

### Phase 1 — The language core (1–2 weeks) ← **the floor**

Nothing else can start. Implement across lexer → parser → typechecker → codegen:

1. Assignment statement (`i = 5;`), with E001 on type mismatch.
2. `while` loops.
3. `for` loops.
4. Array indexing (`a[i]`), read and write, with bounds semantics decided.
5. Module-level variables.

Each lands with conformance tests. Exit criterion: a bubble sort compiles and runs.

### Phase 2 — Freeze the seed subset (3–5 days)

Write down the minimum feature set required to express a compiler. Make
`stage0.py` correct for exactly that. Get `std/str.sta` and `std/mem.sta`
genuinely compiling and linking — a lexer depends on them.

### Phase 3 — `lexer.sta` (1–2 weeks)

**Differential testing is the method.** The Python lexer is the oracle: run both
over the same input and require byte-identical token streams. Not "looks right."

### Phase 4 — `parser.sta` (2–4 weeks)

Same discipline. Both parsers emit AST JSON via the existing `--ast` flag; the
JSON must match exactly.

### Phase 5 — typechecker and codegen in Strata (3–6 weeks)

Generated C compared against the Python compiler's output.

### Phase 6 — The fixpoint

`stage0` compiles `compiler.sta` → `strata1`. `strata1` compiles `compiler.sta`
→ `strata2`. If `strata1` and `strata2` are byte-identical, self-hosting is
proven. This is the milestone to announce, and it is objective.

### Then, in order

FFI. WASM via clang from the existing C output. `layout` blocks and the vertical
slice demo. An inference runtime for `predict`. Fibers.

---

## Part 4 — The single most valuable demo

Not a feature. A thirty-second sequence:

1. A `database` block, a typed query, a rendered field.
2. Rename the column.
3. The **build fails**, pointing at the line of UI that used it.

No other stack does this. Blazor shares a language but the schema contract still
breaks at runtime. `sqlx` checks SQL at compile time but nothing reaches the
screen. This demo is the argument for Strata existing as a language, and
everything in Phases 1–6 is in service of being able to run it honestly.

---

## Part 5 — The pattern worth naming

Three times now this project has produced something that looked finished and was
not: a commit claiming "32/32 passing" while the suite was 30/31 and segfaulting;
"Stage 2 self-hosting complete" with a compiler that does not compile; a
self-repair loop that grepped source text instead of running the compiler. The
`bin/` audit is the same pattern at scale.

The countermeasure is mechanical, not motivational: **every claim needs an
executable check.** The conformance suite, the documentation harness and the
differential testing above all exist for that reason. A claim without a test that
fails when it stops being true is not a status — it is a hope.
