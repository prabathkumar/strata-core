#!/usr/bin/env bash
# Install the Strata toolchain so that `strata` works anywhere.
#
# Until this existed, using Strata meant cloning the repository and running
# ./bin/strata from inside it. That is fine for the person who wrote it and
# not a thing you can ask a team to do: there is no command on their machine,
# no version to pin in a Dockerfile, and no way to have two versions on one
# box.
#
#   tools/install.sh                     -> ~/.strata, shim in ~/.local/bin
#   tools/install.sh --prefix /opt/strata --bindir /usr/local/bin
#   tools/install.sh --uninstall
#
# What lands on disk is a self-contained tree: the driver, the bootstrap
# compiler, the code generators, the standard library and the error taxonomy.
# Nothing is symlinked back into the checkout, so the source tree can be
# deleted afterwards and the install keeps working -- which is the only way
# to know the install is real rather than a pointer at a working copy.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${STRATA_PREFIX:-$HOME/.strata}"
BINDIR="${STRATA_BINDIR:-$HOME/.local/bin}"
UNINSTALL=0

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix)    PREFIX="$2"; shift 2 ;;
        --bindir)    BINDIR="$2"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help)   sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

if [ "$UNINSTALL" -eq 1 ]; then
    rm -f "$BINDIR/strata"
    rm -rf "$PREFIX"
    echo "removed $PREFIX and $BINDIR/strata"
    exit 0
fi

# The toolchain needs a C compiler to produce a binary at all, so a missing
# one is found here rather than in the middle of somebody's first build.
CC_FOUND=""
for c in cc gcc clang; do
    command -v "$c" >/dev/null 2>&1 && { CC_FOUND="$c"; break; }
done
if [ -z "$CC_FOUND" ]; then
    echo "no C compiler found (looked for cc, gcc, clang)." >&2
    echo "Strata compiles to C, so one is required. Install build-essential" >&2
    echo "or Xcode command line tools and run this again." >&2
    exit 1
fi
# Existing is not the same as runnable: an Apple silicon Mac that still has an
# Intel Homebrew in /usr/local finds an x86 python3 on PATH and then fails with
# "Bad CPU type in executable" halfway through the install. Try each candidate
# instead of testing for one.
PY3=""
for _c in "${STRATA_PYTHON:-}" python3 /opt/homebrew/bin/python3 \
          /usr/bin/python3 /usr/local/bin/python3; do
    [ -n "$_c" ] || continue
    if command -v "$_c" >/dev/null 2>&1 && "$_c" -c "pass" >/dev/null 2>&1; then
        PY3="$_c"; break
    fi
done
if [ -z "$PY3" ]; then
    echo "no working python3 found. Tried PATH, /opt/homebrew, /usr/bin and" >&2
    echo "/usr/local. Set STRATA_PYTHON to one that runs on this machine." >&2
    exit 1
fi
export STRATA_PYTHON="$PY3"

# Read after the prerequisite checks above, not before: a machine missing a
# compiler should be told that, and an earlier version of this script failed
# on the version line first and reported the wrong problem.
VERSION="$(sed -n 's/^.*Strata toolchain \([0-9][^"]*\)".*$/\1/p;/Strata toolchain/q' "$SRC/bin/strata")"
[ -n "$VERSION" ] || VERSION="unknown"

echo "installing Strata $VERSION"
echo "  from   $SRC"
echo "  into   $PREFIX"
echo "  shim   $BINDIR/strata"

rm -rf "$PREFIX"
mkdir -p "$PREFIX" "$BINDIR"

# Only what a build needs. The test suites, the applications, the examples and
# the git history stay behind: an install is a toolchain, not a copy of the
# project that made it.
cp -R "$SRC/bin"       "$PREFIX/bin"
cp -R "$SRC/bootstrap" "$PREFIX/bootstrap"
cp -R "$SRC/std"       "$PREFIX/std"
cp    "$SRC/ERROR_TAXONOMY.json" "$PREFIX/"
cp    "$SRC/ai_self_repair.py"   "$PREFIX/" 2>/dev/null || true

mkdir -p "$PREFIX/compiler"
cp "$SRC/compiler/"*.py "$PREFIX/compiler/"
# The C runtime preamble is a source file, not a build artifact -- every
# generated program is pasted on top of it. The generated .c files beside it
# are artifacts and stay behind.
cp "$SRC/compiler/runtime_preamble.c" "$SRC/compiler/runtime_preamble_wasm.c" \
   "$PREFIX/compiler/"
# The compiler's own Strata sources. The formatter is written in Strata and
# imports the lexer from here, so shipping fmt.sta alone produced an install
# whose `strata fmt` could not build -- found by the check at the end of this
# script, which is why it is a check and not a "done".
cp "$SRC/compiler/"*.sta "$PREFIX/compiler/"
find "$PREFIX" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# A shim rather than a symlink: a symlink into the install is resolved by
# bash, which then computes the install root correctly, but a symlink from a
# checkout is how you end up with a `strata` that breaks when the checkout
# moves. This is explicit about which tree it runs.
cat > "$BINDIR/strata" <<EOF
#!/usr/bin/env bash
exec "$PREFIX/bin/strata" "\$@"
EOF
chmod +x "$BINDIR/strata"

# Prebuild the formatter so the first `strata fmt` is not a compile, and so a
# broken install is discovered now rather than by whoever runs it next.
mkdir -p "$PREFIX/build"
"$PY3" "$PREFIX/bootstrap/stage0.py" "$PREFIX/compiler/fmt_cli.sta" \
    -o "$PREFIX/build/strata-fmt" >/dev/null 2>&1 \
    || { echo "the formatter did not build; the install is incomplete." >&2
         echo "Run the same command without the redirect to see why." >&2
         exit 1; }

echo "$VERSION" > "$PREFIX/VERSION"

# Prove it, here, rather than printing "done" and hoping. A project is built
# in a throwaway directory outside both the source tree and the install.
probe="$(mktemp -d)"
trap 'rm -rf "$probe"' EXIT
if ( cd "$probe" && "$BINDIR/strata" new hello >/dev/null 2>&1 \
     && cd hello && "$BINDIR/strata" build >/dev/null 2>&1 \
     && [ -x build/hello ] ); then
    echo "  checked: built a new project outside the source tree"
else
    echo "installed, but building a new project failed. Something is missing." >&2
    exit 1
fi

echo
echo "Strata $VERSION installed."
case ":$PATH:" in
    *":$BINDIR:"*) echo "Run: strata new myapp && cd myapp && strata run" ;;
    *)
        echo "$BINDIR is not on your PATH. Add this to your shell profile:"
        echo
        echo "    export PATH=\"$BINDIR:\$PATH\""
        echo
        echo "Then: strata new myapp && cd myapp && strata run"
        ;;
esac
