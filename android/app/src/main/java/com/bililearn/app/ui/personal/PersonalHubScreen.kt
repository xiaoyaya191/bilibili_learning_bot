package com.bililearn.app.ui.personal

import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
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
import com.bililearn.app.data.database.entity.DiaryEntryEntity
import com.bililearn.app.data.database.entity.PermanentMemoryEntity
import com.bililearn.app.data.database.entity.ReminderEntity
import com.bililearn.app.service.ReminderWorker
import kotlinx.coroutines.launch
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID

private val dateFormat = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

@Composable
fun PersonalHubScreen() {
    val app = BiliLearnApplication.instance
    val dao = app.database.personalDataDao()
    val reminders by dao.remindersFlow().collectAsState(initial = emptyList())
    val diary by dao.diaryFlow().collectAsState(initial = emptyList())
    val memories by dao.memoriesFlow().collectAsState(initial = emptyList())
    var tab by remember { mutableIntStateOf(0) }
    var query by remember { mutableStateOf("") }
    var editor by remember { mutableStateOf<EditorTarget?>(null) }

    Scaffold(
        floatingActionButton = {
            if (tab < 3) FloatingActionButton(onClick = { editor = EditorTarget.New(tab) }) {
                Icon(Icons.Default.Add, contentDescription = "新增")
            }
        }
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
                Text("个人数据中心", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text("待办、学习日记与长期记忆", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            TabRow(selectedTabIndex = tab) {
                listOf("待办 ${reminders.size}", "日记 ${diary.size}", "记忆 ${memories.size}", "心情统计").forEachIndexed { index, title ->
                    Tab(selected = tab == index, onClick = { tab = index }, text = { Text(title) })
                }
            }
            if (tab == 1 || tab == 2) {
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                    singleLine = true,
                    label = { Text("搜索") },
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                    trailingIcon = if (query.isNotEmpty()) ({ IconButton(onClick = { query = "" }) { Icon(Icons.Default.Close, "清空搜索") } }) else null
                )
            }
            when (tab) {
                0 -> ReminderList(reminders, onEdit = { editor = EditorTarget.Reminder(it) })
                1 -> DiaryList(diary.filter { query.isBlank() || listOf(it.title, it.content, it.mood, it.tags).any { value -> value.contains(query, true) } }, onEdit = { editor = EditorTarget.Diary(it) })
                2 -> MemoryList(memories.filter { query.isBlank() || listOf(it.summary, it.content, it.tags).any { value -> value.contains(query, true) } }, onEdit = { editor = EditorTarget.Memory(it) })
                else -> MoodStatistics(diary)
            }
        }
    }
    editor?.let { target -> PersonalEditor(target = target, onDismiss = { editor = null }) }
}

@Composable
private fun MoodStatistics(items: List<DiaryEntryEntity>) {
    val counts = items.map { it.mood.trim().ifBlank { "未记录" } }.groupingBy { it }.eachCount().entries.sortedByDescending { it.value }
    val maximum = counts.maxOfOrNull { it.value } ?: 1
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text("共 ${items.size} 篇日记，${counts.size} 种心情记录", style = MaterialTheme.typography.titleMedium)
        }
        if (counts.isEmpty()) item { Text("暂无心情数据", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        items(counts, key = { it.key }) { entry ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(Modifier.fillMaxWidth()) {
                        Text(entry.key, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                        Text("${entry.value} 次")
                    }
                    LinearProgressIndicator(
                        progress = { entry.value.toFloat() / maximum },
                        modifier = Modifier.fillMaxWidth().height(8.dp)
                    )
                }
            }
        }
    }
}

@Composable
private fun ReminderList(items: List<ReminderEntity>, onEdit: (ReminderEntity) -> Unit) {
    val context = LocalContext.current
    val dao = BiliLearnApplication.instance.database.personalDataDao()
    val scope = rememberCoroutineScope()
    PersonalList(items, "还没有待办") { item ->
        ListItem(
            headlineContent = { Text(item.content, fontWeight = if (item.completed) FontWeight.Normal else FontWeight.SemiBold) },
            supportingContent = { Text(if (item.completed) "已完成" else "到期 ${formatTime(item.dueAt)}") },
            leadingContent = {
                Checkbox(checked = item.completed, onCheckedChange = { checked ->
                    scope.launch {
                        val changed = item.copy(completed = checked, updatedAt = System.currentTimeMillis())
                        dao.upsertReminder(changed)
                        if (checked) ReminderWorker.cancel(context, item.id) else ReminderWorker.schedule(context, changed)
                    }
                })
            },
            trailingContent = { IconButton(onClick = { onEdit(item) }) { Icon(Icons.Default.Edit, "编辑待办") } }
        )
    }
}

@Composable
private fun DiaryList(items: List<DiaryEntryEntity>, onEdit: (DiaryEntryEntity) -> Unit) {
    PersonalList(items, "还没有学习日记") { item ->
        ListItem(
            headlineContent = { Text(item.title.ifBlank { "未命名日记" }, fontWeight = FontWeight.SemiBold) },
            supportingContent = { Text(listOf(item.mood, item.tags, formatTime(item.updatedAt)).filter { it.isNotBlank() }.joinToString("  ")) },
            leadingContent = { Icon(Icons.Default.EditNote, null) },
            trailingContent = { IconButton(onClick = { onEdit(item) }) { Icon(Icons.Default.Edit, "编辑日记") } }
        )
    }
}

