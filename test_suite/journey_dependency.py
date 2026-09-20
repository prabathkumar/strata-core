#!/usr/bin/env python3
"""Two projects share a library.

Until this existed, sharing code between Strata projects meant copying files
between folders: the copies drift, and nothing can say which version a build
used. This walks the whole thing from an empty directory -- declare a
dependency, resolve it, build against it, change the library and see the
change -- and checks the ways it can go wrong say so clearly.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

passed = 0
failures = []


def check(label, ok, detail=""):
    global passed
    if ok:
        passed += 1
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}")
        failures.append(f"{label}{': ' + detail if detail else ''}")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def strata(*args, cwd):
    return subprocess.run([STRATA, *args], cwd=cwd, capture_output=True,
                          text=True, timeout=300)


LIB_ROUNDING = '''import mem from std;

float to_cents(float amount) {
    float scaled = amount * 100.0;
    return float(int(scaled + 0.5)) / 100.0;
}
'''

APP_MAIN = '''import io       from std;
import str      from std;
import rounding from money;

int main() {
    print(str_fixed(to_cents(12.3456), 2));
    return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory() as tmp:
        lib = os.path.join(tmp, "money")
        app = os.path.join(tmp, "shop")
        write(os.path.join(lib, "Strata.toml"),
              '[package]\nname = "money"\nversion = "0.1.0"\n')
        write(os.path.join(lib, "src", "rounding.sta"), LIB_ROUNDING)
        write(os.path.join(app, "Strata.toml"),
              '[package]\nname = "shop"\nversion = "0.1.0"\n\n'
              '[build]\nmain = "src/main.sta"\noutput = "build/shop"\n\n'
              '[dependencies]\nmoney = { path = "../money" }\n')
        write(os.path.join(app, "src", "main.sta"), APP_MAIN)

        # Before resolving, the import has nothing behind it. That is an
        # advisory, not a failure -- but the program cannot link.
        r = strata("build", cwd=app)
        check("an unresolved dependency does not silently succeed",
              r.returncode != 0, r.stdout[-200:] + r.stderr[-200:])

        r = strata("deps", "-v", cwd=app)
        check("strata deps resolves it", r.returncode == 0,
              r.stdout[-300:] + r.stderr[-300:])
        check("the dependency is in place",
              os.path.isdir(os.path.join(app, ".strata", "deps", "money")))

        lock = os.path.join(app, "Strata.lock")
        check("a lock file is written", os.path.isfile(lock))
        if os.path.isfile(lock):
            text = open(lock).read()
            check("the lock records the dependency as declared",
                  '[money]' in text and 'kind = "path"' in text
                  and 'path = "../money"' in text, text[:200])
            check("the lock holds no machine-specific path",
                  tmp not in text,
                  "an absolute path from this machine leaked into the lock")

        r = strata("build", cwd=app)
        check("the app builds against it", r.returncode == 0,
              r.stdout[-300:] + r.stderr[-300:])

        binary = os.path.join(app, "build", "shop")
        if os.path.isfile(binary):
            out = subprocess.run([binary], cwd=app, capture_output=True,
                                 text=True, timeout=60)
            check("and runs, using the library's code",
                  out.stdout.strip() == "12.35", repr(out.stdout))
        else:
            check("and runs, using the library's code", False, "no binary")

        # A path dependency is linked, not copied: editing the library is
        # visible to the next build. A copy would go stale in silence.
        write(os.path.join(lib, "src", "rounding.sta"),
              LIB_ROUNDING.replace("+ 0.5", "+ 0.0"))
        r = strata("build", cwd=app)
        out = subprocess.run([binary], cwd=app, capture_output=True,
                             text=True, timeout=60) if r.returncode == 0 else None
        check("a change in the library reaches the next build",
              out is not None and out.stdout.strip() == "12.34",
              repr(out.stdout) if out else "build failed")

        # A path that is not there.
        broken = os.path.join(tmp, "broken")
        write(os.path.join(broken, "Strata.toml"),
              '[package]\nname = "broken"\n\n[dependencies]\n'
              'ghost = { path = "../nowhere" }\n')
        r = strata("deps", cwd=broken)
        check("a missing dependency is reported, not ignored",
              r.returncode != 0 and "no such directory" in r.stderr.lower(),
              r.stderr[-200:])

        # A git dependency with no revision cannot be reproduced.
        floating = os.path.join(tmp, "floating")
        write(os.path.join(floating, "Strata.toml"),
              '[package]\nname = "floating"\n\n[dependencies]\n'
              'http2 = { git = "https://example.invalid/h" }\n')
        r = strata("deps", cwd=floating)
        check("a git dependency with no pinned revision is refused",
              r.returncode != 0 and "rev" in r.stderr.lower(), r.stderr[-200:])

        # Nothing declared is not an error.
        plain = os.path.join(tmp, "plain")
        write(os.path.join(plain, "Strata.toml"), '[package]\nname = "plain"\n')
        r = strata("deps", cwd=plain)
        check("a project with no dependencies resolves cleanly",
              r.returncode == 0, r.stderr[-200:])

    print("=" * 64)
    for f in failures:
        print(f"  {f}")
    print(f"  {passed}/{passed + len(failures)} steps passed")
    print("=" * 64)
    if failures:
        print("  Two projects cannot yet share a library. FAIL")
        return 1
    print("  A project can depend on another project's library. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
