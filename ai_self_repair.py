#!/usr/bin/env python3
"""Strata autonomous repair loop.

Runs the real compiler, reads its machine-readable diagnostics, applies a
repair, and recompiles — iterating until the file compiles cleanly or no
further progress can be made.

The loop is deliberately backend-agnostic. A repair backend receives the
source and one structured diagnostic and returns patched source or None:

    def backend(source: str, diagnostic: dict) -> str | None

Two ship here. `rules` is deterministic and offline: it uses the location and
hint the compiler already provides. `llm` sends the diagnostic and the
surrounding source to a language model, which is the intended production
path. Because diagnostics carry a taxonomy classification and remediation
strategy, an LLM backend needs no knowledge of Strata beyond the payload.

Usage:
    python3 ai_self_repair.py path/to/file.sta [--backend rules|llm]
                                               [--max-passes N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.join(ROOT, "bootstrap", "stage0.py")


# ── Compiler interface ────────────────────────────────────────────────────────

def diagnose(path: str, cwd: str = ROOT) -> dict:
    """Compile and return the compiler's structured diagnostics payload.

    `cwd` is the project root when repairing a project, because a project's
    imports resolve relative to it.
    """
    r = subprocess.run([sys.executable, COMPILER, path, "--json"],
                       capture_output=True, text=True, cwd=cwd)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"file": path, "ok": False, "error_count": 1, "stage": "compiler",
                "diagnostics": [{"code": "E999", "classification": "Compiler Failure",
                                 "message": (r.stderr or r.stdout or "no output").strip()[:300],
                                 "line": 0, "column": 0, "hint": "",
                                 "remediation_strategy": ""}]}


# ── Repair backends ───────────────────────────────────────────────────────────

def _line_at(source: str, n: int):
    lines = source.splitlines()
    return lines[n - 1] if 0 < n <= len(lines) else None


def _replace_line(source: str, n: int, new: str) -> str:
    lines = source.splitlines()
    lines[n - 1] = new
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def repair_rules(source: str, d: dict):
    """Deterministic repairs driven by the compiler's own diagnostic.

    Only handles cases where the fix is unambiguous from the hint. Anything
    requiring judgement returns None and is left for the llm backend.
    """
    line_no = d.get("line", 0)
    line = _line_at(source, line_no)
    if not line:
        return None
    code = d.get("code")

    # E004: the hint enumerates the valid columns; pick the closest one.
    if code == "E004":
        m = re.search(r"Column '([^']+)'", d.get("message", ""))
        valid = re.findall(r"'([^']+)'", d.get("hint", ""))
        if m and valid:
            import difflib
            best = difflib.get_close_matches(m.group(1), valid, n=1, cutoff=0.4)
            if best:
                return _replace_line(source, line_no,
                                     re.sub(rf"\b{re.escape(m.group(1))}\b", best[0], line))

    # E001: a str literal assigned to an int/float declaration.
    if code == "E001" and "declared as" in d.get("message", ""):
        m = re.search(r"declared as '(\w+)' but assigned '(\w+)'", d["message"])
        if m and m.group(1) in ("int", "float") and m.group(2) == "str":
            lit = re.search(r'=\s*"([^"]*)"', line)
            if lit:
                digits = re.sub(r"[^0-9.\-]", "", lit.group(1))
                if digits.strip("-.") == "":
                    digits = "0"
                if m.group(1) == "float" and "." not in digits:
                    digits += ".0"
                return _replace_line(source, line_no,
                                     re.sub(r'"[^"]*"', digits, line, count=1))
    # E009: an insert that does not name every column. The column and its
    # declared type are both in the hint, so the fix is unambiguous: name it
    # with the zero value of its type and let a human decide the real one.
    if code == "E009":
        m = re.search(r"omits column '([^']+)'", d.get("message", ""))
        t = re.search(r"is '(\w+)'", d.get("hint", ""))
        if m and t:
            default = {"int": "0", "float": "0.0", "str": '""'}.get(t.group(1))
            if default:
                lines = source.splitlines()
                # The insert may span several lines; the closing bracket is
                # what the new column goes before.
                for n in range(line_no, min(line_no + 8, len(lines)) + 1):
                    cur = lines[n - 1]
                    if "]" in cur:
                        head, sep, tail = cur.rpartition("]")
                        return _replace_line(
                            source, n,
                            f"{head.rstrip()}, {m.group(1)} = {default}{sep}{tail}")
    return None


def repair_llm(source: str, d: dict):
    """Send the diagnostic and source to a language model for a patch.

    Requires ANTHROPIC_API_KEY, and network access unless STRATA_REPAIR_URL
    points at a model running locally. The prompt carries the
    taxonomy classification and remediation strategy straight from the
    compiler, so the model is told what kind of error this is and how the
    language's own authors say to fix it.
    """
    try:
        import anthropic
    except ImportError:
        print("  [llm] anthropic package not installed; skipping", file=sys.stderr)
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  [llm] ANTHROPIC_API_KEY not set; skipping", file=sys.stderr)
        return None

    prompt = _repair_prompt(source, d)
    try:
        # STRATA_REPAIR_URL points the loop at a local model instead of a
        # hosted one: anything speaking the same protocol on localhost, run
        # through Ollama, llama.cpp or a proxy. A repair that never leaves the
        # machine costs nothing per call and keeps the source in the building,
        # which for most enterprises is the part that decides whether an AI
        # repair loop is allowed at all.
        base = os.environ.get("STRATA_REPAIR_URL")
        client = anthropic.Anthropic(base_url=base) if base else anthropic.Anthropic()
        msg = client.messages.create(
            model=os.environ.get("STRATA_REPAIR_MODEL", "claude-sonnet-4-5"),
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        out = msg.content[0].text.strip()
        out = re.sub(r"^```[a-z]*\n|\n```$", "", out)
        return _splice(out, source, d, "llm")
    except Exception as e:
        print(f"  [llm] request failed: {e}", file=sys.stderr)
        return None


def _repair_prompt(source: str, d: dict) -> str:
    """The whole of what a repair backend sends. One place, so the two
    model-backed backends cannot drift apart and be compared as if they had
    not."""
    return f"""You are repairing a program written in Strata.

