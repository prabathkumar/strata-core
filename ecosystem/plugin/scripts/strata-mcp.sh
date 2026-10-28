#!/usr/bin/env bash
#
# Start the Strata MCP server for a client that speaks stdio.
#
# WHY A SCRIPT RATHER THAN THE BINARY
#
# The binary is not in the plugin. It is built from the Strata checkout, by
# the Strata compiler, and which checkout that is depends on the machine. So
# the plugin carries this, and the user names the checkout once when the
# plugin is enabled.
#
# It also builds the server when it is missing or out of date, because the
# alternative is a client that starts, fails to find a binary, and reports
# "server exited" — which tells the user nothing about what to do next.
#
# EVERYTHING THIS PRINTS GOES TO STANDARD ERROR
#
# Standard output is the JSON-RPC channel. One word of English on it
# desynchronises the client, and the failure shows up later as a wrong answer
# to a different request. `exec` at the end hands stdout to the server and
# nothing in here has written to it.

set -u

say() { printf 'strata-mcp: %s\n' "$1" >&2; }

die() { say "$1"; exit 2; }

# A value the client did not substitute. An unset optional in the manifest
# may arrive as the literal `${user_config.whatever}` rather than as nothing,
# and a key-shaped string that is not a key is worse than no key at all: the
# server would believe it had one and send it. So anything still carrying the
# substitution marker is treated as absent.
unsubstituted() {
    case "$1" in
        *'${'*) return 0 ;;
        *) return 1 ;;
    esac
}

ROOT="${1:-}"
if [ -z "$ROOT" ] || unsubstituted "$ROOT"; then ROOT="${STRATA_ROOT:-}"; fi
if [ -z "$ROOT" ] || unsubstituted "$ROOT"; then
    die "no Strata checkout was named. Set the plugin's \"Strata checkout\" option to the absolute path of a checkout holding bin/strata and ERROR_TAXONOMY.json."
fi

# The same two markers the server itself requires. Checking them here means
# the user is told which directory was wrong, rather than being told by a
# server that has already taken over the stream.
[ -d "$ROOT" ] || die "'$ROOT' is not a directory."
[ -x "$ROOT/bin/strata" ] || die "'$ROOT' holds no executable bin/strata, so it is not a Strata checkout."
[ -f "$ROOT/ERROR_TAXONOMY.json" ] || die "'$ROOT' holds no ERROR_TAXONOMY.json. A tree without the taxonomy is one where a diagnostic is worth no more than its text, and this server will not serve it."

for var in STRATA_LLM_KEY STRATA_LLM_MODEL STRATA_LLM_URL; do
    value="$(eval "printf '%s' \"\${$var:-}\"")"
    if unsubstituted "$value"; then unset "$var"; fi
done

SERVER_DIR="$ROOT/ecosystem/mcp_strata"
SERVER="$SERVER_DIR/build/mcp_strata"
[ -d "$SERVER_DIR" ] || die "'$ROOT' has no ecosystem/mcp_strata. This plugin serves a checkout that carries the Strata MCP server."

# Rebuild when any source is newer than the binary. `find -newer` rather than
# a timestamp comparison, because the shell has no portable one.
needs_build=0
if [ ! -x "$SERVER" ]; then
    needs_build=1
elif [ -n "$(find "$SERVER_DIR/src" -name '*.sta' -newer "$SERVER" -print -quit 2>/dev/null)" ]; then
    needs_build=1
fi

if [ "$needs_build" = "1" ]; then
    # std/tls.sta reaches OpenSSL through pkg-config, and on a machine whose
    # .pc file is not on the default search path the build still succeeds --
    # TLS compiles to a refusal that explains itself. That is the wrong kind
    # of success for a tool that calls a model over https, so the usual
    # out-of-the-way location is offered when nothing else is set. A
    # deliberate PKG_CONFIG_PATH is left alone.
    if [ -z "${PKG_CONFIG_PATH:-}" ] && [ -d "$HOME/osslshim/pkgconfig" ]; then
        export PKG_CONFIG_PATH="$HOME/osslshim/pkgconfig"
    fi
    say "building the server in $SERVER_DIR (this happens once, and again whenever its sources change)"
    if ! ( cd "$SERVER_DIR" && "$ROOT/bin/strata" build ) >&2; then
        die "the server did not build. Run '$ROOT/bin/strata build' in $SERVER_DIR to see why."
    fi
    [ -x "$SERVER" ] || die "the build reported success but produced no binary at $SERVER."
fi

exec "$SERVER" --root "$ROOT"
