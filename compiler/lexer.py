#!/usr/bin/env python3
# STRATA COMPILER — COMPONENT 1: LEXER v1.0.0
from __future__ import annotations
import sys, json
from dataclasses import dataclass
from enum import Enum, auto
from typing import List

class TT(Enum):
    INT_LIT=auto(); FLOAT_LIT=auto(); STR_LIT=auto(); IDENT=auto()
    KW_INT=auto(); KW_FLOAT=auto(); KW_STR=auto(); KW_VOID=auto()
    KW_LIST=auto(); KW_TENSOR=auto(); KW_BOOL=auto()
    KW_IF=auto(); KW_ELSE=auto(); KW_RETURN=auto(); KW_ASSERT=auto()
    KW_WHILE=auto(); KW_FOR=auto(); KW_BREAK=auto(); KW_CONTINUE=auto()
    KW_IMPORT=auto(); KW_FROM=auto(); KW_DEF=auto()
    KW_DATABASE=auto(); KW_STREAM=auto(); KW_PROTOCOL=auto()
    KW_MODEL=auto(); KW_PREDICT=auto(); KW_REPORT=auto()
    KW_RENDER=auto(); KW_LAYOUT=auto(); KW_VERIFY=auto()
    KW_INPUT=auto(); KW_OUTPUT=auto(); KW_METRICS=auto()
    KW_TITLE=auto(); KW_DATASRC=auto(); KW_TO=auto()
    KW_PRINT=auto(); KW_TRUE=auto(); KW_FALSE=auto()
    L_BRACE=auto(); R_BRACE=auto(); L_PAREN=auto(); R_PAREN=auto()
    L_BRACKET=auto(); R_BRACKET=auto(); SEMICOLON=auto(); COLON=auto()
    COMMA=auto(); DOT=auto(); ASSIGN=auto(); ARROW_L=auto()
    CAST_OP=auto(); BORROW=auto(); PLUS=auto(); MINUS=auto()
    STAR=auto(); SLASH=auto(); PERCENT=auto(); EQ=auto(); NEQ=auto()
    LT=auto(); GT=auto(); LTE=auto(); GTE=auto(); AND=auto()
    OR=auto(); NOT=auto(); EOF=auto(); UNKNOWN=auto()

# `input`, `output`, `metrics`, `title`, `datasource` and `to` are NOT here on
# purpose. They are field names inside model, report and render syntax, and
# reserving them globally would stop a program using ordinary words as
# identifiers — a variable called `title` or a function called `to_json`. The
# parsers match them contextually, where they can only mean one thing.
KEYWORDS = {
    "int":TT.KW_INT,"float":TT.KW_FLOAT,"str":TT.KW_STR,"void":TT.KW_VOID,
    "list":TT.KW_LIST,"tensor":TT.KW_TENSOR,"bool":TT.KW_BOOL,
    "if":TT.KW_IF,"else":TT.KW_ELSE,"return":TT.KW_RETURN,
    "while":TT.KW_WHILE,"for":TT.KW_FOR,
    "break":TT.KW_BREAK,"continue":TT.KW_CONTINUE,
    "assert":TT.KW_ASSERT,"import":TT.KW_IMPORT,"from":TT.KW_FROM,"def":TT.KW_DEF,
    "database":TT.KW_DATABASE,"stream":TT.KW_STREAM,"protocol":TT.KW_PROTOCOL,
    "model":TT.KW_MODEL,"predict":TT.KW_PREDICT,"report":TT.KW_REPORT,
    "render":TT.KW_RENDER,"layout":TT.KW_LAYOUT,"verify":TT.KW_VERIFY,
    "true":TT.KW_TRUE,"false":TT.KW_FALSE,
}

@dataclass
class Token:
    type: TT; value: str; line: int; col: int
    def to_dict(self):
        return {"type":self.type.name,"value":self.value,"line":self.line,"col":self.col}

