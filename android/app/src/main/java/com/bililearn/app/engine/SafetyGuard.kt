package com.bililearn.app.engine

import com.bililearn.app.data.prefs.AppPreferences

class SafetyGuard(private val preferences: AppPreferences) {

    fun isContentSafe(text: String): Boolean {
        if (text.isBlank()) return true

        if (preferences.isContentFilterEnabled() &&
            preferences.getBlockedTerms().any { text.contains(it, ignoreCase = true) }
        ) {
            return false
        }

        if (preferences.isPromptInjectionProtectionEnabled() &&
            preferences.getPromptInjectionPatterns().any { text.contains(it, ignoreCase = true) }
        ) {
            return false
        }

        return true
    }

    fun sanitizeText(text: String): String {
        if (!preferences.isContentFilterEnabled()) return text
        var result = text
        for (kw in preferences.getBlockedTerms()) {
            result = result.replace(kw, "**", ignoreCase = true)
        }
        return result
    }
}
