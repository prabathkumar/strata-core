#!/usr/bin/env python3
"""Tests for the autonomous repair loop.

`ai_self_repair.py` is the project's headline claim: the compiler emits
machine-readable diagnostics carrying a taxonomy classification and a
remediation strategy, and a repair loop reads them, patches the source and
recompiles until it is clean. Until this file existed that claim had no
executable check — the loop could have broken on any change to a diagnostic
message and nothing would have failed.

Two things are tested, and the first matters more:

  1. The JSON contract. The loop reads specific keys out of `--json`. If a key
     is renamed, dropped, or changes shape, the loop degrades to its E999
     fallback and silently repairs nothing. These tests fail loudly instead.

  2. The loop's behaviour: that it converges, that it stops rather than
     spinning when it cannot make progress, that --dry-run restores the file
     byte for byte, and that a clean file is left alone.

The `llm` backend is not tested here — it needs a network and an API key, so
it cannot be a CI gate. What is tested is that it is reachable and that it
declines cleanly when its prerequisites are absent, which is the failure mode
that would otherwise look like a successful no-op.

Usage:  python3 test_suite/self_repair.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPAIR = os.path.join(ROOT, "ai_self_repair.py")
COMPILER = os.path.join(ROOT, "bootstrap", "stage0.py")

PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def write(source):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "case.sta")
    open(p, "w").write(source)
    return d, p


def diagnose(path):
    r = subprocess.run([sys.executable, COMPILER, path, "--json"],
                       capture_output=True, text=True, cwd=ROOT)
    return json.loads(r.stdout)


def run_repair(path, *args):
    r = subprocess.run([sys.executable, REPAIR, path, *args],
                       capture_output=True, text=True, cwd=ROOT, timeout=120)
    return r.returncode, r.stdout + r.stderr


def compiles(path):
    return diagnose(path).get("ok") is True


# ── 1. The JSON contract the loop depends on ──────────────────────────────────

print("\n── Diagnostic payload contract ──────────────────────────────────")

BAD_TYPE = ('import io from std;\n'
            'int main() {\n'
            '    int n = "hello";\n'
            '    print(str(n));\n'
            '    return 0;\n'
            '}\n')

d, p = write(BAD_TYPE)
report = diagnose(p)

# Keys the loop reads directly. Renaming any of these makes the loop fall back
# to E999 and repair nothing, which looks like "no repair was possible".
for key in ("file", "stage", "ok", "error_count", "diagnostics"):
    ok(f"payload has '{key}'", key in report, f"got keys {sorted(report)}")

ok("a broken file reports ok=false", report.get("ok") is False)
ok("error_count matches the diagnostic list",
   report.get("error_count") == len(report.get("diagnostics", [])))

diag = (report.get("diagnostics") or [{}])[0]
for key in ("code", "classification", "message", "line", "column", "hint",
            "remediation_strategy", "file"):
    ok(f"diagnostic has '{key}'", key in diag, f"got keys {sorted(diag)}")

ok("line is an int, not a string", isinstance(diag.get("line"), int),
   f"got {type(diag.get('line')).__name__}")
# The loop patches a file. In a multi-file project the diagnostic is often
# not in the file being compiled, so `file` decides which one it opens.
ok("the diagnostic names its own file",
   bool(diag.get("file")) and diag["file"].endswith(".sta"),
   f"got {diag.get('file')!r}")
ok("remediation_strategy is non-empty",
   bool(str(diag.get("remediation_strategy", "")).strip()))
ok("classification is non-empty",
   bool(str(diag.get("classification", "")).strip()))
shutil.rmtree(d, ignore_errors=True)

# An advisory is reported but must not make ok=false. The loop reads that
# field to decide whether to keep patching, and it cannot fix a dependency
# that is genuinely external — it would burn every pass and report failure on
# a file that compiles.
d, p = write('import pricing from vendor_sdk;\n'
             'import io from std;\n'
             'int main() { print("x"); return 0; }\n')
adv = diagnose(p)
ok("an advisory does not make ok=false", adv.get("ok") is True,
   f"ok={adv.get('ok')} diagnostics={adv.get('diagnostics')}")
ok("an advisory is still reported",
   any(x.get("code") == "E007" for x in adv.get("diagnostics", [])))
ok("the advisory is marked ADVISORY",
   all(x.get("severity") == "ADVISORY"
       for x in adv.get("diagnostics", []) if x.get("code") == "E007"))
ok("payload carries advisory_count", adv.get("advisory_count") == 1,
   f"got {adv.get('advisory_count')}")
ok("error_count excludes advisories", adv.get("error_count") == 0,
   f"got {adv.get('error_count')}")
rc, out = run_repair(p)
ok("the loop does not try to repair an advisory",
   rc == 0 and "clean after 0 repair" in out, out[-160:])
shutil.rmtree(d, ignore_errors=True)

# A clean file must report ok=true with no diagnostics, or the loop would
# never terminate.
d, p = write('import io from std;\nint main() { print("hi"); return 0; }\n')
clean = diagnose(p)
ok("a clean file reports ok=true", clean.get("ok") is True)
ok("a clean file reports no diagnostics", clean.get("diagnostics") == [])
shutil.rmtree(d, ignore_errors=True)

# Parse errors are reported through the same shape, at an earlier stage.
d, p = write('int main() { int x = ; }\n')
pe = diagnose(p)
ok("a parse error uses the same payload shape",
   pe.get("ok") is False and isinstance(pe.get("diagnostics"), list)
   and pe.get("stage") == "parse", f"got {pe.get('stage')!r}")
shutil.rmtree(d, ignore_errors=True)


# ── 2. The loop ───────────────────────────────────────────────────────────────

print("\n── Repair loop ──────────────────────────────────────────────────")

d, p = write(BAD_TYPE)
rc, out = run_repair(p)
ok("E001 str-for-int is repaired", rc == 0, out[-200:])
ok("the repaired file compiles", compiles(p))
ok("the repair is reported, not silent", "patch applied" in out)
shutil.rmtree(d, ignore_errors=True)

BAD_COLUMN = ('database Orders { int id; str customer; }\n'
              'int main() { list[Orders] r = Orders <- [custmer == "acme"]; return 0; }\n')
d, p = write(BAD_COLUMN)
rc, out = run_repair(p)
ok("E004 typo'd column is repaired to the closest valid one", rc == 0, out[-200:])
ok("the repaired query names a real column", "customer" in open(p).read())
shutil.rmtree(d, ignore_errors=True)

# Two errors, one pass each: the loop must keep going rather than stopping at
# the first clean recompile of a single diagnostic.
TWO_ERRORS = ('import io from std;\n'
              'database Orders { int id; str customer; }\n'
              'int main() {\n'
              '    int n = "hello";\n'
              '    list[Orders] r = Orders <- [custmer == "acme"];\n'
              '    print(str(n));\n'
              '    return 0;\n'
              '}\n')
d, p = write(TWO_ERRORS)
rc, out = run_repair(p)
ok("two independent errors are repaired in sequence", rc == 0, out[-300:])
ok("more than one pass was needed", out.count("patch applied") >= 2,
   f"{out.count('patch applied')} patches")
ok("the twice-repaired file compiles", compiles(p))
shutil.rmtree(d, ignore_errors=True)

# Something the rules backend cannot judge. The loop must stop and say so —
# not spin to max-passes, and not claim success.
# E001 where the right-hand side is not a literal. The rules backend only
# rewrites literals, so this is beyond it by design and must be handed off
# rather than guessed at.
UNREPAIRABLE = ('import io from std;\n'
                'str name() { return "x"; }\n'
                'int main() { int n = name(); print(str(n)); return 0; }\n')
d, p = write(UNREPAIRABLE)
before = open(p).read()
rc, out = run_repair(p, "--max-passes", "5")
ok("an unrepairable file exits non-zero", rc != 0)
ok("it says it stopped rather than claiming success",
   "no change" in out and "clean after" not in out, out[-200:])
ok("it stops on the first pass rather than spinning",
   out.count("pass ") == 1, f"{out.count('pass ')} passes")
ok("an unrepairable file is left untouched", open(p).read() == before)
shutil.rmtree(d, ignore_errors=True)

# --dry-run must restore the original byte for byte, including its trailing
# newline, even though a repair was applied along the way.
d, p = write(BAD_TYPE)
rc, out = run_repair(p, "--dry-run")
ok("--dry-run still reports the repair", "patch applied" in out)
ok("--dry-run restores the original exactly", open(p).read() == BAD_TYPE,
   repr(open(p).read()[:80]))
shutil.rmtree(d, ignore_errors=True)

# An already-clean file: no passes, no writes, exit 0.
CLEAN = 'import io from std;\nint main() { print("hi"); return 0; }\n'
d, p = write(CLEAN)
rc, out = run_repair(p)
ok("a clean file needs no repair", rc == 0 and "clean after 0 repair" in out,
   out[-120:])
ok("a clean file is not rewritten", open(p).read() == CLEAN)
shutil.rmtree(d, ignore_errors=True)

# A missing file is an error, not a traceback.
rc, out = run_repair(os.path.join(tempfile.gettempdir(), "no_such_strata_file.sta"))
ok("a missing file exits cleanly", rc == 2 and "Traceback" not in out, out[-120:])


# ── 3. The llm backend declines cleanly ───────────────────────────────────────

print("\n── LLM backend ──────────────────────────────────────────────────")

# Not a network test. The point is that without its prerequisites the backend
# says so and the loop reports unresolved — rather than looking like a
# successful run that happened to change nothing.
env = dict(os.environ)
env.pop("ANTHROPIC_API_KEY", None)
d, p = write(BAD_TYPE)
r = subprocess.run([sys.executable, REPAIR, p, "--backend", "llm"],
                   capture_output=True, text=True, cwd=ROOT, env=env, timeout=120)
out = r.stdout + r.stderr
ok("the llm backend is reachable", "Traceback" not in out, out[-200:])
ok("without a key it declines out loud",
   ("ANTHROPIC_API_KEY not set" in out) or ("not installed" in out), out[-200:])
ok("and the loop reports unresolved rather than success",
   r.returncode != 0 and "clean after" not in out)
shutil.rmtree(d, ignore_errors=True)


# ── 4. The claude backend, where the CLI is available ─────────────────────────

print("\n── Claude backend ───────────────────────────────────────────────")

# `claude -p` is the non-interactive mode of the CLI a developer already has
# signed in, so this backend runs on a subscription rather than on an API key
# somebody has to provision and rotate. A demo that needs a key is a demo that
# does not get run.
#
# It is skipped where the CLI is absent — CI has no Claude credentials — so
# this suite reports it as skipped rather than passing on nothing. What it
# repairs when it does run is E008, the auth bypass: `Session <- [token ==
# token]` compares the column with itself and matches every row. The
# deterministic backend has no rule for that, because the fix is to rename a
# parameter and its uses.

CASE = os.path.join(ROOT, "test_suite", "repair_cases", "e008_auth_bypass.sta")

def claude_answers():
    """Installed is not the same as usable: the CLI can be on PATH and print
    `claude is not enabled in this environment` with a zero exit status."""
    try:
        r = subprocess.run(["claude", "-p", "Reply with exactly: PONG"],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return False
    return r.returncode == 0 and "PONG" in r.stdout


if shutil.which("claude") is None:
    print("  SKIP  the claude CLI is not on PATH")
elif not claude_answers():
    print("  SKIP  the claude CLI is present but not usable here")
elif not os.path.exists(CASE):
    print("  SKIP  the case file is missing")
else:
    d = tempfile.mkdtemp(prefix="strata-repair-claude-")
    p = os.path.join(d, "e008_auth_bypass.sta")
    shutil.copy(CASE, p)

    r = subprocess.run([sys.executable, REPAIR, p, "--backend", "claude",
                        "--max-passes", "3"],
                       capture_output=True, text=True, cwd=ROOT, timeout=600)
    out = r.stdout + r.stderr
    ok("it repairs an E008 the rules backend cannot",
       r.returncode == 0 and "clean after" in out, out[-300:])

    patched = open(p).read()
    # Comments are not code: the case file's own header quotes the broken line
    # to explain it, and an earlier version of this check searched the whole
    # file and failed on a correct repair.
    code = "\n".join(l for l in patched.splitlines()
                     if not l.lstrip().startswith("//"))
    ok("by renaming the parameter rather than the column",
       "Session <- [token == token]" not in code
       and "Session <- [token ==" in code,
       code[code.find("user_for"):][:160])

    binary = os.path.join(d, "e008")
    b = subprocess.run([sys.executable, COMPILER, p, "-o", binary],
                       capture_output=True, text=True, cwd=ROOT, timeout=300)
    ok("and the repaired program builds", b.returncode == 0,
       (b.stdout + b.stderr)[-200:])
    if b.returncode == 0:
        run = subprocess.run([binary], capture_output=True, text=True, timeout=60)
        ok("a forged token no longer authenticates",
           run.stdout.strip() == "0", run.stdout.strip())
    shutil.rmtree(d, ignore_errors=True)


total = PASS + FAIL
print("\n" + "=" * 62)
print(f"  {PASS}/{total} checks passed")
print("=" * 62)
if FAIL == 0:
    print("  The repair loop works and the diagnostic contract holds. OK")
    sys.exit(0)
print(f"  {FAIL} FAILED")
sys.exit(1)
