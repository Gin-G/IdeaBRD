import com.android.build.api.artifact.SingleArtifact
import java.util.zip.ZipFile

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

    androidResources {
        // AGP's default ignore pattern drops any asset directory whose name
        // starts with an underscore — and SvelteKit calls its entire build
        // output `_app`. Left alone, the APK ships index.html with none of the
        // JavaScript or CSS it asks for, and the app opens to a blank page with
        // nothing in the build log to say why. This is the stock pattern with
        // `<dir>_*` taken out.
        ignoreAssetsPattern =
            "!.svn:!.git:!.ds_store:!*.scc:.*:!CVS:!thumbs.db:!picasa.ini:!*~"
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

/**
 * Fail the build if the web app didn't make it into the APK.
 *
 * This is here because it already happened, twice, and shipped: AGP's default
 * asset ignore pattern drops directories whose names begin with an underscore,
 * SvelteKit calls its build output `_app`, and so the APK contained index.html
 * and none of the JavaScript it asks for. Nothing failed. The build was green,
 * the release was signed and published, and the app opened to a white page.
 *
 * A packaging rule that silently discards the entire application is worth a
 * check that runs every time rather than a comment nobody reads.
 */
abstract class VerifyWebAssetsTask : DefaultTask() {
    /** Where `npx cap copy android` puts the built web app. */
    @get:Internal
    abstract val webAssets: DirectoryProperty

    /** The APK, so this checks what actually shipped rather than an input to it. */
    @get:InputFiles
    abstract val apkDirectory: DirectoryProperty

    @TaskAction
    fun verify() {
        val source = webAssets.get().asFile
        if (!source.isDirectory) {
            throw GradleException(
                "$source does not exist. Run `npm run build && npx cap copy android` " +
                    "in ../frontend first: without it the app has no web app to load.",
            )
        }
        val expected = source.walkTopDown()
            .filter { it.isFile }
            .map { it.relativeTo(source).invariantSeparatorsPath }
            .toSortedSet()

        val apk = apkDirectory.get().asFile.walkTopDown().firstOrNull { it.extension == "apk" }
            ?: throw GradleException("No APK found in ${apkDirectory.get().asFile}.")

        val packaged = ZipFile(apk).use { zip ->
            zip.entries().asSequence()
                .map { it.name }
                .filter { it.startsWith("assets/public/") }
                .map { it.removePrefix("assets/public/") }
                .toSortedSet()
        }

        val missing = expected - packaged
        if (missing.isNotEmpty()) {
            throw GradleException(
                "${apk.name} is missing ${missing.size} of ${expected.size} web assets, " +
                    "starting with: ${missing.take(5).joinToString()}. The app would open " +
                    "to a blank page. Check android.androidResources.ignoreAssetsPattern — " +
                    "AGP's default drops any directory whose name starts with an underscore.",
            )
        }
        logger.lifecycle("${apk.name}: all ${expected.size} web assets packaged.")
    }
}

androidComponents {
    onVariants { variant ->
        val verify = tasks.register<VerifyWebAssetsTask>(
            "verify${variant.name.replaceFirstChar(Char::uppercaseChar)}WebAssets",
        ) {
            webAssets.set(layout.projectDirectory.dir("src/main/assets/public"))
            apkDirectory.set(variant.artifacts.get(SingleArtifact.APK))
        }
        // AGP creates the assemble tasks after this block runs, so match them
        // lazily rather than looking one up that doesn't exist yet.
        val assembleTask = "assemble${variant.name.replaceFirstChar(Char::uppercaseChar)}"
        tasks.configureEach {
            if (name == assembleTask) finalizedBy(verify)
        }
    }
}
