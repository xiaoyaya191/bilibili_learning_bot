package com.bililearn.app.ui.advanced

import android.widget.Toast
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Publish
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.model.ChatMessage
import com.bililearn.app.data.model.DmPolicy
import com.bililearn.app.data.model.DynamicDraft
import com.bililearn.app.data.model.LearningGoal
import com.bililearn.app.data.model.QuotaPolicy
import com.bililearn.app.data.model.RelationshipProfile
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.text.DateFormat
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URI
import java.util.Date
import java.util.UUID
import java.util.concurrent.TimeUnit

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdvancedCenterScreen() {
    val prefs = BiliLearnApplication.instance.preferences
    val animations by prefs.animationsEnabledFlow.collectAsState()
    val tabs = listOf("学习目标", "动态发布", "关系", "策略", "网络")
    var selectedTab by remember { mutableIntStateOf(0) }
    Scaffold(topBar = { TopAppBar(title = { Text("高级中心") }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            TabRow(selectedTabIndex = selectedTab) {
                tabs.forEachIndexed { index, label ->
                    Tab(selected = selectedTab == index, onClick = { selectedTab = index }, text = { Text(label) })
                }
            }
            if (animations) {
                AnimatedContent(
                    targetState = selectedTab,
                    transitionSpec = { fadeIn() togetherWith fadeOut() },
                    label = "advanced-tabs"
                ) { tab -> AdvancedTab(tab) }
            } else {
                AdvancedTab(selectedTab)
            }
        }
    }
}

@Composable
private fun AdvancedTab(tab: Int) {
    when (tab) {
        0 -> GoalCenterPanel()
        1 -> DynamicCenterPanel()
        2 -> RelationshipPanel()
        3 -> PolicyPanel()
        else -> NetworkPanel()
    }
}

@Composable
private fun GoalCenterPanel() {
    val app = BiliLearnApplication.instance
    val store = app.advancedStore
    val goals by store.goals.collectAsState()
    val history by store.goalHistory.collectAsState()
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var editor by remember { mutableStateOf<LearningGoal?>(null) }
    var creating by remember { mutableStateOf(false) }
    var aiBusy by remember { mutableStateOf(false) }
    var aiSuggestion by remember { mutableStateOf("") }

    LazyColumn(
        Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { creating = true; editor = LearningGoal(UUID.randomUUID().toString(), "") }, modifier = Modifier.weight(1f)) {
                    Icon(Icons.Default.Add, null)
                    Text("新建目标")
                }
                OutlinedButton(
                    enabled = !aiBusy,
                    onClick = {
                        scope.launch {
                            aiBusy = true
                            val response = app.botEngine.llmClient.chatCompletion(
                                listOf(
                                    ChatMessage("system", "根据用户现有学习目标提出一个明确、可执行的新学习目标。只输出目标名称、视频数、分钟数和一句说明。"),
                                    ChatMessage("user", goals.joinToString("\n") { "${it.title}: ${it.targetVideos}个视频/${it.targetMinutes}分钟" }.ifBlank { "目前没有目标" })
                                )
                            )
                            aiSuggestion = if (response.ok) response.content else response.error.orEmpty()
                            aiBusy = false
                        }
                    },
                    modifier = Modifier.weight(1f)
                ) {
                    if (aiBusy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else Icon(Icons.Default.AutoAwesome, null)
                    Text("AI 建议")
                }
            }
        }
        if (aiSuggestion.isNotBlank()) {
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp)) {
                        Text("AI 建议", fontWeight = FontWeight.Bold)
                        Text(aiSuggestion, style = MaterialTheme.typography.bodyMedium)
                        TextButton(onClick = { aiSuggestion = "" }) { Text("关闭") }
                    }
                }
            }
        }
        items(goals, key = { it.id }) { goal ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(goal.title, fontWeight = FontWeight.Bold)
                            Text("${goal.targetVideos} 个视频 / ${goal.targetMinutes} 分钟 · ${goalStatus(goal.status)}", style = MaterialTheme.typography.bodySmall)
                            if (goal.description.isNotBlank()) Text(goal.description, style = MaterialTheme.typography.bodyMedium)
                        }
                        IconButton(onClick = { creating = false; editor = goal }) { Icon(Icons.Default.Edit, "编辑目标") }
                        IconButton(onClick = { store.deleteGoal(goal.id) }) { Icon(Icons.Default.Delete, "删除目标") }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        when (goal.status) {
                            "ACTIVE" -> {
                                FilledTonalButton(onClick = { store.finishGoal(goal.id, true) }) { Icon(Icons.Default.Check, null); Text("完成") }
                                OutlinedButton(onClick = { store.finishGoal(goal.id, false) }) { Icon(Icons.Default.Stop, null); Text("停止") }
                            }
                            else -> OutlinedButton(onClick = { store.startGoal(goal.id) }) { Icon(Icons.Default.PlayArrow, null); Text("开始") }
                        }
                    }
                }
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("历史", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                TextButton(onClick = { store.clearGoalHistory() }) { Text("清空") }
            }
        }
        items(history, key = { it.id }) { item ->
            Card(Modifier.fillMaxWidth()) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(item.title, fontWeight = FontWeight.Medium)
                        Text("${goalStatus(item.outcome)} · ${formatTime(item.timestamp)}", style = MaterialTheme.typography.bodySmall)
                    }
                    IconButton(onClick = { store.deleteGoalHistory(item.id) }) { Icon(Icons.Default.Delete, "删除历史") }
                }
            }
        }
    }

    editor?.let { initial ->
        GoalEditorDialog(initial, creating, onDismiss = { editor = null }) { goal ->
            if (goal.title.isBlank()) Toast.makeText(context, "目标名称不能为空", Toast.LENGTH_SHORT).show()
            else { store.saveGoal(goal); editor = null }
        }
    }
}

