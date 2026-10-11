# Changing a stored table

A design note, written before any of it is built, because this adds syntax to
the language and that is a decision rather than a fix.

## The problem, as a developer meets it

You have a table and a file full of rows:

```text
database Item { int id; str name; float price; }
```

Six weeks in, `price` should be called `cost`. You change the declaration. The
compiler does exactly what it promises — the query, the aggregate and the page
all fail to build until you fix them, which is the whole reason to use this
language. You fix them. Then you run the program:

```text
[STRATA LOAD] Item: refusing to read 'items.tsv' — it carries 'price', which
this table does not declare, and does not carry 'cost', which it does. If
'price' was renamed to 'cost', the stored file still says the old name and
every row would read as empty
```

The refusal is right. Reading that file would put empty values in a money
column. But the message tells you what is wrong and nothing about what to do,
and there is nothing you *can* do: one program cannot declare two versions of
the same table, so you cannot load the old shape and save the new one. The
only route is to open the file and edit its header by hand.

An eleventh pilot called this the thing that would stop their team adopting
Strata — not data loss, which the compiler now prevents, but the absence of
any supported way to change a table that already has data in it.

## What already works, and what does not

| Change | Reading an old file | Why |
|---|---|---|
| A column added | works | absent from the header, zero-filled |
| A column dropped | reads; a write is refused | the data would be deleted |
| Columns reordered | works | matched by name |
| **A column renamed** | **refused** | every row would read as empty |
| **A column's type changed** | **refused** | the stored values are the other type |
| A table renamed | refused | the header names the old table |

The three refusals are correct and must stay. What is missing is a way to say
"yes, I meant that" in a form the compiler can check.

## The shape proposed

A migration lives in the source, next to the schema it belongs to, and is
checked against it:

```text
database Item {
    int   id;
    str   name;
    float cost;
}

migrate Item {
    rename price to cost;
    retype quantity to float;
}
```

Reading a file whose header does not match the declaration, the loader
consults the migration: a column named `price` in the file is the column named
`cost` in the schema, and a `quantity` stored as a whole number is read as a
decimal. The load succeeds, and the next `save` writes the new shape. One run
migrates the file.

### Why in the language rather than a `strata migrate` command

A command-line migration is a thing somebody typed once, on one machine, that
is not in the repository, that nobody reviewed, and that the compiler cannot
check. `strata migrate items.tsv --rename price=cost` would be three ways to
get it wrong before breakfast: a column that does not exist, a direction
reversed, a file migrated twice.

Declared in the source it is the opposite of all of that. `rename price to
cost` is checked — `cost` must be a column of `Item`, and `price` must NOT be,
or the migration contradicts the schema. It is in the diff, so a reviewer sees
the rename and its migration in one change. It runs on every machine and in
CI, not just on the laptop of whoever remembered.

And it completes an existing refusal rather than working around it. A drop and
an add together are refused today precisely because, from the file's side,
that is what a rename looks like. The migration is the one thing that can tell
the compiler which of the two it is.

### What it must not become

Not a general transformation language. No expressions, no conditionals, no
computing one column from two others. The moment a migration can run
arbitrary code it is a program that silently rewrites stored data, which is
the thing this whole part of the compiler exists to prevent.

The proposed vocabulary is four statements and nothing else:

```text
rename <old> to <new>;        a column that changed its name
retype <column> to <type>;    a widening only: int to float
rename table <Old> to <New>;  a table that changed its name
drop <column>;                deliberately discarding a column's data
```

`drop` is there because dropping a column from the schema is currently a trap:
reading is fine, and the next write is refused to protect the data. Saying
`drop note;` is how you confirm you meant it.

`retype` is a widening only. Reading a decimal back as a whole number loses
the part after the point, and no declaration should be able to make that
happen quietly.

### Open questions, for a person to answer

1. **When is a migration spent?** Once every file has been rewritten in the
   new shape, the migration is dead code that still has to be carried. Does it
   stay forever, or is there a point at which the compiler says "no file this
   project reads still has the old shape, delete this"? Carrying them forever
   is how a schema file becomes a changelog nobody reads.
2. **Does a migration have a version?** Two renames of the same column across
   two releases need an order. A list of statements has one; a set does not.
3. **Should it apply on read only, or also convert the file in place?**
   Reading and then saving migrates the file as a side effect of the program
   doing its normal work, which is quiet. A `strata migrate` command that only
   *applies the declared migration* — no arguments, nothing to get wrong — may
   be worth having so the conversion is a thing somebody did on purpose.
4. **What does the type checker do with a migration that no longer makes
   sense** — a rename whose new column has since been deleted? Refusing the
   build is consistent with everything else here and will annoy somebody.

## What is built

`rename`, `drop` and `retype` are built, checked against the schema, and
tested across `load`, `scan` and `rewrite`. Renaming a table is not.

Of the four open questions above, three now have answers in the code rather
than in this note: statements apply in the order they are written; a migration
applies on read, and the next save writes the new shape; and a migration that
no longer makes sense does not compile. The first question — when a migration
is spent — is still open, and a file that carries both the old and the new
column name is refused precisely because nobody can tell from the file which
of the two it is.

## The size of it

Both compilers, as always: a keyword and a declaration in the parser, a check
that the migration agrees with the schema, header-matching in the generated
loader, and the same again in the self-hosted compiler so the two stay
byte-identical. Plus the test matrix — every schema change, with and without a
migration declared, across `load`, `scan` and `rewrite`.

It is the largest single piece of work left before Beta, and it is the one a
team notices the absence of in their first month.
