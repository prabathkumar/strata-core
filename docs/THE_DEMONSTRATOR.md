# The demonstrator

Sixty-six CI steps prove the compiler works. They do not show anybody what
the language is *for*. This does.

`apps/payables` is the smallest system that still touches every tier: a
supplier file coming in, stored tables, business rules, a web page, a report,
a command line and a phone screen. It is about 600 lines of Strata. It exists
so that **one schema change can be shown breaking all of them at once**,
which is the only claim this language makes that other languages do not.

## Twenty minutes with it

```sh
cd apps/payables
../../bin/strata build src/main.sta -o build/payables
./build/payables import data/incoming.csv
```

```
took 5 bill(s), set aside 5
run 'payables show' to see which lines and why
```

### 1. The file is the one a supplier actually sends

`data/incoming.csv` is not a tidy fixture. It has a byte-order mark on the
front because it came out of Excel, a company name with a comma inside
quotes, a doubled quote inside a name, an amount typed `RM250.00`, a date of
30 February, a blank due-date cell, and a supplier nobody has heard of.

Five rows are good. Five are not. The five that are not come back with their
line numbers and a reason in words:

```
$ ./build/payables show

5 open, 155640.60 owed, 13340.60 of it overdue

oldest first:
  INV-1001  Selasih Sdn Bhd  2026-09-30  19 days late  12500.00
  INV-1002  Kolam Trading    2026-10-05  14 days late     840.50
  INV-1009  Selasih Sdn Bhd  2026-10-18   1 day late       0.10
  INV-1003  Tanjung Supplies 2026-11-20  due in 32 days 97300.00
  INV-1010  Tanjung Supplies 2026-12-01  due in 43 days 45000.00

set aside:
  line 5  INV-1004  'RM250.00' is not an amount
  line 6  INV-1005  '2026-02-30' is not a date in the form YYYY-MM-DD
  line 7  INV-1006  the due date is blank
  line 8  INV-1007  there is no supplier called 'Nobody Ltd'
  line 9  INV-1008  there is no supplier called 'He said "fine"'
```

Nothing was guessed at and nothing was dropped. That is the whole of
`src/importer.sta`: every value is parsed by something that can say no
(`csv_row_ok_at`, `date_parse_ok`, `money_parse_ok`) and a row that fails any
of them is written to a `Rejected` table with its line number, rather than
turned into a plausible number that flows into a ledger.

### 2. The money is exact

`155640.60` is exact to the cent, and stays exact however many rows are added
up. `amount` is an `int` holding minor units, not a `float` — a float cannot
hold 0.10 exactly, so a ledger built on one is eventually a penny out and
nobody can say why. `std/money.sta` does the arithmetic and the formatting.

`due` is an `int` too, holding seconds since 1970 UTC. The language has no
date type; `std/time.sta` has the calendar, borrowed from C rather than
invented.

### 3. The ranking is part of the query

```text
list[Bill] largest = Bill <- [state == "OPEN"] by amount desc first 5;
```

Not `sort_by(bills, "amount")`. A column name passed as a string is a schema
nothing checks — rename the column and that call still compiles and silently
sorts by nothing. Here `amount` is checked against the schema like any other
column, which is what makes step 7 work.

### 4. The web page

```sh
./build/payables serve 8095
```

`src/views.sta` is a `layout`, and a layout is a value: `render Outstanding(...)`
yields the document as a `str`, which is what lets it answer an HTTP request
with no template language and nothing to install. Every column the page shows
is checked against `database Bill`. There is no string naming a field
anywhere in it.

### 5. The phone, from the same table

```sh
cd ../payables_mobile
../../bin/strata deps
../../bin/strata build src/main.sta -o build/payables_mobile
cd ../payables && ../payables_mobile/build/payables_mobile
```

```
drew 5 bill(s) on the list screen
```

The phone app does **not** have its own copy of the schema. It takes it as a
path dependency:

```toml
[dependencies]
payables = { path = "../payables" }
```

This is the one thing the project previously got wrong and did not know. The
orders app's phone tier carried a hand-written copy of its `database` block
for a year, under a comment saying there was only one description of an
order. A blind evaluator renamed a column in round 13 and found the web build
breaking correctly while the phone build stayed green, still drawing a column
that no longer existed. Here there is one description, and
`test_suite/a_rename_reaches_every_tier.py` fails if anybody pastes a second
one back.

### 6. Change one thing, and watch

```sh
./build/payables paid 3
```

The total drops from `155640.60` to `58340.60`, and the phone sees it,
because it is the same table rather than a copy that is synchronised.

### 7. The step the other six set up

Open `src/schema.sta` and rename one column:

```diff
 database Bill {
     int id;
     int supplier_id;
     str reference;
     int due;
-    int amount;
+    int gross;
     str state;
 }
```

Then build anything:

```
$ ../../bin/strata check src/rules.sta
  E004  Column 'amount' does not exist in 'Bill'

$ ../../bin/strata check src/importer.sta
  E004  Column 'amount' does not exist in 'Bill'

$ ../../bin/strata check src/views.sta
  E004  Field 'amount' not in 'Bill'

$ cd ../payables_mobile && ../../bin/strata check src/screen.sta
  E004  Field 'amount' not in 'Bill'
```

**Six tiers, one rename, nothing left behind** — the rules, the import, the
web page, the report, the command line and the phone. Before the program
runs. `test_suite/journey_payables.py` does exactly this on every commit and
fails if any one of them still compiles.

That is the sentence the whole project is built to be able to say. Everything
else — the two compilers, the differentials, the self-hosting fixpoint, the
fourteen blind pilot rounds — exists to make that sentence trustworthy.

## What this does not show

Being honest about the edges, because a demonstrator that oversells is worse
than none:

- **The report is raw.** `render Largest` writes the stored values —
  `1795132800` rather than `2026-11-20`, `9730000` rather than `97300.00`. A
  `report` dumps the table; the page is the human view. Formatting inside a
  report is not something the language does yet.
- **No authentication.** The orders app has sessions, password hashing and
  CSRF tokens; this one deliberately does not, so the schema story is not
  buried under login code.
- **One process, one file.** `save` and `load` are TSV files with a lock
  around them. `std/postgres.sta` exists and the orders app uses it; this one
  stays on files so it runs anywhere with no setup.
- **No `group by`.** "Total by supplier" is a loop with a running tally. That
  is the largest language-level gap left.
- **It is 600 lines.** A real payables system is not. The point is not that
  this is production software; it is that the mechanism holding six tiers in
  agreement is the same mechanism at 600 lines and at 60,000, and at 600 you
  can read all of it in an afternoon.
