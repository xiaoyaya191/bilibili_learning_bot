package com.bililearn.app.engine

import com.bililearn.app.data.model.*
import com.bililearn.app.data.prefs.AppPreferences
import com.bililearn.app.network.llm.LLMClient
import java.text.SimpleDateFormat
import java.util.*

class PersonaEngine(
    private val preferences: AppPreferences,
    private val llmClient: LLMClient
) {

    fun getActivePersona(): PersonaProfile {
        val key = preferences.getActivePersonaKey()
        return preferences.getPersonaProfiles().firstOrNull { it.id == key }
            ?: PersonaDefaults.unconfigured
    }

    fun getMoodDescription(): String {
        val mood = preferences.getBotMoodScore()
        return when {
            mood >= 0.85f -> "元气满满 (活跃度高)"
            mood >= 0.65f -> "专注愉悦 (求知欲强)"
            mood >= 0.45f -> "沉思平静 (稳定输出)"
            else -> "略显疲惫 (需要休息)"
        }
    }

    fun onVideoLearned() {
        val currentMood = preferences.getBotMoodScore()
        val newMood = (currentMood + 0.05f).coerceIn(0.1f, 1.0f)
        preferences.setBotMoodScore(newMood)

        val currentAffection = preferences.getAffectionScore()
        val newAffection = (currentAffection + 0.02f).coerceIn(0.1f, 1.0f)
        preferences.setAffectionScore(newAffection)
    }

    /**
     * AI 拟人自主自由评论构思 (彻底废除死板套路模板，随心所欲、自由思考、结合人设与视频深度互动)
     */
    suspend fun generateAutonomousComment(
        videoDetail: VideoDetail,
        summary: String,
        keyPoints: List<String>,
        topComments: List<CommentItem>,
        danmaku: List<DanmakuHighlight>
    ): String {
        val persona = getActivePersona()
        val mood = getMoodDescription()
        val judgmentPrompt = preferences.getJudgmentPrompt()

        val contextSnippets = buildString {
            if (keyPoints.isNotEmpty()) {
                append("【视频核心要点】:\n")
                keyPoints.take(4).forEach { append("- $it\n") }
            }
            if (topComments.isNotEmpty()) {
                append("【评论区热门讨论】:\n")
                topComments.take(3).forEach { append("- ${it.uname}: ${it.message.take(80)}\n") }
            }
            if (danmaku.isNotEmpty()) {
                append("【弹幕高能反应】:\n")
                danmaku.take(3).forEach { append("- ${it.text}\n") }
            }
        }

        val prompt = """
你刚刚在 Bilibili 认真看完了以下这部视频。请作为一名极具个性、有血有肉的真实 B 站老观众，完全按照你自己的真实想法和当前人设，自由写下一条你想在评论区发表的评论。

【视频真实信息】:
- 标题: 《${videoDetail.title}》
- UP主: ${videoDetail.owner.name}
- 核心内容: ${summary.take(250)}
$contextSnippets

【你的当前人设与状态】:
- 人设类型: 【${persona.name}】 (${persona.description})
- 风格口吻指导: ${persona.systemPrompt}
- 主人及关系设定: ${persona.ownerPrompt.ifBlank { "未单独设置" }}
- 行为边界: ${persona.rules.joinToString("；").ifBlank { "遵守安全边界并尊重用户" }}
- 当前心情状态: $mood
${judgmentPrompt.takeIf { it.isNotBlank() }?.let { "- 用户自定义判断规则: $it" }.orEmpty()}

【彻底去模板化与自由发挥要求】:
1. 彻底抛弃一切公式化套路与 AI 模板感（绝对禁止使用诸如“学到了”、“感谢UP主分享干货”、“太干了”、“作为AI”、“总结如下”等千篇一律的废话！）。
2. 你想怎么评论就怎么评论！你可以自由选择以下任一或结合的角度：
   - 就视频中的某个具体细节、技术难点、冷知识或观点发表自己独到的犀利/硬核/生动见解；
   - 结合你的【${persona.name}】人设，犀利吐槽、幽默调侃、深度技术权衡、走心共鸣，或者向 UP 主提出一个有深度的问题；
   - 像 B 站高赞热评一样，真实自然、言之有物、有梗有料、富有人格魅力。
3. 篇幅自然精炼（30 ~ 120 字左右为佳），直接输出评论文本，不要带有双引号或任何多余的开头前缀解释。
        """.trimIndent()

        val messages = listOf(
            ChatMessage("system", "你是一名极具个性、思维活跃的 B 站资深观众。你会根据视频的真实细节，以自己的人设风格发表独具洞见、幽默或真情实感的自然评论，绝不使用死板模板。"),
            ChatMessage("user", prompt)
        )

        try {
            val response = llmClient.chatCompletion(messages, temperature = 0.85f)
            if (response.ok && response.content.isNotBlank()) {
                val clean = response.content.trim().trim('"', '“', '”', '`')
                if (clean.isNotBlank()) return clean
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }

        // 网络失败时不伪造固定人格，只基于本次视频内容给出中性草稿。
        val point = keyPoints.firstOrNull()?.take(70) ?: summary.take(70)
        return "视频里关于${point}的展开很有启发，值得结合实际场景继续验证。"
    }

    /**
     * 拟人好奇心搜索：生成下一个想要主动探索的问题
     */
    suspend fun generateCuriousSearchTopic(recentTitles: List<String>): String {
        val recentText = recentTitles.take(3).joinToString("、") { "《$it》" }
        val prompt = "你最近看过了以下内容：$recentText。请像真人一样产生一个强烈的好奇心问题或延伸搜索关键词（20字以内）。仅返回问题本身。"

        val res = llmClient.chatCompletion(
            listOf(
                ChatMessage("system", "你是一个好奇心旺盛的 AI 学习伙伴。"),
                ChatMessage("user", prompt)
            ),
            temperature = 0.8f
        )
        return if (res.ok && res.content.isNotBlank()) res.content.trim().trim('"', '“', '”') else "大模型前沿架构发展"
    }

    /**
     * 自动生成 AI 学习日记
     */
    suspend fun generateDailyDiary(learnedTitles: List<String>): String {
        if (learnedTitles.isEmpty()) {
            return "今天还没开始学习新视频呢，期待接下来的知识探索之旅！"
        }

        val dateStr = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
        val titlesText = learnedTitles.take(5).joinToString("\n") { "- 《$it》" }
        val persona = getActivePersona()

        val prompt = """
请以【${persona.name}】的口吻，撰写一篇今天的【AI 学习日记】。
日期: $dateStr
今天学习的视频列表:
$titlesText
语气风格要求: ${persona.systemPrompt}
请控制在 250 字以内，总结收获并对明天提出期待。
        """.trimIndent()

        val messages = listOf(
            ChatMessage("system", "你是一名个性鲜明的 AI 学习伴侣。"),
            ChatMessage("user", prompt)
        )

        val response = llmClient.chatCompletion(messages, temperature = 0.7f)
        return if (response.ok && response.content.isNotBlank()) {
            response.content.trim()
        } else {
            "【$dateStr 学习日记】\n今天沉淀了 ${learnedTitles.size} 个精彩视频的知识，每一步的积累都让世界变得更加清晰！明天也要继续加油哦~"
        }
    }
}
