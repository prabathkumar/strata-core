#!/usr/bin/env python3
"""Rename one column, and check that NO tier is left behind.

This is the project's central claim, written as a test rather than as a
sentence in the README: change one thing in one place, and the compiler finds
every consequence across the database, the rules, the web page and the phone
screen, before the program runs.

It was not true. `apps/orders_mobile/src/screen.sta` carried its own copy of
`database Order`, written out again by hand, with a comment above it saying
there was only one description of an order. A blind evaluator in round 13
renamed `customer` to `client` in the real schema and found:

    bin/strata check apps/orders/src/main.sta
      E004 rules.sta:46:5  Column 'customer' does not exist in 'Order'
      E004 views.sta:76:26 Field 'customer' not in 'Order'

    bin/strata check apps/orders_mobile/src/main.sta
      No errors. OK                       <-- still drawing row.customer

One rename, one tier silently left behind, and the README claiming the
opposite. The web tier worked exactly as advertised; the phone tier had
opted out of the mechanism by copy-paste.

So this checks two things, and the second is the one that keeps it fixed:

  1. A rename in the schema breaks EVERY tier that reads that column --
     including the phone.
  2. No tier re-declares a table that another tier already declares. A copy
     cannot drift if there is no copy, and the only durable fix for a
     copy-paste is a test that notices the paste.
"""
import os
import re
import shutil
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


def check(path, cwd):
    r = subprocess.run([STRATA, "check", path], capture_output=True,
                       text=True, cwd=cwd, timeout=300)
    return r.returncode, r.stdout + r.stderr


def declared_tables(path):
    """The tables a file declares, by name."""
    try:
        with open(path) as f:
            src = f.read()
    except OSError:
        return set()
    return set(re.findall(r"^\s*database\s+(\w+)\s*\{", src, re.M))


def main():
    print()
    print("── one rename, every tier ─" + "─" * 40)

    # ── 1. No tier re-declares another tier's table ──────────────────────
    #
    # Across the whole repository, not only the two apps: a `database` block
    # with the same name in two files is two descriptions of one thing, and
    # the compiler can only check against the one it was given.
    # Scoped to the APPLICATIONS. A standalone example or a one-file test case
    # declaring its own `Order` is not a second description of anything -- it
    # is a whole program. The claim is about tiers of one system sharing one
    # schema, so that is where this looks.
    # Scoped to ONE application at a time -- a directory with a Strata.toml,
    # plus whatever it declares as a dependency. Two separate applications
    # each having their own `Invoice` is two programs, not two descriptions of
    # one thing. The claim is about the tiers of a single system.
    duplicated = []
    for top in ("apps", "site"):
        top_dir = os.path.join(ROOT, top)
        if not os.path.isdir(top_dir):
            continue
        projects = []
        if os.path.isfile(os.path.join(top_dir, "Strata.toml")):
            projects.append(top_dir)
        for n in sorted(os.listdir(top_dir)):
            d = os.path.join(top_dir, n)
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, "Strata.toml")):
                projects.append(d)
        for proj in projects:
            owners = {}
            roots = [proj]
            deps = os.path.join(proj, ".strata", "deps")
            if os.path.isdir(deps):
                roots += [os.path.join(deps, n) for n in sorted(os.listdir(deps))]
            for root in roots:
                for base, dirs, names in os.walk(root):
                    dirs[:] = [d for d in dirs if d not in
                               ("build", ".strata", "_to_delete", "android")]
                    for n in names:
                        if not n.endswith(".sta"):
                            continue
                        full = os.path.join(base, n)
                        rel = os.path.relpath(os.path.realpath(full), ROOT)
                        for t in declared_tables(full):
                            if t in owners and owners[t] != rel:
                                duplicated.append(
                                    f"{os.path.basename(proj)} sees '{t}' in "
                                    f"{owners[t]} and again in {rel}")
                            else:
                                owners[t] = rel
    ok("no tier of one application re-declares another tier's table",
       not duplicated, "; ".join(duplicated))

    # ── 2. A rename reaches every tier ───────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "repo")
        os.makedirs(work)
        # A copy of the WORKING tree, not of HEAD: this has to fail on a bad
        # change before that change is committed, which is the only moment
        # the answer is useful.
        subprocess.run(["tar", "-cf", os.path.join(tmp, "t.tar"),
                        "--exclude=.git", "--exclude=build",
                        "--exclude=.strata", "--exclude=_to_delete",
                        "."],
                       cwd=ROOT, check=False, timeout=300)
        subprocess.run(["tar", "-xf", os.path.join(tmp, "t.tar"), "-C", work],
                       check=False, timeout=300)
        if not os.path.isdir(os.path.join(work, "apps")):
            print("  SKIP  could not export a clean tree to edit")
            return 0
        os.chmod(os.path.join(work, "bin", "strata"), 0o755)

        tiers = {
            "the web service": "apps/orders/src/main.sta",
            "the phone app": "apps/orders_mobile/src/main.sta",
        }

        # Dependencies first. A path dependency is a symlink, so it tracks
        # the real directory live -- but it has to be made INSIDE this copy,
        # or it would point back at the tree this test must not touch.
        subprocess.run([os.path.join(work, "bin", "strata"), "deps"],
                       cwd=os.path.join(work, "apps", "orders_mobile"),
                       capture_output=True, text=True, timeout=300)

        # Everything builds before the rename, so a failure after it is the
        # rename and not the copy.
        for who, path in tiers.items():
            rc, out = check(os.path.join(work, path), work)
            ok(f"{who} builds before the rename", rc == 0, out[-400:])

        schema = os.path.join(work, "apps", "orders", "src", "schema.sta")
        with open(schema) as f:
            src = f.read()
        ok("the schema declares the column being renamed", "str   customer;" in src, "")
        with open(schema, "w") as f:
            f.write(src.replace("str   customer;", "str   client;", 1))

        for who, path in tiers.items():
            rc, out = check(os.path.join(work, path), work)
            ok(f"{who} FAILS after the rename", rc != 0, out[-600:])
            ok(f"and {who} says which column is gone",
               "customer" in out, out[-600:])

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  A tier can be left behind by a rename. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  One description of one thing, and a rename reaches all of it. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
