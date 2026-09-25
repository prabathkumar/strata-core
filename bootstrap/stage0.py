#!/usr/bin/env python3
# STRATA — STAGE 0 BOOTSTRAP COMPILER
# Compiles .sta source files to C via Python bootstrap
# Once compiler/compiler.sta compiles itself, this file is retired.
from __future__ import annotations
import sys, os, re, json, platform, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from compiler.lexer import Lexer, Token, TT, LexError, tokenise_file
from compiler.parser import (
    Parser, ParseError, CompilationUnit,
    DatabaseDecl, ProtocolDecl, ModelDecl, ReportDecl,
    FunctionDecl, ImportDecl, FieldDecl, Param, InsertStmt, DeleteStmt, ConstDecl,
    LayoutDecl, Element, Prop, ForInStmt, ForeignDecl, TableIOStmt,
    VarDecl, ReturnStmt, IfStmt, PrintStmt, ExprStmt, RenderStmt, VerifyBlock,
    AssignStmt, WhileStmt, ForStmt, BreakStmt, ContinueStmt, IndexExpr, ScanStmt, AppendStmt, RewriteStmt, DropStmt,
    AssertStmt, RenderStmt, VerifyBlock,
    BinaryExpr, UnaryExpr, CallExpr, BorrowExpr, CastExpr,
    PredictExpr, QueryExpr, ListLiteral, MemberAccess, RenderExpr,
    IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, Identifier,
    PrimitiveType, ListType, TensorType,
)

def _load_preamble(name="runtime_preamble.c"):
    """The C runtime prelude, shared with the Strata-written code generator.

    Kept in compiler/runtime_preamble.c rather than inline so that both
    implementations emit identical bytes by construction. Two copies of 76
    lines of C would drift, and the codegen differential would then fail for a
    reason that has nothing to do with code generation.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "compiler", name)
    with open(path) as f:
        return f.read()


C_PREAMBLE = _load_preamble()

# A freestanding WebAssembly build has no libc, so it uses its own prelude.
# Both are read from disk rather than inlined, for the same reason: one source
# of truth, shared with the Strata-written generator.
WASM_PREAMBLE = _load_preamble("runtime_preamble_wasm.c")

# Functions already defined by C_PREAMBLE; an imported module redefining one
# of these would be a duplicate symbol, so they are never re-emitted.
PREAMBLE_BUILTINS = frozenset(('file_exists', 'file_read', 'file_write', 'float_to_str', 'int_to_str', 'sb_append_f', 'sb_append_line_f', 'sb_new_f', 'str_concat', 'str_eq', 'str_index_of', 'str_len', 'str_slice', 'str_starts_with', 'str_to_int', 'strata_concat', 'strata_float_to_str', 'strata_int_to_str'))

# Identifiers that are legal in Strata but reserved in C. A Strata program is
# not required to know what C reserves, so any collision is mangled on the way
# out. Without this, a function named `register` or a variable named `class`
# emits code the backend compiler rejects with a syntax error pointing at
# generated source the user never wrote.
C_RESERVED = frozenset("""
auto break case char const continue default do double else enum extern float
for goto if inline int long register restrict return short signed sizeof static
struct switch typedef union unsigned void volatile while
_Bool _Complex _Imaginary bool complex imaginary
""".split())


# Return types of the prelude's own functions. Without these, a conversion
# such as str(strata_tensor_get(t, 0)) cannot tell a float from an int and
# routes it through the integer converter, silently truncating 6.5 to 6.
BUILTIN_RETURNS = {
    "strata_concat": "strata_str", "strata_int_to_str": "strata_str",
    "strata_float_to_str": "strata_str", "str_concat": "strata_str",
    "int_to_str": "strata_str", "float_to_str": "strata_str",
    "str_slice": "strata_str", "file_read": "strata_str",
    "str_len": "strata_int", "str_eq": "strata_int", "str_to_int": "strata_int",
    "str_index_of": "strata_int", "str_starts_with": "strata_int",
    "file_write": "strata_int", "file_exists": "strata_int",
    "strata_len": "strata_int", "strata_model_load": "strata_int",
    "current_message": "strata_str",
    "strata_publish": "strata_int", "strata_run": "strata_int",
    "strata_tensor": "double*", "strata_predict": "double*",
    "strata_tensor_add": "double*",
    "strata_tensor_get": "strata_float", "strata_tensor_set": "void",
}


def _verify_symbol(label):
    """A C identifier derived from a verify block's label."""
    return "".join(c if c.isalnum() else "_" for c in label)[:48]


def _assert_text(node):
    """Short source-like rendering of an assertion, for the failure line."""
    if isinstance(node, BinaryExpr):
        return f"{_assert_text(node.left)} {node.op} {_assert_text(node.right)}"
    if isinstance(node, Identifier):
        return node.name
    if isinstance(node, IntLiteral):
        return str(node.value)
    if isinstance(node, StrLiteral):
        return f"'{node.value}'"
    if isinstance(node, CallExpr):
        return f"{node.callee}(...)"
    if isinstance(node, MemberAccess):
        return f"{_assert_text(node.obj)}.{node.member}"
    return "<expr>"


def _c_string(value):
    """A Strata string literal as a C string literal.

    The lexer decodes escapes, so by here `\\r` is a real carriage return.
    Re-escaping only backslash, quote and newline left tabs and carriage
    returns raw in the emitted C: a raw tab happens to be legal inside a C
    literal, and a raw CR ends the line, so `"\\r\\n"` failed to compile with
    "missing terminating \" character" pointing at generated code the author
    never wrote.
    """
    out = []
    for ch in value:
        if ch == "\\":  out.append("\\\\")
        elif ch == '"':  out.append('\\"')
        elif ch == "\n": out.append("\\n")
        elif ch == "\r": out.append("\\r")
        elif ch == "\t": out.append("\\t")
        else:            out.append(ch)
    return '"' + "".join(out) + '"'


def cname(name):
    """A C-safe spelling of a Strata identifier."""
    return name + "_" if name in C_RESERVED else name


# Native block variable substitution
def subst_native(code: str, param_names: list) -> str:
    """Replace $varname with the C variable name in native blocks."""
    # Replace $varname with varname
    result = re.sub(r'\$([a-zA-Z_][a-zA-Z0-9_]*)', lambda m: m.group(1), code)
    return result

class StrataCodegenError(Exception):
    """A statement the generator has no rule for.

    Raised rather than ignored: an unhandled statement used to be emitted as
    nothing, so a program could compile, link, run and quietly skip a loop.
    """


