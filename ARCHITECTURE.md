# What a Strata application is

Until 2026-09-14 there was no answer to this. The compiler was in good shape
and there was no system: `Strata.toml` was ignored, `strata build` took a
single file, the one thing shaped like a service was a six-line hello world
that did not compile, and `deploy/` held Terraform that deployed nothing.

This describes the shape an application actually has, and is kept honest by
`apps/orders`, which runs.

---

## Layout

```
apps/orders/
  Strata.toml         package name, entry point, output path
  src/
    schema.sta        database blocks — the data tier
    views.sta         layout blocks  — the UI tier
    main.sta          routes, business rules, entry point
  data/
    orders.tsv        persisted rows, with a schema header
  build/
    orders            one binary
```

`strata build` with no arguments builds the project the current directory
belongs to, walking up to find `Strata.toml` and reading `main` and `output`
from it. `strata run` builds and runs it; `strata new` scaffolds one that
builds unedited. A single file still compiles with `strata build <file.sta>`,
for a script or an example.

`import schema from app;` resolves to `src/schema.sta`. `app` is a module
source alongside `std` and `compiler`, which is what lets an application be
more than one file without putting its modules in the standard library.

## The tiers, and what holds them together

| Tier | Written as | Checked against |
|---|---|---|
| Data | `database Order { ... }` | — it is the declaration everything else is checked against |
| Query | `Order <- [status == "OPEN"]` | the schema: a wrong column is E004 |
| Aggregate | `sum(open_orders.amount)` | the schema, through the projection |
| UI | `layout Dashboard() { ... }` | the schema: a field rendered from a row is checked |
| Transport | `http_listen`, `http_path`, `http_body`, `http_form_value`, `http_redirect` | ordinary Strata, in `std/http.sta` |
| Input | `form { field "customer"; }` in a layout | the handler that reads it — and the schema, when the row is inserted |

Rename `amount` in `schema.sta` and the build fails at the insert, at the
aggregate and at the page — before anything runs, and each diagnostic names
the file it is in:

```
[E004] Column 'amount' does not exist in 'Order' (line 17, col 5)
[E004] Field 'amount' not in 'Order' (src/views.sta:line 21, col 30)
```

The project's own modules are checked; `std` and `compiler` are not. They are
dependencies with their own suite, and re-checking them on every application
build would put their diagnostics in every user's output. That is the argument for
Strata being a language rather than a library, and it is now demonstrable on a
service rather than on an example.

## What makes the web tier work

A layout compiles to a function that writes to a `FILE*`. `render Dashboard`
is an expression yielding the document as a `str`, via `open_memstream`, so
the same generated function serves both `render L to "page.html"` and an HTTP
response body. Without that, a layout could only be written to disk and no
layout could ever answer a request.

`std/http.sta` is written in Strata: `foreign` blocks include the socket
headers and `native` blocks make the calls. It needed no compiler change,
which is the point — the web tier is library code, not a privileged part of
the language.

## What this is not, yet

- **The HTTP server is one connection at a time.** No TLS, no keep-alive, no
  concurrency, no streaming, no timeouts, and a request body larger than one
  `read()` is truncated. A second client waits. Not for the public internet.
- **No client-side interactivity.** Pages are server-rendered HTML. The
  WebAssembly target cannot reach the DOM without a JavaScript shim, as with
  every WASM framework.
- **No sessions, no auth.** Forms and POST work; nothing identifies who posted.
- **No CSRF protection.** A form post is accepted from anywhere.
- **No request timeout.** A client that announces a Content-Length and then sends less will hold the connection, and there is only one.
- **`_to_delete/` under `apps/orders`** holds two scratch files the mount
  would not let me remove. Delete them when convenient.