@Composable
private fun MemoryList(items: List<PermanentMemoryEntity>, onEdit: (PermanentMemoryEntity) -> Unit) {
    PersonalList(items, "还没有长期记忆") { item ->
        ListItem(
            headlineContent = { Text(item.summary.ifBlank { item.content.take(36) }, fontWeight = FontWeight.SemiBold) },
            supportingContent = { Text(item.tags.ifBlank { formatTime(item.updatedAt) }) },
            leadingContent = { Icon(Icons.Default.Psychology, null) },
            trailingContent = { IconButton(onClick = { onEdit(item) }) { Icon(Icons.Default.Edit, "编辑记忆") } }
        )
    }
}

@Composable
private fun <T> PersonalList(items: List<T>, emptyText: String, row: @Composable (T) -> Unit) {
    if (items.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text(emptyText, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    } else {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(items) { item ->
                Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) { row(item) }
            }
            item { Spacer(Modifier.height(72.dp)) }
        }
    }
}

private sealed interface EditorTarget {
    data class New(val tab: Int) : EditorTarget
    data class Reminder(val item: ReminderEntity) : EditorTarget
    data class Diary(val item: DiaryEntryEntity) : EditorTarget
    data class Memory(val item: PermanentMemoryEntity) : EditorTarget
}

@Composable
private fun PersonalEditor(target: EditorTarget, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val dao = BiliLearnApplication.instance.database.personalDataDao()
    val scope = rememberCoroutineScope()
    val type = when (target) { is EditorTarget.New -> target.tab; is EditorTarget.Reminder -> 0; is EditorTarget.Diary -> 1; is EditorTarget.Memory -> 2 }
    var title by remember(target) { mutableStateOf((target as? EditorTarget.Diary)?.item?.title.orEmpty()) }
    var content by remember(target) { mutableStateOf(when (target) { is EditorTarget.Reminder -> target.item.content; is EditorTarget.Diary -> target.item.content; is EditorTarget.Memory -> target.item.content; else -> "" }) }
    var extra by remember(target) { mutableStateOf(when (target) { is EditorTarget.Diary -> target.item.mood; is EditorTarget.Memory -> target.item.summary; else -> "" }) }
    var tags by remember(target) { mutableStateOf(when (target) { is EditorTarget.Diary -> target.item.tags; is EditorTarget.Memory -> target.item.tags; else -> "" }) }
    var dueText by remember(target) { mutableStateOf(formatTime((target as? EditorTarget.Reminder)?.item?.dueAt ?: (System.currentTimeMillis() + 3_600_000))) }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (target is EditorTarget.New) listOf("新增待办", "新增日记", "新增记忆")[type] else listOf("编辑待办", "编辑日记", "编辑记忆")[type]) },
        text = {
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (type == 1) OutlinedTextField(title, { title = it }, label = { Text("标题") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                if (type == 2) OutlinedTextField(extra, { extra = it }, label = { Text("摘要") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                OutlinedTextField(content, { content = it }, label = { Text(if (type == 0) "待办内容" else "正文") }, modifier = Modifier.fillMaxWidth(), minLines = if (type == 0) 2 else 5)
                if (type == 0) OutlinedTextField(dueText, { dueText = it }, label = { Text("到期时间 yyyy-MM-dd HH:mm") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                if (type == 1) OutlinedTextField(extra, { extra = it }, label = { Text("心情") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                if (type != 0) OutlinedTextField(tags, { tags = it }, label = { Text("标签，用逗号分隔") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
                error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            }
        },
        confirmButton = {
            Button(onClick = {
                if (content.isBlank()) { error = "内容不能为空"; return@Button }
                val now = System.currentTimeMillis()
                scope.launch {
                    when (type) {
                        0 -> {
                            val dueAt = parseTime(dueText)
                            if (dueAt == null) { error = "时间格式不正确"; return@launch }
                            val old = (target as? EditorTarget.Reminder)?.item
                            val item = ReminderEntity(old?.id ?: UUID.randomUUID().toString(), content.trim(), dueAt, old?.completed ?: false, old?.createdAt ?: now, now)
                            dao.upsertReminder(item)
                            if (!item.completed) ReminderWorker.schedule(context, item)
                        }
                        1 -> {
                            val old = (target as? EditorTarget.Diary)?.item
                            dao.upsertDiary(DiaryEntryEntity(old?.id ?: UUID.randomUUID().toString(), title.trim(), content.trim(), extra.trim(), tags.trim(), old?.source ?: "manual", old?.createdAt ?: now, now))
                        }
                        else -> {
                            val old = (target as? EditorTarget.Memory)?.item
                            dao.upsertMemory(PermanentMemoryEntity(old?.id ?: UUID.randomUUID().toString(), content.trim(), extra.trim(), tags.trim(), old?.source ?: "manual", old?.createdAt ?: now, now))
                        }
                    }
                    onDismiss()
                }
            }) { Text("保存") }
        },
        dismissButton = {
            Row {
                if (target !is EditorTarget.New) TextButton(onClick = {
                    scope.launch {
                        when (target) {
                            is EditorTarget.Reminder -> { dao.deleteReminder(target.item); ReminderWorker.cancel(context, target.item.id) }
                            is EditorTarget.Diary -> dao.deleteDiary(target.item)
                            is EditorTarget.Memory -> dao.deleteMemory(target.item)
                            else -> Unit
                        }
                        Toast.makeText(context, "已删除", Toast.LENGTH_SHORT).show()
                        onDismiss()
                    }
                }) { Text("删除", color = MaterialTheme.colorScheme.error) }
                TextButton(onClick = onDismiss) { Text("取消") }
            }
        }
    )
}

private fun formatTime(time: Long): String = java.time.Instant.ofEpochMilli(time).atZone(ZoneId.systemDefault()).toLocalDateTime().format(dateFormat)
private fun parseTime(value: String): Long? = runCatching { LocalDateTime.parse(value.trim(), dateFormat).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli() }.getOrNull()