class CodeGen:
    def __init__(self, ast, source_path, modules=None, target="native",
                 test_mode=False):
        self.target = target
        # In test mode the entry point runs verify blocks instead of main().
        self.test_mode = test_mode
        # name -> C type for every `const` in the unit.
        self.const_types = {}
        # Whether code is being generated for a layout body, where a
        # statement may be an element, or for a function body, where it may
        # not. `for X in xs` is the one construct that appears in both.
        self.in_layout = False
        self.verify_blocks = []
        self.ast = ast
        self.source_path = source_path
        self.modules = modules or []
        self.out = []
        self.indent = 0
        self.schemas = {}
        self.func_returns = {}
        # Constants are file-scope, so they survive the reset that happens
        # at the start of each function and layout.
        self.var_types = dict(self.const_types)
        self.native_blocks = []  # collect native blocks
        # database/protocol/model names. Records are always handled by
        # reference in C, so these map to 'T*' rather than 'T'.
        self.record_types = set()
        self.model_names = set()
        # Parameters declared `T &x` where T is not already a pointer. They
        # arrive as T*, so every use must dereference; without this a write
        # through a borrowed scalar performs pointer arithmetic instead, and
        # is silently wrong.
        self.borrowed_scalars = set()
        self.symbol_owner = {}
        # Set while generating a query condition: a bare identifier naming a
        # column of this table resolves to the row under test.
        self.query_row_type = None
        # True while a layout is being generated as a drawn screen rather than
        # as HTML, so the shared loop generator knows where to send the body.
        self.in_draw = False
        self.query_depth = 0
        # Database fields by table name, for report rendering.
        self.schema_fields = {}
        self.rewrite_depth = 0
        # Libraries named by foreign blocks, passed to the linker.
        self.link_libs = []

    def emit(self, line=""):
        self.out.append("    " * self.indent + line)

    def emit_raw(self, line):
        self.out.append(line)

    def generate(self):
        self.emit_raw(WASM_PREAMBLE if self.target == "wasm" else C_PREAMBLE)

        # Imported modules first, in dependency order. Names already provided by
        # the C preamble or by an earlier module are skipped so that a symbol
        # imported down two paths is emitted exactly once.
        emitted_decls, emitted_fns = set(), set(PREAMBLE_BUILTINS)
        units = [(name, m) for name, m in self.modules] + [(None, self.ast)]

        for _, unit in units:
            for d in unit.declarations:
                if isinstance(d, (DatabaseDecl, ProtocolDecl)):
                    self.record_types.add(d.name)
                if isinstance(d, DatabaseDecl):
                    self.schemas[d.name] = [f.name for f in d.fields]
                    self.schema_fields[d.name] = d.fields
                elif isinstance(d, ModelDecl):
                    self.model_names.add(d.name)

        for mod_name, unit in units:
            is_root = unit is self.ast
            # Dedup is by name, for the diamond case — one module reached by
            # two import paths. A `foreign` block has no name, so keying it as
            # None made the first one mark every later nameless declaration as
            # already emitted: a `link` in an imported module was dropped and
            # the program failed at the linker.
            decls = [d for d in unit.declarations
                     if getattr(d, "name", None) is None
                     or getattr(d, "name") not in emitted_decls]
            fns = [f for f in unit.functions if f.name not in emitted_fns]
            if not is_root and (decls or fns):
                self.emit_raw(f"\n/* ── module {mod_name} ── */")
            for d in decls:
                if getattr(d, "name", None) is not None:
                    emitted_decls.add(d.name)
                self._forward_declare(d)
            # Constants first, whatever order they were written in. A layout
            # or report declared above a constant would otherwise not see it,
            # and "it depends where you put it in the file" is not a rule
            # anyone should have to learn.
            for d in decls:
                if isinstance(d, ConstDecl):
                    self._gen_decl(d)
            for d in decls:
                if not isinstance(d, ConstDecl):
                    self._gen_decl(d)
            for fn in fns:
                # Strata has no namespaces, so two modules defining the same
                # function name collide. Dedup exists for the diamond case —
                # one module reached by two import paths — and must not
                # silently discard a genuinely different definition.
                owner = self.symbol_owner.get(fn.name)
                if owner is not None and owner != mod_name:
                    print(f"[STRATA LINK ERROR] '{fn.name}' is defined by both "
                          f"'{owner}' and '{mod_name}'. Strata has no namespaces; "
                          f"rename one.", file=sys.stderr)
                    sys.exit(1)
                self.symbol_owner[fn.name] = mod_name
                emitted_fns.add(fn.name)
                self._forward_fn(fn)
            for fn in fns:
                self._gen_function(fn)

        # Verify blocks come last: they call functions, and emitting them with
        # the declarations would make those calls implicit declarations that
        # conflict with the real definitions.
        for _, unit in units:
            for d in unit.declarations:
                if isinstance(d, VerifyBlock):
                    self.verify_blocks.append(d)
                    self._gen_verify(d)

        # A module with no main() is a library unit: emitting the C entry point
        # would force an undefined reference to strata_main.
        self._gen_stream_registry()

        if self.test_mode:
            self._gen_test_main()
        elif self.target != "wasm" and any(fn.name == "main" for fn in self.ast.functions):
            self.emit_raw("""
int main(int argc, char** argv) {
    __strata_argc = argc;
    __strata_argv = argv;
    __strata_register_streams();
    return (int)strata_main();
}
""")
        # Replace strata main declaration
        result = "\n".join(self.out)
        result = result.replace(
            "\nstrata_int main(void);",
            "\nstrata_int strata_main(void);"
        ).replace(
            "\nstrata_int main(void) {",
            "\nstrata_int strata_main(void) {"
        ).replace(
            "\nvoid main(void);",
            "\nvoid strata_main(void);"
        )
        return result

    def _forward_declare(self, decl):
        if isinstance(decl, (DatabaseDecl, ProtocolDecl)):
            self.emit_raw(f"typedef struct {decl.name} {decl.name};")

    def _forward_fn(self, fn):
        rt = self._c_type(fn.return_type) if fn.return_type else "void"
        if fn.kind == "def": rt = "void"
        params = ", ".join(self._c_param(p) for p in fn.params) if fn.params else "void"
        self.emit_raw(f"{rt} {cname(fn.name)}({params});")

    def _gen_decl(self, decl):
        if isinstance(decl, ConstDecl):
            # A file-scope `static const`, emitted with the declarations so it
            # is in scope for every function below it. The type comes from the
            # declaration rather than from the value, so `const float RATE = 1;`
            # is a float.
            ct = self._c_type(decl.const_type)
            self.const_types[decl.name] = ct
            self.var_types[decl.name] = ct
            value = self._gen_expr(decl.value, [])
            qualifier = "static const " if ct != "strata_str" else "static "
            self.emit_raw(f"{qualifier}{ct} {cname(decl.name)} = {value};")
            return
        if isinstance(decl, DatabaseDecl):
            self._gen_struct(decl.name, decl.fields)
            self.schemas[decl.name] = [f.name for f in decl.fields]
            self.schema_fields[decl.name] = decl.fields
            self._gen_table_storage(decl.name)
            self._gen_table_io(decl.name, decl.fields)
            self._gen_table_scan(decl.name, decl.fields)
            self._gen_table_append(decl.name, decl.fields)
            self._gen_table_write_row(decl.name, decl.fields)
        elif isinstance(decl, ProtocolDecl):
            self._gen_struct(decl.name, decl.fields)
        elif isinstance(decl, ModelDecl):
            self._gen_model(decl)
        elif isinstance(decl, ReportDecl):
            self._gen_report(decl)
        elif isinstance(decl, LayoutDecl):
            self._gen_layout(decl)
        elif isinstance(decl, ForeignDecl):
            self._gen_foreign(decl)


    def _sql_where(self, expr, schema):
        """A query condition as SQL, or None when it cannot be expressed.

        Only the shapes that mean the same thing in both places are
        translated: comparisons between a column and a literal, and `&&`/`||`
        joining them. Anything else -- a function call, a parameter, arithmetic
        -- returns None, and the caller loads the table and filters in memory
        exactly as before. A wrong WHERE clause would silently return the wrong
        rows, so the rule is translate what is certain and decline the rest.
        """
        cols = self.schemas.get(schema, [])

        def go(e):
            if isinstance(e, BinaryExpr):
                if e.op in ("&&", "||"):
                    l, r = go(e.left), go(e.right)
                    if l is None or r is None:
                        return None
                    return f"({l} {'AND' if e.op == '&&' else 'OR'} {r})"
                if e.op in ("==", "!=", "<", ">", "<=", ">="):
                    col = lit = None
                    for a, b in ((e.left, e.right), (e.right, e.left)):
                        if isinstance(a, Identifier) and a.name in cols:
                            col, lit = a, b
                            break
                    if col is None:
                        return None
                    flip = col is e.right
                    v = self._sql_literal(lit)
                    if v is None:
                        return None
                    op = {"==": "=", "!=": "<>"}.get(e.op, e.op)
                    if flip:
                        op = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}.get(op, op)
                    return f'(\\"{col.name}\\" {op} {v})'
            return None

        return go(expr)

    def _sql_literal(self, e):
        """A literal as SQL, or None if it is not a literal.

        Strings are escaped by doubling the quote, which is the whole of SQL
        string escaping -- and this only ever sees a literal from the program's
        own source, never anything a user typed."""
        if isinstance(e, IntLiteral):
            return str(e.value)
        # Floats are deliberately not translated. This generator holds the
        # parsed number and the one written in Strata holds the text it was
        # written as, and there is no representation both are guaranteed to
        # print identically -- `1.50` and `1.5` are the same number and
        # different strings. A float comparison falls back to loading the
        # table and filtering in memory, which is the same answer.
        if isinstance(e, StrLiteral):
            return "'" + str(e.value).replace("'", "''") + "'"
        return None

    def _gen_table_push(self, name, indent):
        """Append a row, growing the table if it is full.

        This used to be `if (count < CAP) rows[count++] = r;` -- a row past
        the end was dropped without a word."""
        self.emit_raw(f"{indent}if (!strata_table_room((void***)&{name}__rows, "
                      f"&{name}__cap, {name}__count + 1)) "
                      f'strata_table_full("{name}");')
        self.emit_raw(f"{indent}{name}__rows[{name}__count++] = r;")

    def _gen_table_storage(self, name):
        """Backing store for a database block.

        Emitted after the struct so the row type is complete."""
        self.emit_raw(f"static {name}** {name}__rows = NULL;")
        self.emit_raw(f"static strata_int {name}__count = 0;")
        self.emit_raw(f"static strata_int {name}__cap = 0;")
        # Which file this table was last read from, and that file's identity at
        # the time. `load` uses them to skip work it has already done.
        self.emit_raw(f"static char* {name}__from = NULL;")
        self.emit_raw(f"static int64_t {name}__stamp = 0;")
        # What the Postgres store held when this process last read or wrote
        # it, and scratch space for what it holds now. Declared for every
        # table and used only under STRATA_POSTGRES, because a type that is
        # never mentioned costs nothing.
        self.emit_raw("#ifdef STRATA_POSTGRES")
        self.emit_raw(f"static StrataPgSnap {name}__pg_was = {{0}};")
        self.emit_raw(f"static StrataPgSnap {name}__pg_now = {{0}};")
        self.emit_raw("#endif")

    def _gen_table_io(self, name, fields):
        """Serialisers generated from the schema.

        The file carries a header naming each column and its type, so a table
        saved by one version of a schema loads under another: a dropped column
        is skipped, a new one keeps its zero value, and a column whose type
        changed is refused rather than misread. Field order is no longer the
        contract — the names are.
        """
        def tchar(fd):
            ct = self._c_type(fd.field_type)
            return "s" if ct == "strata_str" else ("f" if ct == "strata_float" else "i")

        # Only scalar columns are written and read. A column whose type is a
        # record is a pointer into this process, and a pointer means nothing in
        # a file — the loader used to emit `r->field = (strata_int)atoll(buf);`
        # for one, which is an int assigned to a pointer. gcc 11 warns; clang
        # and gcc 14 reject it, so the compiler built on one machine and not on
        # another. `database P { TokVec toks; ... }` in the parser is such a
        # table, and it is never saved — the invalid C was generated anyway,
        # because save and load are emitted for every table.
        SCALARS = ("strata_int", "strata_float", "strata_str")
        fields = [fd for fd in fields if self._c_type(fd.field_type) in SCALARS]

        def sqltype(fd):
            ct = self._c_type(fd.field_type)
            return ("TEXT" if ct == "strata_str"
                    else "DOUBLE PRECISION" if ct == "strata_float" else "BIGINT")

        n = len(fields)
        # The first column is the table's key when it is an integer. That is
        # the convention every `database` block in this repository already
        # follows (`int id;` first), and it is what an upsert conflicts on and
        # what a delete matches. A table whose first column is not an integer
        # keeps the whole-table replace it had before, rather than the
        # compiler guessing at a key.
        key = (fields[0].name
               if fields and self._c_type(fields[0].field_type) == "strata_int"
               else None)
        cols_sql = ", ".join(
            [f'\\"{fd.name}\\" {sqltype(fd)}'
             + (" PRIMARY KEY" if key and fd.name == key else "")
             for fd in fields])
        col_list = ", ".join([f'\\"{fd.name}\\"' for fd in fields])
        placeholders = ", ".join([f"${i + 1}" for i in range(n)])
        select_sql = f'SELECT {col_list} FROM \\"{name}\\"'
        insert_sql = f'INSERT INTO \\"{name}\\" ({col_list}) VALUES ({placeholders})'
        if key:
            sets = ", ".join([f'\\"{fd.name}\\" = EXCLUDED.\\"{fd.name}\\"'
                              for fd in fields if fd.name != key])
            upsert_sql = (insert_sql + f' ON CONFLICT (\\"{key}\\") DO UPDATE SET {sets}'
                          if sets else
                          insert_sql + f' ON CONFLICT (\\"{key}\\") DO NOTHING')
        else:
            upsert_sql = insert_sql
        delete_sql = f'DELETE FROM \\"{name}\\" WHERE \\"{key}\\" = $1' if key else ''

        header = "\\t".join([f"{fd.name}:{tchar(fd)}" for fd in fields])
        self.emit_raw(f"static strata_int {name}__save(strata_str path) {{")
        self.emit_raw("    path = (strata_str)strata_env_path(path);")
        self.emit_raw('    if (!path || !*path) { return 0; }')
        self._gen_pg_save(name, fields, cols_sql, upsert_sql, delete_sql, key, n)
        self.emit_raw(f'    FILE* f = fopen(path, "w"); if (!f) return 0;')
        self.emit_raw(f'    fprintf(f, "#strata\\t{name}\\t{header}\\n");')
        self.emit_raw(f"    for (strata_int i = 0; i < {name}__count; i++) {{")
        self.emit_raw(f"        {name}* r = {name}__rows[i];")
        for i, fd in enumerate(fields):
            ct = self._c_type(fd.field_type)
            if i:
                self.emit_raw("        fputc(0x09, f);")
            if ct == "strata_str":
                self.emit_raw(f"        strata_write_escaped(f, r->{fd.name});")
            elif ct == "strata_float":
                self.emit_raw(f'        fprintf(f, "%.17g", r->{fd.name});')
            else:
                self.emit_raw(f'        fprintf(f, "%lld", (long long)r->{fd.name});')
        self.emit_raw('        fputc(0x0a, f);')
        self.emit_raw("    }")
        self.emit_raw("    fclose(f);")
        # A writer has the rows it just wrote; reloading them would be work
        # to arrive back where it started.
        self.emit_raw(f"    free({name}__from);")
        self.emit_raw(f"    {name}__from = strata_dup(path);")
        self.emit_raw(f"    {name}__stamp = strata_file_stamp(path);")
        self.emit_raw("    return 1;")
        self.emit_raw("}")

        self.emit_raw(f"static strata_int {name}__load(strata_str path, "
                      f"strata_str _where) {{")
        self.emit_raw("    path = (strata_str)strata_env_path(path);")
        self.emit_raw('    if (!path || !*path) { return 0; }')
        # Already loaded, from the same file, and the file has not changed
        # since: there is nothing to do. A service that forks per request
        # inherits the parent's tables, so this turns the reload on every
        # request into a stat() — including on the requests that never touch
        # the table.
        self.emit_raw(f"    int64_t _stamp = strata_file_stamp(path);")
        # A filtered load asks for a different set of rows, so the table it
        # already holds is not the answer even when the file has not changed.
        self.emit_raw(f"    if ((!_where || !*_where) && _stamp != 0 "
                      f"&& _stamp == {name}__stamp")
        self.emit_raw(f"        && {name}__from && strcmp({name}__from, path) == 0) {{")
        self.emit_raw(f"        return 1;")
        self.emit_raw(f"    }}")
        self._gen_pg_load(name, fields, select_sql, key)
        self.emit_raw(f'    FILE* f = fopen(path, "r"); if (!f) return 0;')
        self.emit_raw("    char buf[4096];")
        self.emit_raw("    char _names[STRATA_MAX_COLS][STRATA_NAME_CAP];")
        self.emit_raw("    char _types[STRATA_MAX_COLS];")
        self.emit_raw("    int _map[STRATA_MAX_COLS];")
        self.emit_raw("    char _table[STRATA_NAME_CAP];")
        self.emit_raw("    int _ncol = strata_read_header(f, _names, _types, "
                      "STRATA_MAX_COLS, _table);")
        self.emit_raw(f"    if (_ncol == -2) {{ fclose(f); {name}__count = 0; return 1; }}")
        self.emit_raw("    if (_ncol == -1) {")
        self.emit_raw(f'        strata_load_refuse("{name}", path, "no schema header; '
                      f'it was written before headers existed. Re-save it.");')
        self.emit_raw("        fclose(f); return 0;")
        self.emit_raw("    }")
        # The header names the table it was written from. A file belonging
        # to a different table has the wrong shape and the wrong meaning, and
        # reading it positionally produced rows of plausible nonsense.
        self.emit_raw(f'    if (_table[0] && strcmp(_table, "{name}") != 0) {{')
        self.emit_raw("        char _why[192];")
        self.emit_raw('        snprintf(_why, sizeof(_why), "it was saved from '
                      '\'%s\', not this table", _table);')
        self.emit_raw(f'        strata_load_refuse("{name}", path, _why);')
        self.emit_raw("        fclose(f); return 0;")
        self.emit_raw("    }")
        self.emit_raw("    int _matched = 0;")
        self.emit_raw("    for (int _c = 0; _c < _ncol; _c++) {")
        self.emit_raw("        _map[_c] = -1;")
        for idx, fd in enumerate(fields):
            self.emit_raw(f'        if (strcmp(_names[_c], "{fd.name}") == 0) {{')
            self.emit_raw(f"            if (_types[_c] != '{tchar(fd)}') {{")
            self.emit_raw(f'                strata_load_refuse("{name}", path, '
                          f'"column \'{fd.name}\' changed type since it was saved");')
            self.emit_raw("                fclose(f); return 0;")
            self.emit_raw("            }")
            self.emit_raw(f"            _map[_c] = {idx};")
            self.emit_raw("        }")
        self.emit_raw("        if (_map[_c] >= 0) _matched++;")
        self.emit_raw("    }")
        # A column the file carries and this table does not is a DROPPED
        # column, which is supported: it is skipped and the rest loads. But a
        # file where NOTHING matches is not this table's file at all, and
        # reading it left every field at its default -- a row of zeroes
        # arriving as though it were data.
        self.emit_raw("    if (_ncol > 0 && _matched == 0) {")
        self.emit_raw(f'        strata_load_refuse("{name}", path, "none of its '
                      f'columns are in this table");')
        self.emit_raw("        fclose(f); return 0;")
        self.emit_raw("    }")
        self.emit_raw(f"    {name}__count = 0;")
        self.emit_raw("    while (1) {")
        self.emit_raw(f"        {name}* r = ({name}*)calloc(1, sizeof({name}));")
        # A column the file does not carry keeps its zero value; for a str that
        # is "" rather than NULL, so a new column cannot crash a printf.
        for fd in fields:
            if self._c_type(fd.field_type) == "strata_str":
                self.emit_raw(f'        r->{fd.name} = "";')
        self.emit_raw("        int _more = 0, _eof = 0;")
        self.emit_raw("        for (int _c = 0; _c < _ncol; _c++) {")
        self.emit_raw("            _more = strata_read_field(f, buf, 4096);")
        self.emit_raw("            if (_more < 0) { _eof = 1; break; }")
        self.emit_raw("            switch (_map[_c]) {")
        for idx, fd in enumerate(fields):
            ct = self._c_type(fd.field_type)
            if ct == "strata_str":
                conv = f"r->{fd.name} = strata_dup(buf);"
            elif ct == "strata_float":
                conv = (f"{{ strata_float _v; if (!strata_parse_float(buf, &_v)) {{ "
                        f'strata_load_bad_value("{name}", path, "{fd.name}", '
                        f"buf, {name}__count + 1); free(r); fclose(f); "
                        f"{name}__count = 0; return 0; }} r->{fd.name} = ({ct})_v; }}")
            else:
                # A number that is not a number stops the load rather than
                # becoming zero. atoll answers 0 for "notanint", so a corrupted
                # digit in a stored file used to arrive as a silent zero -- in a
                # money column, a balance quietly wrong instead of a load that
                # failed. The temporary is because a column's C type is not
                # always exactly strata_int, and taking its address is stricter
                # than the cast this replaced.
                conv = (f"{{ strata_int _v; if (!strata_parse_int(buf, &_v)) {{ "
                        f'strata_load_bad_value("{name}", path, "{fd.name}", '
                        f"buf, {name}__count + 1); free(r); fclose(f); "
                        f"{name}__count = 0; return 0; }} r->{fd.name} = ({ct})_v; }}")
            self.emit_raw(f"                case {idx}: {conv} break;")
        self.emit_raw("                default: break;   /* a column this "
                      "schema no longer has */")
        self.emit_raw("            }")
        self.emit_raw("        }")
        self.emit_raw("        if (_eof) { free(r); break; }")
        self._gen_table_push(name, "        ")
        self.emit_raw("    }")
        self.emit_raw("    fclose(f);")
        self.emit_raw(f"    free({name}__from);")
        self.emit_raw(f"    {name}__from = strata_dup(path);")
        self.emit_raw(f"    {name}__stamp = strata_file_stamp(path);")
        self.emit_raw("    return 1;")
        self.emit_raw("}")

    def _gen_table_append(self, name, fields):
        """Writing a stored table one row at a time.

        `save` writes the table in memory, so what a program can PRODUCE was
        bounded the way what it could read used to be. An append writes one
        row and keeps nothing: the handle stays open between rows, so a job
        can emit a file larger than memory the way a scan reads one.

        The header is written only when the file is new or empty, and it is
        the same header `save` writes -- a file this produces is one `scan`
        and `load` accept, with the same table name and the same column types.
        """
        header = "\\t".join(
            f"{fd.name}:{'s' if self._c_type(fd.field_type) == 'strata_str' else ('f' if self._c_type(fd.field_type) == 'strata_float' else 'i')}"
            for fd in fields)
        self.emit_raw(f"static FILE* {name}__append_file = NULL;")
        self.emit_raw(f"static char* {name}__append_path = NULL;")
        self.emit_raw(f"static void {name}__append_close(void) {{")
        self.emit_raw(f"    if ({name}__append_file) {{ fclose({name}__append_file); "
                      f"{name}__append_file = NULL; }}")
        self.emit_raw("}")
        self.emit_raw(f"static FILE* {name}__append_open(const char* path) {{")
        # The common case: the same file as the row before, already open.
        self.emit_raw(f"    if ({name}__append_file && {name}__append_path "
                      f"&& strcmp({name}__append_path, path) == 0)")
        self.emit_raw(f"        return {name}__append_file;")
        self.emit_raw(f"    if ({name}__append_file) {{ fclose({name}__append_file); "
                      f"{name}__append_file = NULL; }}")
        self.emit_raw(f"    free({name}__append_path); {name}__append_path = NULL;")
        # A header belongs at the top of a new file and nowhere else, so an
        # appended-to file does not grow a header in the middle of itself.
        self.emit_raw("    int fresh = 1;")
        self.emit_raw('    FILE* probe = fopen(path, "r");')
        self.emit_raw("    if (probe) { if (fgetc(probe) != EOF) fresh = 0; fclose(probe); }")
        self.emit_raw('    FILE* f = fopen(path, "a");')
        self.emit_raw("    if (!f) {")
        self.emit_raw(f'        fprintf(stderr, "[STRATA APPEND] {name}: cannot write '
                      f'\'%s\'\\n", path);')
        self.emit_raw("        return NULL;")
        self.emit_raw("    }")
        self.emit_raw(f'    if (fresh) fprintf(f, "#strata\\t{name}\\t{header}\\n");')
        self.emit_raw("    static int registered = 0;")
        self.emit_raw(f"    if (!registered) {{ atexit({name}__append_close); registered = 1; }}")
        self.emit_raw(f"    {name}__append_file = f;")
        self.emit_raw(f"    {name}__append_path = strata_dup(path);")
        self.emit_raw("    return f;")
        self.emit_raw("}")

    def _gen_table_write_row(self, name, fields):
        """One row of this table, written the way `save` writes one.

        A rewrite has a whole row in hand rather than a list of expressions,
        so it needs this; keeping it in one place is also what stops the two
        writers drifting into producing subtly different files.
        """
        self.emit_raw(f"static void {name}__write_row(FILE* f, const {name}* r) {{")
        for i, fd in enumerate(fields):
            ct = self._c_type(fd.field_type)
            if i:
                self.emit_raw("    fputc(0x09, f);")
            if ct == "strata_str":
                self.emit_raw(f"    strata_write_escaped(f, r->{fd.name});")
            elif ct == "strata_float":
                self.emit_raw(f'    fprintf(f, "%.17g", (double)r->{fd.name});')
            else:
                self.emit_raw(f'    fprintf(f, "%lld", (long long)r->{fd.name});')
        self.emit_raw("    fputc(0x0a, f);")
        self.emit_raw("}")

    def _gen_table_scan(self, name, fields):
        """Reading a stored table one row at a time.

        A load brings the whole table into the process, which is right when it
        is small and impossible when it is not. These three functions are what
        `scan T from "p" as row { ... }` compiles to: open and validate the
        header once, then hand back one row at a time into a single struct the
        caller owns. Nothing accumulates, so a file of any size costs what one
        row costs.

        The header checks are deliberately the same ones a load makes. A scan
        that quietly accepted a file a load would refuse would be a second,
        laxer way into the same data.
        """
        def tchar(fd):
            ct = self._c_type(fd.field_type)
            return "s" if ct == "strata_str" else ("f" if ct == "strata_float" else "i")

        strs = [fd for fd in fields if self._c_type(fd.field_type) == "strata_str"]

        self.emit_raw(f"static void {name}__scan_free({name}* r) {{")
        for fd in strs:
            self.emit_raw(f"    if (r->{fd.name}) {{ free(r->{fd.name}); "
                          f"r->{fd.name} = NULL; }}")
        if not strs:
            self.emit_raw("    (void)r;")
        self.emit_raw("}")

        # A deleted row is freed at the next scratch_reset, when nothing in
        # the arena can still be pointing at it. This is the whole row, not
        # just its strings.
        self.emit_raw(f"static void {name}__row_free(void* p) {{")
        self.emit_raw(f"    {name}__scan_free(({name}*)p);")
        self.emit_raw("    free(p);")
        self.emit_raw("}")

        self.emit_raw(f"static FILE* {name}__scan_open(const char* path, "
                      "int* map, int* ncol) {")
        self.emit_raw('    FILE* f = fopen(path, "r");')
        self.emit_raw("    if (!f) {")
        self.emit_raw(f'        strata_load_refuse("{name}", path, "there is no such file");')
        self.emit_raw("        return NULL;")
        self.emit_raw("    }")
        self.emit_raw("    char _names[STRATA_MAX_COLS][STRATA_NAME_CAP];")
        self.emit_raw("    char _types[STRATA_MAX_COLS];")
        self.emit_raw("    char _table[STRATA_NAME_CAP];")
        self.emit_raw("    int n = strata_read_header(f, _names, _types, "
                      "STRATA_MAX_COLS, _table);")
        self.emit_raw("    if (n == -2) { *ncol = 0; return f; }")
        self.emit_raw("    if (n == -1) {")
        self.emit_raw(f'        strata_load_refuse("{name}", path, "no schema header; '
                      f'it was written before headers existed. Re-save it.");')
        self.emit_raw("        fclose(f); return NULL;")
        self.emit_raw("    }")
        self.emit_raw(f'    if (_table[0] && strcmp(_table, "{name}") != 0) {{')
        self.emit_raw("        char _why[192];")
        self.emit_raw('        snprintf(_why, sizeof(_why), "it was saved from '
                      '\'%s\', not this table", _table);')
        self.emit_raw(f'        strata_load_refuse("{name}", path, _why);')
        self.emit_raw("        fclose(f); return NULL;")
        self.emit_raw("    }")
        self.emit_raw("    int matched = 0;")
        self.emit_raw("    for (int c = 0; c < n; c++) {")
        self.emit_raw("        map[c] = -1;")
        for idx, fd in enumerate(fields):
            self.emit_raw(f'        if (strcmp(_names[c], "{fd.name}") == 0) {{')
            self.emit_raw(f"            if (_types[c] != '{tchar(fd)}') {{")
            self.emit_raw(f'                strata_load_refuse("{name}", path, '
                          f'"column \'{fd.name}\' changed type since it was saved");')
            self.emit_raw("                fclose(f); return NULL;")
            self.emit_raw("            }")
            self.emit_raw(f"            map[c] = {idx};")
            self.emit_raw("        }")
        self.emit_raw("        if (map[c] >= 0) matched++;")
        self.emit_raw("    }")
        self.emit_raw("    if (n > 0 && matched == 0) {")
        self.emit_raw(f'        strata_load_refuse("{name}", path, "none of its '
                      f'columns are in this table");')
        self.emit_raw("        fclose(f); return NULL;")
        self.emit_raw("    }")
        self.emit_raw("    *ncol = n;")
        self.emit_raw("    return f;")
        self.emit_raw("}")

        self.emit_raw(f"static int {name}__scan_next(FILE* f, const int* map, "
                      f"int ncol, {name}* out, const char* path, strata_int rowno) {{")
        self.emit_raw(f"    {name}__scan_free(out);")
        self.emit_raw(f"    memset(out, 0, sizeof({name}));")
        for fd in strs:
            self.emit_raw(f'    out->{fd.name} = strata_dup("");')
        self.emit_raw("    char buf[4096];")
        self.emit_raw("    for (int c = 0; c < ncol; c++) {")
        self.emit_raw("        int more = strata_read_field(f, buf, 4096);")
        self.emit_raw("        if (more < 0) return 0;")
        self.emit_raw("        switch (map[c]) {")
        for idx, fd in enumerate(fields):
            ct = self._c_type(fd.field_type)
            if ct == "strata_str":
                conv = f"free(out->{fd.name}); out->{fd.name} = strata_dup(buf);"
            elif ct == "strata_float":
                conv = (f"{{ strata_float _v; if (!strata_parse_float(buf, &_v)) {{ "
                        f'strata_load_bad_value("{name}", path, "{fd.name}", buf, rowno); '
                        f"return 0; }} out->{fd.name} = ({ct})_v; }}")
            else:
                conv = (f"{{ strata_int _v; if (!strata_parse_int(buf, &_v)) {{ "
                        f'strata_load_bad_value("{name}", path, "{fd.name}", buf, rowno); '
                        f"return 0; }} out->{fd.name} = ({ct})_v; }}")
            self.emit_raw(f"            case {idx}: {conv} break;")
        self.emit_raw("            default: break;")
        self.emit_raw("        }")
        self.emit_raw("    }")
        self.emit_raw("    return 1;")
        self.emit_raw("}")

    def _gen_pg_save(self, name, fields, cols_sql, upsert_sql, delete_sql,
                     key, n):
        """The database branch of a save.

        Only rows the store does not already have in this exact shape are
        sent, and keys that have gone from memory are deleted. A save that
        follows a load writes the difference; a save with no prior load
        replaces the table, because a process that has not read it cannot know
        what else is there."""
        self.emit_raw("#ifdef STRATA_POSTGRES")
        self.emit_raw("    if (strata_pg_is_url(path)) {")
        self.emit_raw("        void* _pg = strata_pg_open(path);")
        self.emit_raw("        if (!_pg) { return 0; }")
        if key:
            self.emit_raw(f"        int _known = strata_pg_snap_describes("
                          f"&{name}__pg_was, path);")
        else:
            # No integer key in the first column, so there is nothing to
            # conflict on and nothing to match a row by. The table is
            # replaced, as it was before. Stated in the generated C so anyone
            # reading it knows why this one is different.
            self.emit_raw("        int _known = 0;   /* no integer key column */")
        self.emit_raw(f'        if (!strata_pg_begin(_pg, "{name}", "{cols_sql}", '
                      f'"{key or ""}", !_known)) {{')
        self.emit_raw("            strata_pg_abort(_pg); return 0;")
        self.emit_raw("        }")
        if key:
            self.emit_raw(f"        strata_pg_snap_clear(&{name}__pg_now);")
        self.emit_raw(f"        for (strata_int i = 0; i < {name}__count; i++) {{")
        self.emit_raw(f"            {name}* r = {name}__rows[i];")
        self.emit_raw(f"            char _b[{max(n, 1)}][48];")
        self.emit_raw(f"            const char* _v[{max(n, 1)}];")
        for i, fd in enumerate(fields):
            ct = self._c_type(fd.field_type)
            if ct == "strata_str":
                self.emit_raw(f'            _v[{i}] = r->{fd.name} ? r->{fd.name} : "";')
            elif ct == "strata_float":
                self.emit_raw(f"            _v[{i}] = strata_pg_float(_b[{i}], r->{fd.name});")
            else:
                self.emit_raw(f"            _v[{i}] = strata_pg_int(_b[{i}], "
                              f"(long long)r->{fd.name});")
        if key:
            self.emit_raw(f"            uint64_t _h = strata_pg_hash({n}, _v);")
            self.emit_raw(f"            int64_t _k = (int64_t)r->{key};")
            self.emit_raw(f"            strata_pg_snap_put(&{name}__pg_now, _k, _h);")
            self.emit_raw(f"            if (_known && strata_pg_snap_unchanged("
                          f"&{name}__pg_was, _k, _h)) {{ continue; }}")
        self.emit_raw(f'            if (!strata_pg_insert(_pg, "{upsert_sql}", {n}, _v)) {{')
        self.emit_raw("                strata_pg_abort(_pg); return 0;")
        self.emit_raw("            }")
        self.emit_raw("        }")
        if key:
            self.emit_raw("        if (_known && !strata_pg_delete_gone(_pg, "
                          f'"{delete_sql}", &{name}__pg_was, &{name}__pg_now)) {{')
            self.emit_raw("            strata_pg_abort(_pg); return 0;")
            self.emit_raw("        }")
        self.emit_raw('        strata_int _ok = strata_pg_exec(_pg, "COMMIT");')
        if key:
            self.emit_raw("        if (_ok) {")
            self.emit_raw(f"            strata_pg_snap_adopt(&{name}__pg_was, "
                          f"&{name}__pg_now, path);")
            self.emit_raw("        }")
        self.emit_raw("        strata_pg_close(_pg);")
        self.emit_raw("        return _ok;")
        self.emit_raw("    }")
        self.emit_raw("#endif")

    def _gen_pg_load(self, name, fields, select_sql, key):
        """The database branch of a load.

        No stamp check above it applies: strata_file_stamp() returns 0 for a
        URL, so the skip never fires and the table is read every time. A file
        has a modification time to compare and a query does not."""
        self.emit_raw("#ifdef STRATA_POSTGRES")
        self.emit_raw("    if (strata_pg_is_url(path)) {")
        self.emit_raw("        void* _pg = strata_pg_open(path);")
        self.emit_raw("        if (!_pg) { return 0; }")
        # The WHERE the caller translated, if any. Appended here rather than
        # baked into select_sql, because the same __load serves every call
        # site and each may ask for something different.
        self.emit_raw(f'        char _q[2048];')
        self.emit_raw(f'        snprintf(_q, sizeof(_q), "{select_sql}%s%s",')
        self.emit_raw('                 (_where && *_where) ? " WHERE " : "",')
        self.emit_raw('                 (_where && *_where) ? _where : "");')
        self.emit_raw("        void* _res = strata_pg_select(_pg, _q);")
        self.emit_raw("        if (!_res) { strata_pg_close(_pg); return 0; }")
        self.emit_raw(f"        {name}__count = 0;")
        if key:
            self.emit_raw(f"        strata_pg_snap_clear(&{name}__pg_now);")
        self.emit_raw("        strata_int _rows = strata_pg_rows(_res);")
        self.emit_raw("        for (strata_int _i = 0; _i < _rows; _i++) {")
        self.emit_raw(f"            {name}* r = ({name}*)calloc(1, sizeof({name}));")
        for i, fd in enumerate(fields):
            ct = self._c_type(fd.field_type)
            src = f"strata_pg_value(_res, _i, {i})"
            if ct == "strata_str":
                self.emit_raw(f"            r->{fd.name} = strata_dup({src});")
            elif ct == "strata_float":
                self.emit_raw(f"            r->{fd.name} = strtod({src}, NULL);")
            else:
                self.emit_raw(f"            r->{fd.name} = (strata_int)atoll({src});")
        self._gen_table_push(name, "            ")
        # What the table held when it was read, so the next save can tell
        # which rows actually changed.
        if key:
            self.emit_raw(f"            const char* _v[{max(len(fields), 1)}];")
            for i in range(len(fields)):
                self.emit_raw(f"            _v[{i}] = strata_pg_value(_res, _i, {i});")
            self.emit_raw(f"            strata_pg_snap_put(&{name}__pg_now, "
                          f"(int64_t)r->{key}, strata_pg_hash({len(fields)}, _v));")
        self.emit_raw("        }")
        if key:
            # A filtered load has seen part of the table, so the snapshot
            # describes part of it. That is still exactly right for the next
            # save: a row never read is never deleted, because delete only
            # touches keys that WERE read and have since gone.
            self.emit_raw(f"        strata_pg_snap_adopt(&{name}__pg_was, "
                          f"&{name}__pg_now, path);")
        self.emit_raw("        strata_pg_clear(_res);")
        self.emit_raw("        strata_pg_close(_pg);")
        self.emit_raw("        return 1;")
        self.emit_raw("    }")
        self.emit_raw("#endif")

    def _gen_struct(self, name, fields):
        self.emit_raw(f"\nstruct {name} {{")
        for f in fields:
            self.emit_raw(f"    {self._c_type(f.field_type)} {f.name};")
        self.emit_raw(f"}};")

    def _gen_model(self, decl):
        # Same layout as StrataModel in the prelude, so strata_predict can
        # read it without a cast that depends on field order.
        #
        # `dims` is the input width, then each layer's output width; `acts` the
        # activation after each layer. A model with no hidden layers is one
        # layer, so the forward pass has no special case for it.
        hidden = getattr(decl, "hidden", []) or []
        dims = ([decl.input_type.cols]
                + [h.width for h in hidden]
                + [decl.output_type.cols])
        acts = [{"relu": "r", "sigmoid": "s"}.get(h.activation, "n") for h in hidden]
        acts.append("n")                      # the output layer is linear
        self.emit_raw(f"\ntypedef StrataModel {decl.name};")
        dim_list = ",".join(str(d) for d in dims)
        act_list = ",".join(f"'{a}'" for a in acts)
        self.emit_raw(
            f"static {decl.name} {decl.name}_instance = "
            f"{{{decl.input_type.rows},{decl.input_type.cols},"
            f"{decl.output_type.rows},{decl.output_type.cols},NULL,"
            f"{len(dims) - 1},{{{dim_list}}},{{{act_list}}}}};")

    # Layout properties are declarative and map onto CSS. Anything not listed
    # is emitted as a data- attribute rather than dropped, so an unrecognised
    # property is visible in the output instead of silently disappearing.
    CSS_PROPS = {
        "background": "background", "color": "color", "size": "font-size:{}px",
        "weight": "font-weight", "width": "width:{}px", "height": "height:{}px",
        "padding": "padding:{}px", "padding_x": "padding-left:{0}px;padding-right:{0}px",
        "padding_y": "padding-top:{0}px;padding-bottom:{0}px",
        "padding_top": "padding-top:{}px", "margin_top": "margin-top:{}px",
        "border_radius": "border-radius:{}px", "border_color": "border:1px solid {}",
        "spacing": "gap:{}px", "columns": "grid-template-columns:repeat({},1fr)",
    }

    # Element tag -> HTML tag.
    HTML_TAG = {
        "window": "div", "row": "div", "column": "div", "grid": "div",
        "text": "span", "spacer": "div", "canvas": "canvas",
        "button": "button", "image": "img",
        # The UI tier could render data but not collect any, so an
        # application could show a list and never add to it.
        "form": "form", "field": "input",
    }

    # Elements with no closing tag.
    VOID_TAGS = {"input", "img"}

    # Properties that are HTML attributes rather than style. Anything not here
    # and not a CSS property is still emitted as a data- attribute, so an
    # unrecognised one is visible rather than silently dropped.
    ATTR_PROPS = {"action", "method", "name", "type", "placeholder", "value",
                  "required", "href", "src", "alt", "step", "min", "max"}

    def _css_for(self, el):
        """Inline style string for an element's properties."""
        parts = []
        if el.tag == "row":    parts.append("display:flex;flex-direction:row;align-items:center")
        if el.tag == "column": parts.append("display:flex;flex-direction:column")
        if el.tag == "grid":   parts.append("display:grid")
        for p in el.props:
            spec = self.CSS_PROPS.get(p.name)
            if spec is None:
                continue
            v = p.value
            raw = v.value if isinstance(v, (StrLiteral, IntLiteral, FloatLiteral)) else None
            if raw is None:
                continue
            parts.append(spec.format(raw) if "{" in spec else f"{spec}:{raw}")
        return ";".join(parts)

    def _gen_stream_registry(self):
        """Register every stream handler against its channel.

        The channel is the handler's name: `stream Ingest(str m)` receives
        messages published to "Ingest".
        """
        streams = [fn for _, u in ([(None, self.ast)] + list(self.modules))
                   for fn in u.functions if fn.kind == "stream"]
        self.emit_raw("\nstatic void __strata_register_streams(void) {")
        if not streams:
            self.emit_raw("    /* no stream handlers */")
        for fn in streams:
            self.emit_raw(f'    strata_on("{fn.name}", (StrataHandler){cname(fn.name)});')
        self.emit_raw("}")

    def _gen_test_main(self):
        """An entry point that runs every verify block and reports."""
        self.emit_raw("\nint main(int argc, char** argv) {")
        self.emit_raw("    __strata_argc = argc; __strata_argv = argv;")
        self.emit_raw("    __strata_register_streams();")
        self.emit_raw("    int blocks = 0, failed_blocks = 0;")
        for d in self.verify_blocks:
            safe = _verify_symbol(d.label)
            label = d.label.replace('"', '\\"')
            self.emit_raw("    {")
            self.emit_raw("        int before = __strata_fail_count;")
            self.emit_raw(f'        fprintf(stderr, "  {label}\\n");')
            self.emit_raw(f"        __strata_verify_{safe}();")
            self.emit_raw("        blocks++;")
            self.emit_raw("        if (__strata_fail_count > before) failed_blocks++;")
            self.emit_raw("    }")
        self.emit_raw('    fprintf(stderr, "\\n  %d block(s), %d assertion(s), '
                      '%d failed\\n", blocks, __strata_assert_count, __strata_fail_count);')
        self.emit_raw("    return __strata_fail_count == 0 ? 0 : 1;")
        self.emit_raw("}")

    def _gen_verify(self, decl):
        """A verify block becomes a function a test driver can call."""
        safe = _verify_symbol(decl.label)
        self.emit_raw(f"\n/* verify: {decl.label} */")
        self.emit_raw(f"void __strata_verify_{safe}(void) {{")
        self.indent = 1
        self.var_types = dict(self.const_types)
        for st in decl.assertions:
            self._gen_stmt(st, [])
        self.indent = 0
        self.emit_raw("}")

    def _gen_foreign(self, decl):
        """Include the header and record the library to link.

        No prototypes are emitted: the header already declares them, and
        re-declaring risks conflicting with the real signature.
        """
        self.emit_raw(f"#include <{decl.header}>")
        if decl.link:
            self.link_libs.append(decl.link)
        # Record return types so conversions dispatch correctly: without this
        # str(sqrt(x)) routes a float through the integer converter.
        for fn in decl.functions:
            self.func_returns[fn.name] = self._c_type(fn.return_type)

    def _has_ui(self):
        """Whether this program brought in the screen-drawing module.

        A layout is generated twice when it did: once as HTML for the web, and
        once as a drawn screen for a phone. A program that does not import `ui`
        gets only the HTML, because the drawn version calls functions that
        would not be there to link against.

        The same rule the Postgres backend uses: importing the module is the
        switch, and a program that does not ask for something carries neither
        the dependency nor the code."""
        for name, _ in self.modules:
            if name == "ui":
                return True
        return False

    # Colours in a layout are written the way HTML writes them -- "#7ee787".
    # The drawn screen needs the number. Worked out here, at compile time, from
    # a literal; anything that is not a literal keeps the default, because a
    # colour computed at run time is not something a layout can express today
    # and guessing would be worse than ignoring.
    def _layout_colour(self, el, name, fallback):
        for pr in el.props:
            if pr.name != name:
                continue
            if isinstance(pr.value, StrLiteral):
                text = str(pr.value.value).strip()
                if text.startswith("#") and len(text) == 7:
                    try:
                        return int(text[1:], 16)
                    except ValueError:
                        return fallback
            if isinstance(pr.value, IntLiteral):
                return int(pr.value.value)
        return fallback

    def _layout_int(self, el, name, fallback):
        for pr in el.props:
            if pr.name == name and isinstance(pr.value, IntLiteral):
                return int(pr.value.value)
        return fallback

    def _layout_str_prop(self, el, name):
        for pr in el.props:
            if pr.name == name and isinstance(pr.value, StrLiteral):
                return str(pr.value.value)
        return ""

    def _gen_layout(self, decl):
        """A layout becomes a function that writes HTML to a stream.

        Its parameters are the view's inputs — a filter, an id — because
        Strata has no module-level variables and a view that can only read
        globals is a view that cannot be reused.
        """
        params = getattr(decl, "params", [])
        sig = "".join(f", {self._c_param(p)}" for p in params)
        self.emit_raw(f"\nvoid {decl.name}_render(FILE* _out{sig}) {{")
        self.var_types = dict(self.var_types)
        for p in params:
            self.var_types[p.name] = self._c_type(p.param_type)
        self.indent = 1
        self.emit('fprintf(_out,"<!doctype html><meta charset=\\"utf-8\\">");')
        self.in_layout = True
        for st in decl.body:
            self._gen_layout_node(st)
        self.in_layout = False
        self.indent = 0
        self.emit_raw("}")
        if self._has_ui():
            self._gen_layout_draw(decl)

    # ── The same layout, drawn ───────────────────────────────────────────────
    #
    # A layout was one description that rendered one way: HTML. The phone
    # screens were written separately with the UI library, so there were two
    # ways to write a screen -- which is the split this language exists to
    # remove, reappearing inside it.
    #
    # `X_draw(...)` takes the same parameters as `X_render(...)` and produces
    # the same screen as things to draw. A column flows down, a row places its
    # children across, and everything else is what it was.
    #
    # The two are not pixel-identical and are not meant to be. A browser has a
    # layout engine and a phone screen here does not; what is shared is the
    # DESCRIPTION -- the same fields, the same rows, the same queries, checked
    # against the same schema once.
    def _gen_layout_draw(self, decl):
        params = getattr(decl, "params", [])
        sig = ", ".join(self._c_param(p) for p in params) or "void"
        self.emit_raw(f"\nvoid {decl.name}_draw({sig}) {{")
        self.var_types = dict(self.var_types)
        for p in params:
            self.var_types[p.name] = self._c_type(p.param_type)
        self.indent = 1
        self.emit("ui_flow(0, 0, 411, 8);")
        self.in_layout = True
        self.in_draw = True
        for st in decl.body:
            self._gen_draw_node(st)
        self.in_draw = False
        self.in_layout = False
        self.indent = 0
        self.emit_raw("}")

    def _gen_draw_node(self, node):
        if isinstance(node, Element):
            self._gen_draw_element(node); return
        if isinstance(node, ForInStmt):
            # The same loop the HTML gets, around drawing instead of printing.
            self._gen_for_in(node); return
        if isinstance(node, IfStmt):
            self._gen_if(node, []); return
        self._gen_stmt(node, [])

    def _gen_draw_element(self, el):
        INK = 0x1A1A1A
        tag = el.tag

        if tag in ("window", "grid"):
            # The host owns the window. Its children simply flow.
            for c in el.children:
                self._gen_draw_node(c)
            return

        if tag == "column":
            pad = self._layout_int(el, "padding", 0)
            bg = self._layout_colour(el, "background", -1)
            if bg >= 0:
                # A column's background is painted behind whatever it holds, so
                # its height is not known until the children are placed. The
                # panel is drawn afterwards is impossible with a display list
                # that is appended to, so it is drawn as a full-width band from
                # here to the bottom of the screen -- honest for a page
                # background and wrong for a card, which is why a card should
                # be a row.
                self.emit(f"ui_rect(0, ui_flow_y(), 411, 731 - ui_flow_y(), {bg});")
            if pad:
                self.emit(f"ui_flow(ui_flow_x() + {pad}, ui_flow_y() + {pad}, "
                          f"411 - 2 * {pad}, ui_flow_gap());")
            for c in el.children:
                self._gen_draw_node(c)
            return

        if tag == "row":
            pad = self._layout_int(el, "padding", 0)
            bg = self._layout_colour(el, "background", -1)
            height = 24 + 2 * pad
            if bg >= 0:
                self.emit(f"ui_rect(ui_flow_x(), ui_flow_y(), ui_flow_w(), "
                          f"{height}, {bg});")
            # Children across, evenly: a display list appended to cannot know
            # how wide a child will be before it is placed, so a row divides
            # its width rather than measuring. `spacer` is what asks for the
            # division, so a row with no spacers packs from the left.
            drawable = [c for c in el.children
                        if isinstance(c, Element) and c.tag != "spacer"]
            slots = max(len(drawable), 1)
            self.emit(f"{{ strata_int _rw = ui_flow_w() / {slots};")
            self.emit(f"strata_int _rx = ui_flow_x() + {pad};")
            self.emit(f"strata_int _ry = ui_flow_y() + {pad};")
            for c in drawable:
                self._gen_draw_inline(c, INK)
                self.emit("_rx += _rw;")
            self.emit("}")
            self.emit(f"ui_advance({height});")
            return

        if tag == "text":
            colour = self._layout_colour(el, "color", INK)
            size = self._layout_int(el, "size", 8)
            scale = max(1, size // 8)
            value = self._gen_expr(el.label, []) if el.label is not None else '""'
            self.emit(f"ui_line({value}, {colour}, {scale});")
            return

        if tag == "spacer":
            self.emit("ui_advance(8);")
            return

        if tag == "button":
            label = self._gen_expr(el.label, []) if el.label is not None else '""'
            action = self._layout_str_prop(el, "action") or "submit"
            self.emit(f'ui_button(ui_flow_x(), ui_flow_y(), ui_flow_w(), 44, '
                      f'{label}, "{action}", 0x1F4E62, 0xFFFFFF);')
            self.emit("ui_advance(44);")
            return

        if tag == "field":
            # A hidden field is not drawn: it carries a token a browser needs
            # and a phone does not.
            if self._layout_str_prop(el, "type") == "hidden":
                return
            name = self._gen_expr(el.label, []) if el.label is not None else '""'
            hint = self._layout_str_prop(el, "placeholder")
            self.emit(f'ui_input(44, {name}, "{hint}", 0xFFFFFF, {INK}, '
                      f'0xE1E1E1, 0xE1E1E1);')
            return

        if tag == "form":
            for c in el.children:
                self._gen_draw_node(c)
            return

        # Anything with no drawing rule still draws its children, so an
        # unhandled wrapper loses its box and not its contents.
        for c in el.children:
            self._gen_draw_node(c)

    def _gen_draw_inline(self, el, ink):
        """One child of a row, placed at _rx/_ry rather than at the flow."""
        if el.tag == "text":
            colour = self._layout_colour(el, "color", ink)
            size = self._layout_int(el, "size", 8)
            scale = max(1, size // 8)
            value = self._gen_expr(el.label, []) if el.label is not None else '""'
            self.emit(f"ui_text(_rx, _ry, {value}, {colour}, {scale});")
            return
        if el.tag == "button":
            label = self._gen_expr(el.label, []) if el.label is not None else '""'
            action = self._layout_str_prop(el, "action") or "submit"
            self.emit(f'ui_button(_rx, _ry, _rw - 8, 24, {label}, "{action}", '
                      f'0x1F4E62, 0xFFFFFF);')
            return
        if el.tag == "form":
            for c in el.children:
                if isinstance(c, Element):
                    self._gen_draw_inline(c, ink)
            return
        if el.tag == "field":
            return

    def _gen_layout_node(self, node):
        if isinstance(node, Element):
            self._gen_element(node); return
        if isinstance(node, ForInStmt):
            self._gen_for_in(node); return
        if isinstance(node, IfStmt):
            self._gen_if(node, []); return
        self._gen_stmt(node, [])

    def _attrs_for(self, el):
        """Literal HTML attributes from an element's properties."""
        out = []
        for p in el.props:
            if p.name not in self.ATTR_PROPS:
                continue
            v = p.value
            raw = v.value if isinstance(v, (StrLiteral, IntLiteral, FloatLiteral)) else None
            if raw is None:
                continue
            out.append(f' {p.name}=\\"{self._html_escape(str(raw))}\\"')
        return "".join(out)

    def _computed_attrs(self, el):
        """Attributes whose value is an expression rather than a literal.

        A row's own id has to reach the form that acts on it, and a literal
        cannot carry it. These are emitted as their own fprintf because the
        value is only known at run time.
        """
        out = []
        for p in el.props:
            if p.name not in self.ATTR_PROPS:
                continue
            if isinstance(p.value, (StrLiteral, IntLiteral, FloatLiteral)):
                continue
            out.append((p.name, p.value))
        return out

    def _gen_element(self, el):
        tag = self.HTML_TAG.get(el.tag, "div")
        css = self._css_for(el)
        style = (' style=\\"' + css + '\\"') if css else ""
        attrs = self._attrs_for(el)
        # `field "customer"` names the form field it submits; the label is the
        # name rather than text, because an input has no text content.
        if el.tag == "field" and isinstance(el.label, StrLiteral) \
           and " name=" not in attrs:
            attrs = f' name=\\"{self._html_escape(el.label.value)}\\"' + attrs
        computed = self._computed_attrs(el)
        if tag in self.VOID_TAGS:
            self.emit('fprintf(_out,"<' + tag + attrs + '");')
            self._emit_computed_attrs(computed)
            self.emit('fprintf(_out,"' + style + '>");')
            return
        if el.tag == "window":
            title = el.label.value if isinstance(el.label, StrLiteral) else el.tag
            self.emit('fprintf(_out,"<title>' + self._html_escape(title) + '</title>");')
            self.emit('fprintf(_out,"<body' + attrs + style + '>");')
            for c in el.children:
                self._gen_layout_node(c)
            self.emit('fprintf(_out,"</body>");')
            return
        self.emit('fprintf(_out,"<' + tag + attrs + '");')
        self._emit_computed_attrs(computed)
        self.emit('fprintf(_out,"' + style + '>");')
        if el.label is not None and el.tag != "canvas":
            if isinstance(el.label, StrLiteral):
                self.emit('fprintf(_out,"%s","' + self._html_escape(el.label.value) + '");')
            elif not isinstance(el.label, Identifier):
                # A computed label — a field from a query row, for instance.
                self.emit(f'fprintf(_out,"%s",{self._gen_expr(el.label, [])});')
            elif el.label.name in self.var_types:
                # A bare identifier names the element — `canvas topology_view`
                # — unless it resolves to a value in scope, which is the same
                # rule the type checker applies. Without this a layout
                # parameter renders as nothing at all.
                self.emit(f'fprintf(_out,"%s",{self._gen_expr(el.label, [])});')
        for c in el.children:
            self._gen_layout_node(c)
        self.emit('fprintf(_out,"</' + tag + '>");')

    def _emit_computed_attrs(self, computed):
        for name, value in computed:
            self.emit(f'fprintf(_out," {name}=\\"%s\\"",'
                      f'{self._gen_expr(value, [])});')

    def _gen_delete(self, stmt, param_names):
        """`delete T <- [cond];` — the surviving rows are moved down and the
        count is reduced, so the table holds exactly what is left.

        The row is handed to strata_retire rather than freed here. Something
        else may still be holding it — a list a query returned a moment ago
        points at the same rows — so it is freed at the next scratch_reset(),
        when the arena those lists live in is thrown away too. Before the
        arena existed there was no such moment, and the row simply leaked.
        """
        src = stmt.table
        if src not in self.schemas:
            return
        self._validate_query_columns(stmt.condition, src, stmt.line)
        prev = self.query_row_type
        self.query_row_type = src
        cond = self._gen_expr(stmt.condition, param_names)
        self.query_row_type = prev
        self.emit("{")
        self.indent += 1
        self.emit("strata_int _kept = 0;")
        self.emit(f"for (strata_int _di = 0; _di < {src}__count; _di++) {{")
        self.indent += 1
        self.emit(f"{src}* _row = {src}__rows[_di];")
        self.emit(f"if (!({cond})) {{ {src}__rows[_kept++] = _row; }}"
                  f" else {{ strata_retire(_row, {src}__row_free); }}")
        self.indent -= 1
        self.emit("}")
        self.emit(f"{src}__count = _kept;")
        self.indent -= 1
        self.emit("}")

    def _gen_rewrite(self, node, param_names=None):
        """`rewrite T from "p" as row { ... }`.

        The file is streamed through a temporary beside it and the temporary
        is renamed over the original once the last row is read. That is what
        makes it safe: a job that dies half way leaves the original file
        exactly as it was, because a rename is atomic and a half-written
        temporary is never the table.
        """
        if param_names is None:
            param_names = []
        self.rewrite_depth += 1
        d = self.rewrite_depth
        self.var_types[node.var] = node.table + "*"
        t = node.table
        path = _c_string(node.path)
        self.emit("{")
        self.indent += 1
        self.emit(f"int _wmap{d}[STRATA_MAX_COLS]; int _wncol{d} = 0;")
        self.emit(f"FILE* _wf{d} = {t}__scan_open({path}, _wmap{d}, &_wncol{d});")
        self.emit(f"if (_wf{d}) {{")
        self.indent += 1
        self.emit(f"char _wtmp{d}[4096];")
        self.emit(f'snprintf(_wtmp{d}, sizeof(_wtmp{d}), "%s.strata-rewrite", {path});')
        self.emit(f'FILE* _ww{d} = fopen(_wtmp{d}, "w");')
        self.emit(f"if (!_ww{d}) {{")
        self.indent += 1
        self.emit('fprintf(stderr, "[STRATA REWRITE] ' + t +
                  ': cannot write \'%s\'\\n", _wtmp' + str(d) + ');')
        self.emit(f"fclose(_wf{d});")
        self.indent -= 1
        self.emit("} else {")
        self.indent += 1
        header = "\\t".join(
            f"{fd.name}:{'s' if self._c_type(fd.field_type) == 'strata_str' else ('f' if self._c_type(fd.field_type) == 'strata_float' else 'i')}"
            for fd in self.schema_fields.get(t, []))
        self.emit(f'fprintf(_ww{d}, "#strata\\t{t}\\t{header}\\n");')
        self.emit(f"{t} _wrow{d}; memset(&_wrow{d}, 0, sizeof({t}));")
        self.emit(f"{t}* {cname(node.var)} = &_wrow{d};")
        self.emit(f"strata_int _wno{d} = 0; int _wdrop{d} = 0;")
        self.emit(f"while ({t}__scan_next(_wf{d}, _wmap{d}, _wncol{d}, &_wrow{d}, "
                  f"{path}, ++_wno{d})) {{")
        self.indent += 1
        self.emit(f"_wdrop{d} = 0;")
        for st in node.body:
            self._gen_stmt(st, param_names)
        self.emit(f"_wnext{d}:;")
        self.emit(f"if (!_wdrop{d}) {t}__write_row(_ww{d}, &_wrow{d});")
        self.indent -= 1
        self.emit("}")
        self.emit(f"{t}__scan_free(&_wrow{d});")
        self.emit(f"fclose(_ww{d}); fclose(_wf{d});")
        # Only now does the new file become the table.
        self.emit(f"if (rename(_wtmp{d}, {path}) != 0) {{")
        self.indent += 1
        self.emit('fprintf(stderr, "[STRATA REWRITE] ' + t +
                  ': could not replace \'%s\'; the new rows are in \'%s\'\\n", ' + path + ', _wtmp' + str(d) + ');')
        self.indent -= 1
        self.emit("}")
        self.indent -= 1
        self.emit("}")
        self.indent -= 1
        self.emit("}")
        self.indent -= 1
        self.emit("}")
        self.rewrite_depth -= 1

    def _gen_append(self, node, param_names=None):
        """`append T to "p" [col = expr, ...];` — one row, straight to a file.

        The columns are written in SCHEMA order whatever order they were
        written in, because the header says schema order and a reader trusts
        it. The type checker has already insisted every column is present.
        """
        if param_names is None:
            param_names = []
        given = dict(node.assignments)
        fields = self.schema_fields.get(node.target, [])
        self.emit("{")
        self.indent += 1
        self.emit(f"FILE* _pf = {node.target}__append_open({_c_string(node.path)});")
        self.emit("if (_pf) {")
        self.indent += 1
        for i, fd in enumerate(fields):
            if i:
                self.emit("fputc(0x09, _pf);")
            expr = given.get(fd.name)
            if expr is None:
                continue
            value = self._gen_expr(expr, param_names)
            ct = self._c_type(fd.field_type)
            if ct == "strata_str":
                self.emit(f"strata_write_escaped(_pf, {value});")
            elif ct == "strata_float":
                self.emit(f'fprintf(_pf, "%.17g", (double)({value}));')
            else:
                self.emit(f'fprintf(_pf, "%lld", (long long)({value}));')
        self.emit("fputc(0x0a, _pf);")
        self.indent -= 1
        self.emit("}")
        self.indent -= 1
        self.emit("}")

    def _gen_scan(self, node, param_names=None):
        """`scan T from "p" as row { ... }`.

        One struct, reused for every row. The body sees a pointer to it, and
        nothing survives the turn of the loop -- which is exactly the deal
        that lets a file larger than memory be read at all.
        """
        if param_names is None:
            param_names = []
        # The body holds a POINTER to the one struct being reused, so member
        # access on it is `->`. Writing the row type without the star made
        # every `row.column` in a scan body emit a `.` and fail to compile.
        self.var_types[node.var] = node.table + "*"
        self.emit("{")
        self.indent += 1
        self.emit("int _smap[STRATA_MAX_COLS]; int _sncol = 0;")
        self.emit(f'FILE* _sf = {node.table}__scan_open({_c_string(node.path)}, '
                  f"_smap, &_sncol);")
        self.emit("if (_sf) {")
        self.indent += 1
        self.emit(f"{node.table} _srow; memset(&_srow, 0, sizeof({node.table}));")
        self.emit(f"{node.table}* {cname(node.var)} = &_srow;")
        self.emit("strata_int _srowno = 0;")
        self.emit(f"while ({node.table}__scan_next(_sf, _smap, _sncol, &_srow, "
                  f"{_c_string(node.path)}, ++_srowno)) {{")
        self.indent += 1
        for st in node.body:
            self._gen_stmt(st, param_names)
        self.indent -= 1
        self.emit("}")
        self.emit(f"{node.table}__scan_free(&_srow);")
        self.emit("fclose(_sf);")
        self.indent -= 1
        self.emit("}")
        self.indent -= 1
        self.emit("}")

    def _gen_for_in(self, node, param_names=None):
        """Iterate a list, by its length.

        This used to walk to the first NULL, which was wrong for any list of
        scalars — 0 is a valid int — and became wrong for query results too
        once lists started carrying a length header instead of a terminator.
        """
        if param_names is None:
            param_names = []
        coll = self._gen_expr(node.collection, param_names)
        ct = self._expr_ctype(node.collection, param_names) or ""
        elem = ct[:-1] if ct.endswith("*") else "void*"
        self.var_types[node.var] = elem
        it = f"_it_{cname(node.var)}"
        self.emit("{")
        self.indent += 1
        self.emit(f"{elem}* {it} = {coll};")
        self.emit(f"strata_int {it}_n = strata_len({it});")
        self.emit(f"for (strata_int {it}_i = 0; {it}_i < {it}_n; {it}_i++) {{")
        self.indent += 1
        self.emit(f"{elem} {cname(node.var)} = {it}[{it}_i];")
        for st in node.body:
            # One loop, three destinations: a function body, a layout being
            # written as HTML, and the same layout being drawn.
            if self.in_draw:
                self._gen_draw_node(st)
            elif self.in_layout:
                self._gen_layout_node(st)
            else:
                self._gen_stmt(st, param_names)
        self.indent -= 1
        self.emit("}")
        self.indent -= 1
        self.emit("}")

    def _html_escape(self, t):
        return t.replace("\\", "").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")

    def _gen_report(self, decl):
        """A report renders its datasource and its metrics as Markdown.

        It used to emit the title and nothing else, so `render` produced a
        one-line file that looked like it had worked. The metrics are
        evaluated with `rows` bound to the datasource result, which is what
        makes `int deals = strata_len(rows);` mean something.
        """
        title = decl.title.replace('"', '\\"')
        src = decl.datasource.source if decl.datasource else None
        self.emit_raw(f"\nvoid {decl.name}_render(FILE* _out) {{")

        if src is None or src not in self.schemas:
            # The checker has already reported an unknown or missing table.
            self.emit_raw(f'    fprintf(_out, "# {title}\\n");')
            self.emit_raw("}")
            return

        prev_vars = self.var_types
        self.var_types = dict(self.const_types); self.var_types["rows"] = f"{src}**"
        rows = self._gen_query_expr(decl.datasource, [])
        self.emit_raw(f"    {src}** rows = {rows};")
        self.emit_raw(f"    strata_int _rn = strata_len(rows);")
        self.emit_raw(f'    fprintf(_out, "# {title}\\n\\n");')

        for m in decl.metrics:
            ct = self._c_type(m.metric_type)
            val = self._gen_expr(m.expr, [])
            label = m.name.replace('"', '\\"')
            if ct == "strata_str":
                self.emit_raw(f'    fprintf(_out, "- {label}: %s\\n", (strata_str)({val}));')
            elif ct == "strata_float":
                self.emit_raw(f'    fprintf(_out, "- {label}: %.17g\\n", (double)({val}));')
            else:
                self.emit_raw(f'    fprintf(_out, "- {label}: %lld\\n", (long long)({val}));')
        if decl.metrics:
            self.emit_raw('    fprintf(_out, "\\n");')

        fields = self.schema_fields.get(src, [])
        header = " | ".join(f.name for f in fields)
        rule = " | ".join("---" for _ in fields)
        self.emit_raw(f'    fprintf(_out, "| {header} |\\n| {rule} |\\n");')
        self.emit_raw("    for (strata_int _i = 0; _i < _rn; _i++) {")
        self.emit_raw(f"        {src}* _row = rows[_i];")
        parts, args = [], []
        for f in fields:
            ct = self._c_type(f.field_type)
            if ct == "strata_str":
                parts.append("%s"); args.append(f"_row->{f.name}")
            elif ct == "strata_float":
                parts.append("%.17g"); args.append(f"(double)_row->{f.name}")
            else:
                parts.append("%lld"); args.append(f"(long long)_row->{f.name}")
        fmt = " | ".join(parts)
        arglist = ("".join(", " + a for a in args))
        self.emit_raw(f'        fprintf(_out, "| {fmt} |\\n"{arglist});')
        self.emit_raw("    }")
        self.emit_raw(f'    fprintf(_out, "\\n%lld row(s).\\n", (long long)_rn);')
        self.emit_raw("}")
        self.var_types = prev_vars

    def _gen_function(self, fn):
        rt = self._c_type(fn.return_type) if fn.return_type else "void"
        if fn.kind == "def": rt = "void"
        params = ", ".join(self._c_param(p) for p in fn.params) if fn.params else "void"
        self.func_returns[fn.name] = rt
        self.var_types = dict(self.const_types)
        self.borrowed_scalars = set()
        for p in fn.params:
            ct = self._c_type(p.param_type)
            if p.borrow and not ct.endswith("*"):
                self.borrowed_scalars.add(p.name)
            self.var_types[p.name] = ct
        # Collect param names for native substitution
        param_names = [p.name for p in fn.params]
        if self.target == "wasm" and fn.kind != "foreign":
            # Every top-level function is part of the module's interface; a
            # wasm module has no main() to start from.
            self.emit_raw(f'\n__attribute__((export_name("{fn.name}")))')
        self.emit_raw(f"\n{rt} {cname(fn.name)}({params}) {{}}"
                      if False else f"\n{rt} {cname(fn.name)}({params}) {{")
        self.indent = 1
        for stmt in fn.body:
            self._gen_stmt(stmt, param_names)
        self.indent = 0
        self.emit_raw("}")

    def _gen_stmt(self, stmt, param_names=None):
        if param_names is None: param_names = []

        # Handle native blocks — CallExpr with callee="native"
        if isinstance(stmt, InsertStmt):
            self._gen_insert(stmt, param_names); return

        if isinstance(stmt, ExprStmt) and isinstance(stmt.expr, CallExpr):
            if stmt.expr.callee == "native":
                if stmt.expr.args and isinstance(stmt.expr.args[0], StrLiteral):
                    raw_c = stmt.expr.args[0].value
                    raw_c = subst_native(raw_c, param_names)
                    # Emit as-is, preserving all newlines
                    self.emit_raw(raw_c)
                return

        if isinstance(stmt, VarDecl):
            self._gen_var_decl(stmt, param_names)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                self.emit(f"return {self._gen_expr(stmt.value, param_names)};")
            else:
                self.emit("return;")
        elif isinstance(stmt, IfStmt):
            self._gen_if(stmt, param_names)
        elif isinstance(stmt, AssignStmt):
            tgt = self._gen_expr(stmt.target, param_names)
            val = self._gen_expr(stmt.value, param_names)
            self.emit(f"{tgt} = {val};")
        elif isinstance(stmt, WhileStmt):
            self.emit(f"while ({self._gen_expr(stmt.condition, param_names)}) {{")
            self.indent += 1
            for st in stmt.body: self._gen_stmt(st, param_names)
            self.indent -= 1
            self.emit("}")
        elif isinstance(stmt, ForStmt):
            self._gen_for(stmt, param_names)
        elif isinstance(stmt, ScanStmt):
            self._gen_scan(stmt, param_names)
        elif isinstance(stmt, AppendStmt):
            self._gen_append(stmt, param_names)
        elif isinstance(stmt, RewriteStmt):
            self._gen_rewrite(stmt, param_names)
        elif isinstance(stmt, DropStmt):
            # Outside a rewrite the checker has nothing to object to and the
            # generator has nowhere to jump, so it is a statement that does
            # nothing rather than a compile error. Worth revisiting.
            if self.rewrite_depth:
                self.emit(f"{{ _wdrop{self.rewrite_depth} = 1; "
                          f"goto _wnext{self.rewrite_depth}; }}")
        elif isinstance(stmt, ForInStmt):
            self._gen_for_in(stmt, param_names)
        elif isinstance(stmt, DeleteStmt):
            self._gen_delete(stmt, param_names)
        elif isinstance(stmt, BreakStmt):
            self.emit("break;")
        elif isinstance(stmt, ContinueStmt):
            self.emit("continue;")
        elif isinstance(stmt, PrintStmt):
            val = self._gen_expr(stmt.value, param_names)
            self.emit(f'printf("%s\\n",(strata_str)({val}));')
        elif isinstance(stmt, TableIOStmt):
            fn = "__save" if stmt.op == "save" else "__load"
            where = ""
            if stmt.op == "load" and getattr(stmt, "cond", None) is not None:
                if stmt.table in self.schemas:
                    self._validate_query_columns(stmt.cond, stmt.table, stmt.line)
                where = self._sql_where(stmt.cond, stmt.table) or ""
            if fn == "__load":
                self.emit(f'{stmt.table}{fn}("{stmt.path}", "{where}");')
            else:
                self.emit(f'{stmt.table}{fn}("{stmt.path}");')
            if stmt.op == "load" and getattr(stmt, "cond", None) is not None:
                # The database has already applied the WHERE when it could be
                # translated. This pass is what makes the two stores agree:
                # a file has no WHERE, and a condition SQL could not express
                # is filtered here for both.
                t = stmt.table
                self.emit("{")
                self.indent += 1
                self.emit("strata_int _kept = 0;")
                self.emit(f"for (strata_int _i = 0; _i < {t}__count; _i++) {{")
                self.indent += 1
                self.emit(f"{t}* _row = {t}__rows[_i];")
                prev = self.query_row_type
                self.query_row_type = t
                cond = self._gen_expr(stmt.cond, param_names)
                self.query_row_type = prev
                self.emit(f"if ({cond}) {{ {t}__rows[_kept++] = _row; }}")
                self.emit("else { free(_row); }")
                self.indent -= 1
                self.emit("}")
                self.emit(f"{t}__count = _kept;")
                # What is in memory is no longer the whole file, so the
                # load-skip must not treat it as though it were. Without
                # this, a filtered load followed by a plain one returned the
                # filtered rows: the file had not changed, so the plain load
                # decided it had nothing to do.
                self.emit(f"{t}__stamp = 0;")
                self.indent -= 1
                self.emit("}")
        elif isinstance(stmt, RenderStmt):
            self.emit(f'{{ FILE* _f=fopen("{stmt.path}","w"); if(_f){{ '
                      f'{stmt.report}_render(_f); fclose(_f); }} }}')
        elif isinstance(stmt, VerifyBlock):
            self.emit(f"/* assert group: {stmt.label} */")
            for st in stmt.assertions:
                self._gen_stmt(st, param_names)
        elif isinstance(stmt, AssertStmt):
            cond = self._gen_expr(stmt.condition, param_names)
            if self.test_mode:
                # Record and continue: one failure should not hide the rest of
                # the block.
                src = _assert_text(stmt.condition).replace('"', '\\"')
                self.emit(f'__strata_assert(({cond}), "{src}", {stmt.line});')
            else:
                self.emit(f'if(!({cond})){{fprintf(stderr,"[STRATA ASSERT FAILED] line {stmt.line}\\n");exit(1);}}')
        elif isinstance(stmt, VerifyBlock):
            self.emit(f'/* verify: {stmt.label} */')
            for a in stmt.assertions:
                self._gen_stmt(a, param_names)
        elif isinstance(stmt, ExprStmt):
            self.emit(f"{self._gen_expr(stmt.expr, param_names)};")
        else:
            # A statement the generator does not know was previously emitted
            # as nothing at all: `for R in rows { ... }` in a function body
            # compiled, linked, ran and did nothing, with no diagnostic
            # anywhere. Silence is the worst answer a compiler can give.
            raise StrataCodegenError(
                f"no code generated for {type(stmt).__name__} "
                f"at line {getattr(stmt, 'line', 0)}")

    def _gen_var_decl(self, stmt, param_names):
        ctype = self._c_type(stmt.var_type)
        name = stmt.name

        if stmt.value is None:
            # Zero rather than whatever the stack held. A pointer type zeroes
            # to NULL, which the rest of the runtime already treats as empty.
            zero = "NULL" if ctype.endswith("*") else "0"
            if ctype == "strata_str":
                zero = '""'
            self.emit(f"{ctype} {cname(name)} = {zero};")
            self.var_types[name] = ctype
            return

        # Check for native block assignment
        if isinstance(stmt.value, CallExpr) and stmt.value.callee == "native":
            if stmt.value.args and isinstance(stmt.value.args[0], StrLiteral):
                raw_c = stmt.value.args[0].value
                raw_c = subst_native(raw_c, param_names)
                self.emit(f"{ctype} {cname(name)};")
                self.emit_raw("{")
                self.emit_raw(raw_c)
                self.emit_raw("}")
                self.var_types[name] = ctype
                return

        if isinstance(stmt.value, QueryExpr):
            src = stmt.value.source
            if src in self.schemas:
                self._validate_query_columns(stmt.value.condition, src, stmt.line)
            if src not in self.schemas:
                # No such table: the checker has already reported it.
                self.emit(f"{ctype} {cname(name)} = NULL;")
            else:
                self.query_row_type = src
                cond = self._gen_expr(stmt.value.condition, param_names)
                self.query_row_type = None

                # Querying into a record rather than a list means "the first
                # row that matches, or none".
                if not isinstance(stmt.var_type, ListType):
                    self.emit(f"{ctype} {cname(name)} = NULL;")
                    self.emit("{")
                    self.indent += 1
                    self.emit(f"for (strata_int _i = 0; _i < {src}__count; _i++) {{")
                    self.indent += 1
                    self.emit(f"{src}* _row = {src}__rows[_i];")
                    self.emit(f"if ({cond}) {{ {cname(name)} = _row; break; }}")
                    self.indent -= 1
                    self.emit("}")
                    self.indent -= 1
                    self.emit("}")
                    self.var_types[name] = ctype
                    return

                self.emit(f"{ctype} {cname(name)} = ({ctype})strata_list_new("
                          f"{src}__count, sizeof(void*));")
                self.emit("{")
                self.indent += 1
                self.emit("strata_int _n = 0;")
                self.emit(f"for (strata_int _i = 0; _i < {src}__count; _i++) {{")
                self.indent += 1
                self.emit(f"{src}* _row = {src}__rows[_i];")
                self.emit(f"if ({cond}) {{ {cname(name)}[_n++] = _row; }}")
                self.indent -= 1
                self.emit("}")
                self.emit(f"strata_list_set_len({cname(name)}, _n);")
                self.indent -= 1
                self.emit("}")
        else:
            val = self._gen_expr(stmt.value, param_names)
            self.emit(f"{ctype} {cname(name)} = {val};")
        self.var_types[name] = ctype

    def _gen_insert(self, stmt, param_names):
        cols = self.schemas.get(stmt.target)
        if cols is None:
            print(f"[E004] Unknown database '{stmt.target}' (line {stmt.line})",
                  file=sys.stderr)
            sys.exit(1)
        for col, _ in stmt.assignments:
            if col not in cols:
                print(f"[E004] Column '{col}' does not exist in '{stmt.target}' "
                      f"(line {stmt.line})\nHint: Valid columns: {cols}", file=sys.stderr)
                sys.exit(1)
        self.emit("{")
        self.indent += 1
        self.emit(f"{stmt.target}* _r = ({stmt.target}*)calloc(1, sizeof({stmt.target}));")
        # A str column takes a COPY. The value may be a temporary from the
        # arena, and the arena is thrown away at the next scratch_reset()
        # while the table is not -- so a table that merely pointed at one
        # would be holding freed memory. It also makes every stored string
        # the table's own, which is what lets a deleted row be freed.
        types = {fd.name: self._c_type(fd.field_type)
                 for fd in self.schema_fields.get(stmt.target, [])}
        for col, v in stmt.assignments:
            val = self._gen_expr(v, param_names)
            if types.get(col) == "strata_str":
                val = f"strata_dup({val})"
            self.emit(f"_r->{col} = {val};")
        t = stmt.target
        self.emit(f"if (!strata_table_room((void***)&{t}__rows, &{t}__cap, "
                  f'{t}__count + 1)) strata_table_full("{t}");')
        self.emit(f"{t}__rows[{t}__count++] = _r;")
        self.indent -= 1
        self.emit("}")

    def _validate_query_columns(self, cond, schema, line):
        cols = self.schemas.get(schema, [])
        if isinstance(cond, BinaryExpr):
            if isinstance(cond.left, Identifier) and cond.left.name not in cols:
                print(f"[E004] Column '{cond.left.name}' not in '{schema}'. Valid: {cols}", file=sys.stderr)
                sys.exit(1)
            self._validate_query_columns(cond.left, schema, line)
            self._validate_query_columns(cond.right, schema, line)

    def _gen_for(self, stmt, param_names):
        init = ""
        if isinstance(stmt.init, VarDecl):
            ctype = self._c_type(stmt.init.var_type)
            init = f"{ctype} {cname(stmt.init.name)} = {self._gen_expr(stmt.init.value, param_names)}"
            self.var_types[stmt.init.name] = ctype
        elif isinstance(stmt.init, AssignStmt):
            init = (f"{self._gen_expr(stmt.init.target, param_names)} = "
                    f"{self._gen_expr(stmt.init.value, param_names)}")
        cond = self._gen_expr(stmt.condition, param_names)
        step = ""
        if isinstance(stmt.step, AssignStmt):
            step = (f"{self._gen_expr(stmt.step.target, param_names)} = "
                    f"{self._gen_expr(stmt.step.value, param_names)}")
        self.emit(f"for ({init}; {cond}; {step}) {{")
        self.indent += 1
        for st in stmt.body: self._gen_stmt(st, param_names)
        self.indent -= 1
        self.emit("}")

    def _gen_if(self, stmt, param_names):
        cond = self._gen_expr(stmt.condition, param_names)
        self.emit(f"if ({cond}) {{")
        self.indent += 1
        for s in stmt.then_block: self._gen_stmt(s, param_names)
        self.indent -= 1
        if stmt.else_block:
            self.emit("} else {")
            self.indent += 1
            for s in stmt.else_block: self._gen_stmt(s, param_names)
            self.indent -= 1
        self.emit("}")

    def _expr_ctype(self, expr, param_names=None):
        """Best-effort static type of an expression, as a C type name."""
        if isinstance(expr, IntLiteral):   return "strata_int"
        if isinstance(expr, FloatLiteral): return "strata_float"
        if isinstance(expr, StrLiteral):   return "strata_str"
        if isinstance(expr, BoolLiteral):  return "strata_int"
        if isinstance(expr, Identifier):
            return self.var_types.get(expr.name)
        if isinstance(expr, UnaryExpr):
            return self._expr_ctype(expr.operand, param_names)
        if isinstance(expr, BinaryExpr):
            if expr.op in ("==","!=","<",">","<=",">=","&&","||"):
                return "strata_int"
            lt = self._expr_ctype(expr.left, param_names)
            rt = self._expr_ctype(expr.right, param_names)
            if "strata_str" in (lt, rt):   return "strata_str"
            if "strata_float" in (lt, rt): return "strata_float"
            if lt == rt:                   return lt
            return None
        if isinstance(expr, CastExpr):
            t = getattr(expr, "target_type", None)
            return f"{t}*" if t else None
        if isinstance(expr, MemberAccess):
            # Resolve the field's declared type so that conversions such as
            # str() can dispatch on it.
            ot = self._expr_ctype(expr.obj, param_names) or ""
            rec = ot[:-1] if ot.endswith("*") else ot
            for d in list(self.ast.declarations) + [d for _, m in self.modules for d in m.declarations]:
                if isinstance(d, (DatabaseDecl, ProtocolDecl)) and d.name == rec:
                    for f in d.fields:
                        if f.name == expr.member:
                            return self._c_type(f.field_type)
            return None
        if isinstance(expr, IndexExpr):
            base = self._expr_ctype(expr.target, param_names)
            # Indexing a str yields a character code.
            if base == "strata_str": return "strata_int"
            # list[T] is T* in C, so an element is the pointee.
            return base[:-1] if base and base.endswith("*") else None
        if isinstance(expr, QueryExpr):
            # A query is a list of matching rows, and list[T] is T* in C.
            return f"{expr.source}**" if expr.source in self.record_types else None
        if isinstance(expr, BorrowExpr):
            return self._expr_ctype(expr.target, param_names)
        if isinstance(expr, RenderExpr): return "strata_str"
        if isinstance(expr, CallExpr):
            if expr.callee == "str":   return "strata_str"
            if expr.callee == "int":   return "strata_int"
            if expr.callee == "float": return "strata_float"
            # An aggregate keeps its element's type, except avg which is
            # always float and count which is always int. Without this,
            # str(sum(rows.amount)) routes a double through the int converter
            # and 60.75 prints as 60.
            if expr.callee == "count": return "strata_int"
            if expr.callee == "len":   return "strata_int"
            if expr.callee == "avg":   return "strata_float"
            if expr.callee in ("sum", "min", "max"):
                return self._agg_ctype(expr, param_names)
            return self.func_returns.get(expr.callee) or BUILTIN_RETURNS.get(expr.callee)
        return None

    def _gen_expr(self, expr, param_names=None):
        if param_names is None: param_names = []
        if isinstance(expr, IntLiteral): return str(expr.value)
        if isinstance(expr, FloatLiteral): return str(expr.value)
        if isinstance(expr, StrLiteral):
            return _c_string(expr.value)
        if isinstance(expr, BoolLiteral): return "1" if expr.value else "0"
        if isinstance(expr, Identifier):
            if expr.name in self.model_names:
                return f"&{expr.name}_instance"
            if self.query_row_type and expr.name in self.schemas.get(self.query_row_type, []):
                return f"_row->{expr.name}"
            if expr.name in self.borrowed_scalars:
                return f"(*{cname(expr.name)})"
            return cname(expr.name)
        if isinstance(expr, BinaryExpr):
            l = self._gen_expr(expr.left, param_names)
            r = self._gen_expr(expr.right, param_names)
            lt = self._expr_ctype(expr.left, param_names)
            rt = self._expr_ctype(expr.right, param_names)
            if expr.op == "+":
                if lt == "strata_str" or rt == "strata_str":
                    return f"strata_concat({l},{r})"
                return f"({l} + {r})"
            # Comparing two strings with C's == compares POINTERS. It looks
            # right whenever both sides are literals in the same binary, and
            # silently fails the moment one side was read from a file or built
            # at runtime: `status == "OPEN"` matched every row before a save
            # and no row after a load.
            if expr.op in ("==", "!=") and "strata_str" in (lt, rt):
                eq = f"(strcmp({l},{r}) == 0)"
                return eq if expr.op == "==" else f"(!{eq})"
            return f"({l} {expr.op} {r})"
        if isinstance(expr, UnaryExpr):
            return f"({expr.op}{self._gen_expr(expr.operand, param_names)})"
        if isinstance(expr, CallExpr):
            # native block as expression
            if expr.callee == "native":
                if expr.args and isinstance(expr.args[0], StrLiteral):
                    raw_c = expr.args[0].value
                    raw_c = subst_native(raw_c, param_names)
                    # Strip outer whitespace but keep internal newlines
                    return f"({raw_c.strip()})"
                return "/* native */"
            return self._gen_call(expr, param_names)
        if isinstance(expr, BorrowExpr):
            inner = self._gen_expr(expr.target, param_names)
            ct = self._expr_ctype(expr.target, param_names) or ""
            # Records are already references; borrowing one passes it through.
            if ct.endswith("*") or "." in inner or "->" in inner:
                return inner
            return f"(&{inner})"
        if isinstance(expr, CastExpr):
            if expr.target_type not in self.record_types:
                known = sorted(self.record_types)
                print(f"[E004] Unknown type '{expr.target_type}' in '::' cast "
                      f"(line {getattr(expr, 'line', '?')})\n"
                      f"Hint: Declared record types: {known}", file=sys.stderr)
                sys.exit(1)
            return f"(({expr.target_type}*)({self._gen_expr(expr.source, param_names)}))"
        if isinstance(expr, PredictExpr):
            return f"strata_predict(&{expr.model}_instance,{self._gen_expr(expr.arg, param_names)})"
        if isinstance(expr, ListLiteral):
            if not expr.elements:
                return "NULL"
            # Allocated with a length header rather than written as a C99
            # compound literal, because a bare array carries no count and
            # len() then has nothing to read.
            elems = [self._gen_expr(e, param_names) for e in expr.elements]
            et = self._expr_ctype(expr.elements[0], param_names) or "strata_int"
            self.query_depth += 1
            tag = f"_lit{self.query_depth}"
            self.query_depth -= 1
            sets = " ".join(f"{tag}[{i}] = {v};" for i, v in enumerate(elems))
            return (f"({{ {et}* {tag} = ({et}*)strata_list_new({len(elems)}, "
                    f"sizeof({et})); {sets} {tag}; }})")
        if isinstance(expr, IndexExpr):
            target = self._gen_expr(expr.target, param_names)
            index = self._gen_expr(expr.index, param_names)
            # Indexing a str yields the BYTE, 0..255.
            #
            # Plain `char` is signed on x86 and unsigned on ARM, so this used
            # to answer -30 on one machine and 226 on the other for the same
            # byte of the same file. The lexer's rule for "is this a UTF-8
            # continuation byte" was written against the signed answer and was
            # simply wrong on ARM: every column number after a non-ASCII
            # character on the line came out too large. The cast makes the
            # language say what the value is instead of leaving it to the
            # machine.
            if self._expr_ctype(expr.target, param_names) == "strata_str":
                return f"((strata_int)(unsigned char){target}[{index}])"
            return f"{target}[{index}]"
        if isinstance(expr, MemberAccess):
            obj = self._gen_expr(expr.obj, param_names)
            ct = self._expr_ctype(expr.obj, param_names) or ""
            arrow = "->" if ct.endswith("*") else "."
            return f"{obj}{arrow}{expr.member}"
        if isinstance(expr, RenderExpr):
            # The layout writes to a FILE*; open_memstream makes that FILE* a
            # buffer, so the same generated function serves a file and an HTTP
            # response body.
            self.query_depth += 1
            tag = f"_r{self.query_depth}"
            self.query_depth -= 1
            args = "".join("," + self._gen_expr(a, param_names)
                           for a in getattr(expr, "args", []))
            return (f"({{ char* {tag}b = NULL; size_t {tag}n = 0; "
                    f"FILE* {tag}f = open_memstream(&{tag}b, &{tag}n); "
                    f"{expr.target}_render({tag}f{args}); "
                    f"strata_render_end({tag}f, &{tag}b); }})")
        if isinstance(expr, QueryExpr):
            return self._gen_query_expr(expr, param_names)
        if isinstance(expr, TableIOStmt):
            # Storage as a value: 1 when it worked, 0 when it did not. The
            # machinery underneath has always known; the language used to
            # throw the answer away.
            if expr.op == "save":
                return f'{expr.table}__save("{expr.path}")'
            where = ""
            if getattr(expr, "cond", None) is not None:
                if expr.table in self.schemas:
                    self._validate_query_columns(expr.cond, expr.table, expr.line)
                where = self._sql_where(expr.cond, expr.table) or ""
            call = f'{expr.table}__load("{expr.path}", "{where}")'
            if getattr(expr, "cond", None) is None:
                return call
            # A filtered load used as a value still has to apply the part of
            # the filter SQL could not express, and still has to say whether
            # the load itself worked.
            t = expr.table
            prev = self.query_row_type
            self.query_row_type = t
            cond = self._gen_expr(expr.cond, param_names)
            self.query_row_type = prev
            return (f"({{ strata_int _lok = {call}; strata_int _kept = 0; "
                    f"for (strata_int _i = 0; _i < {t}__count; _i++) {{ "
                    f"{t}* _row = {t}__rows[_i]; "
                    f"if ({cond}) {{ {t}__rows[_kept++] = _row; }} "
                    f"else {{ free(_row); }} }} "
                    f"{t}__count = _kept; {t}__stamp = 0; _lok; }})")
        if isinstance(expr, DeleteStmt):
            # How many rows went, which is the useful answer — a delete that
            # matched nothing is not a failure, it is a zero.
            src = expr.table
            if src not in self.schemas:
                return "0"
            self._validate_query_columns(expr.condition, src, expr.line)
            prev = self.query_row_type
            self.query_row_type = src
            cond = self._gen_expr(expr.condition, param_names)
            self.query_row_type = prev
            return (f"({{ strata_int _kept = 0; "
                    f"for (strata_int _di = 0; _di < {src}__count; _di++) {{ "
                    f"{src}* _row = {src}__rows[_di]; "
                    f"if (!({cond})) {{ {src}__rows[_kept++] = _row; }}"
                    f" else {{ strata_retire(_row, {src}__row_free); }} }} "
                    f"strata_int _gone = {src}__count - _kept; "
                    f"{src}__count = _kept; _gone; }})")
        # An expression with no rule used to become the literal 0. A program
        # could compile, run, and quietly take the wrong branch -- which is
        # exactly what `if (save Order to url)` did before this function knew
        # about storage. Unhandled is now a compile error, as it already was
        # for statements.
        raise StrataCodegenError(
            f"no code generated for {type(expr).__name__} at line "
            f"{getattr(expr, 'line', '?')}")

    def _agg_ctype(self, expr, param_names):
        """The C type sum/min/max yields: that of the values being aggregated."""
        if not expr.args:
            return "strata_float"
        arg = expr.args[0]
        if isinstance(arg, MemberAccess):
            base_ct = self._expr_ctype(arg.obj, param_names) or ""
            row = base_ct[:-2] if base_ct.endswith("**") else ""
            for f in self.schema_fields.get(row, []):
                if f.name == arg.member:
                    return self._c_type(f.field_type)
            return "strata_float"
        ct = self._expr_ctype(arg, param_names) or ""
        return "strata_float" if ct == "strata_float*" else "strata_int"

    AGG_KIND = {"sum": 0, "avg": 1, "min": 2, "max": 3}

    def _gen_aggregate(self, expr, param_names):
        """count(), and sum/avg/min/max over a list or a column projection.

        One runtime function serves every schema: for a projection it is given
        the byte offset of the column inside the row, so it can read the field
        without knowing the type it came from.
        """
        name = expr.callee
        if not expr.args:
            return "0"
        arg = expr.args[0]
        if name == "count":
            return f"strata_len({self._gen_expr(arg, param_names)})"

        kind = self.AGG_KIND[name]
        if isinstance(arg, MemberAccess):
            base_ct = self._expr_ctype(arg.obj, param_names) or ""
            row = base_ct[:-2] if base_ct.endswith("**") else ""
            fields = {f.name: f for f in self.schema_fields.get(row, [])}
            fd = fields.get(arg.member)
            if fd is not None:
                elem = "f" if self._c_type(fd.field_type) == "strata_float" else "i"
                target = self._gen_expr(arg.obj, param_names)
                call = (f"strata_agg({target}, {kind}, '{elem}', "
                        f"(long)offsetof({row}, {arg.member}))")
                if name == "avg" or elem == "f":
                    return call
                return f"((strata_int)({call}))"

        # A plain list of numbers: the elements are the values.
        target = self._gen_expr(arg, param_names)
        ct = self._expr_ctype(arg, param_names) or ""
        elem = "f" if ct == "strata_float*" else "i"
        call = f"strata_agg({target}, {kind}, '{elem}', -1)"
        if name == "avg" or elem == "f":
            return call
        return f"((strata_int)({call}))"

    def _gen_query_expr(self, expr, param_names):
        """A query used where a value is expected, not on the right of a
        declaration. It becomes a statement expression that collects the
        matching rows into a NULL-terminated array and yields it, so
        `len(Orders <- [id > 0])` means what it reads as.
        """
        src = expr.source
        if src not in self.schemas:
            # The checker has already reported E004; keep going so it can
            # report the rest of the file.
            return "NULL"
        self._validate_query_columns(expr.condition, src, expr.line)
        self.query_depth += 1
        tag = f"_q{self.query_depth}"
        prev = self.query_row_type
        self.query_row_type = src
        cond = self._gen_expr(expr.condition, param_names)
        self.query_row_type = prev
        self.query_depth -= 1
        return (f"({{ {src}** {tag} = ({src}**)strata_list_new("
                f"{src}__count, sizeof(void*)); strata_int {tag}n = 0; "
                f"for (strata_int {tag}i = 0; {tag}i < {src}__count; {tag}i++) {{ "
                f"{src}* _row = {src}__rows[{tag}i]; "
                f"if ({cond}) {{ {tag}[{tag}n++] = _row; }} }} "
                f"strata_list_set_len({tag}, {tag}n); {tag}; }})")

    def _gen_call(self, expr, param_names):
        if expr.callee == "str":
            # str() must dispatch on the argument: routing a float through the
            # integer converter silently truncates it, so 91.4 printed as 91.
            at = self._expr_ctype(expr.args[0], param_names)
            conv = "strata_float_to_str" if at == "strata_float" else "strata_int_to_str"
            return f"{conv}({self._gen_expr(expr.args[0], param_names)})"
        if expr.callee == "int":   return f"((strata_int)({self._gen_expr(expr.args[0], param_names)}))"
        if expr.callee == "float": return f"((strata_float)({self._gen_expr(expr.args[0], param_names)}))"
        if expr.callee == "len":
            return f"strata_len({self._gen_expr(expr.args[0], param_names)})"
        if expr.callee in ("sum", "avg", "min", "max", "count"):
            return self._gen_aggregate(expr, param_names)
        args = ", ".join(self._gen_expr(a, param_names) for a in expr.args)
        return f"{cname(expr.callee)}({args})"

    def _c_type(self, t):
        if t is None: return "void"
        if isinstance(t, PrimitiveType):
            mapped = {"int":"strata_int","float":"strata_float","str":"strata_str",
                      "void":"void","bool":"strata_bool"}.get(t.name)
            if mapped: return mapped
            return f"{t.name}*" if t.name in self.record_types else t.name
        if isinstance(t, ListType): return f"{self._c_type(t.element_type)}*"
        if isinstance(t, TensorType): return "double*"
        return "void*"

    def _c_param(self, p):
        ct = self._c_type(p.param_type)
        # A record is already a pointer; '&' on it is a no-op, not a double
        # indirection.
        star = "*" if (p.borrow and not ct.endswith("*")) else ""
        return f"{ct}{star} {cname(p.name)}"

# Import sources backed by a directory in the project tree. `std` is the
# bundled standard library; `compiler` lets the self-hosting sources import one
# another. Anything else (hub, python_engine, ...) is an external registry with
# no local checkout.
# `app` is the project's own src/ directory: an application is more than
# one file, and without a project-local source every module of it would
# have to live in std/.
LOCAL_SOURCES = ("std", "compiler", "app")

def _project_root(src_dir):
    """The nearest directory at or above `src_dir` holding a Strata.toml."""
    if not src_dir:
        return None
    here = os.path.abspath(src_dir)
    for _ in range(8):
        if os.path.isfile(os.path.join(here, "Strata.toml")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return None


def _resolve_dependency(imp, app_root):
    """A module from a declared dependency, once `strata deps` has fetched it.

    The compiler only looks in .strata/deps/<name>/. It does not read
    Strata.toml, resolve versions or reach the network: a build is the same
    whether or not anything has moved in someone else's repository since.
    """
    proj = _project_root(app_root)
    if proj is None:
        return None
    leaf = imp.name.split(".")[-1]
    base = os.path.join(proj, ".strata", "deps", imp.source)
    for cand in (os.path.join(base, "src", leaf + ".sta"),
                 os.path.join(base, leaf + ".sta")):
        if os.path.isfile(cand):
            return cand
    return None


def _resolve_module(imp, search_root, app_root=None):
    """Map an ImportDecl onto a .sta file path, or None if not locally resolvable.

    `import core.io from std;`   -> <root>/std/io.sta
    `import io from std;`        -> <root>/std/io.sta
    `import lexer from compiler;`-> <root>/compiler/lexer.sta
    `import schema from app;`    -> <dir of the file being compiled>/schema.sta
    `import money from finance;` -> <project>/.strata/deps/finance/{src/,}money.sta
    """
    if imp.source not in LOCAL_SOURCES:
        return _resolve_dependency(imp, app_root)
    leaf = imp.name.split(".")[-1]
    if imp.source == "app":
        if app_root is None:
            return None
        cand = os.path.join(app_root, leaf + ".sta")
        if os.path.isfile(cand):
            return cand
        # A project's tests do not sit beside its sources. `app` therefore also
        # looks in a sibling src/, so tests/rules_test.sta can import the
        # modules it tests.
        sibling = os.path.join(app_root, "..", "src", leaf + ".sta")
        return sibling if os.path.isfile(sibling) else None
    nested = os.path.join(search_root, imp.source, *imp.name.split("."))
    for cand in (nested + ".sta", os.path.join(search_root, imp.source, leaf + ".sta")):
        if os.path.isfile(cand):
            return cand
    return None

def link_flags_libs(link_flags):
    """The library names inside a list of -l flags.

    `link_flags` is what the foreign declarations asked for, already formatted
    for the compiler. This reads them back so the build can react to WHAT is
    being linked, not just pass it along."""
    return [f[2:] for f in link_flags if f.startswith("-l")]


def resolve_imports(ast, source_path, verbose=False):
    """Transitively parse every locally-resolvable import.

    Returns (modules, unresolved) with modules in dependency order (deepest
    first) so a module's own dependencies are emitted before it.
    """
    # The stdlib ships with the compiler, so its location must not depend on
    # where the file being compiled happens to sit. Prefer the install root,
    # then fall back to the source tree for an in-project override.
    src_dir = os.path.dirname(os.path.abspath(source_path))
    candidates = [
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # install root
        os.path.dirname(src_dir),
        src_dir,
        os.getcwd(),
    ]
    search_root = next((c for c in candidates
                        if os.path.isdir(os.path.join(c, "std"))), src_dir)
    # An `app` import resolves beside the file being compiled, so a project
    # can be more than one file without putting its modules in std/.
    app_root = src_dir
    modules, unresolved, seen = [], [], set()
    # The project's own modules, with their paths, so a diagnostic from one of
    # them can name the file it is in.
    app_modules = []

    def walk(node_ast):
        for imp in node_ast.imports:
            path = _resolve_module(imp, search_root, app_root)
            if path is None:
                key = f"{imp.name} from {imp.source}"
                if key not in unresolved:
                    unresolved.append(key)
                continue
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            try:
                mod_ast = parse_file(path)
            except (Exception, SystemExit) as e:
                # A broken stdlib module degrades to a link-time undefined
                # symbol rather than failing the importing file. A broken
                # compiler/ module is different: skipping it silently produces
                # a baffling C error about a missing type instead of naming the
                # real syntax error, so that case is fatal.
                if imp.source == "compiler":
                    print(f"[STRATA IMPORT ERROR] '{path}' failed to parse:\n  {e}",
                          file=sys.stderr)
                    sys.exit(1)
                print(f"[STRATA IMPORT WARNING] skipping '{path}': {e}", file=sys.stderr)
                continue
            walk(mod_ast)
            modules.append((imp.name, mod_ast))
            if imp.source == "app":
                app_modules.append((os.path.relpath(path, os.getcwd())
                                    if not os.path.isabs(source_path)
                                    else path, mod_ast))
            if verbose:
                print(f"  import: {imp.name} from {imp.source} -> {os.path.relpath(path, search_root)}")
    walk(ast)
    # The root file's own unresolved imports, as nodes, so a diagnostic can
    # point at the line rather than at the file.
    root_unresolved = [imp for imp in ast.imports
                       if _resolve_module(imp, search_root, app_root) is None]
    return modules, unresolved, root_unresolved, app_modules

_TAXONOMY_CACHE = None


def load_taxonomy():
    """ERROR_TAXONOMY.json, keyed by error code. Empty dict if unavailable."""
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "ERROR_TAXONOMY.json")
        try:
            with open(path) as f:
                _TAXONOMY_CACHE = json.load(f).get("taxonomy", {})
        except Exception:
            _TAXONOMY_CACHE = {}
    return _TAXONOMY_CACHE


def diagnostics_payload(source_path, errors, stage):
    """Structured diagnostics for machine consumption.

    This is what makes the error matrix actionable by a repair agent: each
    diagnostic carries its taxonomy classification and remediation strategy
    alongside the location, so a caller never has to scrape human-readable
    compiler text.
    """
    tax = load_taxonomy()
    out = []
    for e in errors:
        meta = tax.get(e.code, {})
        out.append({
            "code": e.code,
            # Which file the diagnostic is in. The repair loop needs this to
            # know which file to patch: an application is several files, and
            # the one being compiled is often not the one that is wrong.
            "file": e.file or source_path,
            "classification": meta.get("classification", ""),
            "severity": meta.get("severity", "CRITICAL_HALT"),
            "message": e.message,
            "line": e.line,
            "column": e.col,
            "hint": e.hint,
            "remediation_strategy": meta.get("ai_remediation_strategy", ""),
        })
    # An advisory is reported but does not stop the build, so it must not make
    # `ok` false: a repair loop reads that field to decide whether to keep
    # patching, and it cannot fix a dependency that is genuinely external.
    halting = [d for d in out if d["severity"] != "ADVISORY"]
    return {"file": source_path, "stage": stage,
            "ok": not halting, "error_count": len(halting),
            "advisory_count": len(out) - len(halting), "diagnostics": out}


def compile_sta(source_path, output_path, target="native", verbose=False,
                json_diagnostics=False, test_mode=False):
    if not json_diagnostics:
        print(f"[Strata Stage 0] Compiling '{source_path}'...")
    try:
        ast = parse_file(source_path)
    except (LexError, ParseError) as e:
        if json_diagnostics:
            code = "E000"
            print(json.dumps({"file": source_path, "stage": "parse", "ok": False,
                              "error_count": 1,
                              "diagnostics": [{
                                  "code": code,
                                  "classification": "Syntax Violation",
                                  "severity": "CRITICAL_HALT",
                                  "message": str(e),
                                  "line": getattr(e, "line", 0),
                                  "column": getattr(e, "col", 0),
                                  "hint": "",
                                  "remediation_strategy":
                                      "Correct the token sequence so it matches the "
                                      "grammar in LANGUAGE_SPECIFICATION.md.",
                              }]}, indent=2))
            sys.exit(1)
        print(str(e), file=sys.stderr); sys.exit(1)
    if verbose:
        print(f"  AST: {len(ast.imports)} imports, {len(ast.declarations)} decls, {len(ast.functions)} functions")
    # Type-check before generating code. Without this the E001-E006 taxonomy
    # only ever runs under `strata check`, and a type error reaches the user as
    # a C compiler diagnostic instead of a Strata one.
    #
    # Imports are resolved BEFORE the check, not after, so the checker knows
    # which names are reachable. Without that it cannot tell a typo from a
    # call into std/, and an undefined function reaches the user as a C linker
    # error naming a C symbol — invisible to --json and to the repair loop.
    # An import with no local checkout means the picture is incomplete, so the
    # checker is left lenient rather than guessing.
    modules, unresolved, root_unresolved, app_modules = resolve_imports(
        ast, source_path, verbose)
    try:
        from compiler.typechecker import TypeChecker
        errors = TypeChecker(ast, filename=source_path,
                             modules=None if root_unresolved else modules,
                             unresolved_imports=root_unresolved,
                             project_modules=app_modules).check()
    except ImportError:
        errors = []
    if json_diagnostics:
        payload = diagnostics_payload(source_path, errors, "typecheck")
        print(json.dumps(payload, indent=2))
        sys.exit(1 if errors else 0)
    tax = load_taxonomy()
    advisories = [e for e in errors
                  if tax.get(e.code, {}).get("severity") == "ADVISORY"]
    halting = [e for e in errors if e not in advisories]
    for a in advisories:
        print(f"[Strata Check] advisory: {a}", file=sys.stderr)
    if halting:
        print(f"[Strata Check] {len(halting)} error(s) found:", file=sys.stderr)
        for e in halting:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    # Root-level unresolved imports are reported as E007 by the checker above.
    # These are the transitive ones — a module we imported has an import we
    # could not follow — which no single line of this file can point at.
    root_keys = {f"{i.name} from {i.source}" for i in root_unresolved}
    for u in unresolved:
        if u in root_keys:
            continue
        print(f"[STRATA IMPORT] '{u}' is an external module reached through an "
              f"import of this file; its symbols must be provided at link time.",
              file=sys.stderr)
    gen = CodeGen(ast, source_path, modules, target=target, test_mode=test_mode)
    c_source = gen.generate()
    # There is no libcrypt on macOS: crypt(3) is in libSystem, so asking for
    # it is a link error rather than a no-op.
    _libs = [l for l in dict.fromkeys(gen.link_libs)
             if not (l == "crypt" and platform.system() == "Darwin")]
    link_flags = [f"-l{l}" for l in _libs]
    base = os.path.splitext(source_path)[0]
    c_path = base + ".c"
    with open(c_path, "w") as f: f.write(c_source)
    if not json_diagnostics:
        print(f"  C source: {c_path}")
    # STRATA_CC pins the backend compiler, so a build can be reproduced against
    # a specific toolchain rather than whichever one happens to be installed.
    forced = os.environ.get("STRATA_CC")
    candidates = (forced,) if forced else ("clang", "gcc", "cc")
    cc = next((c for c in candidates
               if subprocess.run(["which", c], capture_output=True).returncode == 0), None)
    if not cc: print("[STRATA ERROR] No C compiler found.", file=sys.stderr); sys.exit(1)
    # A unit with no main() is a library, not a program: link it as an object
    # file rather than asking the linker for an entry point it cannot have.
    # In test mode the generated entry point is main(), so the unit is a
    # program even when the source declares no main of its own.
    is_library = (not test_mode) and not any(fn.name == "main" for fn in ast.functions)
    # Unresolved externals are reported by the import pass and left to the
    # linker. C99 removed implicit declarations and clang 16+ makes them a hard
    # error, so without this every program calling an unresolved symbol fails
    # to build on clang while succeeding on gcc.
    # The backend C compiler is part of the toolchain, and the toolchain must
    # not depend on which one is installed. gcc 11 only warns where clang 16+
    # and gcc 14 make an error, so a bug that failed CI built fine on a machine
    # with an older gcc. These make the strict ones' errors errors everywhere.
    portability = ["-Wno-implicit-function-declaration",
                   "-Werror=int-conversion",
                   "-Werror=incompatible-pointer-types",
                   "-Werror=return-type",
                   # glibc declares crypt(3) in <unistd.h> only under this.
                   # macOS declares it there regardless and ignores the flag.
                   "-D_GNU_SOURCE"]
    # Linking libpq is what turns the Postgres table backend on. The flag is
    # derived from the program's own `foreign ... link "pq"` -- which comes
    # from importing `postgres from std` -- so no program that does not ask
    # for a database carries a libpq dependency or the code that uses it.
    #
    # pg_config is asked where the headers and libraries are rather than
    # guessing /usr/include/postgresql: the answer differs between Debian,
    # Red Hat and Homebrew, and a hardcoded path is a build that works on the
    # machine it was written on.
    if any(l == "pq" for l in link_flags_libs(link_flags)):
        portability = portability + ["-DSTRATA_POSTGRES"]
        for flag, arg in (("-I", "--includedir"), ("-L", "--libdir")):
            try:
                d = subprocess.run(["pg_config", arg], capture_output=True,
                                   text=True).stdout.strip()
            except FileNotFoundError:
                d = ""
            if d:
                portability = portability + [flag + d]
        # Debian keeps libpq-fe.h in a subdirectory of the include dir.
        portability = portability + ["-I/usr/include/postgresql"]
    if target == "wasm":
        flags = ([cc,"-Oz","--target=wasm32","-nostdlib",
                  "-Wl,--no-entry","-Wl,--strip-all",
                  "-Wl,--export-dynamic","-Wl,--allow-undefined"] + portability +
                 ["-o",output_path,c_path])
    elif is_library:
        if not output_path.endswith(".o"):
            output_path += ".o"
        flags = [cc,"-O2","-c"] + portability + ["-o",output_path,c_path]
    else:
        flags = [cc,"-O2"] + portability + ["-o",output_path,c_path,"-lm"] + link_flags
    if verbose: print(f"  CC: {' '.join(flags)}")
    r = subprocess.run(flags, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[STRATA C ERROR]\n{r.stderr}", file=sys.stderr); sys.exit(1)
    print(f"  {'Object' if is_library and target != 'wasm' else 'Binary'}: {output_path}")
    if not json_diagnostics:
        print(f"[Strata Stage 0] Done. OK")

def parse_file(path):
    toks = tokenise_file(path)
    return Parser(toks).parse()

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Strata Stage 0 Bootstrap Compiler")
    ap.add_argument("file")
    ap.add_argument("-o","--output",default=None)
    ap.add_argument("--target",choices=["native","wasm","c"],default="native")
    ap.add_argument("--ast",action="store_true")
    ap.add_argument("--emit-c",action="store_true")
    ap.add_argument("-v","--verbose",action="store_true")
    ap.add_argument("--test",action="store_true",
                    help="build a runner for this file's verify blocks")
    ap.add_argument("--json",action="store_true",
                    help="emit machine-readable diagnostics for repair agents")
    args = ap.parse_args()
    if args.ast:
        import json; ast=parse_file(args.file); print(json.dumps(ast.to_dict(),indent=2)); return
    base = os.path.splitext(args.file)[0]
    out = args.output or base
    # `-o build/orders` creates build/ if it is not there. The linker's error
    # for a missing directory is "cannot open output file", which reads like a
    # permission problem and is not one; `strata build` had a mkdir of its own,
    # so the compiler was only ever missing it when called directly — which is
    # exactly what a Dockerfile does.
    out_dir = os.path.dirname(os.path.abspath(out))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    if args.emit_c:
        # Imports must be resolved here exactly as in a real build; emitting
        # only the root unit produces C that cannot link.
        try: ast=parse_file(args.file)
        except (LexError,ParseError) as e: print(str(e),file=sys.stderr); sys.exit(1)
        modules, _, _, _ = resolve_imports(ast, args.file, args.verbose)
        print(CodeGen(ast,args.file,modules,target=args.target).generate()); return
    compile_sta(args.file, out, target=args.target, verbose=args.verbose,
                json_diagnostics=args.json, test_mode=args.test)

if __name__=="__main__": main()
