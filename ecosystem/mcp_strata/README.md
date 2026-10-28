# The Strata MCP server, written in Strata

The same thing `ecosystem/mcp/` is, written in the language it is about.

`ecosystem/mcp/` is the reference, and it works. This is not a replacement
for it and not an improvement on it. It is the answer to a question that only
a program can answer: **can this language carry its own tooling?** An
ecosystem component written in Python is a quiet admission that it cannot, and
the only way to find out is to write the thing and see what hurts.

What hurts is in the report that came with this directory. The short version
is that the language has no map, no growable list, no module-level variable,
no `&&`, no regular expressions and no JSON reader — and that a JSON-RPC
server is mostly maps, growable lists and JSON. Every one of those became a
`database` table, a six-argument function with `""` as the terminator, or a
hand-written scanner. None of it was impossible. All of it was longer.

---

## What it needs

A Strata checkout. Nothing else — no Python at run time, no packages, no
`pip install`. The binary is a binary.

The compiler is still needed to *build* it, and `bin/strata ast`, which
`strata_schema` calls, still goes through Python inside the toolchain. That
is the toolchain's business, not this server's.

---

## Building and running it

```sh
cd ecosystem/mcp_strata
../../bin/strata build          # -> ecosystem/mcp_strata/build/mcp_strata
```

```sh
./build/mcp_strata                        # finds the checkout from its own path
./build/mcp_strata --root /path/to/strata
```

It speaks JSON-RPC 2.0 over newline-delimited JSON on stdin and stdout, so
running it in a terminal looks like it has hung. It has not; it is waiting
for a client. To see it work:

```sh
bash ecosystem/mcp_strata/test_server.sh     # 32 checks, end to end
cd ecosystem/mcp_strata && ../../bin/strata test .   # the verify blocks
```

The root is found in this order: `--root`, then `STRATA_ROOT`, then by walking
up from the binary's own path, then by walking up from the current directory.
A directory counts as a checkout only when it holds **both** `bin/strata` and
`ERROR_TAXONOMY.json` — `bin/strata` alone would match a half-copied tree, and
a tree with no taxonomy is one where a diagnostic is worth no more than its
text.

### Pointing Claude Code at it

```sh
claude mcp add strata-sta -- /absolute/path/to/strata/ecosystem/mcp_strata/build/mcp_strata --root /absolute/path/to/strata
```

### Pointing Claude Desktop at it

```json
{
  "mcpServers": {
    "strata-sta": {
      "command": "/absolute/path/to/strata/ecosystem/mcp_strata/build/mcp_strata",
      "args": ["--root", "/absolute/path/to/strata"]
    }
  }
}
```

Absolute paths in both. A client starts the server with an unpredictable
working directory, which is also why every path a caller sends is read against
the checkout rather than against the current directory.

---

## The tools

| Tool | What it answers |
|---|---|
| `strata_check(path)` | Does this type-check, and if not, exactly what is wrong? |
| `strata_taxonomy(code)` | What does this error code mean, and what should be done about it? |
| `strata_build(path, out, workspace)` | Does it compile, and where is the binary? |
| `strata_run(path, args, workspace)` | What does it print, and what does it exit with? |
| `strata_schema(project_dir)` | What tables are there, with what columns and types? |
| `strata_rename_impact(project_dir, table, column, new_name)` | What would this rename break, across every tier? |

The names, the arguments and the shape of every result are the Python
server's. They are meant to be interchangeable, and on the two tools where
that is checkable they are byte-for-byte the same answer:

```
$ strata_schema apps/payables        -> identical tables, columns and lines
$ strata_rename_impact Bill.amount   -> identical 12 impacts, identical tiers
```

### `strata_rename_impact`

The tool worth looking at first, because it answers the question this language
exists to answer: *if I rename this column, what breaks?* — before anything is
changed.

It copies the project to `/tmp`, changes one line — the column's declaration
in its `database` block — re-checks every file, and reports every place that
stopped compiling with the tier it belongs to. Renaming `Bill.amount` in
`apps/payables`:

```
tiers_broken: ["phone","program","report","rules","web"]
declaration:  apps/payables/src/schema.sta:30   (the one line that was changed)

  rules    apps/payables/src/importer.sta:167     E004 Column 'amount' does not exist in 'Bill'
  rules    apps/payables/src/importer.sta:167     E009 Insert into 'Bill' omits column 'gross'
  report   apps/payables/src/main.sta:31          E004 'amount' is not a column of 'Bill'
  program  apps/payables/src/main.sta:151         E004 Field 'amount' not in 'Bill'
  rules    apps/payables/src/rules.sta:112        E004 Column 'amount' does not exist in 'Bill'
  rules    apps/payables/src/rules.sta:112        E002 Return mismatch: expected 'int', got 'float'
  rules    apps/payables/src/rules.sta:124        E004 Field 'amount' not in 'Bill'
  web      apps/payables/src/views.sta:68         E004 Field 'amount' not in 'Bill'
  web      apps/payables/src/views.sta:78         E004 'amount' is not a column of 'Bill'
  web      apps/payables/src/views.sta:85         E004 Field 'amount' not in 'Bill'
  web      apps/payables/src/views.sta:87         E004 Field 'amount' not in 'Bill'
  phone    apps/payables_mobile/src/screen.sta:84 E004 Field 'amount' not in 'Bill'
```

