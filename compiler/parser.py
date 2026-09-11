#!/usr/bin/env python3
# STRATA COMPILER — COMPONENT 2: PARSER + AST v1.0.0
from __future__ import annotations
import sys, json
from dataclasses import dataclass, field
from typing import List, Optional, Any
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from compiler.lexer import Lexer, Token, TT, LexError, tokenise_file

# ── AST Node Base ─────────────────────────────────────────────────────────────

@dataclass
class Node:
    line: int = field(repr=False)
    col:  int = field(repr=False)
    def to_dict(self) -> dict:
        raise NotImplementedError

# ── Literals ──────────────────────────────────────────────────────────────────

@dataclass
class IntLiteral(Node):
    value: int
    def to_dict(self): return {"node":"IntLiteral","value":self.value}

@dataclass
class FloatLiteral(Node):
    value: float
    def to_dict(self): return {"node":"FloatLiteral","value":self.value}

@dataclass
class StrLiteral(Node):
    value: str
    def to_dict(self): return {"node":"StrLiteral","value":self.value}

@dataclass
class BoolLiteral(Node):
    value: bool
    def to_dict(self): return {"node":"BoolLiteral","value":self.value}

@dataclass
class Identifier(Node):
    name: str
    def to_dict(self): return {"node":"Identifier","name":self.name}

# ── Types ─────────────────────────────────────────────────────────────────────

@dataclass
class PrimitiveType(Node):
    name: str   # int | float | str | void | bool
    def to_dict(self): return {"node":"PrimitiveType","name":self.name}

@dataclass
class ListType(Node):
    element_type: Any   # PrimitiveType | Identifier
    def to_dict(self): return {"node":"ListType","element_type":self.element_type.to_dict()}

@dataclass
class TensorType(Node):
    dtype: str
    rows: int
    cols: int
    def to_dict(self): return {"node":"TensorType","dtype":self.dtype,"rows":self.rows,"cols":self.cols}

# ── Expressions ───────────────────────────────────────────────────────────────

@dataclass
class BinaryExpr(Node):
    op: str
    left: Any
    right: Any
    def to_dict(self): return {"node":"BinaryExpr","op":self.op,
                               "left":self.left.to_dict(),"right":self.right.to_dict()}

@dataclass
class UnaryExpr(Node):
    op: str
    operand: Any
    def to_dict(self): return {"node":"UnaryExpr","op":self.op,"operand":self.operand.to_dict()}

@dataclass
class CallExpr(Node):
    callee: str
    args: List[Any]
    def to_dict(self): return {"node":"CallExpr","callee":self.callee,
                               "args":[a.to_dict() for a in self.args]}

@dataclass
class BorrowExpr(Node):
    target: Any
    def to_dict(self): return {"node":"BorrowExpr","target":self.target.to_dict()}

@dataclass
class CastExpr(Node):
    source: Any
    target_type: str
    def to_dict(self): return {"node":"CastExpr","source":self.source.to_dict(),
                               "target_type":self.target_type}

@dataclass
class PredictExpr(Node):
    model: str
    arg: Any
    def to_dict(self): return {"node":"PredictExpr","model":self.model,"arg":self.arg.to_dict()}

@dataclass
class QueryExpr(Node):
    source: str
    condition: Any
    def to_dict(self): return {"node":"QueryExpr","source":self.source,
                               "condition":self.condition.to_dict()}

@dataclass
class ListLiteral(Node):
    elements: List[Any]
    def to_dict(self): return {"node":"ListLiteral","elements":[e.to_dict() for e in self.elements]}

@dataclass
class MemberAccess(Node):
    obj: Any
    member: str
    def to_dict(self): return {"node":"MemberAccess","obj":self.obj.to_dict(),"member":self.member}

# ── Statements ────────────────────────────────────────────────────────────────

@dataclass
class VarDecl(Node):
    var_type: Any
    name: str
    value: Any
    def to_dict(self): return {"node":"VarDecl","type":self.var_type.to_dict(),
                               "name":self.name,"value":self.value.to_dict()}

