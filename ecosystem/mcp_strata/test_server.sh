#!/usr/bin/env bash
#
# The Strata MCP server, driven the way a client drives it.
#
# It starts the server, speaks JSON-RPC to it on stdin, and reads the replies
# off stdout. Nothing here imports the server's own code, so a test passing
# means the thing a client talks to works, not that a function returns what
# another function expects.
#
# WHY EACH CASE IS HERE
#
#   * tools/list and initialize are the first two calls every client makes.
#     A server that gets either wrong is never reached for anything else.
#   * A notification -- `notifications/initialized`, which every client sends
#     -- must get NO reply. Answering one desynchronises the stream, and the
#     failure shows up later as the wrong answer to a different request.
#   * One reply per line. The taxonomy is pretty-printed in its file, and a
#     reply that carried its newlines through would be read by the client as
#     several broken messages. This is the bug that framing check exists for.
#   * Malformed JSON is -32700 and an unknown method is -32601, because those
#     are what a client's error handling switches on.
#   * An unknown TOOL is not a protocol error. It comes back as a result with
#     isError, so the agent can read the reason and try another name.
#   * Diagnostics have to come back from a file that does NOT compile. A
#     check tool only ever tested against working code has not been tested.
#   * Three shapes of path escape -- absolute, climbing, and a symbolic link
#     inside the tree pointing out of it. The link is the one a check written
#     against the spelling of a path lets through.
#   * An argument containing a semicolon must arrive at the program as one
#     argument containing a semicolon. If any of this ever reached a shell,
#     this is the case that says so.
#   * strata_rename_impact must reach the PHONE tier, which lives in a
#     separate project that takes the schema as a dependency. A tool that
#     only looked inside the directory it was given reports five tiers out of
#     six and looks right doing it.
#   * And the caller's own file must be byte-for-byte unchanged afterwards.
#     The rename is applied to a copy; this is what proves it.
#   * strata_ask_model is driven as far as the socket and no further, because
#     there is no key on the machine this was written on. What IS checked is
#     everything a missing key would otherwise hide: that the tool is in the
#     catalogue, that an unset variable is a refusal naming it rather than an
#     invented answer, that the prompt is assembled out of the compiler's own
#     diagnostics and the taxonomy, and that a key put in the environment
#     reaches NEITHER the reply, NOR the prompt, NOR standard error. The last
#     one is the case worth having: a tool that leaks a credential into an
#     agent's transcript has leaked it everywhere that transcript goes.
#   * And a failed call must leave no error flag set. Strata exits 65 at the
#     end of a program that recorded an error nobody cleared, so a server
#     that reports a failed call properly and then dies at the end of the
#     session has reported it wrongly.
#
# Run: bash ecosystem/mcp_strata/test_server.sh
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SERVER="$HERE/build/mcp_strata"
WORK="$(mktemp -d /tmp/mcp-strata-test-XXXXXX)"
LINK="$HERE/examples/escape_link"

# A key-shaped string that is not a key. Everything below that sets it then
# asks whether it came back out.
FAKE_KEY="sk-not-a-real-key-0123456789"

passed=0
failed=0
declare -a problems=()

cleanup() { rm -rf "$WORK"; rm -f "$LINK"; }
trap cleanup EXIT

ok() {  # ok <label> <condition-already-evaluated:0|1> [detail]
    if [ "$2" = "0" ]; then
        passed=$((passed + 1))
        printf '  ok    %s\n' "$1"
    else
        failed=$((failed + 1))
        printf '  FAIL  %s\n' "$1"
        problems+=("$1: ${3:-}")
    fi
}

has() {  # has <file> <literal> -> 0 when present
    grep -qF -- "$2" "$1"
}

reply() {  # reply <id> -> the one line that answered that id
    grep -F "\"id\":$1," "$WORK/out.jsonl" | head -1
}

printf '[mcp_strata] building the server\n'
( cd "$HERE" && "$ROOT/bin/strata" build ) >"$WORK/build.log" 2>&1
if [ ! -x "$SERVER" ]; then
    printf '  FAIL  the server does not build\n'
    tail -20 "$WORK/build.log"
    exit 1
fi
printf '[mcp_strata] driving it\n'

# A symbolic link inside the tree, pointing out of it. Made here rather than
# committed, so a checkout never carries one.
ln -sfn /etc "$LINK"

# The schema the rename test must leave alone.
SCHEMA="$ROOT/apps/payables/src/schema.sta"
before="$(cksum "$SCHEMA")"

