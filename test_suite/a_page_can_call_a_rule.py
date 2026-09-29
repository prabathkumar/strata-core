#!/usr/bin/env python3
"""The most obvious thing a newcomer writes: a page that calls a rule.

A `database` block, a rule that turns a column into a word, and a `layout`
that renders the rule's answer. That is the README's own pitch, and it did
not build: the render function was emitted before the prototypes, so the C
compiler met the call first, guessed a signature for it, and then reported
conflicting types against the real definition.

`strata check` said the file was fine, and the error the developer saw was
about a function signature they had never written, in a file they had never
written. Both compilers now emit prototypes first.

The same program also carries a literal `%` in its style, which used to be
handed to printf as a conversion specifier.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

SOURCE = '''import io from std;

database Ticket {
    int id;
    int hours;
}

str priority_of(int hours) {
    if (hours > 24) { return "HIGH"; }
    return "LOW";
}

layout Board() {
    window "Board" [width = 600, height = 400] {
        list[Ticket] open = Ticket <- [id > 0];
        column [padding = 20] {
            text "50% of tickets are urgent";
            for T in open {
                row {
                    text priority_of(T.hours);
                }
            }
        }
    }
}

int main() {
    Ticket <- [id = 1, hours = 48];
    render Board to "board.html";
    return 0;
}
'''

passed = failed = 0


def ok(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label} — {detail}")


def main():
    print("\n── a page that calls a rule ─────────────────────────────────────")
    with tempfile.TemporaryDirectory(prefix="strata-page-rule-") as tmp:
        src = os.path.join(tmp, "board.sta")
        open(src, "w").write(SOURCE)

        r = subprocess.run([STRATA, "check", src], cwd=tmp,
                           capture_output=True, text=True)
        ok("the checker accepts it", r.returncode == 0,
           (r.stdout + r.stderr)[-300:])

        r = subprocess.run([STRATA, "run", src], cwd=tmp,
                           capture_output=True, text=True)
        out = r.stdout + r.stderr
        # The whole point: what the checker accepts, the build accepts.
        ok("and so does the build", r.returncode == 0, out[-400:])
        ok("with no C compiler error about a signature nobody wrote",
           "conflicting types" not in out, out[-300:])
        ok("and no unknown conversion in a format string",
           "unknown conversion" not in out, out[-300:])

        page = os.path.join(tmp, "board.html")
        ok("the page was written", os.path.isfile(page))
        html = open(page).read() if os.path.isfile(page) else ""
        ok("the rule ran and its answer is on the page",
           "HIGH" in html, html[:200])
        # Doubled in the C source, single in the output.
        ok("a literal per-cent survives as one character",
           "50% of tickets" in html, html[:300])
        ok("and so does a per-cent in a style",
           "width:100%;" in html or 'width:100%"' in html, html[:300])

    print("\n================================================================")
    print(f"  {passed}/{passed + failed} checks passed")
    print("================================================================")
    if failed:
        print("  A page cannot call a rule. FAIL")
        return 1
    print("  A page can call a rule, and a per-cent sign is a per-cent sign. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
