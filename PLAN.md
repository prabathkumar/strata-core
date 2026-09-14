# Plan of record — end-to-end journeys

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

## Journey C — Survive contact (2.5 days)

*The service meets more than one person.*

Two clients at once → a slow client → a malformed request → a restart with
live data → a list long enough to hurt.

| Needs | State before |
|---|---|
| Concurrency | one connection at a time; the second waits |
| A request timeout | a client that under-delivers its Content-Length hangs the server |
| Errors that do not take the process down | unchecked |
| Measured numbers | none published, correctly — none measured |

## Then

Hardening (2 days) for whatever A–C expose, and the first measured
performance figures.

**Total: 11.5 days.**

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
