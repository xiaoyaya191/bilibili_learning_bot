package com.bililearn.app.ui.tools

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.model.ChatMessage
import com.bililearn.app.data.model.CustomToolItem
import com.bililearn.app.data.model.SearchRecord
import com.bililearn.app.data.model.AgentMessageRecord
import com.bililearn.app.data.model.AgentSessionRecord
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID
import java.util.concurrent.TimeUnit
import com.bililearn.app.network.research.WebResearchClient
import com.bililearn.app.network.mcp.McpHttpClient

@Composable
fun ToolCenterScreen() {
    val tabs = listOf("深度搜索", "提示词", "技能", "Agent", "集成")
    var tab by remember { mutableIntStateOf(0) }
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
            Text("工具中心", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text("搜索、提示词、技能与外部服务", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        TabRow(tab) { tabs.forEachIndexed { index, label -> Tab(tab == index, { tab = index }, text = { Text(label) }) } }
        when (tab) {
            0 -> DeepSearchPanel()
            1 -> ToolItemsPanel("prompt")
            2 -> ToolItemsPanel("skill")
            3 -> AgentWorkspacePanel()
            else -> IntegrationPanel()
        }
    }
}

@Composable
private fun AgentWorkspacePanel() {
    val app = BiliLearnApplication.instance
    val store = app.toolboxStore
    val sessions by store.agentSessions.collectAsState()
    val items by store.items.collectAsState()
    val scope = rememberCoroutineScope()
    var selectedId by remember { mutableStateOf(sessions.firstOrNull()?.id.orEmpty()) }
    val session = sessions.firstOrNull { it.id == selectedId }
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var toolMode by remember { mutableStateOf(false) }
    val mcpServices = items.filter { it.kind == "mcp" && it.enabled }
    var selectedMcpId by remember { mutableStateOf(mcpServices.firstOrNull()?.id.orEmpty()) }
    var mcpTools by remember { mutableStateOf(emptyList<com.bililearn.app.network.mcp.McpToolInfo>()) }
    var selectedTool by remember { mutableStateOf("") }
    var arguments by remember { mutableStateOf("{}") }
    var toolError by remember { mutableStateOf("") }

    LaunchedEffect(sessions.size) {
        if (selectedId.isBlank() && sessions.isNotEmpty()) selectedId = sessions.first().id
    }
    LaunchedEffect(selectedMcpId) {
        val service = mcpServices.firstOrNull { it.id == selectedMcpId }
        if (service != null) {
            toolError = ""
            val result = McpHttpClient().listTools(service.content)
            mcpTools = result.getOrDefault(emptyList())
            selectedTool = mcpTools.firstOrNull()?.name.orEmpty()
            toolError = result.exceptionOrNull()?.message.orEmpty()
        } else mcpTools = emptyList()
    }

    fun append(role: String, content: String) {
        selectedId = store.appendAgentMessage(selectedId, content, role, content)
    }

    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Agent 工作区", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            FilledIconButton(onClick = {
                val fresh = AgentSessionRecord(UUID.randomUUID().toString(), "新会话")
                store.saveAgentSession(fresh)
                selectedId = fresh.id
            }) { Icon(Icons.Default.Add, "新建会话") }
        }
        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            items(sessions, key = { it.id }) { item ->
                InputChip(
                    selected = item.id == selectedId,
                    onClick = { selectedId = item.id },
                    label = { Text(item.title, maxLines = 1) },
                    trailingIcon = { IconButton(onClick = { store.deleteAgentSession(item.id) }, modifier = Modifier.size(24.dp)) { Icon(Icons.Default.Close, "删除会话", Modifier.size(16.dp)) } }
                )
            }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(session?.messages.orEmpty()) { message ->
                Surface(
                    modifier = Modifier.fillMaxWidth(if (message.role == "user") 0.9f else 1f),
                    shape = RoundedCornerShape(8.dp),
                    tonalElevation = if (message.role == "user") 2.dp else 1.dp
                ) { SelectionContainer { Text(message.content, Modifier.padding(10.dp)) } }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            FilterChip(selected = !toolMode, onClick = { toolMode = false }, label = { Text("对话") })
            FilterChip(selected = toolMode, onClick = { toolMode = true }, label = { Text("MCP 工具") })
        }
        if (!toolMode) {
            OutlinedTextField(input, { input = it }, label = { Text("消息") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
            Button(enabled = input.isNotBlank() && !busy, onClick = {
                val userText = input.trim()
                append("user", userText)
                input = ""
                scope.launch {
                    busy = true
                    val currentMessages = (session?.messages.orEmpty() + AgentMessageRecord("user", userText))
                    val persona = app.botEngine.personaEngine.getActivePersona()
                    val enabledContext = items.filter { it.enabled && it.kind in setOf("prompt", "skill") }
                        .joinToString("\n\n") { "${it.name}: ${it.content}" }
                    val system = buildString {
                        appendLine("你是 BiliLearn 的本地 Agent。回答必须明确区分事实、推断与未知项。")
                        if (persona.id.isNotBlank()) appendLine("用户自定义人格: ${persona.systemPrompt}")
                        if (enabledContext.isNotBlank()) appendLine("启用的提示词与技能:\n$enabledContext")
                    }
                    val response = app.botEngine.llmClient.chatCompletion(
                        listOf(ChatMessage("system", system)) + currentMessages.takeLast(20).map { ChatMessage(it.role, it.content) },
                        temperature = 0.3f
                    )
                    append("assistant", if (response.ok) response.content else "请求失败: ${response.error}")
                    busy = false
                }
            }, modifier = Modifier.fillMaxWidth()) {
                if (busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Icon(Icons.Default.Send, null)
                Text("发送")
            }
        } else {
            if (mcpServices.isEmpty()) Text("没有已启用的 MCP 服务", color = MaterialTheme.colorScheme.onSurfaceVariant)
            LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(mcpServices, key = { it.id }) { service ->
                    FilterChip(selected = selectedMcpId == service.id, onClick = { selectedMcpId = service.id }, label = { Text(service.name) })
                }
            }
            LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                items(mcpTools, key = { it.name }) { tool ->
                    FilterChip(selected = selectedTool == tool.name, onClick = { selectedTool = tool.name }, label = { Text(tool.name) })
                }
            }
            if (toolError.isNotBlank()) Text(toolError, color = MaterialTheme.colorScheme.error)
            OutlinedTextField(arguments, { arguments = it }, label = { Text("工具参数 JSON") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
            Button(enabled = selectedTool.isNotBlank() && !busy, onClick = {
                val service = mcpServices.firstOrNull { it.id == selectedMcpId } ?: return@Button
                scope.launch {
                    busy = true
                    append("user", "调用 MCP ${service.name}/$selectedTool，参数: $arguments")
                    val result = McpHttpClient().callTool(service.content, selectedTool, arguments)
                    append("tool", result.getOrElse { "工具调用失败: ${it.message}" })
                    busy = false
                }
            }, modifier = Modifier.fillMaxWidth()) { Text("执行并记录结果") }
        }
    }
}

@Composable
private fun DeepSearchPanel() {
    val app = BiliLearnApplication.instance
    val store = app.toolboxStore
    val history by store.searchHistory.collectAsState()
    val enabledPrompts by store.items.collectAsState()
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var running by remember { mutableStateOf(false) }
    var currentAnswer by remember { mutableStateOf("") }
    var sourceLinks by remember { mutableStateOf(emptyList<Pair<String, String>>()) }
    var error by remember { mutableStateOf<String?>(null) }
    Column(Modifier.fillMaxSize().padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), label = { Text("研究问题") }, minLines = 2)
        Button(
            onClick = {
                if (query.isBlank() || running) return@Button
                scope.launch {
                    running = true
                    error = null
                    val wiki = WebResearchClient().searchWikipedia(query).getOrDefault(emptyList())
                    val bili = app.botEngine.biliApiClient.searchVideos(query).getOrDefault(emptyList())
                    sourceLinks = wiki.map { it.title to it.url } + bili.map { it.title to "https://www.bilibili.com/video/${it.bvid}" }
                    val sources = buildString {
                        wiki.forEachIndexed { index, item -> appendLine("[W${index + 1}] ${item.title}: ${item.summary} (${item.url})") }
                        bili.forEachIndexed { index, item -> appendLine("[B${index + 1}] ${item.title} / ${item.ownerName} (https://www.bilibili.com/video/${item.bvid})") }
                    }
                    val promptContext = enabledPrompts.filter { it.kind == "prompt" && it.enabled }.joinToString("\n\n") { "${it.name}: ${it.content}" }
                    val response = app.botEngine.llmClient.chatCompletion(
                        listOf(
                            ChatMessage("system", "你是严谨的深度研究助手。只基于给定资料和通用知识作答，给出结构化结论，明确事实、推断和不确定项。引用资料时使用 [W1] 或 [B1] 标记。\n$promptContext"),
                            ChatMessage("user", "研究问题：${query.trim()}\n\n检索资料：\n$sources")
                        ),
                        temperature = 0.2f
                    )
                    if (response.ok) {
                        currentAnswer = response.content
                        store.addSearchRecord(SearchRecord(UUID.randomUUID().toString(), query.trim(), response.content))
                    } else error = response.error
                    running = false
                }
            },
            enabled = query.isNotBlank() && !running,
            modifier = Modifier.fillMaxWidth()
        ) {
            if (running) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Icon(Icons.Default.Search, null)
            Spacer(Modifier.width(8.dp))
            Text(if (running) "研究中" else "开始深度搜索")
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (currentAnswer.isNotBlank()) {
            Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) {
                SelectionContainer { Text(currentAnswer, Modifier.padding(12.dp)) }
            }
            if (sourceLinks.isNotEmpty()) {
                Text("检索来源", style = MaterialTheme.typography.titleSmall)
                sourceLinks.take(3).forEach { (title, url) ->
                    TextButton(onClick = { runCatching { app.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) } }, modifier = Modifier.fillMaxWidth()) {
                        Text(title, maxLines = 1, modifier = Modifier.weight(1f))
                        Icon(Icons.Default.OpenInNew, "打开来源")
                    }
                }
            }
        }
        Text("搜索历史", style = MaterialTheme.typography.titleMedium)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(history, key = { it.id }) { record ->
                Surface(onClick = { query = record.query; currentAnswer = record.answer }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) {
                    ListItem(
                        headlineContent = { Text(record.query, maxLines = 2) },
                        supportingContent = { Text(formatTime(record.createdAt)) },
                        trailingContent = { IconButton(onClick = { store.deleteSearchRecord(record.id) }) { Icon(Icons.Default.DeleteOutline, "删除搜索记录") } }
                    )
                }
            }
        }
    }
}

