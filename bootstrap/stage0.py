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
    VarDecl, ReturnStmt, IfStmt, PrintStmt, ExprStmt,
    AssignStmt, WhileStmt, ForStmt, BreakStmt, ContinueStmt, IndexExpr,
    AssertStmt, RenderStmt, VerifyBlock,
    BinaryExpr, UnaryExpr, CallExpr, BorrowExpr, CastExpr,
    PredictExpr, QueryExpr, ListLiteral, MemberAccess,
    IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, Identifier,
    PrimitiveType, ListType, TensorType,
)

def _load_preamble():
    """The C runtime prelude, shared with the Strata-written code generator.

    Kept in compiler/runtime_preamble.c rather than inline so that both
    implementations emit identical bytes by construction. Two copies of 76
    lines of C would drift, and the codegen differential would then fail for a
    reason that has nothing to do with code generation.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "compiler", "runtime_preamble.c")
    with open(path) as f:
        return f.read()


C_PREAMBLE = _load_preamble()

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
    def __init__(self, ast, source_path, modules=None):
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
        # Parameters declared `T &x` where T is not already a pointer. They
        # arrive as T*, so every use must dereference; without this a write
        # through a borrowed scalar performs pointer arithmetic instead, and
        # is silently wrong.
        self.borrowed_scalars = set()
        self.symbol_owner = {}

    def emit(self, line=""):
        self.out.append("    " * self.indent + line)

    def emit_raw(self, line):
        self.out.append(line)

    def generate(self):
        self.emit_raw(C_PREAMBLE)

        # Imported modules first, in dependency order. Names already provided by
        # the C preamble or by an earlier module are skipped so that a symbol
        # imported down two paths is emitted exactly once.
        emitted_decls, emitted_fns = set(), set(PREAMBLE_BUILTINS)
        units = [(name, m) for name, m in self.modules] + [(None, self.ast)]

        for _, unit in units:
            for d in unit.declarations:
                if isinstance(d, (DatabaseDecl, ProtocolDecl)):
                    self.record_types.add(d.name)

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

        # A module with no main() is a library unit: emitting the C entry point
        # would force an undefined reference to strata_main.
        if any(fn.name == "main" for fn in self.ast.functions):
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
        elif isinstance(decl, ProtocolDecl):
            self._gen_struct(decl.name, decl.fields)
        elif isinstance(decl, ModelDecl):
            self._gen_model(decl)
        elif isinstance(decl, ReportDecl):
            self._gen_report(decl)

    def _gen_struct(self, name, fields):
        self.emit_raw(f"\nstruct {name} {{")
        for f in fields:
            self.emit_raw(f"    {self._c_type(f.field_type)} {f.name};")
        self.emit_raw(f"}};")

    def _gen_model(self, decl):
        self.emit_raw(f"\ntypedef struct {{ int rows_in,cols_in,rows_out,cols_out; double* weights; }} {decl.name};")
        self.emit_raw(f"static {decl.name} {decl.name}_instance = {{{decl.input_type.rows},{decl.input_type.cols},{decl.output_type.rows},{decl.output_type.cols},NULL}};")

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
        self.emit_raw(f"\n{rt} {cname(fn.name)}({params}) {{")
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
            self.emit(f"{ctype} {cname(name)} = NULL; /* query:{src} */")
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
        vals = ", ".join(f"{c}={self._gen_expr(v, param_names)}"
                         for c, v in stmt.assignments)
        self.emit(f"/* insert into {stmt.target}: {vals} */")

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
            return self.func_returns.get(expr.callee)
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
        if expr.callee == "str":   return f"strata_int_to_str({self._gen_expr(expr.args[0], param_names)})"
        if expr.callee == "int":   return f"((strata_int)({self._gen_expr(expr.args[0], param_names)}))"
        if expr.callee == "float": return f"((strata_float)({self._gen_expr(expr.args[0], param_names)}))"
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
    gen = CodeGen(ast, source_path, modules)
    c_source = gen.generate()
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
        flags = ([cc,"-O2","--target=wasm32","--no-standard-libraries",
                  "-Wl,--export-all","-Wl,--no-entry"] + portability +
                 ["-o",output_path,c_path])
    elif is_library:
        if not output_path.endswith(".o"):
            output_path += ".o"
        flags = [cc,"-O2","-c"] + portability + ["-o",output_path,c_path]
    else:
        flags = [cc,"-O2"] + portability + ["-o",output_path,c_path,"-lm"]
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
        print(CodeGen(ast,args.file,modules).generate()); return
    compile_sta(args.file, out, target=args.target, verbose=args.verbose,
                json_diagnostics=args.json)

if __name__=="__main__": main()
