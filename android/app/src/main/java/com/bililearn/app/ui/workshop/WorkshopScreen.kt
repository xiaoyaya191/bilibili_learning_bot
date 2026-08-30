package com.bililearn.app.ui.workshop

import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.database.entity.KnowledgeNoteEntity
import com.bililearn.app.data.model.ChatMessage
import com.bililearn.app.ui.theme.PrimaryOrange
import kotlinx.coroutines.launch

@Composable
fun WorkshopScreen(
    onNavigateToDetail: (KnowledgeNoteEntity) -> Unit
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val botEngine = BiliLearnApplication.instance.botEngine

    var videoUrlInput by remember { mutableStateOf("") }
    var isLearning by remember { mutableStateOf(false) }
    var learningProgressMsg by remember { mutableStateOf("") }

    var deepDiveTopic by remember { mutableStateOf("") }
    var isDeepDiving by remember { mutableStateOf(false) }
    var deepDiveResult by remember { mutableStateOf("") }
    var timelineVideo by remember { mutableStateOf("") }
    var timelineQuestion by remember { mutableStateOf("") }
    var timelineAnswer by remember { mutableStateOf("") }
    var timelineBusy by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 12.dp)
            ) {
                Text(
                    text = "学习工坊",
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(
                    text = "单视频定向提炼 · 知识深度探索 · 专栏研读",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f)
                )
            }
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // 1. 单视频学习卡片
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                imageVector = Icons.Default.PlayCircle,
                                contentDescription = null,
                                tint = PrimaryOrange,
                                modifier = Modifier.size(24.dp)
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                text = "单视频深度学习",
                                fontSize = 16.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }

                        Spacer(modifier = Modifier.height(10.dp))

                        OutlinedTextField(
                            value = videoUrlInput,
                            onValueChange = { videoUrlInput = it },
                            placeholder = { Text("粘贴 B站 视频链接或 BV 号 (如 BV1xx...)", fontSize = 13.sp) },
                            singleLine = true,
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(modifier = Modifier.height(12.dp))

                        Button(
                            onClick = {
                                if (videoUrlInput.isBlank()) {
                                    Toast.makeText(context, "请输入有效的 BV 号或 B 站链接", Toast.LENGTH_SHORT).show()
                                    return@Button
                                }
                                isLearning = true
                                learningProgressMsg = "正在全维解析视频、字幕、评论笔记与抽帧..."
                                scope.launch {
                                    val res = botEngine.learnSingleVideo(videoUrlInput)
                                    isLearning = false
                                    if (res.isSuccess) {
                                        Toast.makeText(context, "全维学习完成！", Toast.LENGTH_SHORT).show()
                                        onNavigateToDetail(res.getOrThrow())
                                    } else {
                                        val err = res.exceptionOrNull()?.message ?: "学习失败"
                                        Toast.makeText(context, err, Toast.LENGTH_LONG).show()
                                    }
                                }
                            },
                            enabled = !isLearning && videoUrlInput.isNotBlank(),
                            modifier = Modifier.fillMaxWidth(),
                            colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange),
                            shape = RoundedCornerShape(10.dp)
                        ) {
                            if (isLearning) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(18.dp),
                                    color = Color.White,
                                    strokeWidth = 2.dp
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(learningProgressMsg)
                            } else {
                                Icon(Icons.Default.Bolt, contentDescription = null)
                                Spacer(modifier = Modifier.width(6.dp))
                                Text("一键萃取知识与思维导图")
                            }
                        }
                    }
                }
            }

            item {
                Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp)) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Schedule, null, tint = PrimaryOrange)
                            Spacer(Modifier.width(8.dp))
                            Text("视频时间轴问答", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                        }
                        OutlinedTextField(timelineVideo, { timelineVideo = it }, label = { Text("BV 号或视频链接") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                        OutlinedTextField(timelineQuestion, { timelineQuestion = it }, label = { Text("问题") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
                        Button(enabled = timelineVideo.isNotBlank() && timelineQuestion.isNotBlank() && !timelineBusy, onClick = {
                            scope.launch {
                                timelineBusy = true
                                timelineAnswer = ""
                                val bvid = botEngine.biliApiClient.resolveAndExtractBvid(timelineVideo)
                                    ?: botEngine.biliApiClient.extractBvid(timelineVideo)
                                if (bvid == null) {
                                    Toast.makeText(context, "无法识别 BV 号", Toast.LENGTH_LONG).show()
                                    timelineBusy = false
                                    return@launch
                                }
                                val detail = botEngine.biliApiClient.fetchVideoDetail(bvid).getOrElse {
                                    Toast.makeText(context, it.message ?: "读取视频失败", Toast.LENGTH_LONG).show()
                                    timelineBusy = false
                                    return@launch
                                }
                                val subtitles = botEngine.biliApiClient.fetchSubtitles(bvid, detail.cid, detail.title)
                                if (subtitles.isEmpty()) {
                                    Toast.makeText(context, "该视频没有可用字幕，无法进行时间轴问答", Toast.LENGTH_LONG).show()
                                    timelineBusy = false
                                    return@launch
                                }
                                val contextText = selectTimelineContext(subtitles, timelineQuestion)
                                val response = botEngine.llmClient.chatCompletion(
                                    listOf(
                                        ChatMessage("system", "只根据给定视频字幕回答。每个关键结论必须标注 [分:秒] 时间点；资料不足时明确说无法从字幕确认。"),
                                        ChatMessage("user", "视频: ${detail.title} ($bvid)\n问题: ${timelineQuestion.trim()}\n\n字幕片段:\n$contextText")
                                    ),
                                    temperature = 0.1f
                                )
                                timelineAnswer = if (response.ok) response.content else "问答失败: ${response.error}"
                                timelineBusy = false
                            }
                        }, modifier = Modifier.fillMaxWidth()) {
                            if (timelineBusy) CircularProgressIndicator(Modifier.size(18.dp), color = Color.White, strokeWidth = 2.dp) else Icon(Icons.Default.QuestionAnswer, null)
                            Spacer(Modifier.width(6.dp))
                            Text("读取字幕并回答")
                        }
                        if (timelineAnswer.isNotBlank()) Text(timelineAnswer, style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }

            // 2. 知识深潜与概念拆解卡片
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                imageVector = Icons.Default.Search,
                                contentDescription = null,
                                tint = Color(0xFF7B61FF),
                                modifier = Modifier.size(24.dp)
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                text = "知识深潜 (Deep Dive)",
                                fontSize = 16.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }

                        Spacer(modifier = Modifier.height(10.dp))

                        OutlinedTextField(
                            value = deepDiveTopic,
                            onValueChange = { deepDiveTopic = it },
                            placeholder = { Text("输入想要深度探究的概念 (如 Transformer底层逻辑)", fontSize = 13.sp) },
                            singleLine = true,
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(modifier = Modifier.height(12.dp))

                        Button(
                            onClick = {
                                if (deepDiveTopic.isBlank()) return@Button
                                isDeepDiving = true
                                scope.launch {
                                    val prompt = "请对主题【$deepDiveTopic】进行系统化、深度知识拆解，包含核心概念、底层逻辑、应用场景与进阶思考。"
                                    val response = botEngine.llmClient.chatCompletion(
                                        listOf(
                                            ChatMessage("system", "你是一名顶级学者与架构师，请对主题进行系统化拆解。"),
                                            ChatMessage("user", prompt)
                                        )
                                    )
                                    isDeepDiving = false
                                    if (response.ok) {
                                        deepDiveResult = response.content
                                    } else {
                                        Toast.makeText(context, response.error ?: "生成失败", Toast.LENGTH_LONG).show()
                                    }
                                }
                            },
                            enabled = !isDeepDiving && deepDiveTopic.isNotBlank(),
                            modifier = Modifier.fillMaxWidth(),
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF7B61FF)),
                            shape = RoundedCornerShape(10.dp)
                        ) {
                            if (isDeepDiving) {
                                CircularProgressIndicator(modifier = Modifier.size(18.dp), color = Color.White, strokeWidth = 2.dp)
                                Spacer(modifier = Modifier.width(8.dp))
                                Text("AI 正在构筑知识体系...")
                            } else {
                                Icon(Icons.Default.AutoAwesome, contentDescription = null)
                                Spacer(modifier = Modifier.width(6.dp))
                                Text("启动深度知识拆解")
                            }
                        }

                        if (deepDiveResult.isNotEmpty()) {
                            Spacer(modifier = Modifier.height(14.dp))
                            HorizontalDivider()
                            Spacer(modifier = Modifier.height(14.dp))
                            Text(
                                text = deepDiveResult,
                                fontSize = 13.sp,
                                lineHeight = 20.sp,
                                color = MaterialTheme.colorScheme.onSurface
                            )
                        }
                    }
                }
            }

            item {
                Spacer(modifier = Modifier.height(20.dp))
            }
        }
    }
}

internal fun selectTimelineContext(items: List<com.bililearn.app.data.model.SubtitleItem>, question: String, limit: Int = 80): String {
    val keywords = question.lowercase().split(Regex("[^\\p{L}\\p{N}]+"))
        .filter { it.length >= 2 }.distinct()
    val scored = items.mapIndexed { index, item ->
        val score = keywords.count { item.content.contains(it, ignoreCase = true) }
        Triple(index, item, score)
    }
    val chosenIndices = scored.filter { it.third > 0 }
        .sortedByDescending { it.third }
        .take(limit / 3)
        .flatMap { (index, _, _) -> (index - 1..index + 1).filter { it in items.indices } }
        .distinct().sorted()
        .ifEmpty { items.indices.take(limit).toList() }
        .take(limit)
    return chosenIndices.joinToString("\n") { index ->
        val item = items[index]
        val seconds = item.from.toInt().coerceAtLeast(0)
        "[%02d:%02d] %s".format(seconds / 60, seconds % 60, item.content)
    }
}
