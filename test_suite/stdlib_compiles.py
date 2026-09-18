#!/usr/bin/env python3
"""Every standard library module compiles and links.

This replaces `stdlib_parses.py`, which asserted that the modules parsed and
nothing more. They did parse. Seven of them also called functions that exist
nowhere in the project, so anything importing them failed at the C linker —
for as long as the suite had existed, reporting "13 parse, 0 fail" the whole
time. Parsing was never the claim worth making.

Two things are checked per module:

  1. It type-checks clean, which since the undefined-call rule means every
     name it calls actually resolves.
  2. A program that imports it and calls into it BUILDS AND RUNS. A module can
     type-check and still fail to link — that is exactly how this went
     unnoticed — so the check has to get as far as a binary that executes.

Modules under std/unimplemented/ are not checked. They are there because they
do not compile; see the README in that directory.

Usage:  python3 test_suite/stdlib_compiles.py
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STD = os.path.join(ROOT, "std")
COMPILER = os.path.join(ROOT, "bootstrap", "stage0.py")

# A call into each module, so the link is actually exercised rather than just
# the declaration being emitted. A module with no entry here is still checked
# for compiling; it is just not linked against.
def has_libpq():
    """Whether this machine can compile against libpq.

    std/postgres.sta declares `foreign "libpq-fe.h"`, so compiling it needs
    the PostgreSQL client headers. A developer without them should be told the
    module was skipped, not handed a build error for a module they are not
    using. CI installs them, so the skip never becomes the normal result
    there.
    """
    import subprocess as sp
    for d in ("/usr/include/postgresql", "/usr/include", "/usr/local/include"):
        if os.path.exists(os.path.join(d, "libpq-fe.h")):
            return True
    try:
        d = sp.run(["pg_config", "--includedir"], capture_output=True,
                   text=True).stdout.strip()
        return bool(d) and os.path.exists(os.path.join(d, "libpq-fe.h"))
    except FileNotFoundError:
        return False


NEEDS_LIBPQ = {"postgres"}

SMOKE = {
    "io":        'print("x"); print_int(1);',
    "core":      'print_line("x"); print_raw(convert_int_to_str(7));',
    "str":       'StringBuilder sb = sb_new(); sb_append(&sb, "a"); sb_append_line(&sb, "b"); print_raw(sb_to_str(&sb));',
    "mem":       'print(str_concat(str_slice("abcdef", 1, 3), str(str_len("xy"))));',
    "ml":        'print(str(verify_model_dimensions(4, 2)));',
    "simd_math": 'print(str(verify_vector_alignment(8)));',
    "postgres":  'print(str(is_database_url("postgres://x/y"))); '
                 'print(resolve_env_path("plain"));',
    "ui":        'ui_begin(); ui_rect(0, 0, 10, 10, 255); '
                 'ui_text(1, 1, "hi", 0, 1); ui_touch(0, 0, 10, 10, "tap"); '
                 'print(ui_hit(5, 5));',
    "metrics":   'int p = metrics_start(); metrics_record(p, 200, 3); '
                 'metrics_record(p, 500, 1500); metrics_refused(p); '
                 'print(metrics_render(p));',
    "telemetry": 'record_telemetry_metric(1, "s", 1.0, 2.0); dispatch_performance_audit();',
    "testing":   'assert_true("t", 1 == 1);',
    "cli":       'print(str(arg_count())); print(arg(0)); print(subcommand()); '
                 'print(str(has_flag("--x"))); print(flag_value("--x")); '
                 'print(positional(0));',
    "json":      'print(json_str("a\\"b")); print(json_field("k", json_int(1))); '
                 'print(json_num(1.5));',
}

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def compiles(path):
    r = subprocess.run([sys.executable, COMPILER, path, "--json"],
                       capture_output=True, text=True, cwd=ROOT, timeout=120)
    import json
    try:
        payload = json.loads(r.stdout)
    except Exception:
        return False, (r.stdout + r.stderr)[-200:]
    if payload.get("ok"):
        return True, ""
    return False, "; ".join(f"{d['code']} {d['message']}"
                            for d in payload.get("diagnostics", [])[:3])


print("\n── Standard library ─────────────────────────────────────────────")

modules = sorted(f[:-4] for f in os.listdir(STD) if f.endswith(".sta"))
if not modules:
    print("  FAIL  no modules found in std/")
    sys.exit(1)

LIBPQ = has_libpq()

for m in modules:
    if m in NEEDS_LIBPQ and not LIBPQ:
        print(f"  SKIP  {m} — the PostgreSQL client headers are not installed")
        continue
    good, why = compiles(os.path.join(STD, m + ".sta"))
    ok(f"{m} type-checks", good, why)

print("\n── Linking against each module ──────────────────────────────────")

for m in modules:
    if m in NEEDS_LIBPQ and not LIBPQ:
        continue
    body = SMOKE.get(m)
    if body is None:
        print(f"  SKIP  {m} — no smoke call defined")
        continue
    d = tempfile.mkdtemp()
    try:
        sta = os.path.join(d, "smoke.sta")
        out = os.path.join(d, "smoke")
        src = "import io from std;\n"
        if m != "io":
            src += f"import {m} from std;\n"
        src += "int main() {\n    " + body + "\n    print(\"linked\");\n    return 0;\n}\n"
        open(sta, "w").write(src)
        r = subprocess.run([sys.executable, COMPILER, sta, "-o", out],
                           capture_output=True, text=True, cwd=ROOT, timeout=120)
        if r.returncode != 0:
            ok(f"{m} links", False, (r.stderr or r.stdout)[-220:])
            continue
        r2 = subprocess.run([out], capture_output=True, text=True, timeout=10)
        ok(f"{m} links and runs", "linked" in r2.stdout,
           f"exit {r2.returncode}: {(r2.stdout + r2.stderr)[-120:]}")
    except Exception as e:
        ok(f"{m} links", False, str(e))
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)

# Nothing under std/ may import a quarantined module: that would put the
# breakage straight back.
print("\n── Quarantine holds ─────────────────────────────────────────────")
quarantined = sorted(f[:-4] for f in os.listdir(os.path.join(STD, "unimplemented"))
                     if f.endswith(".sta")) if os.path.isdir(os.path.join(STD, "unimplemented")) else []
leaks = []
for m in modules:
    text = open(os.path.join(STD, m + ".sta")).read()
    for q in quarantined:
        if f"import {q} " in text or f"import core.{q} " in text:
            leaks.append(f"{m} imports {q}")
ok("no std module imports a quarantined one", not leaks, "; ".join(leaks))

total = PASS + FAIL
print("\n" + "=" * 62)
print(f"  {PASS}/{total} checks passed over {len(modules)} modules "
      f"({len(quarantined)} quarantined)")
print("=" * 62)
if FAIL == 0:
    print("  The standard library compiles, links and runs. OK")
    sys.exit(0)
print(f"  {FAIL} FAILED")
sys.exit(1)
