#!/usr/bin/env python3
"""Build a WebAssembly module from Strata and check it is well-formed.

Skipped when the toolchain is absent: a freestanding wasm build needs clang
with the wasm32 target, which gcc cannot provide. Skipping is reported, never
silent — a check that quietly does nothing is worse than no check.

What this verifies is that the module compiles, carries the wasm magic number,
and exports the functions the source declared. Executing it needs a wasm
runtime, which is not assumed here; `tools/` documents how to run one.

Sizes are printed rather than asserted. A size assertion would either be
generous enough to be meaningless or tight enough to fail on a toolchain
change, and this project has already published one bundle size that nothing
measured.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAMPLE = """str classify(int score) {
    if (score > 850) { return "PRIME"; }
    if (score > 600) { return "STANDARD"; }
    return "SUBPRIME";
}
int fib(int n) { if (n < 2) { return n; } return fib(n - 1) + fib(n - 2); }
"""


def have_wasm_clang():
    r = subprocess.run(["which", "clang"], capture_output=True)
    if r.returncode != 0:
        return False
    t = subprocess.run(["clang", "-print-targets"], capture_output=True, text=True)
    return "wasm32" in t.stdout


def main():
    print("\n── WebAssembly target ───────────────────────────────────────────")
    if not have_wasm_clang():
        print("  SKIP  clang with a wasm32 target is not installed here.")
        print("        The wasm backend is exercised in CI, where it is.")
        print("=" * 64)
        return 0

    tmp = tempfile.mkdtemp(prefix="strata-wasm-")
    sta = os.path.join(tmp, "m.sta")
    cfile = os.path.join(tmp, "m.c")
    wasm = os.path.join(tmp, "m.wasm")
    open(sta, "w").write(SAMPLE)

    r = subprocess.run([sys.executable, "bootstrap/stage0.py", sta,
                        "--target", "wasm", "--emit-c"],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        print("  FAIL  could not generate wasm C:\n" + r.stderr[:300]); return 1
    open(cfile, "w").write(r.stdout)

    r = subprocess.run(["clang", "-Oz", "--target=wasm32", "-nostdlib",
                        "-Wl,--no-entry", "-Wl,--strip-all",
                        "-Wl,--export-dynamic", "-Wl,--allow-undefined",
                        "-Wno-implicit-function-declaration",
                        "-o", wasm, cfile], capture_output=True, text=True)
    if r.returncode != 0:
        print("  FAIL  clang could not build the module:\n" + r.stderr[:400]); return 1

    blob = open(wasm, "rb").read()
    ok = True
    if blob[:4] != b"\x00asm":
        print(f"  FAIL  not a wasm module (magic {blob[:4]!r})"); ok = False
    else:
        print(f"  PASS  valid wasm module")
    for name in ("classify", "fib"):
        if name.encode() in blob:
            print(f"  PASS  exports '{name}'")
        else:
            print(f"  FAIL  '{name}' is not exported"); ok = False

    import gzip
    print(f"\n  size: {len(blob)} bytes ({len(gzip.compress(blob))} gzipped)")
    print("=" * 64)
    print("  WebAssembly target works. OK" if ok else "  WebAssembly target is broken.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
