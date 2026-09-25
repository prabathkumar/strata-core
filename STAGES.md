# The ten stages, and which are closed

The end-to-end pipeline a Strata program passes through, from someone typing a
line to a service running in production. This file is the record; the same map
is published as the "Strata End to End" artifact.

**A stage is closed when a suite that runs on every commit proves it, and that
suite exits non-zero when it does not** — and *green must mean the same thing
locally and on the runner*.

It did not, for ten consecutive runs. The parser differential had been failing
in CI since run #94, the commit that introduced `save`/`load`, and every stage
below was closed on local evidence while the gate meant to prove them was red.
The development machine has gcc 11 and no clang; the runner has clang; an
integer assigned to a pointer is a warning on one and an error on the other.
The C flags now carry `-Werror=int-conversion`, `-Werror=incompatible-pointer-types`
and `-Werror=return-type` so both reject it, and the suites are run in an
Ubuntu 24.04 container with clang as well as here.

**CI is green as of run #105 on `e7db33d`** — 32 steps, the first green run
since #93 on 13 September. Every stage below is now closed against a gate that
is actually passing, which is what the rule at the top of this file was for.

Getting there took three passes and each one found something the one before
could not: the parser differential (an int assigned to a pointer, a warning on
gcc 11 and an error on clang), then the change journey's deploy step (the image
was built from source whose port had been rewritten for the test, and had never
run anywhere with Docker installed). Both were found by an environment that was
not this machine. Not when the code exists, not when it
worked once by hand. Anything that has never been run is marked as not run,
never counted as closed.

| # | Stage | State | Proven by |
|---|---|---|---|
| 1 | Write — the language surface | closed | `conformance.py` 182/182, `doc_examples.py`, `stdlib_compiles.py` |
| 2 | Check — E001–E009, the cross-tier contract | closed | `typecheck_diff.py`, 101 files identical to the oracle; `first_hour.py` holds `strata check` to what `strata build` accepts |
| 3 | Repair — diagnostics to a patch | closed | `self_repair.py` — 48 checks gated in CI on the deterministic backend, plus 4 on the Claude backend where the CLI is usable |
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

### Stage 3, closed 14 September 2026

The model-backed repair backend has now been run, which it never had been.
`ai_self_repair.py --backend claude` drives `claude -p`, the non-interactive
mode of the CLI a developer already has signed in, so it needs **no API key** —
a demo that needs a secret provisioned is a demo that does not get run.

What it repaired is the part worth stating. The deterministic backend fixes
what the hint spells out and declines the rest. Given E008 — the auth bypass,
`Session <- [token == token]`, which matches every row so any token
authenticates — it produced no change and stopped, correctly. The Claude
backend renamed the parameter and its use, the program built, and a forged
token stopped authenticating.

It is gated in CI only for the deterministic backend, because CI has no Claude
credentials; the four Claude checks skip there and run where the CLI works.
The skip is reported as a skip, never as a pass.

Running it found a hole in the backend itself: a CLI that is installed but not
signed in prints a sentence and exits 0, and the loop wrote that sentence over
the file and called it a repair. An answer that is not a program is a failed
call now.

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
source, so it cannot tell a forgetful operator from an attacker. (Metrics and
a failure log were added afterwards; the note stands as what was true when
the stage closed.)

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

## The claims audit, 15 September 2026

Every document, config and stub in the repository was checked against something
that runs, and what could not be backed was removed: a lockfile declaring
dependencies from a registry that never existed (with a fake package manager
spliced into it), a submodule with no `.gitmodules`, unapplied infrastructure,
twelve tools that printed success without working, and four manuals describing
an LTS programme for a language a fortnight old. `LANGUAGE_SPECIFICATION.md`
was rewritten against the grammar the compiler has. The `No Unbacked Claims` CI
step fails if any of it returns.

### The compiler driver, closed 19 September 2026

Strata builds Strata programs without Python. The driver parses, type checks,
generates C, picks a compiler, assembles the flags, runs the build, and reports
diagnostics as data. Four differential tests hold it to the bootstrap: the
linker command (64 files agree), the C compiler invocation across native, wasm
and test builds (195 agree), the finished binary byte for byte (9 programs),
and the `--json` payload field by field (21 cases).

What is left in `bootstrap/` is a Python lexer, parser and code generator kept
as an oracle to compare against.

## All ten are closed. What is still not true

1. A load that meets a damaged row refuses the whole file rather than reading
   part of it: the table is left empty and the reason is on stderr. There are
   still no exceptions, so a caller that ignores the failure carries on with
   no rows — but it can no longer pretend it succeeded. The error is recorded,
   `had_error()` and `clear_error()` handle it, and a program that reaches its
   exit with one unchecked prints what it was and exits 65. What this does not
   do is stop the run at the point of failure, or let a function report a
   failure to its caller: the error is one global flag, so two failures before
   a check leave only the second message, and library code cannot raise
   anything.
2. A table is held in the process that loaded it, and reloaded only when the
   file on disk changes. That is right for one service on one machine and
   wrong the moment a second machine writes the same file over a share where
   the clock or the metadata lags.
