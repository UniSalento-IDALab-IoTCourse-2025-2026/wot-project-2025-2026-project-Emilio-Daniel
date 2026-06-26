plugins {
    id("com.android.application")
}

android {
    namespace = "it.unisalento.iotedgecompanion"
    compileSdk = 35

    defaultConfig {
        applicationId = "it.unisalento.iotedgecompanion"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }
}
