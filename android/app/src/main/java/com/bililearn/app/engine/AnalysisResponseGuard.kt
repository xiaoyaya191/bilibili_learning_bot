package com.bililearn.app.engine

import com.google.gson.JsonObject
import com.google.gson.JsonParser

internal object AnalysisResponseGuard {
    fun extractJsonObject(rawContent: String): JsonObject? {
        val content = rawContent.replace(Regex("<think>[\\s\\S]*?</think>"), "").trim()
        val start = content.indexOf('{')
        val end = content.lastIndexOf('}')
        if (start < 0 || end <= start) return null
        return runCatching {
            JsonParser.parseString(content.substring(start, end + 1)).asJsonObject
        }.getOrNull()
    }

    fun matches(json: JsonObject?, bvid: String, requestId: String): Boolean {
        if (json == null) return false
        val responseBvid = json.get("source_bvid")?.asString.orEmpty()
        val responseRequestId = json.get("request_id")?.asString.orEmpty()
        return responseBvid.equals(bvid, ignoreCase = true) && responseRequestId == requestId
    }
}
