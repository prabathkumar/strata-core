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

## Journey B — Change the system (3 days)

*A developer clones the repo and changes the schema.*

Clone → `strata run` → add a column → the build fails in three files → the AI
repair loop fixes them → `strata test` passes → existing data still loads →
deploy with Docker.

| Needs | State before |
|---|---|
| `strata test` over a project | runs over a directory of files |
| The repair loop against a multi-file project | patches one file |
| Data surviving the schema change | works — the header carries the schema |
| A Dockerfile that builds and runs the service | builds a toolchain, runs nothing |
| The journey recorded, reproducible from a clean clone | — |

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
