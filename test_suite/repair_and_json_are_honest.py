#!/usr/bin/env python3
"""Two claims the documentation makes, checked against the tools.

Both of these were found by handing the repository to somebody who had never
seen it and asking them to build something. Neither was visible from inside.

  - `strata check --json` printed the same human text it always had. The flag
    was accepted and dropped. Three documents promised a payload a model could
    act on, and that payload is the project's central claim.

  - `strata repair` answered E009 by writing the zero value of the column into
    every insert, reporting "clean" and exiting 0. E009 exists precisely
    because that silently corrupts every row the statement creates. The
    compiler refused to guess and the companion tool guessed, guessed wrong,
    and called it success.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

PROGRAM = """import io from std;
database Ticket { int id; str customer; int hours; str region; }
int main() {
    Ticket <- [id = 101, customer = "Acme", hours = 9];
    print(str(count(Ticket <- [id > 0])));
    return 0;
}
"""

BAD_COLUMN = """import io from std;
database Item { int id; str name; }
int main() {
    list[Item] r = Item <- [nmae == "x"];
    print(str(count(r)));
    return 0;
}
"""


def main():
    print("=" * 64)
    print("  The tools do what the documentation says")
    print("=" * 64)
    failures = []

    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "prog.sta")
        open(p, "w").write(BAD_COLUMN)
        r = subprocess.run([STRATA, "check", p, "--json"],
                           capture_output=True, text=True, cwd=tmp)
        try:
            payload = json.loads(r.stdout)
            print("  check --json returns JSON:      yes")
        except json.JSONDecodeError:
            payload = None
            failures.append(
                "`strata check --json` did not return JSON; it printed: "
                + (r.stdout or r.stderr).strip()[:110])

        if payload is not None:
            for field in ("ok", "stage", "error_count", "diagnostics"):
                if field not in payload:
                    failures.append(f"the JSON payload has no '{field}'")
            ds = payload.get("diagnostics") or []
            if not any(d.get("code") == "E004" for d in ds):
                failures.append(
                    f"no E004 in the payload for an unknown column: "
                    f"{[d.get('code') for d in ds]}")
            for d in ds:
                for field in ("code", "line", "message", "hint"):
                    if field not in d:
                        failures.append(f"a diagnostic has no '{field}'")
                break

        # E009 must not be answered with a default value.
        q = os.path.join(tmp, "insert.sta")
        open(q, "w").write(PROGRAM)
        before = open(q).read()
        r = subprocess.run([STRATA, "repair", q],
                           capture_output=True, text=True, cwd=tmp)
        after = open(q).read()
        out = r.stdout + r.stderr

        if 'region = ""' in after:
            failures.append(
                "repair answered E009 by writing an empty string into the "
                "insert -- the corruption E009 exists to catch")
        if after != before:
            failures.append("repair changed a file it could not honestly fix")
        if r.returncode == 0:
            failures.append(
                f"repair exited 0 having not fixed anything; a clean exit "
                f"means a clean file")
        if "E009" not in out:
            failures.append("repair did not say which diagnostic it refused")
        print(f"  repair refuses E009:            "
              f"{'yes' if after == before else 'NO'}")
        print(f"  and exits non-zero:             "
              f"{'yes' if r.returncode != 0 else 'NO'}")

    if failures:
        for f in failures:
            print(f"  {f}")
        print("=" * 64)
        print("  A documented claim is not true. FAIL")
        return 1

    print("=" * 64)
    print("  Both claims hold. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
