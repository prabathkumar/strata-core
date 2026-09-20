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

        # A dependency has dependencies of its own. shop -> money -> fmtlib:
        # fmtlib is never named by shop, and shop must still get it.
        fmt = os.path.join(tmp, "fmt")
        write(os.path.join(fmt, "Strata.toml"), '[package]\nname = "fmtlib"\n')
        write(os.path.join(fmt, "src", "pad.sta"),
              'import mem from std;\nimport str from std;\n\n'
              'str pad_left(str s, int width) {\n'
              '    StringBuilder sb = sb_new();\n'
              '    int n = str_len(s);\n'
              '    for (int i = n; i < width; i = i + 1) { sb_append(&sb, " "); }\n'
              '    sb_append(&sb, s);\n'
              '    return sb_to_str(&sb);\n}\n')
        write(os.path.join(lib, "Strata.toml"),
              '[package]\nname = "money"\n\n[dependencies]\n'
              'fmtlib = { path = "../fmt" }\n')
        write(os.path.join(lib, "src", "rounding.sta"),
              'import mem from std;\nimport str from std;\nimport pad from fmtlib;\n\n'
              'str cents(float amount) {\n'
              '    float r = float(int(amount * 100.0 + 0.5)) / 100.0;\n'
              '    return pad_left(str_fixed(r, 2), 8);\n}\n')
        write(os.path.join(app, "src", "main.sta"),
              'import io       from std;\nimport rounding from money;\n\n'
              'int main() {\n    print(cents(12.3456));\n    return 0;\n}\n')

        shutil.rmtree(os.path.join(app, ".strata"), ignore_errors=True)
        r = strata("deps", "-v", cwd=app)
        check("a dependency's own dependency is fetched too",
              r.returncode == 0
              and os.path.isdir(os.path.join(app, ".strata", "deps", "fmtlib")),
              r.stdout[-200:] + r.stderr[-200:])
        if os.path.isfile(lock):
            text = open(lock).read()
            check("the lock says who asked for it",
                  '[fmtlib]' in text and 'asked-by = "money"' in text, text[-200:])
        r = strata("build", cwd=app)
        out = subprocess.run([binary], cwd=app, capture_output=True, text=True,
                             timeout=60) if r.returncode == 0 else None
        check("and the program uses it",
              out is not None and out.stdout.strip() == "12.35",
              (r.stdout + r.stderr)[-300:] if out is None else repr(out.stdout))

        # Two packages naming the same dependency differently. There is no
        # version solving, so this is reported rather than decided.
        other = os.path.join(tmp, "other_fmt")
        write(os.path.join(other, "Strata.toml"), '[package]\nname = "fmtlib"\n')
        write(os.path.join(other, "src", "pad.sta"),
              'str pad_left(str s, int w) { return s; }\n')
        write(os.path.join(app, "Strata.toml"),
              '[package]\nname = "shop"\n\n'
              '[build]\nmain = "src/main.sta"\noutput = "build/shop"\n\n'
              '[dependencies]\nmoney  = { path = "../money" }\n'
              'fmtlib = { path = "../other_fmt" }\n')
        shutil.rmtree(os.path.join(app, ".strata"), ignore_errors=True)
        r = strata("deps", cwd=app)
        check("a disagreement about one name is reported, naming both askers",
              r.returncode != 0 and "disagree" in r.stderr
              and "money" in r.stderr and "other_fmt" in r.stderr,
              r.stderr[-300:])

        # A git dependency, against a repository on disk so the test needs no
        # network. The point of pinning a revision is that upstream moving
        # does not change this build, and nothing checked that until now.
        def git(*args, cwd):
            return subprocess.run(
                ["git", "-c", "user.email=t@example.invalid",
                 "-c", "user.name=test", *args],
                cwd=cwd, capture_output=True, text=True, timeout=120)

        upstream = os.path.join(tmp, "greet")
        write(os.path.join(upstream, "Strata.toml"), '[package]\nname = "greet"\n')
        write(os.path.join(upstream, "src", "hello.sta"),
              'import mem from std;\n\nstr greeting() { return "first"; }\n')
        git("init", "-q", ".", cwd=upstream)
        git("add", "-A", cwd=upstream)
        git("commit", "-qm", "one", cwd=upstream)
        first = git("rev-parse", "HEAD", cwd=upstream).stdout.strip()

        gitapp = os.path.join(tmp, "gitapp")
        write(os.path.join(gitapp, "Strata.toml"),
              '[package]\nname = "gitapp"\n\n[build]\n'
              'main = "src/main.sta"\noutput = "build/gitapp"\n\n'
              '[dependencies]\n'
              f'greet = {{ git = "{upstream}", rev = "{first}" }}\n')
        write(os.path.join(gitapp, "src", "main.sta"),
              'import io    from std;\nimport hello from greet;\n\n'
              'int main() { print(greeting()); return 0; }\n')

        r = strata("deps", "-v", cwd=gitapp)
        check("a git dependency is fetched at its revision", r.returncode == 0,
              r.stdout[-200:] + r.stderr[-200:])
        gitbin = os.path.join(gitapp, "build", "gitapp")
        r = strata("build", cwd=gitapp)
        out = subprocess.run([gitbin], cwd=gitapp, capture_output=True,
                             text=True, timeout=60) if r.returncode == 0 else None
        check("and the program uses it",
              out is not None and out.stdout.strip() == "first",
              (r.stdout + r.stderr)[-300:] if out is None else repr(out.stdout))

        # Upstream moves. The pin is the whole point: this build must not.
        write(os.path.join(upstream, "src", "hello.sta"),
              'import mem from std;\n\nstr greeting() { return "second"; }\n')
        git("commit", "-aqm", "two", cwd=upstream)
        second = git("rev-parse", "HEAD", cwd=upstream).stdout.strip()

        strata("deps", cwd=gitapp)
        strata("build", cwd=gitapp)
        out = subprocess.run([gitbin], cwd=gitapp, capture_output=True,
                             text=True, timeout=60)
        check("upstream moving does not change a pinned build",
              out.stdout.strip() == "first", repr(out.stdout))

        manifest = os.path.join(gitapp, "Strata.toml")
        write(manifest, open(manifest).read().replace(first, second))
        strata("deps", cwd=gitapp)
        strata("build", cwd=gitapp)
        out = subprocess.run([gitbin], cwd=gitapp, capture_output=True,
                             text=True, timeout=60)
        check("repinning the revision does change it",
              out.stdout.strip() == "second", repr(out.stdout))

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
