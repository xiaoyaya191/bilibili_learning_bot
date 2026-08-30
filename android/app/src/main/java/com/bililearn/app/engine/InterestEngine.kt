package com.bililearn.app.engine

import android.content.Context
import android.content.SharedPreferences
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Locale

data class InterestTag(
    val name: String,
    val weight: Float = 1.0f, // 0.5f: 关注, 1.0f: 喜爱, 1.5f: 强兴趣
    val hitCount: Int = 0
)

data class InterestMatchDetail(
    val score: Double,
    val matchedInterests: List<String>,
    val hitExclusion: String? = null,
    val reason: String
)

class InterestEngine(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences("bililearn_interests", Context.MODE_PRIVATE)

    private val gson = Gson()

    // No built-in interests: the profile belongs entirely to the user.
    private val defaultTags = emptyList<InterestTag>()
    private val defaultExclusions = emptyList<String>()

    // 兴趣标签关键词语义拓展词库 (解决用户设"AI技术"，视频标题是"DeepSeek重磅发布"或"ChatGPT实操"无法命中的痛点)
    private val synonymMap = mapOf(
        "AI技术" to listOf("ai", "gpt", "llm", "agent", "transformer", "大模型", "人工智能", "openai", "claude", "deepseek", "sora", "cursor", "copilot", "提示词", "prompt", "算力"),
        "深度学习" to listOf("深度学习", "机器学习", "神经网络", "pytorch", "tensorflow", "backprop", "反向传播", "强化学习", "rlhf", "梯度下降", "cv", "nlp", "diffusion", "扩散模型"),
        "编程开发" to listOf("python", "java", "c++", "rust", "golang", "kotlin", "vue", "react", "spring", "docker", "k8s", "linux", "git", "前端", "后端", "全栈", "代码", "源码", "算法", "重构", "实战", "项目"),
        "架构设计" to listOf("架构", "系统设计", "分布式", "微服务", "高并发", "高性能", "消息队列", "redis", "mysql", "设计模式", "底层原理"),
        "开源硬件" to listOf("单片机", "stm32", "树莓派", "esp32", "嵌入式", "电路", "pcb", "fpga", "arduino", "芯片", "risc-v"),
        "数码科技" to listOf("数码", "芯片", "显卡", "gpu", "cpu", "半导体", "手机评测", "装机", "nas", "黑科技"),
        "数学" to listOf("微积分", "线性代数", "概率论", "高等数学", "离散数学", "统计学", "傅里叶", "矩阵"),
        "认知科学" to listOf("认知", "心理学", "思维模型", "神经科学", "大脑", "记忆法", "逻辑学", "方法论")
    )

    private val _interestsFlow = MutableStateFlow(getInterestTags())
    val interestsFlow: StateFlow<List<InterestTag>> = _interestsFlow.asStateFlow()

    private val _exclusionsFlow = MutableStateFlow(getExclusions())
    val exclusionsFlow: StateFlow<List<String>> = _exclusionsFlow.asStateFlow()

    fun isAutoEvolveEnabled(): Boolean = prefs.getBoolean("auto_evolve", true)
    fun setAutoEvolveEnabled(enabled: Boolean) = prefs.edit().putBoolean("auto_evolve", enabled).apply()

    fun getInterestTags(): List<InterestTag> {
        val jsonStr = prefs.getString("interest_tags_v2", "") ?: ""
        if (jsonStr.isBlank()) return defaultTags
        return try {
            val type = object : TypeToken<List<InterestTag>>() {}.type
            gson.fromJson(jsonStr, type) ?: defaultTags
        } catch (e: Exception) {
            defaultTags
        }
    }

    fun setInterestTags(tags: List<InterestTag>) {
        prefs.edit().putString("interest_tags_v2", gson.toJson(tags)).apply()
        _interestsFlow.value = tags
    }

    fun addInterest(name: String, weight: Float = 1.0f) {
        val current = getInterestTags().toMutableList()
        val existingIdx = current.indexOfFirst { it.name.equals(name, ignoreCase = true) }
        if (existingIdx >= 0) {
            current[existingIdx] = current[existingIdx].copy(weight = weight)
        } else {
            current.add(InterestTag(name, weight, 0))
        }
        setInterestTags(current)
    }

    fun removeInterest(name: String) {
        val current = getInterestTags().toMutableList()
        current.removeAll { it.name.equals(name, ignoreCase = true) }
        setInterestTags(current)
    }

    fun getExclusions(): List<String> {
        val jsonStr = prefs.getString("exclusions_v2", "") ?: ""
        if (jsonStr.isBlank()) return defaultExclusions
        return try {
            val type = object : TypeToken<List<String>>() {}.type
            gson.fromJson(jsonStr, type) ?: defaultExclusions
        } catch (e: Exception) {
            defaultExclusions
        }
    }

    fun setExclusions(list: List<String>) {
        prefs.edit().putString("exclusions_v2", gson.toJson(list)).apply()
        _exclusionsFlow.value = list
    }

    fun reloadFromDisk() {
        _interestsFlow.value = getInterestTags()
        _exclusionsFlow.value = getExclusions()
    }

    fun clearAll() {
        prefs.edit().clear().commit()
        reloadFromDisk()
    }

    fun addExclusion(word: String) {
        val current = getExclusions().toMutableList()
        if (!current.contains(word)) {
            current.add(word)
            setExclusions(current)
        }
    }

    fun removeExclusion(word: String) {
        val current = getExclusions().toMutableList()
        current.remove(word)
        setExclusions(current)
    }

    /**
     * 兴趣画像自适应进化：根据新学到的标签增强权重或探索新标签
     */
    fun onKnowledgeLearned(tags: List<String>) {
        if (!isAutoEvolveEnabled() || tags.isEmpty()) return

        val current = getInterestTags().toMutableList()
        tags.forEach { tag ->
            val cleanTag = tag.trim().trim('#')
            if (cleanTag.isNotBlank() && cleanTag.length in 2..15) {
                val idx = current.indexOfFirst { it.name.equals(cleanTag, ignoreCase = true) }
                if (idx >= 0) {
                    val old = current[idx]
                    val newWeight = (old.weight + 0.05f).coerceAtMost(2.0f)
                    current[idx] = old.copy(weight = newWeight, hitCount = old.hitCount + 1)
                } else if (current.size < 25) {
                    current.add(InterestTag(cleanTag, 0.7f, 1))
                }
            }
        }
        setInterestTags(current)
    }

    /**
     * 计算视频与当前兴趣的精准匹配评分 (具有极强区分度)
     * - 命中负向词: 0.0 分 (一票否决)
     * - 命中正向兴趣: 5.0 ~ 30.0+ 分 (按权重与命中项大幅提权)
     * - 完全未命中: 0.0 分 (不进入自动学习流)
     */
    fun evaluateVideo(title: String, desc: String = ""): InterestMatchDetail {
        val text = "$title $desc".lowercase(Locale.getDefault())

        // 1. 命中负向排除词，一票否决直接归零
        for (ex in getExclusions()) {
            if (ex.isNotBlank() && text.contains(ex.lowercase(Locale.getDefault()))) {
                return InterestMatchDetail(
                    score = 0.0,
                    matchedInterests = emptyList(),
                    hitExclusion = ex,
                    reason = "命中负向过滤词: 【$ex】"
                )
            }
        }

        // 2. 遍历正向兴趣标签与语义拓展词库进行打分
        val matched = mutableListOf<String>()
        var totalWeight = 0f

        for (tag in getInterestTags()) {
            val tagNameLower = tag.name.lowercase(Locale.getDefault())
            var hit = false

            // A. 直接匹配标签名
            if (text.contains(tagNameLower)) {
                hit = true
            }

            // B. 匹配同义拓展词库
            if (!hit) {
                val synonyms = synonymMap[tag.name]
                if (synonyms != null) {
                    for (syn in synonyms) {
                        if (text.contains(syn.lowercase(Locale.getDefault()))) {
                            hit = true
                            break
                        }
                    }
                }
            }

            if (hit) {
                matched.add(tag.name)
                totalWeight += tag.weight
            }
        }

        // 3. 计算最终得分 (若未命中任何兴趣标签，返回 0.0 分)
        if (matched.isEmpty()) {
            return InterestMatchDetail(
                score = 0.0,
                matchedInterests = emptyList(),
                reason = "未命中任何已设定的学习兴趣标签"
            )
        }

        // 基础命中分 5.0 + 权重加成 + 多项匹配加成
        val score = 5.0 + (totalWeight * 4.0) + (matched.size * 2.0)

        return InterestMatchDetail(
            score = score,
            matchedInterests = matched.distinct(),
            reason = "命中兴趣画像: [${matched.distinct().joinToString(", ")}], 权重加成后评分: ${String.format("%.1f", score)}"
        )
    }

    fun calculateScore(title: String, desc: String = ""): Double {
        return evaluateVideo(title, desc).score
    }
}
