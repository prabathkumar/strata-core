/*
 * The entire Strata-to-Swift boundary.
 *
 * Strata compiles to C, and Swift calls C without a glue layer, so this file
 * is the whole bridge: five declarations and nothing else. Compare the
 * Android side, which needs JNI wrappers around these same five.
 *
 * Add this file as the target's "Objective-C Bridging Header" in Xcode and
 * the functions become ordinary Swift calls.
 */

#ifndef STRATA_BRIDGE_H
#define STRATA_BRIDGE_H

#include <stdint.h>

/* Rebuild the display list. Returns how many items it holds. */
int64_t host_draw(void);

/* One item, as "kind|x|y|w|h|colour|scale|text|action". */
char* host_item(int64_t index);

/* What a tap at this point means, or "" for nothing. */
char* host_hit(int64_t x, int64_t y);

/* Tell Strata a tap happened; it decides what changes. */
int64_t host_act(const char* action);

/* Called once before anything else, so a screen has rows to show. */
int64_t host_start(void);

#endif
