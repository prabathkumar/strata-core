# The ten stages, and which are closed

The end-to-end pipeline a Strata program passes through, from someone typing a
line to a service running in production. This file is the record; the same map
is published as the "Strata End to End" artifact.

**A stage is closed when a suite that runs on every commit proves it, and that
suite exits non-zero when it does not.** Not when the code exists, not when it
worked once by hand. Anything that has never been run is marked as not run,
never counted as closed.

| # | Stage | State | Proven by |
|---|---|---|---|
| 1 | Write — the language surface | closed | `conformance.py` 182/182, `doc_examples.py`, `stdlib_compiles.py` |
| 2 | Check — E001–E009, the cross-tier contract | closed | `typecheck_diff.py`, 84 files identical to the oracle |
| 3 | Repair — diagnostics to a patch | **partly** | `self_repair.py` 48/48 — rules backend only; the LLM backend has never run |
| 4 | Format — one canonical form | closed | `strata fmt --check` in CI, `fmt.py` |
| 5 | Build — C, self-hosted, reproducible | closed | four differentials byte-identical, `fixpoint.py` |
| 6 | Test — an application can be tested | closed | `strata test` over a project; both apps have their own |
| 7 | Run — it does the job | closed | `journey_orders.py` 25/25, `journey_ledger.py` 19/19 |
| 8 | Survive — more than one person | closed | `journey_survive.py` 18/18, with measured numbers |
| 9 | Deploy — an image that runs | **partly — here** | scratch image built and driven; the Debian Dockerfile is CI-only |
| 10 | Operate — running it for real | not started | only line-buffered logs exist |

## Closing a stage

When a stage closes, three things change together, or it has not closed:

1. the suite that proves it runs in `.github/workflows/build-check.yml`;
2. the row above says so, with the suite named;
3. Prabath is told — he asked to hear about every stage closed.

## What stands between stage 9 and stage 10

1. CSRF token, rate limit, login lockout, connection limit.
2. The real image built somewhere other than CI.
3. Stop reloading every table on every request.
4. `delete` in the language — nothing prunes an expired session.
5. The LLM repair backend, run once for real.