class LexError(Exception):
    def __init__(self,msg,line,col):
        self.line=line; self.col=col
        super().__init__(f"[STRATA LEX ERROR] {msg} at line {line}, col {col}")

class Lexer:
    def __init__(self,source,filename="<stdin>"):
        self.source=source; self.filename=filename
        self.pos=0; self.line=1; self.col=1; self.tokens=[]

    def tokenise(self):
        while not self._at_end():
            self._scan_token()
        self.tokens.append(Token(TT.EOF,"",self.line,self.col))
        return self.tokens

    def _scan_token(self):
        sl,sc=self.line,self.col
        ch=self._advance()
        if ch in (' ','\t','\r'):
            return
        if ch == '\n':
            self.line += 1; self.col = 1; return
        if ch=='/' and self._peek()=='/':
            self._line_comment(); return
        if ch=='/' and self._peek()=='*':
            self._block_comment(sl,sc); return
        if ch=='"':
            self._string_literal(sl,sc); return
        if ch.isdigit():
            self._number_literal(ch,sl,sc); return
        if ch.isalpha() or ch=='_':
            self._identifier(ch,sl,sc); return
        if ch=='<' and self._peek()=='-':
            self._advance(); self._add(TT.ARROW_L,'<-',sl,sc); return
        if ch==':' and self._peek()==':':
            self._advance(); self._add(TT.CAST_OP,'::',sl,sc); return
        if ch=='=' and self._peek()=='=':
            self._advance(); self._add(TT.EQ,'==',sl,sc); return
        if ch=='!' and self._peek()=='=':
            self._advance(); self._add(TT.NEQ,'!=',sl,sc); return
        if ch=='<' and self._peek()=='=':
            self._advance(); self._add(TT.LTE,'<=',sl,sc); return
        if ch=='>' and self._peek()=='=':
            self._advance(); self._add(TT.GTE,'>=',sl,sc); return
        if ch=='&' and self._peek()=='&':
            self._advance(); self._add(TT.AND,'&&',sl,sc); return
        if ch=='|' and self._peek()=='|':
            self._advance(); self._add(TT.OR,'||',sl,sc); return
        SINGLE={
            '{':TT.L_BRACE,'}':TT.R_BRACE,'(':TT.L_PAREN,')':TT.R_PAREN,
            '[':TT.L_BRACKET,']':TT.R_BRACKET,';':TT.SEMICOLON,':':TT.COLON,
            ',':TT.COMMA,'.':TT.DOT,'=':TT.ASSIGN,'&':TT.BORROW,'+':TT.PLUS,
            '-':TT.MINUS,'*':TT.STAR,'/':TT.SLASH,'%':TT.PERCENT,
            '<':TT.LT,'>':TT.GT,'!':TT.NOT
        }
        if ch in SINGLE:
            self._add(SINGLE[ch],ch,sl,sc); return
        # Source-organisation directives (#region / #endregion) carry no
        # semantics; they are skipped like a line comment.
        if ch=='#':
            self._line_comment(); return
        raise LexError(f"Unexpected character '{ch}'",sl,sc)

    def _line_comment(self):
        while not self._at_end() and self._peek()!='\n':
            self._advance()

    def _block_comment(self,sl,sc):
        self._advance()
        while not self._at_end():
            ch=self._advance()
            if ch=='\n': self.line+=1; self.col=1
            elif ch=='*' and self._peek()=='/':
                self._advance(); return
        raise LexError("Unterminated block comment",sl,sc)

    def _string_literal(self,sl,sc):
        buf=[]
        ESC={'n':'\n','t':'\t','r':'\r','"':'"','\\':'\\'}
        while not self._at_end():
            ch=self._advance()
            if ch=='\\':
                esc=self._advance()
                buf.append(ESC.get(esc,esc))
            elif ch=='"':
                self._add(TT.STR_LIT,''.join(buf),sl,sc); return
            elif ch=='\n':
                # Allow newlines inside strings (needed for native blocks)
                self.line += 1; self.col = 1
                buf.append('\n')
            else:
                buf.append(ch)
        raise LexError("Unterminated string",sl,sc)

    def _number_literal(self,first,sl,sc):
        # `0x1F4E62` is one integer written the way the thing it describes is
        # written everywhere else. Without it a colour is a hand conversion to
        # decimal, and the first one written in this repository was wrong --
        # the screen rendered green instead of teal, and a pixel check caught
        # it rather than a person.
        #
        # The token keeps its source text and the value is worked out when the
        # code is generated, so both compilers agree by construction: there is
        # no arithmetic here for the two of them to disagree about.
        if first=='0' and not self._at_end() and self._peek() in 'xX':
            buf=[first,self._advance()]
            digits=0
            while not self._at_end() and self._peek() in '0123456789abcdefABCDEF':
                buf.append(self._advance()); digits+=1
            if digits==0: raise LexError("A hex literal needs at least one digit",sl,sc)
            if digits>16: raise LexError("Hex literal is too long for an int",sl,sc)
            self._add(TT.INT_LIT,''.join(buf),sl,sc)
            return
        buf=[first]; is_float=False
        while not self._at_end() and (self._peek().isdigit() or self._peek()=='.'):
            ch=self._advance()
            if ch=='.':
                if is_float: raise LexError("Malformed float",sl,sc)
                is_float=True
            buf.append(ch)
        self._add(TT.FLOAT_LIT if is_float else TT.INT_LIT,''.join(buf),sl,sc)

    def _identifier(self,first,sl,sc):
        buf=[first]
        while not self._at_end() and (self._peek().isalnum() or self._peek()=='_'):
            buf.append(self._advance())
        word=''.join(buf)
        self._add(KEYWORDS.get(word,TT.IDENT),word,sl,sc)

    def _add(self,tt,value,line,col):
        self.tokens.append(Token(tt,value,line,col))

    def _advance(self):
        ch=self.source[self.pos]; self.pos+=1; self.col+=1; return ch

    def _peek(self,offset=0):
        idx=self.pos+offset
        return '\0' if idx>=len(self.source) else self.source[idx]

    def _at_end(self):
        return self.pos>=len(self.source)