cat > "$WORK/in.jsonl" <<'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
this is not json
{"jsonrpc":"2.0","id":3,"method":"no/such/method"}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"strata_nonsense","arguments":{}}}
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"strata_check","arguments":{"path":"ecosystem/mcp_strata/examples/broken.sta"}}}
{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"strata_check","arguments":{"path":"ecosystem/mcp_strata/examples/hello.sta"}}}
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"strata_check","arguments":{"path":"/etc/passwd"}}}
{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"strata_check","arguments":{"path":"../../etc/passwd"}}}
{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"strata_check","arguments":{"path":"ecosystem/mcp_strata/examples/escape_link/passwd"}}}
{"jsonrpc":"2.0","id":10,"method":"tools/call","params":{"name":"strata_taxonomy","arguments":{"code":"E004"}}}
{"jsonrpc":"2.0","id":11,"method":"tools/call","params":{"name":"strata_taxonomy","arguments":{"code":"E999"}}}
{"jsonrpc":"2.0","id":12,"method":"tools/call","params":{"name":"strata_taxonomy","arguments":{"code":"E004; rm -rf /"}}}
{"jsonrpc":"2.0","id":13,"method":"tools/call","params":{"name":"strata_taxonomy","arguments":{}}}
{"jsonrpc":"2.0","id":14,"method":"tools/call","params":{"name":"strata_schema","arguments":{"project_dir":"apps/payables"}}}
{"jsonrpc":"2.0","id":15,"method":"tools/call","params":{"name":"strata_build","arguments":{"path":"ecosystem/mcp_strata/examples/hello.sta"}}}
{"jsonrpc":"2.0","id":16,"method":"tools/call","params":{"name":"strata_run","arguments":{"path":"ecosystem/mcp_strata/examples/hello.sta","args":["one;two three"]}}}
{"jsonrpc":"2.0","id":17,"method":"tools/call","params":{"name":"strata_rename_impact","arguments":{"project_dir":"apps/payables","table":"Bill","column":"amount","new_name":"gross"}}}
{"jsonrpc":"2.0","id":18,"method":"tools/call","params":{"name":"strata_rename_impact","arguments":{"project_dir":"apps/payables","table":"Bill","column":"amount","new_name":"a;rm -rf /"}}}
{"jsonrpc":"2.0","id":19,"method":"tools/call","params":{"name":"strata_rename_impact","arguments":{"project_dir":"apps/payables","table":"Bill","column":"no_such_column","new_name":"gross"}}}
{"jsonrpc":"2.0","id":20,"method":"ping"}
{"jsonrpc":"2.0","id":21,"method":"tools/call","params":{"name":"strata_ask_model","arguments":{"question":"what is wrong here","code":"E004"}}}
EOF

# With the model variables deliberately unset: the server inherits whatever
# the developer's shell happens to hold, and a test whose answer depends on
# that is a test that passes on one machine.
env -u STRATA_LLM_KEY -u STRATA_LLM_MODEL -u STRATA_LLM_URL -u STRATA_LLM_DRY_RUN \
    "$SERVER" --root "$ROOT" < "$WORK/in.jsonl" > "$WORK/out.jsonl" 2> "$WORK/err.txt"

# ── the protocol ─────────────────────────────────────────────────────────

lines=$(grep -c . "$WORK/out.jsonl")
ok "one reply per request, and none for the notification" \
   "$([ "$lines" = "22" ] && echo 0 || echo 1)" \
   "expected 22 lines (21 ids + the parse error), got $lines"

reply 1 > "$WORK/r1"
ok "initialize answers, mirroring the version the client asked for" \
   "$(has "$WORK/r1" '"protocolVersion":"2025-03-26"' && has "$WORK/r1" '"name":"strata-sta"' && echo 0 || echo 1)" \
   "$(cat "$WORK/r1")"

reply 2 > "$WORK/r2"
ok "tools/list names every tool with an input schema" \
   "$(has "$WORK/r2" '"name":"strata_check"' && has "$WORK/r2" '"name":"strata_taxonomy"' \
      && has "$WORK/r2" '"name":"strata_build"' && has "$WORK/r2" '"name":"strata_run"' \
      && has "$WORK/r2" '"name":"strata_schema"' && has "$WORK/r2" '"name":"strata_rename_impact"' \
      && has "$WORK/r2" '"name":"strata_ask_model"' \
      && has "$WORK/r2" '"inputSchema"' && echo 0 || echo 1)" \
   "$(cut -c1-200 "$WORK/r2")"

