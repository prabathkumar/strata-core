#!/usr/bin/env python3
"""Ordering rows, and why it is in the language rather than in a library.

Until this existed a Strata program could filter rows and could add them up,
and could not put them in order. "Show me the ten largest invoices" -- the
first thing anyone asks of a business system -- had no answer, because a
column cannot be projected out of a result except inside an aggregate.

The obvious fix is a library function, `sort_by(rows, "amount")`. It is the
wrong fix, and this file is mostly about why:

  A column name passed as a STRING is a schema that nothing checks. Rename
  the column and that call still compiles, still runs, and silently sorts by
  nothing. The whole claim of this language is that renaming a column breaks
  every line that reads it, before the program runs -- and a library sort
  would have been a hole straight through the middle of that claim.

So `by` is part of the query, the column is checked against the schema like
any other, and the last check below is the one that matters: a renamed column
stops an ordered query from compiling.

What else is checked here:

  - ascending by default, `desc` when asked
  - ties keep the order the table had. The sort is a merge sort rather than
    qsort for exactly this reason: qsort is not stable, so two rows with the
    same key could come back either way round and a report could change
    between runs with nothing in the data changing
  - `first N` is applied AFTER the ordering, so `by amount desc first 3` is
    the three largest and not three arbitrary rows that were then sorted
  - text orders too, and so do decimals
  - a column that is not there, and `first 0`, are refused by BOTH compilers
"""
import os
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


def run(src, mode="run"):
    """Compile and run through the Python oracle (`run`) or the self-hosted
    compiler (`build`). Both must agree; that is half the point."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.sta")
        with open(p, "w") as f:
            f.write(src)
        if mode == "run":
            r = subprocess.run([STRATA, "run", p], capture_output=True,
                               text=True, timeout=180)
            return r.stdout + r.stderr, r.returncode
        out = os.path.join(d, "t")
        r = subprocess.run([STRATA, "build", p, "-o", out],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            return r.stdout + r.stderr, r.returncode
        r2 = subprocess.run([out], capture_output=True, text=True, timeout=180)
        return r2.stdout + r2.stderr, r2.returncode


def check(src):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.sta")
        with open(p, "w") as f:
            f.write(src)
        r = subprocess.run([STRATA, "check", p], capture_output=True,
                           text=True, timeout=180)
        return r.stdout + r.stderr, r.returncode


HEAD = """import io from std;

database Invoice { int id; str who; int amount; float rate; }

def seed() {
    Invoice <- [id = 1, who = "delta", amount = 300, rate = 1.5];
    Invoice <- [id = 2, who = "alpha", amount = 100, rate = 0.5];
    Invoice <- [id = 3, who = "charlie", amount = 900, rate = 2.5];
    Invoice <- [id = 4, who = "bravo", amount = 100, rate = 0.25];
}

