#!/usr/bin/env python3
"""`strata fmt` preserves meaning and is idempotent.

A formatter is only worth having if a reviewer can stop reading its output.
Two properties make that true, and both are checked here over every .sta file
in the repository rather than over a handful of samples:

  1. **The syntax tree is unchanged.** The formatted file parses to exactly
     the same AST as the original. A formatter that alters meaning is worse
     than no formatter, because it does it silently and at scale.

  2. **Formatting is idempotent.** fmt(fmt(x)) == fmt(x). Without this, a
     repository never converges: every run produces a diff, which is the exact
     noise the tool exists to remove.

Two further properties matter for this implementation in particular, because
it rewrites lines rather than reprinting from tokens:

  3. Comments survive. The lexer discards them, so anything built on the token
     stream would delete every comment in the file.

  4. The inside of a `native "..."` block is byte-identical. The code
     generator emits that C verbatim; re-indenting it would change the
     program.

Usage:  python3 test_suite/fmt.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FMT_SRC = os.path.join(ROOT, "compiler", "fmt_cli.sta")
FMT_BIN = os.path.join(ROOT, "build", "strata-fmt")

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def build():
    os.makedirs(os.path.dirname(FMT_BIN), exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "bootstrap", "stage0.py"),
                        FMT_SRC, "-o", FMT_BIN],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        print("The formatter failed to compile:")
        print(r.stdout + r.stderr)
        sys.exit(1)


def fmt(text):
    with tempfile.NamedTemporaryFile("w", suffix=".sta", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        r = subprocess.run([FMT_BIN, path], capture_output=True, text=True,
                           timeout=60)
        if r.returncode != 0:
            return None
        return r.stdout
    finally:
        os.unlink(path)


def ast_of(text):
    """The syntax tree, as the parser sees it — positions excluded.

    `to_dict()` omits line and column, which is what makes it usable here:
    a formatter moves every token, so comparing positions would compare
    nothing but the formatting.
    """
    sys.path.insert(0, ROOT)
    from compiler.lexer import Lexer
    from compiler.parser import Parser
    try:
        return json.dumps(Parser(Lexer(text).tokenise()).parse().to_dict(),
                          sort_keys=True)
    except Exception as e:
        return f"PARSE_ERROR: {e}"


def natives(text):
    """The contents of every native block, in order."""
    out, i = [], 0
    while True:
        k = text.find('native "', i)
        if k < 0:
            return out
        j = k + 8
        while j < len(text):
            if text[j] == "\\":
                j += 2
                continue
            if text[j] == '"':
                break
            j += 1
        out.append(text[k + 8:j])
        i = j + 1


build()

print("\n── Behaviour ────────────────────────────────────────────────────")

MESSY = ('import io from std;\n'
         'int helper(int n) {\n'
         'if (n > 0) {\n'
         'return n;\n'
         '}\n'
         'return 0;\n'
         '  }\n'
         '\n\n\n'
         '// a comment\n'
         'int main() {\n'
         '  str s = "a brace { inside a string }";\n'
         '  print(s);\n'
         '        return helper(3);\n'
         '}\n')

got = fmt(MESSY)
ok("the formatter runs", got is not None)
if got:
    ok("nested blocks are indented four spaces per level",
       "    if (n > 0) {\n        return n;\n    }\n" in got, repr(got[:200]))
    ok("a closing brace dedents its own line", "\n}\n" in got)
    ok("comments survive", "// a comment" in got)
    ok("a brace inside a string does not change depth",
       "    print(s);" in got, repr(got))
    ok("runs of blank lines collapse to one", "\n\n\n" not in got)
    ok("the file ends with exactly one newline",
       got.endswith("\n") and not got.endswith("\n\n"))

NATIVE = ('import io from std;\n'
          'str f() {\n'
          'native "\n'
          '   int x = 1;\n'
          '       if (x) { printf(\\"deep\\\\n\\"); }\n'
          '   return \\"ok\\";\n'
          '";\n'
          '}\n')
got = fmt(NATIVE)
ok("a native block survives byte for byte",
   got is not None and natives(got) == natives(NATIVE),
   f"{natives(NATIVE)!r} -> {natives(got)!r}" if got else "no output")

ok("an empty file is handled", fmt("") in ("", "\n"))
ok("a file that is only a comment is handled",
   (fmt("// just this\n") or "").strip() == "// just this")

print("\n── Every file in the repository ─────────────────────────────────")

targets = []
for d in ("std", "compiler", "examples", "test_suite"):
    full = os.path.join(ROOT, d)
    for dirpath, _, names in os.walk(full):
        if "unimplemented" in dirpath:
            continue
        for nm in sorted(names):
            if nm.endswith(".sta"):
                targets.append(os.path.join(dirpath, nm))

ok("found files to check", len(targets) > 20, f"only {len(targets)}")

bad_ast, bad_idem, bad_native, bad_comments = [], [], [], []
for path in sorted(targets):
    original = open(path).read()
    once = fmt(original)
    if once is None:
        bad_ast.append(os.path.relpath(path, ROOT) + " (formatter failed)")
        continue
    twice = fmt(once)
    if twice != once:
        bad_idem.append(os.path.relpath(path, ROOT))
    if ast_of(once) != ast_of(original):
        bad_ast.append(os.path.relpath(path, ROOT))
    if natives(once) != natives(original):
        bad_native.append(os.path.relpath(path, ROOT))
    if once.count("//") < original.count("//"):
        bad_comments.append(os.path.relpath(path, ROOT))

ok(f"the syntax tree is unchanged ({len(targets)} files)", not bad_ast,
   ", ".join(bad_ast[:5]))
ok(f"formatting is idempotent ({len(targets)} files)", not bad_idem,
   ", ".join(bad_idem[:5]))
ok(f"native blocks are byte-identical ({len(targets)} files)", not bad_native,
   ", ".join(bad_native[:5]))
ok(f"no comment is dropped ({len(targets)} files)", not bad_comments,
   ", ".join(bad_comments[:5]))

total = PASS + FAIL
print("\n" + "=" * 62)
print(f"  {PASS}/{total} checks passed over {len(targets)} files")
print("=" * 62)
if FAIL == 0:
    print("  Formatting preserves meaning and converges. OK")
    sys.exit(0)
print(f"  {FAIL} FAILED")
sys.exit(1)
