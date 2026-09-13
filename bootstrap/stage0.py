#!/usr/bin/env python3
# STRATA — STAGE 0 BOOTSTRAP COMPILER
# Compiles .sta source files to C via Python bootstrap
# Once compiler/compiler.sta compiles itself, this file is retired.
from __future__ import annotations
import sys, os, re, json, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from compiler.lexer import Lexer, Token, TT, LexError, tokenise_file
from compiler.parser import (
    Parser, ParseError, CompilationUnit,
    DatabaseDecl, ProtocolDecl, ModelDecl, ReportDecl,
    FunctionDecl, ImportDecl, FieldDecl, Param, InsertStmt,
    LayoutDecl, Element, Prop, ForInStmt, ForeignDecl, TableIOStmt,
    VarDecl, ReturnStmt, IfStmt, PrintStmt, ExprStmt, RenderStmt, VerifyBlock,
    AssignStmt, WhileStmt, ForStmt, BreakStmt, ContinueStmt, IndexExpr,
    AssertStmt, RenderStmt, VerifyBlock,
    BinaryExpr, UnaryExpr, CallExpr, BorrowExpr, CastExpr,
    PredictExpr, QueryExpr, ListLiteral, MemberAccess,
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
    "strata_tensor": "double*", "strata_predict": "double*",
    "strata_tensor_add": "double*",
    "strata_tensor_get": "strata_float", "strata_tensor_set": "void",
}


def cname(name):
    """A C-safe spelling of a Strata identifier."""
    return name + "_" if name in C_RESERVED else name


# Native block variable substitution
def subst_native(code: str, param_names: list) -> str:
    """Replace $varname with the C variable name in native blocks."""
    # Replace $varname with varname
    result = re.sub(r'\$([a-zA-Z_][a-zA-Z0-9_]*)', lambda m: m.group(1), code)
    return result

