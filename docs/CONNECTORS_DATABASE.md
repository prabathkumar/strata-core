# Database connectors

Two modules, and they are not the same kind of thing.

| | `std/redis.sta` | `std/mysql.sta` |
|---|---|---|
| What it is | A Redis client, complete | A MySQL/MariaDB client |
| Third-party library | **None.** RESP over a plain socket | libmariadb or libmysqlclient |
| State on this machine | Built, and tested against a live server | **Built, never run.** No client library here |
| Works with `save` / `load` | No | No — see [Where the check stops](#where-the-check-stops) |

`std/postgres.sta` is the odd one out and worth understanding first: importing
it changes what `save` and `load` *mean*, because the compiler generates the
SQL from the `database` block. Neither module here does that. They are
clients: you write the commands, they carry them safely.

---

## std/redis.sta

### What it does

GET, SET, DEL, EXISTS, INCR, EXPIRE, and LPUSH/RPOP as a queue, over an
ordinary TCP connection. `redis_call` is the door for every other command and
is the same door the named helpers use.

```text
import io    from std;
import str   from std;
import os    from std;
import redis from std;

int main() {
    int cache = redis_open(env("CACHE_URL"));   // redis://:pw@host:6379/0
    if (cache < 0) {
        print(last_error());
        clear_error();
        return 1;
    }

    redis_set_expiring(cache, "rate:acme", "1", 60);
    print(str(redis_incr(cache, "requests")));

    str who = redis_get_or(cache, "session:abc", "");
    if (str_len(who) == 0) { print("not signed in"); }

    redis_lpush(cache, "outbox", "invoice-1001");
    str job = redis_rpop(cache, "outbox");

    redis_close(cache);
    return 0;
}
```

Anything not wrapped goes through `redis_call`, which hands back the reply for
`resp_kind`, `resp_value`, `resp_integer`, `resp_count` and `resp_at` to read:

```text
str reply = redis_call(cache, ["LRANGE", "outbox", "0", "-1"]);
for (int i = 0; i < resp_count(reply); i = i + 1) {
    print(resp_value(resp_at(reply, i)));
}
```

### Every command goes as counted strings, always

Redis accepts commands typed as words on a line. Nothing here sends that form,
and there is no function that can. Every command is a RESP array in which each
argument carries its own byte count, so a key or value containing a space, a
quote or a line ending is still one argument:

```text
redis_set(cache, "k\r\nDEL everything", "v");   // one key, with CRLF in it
```

That is the Redis-shaped version of what `std/postgres.sta` does by sending
parameters instead of building a SQL string, and it is checked from the
server's side in `test_suite/connectors_database.py`.

### What it refuses

Each of these sets the error flag with a reason and gives back nothing, rather
than giving back something that looks right:

- a value with a **zero byte** in it — Strata text is a C string, and the part
  before the zero would look like a shorter value stored on purpose;
- a reply **larger than 8 MB**;
- a reply that is **not RESP at all**, which is what a port pointed at the
  wrong service sends;
- a reply whose **length does not match its own count**;
- **two replies in one buffer**, which means this client lost its place in the
  conversation;
- a number of **more than 18 digits**, rather than wrapping it around;
- an error the server sent, which arrives as that error with the server's own
  words.

### What it does not do

- **No pipelining, no pool, no MULTI/EXEC, no SUBSCRIBE.** One connection, one
  command at a time. A subscriber never stops reading, which is a different
  shape of program.
- **No TLS.** Keep it on a private network, as Redis itself says.
- **No binary values.** See the zero-byte refusal above.
- **A missing key and an empty value read the same** through `redis_get` —
  both are `""`. `redis_exists` answers the question they differ on, and
  `redis_get_or` lets you name what absent should mean. The same is true of
  `redis_rpop` on an empty queue.
- **No automatic reconnect.** A connection that drops stays dropped; the next
  call fails and says so.
- **No key namespacing, no serialisation.** A value is text you wrote.

---

## std/mysql.sta

### Read this first

**There was no MySQL or MariaDB client library on the machine this was written
on.** The branch that talks to one has never been compiled against the real
header, never linked, and never run. What *has* been exercised is the refusal
path, and the branch is compiled on every test run against a stub header
declaring the public C API — which proves it is consistent C that uses the API
as documented, and proves nothing about the real library's ABI.

Treat it as unproven code with a working front door. The first person with a
MySQL instance should run `test_suite/connectors_database.py` on a machine
with `libmariadb-dev` installed and then say what happened.

### What it does

```text
import io    from std;
import str   from std;
import mysql from std;

int main() {
    if (mysql_available() == 0) {
        print(mysql_last_reason());        // says what to install
        return 1;
    }
    int db = mysql_open("$SALES_DB");      // mysql://app:pw@host:3306/sales
    if (db < 0) { print(last_error()); clear_error(); return 1; }

    // A statement. The value goes as a parameter, never into the SQL.
    mysql_param(db, "OPEN");
    int changed = mysql_exec(db, "UPDATE orders SET status = ? WHERE id = 1");

    // A query. Columns are named, so the positions read below are the
    // positions asked for.
    mysql_param(db, "OPEN");
    int rows = mysql_query(db,
        "SELECT id, customer, amount FROM orders WHERE status = ?");
    for (int r = 0; r < rows; r = r + 1) {
        if (mysql_cell_is_null(db, r, 2) == 1) { continue; }
        print(mysql_cell(db, r, 1) + " " + mysql_cell(db, r, 2));
    }

    mysql_close_connection(db);
    return 0;
}
```

`mysql_placeholders(n)` writes the `?, ?, ?` for an insert. That is the only
part of a statement this will generate for you, because it carries no data.

### Where the check stops

This is the part worth being precise about, because the cross-tier check is
the reason to use this language at all.

A `database` block is still the single declaration of a row's shape, and it is
still checked everywhere Strata can see it:

```text
database Order { int id; str customer; float amount; }
```

Rename `amount` to `total` and every query, aggregate, report and page that
names it fails to build. That is unchanged by this module.

**Nothing crosses into the SQL.** The statement you pass to `mysql_query` is a
string. The compiler does not parse it, does not know your MySQL schema, and
cannot compare the two. Concretely:

| | Checked? | When you find out |
|---|---|---|
| A column renamed in the `database` block | **yes** | build |
| A column renamed in the SQL string | no | run time, from the server |
| A column that exists in neither | no | run time, from the server |
| The number of `?` against the values given | **yes** | run time, before the statement executes |
| A column read at the wrong position | no | never — you get the wrong column |
| A value of the wrong type | no | the server casts it, or refuses |
| MySQL's schema against the `database` block | **no, never** | — |

Contrast `std/postgres.sta`, where `save Order to "postgres://..."` has the
compiler generate the SQL *from* the declaration, so the two cannot drift.
There is no MySQL branch beside that one, and adding it is a compiler change,
not a driver change.

Two habits make the gap smaller:

1. **Name every column in a `SELECT`.** `SELECT *` makes column order the
   server's business, and `mysql_cell(db, r, 2)` then means whatever the
   server put third today.
2. **Keep a `database` block as the row's declaration anyway**, and load query
   results into it. Everything downstream is then checked again.

### The type mapping, if you create the table from a Strata schema

The same mapping the compiler uses for Postgres, spelled the MySQL way:

| Strata | MySQL column |
|---|---|
| `int` | `BIGINT` |
| `float` | `DOUBLE` |
| `str` | `TEXT` |

Nothing enforces this. It is written down so that two people creating the same
table pick the same types.

### What it does not do

- **A query is read whole into memory.** Same shape as `load`: right for
  thousands of rows, wrong for millions. No cursor, no streaming.
- **Every value comes back as text**, numbers and dates included, because every
  parameter is bound as text and every column is fetched as text. `str_to_int`
  and `float()` are how you get a number out. A SQL `NULL` is its own answer
  through `mysql_cell_is_null`, and reads as `""` through `mysql_cell`.
- **No transactions of its own.** `BEGIN` and `COMMIT` are statements you can
  run; nothing here runs them for you.
- **No pool, no reconnect**, and at most 8 open connections per process.
- **No `save` / `load` support.** `save Order to "mysql://..."` writes a file
  with a strange name.
- **A value with a zero byte is refused**, so a `BLOB` column is not readable
  through this.
- **At most 64 parameters** in one statement.

### Why it is not a `foreign` block

`foreign "mysql.h" link "mariadb" { }` is how `std/postgres.sta` reaches
libpq, and it could not be used here. The compiler emits a `foreign` header as
an unguarded `#include` and its library as an unguarded `-l`, with one
hardcoded exception for headers beginning `openssl/`
(`compiler/codegen.sta`, `gen_decl`). A module written that way does not
degrade on a machine without the MySQL client — it fails the build of every
program that imports it, and of every program that imports something that
imports it.

So the header is found with `__has_include` at build time and the symbols with
`dlopen` at run time, and nothing is added to the link line. The function
pointers are typed with `__typeof__` of the header's own declarations, so the
calls are checked against the real API rather than against prototypes written
from memory.

The cost is one unusual shape: everything that needs a MySQL type lives in a
single `native` block, dispatched by an operation code, because a block-scope
`#include` only works once per file — the second is swallowed by the header's
own include guard and its types are then missing.

The tidy fix is a compiler change, not a module change: generalise the
`openssl/` exception so that any `foreign` header can be guarded and any
library dropped from the link line when it is not installed. That is the same
pattern `openssl_is_here()` and `usable_libs()` already implement in
`compiler/build.sta`, applied to more than one library.

---

## Running the tests

```bash
strata test std/redis.sta std/mysql.sta      # the verify blocks
python3 test_suite/connectors_database.py    # live Redis, and MySQL's refusals
```

The Python suite starts a strict RESP server of its own — written from the
protocol rather than from the client, and refusing the inline command form —
so the Redis cases run with no server installed. It needs no network beyond
localhost.
