# Changelog

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