ok "malformed JSON is a parse error, with a null id" \
   "$(grep -qF '"code":-32700' "$WORK/out.jsonl" && grep -qF '"id":null' "$WORK/out.jsonl" && echo 0 || echo 1)"

reply 3 > "$WORK/r3"
ok "an unknown method is -32601" \
   "$(has "$WORK/r3" '"code":-32601' && echo 0 || echo 1)" "$(cat "$WORK/r3")"

reply 4 > "$WORK/r4"
ok "an unknown tool is a result with isError, not a protocol error" \
   "$(has "$WORK/r4" '"isError":true' && has "$WORK/r4" 'no tool called' \
      && ! has "$WORK/r4" '"error":{"code"' && echo 0 || echo 1)" "$(cat "$WORK/r4")"

reply 20 > "$WORK/r20"
ok "ping answers, so a client's keepalive does not time out" \
   "$(has "$WORK/r20" '"result":{}' && echo 0 || echo 1)" "$(cat "$WORK/r20")"

ok "nothing but the protocol reaches standard output" \
   "$(grep -cv '^{' "$WORK/out.jsonl" | grep -q '^0$' && echo 0 || echo 1)" \
   "a line that is not a JSON object got onto stdout"

# ── strata_check ─────────────────────────────────────────────────────────

reply 5 > "$WORK/r5"
ok "a file that does not type-check comes back with its diagnostics" \
   "$(has "$WORK/r5" '"code":"E009"' && has "$WORK/r5" '"code":"E004"' \
      && has "$WORK/r5" '"line":19' && has "$WORK/r5" '"isError":true' && echo 0 || echo 1)" \
   "$(cut -c1-300 "$WORK/r5")"

ok "each diagnostic carries the taxonomy's own remediation strategy" \
   "$(has "$WORK/r5" '"ai_remediation_strategy"' \
      && has "$WORK/r5" '"compiler_remediation_strategy"' \
      && has "$WORK/r5" '"taxonomy_known":true' \
      && has "$WORK/r5" 'Database Schema Selector Violation' && echo 0 || echo 1)"

ok "a message with a character outside ASCII survives the trip" \
   "$(has "$WORK/r5" 'omits column' && python3 -c "
import json,sys
d=json.loads(open('$WORK/r5').read())
g=[x for x in d['result']['structuredContent']['diagnostics'] if x['code']=='E009'][0]
sys.exit(0 if '—' in g['hint'] else 1)" && echo 0 || echo 1)" \
   "the em dash in the compiler's hint did not come back whole"

reply 6 > "$WORK/r6"
ok "a file that does type-check says so, with no diagnostics" \
   "$(has "$WORK/r6" '"ok":true' && has "$WORK/r6" '"diagnostics":[]' \
      && has "$WORK/r6" '"isError":false' && echo 0 || echo 1)" "$(cut -c1-300 "$WORK/r6")"

# ── paths ────────────────────────────────────────────────────────────────

reply 7 > "$WORK/r7"
ok "an absolute path outside the checkout is refused" \
   "$(has "$WORK/r7" 'resolves outside' && has "$WORK/r7" '"isError":true' && echo 0 || echo 1)" \
   "$(cat "$WORK/r7")"

reply 8 > "$WORK/r8"
ok "a path that climbs out of the checkout is refused" \
   "$(has "$WORK/r8" 'resolves outside' && echo 0 || echo 1)" "$(cat "$WORK/r8")"

reply 9 > "$WORK/r9"
ok "a symbolic link inside the checkout pointing out of it is refused" \
   "$(has "$WORK/r9" 'resolves outside' && echo 0 || echo 1)" \
   "a path check made on the spelling rather than on what it resolves to lets this through: $(cat "$WORK/r9")"

# ── strata_taxonomy ──────────────────────────────────────────────────────

reply 10 > "$WORK/r10"
ok "one taxonomy entry comes back whole" \
   "$(has "$WORK/r10" '"known":true' && has "$WORK/r10" 'Database Schema Selector Violation' \
      && has "$WORK/r10" '"version":"1.2.0"' && echo 0 || echo 1)" "$(cut -c1-300 "$WORK/r10")"