@Composable
private fun GoalEditorDialog(initial: LearningGoal, isNew: Boolean, onDismiss: () -> Unit, onSave: (LearningGoal) -> Unit) {
    var title by remember(initial.id) { mutableStateOf(initial.title) }
    var description by remember(initial.id) { mutableStateOf(initial.description) }
    var videos by remember(initial.id) { mutableStateOf(initial.targetVideos.toString()) }
    var minutes by remember(initial.id) { mutableStateOf(initial.targetMinutes.toString()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (isNew) "新建学习目标" else "编辑学习目标") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(title, { title = it }, label = { Text("目标名称") })
                OutlinedTextField(description, { description = it }, label = { Text("说明") })
                OutlinedTextField(videos, { videos = it.filter(Char::isDigit) }, label = { Text("视频数") })
                OutlinedTextField(minutes, { minutes = it.filter(Char::isDigit) }, label = { Text("分钟数") })
            }
        },
        confirmButton = { TextButton(onClick = { onSave(initial.copy(title = title.trim(), description = description.trim(), targetVideos = videos.toIntOrNull()?.coerceAtLeast(1) ?: 1, targetMinutes = minutes.toIntOrNull()?.coerceAtLeast(1) ?: 30, updatedAt = System.currentTimeMillis())) }) { Text("保存") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}

@Composable
private fun DynamicCenterPanel() {
    val app = BiliLearnApplication.instance
    val store = app.advancedStore
    val drafts by store.drafts.collectAsState()
    val logs by store.publishLogs.collectAsState()
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var text by remember { mutableStateOf("") }
    var editingId by remember { mutableStateOf<String?>(null) }
    var confirmPublish by remember { mutableStateOf<DynamicDraft?>(null) }
    var busy by remember { mutableStateOf(false) }

    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            OutlinedTextField(text, { text = it.take(2000) }, label = { Text("动态草稿") }, minLines = 4, modifier = Modifier.fillMaxWidth())
            Spacer(Modifier.height(8.dp))
            Button(
                enabled = text.isNotBlank(),
                onClick = {
                    store.saveDraft(DynamicDraft(editingId ?: UUID.randomUUID().toString(), text.trim()))
                    text = ""; editingId = null
                }
            ) { Text(if (editingId == null) "保存草稿" else "更新草稿") }
        }
        items(drafts, key = { it.id }) { draft ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Text(draft.content)
                    Text(formatTime(draft.updatedAt), style = MaterialTheme.typography.bodySmall)
                    Row {
                        IconButton(onClick = { editingId = draft.id; text = draft.content }) { Icon(Icons.Default.Edit, "编辑草稿") }
                        IconButton(onClick = { store.deleteDraft(draft.id) }) { Icon(Icons.Default.Delete, "删除草稿") }
                        IconButton(onClick = { confirmPublish = draft }) { Icon(Icons.Default.Publish, "发布动态") }
                    }
                }
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("发布日志", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                TextButton(onClick = store::clearPublishLogs) { Text("清空") }
            }
        }
        items(logs, key = { it.id }) { log ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Text(if (log.success) "发布成功" else "发布失败", fontWeight = FontWeight.Bold)
                    Text(log.content, maxLines = 3)
                    Text("${log.detail} · ${formatTime(log.timestamp)}", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }

    confirmPublish?.let { draft ->
        AlertDialog(
            onDismissRequest = { if (!busy) confirmPublish = null },
            title = { Text("确认发布 B 站动态") },
            text = { Text(draft.content) },
            confirmButton = {
                TextButton(enabled = !busy, onClick = {
                    scope.launch {
                        busy = true
                        val result = app.botEngine.biliApiClient.publishTextDynamic(draft.content)
                        store.recordPublish(draft.content, result.isSuccess, result.exceptionOrNull()?.message ?: "B 站已接受发布请求")
                        if (result.isSuccess) store.deleteDraft(draft.id)
                        Toast.makeText(context, result.exceptionOrNull()?.message ?: "发布成功", Toast.LENGTH_LONG).show()
                        busy = false; confirmPublish = null
                    }
                }) { Text("确认发布") }
            },
            dismissButton = { TextButton(enabled = !busy, onClick = { confirmPublish = null }) { Text("取消") } }
        )
    }
}