def tokenise_file(path):
    with open(path,'r',encoding='utf-8') as f:
        source=f.read()
    return Lexer(source,filename=path).tokenise()

def tokens_to_json(tokens):
    return json.dumps([t.to_dict() for t in tokens],indent=2)

def print_token_table(tokens):
    print(f"{'TYPE':<22} {'VALUE':<30} {'LINE':>5} {'COL':>5}")
    print('-'*66)
    for t in tokens:
        if t.type==TT.EOF: break
        v=t.value if len(t.value)<=30 else t.value[:27]+'...'
        print(f"{t.type.name:<22} {v:<30} {t.line:>5} {t.col:>5}")

def main():
    import argparse
    ap=argparse.ArgumentParser(description="Strata Lexer v1.0.0")
    ap.add_argument("file",help=".sta source file")
    ap.add_argument("--json",action="store_true")
    ap.add_argument("--count",action="store_true")
    args=ap.parse_args()
    try:
        tokens=tokenise_file(args.file)
    except LexError as e:
        print(str(e),file=sys.stderr); sys.exit(1)
    except FileNotFoundError:
        print(f"File not found: {args.file}",file=sys.stderr); sys.exit(1)
    if args.json:
        print(tokens_to_json(tokens))
    elif args.count:
        from collections import Counter
        c=Counter(t.type.name for t in tokens if t.type!=TT.EOF)
        print(f"\n[Strata Lexer] {args.file}: {sum(c.values())} tokens, {len(c)} types")
        for n,v in sorted(c.items(),key=lambda x:-x[1]):
            print(f"  {n:<22} {v}")
    else:
        print(f"\n[Strata Lexer] Tokenising '{args.file}'...\n")
        print_token_table(tokens)
        print(f"\n  {len([t for t in tokens if t.type!=TT.EOF])} tokens. OK")

if __name__=="__main__":
    main()
