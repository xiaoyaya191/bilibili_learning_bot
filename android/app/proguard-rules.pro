# BiliLearn Proguard Rules
-keepattributes *Annotation*
-keepclassmembers class * {
    @androidx.room.* *;
}
-keep class com.bililearn.app.data.model.** { *; }
