#!/usr/bin/env bash
# Put an .apk or .ipa on BrowserStack App Live and print the id to open it with.
#
# Credentials come from the environment and are never written anywhere:
#
#   export BROWSERSTACK_USERNAME="..."
#   export BROWSERSTACK_ACCESS_KEY="..."
#   bash tools/browserstack_upload.sh path/to/app.apk
#
# BrowserStack re-signs what it installs, which is why an unsigned .ipa and a
# debug-signed .apk are both fine here and why none of this needs an Apple
# developer account.
set -euo pipefail

APP="${1:-}"
[ -n "$APP" ] || { echo "usage: $0 <app.apk|app.ipa>" >&2; exit 1; }
[ -f "$APP" ]  || { echo "no such file: $APP" >&2; exit 1; }

: "${BROWSERSTACK_USERNAME:?set BROWSERSTACK_USERNAME in your environment}"
: "${BROWSERSTACK_ACCESS_KEY:?set BROWSERSTACK_ACCESS_KEY in your environment}"

# A placeholder left in by mistake reaches BrowserStack as a wrong password
# and comes back as an unhelpful 401, so it is caught here instead.
case "$BROWSERSTACK_ACCESS_KEY" in
    *"<"*|*">"*|"your key"|"")
        echo "BROWSERSTACK_ACCESS_KEY still looks like a placeholder:" >&2
        echo "  $BROWSERSTACK_ACCESS_KEY" >&2
        echo "Export the real key from BrowserStack > Account > Settings." >&2
        exit 1 ;;
esac

echo "uploading $(basename "$APP") ($(du -h "$APP" | cut -f1 | tr -d ' '))"

# The status code is kept, because an authentication failure here comes back
# with an empty body: without the code the only thing that could be said was
# "that was not JSON", which describes the symptom and not the cause.
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT
STATUS="$(curl -sS -u "$BROWSERSTACK_USERNAME:$BROWSERSTACK_ACCESS_KEY" \
    -X POST "https://api-cloud.browserstack.com/app-live/upload" \
    -F "file=@$APP" \
    -F 'data={"custom_id":"strata-orders"}' \
    -o "$BODY_FILE" -w '%{http_code}')"

if [ "$STATUS" = "401" ] || [ "$STATUS" = "403" ]; then
    echo "BrowserStack refused the credentials (HTTP $STATUS)." >&2
    echo >&2
    echo "The username is NOT your email address. It is the handle shown in" >&2
    echo "BrowserStack under Account > Settings > Username & Access Keys," >&2
    echo "next to the access key — something like prabathkumar_AbC123." >&2
    echo >&2
    echo "  you sent: $BROWSERSTACK_USERNAME" >&2
    exit 1
fi
if [ "$STATUS" != "200" ]; then
    echo "BrowserStack answered HTTP $STATUS:" >&2
    head -c 800 "$BODY_FILE" >&2
    echo >&2
    exit 1
fi

cat "$BODY_FILE" | python3 - <<'PYEOF'
import json
import sys

raw = sys.stdin.read()
try:
    d = json.loads(raw)
except json.JSONDecodeError:
    sys.exit("BrowserStack did not answer with JSON:\n" + raw[:800])

if "app_url" in d:
    print("  app_url:   " + d["app_url"])
    print("  custom_id: " + d.get("custom_id", "strata-orders"))
    print()
    print("Open https://app-live.browserstack.com, pick a device, and choose")
    print("the app under Uploaded Apps. It installs as a real app on a real")
    print("handset; the first launch is the one that matters.")
else:
    sys.exit("upload failed: " + json.dumps(d, indent=2))
PYEOF
