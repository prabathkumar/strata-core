#!/usr/bin/env python3
"""A scan costs what one row costs, however big the file is -- and so does
an append.

`load` brings a whole table into the process. That is right when the table is
small and impossible when it is not, and "a table has to fit in memory" was
the first thing an enterprise developer asked about. `scan` reads one row at a
time into a single reused struct.

The claim is only worth making if it is measured, so this measures it: the
same file, the same answer, both ways, with peak memory compared. A scan must
stay flat while a load grows with the file -- if someone ever makes the scan
accumulate, this fails rather than quietly becoming a load with extra steps.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRATA = os.path.join(ROOT, "bin", "strata")
ROWS = 400000
# What a scan may use ABOVE the harness's own overhead, whatever the file size.
# Generous against the ~0.1MB measured, so a different libc's buffering does
# not make the suite flap; a regression to loading would be a hundred times it.
SCAN_CEILING_KB = 4 * 1024

SCAN = '''import io  from std;
import mem from std;

database Big { int id; str name; float amount; }

int main() {
    float total = 0.0;
    int seen = 0;
    scan Big from "big.tsv" as r {
        total = total + r.amount;
        seen = seen + 1;
    }
    print(str(seen));
    print(str(total));
    return 0;
}
'''

NOOP = '''import io from std;

int main() { print("0"); return 0; }
'''

PIPELINE = '''import io  from std;
import mem from std;

database Big { int id; str name; float amount; }
database Kept { int id; float doubled; }

int main() {
    int written = 0;
    scan Big from "big.tsv" as r {
        if (r.amount > 500.0) {
            append Kept to "kept.tsv" [id = r.id, doubled = r.amount * 2.0];
            written = written + 1;
        }
    }
    print(str(written));
    return 0;
}
'''

LOAD = '''import io  from std;
import mem from std;

database Big { int id; str name; float amount; }

int main() {
    load Big from "big.tsv";
    list[Big] all = Big <- [id > -1];
    float total = 0.0;
    for r in all { total = total + r.amount; }
    print(str(count(all)));
    print(str(total));
    return 0;
}
'''

# Run the program in a Python of its own and report that child's peak. Asking
# RUSAGE_CHILDREN in THIS process would report the maximum over every child it
# has ever had, so measuring the small program first and the large one second
# made the difference look real when it was only an ordering. A helper process
# has exactly one child. ru_maxrss is kilobytes on Linux and bytes on macOS.
#
# The number still carries the harness with it: a forked child holds its
# parent's pages until the exec, and a Python interpreter is several megabytes
# of them. So a do-nothing Strata program is measured the same way and its
# figure subtracted -- what is left is what the program itself used. This is
# also why the test does not depend on /usr/bin/time, whose -v is GNU-only and
# absent on macOS.
HELPER = '''
import resource, subprocess, sys
subprocess.run([sys.argv[1]], cwd=sys.argv[2], stdout=open(sys.argv[3], "w"))
peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
print(peak // 1024 if sys.platform == "darwin" else peak)
'''


def peak_kb_of(binary, cwd, out_path):
    r = subprocess.run([sys.executable, "-c", HELPER, binary, cwd, out_path],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError("could not measure: " + r.stderr[-300:])
    return open(out_path).read(), int(r.stdout.strip())


def main():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "big.tsv")
        with open(data, "w") as f:
            f.write("#strata\tBig\tid:i\tname:s\tamount:f\n")
            for i in range(ROWS):
                f.write(f"{i}\tname_{i}\t{i % 1000}.25\n")
        print(f"  {ROWS} rows, {os.path.getsize(data) / (1024*1024):.0f}MB on disk")

        built = {}
        for label, source in (("noop", NOOP), ("scan", SCAN), ("load", LOAD),
                              ("pipeline", PIPELINE)):
            src = os.path.join(tmp, f"{label}.sta")
            open(src, "w").write(source)
            out = os.path.join(tmp, label)
            b = subprocess.run([STRATA, "build", src, "-o", out], cwd=ROOT,
                               capture_output=True, text=True)
            if b.returncode != 0:
                print((b.stdout + b.stderr)[-400:])
                print(f"  could not build the {label} program. FAIL")
                return 1
            built[label] = out

        _, floor = peak_kb_of(built["noop"], tmp, os.path.join(tmp, "noop.out"))
        print(f"  harness overhead measured at {floor / 1024:.1f}MB, subtracted")

        results = {}
        for label in ("scan", "load"):
            stdout, peak = peak_kb_of(built[label], tmp,
                                      os.path.join(tmp, label + ".out"))
            own = max(peak - floor, 0)
            results[label] = (stdout, own)
            print(f"  {label}: {own / 1024:.1f}MB of its own, "
                  f"printed {stdout.strip().splitlines()[:2]}")

        scan_out, scan_peak = results["scan"]
        load_out, load_peak = results["load"]

        # A whole job: read a file bigger than memory, write one. Both ends
        # stream, so the cost is one row in and one row out however many there
        # are -- which is the point of having both halves.
        pipe_out, pipe_peak = peak_kb_of(built["pipeline"], tmp,
                                         os.path.join(tmp, "pipeline.out"))
        pipe_peak = max(pipe_peak - floor, 0)
        kept = os.path.join(tmp, "kept.tsv")
        kept_rows = (sum(1 for _ in open(kept)) - 1) if os.path.isfile(kept) else -1
        print(f"  pipeline: {pipe_peak / 1024:.1f}MB of its own, "
              f"wrote {kept_rows} rows, printed {pipe_out.strip()!r}")
        if pipe_peak > SCAN_CEILING_KB:
            failures.append(
                f"the pipeline used {pipe_peak / 1024:.1f}MB, over the "
                f"{SCAN_CEILING_KB / 1024:.0f}MB ceiling — one end is accumulating")
        if pipe_out.strip() != str(kept_rows):
            failures.append(
                f"the pipeline says it wrote {pipe_out.strip()!r} rows and the "
                f"file has {kept_rows}")
        if kept_rows <= 0:
            failures.append("the pipeline wrote nothing")

        if scan_out.strip() != load_out.strip():
            failures.append("a scan and a load give different answers:\n"
                            f"      scan: {scan_out.strip()!r}\n"
                            f"      load: {load_out.strip()!r}")
        if scan_out.strip().splitlines()[:1] != [str(ROWS)]:
            failures.append(f"the scan saw {scan_out.strip().splitlines()[:1]} "
                            f"rows, not {ROWS}")
        if scan_peak > SCAN_CEILING_KB:
            failures.append(
                f"the scan used {scan_peak / 1024:.1f}MB, over the "
                f"{SCAN_CEILING_KB / 1024:.0f}MB ceiling — it is accumulating")
        if load_peak <= max(scan_peak, 1) * 4:
            failures.append(
                f"the load used {load_peak / 1024:.1f}MB and the scan "
                f"{scan_peak / 1024:.1f}MB — too close to be measuring anything")

    print("=" * 64)
    for f in failures:
        print(f"  {f}")
    print("=" * 64)
    if failures:
        print("  A scan is not constant memory. FAIL")
        return 1
    print("  A scan reads a file of any size in the memory of one row. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
