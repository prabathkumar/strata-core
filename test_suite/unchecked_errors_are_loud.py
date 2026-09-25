#!/usr/bin/env python3
"""An error nobody checked must not look like success.

Strata has no exceptions. A load that meets a damaged file refuses it, says so
on stderr and leaves the table empty -- and a program that does not check
carries on with no rows and no idea. Four of the bugs found in this project's
first fortnight were that shape: the happy path tested, the error path not.

Halting on the spot would be wrong, because a server should not die over one
bad row, so the accounting is at exit instead: an unchecked error means a
non-zero exit code, which a shell script and a CI job both notice. A program
that checks and clears exits normally, because a handled failure is not a
failure.

Both halves are tested here. A test that only proved the first would pass on a
language that always exited 65.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

IGNORES = '''import io from std;
import str from std;
database Sale { int id; int amount; }
int main() {
    load Sale from "bad.tsv";
    print(str(count(Sale <- [id > 0])));
    return 0;
}
'''

HANDLES = '''import io from std;
import str from std;
database Sale { int id; int amount; }
int main() {
    load Sale from "bad.tsv";
    print(str(count(Sale <- [id > 0])));
    if (had_error() == 1) {
        print("handled");
        clear_error();
    }
    return 0;
}
'''

KEEPS = '''import io from std;
import str from std;
int charge(int amount) {
    if (amount <= 0) {
        fail("charge: amount must be positive");
        return 0;
    }
    return amount;
}
int main() {
    charge(-5);
    charge(0);
    print(str_concat("held ", str(errors_held())));
    print(str_concat("first ", error_at(0)));
    clear_error();
    print(str_concat("cleared ", str(errors_held())));
    return 0;
}
'''

CLEAN = '''import io from std;
import str from std;
database Sale { int id; int amount; }
int main() {
    Sale <- [id = 1, amount = 5];
    print(str(count(Sale <- [id > 0])));
    return 0;
}
'''


def run(tmp, name, src):
    path = os.path.join(tmp, name + ".sta")
    with open(path, "w") as f:
        f.write(src)
    binary = os.path.join(tmp, name)
    b = subprocess.run([STRATA, "build", path, "-o", binary],
                       capture_output=True, text=True, cwd=tmp)
    if b.returncode != 0:
        return None, "", (b.stderr or b.stdout)
    r = subprocess.run([binary], capture_output=True, text=True, cwd=tmp)
    return r.returncode, r.stdout, r.stderr


def main():
    print("=" * 64)
    print("  An unchecked error is not success")
    print("=" * 64)
    failures = []

    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "bad.tsv"), "w") as f:
            f.write("1\t12x\n")          # no schema header: refused

        code, out, err = run(tmp, "ignores", IGNORES)
        if code is None:
            failures.append(f"the ignoring program did not build: {err.strip()[:120]}")
        else:
            if code == 0:
                failures.append(
                    "a program that ignored a failed load exited 0; an unchecked "
                    "error must not look like success")
            elif code != 65:
                failures.append(f"expected exit 65 for an unchecked error, got {code}")
            if "nobody checked" not in err:
                failures.append("the exit message does not say an error went unchecked")
            print(f"  ignored  -> exit {code}, message on stderr: "
                  f"{'yes' if 'nobody checked' in err else 'NO'}")

        code, out, err = run(tmp, "handles", HANDLES)
        if code is None:
            failures.append(f"the handling program did not build: {err.strip()[:120]}")
        else:
            if code != 0:
                failures.append(
                    f"a program that checked and cleared the error exited {code}; "
                    f"a handled failure is not a failure")
            if "handled" not in out:
                failures.append("had_error() did not report the failure to the program")
            print(f"  handled  -> exit {code}, saw the error: "
                  f"{'yes' if 'handled' in out else 'NO'}")

        # A function that knows it failed can say so, and two failures before
        # a check both survive. One slot meant the first was lost, which is
        # the case a program hits when one failure causes the next.
        code, out, err = run(tmp, "keeps", KEEPS)
        if code is None:
            failures.append(f"the reporting program did not build: {err.strip()[:120]}")
        else:
            if "held 2" not in out:
                failures.append(
                    f"two reported failures did not both survive: {out.strip()!r}")
            if "first charge: amount must be positive" not in out:
                failures.append("the earliest error is not readable")
            if "cleared 0" not in out:
                failures.append("clear_error() did not drop the held errors")
            if code != 0:
                failures.append(f"a handled failure exited {code}")
            print(f"  reported -> exit {code}, held "
                  f"{'2' if 'held 2' in out else '?'}, cleared "
                  f"{'yes' if 'cleared 0' in out else 'NO'}")

        code, out, err = run(tmp, "clean", CLEAN)
        if code is None:
            failures.append(f"the clean program did not build: {err.strip()[:120]}")
        else:
            if code != 0:
                failures.append(
                    f"a program with no error at all exited {code}: the epilogue is "
                    f"firing when nothing failed")
            print(f"  no error -> exit {code}")

    if failures:
        for f in failures:
            print(f"  {f}")
        print("=" * 64)
        print("  Errors can still pass for success. FAIL")
        return 1

    print("=" * 64)
    print("  Ignored fails, handled passes, clean stays clean. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
