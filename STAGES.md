# The ten stages, and which are closed

The end-to-end pipeline a Strata program passes through, from someone typing a
line to a service running in production. This file is the record; the same map
is published as the "Strata End to End" artifact.

**A stage is closed when a suite that runs on every commit proves it, and that
suite exits non-zero when it does not** — and green must mean the same thing
locally and on the runner. It did not once: the development machine has gcc 11
and no clang, the runner has clang, and an integer assigned to a pointer is a
warning on one and an error on the other. The C flags now carry
`-Werror=int-conversion` and its neighbours so both reject it. Not when the code exists, not when it
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
| 7 | Run — it does the job | closed | `journey_orders.py` 26/26, `journey_ledger.py` 19/19 |
| 8 | Survive — more than one person | closed | `journey_survive.py` 18/18, with measured numbers |
| 9 | Deploy — an image that runs | closed | the real two-stage Dockerfile built outside CI: apt layer, compile, `strata test` inside the image, container serves as a non-root user |
| 10 | Operate — running it for real | closed | `journey_operate.py` 21/21 — request log, CSRF, lockout, connection cap |

## Closing a stage

When a stage closes, three things change together, or it has not closed:

1. the suite that proves it runs in `.github/workflows/build-check.yml`;
2. the row above says so, with the suite named;
3. Prabath is told — he asked to hear about every stage closed.

### Stage 10, closed 14 September 2026

A request log on stdout, one line each: `GET /login 200 3ms`. CSRF tokens on
every form, checked on every write. Five failed sign-ins lock an account for
five minutes, and a locked account answers the same way whatever was typed, so
the lockout does not tell an attacker which usernames are real. A cap of 64
connections, with the 65th answered 503 rather than forked.

What it found: the service could be made to post by any page on the web; a
password could be guessed as fast as the service could answer, about 450 a
second; `SIGCHLD` was handed to `SIG_IGN`, so the service could not count its
own children and had no way to refuse the next connection. Counting them
brought zombies back — the parent only reaped when the next connection
arrived, which is never while idle — so the listening socket now has a
one-second timeout and the loop reaps at the top.

Two smaller things fell out. Every response helper returns its status code
instead of 1, because a log line needs the status the handler chose. And
`journey_orders` had to start reading the CSRF token off the page, the way a
browser does — a test that could still post without one would have meant the
protection was not real.

Not done at this stage: no metrics, no log for anything but requests, nothing
prunes an expired session, and the lockout is per account rather than per
source, so it cannot tell a forgetful operator from an attacker.

### Stage 9, closed 14 September 2026

The image is `strata-orders:real`, 216 MB, Ubuntu 24.04. The build compiles
the service and runs `strata test` inside the image it ships, so an image that
builds is an image whose tests passed. It runs as uid 10001, logs its startup
line, serves the sign-in page, signs in, creates an order, and refuses a
signed-out request with a redirect.

Two things are worth stating rather than leaving implied. The base moved from
`debian:bookworm-slim` to `ubuntu:24.04` because no registry is reachable from
here and an Ubuntu root filesystem can be bootstrapped from the archive
(`deploy/bootstrap_base_image.sh`) and imported under that tag — a Dockerfile
only CI can build is a Dockerfile nobody has read. And that bootstrapped base
is the same release from the same archive, not Canonical's published image bit
for bit, so CI remains the authority on the published base; the CI gate has
not yet run on a pushed commit.

The build failed the first time, on something real: `stage0.py -o build/orders`
did not create `build/`, and the linker's error for a missing directory is
"cannot open output file", which reads like a permissions problem and is not
one. `strata build` had a `mkdir -p` of its own, so the compiler was only ever
missing it when called directly — which is exactly what a Dockerfile does.

`deploy/build_scratch_image.sh` remains for the other question: the smallest
thing that can serve. `FROM scratch`, the binary and three libraries, 5.35 MB.

## All ten are closed. What is still not true

1. `delete` does not exist in the language, so nothing prunes an expired
   session and the table grows forever.
2. Every request forks and reloads all three tables, which is why eight
   concurrent clients are slower than one.
3. The LLM repair backend has never been run — stage 3 is closed on the rules
   backend alone.
4. No metrics, and no log of anything but requests.
5. The lockout is per account, not per source: it stops a password guess and
   also lets someone lock an operator out on purpose.
6. The Kubernetes manifest under `deploy/` has never been applied to
   anything.
