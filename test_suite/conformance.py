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

test("e005_unknown_callee_not_flagged",
     'int main() { str m = "id " + imported_helper(1); return 0; }')
test("e005_known_int_still_flagged",
     'int main() { int n = 1; str m = "id " + n; return 0; }', "E005")

print("\n── E006: Tensor Dimension Drift ──────────────────────────────────")
test("e006_undeclared_model", 'int main() { int x = predict GhostModel(x); return 0; }', "E006")
test("e006_valid_model_decl",
     'model FraudNet { input: tensor[float, 1, 64]; output: tensor[float, 1, 2]; }\nint main() { return 0; }')

print("\n── Insert statement (write form of <-) ──────────────────────────")
test("insert_bad_column",
     'database Audit { int id; str actor; }\nint main() { Audit <- [wrong_col = "x"]; return 0; }', "E004")
test("insert_valid",
     'database Audit { int id; str actor; }\nint main() { Audit <- [actor = "prabath"]; return 0; }')
test("insert_multi_column",
     'database Audit { int id; str actor; }\nint main() { Audit <- [id = 1, actor = "p"]; return 0; }')

print("\n── Phase 1: assignment, loops, indexing ─────────────────────────")
test("assign_type_mismatch", 'int main() { int i = 0; i = "text"; return 0; }', "E001")
test("assign_undeclared", 'int main() { ghost = 5; return 0; }', "E001")
test("assign_valid", 'int main() { int i = 0; i = 5; return 0; }')
test("index_non_int", 'int main() { list[int] a = [1,2]; int x = a["k"]; return 0; }', "E001")
test("index_non_list", 'int main() { int n = 5; int x = n[0]; return 0; }', "E003")
test("index_valid", 'int main() { list[int] a = [1,2]; int x = a[0]; return 0; }')
test("while_valid", 'int main() { int i = 0; while (i < 3) { i = i + 1; } return 0; }')
test("for_valid", 'int main() { int t = 0; for (int i = 0; i < 3; i = i + 1) { t = t + i; } return 0; }')

print("\n── Seed subset: constructs the self-hosted compiler needs ──────")
compile_run("seed_string_builder",
    'import io from std;\nimport str from std;\nint main() { StringBuilder sb = sb_new(); sb_append(&sb, "int "); sb_append(&sb, "main"); print(sb_to_str(&sb)); return 0; }',
    "int main")
compile_run("seed_char_scan",
    'import io from std;\nint main() { str s = "AB"; int n = str_len(s); int acc = 0; for (int i = 0; i < n; i = i + 1) { acc = acc + s[i]; } print(str(acc)); return 0; }',
    "131")
compile_run("seed_record_construct",
    'import io from std;\ndatabase Token { int kind; int line; }\nToken tok_new(int k, int l) { native "Token* t=(Token*)malloc(sizeof(Token)); t->kind=k; t->line=l; return t;"; }\nint main() { Token t = tok_new(7, 42); t.line = 43; print(str(t.kind + t.line)); return 0; }',
    "50")
compile_run("seed_growable_vector",
    'import io from std;\ndatabase IntVec { int ptr; int len; int cap; }\nIntVec vec_new() { native "IntVec* v=(IntVec*)malloc(sizeof(IntVec)); v->cap=2; v->len=0; v->ptr=(int64_t)(uintptr_t)malloc(2*sizeof(int64_t)); return v;"; }\ndef vec_push(IntVec &v, int x) { native "if($v->len>=$v->cap){ $v->cap*=2; $v->ptr=(int64_t)(uintptr_t)realloc((void*)(uintptr_t)$v->ptr,$v->cap*sizeof(int64_t)); } ((int64_t*)(uintptr_t)$v->ptr)[$v->len]=$x; $v->len+=1;"; }\nint vec_get(IntVec &v, int i) { native "return ((int64_t*)(uintptr_t)$v->ptr)[$i];"; }\nint main() { IntVec v = vec_new(); for (int i = 0; i < 50; i = i + 1) { vec_push(&v, i * 2); } print(str(vec_get(&v, 49))); return 0; }',
    "98")

print("\n── Cross-tier contract (layout) ──────────────────────────────────")
LAYOUT_OK = ('database M { int id; str service_name; }\n'
             'layout C() { window "x" { list[M] rows = M <- [id == 1];\n'
             '  for R in rows { row { text R.service_name; } } } }')
test("layout_valid", LAYOUT_OK)
test("layout_renamed_column_breaks_ui",
     LAYOUT_OK.replace("str service_name;", "str svc_name;"), "E004")
