package com.bililearn.app.network.mcp

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

data class McpToolInfo(
    val name: String,
    val description: String,
    val inputSchema: String
)

class McpHttpClient {
    private val gson = Gson()
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()
    private val mediaType = "application/json; charset=utf-8".toMediaType()

    suspend fun listTools(endpoint: String): Result<List<McpToolInfo>> = withContext(Dispatchers.IO) {
        runCatching {
            val session = initialize(endpoint)
            sendNotification(endpoint, session)
            val response = rpc(endpoint, session, 2, "tools/list", JsonObject())
            val result = response.getAsJsonObject("result") ?: error(responseError(response))
            result.getAsJsonArray("tools")?.map { element ->
                val tool = element.asJsonObject
                McpToolInfo(
                    name = tool.get("name")?.asString.orEmpty(),
                    description = tool.get("description")?.asString.orEmpty(),
                    inputSchema = tool.get("inputSchema")?.toString().orEmpty()
                )
            }.orEmpty().filter { it.name.isNotBlank() }
        }
    }

    suspend fun callTool(endpoint: String, toolName: String, argumentsJson: String): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val args = if (argumentsJson.isBlank()) JsonObject() else JsonParser.parseString(argumentsJson).asJsonObject
            val session = initialize(endpoint)
            sendNotification(endpoint, session)
            val params = JsonObject().apply {
                addProperty("name", toolName)
                add("arguments", args)
            }
            val response = rpc(endpoint, session, 3, "tools/call", params)
            val result = response.getAsJsonObject("result") ?: error(responseError(response))
            val text = result.getAsJsonArray("content")?.joinToString("\n") { item ->
                val obj = item.asJsonObject
                obj.get("text")?.asString ?: obj.toString()
            }.orEmpty()
            if (result.get("isError")?.asBoolean == true) error(text.ifBlank { "MCP 工具返回错误" })
            text.ifBlank { result.toString() }
        }
    }

    private fun initialize(endpoint: String): String? {
        require(endpoint.startsWith("http://") || endpoint.startsWith("https://")) { "MCP 地址必须以 http:// 或 https:// 开头" }
        val params = JsonObject().apply {
            addProperty("protocolVersion", "2025-03-26")
            add("capabilities", JsonObject())
            add("clientInfo", JsonObject().apply {
                addProperty("name", "BiliLearn Android")
                addProperty("version", "3.1.5")
            })
        }
        val result = post(endpoint, null, requestObject(1, "initialize", params))
        val root = parseMcpPayload(result.first)
        if (!root.has("result")) error(responseError(root))
        return result.second
    }

    private fun sendNotification(endpoint: String, session: String?) {
        val body = JsonObject().apply {
            addProperty("jsonrpc", "2.0")
            addProperty("method", "notifications/initialized")
        }
        runCatching { post(endpoint, session, body) }
    }

    private fun rpc(endpoint: String, session: String?, id: Int, method: String, params: JsonObject): JsonObject {
        return parseMcpPayload(post(endpoint, session, requestObject(id, method, params)).first)
    }

    private fun requestObject(id: Int, method: String, params: JsonObject) = JsonObject().apply {
        addProperty("jsonrpc", "2.0")
        addProperty("id", id)
        addProperty("method", method)
        add("params", params)
    }

    private fun post(endpoint: String, session: String?, body: JsonObject): Pair<String, String?> {
        val builder = Request.Builder()
            .url(endpoint)
            .addHeader("Accept", "application/json, text/event-stream")
            .post(gson.toJson(body).toRequestBody(mediaType))
        if (!session.isNullOrBlank()) builder.addHeader("Mcp-Session-Id", session)
        client.newCall(builder.build()).execute().use { response ->
            val responseBody = response.body?.string().orEmpty()
            if (!response.isSuccessful) error("MCP HTTP ${response.code}: ${responseBody.take(300)}")
            return responseBody to response.header("Mcp-Session-Id")
        }
    }

    private fun responseError(root: JsonObject): String {
        val error = root.getAsJsonObject("error")
        return error?.get("message")?.asString ?: "MCP 协议响应无 result"
    }
}

internal fun parseMcpPayload(raw: String): JsonObject {
    val trimmed = raw.trim()
    require(trimmed.isNotBlank()) { "MCP 服务返回空响应" }
    if (!trimmed.lineSequence().any { it.trimStart().startsWith("data:") }) {
        return JsonParser.parseString(trimmed).asJsonObject
    }
    val candidates = trimmed.split(Regex("\\r?\\n\\r?\\n+"))
        .map { event ->
            event.lineSequence()
                .map(String::trimStart)
                .filter { it.startsWith("data:") }
                .joinToString("\n") { it.removePrefix("data:").trimStart() }
        }
        .filter { it.isNotBlank() && it != "[DONE]" }
    return candidates.asReversed().firstNotNullOfOrNull { payload ->
        runCatching { JsonParser.parseString(payload).asJsonObject }.getOrNull()
    } ?: error("MCP SSE 响应不包含有效 JSON")
}
