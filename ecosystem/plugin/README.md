# The Strata toolchain, as a plugin

This packages `ecosystem/mcp_strata/` — the Strata MCP server, written in
Strata — so an AI coding client can install it in one step instead of being
pointed at a binary by hand. It adds three slash commands and one skill.

The server is the thing that does the work. This directory is wiring and
instructions: a manifest, a launcher, three commands and a skill. Nothing here
is a second implementation of anything.

---

## What it needs

A Strata checkout with `bin/strata` and `ERROR_TAXONOMY.json` in it. Nothing
else — no Python at run time, no packages, no `pip install`. The launcher
builds the server from that checkout the first time it starts, and again
whenever the server's own sources change.

---

## Installing it

The plugin lives inside the Strata checkout, at `ecosystem/plugin/`.

```sh
claude --plugin-dir /absolute/path/to/strata/ecosystem/plugin
```

or, to keep it across sessions, add the checkout as a marketplace and install
`strata-toolchain` from it.

When the plugin is enabled the client asks for its configuration. One option
is required:

| Option | Required | What it is |
|---|---|---|
| **Strata checkout** | yes | The absolute path of the checkout to serve. Must hold both `bin/strata` and `ERROR_TAXONOMY.json`. |
| **Model name** | no | For `strata_ask_model` only. No default. |
| **Chat-completions endpoint** | no | For `strata_ask_model` only. Defaults to `http://127.0.0.1:11434/v1/chat/completions`, a model server on this machine. |
| **API key** | no | For `strata_ask_model` only. Stored in the machine's credential store, handed to the server as an environment variable. Never a tool argument, never written to a file, never in a tool result. |

Before any of that, and again after changing anything here:

```sh
bash ecosystem/plugin/test_plugin.sh          # 14 checks, no client needed
claude plugin validate ecosystem/plugin       # the authoritative one
```

Confirm it loaded with `/mcp`: the server appears as
`plugin:strata-toolchain:strata`, and its tools are named
`mcp__plugin_strata-toolchain_strata__strata_check` and so on.

**One checkout per session.** The root is fixed when the server starts. To
serve a different checkout, change the option and reload.

---

## The commands

| Command | What it does |
|---|---|
| `/strata-toolchain:rename-impact [project] [Table.column] [new-name]` | Answers "what breaks if I rename this column?" — before anything is changed. The rename is applied to a throwaway copy under `/tmp`, everything is re-checked there, and every place that stopped building comes back with the tier it belongs to. Finishes by telling you about the `migrate` block the stored file needs, which the tool itself does not write. |
| `/strata-toolchain:check [file-or-project]` | Type-checks and then explains every diagnostic using the taxonomy's remediation strategy for that code — and names the cases where the taxonomy and the compiler disagree, rather than quietly picking one. Read-only. |
| `/strata-toolchain:ask-model [file-or-project] [question]` | Asks a language model about the diagnostics, with the prompt assembled by the server out of the compiler's own output, the taxonomy and the source around each line. Needs a key; without one it refuses and names the setting. |

`rename-impact` is the one worth trying first. It is the question the language
exists to answer.

## The skill

`skills/strata-codebase/SKILL.md` is what a new engineer would be told on the
first morning: where things are, the commands, and the rules that are not
discoverable from the source — the compiler is written twice and both halves
change together, `strata check` passing must mean a clean build, every change
needs a test that says why it exists. Then the sharp edges, each of which has
cost somebody an afternoon.

The client loads it when you ask about a Strata codebase; you can also run it
as `/strata-toolchain:strata-codebase`.

---

## What it does NOT do

- **It does not install the Strata compiler.** You need a checkout already,
  and the plugin needs to be told where it is. There is no download step and
  no version check.
- **It does not edit your code.** Every tool here reads. `strata_check` runs
  against your own directory because it writes nothing; `strata_build` and
  `strata_run` work on a throwaway copy by default, because the compiler
  writes a generated `.c` file beside every source it reads. The commands tell
  you what to change and stop there.
- **It writes to your checkout once, to build the server.** The first start
  runs `strata build` in `ecosystem/mcp_strata/`, which leaves a binary in
  `build/` and a `.c` file beside each `.sta` in `src/`. Both are already in
  that directory's `.gitignore`. Nothing else in the checkout is touched.
- **It is Linux and macOS.** The launcher is a bash script, and the server
  finds its own binary through `/proc/self/exe` when no root is given — which
  this plugin always gives, so that part does not apply. Nothing here has been
  run on Windows.
- **The MCP server is stdio only.** It runs on the machine the client runs on.
  There is no remote URL, so this plugin does not reach a client that only
  offers connectors over https.
- **No `strata_test` tool.** The Python server has one; the Strata server does
  not, and its README says why. `bin/strata test` from a terminal is the
  answer meanwhile.
- **`rename-impact` only renames.** It does not drop a column, change a type,
  rename a table, or write the `migrate` block. It tells you what would break;
  fixing it is yours.
