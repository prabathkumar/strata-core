# The Strata MCP server

An MCP server that lets an AI agent ask the Strata compiler questions and get
answers back as data.

Strata already emits machine-readable diagnostics — `bin/strata build --json`
and the codes in `ERROR_TAXONOMY.json`, each one carrying a classification and
an `ai_remediation_strategy` written for a machine to follow. What was missing
was a way for an agent to reach them without shelling out and scraping text.
This is that.

The tool worth looking at first is `strata_rename_impact`. It answers the
question this language exists to answer: *if I rename this column, what
breaks?* — and it answers it before anything is changed.

---

## What it needs

Python 3.8 or newer — tested on 3.10. Nothing else.

There is no `pip install`. The official `mcp` package installs cleanly and
would have saved perhaps eighty lines, but it brings twenty-two packages with
it — pydantic, starlette, uvicorn, anyio and the rest. Strata ships no
dependencies at all, and an ecosystem component that makes `pip install` a
precondition for trying the compiler is a worse trade than the eighty lines.
The wire protocol is JSON-RPC 2.0 over newline-delimited JSON on stdin and
stdout, and `server.py` speaks it directly.

If this ever needs resources, prompts, sampling or progress notifications,
take the SDK. Tools alone do not justify it.

---

## Running it

```sh
python3 ecosystem/mcp/server.py                     # finds the checkout itself
python3 ecosystem/mcp/server.py --root /path/to/strata
```

It speaks on stdin and stdout, so running it in a terminal looks like it has
hung. It has not; it is waiting for a client. To see it work, run the tests:

```sh
python3 ecosystem/mcp/test_server.py
```

### Pointing Claude Code at it

```sh
claude mcp add strata -- python3 /absolute/path/to/strata/ecosystem/mcp/server.py
```

### Pointing Claude Desktop at it

In `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "strata": {
      "command": "python3",
      "args": ["/absolute/path/to/strata/ecosystem/mcp/server.py"]
    }
  }
}
```

Use absolute paths in both. The server is started with an unpredictable
working directory, which is also why every path a caller sends is read
against the checkout rather than against the current directory.

---

## The tools

| Tool | What it answers |
|---|---|
| `strata_check(path)` | Does this file type-check, and if not, exactly what is wrong? |
| `strata_build(path, out, workspace)` | Does it compile, and where is the binary? |
| `strata_run(path, args, workspace)` | What does it print, and what does it exit with? |
| `strata_schema(project_dir)` | What tables are there, with what columns and types? |
| `strata_rename_impact(project_dir, table, column, new_name)` | What would this rename break, across every tier? |
| `strata_test(project_dir)` | Do the `verify` blocks pass? |
| `strata_taxonomy(code)` | What does this error code mean, and what should be done about it? |

### `strata_check`

Every diagnostic comes back with the code, the file, the line, the column, the
message and the compiler's hint — and then the part that matters:
`classification`, `severity` and `ai_remediation_strategy`, looked up in
`ERROR_TAXONOMY.json`.

The compiler prints a `remediation_strategy` of its own, and for some codes it
is **not** the one in the taxonomy file. E000 is the plain example: the
compiler says "correct the token sequence so it matches the grammar", the
taxonomy says "correct the syntax at or immediately before the reported
position, and do not attempt any other repair until the file parses". Both are
returned, under `ai_remediation_strategy` and
`compiler_remediation_strategy`, because an agent silently handed the wrong
one of two disagreeing answers is worse off than one handed both.

This is the only tool that runs against your own directory, because
`strata check` writes nothing.

### `strata_rename_impact`

Copies the project to `/tmp`, changes one line — the column's declaration in
its `database` block — re-checks everything, and reports every place that
stopped compiling. Your files are never touched. Renaming `Bill.amount` in
`apps/payables`:

```
tiers_broken: ['phone', 'program', 'report', 'rules', 'web']
declaration:  apps/payables/src/schema.sta:30   (the one line that was changed)

  rules    apps/payables/src/importer.sta:167    E004 Column 'amount' does not exist in 'Bill'
  rules    apps/payables/src/importer.sta:167    E009 Insert into 'Bill' omits column 'gross'
  report   apps/payables/src/main.sta:31         E003 'amount' is not a column of 'Bill'
  program  apps/payables/src/main.sta:151        E004 Field 'amount' not in 'Bill'
  rules    apps/payables/src/rules.sta:112       E004 Column 'amount' does not exist in 'Bill'
  rules    apps/payables/src/rules.sta:112       E002 Return mismatch: expected 'int', got 'float'
  rules    apps/payables/src/rules.sta:124       E004 Field 'amount' not in 'Bill'
  web      apps/payables/src/views.sta:68        E004 Field 'amount' not in 'Bill'
  web      apps/payables/src/views.sta:78        E003 'amount' is not a column of 'Bill'
  web      apps/payables/src/views.sta:85        E004 Field 'amount' not in 'Bill'
  web      apps/payables/src/views.sta:87        E004 Field 'amount' not in 'Bill'
  phone    apps/payables_mobile/src/screen.sta:84 E004 Field 'amount' not in 'Bill'
```