test("layout_bad_query_column",
     'database M { int id; str name; }\nlayout C() { window "x" { list[M] r = M <- [nope == 1]; } }', "E004")
test("layout_for_in_non_list",
     'layout C() { window "x" { int n = 5; for R in n { text "x"; } } }', "E003")
test("layout_element_id_not_undefined",
     'layout C() { window "x" { canvas topology_view [width = 500]; } }')
test("layout_handler_reference",
     'int on_click() { return 0; }\nlayout C() { window "x" { button "Go" [action = on_click]; } }')

print("\n── Contextual keywords ───────────────────────────────────────────")
compile_run("ctx_title_and_metrics_as_variables",
    'import io from std;\nint main() { str title = "T"; str metrics = "M"; print(title + metrics); return 0; }',
    "TM")
compile_run("ctx_to_and_input_as_names",
    'import io from std;\nint to(int x) { return x * 2; }\nint main() { int input = 21; print(str(to(input))); return 0; }',
    "42")
test("ctx_model_block_still_parses",
    'model M { input: tensor[float, 1, 64]; output: tensor[float, 1, 2]; }')
test("ctx_report_block_still_parses",
    'database L { int id; str status; }\nreport R { title: "T", datasource: L <- [status == "X"], metrics: { float t = sum(id); } }')

print("\n── Database runtime ──────────────────────────────────────────────")
compile_run("db_insert_and_query",
    'import io from std;\ndatabase M { int id; str name; }\nint main() { M <- [id = 1, name = "a"]; M <- [id = 2, name = "b"]; list[M] h = M <- [id == 2]; print(str(len(h))); return 0; }',
    "1")
compile_run("db_query_by_string",
    'import io from std;\ndatabase M { int id; str status; }\nint main() { M <- [id = 1, status = "UP"]; M <- [id = 2, status = "DOWN"]; M <- [id = 3, status = "DOWN"]; list[M] d = M <- [status == "DOWN"]; print(str(len(d))); return 0; }',
    "2")
compile_run("db_for_in_renders_rows",
    'import io from std;\ndatabase M { int id; str name; }\nlayout L() { window "w" { list[M] all = M <- [id > 0]; for R in all { text R.name; } } }\nint main() { M <- [id = 1, name = "alpha"]; M <- [id = 2, name = "beta"]; render L to "/tmp/_t.html"; print("rendered"); return 0; }',
    "rendered")
compile_run("db_empty_query",
    'import io from std;\ndatabase M { int id; }\nint main() { list[M] none = M <- [id == 99]; print(str(len(none))); return 0; }',
    "0")
compile_run("float_shortest_roundtrip",
    'import io from std;\nint main() { float a = 91.4; float b = 3.0; print(str(a)); print(str(b)); return 0; }',
    "91.4\n3.0")

print("\n── Foreign function interface ────────────────────────────────────")
compile_run("ffi_calls_libm",
    'import io from std;\nforeign "math.h" link "m" { float sqrt(float x); }\nint main() { print(str(sqrt(144.0))); return 0; }',
    "12.0")
compile_run("ffi_two_args",
    'import io from std;\nforeign "math.h" link "m" { float pow(float a, float b); }\nint main() { print(str(pow(2.0, 10.0))); return 0; }',
    "1024.0")
test("ffi_arg_type_checked",
    'foreign "math.h" link "m" { float sqrt(float x); }\nint main() { float r = sqrt("nope"); return 0; }', "E005")
test("ffi_arg_count_checked",
    'foreign "math.h" link "m" { float pow(float a, float b); }\nint main() { float r = pow(2.0); return 0; }', "E002")
test("ffi_return_type_flows",
    'foreign "math.h" link "m" { float sqrt(float x); }\nint main() { str s = sqrt(4.0); return 0; }', "E001")

print("\n── Inference runtime ─────────────────────────────────────────────")
compile_run("ml_predict_dense_layer",
    'import io from std;\nmodel M { input: tensor[float,1,3]; output: tensor[float,1,2]; }\n'
    'int main() { tensor[float,1,3] x = strata_tensor(3);\n'
    '  strata_tensor_set(x,0,2.0); strata_tensor_set(x,1,3.0); strata_tensor_set(x,2,4.0);\n'
    '  file_write("/tmp/_w.txt", "1 0 0 1 1 1 0.5 0.25");\n'
    '  strata_model_load(M, "/tmp/_w.txt");\n'
    '  tensor[float,1,2] y = predict M(x);\n'
    '  print(str(strata_tensor_get(y,0))); print(str(strata_tensor_get(y,1))); return 0; }',
    "6.5\n7.25")
