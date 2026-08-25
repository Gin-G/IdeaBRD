plugins {
    id("com.android.application")
    kotlin("android")
}

android {
    namespace = "net.nickknows.ideabrd"
    compileSdk = 35

    defaultConfig {
        applicationId = "net.nickknows.ideabrd"
        // JGit reads and writes through java.nio.file, which Android only has
        // from API 26. That is the floor for a git client on a phone, not a
        // preference.
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("ANDROID_VERSION_CODE") ?: "1").toInt()
        versionName = System.getenv("ANDROID_VERSION_NAME") ?: "0.1.0"

        // The GitHub OAuth app the device flow signs in against. A client id is
        // public by design — the device flow exists precisely so an app that
        // cannot keep a secret can still authenticate — but it is per-install
        // configuration, so it comes in from the environment rather than being
        // baked into the source.
        buildConfigField(
            "String",
            "GITHUB_CLIENT_ID",
            "\"${System.getenv("IDEABRD_GITHUB_CLIENT_ID") ?: ""}\"",
        )
    }

    signingConfigs {
        create("release") {
            // Supplied by the release workflow. Absent locally, where a debug
            // build is what anyone wants anyway.
            val store = System.getenv("ANDROID_KEYSTORE_PATH")
            if (store != null) {
                storeFile = file(store)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (System.getenv("ANDROID_KEYSTORE_PATH") != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        resources {
            // JGit ships service files and signatures that collide when merged
            // into an APK; none of them are read at runtime.
            excludes += setOf(
                "META-INF/DEPENDENCIES",
                "META-INF/LICENSE*",
                "META-INF/NOTICE*",
                "META-INF/*.kotlin_module",
                "META-INF/INDEX.LIST",
            )
        }
    }
}

dependencies {
    implementation(project(":core"))

    // The Capacitor runtime, from Maven Central rather than through
    // node_modules: the Gradle build then stands on its own, and `npx cap copy`
    // is only needed to put the built web app into assets.
    implementation("com.capacitorjs:core:6.2.1")

    implementation("androidx.appcompat:appcompat:1.7.0")
    // Keystore-backed encryption for the GitHub token. The key never leaves the
    // secure hardware; this only ever holds the ciphertext.
    implementation("androidx.security:security-crypto:1.1.0-alpha06")

    // JGit does the actual cloning, merging and pushing. The httpclient
    // transport is left out: the phone uses the JDK transport, and dragging
    // Apache HttpClient into an APK for it is a large dependency for nothing.
    implementation("org.eclipse.jgit:org.eclipse.jgit:6.10.0.202406032230-r") {
        exclude(group = "org.apache.httpcomponents")
    }
    implementation("org.slf4j:slf4j-android:1.7.36")
}
