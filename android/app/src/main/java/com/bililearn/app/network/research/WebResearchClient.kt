package com.bililearn.app.network.research

import com.google.gson.Gson
import com.google.gson.JsonObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

data class ResearchSource(val title: String, val summary: String, val url: String)

class WebResearchClient {
    private val client = OkHttpClient.Builder().connectTimeout(20, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).build()
    private val gson = Gson()

    suspend fun searchWikipedia(query: String): Result<List<ResearchSource>> = withContext(Dispatchers.IO) {
        runCatching {
            val encoded = URLEncoder.encode(query.trim(), "UTF-8")
            val url = "https://zh.wikipedia.org/w/api.php?action=query&list=search&srsearch=$encoded&srlimit=8&utf8=1&format=json&origin=*"
            val request = Request.Builder().url(url).header("User-Agent", "BiliLearn-Android/3.1.5").build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) error("资料检索失败: HTTP ${response.code}")
                val json = gson.fromJson(response.body?.string().orEmpty(), JsonObject::class.java)
                json.getAsJsonObject("query")?.getAsJsonArray("search")?.map { element ->
                    val item = element.asJsonObject
                    val title = item.get("title")?.asString.orEmpty()
                    ResearchSource(
                        title = title,
                        summary = item.get("snippet")?.asString.orEmpty().replace(Regex("<[^>]+>"), ""),
                        url = "https://zh.wikipedia.org/wiki/${URLEncoder.encode(title.replace(' ', '_'), "UTF-8")}"
                    )
                } ?: emptyList()
            }
        }
    }
}
