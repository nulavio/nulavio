// The phone side of protocol nv1 in plain Java: no Android API, so it is tested on the desktop JVM
// against the Python desktop (tests/unit/test_companion_protocol.py) and fixed vectors.
plugins {
    `java-library`
    id("com.android.lint") // the app's lint (checkDependencies) also checks this code, which ships in the APK
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

tasks.withType<JavaCompile>().configureEach {
    options.release.set(17)
    options.compilerArgs.addAll(listOf("-Xlint:all", "-Werror"))
}

dependencies {
    // X25519, Ed25519, XChaCha20-Poly1305 (Tink) and keyed BLAKE2b (Bouncy Castle): no cryptography of our own.
    implementation("com.google.crypto.tink:tink-android:1.24.0")
    implementation("org.bouncycastle:bcprov-jdk18on:1.86")
    testImplementation("junit:junit:4.13.2")
}

// This classpath ships in the APK, so it is locked: gradle.lockfile lists every module it resolves,
// transitive ones included. A change shows up in review and fails the build until the lock is
// rewritten (docs/security/dependency-updates.md). STRICT: a missing lock fails too.
dependencyLocking {
    lockMode.set(LockMode.STRICT)
}
configurations.named("runtimeClasspath") {
    resolutionStrategy.activateDependencyLocking()
}

val fixtures = rootDir.parentFile.resolve("tests/fixtures")

tasks.test {
    useJUnit()
    systemProperty("nv1.fixtures", fixtures.path)
}

// The Python cross test runs the test phone (PhoneCli) with this classpath.
val writeTestClasspath by tasks.registering {
    val out = layout.buildDirectory.file("nv1-test-classpath.txt")
    val cp = sourceSets["test"].runtimeClasspath
    inputs.files(cp)
    outputs.file(out)
    doLast { out.get().asFile.writeText(cp.files.joinToString(":")) }
}
tasks.named("testClasses") { finalizedBy(writeTestClasspath) }
