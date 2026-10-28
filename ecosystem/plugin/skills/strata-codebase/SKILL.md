---
description: How to work on a Strata codebase — the project layout, the commands, and the house rules that are not discoverable from the source. Use whenever reading, changing, building or reviewing .sta files, the Strata compiler, or a Strata application.
---

# Working on a Strata codebase

Strata is a statically typed language whose compiler refuses rather than
guesses. One `database` block describes a table, and every other tier — the
rules, the web pages, the reports, the phone screens — is checked against that
one description. Renaming a column is meant to break the build everywhere that
column is read. That is the language working.

This skill is what a new engineer would be told on the first morning. The
sharp edges below each cost somebody an afternoon, and none of them is
discoverable by reading the happy path.

## Where things are

| | |
|---|---|
| `compiler/` | The compiler. `.sta` is the self-hosted implementation; `lexer.py`, `parser.py` and `typechecker.py` are the Python oracle. `.c` files are generated — never edit one. |
| `bootstrap/stage0.py` | The bootstrap compiler, and the second code generator. |
| `std/` | The standard library, about two dozen modules. |
| `bin/strata` | The toolchain entry point. |
| `apps/` | Real applications: `payables`, `orders`, `ledger` and the two phone apps. These are the end-to-end evidence, not samples. |
| `test_suite/` | Differentials, journeys and regression files. Python, run in CI. |
| `examples/` | Single-file programs. Every fenced example in `README.md` and `LANGUAGE_SPECIFICATION.md` is compiled on every commit. |
| `ecosystem/` | The MCP servers — `mcp/` in Python, `mcp_strata/` in Strata — and this plugin. |
| `ERROR_TAXONOMY.json` | Every error code, what it means, and the remediation strategy written for a machine to follow. |
| `STAGES.md` | The gaps list, kept current. **If anything disagrees with it, it is right.** |

## The commands

```sh
bin/strata check <file.sta> [--json]   # type-check; writes nothing
bin/strata build [file.sta]            # no file: builds the project here
bin/strata run   [file.sta]            # build and run
bin/strata test  [dir]                 # run the verify blocks
bin/strata fmt   <file.sta>... --check  # canonical formatting; --check is what CI runs
bin/strata deps  [project-dir]         # fetch path and git dependencies
bin/strata repair <file.sta>           # rules-based fix, no model involved
```

This plugin's MCP tools answer the same questions as data rather than as text:
`strata_check`, `strata_build`, `strata_run`, `strata_schema`,
`strata_taxonomy`, `strata_rename_impact` and `strata_ask_model`. Prefer them
over scraping the command line output — the diagnostics come back with the
taxonomy's classification and remediation strategy already attached.

`build`, `check`, `fmt`, `deps` and `lsp` are self-hosted. `ast`, `lex`,
`test` and `repair` still go through Python.

## The three house rules

### 1. The compiler is written twice, and both copies change together

The lexer, the parser, the type checker and the code generator each exist in
two implementations: Python as the oracle, and Strata as the self-hosted one.
Differential tests in `test_suite/` compare them on every commit, and for code
generation the comparison is **byte for byte**, because the next tool in the
chain is a C compiler that notices any difference.

So: a change to `compiler/typechecker.sta` that is not also made in
`compiler/typechecker.py` fails CI, and the reverse is equally true. Change
both in the same commit. When you are unsure which file is the oracle for the
thing you are touching, look for the matching `*_diff.py` in `test_suite/` —
its docstring names both sides.

A real failure worth knowing about: the two checkers agreed on every machine
the compiler is developed on and disagreed on a fresh clone, because the whole
difference lived in an unfetched dependency path that nobody takes twice.
`test_suite/a_clean_checkout_agrees.py` now runs the comparison in a tree with
no `.strata` anywhere.

### 2. `strata check` passing must mean a clean build

A check that passes and a build that then fails is the worst outcome this
project has, because it makes the fast tool untrustworthy and everybody goes
back to waiting for the slow one. If you find a case where it happens, that is
a bug in the checker, not a quirk to route around.

The one known gap runs the other way and is deliberate: `strata check` on a
single file requires that file to import what it uses, and the project build
currently accepts a file relying on an import in a different file. The check
is right and the build is being tightened. If the editor underlines something
the build accepts, **add the import it names.**

### 3. Every change needs a test, and the test names why

Not "a test exists" — a test whose name and comment say what went wrong and
what would go wrong again. The convention in `test_suite/` is a file per round
of findings (`round_seventeen_stays_fixed.py` and so on) with one check per
finding, each carrying the reason in prose.

Some of those checks are structural rather than behavioural on purpose: they
assert that a single gate still exists and that both code generators still go
through it, because a change that restored a second write path would pass
every behavioural test on the day it was made and fail a month later.

