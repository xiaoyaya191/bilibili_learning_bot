package com.bililearn.app.network.bilibili

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.util.Base64
import com.bililearn.app.data.model.*
import com.bililearn.app.data.prefs.AppPreferences
import com.bililearn.app.network.crypto.BiliCrypto
import com.google.gson.Gson
import com.google.gson.JsonObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.xmlpull.v1.XmlPullParser
import org.xmlpull.v1.XmlPullParserFactory
import java.io.ByteArrayOutputStream
import java.io.StringReader
import java.net.URLEncoder
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URI
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

class BiliApiClient(private val preferences: AppPreferences) {

    @Volatile
    private var client = buildClient()

    fun reloadNetworkConfig() {
        client = buildClient()
    }

    private fun buildClient(): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(60, TimeUnit.SECONDS)
            .readTimeout(180, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .callTimeout(0, TimeUnit.MILLISECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
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

    private val WBI_MIXIN_KEY_ENC_TAB = intArrayOf(
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
        33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
        61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
        36, 20, 34, 44, 52
    )

    private var cachedImgKey = ""
    private var cachedSubKey = ""
    private var lastWbiKeyFetchTime = 0L

    private val guestBuvid3 = "${UUID.randomUUID().toString().replace("-", "")}${System.currentTimeMillis() % 100000}infoc"

    private fun getBaseHeaders(): Map<String, String> {
        val headers = mutableMapOf(
            "User-Agent" to "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer" to "https://www.bilibili.com/",
            "Origin" to "https://www.bilibili.com",
            "Accept" to "application/json, text/plain, */*",
            "Accept-Language" to "zh-CN,zh;q=0.9,en;q=0.8"
        )
        val sessData = preferences.getSessData()
        val cookies = mutableMapOf<String, String>()
        if (sessData.isNotEmpty()) {
            cookies["SESSDATA"] = sessData
            cookies["bili_jct"] = preferences.getBiliJct()
            cookies["DedeUserID"] = preferences.getDedeUserId()
        }
        cookies["buvid3"] = guestBuvid3
        cookies["b_nut"] = (System.currentTimeMillis() / 1000).toString()
        cookies["CURRENT_FNVAL"] = "4048"
        headers["Cookie"] = BiliCrypto.buildCookieHeader(cookies)
        return headers
    }

    /**
     * 智能提取 BV 号 (支持直接输入 BV 号、网页链接以及 b23.tv 短链接重定向解析)
     */
    suspend fun resolveAndExtractBvid(text: String): String? = withContext(Dispatchers.IO) {
        if (text.isBlank()) return@withContext null

        val pattern = Pattern.compile("(BV[a-zA-Z0-9]{10})")
        val matcher = pattern.matcher(text)
        if (matcher.find()) {
            return@withContext matcher.group(1)
        }

        val shortUrlPattern = Pattern.compile("(https?://b23\\.tv/[a-zA-Z0-9_-]+)")
        val shortMatcher = shortUrlPattern.matcher(text)
        if (shortMatcher.find()) {
            val shortUrl = shortMatcher.group(1) ?: return@withContext null
            try {
                val req = Request.Builder().url(shortUrl).get().build()
                client.newCall(req).execute().use { resp ->
                    val finalUrl = resp.request.url.toString()
                    val finalMatcher = pattern.matcher(finalUrl)
                    if (finalMatcher.find()) {
                        return@withContext finalMatcher.group(1)
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
        null
    }

    fun extractBvid(text: String): String? {
        if (text.isBlank()) return null
        val pattern = Pattern.compile("(BV[a-zA-Z0-9]{10})")
        val matcher = pattern.matcher(text)
        return if (matcher.find()) matcher.group(1) else null
    }

    /**
     * 获取 WBI 签名所需的 img_key 和 sub_key (带 1 小时内存缓存)
     */
    private suspend fun getWbiKeys(): Pair<String, String>? = withContext(Dispatchers.IO) {
        val now = System.currentTimeMillis()
        if (cachedImgKey.isNotBlank() && cachedSubKey.isNotBlank() && (now - lastWbiKeyFetchTime < 3600_000L)) {
            return@withContext Pair(cachedImgKey, cachedSubKey)
        }

        try {
            val url = "https://api.bilibili.com/x/web-interface/nav"
            val reqBuilder = Request.Builder().url(url)
            getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext null
                val json = gson.fromJson(body, JsonObject::class.java)
                if (json.get("code")?.asInt == 0) {
                    val wbiImg = json.getAsJsonObject("data")?.getAsJsonObject("wbi_img")
                    val imgUrl = wbiImg?.get("img_url")?.asString ?: ""
                    val subUrl = wbiImg?.get("sub_url")?.asString ?: ""

                    val imgKey = imgUrl.substringAfterLast("/").substringBefore(".")
                    val subKey = subUrl.substringAfterLast("/").substringBefore(".")

                    if (imgKey.isNotBlank() && subKey.isNotBlank()) {
                        cachedImgKey = imgKey
                        cachedSubKey = subKey
                        lastWbiKeyFetchTime = now
                        return@withContext Pair(imgKey, subKey)
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        null
    }

    private fun getMixinKey(orig: String): String {
        val sb = StringBuilder()
        for (i in 0 until 32) {
            if (i < WBI_MIXIN_KEY_ENC_TAB.size && WBI_MIXIN_KEY_ENC_TAB[i] < orig.length) {
                sb.append(orig[WBI_MIXIN_KEY_ENC_TAB[i]])
            }
        }
        return sb.toString()
    }

    private fun md5Hex(str: String): String {
        val md = MessageDigest.getInstance("MD5")
        val digest = md.digest(str.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    /**
     * WBI 加密签名参数
     */
    private fun signWbi(params: Map<String, String>, imgKey: String, subKey: String): String {
        val mixinKey = getMixinKey(imgKey + subKey)
        val currTime = System.currentTimeMillis() / 1000

        val newParams = params.toMutableMap()
        newParams["wts"] = currTime.toString()

        val sortedKeys = newParams.keys.sorted()
        val queryList = mutableListOf<String>()

        for (k in sortedKeys) {
            val v = newParams[k] ?: ""
            val cleanVal = v.replace(Regex("[!'()*]"), "")
            queryList.add("${URLEncoder.encode(k, "UTF-8")}=${URLEncoder.encode(cleanVal, "UTF-8")}")
        }

        val queryString = queryList.joinToString("&")
        val wRid = md5Hex(queryString + mixinKey)

        return "$queryString&w_rid=$wRid"
    }

    /**
     * 获取视频详情
     */
    suspend fun fetchVideoDetail(bvid: String): Result<VideoDetail> = withContext(Dispatchers.IO) {
        val cleanBvid = extractBvid(bvid) ?: bvid.trim()
        try {
            val url = "https://api.bilibili.com/x/web-interface/view?bvid=$cleanBvid"
            val reqBuilder = Request.Builder().url(url)
            getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext Result.failure(Exception("空响应"))
                val json = gson.fromJson(body, JsonObject::class.java)

                if (json.get("code")?.asInt == 0) {
                    val data = json.getAsJsonObject("data")
                    val ownerObj = data.getAsJsonObject("owner")
                    val statObj = data.getAsJsonObject("stat")

                    val pages = mutableListOf<VideoPage>()
                    data.getAsJsonArray("pages")?.forEach { p ->
                        val pObj = p.asJsonObject
                        pages.add(
                            VideoPage(
                                cid = pObj.get("cid")?.asLong ?: 0L,
                                page = pObj.get("page")?.asInt ?: 1,
                                part = pObj.get("part")?.asString ?: "",
                                duration = pObj.get("duration")?.asLong ?: 0L
                            )
                        )
                    }

                    val tags = mutableListOf<String>()
                    data.getAsJsonArray("tag")?.forEach { t ->
                        tags.add(t.asJsonObject.get("tag_name")?.asString ?: "")
                    }

                    val detail = VideoDetail(
                        bvid = data.get("bvid")?.asString ?: cleanBvid,
                        aid = data.get("aid")?.asLong ?: 0L,
                        cid = data.get("cid")?.asLong ?: 0L,
                        title = data.get("title")?.asString ?: "",
                        desc = data.get("desc")?.asString ?: "",
                        pic = data.get("pic")?.asString ?: "",
                        duration = data.get("duration")?.asLong ?: 0L,
                        owner = OwnerInfo(
                            mid = ownerObj.get("mid")?.asLong ?: 0L,
                            name = ownerObj.get("name")?.asString ?: "",
                            face = ownerObj.get("face")?.asString ?: ""
                        ),
                        tname = data.get("tname")?.asString ?: "通用知识",
                        tags = tags,
                        stat = VideoStat(
                            view = statObj.get("view")?.asLong ?: 0L,
                            danmaku = statObj.get("danmaku")?.asLong ?: 0L,
                            reply = statObj.get("reply")?.asLong ?: 0L,
                            favorite = statObj.get("favorite")?.asLong ?: 0L,
                            coin = statObj.get("coin")?.asLong ?: 0L,
                            share = statObj.get("share")?.asLong ?: 0L,
                            like = statObj.get("like")?.asLong ?: 0L
                        ),
                        pages = pages
                    )
                    Result.success(detail)
                } else {
                    Result.failure(Exception(json.get("message")?.asString ?: "请求失败"))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * 拉取视频字幕 (支持 WBI 动态加密签名与 AI 语音转写字幕提取)
     */
    suspend fun fetchSubtitles(bvid: String, cid: Long, videoTitle: String = ""): List<SubtitleItem> = withContext(Dispatchers.IO) {
        val cleanBvid = extractBvid(bvid) ?: bvid.trim()
        val subtitleUrls = mutableListOf<String>()

        // 尝试 WBI 签名接口
        try {
            val wbiKeys = getWbiKeys()
            if (wbiKeys != null) {
                val params = mapOf("bvid" to cleanBvid, "cid" to cid.toString())
                val signedQuery = signWbi(params, wbiKeys.first, wbiKeys.second)
                val wbiUrl = "https://api.bilibili.com/x/player/wbi/v2?$signedQuery"

                val reqBuilder = Request.Builder().url(wbiUrl)
                getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

                val response = client.newCall(reqBuilder.build()).execute()
                response.use { resp ->
                    val body = resp.body?.string() ?: ""
                    val json = gson.fromJson(body, JsonObject::class.java)
                    if (json.get("code")?.asInt == 0) {
                        val subtitleObj = json.getAsJsonObject("data")?.getAsJsonObject("subtitle")
                        val subtitlesArray = subtitleObj?.getAsJsonArray("subtitles")
                        subtitlesArray?.forEach { sub ->
                            val sObj = sub.asJsonObject
                            val subUrl = sObj.get("subtitle_url")?.asString ?: sObj.get("subtitle_url_v2")?.asString ?: ""
                            if (subUrl.isNotBlank()) subtitleUrls.add(subUrl)
                        }
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }

        // 常规备用接口
        if (subtitleUrls.isEmpty()) {
            try {
                val url = "https://api.bilibili.com/x/player/v2?bvid=$cleanBvid&cid=$cid"
                val reqBuilder = Request.Builder().url(url)
                getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

                val response = client.newCall(reqBuilder.build()).execute()
                response.use { resp ->
                    val body = resp.body?.string() ?: ""
                    val json = gson.fromJson(body, JsonObject::class.java)
                    if (json.get("code")?.asInt == 0) {
                        val subtitleObj = json.getAsJsonObject("data")?.getAsJsonObject("subtitle")
                        val subtitlesArray = subtitleObj?.getAsJsonArray("subtitles")
                        subtitlesArray?.forEach { sub ->
                            val sObj = sub.asJsonObject
                            val subUrl = sObj.get("subtitle_url")?.asString ?: ""
                            if (subUrl.isNotBlank()) subtitleUrls.add(subUrl)
                        }
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }

        // 下载字幕内容
        for (rawUrl in subtitleUrls) {
            val realUrl = if (rawUrl.startsWith("//")) "https:$rawUrl" else rawUrl
            try {
                val subReq = Request.Builder().url(realUrl).build()
                val subResp = client.newCall(subReq).execute()
                subResp.use { sResp ->
                    val subBody = sResp.body?.string() ?: return@use
                    val subJson = gson.fromJson(subBody, JsonObject::class.java)
                    val bodyArray = subJson.getAsJsonArray("body") ?: return@use

                    val list = mutableListOf<SubtitleItem>()
                    bodyArray.forEach { itemElem ->
                        val item = itemElem.asJsonObject
                        list.add(
                            SubtitleItem(
                                from = item.get("from")?.asDouble ?: 0.0,
                                to = item.get("to")?.asDouble ?: 0.0,
                                content = item.get("content")?.asString ?: ""
                            )
                        )
                    }
                    if (list.isNotEmpty()) {
                        return@withContext list
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }

        emptyList()
    }

    /**
     * 拉取视频热门评论区与 UP 主置顶时间轴笔记
     */
    suspend fun fetchTopComments(aid: Long): List<CommentItem> = withContext(Dispatchers.IO) {
        val result = mutableListOf<CommentItem>()
        try {
            val url = "https://api.bilibili.com/x/v2/reply/main?type=1&oid=$aid&mode=3&ps=10"
            val reqBuilder = Request.Builder().url(url)
            getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext emptyList()
                val json = gson.fromJson(body, JsonObject::class.java)
                if (json.get("code")?.asInt == 0) {
                    val data = json.getAsJsonObject("data")

                    val topObj = data?.getAsJsonObject("top")
                    val upperTop = topObj?.getAsJsonObject("upper")
                    if (upperTop != null) {
                        val member = upperTop.getAsJsonObject("member")?.get("uname")?.asString ?: "UP主"
                        val msg = upperTop.getAsJsonObject("content")?.get("message")?.asString ?: ""
                        val like = upperTop.get("like")?.asLong ?: 0L
                        if (msg.isNotBlank()) {
                            result.add(CommentItem(member, msg, like, isTop = true, isUp = true))
                        }
                    }

                    val replies = data?.getAsJsonArray("replies")
                    replies?.forEach { elem ->
                        val obj = elem.asJsonObject
                        val member = obj.getAsJsonObject("member")?.get("uname")?.asString ?: "热心观众"
                        val msg = obj.getAsJsonObject("content")?.get("message")?.asString ?: ""
                        val like = obj.get("like")?.asLong ?: 0L
                        if (msg.isNotBlank() && result.none { it.message == msg }) {
                            result.add(CommentItem(member, msg, like, isTop = false, isUp = false))
                        }
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        result
    }

    /**
     * 拉取全片弹幕并萃取高能时刻与观众高频反应
     */
    suspend fun fetchDanmakuHighlights(cid: Long): List<DanmakuHighlight> = withContext(Dispatchers.IO) {
        val result = mutableListOf<DanmakuHighlight>()
        try {
            val url = "https://api.bilibili.com/x/v1/dm/list.so?oid=$cid"
            val reqBuilder = Request.Builder().url(url)
            getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext emptyList()
                if (body.contains("<i")) {
                    val factory = XmlPullParserFactory.newInstance()
                    val parser = factory.newPullParser()
                    parser.setInput(StringReader(body))

                    val rawDanmaku = mutableListOf<Pair<Float, String>>()
                    var eventType = parser.eventType
                    var currentP = ""

                    while (eventType != XmlPullParser.END_DOCUMENT) {
                        if (eventType == XmlPullParser.START_TAG && parser.name == "d") {
                            currentP = parser.getAttributeValue(null, "p") ?: ""
                            val text = parser.nextText()
                            val timeSec = currentP.split(",").getOrNull(0)?.toFloatOrNull() ?: 0f
                            if (text.isNotBlank()) {
                                rawDanmaku.add(Pair(timeSec, text.trim()))
                            }
                        }
                        eventType = parser.next()
                    }

                    if (rawDanmaku.isNotEmpty()) {
                        val windowSize = 30
                        val maxTime = rawDanmaku.maxOf { it.first }.toInt()
                        val buckets = mutableMapOf<Int, MutableList<String>>()

                        rawDanmaku.forEach { (time, text) ->
                            val bucketIdx = (time / windowSize).toInt()
                            buckets.getOrPut(bucketIdx) { mutableListOf() }.add(text)
                        }

                        val sortedBuckets = buckets.entries.sortedByDescending { it.value.size }.take(5)
                        sortedBuckets.forEach { (bucketIdx, texts) ->
                            val startSec = bucketIdx * windowSize
                            val peakTimeStr = String.format("%02d:%02d", startSec / 60, startSec % 60)
                            val topText = texts.groupBy { it }.maxByOrNull { it.value.size }?.key ?: texts.first()
                            result.add(DanmakuHighlight(timeSec = startSec, text = topText, count = texts.size))
                        }
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        result
    }

    /**
     * 精准抽取全视频等距 5 帧关键画面拼图并转为 Base64 (供多模态视觉模型感知画面 PPT/代码/板书，避免冗余帧)
     */
    suspend fun fetchVideoshotSpriteBase64(aid: Long, cid: Long, bvid: String): String? = withContext(Dispatchers.IO) {
        try {
            val url = "https://api.bilibili.com/x/player/videoshot?aid=$aid&cid=$cid&index=1"
            val reqBuilder = Request.Builder().url(url)
            getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext null
                val json = gson.fromJson(body, JsonObject::class.java)

                if (json.get("code")?.asInt == 0) {
                    val data = json.getAsJsonObject("data") ?: return@withContext null
                    val imgXLen = data.get("img_x_len")?.asInt ?: 10
                    val imgYLen = data.get("img_y_len")?.asInt ?: 10
                    val imgXSize = data.get("img_x_size")?.asInt ?: 160
                    val imgYSize = data.get("img_y_size")?.asInt ?: 90
                    val imageArray = data.getAsJsonArray("image") ?: return@withContext null

                    val totalFramesPerSheet = imgXLen * imgYLen
                    val totalSheets = imageArray.size()
                    if (totalSheets == 0) return@withContext null

                    val totalFrames = totalFramesPerSheet * totalSheets
                    // 精准选取全视频等距 5 个关键帧索引 (覆盖 10%, 30%, 50%, 70%, 90% 进度)
                    val targetFrameIndices = listOf(
                        (totalFrames * 0.10).toInt().coerceIn(0, totalFrames - 1),
                        (totalFrames * 0.30).toInt().coerceIn(0, totalFrames - 1),
                        (totalFrames * 0.50).toInt().coerceIn(0, totalFrames - 1),
                        (totalFrames * 0.70).toInt().coerceIn(0, totalFrames - 1),
                        (totalFrames * 0.90).toInt().coerceIn(0, totalFrames - 1)
                    ).distinct()

                    // 缓存已下载的 Sprite 大图
                    val sheetBitmaps = mutableMapOf<Int, Bitmap>()
                    val croppedFrames = mutableListOf<Bitmap>()

                    for (frameIdx in targetFrameIndices) {
                        val sheetIdx = (frameIdx / totalFramesPerSheet).coerceIn(0, totalSheets - 1)
                        val localIdx = frameIdx % totalFramesPerSheet
                        val col = localIdx % imgXLen
                        val row = localIdx / imgXLen
                        val cropX = (col * imgXSize).coerceAtLeast(0)
                        val cropY = (row * imgYSize).coerceAtLeast(0)

                        val sheetBitmap = sheetBitmaps.getOrPut(sheetIdx) {
                            val rawUrl = imageArray.get(sheetIdx).asString
                            val realUrl = if (rawUrl.startsWith("//")) "https:$rawUrl" else rawUrl
                            val imgReq = Request.Builder().url(realUrl).build()
                            val imgResp = client.newCall(imgReq).execute()
                            imgResp.use { iResp ->
                                val bytes = iResp.body?.bytes()
                                if (bytes != null && bytes.isNotEmpty()) {
                                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                                } else null
                            } ?: return@withContext null
                        }

                        if (cropX + imgXSize <= sheetBitmap.width && cropY + imgYSize <= sheetBitmap.height) {
                            val subBitmap = Bitmap.createBitmap(sheetBitmap, cropX, cropY, imgXSize, imgYSize)
                            croppedFrames.add(subBitmap)
                        }
                    }

                    if (croppedFrames.isNotEmpty()) {
                        // 将 5 帧横向拼接为单张轻量 5 帧胶片图 (例如 800 x 90)
                        val frameCount = croppedFrames.size
                        val stitchedWidth = imgXSize * frameCount
                        val stitchedHeight = imgYSize
                        val stitchedBitmap = Bitmap.createBitmap(stitchedWidth, stitchedHeight, Bitmap.Config.RGB_565)
                        val canvas = Canvas(stitchedBitmap)

                        for (i in 0 until frameCount) {
                            canvas.drawBitmap(croppedFrames[i], (i * imgXSize).toFloat(), 0f, null)
                        }

                        val outputStream = ByteArrayOutputStream()
                        stitchedBitmap.compress(Bitmap.CompressFormat.JPEG, 85, outputStream)
                        val stitchedBytes = outputStream.toByteArray()
                        return@withContext Base64.encodeToString(stitchedBytes, Base64.NO_WRAP)
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        null
    }

    /**
     * 拉取【稍后再看】列表
     */
    suspend fun fetchToviewList(): List<CandidateVideo> = withContext(Dispatchers.IO) {
        try {
            val url = "https://api.bilibili.com/x/v2/history/toview"
            val reqBuilder = Request.Builder().url(url)
            getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext emptyList()
                val json = gson.fromJson(body, JsonObject::class.java)

                if (json.get("code")?.asInt == 0) {
                    val list = mutableListOf<CandidateVideo>()
                    json.getAsJsonObject("data")?.getAsJsonArray("list")?.forEach { elem ->
                        val obj = elem.asJsonObject
                        list.add(
                            CandidateVideo(
                                bvid = obj.get("bvid")?.asString ?: "",
                                title = obj.get("title")?.asString ?: "",
                                pic = obj.get("pic")?.asString ?: "",
                                ownerName = obj.getAsJsonObject("owner")?.get("name")?.asString ?: "",
                                duration = obj.get("duration")?.asLong ?: 0L,
                                source = "稍后再看"
                            )
                        )
                    }
                    return@withContext list
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        emptyList()
    }

    /**
     * 【新功能】拉取无限个性化推荐视频流 (带全网热门与官方知识高分榜双重自动兜底)
     */
    suspend fun fetchRcmdFeed(freshIdx: Int = 1): List<CandidateVideo> = withContext(Dispatchers.IO) {
        val result = mutableListOf<CandidateVideo>()
        try {
            val url = "https://api.bilibili.com/x/web-interface/index/top/feed/rcmd?fresh_idx=$freshIdx&feed_version=V8&fresh_type=4&ps=20"
            val reqBuilder = Request.Builder().url(url)
            getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: ""
                val json = gson.fromJson(body, JsonObject::class.java)

                if (json.get("code")?.asInt == 0) {
                    val items = json.getAsJsonObject("data")?.getAsJsonArray("item")
                    items?.forEach { elem ->
                        val obj = elem.asJsonObject
                        val bvid = obj.get("bvid")?.asString ?: ""
                        val title = obj.get("title")?.asString ?: ""
                        val pic = obj.get("pic")?.asString ?: ""
                        val owner = obj.getAsJsonObject("owner")?.get("name")?.asString ?: obj.get("author")?.asString ?: ""
                        val duration = obj.get("duration")?.asLong ?: 0L
                        if (bvid.isNotEmpty() && title.isNotEmpty()) {
                            result.add(CandidateVideo(bvid, title, pic, owner, duration, source = "个性化推荐流"))
                        }
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }

        // 若个性化推荐流为空 (例如未登录状态或被B站频控)，无缝降级兜底至全站热门与官方知识精选榜
        if (result.isEmpty()) {
            val popular = fetchPopularList(freshIdx)
            if (popular.isNotEmpty()) {
                return@withContext popular
            }
            val ranking = fetchKnowledgeRanking(36)
            if (ranking.isNotEmpty()) {
                return@withContext ranking
            }
        }

        result
    }

    /**
     * 【新功能】拉取各专业知识分区排行榜 (支持 知识/科技/科普/财经/计算机 等各大分区)
     */
    suspend fun fetchKnowledgeRanking(rid: Int = 36): List<CandidateVideo> = withContext(Dispatchers.IO) {
        try {
            val url = "https://api.bilibili.com/x/web-interface/ranking/v2?rid=$rid&type=all"
            val reqBuilder = Request.Builder().url(url)
            getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext emptyList()
                val json = gson.fromJson(body, JsonObject::class.java)

                if (json.get("code")?.asInt == 0) {
                    val list = mutableListOf<CandidateVideo>()
                    json.getAsJsonObject("data")?.getAsJsonArray("list")?.forEach { elem ->
                        val obj = elem.asJsonObject
                        val bvid = obj.get("bvid")?.asString ?: ""
                        val title = obj.get("title")?.asString ?: ""
                        val pic = obj.get("pic")?.asString ?: ""
                        val owner = obj.getAsJsonObject("owner")?.get("name")?.asString ?: ""
                        val duration = obj.get("duration")?.asLong ?: 0L
                        if (bvid.isNotEmpty()) {
                            list.add(CandidateVideo(bvid, title, pic, owner, duration, source = "知识榜单"))
                        }
                    }
                    return@withContext list
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        emptyList()
    }

    /**
     * 拉取全站热门推荐视频流 (支持不断分页翻页)
     */
    suspend fun fetchPopularList(page: Int = 1): List<CandidateVideo> = withContext(Dispatchers.IO) {
        try {
            val url = "https://api.bilibili.com/x/web-interface/popular?ps=20&pn=$page"
            val reqBuilder = Request.Builder().url(url)
            getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext emptyList()
                val json = gson.fromJson(body, JsonObject::class.java)

                if (json.get("code")?.asInt == 0) {
                    val list = mutableListOf<CandidateVideo>()
                    json.getAsJsonObject("data")?.getAsJsonArray("list")?.forEach { elem ->
                        val obj = elem.asJsonObject
                        list.add(
                            CandidateVideo(
                                bvid = obj.get("bvid")?.asString ?: "",
                                title = obj.get("title")?.asString ?: "",
                                pic = obj.get("pic")?.asString ?: "",
                                ownerName = obj.getAsJsonObject("owner")?.get("name")?.asString ?: "",
                                duration = obj.get("duration")?.asLong ?: 0L,
                                source = "热门推荐"
                            )
                        )
                    }
                    return@withContext list
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        emptyList()
    }

    /**
     * 校验当前登录凭证并拉取用户头像、用户名、硬币数
     */
    suspend fun fetchNavUserInfo(): Result<UserProfile> = withContext(Dispatchers.IO) {
        try {
            val url = "https://api.bilibili.com/x/web-interface/nav"
            val reqBuilder = Request.Builder().url(url)
            getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext Result.failure(Exception("空响应"))
                val json = gson.fromJson(body, JsonObject::class.java)

                if (json.get("code")?.asInt == 0) {
                    val data = json.getAsJsonObject("data")
                    val isLogin = data.get("isLogin")?.asBoolean ?: false
                    if (isLogin) {
                        val profile = UserProfile(
                            uid = data.get("mid")?.asLong ?: 0L,
                            uname = data.get("uname")?.asString ?: "",
                            avatar = data.get("face")?.asString ?: "",
                            level = data.getAsJsonObject("level_info")?.get("current_level")?.asInt ?: 0,
                            vipType = data.get("vipType")?.asInt ?: 0,
                            vipStatus = data.get("vipStatus")?.asInt ?: 0,
                            coins = data.get("money")?.asDouble ?: 0.0,
                            isLogin = true
                        )
                        Result.success(profile)
                    } else {
                        Result.failure(Exception("未登录或 Cookie 已过期"))
                    }
                } else {
                    Result.failure(Exception(json.get("message")?.asString ?: "校验失败"))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun fetchWatchHistory(): Result<List<CandidateVideo>> = withContext(Dispatchers.IO) {
        readVideoList(
            "https://api.bilibili.com/x/web-interface/history/cursor?max=0&view_at=0&business=archive&ps=30",
            "观看历史"
        ) { data -> data.getAsJsonArray("list") }
    }

    suspend fun removeFromToview(bvid: String): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("请先登录 B 站"))
        val aid = fetchVideoDetail(bvid).getOrElse { return@withContext Result.failure(it) }.aid
        postCsrf(
            "https://api.bilibili.com/x/v2/history/toview/del",
            FormBody.Builder().add("aid", aid.toString()).add("csrf", csrf).build()
        )
    }

    suspend fun clearToview(): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("请先登录 B 站"))
        postCsrf(
            "https://api.bilibili.com/x/v2/history/toview/clear",
            FormBody.Builder().add("csrf", csrf).build()
        )
    }

    suspend fun fetchFavoriteFolders(): Result<List<FavoriteFolder>> = withContext(Dispatchers.IO) {
        val uid = preferences.getDedeUserId()
        if (uid.isBlank()) return@withContext Result.failure(Exception("请先登录 B 站"))
        runCatching {
            val json = getJson("https://api.bilibili.com/x/v3/fav/folder/created/list-all?up_mid=$uid")
            requireApiSuccess(json)
            json.getAsJsonObject("data")?.getAsJsonArray("list")?.map { element ->
                val item = element.asJsonObject
                FavoriteFolder(
                    id = item.get("id")?.asLong ?: 0,
                    title = item.get("title")?.asString.orEmpty(),
                    mediaCount = item.get("media_count")?.asInt ?: 0
                )
            }?.filter { it.id > 0 } ?: emptyList()
        }
    }

    suspend fun fetchFavoriteVideos(mediaId: Long): Result<List<CandidateVideo>> = withContext(Dispatchers.IO) {
        readVideoList(
            "https://api.bilibili.com/x/v3/fav/resource/list?media_id=$mediaId&pn=1&ps=40&order=mtime&type=0",
            "收藏夹"
        ) { data -> data.getAsJsonArray("medias") }
    }

    suspend fun createFavoriteFolder(title: String): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("请先登录 B 站"))
        if (title.isBlank()) return@withContext Result.failure(Exception("收藏夹名称不能为空"))
        postCsrf(
            "https://api.bilibili.com/x/v3/fav/folder/add",
            FormBody.Builder().add("title", title.trim()).add("intro", "").add("privacy", "0").add("csrf", csrf).build()
        )
    }

    suspend fun renameFavoriteFolder(mediaId: Long, title: String): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("请先登录 B 站"))
        if (title.isBlank()) return@withContext Result.failure(Exception("收藏夹名称不能为空"))
        postCsrf(
            "https://api.bilibili.com/x/v3/fav/folder/edit",
            FormBody.Builder().add("media_id", mediaId.toString()).add("title", title.trim()).add("intro", "").add("privacy", "0").add("csrf", csrf).build()
        )
    }

    suspend fun deleteFavoriteFolder(mediaId: Long): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("请先登录 B 站"))
        postCsrf(
            "https://api.bilibili.com/x/v3/fav/folder/del",
            FormBody.Builder().add("media_ids", mediaId.toString()).add("csrf", csrf).build()
        )
    }

    suspend fun fetchDynamicVideos(): Result<List<CandidateVideo>> = withContext(Dispatchers.IO) {
        runCatching {
            val json = getJson("https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all?type=video")
            requireApiSuccess(json)
            val result = mutableListOf<CandidateVideo>()
            json.getAsJsonObject("data")?.getAsJsonArray("items")?.forEach { element ->
                val item = element.asJsonObject
                val modules = item.getAsJsonObject("modules")
                val author = modules?.getAsJsonObject("module_author")?.get("name")?.asString.orEmpty()
                val archive = modules?.getAsJsonObject("module_dynamic")
                    ?.getAsJsonObject("major")?.getAsJsonObject("archive")
                if (archive != null) {
                    val bvid = archive.get("bvid")?.asString.orEmpty()
                    if (bvid.isNotBlank()) {
                        result += CandidateVideo(
                            bvid = bvid,
                            title = archive.get("title")?.asString.orEmpty(),
                            pic = archive.get("cover")?.asString.orEmpty(),
                            ownerName = author,
                            duration = parseDurationText(archive.get("duration_text")?.asString.orEmpty()),
                            source = "关注动态"
                        )
                    }
                }
            }
            result
        }
    }

    suspend fun fetchPrivateConversations(): Result<List<BiliConversation>> = withContext(Dispatchers.IO) {
        if (!preferences.isBiliLoggedIn()) return@withContext Result.failure(Exception("请先登录 B 站"))
        runCatching {
            val json = getJson("https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions?session_type=1&group_fold=1&unfollow_fold=0&sort_rule=2&build=0&mobi_app=web")
            requireApiSuccess(json)
            val conversations = json.getAsJsonObject("data")?.getAsJsonArray("session_list")?.mapNotNull { element ->
                val item = element.asJsonObject
                val talkerId = item.get("talker_id")?.asLong ?: 0
                if (talkerId <= 0) null else BiliConversation(
                    talkerId = talkerId,
                    unreadCount = item.get("unread_count")?.asInt ?: 0,
                    lastMessage = parseMessageContent(item.getAsJsonObject("last_msg")?.get("content")?.asString.orEmpty()),
                    lastTimestamp = item.getAsJsonObject("last_msg")?.get("timestamp")?.asLong ?: 0
                )
            } ?: emptyList()
            conversations.map { conversation ->
                runCatching {
                    val cardJson = getJson("https://api.bilibili.com/x/web-interface/card?mid=${conversation.talkerId}")
                    requireApiSuccess(cardJson)
                    val card = cardJson.getAsJsonObject("data")?.getAsJsonObject("card")
                    conversation.copy(
                        talkerName = card?.get("name")?.asString.orEmpty(),
                        avatarUrl = card?.get("face")?.asString.orEmpty()
                    )
                }.getOrDefault(conversation)
            }
        }
    }

    suspend fun fetchPrivateMessages(talkerId: Long): Result<List<BiliPrivateMessage>> = withContext(Dispatchers.IO) {
        if (!preferences.isBiliLoggedIn()) return@withContext Result.failure(Exception("请先登录 B 站"))
        runCatching {
            val url = "https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs?talker_id=$talkerId&session_type=1&size=50&sender_device_id=1&build=0&mobi_app=web"
            val json = getJson(url)
            requireApiSuccess(json)
            json.getAsJsonObject("data")?.getAsJsonArray("messages")?.map { element ->
                val item = element.asJsonObject
                BiliPrivateMessage(
                    sequence = item.get("msg_seqno")?.asLong ?: item.get("msg_key")?.asLong ?: 0,
                    senderUid = item.get("sender_uid")?.asLong ?: 0,
                    receiverId = item.get("receiver_id")?.asLong ?: 0,
                    content = parseMessageContent(item.get("content")?.asString.orEmpty()),
                    timestamp = item.get("timestamp")?.asLong ?: 0
                )
            }?.sortedBy { it.timestamp } ?: emptyList()
        }
    }

    suspend fun sendPrivateMessage(talkerId: Long, message: String): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        val sender = preferences.getDedeUserId()
        if (csrf.isBlank() || sender.isBlank()) return@withContext Result.failure(Exception("请先登录 B 站"))
        if (message.isBlank()) return@withContext Result.failure(Exception("消息不能为空"))
        val now = System.currentTimeMillis() / 1000
        val contentJson = JsonObject().apply { addProperty("content", message.trim()) }.toString()
        val form = FormBody.Builder()
            .add("msg[sender_uid]", sender)
            .add("msg[receiver_id]", talkerId.toString())
            .add("msg[receiver_type]", "1")
            .add("msg[msg_type]", "1")
            .add("msg[msg_status]", "0")
            .add("msg[content]", contentJson)
            .add("msg[timestamp]", now.toString())
            .add("msg[new_face_version]", "0")
            .add("msg[dev_id]", guestBuvid3)
            .add("build", "0")
            .add("mobi_app", "web")
            .add("csrf_token", csrf)
            .add("csrf", csrf)
            .build()
        postCsrf("https://api.vc.bilibili.com/web_im/v1/web_im/send_msg", form)
    }

    suspend fun fetchFollowingUps(page: Int = 1): Result<List<UpProfile>> = withContext(Dispatchers.IO) {
        val uid = preferences.getDedeUserId()
        if (uid.isBlank()) return@withContext Result.failure(Exception("请先登录 B 站"))
        runCatching {
            val json = getJson("https://api.bilibili.com/x/relation/followings?vmid=$uid&pn=$page&ps=50&order=desc&order_type=attention")
            requireApiSuccess(json)
            json.getAsJsonObject("data")?.getAsJsonArray("list")?.map { element ->
                val item = element.asJsonObject
                UpProfile(
                    mid = item.get("mid")?.asLong ?: 0,
                    name = item.get("uname")?.asString.orEmpty(),
                    face = item.get("face")?.asString.orEmpty(),
                    sign = item.get("sign")?.asString.orEmpty()
                )
            }?.filter { it.mid > 0 } ?: emptyList()
        }
    }

    suspend fun fetchUpVideos(mid: Long): Result<List<CandidateVideo>> = withContext(Dispatchers.IO) {
        val keys = getWbiKeys() ?: return@withContext Result.failure(Exception("无法获取 B 站 WBI 签名"))
        val query = signWbi(mapOf("mid" to mid.toString(), "pn" to "1", "ps" to "30", "order" to "pubdate"), keys.first, keys.second)
        readVideoList(
            "https://api.bilibili.com/x/space/wbi/arc/search?$query",
            "UP 视频"
        ) { data -> data.getAsJsonObject("list")?.getAsJsonArray("vlist") }
    }

    suspend fun searchVideos(keyword: String): Result<List<CandidateVideo>> = withContext(Dispatchers.IO) {
        if (keyword.isBlank()) return@withContext Result.success(emptyList())
        val keys = getWbiKeys() ?: return@withContext Result.failure(Exception("无法获取 B 站 WBI 签名"))
        val query = signWbi(
            mapOf("search_type" to "video", "keyword" to keyword.trim(), "page" to "1", "page_size" to "12"),
            keys.first,
            keys.second
        )
        readVideoList(
            "https://api.bilibili.com/x/web-interface/wbi/search/type?$query",
            "B 站搜索"
        ) { data -> data.getAsJsonArray("result") }
    }

    suspend fun changeFollow(mid: Long, follow: Boolean): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("请先登录 B 站"))
        postCsrf(
            "https://api.bilibili.com/x/relation/modify",
            FormBody.Builder()
                .add("fid", mid.toString())
                .add("act", if (follow) "1" else "2")
                .add("re_src", "11")
                .add("csrf", csrf)
                .build()
        )
    }

    private suspend fun readVideoList(
        url: String,
        source: String,
        array: (JsonObject) -> com.google.gson.JsonArray?
    ): Result<List<CandidateVideo>> = withContext(Dispatchers.IO) {
        runCatching {
            val json = getJson(url)
            requireApiSuccess(json)
            array(json.getAsJsonObject("data") ?: JsonObject())?.mapNotNull { element ->
                val item = element.asJsonObject
                val history = item.getAsJsonObject("history")
                val bvid = item.get("bvid")?.asString ?: history?.get("bvid")?.asString.orEmpty()
                if (bvid.isBlank()) null else CandidateVideo(
                    bvid = bvid,
                    title = item.get("title")?.asString.orEmpty(),
                    pic = item.get("cover")?.asString ?: item.get("pic")?.asString.orEmpty(),
                    ownerName = item.get("author_name")?.asString
                        ?: item.get("author")?.asString
                        ?: item.getAsJsonObject("upper")?.get("name")?.asString
                        ?: item.getAsJsonObject("owner")?.get("name")?.asString.orEmpty(),
                    duration = runCatching { item.get("duration")?.asLong ?: 0 }.getOrElse {
                        parseDurationText(item.get("duration")?.asString.orEmpty())
                    },
                    source = source
                )
            } ?: emptyList()
        }
    }

    private fun getJson(url: String): JsonObject {
        val builder = Request.Builder().url(url).get()
        getBaseHeaders().forEach { (key, value) -> builder.addHeader(key, value) }
        client.newCall(builder.build()).execute().use { response ->
            if (!response.isSuccessful) throw Exception("网络请求失败: HTTP ${response.code}")
            return gson.fromJson(response.body?.string().orEmpty(), JsonObject::class.java)
                ?: throw Exception("服务器返回空数据")
        }
    }

    private fun requireApiSuccess(json: JsonObject) {
        if (json.get("code")?.asInt != 0) throw Exception(json.get("message")?.asString ?: "B 站接口请求失败")
    }

    private fun postCsrf(url: String, body: FormBody): Result<Boolean> = runCatching {
        val builder = Request.Builder().url(url).post(body)
        getBaseHeaders().forEach { (key, value) -> builder.addHeader(key, value) }
        client.newCall(builder.build()).execute().use { response ->
            if (!response.isSuccessful) throw Exception("网络请求失败: HTTP ${response.code}")
            val json = gson.fromJson(response.body?.string().orEmpty(), JsonObject::class.java)
            requireApiSuccess(json)
            true
        }
    }

    private fun parseDurationText(value: String): Long {
        val parts = value.split(":").mapNotNull(String::toLongOrNull)
        return when (parts.size) {
            3 -> parts[0] * 3600 + parts[1] * 60 + parts[2]
            2 -> parts[0] * 60 + parts[1]
            1 -> parts[0]
            else -> 0
        }
    }

    private fun parseMessageContent(raw: String): String = runCatching {
        gson.fromJson(raw, JsonObject::class.java)?.get("content")?.asString ?: raw
    }.getOrDefault(raw)

    // ==================== Bilibili 拟人交互操作 ====================

    suspend fun sendLike(bvid: String, like: Int = 1): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("未登录 B站，无法点赞"))

        val form = FormBody.Builder()
            .add("bvid", bvid)
            .add("like", like.toString())
            .add("csrf", csrf)
            .build()

        val reqBuilder = Request.Builder()
            .url("https://api.bilibili.com/x/web-interface/archive/like")
            .post(form)
        getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

        try {
            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: ""
                val json = gson.fromJson(body, JsonObject::class.java)
                if (json.get("code")?.asInt == 0) {
                    Result.success(true)
                } else {
                    Result.failure(Exception(json.get("message")?.asString ?: "点赞失败"))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun sendCoin(bvid: String, multiply: Int = 1): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("未登录 B站，无法投币"))

        val form = FormBody.Builder()
            .add("bvid", bvid)
            .add("multiply", multiply.toString())
            .add("select_like", "1")
            .add("csrf", csrf)
            .build()

        val reqBuilder = Request.Builder()
            .url("https://api.bilibili.com/x/web-interface/coin/add")
            .post(form)
        getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

        try {
            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: ""
                val json = gson.fromJson(body, JsonObject::class.java)
                if (json.get("code")?.asInt == 0) {
                    Result.success(true)
                } else {
                    Result.failure(Exception(json.get("message")?.asString ?: "投币失败"))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun sendFavorite(aid: Long, add: Boolean = true): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("未登录 B 站，无法收藏"))

        val form = FormBody.Builder()
            .add("rid", aid.toString())
            .add("type", "2")
            .add("add_media", if (add) "1" else "0")
            .add("csrf", csrf)
            .build()
        val requestBuilder = Request.Builder()
            .url("https://api.bilibili.com/x/v3/fav/resource/deal")
            .post(form)
        getBaseHeaders().forEach { (key, value) -> requestBuilder.addHeader(key, value) }

        try {
            client.newCall(requestBuilder.build()).execute().use { response ->
                val json = gson.fromJson(response.body?.string().orEmpty(), JsonObject::class.java)
                if (json.get("code")?.asInt == 0) {
                    Result.success(true)
                } else {
                    Result.failure(Exception(json.get("message")?.asString ?: "收藏操作失败"))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun sendComment(aid: Long, message: String): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("未登录 B站，无法发表评论"))

        val form = FormBody.Builder()
            .add("type", "1")
            .add("oid", aid.toString())
            .add("message", message)
            .add("csrf", csrf)
            .build()

        val reqBuilder = Request.Builder()
            .url("https://api.bilibili.com/x/v2/reply/add")
            .post(form)
        getBaseHeaders().forEach { (k, v) -> reqBuilder.addHeader(k, v) }

        try {
            val response = client.newCall(reqBuilder.build()).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: ""
                val json = gson.fromJson(body, JsonObject::class.java)
                if (json.get("code")?.asInt == 0) {
                    Result.success(true)
                } else {
                    Result.failure(Exception(json.get("message")?.asString ?: "发评失败"))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun sendDanmaku(cid: Long, message: String, progressMs: Int = 1000): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("未登录 B 站，无法发送弹幕"))
        if (cid <= 0 || message.isBlank()) return@withContext Result.failure(Exception("弹幕参数无效"))
        val form = FormBody.Builder()
            .add("type", "1")
            .add("oid", cid.toString())
            .add("msg", message.trim())
            .add("progress", progressMs.coerceAtLeast(0).toString())
            .add("color", "16777215")
            .add("fontsize", "25")
            .add("pool", "0")
            .add("mode", "1")
            .add("rnd", (System.currentTimeMillis() / 1000).toString())
            .add("csrf", csrf)
            .build()
        postCsrf("https://api.bilibili.com/x/v2/dm/post", form)
    }

    suspend fun publishTextDynamic(content: String): Result<Boolean> = withContext(Dispatchers.IO) {
        val csrf = preferences.getBiliJct()
        val clean = content.trim()
        if (csrf.isBlank()) return@withContext Result.failure(Exception("未登录 B 站，无法发布动态"))
        if (clean.isBlank()) return@withContext Result.failure(Exception("动态内容不能为空"))
        runCatching {
            val payload = JsonObject().apply {
                add("dyn_req", JsonObject().apply {
                    add("content", JsonObject().apply {
                        add("contents", com.google.gson.JsonArray().apply {
                            add(JsonObject().apply {
                                addProperty("raw_text", clean)
                                addProperty("type", 1)
                                addProperty("biz_id", "")
                            })
                        })
                    })
                    addProperty("scene", 1)
                })
            }
            val requestBody = payload.toString().toRequestBody("application/json; charset=utf-8".toMediaType())
            val requestBuilder = Request.Builder()
                .url("https://api.bilibili.com/x/dynamic/feed/create/dyn?csrf=$csrf")
                .post(requestBody)
            getBaseHeaders().forEach { (key, value) -> requestBuilder.addHeader(key, value) }
            client.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful) throw Exception("网络请求失败: HTTP ${response.code}")
                val json = gson.fromJson(response.body?.string().orEmpty(), JsonObject::class.java)
                requireApiSuccess(json)
                true
            }
        }
    }

    suspend fun generateQrCode(): Result<QrCodeSession> = withContext(Dispatchers.IO) {
        try {
            val url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?_=${System.currentTimeMillis()}"
            val request = Request.Builder().url(url).build()
            val response = client.newCall(request).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext Result.failure(Exception("空响应"))
                val json = gson.fromJson(body, JsonObject::class.java)

                if (json.get("code")?.asInt == 0) {
                    val data = json.getAsJsonObject("data")
                    val session = QrCodeSession(
                        qrcodeKey = data.get("qrcode_key")?.asString ?: "",
                        url = data.get("url")?.asString ?: "",
                        status = "pending",
                        message = "请使用 B站手机客户端 扫描二维码"
                    )
                    Result.success(session)
                } else {
                    Result.failure(Exception(json.get("message")?.asString ?: "生成二维码失败"))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun pollQrCode(qrcodeKey: String): Result<Pair<String, Map<String, String>?>> = withContext(Dispatchers.IO) {
        try {
            val url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key=$qrcodeKey&_=${System.currentTimeMillis()}"
            val request = Request.Builder().url(url).build()
            val response = client.newCall(request).execute()
            response.use { resp ->
                val body = resp.body?.string() ?: return@withContext Result.failure(Exception("空响应"))
                val json = gson.fromJson(body, JsonObject::class.java)
                val code = json.getAsJsonObject("data")?.get("code")?.asInt ?: -1

                when (code) {
                    0 -> {
                        val cookies = mutableMapOf<String, String>()
                        resp.headers("Set-Cookie").forEach { header ->
                            val parsed = BiliCrypto.parseCookieString(header.split(";")[0])
                            cookies.putAll(parsed)
                        }
                        Result.success(Pair("SUCCESS", cookies))
                    }
                    86101 -> Result.success(Pair("WAITING", null))
                    86090 -> Result.success(Pair("SCANNED", null))
                    86038 -> Result.success(Pair("TIMEOUT", null))
                    else -> Result.success(Pair("PENDING", null))
                }
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