The phone is a **separate project** that takes the schema as a dependency, so
a tool that only looked inside the directory it was given would have reported
five tiers out of six and looked right doing it. That is the exact failure
`test_suite/a_rename_reaches_every_tier.py` was written about, so sibling
projects that declare a path dependency on this one are copied and checked too.

The `tier` on each impact is a judgement made from the shape of the file, not
something the compiler said, so each one carries `tier_evidence` saying what
the judgement was made from. Argue with it when it is wrong.

### `workspace`: why a copy

`strata build`, `strata run` and `strata test` all make the compiler write a
generated `.c` file beside every `.sta` it reads. An agent asking "does this
build?" has not asked for ten new files in your source directory, and on a
checkout under version control those appear as changes nobody made. So those
three default to `workspace: "scratch"` — a throwaway copy under `/tmp`.

Pass `workspace: "project"` when you want the real thing: a binary in
`build/`, or a program that reads and writes your actual data files.

`strata_rename_impact` has no such option. It always uses a copy.

---

## What it does NOT do yet

This list is the honest one. Every item is a real gap, not a disclaimer.

- **No resources, prompts, sampling, completions or progress.** Tools only.
  A long `strata_rename_impact` gives no progress updates; it simply takes as
  long as it takes.
- **No cancellation.** A `tools/call` runs to completion or hits the 300-second
  timeout. `notifications/cancelled` is accepted and ignored.
- **One request at a time.** Requests are read and answered in order off one
  stream. A slow call blocks the next one.
- **`strata_test` parses text.** `strata test` has no `--json`, so the pass and
  fail lines are read with regular expressions. This is the weakest thing in
  the server: reword those lines in `bin/strata` and a failing block could
  become an unreported one. The full text comes back as `raw_output` so a
  caller can check the parse, and `exit_code` is the authority on pass or fail.
- **`strata_rename_impact` only renames.** It does not drop a column, change a
  type, rename a table, or write the `migrate` block that `FOR_DEVELOPERS.md`
  says you need before the stored file will load. It tells you what would
  break; fixing it is still yours.
- **It only follows dependencies one way, and only between siblings.** Sibling
  projects that depend on the project you named are copied and checked. A
  project somewhere else in the tree that depends on it is not, and neither is
  anything that depends on *that*. For `apps/` as it stands this is exact; for
  a larger layout it would undercount.
- **Cascading diagnostics are not collapsed.** Renaming `Bill.amount` produces
  an `E002` return-type error in `rules.sta` that is a consequence of the
  `E004` two lines above it, not an independent problem. Everything the
  compiler said is reported, and nothing tries to work out which errors caused
  which.
- **`strata_schema` reads `database` blocks only.** Not `model`, not `foreign`,
  not `layout`, not `report`. It gives you the shape of the data and nothing
  else.
- **Column line numbers in `strata_schema` are found by reading the text.**
  `strata ast` carries no line numbers, so the declaration line is located by
  searching the block. A line it could not find comes back as `null` rather
  than as a guess. The column names and types are the compiler's own reading
  and are exact.
- **A file that does not parse is named, not explained.** `strata ast` prints a
  Python traceback rather than a diagnostic when a file is unparseable, so
  `strata_schema` lists such files under `unreadable_files` with the last line
  of that traceback. Use `strata_check` on the file to get the real `E000`.
- **No PostgreSQL awareness.** Tables are read from the declarations, not from
  a live database. Nothing here connects to one.
- **No editing.** Nothing in this server writes to your source. An agent that
  wants to apply a fix must do it with its own file tools.
- **One checkout per server.** `--root` is fixed at start. Serving two
  checkouts means running two servers.

---

## Security

- **Paths cannot escape the checkout.** Every path a caller sends is resolved
  with `realpath` — so a symlink pointing out of the tree is caught rather than
  followed — and then checked to be inside the root the server was started
  with. `../../etc/passwd`, `/etc/passwd` and the rest come back as errors.
  `test_server.py` asks for all three.
- **Nothing reaches a shell.** Every subprocess is an argument list.
  `strata_run`'s `args` go to the program as argv, so a value containing a
  semicolon is an argument containing a semicolon.
- **Table, column and name arguments must be plain identifiers.** Anything else
  is refused before a file is opened.
- **A tool failure is a result, not a protocol error.** It comes back with
  `isError: true` and a readable reason, so the agent can act on it. JSON-RPC
  errors are reserved for a malformed request.

The server runs the compiler, and the compiler runs a C compiler and then your
program. Point it at a checkout you trust.

---

## The files

| | |
|---|---|
| `server.py` | JSON-RPC over stdio, the tool catalogue, and nothing about Strata. |
| `strata_api.py` | The seven tools as plain functions returning plain dictionaries. |
| `strata_tools.py` | Finding the checkout, path safety, running the toolchain, reading block structure. |
| `test_server.py` | Starts the server and speaks to it the way a client does. |

They are split that way so the protocol and the toolchain can be wrong
independently, and so `test_server.py` tests the pair from outside rather than
importing either.
