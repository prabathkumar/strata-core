#!/usr/bin/env python3
"""The same language on the server and on the phone.

The claim is that business rules written once run everywhere, and that a
screen can be described in Strata rather than borrowed from a platform. Both
halves are checked here, because "it compiles for ARM" and "it gives the same
answers on ARM" are different statements and only the second one matters.

  - a rules module compiles for a phone's processor
  - and, run under emulation, gives byte-identical answers to the x86 build
  - a screen described in Strata produces a display list
  - taps land on the right thing, including on nothing
  - the screen paints, and its pixels are the ones expected

What this journey does NOT prove, stated here rather than left to be found:
nothing below has run on a handset. The Android shell in
apps/orders_mobile/android/ is reviewed design, not tested code.

Skips the ARM half when a cross-compiler or emulator is absent, rather than
passing quietly.

Usage:  python3 test_suite/journey_mobile.py
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE0 = os.path.join(ROOT, "bootstrap", "stage0.py")
PASS = FAIL = SKIP = 0

RULES = '''
import io  from std;
import str from std;
import mem from std;

database Order { int id; str customer; float amount; str status; }

const float DISCOUNT_THRESHOLD = 1000.0;
const float DISCOUNT_RATE      = 0.05;

float payable(float amount) {
    if (amount >= DISCOUNT_THRESHOLD) { return amount - (amount * DISCOUNT_RATE); }
    return amount;
}

int can_close(str status) {
    if (str_eq(status, "OPEN") == 1) { return 1; }
    return 0;
}

int main() {
    print(str(payable(999.99)));
    print(str(payable(1000.00)));
    print(str(payable(2500.00)));
    print(str(can_close("OPEN")));
    print(str(can_close("CLOSED")));
    Order <- [id = 1, customer = "acme", amount = 2500.0, status = "OPEN"];
    Order <- [id = 2, customer = "globex", amount = 100.0, status = "CLOSED"];
    list[Order] open_ones = Order <- [status == "OPEN"];
    print(str(count(open_ones)));
    print(str(sum(open_ones.amount)));
    return 0;
}
'''


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


def skip(name, why):
    global SKIP
    print(f"  SKIP  {name} — {why}")
    SKIP += 1


def main():
    tmp = tempfile.mkdtemp(prefix="strata-mobile-")
    try:
        print("── The rules run on a phone's processor ────────────────────────")
        src = os.path.join(tmp, "rules.sta")
        open(src, "w").write(RULES)
        host = os.path.join(tmp, "host")
        r = subprocess.run([sys.executable, STAGE0, src, "-o", host],
                           capture_output=True, text=True, cwd=tmp, timeout=600)
        ok("the rules build for this machine", r.returncode == 0,
           r.stderr[-300:])
        host_out = subprocess.run([host], capture_output=True, text=True,
                                  cwd=tmp).stdout

        cross = shutil.which("aarch64-linux-gnu-gcc")
        emu = shutil.which("qemu-aarch64-static")
        if not cross:
            skip("the ARM64 build", "no aarch64 cross-compiler here")
        else:
            arm = os.path.join(tmp, "arm")
            env = dict(os.environ, STRATA_CC="aarch64-linux-gnu-gcc")
            r = subprocess.run([sys.executable, STAGE0, src, "-o", arm],
                               capture_output=True, text=True, cwd=tmp,
                               env=env, timeout=600)
            ok("the same rules build for ARM64", r.returncode == 0,
               r.stderr[-300:])
            kind = subprocess.run(["file", arm], capture_output=True,
                                  text=True).stdout
            ok("and the result really is ARM64", "aarch64" in kind.lower(),
               kind.strip()[:120])

            if not emu:
                skip("running the ARM64 build", "no aarch64 emulator here")
            else:
                r = subprocess.run([emu, "-L", "/usr/aarch64-linux-gnu", arm],
                                   capture_output=True, text=True, cwd=tmp,
                                   timeout=600)
                ok("it runs", r.returncode == 0, r.stderr[-200:])
                # The whole point. Two processors, one set of rules, and the
                # app and the website cannot disagree about the discount.
                ok("and gives byte-identical answers to the server build",
                   r.stdout == host_out,
                   f"host={host_out!r} arm={r.stdout!r}")

        print("\n── A screen described in Strata ────────────────────────────────")
        app = os.path.join(ROOT, "apps", "orders_mobile")
        work = os.path.join(tmp, "app")
        shutil.copytree(app, work, ignore=shutil.ignore_patterns("build", "data"))
        os.makedirs(os.path.join(work, "data"), exist_ok=True)
        r = subprocess.run([os.path.join(ROOT, "bin", "strata"), "build"],
                           cwd=work, capture_output=True, text=True, timeout=900)
        ok("the screen builds", r.returncode == 0,
           (r.stdout + r.stderr)[-400:])
        if r.returncode != 0:
            return 1
        r = subprocess.run([os.path.join(work, "build", "orders_mobile")],
                           cwd=work, capture_output=True, text=True, timeout=120)
        ok("it runs", r.returncode == 0, (r.stdout + r.stderr)[-300:])
        out = dict(
            (ln.split(": ", 1)[0], ln.split(": ", 1)[1])
            for ln in r.stdout.strip().splitlines() if ": " in ln)

        drawn = int(out.get("list", "things to draw 0").split()[-1])
        # Nine orders, each a card with a hairline, three runs of text and a
        # touch region, plus the bar, its two labels and the button. The exact
        # number matters less than that it is neither zero nor absurd.
        ok("the screen has things to draw", 40 < drawn < 200, str(drawn))

        print("\n── Taps land on the right thing ────────────────────────────────")
        ok("a tap on the first row selects the first order",
           out.get("tap on first row") == "open:1", str(out))

        print("\n── A list that scrolls ─────────────────────────────────────────")
        ok("the list scrolled", out.get("scrolled to") == "129", str(out))
        # The row that was at the top has moved up and out, so the same spot
        # is now a different order. A list that looks scrolled but answers
        # with the old row is the bug this is here for, and it is invisible
        # in a screenshot.
        ok("the same spot now selects a different order",
           out.get("tap where row one was") == "open:3", str(out))
        ok("and a tap above the list hits nothing",
           out.get("tap above the list") == "|", str(out))

        print("\n── A form that types ───────────────────────────────────────────")
        ok("the form opened", out.get("screen now") == "new", str(out))
        ok("typing goes into the focused box",
           out.get("customer typed") == "Durian", str(out))
        ok("backspace removes the last character",
           out.get("amount typed") == "42.5", str(out))

        print("\n── The form and the list are the same table ────────────────────")
        ok("saving returns to the list",
           out.get("screen after save") == "list", str(out))
        ok("the order was added", out.get("orders now") == "10", str(out))
        ok("with the amount that was typed",
           out.get("the new order amount") == "42.50", str(out))

        print("\n── And every frame paints ──────────────────────────────────────")
        frames = ["01-list", "02-scrolled", "03-form-empty", "04-form-typed",
                  "05-saved"]
        for f in frames:
            ok(f"{f} was painted",
               os.path.exists(os.path.join(work, f + ".bmp")))

        def reader(path):
            data = open(path, "rb").read()
            w, h = struct.unpack("<ii", data[18:26])
            pad = (4 - ((w * 3) % 4)) % 4

            def pixel(px, py):
                row = h - 1 - py            # BMP rows are bottom-up
                off = 54 + row * (w * 3 + pad) + px * 3
                return (data[off + 2], data[off + 1], data[off])
            return data, w, h, pixel

        data, w, h, px = reader(os.path.join(work, "01-list.bmp"))
        ok("it is a BMP of the screen's size",
           data[:2] == b"BM" and (w, h) == (411, 731), f"{w}x{h}")
        ok("the title bar is painted", px(5, 5) == (31, 78, 98), str(px(5, 5)))
        ok("a card is painted white", px(200, 100) == (255, 255, 255),
           str(px(200, 100)))
        ok("the button is painted", px(200, 690) == (31, 78, 98),
           str(px(200, 690)))
        ok("there is text on the title bar",
           any(px(x, 30) == (255, 255, 255) for x in range(16, 120)),
           "no white pixels in the title")

        # The clip, in pixels. A scrolled row must not be painted over the
        # title bar, so the bar has to be solid all the way across.
        _, _, _, px2 = reader(os.path.join(work, "02-scrolled.bmp"))
        bar = [px2(x, 40) for x in range(130, 400)]
        ok("a scrolled row is not painted over the title bar",
           all(p == (31, 78, 98) for p in bar),
           "something was drawn on the bar")

        _, _, _, px3 = reader(os.path.join(work, "03-form-empty.bmp"))
        _, _, _, px4 = reader(os.path.join(work, "04-form-typed.bmp"))
        ok("the empty form and the typed form are not the same picture",
           any(px3(x, 137) != px4(x, 137) for x in range(24, 380)),
           "typing changed nothing on screen")

        print("\n── What this does not prove ────────────────────────────────────")
        shell = os.path.join(ROOT, "apps", "orders_mobile", "android")
        ok("the Android shell is present to review",
           os.path.exists(os.path.join(shell, "MainActivity.kt")))
        readme = open(os.path.join(shell, "README.md")).read()
        ok("and says plainly that it has not run on a handset",
           "not been built with the Android SDK" in readme
           or "Not yet run on a device" in readme, readme[:200])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"  {PASS}/{PASS + FAIL} checks passed"
          + (f", {SKIP} skipped" if SKIP else ""))
    print("=" * 64)
    if FAIL:
        print("  The phone half is not real yet. NOT OK")
        return 1
    print("  One language, two processors, and a screen Strata drew. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
