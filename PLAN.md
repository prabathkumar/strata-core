# Plan of record — a service that runs and serves

Approach changed on 2026-09-14: structure and integration first, depth only
where the running service demands it. `ARCHITECTURE.md` says what an
application is; this says what is left and in what order.

Each step's "done" is something that can be run, not something that can be
described. Durations are working days at the pace of 2026-09-14, which
delivered five language items plus the walking skeleton in one day — so treat
them as estimates with the usual asymmetry: they go long, not short.

| # | Activity | Done means | Days |
|---|---|---|---|
| 0 | **Finish the self-hosted port** *(in flight)* | `strata-self` compiles `apps/orders`; the differentials cover `render` as an expression, `app` imports and imported declarations | 0.5 |
| 1 | **`strata build` reads `Strata.toml`** | `cd apps/orders && strata build` produces `build/orders` with no paths on the command line | 0.5 |
| 2 | **Type-check imported modules** | a column break inside `views.sta` is reported by Strata with a line, not by the C compiler | 1.0 |
| 3 | **Forms and POST** | an order is created from the page: request body parsed, handler runs, redirect, row persisted | 1.5 |
| 4 | **Routing, static assets, error pages** | a route table rather than an if-chain; CSS served; real 404 and 500 pages | 1.0 |
| 5 | **Sessions and login** | a cookie, a protected route, a logout. Minimal and honest — no password reset, no OAuth | 2.0 |
| 6 | **Concurrency** | a slow client cannot block every other client. Process or thread per connection; measured, not assumed | 1.5 |
| 7 | **AI repair loop against the service** | rename a column, the loop repairs across `schema.sta`, `views.sta` and `main.sta`, the service rebuilds and serves | 1.5 |
| 8 | **The demo, recorded and reproducible** | a script that runs from a clean clone: build, serve, break the column, fail, repair, serve again | 1.0 |
| 9 | **Deployment that deploys** | the Dockerfile builds and runs the service; the Terraform and k8s YAML that deploy nothing are deleted | 1.0 |
| 10 | **Hardening pass** | whatever 1–9 exposed, plus the first measured performance numbers | 2.0 |
|   | **Total** | | **13.5** |

## Not in this plan, and why

| Deferred | Reason |
|---|---|
| Fibers / coroutines | A blocking request loop with a process per connection is enough for step 6. Fibers are months and mostly a runtime-thread-safety project — see `NEXT_STEPS.md` Part 4. |
| TLS | Terminate it at a proxy. Writing a TLS stack is not this project's argument. |
| Client-side interactivity | WebAssembly cannot reach the DOM without a JavaScript shim, as with every WASM framework. Server-rendered pages carry the demo. |
| Migration tooling (Java/C# → Strata) | Direction, not a project, until the service story stands up. |

## The rule this plan is under

Every step lands with a check that fails when the step stops working, and the
check exercises the path the way it actually runs. That is what the last week
kept proving: a report that emitted only its title still exited 0, `len()`
returned garbage while a test called it and ignored the answer, and seven
standard library modules "passed" a suite that only checked they parsed.
