# The iOS shell

Four files. Three of them are the app; the fourth is this note.

    StrataBridge.h    the five C functions, declared for Swift
    ScreenView.swift  paints the display list, reports taps
    AppDelegate.swift puts the view on the screen

## Why iOS is smaller than Android

Strata compiles to C. Swift calls C directly through a bridging header, so
there is no glue layer: `host_draw()` is an ordinary Swift call. Android has
to go through JNI, which means a hand-written wrapper for each of the five
functions and an NDK toolchain to compile them with.

## Building the object Swift links against

From the repository root:

    STRATA_CC="clang -target arm64-apple-ios26.0-simulator \
      -isysroot $(xcrun --sdk iphonesimulator --show-sdk-path)" \
      bin/strata build apps/orders_mobile/src/host.sta \
      -o apps/orders_mobile/build/host

`src/host.sta` has no `main`, so the compiler emits `build/host.o` — an object
file rather than a program. That is the file the app links.

STRATA_CC pins the C compiler and is handed to the shell as written, so it
carries flags as well as a name. It is what retargets the object at the
Simulator, which runs iOS on an arm64 Mac and will not link an object built
for macOS. Building it without that line produces a macOS object and Xcode
fails at the link with "building for iOS Simulator, but linking object built
for macOS".

Check what you actually got before opening Xcode:

    file apps/orders_mobile/build/host.o

It must say **Mach-O 64-bit arm64 object**. If it says ELF, the file was built
on Linux — `build/` holds whatever ran last, and a folder shared between
machines will hand Xcode an object it cannot read at all ("Unknown file type
in .../host.o"). Rebuild it with the command above.

Match the deployment target to the runtime you actually have. The Simulator
this was first run on had iOS 17, so the object was built with
`-target arm64-apple-ios17.0-simulator` and Xcode's iOS Deployment Target set
to 17.0. Xcode raises that number when it offers to "update to recommended
settings", and then refuses to launch on an older Simulator — the message names
both versions, which is the one Apple error in this file that says what to do.

For a real handset the target is `arm64-apple-ios` against the iPhoneOS SDK
rather than the Simulator one. Nothing here has been built that way.

## The quick way

    cd ~/strata-project
    STRATA_CC="clang -target arm64-apple-ios15.0-simulator \
      -isysroot $(xcrun --sdk iphonesimulator --show-sdk-path)" \
      bin/strata build apps/orders_mobile/src/host.sta \
      -o apps/orders_mobile/build/host
    open apps/orders_mobile/ios/Orders.xcodeproj

Then press Run. `Orders.xcodeproj` is committed, so there is no project to
create: the files, the bridging header and the link flag are already set.

STRATA_CC exists so a build can be pinned to a specific toolchain, and it goes
to the shell as written -- so it can carry flags as well as a compiler name.
That is what retargets the object at the Simulator, which runs iOS on an
arm64 Mac and will not link an object built for macOS. No change to the build
driver was needed; it already had the door.

## The Xcode project, by hand

1. Xcode → File → New → Project → iOS → App.
   Product Name `Orders`, Interface **Storyboard**, Language **Swift**.
   Untick Core Data and Tests.
2. Delete the generated `ViewController.swift`, `Main.storyboard` and
   `SceneDelegate.swift`. In the target's Info tab, remove the
   "Application Scene Manifest" entry and the "Main storyboard file base
   name" entry — `AppDelegate.swift` here owns the window itself.
3. Drag `StrataBridge.h`, `ScreenView.swift` and `AppDelegate.swift` into the
   project, ticking "Copy items if needed".
4. Build Settings → search "bridging" → set
   **Objective-C Bridging Header** to `Orders/StrataBridge.h`.
5. Drag `build/host.o` into the project and confirm it appears under
   Build Phases → Link Binary With Libraries.
6. Choose an iPhone Simulator as the destination and run.

You should get the order list, scrolling, the new-order form, and a saved row
coming back to the list — the same sequence `src/main.sta` writes out as BMPs
on a desktop.

## What this shell is, and is not

It runs. The orders app builds from this project and runs on an iPhone
Simulator: the screens Strata draws appear, rows scroll, the form takes input
and a saved order comes back to the list.

It has run on the Simulator and nowhere else. A Simulator is a program on a
Mac; it shares the Mac's memory, its architecture and its patience. The two
things it will not show you are on the honest-gaps list in `STAGES.md`: the
object is not built for a handset's architecture, and every redraw leaks a few
kilobytes that a desktop run gets back at exit and an app open all afternoon
does not.

## Keeping the two phones the same

`ScreenView.swift` is a deliberate mirror of `../android/MainActivity.kt`.
Both read `"kind|x|y|w|h|colour|scale|text|action"`, both scale by
`width / 411`, both draw kind 0 as a rectangle, kind 1 as 8-pixel monospace
text on a baseline at `y + 7 * scale`, and both ignore kind 2. A change to one
that is not made to the other makes the same app look different on the two
phones.

Both call `host_start()` once when the view is created. On a phone with an
empty table that is the difference between a list and a blank screen.
