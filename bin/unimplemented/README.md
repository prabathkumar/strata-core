# Unimplemented tools

Every script in this directory **printed success without doing the work it
claimed**. They are kept here for reference while being rewritten, and are
deliberately not on `PATH`.

Do not run these expecting results, and do not cite their output as evidence
of anything.

| Tool | What it actually did |
|---|---|
| `strata-checker` | Never called the type checker. Two `grep -q` matches faked E001/E004; everything else printed "Semantic evaluation cleared safely" and exited 0 — including for files that do not exist. |
| `strata-codegen` | Echoed a fixed 5-line WAT module, ignoring its input. |
| `strata-compiler` | Printed "COMPILATION SUCCESSFUL — dist/production_bundle.wasm (14.8 KB)" and "settled in 42.15 ms" while writing zero bytes. This is the origin of the 15KB figure. |
| `strata-debug` | Pure echo. Hardcoded breakpoint line and fake addresses, identical for any input. |
| `strata-bench` | Entirely hardcoded numbers. No timing code. |
| `strata-lsp` | No JSON-RPC framing and no stdout responses. Cannot function as an LSP. |
| `strata-bindgen` | Ignored the input header and wrote a fixed heredoc. |
| `strata-deploy` | Reported healthy liveness probes on a production IP where nothing was deployed. |
| `strata-sync` | Wrote `sha256:e3b0c442...b855` — the hash of the empty string — into `Strata.lock` with a fake upload confirmation. |
| `strata-test` | "Validated" codegen against the codegen stub's own hardcoded output. Contained `echo -p`, an invalid flag. Exited 1. |
| `strata-errors` | A message formatter only; its sole caller was the grep-based checker. |
| `strata-stage1.macho` | A prebuilt macOS Mach-O binary, unrunnable on Linux/CI and unverifiable from source. |

The working toolchain is `bin/strata` (build, check, ast, test), plus
`bin/strata-lexer` and `bin/strata-parser`.

Verification lives in `test_suite/conformance.py` and
`test_suite/doc_examples.py`, both of which run in CI.
