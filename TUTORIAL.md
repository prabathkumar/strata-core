# Your first hour with Strata

By the end of this you will have made a project, broken it on purpose, and
watched the compiler catch the break in three places at once. That last part
is the whole argument for this language existing, and it takes about ten
minutes to see for yourself.

Read [README.md](README.md) first if you want the pitch. This is the hands-on
version.

---

## 1. Install

```bash
git clone https://github.com/prabathkumar/strata-core
cd strata-core && bash tools/install.sh
```

The installer checks for a C compiler and a working Python, builds the
toolchain and puts a `strata` shim on your path. If it stops, it says which
of the two is missing rather than failing later for a confusing reason.

```bash
strata version
```

If that says `command not found`, the installer's shim is not on your path
yet. Either open a new terminal, or add it:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Everything below says `strata`. From inside a clone of this repository,
`./bin/strata` is the same program if you would rather not touch your path.

## 2. A project that runs

```bash
strata new myapp
cd myapp
strata run
```

```
items: 1
value: 9.99
```

Four files. `src/schema.sta` is the data, `src/main.sta` is the program,
`tests/items_test.sta` holds a check, `Strata.toml` says which file is the
entry point. Look at the schema:

```text
database Item {
    int   id;
    str   name;
    float price;
}
```

That is not a class and it is not an ORM mapping. It is a declaration the
compiler holds on to, and everything else in the project is checked against
it.

## 3. Break it on purpose

Open `src/schema.sta` and rename `price` to `unit_price`. Then:

```bash
strata build
```

```
E004 7:5 Column 'price' does not exist in 'Item'
  Hint: Valid columns: ['id', 'name', 'unit_price']
```

The build failed, not the program. Nobody deployed anything. Note what the
error gives you: the column you asked for, the columns that exist, and the
line. That is a machine-readable fact, not a stack trace — `strata check
src/main.sta --json` gives the same thing in a form a model can act on.

Put `price` back — or have the compiler put it back. Mistype a column in
`src/main.sta` instead, say `id` as `idd`, and then:

```bash
strata repair src/main.sta
```

```
  pass 1: 1 diagnostic(s) at stage 'typecheck'
    E004 Database Schema Selector Violation (src/main.sta:8): Column 'idd' does not exist in 'Item'
    patch applied, recompiling
[Strata Repair] clean after 1 repair(s) across 1 file(s).
```

That was `--backend rules`, the default: a deterministic fix taken from the
compiler's own hint, with no model involved and nothing sent anywhere. Most
schema mistakes are this shape, and the cheapest model is the one you never
call. For the ones that need judgement there is `--backend local`, which talks
to a model on your own machine — see the README.

## 4. The part that is not like other stacks

A rename breaking a query is useful. A rename breaking the *screen* is the
thing no shared-language stack does at build time.

```bash
cd ..
strata check examples/cross_tier_contract.sta
```

That file declares a table, queries it, and renders the result — all in one
file, all checked together:

```text
database ServiceMetric {
    int   id;
    str   service_name;
    float resource_utilization;
    str   operational_status;
}

layout OperationsConsole() {
    list[ServiceMetric] degraded = ServiceMetric <- [operational_status == "DEGRADED"];

    for Row in degraded {
        text Row.service_name;
        text str(Row.resource_utilization);
    }
}
```

Rename `service_name` in the database block and run `strata check` again. The
query fails, and so does the line of screen that rendered it. One rename, one
build, every place it mattered — including the one a human reviewer skims past
because it is forty lines further down and looks like markup.

In a C# stack the compiler checks your code against your *model*, and your
model against the *database* is a migration you hope somebody ran. Here there
is no gap to fall into.

## 5. Add something of your own

Back in `myapp`, add a column to `src/schema.sta`:

```text
database Item {
    int   id;
    str   name;
    float price;
    str   category;
}
```

```bash
strata build
```

```
[E009] Insert into 'Item' does not name every column
```

This one surprises people, and it is deliberate. An insert that skips a column
would write an empty string into every row it creates — so adding a column
used to break nothing and quietly corrupt everything. Here it is a build
failure until you say what the new column should hold.

Fix the insert in `src/main.sta`:

```text
Item <- [id = 1, name = "first", price = 9.99, category = "tools"];
```

Then query it:

```text
list[Item] tools = Item <- [category == "tools"];
print(strata_concat("tools: ", str(count(tools))));
```

```bash
strata run
strata test      # runs the verify blocks
strata fmt src/*.sta   # canonical formatting, as CI enforces it
```

## 6. Before you build anything real

Two things will bite you, and they are better read now than discovered.

**Memory is given back in one piece.** Temporaries come from an arena and
`scratch_reset()` throws the whole thing away — after a request, after a
frame, never in a batch job that just exits. Tables keep their own copies and
survive it. But the reset is placed **by hand**, and calling it while a
temporary is still in use is a use-after-free that nothing catches. If you are
writing a batch program you never need it at all.

**There are no exceptions.** A failed load leaves the table empty and records
an error. Check it with `had_error()`, read it with `last_error()`, say it is
handled with `clear_error()`. A program that reaches its exit with an error
nobody checked prints which one and exits 65 — so a silent wrong answer is not
one of the outcomes. Your own code can report a failure with `fail("...")`.

```text
load Ledger from "ledger.tsv";
if (had_error() == 1) {
    print(last_error());
    return 1;
}
```

## 7. What is not here yet

[FOR_DEVELOPERS.md](FOR_DEVELOPERS.md) is the list written for you: what
you can build, what will bite you, and what is missing. [STAGES.md](STAGES.md)
is the fuller version and it is kept current. The short
version: no package registry, no concurrency, nothing has run on a physical
phone, Postgres has no streaming, and the ecosystem is essentially this
repository. For almost anything you would start today, C# or Java is the right
answer — see the comparison in the README, which concedes every row it should.

What Strata has is one type system over the database, the rules and the
screens, and diagnostics a machine can act on. If that is worth the rest, you
are in the right place.
