package com.bililearn.app.engine

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AnalysisResponseGuardTest {
    @Test
    fun acceptsOnlyMatchingVideoAndRequest() {
        val json = AnalysisResponseGuard.extractJsonObject(
            """```json
                {"source_bvid":"BV1Current","request_id":"request-current","summary":"ok"}
                ```""".trimIndent()
        )

        assertTrue(AnalysisResponseGuard.matches(json, "BV1Current", "request-current"))
        assertFalse(AnalysisResponseGuard.matches(json, "BV1Other", "request-current"))
        assertFalse(AnalysisResponseGuard.matches(json, "BV1Current", "request-old"))
    }

    @Test
    fun rejectsMissingOrMalformedIdentity() {
        assertFalse(AnalysisResponseGuard.matches(null, "BV1Current", "request-current"))
        val missingRequest = AnalysisResponseGuard.extractJsonObject(
            """{"source_bvid":"BV1Current","summary":"stale response"}"""
        )
        assertFalse(AnalysisResponseGuard.matches(missingRequest, "BV1Current", "request-current"))
        assertFalse(
            AnalysisResponseGuard.matches(
                AnalysisResponseGuard.extractJsonObject("not json"),
                "BV1Current",
                "request-current"
            )
        )
    }
}
