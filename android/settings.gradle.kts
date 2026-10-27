// Nulavio Companion (ADR 0005, S11): the phone side of protocol nv1 and the Android app.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "nulavio-companion"
include(":nv1", ":app")
