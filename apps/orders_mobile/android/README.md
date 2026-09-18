# The Android shell

Everything a phone needs that Strata does not provide: a window, a canvas, and
finger taps. It is deliberately small — if this file grows, the architecture is
wrong.

The shell does not know what an order is. It asks Strata for a list of things
to draw, paints them, and tells Strata where the finger went. Adding a column,
a screen or a rule changes no Kotlin.

## Building it

```
# 1. the Strata half, for the phone's processor
STRATA_CC=$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android24-clang \
  strata build src/screen.sta -o app/src/main/jniLibs/arm64-v8a/libstrata.so

# 2. the Android half
./gradlew assembleDebug
```

## Not yet run on a device

This is stated plainly rather than left to be discovered. The Strata half is
proven: it compiles for ARM64 and produces byte-identical results to the x86
build under emulation (`test_suite/journey_mobile.py`). The Kotlin below is
written against the documented Android APIs and has **not** been built with the
Android SDK or run on a handset, because neither is available where it was
written. Treat it as a reviewed design, not a tested one.

What is genuinely unknown until someone runs it: the JNI signatures, Gradle
wiring, and how the display list should scale on a real screen density.
