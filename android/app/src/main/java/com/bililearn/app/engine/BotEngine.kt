package com.bililearn.app.engine

import android.content.Context
import com.bililearn.app.data.database.AppDatabase
import com.bililearn.app.data.database.DatabaseBackupManager
import com.bililearn.app.data.database.entity.ActionReviewEntity
import com.bililearn.app.data.database.entity.KnowledgeNoteEntity
import com.bililearn.app.data.model.*
import com.bililearn.app.data.prefs.AppPreferences
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.network.bilibili.BiliApiClient
import com.bililearn.app.network.llm.LLMClient
import com.google.gson.Gson
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.text.SimpleDateFormat
import java.util.*
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue

class BotEngine(
    private val context: Context,
    private val database: AppDatabase,
    val preferences: AppPreferences,
    val databaseBackupManager: DatabaseBackupManager
) {
    val biliApiClient = BiliApiClient(preferences)
    val llmClient = LLMClient(preferences, BiliLearnApplication.instance.advancedStore)
    val understandingEngine = VideoUnderstandingEngine(llmClient)
    val personaEngine = PersonaEngine(preferences, llmClient)
    val miniGoalEngine = MiniGoalEngine(context)
    val interestEngine = InterestEngine(context)
    val documentExportEngine = DocumentExportEngine()
    val ragEngine = KnowledgeRAGEngine()
    val safetyGuard = SafetyGuard(preferences)

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val logStore = LogStore(context)
    private var patrolJob: Job? = null

    // 引入严格互斥锁，确保全局绝对只有 1 个视频处于处理流水线中
    private val learningMutex = Mutex()

    // 失败视频 10 分钟冷却池
    private val failedBvidCooldown = ConcurrentHashMap<String, Long>()

    // 【优先级 1】主人要求的指定 BV 号队列 (最高优先级)
    private val userPriorityQueue = ConcurrentLinkedQueue<String>(preferences.getPendingLearningTasks())
    private val _pendingTasks = MutableStateFlow(userPriorityQueue.toList())
    val pendingTasks: StateFlow<List<String>> = _pendingTasks.asStateFlow()

    private val _status = MutableStateFlow(BotStatus())
    val status: StateFlow<BotStatus> = _status.asStateFlow()

    private val _logs = MutableStateFlow<List<LogEntry>>(
        logStore.load().ifEmpty { listOf(LogEntry(getCurrTime(), "BiliLearn 移动端 AI 全维学习系统已就绪")) }
    )
    val logs: StateFlow<List<LogEntry>> = _logs.asStateFlow()

    private val gson = Gson()

    // 自动连续刷主页推荐流指标
    private var rcmdFreshIdx = 1

    fun addLog(msg: String, level: String = "INFO") {
        val entry = LogEntry(getCurrTime(), msg, level)
        val current = _logs.value.toMutableList()
        current.add(entry)
        if (current.size > 200) current.removeAt(0)
        _logs.value = current
        scope.launch { logStore.append(entry) }
    }

    fun clearLogs() {
        val entry = LogEntry(getCurrTime(), "日志已清空")
        _logs.value = listOf(entry)
        scope.launch { logStore.clear(); logStore.append(entry) }
    }

    private fun getCurrTime(): String {
        return SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
    }

    /**
     * 主人直接要求学习指定 BV 号 (入队最高优先级队列)
     */
    fun enqueueUserRequestedVideo(rawInput: String) {
        val clean = biliApiClient.extractBvid(rawInput) ?: rawInput.trim()
        if (clean.isNotBlank()) {
            if (!userPriorityQueue.contains(clean)) {
                userPriorityQueue.offer(clean)
                syncPendingTasks()
                addLog("收到主人指定学习任务: $clean，已加入最高优先级队列")
            } else {
                addLog("指定视频已在队列中，已忽略重复任务: $clean", "WARN")
            }
        }
    }

    private fun syncPendingTasks() {
        val snapshot = userPriorityQueue.toList()
        _pendingTasks.value = snapshot
        preferences.setPendingLearningTasks(snapshot)
    }

    fun startBot() {
        if (_status.value.isRunning) return

        val startTimeStr = getCurrTime()
        _status.value = _status.value.copy(
            isRunning = true,
            startTimeStr = startTimeStr,
            observation = ObservationState("正在初始化学习巡检队列...", stage = ActivityStage.MONITORING)
        )
        addLog("学习机器人已启动，按【主人指定 > 稍后再看 > 主页推荐】优先级巡检")

        patrolJob = scope.launch {
            runPatrolLoop()
        }
    }

    fun stopBot() {
        patrolJob?.cancel()
        patrolJob = null
        _status.value = _status.value.copy(
            isRunning = false,
            observation = ObservationState("已停止运行", stage = ActivityStage.IDLE)
        )
        addLog("机器人服务已停止")
    }

    private fun isBvidAvailable(bvid: String, learnedSet: Set<String>): Boolean {
        if (bvid in learnedSet) return false
        val cooldownUntil = failedBvidCooldown[bvid] ?: 0L
        return System.currentTimeMillis() > cooldownUntil
    }

    /**
     * 严格优先级巡检主循环：
     * 1. 优先级 1: 主人要求的 BV 号 (Direct Task)
     * 2. 优先级 2: 稍后再看 (Toview Queue)
     * 3. 优先级 3: 主页推荐流 (Homepage Feed) -> 严格按兴趣评分排序
     * 4. 兜底策略: 主页无匹配视频时，等待 10 秒后刷新主页流
     */
    private suspend fun runPatrolLoop() {
        while (currentCoroutineContext().isActive && _status.value.isRunning) {
            try {
                val apiKey = preferences.getApiKey()
                if (apiKey.isBlank()) {
                    _status.value = _status.value.copy(
                        observation = ObservationState("等待配置 API Key", stage = ActivityStage.IDLE)
                    )
                    addLog("提示: 尚未配置 API Key，请在【设置】页面填入后开启自动分析", "WARN")
                    delay(30_000)
                    continue
                }

                _status.value = _status.value.copy(
                    observation = ObservationState("正在按优先级智能巡检待学视频...", stage = ActivityStage.MONITORING)
                )

                val learnedBvids = database.knowledgeNoteDao().getAllLearnedBvids().toSet()
                var candidateBvid: String? = null
                var candidateTitle: String = ""
                var candidateFromPriorityQueue = false

                // ----------------------------------------------------
                // 【优先级 1】主人要求的指定 BV 号
                // ----------------------------------------------------
                if (userPriorityQueue.isNotEmpty()) {
                    val userBvid = userPriorityQueue.peek()
                    if (userBvid != null && isBvidAvailable(userBvid, learnedBvids)) {
                        candidateBvid = userBvid
                        candidateTitle = "主人指定视频"
                        candidateFromPriorityQueue = true
                        addLog("【优先级 1】正在处理主人要求的指定视频: $userBvid")
                    } else if (userBvid != null && userBvid in learnedBvids) {
                        userPriorityQueue.poll()
                        syncPendingTasks()
                    }
                }

                // ----------------------------------------------------
                // 【优先级 2】用户主动加入的【稍后再看】队列
                // ----------------------------------------------------
                if (candidateBvid == null && preferences.isBiliLoggedIn() && preferences.isCheckToviewEnabled()) {
                    val toviewList = biliApiClient.fetchToviewList()
                    val unlearnedToview = toviewList.firstOrNull { isBvidAvailable(it.bvid, learnedBvids) }
                    if (unlearnedToview != null) {
                        candidateBvid = unlearnedToview.bvid
                        candidateTitle = unlearnedToview.title
                        addLog("【优先级 2】发现主人【稍后再看】待学视频: 《${candidateTitle}》")
                    }
                }

                // ----------------------------------------------------
                // 【优先级 3】主页推荐流 (有符合的优先看，没有符合的就随便看)
                // ----------------------------------------------------
                if (candidateBvid == null) {
                    val rcmdList = biliApiClient.fetchRcmdFeed(rcmdFreshIdx)
                    val availableVideos = rcmdList.filter { isBvidAvailable(it.bvid, learnedBvids) }

                    if (availableVideos.isNotEmpty()) {
                        // 对主页批次内的所有可用视频进行精准兴趣评估
                        val evaluated = availableVideos.map { video ->
                            val matchDetail = interestEngine.evaluateVideo(video.title)
                            Triple(video, matchDetail.score, matchDetail)
                        }

                        // 分离出符合正向兴趣的视频 (score > 0.0 且未命中负向词)
                        val matchedList = evaluated
                            .filter { it.second > 0.0 && it.third.hitExclusion == null }
                            .sortedByDescending { it.second }

                        // 过滤出排除负向词的普通推荐视频 (作为无匹配时的随意探索学习)
                        val casualList = evaluated
                            .filter { it.third.hitExclusion == null }

                        if (matchedList.isNotEmpty()) {
                            val (bestVideo, score, detail) = matchedList.first()
                            candidateBvid = bestVideo.bvid
                            candidateTitle = bestVideo.title
                            addLog("【优先级 3·主页推荐】优先命中兴趣内容: 《$candidateTitle》 (${detail.reason})")
                        } else {
                            val pick = casualList.firstOrNull()?.first ?: availableVideos.first()
                            candidateBvid = pick.bvid
                            candidateTitle = pick.title
                            addLog("【优先级 3·主页推荐】本批未精准命中画像，自适应挑选主页推荐: 《$candidateTitle》")
                        }
                    } else {
                        if (rcmdList.isEmpty()) {
                            addLog("【主页推荐】正在通过知识高分池补充推荐流，10 秒后自动重试...")
                        } else {
                            addLog("【主页推荐】第 $rcmdFreshIdx 批主页的 ${rcmdList.size} 个视频均已沉淀入库，10 秒后自动刷新下一批主页推荐流...")
                        }
                        rcmdFreshIdx++
                        delay(10_000)
                        continue
                    }
                }

                // ----------------------------------------------------
                // 执行全维深度萃取
                // ----------------------------------------------------
                addLog("锁定目标: 《$candidateTitle》($candidateBvid)，开始全维知识萃取...")
                val res = learnSingleVideo(candidateBvid)
                if (candidateFromPriorityQueue && userPriorityQueue.peek() == candidateBvid) {
                    userPriorityQueue.poll()
                    syncPendingTasks()
                }
                if (res.isSuccess) {
                    addLog("成功沉淀全维知识卡片与思维导图至知识库")
                    personaEngine.onVideoLearned()
                    delay(6_000)
                } else {
                    val errMsg = res.exceptionOrNull()?.message ?: "未知错误"
                    addLog("视频学习未完成: $errMsg", "WARN")
                    failedBvidCooldown[candidateBvid] = System.currentTimeMillis() + 10 * 60 * 1000
                    delay(3_000)
                }

            } catch (e: CancellationException) {
                break
            } catch (e: Exception) {
                addLog("后台巡检异常: ${e.message}", "ERROR")
                delay(10_000)
            }
        }
    }

    /**
     * 学习单个视频的核心业务流 (融合 字幕 + 评论区/置顶笔记 + 弹幕高能点 + 视觉抽帧 4位一体)
     */
    suspend fun learnSingleVideo(rawInput: String): Result<KnowledgeNoteEntity> = learningMutex.withLock {
        val cleanBvid = biliApiClient.resolveAndExtractBvid(rawInput)
            ?: biliApiClient.extractBvid(rawInput)
            ?: return@withLock Result.failure(Exception("请输入有效的 B 站 BV 号、视频链接或 b23.tv 短链接"))

        database.knowledgeNoteDao().getNoteByBvid(cleanBvid)?.let { existing ->
            addLog("视频已存在于知识库，跳过重复分析: $cleanBvid", "WARN")
            return@withLock Result.success(existing)
        }

        _status.value = _status.value.copy(
            observation = ObservationState("正在拉取视频详情...", bvid = cleanBvid, stage = ActivityStage.FETCHING)
        )
        addLog("正在请求 B站 视频基础数据: $cleanBvid ...")

        // 1. 获取视频详情
        val detailRes = biliApiClient.fetchVideoDetail(cleanBvid)
        if (detailRes.isFailure) {
            val err = detailRes.exceptionOrNull()?.message ?: "获取详情失败"
            _status.value = _status.value.copy(observation = ObservationState("解析失败", bvid = cleanBvid, stage = ActivityStage.ERROR))
            addLog("获取视频详情失败: $err", "ERROR")
            return@withLock Result.failure(Exception(err))
        }

        val videoDetail = detailRes.getOrThrow()
        addLog("目标视频: 《${videoDetail.title}》 | UP主: ${videoDetail.owner.name} | 时长: ${videoDetail.duration / 60}分")

        // 2. 拉取字幕 (带 WBI 动态签名)
        _status.value = _status.value.copy(
            observation = ObservationState("正在拉取完整文稿与字幕...", title = videoDetail.title, bvid = cleanBvid, stage = ActivityStage.SUBTITLES)
        )
        val subtitles = biliApiClient.fetchSubtitles(cleanBvid, videoDetail.cid, videoDetail.title)
        if (subtitles.isNotEmpty()) {
            val totalChars = subtitles.sumOf { it.content.length }
            addLog("成功提取全量官方字幕: 共 ${subtitles.size} 句 (${totalChars} 字)，将按长度分段研读")
        } else {
            addLog("该视频未提供独立字幕，将基于官方简介、分P章节、分类标签与评论区全维提炼")
            /*
            if (preferences.isVideoAsrFallbackEnabled() && localAsrModelManager.isInstalled()) {
                _status.value = _status.value.copy(
                    observation = ObservationState("正在使用本地 Whisper 识别视频音轨...", title = videoDetail.title, bvid = cleanBvid, stage = ActivityStage.SUBTITLES)
                )
                val audioSource = biliApiClient.fetchAudioSource(cleanBvid, videoDetail.cid)
                if (audioSource.isSuccess) {
                    val source = audioSource.getOrThrow()
                    val asr = localAsrEngine.transcribeUrl(
                        source.url,
                        source.headers,
                        preferences.getAsrLanguage(),
                        preferences.getAsrMaxDurationSeconds(),
                        cleanBvid
                    )
                    if (asr.isSuccess && asr.getOrThrow().sourceId == cleanBvid) {
                        subtitles = asr.getOrThrow().segments
                        addLog("本地 Whisper 已识别 ${subtitles.size} 个时间轴片段，结果绑定视频 $cleanBvid")
                    } else {
                        addLog("本地语音识别失败: ${asr.exceptionOrNull()?.message ?: "视频身份不一致"}，将使用官方元数据", "WARN")
                    }
                } else {
                    addLog("无法取得视频音轨: ${audioSource.exceptionOrNull()?.message ?: "未知错误"}，将使用官方元数据", "WARN")
                }
            } else if (preferences.isVideoAsrFallbackEnabled()) {
                addLog("本地 Whisper 模型尚未安装，将使用官方简介、章节和评论区", "WARN")
            */
        }

        // 3. 【多维感知】拉取评论区置顶笔记与时间轴课代表讨论
        var comments = emptyList<CommentItem>()
        if (preferences.isReadCommentsEnabled() && videoDetail.aid > 0) {
            _status.value = _status.value.copy(
                observation = ObservationState("正在研读评论区置顶与时间轴笔记...", title = videoDetail.title, bvid = cleanBvid, stage = ActivityStage.FETCHING)
            )
            comments = biliApiClient.fetchTopComments(videoDetail.aid)
            if (comments.isNotEmpty()) {
                addLog("已研读 ${comments.size} 条置顶笔记/时间轴/精选热评")
            }
        }

        // 4. 【多维感知】拉取弹幕高能时刻与观众共鸣点
        var danmaku = emptyList<DanmakuHighlight>()
        if (preferences.isReadDanmakuEnabled() && videoDetail.cid > 0) {
            danmaku = biliApiClient.fetchDanmakuHighlights(videoDetail.cid)
            if (danmaku.isNotEmpty()) {
                addLog("已捕获 ${danmaku.size} 处全片高能弹幕共鸣点")
            }
        }

        // 5. 【多维感知】拉取视频全时长抽帧拼图 (供多模态视觉大模型观察)
        var frameBase64: String? = null
        if (preferences.isVisionModeEnabled() && videoDetail.aid > 0 && videoDetail.cid > 0) {
            _status.value = _status.value.copy(
                observation = ObservationState("正在抽帧感知视频画面 (PPT/板书/代码)...", title = videoDetail.title, bvid = cleanBvid, stage = ActivityStage.AI_REASONING)
            )
            frameBase64 = biliApiClient.fetchVideoshotSpriteBase64(videoDetail.aid, videoDetail.cid, cleanBvid)
            if (frameBase64 != null) {
                addLog("已抽取视频全时长等距 5 帧关键画面，供视觉模型感知")
            }
        }

        _status.value = _status.value.copy(
            observation = ObservationState("AI 正在全维度萃取核心知识与思维导图...", title = videoDetail.title, bvid = cleanBvid, stage = ActivityStage.AI_REASONING)
        )
        addLog("正在调用认知模型 (${preferences.getBrainModel()}) 综合字幕、评论区、弹幕与画面提炼知识...")

        // 6. AI 全维深度萃取 (严格锁定该视频标题与元数据)
        val analysisRes = understandingEngine.analyzeVideo(
            videoDetail,
            subtitles,
            comments,
            danmaku,
            frameBase64
        ) { completed, total ->
            _status.value = _status.value.copy(
                observation = ObservationState(
                    "AI 正在分段研读长视频 ($completed/$total)...",
                    title = videoDetail.title,
                    bvid = cleanBvid,
                    stage = ActivityStage.AI_REASONING
                )
            )
        }
        if (analysisRes.isFailure) {
            val err = analysisRes.exceptionOrNull()?.message ?: "AI 生成失败"
            _status.value = _status.value.copy(observation = ObservationState("AI 分析失败", title = videoDetail.title, bvid = cleanBvid, stage = ActivityStage.ERROR))
            addLog("AI 生成失败: $err", "ERROR")
            return@withLock Result.failure(Exception(err))
        }

        val parsed = analysisRes.getOrThrow()

        _status.value = _status.value.copy(
            observation = ObservationState("正在沉淀至本地知识库...", title = videoDetail.title, bvid = cleanBvid, stage = ActivityStage.SAVING)
        )

        // 7. 存入 Room 数据库 (严格以当前 videoDetail 的 bvid 与 title 封装)
        val now = System.currentTimeMillis()
        val dateStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date(now))
        val noteEntity = KnowledgeNoteEntity(
            id = "${cleanBvid}_${now}",
            bvid = cleanBvid,
            title = videoDetail.title,
            summary = parsed.summary,
            keyPointsJson = gson.toJson(parsed.keyPoints),
            mindmapMarkdown = parsed.mindmap,
            tagsJson = gson.toJson(parsed.tags),
            quizJson = gson.toJson(parsed.quiz),
            upName = videoDetail.owner.name,
            coverUrl = videoDetail.pic,
            createdAt = now,
            dateStr = dateStr
        )

        database.knowledgeNoteDao().insertNote(noteEntity)
        miniGoalEngine.onVideoLearned(videoDetail.duration)
        interestEngine.onKnowledgeLearned(parsed.tags)
        failedBvidCooldown.remove(cleanBvid)

        // 异步更新一份双写镜像备份 (抵御任何版本升级与数据库重构)
        databaseBackupManager.autoBackup()

        // 8. 行为审批流建议 (AI 拟人自主自由评论生成，提交给主人审核)
        if (preferences.isRequireApprovalForActions() && preferences.isBiliLoggedIn() && preferences.getActivePersonaKey().isNotBlank()) {
            addLog("正在由 AI 结合【${personaEngine.getActivePersona().name}】人设自主构思深度评论 (去模板化)...")
            val proposedComment = personaEngine.generateAutonomousComment(
                videoDetail = videoDetail,
                summary = parsed.summary,
                keyPoints = parsed.keyPoints,
                topComments = comments,
                danmaku = danmaku
            )

            if (safetyGuard.isContentSafe(proposedComment)) {
                database.actionReviewDao().insertReview(
                    ActionReviewEntity(
                        actionType = "LIKE",
                        bvid = cleanBvid,
                        videoTitle = videoDetail.title,
                        reason = "高质量知识视频，建议点赞支持"
                    )
                )
                database.actionReviewDao().insertReview(
                    ActionReviewEntity(
                        actionType = "COMMENT",
                        bvid = cleanBvid,
                        videoTitle = videoDetail.title,
                        targetText = proposedComment,
                        reason = "由 AI 结合《${videoDetail.title}》与【${personaEngine.getActivePersona().name}】人设自主构思的自由评论"
                    )
                )
                addLog("AI 自主构思的评论已提交至行为审核中心")
            }
        }

        val totalCount = database.knowledgeNoteDao().getAllNotes().size
        _status.value = _status.value.copy(
            processedCount = _status.value.processedCount + 1,
            kbItemsCount = totalCount,
            totalDurationMinutes = _status.value.totalDurationMinutes + (videoDetail.duration / 60),
            observation = ObservationState("全维学习完成，已沉淀知识库", title = videoDetail.title, bvid = cleanBvid, stage = ActivityStage.FINISHED)
        )

        addLog("《${videoDetail.title}》全维知识笔记已成功入库")
        return@withLock Result.success(noteEntity)
    }
}