reply 11 > "$WORK/r11"
ok "a code that does not exist is told so, and given the ones that do" \
   "$(has "$WORK/r11" '"known":false' && has "$WORK/r11" '"E013"' && echo 0 || echo 1)" \
   "$(cut -c1-300 "$WORK/r11")"

reply 12 > "$WORK/r12"
ok "a code that is not a code is refused before anything is read" \
   "$(has "$WORK/r12" 'is not an error code' && echo 0 || echo 1)" "$(cat "$WORK/r12")"

reply 13 > "$WORK/r13"
ok "the whole taxonomy comes back on one line, with every code in it" \
   "$(has "$WORK/r13" '"code_count":14' && has "$WORK/r13" '"E000"' \
      && has "$WORK/r13" '"E013"' && echo 0 || echo 1)" "$(cut -c1-200 "$WORK/r13")"

# ── strata_schema ────────────────────────────────────────────────────────

reply 14 > "$WORK/r14"
ok "the database blocks of a project come back with columns and line numbers" \
   "$(has "$WORK/r14" '"table":"Bill"' && has "$WORK/r14" '"name":"amount"' \
      && has "$WORK/r14" '"table":"Supplier"' && has "$WORK/r14" '"unreadable_files":[]' \
      && echo 0 || echo 1)" "$(cut -c1-300 "$WORK/r14")"

# ── strata_build and strata_run ──────────────────────────────────────────

reply 15 > "$WORK/r15"
ok "a program builds, in a copy, and the binary it produced exists" \
   "$(has "$WORK/r15" '"output_exists":true' && has "$WORK/r15" '"workspace":"scratch"' \
      && has "$WORK/r15" '"ok":true' && echo 0 || echo 1)" "$(cut -c1-300 "$WORK/r15")"

reply 16 > "$WORK/r16"
ok "a program runs and its own output comes back on its own" \
   "$(has "$WORK/r16" 'hello from strata' && has "$WORK/r16" '"phase":"run"' \
      && ! has "$WORK/r16" 'Strata Stage 0' && echo 0 || echo 1)" "$(cut -c1-300 "$WORK/r16")"

ok "an argument holding a semicolon arrives as one argument" \
   "$(has "$WORK/r16" 'one;two three' && echo 0 || echo 1)" \
   "if this ever went through a shell, the program would have seen two commands"

# ── strata_rename_impact ─────────────────────────────────────────────────

reply 17 > "$WORK/r17"
ok "a rename reports every tier it reached, the phone included" \
   "$(has "$WORK/r17" '"tiers_broken":["phone","program","report","rules","web"]' \
      && echo 0 || echo 1)" "$(cut -c1-400 "$WORK/r17")"

ok "the phone tier is found in the project next door, not in this one" \
   "$(has "$WORK/r17" '"projects_checked":["payables","payables_mobile"]' \
      && has "$WORK/r17" 'apps/payables_mobile/src/screen.sta' && echo 0 || echo 1)"

ok "the one line that was changed is named, and it is the declaration" \
   "$(has "$WORK/r17" 'apps/payables/src/schema.sta' && has "$WORK/r17" '"note":"the one line that was changed"' \
      && echo 0 || echo 1)"

ok "every impact says which tier it is in and what that was judged from" \
   "$(has "$WORK/r17" '"tier_evidence":"line' && echo 0 || echo 1)"

after="$(cksum "$SCHEMA")"
ok "the caller's own schema file is unchanged, byte for byte" \
   "$([ "$before" = "$after" ] && echo 0 || echo 1)" \
   "before=$before after=$after"

reply 18 > "$WORK/r18"
ok "a new name that is not an identifier is refused before anything is copied" \
   "$(has "$WORK/r18" 'plain identifier' && echo 0 || echo 1)" "$(cat "$WORK/r18")"

reply 19 > "$WORK/r19"
ok "a column that is not there is said to be not there" \
   "$(has "$WORK/r19" 'no column' && has "$WORK/r19" '"isError":true' && echo 0 || echo 1)" \
   "$(cat "$WORK/r19")"

# ── strata_ask_model ─────────────────────────────────────────────────────
#
# Every case below stops before the socket. There is no key here, so the one
# thing that cannot be tested is whether a real service answers; everything
# that decides WHAT would be sent, and whether the credential stays put, can
# be and is.

reply 21 > "$WORK/r21"
ok "an unset model is a refusal that names the variable" \
   "$(has "$WORK/r21" 'STRATA_LLM_MODEL is not set' && has "$WORK/r21" '"isError":true' \
      && echo 0 || echo 1)" "$(cat "$WORK/r21")"

