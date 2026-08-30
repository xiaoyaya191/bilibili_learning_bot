package com.bililearn.app.ui.tutor

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.LibraryBooks
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.database.entity.ChatMessageEntity
import com.bililearn.app.data.database.entity.ChatSessionEntity
import com.bililearn.app.data.model.ChatMessage
import com.bililearn.app.ui.theme.PrimaryOrange
import com.google.gson.Gson
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

/**
 * 优雅格式化 AI 导师回答，将粗糙的 Markdown 符号 (**、###、` 等) 转换为排版优美、字迹清爽的富文本
 */
@Composable
fun FormattedChatText(
    text: String,
    isUser: Boolean,
    modifier: Modifier = Modifier
) {
    if (isUser) {
        Text(
            text = text,
            fontSize = 14.sp,
            lineHeight = 21.sp,
            color = Color.White,
            modifier = modifier
        )
        return
    }

    val annotatedString = remember(text) {
        buildCleanAnnotatedString(text)
    }

    Text(
        text = annotatedString,
        fontSize = 14.sp,
        lineHeight = 22.sp,
        color = MaterialTheme.colorScheme.onSurface,
        modifier = modifier
    )
}

/**
 * 将原始 Markdown 字符串解析为清爽干净的 AnnotatedString (剔除生硬的符号，保留优雅版式)
 */
