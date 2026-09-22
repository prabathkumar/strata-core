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

    bin/strata build apps/orders_mobile/src/host.sta -o apps/orders_mobile/build/host

`src/host.sta` has no `main`, so the compiler emits `build/host.o` — an object
file rather than a program. That is the file the app links.

For the Simulator on Apple silicon that object is already the right
architecture. For a real handset it is not: it has to be rebuilt for
`arm64-apple-ios`, which the driver does not target yet.

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

## What this shell is not

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