@Composable
private fun ToolItemsPanel(kind: String) {
    val store = BiliLearnApplication.instance.toolboxStore
    val allItems by store.items.collectAsState()
    val values = allItems.filter { it.kind == kind }
    var editor by remember { mutableStateOf<CustomToolItem?>(null) }
    var creating by remember { mutableStateOf(false) }
    var extracting by remember { mutableStateOf(false) }
    Scaffold(floatingActionButton = {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (kind == "skill") SmallFloatingActionButton(onClick = { extracting = true }) { Icon(Icons.Default.AutoAwesome, "AI 提取技能") }
            FloatingActionButton(onClick = { creating = true }) { Icon(Icons.Default.Add, "新增") }
        }
    }) { padding ->
        if (values.isEmpty()) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) { Text(if (kind == "prompt") "还没有自定义提示词" else "还没有自定义技能") }
        } else {
            LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(values, key = { it.id }) { item ->
                    Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) {
                        ListItem(
                            headlineContent = { Text(item.name, fontWeight = FontWeight.SemiBold) },
                            supportingContent = { Text(item.content, maxLines = 3) },
                            leadingContent = { Switch(item.enabled, { store.saveItem(item.copy(enabled = it, updatedAt = System.currentTimeMillis())) }) },
                            trailingContent = { IconButton(onClick = { editor = item }) { Icon(Icons.Default.Edit, "编辑") } }
                        )
                    }
                }
            }
        }
    }
    if (creating || editor != null) {
        ToolItemEditor(kind, editor, onDismiss = { creating = false; editor = null }, onSave = { store.saveItem(it); creating = false; editor = null }, onDelete = { store.deleteItem(it); editor = null })
    }
    if (extracting) {
        SkillExtractionDialog(onDismiss = { extracting = false }) {
            store.saveItem(it)
            extracting = false
        }
    }
}

