# The Strata language

What the compiler in this repository accepts, as of 15 September 2026.

Every fenced block below is compiled by `test_suite/doc_examples.py` on every
commit, so an example that stops working fails the build. The prose is held to
the same standard by hand: this file describes what the compiler does, not what
the language is for.

The previous version of this document described `stream` as an asynchronous
ingestion channel running on a fiber, `layout` as compiling straight to
WebAssembly Text, `render` as producing PDF, and `assert` as a compile-time
check. None of those were true, and the syntax it gave for `stream` did not
parse. It is the reason for the standard above.

---

## 1. Lexical rules

Statements end with `;`. Blocks are `{ }`. Parameters are `( )`. Type
parameters and query conditions are `[ ]`. Comments are `//` to end of line,
or `/* ... */`.

There is no type inference: every declaration names its type. There is no
implicit conversion between `int`, `float` and `str`.

## 2. Keywords

Reserved, and not usable as identifiers:

`int` `float` `str` `void` `bool` `list` `tensor`
`if` `else` `while` `for` `break` `continue` `return`
`def` `import` `from` `assert` `verify`
`database` `stream` `protocol` `model` `predict` `report` `render` `layout`
`true` `false`

**Contextual words** — meaningful only in one position, and ordinary
identifiers everywhere else: `save`, `load`, `delete`, `to`, `in`, `native`,
`foreign`, `link`, `title`, `datasource`, `metrics`, `input`, `output`.

## 3. Types

| Type | What it is |
|---|---|
| `int` | 64-bit signed integer |
| `float` | 64-bit IEEE 754 |
| `str` | A C string. Not length-prefixed; `+` concatenates |
| `bool` | `true` / `false`, an integer underneath |
| `list[T]` | A homogeneous array carrying its own length |
| `tensor[T, rows, cols]` | A fixed-shape numeric block, used by `model` |
| A `database` or `protocol` name | A row of that table, as a value |

## 4. Declarations

### `database`

A table. The declaration is the contract every other tier is checked against:
rename a column and the queries, the aggregates, the report and the page all
fail to build.

```text
import io from std;

database Order {
    int   id;
    str   customer;
    float amount;
}

int main() {
    Order <- [id = 1, customer = "acme", amount = 12.50];
    print(str(count(Order <- [id > 0])));
    return 0;
}
```

Rows live in memory. `save Order to "path";` and `load Order from "path";`
write and read a tab-separated file whose header names each column and its
type, so a table saved under one version of a schema loads under another: a
dropped column is skipped, a new one keeps its zero value, and a column whose
type changed is refused rather than misread. Only scalar columns are written.

### `protocol`

The same shape as `database`, for a record that is not a table — typically the
target of a `::` cast.

### `model` and `predict`

```text
import io from std;

model Classifier {
    input: tensor[float, 1, 4];
    output: tensor[float, 1, 2];
}
```

`predict Classifier(input)` runs a feed-forward network whose weights are
loaded from a file. `tensor` exists for this and is not a general numeric type.

### `report` and `render`

A report is a query plus named metrics, rendered to **Markdown**. Not PDF.

```text
import io from std;

database Sale { int id; float amount; }

report Quarterly {
    title: "Large sales",
    datasource: Sale <- [amount > 100.00],
    metrics: {
        int large = strata_len(rows);
    }
}

int main() {
    Sale <- [id = 1, amount = 120.50];
    render Quarterly to "quarterly.md";
    return 0;
}
```

`rows` is bound to the datasource inside `metrics`. The path after `to` is a
string literal; it cannot be an expression, so a program cannot choose at run
time where a report goes.

### `layout`

A layout is a function that writes **HTML** to a stream. `render Name(args)`
yields the document as a `str`, which is what lets it answer an HTTP request.
It does not compile to WebAssembly.

A layout body holds elements — `window`, `row`, `column`, `text`, `form`,
`field`, `button`, `spacer` — each with optional properties in `[ ]`.
Recognised properties become HTML attributes or CSS; anything else is emitted
as a `data-` attribute rather than dropped.

### `stream`

A named handler registered in a dispatch table at startup:

