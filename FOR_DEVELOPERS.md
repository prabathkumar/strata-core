# Before you build something in Strata

`STAGES.md` is the working list of what is and is not done, kept current and
written for whoever is building the compiler. This is the same truth aimed at
you: what you can build today, what will bite you, and what is simply not
here.

Read the sharp edges section even if you skip the rest. Everything in it can
cost you an afternoon or worse, and none of it is discoverable by reading the
happy path.

---

## What you can build today

| | |
|---|---|
| **Batch and command-line programs** | Read, transform, write, exit. The best-supported thing here, and the least likely to surprise you. |
| **Services** | An HTTP server, sessions, password hashing, a forked worker per connection. Single-machine, single-writer. |
| **Server-rendered web** | `layout` blocks compile to HTML. Buttons post to routes; nothing in a page calls back into Strata, because Strata emits no JavaScript. |
| **Phone screens** | Five C functions a shell calls. Swift and Kotlin shells are in `apps/orders_mobile/`. Compiles and runs against the contract; **never run on a physical handset**. |

Data lives in tab-separated files or PostgreSQL. A table loads whole into
memory unless you stream it with `scan`, `append` and `rewrite`, which work at
constant memory on files — Postgres has none of them.

---

## The sharp edges

These are the ones that hurt rather than disappoint.

### `scratch_reset()` in the wrong place is a use-after-free

Memory comes from an arena. `scratch_reset()` throws the whole arena away, and
nothing checks whether you were still using something in it. There is no
error, no crash you can rely on, and no test that catches it — you get wrong
data or a segfault somewhere unrelated.

The rule: **after a reset, only what is in a table still exists.** Tables keep
their own copies. Everything else — strings you built, query results, string
builders — is gone.

```text
list[Order] open = Order <- [status == "OPEN"];
scratch_reset();                  // `open` is now dangling memory
print(str(count(open)));          // wrong answer or a crash
```

Put the reset at a boundary where nothing is in hand: the top of a request,
the top of a frame. A batch program that runs and exits never needs it.

### A `foreign` block only works where somebody has built it

A `foreign` block names a C header and a library. Both are platform-specific,
and nothing warns you. `std/auth.sta` declared `crypt.h` and `-lcrypt`, which
do not exist on macOS — so password hashing silently did not compile there for
as long as CI ran only Linux. It is fixed, and the lesson is not.

If you add a `foreign` block, build it on every platform your team uses before
you rely on it.

### Concurrency is processes, not threads

Requests do run in parallel. The HTTP server forks a process per connection,
so a four-core machine serves four requests at once, each child inherits the
parent's loaded tables copy-on-write, and counters live in memory mapped
before the first fork so every child adds to the same numbers.

What there is none of is **shared mutable memory**. No threads, no async, no
parallelism inside one request. Which means:

- A write takes a file lock (`lock_exclusive`) around the read-change-save,
  so writes serialise across the whole service.
- A child's changes to a table are its own. Nothing another child does is
  visible until it reaches the file.
- A slow request occupies a process for its whole life, and there are only
  `MAX_CONNECTIONS` of them.
- There is no in-memory cache shared between requests, and no way to build one
  short of a file or mmap.

That is a real model with real limits rather than an absence, and it is the
same one nginx and Apache prefork have used for twenty years. If your problem
is read-heavy and its writes are modest, it will do. If you need many threads
over one shared heap, this is the wrong tool today and the reason is in the
memory model rather than the scheduler: `scratch_reset()` is placed by hand
and tables are global, so threads would need a per-thread arena and a lock on
every table before they were safe.

### One writer, one machine

A table is held in the process that loaded it and reloaded when the file
changes. That is right for one service on one machine and wrong the moment a
second machine writes the same file.

---

## What will annoy you

- **No package registry.** A dependency is a path or a git revision, named
  exactly. `strata deps` fetches the graph, including dependencies of
  dependencies, and refuses when two packages disagree about a name.
  `"^1.2"` means nothing here.
- **A query is a scan.** No index, no joins, no ordering, no `GROUP BY`.
  Aggregates read a list that already exists.
- **The standard library is small.** `std/` is what there is. There is no
  float-to-int cast and no int-to-float conversion, which you will notice the
  first afternoon you do arithmetic.
- **`build/` holds whatever ran last.** Build outputs are platform-specific
  and the compiler does not name them per platform, so a folder shared between
  two machines — a Mac and a Linux VM, a network home directory — hands the
  second one an object the first built. It shows up as "cannot execute binary
  file", or as Xcode saying "Unknown file type". `file build/whatever.o` says
  which it is; rebuilding fixes it.
- **A float saved to a file loses a trailing `.0`.** A column holding `225.0`
  is written as `225` while `62.5` keeps its point. It reloads as the same
  number and the file's header still says the column is a float, so nothing
  is lost — but anything downstream reading that column by eye or by regex
  will notice.
- **No client-side interactivity**, because no JavaScript is emitted.
- **`ast`, `lex`, `test` and `repair` still go through Python.** `build`,
  `check`, `fmt` and `deps` are self-hosted.

---

## Things that will feel strange, and are deliberate

**An insert must name every column.** Add a column to a schema and every
insert fails the build until you say what it holds. Without that, adding a
column writes an empty value into every row it creates — nothing breaks, and
everything is quietly wrong.

**There are no exceptions.** A failed load leaves the table empty and records
an error. Check it, act, clear it:

```text
load Ledger from "ledger.tsv";
if (had_error() == 1) {
    print(last_error());
    return 1;
}
```

A program that reaches its exit with an error nobody checked prints which one
and exits 65. Your own code reports failure with `fail("...")`. Up to sixteen
errors are kept, oldest first, through `error_at()`.

**The compiler refuses rather than guessing.** A stored file whose column
changed type is refused, not coerced. Two packages disagreeing about a name is
an error, not a silent pick. You will meet this as friction before you meet it
as a bug you did not have.

---

## If something is wrong

A test file reaches your project's code by importing the module, the same way
any other file does — `import rules from app;`. Without it the build fails
with E002 naming the function it could not find, which means the file is not
in scope rather than that the function is missing.

```bash
strata check file.sta --json    # the diagnostic, machine-readable
strata repair file.sta          # rules-based fix, no model involved
strata fmt src/*.sta --check    # canonical formatting, as CI enforces it
strata test                     # run the verify blocks
```

Every diagnostic has a code. `ERROR_TAXONOMY.json` says what each one means
and how the language's authors say to fix it — that is what the repair loop
reads, and you can read it too.

---

## Where the truth is kept

- **[STAGES.md](STAGES.md)** — the full gaps list, kept current. If something
  here disagrees with it, it is right and this is stale.
- **[README.md](README.md)** — what it is and how it compares.
- **[TUTORIAL.md](TUTORIAL.md)** — the first hour, hands-on.
- **[LANGUAGE_SPECIFICATION.md](LANGUAGE_SPECIFICATION.md)** — the language
  itself.

Every code example in the README and the specification is compiled on every
commit, so an example that stopped working fails the build rather than sitting
there looking plausible.