3. The repair loop repairs a project now, and did not until the tutorial was
   written and run. A file inside a project was handed to the compiler from
   the Strata repository rather than from the project, so neither the file nor
   its `import schema from app` resolved: the loop saw a compiler failure
   instead of the E004 that was there and answered "backend produced no
   change". The generated README had been telling every newcomer to run
   exactly that command. `test_suite/first_hour.py` now breaks a generated
   project and requires the loop to fix it.
4. `strata check --json` goes through the bootstrap, not the self-hosted
   emitter. `compiler/json_cli.sta` exists and the two agree on the test
   corpus, but in a project created by `strata new` it reports `std` as
   unresolved while `strata build` compiles the same file without complaint.
   A checker that disagrees with the compiler is worse than no checker, so
   the flag uses the answer that is right until json_cli resolves imports the
   way the compiler does.
5. The Claude repair backend is not gated in CI, because CI has no Claude
   credentials. It runs where the CLI does.
6. `scan` reads, `append` writes and `rewrite` changes a FILE-backed table one
   row at a time, so reading, producing and updating a table are all possible
   without holding it. Postgres has none of them: a Postgres-backed table is
   still loaded whole into memory, so the working set has to fit, and there is
   no cursor and no connection pool beyond one handle per process. A rewrite
   also rewrites the WHOLE file to change one row, which is right for a batch
   pass and wrong for a single update in a service.
7. Passwords and sessions now compile on macOS, and did not until the macOS
   CI job was added and failed on its first run. `std/auth.sta` declared
   crypt(3) as `foreign "crypt.h" link "crypt"`; on a Mac that header does not
   exist and there is no libcrypt. It is now <unistd.h> on both, with
   -D_GNU_SOURCE for glibc and no -lcrypt on Darwin — 210/210 on a Mac where
   two cases used to fail. What that episode leaves behind is the real entry:
   anything reached through a `foreign` block is only known to work on a
   platform something has actually built it on, and the only two are Linux and
   macOS.
8. A lockout is counted against the pair of account and source, which stops
   both the password guess and the trick of locking an operator out on
   purpose. What it does not stop is one source spreading attempts across many
   usernames — that needs a rate limit, which this is not.
9. Nothing has run on a handset. `apps/orders_mobile/ios/` builds against a
   real bridge — `src/host.sta` compiles to a linkable object and Swift calls
   its five C functions with no glue layer — but it has only ever been pointed
   at the Simulator. `apps/orders_mobile/android/` is still reviewed design
   rather than tested code: the machine here has no NDK, so the JNI wrappers
   around those same five functions have never been compiled.
10. Memory is given back in one piece or not at all. Temporaries come from an
   arena and `scratch_reset()` throws the whole arena away; tables keep their
   own copies and survive it. Measured: four million temporaries with resets
   peak at 1.4 MB, one million without at 93 MB. What this is NOT is
   individual deallocation — there is still no way to free one value, and a
   single request that builds something enormous holds it until the next
   reset. Rows removed by `delete` ARE reclaimed, at the same moment: they are
   retired rather than freed on the spot, and a reset frees them once the
   arena that any query result lives in has gone. 400,000 insert/delete cycles
   held 13.7 MB before and 1.15 MB after, and 800,000 no longer cost more than
   400,000. The phone bridge resets at the top of each frame: 60,000 frames of
   a twenty-row screen hold 1.28 MB, where 20,000 frames without the reset
   reached 326 MB. The reset is placed by hand, so calling it while a temporary — or
   a row — is still in use is a use-after-free that nothing catches. A phone shell and a
   server both now have somewhere honest to put that call; neither has been
   run for a week to prove it.
11. There is no registry and no version solving. A dependency is a path or a
   git revision, named exactly; `strata deps` fetches the graph, including
   dependencies of dependencies, and refuses when two packages disagree about
   one name rather than choosing for you. Nothing publishes, nothing searches,
   and "^1.2" means nothing here.
12. A layout has no event model. A button names a route it posts to; nothing
   in a rendered page calls a Strata function by itself, because Strata emits
   no JavaScript. Passing a handler's name to `action` is now E001 rather
   than, as before, a clean type check followed by a C compiler error.
13. `build`, `check`, `fmt` and `deps` are self-hosted, with
   `STRATA_BOOTSTRAP=1` as the way back for a build. `ast`, `lex`, `test` and
   `repair` still go through Python. The build is self-hosted; the toolchain around it is not.

### Corrected rather than deleted

This list said "the Kubernetes manifest under `deploy/` has never been applied
to anything." There is no Kubernetes manifest. It was removed by the claims
audit above, and the `No Unbacked Claims` CI step fails if it comes back — so
the honest-gaps list had itself gone stale, describing a file that is not
there. Deployment is a Docker image, built and run by `journey_change`;
orchestration is not attempted and is not claimed.

It also said "sessions are pruned only when one is created, which is not a
schedule" and "metrics start at zero when the service restarts". The first is
fixed: the service sweeps on a clock. The second was a misunderstanding on the
author's part — a counter is *expected* to reset, which is why monitoring
systems read counters as rates. What was missing was the type information that
tells a scraper so, and a process start time to make a restart readable rather
than inferred. Both are published now.