```text
import io from std;

stream OnMessage(str payload) {
    print(payload);
}

int main() { return 0; }
```

That is the whole of it. There is no scheduler, no fiber, and nothing
asynchronous.

### `foreign` and `native`

`foreign "header.h" link "name" { ... }` includes a C header and adds a linker
flag; the signatures inside it are checked like any other function. A `native`
block is C written inline as a function body, with `$name` substituted for a
parameter. The HTTP server and the password hashing in `std/` are built from
these — the web tier is library code, not a privileged part of the language.

### Functions

`int f(str a) { ... }` or `def f(str a) { ... }` for one returning nothing.
A parameter written `Type &name` is passed by reference.

## 5. Operators

### `<-` — query and insert

```text
import io from std;

database Ticket { int id; str state; }

int open_count() {
    list[Ticket] open_ones = Ticket <- [state == "OPEN"];
    return count(open_ones);
}

int main() {
    Ticket <- [id = 1, state = "OPEN"];
    print(str(open_count()));
    return 0;
}
```

A query is an expression and may appear anywhere a value may. It is a scan:
there are no joins, no ordering, no indexes and no aggregates inside the
condition. Inside the brackets a bare name is always the **column** — if a
variable of the same name is in scope, that is E008 rather than a silent
comparison of the column with itself.

An insert must name every column (E009).

`delete Ticket <- [state == "CLOSED"];` removes the matching rows.

### `::` — cast

`value :: RecordType` reinterprets a value as a record type. It is a pointer
recast, not a conversion.

### `&` — borrow

In a parameter list, pass by reference rather than by copy.

### Aggregates

`count(rows)`, and `sum`, `avg`, `min`, `max` over a projected column —
`sum(rows.amount)`. The projection is checked against the schema. `sum`, `min`
and `max` keep the column's type; `avg` is always `float`.

## 6. Statements

Variable declaration and assignment, `if` / `else`, `while`, C-style `for`,
`for Row in rows` over a list, `break`, `continue`, `return`, `assert`,
`verify` blocks, insert, `delete`, `save` / `load`, `render ... to`, and
expression statements.

`assert` is checked **at run time**, not during compilation. A `verify` block
is a test that `strata test` builds and runs:

```text
import io from std;

int twice(int x) { return x * 2; }

verify "doubling" {
    assert twice(21) == 42;
}
```

## 7. Diagnostics

Every diagnostic carries a code, a classification, a severity, a location, a
hint and a remediation strategy, and `--json` emits them as a payload for a
repair agent. The full taxonomy is `ERROR_TAXONOMY.json`.

| Code | Classification | What triggers it |
|---|---|---|
| `E001` | Variable Mutation Mismatch | A value that does not match the declared type |
| `E002` | Function Return Contract Breach | A call to an undefined function, the wrong number of arguments, or a `return` that does not match the signature |
| `E003` | Generic Collection Pollution | A list holding more than one type, or indexing something that is not a list |
| `E004` | Database Schema Selector Violation | A column or table that does not exist, in a query, an insert, a delete, an aggregate or a report |
| `E005` | Boundary Perimeter Contamination | An argument whose type does not match the declaration, including across `foreign` |
| `E006` | Tensor Dimension Drift | A `predict` whose input shape does not match the model |
| `E007` | Unresolved Module Import | An import with no local checkout. **Advisory** — it does not stop the build |
| `E008` | Ambiguous Query Identifier | A bare name in a query condition that is both a column and a variable in scope |
| `E009` | Incomplete Insert | An insert that does not name every column |

## 8. What the language does not have

Stated because their absence is load-bearing, and because earlier versions of
this document implied otherwise:

- no module-level variables or constants — a constant is a function
- no `map`, `set`, or dictionary type
- no date or time type
- no grouping or ordering in a query
- no user-defined generics, no interfaces, no inheritance
- no exceptions — errors are return values
- no garbage collector, and no `free`: `delete` unlinks a row and does not
  release it, because something else may still be holding it
- no package manager and no registry. `import ... from std` and
  `from compiler` resolve inside this repository; `from app` resolves inside
  the project being built
- no fibers, no coroutines, no async
