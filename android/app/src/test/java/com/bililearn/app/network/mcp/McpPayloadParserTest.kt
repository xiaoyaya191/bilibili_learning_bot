package com.bililearn.app.network.mcp

import org.junit.Assert.assertEquals
import org.junit.Test

class McpPayloadParserTest {
    @Test
    fun parsesPlainJson() {
        assertEquals(1, parseMcpPayload("""{"jsonrpc":"2.0","id":1,"result":{}}""").get("id").asInt)
    }

    @Test
    fun parsesLastValidSseEventWithoutConcatenatingEvents() {
        val raw = """
            event: message
            data: {"jsonrpc":"2.0","id":1,"result":{"step":"first"}}

            event: message
            data: {"jsonrpc":"2.0","id":1,"result":{"step":"final"}}

            data: [DONE]
        """.trimIndent()
        assertEquals("final", parseMcpPayload(raw).getAsJsonObject("result").get("step").asString)
    }
}