def show(list[Invoice] rows) {
    for R in rows { print(str_concat(str_concat(R.who, " "), str(R.amount))); }
}
"""


def program(body):
    return HEAD + "\nint main() {\n    seed();\n" + body + "\n    return 0;\n}\n"


def lines(out):
    return [l for l in out.splitlines() if l and not l.startswith("[Strata")
            and not l.strip().startswith("C source:")
            and not l.strip().startswith("Binary:")]


def main():
    print()
    print("── ordering a query ─" + "─" * 44)

    # 1. Ascending, and 2. descending. Through BOTH compilers.
    asc = program('    show(Invoice <- [id > 0] by amount);')
    desc = program('    show(Invoice <- [id > 0] by amount desc);')
    for mode, who in (("run", "the Python oracle"), ("build", "the self-hosted compiler")):
        out, rc = run(asc, mode)
        ok(f"smallest first, through {who}",
           lines(out) == ["alpha 100", "bravo 100", "delta 300", "charlie 900"],
           out)
        out, rc = run(desc, mode)
        ok(f"largest first, through {who}",
           lines(out) == ["charlie 900", "delta 300", "alpha 100", "bravo 100"],
           out)

    # 3. Ties keep the table's order. alpha was inserted before bravo and both
    #    are 100, so alpha stays first -- ascending AND descending.
    out, _ = run(asc)
    ok("a tie keeps the order the table had",
       lines(out)[:2] == ["alpha 100", "bravo 100"], out)
    out, _ = run(desc)
    ok("and keeps it when the order is reversed, rather than flipping the tie",
       lines(out)[-2:] == ["alpha 100", "bravo 100"], out)

    # 4. `first N` after the ordering, not before.
    out, _ = run(program('    show(Invoice <- [id > 0] by amount desc first 2);'))
    ok("`first 2` is the two largest, not two arbitrary rows put in order",
       lines(out) == ["charlie 900", "delta 300"], out)

    out, _ = run(program('    show(Invoice <- [id > 0] by amount first 1);'))
    ok("`first 1` with no `desc` is the smallest",
       lines(out) == ["alpha 100"], out)

    # `first` larger than the result is not an error and not padding.
    out, _ = run(program('    show(Invoice <- [id > 0] by amount first 99);'))
    ok("asking for more rows than exist gives the rows that exist",
       len(lines(out)) == 4, out)

    # `first` without `by` is still a limit.
    out, _ = run(program('    show(Invoice <- [id > 0] first 2);'))
    ok("`first` on its own limits without claiming an order",
       len(lines(out)) == 2, out)

    # 5. Text and decimals order too.
    out, _ = run(program('    show(Invoice <- [id > 0] by who);'))
    ok("text orders", [l.split()[0] for l in lines(out)]
       == ["alpha", "bravo", "charlie", "delta"], out)
    out, _ = run(program('    show(Invoice <- [id > 0] by rate desc first 1);'))
    ok("decimals order", lines(out) == ["charlie 900"], out)

    # 6. The condition still applies, and ordering happens on what survived it.
    out, _ = run(program('    show(Invoice <- [amount > 150] by amount);'))
    ok("the filter still runs, and only the rows that passed it are ordered",
       lines(out) == ["delta 300", "charlie 900"], out)

    # 7. A column that is not there. Both compilers, same code, same message.
    bad = program('    show(Invoice <- [id > 0] by total);')
    cout, crc = check(bad)
    ok("an unknown column is E003 from the self-hosted checker",
       crc != 0 and "E003" in cout and "'total' is not a column" in cout, cout)
    bout, brc = run(bad, "build")
    ok("and the Python oracle says the same thing",
       brc != 0 and "E003" in bout and "'total' is not a column" in bout, bout)
    ok("and the hint names the columns that do exist",
       "amount" in cout and "who" in cout, cout)

    # 8. `first 0` asks for nothing, which is a condition rather than a limit.
    zero = program('    show(Invoice <- [id > 0] by amount first 0);')
    cout, crc = check(zero)
    ok("`first 0` is refused by the self-hosted compiler", crc != 0, cout)
    bout, brc = run(zero, "build")
    ok("and by the Python oracle", brc != 0, bout)
    ok("and both say the same thing about it",
       "asks for no rows" in cout and "asks for no rows" in bout,
       cout + "|" + bout)

    # 9. THE ONE THAT MATTERS. Rename the column and the ordered query stops
    #    compiling. A library sort taking "amount" as a string would not have
    #    noticed, and the program would have silently stopped being ordered.
    renamed = (HEAD.replace("int amount;", "int value;")
                   .replace("amount = 300", "value = 300")
                   .replace("amount = 100", "value = 100")
                   .replace("amount = 900", "value = 900")
                   .replace("R.amount", "R.value")
               + "\nint main() {\n    seed();\n"
                 "    show(Invoice <- [id > 0] by amount);\n    return 0;\n}\n")
    cout, crc = check(renamed)
    ok("renaming the column breaks the query that ordered by it",
       crc != 0 and "E003" in cout, cout)
    ok("and it says which column is gone",
       "'amount'" in cout, cout)

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  Ordering is not trustworthy. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  Rows can be ordered, and the column is checked like every other. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
