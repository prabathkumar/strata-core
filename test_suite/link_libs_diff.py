#!/usr/bin/env python3
"""The two compilers agree on what to link.

A program's C libraries are not configured anywhere; they are derived from its
own `foreign ... link` declarations and those of everything it imports. The
bootstrap works that out in Python, the self-hosted driver works it out in
Strata, and the linker command they build has to be identical -- a missing
-lpq is a program that compiles and then fails at link time with an undefined
symbol, and an extra one is a dependency the user never asked for.

This compares the two answers, including their order, over every .sta file in
the repository.
"""
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "build", "link_cli")
SKIP_DIRS = {".git", "build", "node_modules", "Claude outputs", "_to_delete",
             "unimplemented", "repair_cases", "typecheck_cases", "verify_cases"}


def load_stage0():
    spec = importlib.util.spec_from_file_location(
        "stage0", os.path.join(ROOT, "bootstrap", "stage0.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def python_flags(stage0, path):
    ast = stage0.parse_file(path)
    mods, _, _, _ = stage0.resolve_imports(ast, path)
    gen = stage0.CodeGen(ast, path, mods)
    gen.generate()
    return " ".join("-l" + lib for lib in dict.fromkeys(gen.link_libs))


def strata_flags(path):
    r = subprocess.run([CLI, ROOT, path], capture_output=True, text=True)
    return r.stdout.strip()


def sources():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.endswith(".sta"):
                yield os.path.join(dirpath, name)


def main():
    if not os.path.isfile(CLI):
        print(f"  building {os.path.relpath(CLI, ROOT)}")
        os.makedirs(os.path.dirname(CLI), exist_ok=True)
        build = subprocess.run(
            [sys.executable, "bootstrap/stage0.py", "compiler/link_cli.sta",
             "-o", CLI], cwd=ROOT, capture_output=True, text=True)
        if build.returncode != 0:
            print(build.stdout + build.stderr)
            print("  Could not build the Strata side. FAIL")
            return 1

    stage0 = load_stage0()
    checked = same = skipped = 0
    divergent = []
    for path in sources():
        rel = os.path.relpath(path, ROOT)
        try:
            expected = python_flags(stage0, path)
        except (Exception, SystemExit):
            # A file the bootstrap cannot parse is not this test's business.
            skipped += 1
            continue
        actual = strata_flags(path)
        checked += 1
        if expected == actual:
            same += 1
        else:
            divergent.append((rel, expected, actual))

    print("=" * 62)
    for rel, expected, actual in divergent:
        print(f"  {rel}")
        print(f"    bootstrap: [{expected}]")
        print(f"    strata:    [{actual}]")
    print(f"  {same}/{checked} agree, {len(divergent)} divergent, {skipped} skipped")
    print("=" * 62)
    if divergent:
        print("  The two compilers disagree about what to link. FAIL")
        return 1
    print("  Both compilers build the same linker command. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
