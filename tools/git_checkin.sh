#!/usr/bin/env bash
# Commit and push from an unattended session.
#
# Refuses a commit whose .sta files are not canonically formatted, which is the
# check CI runs and the one that is cheapest to fail locally.
#
# Two things make plain `git commit` fail when this repo is reached through the
# Cowork device bridge:
#
#   1. The mount refuses unlink(2). Git writes `.git/index.lock`, `HEAD.lock`
#      and temp objects, then cannot remove them — so the FIRST git write
#      succeeds and every later one fails with "File exists". Renaming is
#      allowed, so stale locks are parked in .git/stalelocks/ rather than
#      deleted.
#   2. The bridge VM has its own home, so ~/.gitconfig is not the user's and
#      there is no committer identity. It is supplied per-command.
#
# The index is also kept outside the mount, which avoids creating
# `.git/index.lock` in the first place.
#
# Usage:  tools/git_checkin.sh <message-file> [--no-push]
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

MSG_FILE="${1:?usage: git_checkin.sh <message-file> [--no-push]}"
PUSH=1
[ "${2:-}" = "--no-push" ] && PUSH=0

NAME="$(git log -1 --format='%an' 2>/dev/null || echo 'Strata')"
EMAIL="$(git log -1 --format='%ae' 2>/dev/null || echo 'strata@localhost')"
export GIT_INDEX_FILE="${GIT_INDEX_FILE:-$HOME/.strata-git-index}"

park_locks() {
    mkdir -p .git/stalelocks 2>/dev/null
    local stamp; stamp="$(date +%s%N)"
    # Only lock files, and only ones git is not currently holding — this runs
    # single-threaded, so anything here is left over from a previous call.
    find .git -maxdepth 3 -name '*.lock' -not -path '.git/stalelocks/*' 2>/dev/null |
    while read -r f; do
        mv "$f" ".git/stalelocks/$(basename "$f").$stamp" 2>/dev/null
    done
    # Temp objects git could not unlink. Harmless, but they accumulate.
    find .git/objects -name 'tmp_obj_*' -exec mv {} .git/stalelocks/ \; 2>/dev/null
}

git_q() { git -c user.name="$NAME" -c user.email="$EMAIL" "$@"; }

park_locks
git read-tree HEAD 2>/dev/null

park_locks
git add -A 2>&1 | grep -v "unable to unlink" | grep -v '^$'

if [ -z "$(git diff --cached --name-only)" ]; then
    echo "[checkin] nothing to commit"
    exit 0
fi

echo "[checkin] staging $(git diff --cached --name-only | wc -l | tr -d ' ') file(s)"

# The same formatting check CI runs, before the commit rather than after the
# email. Commit f424196 went up with an unformatted std/metrics.sta and turned
# CI red; eighteen test suites had passed, because none of them check that the
# files in the repository are formatted -- test_suite/fmt.py checks that
# formatting preserves meaning, which is a different question. A check that
# only exists in CI is a check that finds things too late.
#
# --no-fmt skips it, for a commit that is deliberately not formatted.
if [ "${SKIP_FMT:-0}" -ne 1 ]; then
    fmt_files=$(git diff --cached --name-only --diff-filter=ACM \
                | grep '\.sta$' | grep -v 'unimplemented' || true)
    if [ -n "$fmt_files" ]; then
        # shellcheck disable=SC2086
        if ! ./bin/strata fmt --check $fmt_files >/tmp/fmt_check.out 2>&1; then
            echo "[checkin] COMMIT REFUSED — these are not canonically formatted:" >&2
            cat /tmp/fmt_check.out >&2
            echo "[checkin] run: ./bin/strata fmt $(echo $fmt_files | tr '\n' ' ')" >&2
            exit 1
        fi
        echo "[checkin] formatting checked on $(echo "$fmt_files" | wc -l | tr -d ' ') .sta file(s)"
    fi
fi

park_locks
if ! git_q commit -F "$MSG_FILE" 2>&1 | grep -v "unable to unlink" | grep -v '^$'; then
    echo "[checkin] COMMIT FAILED" >&2
    exit 1
fi

if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
    echo "[checkin] COMMIT FAILED — HEAD unreadable" >&2
    exit 1
fi
echo "[checkin] committed $(git log -1 --format='%h %s')"

if [ "$PUSH" -eq 1 ]; then
    park_locks
    if git push origin HEAD 2>&1 | grep -v "unable to unlink" | grep -v '^$'; then
        echo "[checkin] pushed"
    else
        echo "[checkin] PUSH FAILED — the commit is local; push it yourself" >&2
        exit 2
    fi
fi
park_locks
exit 0
