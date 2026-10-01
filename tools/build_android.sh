#!/usr/bin/env bash
# Build the Orders app for Android.
#
# Two steps, and the first is the only one that is Strata's business:
#
#   1. The compiler turns apps/orders_mobile/src/host.sta into C.
#   2. Gradle and the NDK turn that C, plus the JNI shim, into libstrata.so
#      for each ABI, and wrap it in an APK.
#
# The generated C is not checked in. It lands in the jni directory, which
# .gitignore covers, so the repository holds the source and never a stale
# copy of its output.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/apps/orders_mobile"
JNI="$APP/android/app/src/main/jni"

echo "[1/2] compiling src/host.sta to C"
( cd "$APP" && python3 "$ROOT/bootstrap/stage0.py" src/host.sta --emit-c ) > "$JNI/host.c"
echo "      $(wc -l < "$JNI/host.c") lines -> app/src/main/jni/host.c"

# A missing SDK is the usual reason this stops, and the message Gradle gives
# for it names a file rather than the thing to install.
if [ -z "${ANDROID_HOME:-}" ] && [ -z "${ANDROID_SDK_ROOT:-}" ] \
   && [ ! -d "$HOME/Library/Android/sdk" ] && [ ! -d "$HOME/Android/Sdk" ]; then
    echo
    echo "No Android SDK found."
    echo "  Install Android Studio, then in it: Settings -> Languages & Frameworks"
    echo "  -> Android SDK -> SDK Tools -> tick 'NDK (Side by side)' and 'CMake'."
    echo "  Or set ANDROID_HOME to an existing SDK."
    echo
    echo "The C is built and correct; only the Android toolchain is missing."
    exit 2
fi

echo "[2/2] assembling the APK"
cd "$APP/android"
if [ ! -x ./gradlew ]; then
    # No wrapper checked in, so use whatever gradle the machine has.
    command -v gradle >/dev/null || {
        echo "gradle is not installed and there is no ./gradlew here." >&2
        echo >&2
        if [ "$(uname -s)" = "Darwin" ]; then
            echo "  brew install gradle" >&2
        else
            echo "  sudo apt install gradle     (or use your package manager)" >&2
        fi
        echo >&2
        echo "Opening apps/orders_mobile/android in Android Studio once also" >&2
        echo "works: it writes the wrapper, and after that this script uses it." >&2
        echo >&2
        echo "The C is built and correct; only the build tool is missing." >&2
        exit 2
    }
    # With gradle present, leave a wrapper behind so the next person -- and CI
    # -- builds with a pinned version rather than whatever they happen to have.
    [ -f gradle/wrapper/gradle-wrapper.properties ] || gradle wrapper --quiet || true
    gradle assembleRelease
else
    ./gradlew assembleRelease
fi

APK="$APP/android/app/build/outputs/apk/release/app-release.apk"
if [ -f "$APK" ]; then
    echo
    echo "APK: $APK"
    echo "Upload it with: bash tools/browserstack_upload.sh \"$APK\""
else
    echo "Gradle finished but no APK is where one was expected." >&2
    exit 1
fi