The phone is a **separate project** that takes the schema as a dependency, so
a tool that only looked inside the directory it was given would report five
tiers out of six and look right doing it. Sibling projects that declare a path
dependency on this one are copied and checked too.

The `tier` on each impact is a judgement made from the shape of the file, not
something the compiler said, so each one carries `tier_evidence` saying what
the judgement was made from. Argue with it when it is wrong.

### `strata_check`

Every diagnostic comes back with the code, the file, the line, the column, the
message and the compiler's hint — and then `classification`, `severity` and
`ai_remediation_strategy`, looked up in `ERROR_TAXONOMY.json`.

The compiler prints a `remediation_strategy` of its own, and for some codes it
is **not** the one in the taxonomy. Both are returned, under
`ai_remediation_strategy` and `compiler_remediation_strategy`, because an
agent silently handed the wrong one of two disagreeing answers is worse off
than one handed both.

This is the only tool that runs against your own directory, because
`strata check` writes nothing.

### `workspace`: why a copy

`strata build` and `strata run` make the compiler write a generated `.c` file
beside every `.sta` it reads. An agent asking "does this build?" has not asked
for ten new files in your source directory. So both default to
`workspace: "scratch"` — a throwaway copy under `/tmp`. Pass
`workspace: "project"` when you want a binary in `build/` or a program that
reads and writes your real data files.

`strata_rename_impact` has no such option. It always uses a copy.

---

## How it differs from the Python one

These are differences in behaviour, not in style. Everything else is meant to
match.

- **`strata_test` is not here.** The Python server has it. It works by
  matching `strata test`'s human-readable output with regular expressions,
  which its own README calls the weakest thing in that server — and Strata has
  no regular expressions at all, so the weakest thing there would have been
  the longest thing here. A tool reimplemented worse is not worth having.
- **No JSON-RPC batches.** A top-level array is refused with `-32600` and a
  sentence saying so. MCP's 2025-06-18 revision removed batching, so this is
  the current protocol rather than a gap — but the Python server accepts one
  and this does not. The deeper reason is below, under the parser.
- **At most six program arguments**, and none of them may be empty. The
  language has no growable list, so an argument list is six `str` parameters
  with `""` marking the end. A seventh is refused with a readable message
  rather than dropped.
- **A document nested more than 64 deep is a parse error.** A recursive
  descent parser will run out of C stack on a document built to make it, and a
  crash is a worse answer than a refusal. It comes back as `-32700`, which is
  the right family of answer and not a precise description of what happened.
- **Both `jsonrpc` and the shape of `params` are read loosely.** A missing
  `params` reads as absent arguments rather than as an invalid request, so
  there is no `-32602`.
- **Errors are not caught, because the language has no exceptions.** The
  Python server wraps every dispatch in `try/except` and returns a traceback
  as a tool result. Here, a failure that is anticipated is a return value and
  a failure that is not is a dead server. Nothing in the end-to-end test
  produces one, which is not the same as there being none.
- **It is about 2.4 times as long** — 3,720 lines against 1,738 — and roughly
  700 of those are a JSON reader that Python has in its standard library. The
  speed is the same: both answer `strata_rename_impact` on `apps/payables` in
  about a second, because both spend that second inside the compiler.

---

## What it does NOT do

This list is the honest one. Every item is a real gap, not a disclaimer.

- **No resources, prompts, sampling, completions or progress.** Tools only.
  A long `strata_rename_impact` gives no progress updates.
- **No cancellation.** A `tools/call` runs to completion or hits the
  300-second timeout. `notifications/cancelled` is accepted and ignored,
  like every other notification.
- **One request at a time.** Requests are read and answered in order off one
  stream. A slow call blocks the next one.
- **One JSON document at a time.** The parser keeps its tree in a table and
  parsing clears it, so a request's tree is gone the moment a tool parses the
  compiler's answer. Every argument is read out into local variables before a
  tool runs, which works and is the reason batches are refused rather than
  half-answered. It is the sharpest edge in this code and the first thing to
  fix if the language ever gets a second one.
