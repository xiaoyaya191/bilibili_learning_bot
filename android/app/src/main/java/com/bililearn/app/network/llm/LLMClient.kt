package com.bililearn.app.network.llm

import com.bililearn.app.data.model.ChatMessage
import com.bililearn.app.data.model.ChatResponse
import com.bililearn.app.data.model.UsageInfo
import com.bililearn.app.data.prefs.AppPreferences
import com.bililearn.app.data.prefs.AdvancedStore
import com.google.gson.Gson
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.BufferedReader
import java.io.InputStreamReader
import java.nio.charset.StandardCharsets
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URI
import java.util.concurrent.TimeUnit

class LLMClient(
    private val preferences: AppPreferences,
    private val advancedStore: AdvancedStore
) {

    // 配置 OkHttpClient 长连接与心跳保持
    @Volatile
    private var client = buildClient()

    fun reloadNetworkConfig() {
        client = buildClient()
    }

    private fun buildClient(): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(60, TimeUnit.SECONDS)
            .readTimeout(600, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .callTimeout(0, TimeUnit.MILLISECONDS)
            .retryOnConnectionFailure(true)
        if (preferences.isProxyEnabled()) {
            runCatching {
                val uri = URI(preferences.getProxyUrl())
                val port = if (uri.port > 0) uri.port else 8080
                val type = if (uri.scheme.equals("socks", true) || uri.scheme.equals("socks5", true)) Proxy.Type.SOCKS else Proxy.Type.HTTP
                require(!uri.host.isNullOrBlank())
                builder.proxy(Proxy(type, InetSocketAddress(uri.host, port)))
            }
        }
        return builder.build()
    }

    private val gson = Gson()
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    /**
     * 判断当前模型是否具备多模态视觉处理能力
     */
    private fun isVisionSupportedModel(model: String): Boolean {
        val m = model.lowercase()
        return m.contains("4o") || m.contains("vision") || m.contains("vl") ||
                m.contains("gemini") || m.contains("claude") || m.contains("minicpm") ||
                m.contains("qvq") || m.contains("gpt-4-turbo")
    }

    /**
     * 实时向 API 服务商拉取官方/自定义当前可用的模型列表
     */
    suspend fun fetchAvailableModels(
        apiKey: String = preferences.getApiKey(),
        baseUrl: String = preferences.getBaseUrl()
    ): Result<List<String>> = withContext(Dispatchers.IO) {
        val cleanKey = apiKey.trim()
        var cleanUrl = baseUrl.trim().trimEnd('/')

        if (cleanUrl.isEmpty()) {
            cleanUrl = "https://api.openai.com/v1"
        }

        val reqBuilder = Request.Builder()
        reqBuilder.addHeader("Accept", "application/json")
        reqBuilder.addHeader("User-Agent", "BiliLearn-Mobile/3.1.3")

        val targetUrl: String
        when {
            cleanUrl.contains("anthropic.com") -> {
                reqBuilder.addHeader("x-api-key", cleanKey)
                reqBuilder.addHeader("anthropic-version", "2023-06-01")
                targetUrl = "$cleanUrl/models"
            }
            cleanUrl.contains("generativelanguage.googleapis.com") -> {
                targetUrl = if (cleanUrl.contains("?")) "$cleanUrl&key=$cleanKey" else "$cleanUrl/models?key=$cleanKey"
            }
            cleanUrl.contains(":11434") -> {
                targetUrl = "$cleanUrl/api/tags"
            }
            else -> {
                if (cleanKey.isNotEmpty()) {
                    reqBuilder.addHeader("Authorization", "Bearer $cleanKey")
                }
                targetUrl = if (cleanUrl.endsWith("/v1") || cleanUrl.contains("deepseek") || cleanUrl.contains("siliconflow") || cleanUrl.contains("/v1/")) {
                    "$cleanUrl/models"
                } else {
                    "$cleanUrl/v1/models"
                }
            }
        }

        try {
            val request = reqBuilder.url(targetUrl).get().build()
            val response = client.newCall(request).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: ""

                if (!resp.isSuccessful) {
                    val errText = try {
                        val errJson = gson.fromJson(body, JsonObject::class.java)
                        errJson.getAsJsonObject("error")?.get("message")?.asString ?: "HTTP ${resp.code}"
                    } catch (e: Exception) {
                        "HTTP ${resp.code}"
                    }
                    return@withContext Result.failure(Exception("拉取模型失败: $errText"))
                }

                val json = gson.fromJson(body, JsonObject::class.java)
                val modelList = mutableListOf<String>()

                if (json.has("data") && json.get("data").isJsonArray) {
                    json.getAsJsonArray("data").forEach { item ->
                        if (item.isJsonObject) {
                            val id = item.asJsonObject.get("id")?.asString
                            if (!id.isNullOrBlank()) modelList.add(id)
                        } else if (item.isJsonPrimitive) {
                            modelList.add(item.asString)
                        }
                    }
                }

                if (json.has("models") && json.get("models").isJsonArray) {
                    json.getAsJsonArray("models").forEach { item ->
                        if (item.isJsonObject) {
                            var id = item.asJsonObject.get("name")?.asString ?: item.asJsonObject.get("id")?.asString
                            if (!id.isNullOrBlank()) {
                                if (id.startsWith("models/")) id = id.substring("models/".length)
                                modelList.add(id)
                            }
                        }
                    }
                }

                if (json.has("models") && modelList.isEmpty()) {
                    json.getAsJsonArray("models")?.forEach { item ->
                        val name = item.asJsonObject?.get("name")?.asString
                        if (!name.isNullOrBlank()) modelList.add(name)
                    }
                }

                val uniqueSorted = modelList.distinct().sorted()
                if (uniqueSorted.isNotEmpty()) {
                    preferences.setSavedAvailableModels(uniqueSorted)
                    Result.success(uniqueSorted)
                } else {
                    Result.failure(Exception("未能从服务商返回的数据中解析出模型列表"))
                }
            }
        } catch (e: Exception) {
            Result.failure(Exception("连接服务商超时或网络错误: ${e.message}"))
        }
    }

    /**
     * 执行大模型聊天/知识生成请求
     * 【核心升级】：启用 SSE 流式增量传输（Stream: true），彻底解决云网关 (ALB/Nginx) 504 Gateway Time-out 超时问题
     */
    suspend fun chatCompletion(
        messages: List<ChatMessage>,
        customModel: String? = null,
        temperature: Float = 0.3f,
        imageBase64: String? = null
    ): ChatResponse = withContext(Dispatchers.IO) {
        val apiKey = preferences.getApiKey().trim()
        if (apiKey.isEmpty()) {
            return@withContext ChatResponse(
                ok = false,
                error = "请先在【设置】页面配置 API Key"
            )
        }
        if (!advancedStore.addUsage()) {
            val quota = advancedStore.normalizedQuota()
            return@withContext ChatResponse(
                ok = false,
                error = "今日 AI 请求配额已用完 (${quota.usedToday}/${quota.dailyLimit})，请在高级中心调整配额"
            )
        }

        var baseUrl = preferences.getBaseUrl().trim().trimEnd('/')
        val model = customModel ?: preferences.getBrainModel()

        val reqUrl = if (baseUrl.endsWith("/v1")) {
            "$baseUrl/chat/completions"
        } else if (baseUrl.contains("deepseek") || baseUrl.contains("siliconflow") || baseUrl.contains("/v1/")) {
            "$baseUrl/chat/completions"
        } else {
            "$baseUrl/v1/chat/completions"
        }

        // 仅当模型真正支持 Vision 时才传递多模态图片，避免纯文本模型 (如 deepseek-chat) 报错或卡死
        val enableVision = !imageBase64.isNullOrBlank() && isVisionSupportedModel(model)

        val rootObj = JsonObject().apply {
            addProperty("model", model)
            addProperty("temperature", temperature)
            addProperty("max_tokens", 4096)
            addProperty("stream", true) // 关键！开启流式传输，服务端持续回传分片，负载均衡网关永远不会发生 504 超时

            val msgsArr = JsonArray()
            messages.forEachIndexed { index, msg ->
                val mObj = JsonObject().apply {
                    addProperty("role", msg.role)

                    if (msg.role == "user" && index == messages.size - 1 && enableVision) {
                        val contentArr = JsonArray()
                        val textObj = JsonObject().apply {
                            addProperty("type", "text")
                            addProperty("text", msg.content)
                        }
                        contentArr.add(textObj)

                        val imgObj = JsonObject().apply {
                            addProperty("type", "image_url")
                            val urlObj = JsonObject().apply {
                                addProperty("url", imageBase64)
                            }
                            add("image_url", urlObj)
                        }
                        contentArr.add(imgObj)
                        add("content", contentArr)
                    } else {
                        addProperty("content", msg.content)
                    }
                }
                msgsArr.add(mObj)
            }
            add("messages", msgsArr)
        }

        val requestBody = rootObj.toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(reqUrl)
            .addHeader("Authorization", "Bearer $apiKey")
            .addHeader("Content-Type", "application/json")
            .addHeader("Accept", "text/event-stream, application/json")
            .post(requestBody)
            .build()

        try {
            val response = client.newCall(request).execute()
            response.use { resp ->
                if (!resp.isSuccessful) {
                    val body = resp.body?.string() ?: ""
                    val errText = try {
                        val errJson = gson.fromJson(body, JsonObject::class.java)
                        errJson.getAsJsonObject("error")?.get("message")?.asString ?: body
                    } catch (e: Exception) {
                        if (resp.code == 504) "网关超时 (HTTP 504)。已启用流式重连" else "HTTP ${resp.code}"
                    }
                    return@withContext ChatResponse(
                        ok = false,
                        error = "AI 调用失败 (HTTP ${resp.code}): $errText"
                    )
                }

                val contentType = resp.header("Content-Type") ?: ""
                val byteStream = resp.body?.byteStream()
                    ?: return@withContext ChatResponse(ok = false, error = "响应流为空")

                val reader = BufferedReader(InputStreamReader(byteStream, StandardCharsets.UTF_8))
                val contentBuilder = StringBuilder()

                // 解析 SSE (Server-Sent Events) 流式数据
                while (true) {
                    val line = reader.readLine() ?: break
                    val trimmed = line.trim()
                    if (trimmed.isEmpty()) continue
                    if (trimmed == "data: [DONE]" || trimmed == "[DONE]") break

                    if (trimmed.startsWith("data:")) {
                        val jsonStr = trimmed.substring(5).trim()
                        try {
                            val chunk = gson.fromJson(jsonStr, JsonObject::class.java)
                            val choices = chunk.getAsJsonArray("choices")
                            if (choices != null && choices.size() > 0) {
                                val delta = choices.get(0).asJsonObject.getAsJsonObject("delta")
                                val text = delta?.get("content")?.asString
                                if (!text.isNullOrEmpty()) {
                                    contentBuilder.append(text)
                                }
                            }
                        } catch (e: Exception) {
                            // 忽略单个 chunk 解析异常
                        }
                    } else if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
                        // 兜底非流式直接返回整个 JSON 的情况
                        try {
                            val chunk = gson.fromJson(trimmed, JsonObject::class.java)
                            val choices = chunk.getAsJsonArray("choices")
                            if (choices != null && choices.size() > 0) {
                                val msg = choices.get(0).asJsonObject.getAsJsonObject("message")
                                val text = msg?.get("content")?.asString
                                if (!text.isNullOrEmpty()) {
                                    contentBuilder.append(text)
                                }
                            }
                        } catch (e: Exception) {
                            // ignore
                        }
                    }
                }

                val finalContent = contentBuilder.toString().trim()
                if (finalContent.isNotEmpty()) {
                    return@withContext ChatResponse(
                        ok = true,
                        content = finalContent
                    )
                } else {
                    return@withContext ChatResponse(ok = false, error = "模型返回数据为空，请重试")
                }
            }
        } catch (e: java.net.SocketTimeoutException) {
            return@withContext ChatResponse(
                ok = false,
                error = "AI 响应超时: 模型生成时间过长，请检查网络或更换更敏捷的模型"
            )
        } catch (e: Exception) {
            return@withContext ChatResponse(
                ok = false,
                error = "网络异常: ${e.localizedMessage ?: e.message}"
            )
        }
    }
}