class CodeGen:
    def __init__(self, ast, source_path, modules=None, target="native"):
        self.target = target
        self.ast = ast
        self.source_path = source_path
        self.modules = modules or []
        self.out = []
        self.indent = 0
        self.schemas = {}
        self.func_returns = {}
        self.var_types = {}
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
                elif isinstance(d, ModelDecl):
                    self.model_names.add(d.name)

        for mod_name, unit in units:
            is_root = unit is self.ast
            decls = [d for d in unit.declarations if getattr(d, "name", None) not in emitted_decls]
            fns = [f for f in unit.functions if f.name not in emitted_fns]
            if not is_root and (decls or fns):
                self.emit_raw(f"\n/* ── module {mod_name} ── */")
            for d in decls:
                emitted_decls.add(getattr(d, "name", None))
                self._forward_declare(d)
            for d in decls:
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
                    self._gen_verify(d)

        # A module with no main() is a library unit: emitting the C entry point
        # would force an undefined reference to strata_main.
        if self.target != "wasm" and any(fn.name == "main" for fn in self.ast.functions):
            self.emit_raw("""
int main(int argc, char** argv) {
    __strata_argc = argc;
    __strata_argv = argv;
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
        if isinstance(decl, DatabaseDecl):
            self._gen_struct(decl.name, decl.fields)
            self.schemas[decl.name] = [f.name for f in decl.fields]
            self._gen_table_storage(decl.name)
            self._gen_table_io(decl.name, decl.fields)
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


    def _gen_table_storage(self, name):
        """Backing store for a database block.

        Emitted after the struct so the row type is complete."""
        self.emit_raw(f"static {name}* {name}__rows[STRATA_TABLE_CAP];")
        self.emit_raw(f"static strata_int {name}__count = 0;")

    def _gen_table_io(self, name, fields):
        """Serialisers generated from the schema.

        Field order is the declaration order, which is also the contract: a
        file written by one schema is not readable by another.
        """
        self.emit_raw(f"static strata_int {name}__save(strata_str path) {{")
        self.emit_raw(f'    FILE* f = fopen(path, "w"); if (!f) return 0;')
        self.emit_raw(f"    for (strata_int i = 0; i < {name}__count; i++) {{")
        self.emit_raw(f"        {name}* r = {name}__rows[i];")
        for i, fd in enumerate(fields):
            sep = "" if i == 0 else '        fputc(0x09, f);\n'
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
        self.emit_raw("    fclose(f); return 1;")
        self.emit_raw("}")

        self.emit_raw(f"static strata_int {name}__load(strata_str path) {{")
        self.emit_raw(f'    FILE* f = fopen(path, "r"); if (!f) return 0;')
        self.emit_raw("    char buf[4096]; int more;")
        self.emit_raw(f"    {name}__count = 0;")
        self.emit_raw("    while (1) {")
        self.emit_raw(f"        {name}* r = ({name}*)calloc(1, sizeof({name}));")
        self.emit_raw("        more = strata_read_field(f, buf, 4096);")
        self.emit_raw("        if (more < 0) { free(r); break; }")
        for i, fd in enumerate(fields):
            if i:
                self.emit_raw("        strata_read_field(f, buf, 4096);")
            ct = self._c_type(fd.field_type)
            if ct == "strata_str":
                self.emit_raw(f"        r->{fd.name} = strata_dup(buf);")
            elif ct == "strata_float":
                self.emit_raw(f"        r->{fd.name} = strtod(buf, NULL);")
            else:
                self.emit_raw(f"        r->{fd.name} = (strata_int)atoll(buf);")
        self.emit_raw(f"        if ({name}__count < STRATA_TABLE_CAP) "
                      f"{name}__rows[{name}__count++] = r;")
        self.emit_raw("    }")
        self.emit_raw("    fclose(f); return 1;")
        self.emit_raw("}")

    def _gen_struct(self, name, fields):
        self.emit_raw(f"\nstruct {name} {{")
        for f in fields:
            self.emit_raw(f"    {self._c_type(f.field_type)} {f.name};")
        self.emit_raw(f"}};")

    def _gen_model(self, decl):
        # Same layout as StrataModel in the prelude, so strata_predict can
        # read it without a cast that depends on field order.
        self.emit_raw(f"\ntypedef StrataModel {decl.name};")
        self.emit_raw(f"static {decl.name} {decl.name}_instance = {{{decl.input_type.rows},{decl.input_type.cols},{decl.output_type.rows},{decl.output_type.cols},NULL}};")

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
    }

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

    def _gen_verify(self, decl):
        """A verify block becomes a function a test driver can call."""
        safe = "".join(c if c.isalnum() else "_" for c in decl.label)[:48]
        self.emit_raw(f"\n/* verify: {decl.label} */")
        self.emit_raw(f"void __strata_verify_{safe}(void) {{")
        self.indent = 1
        self.var_types = {}
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

    def _gen_layout(self, decl):
        """A layout becomes a function that writes HTML to a stream."""
        self.emit_raw(f"\nvoid {decl.name}_render(FILE* _out) {{")
        self.indent = 1
        self.emit('fprintf(_out,"<!doctype html><meta charset=\\"utf-8\\">");')
        for st in decl.body:
            self._gen_layout_node(st)
        self.indent = 0
        self.emit_raw("}")

    def _gen_layout_node(self, node):
        if isinstance(node, Element):
            self._gen_element(node); return
        if isinstance(node, ForInStmt):
            self._gen_for_in(node); return
        if isinstance(node, IfStmt):
            self._gen_if(node, []); return
        self._gen_stmt(node, [])

    def _gen_element(self, el):
        tag = self.HTML_TAG.get(el.tag, "div")
        css = self._css_for(el)
        style = (' style=\\"' + css + '\\"') if css else ""
        if el.tag == "window":
            title = el.label.value if isinstance(el.label, StrLiteral) else el.tag
            self.emit('fprintf(_out,"<title>' + self._html_escape(title) + '</title>");')
            self.emit('fprintf(_out,"<body' + style + '>");')
            for c in el.children:
                self._gen_layout_node(c)
            self.emit('fprintf(_out,"</body>");')
            return
        self.emit('fprintf(_out,"<' + tag + style + '>");')
        if el.label is not None and el.tag != "canvas":
            if isinstance(el.label, StrLiteral):
                self.emit('fprintf(_out,"%s","' + self._html_escape(el.label.value) + '");')
            elif not isinstance(el.label, Identifier):
                # A computed label — a field from a query row, for instance.
                self.emit(f'fprintf(_out,"%s",{self._gen_expr(el.label, [])});')
        for c in el.children:
            self._gen_layout_node(c)
        self.emit('fprintf(_out,"</' + tag + '>");')

    def _gen_for_in(self, node):
        """Iterate query results.

        Queries currently evaluate to NULL — there is no database runtime — so
        this loop renders zero rows. The structure is emitted rather than
        faked, so what appears in the page is what the program actually
        produced.
        """
        coll = self._gen_expr(node.collection, [])
        ct = self._expr_ctype(node.collection, []) or ""
        elem = ct[:-1] if ct.endswith("*") else "void*"
        self.var_types[node.var] = elem
        it = f"_it_{cname(node.var)}"
        self.emit(f"for ({elem}* {it} = {coll}; {it} && *{it}; {it}++) {{")
        self.indent += 1
        self.emit(f"{elem} {cname(node.var)} = *{it};")
        for st in node.body:
            self._gen_layout_node(st)
        self.indent -= 1
        self.emit("}")

    def _html_escape(self, t):
        return t.replace("\\", "").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")

    def _gen_report(self, decl):
        self.emit_raw(f"\nvoid {decl.name}_generate(FILE* _out) {{")
        self.emit_raw(f'    fprintf(_out,"# {decl.title}\\n");')
        self.emit_raw(f"}}")

    def _gen_function(self, fn):
        rt = self._c_type(fn.return_type) if fn.return_type else "void"
        if fn.kind == "def": rt = "void"
        params = ", ".join(self._c_param(p) for p in fn.params) if fn.params else "void"
        self.func_returns[fn.name] = rt
        self.var_types = {}
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
        elif isinstance(stmt, BreakStmt):
            self.emit("break;")
        elif isinstance(stmt, ContinueStmt):
            self.emit("continue;")
        elif isinstance(stmt, PrintStmt):
            val = self._gen_expr(stmt.value, param_names)
            self.emit(f'printf("%s\\n",(strata_str)({val}));')
        elif isinstance(stmt, TableIOStmt):
            fn = "__save" if stmt.op == "save" else "__load"
            self.emit(f'{stmt.table}{fn}("{stmt.path}");')
        elif isinstance(stmt, RenderStmt):
            self.emit(f'{{ FILE* _f=fopen("{stmt.path}","w"); if(_f){{ '
                      f'{stmt.report}_render(_f); fclose(_f); }} }}')
        elif isinstance(stmt, VerifyBlock):
            self.emit(f"/* assert group: {stmt.label} */")
            for st in stmt.assertions:
                self._gen_stmt(st, param_names)
        elif isinstance(stmt, AssertStmt):
            cond = self._gen_expr(stmt.condition, param_names)
            self.emit(f'if(!({cond})){{fprintf(stderr,"[STRATA ASSERT FAILED] line {stmt.line}\\n");exit(1);}}')
        elif isinstance(stmt, RenderStmt):
            self.emit(f'{{FILE* _rf=fopen("{stmt.path}","w");{stmt.report}_generate(_rf);fclose(_rf);}}')
        elif isinstance(stmt, VerifyBlock):
            self.emit(f'/* verify: {stmt.label} */')
            for a in stmt.assertions:
                self._gen_stmt(a, param_names)
        elif isinstance(stmt, ExprStmt):
            self.emit(f"{self._gen_expr(stmt.expr, param_names)};")

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

                self.emit(f"{ctype} {cname(name)} = ({ctype})malloc("
                          f"sizeof(void*) * ({src}__count + 1));")
                self.emit("{")
                self.indent += 1
                self.emit("strata_int _n = 0;")
                self.emit(f"for (strata_int _i = 0; _i < {src}__count; _i++) {{")
                self.indent += 1
                self.emit(f"{src}* _row = {src}__rows[_i];")
                self.emit(f"if ({cond}) {{ {cname(name)}[_n++] = _row; }}")
                self.indent -= 1
                self.emit("}")
                self.emit(f"{cname(name)}[_n] = NULL;")
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
        for col, v in stmt.assignments:
            self.emit(f"_r->{col} = {self._gen_expr(v, param_names)};")
        self.emit(f"if ({stmt.target}__count < STRATA_TABLE_CAP) "
                  f"{stmt.target}__rows[{stmt.target}__count++] = _r;")
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
            return f"{expr.source}*" if expr.source in self.record_types else None
        if isinstance(expr, BorrowExpr):
            return self._expr_ctype(expr.target, param_names)
        if isinstance(expr, CallExpr):
            if expr.callee == "str":   return "strata_str"
            if expr.callee == "int":   return "strata_int"
            if expr.callee == "float": return "strata_float"
            return self.func_returns.get(expr.callee) or BUILTIN_RETURNS.get(expr.callee)
        return None

    def _gen_expr(self, expr, param_names=None):
        if param_names is None: param_names = []
        if isinstance(expr, IntLiteral): return str(expr.value)
        if isinstance(expr, FloatLiteral): return str(expr.value)
        if isinstance(expr, StrLiteral):
            esc = expr.value.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n')
            return f'"{esc}"'
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
            if expr.op == "+":
                lt = self._expr_ctype(expr.left, param_names)
                rt = self._expr_ctype(expr.right, param_names)
                if lt == "strata_str" or rt == "strata_str":
                    return f"strata_concat({l},{r})"
                return f"({l} + {r})"
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
            # C99 compound literal: gives the list backing storage so that
            # indexing reads real memory instead of dereferencing NULL.
            elems = ", ".join(self._gen_expr(e, param_names) for e in expr.elements)
            et = self._expr_ctype(expr.elements[0], param_names) or "strata_int"
            return f"({et}[]){{{elems}}}"
        if isinstance(expr, IndexExpr):
            return (f"{self._gen_expr(expr.target, param_names)}"
                    f"[{self._gen_expr(expr.index, param_names)}]")
        if isinstance(expr, MemberAccess):
            obj = self._gen_expr(expr.obj, param_names)
            ct = self._expr_ctype(expr.obj, param_names) or ""
            arrow = "->" if ct.endswith("*") else "."
            return f"{obj}{arrow}{expr.member}"
        if isinstance(expr, QueryExpr): return f"NULL/*query {expr.source}*/"
        return "0"

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
LOCAL_SOURCES = ("std", "compiler")

def _resolve_module(imp, search_root):
    """Map an ImportDecl onto a .sta file path, or None if not locally resolvable.

    `import core.io from std;`   -> <root>/std/io.sta
    `import io from std;`        -> <root>/std/io.sta
    `import lexer from compiler;`-> <root>/compiler/lexer.sta
    """
    if imp.source not in LOCAL_SOURCES:
        return None
    leaf = imp.name.split(".")[-1]
    nested = os.path.join(search_root, imp.source, *imp.name.split("."))
    for cand in (nested + ".sta", os.path.join(search_root, imp.source, leaf + ".sta")):
        if os.path.isfile(cand):
            return cand
    return None

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
    modules, unresolved, seen = [], [], set()

    def walk(node_ast):
        for imp in node_ast.imports:
            path = _resolve_module(imp, search_root)
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
            if verbose:
                print(f"  import: {imp.name} from {imp.source} -> {os.path.relpath(path, search_root)}")
    walk(ast)
    return modules, unresolved

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
            "classification": meta.get("classification", ""),
            "severity": meta.get("severity", "CRITICAL_HALT"),
            "message": e.message,
            "line": e.line,
            "column": e.col,
            "hint": e.hint,
            "remediation_strategy": meta.get("ai_remediation_strategy", ""),
        })
    return {"file": source_path, "stage": stage,
            "ok": not out, "error_count": len(out), "diagnostics": out}


def compile_sta(source_path, output_path, target="native", verbose=False,
                json_diagnostics=False):
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
    try:
        from compiler.typechecker import TypeChecker
        errors = TypeChecker(ast, filename=source_path).check()
    except ImportError:
        errors = []
    if json_diagnostics:
        payload = diagnostics_payload(source_path, errors, "typecheck")
        print(json.dumps(payload, indent=2))
        sys.exit(1 if errors else 0)
    if errors:
        print(f"[Strata Check] {len(errors)} error(s) found:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    modules, unresolved = resolve_imports(ast, source_path, verbose)
    for u in unresolved:
        print(f"[STRATA IMPORT] '{u}' is an external module with no local "
              f"checkout; its symbols must be provided at link time.", file=sys.stderr)
    gen = CodeGen(ast, source_path, modules, target=target)
    c_source = gen.generate()
    link_flags = [f"-l{l}" for l in dict.fromkeys(gen.link_libs)]
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
    is_library = not any(fn.name == "main" for fn in ast.functions)
    # Unresolved externals are reported by the import pass and left to the
    # linker. C99 removed implicit declarations and clang 16+ makes them a hard
    # error, so without this every program calling an unresolved symbol fails
    # to build on clang while succeeding on gcc.
    portability = ["-Wno-implicit-function-declaration"]
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
    ap.add_argument("--json",action="store_true",
                    help="emit machine-readable diagnostics for repair agents")
    args = ap.parse_args()
    if args.ast:
        import json; ast=parse_file(args.file); print(json.dumps(ast.to_dict(),indent=2)); return
    base = os.path.splitext(args.file)[0]
    out = args.output or base
    if args.emit_c:
        # Imports must be resolved here exactly as in a real build; emitting
        # only the root unit produces C that cannot link.
        try: ast=parse_file(args.file)
        except (LexError,ParseError) as e: print(str(e),file=sys.stderr); sys.exit(1)
        modules,_ = resolve_imports(ast, args.file, args.verbose)
        print(CodeGen(ast,args.file,modules,target=args.target).generate()); return
    compile_sta(args.file, out, target=args.target, verbose=args.verbose,
                json_diagnostics=args.json)

if __name__=="__main__": main()
