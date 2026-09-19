#!/usr/bin/env python3
"""The grammar exists once, in two places, and they must not drift.

Syntax highlighting rules live in editor/strata-grammar/ so they can be
published as a repository of their own -- Linguist and several editors take a
grammar only as a standalone repo, not as a folder inside an extension. The
VS Code extension needs its own copy beside its manifest. Two copies of the
same file is a standing invitation to fix a highlighting bug in one of them.

There was a third copy, .vscode/strata.tmLanguage.json, orphaned: a much older
stub with a different scope name, referenced by nothing, that would silently
have done nothing for anyone who edited it. This test also keeps that from
coming back.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANONICAL = os.path.join(ROOT, "editor", "strata-grammar", "strata.tmLanguage.json")
COPIES = [
    os.path.join(ROOT, "editor", "vscode-strata", "syntaxes", "strata.tmLanguage.json"),
]
CONFIG_CANONICAL = os.path.join(ROOT, "editor", "strata-grammar",
                                "language-configuration.json")
CONFIG_COPIES = [
    os.path.join(ROOT, "editor", "vscode-strata", "language-configuration.json"),
]
FORBIDDEN = [os.path.join(ROOT, ".vscode", "strata.tmLanguage.json")]
SCOPE = "source.strata"
EXTENSION = ".sta"

failures = []


def same(canonical, copies, label):
    with open(canonical, "rb") as f:
        want = f.read()
    for copy in copies:
        rel = os.path.relpath(copy, ROOT)
        if not os.path.isfile(copy):
            failures.append(f"{rel} is missing")
            continue
        with open(copy, "rb") as f:
            got = f.read()
        if got != want:
            failures.append(
                f"{rel} has drifted from "
                f"{os.path.relpath(canonical, ROOT)} ({label})")


def main():
    same(CANONICAL, COPIES, "grammar")
    same(CONFIG_CANONICAL, CONFIG_COPIES, "language configuration")

    for path in FORBIDDEN:
        if os.path.isfile(path):
            failures.append(
                f"{os.path.relpath(path, ROOT)} is back. It is an orphaned copy "
                f"nothing reads; the grammar lives in editor/strata-grammar/.")

    grammar = json.load(open(CANONICAL))
    if grammar.get("scopeName") != SCOPE:
        failures.append(f"scopeName is {grammar.get('scopeName')!r}, not {SCOPE!r}")

    manifest = json.load(open(os.path.join(ROOT, "editor", "vscode-strata",
                                           "package.json")))
    contributes = manifest.get("contributes", {})
    scopes = [g.get("scopeName") for g in contributes.get("grammars", [])]
    if SCOPE not in scopes:
        failures.append(f"the extension does not contribute {SCOPE!r}: {scopes}")
    exts = [e for lang in contributes.get("languages", [])
            for e in lang.get("extensions", [])]
    if EXTENSION not in exts:
        failures.append(f"the extension does not claim {EXTENSION!r}: {exts}")

    print("=" * 62)
    for f in failures:
        print(f"  {f}")
    if failures:
        print(f"  {len(failures)} problem(s)")
        print("=" * 62)
        print("  The grammar has drifted. FAIL")
        return 1
    print(f"  grammar, language configuration, scope {SCOPE}, extension {EXTENSION}")
    print("=" * 62)
    print("  One grammar, consistent everywhere. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
