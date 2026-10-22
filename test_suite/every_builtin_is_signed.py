#!/usr/bin/env python3
"""Every prelude builtin has a signature, in both checkers.

This is the actual repair from round 15, and it is a test rather than a code
change because the bug was never in the code.

Three rounds in a row found a builtin with no signature. Each one was given a
signature. The next round found another. Round 15 said why:

    the signature table was patched name-by-name after the last evaluation,
    which is why a third of the builtins are still open: the design is a
    deny-list of known holes, not a type system.

That is correct. A list of names with a list of exceptions beside it will
always be one name behind whoever is looking, because nothing makes the two
lists agree. This test makes them agree:

  * every name the checkers treat as a known builtin must have a signature
  * the two checkers must carry the SAME signatures
  * `native` is the one exemption, and it is named here rather than implied,
    because it is a compiler intrinsic that pastes C into the output rather
    than a function that can have a type

Add a builtin without a signature from now on and the build fails here, with
a message saying which one. That is the difference between a deny-list and a
rule.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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


def sta_names():
    """The names is_runtime_builtin() in compiler/typechecker.sta knows."""
    src = open(os.path.join(ROOT, "compiler", "typechecker.sta")).read()
    m = re.search(r'str known = ",([^"]*)";', src)
    if not m:
        return None
    return {n for n in m.group(1).split(",") if n}


def sta_signatures():
    """The signatures prelude_signatures() carries, as {name: (ret, args)}."""
    src = open(os.path.join(ROOT, "compiler", "typechecker.sta")).read()
    m = re.search(r'return ";([^"]*);";\s*\n\}', src)
    if not m:
        m = re.search(r'return ";(str_len:[^"]*)";', src)
    if not m:
        return None
    out = {}
    for entry in m.group(1).split(";"):
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 2:
            continue
        name, ret = parts[0], parts[1]
        args = tuple(a for a in (parts[2] if len(parts) > 2 else "").split(",") if a)
        out[name] = (ret, args)
    return out


def main():
    print()
    print("── every builtin is signed ─" + "─" * 40)

    from compiler.typechecker import (RUNTIME_BUILTINS, PRELUDE_SIGNATURES,
                                      SIGNATURE_EXEMPT)

    # 1. The oracle's own two lists agree.
    unsigned = sorted(set(RUNTIME_BUILTINS) - set(PRELUDE_SIGNATURES)
                      - set(SIGNATURE_EXEMPT))
    ok("every builtin the oracle knows has a signature",
       not unsigned,
       "unsigned: " + ", ".join(unsigned))

    orphans = sorted(set(PRELUDE_SIGNATURES) - set(RUNTIME_BUILTINS))
    ok("and no signature names something that is not a builtin",
       not orphans, "orphaned: " + ", ".join(orphans))

    ok("the exemption list is exactly what it should be",
       set(SIGNATURE_EXEMPT) == {"native"},
       str(sorted(SIGNATURE_EXEMPT)))

    # 2. The self-hosted checker knows the same names.
    names = sta_names()
    ok("the self-hosted checker's builtin list could be read",
       names is not None, "is_runtime_builtin() did not match")
    if names is not None:
        only_py = sorted(set(RUNTIME_BUILTINS) - names)
        only_sta = sorted(names - set(RUNTIME_BUILTINS))
        ok("the two checkers know the same builtins",
           not only_py and not only_sta,
           f"oracle only: {only_py}; self-hosted only: {only_sta}")

    # 3. And carry the same signatures.
    sigs = sta_signatures()
    ok("the self-hosted checker's signature table could be read",
       sigs is not None, "prelude_signatures() did not match")
    if sigs is not None:
        if names is not None:
            unsigned_sta = sorted(names - set(sigs) - set(SIGNATURE_EXEMPT))
            ok("every builtin the self-hosted checker knows has a signature",
               not unsigned_sta, "unsigned: " + ", ".join(unsigned_sta))

        disagree = []
        for name, (rt, args) in sorted(PRELUDE_SIGNATURES.items()):
            if name not in sigs:
                disagree.append(f"{name}: missing from the self-hosted table")
                continue
            srt, sargs = sigs[name]
            want_rt = rt if rt is not None else "*"
            want_args = tuple(a if a is not None else "*" for a in args)
            if srt != want_rt or sargs != want_args:
                disagree.append(
                    f"{name}: oracle {want_rt}({', '.join(want_args)}) vs "
                    f"self-hosted {srt}({', '.join(sargs)})")
        ok("and the signatures themselves are identical",
           not disagree, "; ".join(disagree[:6]))

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  A builtin can reach a program unchecked. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print(f"  {len(PRELUDE_SIGNATURES)} builtins, all signed, both checkers "
          "agreeing. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
