package com.bililearn.app.engine

import com.bililearn.app.data.database.entity.KnowledgeNoteEntity
import java.util.regex.Pattern

data class RAGSearchResult(
    val note: KnowledgeNoteEntity,
    val score: Double,
    val matchedKeywords: List<String>
)

class KnowledgeRAGEngine {

    // 常见中文停用词表
    private val stopWords = setOf(
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
        "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
        "自己", "这", "如何", "怎么", "什么", "为什么", "哪个", "请问", "讲讲", "介绍",
        "总结", "分析", "解释", "一下", "能不能", "可以", "吗", "呢", "吧", "呀", "啊", "谁", "与", "及"
    )

    /**
     * 针对用户输入的问题进行关键词提取与多粒度分词 (支持中英文、专有名词、双字/三字滑动窗口)
     */
    fun extractKeywords(query: String): List<String> {
        val cleanQuery = query.trim()
        if (cleanQuery.isBlank()) return emptyList()

        val keywords = mutableSetOf<String>()

        // 1. 提取英文/数字/专有名词 (如 Python, Transformer, HTTP, LLM, 504)
        val engPattern = Pattern.compile("[a-zA-Z0-9_+#\\.-]{2,}")
        val engMatcher = engPattern.matcher(cleanQuery)
        while (engMatcher.find()) {
            val word = engMatcher.group()
            if (word.lowercase() !in stopWords) {
                keywords.add(word)
            }
        }

        // 2. 提取中文词组
        val chineseText = cleanQuery.replace(Regex("[^\u4e00-\u9fa5]"), " ")
        val segments = chineseText.split("\\s+".toRegex()).filter { it.length >= 2 }

        for (seg in segments) {
            if (seg.length in 2..6 && seg !in stopWords) {
                keywords.add(seg)
            } else if (seg.length > 6) {
                // 滑动窗口切分双字/三字词
                for (i in 0 until seg.length - 1) {
                    val sub2 = seg.substring(i, i + 2)
                    if (sub2 !in stopWords) keywords.add(sub2)
                    if (i + 3 <= seg.length) {
                        val sub3 = seg.substring(i, i + 3)
                        if (sub3 !in stopWords) keywords.add(sub3)
                    }
                }
            }
        }

        return keywords.toList()
    }

    /**
     * 智能语义评分检索：只根据提问关键词对全库笔记打分并返回 Top 1~3 最相关的笔记
     */
    fun searchRelevantNotes(
        query: String,
        allNotes: List<KnowledgeNoteEntity>,
        topK: Int = 3
    ): List<RAGSearchResult> {
        val keywords = extractKeywords(query)
        if (keywords.isEmpty() || allNotes.isEmpty()) return emptyList()

        val results = mutableListOf<RAGSearchResult>()

        for (note in allNotes) {
            var score = 0.0
            val matched = mutableListOf<String>()

            val titleLower = note.title.lowercase()
            val summaryLower = note.summary.lowercase()
            val tagsLower = note.tagsJson.lowercase()
            val keyPointsLower = note.keyPointsJson.lowercase()

            for (kw in keywords) {
                val kwLower = kw.lowercase()
                var kwMatched = false

                // 标题匹配 (高权重 10.0)
                if (titleLower.contains(kwLower)) {
                    score += 10.0
                    kwMatched = true
                }

                // 标签匹配 (权重 8.0)
                if (tagsLower.contains(kwLower)) {
                    score += 8.0
                    kwMatched = true
                }

                // 知识要点匹配 (权重 4.0)
                if (keyPointsLower.contains(kwLower)) {
                    score += 4.0
                    kwMatched = true
                }

                // 摘要匹配 (权重 3.0)
                if (summaryLower.contains(kwLower)) {
                    score += 3.0
                    kwMatched = true
                }

                if (kwMatched) {
                    matched.add(kw)
                }
            }

            if (score > 0.0 && matched.isNotEmpty()) {
                results.add(RAGSearchResult(note, score, matched.distinct()))
            }
        }

        // 按相关度降序排列，取 Top K
        return results.sortedByDescending { it.score }.take(topK)
    }

    /**
     * 构建紧凑、高质量的 RAG 上下文提示词 (严格控制 Token 大小，彻底解决上下文爆炸)
     */
    fun buildRagContext(searchResults: List<RAGSearchResult>): String {
        if (searchResults.isEmpty()) {
            return "【知识库检索结果】：本地知识库中未检索到与该问题直接强相关的笔记。请基于你的广博知识体系为用户进行专业解答。"
        }

        val sb = StringBuilder()
        sb.append("【本地知识库精准检索结果（仅提取与提问强相关的笔记片段）】:\n\n")

        searchResults.forEachIndexed { index, res ->
            val note = res.note
            sb.append("--- [参考笔记 ${index + 1}] 《${note.title}》 (UP主: ${note.upName}) ---\n")
            sb.append("核心摘要: ${note.summary.take(250)}\n")
            val kps = note.getKeyPointsList().take(2)
            if (kps.isNotEmpty()) {
                sb.append("关键要点:\n")
                kps.forEach { kp -> sb.append("• ${kp.take(150)}\n") }
            }
            sb.append("\n")
        }

        sb.append("【导师回答原则】：请优先参考并结合上述检索到的本地知识库笔记内容为用户进行亲切、条理分明的解答。")
        return sb.toString().trim()
    }
}
