#!/usr/bin/env python3
"""`strata doc` must describe the project that is there, not one that was.

The reason an architecture document is worthless six months after somebody
wrote it is that it was written by hand and nothing kept it honest. This one
is derived from the same parse the build uses, so the test that matters is not
"does it produce output" but "does it change when the code changes".

So: generate it, rename a column, generate it again, and require the new name
to be in the second document and the old name to be gone.
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")


def doc(path):
    r = subprocess.run([STRATA, "doc", path], capture_output=True, text=True,
                       cwd=path)
    return r.returncode, r.stdout, r.stderr


def main():
    print("=" * 64)
    print("  The architecture document describes what is there")
    print("=" * 64)
    failures = []

    with tempfile.TemporaryDirectory() as tmp:
        app = os.path.join(tmp, "app")
        b = subprocess.run([STRATA, "new", "app"], capture_output=True,
                           text=True, cwd=tmp)
        if b.returncode != 0:
            print(f"  could not generate a project: {b.stderr[-160:]}")
            print("=" * 64)
            return 1

        code, out, err = doc(app)
        if code != 0:
            failures.append(f"strata doc exited {code}: {err.strip()[-160:]}")

        for want in ("# Architecture", "### Item", "| `price` | `float` |",
                     "src/main.sta", "int main()"):
            if want not in out:
                failures.append(f"the document does not mention {want!r}")
        if "**Imports:**" not in out:
            failures.append("the document does not list a file's imports")
        print(f"  describes the schema, imports and functions: "
              f"{'yes' if not failures else 'NO'}")

        # The whole claim: it cannot describe a system that is not there.
        schema = os.path.join(app, "src", "schema.sta")
        text = open(schema).read()
        open(schema, "w").write(text.replace("float price;", "float unit_price;"))
        code2, out2, _ = doc(app)
        if "| `unit_price` | `float` |" not in out2:
            failures.append(
                "renaming a column did not change the document: it is not "
                "derived from the code")
        if "| `price` | `float` |" in out2:
            failures.append(
                "the document still shows a column that no longer exists")
        open(schema, "w").write(text)
        print(f"  follows a rename in the schema:              "
              f"{'yes' if '`unit_price`' in out2 else 'NO'}")

        r = subprocess.run([STRATA, "doc", "--help"], capture_output=True,
                           text=True, cwd=app)
        if r.returncode != 0 or "Usage: strata doc" not in r.stdout:
            failures.append("strata doc --help is not help")

    if failures:
        for f in failures:
            print(f"  {f}")
        print("=" * 64)
        print("  The document does not track the code. FAIL")
        return 1

    print("=" * 64)
    print("  Derived from the code, and it follows it. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
