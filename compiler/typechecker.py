#!/usr/bin/env python3
# STRATA COMPILER — COMPONENT 3: TYPE CHECKER
# Enforces E001-E006 at compile time
from __future__ import annotations
import sys, os, json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from compiler.lexer import LexError, tokenise_file
from compiler.parser import (
    Parser, ParseError, CompilationUnit,
    DatabaseDecl, ProtocolDecl, ModelDecl, ReportDecl,
    FunctionDecl, ImportDecl, FieldDecl, Param,
    VarDecl, ReturnStmt, IfStmt, PrintStmt, ExprStmt,
    AssignStmt, WhileStmt, ForStmt, BreakStmt, ContinueStmt, IndexExpr,
    AssertStmt, RenderStmt, VerifyBlock, InsertStmt, DeleteStmt, ConstDecl,
    LayoutDecl, Element, Prop, ForInStmt, ForeignDecl, TableIOStmt,
    BinaryExpr, UnaryExpr, CallExpr, BorrowExpr, CastExpr,
    PredictExpr, QueryExpr, ListLiteral, MemberAccess, RenderExpr,
    IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, Identifier,
    PrimitiveType, ListType, TensorType,
)

@dataclass
class StrataError:
    code: str; message: str; line: int; col: int; hint: str = ""
    # The file the diagnostic is in. An application is several files, and a
    # line number against the wrong one is worse than no line number.
    file: str = ""
    def __str__(self):
        where = f"{self.file}:" if self.file else ""
        out = f"[{self.code}] {self.message} ({where}line {self.line}, col {self.col})"
        if self.hint: out += f"\n  Hint: {self.hint}"
        return out

class TypeCheckError(Exception):
    def __init__(self, error):
        self.error = error; super().__init__(str(error))

@dataclass
class SType:
    name: str
    is_list: bool = False
    element_type: Optional['SType'] = None
    is_tensor: bool = False
    tensor_rows: int = 0
    tensor_cols: int = 0
    dtype: str = ""
    def __eq__(self, other):
        if not isinstance(other, SType): return False
        if self.is_tensor and other.is_tensor:
            return self.dtype==other.dtype and self.tensor_rows==other.tensor_rows and self.tensor_cols==other.tensor_cols
        if self.is_list and other.is_list:
            return self.element_type == other.element_type
        return self.name == other.name
    def __repr__(self):
        if self.is_tensor: return f"tensor[{self.dtype},{self.tensor_rows},{self.tensor_cols}]"
        if self.is_list: return f"list[{self.element_type}]"
        return self.name

T_INT=SType("int"); T_FLOAT=SType("float"); T_STR=SType("str")
T_VOID=SType("void"); T_BOOL=SType("bool")
PRIMITIVES={"int":T_INT,"float":T_FLOAT,"str":T_STR,"void":T_VOID,"bool":T_BOOL}

def is_compatible(declared, actual):
    if declared == actual: return True
    if declared.name == "float" and actual.name == "int": return True
    return False

class Scope:
    def __init__(self, parent=None):
        self.parent=parent; self.symbols={}
    def define(self, name, stype): self.symbols[name]=stype
    def lookup(self, name):
        if name in self.symbols: return self.symbols[name]
        if self.parent: return self.parent.lookup(name)
        return None

# Functions the generated C already has, either from the runtime prelude or as
# a compiler intrinsic. A call to one of these is never "undefined", and this
# list drifting out of date would show up as a false positive on real code —
# `test_suite/conformance.py` asserts it covers everything the code generator
# knows how to emit.
RUNTIME_BUILTINS = frozenset((
    # prelude: strings, files, string builder
    'file_exists', 'file_read', 'file_write', 'float_to_str', 'int_to_str',
    'sb_append_f', 'sb_append_line_f', 'sb_new_f', 'str_concat', 'str_eq',
    'str_index_of', 'str_len', 'str_slice', 'str_starts_with', 'str_to_int',
    'strata_concat', 'strata_float_to_str', 'strata_int_to_str', 'strata_dup',
    'strata_len', 'strata_write_escaped', 'strata_read_field',
    'strata_read_header', 'strata_load_refuse',
    # prelude: streams
    'strata_on', 'strata_publish', 'strata_run', 'current_message',
    'strata_set_message',
    # prelude: tensors and models
    'strata_tensor', 'strata_tensor_set', 'strata_tensor_get',
    'strata_tensor_add', 'strata_predict', 'strata_model_load',
    'strata_activate', 'strata_weight_count',
    # compiler intrinsics
    'native',
))

# Handled before the lookup, but listed so the test above can be exhaustive.
CAST_AND_AGGREGATE = frozenset((
    'str', 'int', 'float', 'bool', 'len', 'sum', 'avg', 'min', 'max', 'count',
))


