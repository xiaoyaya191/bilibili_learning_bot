package com.bililearn.app.ui.messages

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.model.BiliConversation
import com.bililearn.app.data.model.BiliPrivateMessage
import kotlinx.coroutines.launch
import coil.compose.AsyncImage
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable
fun PrivateMessagesScreen() {
    val api = BiliLearnApplication.instance.botEngine.biliApiClient
    val ownUid = BiliLearnApplication.instance.preferences.getDedeUserId().toLongOrNull() ?: 0
    val scope = rememberCoroutineScope()
    var conversations by remember { mutableStateOf(emptyList<BiliConversation>()) }
    var selected by remember { mutableStateOf<BiliConversation?>(null) }
    var messages by remember { mutableStateOf(emptyList<BiliPrivateMessage>()) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    fun loadConversations() {
        scope.launch {
            loading = true
            api.fetchPrivateConversations().onSuccess { conversations = it; error = null }.onFailure { error = it.message }
            loading = false
        }
    }
    fun loadMessages(item: BiliConversation) {
        selected = item
        scope.launch {
            loading = true
            api.fetchPrivateMessages(item.talkerId).onSuccess { messages = it; error = null }.onFailure { error = it.message }
            loading = false
        }
    }
    LaunchedEffect(Unit) { loadConversations() }
    if (selected == null) ConversationList(conversations, loading, error, ::loadConversations, ::loadMessages)
    else ConversationDetail(selected!!, messages, ownUid, loading, error, onBack = { selected = null; messages = emptyList() }, onRefresh = { loadMessages(selected!!) })
}

@Composable
private fun ConversationList(items: List<BiliConversation>, loading: Boolean, error: String?, onRefresh: () -> Unit, onSelect: (BiliConversation) -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("B 站私聊", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text("会话消息由 B 站账号同步", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = onRefresh, enabled = !loading) { Icon(Icons.Default.Refresh, "刷新会话") }
        }
        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text(error, color = MaterialTheme.colorScheme.error) }
            items.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("没有可显示的私聊会话") }
            else -> LazyColumn(contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(items, key = { it.talkerId }) { item ->
                    Surface(onClick = { onSelect(item) }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) {
                        ListItem(
                            headlineContent = { Text(item.talkerName.ifBlank { "用户 UID ${item.talkerId}" }, fontWeight = FontWeight.SemiBold) },
                            supportingContent = { Text(item.lastMessage.ifBlank { "暂无文本消息" }, maxLines = 2) },
                            leadingContent = {
                                if (item.avatarUrl.isNotBlank()) AsyncImage(item.avatarUrl, null, Modifier.size(40.dp))
                                else Icon(Icons.Default.AccountCircle, null)
                            },
                            trailingContent = { if (item.unreadCount > 0) Badge { Text(item.unreadCount.toString()) } }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ConversationDetail(item: BiliConversation, messages: List<BiliPrivateMessage>, ownUid: Long, loading: Boolean, error: String?, onBack: () -> Unit, onRefresh: () -> Unit) {
    val api = BiliLearnApplication.instance.botEngine.biliApiClient
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()
    var input by remember { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    var sendError by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(messages.size) { if (messages.isNotEmpty()) listState.scrollToItem(messages.lastIndex) }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.Default.ArrowBack, "返回会话列表") }
            Column(Modifier.weight(1f)) { Text(item.talkerName.ifBlank { "UID ${item.talkerId}" }, fontWeight = FontWeight.Bold); Text("UID ${item.talkerId}", style = MaterialTheme.typography.labelSmall) }
            IconButton(onClick = onRefresh, enabled = !loading) { Icon(Icons.Default.Refresh, "刷新消息") }
        }
        if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
        error?.let { Text(it, Modifier.padding(horizontal = 12.dp), color = MaterialTheme.colorScheme.error) }
        LazyColumn(state = listState, modifier = Modifier.weight(1f).fillMaxWidth(), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(messages, key = { "${it.sequence}-${it.timestamp}" }) { message ->
                val mine = message.senderUid == ownUid
                Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
                    Surface(
                        color = if (mine) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant,
                        shape = RoundedCornerShape(8.dp),
                        modifier = Modifier.widthIn(max = 310.dp)
                    ) {
                        Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                            Text(message.content)
                            Text(formatMessageTime(message.timestamp), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
        sendError?.let { Text(it, Modifier.padding(horizontal = 12.dp), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
        Row(Modifier.fillMaxWidth().padding(10.dp), verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(input, { input = it }, Modifier.weight(1f), label = { Text("输入消息") }, maxLines = 4)
            FilledIconButton(
                onClick = {
                    if (input.isBlank()) return@FilledIconButton
                    val policy = BiliLearnApplication.instance.advancedStore.dmPolicy.value
                    val uid = item.talkerId.toString()
                    if (uid in policy.blacklist || (policy.whitelistOnly && uid !in policy.whitelist)) {
                        sendError = "当前私信规则禁止向该联系人发送消息"
                        return@FilledIconButton
                    }
                    val text = input.trim()
                    sending = true
                    sendError = null
                    scope.launch {
                        api.sendPrivateMessage(item.talkerId, text)
                            .onSuccess { input = ""; onRefresh() }
                            .onFailure { sendError = it.message ?: "发送失败" }
                        sending = false
                    }
                },
                enabled = input.isNotBlank() && !sending
            ) { if (sending) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) else Icon(Icons.Default.Send, "发送消息") }
        }
    }
}

private fun formatMessageTime(seconds: Long): String {
    if (seconds <= 0) return ""
    return DateTimeFormatter.ofPattern("MM-dd HH:mm").format(Instant.ofEpochSecond(seconds).atZone(ZoneId.systemDefault()))
}
