---
description: Type-check a Strata file or project and explain every diagnostic using the error taxonomy's remediation strategy, naming the cases where the taxonomy and the compiler disagree.
argument-hint: [file-or-project]
allowed-tools: mcp__plugin_strata-toolchain_strata__strata_check, mcp__plugin_strata-toolchain_strata__strata_taxonomy, mcp__plugin_strata-toolchain_strata__strata_schema
---

Check `$ARGUMENTS` and explain what came back. If no path was given, ask for
one.

## What to do

1. Call `strata_check` with `path`. It is read-only: it writes nothing, and
   it runs against the user's own directory rather than a copy. A path that
   resolves outside the checkout is refused, including through a symbolic
   link, and that refusal is the answer rather than something to work around.

2. If `diagnostics` is empty and `ok` is true, say so in one line and stop.

3. Otherwise, take the diagnostics **in order** and explain each one:

   - the code, the file, the line and the column;
   - what the compiler said, in the compiler's own words;
   - `classification` and `severity` from `ERROR_TAXONOMY.json`;
   - `taxonomy_diagnostic` — what this code means in general, which is often
     the sentence that makes the specific message make sense;
   - `ai_remediation_strategy` — what the language's authors say to do about
     this code. **This is the strategy to follow.**

4. Where `compiler_remediation_strategy` differs from
   `ai_remediation_strategy`, say so explicitly, quote both, and say which
   you are following and why. They disagree for some codes on purpose, and a
   reader handed one of two disagreeing answers with nothing saying there was
   another will follow it confidently.

5. Where `taxonomy_known` is false, say that the code is not in the taxonomy
   and that the strategy you are quoting is the compiler's own. Do not
   present it as the agreed answer.

6. Propose the smallest change that removes the first diagnostic, and say why
   that is the right change rather than the one that merely silences it.
   Then re-run `strata_check` on the same path to confirm — a repair nobody
   re-checked is a guess.

## Things that will mislead you if you forget them

- **A cascade is one mistake, not five.** A column that does not exist makes
  every expression built from it the wrong type. Fix the first diagnostic and
  check again before reading the rest as separate work.
- **`E000` means nothing else is trustworthy.** When the file did not parse,
  no other diagnostic about it is reliable. Repair the syntax at or just
  before the reported position and check again before touching anything else.
- **`E007` is an advisory about an unfetched dependency**, not a mistake in
  the file. The fix is usually `strata deps`, not an edit.
- **`strata check` on one file is stricter than the project build**: it
  requires that file to import what it uses, and the project build currently
  accepts a file that relies on an import somewhere else. If the check names
  an import the build did not need, add the import — the check is the one
  that is right.
- **An insert that omits a column is `E009` and is a real mistake.** The
  unnamed columns would be written as a zero or an empty string in every row
  the statement creates, with nothing else to show for it.

If a diagnostic code is one you have not met, call `strata_taxonomy` with it
and read the entry before saying anything about it.
