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
    AssertStmt, RenderStmt, VerifyBlock, InsertStmt,
    LayoutDecl, Element, Prop, ForInStmt, ForeignDecl,
    BinaryExpr, UnaryExpr, CallExpr, BorrowExpr, CastExpr,
    PredictExpr, QueryExpr, ListLiteral, MemberAccess,
    IntLiteral, FloatLiteral, StrLiteral, BoolLiteral, Identifier,
    PrimitiveType, ListType, TensorType,
)

@dataclass
class StrataError:
    code: str; message: str; line: int; col: int; hint: str = ""
    def __str__(self):
        out = f"[{self.code}] {self.message} (line {self.line}, col {self.col})"
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

class TypeChecker:
    def __init__(self, ast, filename="<stdin>"):
        self.ast=ast; self.filename=filename; self.errors=[]
        self.global_scope=Scope(); self.schemas={}; self.models={}
        self.functions={}; self.current_return_type=None

    def check(self):
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
        return self.errors

    def _register_declarations(self):
        for d in self.ast.declarations:
            if isinstance(d, DatabaseDecl):
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

    def _check_assign(self,stmt,scope):
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
                self._validate_query_cond(stmt.value.condition,src,stmt.line,stmt.col)
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
        if isinstance(expr,QueryExpr):
            src=expr.source
            if src in self.schemas:
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
            for a in expr.args: self._infer_type(a,scope)
            return T_FLOAT
        fn=self.functions.get(expr.callee)
        if fn is None:
            # An imported or not-yet-resolved callee. Its signature is unknown,
            # but its arguments are ordinary expressions and every rule still
            # applies inside them — otherwise any call into std/ is a hole
            # through which unchecked code passes.
            for a in expr.args: self._infer_type(a,scope)
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

    def _validate_query_cond(self,cond,schema,line,col):
        fields=self.schemas.get(schema,{})
        if isinstance(cond,BinaryExpr):
            if isinstance(cond.left,Identifier) and cond.left.name not in fields:
                self._error("E004",
                    f"Column '{cond.left.name}' does not exist in '{schema}'",
                    line,col,f"Valid columns: {list(fields.keys())}")
            self._validate_query_cond(cond.left,schema,line,col)
            self._validate_query_cond(cond.right,schema,line,col)

    def _resolve_type(self,node):
        if node is None: return T_VOID
        if isinstance(node,PrimitiveType): return PRIMITIVES.get(node.name,SType(node.name))
        if isinstance(node,ListType):
            return SType("list",is_list=True,element_type=self._resolve_type(node.element_type))
        if isinstance(node,TensorType):
            return SType("tensor",is_tensor=True,tensor_rows=node.rows,tensor_cols=node.cols,dtype=node.dtype)
        return T_VOID

    def _error(self,code,message,line,col,hint=""):
        self.errors.append(StrataError(code,message,line,col,hint))

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
