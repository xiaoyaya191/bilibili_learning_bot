package com.bililearn.app.network.asr

import android.content.Context
import android.net.Uri
import com.bililearn.app.data.prefs.AppPreferences
import com.google.gson.JsonParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

class AudioTranscriptionClient(
    private val context: Context,
    private val preferences: AppPreferences
) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.MINUTES)
        .readTimeout(10, TimeUnit.MINUTES)
        .build()

    suspend fun transcribe(uri: Uri, language: String): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val key = preferences.getApiKey().trim()
            require(key.isNotBlank()) { "请先配置支持音频转写的 API Key" }
            val bytes = context.contentResolver.openInputStream(uri)?.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(64 * 1024)
                var total = 0L
                while (true) {
                    val read = input.read(buffer)
                    if (read <= 0) break
                    total += read
                    require(total <= MAX_FILE_BYTES) { "文件超过 25 MB，请先压缩或切分" }
                    output.write(buffer, 0, read)
                }
                output.toByteArray()
            } ?: error("无法读取所选文件")
            val mime = context.contentResolver.getType(uri) ?: "application/octet-stream"
            val fileName = queryName(uri).ifBlank { "audio-upload" }
            val form = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("model", preferences.getAsrModel())
                .addFormDataPart("language", language.substringBefore('-'))
                .addFormDataPart("response_format", "json")
                .addFormDataPart("file", fileName, bytes.toRequestBody(mime.toMediaTypeOrNull()))
                .build()
            val base = preferences.getBaseUrl().trim().trimEnd('/')
            val endpoint = if (base.endsWith("/v1")) "$base/audio/transcriptions" else "$base/v1/audio/transcriptions"
            val request = Request.Builder().url(endpoint).addHeader("Authorization", "Bearer $key").post(form).build()
            client.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) error("转写服务 HTTP ${response.code}: ${body.take(300)}")
                val root = JsonParser.parseString(body).asJsonObject
                root.get("text")?.asString?.trim().takeUnless { it.isNullOrBlank() }
                    ?: error("转写服务未返回 text")
            }
        }
    }

    private fun queryName(uri: Uri): String {
        return context.contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0).orEmpty() else ""
        }.orEmpty()
    }

    companion object {
        private const val MAX_FILE_BYTES = 25L * 1024 * 1024
    }
}
