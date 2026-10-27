// Nulavio Companion for Android (ADR 0005, S11): free software only, no Google Play Services,
// Firebase or trackers, so it can be built by F-Droid.
plugins {
    id("com.android.application")
}

android {
    namespace = "net.nulavio.companion"
    compileSdk = 37

    defaultConfig {
        applicationId = "net.nulavio.companion"
        minSdk = 30 // BiometricPrompt with a CryptoObject and device-credential fallback, per-use Keystore keys
        targetSdk = 37
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        buildConfig = true // BuildConfig.DEBUG gates the test hooks below
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    dependenciesInfo {
        // F-Droid: no dependency metadata block encrypted for Google in the APK.
        includeInApk = false
        includeInBundle = false
    }

    lint {
        abortOnError = true
        warningsAsErrors = false
    }
}

dependencies {
    implementation(project(":nv1"))
    // QR scanning with the camera (Apache-2.0), no Google services.
    implementation("com.journeyapps:zxing-android-embedded:4.3.0") { isTransitive = false }
    implementation("com.google.zxing:core:3.5.4")
}
