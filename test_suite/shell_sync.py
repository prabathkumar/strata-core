#!/usr/bin/env python3
"""The two phone shells describe the same screen, and must not drift.

apps/orders_mobile/android/MainActivity.kt and .../ios/ScreenView.swift are
independent files that read the same display list from the same five Strata
functions. Nothing makes them agree except care, and care does not survive six
months. A change made to one and not the other makes the same app look
different on the two phones -- the kind of difference nobody finds until a
customer is holding the wrong one.

This checks the things that would actually diverge: the five functions the
bridge exposes, and the three numbers that decide where a glyph lands.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "apps", "orders_mobile")
HOST = os.path.join(APP, "src", "host.sta")
KOTLIN = os.path.join(APP, "android", "MainActivity.kt")
SWIFT = os.path.join(APP, "ios", "ScreenView.swift")
HEADER = os.path.join(APP, "ios", "StrataBridge.h")

# The bridge, as Strata defines it, and the name each shell knows it by.
BRIDGE = {
    "host_draw":  ("drawScreen", "host_draw"),
    "host_item":  ("itemAt",     "host_item"),
    "host_hit":   ("hit",        "host_hit"),
    "host_act":   ("act",        "host_act"),
    "host_start": ("start",      "host_start"),
}

# The display list is in device-independent pixels against a screen this wide.
REFERENCE_WIDTH = "411"
# Strata's font is this many pixels tall at scale 1, on a baseline this far
# down from the top of the cell.
GLYPH_HEIGHT = "8"
GLYPH_BASELINE = "7"


def read(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def strip_comments(text):
    """Comments say the same numbers the code does.

    Without this the test reads "411" out of the comment explaining the 411
    and passes while the divisor beside it says something else -- a green test
    that cannot go red, which is worse than no test.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def main():
    print("=" * 62)
    print("  Phone shells in step")
    print("=" * 62)
    failures = []

    host = read(HOST)
    kotlin = read(KOTLIN)
    swift = read(SWIFT)
    header = read(HEADER)

    for label, path, text in (("host.sta", HOST, host),
                              ("MainActivity.kt", KOTLIN, kotlin),
                              ("ScreenView.swift", SWIFT, swift),
                              ("StrataBridge.h", HEADER, header)):
        if text is None:
            failures.append(f"{label} is missing ({path})")

    if failures:
        for f in failures:
            print(f"  {f}")
        print("=" * 62)
        print("  A shell has gone missing. FAIL")
        return 1

    # Every function the bridge promises is defined in Strata, declared for
    # Swift, and reachable from both shells.
    for strata_name, (kotlin_name, swift_name) in sorted(BRIDGE.items()):
        if not re.search(r"\b(int|str)\s+%s\s*\(" % strata_name, host):
            failures.append(f"host.sta does not define {strata_name}()")
        if strata_name not in header:
            failures.append(f"StrataBridge.h does not declare {strata_name}")
        if not re.search(r"\bexternal fun %s\b" % kotlin_name, kotlin):
            failures.append(
                f"MainActivity.kt does not declare {kotlin_name}() "
                f"for {strata_name}")
        if not re.search(r"\b%s\b" % kotlin_name, kotlin.split("external fun")[-1] + kotlin):
            failures.append(f"MainActivity.kt never calls {kotlin_name}()")
        if not re.search(r"\b%s\s*\(" % swift_name, swift):
            failures.append(f"ScreenView.swift never calls {swift_name}()")

    # Both shells lay a glyph down in the same place. Checked against the
    # code only: the comments beside these numbers quote them too.
    for label, text in (("MainActivity.kt", strip_comments(kotlin)),
                        ("ScreenView.swift", strip_comments(swift))):
        if REFERENCE_WIDTH not in text:
            failures.append(
                f"{label} does not scale against a {REFERENCE_WIDTH}-wide screen")
        if not re.search(r"\b%s(\.0)?f?\b" % GLYPH_HEIGHT, text):
            failures.append(f"{label} does not size text at {GLYPH_HEIGHT} pixels")
        if not re.search(r"\b%s(\.0)?f?\b" % GLYPH_BASELINE, text):
            failures.append(
                f"{label} does not put the baseline {GLYPH_BASELINE} pixels down")

    # Both shells split the same packed line into the same nine fields.
    for label, text in (("MainActivity.kt", strip_comments(kotlin)),
                        ("ScreenView.swift", strip_comments(swift))):
        if '"|"' not in text:
            failures.append(f"{label} does not split items on '|'")
        if not re.search(r"(count|size)\s*<\s*9\b", text):
            failures.append(
                f"{label} does not refuse an item with fewer than nine fields")

    if failures:
        for f in failures:
            print(f"  {f}")
        print(f"  {len(failures)} problem(s)")
        print("=" * 62)
        print("  The phone shells have drifted. FAIL")
        return 1

    print(f"  {len(BRIDGE)} bridge functions, both shells, "
          f"{REFERENCE_WIDTH}dp reference, {GLYPH_HEIGHT}px glyphs")
    print("=" * 62)
    print("  One screen, two phones, same shape. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