@Composable
private fun RelationshipPanel() {
    val store = BiliLearnApplication.instance.advancedStore
    val items by store.relationships.collectAsState()
    val dmPolicy by store.dmPolicy.collectAsState()
    var editor by remember { mutableStateOf<RelationshipProfile?>(null) }
    var blacklist by remember(dmPolicy) { mutableStateOf(dmPolicy.blacklist.joinToString("\n")) }
    var whitelist by remember(dmPolicy) { mutableStateOf(dmPolicy.whitelist.joinToString("\n")) }
    var whitelistOnly by remember(dmPolicy) { mutableStateOf(dmPolicy.whitelistOnly) }
    LazyColumn(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Button(onClick = { editor = RelationshipProfile(UUID.randomUUID().toString(), "", "") }) { Icon(Icons.Default.Add, null); Text("新建关系") } }
        items(items, key = { it.id }) { profile ->
            Card(Modifier.fillMaxWidth()) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(profile.name, fontWeight = FontWeight.Bold)
                        Text("${profile.relation} · 好感度 ${profile.affection}", style = MaterialTheme.typography.bodySmall)
                        if (profile.notes.isNotBlank()) Text(profile.notes)
                    }
                    IconButton(onClick = { editor = profile }) { Icon(Icons.Default.Edit, "编辑关系") }
                    IconButton(onClick = { store.deleteRelationship(profile.id) }) { Icon(Icons.Default.Delete, "删除关系") }
                }
            }
        }
        item {
            HorizontalDivider()
            Text("私信过滤", style = MaterialTheme.typography.titleMedium)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(whitelistOnly, { whitelistOnly = it })
                Text("仅允许白名单联系人")
            }
            OutlinedTextField(blacklist, { blacklist = it }, label = { Text("黑名单 UID，每行一个") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
            OutlinedTextField(whitelist, { whitelist = it }, label = { Text("白名单 UID，每行一个") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
            Button(onClick = {
                store.setDmPolicy(DmPolicy(whitelistOnly, blacklist.lines(), whitelist.lines()))
            }) { Text("保存私信规则") }
        }
    }
    editor?.let { initial -> RelationshipEditor(initial, { editor = null }) { store.saveRelationship(it); editor = null } }
}

@Composable
private fun RelationshipEditor(initial: RelationshipProfile, onDismiss: () -> Unit, onSave: (RelationshipProfile) -> Unit) {
    var name by remember(initial.id) { mutableStateOf(initial.name) }
    var relation by remember(initial.id) { mutableStateOf(initial.relation) }
    var notes by remember(initial.id) { mutableStateOf(initial.notes) }
    var affection by remember(initial.id) { mutableIntStateOf(initial.affection) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("编辑关系") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it }, label = { Text("名称或 UID") })
                OutlinedTextField(relation, { relation = it }, label = { Text("关系") })
                Text("好感度 $affection")
                Slider(affection.toFloat(), { affection = it.toInt() }, valueRange = 0f..100f)
                OutlinedTextField(notes, { notes = it }, label = { Text("备注") })
            }
        },
        confirmButton = { TextButton(enabled = name.isNotBlank(), onClick = { onSave(initial.copy(name = name.trim(), relation = relation.trim(), affection = affection, notes = notes.trim(), updatedAt = System.currentTimeMillis())) }) { Text("保存") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}

@Composable
private fun PolicyPanel() {
    val app = BiliLearnApplication.instance
    val prefs = app.preferences
    val store = app.advancedStore
    val savedQuota by store.quota.collectAsState()
    var quotaEnabled by remember(savedQuota) { mutableStateOf(savedQuota.enabled) }
    var dailyLimit by remember(savedQuota) { mutableStateOf(savedQuota.dailyLimit.toString()) }
    var warning by remember(savedQuota) { mutableStateOf(savedQuota.warningPercent.toString()) }
    var contentFilter by remember { mutableStateOf(prefs.isContentFilterEnabled()) }
    var injectionProtection by remember { mutableStateOf(prefs.isPromptInjectionProtectionEnabled()) }
    var blockedTerms by remember { mutableStateOf(prefs.getBlockedTerms().joinToString("\n")) }
    var injectionPatterns by remember { mutableStateOf(prefs.getPromptInjectionPatterns().joinToString("\n")) }
    var judgmentPrompt by remember { mutableStateOf(prefs.getJudgmentPrompt()) }
    val context = LocalContext.current
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("请求配额", style = MaterialTheme.typography.titleMedium)
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("启用每日请求上限", modifier = Modifier.weight(1f))
            Switch(quotaEnabled, { quotaEnabled = it })
        }
        OutlinedTextField(dailyLimit, { dailyLimit = it.filter(Char::isDigit) }, label = { Text("每日上限") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(warning, { warning = it.filter(Char::isDigit) }, label = { Text("提醒百分比") }, modifier = Modifier.fillMaxWidth())
        Text("今日已记录 ${store.normalizedQuota().usedToday} 次", style = MaterialTheme.typography.bodySmall)
        Button(onClick = {
            store.setQuota(QuotaPolicy(quotaEnabled, dailyLimit.toIntOrNull() ?: 100, warning.toIntOrNull() ?: 80, savedQuota.usedToday, savedQuota.usageDate))
            Toast.makeText(context, "配额设置已保存", Toast.LENGTH_SHORT).show()
        }) { Text("保存配额") }
        HorizontalDivider()
        Text("判断与安全策略", style = MaterialTheme.typography.titleMedium)
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("启用自定义内容过滤", modifier = Modifier.weight(1f))
            Switch(contentFilter, { contentFilter = it })
        }
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("启用提示注入保护", modifier = Modifier.weight(1f))
            Switch(injectionProtection, { injectionProtection = it })
        }
        OutlinedTextField(judgmentPrompt, { judgmentPrompt = it }, label = { Text("判断提示词") }, modifier = Modifier.fillMaxWidth(), minLines = 4)
        OutlinedTextField(blockedTerms, { blockedTerms = it }, label = { Text("过滤词，每行一个") }, modifier = Modifier.fillMaxWidth(), minLines = 4)
        OutlinedTextField(injectionPatterns, { injectionPatterns = it }, label = { Text("注入特征，每行一个") }, modifier = Modifier.fillMaxWidth(), minLines = 4)
        Button(onClick = {
            prefs.setContentFilterEnabled(contentFilter)
            prefs.setPromptInjectionProtectionEnabled(injectionProtection)
            prefs.setJudgmentPrompt(judgmentPrompt)
            prefs.setBlockedTerms(blockedTerms.lines())
            prefs.setPromptInjectionPatterns(injectionPatterns.lines())
            Toast.makeText(context, "策略已保存并立即生效", Toast.LENGTH_SHORT).show()
        }) { Text("保存策略") }
        OutlinedButton(onClick = {
            contentFilter = false
            injectionProtection = true
            judgmentPrompt = ""
            blockedTerms = ""
            injectionPatterns = listOf("ignore previous instructions", "system prompt", "jailbreak", "忽略之前的指令", "开启开发者模式").joinToString("\n")
        }) { Text("恢复默认策略") }
        Spacer(Modifier.height(20.dp))
    }
}

