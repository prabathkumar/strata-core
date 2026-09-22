#!/usr/bin/env python3
# STRATA — Conformance Test Suite — E001-E006 + End-to-End
import shutil
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

def check_codes(name, source, expect=None, reject=None, files=None):
    """Compile with --json and assert on the diagnostics.

    The undefined-call rule only arms once imports are resolved, which happens
    inside the compiler, so it cannot be reached through the bare TypeChecker
    the `test` helper uses.
    """
    global PASS, FAIL
    d = tempfile.mkdtemp()
    try:
        for fn, content in (files or {}).items():
            os.makedirs(os.path.dirname(os.path.join(d, fn)) or d, exist_ok=True)
            open(os.path.join(d, fn), "w").write(content)
        sta = os.path.join(d, "case.sta")
        open(sta, "w").write(source)
        r = subprocess.run(["python3", "bootstrap/stage0.py", sta, "--json"],
                           capture_output=True, text=True, timeout=60)
        try:
            payload = json.loads(r.stdout)
        except Exception:
            print(f"  FAIL  {name} — no JSON: {(r.stdout + r.stderr)[:120]}"); FAIL += 1; return
        msgs = [f"{x['code']} {x['message']}" for x in payload.get("diagnostics", [])]
        if expect and not any(expect in m for m in msgs):
            print(f"  FAIL  {name} — expected {expect!r}, got {msgs or 'no errors'}"); FAIL += 1; return
        if reject and any(reject in m for m in msgs):
            print(f"  FAIL  {name} — {reject!r} fired and should not have: {msgs}"); FAIL += 1; return
        print(f"  PASS  {name}"); PASS += 1
    except Exception as e:
        print(f"  FAIL  {name} — {e}"); FAIL += 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def compile_run_in(name, source, expected, files=None, runs=1):
    """Compile and run in a scratch directory, optionally seeding files first.

    Persistence and migration can only be checked by writing a file with one
    schema and reading it with another, which needs two programs and a shared
    directory.
    """
    global PASS, FAIL
    d = tempfile.mkdtemp()
    try:
        for fn, content in (files or {}).items():
            open(os.path.join(d, fn), "w").write(content)
        outs = []
        for i, src in enumerate(source if isinstance(source, list) else [source]):
            sta = os.path.join(d, f"p{i}.sta"); exe = os.path.join(d, f"p{i}")
            open(sta, "w").write(src)
            r = subprocess.run(["python3", "bootstrap/stage0.py", sta, "-o", exe],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  FAIL  {name} — compile: {r.stderr[-200:]}"); FAIL += 1; return
            r2 = subprocess.run([exe], capture_output=True, text=True, timeout=5, cwd=d)
            outs.append((r2.stdout + r2.stderr).strip())
        got = "\n".join(o for o in outs if o)
        if got == expected.strip():
            print(f"  PASS  {name} — {got.splitlines()[-1] if got else '(no output)'!r}"); PASS += 1
        else:
            print(f"  FAIL  {name} — expected {expected!r} got {got!r}"); FAIL += 1
    except Exception as e:
        print(f"  FAIL  {name} — {e}"); FAIL += 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def compile_render(name, source, expected):
    """Compile, run, and compare the file the program rendered.

    A report that emits only its title still runs and still exits 0. The only
    check that fails when rendering stops working is reading what was written.
    """
    global PASS, FAIL
    d = tempfile.mkdtemp()
    sta = os.path.join(d, "r.sta"); out = os.path.join(d, "r")
    open(sta, "w").write(source)
    try:
        r = subprocess.run(["python3", "bootstrap/stage0.py", sta, "-o", out],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  FAIL  {name} — compile: {r.stderr[-200:]}"); FAIL += 1; return
        subprocess.run([out], capture_output=True, text=True, timeout=5, cwd=d)
        rendered = os.path.join(d, "out.md")
        if not os.path.exists(rendered):
            print(f"  FAIL  {name} — nothing was rendered"); FAIL += 1; return
        got = open(rendered).read().strip()
        if got == expected.strip():
            print(f"  PASS  {name} — {len(got.splitlines())} lines rendered"); PASS += 1
        else:
            print(f"  FAIL  {name} — rendered:\n{got}\n  expected:\n{expected}"); FAIL += 1
    except Exception as e:
        print(f"  FAIL  {name} — {e}"); FAIL += 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def compile_run(name, source, expected):
    """Compile and run, in a scratch directory of its own.

    The scratch directory is not a detail. Programs used to run here, in the
    repository, so the first test that saved a table left its .tsv in the
    working tree -- and a file left behind is a file the next run reads."""
    global PASS, FAIL
    with tempfile.NamedTemporaryFile(suffix=".sta", mode="w", delete=False) as f:
        f.write(source); sta = f.name
    out = sta.replace(".sta", "")
    scratch = tempfile.mkdtemp()
    try:
        r = subprocess.run(["python3", "bootstrap/stage0.py", sta, "-o", out],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  FAIL  {name} — compile: {r.stderr[:60]}"); FAIL += 1; return
        r2 = subprocess.run([out], capture_output=True, text=True, timeout=5,
                            cwd=scratch)
        got = r2.stdout.strip()
        if got == expected.strip():
            print(f"  PASS  {name} — {got!r}"); PASS += 1
        else:
            print(f"  FAIL  {name} — expected {expected!r} got {got!r}"); FAIL += 1
    except Exception as e:
        print(f"  FAIL  {name} — {e}"); FAIL += 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
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
# An insert that names some of the columns used to be valid; the rest were
# written as zeros. It is E009 now — see journey_change.py for why.
test("insert_omits_column",
     'database Audit { int id; str actor; }\nint main() { Audit <- [actor = "prabath"]; return 0; }',
     "E009")
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
# This asserted the opposite -- that a bare handler name in a layout property
# type checks clean. It did, and then the program did not compile: the name
# reached the generated C as an undeclared variable. The test only ever looked
# at the checker's silence, never at whether the thing it permitted could be
# built. Strata has no function values and no browser event loop; a button
# names a route it posts to.
test("layout_handler_reference_is_e001",
     'int on_click() { return 0; }\nlayout C() { window "x" { button "Go" [action = on_click]; } }',
     "E001")
compile_run("a_layout_action_is_a_route",
     'import io from std;\nlayout C() { window "x" { form [action = "/click", method = "post"] { button "Go"; } } }\n'
     'int main() { print("ok"); return 0; }',
     "ok")

print("\n── A byte is a byte on every machine ─────────────────────────────")
# Plain `char` is signed on x86 and unsigned on ARM. Indexing a str used to
# inherit that, so the same byte of the same file read as -30 on one machine
# and 226 on another -- and the lexer's UTF-8 rule, written against the signed
# answer, put every column after a non-ASCII character in the wrong place.
compile_run("a_high_byte_reads_the_same_everywhere",
    'import io from std;\nimport mem from std;\n'
    'int main() { str e = "\u2014"; print(str(e[0])); print(str(e[1])); '
    'print(str(str_len(e))); return 0; }',
    "226\n128\n3")
compile_run("an_ascii_byte_is_its_code_point",
    'import io from std;\nimport mem from std;\n'
    'int main() { str s = "Az"; print(str(s[0])); print(str(s[1])); return 0; }',
    "65\n122")

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
    'database L { int id; str status; }\nreport R { title: "T", datasource: L <- [status == "X"], metrics: { int t = strata_len(rows); } }')

# This case used to read `float t = sum(id);` and was asserted to be clean.
# It was not clean: `sum` does not exist and a metric does not see the columns
# of a row — it sees `rows`, because there is no aggregation to evaluate a
# column across a result set. Nothing checked metrics, so it passed.
test("report_metric_cannot_name_a_column",
    'database L { int id; str status; }\nreport R { title: "T", datasource: L <- [status == "X"], metrics: { int t = id; } }',
    "E001")

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
# A query into a single record used to mean "the first row that matches, or
# none". This test asserted the matching half and there was no test for the
# other one -- where "none" was a raw null that nothing in the language could
# test for, so reading it crashed. The form is refused now; the list form,
# which makes the caller say what zero rows means, is what replaces it.
test("single_record_query_is_e001",
    'database M { int id; str name; }\n'
    'int main() { M hit = M <- [id == 2]; return 0; }', "E001")
compile_run("query_into_a_list_of_rows",
    'import io from std;\ndatabase M { int id; str name; }\n'
    'int main() { M <- [id = 1, name = "a"]; M <- [id = 2, name = "b"];\n'
    '  list[M] hit = M <- [id == 2];\n'
    '  if (count(hit) == 0) { print("none"); return 0; }\n'
    '  for row in hit { print(row.name); }\n'
    '  return 0; }',
    "b")
compile_run("a_query_that_matches_nothing_is_not_a_crash",
    'import io from std;\ndatabase M { int id; str name; }\n'
    'int main() { M <- [id = 1, name = "a"];\n'
    '  list[M] hit = M <- [id == 99];\n'
    '  if (count(hit) == 0) { print("none"); return 0; }\n'
    '  for row in hit { print(row.name); }\n'
    '  return 0; }',
    "none")
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

print("\n── Test runner ───────────────────────────────────────────────────")
import json
import shutil
import subprocess as _sp, tempfile as _tf, os as _os
def run_test_build(name, source, want_exit, want_in_output):
    global PASS, FAIL
    d = _tf.mkdtemp()
    f = _os.path.join(d, "t.sta"); open(f, "w").write(source)
    b = _os.path.join(d, "t")
    r = _sp.run(["python3", "bootstrap/stage0.py", f, "--test", "-o", b],
                capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  FAIL  {name} — build: {r.stderr[:60]}"); FAIL += 1; return
    r2 = _sp.run([b], capture_output=True, text=True)
    out = r2.stdout + r2.stderr
    if r2.returncode == want_exit and want_in_output in out:
        print(f"  PASS  {name}"); PASS += 1
    else:
        print(f"  FAIL  {name} — exit {r2.returncode} (want {want_exit}); output: {out[:70]!r}")
        FAIL += 1

run_test_build("test_all_assertions_pass",
    'int twice(int x) { return x * 2; }\nverify "doubling" { assert twice(21) == 42; }',
    0, "0 failed")
run_test_build("test_failure_is_reported_and_exits_nonzero",
    'int half(int x) { return x / 2; }\nverify "halving" { assert half(7) == 4; }',
    1, "1 failed")
run_test_build("test_failure_does_not_hide_later_assertions",
    'verify "several" { assert 1 == 2; assert 2 == 3; assert 1 == 1; }',
    1, "3 assertion(s), 2 failed")

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


print("\n── Stream dispatch ──────────────────────────────────────────────")

compile_run("e2e_stream_dispatch_in_order",
    'import io from std;\nstream Ingest(str message) { print(strata_concat("handled: ", current_message())); }\nstream Audit(str message) { print(strata_concat("audited: ", message)); }\nint main() { strata_publish("Ingest", "order-1"); strata_publish("Audit", "order-1"); strata_publish("Ingest", "order-2"); int delivered = strata_run(); print(strata_concat("delivered: ", str(delivered))); return 0; }',
    "handled: order-1\naudited: order-1\nhandled: order-2\ndelivered: 3")

compile_run("e2e_stream_publish_unknown_channel_is_dropped",
    'import io from std;\nstream Ingest(str message) { print(current_message()); }\nint main() { strata_publish("Nobody", "x"); int delivered = strata_run(); print(strata_concat("delivered: ", str(delivered))); return 0; }',
    "delivered: 0")

compile_run("e2e_stream_handler_may_publish",
    'import io from std;\nstream A(str message) { print(strata_concat("a: ", message)); strata_publish("B", message); }\nstream B(str message) { print(strata_concat("b: ", message)); }\nint main() { strata_publish("A", "go"); int n = strata_run(); print(str(n)); return 0; }',
    "a: go\nb: go\n2")


print("\n── Query expressions ────────────────────────────────────────────")

_DB = 'import io from std;\ndatabase Orders { int id; str name; }\n'

compile_run("e2e_query_in_call_argument",
    _DB + 'int main() { Orders <- [id = 1, name = "a"]; Orders <- [id = 2, name = "b"]; Orders <- [id = 3, name = "c"]; print(str(strata_len(Orders <- [id > 1]))); return 0; }',
    "2")

compile_run("e2e_query_matching_nothing_is_empty",
    _DB + 'int main() { Orders <- [id = 1, name = "a"]; print(str(strata_len(Orders <- [id > 99]))); return 0; }',
    "0")

compile_run("e2e_query_passed_to_a_function",
    _DB + 'int count(list[Orders] rows) { return strata_len(rows); }\nint main() { Orders <- [id = 1, name = "a"]; Orders <- [id = 2, name = "b"]; print(str(count(Orders <- [id > 0]))); return 0; }',
    "2")

compile_run("e2e_query_expression_and_declaration_agree",
    _DB + 'int main() { Orders <- [id = 1, name = "a"]; Orders <- [id = 2, name = "b"]; list[Orders] d = Orders <- [id > 0]; print(str(strata_len(d) == strata_len(Orders <- [id > 0]))); return 0; }',
    "1")

test("query_expression_bad_column_is_E004",
    _DB + 'int main() { print(str(strata_len(Orders <- [nope > 1]))); return 0; }',
    "E004")

test("query_expression_unknown_table_is_E004",
    _DB + 'int main() { print(str(strata_len(Nothing <- [id > 1]))); return 0; }',
    "E004")


print("\n── Reports ──────────────────────────────────────────────────────")

_RDB = 'import io from std;\ndatabase Sales { int id; str region; float amount; }\n'

compile_render("e2e_report_renders_rows_and_metrics",
    _RDB + 'report R { title: "Sales", datasource: Sales <- [amount > 100.00], metrics: { int hits = strata_len(rows); } }\nint main() { Sales <- [id = 1, region = "apac", amount = 120.50]; Sales <- [id = 2, region = "emea", amount = 75.00]; render R to "out.md"; return 0; }',
    '# Sales\n\n- hits: 1\n\n| id | region | amount |\n| --- | --- | --- |\n| 1 | apac | 120.5 |\n\n1 row(s).')

compile_render("e2e_report_with_no_matching_rows",
    _RDB + 'report R { title: "Empty", datasource: Sales <- [amount > 999.00], metrics: { int hits = strata_len(rows); } }\nint main() { Sales <- [id = 1, region = "apac", amount = 1.00]; render R to "out.md"; return 0; }',
    '# Empty\n\n- hits: 0\n\n| id | region | amount |\n| --- | --- | --- |\n\n0 row(s).')

test("report_metric_type_mismatch_is_E001",
    _RDB + 'report R { title: "x", datasource: Sales <- [amount > 0.00], metrics: { int hits = "many"; } }\nint main() { render R to "out.md"; return 0; }',
    "E001")

test("report_datasource_bad_column_is_E004",
    _RDB + 'report R { title: "x", datasource: Sales <- [amonut > 0.00], metrics: { int hits = strata_len(rows); } }\nint main() { render R to "out.md"; return 0; }',
    "E004")


print("\n── Schema migration ─────────────────────────────────────────────")

_W = 'import io from std;\ndatabase T { int id; str name; float amt; }\nint main() { T <- [id = 1, name = "a", amt = 1.50]; T <- [id = 2, name = "b", amt = 2.50]; save T to "t.tsv"; print("saved"); return 0; }'

compile_run_in("migrate_round_trip",
    [_W, 'import io from std;\ndatabase T { int id; str name; float amt; }\nint main() { load T from "t.tsv"; print(str(strata_len(T <- [id > 0]))); return 0; }'],
    "saved\n2")

compile_run_in("migrate_column_dropped_and_added",
    [_W, 'import io from std;\ndatabase T { int id; str currency; }\nint main() { load T from "t.tsv"; list[T] r = T <- [id > 0]; T first = r[0]; print(strata_concat(str(first.id), strata_concat(" cur=[", strata_concat(first.currency, "]")))); return 0; }'],
    "saved\n1 cur=[]")

compile_run_in("migrate_columns_reordered_match_by_name",
    [_W, 'import io from std;\ndatabase T { float amt; str name; int id; }\nint main() { load T from "t.tsv"; list[T] r = T <- [id == 2]; T x = r[0]; print(strata_concat(x.name, strata_concat(" ", str(x.amt)))); return 0; }'],
    "saved\nb 2.5")

compile_run_in("migrate_type_change_is_refused",
    [_W, 'import io from std;\ndatabase T { int id; str name; str amt; }\nint main() { int ok = 0; load T from "t.tsv"; print(str(strata_len(T <- [id > 0]))); return 0; }'],
    "saved\n0\n[STRATA LOAD] T: refusing to read 't.tsv' — column 'amt' changed type since it was saved")

compile_run_in("migrate_headerless_file_is_refused",
    ['import io from std;\ndatabase T { int id; str name; }\nint main() { load T from "t.tsv"; print(str(strata_len(T <- [id > 0]))); return 0; }'],
    "0\n[STRATA LOAD] T: refusing to read 't.tsv' — no schema header; it was written before headers existed. Re-save it.",
    files={"t.tsv": "1\ta\n2\tb\n"})

print("\n── Model layers ─────────────────────────────────────────────────")

_NN = ('import io from std;\nmodel M {\n    input:  tensor[float, 1, 2];\n'
       '    hidden: 3 relu;\n    hidden: 2 relu;\n    output: tensor[float, 1, 1];\n}\n'
       'int main() { tensor[float, 1, 2] x = strata_tensor(2); strata_tensor_set(x, 0, 1.0); '
       'strata_tensor_set(x, 1, 2.0); if (strata_model_load(M, "w.txt") == 0) { print("refused"); } '
       'tensor[float, 1, 1] y = predict M(x); print(str(strata_tensor_get(y, 0))); return 0; }')

# Every weight and bias 0.5: layer 1 gives 0.5*1+0.5*2+0.5 = 2.0 (x3), layer 2
# gives 0.5*2*3+0.5 = 3.5 (x2), the linear output gives 0.5*3.5*2+0.5 = 4.0.
compile_run_in("nn_two_hidden_relu_layers", [_NN], "4.0",
    files={"w.txt": " ".join(["0.5"] * 20)})

# relu clamps: with negative weights every hidden unit is zero, so only the
# output bias survives.
compile_run_in("nn_relu_clamps_at_zero", [_NN], "0.5",
    files={"w.txt": " ".join(["-1.0"] * 17 + ["0.0", "0.0", "0.5"])})

compile_run_in("nn_short_weight_file_is_refused", [_NN],
    'refused\n0.0\n[STRATA MODEL] \'w.txt\' holds 3 weights; this model needs 20. Not loading a partial model.',
    files={"w.txt": "0.5 0.5 0.5"})

# A model with no hidden layers is one dense layer, exactly as before.
compile_run_in("nn_no_hidden_layers_is_one_dense_layer",
    ['import io from std;\nmodel M { input: tensor[float, 1, 2]; output: tensor[float, 1, 1]; }\n'
     'int main() { tensor[float, 1, 2] x = strata_tensor(2); strata_tensor_set(x, 0, 1.0); '
     'strata_tensor_set(x, 1, 2.0); strata_model_load(M, "w.txt"); '
     'tensor[float, 1, 1] y = predict M(x); print(str(strata_tensor_get(y, 0))); return 0; }'],
    "4.0", files={"w.txt": "1.0 1.0 1.0"})

# sigmoid: every weight and bias zero, so each hidden pre-activation is 0 and
# sigmoid(0) = 0.5. The output layer is linear: 0.5*2*0 + 0 = 0, plus bias 1.
compile_run_in("nn_sigmoid_activation",
    ['import io from std;\nmodel M { input: tensor[float, 1, 2]; hidden: 2 sigmoid; output: tensor[float, 1, 1]; }\n'
     'int main() { tensor[float, 1, 2] x = strata_tensor(2); strata_model_load(M, "w.txt"); '
     'tensor[float, 1, 1] y = predict M(x); print(str(strata_tensor_get(y, 0))); return 0; }'],
    "2.0", files={"w.txt": " ".join(["0.0"] * 6 + ["1.0", "1.0", "1.0"])})

test("nn_unknown_activation_is_rejected",
    'model M { input: tensor[float, 1, 2]; hidden: 3 tanh; output: tensor[float, 1, 1]; }',
    "PARSE")

test("nn_hidden_is_contextual_not_reserved",
    'import io from std;\nint main() { int hidden = 1; int relu = 2; print(str(hidden + relu)); return 0; }')


print("\n── Undefined function calls ─────────────────────────────────────")

# The rule rests entirely on one hand-written list of names the runtime
# provides. If the code generator learns to emit a builtin that the list does
# not know, every program calling it is rejected. This is the guard.
def _builtin_lists_agree():
    global PASS, FAIL
    import re as _re
    from compiler.typechecker import RUNTIME_BUILTINS, CAST_AND_AGGREGATE
    from bootstrap.stage0 import BUILTIN_RETURNS, PREAMBLE_BUILTINS
    emitted = set(BUILTIN_RETURNS) | set(PREAMBLE_BUILTINS)
    missing = emitted - RUNTIME_BUILTINS - CAST_AND_AGGREGATE
    if missing:
        print(f"  FAIL  runtime_builtins_cover_the_code_generator — "
              f"the generator emits {sorted(missing)} but the checker would "
              f"call them undefined"); FAIL += 1
    else:
        print(f"  PASS  runtime_builtins_cover_the_code_generator "
              f"({len(emitted)} emitted names covered)"); PASS += 1

    # And the self-hosted checker carries its own copy of the same list.
    src = open(os.path.join("compiler", "typechecker.sta")).read()
    m = _re.search(r'str known = ",([^"]*)";', src)
    if not m:
        print("  FAIL  strata_builtin_list_found — is_runtime_builtin no longer "
              "holds a comma-separated list"); FAIL += 1; return
    sta_names = {n for n in m.group(1).split(",") if n}
    if sta_names != set(RUNTIME_BUILTINS):
        only_py = sorted(set(RUNTIME_BUILTINS) - sta_names)
        only_sta = sorted(sta_names - set(RUNTIME_BUILTINS))
        print(f"  FAIL  strata_builtin_list_matches_oracle — "
              f"only in oracle: {only_py}, only in .sta: {only_sta}"); FAIL += 1
    else:
        print(f"  PASS  strata_builtin_list_matches_oracle "
              f"({len(sta_names)} names)"); PASS += 1

_builtin_lists_agree()

_STD = 'import io from std;\n'

check_codes("undefined_call_is_E002",
    _STD + 'int main() { return undefined_thing(1); }',
    expect="E002 Undefined function 'undefined_thing'")

check_codes("a_typo_names_the_typo_not_a_C_symbol",
    _STD + 'int helper() { return 1; }\nint main() { return helpr(); }',
    expect="Undefined function 'helpr'")

check_codes("calls_into_std_are_not_undefined",
    _STD + 'int main() { print("hi"); return 0; }',
    reject="Undefined function")

check_codes("runtime_builtins_are_not_undefined",
    _STD + 'int main() { print(strata_concat("a", str(strata_len(strata_tensor(2))))); return 0; }',
    reject="Undefined function")

check_codes("aggregates_are_not_undefined",
    _STD + 'int main() { list[int] xs = [1,2]; int n = len(xs); print(str(n)); return 0; }',
    reject="Undefined function")

check_codes("foreign_declarations_are_not_undefined",
    'foreign "math.h" link "m" { float sqrt(float x); }\nint main() { float r = sqrt(4.0); return 0; }',
    reject="Undefined function")

check_codes("a_database_name_is_not_an_undefined_call",
    _STD + 'database T { int id; }\nint main() { T <- [id = 1]; print(str(strata_len(T <- [id > 0]))); return 0; }',
    reject="Undefined function")

# An import with no local checkout means the picture is incomplete, so the
# rule disarms rather than guessing. Without this, any program using an
# external module would be unusable.
check_codes("an_unresolved_import_disarms_the_rule",
    'import pricing from vendor_sdk;\nint main() { return vendor_only_function(1); }',
    reject="Undefined function")


print("\n── Unresolved imports ───────────────────────────────────────────")

check_codes("unresolved_import_is_E007",
    'import pricing from vendor_sdk;\nimport io from std;\nint main() { print("x"); return 0; }',
    expect="E007")

check_codes("a_resolvable_import_is_not_reported",
    'import io from std;\nint main() { print("x"); return 0; }',
    reject="E007")

# The point of making it an advisory: the build still succeeds. A dependency
# provided at link time is legitimate, and halting on one would make external
# modules unusable.
compile_run_in("an_advisory_does_not_stop_the_build",
    ['import pricing from vendor_sdk;\nimport io from std;\nint main() { print("built"); return 0; }'],
    "built")

# And the reason it is worth reporting at all: an unresolvable import disarms
# the undefined-call check, so without E007 this file would say nothing.
check_codes("an_unresolved_import_is_reported_even_though_calls_are_not",
    'import pricing from vendor_sdk;\nint main() { return vendor_only(1); }',
    expect="E007", reject="Undefined function")


print("\n── Lists carry their length ─────────────────────────────────────")

# len() walked to the first zero, so it returned whatever followed the array
# in memory: len([1,2,3]) was 5 and len([5,7]) was 7. A list carries its count
# in the word before its data now.
compile_run("len_of_an_int_list",
    'import io from std;\nint main() { list[int] a = [1,2,3]; print(str(len(a))); return 0; }',
    "3")
compile_run("len_of_a_two_element_list",
    'import io from std;\nint main() { list[int] a = [5,7]; print(str(len(a))); return 0; }',
    "2")
compile_run("len_of_a_str_list",
    'import io from std;\nint main() { list[str] a = ["a","b","c"]; print(str(len(a))); return 0; }',
    "3")
compile_run("len_of_a_float_list",
    'import io from std;\nint main() { list[float] a = [1.5,2.5]; print(str(len(a))); return 0; }',
    "2")
compile_run("a_list_containing_zero_still_has_its_length",
    'import io from std;\nint main() { list[int] a = [0,0,0]; print(str(len(a))); return 0; }',
    "3")
compile_run("len_of_an_empty_query_is_zero",
    'import io from std;\ndatabase T { int id; }\nint main() { print(str(len(T <- [id > 0]))); return 0; }',
    "0")

print("\n── Aggregates ───────────────────────────────────────────────────")

_ADB = ('import io from std;\ndatabase O { int id; float amount; }\n'
        'int main() { O <- [id = 3, amount = 10.50]; O <- [id = 1, amount = 30.25]; '
        'O <- [id = 2, amount = 20.00]; list[O] r = O <- [id > 0]; ')

compile_run("agg_count", _ADB + 'print(str(count(r))); return 0; }', "3")
compile_run("agg_sum_float", _ADB + 'print(str(sum(r.amount))); return 0; }', "60.75")
compile_run("agg_avg", _ADB + 'print(str(avg(r.amount))); return 0; }', "20.25")
compile_run("agg_min", _ADB + 'print(str(min(r.amount))); return 0; }', "10.5")
compile_run("agg_max", _ADB + 'print(str(max(r.amount))); return 0; }', "30.25")

# The column's type is kept, so an int column sums to an int rather than
# arriving through the float converter.
compile_run("agg_sum_of_an_int_column_is_an_int",
    _ADB + 'print(str(sum(r.id))); return 0; }', "6")
compile_run("agg_min_of_an_int_column_is_an_int",
    _ADB + 'print(str(min(r.id))); return 0; }', "1")

compile_run("agg_over_a_plain_list",
    'import io from std;\nint main() { list[int] xs = [4,1,7]; print(strata_concat(str(sum(xs)), strata_concat(" ", strata_concat(str(min(xs)), strata_concat(" ", str(max(xs))))))); return 0; }',
    "12 1 7")

# An empty result aggregates to zero rather than failing or producing a NaN:
# a report over a filter that matched nothing should render zeroes.
compile_run("agg_of_an_empty_result_is_zero",
    'import io from std;\ndatabase O { int id; float amount; }\nint main() { list[O] r = O <- [id > 0]; print(strata_concat(str(count(r)), strata_concat(" ", str(sum(r.amount))))); return 0; }',
    "0 0.0")

test("agg_unknown_column_is_E004",
    'database O { int id; float amount; }\nint main() { list[O] r = O <- [id > 0]; float t = sum(r.nope); return 0; }',
    "E004")

test("agg_over_a_str_column_is_E003",
    'database O { int id; str name; }\nint main() { list[O] r = O <- [id > 0]; float t = sum(r.name); return 0; }',
    "E003")

test("agg_over_a_non_list_is_E003",
    'import io from std;\nint main() { int n = 5; float t = sum(n); return 0; }',
    "E003")

test("agg_with_two_arguments_is_E002",
    'import io from std;\nint main() { list[int] xs = [1]; float t = sum(xs, xs); return 0; }',
    "E002")

test("count_of_a_non_list_is_E003",
    'import io from std;\nint main() { int n = 5; int c = count(n); return 0; }',
    "E003")


print("\n── String equality compares contents ────────────────────────────")

# `==` on strings compiled to C's pointer comparison. It looked right whenever
# both sides were literals in the same binary — which is every test that
# existed — and failed the moment one side came from a file or was built at
# runtime. `status == "OPEN"` matched every row before a save and no row after
# a load.
compile_run("str_eq_literal_and_built_value",
    'import io from std;\nint main() { str a = "OPEN"; str b = strata_concat("OP", "EN"); if (a == b) { print("equal"); } return 0; }',
    "equal")

compile_run("str_neq_is_also_by_content",
    'import io from std;\nint main() { str a = "OPEN"; str b = strata_concat("OP", "EN"); if (a != b) { print("differ"); } else { print("same"); } return 0; }',
    "same")

compile_run("str_eq_distinguishes_different_content",
    'import io from std;\nint main() { str a = "OPEN"; str b = strata_concat("CLOS", "ED"); if (a == b) { print("equal"); } else { print("differ"); } return 0; }',
    "differ")

# The case that found it: a string query after a round trip through disk.
compile_run_in("str_query_matches_after_a_load",
    ['import io from std;\ndatabase T { int id; str status; }\n'
     'int main() { T <- [id = 1, status = "OPEN"]; T <- [id = 2, status = "CLOSED"]; '
     'save T to "t.tsv"; print("saved"); return 0; }',
     'import io from std;\ndatabase T { int id; str status; }\n'
     'int main() { load T from "t.tsv"; print(str(count(T <- [status == "OPEN"]))); return 0; }'],
    "saved\n1")

compile_run("str_eq_on_a_row_field",
    'import io from std;\ndatabase T { int id; str name; }\nint main() { T <- [id = 1, name = "acme"]; list[T] r = T <- [id > 0]; T row = r[0]; if (row.name == "acme") { print("matched"); } return 0; }',
    "matched")


print("\n── The cross-tier contract reaches every file ───────────────────")

# Only the file being compiled had its bodies checked, so a renamed column
# failed the build at the entry point and sailed past the UI tier — the tier
# the whole cross-tier claim is about. The break surfaced later as a C
# compiler error naming a C symbol.
_SCHEMA = 'database Order { int id; float amount; }\n'
_VIEWS = ('import io from std;\nimport schema from app;\n'
          'layout Dash() { window "w" { list[Order] r = Order <- [id > 0]; '
          'for O in r { text str(O.amount); } } }\n')
_MAIN = ('import io from std;\nimport str from std;\nimport mem from std;\n'
         'import schema from app;\nimport views from app;\n'
         'int main() { print(render Dash); return 0; }\n')

check_codes("a_project_builds_across_files", _MAIN,
    reject="E00", files={"schema.sta": _SCHEMA, "views.sta": _VIEWS})

# The renamed column: `amount` is gone, and views.sta is the only file that
# still mentions it.
check_codes("a_renamed_column_breaks_the_ui_tier", _MAIN,
    expect="E004",
    files={"schema.sta": 'database Order { int id; float total_amount; }\n',
           "views.sta": _VIEWS})

def _ui_break_names_the_ui_file():
    global PASS, FAIL
    d = tempfile.mkdtemp()
    try:
        open(os.path.join(d, "schema.sta"), "w").write(
            'database Order { int id; float total_amount; }\n')
        open(os.path.join(d, "views.sta"), "w").write(_VIEWS)
        sta = os.path.join(d, "case.sta")
        open(sta, "w").write(_MAIN)
        r = subprocess.run(["python3", "bootstrap/stage0.py", sta, "--json"],
                           capture_output=True, text=True, timeout=60)
        payload = json.loads(r.stdout)
        files = {x.get("file", "") for x in payload.get("diagnostics", [])}
        if any(f.endswith("views.sta") for f in files):
            print("  PASS  the diagnostic names views.sta, not the entry point")
            PASS += 1
        else:
            print(f"  FAIL  the diagnostic names views.sta — got {files}")
            FAIL += 1
    except Exception as e:
        print(f"  FAIL  the diagnostic names views.sta — {e}"); FAIL += 1
    finally:
        shutil.rmtree(d, ignore_errors=True)

_ui_break_names_the_ui_file()


print("\n── String literals survive code generation ──────────────────────")

# The lexer decodes escapes, so by code generation a `\r` is a real carriage
# return. Only backslash, quote and newline were re-escaped, so a tab went
# through raw (legal in a C literal, by luck) and a carriage return ended the
# line: "\r\n" failed to compile with "missing terminating \" character",
# pointing at generated code the author never wrote.
compile_run("a_carriage_return_in_a_literal_compiles",
    'import io from std;\nimport mem from std;\nint main() { str s = "a\\r\\nb"; print(str(str_len(s))); return 0; }',
    "4")
compile_run("a_tab_in_a_literal_survives",
    'import io from std;\nimport mem from std;\nint main() { str s = "a\\tb"; print(str(str_len(s))); return 0; }',
    "3")

print("\n── Forms ────────────────────────────────────────────────────────")

_F = 'import io from std;\nimport str from std;\nimport mem from std;\nimport http from std;\n'

compile_run("form_value_is_decoded",
    _F + 'int main() { str b = "customer=acme+corp&amount=12.50&note=a%2Fb%20c"; print(http_form_value(b, "customer")); print(http_form_value(b, "note")); return 0; }',
    "acme corp\na/b c")

compile_run("a_missing_form_field_is_empty",
    _F + 'int main() { str b = "a=1"; print(strata_concat("[", strata_concat(http_form_value(b, "nope"), "]"))); return 0; }',
    "[]")

# A field whose name is a prefix of another must not match it.
compile_run("form_value_matches_the_whole_name",
    _F + 'int main() { str b = "amount_total=9&amount=4"; print(http_form_value(b, "amount")); return 0; }',
    "4")

compile_run("a_body_is_what_follows_the_headers",
    _F + 'int main() { str r = strata_concat("POST /x HTTP/1.1\\r\\nHost: h\\r\\n\\r\\n", "a=1&b=2"); print(http_body(r)); return 0; }',
    "a=1&b=2")

# The UI tier collects input, not just renders it.
compile_run("a_layout_renders_a_form",
    'import io from std;\nlayout F() { window "w" { form [action = "/x", method = "post"] { field "who" [placeholder = "name"]; button "Go" [type = "submit"]; } } }\nint main() { print(render F); return 0; }',
    '<!doctype html><meta charset="utf-8"><title>w</title><body><form action="/x" method="post"><input name="who" placeholder="name"><button type="submit">Go</button></form></body>')


print("\n── A query name that is also a variable ─────────────────────────")

# Inside a query a bare name is always the COLUMN. If a variable of the same
# name is in scope, the column wins silently: `Session <- [token == token]`
# compares the column with itself and matches every row. Written as a session
# lookup — which is the natural way to write it — any token authenticates.
_SESS = 'database Session { str token; int user_id; }\n'

test("a_variable_shadowed_by_a_column_is_E008",
    _SESS + 'int lookup(str token) { list[Session] r = Session <- [token == token]; return count(r); }',
    "E008")

test("a_differently_named_variable_is_fine",
    _SESS + 'int lookup(str want) { list[Session] r = Session <- [token == want]; return count(r); }')

test("a_column_compared_with_a_literal_is_fine",
    _SESS + 'int lookup() { list[Session] r = Session <- [token == "abc"]; return count(r); }')

print("\n── Views take their inputs ──────────────────────────────────────")

# Strata has no module-level variables, so a view that filters has to take the
# filter as an argument.
compile_run("a_layout_takes_parameters",
    'import io from std;\nlayout D(str region) { window "w" { text region; } }\nint main() { print(render D("apac")); return 0; }',
    '<!doctype html><meta charset="utf-8"><title>w</title><body><span>apac</span></body>')

# A row's own id has to reach the form that acts on it, which a literal
# attribute cannot carry.
compile_run("an_attribute_value_can_be_computed",
    'import io from std;\ndatabase T { int id; }\nlayout D() { window "w" { list[T] r = T <- [id > 0]; for O in r { field "id" [type = "hidden", value = str(O.id)]; } } }\nint main() { T <- [id = 7]; print(render D); return 0; }',
    '<!doctype html><meta charset="utf-8"><title>w</title><body><input name="id" type="hidden" value="7"></body>')

print("\n── Native blocks and shared buffers ─────────────────────────────")

# A native block returning a `static char[]` hands every caller the SAME
# pointer, so two results alias and the second overwrites the first. That made
# two session tokens identical and every password match.
compile_run("two_results_do_not_alias",
    'import io from std;\nimport str from std;\nimport mem from std;\nimport auth from std;\nint main() { str a = new_session_token(); str b = new_session_token(); if (str_eq(a, b) == 1) { print("ALIASED"); } else { print("distinct"); } return 0; }',
    "distinct")

compile_run("a_wrong_password_is_rejected",
    'import io from std;\nimport str from std;\nimport mem from std;\nimport auth from std;\nint main() { str h = hash_password("right"); print(strata_concat(str(password_matches("right", h)), str(password_matches("wrong", h)))); return 0; }',
    "10")

# A table's rows used to live in a fixed array of 4096. An insert past the end
# was skipped -- no error, no message, exit status zero -- so a program asked
# to store five thousand rows held four thousand and ninety-six and said
# nothing about the other nine hundred and four. Kept here, in the file-backed
# suite, so the fix is proved without needing a database.
compile_run("a_table_holds_more_than_four_thousand_rows",
    'import io from std;\nimport str from std;\nimport mem from std;\n'
    'database Row { int id; str name; }\n'
    'int main() { for (int i = 1; i <= 5000; i = i + 1) '
    '{ Row <- [id = i, name = "x"]; } '
    'print(str(count(Row <- [id > 0]))); return 0; }',
    "5000")

compile_run("and_keeps_them_all_through_a_save_and_a_load",
    'import io from std;\nimport str from std;\nimport mem from std;\n'
    'database Row { int id; str name; }\n'
    'int main() { for (int i = 1; i <= 5000; i = i + 1) '
    '{ Row <- [id = i, name = "x"]; } '
    'save Row to "rows.tsv"; load Row from "rows.tsv"; '
    'print(str(count(Row <- [id > 0]))); return 0; }',
    "5000")

# A filtered load against a file has no WHERE to push down, so the rows are
# read and then dropped. The answer must be the same as the database's.
compile_run("a_filtered_load_from_a_file_gives_the_same_answer",
    'import io from std;\nimport str from std;\nimport mem from std;\n'
    'database Row { int id; str tag; }\n'
    'int main() { Row <- [id = 1, tag = "keep"]; Row <- [id = 2, tag = "drop"]; '
    'Row <- [id = 3, tag = "keep"]; save Row to "f.tsv"; '
    'load Row from "f.tsv" <- [tag == "keep"]; '
    'print(str(count(Row <- [id > 0]))); return 0; }',
    "2")

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
