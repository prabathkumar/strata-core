#!/usr/bin/env python3
"""The write side is held to the same standard as the read side.

`load` was taught to refuse a damaged file rather than misread it. The other
three ways a program touches a stored table -- `scan`, `rewrite` and
`append` -- were not, and each of them had its own way of being quietly
wrong:

  * a value longer than the reader holds made `scan` report "no more rows",
    so a total came out short; the same answer made `rewrite` RENAME the
    short file over the original, destroying every row after the damaged one
    with exit 0 and nothing printed;
  * a file with no header at all made `scan` invent rows forever and
    `rewrite` write until the disk filled;
  * `scan` did not flush the handle `append` writes through, so a program
    could not see rows it had just written;
  * `save` answered "did not work" on an unwritable path and the call site
    discarded the answer, so the program printed its success line and exited
    0 with no file anywhere;
  * a text value longer than the reader can hold was written anyway, which
    made the file unreadable by the program that wrote it;
  * `append` wrote its columns in declaration order into a file whose header
    said another order, so a quantity was read back as a price;
  * assigning to a text column of a scan row stored a pointer the row would
    free, and the example in the specification's own `rewrite` section
    aborted.

Every case below was found by a blind audit, and every one of them was
silent. This file exists so that none of them is silent again.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")

SAVE_AFTER_FAILED_LOAD = 'import io from std;\ndatabase Note { int id; str body; }\nint main() {\n    load Note from "ledgre.tsv";\n    list[Note] all = Note <- [id > 0];\n    print(str_concat("loaded: ", str(count(all))));\n    Note <- [id = 3, body = "today"];\n    save Note to "ledger.tsv";\n    print("saved");\n    return 0;\n}\n'

FIRST_RUN_CREATES = 'import io from std;\ndatabase Note { int id; str body; }\nint main() {\n    load Note from "fresh.tsv";\n    Note <- [id = 1, body = "first"];\n    save Note to "fresh.tsv";\n    print("created");\n    return 0;\n}\n'

SAVE_OVER_ANOTHER_TABLE = 'import io from std;\ndatabase Note  { int id; str body; }\ndatabase Other { int k; str v; }\nint main() {\n    Note <- [id = 1, body = "important"];\n    save Note to "precious.tsv";\n    Other <- [k = 7, v = "junk"];\n    save Other to "precious.tsv";\n    print("done");\n    return 0;\n}\n'

RENAMED_COLUMN = 'import io from std;\ndatabase Item { int id; str name; float unit_price; }\nint main() {\n    load Item from "items.tsv";\n    list[Item] all = Item <- [id > 0];\n    print(str_concat("total: ", str(sum(all.unit_price))));\n    return 0;\n}\n'

ADDED_COLUMN = 'import io from std;\ndatabase Item { int id; str name; float price; str note; }\nint main() {\n    load Item from "items.tsv";\n    list[Item] all = Item <- [id > 0];\n    print(str_concat("rows: ", str(count(all))));\n    return 0;\n}\n'

PATH_IS_A_VARIABLE = 'import io from std;\ndatabase T { int id; }\nint main() {\n    str path = "out.tsv";\n    T <- [id = 1];\n    save T to path;\n    return 0;\n}\n'

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


def build(tmp, name, source):
    src = os.path.join(tmp, name + ".sta")
    open(src, "w").write(source)
    binary = os.path.join(tmp, name)
    r = subprocess.run([STRATA, "build", src, "-o", binary],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return None, (r.stdout + r.stderr)[-400:]
    return binary, ""


def run(binary, cwd, timeout=60):
    try:
        r = subprocess.run([binary], cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return None, "", "it did not finish"


def rows_in(path):
    """Counted without Strata: the file is the authority, not the program."""
    if not os.path.exists(path):
        return -1
    with open(path, "rb") as f:
        lines = [l for l in f.read().split(b"\n") if l.strip()]
    return max(0, len(lines) - 1)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        print("\n── a damaged file is refused, and left alone ───────────────────")

        rw, err = build(tmp, "rw", '''import io from std;
database T { int id; str s; }
int main() { rewrite T from "mid.tsv" as r { r.id = r.id; } print("done"); return 0; }
''')
        ok("the rewrite program builds", rw is not None, err)
        if rw:
            work = os.path.join(tmp, "w1")
            os.makedirs(work, exist_ok=True)
            p = os.path.join(work, "mid.tsv")
            lines = ["#strata\tT\tid:i\ts:s"]
            lines += [f"{i}\tok" for i in (1, 2, 3)]
            lines.append("4\t" + "A" * 6000)
            lines += [f"{i}\tok" for i in (5, 6, 7)]
            open(p, "w").write("\n".join(lines) + "\n")
            rc, out, errout = run(rw, work)
            ok("a rewrite over an unreadable value does not exit 0",
               rc not in (0, None), f"exit {rc}")
            ok("it says the file was refused",
               "longer than this reader can hold" in errout, errout[-200:])
            ok("and every row the file had is still in it",
               rows_in(p) == 7, f"{rows_in(p)} rows left of 7")

        sc, err = build(tmp, "sc", '''import io from std;
database T { int id; str s; }
int main() { int n = 0; scan T from "mid.tsv" as r { n = n + 1; } print(str(n)); return 0; }
''')
        ok("the scan program builds", sc is not None, err)
        if sc:
            work = os.path.join(tmp, "w1")
            rc, out, errout = run(sc, work)
            ok("a scan over the same file refuses rather than undercounting",
               rc not in (0, None) and "longer than this reader" in errout,
               f"exit {rc}: {out.strip()!r} {errout[-120:]!r}")

        print("\n── a file with no header ends the loop ─────────────────────────")
        work = os.path.join(tmp, "w2")
        os.makedirs(work, exist_ok=True)
        open(os.path.join(work, "empty.tsv"), "w").close()
        e1, err = build(tmp, "e1", '''import io from std;
database K { int id; }
int main() { int n = 0; scan K from "empty.tsv" as r { n = n + 1; if (n > 100000) { break; } } print(str(n)); return 0; }
''')
        ok("the empty-scan program builds", e1 is not None, err)
        if e1:
            rc, out, errout = run(e1, work, timeout=30)
            ok("a scan of an empty file reads no rows and finishes",
               rc == 0 and out.strip() == "0", f"exit {rc}: {out.strip()!r}")

        e2, err = build(tmp, "e2", '''import io from std;
database K { int id; }
int main() { rewrite K from "empty.tsv" as r { r.id = r.id + 1; } print("done"); return 0; }
''')
        ok("the empty-rewrite program builds", e2 is not None, err)
        if e2:
            rc, out, errout = run(e2, work, timeout=30)
            ok("a rewrite of an empty file finishes rather than filling the disk",
               rc == 0, f"exit {rc}")
            leftover = os.path.join(work, "empty.tsv.strata-rewrite")
            ok("and leaves no temporary behind", not os.path.exists(leftover))

        print("\n── a program can read what it has just written ─────────────────")
        work = os.path.join(tmp, "w3")
        os.makedirs(work, exist_ok=True)
        open(os.path.join(work, "ab.tsv"), "w").write(
            "#strata\tK\tid:i\n1\n2\n")
        ab, err = build(tmp, "ab", '''import io from std;
database K { int id; }
int main() {
    int i = 0;
    while (i < 5) { append K to "ab.tsv" [id = i]; i = i + 1; }
    int n = 0;
    scan K from "ab.tsv" as r { n = n + 1; }
    print(str(n));
    return 0;
}
''')
        ok("the append-then-scan program builds", ab is not None, err)
        if ab:
            rc, out, errout = run(ab, work)
            actual = rows_in(os.path.join(work, "ab.tsv"))
            ok("a scan sees the rows this program appended",
               out.strip() == str(actual) and actual == 7,
               f"scan said {out.strip()!r}, the file holds {actual}")

        print("\n── a write that cannot happen is not called a success ──────────")
        work = os.path.join(tmp, "w4")
        os.makedirs(work, exist_ok=True)
        sv, err = build(tmp, "sv", '''import io from std;
database T { int id; }
int main() { T <- [id = 1]; save T to "nodir/x.tsv"; print("saved"); return 0; }
''')
        ok("the unwritable-save program builds", sv is not None, err)
        if sv:
            rc, out, errout = run(sv, work)
            ok("a save into a directory that is not there does not exit 0",
               rc not in (0, None), f"exit {rc}")
            ok("and says why", "could not write" in errout, errout[-160:])

        print("\n── what is written can be read back ────────────────────────────")
        work = os.path.join(tmp, "w5")
        os.makedirs(work, exist_ok=True)
        lg, err = build(tmp, "lg", '''import io  from std;
import str from std;
database T { int id; str s; }
int main() {
    StringBuilder sb = sb_new();
    int i = 0;
    while (i < 500) { sb_append(&sb, "0123456789"); i = i + 1; }
    T <- [id = 1, s = sb_to_str(&sb)];
    save T to "big.tsv";
    print("saved");
    return 0;
}
''')
        ok("the long-value program builds", lg is not None, err)
        if lg:
            rc, out, errout = run(lg, work)
            ok("a value longer than a stored column holds is refused on write",
               rc not in (0, None) and "at most" in errout,
               f"exit {rc}: {errout[-160:]}")

        print("\n── an append agrees with the file it appends to ────────────────")
        work = os.path.join(tmp, "w6")
        os.makedirs(work, exist_ok=True)
        open(os.path.join(work, "p.tsv"), "w").write(
            "#strata\tP\tqty:i\tprice:i\n5\t100\n")
        apx, err = build(tmp, "apx", '''import io from std;
database P { int price; int qty; }
int main() { append P to "p.tsv" [price = 999, qty = 7]; print("appended"); return 0; }
''')
        ok("the reordered-append program builds", apx is not None, err)
        if apx:
            rc, out, errout = run(apx, work)
            ok("appending to a file whose columns are in another order is refused",
               rc not in (0, None) and "columns" in errout,
               f"exit {rc}: {errout[-160:]}")
            ok("and the file it refused is unchanged",
               rows_in(os.path.join(work, "p.tsv")) == 1,
               f"{rows_in(os.path.join(work, 'p.tsv'))} rows")

        print("\n── a rewrite may set a text column ─────────────────────────────")
        work = os.path.join(tmp, "w7")
        os.makedirs(work, exist_ok=True)
        open(os.path.join(work, "o.tsv"), "w").write(
            "#strata\tO\tid:i\tstatus:s\n1\tOPEN\n2\tCANCELLED\n3\tOPEN\n")
        # Copied out of LANGUAGE_SPECIFICATION.md. It aborted with an invalid
        # pointer, which means the specification shipped an example that
        # crashed.
        st, err = build(tmp, "st", '''import io  from std;
import str from std;
database O { int id; str status; }
int main() {
    rewrite O from "o.tsv" as r {
        if (str_eq(r.status, "CANCELLED") == 1) { drop; }
        if (str_eq(r.status, "OPEN") == 1) { r.status = "CLOSED"; }
    }
    print("done");
    return 0;
}
''')
        ok("the specification's rewrite example builds", st is not None, err)
        if st:
            rc, out, errout = run(st, work)
            body = open(os.path.join(work, "o.tsv")).read()
            ok("it runs without crashing", rc == 0, f"exit {rc}: {errout[-160:]}")
            ok("and the rows say what it set them to",
               body.count("CLOSED") == 2 and "CANCELLED" not in body,
               body.replace("\t", "|"))

        print("\n\u2500\u2500 a save does not replace rows after a failure \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
        # There are no exceptions, so a failed `load` leaves the table EMPTY
        # and the program carries on -- and the next `save` wrote that empty
        # table over the file. One mistyped load path turned a year of
        # records into two lines of header, with the right exit code arriving
        # after the write. Found by a pilot who called it the reason not to
        # adopt this.
        work = os.path.join(tmp, "wa")
        os.makedirs(work, exist_ok=True)
        stored = ("#strata\tNote\tid:i\tbody:s\n"
                  "1\tyear of records\n2\tmore records\n")
        open(os.path.join(work, "ledger.tsv"), "w").write(stored)
        cl, err = build(tmp, "cl", SAVE_AFTER_FAILED_LOAD)
        ok("the mistyped-path program builds", cl is not None, err)
        if cl:
            rc, out, errout = run(cl, work)
            ok("the run does not end as a success", rc not in (0, None),
               f"exit {rc}")
            ok("and every stored row is still in the file",
               open(os.path.join(work, "ledger.tsv")).read() == stored,
               open(os.path.join(work, "ledger.tsv")).read())
            ok("and it says why the write was refused",
               "would replace" in errout, errout[-200:])

        # A first run that loads a file which does not exist yet and then
        # creates it destroys nothing, and is an ordinary way to start.
        fr, err = build(tmp, "fr", FIRST_RUN_CREATES)
        ok("the first-run program builds", fr is not None, err)
        if fr:
            rc, out, errout = run(fr, work)
            ok("a first run still creates its file",
               os.path.exists(os.path.join(work, "fresh.tsv")),
               f"exit {rc}: {errout[-160:]}")
            ok("with the row it added",
               "first" in open(os.path.join(work, "fresh.tsv")).read())

        print("\n\u2500\u2500 a save does not overwrite another table's file \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
        # `load` refuses a file saved from another table, by name. `save` did
        # not look, so one transposed filename replaced an unrelated table's
        # file without a word.
        work = os.path.join(tmp, "wb")
        os.makedirs(work, exist_ok=True)
        fo, err = build(tmp, "fo", SAVE_OVER_ANOTHER_TABLE)
        ok("the two-table program builds", fo is not None, err)
        if fo:
            rc, out, errout = run(fo, work)
            body = open(os.path.join(work, "precious.tsv")).read()
            ok("the first table's file is still the first table's",
               "Note" in body.splitlines()[0] and "important" in body, body)
            ok("and the refusal names what it holds",
               "not this table" in errout, errout[-200:])

        print("\n\u2500\u2500 a renamed column is refused, not zero-filled \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
        # The whole pitch is that a rename cannot slip through. It slipped
        # through the data tier completely: rename `price` to `unit_price`,
        # fix the six diagnostics the compiler gives you, and every
        # historical row reads 0.00 for money -- rows loaded, exit 0,
        # had_error() clean. A drop on its own and an addition on its own are
        # still allowed; it is the two together, which is what a rename looks
        # like from the file's side, that cannot be anything but a mistake.
        work = os.path.join(tmp, "w9")
        os.makedirs(work, exist_ok=True)
        open(os.path.join(work, "items.tsv"), "w").write(
            "#strata\tItem\tid:i\tname:s\tprice:f\n"
            "1\twidget\t9.99\n2\tgadget\t4.5\n")
        rn, err = build(tmp, "rn", RENAMED_COLUMN)
        ok("the renamed-column program builds", rn is not None, err)
        if rn:
            rc, out, errout = run(rn, work)
            ok("loading a file written before the rename does not exit 0",
               rc not in (0, None), f"exit {rc}: {out.strip()!r}")
            ok("and names both the old column and the new one",
               "'price'" in errout and "'unit_price'" in errout,
               errout[-220:])
            # The program carries on -- there are no exceptions -- so it
            # still prints a total over no rows. What must not happen is the
            # run ending as a success with that number in it.
            ok("and the run ends at exit 65, not as a success",
               rc == 65, f"exit {rc}: {out.strip()!r}")

        ad, err = build(tmp, "ad", ADDED_COLUMN)
        ok("an added column on its own still builds", ad is not None, err)
        if ad:
            rc, out, errout = run(ad, work)
            ok("and an added column on its own still loads",
               rc == 0 and "rows: 2" in out,
               f"exit {rc}: {out.strip()!r} {errout[-120:]}")

        print("\n\u2500\u2500 a path is a path, not the name of a variable \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
        # `save T to path;` where path is a variable: the self-hosted parser
        # took any token here and the generator wrote the IDENTIFIER'S NAME,
        # so a built binary created a file called "path" and a later load read
        # it back, hiding the mistake. The bootstrap refused the same program,
        # which made it a disagreement between the two compilers as well.
        work = os.path.join(tmp, "w8")
        os.makedirs(work, exist_ok=True)
        src = os.path.join(work, "bug.sta")
        open(src, "w").write(PATH_IS_A_VARIABLE)
        chk = subprocess.run([STRATA, "check", src], cwd=ROOT,
                             capture_output=True, text=True)
        ok("a variable where a path belongs is refused by strata check",
           chk.returncode != 0, (chk.stdout + chk.stderr)[-200:])
        bld = subprocess.run([STRATA, "build", src, "-o",
                              os.path.join(work, "bug")],
                             cwd=ROOT, capture_output=True, text=True)
        ok("and by strata build", bld.returncode != 0,
           (bld.stdout + bld.stderr)[-200:])
        ok("and no file named after the variable is anywhere",
           not os.path.exists(os.path.join(work, "path"))
           and not os.path.exists(os.path.join(ROOT, "path")))

    print("=" * 64)
    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {passed} passed, {len(failures)} failed")
        print("  A write can still be quietly wrong. FAIL")
        return 1
    print(f"  {passed}/{passed} checks passed")
    print("=" * 64)
    print("  Writing is held to the same standard as reading. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