class TypeChecker:
    def __init__(self, ast, filename="<stdin>", modules=None,
                 unresolved_imports=None, project_modules=None):
        """`modules` is the resolved import graph, when the caller has one.

        Without it a call to an unknown function cannot be distinguished from a
        call into an import, so the checker stays lenient and the mistake
        surfaces as a C linker error naming a C symbol. With it, the set of
        reachable names is known and an unknown callee is E002.

        Pass [] for a file that imports nothing — that is still a complete
        picture. None means "imports were not resolved", which is not.
        """
        self.ast=ast; self.filename=filename; self.errors=[]
        self.global_scope=Scope(); self.schemas={}; self.models={}
        # Names declared `const`, so an assignment to one is an error.
        self.constants=set()
        # (name, line, col) already reported as an ambiguous query identifier.
        self._reported_ambiguous=set()
        self.functions={}; self.current_return_type=None
        self.strict_calls = modules is not None
        self.unresolved_imports = unresolved_imports or []
        # Which file the diagnostics being produced right now belong to.
        self.current_file = ""
        # (path, unit) for each module of the project itself. Dependencies are
        # not here: they have their own suite.
        self.project_modules = [(p, u, "app") for p, u in (project_modules or [])]
        # Names only, not signatures: knowing that `str_pad` exists is enough
        # to not report it, and checking argument types across a module
        # boundary is a separate change with its own risk.
        self.imported_names = set()
        # Kept for registering imported declarations in check().
        self.modules = list(modules or [])
        for m in self.modules:
            # resolve_imports yields (module_name, unit) pairs.
            unit = m[1] if isinstance(m, tuple) else m
            for fn in getattr(unit, "functions", []):
                self.imported_names.add(fn.name)
            for d in getattr(unit, "declarations", []):
                name = getattr(d, "name", None)
                if name:
                    self.imported_names.add(name)
                for ffn in getattr(d, "functions", []) or []:
                    self.imported_names.add(ffn.name)

    def check(self):
        self._report_unresolved_imports()
        self._register_imported_declarations()
        self._register_declarations()
        self._register_foreign()
        self._register_functions()
        # Reports and layouts are checked after functions are registered:
        # either may be declared before the database it draws from, and a
        # layout may reference a handler defined further down the file.
        for d in self.ast.declarations:
            if isinstance(d, ReportDecl):
                self._check_report(d)
            elif isinstance(d, LayoutDecl):
                self._check_layout(d)
            elif isinstance(d, VerifyBlock):
                # A verify block is a body like any other.
                vscope = Scope(self.global_scope)
                for st in d.assertions:
                    self._check_stmt(st, vscope)
        self._check_functions()
        self._check_project_modules()
        return self.errors

    def _report_unresolved_imports(self):
        """An import with no local checkout, reported at its own line.

        The compiler used to print this on stderr and carry on, so it never
        reached `--json` and the repair loop could not see it. It matters more
        than it looks: an unresolvable import also disarms the undefined-call
        check, so a file importing a module that is not there reports nothing
        at all — moving a broken module out of the way makes its callers look
        clean.

        It is an advisory, not an error. A dependency provided at link time is
        legitimate, and failing the build on one would make external modules
        unusable.
        """
        for imp in self.unresolved_imports:
            self._error("E007",
                f"'{imp.name}' from '{imp.source}' has no local checkout",
                imp.line, imp.col,
                f"Its symbols must be provided at link time, and nothing it "
                f"declares is checked here — including calls into it")

    def _register_imported_declarations(self):
        """Schemas and models an import brings in.

        Without this an application cannot be more than one file: a `database`
        block in schema.sta is invisible to the module that queries it, and
        every query reports E004 against a table that is right there.

        Registered before the file's own declarations, so a local one wins.
        """
        for m in self.modules:
            unit = m[1] if isinstance(m, tuple) else m
            for d in getattr(unit, "declarations", []):
                if isinstance(d, (DatabaseDecl, ProtocolDecl)):
                    self.schemas[d.name] = {
                        f.name: self._resolve_type(f.field_type) for f in d.fields}
                    self.global_scope.define(d.name, SType(d.name))
                elif isinstance(d, ModelDecl):
                    self.models[d.name] = (self._resolve_type(d.input_type),
                                           self._resolve_type(d.output_type))
                    self.global_scope.define(d.name, SType(d.name))
                elif isinstance(d, (ReportDecl, LayoutDecl)):
                    self.global_scope.define(d.name, SType(d.name))
                elif isinstance(d, ConstDecl):
                    # A constant crosses a module boundary like any other
                    # name. Without this, moving a constant into the module
                    # that owns it makes it invisible to the file that uses
                    # it — which is where anyone would put it.
                    self.constants.add(d.name)
                    self.global_scope.define(d.name,
                                             self._resolve_type(d.const_type))

    def _register_declarations(self):
        for d in self.ast.declarations:
            if isinstance(d, ConstDecl):
                # A constant is a name in the global scope that nothing may
                # assign to. Its value is checked against its declared type
                # here, so `const int PORT = "8080";` fails at the declaration
                # rather than wherever PORT is first used.
                declared = self._resolve_type(d.const_type)
                self.constants.add(d.name)
                self.global_scope.define(d.name, declared)
                actual = self._infer_type(d.value, self.global_scope)
                if actual and not is_compatible(declared, actual):
                    self._error("E001",
                        f"Constant '{d.name}' is '{declared}' but its value is "
                        f"'{actual}'",
                        d.line, d.col,
                        f"Give it a value of type '{declared}', or declare it "
                        f"as '{actual}'")
            elif isinstance(d, DatabaseDecl):
                self.schemas[d.name]={f.name:self._resolve_type(f.field_type) for f in d.fields}
                self.global_scope.define(d.name, SType(d.name))
            elif isinstance(d, ProtocolDecl):
                self.schemas[d.name]={f.name:self._resolve_type(f.field_type) for f in d.fields}
                self.global_scope.define(d.name, SType(d.name))
            elif isinstance(d, ModelDecl):
                self.models[d.name]=(self._resolve_type(d.input_type),self._resolve_type(d.output_type))
                self.global_scope.define(d.name, SType(d.name))
            elif isinstance(d, ReportDecl):
                self.global_scope.define(d.name, SType(d.name))
            elif isinstance(d, LayoutDecl):
                # A layout is renderable in the same way a report is.
                self.global_scope.define(d.name, SType(d.name))


    def _register_foreign(self):
        """Foreign signatures are registered like any other function.

        The point of declaring them is that a call across the boundary is
        checked: passing a str where the C function takes an int is E005, not a
        crash at runtime.
        """
        for d in self.ast.declarations:
            if isinstance(d, ForeignDecl):
                for fn in d.functions:
                    rt = self._resolve_type(fn.return_type)
                    pts = [self._resolve_type(p.param_type) for p in fn.params]
                    self.functions[fn.name] = (rt, pts)

    def _register_functions(self):
        for fn in self.ast.functions:
            rt=T_VOID
            if fn.kind=="function" and fn.return_type: rt=self._resolve_type(fn.return_type)
            params=[self._resolve_type(p.param_type) for p in fn.params]
            self.functions[fn.name]=(rt,params)
            self.global_scope.define(fn.name,rt)

    def _check_functions(self):
        for fn in self.ast.functions:
            scope=Scope(parent=self.global_scope)
            for p in fn.params: scope.define(p.name,self._resolve_type(p.param_type))
            self.current_return_type=T_VOID
            if fn.kind=="function" and fn.return_type:
                self.current_return_type=self._resolve_type(fn.return_type)
            self._check_body(fn.body,scope)

    def _check_project_modules(self):
        """Check the bodies of the project's own modules, not its dependencies.

        Only the file being compiled used to have its bodies checked, so a
        column renamed in schema.sta failed the build at main.sta and sailed
        past views.sta — the UI tier, which is the one the cross-tier claim is
        about. The break surfaced later as a C compiler error naming a C
        symbol.

        `std` and `compiler` modules are deliberately not checked here. They
        are dependencies with their own suite (`stdlib_compiles.py`), and
        re-checking them on every application build would put their
        diagnostics in every user's output.
        """
        for name, unit, source in self.project_modules:
            self.current_file = name
            saved_functions = self.functions
            # An imported module's own functions and declarations, on top of
            # what is already known, so a call between two project modules
            # resolves.
            self.functions = dict(self.functions)
            for fn in unit.functions:
                rt = T_VOID
                if fn.kind == "function" and fn.return_type:
                    rt = self._resolve_type(fn.return_type)
                self.functions[fn.name] = (
                    rt, [self._resolve_type(p.param_type) for p in fn.params])
            for d in unit.declarations:
                if isinstance(d, ReportDecl):
                    self._check_report(d)
                elif isinstance(d, LayoutDecl):
                    self._check_layout(d)
            for fn in unit.functions:
                scope = Scope(parent=self.global_scope)
                for p in fn.params:
                    scope.define(p.name, self._resolve_type(p.param_type))
                self.current_return_type = T_VOID
                if fn.kind == "function" and fn.return_type:
                    self.current_return_type = self._resolve_type(fn.return_type)
                self._check_body(fn.body, scope)
            self.functions = saved_functions
        self.current_file = ""

    def _check_body(self,stmts,scope):
        for s in stmts: self._check_stmt(s,scope)

    def _check_element(self,stmt,scope):
        # A bare identifier after a tag — `canvas topology_view [...]` — names
        # the element rather than referring to a value. It is only treated as
        # an expression when it actually resolves, so that `text username` is
        # still checked while an element id is not reported as undefined.
        label = stmt.label
        if label is not None:
            bare_name = isinstance(label, Identifier) and not scope.lookup(label.name)
            if not bare_name:
                self._infer_type(label,scope)
        for p in stmt.props: self._infer_type(p.value,scope)
        inner=Scope(scope)
        for c in stmt.children: self._check_stmt(c,inner)

    def _check_for_in(self,stmt,scope):
        """Bind the loop variable to the collection's element type.

        Without this the loop body cannot resolve `item.column`, and the
        cross-tier guarantee would stop at the query.
        """
        ct=self._infer_type(stmt.collection,scope)
        inner=Scope(scope)
        if ct is not None and ct.is_list and ct.element_type is not None:
            inner.define(stmt.var, ct.element_type)
        else:
            if ct is not None:
                self._error("E003",f"'{stmt.var}' iterates '{ct}', which is not a list",
                    stmt.line,stmt.col,"Iterate a list[T], such as a query result")
        for st in stmt.body: self._check_stmt(st,inner)

    def _check_insert(self,stmt,scope):
        """`Table <- [col = expr, ...]` — validate target and every column."""
        if stmt.target not in self.schemas:
            self._error("E004",f"Database '{stmt.target}' not declared",
                stmt.line,stmt.col,f"Declare 'database {stmt.target}' first")
            return
        fields=self.schemas[stmt.target]
        for col,value in stmt.assignments:
            if col not in fields:
                self._error("E004",
                    f"Column '{col}' does not exist in '{stmt.target}'",
                    stmt.line,stmt.col,
                    f"Valid columns: {sorted(fields)}")
            self._infer_type(value,scope)
        # Every column must be named. A column added to the schema and not
        # named here would otherwise be written as a zero or an empty string,
        # silently, in every insert in the program — which is exactly the
        # change a developer makes most often. The build is where that is
        # found, not the data file.
        named={col for col,_ in stmt.assignments}
        for col in fields:
            if col not in named:
                self._error("E009",
                    f"Insert into '{stmt.target}' omits column '{col}'",
                    stmt.line,stmt.col,
                    f"Add '{col} = <value>' to the insert — "
                    f"'{col}' is '{fields[col]}' — "
                    f"or remove '{col}' from 'database {stmt.target}'")

    def _check_assign(self,stmt,scope):
        if isinstance(stmt.target,Identifier) and stmt.target.name in self.constants:
            self._error("E001",
                f"Cannot assign to constant '{stmt.target.name}'",
                stmt.line,stmt.col,
                "A constant is fixed when the program is built. Use a local "
                "variable if the value needs to change.")
            return
        """`target = value` must not change the target's declared type."""
        target=self._infer_type(stmt.target,scope)
        value=self._infer_type(stmt.value,scope)
        if isinstance(stmt.target,Identifier) and target is None:
            self._error("E001",f"'{stmt.target.name}' is not declared",
                stmt.line,stmt.col,
                f"Declare it first, e.g. 'int {stmt.target.name} = ...;'")
            return
        if target and value and not is_compatible(target,value):
            name=getattr(stmt.target,"name","target")
            self._error("E001",
                f"Type mismatch: '{name}' is '{target}' but assigned '{value}'",
                stmt.line,stmt.col,
                f"Assign a value of type '{target}'")

    def _check_layout(self,decl):
        """A layout is checked like any other body.

        This is the point of the language: a field rendered on screen is
        resolved against the database schema at build time, so renaming a
        column fails the build at the line of UI that used it rather than at
        runtime in front of a user.
        """
        scope=Scope(self.global_scope)
        for p in getattr(decl,"params",[]):
            scope.define(p.name,self._resolve_type(p.param_type))
        for st in decl.body: self._check_stmt(st,scope)

    def _check_report(self,decl):
        """A report's datasource is a query and gets the same E004 treatment.

        Without this a typo'd column in `datasource:` compiles silently, which
        is the exact failure `database` blocks exist to prevent.
        """
        q=getattr(decl,"datasource",None)
        if q is None or not isinstance(q,QueryExpr): return
        if q.source not in self.schemas:
            self._error("E004",f"Database '{q.source}' not declared",
                decl.line,decl.col,
                f"Declare 'database {q.source}' before reporting on it")
            return
        self._validate_query_cond(q.condition,q.source,decl.line,decl.col)
        # Metrics are expressions evaluated where `rows` is the datasource
        # result, so `strata_len(rows)` is what a count is written as. Without
        # this a metric declared `int` and assigned a str compiled silently.
        mscope=Scope(self.global_scope)
        mscope.define("rows",SType("list",is_list=True,element_type=SType(q.source)))
        for m in decl.metrics:
            declared=self._resolve_type(m.metric_type)
            actual=self._infer_type(m.expr,mscope)
            if actual and not is_compatible(declared,actual):
                self._error("E001",
                    f"Type mismatch: metric '{m.name}' declared as '{declared}' "
                    f"but assigned '{actual}'",
                    m.line,m.col,f"Change value to type '{declared}' or update declaration")

    def _check_stmt(self,stmt,scope):
        if isinstance(stmt,VarDecl): self._check_var_decl(stmt,scope)
        elif isinstance(stmt,ReturnStmt): self._check_return(stmt,scope)
        elif isinstance(stmt,IfStmt): self._check_if(stmt,scope)
        elif isinstance(stmt,AssignStmt): self._check_assign(stmt,scope)
        elif isinstance(stmt,WhileStmt):
            self._infer_type(stmt.condition,scope)
            inner=Scope(scope)
            for st in stmt.body: self._check_stmt(st,inner)
        elif isinstance(stmt,ForStmt):
            inner=Scope(scope)
            if stmt.init is not None: self._check_stmt(stmt.init,inner)
            self._infer_type(stmt.condition,inner)
            if stmt.step is not None: self._check_stmt(stmt.step,inner)
            for st in stmt.body: self._check_stmt(st,inner)
        elif isinstance(stmt,(BreakStmt,ContinueStmt)): pass
        elif isinstance(stmt,PrintStmt): self._infer_type(stmt.value,scope)
        elif isinstance(stmt,AssertStmt): self._infer_type(stmt.condition,scope)
        elif isinstance(stmt,InsertStmt): self._check_insert(stmt,scope)
        elif isinstance(stmt,DeleteStmt):
            if stmt.table not in self.schemas:
                self._error("E004",f"Database '{stmt.table}' not declared",
                    stmt.line,stmt.col,f"Declare 'database {stmt.table}' before deleting from it")
            else:
                self._validate_query_cond(stmt.condition,stmt.table,
                                          stmt.line,stmt.col,scope)
        elif isinstance(stmt,TableIOStmt):
            if stmt.table not in self.schemas:
                self._error("E004",f"Database '{stmt.table}' not declared",
                    stmt.line,stmt.col,f"Declare 'database {stmt.table}' first")
        elif isinstance(stmt,Element): self._check_element(stmt,scope)
        elif isinstance(stmt,ForInStmt): self._check_for_in(stmt,scope)
        elif isinstance(stmt,ExprStmt): self._infer_type(stmt.expr,scope)
        elif isinstance(stmt,VerifyBlock):
            inner=Scope(scope)
            for a in stmt.assertions: self._check_stmt(a,inner)
        elif isinstance(stmt,RenderStmt):
            if stmt.report not in self.global_scope.symbols:
                self._error("E004",f"Report '{stmt.report}' not declared",stmt.line,stmt.col,
                    f"Declare 'report {stmt.report}' first")

    def _check_var_decl(self,stmt,scope):
        declared=self._resolve_type(stmt.var_type)
        if stmt.value is None:
            scope.define(stmt.name, declared)
            return
        if isinstance(stmt.value,QueryExpr):
            # A query into a record type yields the first match rather than a
            # list, so the element type is what must be compatible.
            src=stmt.value.source
            if src not in self.schemas:
                self._error("E004",f"Database '{src}' not declared",stmt.line,stmt.col,
                    f"Declare 'database {src}' before querying")
            else:
                self._validate_query_cond(stmt.value.condition,src,stmt.line,stmt.col,scope)
            scope.define(stmt.name,declared); return
        actual=self._infer_type(stmt.value,scope)
        if actual and not is_compatible(declared,actual):
            self._error("E001",
                f"Type mismatch: '{stmt.name}' declared as '{declared}' but assigned '{actual}'",
                stmt.line,stmt.col,f"Change value to type '{declared}' or update declaration")
        if declared.is_list and isinstance(stmt.value,ListLiteral):
            self._check_list_elems(stmt.value,declared.element_type,stmt.name,stmt.line,stmt.col,scope)
        scope.define(stmt.name,declared)

    def _check_return(self,stmt,scope):
        if self.current_return_type is None: return
        if stmt.value is None:
            if self.current_return_type!=T_VOID:
                self._error("E002",
                    f"Function expects '{self.current_return_type}' but returns nothing",
                    stmt.line,stmt.col,f"Add return value of type '{self.current_return_type}'")
            return
        actual=self._infer_type(stmt.value,scope)
        if actual and not is_compatible(self.current_return_type,actual):
            self._error("E002",
                f"Return mismatch: expected '{self.current_return_type}', got '{actual}'",
                stmt.line,stmt.col,f"Change return value to type '{self.current_return_type}'")

    def _check_if(self,stmt,scope):
        self._infer_type(stmt.condition,scope)
        self._check_body(stmt.then_block,Scope(parent=scope))
        if stmt.else_block: self._check_body(stmt.else_block,Scope(parent=scope))

    def _infer_type(self,expr,scope):
        if isinstance(expr,IntLiteral): return T_INT
        if isinstance(expr,FloatLiteral): return T_FLOAT
        if isinstance(expr,StrLiteral): return T_STR
        if isinstance(expr,BoolLiteral): return T_BOOL
        if isinstance(expr,Identifier):
            t=scope.lookup(expr.name)
            if t is None and expr.name in self.models:
                # A bare model name is the model itself, so it can be passed
                # to the runtime without exposing a generated C global.
                return SType("model")
            if t is None and expr.name in self.functions:
                # A bare function name is a reference, not a call — an event
                # handler passed to a layout element, for instance. Its type is
                # not yet expressible, but it is certainly not undefined.
                return None
            if t is None:
                self._error("E001",f"Undefined identifier '{expr.name}'",
                    expr.line,expr.col,f"Declare '{expr.name}' before use")
            return t
        if isinstance(expr,BinaryExpr): return self._infer_binary(expr,scope)
        if isinstance(expr,UnaryExpr): return self._infer_type(expr.operand,scope)
        if isinstance(expr,CallExpr): return self._infer_call(expr,scope)
        if isinstance(expr,BorrowExpr): return self._infer_type(expr.target,scope)
        if isinstance(expr,CastExpr): return SType(expr.target_type)
        if isinstance(expr,PredictExpr): return self._infer_predict(expr,scope)
        if isinstance(expr,ListLiteral):
            if not expr.elements: return SType("list",is_list=True,element_type=T_VOID)
            et=self._infer_type(expr.elements[0],scope)
            return SType("list",is_list=True,element_type=et)
        if isinstance(expr,MemberAccess):
            ot=self._infer_type(expr.obj,scope)
            if ot is not None and ot.is_list:
                # A collection has no fields of its own. Without this the
                # mistake reaches the C compiler as a pointer error naming
                # generated code.
                self._error("E003",
                    f"'{expr.member}' is a field of the row, not of '{ot}'",
                    expr.line,expr.col,
                    "Index the list or iterate it with 'for x in ...' first")
                return None
            if ot and ot.name in self.schemas:
                fields=self.schemas[ot.name]
                if expr.member not in fields:
                    self._error("E004",f"Field '{expr.member}' not in '{ot.name}'",
                        expr.line,expr.col,f"Valid fields: {list(fields.keys())}")
                    return None
                return fields[expr.member]
        if isinstance(expr,IndexExpr):
            bt=self._infer_type(expr.target,scope)
            it=self._infer_type(expr.index,scope)
            if it and it!=T_INT:
                self._error("E001",f"List index must be 'int', got '{it}'",
                    expr.line,expr.col,"Use an integer expression as the index")
            if bt and bt.is_list: return bt.element_type
            # A str indexes to its character code, which is what makes
            # character scanning expressible in the language.
            if bt==T_STR: return T_INT
            if bt:
                self._error("E003",f"Cannot index into '{bt}' — not a list or str",
                    expr.line,expr.col,"Indexing applies to list[T] and str values")
            return None
        if isinstance(expr,RenderExpr):
            for a in getattr(expr,"args",[]): self._infer_type(a,scope)
            if self.global_scope.lookup(expr.target) is None:
                self._error("E002",f"'{expr.target}' is not a layout or report",
                    expr.line,expr.col,
                    f"Declare 'layout {expr.target}' or 'report {expr.target}'")
            return T_STR
        if isinstance(expr,QueryExpr):
            src=expr.source
            if src not in self.schemas:
                self._error("E004",f"Database '{src}' not declared",
                    expr.line,expr.col,
                    f"Declare 'database {src}' before querying it")
                return None
            self._validate_query_cond(expr.condition,src,expr.line,expr.col,scope)
            return SType("list",is_list=True,element_type=SType(src))
        return None

    def _infer_binary(self,expr,scope):
        left=self._infer_type(expr.left,scope)
        right=self._infer_type(expr.right,scope)
        if expr.op in ("==","!=","<",">","<=",">=","&&","||"): return T_BOOL
        if expr.op=="+" and left==T_STR:
            # `right is None` means the type could not be inferred — typically a
            # call into an imported module, since only the root file is checked.
            # Reporting that as contamination makes E005 fire on every
            # multi-module program, including this project's own stdlib.
            if right is not None and right!=T_STR:
                self._error("E005",f"Cannot concat str with '{right}' — wrap in str()",
                    expr.line,expr.col,"Use str() to convert first")
            return T_STR
        if expr.op in ("+","-","*","/","%"):
            if left and right:
                return T_FLOAT if (left.name=="float" or right.name=="float") else T_INT
        return left

    def _infer_call(self,expr,scope):
        if expr.callee in ("str","int","float"):
            # Infer the arguments even though the result type is fixed:
            # otherwise every rule is silently skipped inside str(...).
            for a in expr.args: self._infer_type(a,scope)
            return {"str":T_STR,"int":T_INT,"float":T_FLOAT}[expr.callee]
        if expr.callee=="bool":
            for a in expr.args: self._infer_type(a,scope)
            return T_BOOL
        if expr.callee=="len":
            for a in expr.args: self._infer_type(a,scope)
            return T_INT
        if expr.callee in ("sum","avg","min","max","count"):
            return self._infer_aggregate(expr,scope)
        fn=self.functions.get(expr.callee)
        if fn is None:
            # Whether or not the callee resolves, its arguments are ordinary
            # expressions and every rule still applies inside them — otherwise
            # any call into std/ is a hole through which unchecked code passes.
            for a in expr.args: self._infer_type(a,scope)
            if (self.strict_calls
                    and expr.callee not in self.imported_names
                    and expr.callee not in RUNTIME_BUILTINS
                    and expr.callee not in self.schemas
                    and expr.callee not in self.models
                    and self.global_scope.lookup(expr.callee) is None):
                self._error("E002", f"Undefined function '{expr.callee}'",
                    expr.line, expr.col,
                    f"Declare '{expr.callee}' or import the module that defines it")
            return None
        rt,pts=fn
        if len(expr.args)!=len(pts):
            self._error("E002",f"'{expr.callee}' expects {len(pts)} args, got {len(expr.args)}",
                expr.line,expr.col,"")
            return rt
        for i,(arg,pt) in enumerate(zip(expr.args,pts)):
            at=self._infer_type(arg,scope)
            if at and not is_compatible(pt,at):
                self._error("E005",f"Arg {i+1} of '{expr.callee}': expected '{pt}', got '{at}'",
                    expr.line,expr.col,f"Cast argument to '{pt}'")
        return rt

    def _infer_aggregate(self,expr,scope):
        """`count(rows)`, and `sum(xs)` / `sum(rows.column)` for the rest.

        A column projection is written `rows.amount` and is checked against
        the row type's schema, so a renamed column fails the build here in the
        same way it fails at a query or in a layout. That contract is the
        reason this is in the language rather than in a library.

        `sum`, `min` and `max` keep the element's own type — summing ints
        gives an int. `avg` is always float, and `count` always int.
        """
        name=expr.callee
        if len(expr.args)!=1:
            self._error("E002",f"'{name}' takes one argument, got {len(expr.args)}",
                expr.line,expr.col,f"Write {name}(rows) or {name}(rows.column)")
            return T_INT if name=="count" else T_FLOAT

        arg=expr.args[0]
        # count() does not need a column: it is about the rows themselves.
        if name=="count":
            at=self._infer_type(arg,scope)
            if at and not at.is_list:
                self._error("E003",f"'count' expects a list, got '{at}'",
                    expr.line,expr.col,"Pass a list or a query result")
            return T_INT

        elem=None
        if isinstance(arg,MemberAccess):
            base=self._infer_type(arg.obj,scope)
            if base is not None and base.is_list:
                row=base.element_type
                cols=self.schemas.get(row.name if row else "")
                if cols is None:
                    self._error("E003",
                        f"'{name}' cannot project '{arg.member}' out of "
                        f"'{base}' — its element is not a record",
                        expr.line,expr.col,
                        f"Project a column of a database or protocol type")
                    return T_FLOAT
                if arg.member not in cols:
                    self._error("E004",
                        f"Column '{arg.member}' does not exist in '{row.name}'",
                        expr.line,expr.col,
                        f"Valid columns: {sorted(cols)}")
                    return T_FLOAT
                elem=cols[arg.member]
            else:
                # Not a projection at all — an ordinary member access.
                elem=self._infer_type(arg,scope)
        else:
            at=self._infer_type(arg,scope)
            if at is not None and at.is_list:
                elem=at.element_type
            elif at is not None:
                self._error("E003",f"'{name}' expects a list, got '{at}'",
                    expr.line,expr.col,
                    f"Write {name}(rows.column) to aggregate a column")
                return T_FLOAT

        if elem is not None and elem.name not in ("int","float"):
            self._error("E003",f"'{name}' expects numbers, got '{elem}'",
                expr.line,expr.col,"Aggregates apply to int and float")
            return T_FLOAT
        if name=="avg":
            return T_FLOAT
        return elem if elem is not None else T_FLOAT

    def _infer_predict(self,expr,scope):
        model=self.models.get(expr.model)
        if model is None:
            self._error("E006",f"Model '{expr.model}' not declared",expr.line,expr.col,
                f"Declare 'model {expr.model}' first")
            return None
        it,ot=model
        at=self._infer_type(expr.arg,scope)
        if at and at.is_tensor:
            if at.tensor_rows!=it.tensor_rows or at.tensor_cols!=it.tensor_cols:
                self._error("E006",
                    f"Tensor shape mismatch for '{expr.model}': expected [{it.tensor_rows},{it.tensor_cols}], got [{at.tensor_rows},{at.tensor_cols}]",
                    expr.line,expr.col,"Reshape tensor to match model contract")
        return ot

    def _check_list_elems(self,literal,expected,name,line,col,scope):
        if expected is None: return
        for i,elem in enumerate(literal.elements):
            et=self._infer_type(elem,scope)
            if et and not is_compatible(expected,et):
                self._error("E003",
                    f"List '{name}' element {i+1}: expected '{expected}', got '{et}'",
                    line,col,f"All elements of list[{expected}] must be '{expected}'")

    def _validate_query_cond(self,cond,schema,line,col,scope=None):
        """Columns exist, and a bare name is not ambiguous.

        Inside the brackets a bare identifier is always the ROW's column. If a
        variable of the same name is also in scope, the column wins silently —
        so `Session <- [token == token]` compares the column with itself and
        matches every row. Written as a session lookup, that means any token
        authenticates. Naming a parameter after the column it filters on is
        the most natural thing to write, which is what makes it worth an error
        rather than a convention.
        """
        fields=self.schemas.get(schema,{})
        if isinstance(cond,BinaryExpr):
            if isinstance(cond.left,Identifier) and cond.left.name not in fields:
                self._error("E004",
                    f"Column '{cond.left.name}' does not exist in '{schema}'",
                    line,col,f"Valid columns: {list(fields.keys())}")
            self._validate_query_cond(cond.left,schema,line,col,scope)
            self._validate_query_cond(cond.right,schema,line,col,scope)
        elif isinstance(cond,Identifier) and scope is not None:
            if cond.name in fields and scope.lookup(cond.name) is not None:
                # Once per name, per position. `[token == token]` — the exact
                # shape that made this rule necessary — has the ambiguous name
                # on both sides, and the walk visits both, so the same mistake
                # was reported twice. Two different ambiguous names on one
                # line still give two diagnostics, which is right.
                key = (cond.name, line, col)
                if key in self._reported_ambiguous:
                    return
                self._reported_ambiguous.add(key)
                self._error("E008",
                    f"'{cond.name}' is both a column of '{schema}' and a "
                    f"variable in scope",
                    line,col,
                    f"Inside a query the name is always the column, so this "
                    f"compares '{cond.name}' with itself and matches every "
                    f"row. Rename the variable.")

    def _resolve_type(self,node):
        if node is None: return T_VOID
        if isinstance(node,PrimitiveType): return PRIMITIVES.get(node.name,SType(node.name))
        if isinstance(node,ListType):
            return SType("list",is_list=True,element_type=self._resolve_type(node.element_type))
        if isinstance(node,TensorType):
            return SType("tensor",is_tensor=True,tensor_rows=node.rows,tensor_cols=node.cols,dtype=node.dtype)
        return T_VOID

    def _error(self,code,message,line,col,hint=""):
        self.errors.append(StrataError(code,message,line,col,hint,
                                       self.current_file))