The Strata compiler rejected it with this diagnostic:

  code:        {d.get('code')}
  class:       {d.get('classification')}
  message:     {d.get('message')}
  location:    line {d.get('line')}, column {d.get('column')}
  hint:        {d.get('hint')}
  remediation: {d.get('remediation_strategy')}

{_window(source, d)}

Return ONLY the corrected version of line {d.get('line')} and nothing else.
No explanation, no code fences, no other lines. If the fix needs more than one
line, return those lines and nothing else. Change only what the diagnostic
requires."""


WINDOW = 8


def _window(source: str, d: dict) -> str:
    """The lines around the error, numbered, instead of the whole file.

    Sending the file made a repair cost the size of the codebase rather than
    the size of the mistake, and a local model's context is small -- 4096
    tokens by default in Ollama -- so a real file silently truncated and the
    model looked unreliable when it was simply being shown half a program.

    It is also a correctness argument rather than a cost one. A model that can
    only see eight lines either side cannot quietly reformat something forty
    lines away, and the diagnostic already carries what the fix needs: the
    code, the line, the column, the hint and the remediation.
    """
    lines = source.splitlines()
    n = d.get("line")
    if not isinstance(n, int) or not (1 <= n <= len(lines)):
        return "Full source:\n```\n" + source + "\n```"
    lo = max(1, n - WINDOW)
    hi = min(len(lines), n + WINDOW)
    shown = "\n".join(
        f"{i:>4} {'>' if i == n else ' '} {lines[i - 1]}"
        for i in range(lo, hi + 1))
    return (f"The lines around it, with the offending one marked `>`:\n"
            f"```\n{shown}\n```")


def repair_claude(source: str, d: dict):
    """Send the diagnostic to Claude Code's CLI and take back patched source.

    This is the backend that needs no API key. `claude -p` is the
    non-interactive mode of the CLI a developer already has signed in, so the
    repair loop runs on a subscription rather than on a secret somebody has to
    provision, store and rotate. That matters more than it sounds: a demo that
    needs a key is a demo that does not get run.

    The prompt is the same payload `llm` sends. The compiler's diagnostic
    carries its own taxonomy classification and remediation strategy, so the
    model is told what kind of error this is and how the language's authors say
    to fix it — no Strata-specific prompt engineering here.
    """
    if shutil.which("claude") is None:
        print("  [claude] the claude CLI is not on PATH; skipping", file=sys.stderr)
        return None

    prompt = _repair_prompt(source, d)
    try:
        r = subprocess.run(["claude", "-p", prompt],
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        print("  [claude] timed out", file=sys.stderr)
        return None
    if r.returncode != 0:
        print(f"  [claude] exited {r.returncode}: {r.stderr.strip()[:200]}",
              file=sys.stderr)
        return None
    out = r.stdout.strip()
    # A model asked for source sometimes wraps it in a fence anyway.
    out = re.sub(r"^```[a-z]*\n", "", out)
    out = re.sub(r"\n```$", "", out)
    return _splice(out, source, d, "claude")


def _splice(out: str, original: str, d: dict, who: str):
    """Put the model's replacement line(s) back into the file.

    The backends still hand the loop a whole file, so only the prompt and this
    changed -- the repair loop, the plausibility rules and the three backends
    are otherwise untouched.
    """
    n = d.get("line")
    lines = original.splitlines()
    if not isinstance(n, int) or not (1 <= n <= len(lines)):
        # No line to splice into: the prompt asked for the whole file.
        return _plausible_source(out, original, who)

    out = re.sub(r"^```[a-z]*\n|\n```$", "", out.strip())
    # A model asked for one line sometimes says "Here is the corrected line:"
    # first. Anything before a line that looks like code is not the answer.
    candidate = [l for l in out.splitlines() if l.strip()]
    if not candidate:
        print(f"  [{who}] the answer was empty; ignoring it", file=sys.stderr)
        return None
    # A reply that restates the whole file is still a usable answer -- take it
    # rather than throwing away a correct repair on a formatting quibble.
    if len(candidate) > 2 * WINDOW + 2:
        return _plausible_source(out, original, who)
    if any(re.match(r"^\s*(here|the|this|i |sure|certainly)\b", l, re.I)
           and "=" not in l and ";" not in l for l in candidate):
        print(f"  [{who}] the answer is prose, not a line of code; ignoring it",
              file=sys.stderr)
        return None

    # Models hand back the code without its indentation, because they were
    # shown a numbered window and the number stood where the whitespace was.
    # Left alone that de-indents the line, the file stops being canonically
    # formatted, and CI fails the build over a repair that was otherwise
    # right. Keep the original line's indent when the answer brought none.
    replacement = out.splitlines()
    indent = re.match(r"^[ \t]*", lines[n - 1]).group(0)
    if indent and replacement and not replacement[0][:1].isspace():
        replacement = [indent + replacement[0]] + replacement[1:]

    patched = lines[:n - 1] + replacement + lines[n:]
    result = "\n".join(patched) + ("\n" if original.endswith("\n") else "")
    if result == original:
        return None
    return result


def _plausible_source(out: str, original: str, who: str):
    """Reject an answer that is not a program.

    A CLI that is installed but not signed in prints a sentence and exits 0.
    Without this the loop wrote that sentence over the file and called it a
    repair — found the first time this ran on a machine where the CLI was
    present and disabled. A repair backend is given a file and must return a
    file; anything that is obviously not one is a failed call, not a patch.
    """
    if not out or "{" not in out:
        print(f"  [{who}] the answer is not source; ignoring it",
              file=sys.stderr)
        return None
    if len(out) < len(original) // 2:
        print(f"  [{who}] the answer is far shorter than the file "
              f"({len(out)} vs {len(original)} bytes); ignoring it",
              file=sys.stderr)
        return None
    return out


def repair_local(source: str, d: dict) -> str | None:
    """Send the diagnostic to a model running on this machine.

    Speaks /v1/chat/completions, which Ollama, LM Studio, llama.cpp's server
    and vLLM all answer, so one code path reaches any of them. Standard
    library only: a repair loop that needs a package installed before it works
    is a repair loop most people never try.

    Why local is the interesting case rather than the cheap one: the source
    never leaves the machine. For most enterprises that is not a preference,
    it is the difference between an AI repair loop being allowed and not. The
    price per call being zero is a bonus.

        STRATA_REPAIR_URL    default http://localhost:11434
        STRATA_REPAIR_MODEL  default qwen2.5-coder:7b
    """
    import json as _json
    import urllib.error
    import urllib.request

    base = os.environ.get("STRATA_REPAIR_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("STRATA_REPAIR_MODEL", "qwen2.5-coder:7b")
    body = _json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": _repair_prompt(source, d)}],
        "temperature": 0,          # a repair is not a place for invention
        "stream": False,
    }).encode()

    req = urllib.request.Request(f"{base}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            payload = _json.loads(r.read().decode())
    except urllib.error.URLError as e:
        print(f"  [local] no model answered at {base}: {e.reason}. "
              f"Start one (`ollama serve`) or set STRATA_REPAIR_URL.",
              file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [local] request failed: {e}", file=sys.stderr)
        return None

    try:
        out = payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        print(f"  [local] unexpected reply shape: {str(payload)[:160]}",
              file=sys.stderr)
        return None

    out = re.sub(r"^```[a-z]*\n|\n```$", "", out.strip())
    # The same plausibility gate the other backends use. A small model is more
    # likely to return an apology, a diff or half a file, and none of those
    # should reach the source tree.
    return _splice(out, source, d, "local")


BACKENDS = {"rules": repair_rules, "llm": repair_llm, "claude": repair_claude,
            "local": repair_local}


# ── Loop ──────────────────────────────────────────────────────────────────────

def repair(path: str, backend="rules", max_passes=5, dry_run=False,
           cwd: str = ROOT) -> int:
    """Repair until the compilation unit is clean.

    A unit is one file or a whole project, and the difference matters less
    than it looks: the compiler reports which file each diagnostic is in, so
    the loop reads that field and edits that file. Repairing the entry point
    alone was a single-file assumption hiding in the loop, not in the
    compiler — a project's first diagnostic is usually in a module the entry
    point imports.
    """
    backend_fn = BACKENDS[backend]
    originals: dict[str, str] = {}          # path -> content before any repair
    print(f"[Strata Repair] target: {path}   backend: {backend}   root: {cwd}")

    def restore():
        for f, text in originals.items():
            open(f, "w").write(text)

    for attempt in range(1, max_passes + 1):
        report = diagnose(path, cwd)
        if report.get("ok"):
            print(f"[Strata Repair] clean after {attempt - 1} repair(s)"
                  + (f" across {len(originals)} file(s)." if originals else "."))
            if dry_run and originals:
                restore()
                print("[Strata Repair] dry run — originals restored.")
            return 0

        diags = [x for x in report.get("diagnostics", [])
                 if x.get("severity") != "ADVISORY"]
        if not diags:
            print("[Strata Repair] only advisories remain — stopping.")
            break
        print(f"\n  pass {attempt}: {len(diags)} diagnostic(s) at "
              f"stage '{report.get('stage')}'")
        d = diags[0]
        target = os.path.join(cwd, d.get("file") or path)
        if not os.path.exists(target):
            target = path
        print(f"    {d['code']} {d.get('classification','')} "
              f"({os.path.relpath(target, cwd)}:{d.get('line')}): "
              f"{d.get('message','')}")

        source = open(target).read()
        originals.setdefault(target, source)
        patched = backend_fn(source, d)
        if patched is None or patched == source:
            print("    backend produced no change — stopping.")
            break
        open(target, "w").write(patched)
        print("    patch applied, recompiling")

    if dry_run and originals:
        restore()
        print("[Strata Repair] dry run — originals restored.")
    print("[Strata Repair] unresolved.")
    return 1


def main():
    ap = argparse.ArgumentParser(description="Strata autonomous repair loop")
    ap.add_argument("file", nargs="?",
                    help="a .sta file; omit it when --project is given")
    ap.add_argument("--project", metavar="DIR",
                    help="repair a project: its Strata.toml names the entry "
                         "point, and diagnostics are followed into whichever "
                         "of its files they are in")
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="rules")
    ap.add_argument("--max-passes", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true",
                    help="report the repairs but restore the original file")
    a = ap.parse_args()
    if a.project:
        root = os.path.abspath(a.project)
        toml = os.path.join(root, "Strata.toml")
        if not os.path.exists(toml):
            print(f"[Strata Repair] no Strata.toml in {a.project}", file=sys.stderr)
            return 2
        m = re.search(r'^\s*main\s*=\s*"([^"]+)"', open(toml).read(), re.M)
        main_rel = m.group(1) if m else "src/main.sta"
        if not os.path.exists(os.path.join(root, main_rel)):
            print(f"[Strata Repair] {toml} names main = \"{main_rel}\", "
                  f"which does not exist", file=sys.stderr)
            return 2
        return repair(main_rel, a.backend, a.max_passes, a.dry_run, cwd=root)
    if not a.file:
        print("[Strata Repair] give a file or --project DIR", file=sys.stderr)
        return 2
    if not os.path.exists(a.file):
        print(f"[Strata Repair] no such file: {a.file}", file=sys.stderr)
        return 2
    # Compile the file from ITS project, not from wherever the toolchain
    # happens to live. Without this a file inside a `strata new` project was
    # handed to the compiler from the Strata repository, where neither the
    # file nor its `import schema from app` could be found -- so the loop got
    # a compiler failure instead of the E004 that was actually there, and
    # reported "backend produced no change". It looked like a model that could
    # not help rather than a loop that never looked.
    target = os.path.abspath(a.file)
    root = os.path.dirname(target)
    probe = root
    for _ in range(6):
        if os.path.exists(os.path.join(probe, "Strata.toml")):
            root = probe
            break
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return repair(os.path.relpath(target, root), a.backend, a.max_passes,
                  a.dry_run, cwd=root)


if __name__ == "__main__":
    sys.exit(main())
