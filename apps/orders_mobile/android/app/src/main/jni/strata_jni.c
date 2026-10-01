/* The Android side of the bridge.
 *
 * The Swift shell calls the compiler's own object directly, because Objective-C
 * and C are the same ABI. Java cannot: every call has to cross JNI, which is
 * what this file is and all it is. It converts strings and nothing else.
 *
 * The five functions are the same five the phone bridge has always had. If
 * this file ever needs a sixth, something has leaked out of Strata that should
 * not have.
 */
#include <jni.h>
#include <stdlib.h>
#include <string.h>   /* strdup */

typedef long long strata_int;
typedef char*     strata_str;

strata_int host_draw(void);
strata_str host_item(strata_int index);
strata_str host_hit(strata_int x, strata_int y);
strata_int host_act(strata_str action);
strata_int host_start(void);

#define FN(name) Java_org_stratalang_orders_MainActivity_##name

JNIEXPORT jint JNICALL
FN(drawScreen)(JNIEnv* env, jobject self) {
    (void)env; (void)self;
    return (jint)host_draw();
}

JNIEXPORT jstring JNICALL
FN(itemAt)(JNIEnv* env, jobject self, jint index) {
    (void)self;
    /* Arena memory: the string belongs to Strata and is valid until the next
     * scratch_reset(). NewStringUTF copies it, so the Java side never holds a
     * pointer into the arena -- which is the whole class of bug the reset
     * boundary exists to make impossible to write by accident. */
    const char* s = host_item((strata_int)index);
    return (*env)->NewStringUTF(env, s ? s : "");
}

JNIEXPORT jstring JNICALL
FN(hit)(JNIEnv* env, jobject self, jint x, jint y) {
    (void)self;
    const char* s = host_hit((strata_int)x, (strata_int)y);
    return (*env)->NewStringUTF(env, s ? s : "");
}

JNIEXPORT jint JNICALL
FN(act)(JNIEnv* env, jobject self, jstring action) {
    (void)self;
    if (!action) { return (jint)host_act(""); }
    const char* raw = (*env)->GetStringUTFChars(env, action, NULL);
    /* host_act stores what it is given, so it gets a copy it owns rather than
     * a pointer JNI is about to take back. */
    char* owned = raw ? strdup(raw) : NULL;
    jint rc = (jint)host_act(owned ? owned : "");
    if (raw) { (*env)->ReleaseStringUTFChars(env, action, raw); }
    return rc;
}

JNIEXPORT jint JNICALL
FN(start)(JNIEnv* env, jobject self) {
    (void)env; (void)self;
    return (jint)host_start();
}
