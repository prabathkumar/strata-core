---
description: Ask a language model about a Strata diagnostic, with the prompt assembled from the compiler's own output, the error taxonomy and the source around each line. Needs an API key in the plugin's settings; without one it refuses rather than guessing.
argument-hint: [file-or-project] [question]
allowed-tools: mcp__plugin_strata-toolchain_strata__strata_ask_model, mcp__plugin_strata-toolchain_strata__strata_check
---

Ask the configured model about `$ARGUMENTS`. Read `$0` as the file or project
and everything after it as the question. If no question was given, use
"Explain each diagnostic and propose the smallest repair."

## Before you call it

**You have a model of your own.** Reach for this when a second opinion is the
point — a diagnostic you have already read and are not sure about, a code
where the taxonomy and the compiler disagree, a repair you want argued
against. For an ordinary diagnostic, `/strata-toolchain:check` is the shorter
road and sends nothing off the machine.

## What to do

1. Call `strata_ask_model` with `question` and `path`. Add `code` when the
   question is about one error code in particular.

2. The server runs `strata check` itself and builds the prompt out of the
   answer: every diagnostic, the taxonomy's classification and remediation
   strategy for each code, the compiler's own strategy where it differs, and
   the source lines either side of each diagnostic with that line marked. You
   do not need to assemble any of that, and you should not paste source into
   the question — it is already in the prompt.

3. Read `mode` in the result. `dry_run` means nothing was sent and
   `user_prompt` is what would have gone out; that is a rehearsal, not an
   answer, and you should say so rather than presenting the prompt as a
   reply.

## What the result is, and what it is not

**It is a model's text and nothing has checked it.** Not the compiler, not
the taxonomy, not this server. Treat every concrete claim in it as a proposal:
if it suggests a change, make the change and run
`/strata-toolchain:check` on the file before you tell the user it works. If
the answer proposes syntax you have not seen elsewhere in the codebase, say
so instead of using it.

## When it refuses

The refusals are deliberate and each names what to do:

- **`STRATA_LLM_KEY is not set`** — no key is configured. Tell the user to
  set the plugin's "API key" option, or to set `STRATA_LLM_KEY` in the
  environment that starts the server. Do not offer to pass a key as an
  argument; the tool does not take one, on purpose, because an argument is a
  line in the transcript.
- **`STRATA_LLM_MODEL is not set`** — no model name is configured. There is
  no default; a default model is a bill nobody agreed to.
- **`refusing to send a key to a plain-HTTP address that is not this
  machine`** — the endpoint is `http://` and not on this machine. The fix is
  an `https://` endpoint, not a workaround.
- **`give this tool a path, a code, or both`** — with neither, the prompt
  would carry nothing you did not already have.

A refusal is an answer. Report it as one, with the variable it named, rather
than retrying.
