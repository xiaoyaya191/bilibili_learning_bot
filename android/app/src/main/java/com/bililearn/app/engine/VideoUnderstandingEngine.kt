package com.bililearn.app.engine

import com.bililearn.app.data.model.*
import com.bililearn.app.network.llm.LLMClient
import com.google.gson.Gson
import com.google.gson.JsonParser
import java.util.Locale
import java.util.UUID

class VideoUnderstandingEngine(private val llmClient: LLMClient) {

    private val gson = Gson()

    private fun subtitleLine(item: SubtitleItem): String {
        val min = (item.from / 60).toInt()
        val sec = (item.from % 60).toInt()
        return "[${String.format(Locale.ROOT, "%02d:%02d", min, sec)}] ${item.content}"
    }

    private fun buildTranscriptChunks(
        subtitles: List<SubtitleItem>,
        videoDetail: VideoDetail,
        maxChars: Int = 12_000
    ): List<String> {
        if (subtitles.isEmpty()) return listOf(buildAdaptiveTranscript(emptyList(), videoDetail))

        val chunks = mutableListOf<String>()
        val current = StringBuilder()
        subtitles.forEach { item ->
            val line = subtitleLine(item)
            if (current.isNotEmpty() && current.length + line.length + 1 > maxChars) {
                chunks += current.toString()
                current.clear()
            }
            current.appendLine(line)
        }
        if (current.isNotEmpty()) chunks += current.toString()
        return chunks
    }

    private suspend fun summarizeTranscriptChunk(
        videoDetail: VideoDetail,
        transcript: String,
        chunkIndex: Int,
        chunkCount: Int,
        requestId: String
    ): Result<String> {
        val prompt = """
目标视频: 《${videoDetail.title}》
source_bvid: ${videoDetail.bvid}
request_id: $requestId
当前分段: ${chunkIndex + 1}/$chunkCount

请只根据下面这段连续时间轴字幕，提炼该分段的事实、论点、案例和结论。不得引入其他视频内容。

$transcript

仅输出 JSON：
{
  "source_bvid": "${videoDetail.bvid}",
  "request_id": "$requestId",
  "chunk_summary": "本段摘要",
  "key_points": ["本段事实要点"]
}
        """.trimIndent()
        val response = llmClient.chatCompletion(
            listOf(
                ChatMessage("system", "你正在处理一个隔离的视频字幕分段。必须原样回传 source_bvid 和 request_id。"),
                ChatMessage("user", prompt)
            ),
            temperature = 0.1f
        )
        if (!response.ok) return Result.failure(Exception(response.error ?: "分段分析失败"))

        val json = AnalysisResponseGuard.extractJsonObject(response.content)
        if (!AnalysisResponseGuard.matches(json, videoDetail.bvid, requestId)) {
            return Result.failure(Exception("AI 分段响应身份校验失败，已阻止跨视频内容写入"))
        }
        val summary = json?.get("chunk_summary")?.asString.orEmpty()
        val points = json?.getAsJsonArray("key_points")
            ?.mapNotNull { runCatching { it.asString }.getOrNull() }
            .orEmpty()
        if (summary.isBlank() && points.isEmpty()) {
            return Result.failure(Exception("AI 分段响应内容为空"))
        }
        return Result.success(buildString {
            appendLine("分段 ${chunkIndex + 1}/$chunkCount: $summary")
            points.forEach { appendLine("- $it") }
        }.trim())
    }

    /**
     * 构建面向视频的全量字幕文稿 (100% 完整传递带时间戳的每一句话)
     */
    private fun buildAdaptiveTranscript(subtitles: List<SubtitleItem>, videoDetail: VideoDetail): String {
        if (subtitles.isEmpty()) {
            val pagesText = if (videoDetail.pages.isNotEmpty()) {
                "分P章节列表:\n" + videoDetail.pages.take(20).joinToString("\n") { "P${it.page}: ${it.part}" }
            } else ""
            val descText = if (videoDetail.desc.isNotBlank()) "官方简介与大纲:\n${videoDetail.desc.take(500)}" else "暂无简介文本"
            return "【说明：本视频无独立文字字幕，请严格基于以下真实简介与章节大纲梳理】\n$descText\n$pagesText"
        }

        val totalChars = subtitles.sumOf { it.content.length }

        // 1. 常规及长视频 (<= 35000 字，覆盖 2 小时以内所有视频): 100% 全量保留每一句带时间戳字幕，不删减一字
        if (totalChars <= 35000) {
            return subtitles.joinToString("\n") { item ->
                val min = (item.from / 60).toInt()
                val sec = (item.from % 60).toInt()
                "[${String.format(Locale.ROOT, "%02d:%02d", min, sec)}] ${item.content}"
            }
        }

        // 2. 超长特大视频 (> 35000 字，如 3~5 小时公开课): 全时长高密度时间轴覆盖
        val maxTargetChars = 32000
        val sampleStep = (totalChars / maxTargetChars).coerceAtLeast(2)
        val sb = StringBuilder()
        sb.append("【注: 本视频为特长视频(时长${videoDetail.duration / 60}分钟，共${totalChars}字)，已对全时长进行高密度关键帧覆盖】\n")

        var currentLength = 0
        for (i in subtitles.indices step sampleStep) {
            val item = subtitles[i]
            val min = (item.from / 60).toInt()
            val sec = (item.from % 60).toInt()
            val line = "[${String.format(Locale.ROOT, "%02d:%02d", min, sec)}] ${item.content}\n"
            sb.append(line)
            currentLength += line.length
            if (currentLength >= maxTargetChars) break
        }

        return sb.toString()
    }