@dataclass
class ReturnStmt(Node):
    value: Optional[Any]
    def to_dict(self): return {"node":"ReturnStmt",
                               "value":self.value.to_dict() if self.value else None}

@dataclass
class IfStmt(Node):
    condition: Any
    then_block: List[Any]
    else_block: Optional[List[Any]]
    def to_dict(self):
        return {"node":"IfStmt","condition":self.condition.to_dict(),
                "then_block":[s.to_dict() for s in self.then_block],
                "else_block":[s.to_dict() for s in self.else_block] if self.else_block else None}

@dataclass
class AssertStmt(Node):
    condition: Any
    def to_dict(self): return {"node":"AssertStmt","condition":self.condition.to_dict()}

@dataclass
class PrintStmt(Node):
    value: Any
    def to_dict(self): return {"node":"PrintStmt","value":self.value.to_dict()}

@dataclass
class ExprStmt(Node):
    expr: Any
    def to_dict(self): return {"node":"ExprStmt","expr":self.expr.to_dict()}

@dataclass
class VerifyBlock(Node):
    label: str
    assertions: List[AssertStmt]
    def to_dict(self): return {"node":"VerifyBlock","label":self.label,
                               "assertions":[a.to_dict() for a in self.assertions]}

@dataclass
class RenderStmt(Node):
    report: str
    path: str
    def to_dict(self): return {"node":"RenderStmt","report":self.report,"path":self.path}

# ── Top-Level Declarations ────────────────────────────────────────────────────

@dataclass
class ImportDecl(Node):
    name: str
    source: str
    def to_dict(self): return {"node":"ImportDecl","name":self.name,"source":self.source}

@dataclass
class FieldDecl(Node):
    field_type: Any
    name: str
    def to_dict(self): return {"node":"FieldDecl","type":self.field_type.to_dict(),"name":self.name}

@dataclass
class DatabaseDecl(Node):
    name: str
    fields: List[FieldDecl]
    def to_dict(self): return {"node":"DatabaseDecl","name":self.name,
                               "fields":[f.to_dict() for f in self.fields]}

@dataclass
class ProtocolDecl(Node):
    name: str
    fields: List[FieldDecl]
    def to_dict(self): return {"node":"ProtocolDecl","name":self.name,
                               "fields":[f.to_dict() for f in self.fields]}

@dataclass
class ModelDecl(Node):
    name: str
    input_type: TensorType
    output_type: TensorType
    def to_dict(self): return {"node":"ModelDecl","name":self.name,
                               "input":self.input_type.to_dict(),
                               "output":self.output_type.to_dict()}

@dataclass
class ReportMetric(Node):
    metric_type: Any
    name: str
    expr: Any
    def to_dict(self): return {"node":"ReportMetric","type":self.metric_type.to_dict(),
                               "name":self.name,"expr":self.expr.to_dict()}

@dataclass
class ReportDecl(Node):
    name: str
    title: str
    datasource: QueryExpr
    metrics: List[ReportMetric]
    def to_dict(self): return {"node":"ReportDecl","name":self.name,"title":self.title,
                               "datasource":self.datasource.to_dict(),
                               "metrics":[m.to_dict() for m in self.metrics]}

@dataclass
class Param(Node):
    param_type: Any
    name: str
    borrow: bool = False
    def to_dict(self): return {"node":"Param","type":self.param_type.to_dict(),
                               "name":self.name,"borrow":self.borrow}

@dataclass
class FunctionDecl(Node):
    return_type: Any   # type node or None for def/stream
    name: str
    params: List[Param]
    body: List[Any]
    kind: str = "function"   # function | def | stream
    def to_dict(self): return {"node":"FunctionDecl","kind":self.kind,
                               "return_type":self.return_type.to_dict() if self.return_type else None,
                               "name":self.name,
                               "params":[p.to_dict() for p in self.params],
                               "body":[s.to_dict() for s in self.body]}

@dataclass
class CompilationUnit(Node):
    imports: List[ImportDecl]
    declarations: List[Any]
    functions: List[FunctionDecl]
    def to_dict(self): return {"node":"CompilationUnit",
                               "imports":[i.to_dict() for i in self.imports],
                               "declarations":[d.to_dict() for d in self.declarations],
                               "functions":[f.to_dict() for f in self.functions]}

