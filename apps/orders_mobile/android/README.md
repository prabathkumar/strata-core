# Orders, on Android

The same five functions the iOS shell calls, reached through JNI because Java
cannot call C directly the way Swift can. Everything that is not those five
functions and the drawing of their answers is Strata.

```
android/
  app/src/main/java/org/stratalang/orders/MainActivity.kt   the whole UI
  app/src/main/jni/strata_jni.c                             the bridge
  app/src/main/jni/CMakeLists.txt                           builds libstrata.so
  app/src/main/jni/host.c                                   generated, not checked in
```

## Building it

```bash
bash tools/build_android.sh
```

Two steps. The Strata compiler turns `src/host.sta` into C; Gradle and the NDK
turn that C plus the shim into `libstrata.so` for `arm64-v8a`, `armeabi-v7a`
and `x86_64`, and wrap it in an APK.

You need Android Studio with **NDK (Side by side)** and **CMake** ticked under
SDK Tools. The script says so rather than letting Gradle fail with a message
about a missing file.

`host.c` is generated and ignored by git, for the same reason the iOS object
is: a generated file in the repository is a second copy of the truth, and the
copy is the one that goes stale.

## What this is, and is not

It runs. The APK was installed on a Google Pixel 7 running Android 13 on
1 October, through BrowserStack App Live, and showed the order list.
`System.loadLibrary("strata")` found the native library, the JNI bridge
resolved, and the screen Strata drew appeared on a phone.

Every commit checks the part that is Strata's responsibility, so it stays
true: `journey_mobile` compiles the phone bridge to C, links it with the JNI
shim into a shared library, and asserts that every function `MainActivity`
declares `external` is in it. A missing one is an `UnsatisfiedLinkError` on
the first tap, which is not a thing to learn from a user.

What it is not: one phone model, on a device farm rather than in somebody's
pocket, and nothing has been near the Play Store.

## Why the screen is drawn rather than built from widgets

`MainActivity` asks Strata for a list of things to draw and paints them. It
knows nothing about orders, customers or amounts. Adding a column, a screen or
a business rule changes this file not at all, which is the point: two phone
platforms and a web tier that all follow one schema, instead of three places
to forget the same change.

The display list is in device-independent pixels against a 411-wide screen and
scaled by one factor. One number, because a layout needing more than one is a
layout that will not survive the next phone.