private fun buildCleanAnnotatedString(rawText: String): AnnotatedString {
    return buildAnnotatedString {
        val lines = rawText.lines()
        lines.forEachIndexed { lineIdx, rawLine ->
            var line = rawLine.trim()

            if (line.startsWith("```")) {
                line = line.replace("```json", "").replace("```markdown", "").replace("```", "").trim()
                if (line.isEmpty()) return@forEachIndexed
            }

            var isHeader = false
            if (line.startsWith("#")) {
                line = line.replace(Regex("^#+\\s*"), "")
                isHeader = true
            }

            if (line.startsWith("- ") || line.startsWith("* ")) {
                line = "• " + line.substring(2)
            }

            val boldPattern = Regex("\\*\\*(.*?)\\*\\*|__(.*?)__|`(.*?)`")
            var lastIndex = 0
            val matches = boldPattern.findAll(line).toList()

            if (isHeader) {
                pushStyle(SpanStyle(fontWeight = FontWeight.Bold, fontSize = 15.sp, color = Color(0xFFE65100)))
            }

            if (matches.isEmpty()) {
                append(line)
            } else {
                for (match in matches) {
                    val matchRange = match.range
                    if (matchRange.first > lastIndex) {
                        append(line.substring(lastIndex, matchRange.first))
                    }
                    val boldContent = match.groups[1]?.value ?: match.groups[2]?.value
                    val codeContent = match.groups[3]?.value

                    if (boldContent != null) {
                        withStyle(SpanStyle(fontWeight = FontWeight.Bold, color = PrimaryOrange)) {
                            append(boldContent)
                        }
                    } else if (codeContent != null) {
                        withStyle(
                            SpanStyle(
                                fontFamily = FontFamily.Monospace,
                                background = Color(0x18000000),
                                fontWeight = FontWeight.Medium
                            )
                        ) {
                            append(" $codeContent ")
                        }
                    }
                    lastIndex = matchRange.last + 1
                }
                if (lastIndex < line.length) {
                    append(line.substring(lastIndex))
                }
            }

            if (isHeader) {
                pop()
            }

            if (lineIdx < lines.size - 1) {
                append("\n")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TutorChatScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val botEngine = BiliLearnApplication.instance.botEngine
    val database = BiliLearnApplication.instance.database
    val gson = remember { Gson() }

    val allSessions by database.chatDao().getAllSessionsFlow().collectAsState(initial = emptyList())
    var currentSessionId by remember { mutableStateOf("") }

    // 初始化默认会话
    LaunchedEffect(allSessions) {
        if (allSessions.isEmpty()) {
            val defaultId = "session_${System.currentTimeMillis()}"
            database.chatDao().insertSession(
                ChatSessionEntity(
                    id = defaultId,
                    title = "学习交流与答疑",
                    createdAt = System.currentTimeMillis(),
                    updatedAt = System.currentTimeMillis()
                )
            )
            // 插入初始欢迎语
            database.chatDao().insertMessage(
                ChatMessageEntity(
                    sessionId = defaultId,
                    role = "assistant",
                    content = "你好呀！我是你的 BiliLearn 专属知识导师兼学习搭子。有什么想问的尽管告诉我吧，我会实时根据关键词精准检索你的知识库为你解答~"
                )
            )
            currentSessionId = defaultId
        } else if (currentSessionId.isEmpty() || allSessions.none { it.id == currentSessionId }) {
            currentSessionId = allSessions.first().id
        }
    }

    val currentSession = allSessions.firstOrNull { it.id == currentSessionId }
    val currentMessages by database.chatDao().getMessagesFlow(currentSessionId).collectAsState(initial = emptyList())

    var messageInput by remember { mutableStateOf("") }
    var isReplying by remember { mutableStateOf(false) }

    val listState = rememberLazyListState()

    var showSessionsSheet by remember { mutableStateOf(false) }
    var showDiaryDialog by remember { mutableStateOf(false) }
    var diaryContent by remember { mutableStateOf("") }
    var isGeneratingDiary by remember { mutableStateOf(false) }

    // 当有新消息时自动滚动到底部
    LaunchedEffect(currentMessages.size) {
        if (currentMessages.isNotEmpty()) {
            listState.animateScrollToItem(currentMessages.size - 1)
        }
    }

    Scaffold(
        topBar = {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                // 点击标题可快速切换会话窗口
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(8.dp))
                        .clickable { showSessionsSheet = true }
                        .padding(vertical = 4.dp, horizontal = 2.dp)
                ) {
                    Column {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                text = currentSession?.title ?: "知识导师",
                                fontSize = 18.sp,
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.primary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.widthIn(max = 180.dp)
                            )
                            Icon(
                                Icons.Default.ArrowDropDown,
                                contentDescription = "切换会话",
                                tint = MaterialTheme.colorScheme.primary
                            )
                        }
                        Text(
                            text = botEngine.personaEngine.getMoodDescription(),
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
                        )
                    }
                }

                Row(verticalAlignment = Alignment.CenterVertically) {
                    // 新建会话按钮
                    IconButton(
                        onClick = {
                            scope.launch {
                                val newSessionId = "session_${System.currentTimeMillis()}"
                                database.chatDao().insertSession(
                                    ChatSessionEntity(
                                        id = newSessionId,
                                        title = "新对话 ${allSessions.size + 1}",
                                        createdAt = System.currentTimeMillis(),
                                        updatedAt = System.currentTimeMillis()
                                    )
                                )
                                database.chatDao().insertMessage(
                                    ChatMessageEntity(
                                        sessionId = newSessionId,
                                        role = "assistant",
                                        content = "已开启新对话窗口！请提出您想深入探讨的问题，我会精准检索知识库为您解答~"
                                    )
                                )
                                currentSessionId = newSessionId
                                Toast.makeText(context, "已新建对话窗口", Toast.LENGTH_SHORT).show()
                            }
                        }
                    ) {
                        Icon(Icons.Default.AddComment, contentDescription = "新建对话", tint = PrimaryOrange)
                    }

                    // 历史会话抽屉
                    IconButton(onClick = { showSessionsSheet = true }) {
                        Icon(Icons.Default.Forum, contentDescription = "历史会话", tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f))
                    }

                    // 学习日记
                    IconButton(
                        onClick = {
                            showDiaryDialog = true
                            isGeneratingDiary = true
                            scope.launch {
                                val notes = database.knowledgeNoteDao().getAllNotes()
                                val titles = notes.map { it.title }
                                diaryContent = botEngine.personaEngine.generateDailyDiary(titles)
                                isGeneratingDiary = false
                            }
                        }
                    ) {
                        Icon(Icons.Default.Book, contentDescription = "学习日记", tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f))
                    }
                }
            }
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding()
        ) {
            // 对话列表
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Spacer(modifier = Modifier.height(8.dp))
                }

                items(currentMessages, key = { it.id }) { msg ->
                    val isUser = msg.role == "user"
                    val matchedTitles = msg.getMatchedTitles()

                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start
                        ) {
                            if (!isUser) {
                                Box(
                                    modifier = Modifier
                                        .size(32.dp)
                                        .clip(CircleShape)
                                        .background(PrimaryOrange.copy(alpha = 0.15f)),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Icon(
                                        Icons.Default.SmartToy,
                                        contentDescription = null,
                                        tint = PrimaryOrange,
                                        modifier = Modifier.size(18.dp)
                                    )
                                }
                                Spacer(modifier = Modifier.width(8.dp))
                            }

                            Card(
                                modifier = Modifier.widthIn(max = 295.dp),
                                shape = RoundedCornerShape(
                                    topStart = 14.dp,
                                    topEnd = 14.dp,
                                    bottomStart = if (isUser) 14.dp else 2.dp,
                                    bottomEnd = if (isUser) 2.dp else 14.dp
                                ),
                                colors = CardDefaults.cardColors(
                                    containerColor = if (isUser) PrimaryOrange else MaterialTheme.colorScheme.surface
                                )
                            ) {
                                Column(modifier = Modifier.padding(12.dp)) {
                                    FormattedChatText(
                                        text = msg.content,
                                        isUser = isUser
                                    )

                                    if (!isUser && matchedTitles.isNotEmpty()) {
                                        Spacer(modifier = Modifier.height(8.dp))
                                        HorizontalDivider(color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f))
                                        Spacer(modifier = Modifier.height(6.dp))
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            Icon(
                                                Icons.AutoMirrored.Filled.LibraryBooks,
                                                contentDescription = null,
                                                tint = PrimaryOrange,
                                                modifier = Modifier.size(12.dp)
                                            )
                                            Spacer(modifier = Modifier.width(4.dp))
                                            Text(
                                                text = "参考知识库: ${matchedTitles.joinToString("、") { "《${it.take(12)}...》" }}",
                                                fontSize = 11.sp,
                                                color = PrimaryOrange,
                                                fontWeight = FontWeight.Medium
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                if (isReplying) {
                    item {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp,
                                color = PrimaryOrange
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("正在检索知识库并思考...", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }

            // 底部输入栏 (自适应输入法弹出高度)
            Surface(
                modifier = Modifier.fillMaxWidth(),
                tonalElevation = 2.dp,
                color = MaterialTheme.colorScheme.surface
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    OutlinedTextField(
                        value = messageInput,
                        onValueChange = { messageInput = it },
                        placeholder = { Text("向助手提问已学知识...", fontSize = 13.sp) },
                        singleLine = false,
                        maxLines = 3,
                        shape = RoundedCornerShape(24.dp),
                        modifier = Modifier.weight(1f)
                    )

                    Spacer(modifier = Modifier.width(8.dp))

                    IconButton(
                        onClick = {
                            val text = messageInput.trim()
                            if (text.isEmpty() || isReplying || currentSessionId.isEmpty()) return@IconButton

                            messageInput = ""
                            isReplying = true

                            scope.launch {
                                // 1. 存入用户消息到 Room 数据库
                                database.chatDao().insertMessage(
                                    ChatMessageEntity(
                                        sessionId = currentSessionId,
                                        role = "user",
                                        content = text
                                    )
                                )

                                // 若当前为初始标题，自动根据提问更新会话名称
                                if (currentSession != null && (currentSession.title.startsWith("新对话") || currentSession.title == "学习交流与答疑")) {
                                    val newTitle = text.take(15)
                                    database.chatDao().updateSession(
                                        currentSession.copy(title = newTitle, updatedAt = System.currentTimeMillis())
                                    )
                                } else if (currentSession != null) {
                                    database.chatDao().updateSession(
                                        currentSession.copy(updatedAt = System.currentTimeMillis())
                                    )
                                }

                                // 2. 基于提问关键词精准检索本地知识库
                                val allNotes = database.knowledgeNoteDao().getAllNotes()
                                val searchResults = botEngine.ragEngine.searchRelevantNotes(text, allNotes, topK = 3)
                                val matchedTitles = searchResults.map { it.note.title }
                                val ragContext = botEngine.ragEngine.buildRagContext(searchResults)

                                val persona = botEngine.personaEngine.getActivePersona()
                                val sysPrompt = """
你是一名个人专属知识导师（当前人格: ${persona.name}）。
人格系统设定: ${persona.systemPrompt}
主人及关系设定: ${persona.ownerPrompt.ifBlank { "未设置" }}
行为边界: ${persona.rules.joinToString("；").ifBlank { "尊重用户并遵守安全边界" }}

【排版与对话准则】：
1. 请用自然生动、流畅亲切的口语化段落进行解答，像面对面的真人导师交流一样。
2. 严禁滥用生硬繁杂的 Markdown 标记符号（严禁输出多余的 ### 标题、复杂的列表符号或密集的 ** 符号），保持对话版面清爽自然、易读优美。
3. 重点概念可以直接用自然的分段或「引号」进行强调。

$ragContext
                                """.trimIndent()

                                val historyEntities = database.chatDao().getMessages(currentSessionId)
                                val chatMsgs = mutableListOf<ChatMessage>()
                                chatMsgs.add(ChatMessage("system", sysPrompt))
                                historyEntities.takeLast(6).forEach {
                                    chatMsgs.add(ChatMessage(it.role, it.content))
                                }

                                val res = botEngine.llmClient.chatCompletion(chatMsgs, temperature = 0.6f)
                                isReplying = false

                                val assistantReply = if (res.ok) {
                                    res.content
                                } else {
                                    "抱歉呀，连接大模型时出现了一点小状况: ${res.error}"
                                }

                                // 3. 存入导师回复到 Room 数据库
                                database.chatDao().insertMessage(
                                    ChatMessageEntity(
                                        sessionId = currentSessionId,
                                        role = "assistant",
                                        content = assistantReply,
                                        matchedTitlesJson = gson.toJson(matchedTitles)
                                    )
                                )
                            }
                        },
                        modifier = Modifier
                            .size(46.dp)
                            .clip(CircleShape)
                            .background(PrimaryOrange)
                    ) {
                        Icon(
                            Icons.AutoMirrored.Filled.Send,
                            contentDescription = "发送",
                            tint = Color.White,
                            modifier = Modifier.size(20.dp)
                        )
                    }
                }
            }
        }
    }

    // 历史会话管理 BottomSheet
    if (showSessionsSheet) {
        ModalBottomSheet(
            onDismissRequest = { showSessionsSheet = false },
            shape = RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp)
                    .padding(bottom = 32.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = "历史对话窗口 (${allSessions.size})",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold
                    )

                    Button(
                        onClick = {
                            scope.launch {
                                val newId = "session_${System.currentTimeMillis()}"
                                database.chatDao().insertSession(
                                    ChatSessionEntity(
                                        id = newId,
                                        title = "新对话 ${allSessions.size + 1}",
                                        createdAt = System.currentTimeMillis(),
                                        updatedAt = System.currentTimeMillis()
                                    )
                                )
                                database.chatDao().insertMessage(
                                    ChatMessageEntity(
                                        sessionId = newId,
                                        role = "assistant",
                                        content = "已开启新对话窗口！请提出您想探讨的问题~"
                                    )
                                )
                                currentSessionId = newId
                                showSessionsSheet = false
                            }
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange),
                        shape = RoundedCornerShape(8.dp),
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp)
                    ) {
                        Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("新建对话", fontSize = 13.sp)
                    }
                }

                Spacer(modifier = Modifier.height(14.dp))

                LazyColumn(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(allSessions, key = { it.id }) { session ->
                        val isSelected = session.id == currentSessionId
                        val dateStr = SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(session.updatedAt))

                        Card(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    currentSessionId = session.id
                                    showSessionsSheet = false
                                },
                            shape = RoundedCornerShape(10.dp),
                            colors = CardDefaults.cardColors(
                                containerColor = if (isSelected) PrimaryOrange.copy(alpha = 0.12f) else MaterialTheme.colorScheme.surface
                            )
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 14.dp, vertical = 12.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    modifier = Modifier.weight(1f)
                                ) {
                                    Icon(
                                        imageVector = if (isSelected) Icons.Default.ChatBubble else Icons.Default.ChatBubbleOutline,
                                        contentDescription = null,
                                        tint = if (isSelected) PrimaryOrange else Color.Gray,
                                        modifier = Modifier.size(18.dp)
                                    )
                                    Spacer(modifier = Modifier.width(10.dp))
                                    Column {
                                        Text(
                                            text = session.title,
                                            fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                                            fontSize = 14.sp,
                                            color = if (isSelected) PrimaryOrange else MaterialTheme.colorScheme.onSurface,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis
                                        )
                                        Text(
                                            text = "活跃: $dateStr",
                                            fontSize = 11.sp,
                                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f)
                                        )
                                    }
                                }

                                if (allSessions.size > 1) {
                                    IconButton(
                                        onClick = {
                                            scope.launch {
                                                database.chatDao().deleteSession(session.id)
                                                database.chatDao().deleteMessagesBySessionId(session.id)
                                                if (currentSessionId == session.id) {
                                                    val remaining = allSessions.filter { it.id != session.id }
                                                    if (remaining.isNotEmpty()) {
                                                        currentSessionId = remaining.first().id
                                                    }
                                                }
                                            }
                                        }
                                    ) {
                                        Icon(
                                            Icons.Default.DeleteOutline,
                                            contentDescription = "删除会话",
                                            tint = Color.Gray,
                                            modifier = Modifier.size(18.dp)
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (showDiaryDialog) {
        AlertDialog(
            onDismissRequest = { showDiaryDialog = false },
            title = { Text("AI 学习日记", fontWeight = FontWeight.Bold) },
            text = {
                if (isGeneratingDiary) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                        Spacer(modifier = Modifier.width(10.dp))
                        Text("AI 伴侣正在翻阅今日知识...")
                    }
                } else {
                    Text(text = diaryContent, fontSize = 14.sp, lineHeight = 22.sp)
                }
            },
            confirmButton = {
                TextButton(onClick = { showDiaryDialog = false }) {
                    Text("知道了", color = PrimaryOrange)
                }
            }
        )
    }
}