# ── Parse Error ───────────────────────────────────────────────────────────────

class ParseError(Exception):
    def __init__(self, msg, line, col):
        self.line = line; self.col = col
        super().__init__(f"[STRATA PARSE ERROR] {msg} at line {line}, col {col}")

# ── Parser ────────────────────────────────────────────────────────────────────

class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = [t for t in tokens if t.type != TT.EOF]
        self.tokens.append(Token(TT.EOF, "", 0, 0))
        self.pos = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def parse(self) -> CompilationUnit:
        imports = []
        declarations = []
        functions = []
        while not self._at_end():
            if self._check(TT.KW_IMPORT):
                imports.append(self._parse_import())
            elif self._check(TT.KW_DATABASE):
                declarations.append(self._parse_database())
            elif self._check(TT.KW_PROTOCOL):
                declarations.append(self._parse_protocol())
            elif self._check(TT.KW_MODEL):
                declarations.append(self._parse_model())
            elif self._check(TT.KW_REPORT):
                declarations.append(self._parse_report())
            elif self._check(TT.KW_DEF):
                functions.append(self._parse_function(kind="def"))
            elif self._check(TT.KW_STREAM):
                functions.append(self._parse_function(kind="stream"))
            elif self._is_type_token():
                functions.append(self._parse_function(kind="function"))
            else:
                t = self._peek()
                raise ParseError(f"Unexpected token '{t.value}'", t.line, t.col)
        return CompilationUnit(0, 0, imports, declarations, functions)

    # ── Import ────────────────────────────────────────────────────────────────

    def _parse_import(self) -> ImportDecl:
        t = self._consume(TT.KW_IMPORT)
        name = self._consume(TT.IDENT).value
        self._consume(TT.KW_FROM)
        source = self._consume(TT.IDENT).value
        self._consume(TT.SEMICOLON)
        return ImportDecl(t.line, t.col, name, source)

    # ── Database ──────────────────────────────────────────────────────────────

    def _parse_database(self) -> DatabaseDecl:
        t = self._consume(TT.KW_DATABASE)
        name = self._consume(TT.IDENT).value
        self._consume(TT.L_BRACE)
        fields = []
        while not self._check(TT.R_BRACE):
            ft = self._parse_type()
            fname = self._consume(TT.IDENT).value
            self._consume(TT.SEMICOLON)
            fields.append(FieldDecl(ft.line, ft.col, ft, fname))
        self._consume(TT.R_BRACE)
        return DatabaseDecl(t.line, t.col, name, fields)

    # ── Protocol ──────────────────────────────────────────────────────────────

    def _parse_protocol(self) -> ProtocolDecl:
        t = self._consume(TT.KW_PROTOCOL)
        name = self._consume(TT.IDENT).value
        self._consume(TT.L_BRACE)
        fields = []
        while not self._check(TT.R_BRACE):
            ft = self._parse_type()
            fname = self._consume(TT.IDENT).value
            self._consume(TT.SEMICOLON)
            fields.append(FieldDecl(ft.line, ft.col, ft, fname))
        self._consume(TT.R_BRACE)
        return ProtocolDecl(t.line, t.col, name, fields)

    # ── Model ─────────────────────────────────────────────────────────────────

    def _parse_model(self) -> ModelDecl:
        t = self._consume(TT.KW_MODEL)
        name = self._consume(TT.IDENT).value
        self._consume(TT.L_BRACE)
        self._consume(TT.KW_INPUT); self._consume(TT.COLON)
        input_type = self._parse_tensor_type()
        self._consume(TT.SEMICOLON)
        self._consume(TT.KW_OUTPUT); self._consume(TT.COLON)
        output_type = self._parse_tensor_type()
        self._consume(TT.SEMICOLON)
        self._consume(TT.R_BRACE)
        return ModelDecl(t.line, t.col, name, input_type, output_type)

    def _parse_tensor_type(self) -> TensorType:
        t = self._consume(TT.KW_TENSOR)
        self._consume(TT.L_BRACKET)
        dtype = self._consume_type_primitive().value
        self._consume(TT.COMMA)
        rows = int(self._consume(TT.INT_LIT).value)
        self._consume(TT.COMMA)
        cols = int(self._consume(TT.INT_LIT).value)
        self._consume(TT.R_BRACKET)
        return TensorType(t.line, t.col, dtype, rows, cols)

    # ── Report ────────────────────────────────────────────────────────────────

    def _parse_report(self) -> ReportDecl:
        t = self._consume(TT.KW_REPORT)
        name = self._consume(TT.IDENT).value
        self._consume(TT.L_BRACE)
        title = ""
        datasource = None
        metrics = []
        while not self._check(TT.R_BRACE):
            if self._check(TT.KW_TITLE):
                self._advance()
                self._consume(TT.COLON)
                title = self._consume(TT.STR_LIT).value
                self._consume(TT.COMMA)
            elif self._check(TT.KW_DATASRC):
                self._advance()
                self._consume(TT.COLON)
                src_name = self._consume(TT.IDENT).value
                self._consume(TT.ARROW_L)
                self._consume(TT.L_BRACKET)
                cond = self._parse_expr()
                self._consume(TT.R_BRACKET)
                self._consume(TT.COMMA)
                datasource = QueryExpr(t.line, t.col, src_name, cond)
            elif self._check(TT.KW_METRICS):
                self._advance()
                self._consume(TT.COLON)
                self._consume(TT.L_BRACE)
                while not self._check(TT.R_BRACE):
                    mt = self._parse_type()
                    mname = self._consume(TT.IDENT).value
                    self._consume(TT.ASSIGN)
                    mexpr = self._parse_expr()
                    self._consume(TT.SEMICOLON)
                    metrics.append(ReportMetric(mt.line, mt.col, mt, mname, mexpr))
                self._consume(TT.R_BRACE)
            else:
                tok = self._peek()
                raise ParseError(f"Unexpected token in report '{tok.value}'", tok.line, tok.col)
        self._consume(TT.R_BRACE)
        return ReportDecl(t.line, t.col, name, title, datasource, metrics)

    # ── Function / def / stream ───────────────────────────────────────────────

    def _parse_function(self, kind="function") -> FunctionDecl:
        t = self._peek()
        return_type = None
        if kind == "function":
            return_type = self._parse_type()
        else:
            self._advance()  # consume def/stream
        name = self._consume(TT.IDENT).value
        self._consume(TT.L_PAREN)
        params = self._parse_params()
        self._consume(TT.R_PAREN)
        self._consume(TT.L_BRACE)
        body = self._parse_body()
        self._consume(TT.R_BRACE)
        return FunctionDecl(t.line, t.col, return_type, name, params, body, kind)

    def _parse_params(self) -> List[Param]:
        params = []
        while not self._check(TT.R_PAREN):
            pt = self._parse_type()
            borrow = False
            if self._check(TT.BORROW):
                self._advance(); borrow = True
            pname = self._consume(TT.IDENT).value
            params.append(Param(pt.line, pt.col, pt, pname, borrow))
            if self._check(TT.COMMA):
                self._advance()
        return params

    # ── Body / Statements ─────────────────────────────────────────────────────

    def _parse_body(self) -> List[Any]:
        stmts = []
        while not self._check(TT.R_BRACE) and not self._at_end():
            stmts.append(self._parse_statement())
        return stmts

    def _parse_statement(self) -> Any:
        t = self._peek()

        if self._check(TT.KW_RETURN):
            return self._parse_return()

        if self._check(TT.KW_IF):
            return self._parse_if()

        if self._check(TT.KW_ASSERT):
            self._advance()
            cond = self._parse_expr()
            self._consume(TT.SEMICOLON)
            return AssertStmt(t.line, t.col, cond)

        if self._check(TT.KW_PRINT):
            self._advance()
            self._consume(TT.L_PAREN)
            val = self._parse_expr()
            self._consume(TT.R_PAREN)
            self._consume(TT.SEMICOLON)
            return PrintStmt(t.line, t.col, val)

        if self._check(TT.KW_RENDER):
            return self._parse_render()

        if self._check(TT.KW_VERIFY):
            return self._parse_verify()

        # Variable declaration: type name = expr;
        if self._is_type_token():
            return self._parse_var_decl()

        # Expression statement
        expr = self._parse_expr()
        self._consume(TT.SEMICOLON)
        return ExprStmt(t.line, t.col, expr)

    def _parse_return(self) -> ReturnStmt:
        t = self._consume(TT.KW_RETURN)
        if self._check(TT.SEMICOLON):
            self._advance()
            return ReturnStmt(t.line, t.col, None)
        val = self._parse_expr()
        self._consume(TT.SEMICOLON)
        return ReturnStmt(t.line, t.col, val)

    def _parse_if(self) -> IfStmt:
        t = self._consume(TT.KW_IF)
        self._consume(TT.L_PAREN)
        cond = self._parse_expr()
        self._consume(TT.R_PAREN)
        self._consume(TT.L_BRACE)
        then_block = self._parse_body()
        self._consume(TT.R_BRACE)
        else_block = None
        if self._check(TT.KW_ELSE):
            self._advance()
            self._consume(TT.L_BRACE)
            else_block = self._parse_body()
            self._consume(TT.R_BRACE)
        return IfStmt(t.line, t.col, cond, then_block, else_block)

    def _parse_var_decl(self) -> VarDecl:
        vtype = self._parse_type()
        name = self._consume(TT.IDENT).value
        self._consume(TT.ASSIGN)
        # Query expression: list[T] name = Source <- [cond];
        if self._check(TT.IDENT) and self._peek_at(1).type == TT.ARROW_L:
            src = self._consume(TT.IDENT).value
            self._consume(TT.ARROW_L)
            self._consume(TT.L_BRACKET)
            cond = self._parse_expr()
            self._consume(TT.R_BRACKET)
            self._consume(TT.SEMICOLON)
            return VarDecl(vtype.line, vtype.col, vtype, name,
                           QueryExpr(vtype.line, vtype.col, src, cond))
        val = self._parse_expr()
        self._consume(TT.SEMICOLON)
        return VarDecl(vtype.line, vtype.col, vtype, name, val)

    def _parse_render(self) -> RenderStmt:
        t = self._consume(TT.KW_RENDER)
        report = self._consume(TT.IDENT).value
        self._consume(TT.KW_TO)
        path = self._consume(TT.STR_LIT).value
        self._consume(TT.SEMICOLON)
        return RenderStmt(t.line, t.col, report, path)

    def _parse_verify(self) -> VerifyBlock:
        t = self._consume(TT.KW_VERIFY)
        label = self._consume(TT.STR_LIT).value
        self._consume(TT.L_BRACE)
        assertions = []
        while not self._check(TT.R_BRACE):
            self._consume(TT.KW_ASSERT)
            cond = self._parse_expr()
            self._consume(TT.SEMICOLON)
            assertions.append(AssertStmt(t.line, t.col, cond))
        self._consume(TT.R_BRACE)
        return VerifyBlock(t.line, t.col, label, assertions)

    # ── Expressions (Pratt precedence) ────────────────────────────────────────

    def _parse_expr(self) -> Any:
        return self._parse_or()

    def _parse_or(self) -> Any:
        left = self._parse_and()
        while self._check(TT.OR):
            op = self._advance().value
            right = self._parse_and()
            left = BinaryExpr(left.line, left.col, op, left, right)
        return left

    def _parse_and(self) -> Any:
        left = self._parse_equality()
        while self._check(TT.AND):
            op = self._advance().value
            right = self._parse_equality()
            left = BinaryExpr(left.line, left.col, op, left, right)
        return left

    def _parse_equality(self) -> Any:
        left = self._parse_comparison()
        while self._check(TT.EQ) or self._check(TT.NEQ):
            op = self._advance().value
            right = self._parse_comparison()
            left = BinaryExpr(left.line, left.col, op, left, right)
        return left

    def _parse_comparison(self) -> Any:
        left = self._parse_addition()
        while self._check(TT.LT) or self._check(TT.GT) or \
              self._check(TT.LTE) or self._check(TT.GTE):
            op = self._advance().value
            right = self._parse_addition()
            left = BinaryExpr(left.line, left.col, op, left, right)
        return left

    def _parse_addition(self) -> Any:
        left = self._parse_unary()
        while self._check(TT.PLUS) or self._check(TT.MINUS):
            op = self._advance().value
            right = self._parse_unary()
            left = BinaryExpr(left.line, left.col, op, left, right)
        return left

    def _parse_unary(self) -> Any:
        if self._check(TT.NOT):
            t = self._advance()
            return UnaryExpr(t.line, t.col, '!', self._parse_unary())
        if self._check(TT.MINUS):
            t = self._advance()
            return UnaryExpr(t.line, t.col, '-', self._parse_unary())
        if self._check(TT.BORROW):
            t = self._advance()
            return BorrowExpr(t.line, t.col, self._parse_primary())
        return self._parse_cast()

    def _parse_cast(self) -> Any:
        expr = self._parse_primary()
        if self._check(TT.CAST_OP):
            self._advance()
            target = self._consume(TT.IDENT).value
            return CastExpr(expr.line, expr.col, expr, target)
        return expr

    def _parse_primary(self) -> Any:
        t = self._peek()

        if self._check(TT.INT_LIT):
            self._advance(); return IntLiteral(t.line, t.col, int(t.value))
        if self._check(TT.FLOAT_LIT):
            self._advance(); return FloatLiteral(t.line, t.col, float(t.value))
        if self._check(TT.STR_LIT):
            self._advance(); return StrLiteral(t.line, t.col, t.value)
        if self._check(TT.KW_TRUE):
            self._advance(); return BoolLiteral(t.line, t.col, True)
        if self._check(TT.KW_FALSE):
            self._advance(); return BoolLiteral(t.line, t.col, False)

        if self._check(TT.L_BRACKET):
            return self._parse_list_literal()

        if self._check(TT.KW_PREDICT):
            return self._parse_predict()

        # Type cast call: str(expr)
        if self._is_type_keyword():
            type_name = self._advance().value
            self._consume(TT.L_PAREN)
            arg = self._parse_expr()
            self._consume(TT.R_PAREN)
            return CallExpr(t.line, t.col, type_name, [arg])

        if self._check(TT.IDENT):
            name = self._advance().value
            # Function call
            if self._check(TT.L_PAREN):
                self._consume(TT.L_PAREN)
                args = []
                while not self._check(TT.R_PAREN):
                    args.append(self._parse_expr())
                    if self._check(TT.COMMA): self._advance()
                self._consume(TT.R_PAREN)
                expr = CallExpr(t.line, t.col, name, args)
            else:
                expr = Identifier(t.line, t.col, name)
            # Member access
            while self._check(TT.DOT):
                self._advance()
                member = self._consume(TT.IDENT).value
                expr = MemberAccess(t.line, t.col, expr, member)
            return expr

        if self._check(TT.L_PAREN):
            self._advance()
            expr = self._parse_expr()
            self._consume(TT.R_PAREN)
            return expr

        raise ParseError(f"Unexpected token '{t.value}' in expression", t.line, t.col)

    def _parse_predict(self) -> PredictExpr:
        t = self._consume(TT.KW_PREDICT)
        model = self._consume(TT.IDENT).value
        self._consume(TT.L_PAREN)
        arg = self._parse_expr()
        self._consume(TT.R_PAREN)
        return PredictExpr(t.line, t.col, model, arg)

    def _parse_list_literal(self) -> ListLiteral:
        t = self._consume(TT.L_BRACKET)
        elements = []
        while not self._check(TT.R_BRACKET):
            elements.append(self._parse_expr())
            if self._check(TT.COMMA): self._advance()
        self._consume(TT.R_BRACKET)
        return ListLiteral(t.line, t.col, elements)

    # ── Type Parsing ──────────────────────────────────────────────────────────

    def _parse_type(self) -> Any:
        t = self._peek()
        if self._check(TT.KW_TENSOR):
            return self._parse_tensor_type()
        if self._check(TT.KW_LIST):
            return self._parse_list_type()
        if self._is_primitive_type():
            self._advance()
            return PrimitiveType(t.line, t.col, t.value)
        if self._check(TT.IDENT):
            self._advance()
            return PrimitiveType(t.line, t.col, t.value)
        raise ParseError(f"Expected type, got '{t.value}'", t.line, t.col)

    def _parse_list_type(self) -> ListType:
        t = self._consume(TT.KW_LIST)
        self._consume(TT.L_BRACKET)
        if self._check(TT.KW_TENSOR):
            elem = self._parse_tensor_type()
        elif self._is_primitive_type():
            et = self._advance()
            elem = PrimitiveType(et.line, et.col, et.value)
        else:
            et = self._consume(TT.IDENT)
            elem = PrimitiveType(et.line, et.col, et.value)
        self._consume(TT.R_BRACKET)
        return ListType(t.line, t.col, elem)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_type_token(self) -> bool:
        return self._is_primitive_type() or self._check(TT.KW_LIST) or \
               self._check(TT.KW_TENSOR) or \
               (self._check(TT.IDENT) and self._peek_at(1).type in
                (TT.IDENT, TT.BORROW))

    def _is_primitive_type(self) -> bool:
        return self._peek().type in (TT.KW_INT, TT.KW_FLOAT, TT.KW_STR,
                                     TT.KW_VOID, TT.KW_BOOL)

    def _is_type_keyword(self) -> bool:
        return self._peek().type in (TT.KW_INT, TT.KW_FLOAT, TT.KW_STR,
                                     TT.KW_VOID, TT.KW_BOOL)

    def _consume_type_primitive(self) -> Token:
        if self._is_primitive_type():
            return self._advance()
        t = self._peek()
        raise ParseError(f"Expected primitive type, got '{t.value}'", t.line, t.col)

    def _consume(self, tt: TT) -> Token:
        t = self._peek()
        if t.type != tt:
            raise ParseError(
                f"Expected {tt.name}, got '{t.value}' ({t.type.name})", t.line, t.col)
        return self._advance()

    def _advance(self) -> Token:
        t = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return t

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _peek_at(self, offset: int) -> Token:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def _check(self, tt: TT) -> bool:
        return self._peek().type == tt

    def _at_end(self) -> bool:
        return self._peek().type == TT.EOF

