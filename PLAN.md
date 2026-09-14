# Plan of record — end-to-end journeys

**Where the project is: [STAGES.md](STAGES.md)** — the ten stages from source to
production, which are closed, and what proves each one. A journey below closes
one or more of those stages.

Reframed on 2026-09-14, at Prabath's call. The earlier plan was a list of
features — routing, then sessions, then concurrency — and a feature list
produces slices that each work alone and have never been walked through
together. A journey is what a real person does from start to finish, and it is
what finds the gaps: one hour of building the walking skeleton surfaced
`render`-to-string, `app` imports and imported declarations, none of which were
on the feature list.

Each journey ends with a test that walks the **whole** journey, not its parts.

---

## Journey A — Run the orders desk ✅ **closed 2026-09-14**

*An operations manager signs in, works, and signs out.*

Sign in → see open orders → create one → edit one → close one → filter the
list → sign out, and be refused when signed out.

`test_suite/journey_orders.py` walks all 25 steps on every commit.

| Built | Note |
|---|---|
| Password hashing | SHA-512 `crypt(3)` with a random salt, over FFI |
| Sessions and cookies | persisted, so a restart does not sign everyone out |
| Routing with an auth gate | GET redirects to sign-in, a write is 403 |
| Create and close through forms | validated; close mutates the row and saves |
| Views that take their inputs | `layout Dashboard(str region, str notice)` |
| Computed HTML attributes | a row's own id reaches the form that acts on it |

Not built, and now recorded rather than assumed: **delete does not exist in
the language**, so signing out expires a session rather than removing it and
nothing prunes the table. Filtering by region is passed to the view but not yet
applied to the query.

## Journey B — Change the system ✅ **closed 2026-09-14**

*A developer clones the repo and changes the schema.*

Clone → `strata run` → add a column → the build fails at every insert →
the repair loop fixes them → `strata test` passes → existing data still
loads → deploy.

`test_suite/journey_change.py` walks all 19 steps, against an export of HEAD
rather than the working tree.

| Built | Note |
|---|---|
| E009, incomplete insert | An insert must name every column. Without it, a new column was written as a zero in every row, silently — so "add a column" broke nothing and corrupted everything |
| The repair loop over a project | It follows the `file` field of each diagnostic, so it repairs whichever of a project's files the error is in |
| `strata test` over a project | Every `.sta` under it, compiled from the project root, so a test can import `app` modules and open the data files by the paths the service uses |
| `apps/orders/src/rules.sta` | The business rules, apart from HTTP, so a rule can be tested without a socket |
| `apps/orders/tests/rules_test.sta` | 5 blocks, 14 assertions — the application's first tests |
| A Dockerfile that builds and runs | Two stages: the toolchain, then the binary, its data and libcrypt |

Corrected from the plan: the build fails in **two** files, not three — the two
that insert rows. The view was not affected, because showing a new column is a
choice, not a contract. The plan claimed three before anyone had tried it.

What the journey found, none of which a unit test would have: adding a column
was an error nowhere; the repair loop had a single-file assumption in the loop
rather than the compiler; `strata test` could not see an application at all;
`import x from app` could not be reached from a `tests/` directory; and the
standard library's own telemetry module had been writing `trace_id` as 0 on
every row since it was written.

The deploy step is honest about where it runs: there is no Docker on the
development machine, so the journey skips it there and CI builds the image and
asks the container for a page on every push.

## Journey C — Survive contact ✅ **closed 2026-09-14**

*The service meets more than one person.*

Two clients at once → a slow client → a client that walks away → a malformed
request → ten writes arriving together → a restart with live data → 2000 rows.

`test_suite/journey_survive.py` walks all 18 steps and prints the numbers.

| Built | Note |
|---|---|
| A process per connection | `http_fork` after `http_accept`; the child serves and `_exit`s |
| A receive timeout | 5s, so a client that under-delivers its `Content-Length` is answered 408 rather than holding the connection |
| SIGPIPE ignored | A client that walked away mid-response used to terminate the service |
| Children reaped | `SIGCHLD` to `SIG_IGN`, so nothing accumulates as a zombie |
| `lock_shared` / `lock_exclusive` | The children share nothing but the filesystem. A GET takes the shared lock and is served in parallel; anything that can write takes the exclusive one |
| An incomplete request is empty | It used to come back as whatever bytes had arrived, which looked like a real request with a strange path |

### Measured, on a 4-core development machine