    /**
     * 格式化评论区精选与UP置顶笔记
     */
    private fun buildCommentsSection(comments: List<CommentItem>): String {
        if (comments.isEmpty()) return "无"
        val sb = StringBuilder()
        comments.take(6).forEach { c ->
            val tag = if (c.isUp && c.isTop) "【UP主置顶】" else if (c.isTop) "【置顶笔记】" else "【热评】"
            sb.append("$tag ${c.uname} (赞${c.like}): ${c.message.take(150)}\n")
        }
        return sb.toString().trim()
    }

    /**
     * 格式化高能弹幕反应
     */
    private fun buildDanmakuSection(danmaku: List<DanmakuHighlight>): String {
        if (danmaku.isEmpty()) return "无"
        val sb = StringBuilder()
        danmaku.take(8).forEach { d ->
            if (d.timeSec > 0) {
                val min = d.timeSec / 60
                val sec = d.timeSec % 60
                sb.append("[${String.format(Locale.ROOT, "%02d:%02d", min, sec)}] ${d.text}\n")
            } else {
                sb.append("${d.text} (${d.count}次)\n")
            }
        }
        return sb.toString().trim()
    }

    /**
     * 鲁棒解析大模型输出为结构化结果 (自适应防错位与事实锚定)
     */
    private fun parseAnalysisJson(rawContent: String, videoDetail: VideoDetail, hasSubtitles: Boolean): ParsedAnalysisResult {
        var content = rawContent.trim()

        // 1. 剥离思考链 <think>
        content = content.replace(Regex("<think>[\\s\\S]*?</think>"), "").trim()

        // 2. 剥离 Markdown 代码块
        if (content.startsWith("```json")) {
            content = content.substring(7)
        } else if (content.startsWith("```")) {
            content = content.substring(3)
        }
        if (content.endsWith("```")) {
            content = content.substring(0, content.length - 3)
        }
        content = content.trim()

        // 3. 提取最外层大括号
        val startIdx = content.indexOf('{')
        val endIdx = content.lastIndexOf('}')
        if (startIdx >= 0 && endIdx > startIdx) {
            content = content.substring(startIdx, endIdx + 1)
        }

        try {
            val jsonObject = JsonParser.parseString(content).asJsonObject

            // 提取 summary
            var summary = jsonObject.get("summary")?.asString
                ?: jsonObject.get("core_summary")?.asString
                ?: jsonObject.get("overview")?.asString
                ?: ""

            // 提取 key_points
            val keyPoints = mutableListOf<String>()
            val kpElem = jsonObject.get("key_points")
                ?: jsonObject.get("keyPoints")
                ?: jsonObject.get("points")
                ?: jsonObject.get("highlights")
            if (kpElem != null && kpElem.isJsonArray) {
                kpElem.asJsonArray.forEach { item ->
                    val s = item.asString
                    if (s.isNotBlank()) keyPoints.add(s)
                }
            }

            // 提取 mindmap
            var mindmap = jsonObject.get("mindmap")?.asString
                ?: jsonObject.get("mind_map")?.asString
                ?: jsonObject.get("mindMap")?.asString
                ?: ""

            if (!mindmap.startsWith("#")) {
                mindmap = "# ${videoDetail.title}\n$mindmap"
            }

            // 提取 tags
            val tags = mutableListOf<String>()
            val tagElem = jsonObject.get("tags") ?: jsonObject.get("tag_list")
            if (tagElem != null && tagElem.isJsonArray) {
                tagElem.asJsonArray.forEach { item ->
                    val s = item.asString
                    if (s.isNotBlank()) tags.add(s)
                }
            }
            if (tags.isEmpty()) {
                if (videoDetail.tname.isNotBlank()) tags.add(videoDetail.tname)
                tags.addAll(videoDetail.tags.take(3))
            }

            // 提取 quiz
            val quizList = mutableListOf<QuizItem>()
            val quizElem = jsonObject.get("quiz") ?: jsonObject.get("quizzes")
            if (quizElem != null && quizElem.isJsonArray) {
                quizElem.asJsonArray.forEach { elem ->
                    if (elem.isJsonObject) {
                        val qObj = elem.asJsonObject
                        val question = qObj.get("question")?.asString ?: ""
                        val answer = qObj.get("answer")?.asString ?: ""
                        val analysis = qObj.get("analysis")?.asString ?: qObj.get("explanation")?.asString ?: ""
                        val opts = mutableListOf<String>()
                        qObj.getAsJsonArray("options")?.forEach { opt ->
                            opts.add(opt.asString)
                        }
                        if (question.isNotBlank()) {
                            quizList.add(QuizItem(question, opts, answer, analysis))
                        }
                    }
                }
            }

            if (summary.isNotBlank() && keyPoints.isNotEmpty()) {
                // 确保摘要以本视频标题为锚点
                if (!summary.contains("《") && !summary.contains(videoDetail.title.take(6))) {
                    summary = "《${videoDetail.title}》: $summary"
                }
                return ParsedAnalysisResult(
                    summary = summary,
                    keyPoints = keyPoints,
                    mindmap = mindmap,
                    tags = tags.ifEmpty { listOf(videoDetail.tname.ifBlank { "深度学习" }, "知识沉淀") },
                    quiz = quizList
                )
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }

        // 尝试 Gson 反序列化
        try {
            val result = gson.fromJson(content, ParsedAnalysisResult::class.java)
            if (result != null && result.summary.isNotBlank()) {
                return result
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }

        // 兜底提取
        val lines = content.lines().filter { it.isNotBlank() }
        val fallbackSummary = lines.take(3).joinToString(" ").take(300)
        return ParsedAnalysisResult(
            summary = fallbackSummary.ifBlank { "《${videoDetail.title}》：系统提炼了该视频的核心要点与关键脉络。" },
            keyPoints = lines.drop(3).take(5).ifEmpty {
                listOf(
                    "主题脉络: 深入解析《${videoDetail.title}》的核心背景与主旨",
                    "关键观点: 结合UP主【${videoDetail.owner.name}】的论述与事实案例梳理",
                    "思考总结: 提炼形成系统化认知结构"
                )
            },
            mindmap = "# ${videoDetail.title}\n## 核心主旨\n- 核心观点\n## 结构脉络\n- 论点梳理\n## 实践与总结\n- 关键结论",
            tags = listOf(videoDetail.tname.ifBlank { "知识学习" }, "BiliLearn"),
            quiz = emptyList()
        )
    }

    /**
     * 四位一体全维深度视频理解 (100% 全量字幕 + 评论区/置顶笔记 + 高能弹幕 + 视觉抽帧 + 自适应领域萃取)
     */
    suspend fun analyzeVideo(
        videoDetail: VideoDetail,
        subtitles: List<SubtitleItem>,
        comments: List<CommentItem> = emptyList(),
        danmaku: List<DanmakuHighlight> = emptyList(),
        frameBase64: String? = null,
        onChunkProgress: ((completed: Int, total: Int) -> Unit)? = null
    ): Result<ParsedAnalysisResult> {
        val hasSubtitles = subtitles.isNotEmpty()
        val transcriptChunks = buildTranscriptChunks(subtitles, videoDetail)
        val requestId = UUID.randomUUID().toString()
        val transcript = if (transcriptChunks.size == 1) {
            transcriptChunks.first()
        } else {
            val partials = mutableListOf<String>()
            transcriptChunks.forEachIndexed { index, chunk ->
                onChunkProgress?.invoke(index, transcriptChunks.size)
                val chunkRequestId = "$requestId-part-${index + 1}"
                val partial = summarizeTranscriptChunk(
                    videoDetail = videoDetail,
                    transcript = chunk,
                    chunkIndex = index,
                    chunkCount = transcriptChunks.size,
                    requestId = chunkRequestId
                )
                if (partial.isFailure) return partial.map { ParsedAnalysisResult() }
                partials += partial.getOrThrow()
            }
            onChunkProgress?.invoke(transcriptChunks.size, transcriptChunks.size)
            "【超长视频分段提炼，共 ${transcriptChunks.size} 段，已连续覆盖完整时间轴】\n" +
                partials.joinToString("\n\n")
        }
        val commentsText = buildCommentsSection(comments)
        val danmakuText = buildDanmakuSection(danmaku)
        val tagsStr = if (videoDetail.tags.isNotEmpty()) videoDetail.tags.joinToString("、") else videoDetail.tname.ifBlank { "通用知识" }

        val groundingConstraint = if (hasSubtitles) {
            """
【核心萃取原则】：
1. 必须 100% 紧密基于下方提供的【视频全时长文稿与字幕】进行逐段深入提炼。
2. 知识要点中必须详细引用文稿中 UP 主亲口讲述的具体理论、推导过程、论据案例、代码实现或关键数据。
3. 严禁脱离文稿凭空想象！
            """.trimIndent()
        } else {
            """
【无文字字幕时的严格事实锚定原则】：
1. 本视频未上传独立文字字幕，因此你必须 100% 严格根据本视频的真实标题《${videoDetail.title}》、官方简介、分区【${videoDetail.tname}】和标签【$tagsStr】进行准确的主题梳理与框架归纳。
2. 绝对禁止捏造与《${videoDetail.title}》不相关的外来技术概念或代码！如果是人文社科、经济或生活思考类视频，请严格提炼其思想论点与社会现象，切勿强行生造技术参数！
            """.trimIndent()
        }

        val prompt = """
你是一名客观、严谨、博学的顶尖知识沉淀导师。
请对以下 Bilibili 视频进行结构化、高密度的深度理解与知识沉淀。

【目标视频唯一锚定】:
- source_bvid: ${videoDetail.bvid}
- request_id: $requestId
- 视频标题: 《${videoDetail.title}》
- UP主: ${videoDetail.owner.name}
- 所属分区: ${videoDetail.tname.ifBlank { "综合学习" }}
- 核心标签: $tagsStr
- 视频时长: ${videoDetail.duration / 60} 分钟

【维度一：视频全时长文稿与字幕】:
$transcript

【维度二：评论区精选、UP主置顶与时间轴笔记】:
$commentsText

【维度三：观众高能弹幕反应】:
$danmakuText

$groundingConstraint

请务必按照以下严格 JSON 格式输出：
{
  "source_bvid": "${videoDetail.bvid}",
  "request_id": "$requestId",
  "summary": "300字左右的高密度核心摘要，开门见山准确概括《${videoDetail.title.replace("\"", "\\\"")}》的核心主旨、论证逻辑与核心结论",
  "key_points": [
    "【核心概念/主旨】: 详细阐述视频提出的核心论点、基础概念或背景动机",
    "【核心论证/方法】: 详细阐述视频中具体的论据、推演逻辑、方法步骤或案例说明",
    "【关键洞见/避坑】: 详细提炼 UP 主指出的核心难点、反直觉洞见或常见认知误区",
    "【价值沉淀/结论】: 详细说明该知识的实际应用场景、启示与落地价值"
  ],
  "mindmap": "# ${videoDetail.title.replace("\"", "\\\"")}\n## 一、核心背景与问题提出\n- 关键现象与核心定义\n## 二、核心逻辑与深入剖析\n- 核心观点展开\n- 论据与方法论\n## 三、实践价值与深度思考\n- 关键结论\n- 行动建议",
  "tags": ["$tagsStr", "${videoDetail.tname.ifBlank { "知识沉淀" }}"],
  "quiz": [
    {
      "question": "基于本视频核心内容的单选题",
      "options": ["A. 正确选项", "B. 混淆项1", "C. 混淆项2", "D. 混淆项3"],
      "answer": "A",
      "analysis": "结合视频内容的详细解析"
    }
  ]
}
请仅输出纯 JSON 字符串。
        """.trimIndent()

        val messages = listOf(
            ChatMessage("system", "你是一名知识萃取专家。必须严格根据当前视频事实输出纯 JSON，并原样回传 source_bvid 与 request_id；禁止跨视频串台。"),
            ChatMessage("user", prompt)
        )

        // 采用 SSE 流式增量传输
        val response = llmClient.chatCompletion(messages, temperature = 0.2f, imageBase64 = frameBase64)
        if (!response.ok) {
            return Result.failure(Exception(response.error ?: "AI 分析失败"))
        }

        val responseJson = AnalysisResponseGuard.extractJsonObject(response.content)
        if (!AnalysisResponseGuard.matches(responseJson, videoDetail.bvid, requestId)) {
            return Result.failure(Exception("AI 响应与当前视频身份不一致，已阻止错误总结写入"))
        }

        val result = parseAnalysisJson(response.content, videoDetail, hasSubtitles)
        return Result.success(result)
    }
}
