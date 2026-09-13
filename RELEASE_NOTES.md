# v0.4.0-alpha

Changes since `v0.3.0-alpha` — 1 commit.

## Verified at release time

Each figure below was produced by running the suite that measures
it, at the moment these notes were generated.

| Check | Result |
|---|---|
| conformance | 64/64 passing |
| Lexer | 32 files identical, 0 divergent |
| Parser | 34 files identical, 0 divergent |
| Type checker | 46 files identical, 0 divergent |
| Documentation | 7 examples compiling, 0 marked roadmap |
| Code generator | 33 files byte-identical |
| Self-hosting fixpoint | reached — bootstrap can be retired |
| Standard library | 13 modules parse |
| Self-hosted compiler | 3,250 lines of Strata across 4 stages, 102 native (3%) |

## Other

- build: generate release notes from git history and live verification