- **`rename-impact` follows dependencies one way, and only between siblings.**
  A project elsewhere in the tree that depends on the one you named is not
  found, and the answer will look complete.
- **`ask-model` is untested against a live service.** There was no API key on
  the machine this was written on. Everything up to the socket is tested;
  whether a real endpoint answers is not. See the server's README.
- **`ask-model` sends your source to whatever endpoint is configured.** The
  prompt carries the lines around each diagnostic. That is the point of it and
  it is also a copy of your code leaving the machine. The default endpoint is
  local so that forgetting the setting sends nothing anywhere.
- **No hooks, no agents, no output styles.** The manifest declares none. A
  rule that must hold every time belongs in a hook, and there is no such rule
  here yet — `strata fmt --check` would be the obvious candidate.
- **It has not been run through `claude plugin validate`.** See below.

---

## What was verified about the manifest format, and what was not

The format was taken from the published plugin manifest reference and the
plugin components reference, not from memory. These parts are quoted from
there:

- the manifest lives at `.claude-plugin/plugin.json`, and `name` is the only
  required field;
- every other field used here — `displayName`, `version`, `description`,
  `author` (`name` required), `license`, `keywords`, `userConfig` — is a
  documented top-level field, and an unrecognised top-level field is stripped
  with a warning rather than failing the load;
- `userConfig` options are **strict**: an unknown key inside one is an error
  and the plugin does not load. The five fields used here — `type`, `title`,
  `description`, `required`, `sensitive` — are all documented, and `type`
  accepts `directory` and `string`;
- `sensitive: true` stores the value in the platform credential store rather
  than in `settings.json`;
- MCP servers go in `.mcp.json` at the plugin root, in the same shape as a
  project `.mcp.json`, and `${CLAUDE_PLUGIN_ROOT}` and `${user_config.KEY}`
  are both substituted in a stdio server's `command`, `args` and `env`;
- the server is named `plugin:<plugin>:<server>` and its tools
  `mcp__plugin_<plugin>_<server>__<tool>`;
- commands are flat Markdown files under `commands/`, becoming
  `/<plugin>:<file>`, and take the same frontmatter as a skill:
  `description`, `argument-hint`, `allowed-tools`, `model`;
- `$ARGUMENTS` is every argument; `$0` is the **first** argument, `$1` the
  second — the index is zero-based, which is the opposite of what it looks
  like;
- skills are `skills/<name>/SKILL.md` with a `description` in the
  frontmatter, and run as `/<plugin>:<name>`.

What could **not** be verified, and what was done about each:

- **`claude plugin validate` was never run.** The machine this was written on
  has a Claude Code binary that accepts only `claude -p "<prompt>"`, so the
  validator could not be reached. Every path in the manifest exists and
  starts with `./` or is a default location, and no unknown key was used in a
  strict object — but nothing has checked that claim mechanically. **Run
  `claude plugin validate ecosystem/plugin` before trusting it.**
- **The plugin was never loaded by a client.** The MCP server underneath it
  was driven end to end, by hand and by its own test script, through exactly
  the launcher this plugin uses — but no client has ever read this manifest.
- **What an unset optional `userConfig` value substitutes to is not
  documented.** It may arrive as an empty string or as the literal
  `${user_config.strata_llm_key}`. The second would be worse than nothing: the
  server would believe it had a key and send it. So `scripts/strata-mcp.sh`
  unsets any `STRATA_LLM_*` variable whose value still carries a `${`, and
  that guard is tested. If the substitution turns out to be an empty string
  the guard costs nothing.
- **There is no `$schema` line.** The field is documented and is ignored by
  Claude Code at load time, so it buys editor autocomplete and nothing else.
  The obvious schemastore URL was tried and does not resolve, and a URL
  nobody checked is worse than no URL, so the field was left out. Add it if
  you find the real one.
- **`allowed-tools` in the command files names the tools in their namespaced
  form.** The naming rule is documented; that these particular strings match
  what the client builds at run time has not been observed. If a command
  prompts for permission anyway, that is why, and it is a nuisance rather
  than a failure.

---

## The files

| | |
|---|---|
| `.claude-plugin/plugin.json` | Metadata and the four configuration options. |
| `.mcp.json` | One stdio server, `strata`, started through the launcher. |
| `scripts/strata-mcp.sh` | Finds the checkout, refuses a tree that is not one, builds the server when it is missing or out of date, and hands over. Everything it prints goes to standard error, because standard output is the protocol channel. |
| `commands/rename-impact.md` | What breaks if I rename this column. |
| `commands/check.md` | Check a file and explain every diagnostic. |
| `commands/ask-model.md` | Ask a model about the diagnostics. |
| `skills/strata-codebase/SKILL.md` | How to work in this codebase. |
| `test_plugin.sh` | Everything about this package that is knowable without a client: the JSON, the paths, the tool names in `allowed-tools` against the server's real catalogue, and the launcher's refusals. 14 checks. |
