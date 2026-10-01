#!/usr/bin/env bash
# Build Orders for a real iPhone, as an unsigned .ipa.
#
# Run this on the Mac: it needs Xcode, which is not available anywhere else.
#
# The Simulator build everything so far has used targets
# arm64-apple-ios-simulator and links against the Simulator SDK. A handset
# needs arm64-apple-ios and the iPhoneOS SDK -- a different object file and a
# different SDK, which is exactly why "it runs in the Simulator" has never
# been allowed to mean "it runs on a phone".
#
# No signing: BrowserStack re-signs what it installs, so this needs no Apple
# developer account and no provisioning profile.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/apps/orders_mobile"
BUILD="$APP/build"

command -v xcodebuild >/dev/null || {
    echo "xcodebuild not found. Run this on the Mac, with Xcode installed." >&2
    exit 2
}

SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
echo "[1/3] compiling src/host.sta for arm64-apple-ios"
mkdir -p "$BUILD"
( cd "$APP" && STRATA_CC="clang -target arm64-apple-ios17.0 -isysroot $SDK" \
    "$ROOT/bin/strata" build src/host.sta -o "$BUILD/host.o" )
file "$BUILD/host.o"

echo "[2/3] building Orders.app"
cd "$APP/ios"
xcodebuild -project Orders.xcodeproj -scheme Orders \
    -configuration Release -sdk iphoneos \
    -derivedDataPath "$BUILD/dd" \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" \
    IPHONEOS_DEPLOYMENT_TARGET=17.0 \
    build

APPDIR="$BUILD/dd/Build/Products/Release-iphoneos/Orders.app"
[ -d "$APPDIR" ] || { echo "no Orders.app at $APPDIR" >&2; exit 1; }

echo "[3/3] wrapping it as an .ipa"
rm -rf "$BUILD/Payload" "$BUILD/Orders.ipa"
mkdir -p "$BUILD/Payload"
cp -R "$APPDIR" "$BUILD/Payload/"
( cd "$BUILD" && zip -qry Orders.ipa Payload )
rm -rf "$BUILD/Payload"

echo
echo "IPA: $BUILD/Orders.ipa"
echo "Upload it with: bash tools/browserstack_upload.sh \"$BUILD/Orders.ipa\""
