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
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
COMPILER = os.path.join(ROOT, "bootstrap", "stage0.py")


# ── Compiler interface ────────────────────────────────────────────────────────

def diagnose(path: str) -> dict:
    """Compile and return the compiler's structured diagnostics payload."""
    r = subprocess.run([sys.executable, COMPILER, path, "--json"],
                       capture_output=True, text=True, cwd=ROOT)
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
    return None


def repair_llm(source: str, d: dict):
    """Send the diagnostic and source to a language model for a patch.

    Requires ANTHROPIC_API_KEY and network access. The prompt carries the
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

    prompt = f"""You are repairing a program written in Strata.

The Strata compiler rejected it with this diagnostic:

  code:        {d.get('code')}
  class:       {d.get('classification')}
  message:     {d.get('message')}
  location:    line {d.get('line')}, column {d.get('column')}
  hint:        {d.get('hint')}
  remediation: {d.get('remediation_strategy')}

Full source:
```
{source}
```

Return the complete corrected source and nothing else. No explanation, no
code fences. Change only what the diagnostic requires."""

    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=os.environ.get("STRATA_REPAIR_MODEL", "claude-sonnet-4-5"),
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        out = msg.content[0].text.strip()
        out = re.sub(r"^```[a-z]*\n|\n```$", "", out)
        return out if out.strip() else None
    except Exception as e:
        print(f"  [llm] request failed: {e}", file=sys.stderr)
        return None


BACKENDS = {"rules": repair_rules, "llm": repair_llm}


# ── Loop ──────────────────────────────────────────────────────────────────────

def repair(path: str, backend="rules", max_passes=5, dry_run=False) -> int:
    name = backend
    backend_fn = BACKENDS[backend]
    original = open(path).read()
    source = original
    print(f"[Strata Repair] target: {path}   backend: {name}")

    for attempt in range(1, max_passes + 1):
        report = diagnose(path)
        if report.get("ok"):
            print(f"[Strata Repair] clean after {attempt - 1} repair(s).")
            if dry_run and source != original:
                open(path, "w").write(original)
                print("[Strata Repair] dry run — original restored.")
            return 0

        diags = report.get("diagnostics", [])
        print(f"\n  pass {attempt}: {len(diags)} diagnostic(s) at "
              f"stage '{report.get('stage')}'")
        d = diags[0]
        print(f"    {d['code']} {d.get('classification','')} "
              f"(line {d.get('line')}): {d.get('message','')}")

        patched = backend_fn(source, d)
        if patched is None or patched == source:
            print(f"    backend produced no change — stopping.")
            break
        open(path, "w").write(patched)
        source = patched
        print(f"    patch applied, recompiling")

    if dry_run:
        open(path, "w").write(original)
        print("[Strata Repair] dry run — original restored.")
    print("[Strata Repair] unresolved.")
    return 1


def main():
    ap = argparse.ArgumentParser(description="Strata autonomous repair loop")
    ap.add_argument("file")
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="rules")
    ap.add_argument("--max-passes", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true",
                    help="report the repairs but restore the original file")
    a = ap.parse_args()
    if not os.path.exists(a.file):
        print(f"[Strata Repair] no such file: {a.file}", file=sys.stderr)
        return 2
    return repair(a.file, a.backend, a.max_passes, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