# A model named and no key: the refusal has to name the variable to set and
# say that the key is not an argument, because an agent reading it will
# otherwise try to pass one.
env -u STRATA_LLM_KEY -u STRATA_LLM_URL -u STRATA_LLM_DRY_RUN STRATA_LLM_MODEL=a-model \
    bash -c 'printf "%s\n" "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"strata_ask_model\",\"arguments\":{\"question\":\"q\",\"code\":\"E004\"}}}" | "$0" --root "$1"' \
    "$SERVER" "$ROOT" > "$WORK/nokey.out" 2> "$WORK/nokey.err"
ok "no key set is a refusal that names the variable, not an invented answer" \
   "$(has "$WORK/nokey.out" 'STRATA_LLM_KEY is not set' \
      && has "$WORK/nokey.out" 'never a tool argument' \
      && has "$WORK/nokey.out" '"isError":true' && echo 0 || echo 1)" \
   "$(cat "$WORK/nokey.out")"

# A dry run, with a key present, against the file that does not compile. This
# is the one that proves the prompt is assembled from the compiler's own
# answer rather than from the file name.
env -u STRATA_LLM_URL STRATA_LLM_MODEL=a-model STRATA_LLM_KEY="$FAKE_KEY" STRATA_LLM_DRY_RUN=1 \
    bash -c 'printf "%s\n" "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"strata_ask_model\",\"arguments\":{\"question\":\"Propose the smallest repair.\",\"path\":\"ecosystem/mcp_strata/examples/broken.sta\"}}}" | "$0" --root "$1"' \
    "$SERVER" "$ROOT" > "$WORK/dry.out" 2> "$WORK/dry.err"

ok "a dry run assembles the prompt and sends nothing" \
   "$(has "$WORK/dry.out" '"mode":"dry_run"' && has "$WORK/dry.out" '"answer":null' \
      && has "$WORK/dry.out" '"isError":false' \
      && has "$WORK/dry.out" '"endpoint":"http://127.0.0.1:11434' && echo 0 || echo 1)" \
   "$(cut -c1-400 "$WORK/dry.out")"

ok "the prompt carries the compiler's diagnostics, the taxonomy and the source" \
   "$(python3 -c "
import json,sys
d=json.load(open('$WORK/dry.out'))
r=d['result']['structuredContent']
p=r['user_prompt']
need=[
 # both diagnostics the broken file is meant to produce
 'E009 at line 18', 'E004 at line 19',
 # the compiler's own words
 \"Column 'nope' does not exist in 'Item'\",
 # the taxonomy's classification and the strategy written for a machine
 'Database Schema Selector Violation',
 'Audit database table block schemas',
 # the source, with the line the compiler pointed at marked
 '> 19 |',
 # and the question the caller asked
 'Propose the smallest repair.',
]
missing=[n for n in need if n not in p]
if missing: print('missing:', missing, file=sys.stderr)
sys.exit(1 if missing else 0)
" && echo 0 || echo 1)" \
   "the prompt is not made of the compiler's answer"

ok "two codes are reported and the file is named, so a caller can check the prompt" \
   "$(has "$WORK/dry.out" '"diagnostic_count":2' \
      && has "$WORK/dry.out" '"codes":["E009","E004"]' \
      && has "$WORK/dry.out" 'ecosystem/mcp_strata/examples/broken.sta' \
      && has "$WORK/dry.out" '"key_is_set":true' && echo 0 || echo 1)" \
   "$(cut -c1-400 "$WORK/dry.out")"

# The case worth having. A credential that reaches a tool result reaches the
# agent's transcript, and from there everywhere that transcript goes.
ok "the key appears in neither the reply, nor the prompt, nor standard error" \
   "$(! grep -qF -- "$FAKE_KEY" "$WORK/dry.out" && ! grep -qF -- "$FAKE_KEY" "$WORK/dry.err" \
      && echo 0 || echo 1)" \
   "the key was echoed back"

# A code on its own, with no key at all: the taxonomy entry is the whole
# prompt, and a dry run needs no credential, which is what makes it testable
# on a machine that has none.
env -u STRATA_LLM_URL -u STRATA_LLM_KEY STRATA_LLM_MODEL=a-model STRATA_LLM_DRY_RUN=1 \
    bash -c 'printf "%s\n" "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"strata_ask_model\",\"arguments\":{\"question\":\"What does this mean?\",\"code\":\"E013\"}}}" | "$0" --root "$1"' \
    "$SERVER" "$ROOT" > "$WORK/code.out" 2> "$WORK/code.err"
