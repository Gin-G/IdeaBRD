// The Android side of IdeaBRD.
//
// Two modules, split along the line that matters: :core is plain Kotlin with no
// Android in it — the file format, the ordering keys, the merge — so it can be
// tested on any machine with a JVM, including one with no Android SDK installed.
// :app is the Capacitor shell and the native plugins, and needs the SDK.
//
// That is also why :app is included conditionally. `./gradlew :core:test` is the
// check that matters most often (it is the parser the phone will own), and it
// should not require a 3GB SDK download to run.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "ideabrd-android"

include(":core")

val hasAndroidSdk =
    System.getenv("ANDROID_HOME") != null ||
        System.getenv("ANDROID_SDK_ROOT") != null ||
        file("local.properties").exists()

if (hasAndroidSdk) {
    include(":app")
} else {
    logger.lifecycle("No Android SDK found — configuring :core only.")
}
