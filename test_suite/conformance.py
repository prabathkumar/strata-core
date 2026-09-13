#!/usr/bin/env python3
# STRATA — Conformance Test Suite — E001-E006 + End-to-End
import sys, os, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from compiler.lexer import Lexer, LexError
from compiler.parser import Parser, ParseError
from compiler.typechecker import TypeChecker

PASS = 0
FAIL = 0

def check(source, filename="<test>"):
    toks = Lexer(source, filename).tokenise()
    ast  = Parser(toks).parse()
    return TypeChecker(ast, filename=filename).check()

def test(name, source, expect_error=None):
    global PASS, FAIL
    try:
        errs = check(source, name)
        if expect_error is None:
            if not errs:
                print(f"  PASS  {name}"); PASS += 1
            else:
                print(f"  FAIL  {name} — expected no errors, got: {errs[0].code}"); FAIL += 1
        else:
            codes = [e.code for e in errs]
            if expect_error in codes:
                print(f"  PASS  {name} — {expect_error} fired correctly"); PASS += 1
            else:
                print(f"  FAIL  {name} — expected {expect_error}, got: {codes or 'no errors'}"); FAIL += 1
    except (LexError, ParseError) as e:
        if expect_error == "PARSE":
            print(f"  PASS  {name} — parse error caught"); PASS += 1
        else:
            print(f"  FAIL  {name} — parse error: {e}"); FAIL += 1

def compile_run(name, source, expected):
    global PASS, FAIL
    with tempfile.NamedTemporaryFile(suffix=".sta", mode="w", delete=False) as f:
        f.write(source); sta = f.name
    out = sta.replace(".sta", "")
    try:
        r = subprocess.run(["python3", "bootstrap/stage0.py", sta, "-o", out],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  FAIL  {name} — compile: {r.stderr[:60]}"); FAIL += 1; return
        r2 = subprocess.run([out], capture_output=True, text=True, timeout=5)
        got = r2.stdout.strip()
        if got == expected.strip():
            print(f"  PASS  {name} — {got!r}"); PASS += 1
        else:
            print(f"  FAIL  {name} — expected {expected!r} got {got!r}"); FAIL += 1
    except Exception as e:
        print(f"  FAIL  {name} — {e}"); FAIL += 1
    finally:
        for p in [sta, out, sta.replace(".sta",".c")]:
            if os.path.exists(p): os.unlink(p)

print("\n── E001: Variable Type Mismatch ─────────────────────────────────")
test("e001_int_gets_str", 'int main() { int x = "hello"; return 0; }', "E001")
test("e001_str_gets_int", 'int main() { str x = 42; return 0; }', "E001")
test("e001_float_gets_str", 'int main() { float x = "bad"; return 0; }', "E001")
test("e001_int_gets_float_ok", 'int main() { float x = 3; return 0; }')
test("e001_valid_int", 'int main() { int x = 42; return 0; }')
test("e001_valid_str", 'int main() { str x = "hello"; return 0; }')
test("e001_undefined_var", 'int main() { return x; }', "E001")

print("\n── E002: Return Type Mismatch ────────────────────────────────────")
test("e002_int_returns_str", 'int add(int a, int b) { return "wrong"; }', "E002")
test("e002_int_returns_nothing", 'int main() { return; }', "E002")
test("e002_valid_return", 'int main() { return 0; }')
test("e002_def_no_return_ok", 'def greet(str name) { print(name); }')
test("e002_arg_count_mismatch", 'int add(int a, int b) { return 0; }\nint main() { int x = add(1); return 0; }', "E002")

print("\n── E003: Collection Pollution ────────────────────────────────────")
test("e003_int_list_gets_str", 'int main() { list[int] nums = [1, 2, "three"]; return 0; }', "E003")
test("e003_str_list_gets_int", 'int main() { list[str] tags = ["a", "b", 99]; return 0; }', "E003")
test("e003_valid_int_list", 'int main() { list[int] nums = [1, 2, 3]; return 0; }')
test("e003_valid_str_list", 'int main() { list[str] tags = ["a", "b", "c"]; return 0; }')

print("\n── E004: Database Schema Violation ──────────────────────────────")
test("e004_bad_column",
     'database User { int id; str name; }\nint main() { list[User] r = User <- [bad_col == "x"]; return 0; }', "E004")
test("e004_typo_column",
     'database UserProfile { int user_id; str security_tier; }\nint main() { list[UserProfile] r = UserProfile <- [sec_tier == "FLAGGED"]; return 0; }', "E004")
test("e004_valid_query",
     'database UserProfile { int user_id; str security_tier; }\nint main() { list[UserProfile] r = UserProfile <- [security_tier == "FLAGGED"]; return 0; }')
test("e004_unknown_database", 'int main() { list[Ghost] r = Ghost <- [id == 1]; return 0; }', "E004")

print("\n── E005: Boundary Contamination ──────────────────────────────────")
test("e005_str_concat_with_int", 'int main() { str msg = "count: " + 42; return 0; }', "E005")
test("e005_valid_str_concat", 'int main() { str a = "hello"; str b = "world"; str c = a + b; return 0; }')
test("e005_arg_type_mismatch", 'int process(int x) { return x; }\nint main() { int r = process("bad"); return 0; }', "E005")

print("\n── E006: Tensor Dimension Drift ──────────────────────────────────")
test("e006_undeclared_model", 'int main() { int x = predict GhostModel(x); return 0; }', "E006")
test("e006_valid_model_decl",
     'model FraudNet { input: tensor[float, 1, 64]; output: tensor[float, 1, 2]; }\nint main() { return 0; }')

print("\n── End-to-End Compilation & Execution ────────────────────────────")
compile_run("e2e_hello_world",
    'import io from std;\nint main() { print("Hello, Strata!"); return 0; }',
    "Hello, Strata!")
compile_run("e2e_arithmetic",
    'import io from std;\nint main() { int x = 10; int y = 32; int z = x + y; print(str(z)); return 0; }',
    "42")
compile_run("e2e_conditional",
    'import io from std;\nint main() { int x = 100; if (x > 50) { print("big"); } else { print("small"); } return 0; }',
    "big")
compile_run("e2e_database_schema",
    'import io from std;\ndatabase Product { int id; str name; float price; }\nint main() { print("schema OK"); return 0; }',
    "schema OK")
compile_run("e2e_function_call",
    'import io from std;\ndef greet(str name) { print(name); }\nint main() { greet("Strata"); return 0; }',
    "Strata")
compile_run("e2e_chained_int_arith",
    'import io from std;\nint main() { int a = 10; int b = 20; int c = 12; print(str(a + b + c)); return 0; }',
    "42")
compile_run("e2e_chained_str_concat",
    'import io from std;\nint main() { str a = "A"; str b = "B"; str c = "C"; print(a + b + c); return 0; }',
    "ABC")
compile_run("e2e_str_param_concat",
    'import io from std;\ndef greet(str n) { print("Hi, " + n); }\nint main() { greet("Prabath"); return 0; }',
    "Hi, Prabath")
compile_run("e2e_int_param_arith",
    'import io from std;\nint add(int a, int b) { return a + b; }\nint main() { print(str(add(40, 2))); return 0; }',
    "42")
compile_run("e2e_str_plus_cast_int",
    'import io from std;\nint main() { int n = 7; print("n=" + str(n)); return 0; }',
    "n=7")
compile_run("e2e_mul_precedence",
    'import io from std;\nint main() { int x = 2; int y = 3; print(str(x + y * 4)); return 0; }',
    "14")
compile_run("e2e_paren_precedence",
    'import io from std;\nint main() { int x = 2; int y = 3; print(str((x + y) * 4)); return 0; }',
    "20")
compile_run("e2e_div_mod",
    'import io from std;\nint main() { print(str(100 / 7)); print(str(7 % 5)); return 0; }',
    "14\n2")

compile_run("e2e_string_concat",
    'import io from std;\nint main() { str a = "Hello, "; str b = "World!"; print(a + b); return 0; }',
    "Hello, World!")

total = PASS + FAIL
print(f"\n{'='*60}")
print(f"  Results: {PASS}/{total} passed, {FAIL} failed")
print(f"{'='*60}")
if FAIL == 0:
    print("  ALL TESTS PASSED OK")
    sys.exit(0)
else:
    print(f"  {FAIL} FAILED")
    sys.exit(1)
