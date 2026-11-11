#!/usr/bin/env python3
"""A module that will not read is reported as that, not as its consequences.

A `native` block holding `'\\0'` is a lex error. When the file holding it was
the one being compiled, the compiler said so exactly, naming the line and the
column. When it was a file somebody IMPORTED, the compiler put that sentence
on standard error as a warning and carried on without it -- and then reported
every function that module provided as undefined, with a hint advising an
import the developer had already written. One bad escape produced eighty-three
of those, and the machine-readable payload, whose entire purpose is that a
machine never has to read compiler prose, carried none of the real cause.

The repair is two halves. The broken import is reported as an E000 against
the file it is in, in the payload. And the cascade behind it is dropped,
because nothing that module declares is visible: every name it would have
provided reads as undefined and every expression built from one reads as the
wrong type. The same reasoning as an unfetched dependency, one level along.

Run: python3 test_suite/a_broken_import_says_so.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

failures = []
passed = 0


def ok(label, cond, detail=""):
    global passed
    if cond:
        passed += 1
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}")
        failures.append(f"{label}: {detail}")


def main():
    print()
    print("── a broken import says so ───" + "─" * 34)

    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "p")
        src = os.path.join(proj, "src")
        os.makedirs(src)
        open(os.path.join(proj, "Strata.toml"), "w").write(
            '[project]\nname = "p"\nmain = "src/main.sta"\n')
        # A lex error, in an imported file, inside a native block.
        open(os.path.join(src, "helper.sta"), "w").write(
            'int helper_value() { native "char c = \'\\0\'; return (int64_t)c;"; }\n'
            'int helper_two() { return 2; }\n')
        open(os.path.join(src, "main.sta"), "w").write(
            "import io from std;\n"
            "import helper from app;\n"
            "int main() {\n"
            "    print(str(helper_value()));\n"
            "    print(str(helper_two()));\n"
            "    return 0;\n"
            "}\n")

        r = subprocess.run([STRATA, "check", "src/main.sta", "--json"],
                           cwd=proj, capture_output=True, text=True,
                           timeout=600)
        try:
            payload = json.loads(r.stdout)
        except ValueError:
            payload = None
        ok("the machine-readable output is still valid JSON",
           payload is not None, r.stdout[:200])
        if payload is None:
            return 1

        diags = payload.get("diagnostics", [])
        codes = [d.get("code") for d in diags]
        ok("it reports the file that could not be read",
           any(c == "E000" for c in codes), f"codes={codes}")
        ok("and names which file, not the one being compiled",
           any("helper.sta" in (d.get("file") or "") for d in diags),
           json.dumps(diags)[:400])
        ok("and carries the lexer's own sentence",
           any("is not an escape" in (d.get("message") or "") for d in diags),
           json.dumps(diags)[:400])

        # The whole point: the consequences are gone.
        ok("nothing it would have provided is reported as undefined",
           "E011" not in codes, f"codes={codes}")
        ok("and there is one diagnostic, not a page of them",
           len(diags) == 1, f"{len(diags)} diagnostics: {codes}")

        ok("the hint says to fix that file before trusting anything else",
           any("Fix that file first" in (d.get("hint") or "") for d in diags),
           json.dumps(diags)[:400])

        ok("and the check does not pass", r.returncode != 0 and
           payload.get("ok") is False, f"rc={r.returncode}")

        # The prose path leads to the same place.
        r2 = subprocess.run([STRATA, "check", "src/main.sta"], cwd=proj,
                            capture_output=True, text=True, timeout=600)
        text = r2.stdout + r2.stderr
        ok("the human-readable path names the real cause too",
           r2.returncode != 0 and "is not an escape" in text, text[-300:])

        # And a sound project is untouched by any of this.
        open(os.path.join(src, "helper.sta"), "w").write(
            "int helper_value() { return 1; }\n"
            "int helper_two() { return 2; }\n")
        r3 = subprocess.run([STRATA, "check", "src/main.sta", "--json"],
                            cwd=proj, capture_output=True, text=True,
                            timeout=600)
        try:
            good = json.loads(r3.stdout)
        except ValueError:
            good = {}
        ok("and a project whose imports all read is still clean",
           r3.returncode == 0 and good.get("ok") is True,
           (r3.stdout + r3.stderr)[-300:])

    print()
    print("=" * 62)
    print(f"  {passed} ok, {len(failures)} failed")
    print("=" * 62)
    if failures:
        for f in failures:
            print("  - " + f[:300])
        print("  A broken import hides behind its consequences again. FAIL")
        return 1
    print("  A broken import says what it is. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