| | |
|---|---|
| dashboard, 20 rows | p50 2.2 ms, p95 2.6 ms |
| dashboard, 2000 rows | 15 ms, 746 KB |
| sequential throughput | ~445 req/s |
| concurrent throughput, 8 clients | ~380 req/s, p95 32 ms |
| slow client released after | 5.0 s (the configured timeout) |

**Concurrent throughput comes out below sequential, and that is the finding.**
It is not the lock — reads take a shared one. Every request forks a process
and reloads all three tables from disk. What the process per connection buys
is that one slow or hostile client cannot hold the others; throughput is the
next piece of work, and the figure above is the honest starting point.

The lost-update test is the one worth keeping: run with `lock_exclusive`
removed, ten concurrent creates against a thousand-row table leave **856 rows,
hundreds of them all-zero** — two processes writing the same file. It was
written first against an empty table, where it passed with the lock removed
and proved nothing.

## Then — what A, B and C left behind

All three journeys are closed. The numbers are measured and published above.
What they exposed, and nobody has done yet:

| Open | Why it matters |
|---|---|
| `delete` does not exist in the language | Sessions expire rather than being removed; nothing prunes the table, and it grows forever |
| Every request reloads all three tables | It is what caps throughput, and it is the next performance work |
| No CSRF token, no rate limit, no lockout | A signed-in operator's browser can be made to post; an attacker can guess passwords as fast as the service answers |
| No connection limit | Nothing stops a client opening sockets faster than children can serve them |
| The region filter reaches the view but not the query | Journey A recorded it; it is still true |
| The two-stage Dockerfile is still CI-only | No container registry is reachable from here, so `debian:bookworm-slim` cannot be pulled. `deploy/build_scratch_image.sh` builds and runs a `FROM scratch` image instead — 5.35 MB, serves `/login`, signs in, creates an order. What remains unverified outside CI is the base image and the apt layer |

## The second application — `apps/ledger` ✅ **2026-09-14**

Everything before this was one program: a signed-in operator, forms, pages,
HTML. A language shaped by its only application is not general-purpose, and
there was no way to tell which of the two Strata was. `apps/ledger` is the
other shape — a command-line tool that also answers JSON, with a `report`
block, an import that reads a file, and no HTML anywhere.

It works, and `test_suite/journey_ledger.py` walks 19 steps of it. What it
cost, in order of severity:

| Found | Fix |
|---|---|
| The command line was reachable only by writing C. Every tool here, the compiler included, opens `main` with a `native` block declaring `extern char** __strata_argv` | `std/cli.sta` — `arg`, `arg_count`, `subcommand`, `has_flag`, `flag_value`, `positional` |
| **`for Row in rows` in a function body generated nothing at all.** It parsed only inside a layout, the generator had no rule for it elsewhere, and an unhandled statement was emitted as silence — the loop compiled, linked, ran and did nothing | Parsed in statement position, generated in both back ends; **an unhandled statement is now an error rather than nothing** |
| No way to write JSON | `std/json.sta` — escaping what JSON requires, which is not what C requires |
| `char_from_code` lived in `std/http.sta`, so writing JSON meant importing an HTTP server for a string helper | Moved to `std/str.sta` |
| `render X to "path"` takes a literal, not an expression, so a program cannot choose at run time where a report goes | Recorded, not worked around: `ledger report` does not take a filename. An earlier version took one, ignored it, and printed the name it had been given |

E008 — the rule the orders desk's auth bypass produced — caught the same
mistake twice in new code within a minute of it being written. The
cross-tier contract held: the ledger's schema, queries, aggregates, report
and JSON all check against one `database` declaration.

Still open from this: `strata check <file>` does not resolve imports the way
`strata build` does, so it reports undeclared databases for any file that
imports its schema. And a diagnostic from an imported module is reported
twice.

## Deferred, and why

| Deferred | Reason |
|---|---|
| Fibers / coroutines | Journey C needs concurrency, not fibers. A process per connection is enough and is days rather than months. |
| TLS | Terminate at a proxy. A TLS stack is not this project's argument. |
| Client-side interactivity | WebAssembly cannot reach the DOM without a JavaScript shim, as with every WASM framework. |
| Migration tooling (Java/C# → Strata) | Not until a service built in Strata survives Journey C. |

## The rule

Every journey lands with a check that fails when the journey stops working,
and it exercises the path the way a person does. That is what the last two days
kept proving: a report that emitted only its title still exited 0, `len()`
returned garbage while a test called it and ignored the answer, and the server
only ever worked with curl because curl happens to send a request in one packet.
