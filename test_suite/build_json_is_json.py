#!/usr/bin/env python3
"""`strata build --json` answers in JSON, whatever happens.

The README offered this flag and nothing tested it. An audit found it
printing nothing at all -- not JSON, not text, on neither stream -- for a
parse error, a type error and a C failure alike, and exiting 1. Anything
piping it into a parser got an empty string on exactly the occasions it
needed an answer.

Four stages, four shapes of failure, one contract: valid JSON on stdout,
with a stage, an ok flag and a diagnostic list.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

CASES = [
    ("a file that builds", "typecheck", True, '''import io from std;
int main() { print("ok"); return 0; }
'''),
    ("a parse error", None, False, '''import io from std;
int main() { print("ok") return 0; }
'''),
    ("a type error", "typecheck", False, '''import io from std;
database T { int id; }
int main() { T <- [id = "x"]; return 0; }
'''),
    ("a C compiler failure", "cc", False, '''import io from std;
foreign "stdio.h" { int nosuchfn_xyz(int x); }
int main() { print(str(nosuchfn_xyz(1))); return 0; }
'''),
]

passed = failed = 0


def ok(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label} — {detail}")


def main():
    print("\n── strata build --json ─────────────────────────────────────────")
    with tempfile.TemporaryDirectory(prefix="strata-buildjson-") as tmp:
        for label, stage, should_build, src in CASES:
            path = os.path.join(tmp, "p.sta")
            open(path, "w").write(src)
            r = subprocess.run(
                [STRATA, "build", path, "-o", os.path.join(tmp, "p.bin"),
                 "--json"],
                cwd=tmp, capture_output=True, text=True)
            try:
                d = json.loads(r.stdout)
            except json.JSONDecodeError:
                ok(label, False,
                   f"not JSON. exit={r.returncode} "
                   f"stdout={r.stdout[:160]!r} stderr={r.stderr[:160]!r}")
                continue
            problems = []
            for key in ("stage", "ok", "diagnostics"):
                if key not in d:
                    problems.append(f"no {key}")
            if d.get("ok") is not (True if should_build else False):
                problems.append(f"ok={d.get('ok')}, expected {should_build}")
            if stage and d.get("stage") != stage:
                problems.append(f"stage={d.get('stage')!r}, expected {stage!r}")
            if not should_build and not d.get("diagnostics"):
                problems.append("no diagnostics on a failure")
            if not should_build and r.returncode == 0:
                problems.append("exit 0 on a failure")
            for diag in d.get("diagnostics", []):
                for key in ("code", "message"):
                    if key not in diag:
                        problems.append(f"diagnostic without {key}")
            ok(label, not problems, "; ".join(problems))

        # The form CI reaches for: no file named, inside a project.
        proj = os.path.join(tmp, "app")
        subprocess.run([STRATA, "new", "app"], cwd=tmp,
                       capture_output=True, text=True)
        if os.path.isdir(proj):
            r = subprocess.run([STRATA, "build", "--json"], cwd=proj,
                               capture_output=True, text=True)
            try:
                d = json.loads(r.stdout)
                ok("a project with no file named answers in JSON too",
                   d.get("ok") is True, str(d)[:200])
            except json.JSONDecodeError:
                ok("a project with no file named answers in JSON too", False,
                   f"exit={r.returncode} stdout={r.stdout[:160]!r}")
        else:
            ok("a project with no file named answers in JSON too", False,
               "strata new did not make a project")

    print("\n================================================================")
    print(f"  {passed}/{passed + failed} checks passed")
    print("================================================================")
    if failed:
        print("  --json is not always JSON. FAIL")
        return 1
    print("  --json is JSON at every stage, pass or fail. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
