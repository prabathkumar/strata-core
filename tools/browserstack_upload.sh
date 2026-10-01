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

echo "uploading $(basename "$APP") ($(du -h "$APP" | cut -f1))"
RESPONSE="$(curl -sS -u "$BROWSERSTACK_USERNAME:$BROWSERSTACK_ACCESS_KEY" \
    -X POST "https://api-cloud.browserstack.com/app-live/upload" \
    -F "file=@$APP" \
    -F 'data={"custom_id":"strata-orders"}')"

printf '%s\n' "$RESPONSE" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit("BrowserStack did not answer with JSON:\n" + sys.stdin.read())
if "app_url" in d:
    print("  app_url:  " + d["app_url"])
    print("  custom_id: " + d.get("custom_id", "strata-orders"))
    print()
    print("Open https://app-live.browserstack.com, pick a device, and choose")
    print("the app under 'Uploaded Apps'. It installs as a real app on a real")
    print("handset; the first launch is the one that matters.")
else:
    sys.exit("upload failed: " + json.dumps(d, indent=2))
'
