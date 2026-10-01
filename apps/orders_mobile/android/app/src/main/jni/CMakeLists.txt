# libstrata.so: the Strata program and the JNI shim, nothing else.
#
# host.c is not checked in. It is produced by the Strata compiler from
# src/host.sta by tools/build_android.sh, for the same reason the iOS object
# is not checked in: a generated file in the repository is a second copy of
# the truth, and the one that goes stale is always the copy.
cmake_minimum_required(VERSION 3.22.1)
project(strata C)

set(CMAKE_C_STANDARD 11)

add_library(strata SHARED
    ${CMAKE_CURRENT_SOURCE_DIR}/host.c
    ${CMAKE_CURRENT_SOURCE_DIR}/strata_jni.c)

# The generated C is warning-clean on gcc and clang and should stay that way;
# -Werror here is what keeps a warning from becoming a habit.
target_compile_options(strata PRIVATE -O2 -Wall)

# log for __android_log_write if the runtime ever needs it; m for the maths
# the generated code calls.
find_library(log-lib log)
target_link_libraries(strata ${log-lib} m)
