plugins {
    kotlin("jvm")
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
    testLogging { events("failed") }
    // The golden IDEA.md files the Python renderer also asserts against. Passed
    // in rather than duplicated into test resources: two copies of a contract
    // are two things that can drift, which is the whole failure being guarded.
    systemProperty(
        "ideabrd.fixtures",
        rootProject.projectDir.parentFile.resolve("fixtures").absolutePath,
    )
}
