#!/usr/bin/env python3
"""Two sentences in the documentation must not contradict each other.

The README said "Runs on physical iPhone and Android handsets" at the top
and "Nothing has run on a physical phone" in the section a sceptic is
explicitly told to read before deciding anything. Both had been true; the
second was left behind when the first stopped being false. Two blind pilots
read both, and both said the same thing: it made every other claim in the
document suspect.

The first attempt at a guard listed the exact sentences that had gone stale.
That caught the two wordings it was given and missed three others saying the
same thing in different words, which the next pilot found. So this matches
the CLAIM rather than the sentence: for each fact with a settled answer, a
pattern that any statement of the opposite would match.

Adding to this file is cheap. The rule for adding: when a claim changes from
false to true, the sentences that said it was false become a pattern here, in
the same commit.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = ["README.md", "TUTORIAL.md", "FOR_DEVELOPERS.md",
        "LANGUAGE_SPECIFICATION.md", "STAGES.md"]

# (what is true, why it is true, patterns that assert the opposite)
SETTLED = [
    ("It has run on physical handsets, both platforms",
     "an iPhone and a Pixel 7 on Android 13, through BrowserStack, "
     "1 October; journey_mobile.py builds both shells on every commit",
     [r"(never|not|nothing|neither).{0,40}run on (a|any) (physical )?"
      r"(handset|phone|device)",
      r"has not been (run )?on a (handset|phone|device)",
      r"the Android shell has never been (compiled|built)"]),
    ("The compiler compiles itself",
     "fixpoint.py: stage0 builds it, it builds itself, and the two agree "
     "byte for byte",
     [r"cannot compile itself", r"does not compile itself",
      r"is not self-hosting"]),
    ("There is a formatter",
     "compiler/fmt.sta, `strata fmt`, gated in CI by `--check`",
     [r"there is no formatter", r"has no formatter"]),
    ("Applications have been built with it",
     "apps/orders and apps/ledger, with their own journeys",
     [r"no application has been built", r"nothing has been built with it"]),
]

# A line that is quoting the past on purpose says so. These are the words
# that mark it, and a line carrying one is not a contradiction.
HISTORICAL = ("used to", "was true", "no longer", "until", "before ",
              "previously", "had been", "stopped being", "once said",
              "we said", "it said", "which was")


def main():
    failures = []
    checked = 0
    print("\n── Every settled claim is stated one way ───────────────────────")
    for truth, backing, patterns in SETTLED:
        hits = []
        for doc in DOCS:
            path = os.path.join(ROOT, doc)
            if not os.path.exists(path):
                continue
            for n, line in enumerate(open(path), 1):
                low = line.lower()
                if any(h in low for h in HISTORICAL):
                    continue
                for pat in patterns:
                    if re.search(pat, low):
                        hits.append(f"{doc}:{n}: {line.strip()[:90]}")
                        break
        checked += 1
        if hits:
            print(f"  FAIL  {truth}")
            for h in hits:
                print(f"          {h}")
            failures.append((truth, backing, hits))
        else:
            print(f"  ok    {truth}")

    print("=" * 64)
    if failures:
        for truth, backing, hits in failures:
            print(f"  {len(hits)} line(s) say the opposite of: {truth}")
            print(f"  It is true because: {backing}")
        print("  The documents disagree with themselves. FAIL")
        return 1
    print(f"  {checked}/{checked} settled claims are stated one way")
    print("=" * 64)
    print("  No sentence contradicts another. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
