#!/usr/bin/env python3
"""Could somebody else use this?

Everything before this proves the language works for the person who has the
repository open. This asks the question their team would ask: can I install
it, does the command work when the source tree is gone, and does my editor
show me anything.

  - the installer refuses a machine with no C compiler, before copying files
  - it installs into a prefix and puts a `strata` on PATH
  - the installed toolchain builds a project in a directory that is not the
    repository and not the install
  - it still works after the source tree it was installed from is deleted
  - `strata new` writes a README with its backticks intact
  - the editor extension's diagnostic parser turns real compiler output into
    the right lines and columns

What this found on the way in:

  - `strata new` ran the backticked `src/schema.sta` in its README heredoc as
    a shell command. Every project created printed an error, and the README
    came out with the backticks eaten. An unquoted heredoc delimiter.
  - The first installer shipped `fmt.sta` but not the compiler's other Strata
    sources, so `strata fmt` on an installed toolchain could not build its own
    formatter. The install script's closing check is what caught it.
  - `strata fmt` cached its formatter under the install root, which a user who
    did not run the installer cannot write to.

Usage:  python3 test_suite/journey_install.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS = FAIL = 0


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def run(args, cwd=None, env=None, timeout=900):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


def main():
    tmp = tempfile.mkdtemp(prefix="strata-install-")
    # The installer is run against a copy, so the test can delete the source
    # tree afterwards and see whether the install survives it. Deleting the
    # real repository to find that out would be a short career.
    src = os.path.join(tmp, "src")
    shutil.copytree(ROOT, src, ignore=shutil.ignore_patterns(
        ".git", "build", "__pycache__", "_to_delete", "apps", "examples",
        "test_suite"))
    prefix = os.path.join(tmp, "prefix")
    bindir = os.path.join(tmp, "bin")
    installer = os.path.join(src, "tools", "install.sh")

    try:
        print("── A machine without a compiler is told so ──────────────────────")
        # PATH stripped of everything, so no cc, gcc or clang can be found.
        bare = dict(os.environ)
        bare["PATH"] = os.path.join(tmp, "empty")
        os.makedirs(bare["PATH"], exist_ok=True)
        for tool in ("python3", "bash", "sed", "cp", "mkdir", "rm", "find",
                     "chmod", "cat", "mktemp", "awk", "uname", "dirname"):
            real = shutil.which(tool)
            if real:
                link = os.path.join(bare["PATH"], tool)
                if not os.path.exists(link):
                    os.symlink(real, link)
        r = run(["bash", installer, "--prefix", prefix + "-x",
                 "--bindir", bindir + "-x"], env=bare)
        ok("it refuses rather than failing halfway", r.returncode != 0,
           f"rc={r.returncode}")
        ok("and says what to install", "C compiler" in (r.stdout + r.stderr),
           (r.stdout + r.stderr)[-200:])
        ok("without leaving a half-built prefix behind",
           not os.path.exists(prefix + "-x"))

        print("\n── It installs ─────────────────────────────────────────────────")
        r = run(["bash", installer, "--prefix", prefix, "--bindir", bindir])
        ok("the installer succeeds", r.returncode == 0,
           (r.stdout + r.stderr)[-400:])
        strata = os.path.join(bindir, "strata")
        ok("there is a strata command", os.access(strata, os.X_OK))
        ok("it checked itself by building a project",
           "checked:" in r.stdout, r.stdout[-200:])
        ok("it records the version it installed",
           os.path.exists(os.path.join(prefix, "VERSION")))
        ok("the standard library came with it",
           os.path.exists(os.path.join(prefix, "std", "http.sta")))
        ok("the test suites did not",
           not os.path.exists(os.path.join(prefix, "test_suite")))

        print("\n── A project builds somewhere else entirely ────────────────────")
        work = os.path.join(tmp, "elsewhere")
        os.makedirs(work)
        r = run([strata, "new", "demo"], cwd=work)
        ok("strata new works outside the repository", r.returncode == 0,
           (r.stdout + r.stderr)[-200:])
        ok("and prints nothing but what it did",
           "No such file" not in (r.stdout + r.stderr), r.stderr[-200:])

        proj = os.path.join(work, "demo")
        readme = open(os.path.join(proj, "README.md")).read()
        ok("the README it wrote keeps its backticks",
           "`src/schema.sta`" in readme, readme[-200:])
        ok("and carries the project's name", readme.startswith("# demo"),
           readme[:40])

        r = run([strata, "build"], cwd=proj)
        ok("the project builds", r.returncode == 0, (r.stdout + r.stderr)[-300:])
        binary = os.path.join(proj, "build", "demo")
        ok("and produced a binary", os.access(binary, os.X_OK))
        r = run([binary], cwd=proj)
        ok("which runs", r.returncode == 0 and "items:" in r.stdout,
           r.stdout[:120])

        r = run([strata, "test"], cwd=proj)
        ok("strata test runs the verify blocks", r.returncode == 0
           and "0 failed" in r.stdout, r.stdout[-200:])

        r = run([strata, "fmt", "--check", os.path.join("src", "main.sta")],
                cwd=proj)
        ok("strata fmt works on an installed toolchain", r.returncode == 0,
           (r.stdout + r.stderr)[-300:])

        print("\n── And still works with the source tree gone ───────────────────")
        shutil.rmtree(src)
        ok("the source tree is gone", not os.path.exists(src))
        work2 = os.path.join(tmp, "after")
        os.makedirs(work2)
        r = run([strata, "new", "after"], cwd=work2)
        ok("strata new still works", r.returncode == 0,
           (r.stdout + r.stderr)[-200:])
        r = run([strata, "build"], cwd=os.path.join(work2, "after"))
        ok("and a project still builds", r.returncode == 0,
           (r.stdout + r.stderr)[-300:])

        print("\n── The editor is told what the compiler found ──────────────────")
        ext = os.path.join(ROOT, "editor", "vscode-strata")
        for f in ("package.json", "language-configuration.json",
                  os.path.join("syntaxes", "strata.tmLanguage.json")):
            p = os.path.join(ext, f)
            try:
                json.load(open(p))
                ok(f"{f} is valid JSON", True)
            except Exception as e:
                ok(f"{f} is valid JSON", False, str(e))

        pkg = json.load(open(os.path.join(ext, "package.json")))
        langs = pkg["contributes"]["languages"][0]
        ok("the extension claims .sta", ".sta" in langs["extensions"])

        node = shutil.which("node")
        if not node:
            print("  SKIP  the diagnostic parser — no node on this machine")
        else:
            # Real compiler output, produced here rather than pasted in, so
            # the parser is tested against what the compiler actually prints
            # today and not against what it printed when this was written.
            broken = os.path.join(work, "broken.sta")
            open(broken, "w").write(
                "import io from std;\n"
                "int main() {\n"
                "    int x = \"hello\";\n"
                "    undefined_thing(1);\n"
                "    return 0;\n"
                "}\n")
            r = run([strata, "check", broken], cwd=work)
            text = r.stdout + r.stderr
            ok("the compiler reports both mistakes",
               "E001" in text and "E002" in text, text[-200:])

            script = os.path.join(tmp, "parse.js")
            open(script, "w").write(
                "const {parse} = require(process.argv[2]);\n"
                "const fs = require('fs');\n"
                "console.log(JSON.stringify("
                "parse(fs.readFileSync(process.argv[3], 'utf8'))));\n")
            out_file = os.path.join(tmp, "check.txt")
            open(out_file, "w").write(text)
            r = run([node, script, os.path.join(ext, "diagnostics.js"),
                     out_file])
            ok("the parser runs", r.returncode == 0, r.stderr[-200:])
            got = json.loads(r.stdout) if r.returncode == 0 else []
            codes = [d["code"] for d in got]
            ok("it found both diagnostics", codes == ["E001", "E002"],
               str(codes))
            ok("on the right lines",
               [d["line"] for d in got] == [2, 3], str(got))
            ok("with the hint attached rather than shown as its own problem",
               all(d["hint"] for d in got), str(got))
            ok("and neither marked advisory",
               not any(d["advisory"] for d in got), str(got))

            # E007 — a module with no local checkout — is advisory in the
            # compiler. An editor that paints it red teaches people to ignore
            # red.
            adv = ("[Strata Check] advisory: [E007] 'lexer' from 'compiler' "
                   "has no local checkout (line 8, col 1)\n"
                   "  Hint: Its symbols must be provided at link time\n")
            open(out_file, "w").write(adv)
            r = run([node, script, os.path.join(ext, "diagnostics.js"),
                     out_file])
            got = json.loads(r.stdout) if r.returncode == 0 else []
            ok("an advisory is parsed as advisory",
               len(got) == 1 and got[0]["advisory"], str(got))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"  {PASS}/{PASS + FAIL} steps passed")
    print("=" * 64)
    if FAIL:
        print("  Somebody else could not use this yet. NOT OK")
        return 1
    print("  It installs, it runs from anywhere, and the editor sees it. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