- **Memory is never given back.** `scratch_reset()` is the language's way of
  freeing temporaries and it is placed by hand; placing it wrong is a
  use-after-free that nothing catches, and the strings this server hands
  between a parse and a reply are exactly the kind it would free. So it is
  never called. A server answering thousands of requests will grow. For an
  editor session it is nothing; for a long-lived service it is a leak.
- **`strata_rename_impact` only renames.** It does not drop a column, change
  a type, rename a table, or write the `migrate` block you need before the
  stored file will load. It tells you what would break; fixing it is yours.
- **It follows dependencies one way, and only between siblings.** A project
  elsewhere in the tree that depends on the one you named is not found.
- **Cascading diagnostics are not collapsed.** The `E002` in `rules.sta:112`
  above is a consequence of the `E004` on the same line, not an independent
  problem. Everything the compiler said is reported.
- **`strata_schema` reads `database` blocks only.** Not `model`, not
  `foreign`, not `layout`, not `report`.
- **Column line numbers are found by reading the text.** `strata ast` carries
  no line numbers, so a declaration line is located by searching the block. A
  line that could not be found comes back as `null` rather than as a guess.
  The names and types are the compiler's own reading and are exact.
- **A file that does not parse is named, not explained.** `strata ast` prints
  a Python traceback rather than a diagnostic for an unparseable file, so
  `strata_schema` lists it under `unreadable_files` with the last line of
  that traceback. Use `strata_check` on it to get the real `E000`.
- **The block scanner is not a parser.** It counts braces with comments and
  string literals skipped, which is enough to say which block a line the
  compiler already pointed at sits in, and not enough for anything else.
- **No PostgreSQL awareness, and no editing.** Tables are read from
  declarations. Nothing here writes to your source.
- **One checkout per server.** `--root` is fixed at start.
- **Linux only, for one function.** Finding its own binary uses
  `/proc/self/exe`. On a machine without it, pass `--root` or run from inside
  the checkout; everything else is POSIX.
- **`find`, `cp` and `rm` are run as programs.** Walking a directory needs
  `opendir` and a `struct dirent`, and a `native` block cannot carry an
  `#include`, so the struct would have to be re-declared by hand against
  whatever libc is on the machine. Running the tool that already does it is
  the smaller risk. They are started with `execvp` and an argument list —
  never through a shell.

---

## Security

- **Paths cannot escape the checkout.** Every path a caller sends is checked
  twice: once on its spelling, with `.` and `..` worked out, so a path that
  climbs out is refused whether or not it exists; and once on what the file
  system resolves it to, which is what catches a symbolic link inside the tree
  pointing out of it. `test_server.sh` asks for all three shapes.
- **Nothing reaches a shell.** Every subprocess is `fork` and `execvp` with an
  argument list. This server does not import `std/os`, whose `run` and
  `capture` hand a string to `/bin/sh` — not because they are wrong, but
  because a program taking paths from a caller is better off not linking a
  shell in at all.
- **Table, column, code and name arguments must be plain identifiers.**
  Anything else is refused before a path is resolved or a file is opened.
- **A tool failure is a result, not a protocol error.** It comes back with
  `isError: true` and a readable reason, so the agent can act on it. JSON-RPC
  errors are reserved for a malformed request.

The server runs the compiler, and the compiler runs a C compiler and then your
program. Point it at a checkout you trust.

---

## The files

| | |
|---|---|
| `src/main.sta` | JSON-RPC over stdio, the tool catalogue, dispatch. Knows nothing about Strata. |
| `src/tools.sta` | `strata_check`, `strata_taxonomy`, `strata_build`, `strata_run`, `strata_schema`. |
| `src/rename.sta` | `strata_rename_impact`, which is big enough to live alone. |
| `src/jsonval.sta` | A JSON reader, a JSON writer's helpers, and three functions that take a span out of a document without reading it. |
| `src/diag.sta` | A compiler diagnostic plus what `ERROR_TAXONOMY.json` knows about its code. |
| `src/blocks.sta` | Which top-level block a line sits in, and therefore which tier. |
| `src/paths.sta` | Path containment, identifier validation, a two-key TOML reader. |
| `src/text.sta` | Replace, line access, whole-word search. The string work `std/` does not have. |
| `src/sys.sta` | Running a program without a shell, and the few file-system calls this needs. |
| `examples/` | One file that compiles and one that does not, both for the test. |
| `test_server.sh` | Starts the server and speaks to it the way a client does. |

The protocol and the toolchain are split so they can be wrong independently,
and `test_server.sh` drives the pair from outside rather than importing
either.

The `verify` blocks are in the modules, next to what they test. They cover the
pure parts — JSON reading and writing, path containment and normalisation,
identifier validation, diagnostic enrichment, block spans, whole-word search —
and `strata test .` runs them. What they cannot cover is anything that needs a
checkout or a subprocess; that is what `test_server.sh` is for.