ok "a code on its own gets its taxonomy entry, and needs no key to do it" \
   "$(has "$WORK/code.out" 'Stored Table Exceeds A Format Limit' \
      && has "$WORK/code.out" '"key_is_set":false' \
      && has "$WORK/code.out" '"isError":false' && echo 0 || echo 1)" \
   "$(cut -c1-300 "$WORK/code.out")"

# Neither a file nor a code: there is nothing this server knows that the
# caller does not, so it says so instead of being a worse client for a model
# than the agent already has.
env -u STRATA_LLM_URL STRATA_LLM_MODEL=a-model STRATA_LLM_KEY="$FAKE_KEY" STRATA_LLM_DRY_RUN=1 \
    bash -c 'printf "%s\n" "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"strata_ask_model\",\"arguments\":{\"question\":\"q\"}}}" | "$0" --root "$1"' \
    "$SERVER" "$ROOT" > "$WORK/bare.out" 2> "$WORK/bare.err"
ok "a question with neither a path nor a code is refused, with a reason" \
   "$(has "$WORK/bare.out" '"isError":true' && has "$WORK/bare.out" '`path`, a `code`, or both' \
      && echo 0 || echo 1)" "$(cat "$WORK/bare.out")"

# A real call, to a host that is not this machine, over plain HTTP. std/llm
# refuses it; this is here to prove the refusal travels all the way back as a
# tool result, and that the key is not quoted into it on the way.
env -u STRATA_LLM_DRY_RUN STRATA_LLM_URL=http://localhost.supplier.example/v1/chat \
    STRATA_LLM_MODEL=a-model STRATA_LLM_KEY="$FAKE_KEY" \
    bash -c 'printf "%s\n" "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"strata_ask_model\",\"arguments\":{\"question\":\"q\",\"code\":\"E004\"}}}" | "$0" --root "$1"' \
    "$SERVER" "$ROOT" > "$WORK/plain.out" 2> "$WORK/plain.err"
plain=$?
ok "a key is not sent over plain HTTP to a host that merely looks local" \
   "$(has "$WORK/plain.out" 'not this machine' && has "$WORK/plain.out" '"isError":true' \
      && ! grep -qF -- "$FAKE_KEY" "$WORK/plain.out" && ! grep -qF -- "$FAKE_KEY" "$WORK/plain.err" \
      && echo 0 || echo 1)" "$(cat "$WORK/plain.out")"

# Strata exits 65 at the end of a program that recorded an error nobody
# cleared. A server that reports a failed call properly and then dies at the
# end of the session has reported it wrongly.
ok "a failed call leaves no error flag set, so the session still ends at 0" \
   "$([ "$plain" = "0" ] && echo 0 || echo 1)" \
   "the server exited $plain after a call that failed and was reported"

# ── starting up ──────────────────────────────────────────────────────────

# A --root that is not a checkout must be REFUSED, not quietly replaced by a
# checkout found somewhere else. Serving a different tree than the one named
# is a wrong answer nobody would think to check for.
echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | "$SERVER" --root /etc \
    > "$WORK/badroot.out" 2> "$WORK/badroot.err"
badroot=$?
ok "a --root that is not a checkout is refused, not silently replaced" \
   "$([ "$badroot" = "2" ] && [ ! -s "$WORK/badroot.out" ] && echo 0 || echo 1)" \
   "exit=$badroot stdout=$(cat "$WORK/badroot.out")"

# ── and the verify blocks, which test the pure parts from inside ─────────

( cd "$HERE" && "$ROOT/bin/strata" test . ) > "$WORK/verify.txt" 2>&1
ok "every verify block in the server's own source passes" \
   "$(grep -qE '^\[Strata Test\] [0-9]+ passed, 0 failed' "$WORK/verify.txt" && echo 0 || echo 1)" \
   "$(tail -5 "$WORK/verify.txt")"

echo
echo "=============================================================="
printf '  %d ok, %d failed\n' "$passed" "$failed"
echo "=============================================================="
if [ "$failed" != "0" ]; then
    for p in "${problems[@]}"; do printf '  - %s\n' "${p:0:300}"; done
    echo "  The Strata MCP server is not working. FAIL"
    exit 1
fi
echo "  The Strata MCP server answers the way a client expects. OK"
exit 0
