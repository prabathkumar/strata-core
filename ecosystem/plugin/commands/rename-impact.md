---
description: Answer "what breaks if I rename this column?" before anything is changed. Runs the rename against a throwaway copy of the project and reports every place that stopped compiling, with the tier it belongs to.
argument-hint: [project-dir] [Table.column] [new-name]
allowed-tools: mcp__plugin_strata-toolchain_strata__strata_schema, mcp__plugin_strata-toolchain_strata__strata_rename_impact, mcp__plugin_strata-toolchain_strata__strata_taxonomy
---

The user wants to know what a column rename would break: `$ARGUMENTS`

Read `$0` as the project directory, `$1` as `Table.column`, and `$2` as the
new name. If any of the three is missing or `$1` has no dot in it, ask for
the missing piece instead of guessing — a rename run against the wrong column
reports a clean answer about the wrong question.

## What to do

1. If you are not certain the table and column exist as spelled, call
   `strata_schema` on the project first and check. A column name that is
   nearly right produces "no column", which is correct and wastes a round
   trip.

2. Call `strata_rename_impact` with `project_dir`, `table`, `column` and
   `new_name`. **Nothing of the user's is modified by this.** The tool copies
   the project to `/tmp`, changes the one line that declares the column, and
   re-checks everything there.

3. Report what came back, grouped by the `tier` on each impact — data, rules,
   web, report, phone, test, program — and within a tier by file and line.
   Lead with the count of tiers and the count of impacts, because that is the
   number the person asked for.

## What to say about the answer, and what not to

- **The declaration line is named separately.** It is the one line the tool
  changed, not a break. Do not count it as one.
- **Cascades are not collapsed.** Two diagnostics on the same line are often
  one mistake: an `E004` about a column that no longer exists, then an `E002`
  about the type of the expression built from it. Say which you think is the
  cause rather than listing both as separate work.
- **`tier` is a judgement, not something the compiler said.** Each impact
  carries `tier_evidence` saying what the judgement was made from. If a tier
  looks wrong to you, say so and quote the evidence.
- **A project elsewhere in the tree is not found.** The tool follows path
  dependencies between *siblings* of the project directory. If something
  further away depends on this schema, nothing here has looked at it, and the
  user should be told that rather than left to assume the list is complete.

## The part that is not in the tool's answer

The build is only half of a rename. The stored file on disk still has the old
column in its header, and the loader refuses a file whose header disagrees
with the schema rather than handing back a row of empty values. So finish by
telling the user they also need a `migrate` block next to the schema:

```
migrate <Table> {
    rename <old> to <new>;
}
```

The migration is checked against the schema, so a claim that is not true does
not compile, and the next ordinary run rewrites the file. Without it the code
builds and the program cannot read its own data.

Do not make any of these changes. This command answers a question; the user
decides whether to go ahead.
