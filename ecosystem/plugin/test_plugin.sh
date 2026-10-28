#!/usr/bin/env bash
#
# The plugin package, checked as far as it can be without a client.
#
# WHAT THIS CAN AND CANNOT SEE
#
# No client reads this manifest here, and `claude plugin validate` is the
# authoritative check -- run it too. What this does is everything that is
# knowable from the files: that the JSON parses, that every path named in it
# exists, that every tool a command claims permission for is a tool the
# server actually has, and that the launcher behaves the way the manifest
# assumes when it is handed a bad root or an unsubstituted placeholder.
#
# WHY EACH CASE IS HERE
#
#   * A manifest that does not parse fails at load with a message about JSON
#     and nothing about which field.
#   * `userConfig` options are strict: an unknown key inside one is an error
#     and the plugin does not load. The five used here are checked by name.
#   * A command naming a tool that does not exist asks for permission to use
#     nothing. The names are built from the plugin name and the server name,
#     so a rename of either silently breaks every one of them -- this is the
#     check that notices.
#   * Standard output is the protocol channel. The launcher prints to stderr
#     and nothing else, or the first thing a client reads is English.
#   * An unset optional may arrive as the literal `${user_config.whatever}`.
#     A key-shaped string that is not a key is worse than no key: the server
#     would believe it had one and send it.
#   * A top-level `bin/` stops claude.ai and Cowork installing the plugin at
#     all, so its absence is worth pinning.
#
# Run: bash ecosystem/plugin/test_plugin.sh
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LAUNCHER="$HERE/scripts/strata-mcp.sh"
WORK="$(mktemp -d /tmp/strata-plugin-test-XXXXXX)"

passed=0
failed=0
declare -a problems=()

cleanup() { rm -rf "$WORK"; }
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

printf '[plugin] reading the manifest\n'

ok "plugin.json is JSON, kebab-case named, and carries the fields a listing needs" \
   "$(python3 -c "
import json,re,sys
m=json.load(open('$HERE/.claude-plugin/plugin.json'))
assert re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', m['name']), m['name']
# The validator refuses a name that passes as one of Anthropic's own.
low=m['name'].lower()
assert not re.search(r'claude|anthropic', low), low
for k in ('version','description','author'):
    assert m.get(k), k
assert m['author'].get('name')
" 2>"$WORK/e1" && echo 0 || echo 1)" "$(cat "$WORK/e1")"

ok "every userConfig option uses only documented keys, and the key is sensitive" \
   "$(python3 -c "
import json,sys
m=json.load(open('$HERE/.claude-plugin/plugin.json'))
allowed={'type','title','description','required','default','options','multiple','sensitive','min','max'}
types={'string','number','boolean','directory','file'}
uc=m['userConfig']
for name,opt in uc.items():
    extra=set(opt)-allowed
    assert not extra, (name, extra)
    for required in ('type','title','description'):
        assert required in opt, (name, required)
    assert opt['type'] in types, (name, opt['type'])
assert uc['strata_root']['type']=='directory'
assert uc['strata_root'].get('required') is True
# A credential that is not marked sensitive is written into settings.json in
# the clear, which is the one mistake this file must not make.
assert uc['strata_llm_key'].get('sensitive') is True
" 2>"$WORK/e2" && echo 0 || echo 1)" "$(cat "$WORK/e2")"

ok ".mcp.json declares one stdio server that runs the launcher that is there" \
   "$(python3 -c "
import json,os,sys
c=json.load(open('$HERE/.mcp.json'))
s=c['mcpServers']
assert list(s)==['strata'], list(s)
e=s['strata']
assert e['command']=='bash', e['command']
assert e['args'][0]=='\${CLAUDE_PLUGIN_ROOT}/scripts/strata-mcp.sh', e['args']
assert '\${user_config.strata_root}' in e['args']
# A remote server would have url/headers instead; this one is stdio, so no
# URL may be in it.
assert 'url' not in e
assert os.path.isfile('$LAUNCHER'), 'the launcher named here does not exist'
" 2>"$WORK/e3" && echo 0 || echo 1)" "$(cat "$WORK/e3")"

ok "every option the server is given an env var for is an option the manifest declares" \
   "$(python3 -c "
import json,re
m=json.load(open('$HERE/.claude-plugin/plugin.json'))
c=json.load(open('$HERE/.mcp.json'))
declared=set(m['userConfig'])
text=json.dumps(c)
used=set(re.findall(r'\\\$\{user_config\.([A-Za-z0-9_]+)\}', text))
missing=used-declared
assert not missing, missing
" 2>"$WORK/e4" && echo 0 || echo 1)" "$(cat "$WORK/e4")"

ok "every command and the skill start with frontmatter carrying a description" \
   "$(python3 -c "
import glob,sys
files=sorted(glob.glob('$HERE/commands/*.md'))+['$HERE/skills/strata-codebase/SKILL.md']
assert len(files)==4, files
for f in files:
    lines=open(f).read().split('\n')
    assert lines[0]=='---', f
    end=lines.index('---',1)
    head='\n'.join(lines[1:end])
    assert 'description:' in head, f
    assert head.strip(), f
" 2>"$WORK/e5" && echo 0 || echo 1)" "$(cat "$WORK/e5")"

# The names in allowed-tools are built from the plugin name and the server
# name. Renaming either breaks all of them and nothing says so at load time.
ok "every tool a command claims permission for is a tool the server has" \
   "$(python3 -c "
import glob,json,re,subprocess,sys
m=json.load(open('$HERE/.claude-plugin/plugin.json'))
server=list(json.load(open('$HERE/.mcp.json'))['mcpServers'])[0]
prefix='mcp__plugin_%s_%s__' % (m['name'], server)
cat=json.loads(subprocess.run(
    ['$ROOT/ecosystem/mcp_strata/build/mcp_strata','--root','$ROOT','--self-test'],
    capture_output=True, text=True, check=True).stdout)