@Composable
private fun NetworkPanel() {
    val app = BiliLearnApplication.instance
    val prefs = app.preferences
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var proxyEnabled by remember { mutableStateOf(prefs.isProxyEnabled()) }
    var proxyUrl by remember { mutableStateOf(prefs.getProxyUrl()) }
    var proxyStatus by remember { mutableStateOf("") }
    var testing by remember { mutableStateOf(false) }
    var bvid by remember { mutableStateOf("") }
    var danmaku by remember { mutableStateOf("") }
    var progressSeconds by remember { mutableStateOf("1") }
    var confirmDanmaku by remember { mutableStateOf(false) }
    var sending by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("网络代理", style = MaterialTheme.typography.titleMedium)
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("启用代理", modifier = Modifier.weight(1f))
            Switch(proxyEnabled, { proxyEnabled = it })
        }
        OutlinedTextField(proxyUrl, { proxyUrl = it }, label = { Text("代理地址") }, supportingText = { Text("支持 http://、socks:// 和 socks5://") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = !proxyEnabled || validProxyUrl(proxyUrl), onClick = {
                prefs.setProxy(proxyEnabled, proxyUrl)
                app.botEngine.biliApiClient.reloadNetworkConfig()
                app.botEngine.llmClient.reloadNetworkConfig()
                Toast.makeText(context, "代理设置已应用到 B 站与模型客户端", Toast.LENGTH_SHORT).show()
            }) { Text("保存并应用") }
            OutlinedButton(enabled = !testing && validProxyUrl(proxyUrl), onClick = {
                scope.launch {
                    testing = true
                    proxyStatus = testProxy(proxyUrl)
                    testing = false
                }
            }) { Text(if (testing) "测试中" else "测试代理") }
        }
        if (proxyStatus.isNotBlank()) Text(proxyStatus, style = MaterialTheme.typography.bodySmall)

        HorizontalDivider()
        Text("发送弹幕", style = MaterialTheme.typography.titleMedium)
        Text("发送前会读取视频 CID，并再次要求确认。", style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(bvid, { bvid = it }, label = { Text("BV 号或视频链接") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(progressSeconds, { progressSeconds = it.filter(Char::isDigit) }, label = { Text("出现时间（秒）") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(danmaku, { danmaku = it.take(100) }, label = { Text("弹幕内容") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
        Button(enabled = bvid.isNotBlank() && danmaku.isNotBlank() && !sending, onClick = { confirmDanmaku = true }) { Text("准备发送") }
    }

    if (confirmDanmaku) {
        AlertDialog(
            onDismissRequest = { if (!sending) confirmDanmaku = false },
            title = { Text("确认发送弹幕") },
            text = { Text("将在 ${progressSeconds.toIntOrNull() ?: 1} 秒发送：\n$danmaku") },
            confirmButton = {
                TextButton(enabled = !sending, onClick = {
                    scope.launch {
                        sending = true
                        val resolved = app.botEngine.biliApiClient.resolveAndExtractBvid(bvid)
                            ?: app.botEngine.biliApiClient.extractBvid(bvid)
                        val result = if (resolved == null) Result.failure(Exception("无法识别 BV 号")) else {
                            app.botEngine.biliApiClient.fetchVideoDetail(resolved).fold(
                                onSuccess = { detail -> app.botEngine.biliApiClient.sendDanmaku(detail.cid, danmaku, (progressSeconds.toIntOrNull() ?: 1) * 1000) },
                                onFailure = { Result.failure(it) }
                            )
                        }
                        Toast.makeText(context, result.exceptionOrNull()?.message ?: "弹幕已发送", Toast.LENGTH_LONG).show()
                        sending = false
                        confirmDanmaku = false
                        if (result.isSuccess) danmaku = ""
                    }
                }) { Text("确认发送") }
            },
            dismissButton = { TextButton(enabled = !sending, onClick = { confirmDanmaku = false }) { Text("取消") } }
        )
    }
}

private fun validProxyUrl(value: String): Boolean = runCatching {
    val uri = URI(value.trim())
    uri.scheme?.lowercase() in setOf("http", "https", "socks", "socks5") && !uri.host.isNullOrBlank() && uri.port in 1..65535
}.getOrDefault(false)

private suspend fun testProxy(value: String): String = withContext(Dispatchers.IO) {
    runCatching {
        val uri = URI(value.trim())
        val type = if (uri.scheme.equals("socks", true) || uri.scheme.equals("socks5", true)) Proxy.Type.SOCKS else Proxy.Type.HTTP
        val client = OkHttpClient.Builder()
            .proxy(Proxy(type, InetSocketAddress(uri.host, uri.port)))
            .connectTimeout(12, TimeUnit.SECONDS)
            .readTimeout(12, TimeUnit.SECONDS)
            .build()
        client.newCall(Request.Builder().url("https://api.bilibili.com/x/web-interface/nav").get().build()).execute().use {
            if (it.isSuccessful) "代理连接成功，HTTP ${it.code}" else "代理已连接，但目标返回 HTTP ${it.code}"
        }
    }.getOrElse { "代理测试失败: ${it.message}" }
}

private fun goalStatus(value: String): String = when (value) {
    "ACTIVE" -> "进行中"
    "COMPLETED" -> "已完成"
    "STOPPED" -> "已停止"
    "STARTED" -> "已开始"
    else -> "待开始"
}

private fun formatTime(value: Long): String = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(value))
