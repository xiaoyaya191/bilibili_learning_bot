plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}

val keystorePropertiesFile = rootProject.file("keystore.properties")
val keystoreProperties = if (keystorePropertiesFile.isFile) {
    keystorePropertiesFile.readLines()
        .mapNotNull { line ->
            val index = line.indexOf('=')
            if (index > 0) line.substring(0, index).trim() to line.substring(index + 1).trim() else null
        }.toMap()
} else emptyMap()

android {
    namespace = "com.bililearn.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.bililearn.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 315
        versionName = "3.1.5"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }

        ksp {
            arg("room.schemaLocation", "$projectDir/schemas")
        }
    }

    signingConfigs {
        if (keystorePropertiesFile.isFile) {
            create("release") {
                storeFile = rootProject.file(requireNotNull(keystoreProperties["storeFile"]))
                storePassword = requireNotNull(keystoreProperties["storePassword"])
                keyAlias = requireNotNull(keystoreProperties["keyAlias"])
                keyPassword = requireNotNull(keystoreProperties["keyPassword"])
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons.extended)
    implementation(libs.androidx.navigation.compose)

    // Room
    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)

    // Network & JSON
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.retrofit)
    implementation(libs.retrofit.gson)
    implementation(libs.gson)

    // Coroutines
    implementation(libs.kotlinx.coroutines.android)

    // Image Loading & QR
    implementation(libs.coil.compose)
    implementation(libs.zxing.core)

    // WorkManager & DataStore
    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.androidx.datastore.preferences)

    // Bouncy Castle (RSA Encryption for Bilibili Login)
    implementation(libs.bouncycastle)

    testImplementation(libs.junit)
}