have={t['name'] for t in cat['tools']}
bad=[]
for f in sorted(glob.glob('$HERE/commands/*.md')):
    head=open(f).read().split('---')[1]
    mm=re.search(r'allowed-tools:(.*)', head)
    if not mm: continue
    for name in [x.strip() for x in mm.group(1).split(',') if x.strip()]:
        if not name.startswith(prefix): bad.append((f,name,'wrong prefix'))
        elif name[len(prefix):] not in have: bad.append((f,name,'no such tool'))
assert not bad, bad
" 2>"$WORK/e6" && echo 0 || echo 1)" "$(cat "$WORK/e6")"

ok "there is no top-level bin/, which would stop the plugin installing at all" \
   "$([ ! -d "$HERE/bin" ] && echo 0 || echo 1)" \
   "claude.ai and Cowork refuse a plugin with a top-level bin/ directory"

printf '[plugin] starting the server through the launcher\n'

# ── the launcher ─────────────────────────────────────────────────────────

bash "$LAUNCHER" </dev/null >"$WORK/noroot.out" 2>"$WORK/noroot.err"
noroot=$?
ok "no checkout named is exit 2, with the reason on stderr and nothing on stdout" \
   "$([ "$noroot" = "2" ] && [ ! -s "$WORK/noroot.out" ] \
      && grep -q 'Strata checkout' "$WORK/noroot.err" && echo 0 || echo 1)" \
   "exit=$noroot stdout=$(cat "$WORK/noroot.out") stderr=$(cat "$WORK/noroot.err")"

bash "$LAUNCHER" /etc </dev/null >"$WORK/badroot.out" 2>"$WORK/badroot.err"
badroot=$?
ok "a directory that is not a checkout is refused, and named" \
   "$([ "$badroot" = "2" ] && [ ! -s "$WORK/badroot.out" ] \
      && grep -q "'/etc'" "$WORK/badroot.err" && echo 0 || echo 1)" \
   "exit=$badroot stderr=$(cat "$WORK/badroot.err")"

# A tree with bin/strata and no taxonomy is the half-copied case: the server
# refuses it too, and saying so here names the directory rather than letting
# a server that has taken over the stream say it.
mkdir -p "$WORK/half/bin" && : > "$WORK/half/bin/strata" && chmod +x "$WORK/half/bin/strata"
bash "$LAUNCHER" "$WORK/half" </dev/null >"$WORK/half.out" 2>"$WORK/half.err"
half=$?
ok "a tree with bin/strata and no taxonomy is refused for the taxonomy" \
   "$([ "$half" = "2" ] && grep -q 'ERROR_TAXONOMY.json' "$WORK/half.err" && echo 0 || echo 1)" \
   "exit=$half stderr=$(cat "$WORK/half.err")"

bash "$LAUNCHER" '${user_config.strata_root}' </dev/null >"$WORK/sub.out" 2>"$WORK/sub.err"
sub=$?
ok "a value the client did not substitute is treated as absent, not as a path" \
   "$([ "$sub" = "2" ] && grep -q 'no Strata checkout was named' "$WORK/sub.err" \
      && echo 0 || echo 1)" "exit=$sub stderr=$(cat "$WORK/sub.err")"

printf '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n' \
  | bash "$LAUNCHER" "$ROOT" >"$WORK/list.out" 2>"$WORK/list.err"
ok "the launcher starts the server, and every tool comes back through it" \
   "$(python3 -c "
import json
d=json.load(open('$WORK/list.out'))
have={t['name'] for t in d['result']['tools']}
need={'strata_check','strata_taxonomy','strata_build','strata_run','strata_schema','strata_rename_impact','strata_ask_model'}
assert need <= have, need-have
" 2>"$WORK/e7" && echo 0 || echo 1)" "$(cat "$WORK/e7")$(cat "$WORK/list.err")"

ok "nothing but the protocol reaches standard output through the launcher" \
   "$(grep -cv '^{' "$WORK/list.out" | grep -q '^0$' && echo 0 || echo 1)" \
   "a line that is not a JSON object got onto stdout: $(grep -v '^{' "$WORK/list.out" | head -3)"

# The one that matters. An unset optional may arrive as the literal
# ${user_config.strata_llm_key}, and a key-shaped string that is not a key is
# worse than no key at all.
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"strata_ask_model","arguments":{"question":"q","code":"E004"}}}' \
  | env STRATA_LLM_KEY='${user_config.strata_llm_key}' \
        STRATA_LLM_MODEL='a-model' STRATA_LLM_DRY_RUN=1 \
        bash "$LAUNCHER" "$ROOT" >"$WORK/ph.out" 2>"$WORK/ph.err"
ok "an unsubstituted key is dropped rather than passed through as a credential" \
   "$(python3 -c "
import json
r=json.load(open('$WORK/ph.out'))['result']['structuredContent']
assert r['key_is_set'] is False, r
assert r['mode']=='dry_run'
" 2>"$WORK/e8" && ! grep -qF 'user_config' "$WORK/ph.out" && echo 0 || echo 1)" \
   "$(cat "$WORK/e8")$(cut -c1-300 "$WORK/ph.out")"

echo
echo "=============================================================="
printf '  %d ok, %d failed\n' "$passed" "$failed"
echo "=============================================================="
if [ "$failed" != "0" ]; then
    for p in "${problems[@]}"; do printf '  - %s\n' "${p:0:300}"; done
    echo "  The plugin package is not right. FAIL"
    exit 1
fi
echo '  The plugin package holds together. `claude plugin validate` is still'
echo '  the authoritative check and has not been run here. OK'
exit 0