@Composable
private fun SkillExtractionDialog(onDismiss: () -> Unit, onSave: (CustomToolItem) -> Unit) {
    val app = BiliLearnApplication.instance
    val scope = rememberCoroutineScope()
    var name by remember { mutableStateOf("") }
    var source by remember { mutableStateOf("") }
    var result by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text("AI 提取技能") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("技能名称") }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(source, { source = it }, label = { Text("原始资料或操作说明") }, minLines = 5, modifier = Modifier.fillMaxWidth())
                Button(enabled = source.isNotBlank() && !busy, onClick = {
                    scope.launch {
                        busy = true
                        val response = app.botEngine.llmClient.chatCompletion(
                            listOf(
                                ChatMessage("system", "把资料整理为可复用的操作技能。输出目标、适用条件、逐步流程、失败处理和验证标准，不添加资料中不存在的事实。"),
                                ChatMessage("user", source.trim())
                            ),
                            temperature = 0.2f
                        )
                        result = if (response.ok) response.content else "提取失败: ${response.error}"
                        busy = false
                    }
                }) {
                    if (busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    Text("提取")
                }
                if (result.isNotBlank()) OutlinedTextField(result, { result = it }, label = { Text("技能内容") }, minLines = 6, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = {
            TextButton(enabled = name.isNotBlank() && result.isNotBlank() && !result.startsWith("提取失败"), onClick = {
                onSave(CustomToolItem(UUID.randomUUID().toString(), "skill", name.trim(), result.trim()))
            }) { Text("保存技能") }
        },
        dismissButton = { TextButton(enabled = !busy, onClick = onDismiss) { Text("取消") } }
    )
}

