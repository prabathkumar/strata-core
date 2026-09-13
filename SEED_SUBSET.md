# The Seed Subset

The minimum Strata needed to write the Strata compiler.

Self-hosting fails when the language keeps growing while the compiler is being
written in it — every new feature is one more thing the Strata-written compiler
must also implement. So the subset is frozen here first, and
`bootstrap/stage0.py` is made correct for exactly this. `compiler/*.sta` may use
**nothing outside this list**.

Anything absent from this document is not available to the self-hosting
compiler, however useful it might be elsewhere.

---

## Verified working

Each line below has been compiled and run.

### Types
- `int`, `str`, `float`, `bool`, `void`
- `list[T]` with literal construction and indexed read/write
- `database` / `protocol` records, handled as references
- Records as parameters via `&` borrow

### Statements
- Declaration with initialiser — `int i = 0;`
- Assignment — `i = 5;`, `a[i] = x;`, `rec.field = x;`
- `if` / `else`
- `while`
- `for (init; cond; step)`
- `break`, `continue`
- `return`
- Expression statements, including calls

### Expressions
- Integer, float, string and bool literals
- Arithmetic `+ - * / %` with correct precedence
- Comparison `== != < > <= >=`
- Logical `&& || !`
- Function calls, including recursion
- Indexing: `a[i]` on `list[T]`, and on `str` yielding a character code
- Member access `rec.field`
- `native "..."` blocks for C escape, with `$name` substitution

### Standard library (compiles and links)
- `std/io.sta` — `print`, `print_raw`, `print_int`, `eprint`, file read/write
- `std/mem.sta` — allocation helpers
- `std/str.sta` — `StringBuilder` (`sb_new`, `sb_append`, `sb_append_line`,
  `sb_to_str`, `sb_length`)
- Compiler builtins — `str_len`, `str_slice`, `str_eq`, `str_index_of`,
  `str_starts_with`, `str_to_int`, `file_read`, `file_write`, `file_exists`

### Demonstrated adequate
- Bubble sort — nested loops, indexed read/write, swap through a temporary
- String building — the output mechanism a code generator needs
- Character scanning — `str_len` plus `s[i]` as a character code

---

## Deliberately excluded

Not needed to write a compiler, and therefore not permitted in `compiler/*.sta`:

`model` / `predict`, `report` / `render`, `layout`, `stream`, `verify`,
the `<-` query and insert operators, the `::` cast, `tensor` types, generics,
closures, and module-level variables.

A compiler needs iteration, mutation, indexing, string building and file I/O.
Everything else is language surface that the self-hosted compiler would have to
reimplement for no benefit to the bootstrap.

---

## Gaps investigated and closed

Three questions decided whether a lexer could be written at all. All three are
answered, each verified by a compiled and executed program:

| Question | Answer |
|---|---|
| Can a record be constructed? | **Yes.** A `native` constructor allocates and returns the record; records are references, so it returns a pointer. Verified: `tok_new(7, 42)` then reading `t.kind` and `t.line`. |
| Can a record field be assigned? | **Yes.** `t.kind = 99;` compiles to `t->kind = 99`. Phase 1's lvalue support covers member targets. |
| Can a collection grow? | **Yes.** `list[T]` literals are fixed-size, but a growable vector is expressible as a record holding a pointer, length and capacity, with `native` push/get doing the `realloc`. Verified: 100 pushes with one reallocation, reading back the correct element. |

This is the same shape as `StringBuilder` in `std/str.sta`, which already works.
The pattern generalises: **a growable structure is a record plus `native`
allocation.** That is sufficient for a token array, a symbol table and an AST
node arena.

**Conclusion: confirmed by building it.** `compiler/lexer.sta` is written
entirely within this subset — 419 lines, of which 27 (6%) are `native` blocks
confined to allocation primitives. It lexes the whole corpus, and its own
source, byte-identically to the Python oracle.

### Still nested, not blocking

`else if` requires `else { if ... }` nesting, and there is no `switch`. A lexer
dispatching over character classes will be verbose. This is a readability cost,
not a capability gap, and is deliberately not being fixed before Phase 3 — the
subset shrinks under pressure rather than growing.

---

## Rule

Adding anything to this document means the self-hosted compiler must implement
it too. The subset should shrink under pressure, not grow.