When you repair something, ask whether the same mistake is wearing another
hat somewhere. Three rounds in a row found the same design gap patched in the
shape the last report happened to show, with the shape one line over left
alone. Prefer a rule that cannot be omitted over a fourth patch.

## Sharp edges

**`scratch_reset()` in the wrong place is a use-after-free.** Memory comes
from an arena and the reset throws the whole arena away. After a reset, only
what is in a `table` still exists — tables keep their own copies. Strings you
built, query results and string builders are gone, with no error and no
reliable crash. Put the reset at a boundary where nothing is in hand. A batch
program that runs and exits never needs it.

**There are no exceptions.** A failure sets an error flag. Read it with
`had_error()`, act, and clear it with `clear_error()`. A program that reaches
its exit with an error nobody cleared prints it and exits 65 — including when
you did deal with it but forgot the clear. Your own code reports failure with
`fail("...")`.

**An insert must name every column.** Adding a column to a schema breaks every
insert until you say what it holds. That is deliberate: without it, adding a
column writes an empty value into every row the statement creates and nothing
looks wrong.

**An `int` widens to a `float` silently; a `float` never narrows to an `int`,
and there is no cast.** This is the one that produced a money total that was
really a row count, in a document that said the opposite until an audit caught
it.

**Never keep money in a `float`.** `std/money.sta` holds an amount as an `int`
of minor units — 1250 is RM 12.50. The compiler cannot tell that you meant
money, so it will let you declare `float price`.

**Text is bytes.** `str_len("héllo")` is 6 and an index is a byte. Use
`str_chars` to count characters and `str_truncate(value, max_bytes)` to trim.

**A renamed column needs a `migrate` block.** The build breaking is half of
it; the stored file still has the old header and the loader refuses it rather
than handing back empty values. Say what you meant next to the schema:
`migrate Item { rename price to cost; }`. The migration is checked against the
schema, so a false claim does not compile, and the next ordinary run rewrites
the file.

**A `foreign` block only works where somebody has built it.** It names a C
header and a library, both platform-specific, and nothing warns you. Build it
on every platform your team uses before relying on it.

**`build/` holds whatever ran last.** Outputs are not named per platform, so a
folder shared between two machines hands the second one an object the first
built. It shows up as "cannot execute binary file". Rebuild.

**Some names need no import and it is not obvious which.** `str_concat`,
`str_len`, `str_eq`, `str_slice`, `str_index_of`, `str_to_int`, `file_read`,
`file_write`, `file_exists`, the `str()`/`int()`/`float()` casts and the
aggregates are prelude. Everything else needs its module imported — delete
`import io from std;` and `print` is `E011`.

**Write the `str_*` names, not the `strata_*` ones.** The runtime's own C
functions are callable and are an implementation detail that is not promised
to stay.

**A query is a scan.** No index, no joins, no `GROUP BY`. `by <column> desc
first 10` orders and then truncates, and `by` names a column rather than a
string, so renaming the column breaks that line like every other.

**Concurrency is processes, not threads.** The HTTP server forks per
connection. There is no shared mutable memory and no in-memory cache between
requests.

**The generated C has no namespace.** A Strata function becomes a C function
of the same name, so a name that libc also uses — `send`, `read`, `write` —
collides once a header declaring it is pulled in, and the error arrives from
the C compiler a long way from the Strata line that caused it. Prefer a name
with a prefix in anything that links the standard library's networking.

## Reading a diagnostic

Every diagnostic has a code and `ERROR_TAXONOMY.json` says what to do about
it. The MCP tools attach that automatically; from the command line, use
`strata check file.sta --json` and look the code up.

Two things to hold on to:

- The compiler prints a remediation strategy of its own, and for some codes it
  is **not** the one in the taxonomy. Both are returned, under
  `ai_remediation_strategy` and `compiler_remediation_strategy`. When they
  disagree, say which one you took.
- `E000` means the file did not parse, so nothing else said about it is
  trustworthy. Fix the syntax and check again before reading anything else.
  The same logic applies to cascades: one missing column makes every
  expression built from it the wrong type.

## Things not to do

- Do not edit a generated `.c` file. They are rebuilt and your change is gone.
- Do not change one half of the compiler without the other.
- Do not widen a column's type to silence `E010`. Convert the value, or change
  the type because the new type is what the data actually is.
- Do not change a function's signature to fit one caller unless you change
  every other caller with it.
- Do not add a flag that turns a check off. There is no `tls_insecure()` and
  no "skip verification in development", on purpose.
- Do not claim something is done because it compiles. `bin/strata test` runs
  the `verify` blocks, and the journeys in `test_suite/` are what prove an
  application still works.