@Composable
private fun IntegrationPanel() {
    val context = LocalContext.current
    val store = BiliLearnApplication.instance.toolboxStore
    val allItems by store.items.collectAsState()
    val values = allItems.filter { it.kind in setOf("integration", "agent", "mcp") }
    val scope = rememberCoroutineScope()
    var editor by remember { mutableStateOf<CustomToolItem?>(null) }
    var creating by remember { mutableStateOf(false) }
    var creationKind by remember { mutableStateOf("mcp") }
    var callTarget by remember { mutableStateOf<CustomToolItem?>(null) }
    var status by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    Column(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Agent 与 MCP 服务", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            TextButton(onClick = { creationKind = "agent"; creating = true }) { Text("新增 Agent") }
            FilledIconButton(onClick = { creationKind = "mcp"; creating = true }) { Icon(Icons.Default.Add, "新增 MCP") }
        }
        Text("MCP 使用 Streamable HTTP JSON-RPC 初始化并读取工具；Agent 端点执行 HTTP 健康检查。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(values, key = { it.id }) { item ->
                Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) {
                    ListItem(
                        headlineContent = { Text(item.name) },
                        supportingContent = { Text(status[item.id] ?: item.content, maxLines = 2) },
                        overlineContent = { Text(if (item.kind == "mcp") "MCP" else "Agent") },
                        leadingContent = { Icon(if (item.kind == "mcp") Icons.Default.Hub else Icons.Default.SmartToy, null) },
                        trailingContent = {
                            Row {
                                IconButton(onClick = {
                                    scope.launch {
                                        status = status + (item.id to "检测中")
                                        status = if (item.kind == "mcp") {
                                            val result = McpHttpClient().listTools(item.content)
                                            status + (item.id to result.fold(
                                                onSuccess = { tools -> "协议连接成功，发现 ${tools.size} 个工具: ${tools.take(4).joinToString { it.name }}" },
                                                onFailure = { "MCP 连接失败: ${it.message}" }
                                            ))
                                        } else status + (item.id to testEndpoint(item.content))
                                    }
                                }) { Icon(Icons.Default.NetworkCheck, "测试连接") }
                                if (item.kind == "mcp") {
                                    IconButton(onClick = { callTarget = item }) { Icon(Icons.Default.PlayArrow, "调用 MCP 工具") }
                                }
                                IconButton(onClick = { runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(item.content))) } }) { Icon(Icons.Default.OpenInNew, "在外部打开") }
                                IconButton(onClick = { editor = item }) { Icon(Icons.Default.Edit, "编辑") }
                            }
                        }
                    )
                }
            }
        }
    }
    if (creating || editor != null) {
        ToolItemEditor(editor?.kind ?: creationKind, editor, onDismiss = { creating = false; editor = null }, onSave = { store.saveItem(it); creating = false; editor = null }, onDelete = { store.deleteItem(it); editor = null })
    }
    callTarget?.let { target -> McpCallDialog(target, onDismiss = { callTarget = null }) }
}