compile_run("ml_untrained_predicts_zeros",
    'import io from std;\nmodel M { input: tensor[float,1,2]; output: tensor[float,1,1]; }\n'
    'int main() { tensor[float,1,2] x = strata_tensor(2);\n'
    '  tensor[float,1,1] y = predict M(x); print(str(strata_tensor_get(y,0))); return 0; }',
    "0.0")
test("ml_shape_mismatch_is_e006",
    'model M { input: tensor[float,1,64]; output: tensor[float,1,2]; }\n'
    'int f(tensor[float,1,32] w) { tensor[float,1,2] y = predict M(w); return 0; }', "E006")
test("ml_undeclared_model_is_e006",
    'int main() { int x = predict Ghost(x); return 0; }', "E006")

test("utf8_columns_count_characters",
     'int main() { str s = "em—dash"; int n = str_len(s); return 0; }')

print("\n── Declarations, verify blocks, single-record queries ───────────")
compile_run("uninit_decl_zeroes",
    'import io from std;\nint main() { int n; float f; n = 7; print(str(n)); print(str(f)); return 0; }',
    "7\n0.0")
compile_run("single_record_query",
    'import io from std;\ndatabase M { int id; str name; }\n'
    'int main() { M <- [id = 1, name = "a"]; M <- [id = 2, name = "b"];\n'
    '  M hit = M <- [id == 2]; print(hit.name); return 0; }',
    "b")
test("verify_block_typechecks",
    'int twice(int x) { return x * 2; }\nverify "doubling" { int a = 21; int b = twice(a); assert b == 42; }', None)
test("assert_group_sees_outer_scope",
    'int f() { return 1; }\nverify "v" { int r = f(); assert "group" { assert r == 1; } }', None)
test("field_access_on_list_is_e003",
    'database M { int id; str name; }\nint main() { list[M] rows = M <- [id == 1]; str n = rows.name; return 0; }', "E003")

print("\n── Table persistence ─────────────────────────────────────────────")
PERSIST = ('import io from std;\ndatabase A { int id; str holder; float balance; }\n'
           'int main() { load A from "/tmp/_p.tsv";\n'
           '  list[A] have = A <- [id > 0]; print(str(len(have)));\n'
           '  A <- [id = 1, holder = "a\\tb", balance = 1250.75];\n'
           '  save A to "/tmp/_p.tsv"; return 0; }')
import os
if os.path.exists("/tmp/_p.tsv"): os.unlink("/tmp/_p.tsv")
compile_run("persist_first_run_empty", PERSIST, "0")
compile_run("persist_second_run_loads", PERSIST, "1")
test("persist_unknown_table_is_e004",
     'int main() { save Ghost to "/tmp/x"; return 0; }', "E004")

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

compile_run("e2e_stdlib_print_is_library",
    'import io from std;\nint main() { print("via stdlib"); return 0; }',
    "via stdlib")

compile_run("e2e_while_countdown",
    'import io from std;\nint main() { int i = 3; while (i > 0) { print(str(i)); i = i - 1; } return 0; }',
    "3\n2\n1")
compile_run("e2e_for_sum",
    'import io from std;\nint main() { int t = 0; for (int i = 1; i <= 10; i = i + 1) { t = t + i; } print(str(t)); return 0; }',
    "55")
compile_run("e2e_break",
    'import io from std;\nint main() { int i = 0; while (i < 100) { if (i == 5) { break; } i = i + 1; } print(str(i)); return 0; }',
    "5")
compile_run("e2e_list_index",
    'import io from std;\nint main() { list[int] a = [10,20,30]; a[0] = 99; print(str(a[0] + a[2])); return 0; }',
    "129")
compile_run("e2e_c_reserved_words_as_names",
    'import io from std;\nint register(int switch_in) { int const_ = switch_in * 2; return const_; }\nint main() { int auto_ = 5; print(str(register(auto_))); return 0; }',
    "10")

compile_run("e2e_borrowed_scalar_write",
    'import io from std;\ndef bump(int &n) { n = n + 1; }\nint main() { int v = 5; bump(&v); bump(&v); print(str(v)); return 0; }',
    "7")

compile_run("e2e_bubble_sort",
    'import io from std;\nint main() { list[int] d = [3,1,2]; int n = 3; for (int i = 0; i < n-1; i = i+1) { for (int j = 0; j < n-i-1; j = j+1) { if (d[j] > d[j+1]) { int t = d[j]; d[j] = d[j+1]; d[j+1] = t; } } } for (int k = 0; k < n; k = k+1) { print(str(d[k])); } return 0; }',
    "1\n2\n3")

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
