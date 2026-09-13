# v0.3.0-alpha

## Verified at release time

Each figure below was produced by running the suite that measures
it, at the moment these notes were generated.

| Check | Result |
|---|---|
| conformance | 63/63 passing |
| Lexer | 32 files identical, 0 divergent |
| Parser | 31 files identical, 0 divergent |
| Type checker | 43 files identical, 0 divergent |
| Documentation | 7 examples compiling, 0 marked roadmap |
| Standard library | 13 modules parse |
| Self-hosted compiler | 2,313 lines of Strata across 3 stages, 93 native (4%) |

## Features

- **phase5**: typechecker.sta — E001-E006 in Strata; fix an E005 false positive
- **phase4**: parser.sta — the Strata parser, written in Strata
- **phase3**: lexer.sta — the Strata lexer, written in Strata
- **lang**: stdlib now parses — # directives, insert statement, print demoted
- **imports**: dotted module paths and stdlib module resolution
- **tests**: conformance suite 32/32 — E001-E006 + 6 end-to-end all pass
- **compiler**: complete bin/strata rewrite — E001-E006 type checking in build+check
- **milestone**: Stage 2 — Strata self-hosting complete
- **milestone**: Stage 1 complete — Strata compiler written in Strata, compiles and runs
- **compiler**: Stage 0 extended — full native block support, compiles .sta to binary
- **strata**: Stage 1 — parser.sta and compiler.sta written in Strata
- **compiler**: Component 3 — Type Checker (E001-E006 at compile time)
- **compiler**: Stage 0 complete — .sta compiles to native binary
- **compiler**: Component 2 — Real Parser + AST (full grammar coverage)
- **compiler**: Component 1 — Real Lexer (44 token types)

## Fixes

- **codegen**: generated C relied on implicit function declarations
- **ci**: stdlib parse check was broken by YAML indentation; untrack build output
- **codegen,parser**: type-directed + dispatch and multiplicative precedence
- **compiler.sta**: rewrite with properly escaped native C strings
- **compiler.sta**: escape newlines in native C string literals
- **stage0**: native blocks emit raw C, borrow on member access, newlines preserved
- **parser**: native block statements parsed correctly — no semicolon required
- **parser**: support forward declarations — fn(params); with no body
- **parser**: _consume_name inserted at correct indent inside Parser class
- **parser**: surgical fix — keywords as names in imports and all name positions
- **lexer**: allow newlines inside string literals for native blocks
- **compiler**: Parser import path — works from project root and bin/
- **compiler**: Lexer syntax error — clean rewrite via raw string

## Verification

- **docs**: compile documentation examples in CI; validate report datasource

## Documentation

- audit findings, roadmap-block tracking, and the adoption/vision sections
- **readme**: rewrite around the verification thesis; separate shipped from planned

## Housekeeping

- add .gitignore — exclude pycache and generated C files

## Release

- v0.3.0-alpha — changelog, honest version, no fabricated dependencies

## Other

- Testing: Implement formal language conformance tests and configure cloud CI/CD pipeline
- Compliance: Publish formal language versioning rules, compatibility contracts, and stable 1.0.0 changelog
- Examples: Implement advanced high-frequency transaction ledger sample application
- Documentation: Deploy unabridged language reference, tutorials handbook, and standard API documentation
- SDK: Implement first-class verify keyword testing blocks and add pipeline test template
- IDE: Implement native language server protocol daemon and VS Code editor configurations
- SDK: Implement native low-overhead fiber debugger and stack tracing core engine
- Compiler: Implement high-fidelity machine-parseable diagnostics engine and error hooks
- SDK: Implement std/pkg_system.sta decentralized module system and cryptographic import resolver
- SDK: Finalize master bin/strata command suite adding new, run, and format commands
- Documentation: Deploy hands-on engineering lead onboarding workshop manual and coding labs
- Documentation: Deploy comprehensive visual architecture manual for executive validation loops
- SDK: Implement comprehensive std/stdlib.sta systems libraries and add bin/strata-sync package registry publisher
- SDK: Implement std/runtime.sta native systems runtime execution core and add capability integration test template
- Compiler: Implement ahead-of-time master translation engine emitting machine code and Wasm
- Compiler: Implement ahead-of-time semantic analyser, scope validator, and type checker tool
- Testing: Implement native automated regression test suite validation engine
- Fix: Re-instantiate missing compiler bin components into workspace path
- Compiler: Implement direct ahead-of-time WebAssembly Text (WAT) code generator module
- Compiler: Implement character-by-character native lexer token mapping utility
- Core: Publish comprehensive formal Strata language specifications manual and EBNF schemas
- Deployment: Implement enterprise-grade production deployment script package and K8s manifests
- SDK: Implement std/tls.sta native TLS 1.3 cryptographic engine and add secure ledger stream template
- SDK: Implement automated strata-bindgen FFI code-generation binder tool
- SDK: Implement low-level WebAssembly SIMD math primitives and vectorization templates
- Feature: Implement compile-time memory reference borrowing layout specification
- SDK: Implement std/telemetry.sta core instrumentation layers and add monitored service template
- SDK: Implement std/ml.sta core machine learning primitives and add predictive analytics template
- Deployment: Update cloud deployment tool to support local simulation fallbacks
- Deployment: Implement comprehensive cloud deployment workflow IaC blueprints
- SDK: Implement std/pkg_manager.sta resolution layer and link third-party download hooks
- IDE: Implement VS Code workspace settings and native LSP connection maps
- Core: Ship AOT compiler, establish std, build python ML FFI, and publish open error taxonomy standard
- SDK: Completely eliminate python runtime scripts from LSP and Benchmark drivers
- SDK: Implement interactive compiler orchestration manager demo command
- Fix: Re-architect bin/strata driver syntax layout loops to resolve bench token error
- SDK: Implement bin/strata-bench harness and layout metric sheets
- SDK: Implement declarative package manager config Strata.toml and Strata.lock
- Feature: Implement high-volume binary serialization protocol template using zero-copy casting
- SDK: Implement std/core.sta Standard Library and bin/strata-lsp background engine
- SDK: Implement Strata.toml manifest and unified bin/strata toolchain driver
- Documentation: Overhaul master README with AI primitives, reporting modules, and network serialization protocols
- Feature: Implement sample brace-enclosed frontend UI layout component specification
- Documentation: Final master rebuild of README unifying all corporate full-stack specifications
- Documentation: Expand README with Python-vs-Strata web architecture paradigm
- Deployment: Implement production automated container build and orchestration script
- Feature: Implement automated AI self-repair utility script for local .sta files
- Feature: Implement native AI model topology keywords and predict tensor operator
- Documentation: Implement developer getting-started quick-start script template
- Testing: Implement local CLI automated test suite verification loops
- Automation: Implement continuous validation check pipeline via GitHub Actions
- Testing: Implement native CLI automated compiler execution test suite script
- Documentation: Expand README with code blueprints, error matrix, and fiber concurrency specs
- Documentation: Overhaul README detailing ideation and enterprise architectures
- Deployment: Implement multi-stage production Docker container blueprint
- Initial commit: AI-Engineered Strata Enterprise Configuration Tree