# ── Public API ────────────────────────────────────────────────────────────────

def parse_file(path: str) -> CompilationUnit:
    tokens = tokenise_file(path)
    return Parser(tokens).parse()

def parse_source(source: str, filename: str = "<stdin>") -> CompilationUnit:
    tokens = Lexer(source, filename).tokenise()
    return Parser(tokens).parse()

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Strata Parser v1.0.0")
    ap.add_argument("file", help=".sta source file")
    ap.add_argument("--json", action="store_true", help="Emit AST as JSON")
    ap.add_argument("--summary", action="store_true", help="Print AST summary")
    args = ap.parse_args()
    try:
        ast = parse_file(args.file)
    except (LexError, ParseError) as e:
        print(str(e), file=sys.stderr); sys.exit(1)
    except FileNotFoundError:
        print(f"File not found: {args.file}", file=sys.stderr); sys.exit(1)
    if args.json:
        print(json.dumps(ast.to_dict(), indent=2))
    elif args.summary:
        print(f"\n[Strata Parser] AST Summary for '{args.file}':")
        print(f"  Imports      : {len(ast.imports)}")
        print(f"  Declarations : {len(ast.declarations)}")
        for d in ast.declarations:
            print(f"    {d.__class__.__name__:<20} {d.name}")
        print(f"  Functions    : {len(ast.functions)}")
        for f in ast.functions:
            rt = f.return_type.name if hasattr(f.return_type,'name') else str(type(f.return_type).__name__) if f.return_type else 'void'
            print(f"    [{f.kind:<8}] {rt:<8} {f.name}({len(f.params)} params) — {len(f.body)} statements")
        print()
    else:
        print(f"\n[Strata Parser] Parsing '{args.file}'...\n")
        ast_dict = ast.to_dict()
        print(json.dumps(ast_dict, indent=2))
        print(f"\n  AST built successfully. ✓")

if __name__ == "__main__":
    main()
