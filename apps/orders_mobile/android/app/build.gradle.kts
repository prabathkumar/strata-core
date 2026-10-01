plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "org.stratalang.orders"
    compileSdk = 34

    defaultConfig {
        applicationId = "org.stratalang.orders"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.4.0-alpha"

        // The two ABIs a real phone actually is. x86_64 is here so the
        // emulator works on an Intel machine; a device farm never needs it.
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64") }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/jni/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Debug signing on purpose: BrowserStack re-signs what it
            // installs, and an unsigned release build cannot be installed
            // anywhere at all. Nothing here is shipped to a store.
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies { }
