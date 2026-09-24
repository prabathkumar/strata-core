"""Where the self-hosted driver is cached.

The name carries the platform that built it, because build/ is not always one
machine's: a folder shared between a Mac and a Linux VM, a network home
directory or a repository on a USB stick otherwise gets a driver built by
whichever ran last, and the other tries to execute a binary for the wrong
operating system.

This lives in one file because three test suites need it and three copies of a
filename is how the next rename breaks CI — which is exactly what happened
when the name changed and these tests kept looking for the old one.

It must agree with driver_bin() in bin/strata, which builds the name from
`uname -s` and `uname -m`.
"""
import os
import platform

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def driver_path(root=None):
    return os.path.join(root or ROOT, "build",
                        f"strata-build-{platform.system()}-{platform.machine()}")
