# v0.5.0-alpha

Changes since `v0.4.0-alpha` — 39 commits.

## Verified at release time

Each figure below was produced by running the suite that measures
it, at the moment these notes were generated.

| Check | Result |
|---|---|
| conformance | 182/182 passing |
| Lexer | 67 files identical, 0 divergent |
| Parser | 77 files identical, 0 divergent |
| Type checker | 95 files identical, 0 divergent |
| Documentation | 15 examples compiling, 0 marked roadmap |
| Code generator | 70 files byte-identical |
| Self-hosting fixpoint | reached — bootstrap can be retired |
| Repair loop | 48/48 checks passing |
| Projects | 14/14 checks — a project builds and the service serves |
| Formatter | meaning preserved and idempotent over 79 files |
| Standard library | 12 modules compile, link and run (5 quarantined) |
| Self-hosted compiler | 5,842 lines of Strata across 4 stages, 102 native (2%) |

## Features

- **lang**: delete, and a repair loop that needs no API key
- **operate**: stage 10 — the service can be run by someone
- **deploy**: stage 9 — the real image builds outside CI
- **apps**: a second application, and the five gaps it found
- **deploy**: the image is built and run, and the service logs
- **journey**: the service survives contact
- **journey**: a developer can change the system
- **journey**: an operations manager can run the orders desk
- **web**: forms — data flows inward
- **check**: the cross-tier contract reaches every file
- **cli**: a project is the unit of building
- **app**: a Strata service that runs and serves
- **lang**: aggregation, and the len() bug underneath it
- **fmt**: strata fmt — canonical formatting, written in Strata
- **check**: E007 for unresolved imports, and advisories in the taxonomy
- **std**: the standard library compiles, links and runs
- **check**: calls to undefined functions are E002, not linker errors
- **lang**: streams, queries, reports, migrations, layers — and the repair loop gets tests
- **test**: strata test builds and runs verify blocks
- **runtime**: table persistence — save and load
- **lang**: every example compiles — 19 of 19
- **ml**: inference runtime for model/predict; fix UTF-8 column counting
- **wasm**: freestanding WebAssembly target, with measured sizes
- **ffi**: foreign blocks — call C libraries with the boundary type-checked
- **runtime**: in-memory tables — the cross-tier demo renders real rows
- **lang**: title, metrics, datasource, input, output and to are contextual
- **layout**: render layouts to HTML from the C backend
- **layout**: cross-tier contract — a renamed column fails the build at the UI

## Fixes

- **journey**: the image must ship the real port
- **codegen**: a table's serialisers only handle scalar columns
- **lang**: string equality compared pointers; self-hosted compiler builds the service
- track compiler/runtime_preamble.c; verify the committed tree builds

## Documentation

- CI is green — run #105, 32 steps
- closures are provisional until CI is green on a pushed commit
- the ten stages, and what closing one requires

## Housekeeping

- the service's lock file is not source
- note the verified check-in path
- **tools**: a check-in script that works from an unattended session
- progress log for unattended runs
