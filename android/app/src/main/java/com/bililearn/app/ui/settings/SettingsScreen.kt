package com.bililearn.app.ui.settings

import android.content.Intent
import android.app.Activity
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.model.ChatMessage
import com.bililearn.app.data.model.PersonaProfile
import com.bililearn.app.ui.theme.BiliPink
import com.bililearn.app.ui.theme.PrimaryOrange
import com.bililearn.app.ui.theme.PurpleAccent
import com.bililearn.app.ui.theme.SuccessGreen
import kotlinx.coroutines.launch
import java.util.UUID
import com.bililearn.app.service.ReminderWorker
import com.bililearn.app.service.BiliBotService
import com.bililearn.app.data.database.BackupPreview

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onNavigateToReviews: () -> Unit = {}
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val botEngine = BiliLearnApplication.instance.botEngine
    val database = BiliLearnApplication.instance.database
    val prefs = botEngine.preferences

    val isBiliLoggedIn by prefs.biliLoggedInFlow.collectAsState()
    val activePresetKey by prefs.activePresetFlow.collectAsState()
    val currentBrainModel by prefs.brainModelFlow.collectAsState()
    val availableModels by prefs.availableModelsFlow.collectAsState()
    val personaProfiles by prefs.personaProfilesFlow.collectAsState()
    val activePersonaKey by prefs.activePersonaKeyFlow.collectAsState()
    val interests by botEngine.interestEngine.interestsFlow.collectAsState()
    val exclusions by botEngine.interestEngine.exclusionsFlow.collectAsState()
    val pendingReviewCount by database.actionReviewDao().getPendingCountFlow().collectAsState(initial = 0)

    var apiKeyInput by remember { mutableStateOf(prefs.getApiKey()) }
    var baseUrlInput by remember { mutableStateOf(prefs.getBaseUrl()) }
    var modelInput by remember { mutableStateOf(currentBrainModel) }
    var showApiKey by remember { mutableStateOf(false) }

    var isFetchingModels by remember { mutableStateOf(false) }
    var fetchModelMsg by remember { mutableStateOf<String?>(null) }
    var showModelPickerDialog by remember { mutableStateOf(false) }

    var isTestingApi by remember { mutableStateOf(false) }
    var apiTestResultMsg by remember { mutableStateOf<String?>(null) }

    var showLoginDialog by remember { mutableStateOf(false) }
    var showAddInterestDialog by remember { mutableStateOf(false) }
    var showAddExclusionDialog by remember { mutableStateOf(false) }
    var newInterestInput by remember { mutableStateOf("") }
    var newInterestWeight by remember { mutableFloatStateOf(1.0f) }
    var newExclusionInput by remember { mutableStateOf("") }
    var showResetSettingsConfirm by remember { mutableStateOf(false) }
    var showFactoryResetConfirm by remember { mutableStateOf(false) }
    var showFactoryResetFinal by remember { mutableStateOf(false) }
    var showPersonaEditor by remember { mutableStateOf(false) }
    var editingPersonaId by remember { mutableStateOf<String?>(null) }
    var personaNameInput by remember { mutableStateOf("") }
    var personaDescriptionInput by remember { mutableStateOf("") }
    var personaPromptInput by remember { mutableStateOf("") }
    var personaOwnerInput by remember { mutableStateOf("") }
    var personaRulesInput by remember { mutableStateOf("") }
    var pendingRestore by remember { mutableStateOf<Pair<String, BackupPreview>?>(null) }

    val importSettingsLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri != null) {
            scope.launch {
                val imported = runCatching {
                    context.contentResolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }
                }.getOrNull()
                if (imported != null && prefs.importSettingsJson(imported)) {
                    apiKeyInput = prefs.getApiKey()
                    baseUrlInput = prefs.getBaseUrl()
                    modelInput = prefs.getBrainModel()
                    Toast.makeText(context, "配置导入成功", Toast.LENGTH_SHORT).show()
                } else {
                    Toast.makeText(context, "配置导入失败，请检查文件格式", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    val exportSettingsLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/json")
    ) { uri: Uri? ->
        if (uri != null) {
            scope.launch {
                val saved = runCatching {
                    context.contentResolver.openOutputStream(uri)?.bufferedWriter()?.use { it.write(prefs.exportSettingsJson()) }
                    true
                }.getOrDefault(false)
                Toast.makeText(context, if (saved) "配置导出成功" else "配置导出失败", Toast.LENGTH_SHORT).show()
            }
        }
    }

    val exportDatabaseLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/json")
    ) { uri: Uri? ->
        if (uri != null) scope.launch {
            val saved = runCatching {
                val json = BiliLearnApplication.instance.databaseBackupManager.exportBackupJson()
                context.contentResolver.openOutputStream(uri)?.bufferedWriter()?.use { it.write(json) }
                    ?: error("write failed")
            }.isSuccess
            Toast.makeText(context, if (saved) "完整数据导出成功" else "完整数据导出失败", Toast.LENGTH_SHORT).show()
        }
    }

    val importDatabaseLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri != null) scope.launch {
            val pending = runCatching {
                val json = context.contentResolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }
                    ?: error("read failed")
                json to BiliLearnApplication.instance.databaseBackupManager.inspectBackup(json)
            }.getOrNull()
            if (pending != null) pendingRestore = pending
            else Toast.makeText(context, "无法读取备份或格式不受支持", Toast.LENGTH_SHORT).show()
        }
    }

    var autoLearnEnabled by remember { mutableStateOf(prefs.isAutoLearnEnabled()) }
    var checkToviewEnabled by remember { mutableStateOf(prefs.isCheckToviewEnabled()) }
    var checkPopularEnabled by remember { mutableStateOf(prefs.isCheckPopularEnabled()) }
    var requireApproval by remember { mutableStateOf(prefs.isRequireApprovalForActions()) }
    var wifiOnly by remember { mutableStateOf(prefs.isWifiOnlyEnabled()) }
    var autoEvolveInterests by remember { mutableStateOf(botEngine.interestEngine.isAutoEvolveEnabled()) }
    var visionModeEnabled by remember { mutableStateOf(prefs.isVisionModeEnabled()) }
    var readCommentsEnabled by remember { mutableStateOf(prefs.isReadCommentsEnabled()) }
    var readDanmakuEnabled by remember { mutableStateOf(prefs.isReadDanmakuEnabled()) }

    Scaffold(
        topBar = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 12.dp)
            ) {
                Text(
                    text = "系统与配置",
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(
                    text = "实时模型 / 兴趣画像 / B 站账号 / 自定义人格",
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
            // 1. 兴趣画像与反垃圾过滤引擎 (用户关注功能)
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Default.Category, contentDescription = null, tint = PrimaryOrange)
                                Spacer(modifier = Modifier.width(8.dp))
                                Text("学习兴趣画像与过滤策略", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                            }
                            IconButton(onClick = { showAddInterestDialog = true }) {
                                Icon(Icons.Default.AddCircle, contentDescription = "添加兴趣", tint = PrimaryOrange)
                            }
                        }

                        Text(
                            text = "机器人巡检视频时优先筛选高匹配度内容，自动过滤不感兴趣或低质视频：",
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
                        )
                        Spacer(modifier = Modifier.height(10.dp))

                        Text("⭐ 核心兴趣标签 (加权优先学习):", fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                        Spacer(modifier = Modifier.height(6.dp))

                        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            items(interests) { tag ->
                                val weightLabel = when {
                                    tag.weight >= 1.4f -> "高"
                                    tag.weight >= 1.0f -> "中"
                                    else -> "低"
                                }
                                InputChip(
                                    selected = true,
                                    onClick = {
                                        botEngine.interestEngine.removeInterest(tag.name)
                                        Toast.makeText(context, "已移除: ${tag.name}", Toast.LENGTH_SHORT).show()
                                    },
                                    label = { Text("$weightLabel ${tag.name}", fontSize = 12.sp) },
                                    trailingIcon = { Icon(Icons.Default.Close, contentDescription = null, modifier = Modifier.size(14.dp)) }
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(12.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("负向屏蔽词 (直接跳过不学):", fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                            TextButton(onClick = { showAddExclusionDialog = true }) {
                                Text("+ 添加屏蔽词", fontSize = 12.sp, color = Color(0xFFD14343))
                            }
                        }

                        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            items(exclusions) { ex ->
                                InputChip(
                                    selected = false,
                                    onClick = {
                                        botEngine.interestEngine.removeExclusion(ex)
                                        Toast.makeText(context, "已取消屏蔽: $ex", Toast.LENGTH_SHORT).show()
                                    },
                                    label = { Text(ex, fontSize = 12.sp, color = Color(0xFFD14343)) },
                                    trailingIcon = { Icon(Icons.Default.Close, contentDescription = null, modifier = Modifier.size(14.dp)) }
                                )
                            }
                        }

                        Spacer(modifier = Modifier.height(8.dp))

                        SwitchRow("随学习过程自动进化兴趣", "根据日常学习与提取的标签动态强化兴趣画像", autoEvolveInterests) {
                            autoEvolveInterests = it
                            botEngine.interestEngine.setAutoEvolveEnabled(it)
                        }
                    }
                }
            }

            // 2. AI 伴侣人设与风格定制
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Icon(Icons.Default.TheaterComedy, contentDescription = null, tint = PrimaryOrange)
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("自定义人格与对话风格", fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                            IconButton(onClick = {
                                editingPersonaId = null
                                personaNameInput = ""
                                personaDescriptionInput = ""
                                personaPromptInput = ""
                                personaOwnerInput = ""
                                personaRulesInput = ""
                                showPersonaEditor = true
                            }) {
                                Icon(Icons.Default.AddCircle, contentDescription = "新建人格", tint = PrimaryOrange)
                            }
                        }

                        Spacer(modifier = Modifier.height(10.dp))

                        personaProfiles.forEach { persona ->
                            val isSelected = activePersonaKey == persona.id
                            Card(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 4.dp)
                                    .clickable {
                                        prefs.setActivePersonaKey(persona.id)
                                        Toast.makeText(context, "已切换为人设: ${persona.name}", Toast.LENGTH_SHORT).show()
                                    },
                                shape = RoundedCornerShape(10.dp),
                                colors = CardDefaults.cardColors(
                                    containerColor = if (isSelected) PrimaryOrange.copy(alpha = 0.12f) else MaterialTheme.colorScheme.background
                                )
                            ) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(12.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(text = persona.name, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                                        Text(text = persona.description, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f))
                                    }
                                    if (!persona.isBuiltIn) {
                                        IconButton(onClick = {
                                            editingPersonaId = persona.id
                                            personaNameInput = persona.name
                                            personaDescriptionInput = persona.description
                                            personaPromptInput = persona.systemPrompt
                                            personaOwnerInput = persona.ownerPrompt
                                            personaRulesInput = persona.rules.joinToString("\n")
                                            showPersonaEditor = true
                                        }) {
                                            Icon(Icons.Default.Edit, contentDescription = "编辑 ${persona.name}", modifier = Modifier.size(18.dp))
                                        }
                                    }
                                    if (isSelected) {
                                        Icon(Icons.Default.CheckCircle, contentDescription = null, tint = PrimaryOrange, modifier = Modifier.size(20.dp))
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 3. AI 模型与服务商配置 (支持官方实时拉取)
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.AutoAwesome, contentDescription = null, tint = PrimaryOrange)
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("AI 大模型配置", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                        }

                        Spacer(modifier = Modifier.height(12.dp))

                        // API Key 输入框
                        OutlinedTextField(
                            value = apiKeyInput,
                            onValueChange = {
                                apiKeyInput = it
                                prefs.setApiKey(it)
                            },
                            label = { Text("API Key") },
                            placeholder = { Text("sk-...") },
                            singleLine = true,
                            visualTransformation = if (showApiKey) VisualTransformation.None else PasswordVisualTransformation(),
                            trailingIcon = {
                                IconButton(onClick = { showApiKey = !showApiKey }) {
                                    Icon(
                                        if (showApiKey) Icons.Default.Visibility else Icons.Default.VisibilityOff,
                                        contentDescription = null
                                    )
                                }
                            },
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(modifier = Modifier.height(10.dp))

                        // Base URL 输入框
                        OutlinedTextField(
                            value = baseUrlInput,
                            onValueChange = {
                                baseUrlInput = it
                                prefs.setBaseUrl(it)
                            },
                            label = { Text("Base URL") },
                            placeholder = { Text("https://api.openai.com/v1") },
                            singleLine = true,
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(modifier = Modifier.height(10.dp))

                        // 当前选中的模型与实时拉取
                        OutlinedTextField(
                            value = modelInput,
                            onValueChange = {
                                modelInput = it
                                prefs.setBrainModel(it)
                            },
                            label = { Text("核心认知模型 (Model)") },
                            placeholder = { Text("输入或从官方列表选择模型") },
                            singleLine = true,
                            trailingIcon = {
                                IconButton(onClick = {
                                    if (availableModels.isNotEmpty()) {
                                        showModelPickerDialog = true
                                    } else {
                                        Toast.makeText(context, "请先点击下方【拉取官方模型列表】", Toast.LENGTH_SHORT).show()
                                    }
                                }) {
                                    Icon(
                                        Icons.Default.ArrowDropDownCircle,
                                        contentDescription = "选择模型",
                                        tint = PrimaryOrange
                                    )
                                }
                            },
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(modifier = Modifier.height(12.dp))

                        // 【核心功能】实时拉取官方模型列表按钮
                        Button(
                            onClick = {
                                if (apiKeyInput.isBlank()) {
                                    Toast.makeText(context, "请先填入 API Key", Toast.LENGTH_SHORT).show()
                                    return@Button
                                }
                                isFetchingModels = true
                                fetchModelMsg = null
                                scope.launch {
                                    val res = botEngine.llmClient.fetchAvailableModels(apiKeyInput, baseUrlInput)
                                    isFetchingModels = false
                                    if (res.isSuccess) {
                                        val models = res.getOrThrow()
                                        fetchModelMsg = "成功：已拉取 ${models.size} 个官方可用模型，点击右侧图标选择"
                                        showModelPickerDialog = true
                                    } else {
                                        fetchModelMsg = "失败：${res.exceptionOrNull()?.message}"
                                    }
                                }
                            },
                            enabled = !isFetchingModels && apiKeyInput.isNotBlank(),
                            modifier = Modifier.fillMaxWidth(),
                            colors = ButtonDefaults.buttonColors(containerColor = PurpleAccent),
                            shape = RoundedCornerShape(10.dp)
                        ) {
                            if (isFetchingModels) {
                                CircularProgressIndicator(modifier = Modifier.size(16.dp), color = Color.White, strokeWidth = 2.dp)
                                Spacer(modifier = Modifier.width(8.dp))
                                Text("正在向官方服务器拉取最新模型列表...")
                            } else {
                                Icon(Icons.Default.CloudSync, contentDescription = null)
                                Spacer(modifier = Modifier.width(6.dp))
                                Text("实时拉取官方/服务商模型列表")
                            }
                        }

                        if (fetchModelMsg != null) {
                            Spacer(modifier = Modifier.height(6.dp))
                            Text(
                                text = fetchModelMsg!!,
                                fontSize = 12.sp,
                                color = if (fetchModelMsg!!.startsWith("成功")) SuccessGreen else Color(0xFFE53935)
                            )
                        }

                        Spacer(modifier = Modifier.height(8.dp))

                        // 测试连接按钮
                        OutlinedButton(
                            onClick = {
                                isTestingApi = true
                                apiTestResultMsg = null
                                scope.launch {
                                    val start = System.currentTimeMillis()
                                    val res = botEngine.llmClient.chatCompletion(
                                        listOf(ChatMessage("user", "Hello! Please reply 'OK'.")),
                                        temperature = 0.1f
                                    )
                                    val elapsed = System.currentTimeMillis() - start
                                    isTestingApi = false
                                    if (res.ok) {
                                        apiTestResultMsg = "成功：当前模型 ${prefs.getBrainModel()}，耗时 ${elapsed}ms"
                                    } else {
                                        apiTestResultMsg = "失败：${res.error}"
                                    }
                                }
                            },
                            enabled = !isTestingApi && apiKeyInput.isNotBlank(),
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(10.dp)
                        ) {
                            if (isTestingApi) {
                                CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                                Spacer(modifier = Modifier.width(8.dp))
                                Text("正在测试接口响应...")
                            } else {
                                Icon(Icons.Default.Speed, contentDescription = null)
                                Spacer(modifier = Modifier.width(6.dp))
                                Text("测试当前模型连通性与延迟")
                            }
                        }

                        if (apiTestResultMsg != null) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(
                                text = apiTestResultMsg!!,
                                fontSize = 12.sp,
                                color = if (apiTestResultMsg!!.startsWith("成功")) SuccessGreen else Color(0xFFE53935)
                            )
                        }
                    }
                }
            }

            // 4. Bilibili 账号管理
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.AccountCircle, contentDescription = null, tint = BiliPink)
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("Bilibili 账号认证", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                        }

                        Spacer(modifier = Modifier.height(12.dp))

                        if (isBiliLoggedIn) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                val avatar = prefs.getUserAvatar()
                                if (avatar.isNotEmpty()) {
                                    AsyncImage(
                                        model = avatar,
                                        contentDescription = "Avatar",
                                        modifier = Modifier
                                            .size(48.dp)
                                            .clip(CircleShape)
                                    )
                                } else {
                                    Box(
                                        modifier = Modifier
                                            .size(48.dp)
                                            .clip(CircleShape)
                                            .background(BiliPink.copy(alpha = 0.2f)),
                                        contentAlignment = Alignment.Center
                                    ) {
                                        Icon(Icons.Default.Person, contentDescription = null, tint = BiliPink)
                                    }
                                }

                                Spacer(modifier = Modifier.width(12.dp))

                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = prefs.getUserName().ifEmpty { "已登录用户" },
                                        fontWeight = FontWeight.Bold,
                                        fontSize = 15.sp
                                    )
                                    Text(
                                        text = "UID: ${prefs.getOwnerMid()}",
                                        fontSize = 12.sp,
                                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f)
                                    )
                                }

                                OutlinedButton(
                                    onClick = {
                                        prefs.clearBiliCookies()
                                        Toast.makeText(context, "已退出 B 站登录", Toast.LENGTH_SHORT).show()
                                    },
                                    shape = RoundedCornerShape(8.dp)
                                ) {
                                    Text("退出", color = Color(0xFFD14343))
                                }
                            }
                        } else {
                            Text(
                                text = "登录 B站 账号后，机器人可自动巡检你的【稍后再看】与【关注UP动态】。",
                                fontSize = 13.sp,
                                lineHeight = 18.sp,
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f)
                            )
                            Spacer(modifier = Modifier.height(12.dp))
                            Button(
                                onClick = { showLoginDialog = true },
                                modifier = Modifier.fillMaxWidth(),
                                colors = ButtonDefaults.buttonColors(containerColor = BiliPink),
                                shape = RoundedCornerShape(10.dp)
                            ) {
                                Icon(Icons.Default.Login, contentDescription = null)
                                Spacer(modifier = Modifier.width(6.dp))
                                Text("登录 B站 (支持免扫码/扫码)")
                            }
                        }
                    }
                }
            }

            // 5. 自动化策略与行为审批
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Tune, contentDescription = null, tint = PrimaryOrange)
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("自动化巡检策略", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                        }

                        Spacer(modifier = Modifier.height(8.dp))

                        SwitchRow("自动后台学习巡检", "常驻后台巡检待学视频并提取知识", autoLearnEnabled) {
                            autoLearnEnabled = it
                            prefs.setAutoLearnEnabled(it)
                        }
                        SwitchRow("巡检【稍后再看】队列", "优先提取用户收藏的待看视频", checkToviewEnabled) {
                            checkToviewEnabled = it
                            prefs.setCheckToviewEnabled(it)
                        }
                        SwitchRow("巡检【热门知识推荐】", "稍后再看为空时自动探索优质知识流", checkPopularEnabled) {
                            checkPopularEnabled = it
                            prefs.setCheckPopularEnabled(it)
                        }
                        SwitchRow("AI 互动需人工审批", "点赞、投币、评论等操作进入待审核列表", requireApproval) {
                            requireApproval = it
                            prefs.setRequireApprovalForActions(it)
                        }
                        SwitchRow("仅在 Wi-Fi 下下载与分析", "移动网络下自动暂停大流量巡检", wifiOnly) {
                            wifiOnly = it
                            prefs.setWifiOnlyEnabled(it)
                        }

                        Divider(modifier = Modifier.padding(vertical = 8.dp), color = MaterialTheme.colorScheme.outlineVariant)

                        SwitchRow("视觉模型抽帧感知", "捕获视频全时长关键帧拼图，供视觉模型观察PPT/代码/板书", visionModeEnabled) {
                            visionModeEnabled = it
                            prefs.setVisionModeEnabled(it)
                        }
                        SwitchRow("研读评论区与UP置顶", "提取UP主置顶笔记、时间轴课代表讨论与热评精髓", readCommentsEnabled) {
                            readCommentsEnabled = it
                            prefs.setReadCommentsEnabled(it)
                        }
                        SwitchRow("捕获高能弹幕反应", "分析全片弹幕密集峰值与观众高能反馈点", readDanmakuEnabled) {
                            readDanmakuEnabled = it
                            prefs.setReadDanmakuEnabled(it)
                        }

                        if (requireApproval) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Button(
                                onClick = onNavigateToReviews,
                                modifier = Modifier.fillMaxWidth(),
                                colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange),
                                shape = RoundedCornerShape(10.dp)
                            ) {
                                Icon(Icons.Default.Inbox, contentDescription = null)
                                Spacer(modifier = Modifier.width(6.dp))
                                Text("进入 AI 行为审核中心 ($pendingReviewCount 项待确认)")
                            }
                        }
                    }
                }
            }

            // 6. 知识库数据安全与镜像自愈
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Security, contentDescription = null, tint = PrimaryOrange)
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("知识库安全与镜像自愈", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                        }

                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = "系统已开启【双写镜像自动备份】。即使 APP 版本迭代升级或数据库重建，系统也会在开机时自动从本地持久化镜像无损自愈恢复全部知识笔记！",
                            fontSize = 12.sp,
                            lineHeight = 18.sp,
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
                        )

                        Spacer(modifier = Modifier.height(12.dp))

                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(
                                onClick = { exportSettingsLauncher.launch("bililearn-settings.json") },
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(10.dp)
                            ) {
                                Icon(Icons.Default.Upload, contentDescription = null, modifier = Modifier.size(16.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("导出配置", fontSize = 12.sp)
                            }
                            OutlinedButton(
                                onClick = { importSettingsLauncher.launch(arrayOf("application/json", "text/plain")) },
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(10.dp)
                            ) {
                                Icon(Icons.Default.Download, contentDescription = null, modifier = Modifier.size(16.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("导入配置", fontSize = 12.sp)
                            }
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedButton(
                            onClick = { showResetSettingsConfirm = true },
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(10.dp)
                        ) {
                            Icon(Icons.Default.RestartAlt, contentDescription = null, modifier = Modifier.size(16.dp))
                            Spacer(modifier = Modifier.width(4.dp))
                            Text("恢复默认配置", fontSize = 12.sp)
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        OutlinedButton(
                            onClick = { showFactoryResetConfirm = true },
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(10.dp),
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)
                        ) {
                            Icon(Icons.Default.DeleteForever, contentDescription = null, modifier = Modifier.size(16.dp))
                            Spacer(modifier = Modifier.width(4.dp))
                            Text("清除全部本地数据", fontSize = 12.sp)
                        }
                        Spacer(modifier = Modifier.height(8.dp))

                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(
                                onClick = {
                                    scope.launch {
                                        val backupManager = BiliLearnApplication.instance.databaseBackupManager
                                        backupManager.autoBackup()
                                        Toast.makeText(context, "已手动更新本地镜像备份！", Toast.LENGTH_SHORT).show()
                                    }
                                },
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(10.dp)
                            ) {
                                Icon(Icons.Default.Save, contentDescription = null, modifier = Modifier.size(16.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("立即备份", fontSize = 12.sp)
                            }

                            Button(
                                onClick = {
                                    scope.launch {
                                        val backupManager = BiliLearnApplication.instance.databaseBackupManager
                                        backupManager.tryAutoRestoreOnStartup()
                                        Toast.makeText(context, "自愈恢复检查完成！", Toast.LENGTH_SHORT).show()
                                    }
                                },
                                modifier = Modifier.weight(1f),
                                colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange),
                                shape = RoundedCornerShape(10.dp)
                            ) {
                                Icon(Icons.Default.Restore, contentDescription = null, modifier = Modifier.size(16.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("自愈恢复", fontSize = 12.sp)
                            }
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(
                                onClick = { exportDatabaseLauncher.launch("bililearn-full-backup.json") },
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(10.dp)
                            ) {
                                Icon(Icons.Default.FileUpload, contentDescription = null, modifier = Modifier.size(16.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("导出完整数据", fontSize = 12.sp)
                            }
                            OutlinedButton(
                                onClick = { importDatabaseLauncher.launch(arrayOf("application/json", "text/plain")) },
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(10.dp)
                            ) {
                                Icon(Icons.Default.FileDownload, contentDescription = null, modifier = Modifier.size(16.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("恢复完整数据", fontSize = 12.sp)
                            }
                        }
                    }
                }
            }

            item {
                Spacer(modifier = Modifier.height(20.dp))
            }
        }
    }

    if (showPersonaEditor) {
        val isEditing = editingPersonaId != null
        AlertDialog(
            onDismissRequest = { showPersonaEditor = false },
            title = { Text(if (isEditing) "编辑自定义人格" else "新建自定义人格") },
            text = {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 460.dp)
                        .verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    OutlinedTextField(
                        value = personaNameInput,
                        onValueChange = { personaNameInput = it },
                        label = { Text("人格名称") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = personaDescriptionInput,
                        onValueChange = { personaDescriptionInput = it },
                        label = { Text("简短说明") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = personaPromptInput,
                        onValueChange = { personaPromptInput = it },
                        label = { Text("系统设定与表达风格") },
                        minLines = 4,
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = personaOwnerInput,
                        onValueChange = { personaOwnerInput = it },
                        label = { Text("主人及关系设定（可选）") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = personaRulesInput,
                        onValueChange = { personaRulesInput = it },
                        label = { Text("行为边界（每行一条）") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        if (personaNameInput.isBlank() || personaPromptInput.isBlank()) {
                            Toast.makeText(context, "人格名称和系统设定不能为空", Toast.LENGTH_SHORT).show()
                            return@Button
                        }
                        val id = editingPersonaId ?: "custom-${UUID.randomUUID()}"
                        prefs.savePersona(
                            PersonaProfile(
                                id = id,
                                name = personaNameInput.trim(),
                                description = personaDescriptionInput.trim(),
                                systemPrompt = personaPromptInput.trim(),
                                ownerPrompt = personaOwnerInput.trim(),
                                rules = personaRulesInput.lines().map(String::trim).filter(String::isNotBlank)
                            )
                        )
                        prefs.setActivePersonaKey(id)
                        showPersonaEditor = false
                        Toast.makeText(context, "人格已保存并启用", Toast.LENGTH_SHORT).show()
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange)
                ) { Text("保存") }
            },
            dismissButton = {
                Row {
                    if (isEditing) {
                        TextButton(onClick = {
                            editingPersonaId?.let(prefs::deletePersona)
                            showPersonaEditor = false
                            Toast.makeText(context, "自定义人格已删除", Toast.LENGTH_SHORT).show()
                        }) { Text("删除", color = MaterialTheme.colorScheme.error) }
                    }
                    TextButton(onClick = { showPersonaEditor = false }) { Text("取消") }
                }
            }
        )
    }

    pendingRestore?.let { (json, preview) ->
        AlertDialog(
            onDismissRequest = { pendingRestore = null },
            title = { Text("确认恢复完整备份") },
            text = {
                Text(
                    "备份格式 v${preview.formatVersion}\n" +
                        "知识笔记 ${preview.knowledgeNotes}，待办 ${preview.reminders}，日记 ${preview.diaryEntries}，长期记忆 ${preview.memories}\n" +
                        "聊天记录 ${preview.chatItems}，行为记录 ${preview.actionReviews}，配置区 ${preview.preferenceFiles}\n" +
                        "背景图片: ${if (preview.hasBackground) "包含" else "不包含"}\n\n" +
                        "继续后会用备份内容替换当前非敏感配置与数据库。API Key 和 B 站登录凭据不会被覆盖。"
                )
            },
            confirmButton = {
                Button(onClick = {
                    pendingRestore = null
                    scope.launch {
                        val app = BiliLearnApplication.instance
                        val result = runCatching { app.databaseBackupManager.restoreFromJson(json) }
                        if (result.isSuccess) {
                            app.preferences.reloadFromDisk()
                            app.toolboxStore.reloadFromDisk()
                            app.advancedStore.reloadFromDisk()
                            app.botEngine.miniGoalEngine.reloadFromDisk()
                            app.botEngine.interestEngine.reloadFromDisk()
                            app.botEngine.biliApiClient.reloadNetworkConfig()
                            app.botEngine.llmClient.reloadNetworkConfig()
                            database.personalDataDao().pendingReminders().forEach { ReminderWorker.schedule(context, it) }
                            apiKeyInput = prefs.getApiKey()
                            baseUrlInput = prefs.getBaseUrl()
                            modelInput = prefs.getBrainModel()
                            Toast.makeText(context, "已恢复 ${result.getOrThrow()} 条数据库记录及 ${preview.preferenceFiles} 个配置区", Toast.LENGTH_LONG).show()
                        } else Toast.makeText(context, result.exceptionOrNull()?.message ?: "恢复失败", Toast.LENGTH_LONG).show()
                    }
                }) { Text("确认替换并恢复") }
            },
            dismissButton = { TextButton(onClick = { pendingRestore = null }) { Text("取消") } }
        )
    }

    // 官方模型选择弹窗
    if (showResetSettingsConfirm) {
        AlertDialog(
            onDismissRequest = { showResetSettingsConfirm = false },
            title = { Text("恢复默认配置？") },
            text = { Text("这会重置 AI 模型、人格、外观和自动化选项。API Key、B 站登录、知识库和聊天记录都会保留。") },
            confirmButton = {
                Button(onClick = {
                    prefs.resetSettings()
                    apiKeyInput = prefs.getApiKey()
                    baseUrlInput = prefs.getBaseUrl()
                    modelInput = prefs.getBrainModel()
                    showResetSettingsConfirm = false
                    Toast.makeText(context, "已恢复默认配置", Toast.LENGTH_SHORT).show()
                }) { Text("重置") }
            },
            dismissButton = {
                TextButton(onClick = { showResetSettingsConfirm = false }) { Text("取消") }
            }
        )
    }

    if (showFactoryResetConfirm) {
        AlertDialog(
            onDismissRequest = { showFactoryResetConfirm = false },
            title = { Text("清除全部本地数据？") },
            text = {
                Text("将永久删除知识库、聊天、待办、日记、长期记忆、工具与 Agent 会话、人格、设置、API Key、B 站登录、背景、日志和自动备份。此操作无法撤销。")
            },
            confirmButton = {
                Button(
                    onClick = {
                        showFactoryResetConfirm = false
                        showFactoryResetFinal = true
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                ) { Text("继续") }
            },
            dismissButton = { TextButton(onClick = { showFactoryResetConfirm = false }) { Text("取消") } }
        )
    }

    if (showFactoryResetFinal) {
        AlertDialog(
            onDismissRequest = { showFactoryResetFinal = false },
            title = { Text("最终确认") },
            text = { Text("最后确认：全部本地数据和登录凭据将被删除，自动备份也不会恢复这些数据。") },
            confirmButton = {
                Button(
                    onClick = {
                        showFactoryResetFinal = false
                        scope.launch {
                            val app = BiliLearnApplication.instance
                            app.botEngine.stopBot()
                            BiliBotService.stop(context)
                            val result = runCatching { app.databaseBackupManager.factoryReset() }
                            if (result.isSuccess) {
                                app.preferences.clearAllData()
                                app.toolboxStore.clearAll()
                                app.advancedStore.clearAll()
                                app.botEngine.miniGoalEngine.clearAll()
                                app.botEngine.interestEngine.clearAll()
                                app.botEngine.biliApiClient.reloadNetworkConfig()
                                app.botEngine.llmClient.reloadNetworkConfig()
                                Toast.makeText(context, "全部本地数据已清除，共删除 ${result.getOrThrow()} 条数据库记录", Toast.LENGTH_LONG).show()
                                (context as? Activity)?.recreate()
                            } else {
                                Toast.makeText(context, result.exceptionOrNull()?.message ?: "清除失败", Toast.LENGTH_LONG).show()
                            }
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                ) { Text("确认全部删除") }
            },
            dismissButton = { TextButton(onClick = { showFactoryResetFinal = false }) { Text("取消") } }
        )
    }

    if (showModelPickerDialog) {
        var modelSearchQuery by remember { mutableStateOf("") }
        val filteredModelList = remember(availableModels, modelSearchQuery) {
            if (modelSearchQuery.isBlank()) availableModels
            else availableModels.filter { it.contains(modelSearchQuery, ignoreCase = true) }
        }

        AlertDialog(
            onDismissRequest = { showModelPickerDialog = false },
            title = {
                Text(
                    text = "选择官方/当前可用模型 (${availableModels.size})",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Bold
                )
            },
            text = {
                Column(modifier = Modifier.fillMaxWidth().height(360.dp)) {
                    OutlinedTextField(
                        value = modelSearchQuery,
                        onValueChange = { modelSearchQuery = it },
                        placeholder = { Text("搜索模型名称...", fontSize = 12.sp) },
                        leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                        singleLine = true,
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth()
                    )

                    Spacer(modifier = Modifier.height(10.dp))

                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        verticalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        items(filteredModelList) { modelName ->
                            val isSelected = modelName == modelInput
                            Card(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        modelInput = modelName
                                        prefs.setBrainModel(modelName)
                                        showModelPickerDialog = false
                                        Toast.makeText(context, "已选用模型: $modelName", Toast.LENGTH_SHORT).show()
                                    },
                                shape = RoundedCornerShape(8.dp),
                                colors = CardDefaults.cardColors(
                                    containerColor = if (isSelected) PrimaryOrange.copy(alpha = 0.15f) else MaterialTheme.colorScheme.surface
                                )
                            ) {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(horizontal = 12.dp, vertical = 10.dp),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Text(
                                        text = modelName,
                                        fontSize = 13.sp,
                                        fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                                        color = if (isSelected) PrimaryOrange else MaterialTheme.colorScheme.onSurface
                                    )
                                    if (isSelected) {
                                        Icon(Icons.Default.Check, contentDescription = null, tint = PrimaryOrange, modifier = Modifier.size(16.dp))
                                    }
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showModelPickerDialog = false }) {
                    Text("关闭", color = PrimaryOrange)
                }
            }
        )
    }

    // 添加兴趣标签弹窗 (支持权重设定)
    if (showAddInterestDialog) {
        AlertDialog(
            onDismissRequest = { showAddInterestDialog = false },
            title = { Text("添加正向学习兴趣", fontWeight = FontWeight.Bold, fontSize = 16.sp) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    OutlinedTextField(
                        value = newInterestInput,
                        onValueChange = { newInterestInput = it },
                        label = { Text("兴趣词 (如 强化学习, 嵌入式, 量化交易)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )

                    Text("兴趣强度 / 优先权重: ${if (newInterestWeight >= 1.4f) "强兴趣 (优先抓取)" else if (newInterestWeight >= 1.0f) "喜爱" else "关注"}", fontSize = 12.sp)

                    Slider(
                        value = newInterestWeight,
                        onValueChange = { newInterestWeight = it },
                        valueRange = 0.5f..1.5f,
                        steps = 1,
                        colors = SliderDefaults.colors(thumbColor = PrimaryOrange, activeTrackColor = PrimaryOrange)
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        if (newInterestInput.isNotBlank()) {
                            botEngine.interestEngine.addInterest(newInterestInput.trim(), newInterestWeight)
                            newInterestInput = ""
                            showAddInterestDialog = false
                            Toast.makeText(context, "兴趣标签已生效！", Toast.LENGTH_SHORT).show()
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange)
                ) {
                    Text("添加兴趣")
                }
            },
            dismissButton = {
                TextButton(onClick = { showAddInterestDialog = false }) {
                    Text("取消")
                }
            }
        )
    }

    // 添加负向屏蔽词弹窗
    if (showAddExclusionDialog) {
        AlertDialog(
            onDismissRequest = { showAddExclusionDialog = false },
            title = { Text("添加负向屏蔽词", fontWeight = FontWeight.Bold, fontSize = 16.sp) },
            text = {
                OutlinedTextField(
                    value = newExclusionInput,
                    onValueChange = { newExclusionInput = it },
                    label = { Text("屏蔽词 (如 八卦, 炒作, 纯搞笑)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        if (newExclusionInput.isNotBlank()) {
                            botEngine.interestEngine.addExclusion(newExclusionInput.trim())
                            newExclusionInput = ""
                            showAddExclusionDialog = false
                            Toast.makeText(context, "屏蔽词已添加！", Toast.LENGTH_SHORT).show()
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFD14343))
                ) {
                    Text("屏蔽")
                }
            },
            dismissButton = {
                TextButton(onClick = { showAddExclusionDialog = false }) {
                    Text("取消")
                }
            }
        )
    }

    if (showLoginDialog) {
        BiliLoginDialog(
            onDismiss = { showLoginDialog = false },
            onLoginSuccess = {
                showLoginDialog = false
                Toast.makeText(context, "登录成功！", Toast.LENGTH_SHORT).show()
            }
        )
    }
}

@Composable
fun SwitchRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, fontSize = 14.sp, fontWeight = FontWeight.Medium)
            Text(text = subtitle, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f))
        }
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            colors = SwitchDefaults.colors(checkedThumbColor = PrimaryOrange, checkedTrackColor = PrimaryOrange.copy(alpha = 0.4f))
        )
    }
}