def typecheck_file(path):
    toks=tokenise_file(path); ast=Parser(toks).parse()
    return TypeChecker(ast,filename=path).check()

def typecheck_source(source,filename="<stdin>"):
    from compiler.lexer import Lexer
    toks=Lexer(source,filename).tokenise(); ast=Parser(toks).parse()
    return TypeChecker(ast,filename=filename).check()

def main():
    import argparse
    ap=argparse.ArgumentParser(description="Strata Type Checker v1.0.0")
    ap.add_argument("file"); ap.add_argument("--json",action="store_true")
    args=ap.parse_args()
    try: errors=typecheck_file(args.file)
    except (LexError,ParseError) as e: print(str(e),file=sys.stderr); sys.exit(1)
    except FileNotFoundError: print(f"File not found: {args.file}",file=sys.stderr); sys.exit(1)
    if args.json:
        print(json.dumps([{"code":e.code,"message":e.message,"line":e.line,"col":e.col,"hint":e.hint} for e in errors],indent=2))
    else:
        if not errors: print(f"[Strata TypeCheck] No errors. OK")
        else:
            print(f"[Strata TypeCheck] {len(errors)} error(s):\n")
            for e in errors: print(f"  {e}\n")
    sys.exit(0 if not errors else 1)

if __name__=="__main__": main()