@Composable
private fun McpCallDialog(target: CustomToolItem, onDismiss: () -> Unit) {
    val scope = rememberCoroutineScope()
    var tools by remember { mutableStateOf(emptyList<com.bililearn.app.network.mcp.McpToolInfo>()) }
    var toolName by remember { mutableStateOf("") }
    var arguments by remember { mutableStateOf("{}") }
    var output by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(true) }
    LaunchedEffect(target.id) {
        val result = McpHttpClient().listTools(target.content)
        tools = result.getOrDefault(emptyList())
        toolName = tools.firstOrNull()?.name.orEmpty()
        output = result.exceptionOrNull()?.message.orEmpty()
        busy = false
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("调用 ${target.name}") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (busy) CircularProgressIndicator(Modifier.size(22.dp))
                if (tools.isNotEmpty()) {
                    Text("可用工具", fontWeight = FontWeight.Bold)
                    tools.forEach { tool ->
                        FilterChip(selected = toolName == tool.name, onClick = { toolName = tool.name }, label = { Text(tool.name) })
                        if (toolName == tool.name && tool.description.isNotBlank()) Text(tool.description, style = MaterialTheme.typography.bodySmall)
                    }
                    OutlinedTextField(arguments, { arguments = it }, label = { Text("参数 JSON") }, minLines = 3, modifier = Modifier.fillMaxWidth())
                    Button(enabled = !busy && toolName.isNotBlank(), onClick = {
                        scope.launch {
                            busy = true
                            val result = McpHttpClient().callTool(target.content, toolName, arguments)
                            output = result.getOrElse { "调用失败: ${it.message}" }
                            busy = false
                        }
                    }) { Text("执行工具") }
                }
                if (output.isNotBlank()) SelectionContainer { Text(output) }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } }
    )
}

@Composable
private fun ToolItemEditor(kind: String, old: CustomToolItem?, onDismiss: () -> Unit, onSave: (CustomToolItem) -> Unit, onDelete: (String) -> Unit) {
    var name by remember(old) { mutableStateOf(old?.name.orEmpty()) }
    var content by remember(old) { mutableStateOf(old?.content.orEmpty()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (old == null) "新增配置" else "编辑配置") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("名称") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                OutlinedTextField(content, { content = it }, label = { Text(if (kind in setOf("integration", "agent", "mcp")) "服务地址" else "内容") }, modifier = Modifier.fillMaxWidth(), minLines = if (kind in setOf("integration", "agent", "mcp")) 1 else 5)
            }
        },
        confirmButton = { Button(onClick = { if (name.isNotBlank() && content.isNotBlank()) onSave(CustomToolItem(old?.id ?: UUID.randomUUID().toString(), kind, name.trim(), content.trim(), old?.enabled ?: true)) }) { Text("保存") } },
        dismissButton = { Row { if (old != null) TextButton(onClick = { onDelete(old.id) }) { Text("删除", color = MaterialTheme.colorScheme.error) }; TextButton(onClick = onDismiss) { Text("取消") } } }
    )
}

private suspend fun testEndpoint(url: String): String = withContext(Dispatchers.IO) {
    if (!url.startsWith("http://") && !url.startsWith("https://")) return@withContext "地址必须以 http:// 或 https:// 开头"
    runCatching {
        val client = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(10, TimeUnit.SECONDS).build()
        client.newCall(Request.Builder().url(url).get().build()).execute().use { "HTTP ${it.code}  ${if (it.isSuccessful) "连接正常" else "服务返回错误"}" }
    }.getOrElse { "连接失败: ${it.message}" }
}

private fun formatTime(value: Long): String = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm").format(Instant.ofEpochMilli(value).atZone(ZoneId.systemDefault()))
