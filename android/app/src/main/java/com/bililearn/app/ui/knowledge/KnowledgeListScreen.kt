package com.bililearn.app.ui.knowledge

import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.database.entity.KnowledgeNoteEntity
import com.bililearn.app.ui.theme.PrimaryOrange
import com.google.gson.Gson
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KnowledgeListScreen(
    onSelectNote: (KnowledgeNoteEntity) -> Unit
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val database = BiliLearnApplication.instance.database

    var searchQuery by remember { mutableStateOf("") }
    var selectedTag by remember { mutableStateOf<String?>(null) }
    var filterRevisitOnly by remember { mutableStateOf(false) }

    var showCreateDialog by remember { mutableStateOf(false) }

    val allNotes by database.knowledgeNoteDao().getAllNotesFlow().collectAsState(initial = emptyList())

    // 提取所有标签
    val allTags = remember(allNotes) {
        val set = mutableSetOf<String>()
        allNotes.forEach { note ->
            set.addAll(note.getTagsList())
        }
        set.toList()
    }

    // 过滤列表 (支持搜索、标签筛选、艾宾浩斯复习过滤)
    val filteredNotes = remember(allNotes, searchQuery, selectedTag, filterRevisitOnly) {
        allNotes.filter { note ->
            val matchQuery = searchQuery.isBlank() ||
                    note.title.contains(searchQuery, ignoreCase = true) ||
                    note.summary.contains(searchQuery, ignoreCase = true)
            val matchTag = selectedTag == null || note.getTagsList().contains(selectedTag)

            val matchRevisit = if (filterRevisitOnly) {
                // 模拟艾宾浩斯复习周期: 1天前、3天前、7天前
                val daysAgo = (System.currentTimeMillis() - note.createdAt) / (1000 * 3600 * 24)
                daysAgo >= 1
            } else true

            matchQuery && matchTag && matchRevisit
        }
    }

    Scaffold(
        topBar = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 12.dp)
            ) {
                Text(
                    text = "知识沉淀库",
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.primary
                )
                Spacer(modifier = Modifier.height(10.dp))

                // 搜索栏
                OutlinedTextField(
                    value = searchQuery,
                    onValueChange = { searchQuery = it },
                    placeholder = { Text("搜索知识卡片、主题或关键词...", fontSize = 13.sp) },
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                    trailingIcon = {
                        if (searchQuery.isNotEmpty()) {
                            IconButton(onClick = { searchQuery = "" }) {
                                Icon(Icons.Default.Clear, contentDescription = "清空")
                            }
                        }
                    },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth()
                )

                // 标签与复习过滤器
                Spacer(modifier = Modifier.height(8.dp))
                LazyRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    item {
                        FilterChip(
                            selected = selectedTag == null && !filterRevisitOnly,
                            onClick = {
                                selectedTag = null
                                filterRevisitOnly = false
                            },
                            label = { Text("全部 (${allNotes.size})") }
                        )
                    }
                    item {
                        FilterChip(
                            selected = filterRevisitOnly,
                            onClick = { filterRevisitOnly = !filterRevisitOnly },
                            label = { Text("艾宾浩斯复习") }
                        )
                    }
                    items(allTags) { tag ->
                        FilterChip(
                            selected = selectedTag == tag,
                            onClick = {
                                selectedTag = if (selectedTag == tag) null else tag
                                filterRevisitOnly = false
                            },
                            label = { Text("# $tag") }
                        )
                    }
                }
            }
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = { showCreateDialog = true },
                containerColor = PrimaryOrange,
                contentColor = MaterialTheme.colorScheme.onPrimary
            ) {
                Icon(Icons.Default.Add, contentDescription = "新建知识笔记")
            }
        }
    ) { padding ->
        if (filteredNotes.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        imageVector = Icons.Default.MenuBook,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.3f),
                        modifier = Modifier.size(64.dp)
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = if (allNotes.isEmpty()) "知识库尚无笔记，点击右下角 + 添加或在工坊学习视频！" else "未找到符合条件的知识卡片",
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f),
                        fontSize = 14.sp
                    )
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(filteredNotes, key = { it.id }) { note ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSelectNote(note) },
                        shape = RoundedCornerShape(14.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                    ) {
                        Column(modifier = Modifier.padding(14.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.Top
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = note.title,
                                        fontSize = 15.sp,
                                        fontWeight = FontWeight.Bold,
                                        maxLines = 2,
                                        color = MaterialTheme.colorScheme.onSurface
                                    )
                                    Spacer(modifier = Modifier.height(4.dp))
                                    Text(
                                        text = "来源: ${note.upName.ifEmpty { "自定义笔记" }} · ${note.dateStr.take(10)}",
                                        fontSize = 11.sp,
                                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f)
                                    )
                                }

                                if (note.coverUrl.isNotEmpty()) {
                                    Spacer(modifier = Modifier.width(10.dp))
                                    AsyncImage(
                                        model = note.coverUrl,
                                        contentDescription = "Cover",
                                        contentScale = ContentScale.Crop,
                                        modifier = Modifier
                                            .size(width = 80.dp, height = 50.dp)
                                            .clip(RoundedCornerShape(8.dp))
                                    )
                                }
                            }

                            Spacer(modifier = Modifier.height(8.dp))
                            Text(
                                text = note.summary,
                                fontSize = 13.sp,
                                maxLines = 2,
                                lineHeight = 18.sp,
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.75f)
                            )

                            Spacer(modifier = Modifier.height(10.dp))
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    note.getTagsList().take(3).forEach { tag ->
                                        Text(
                                            text = "#$tag",
                                            fontSize = 11.sp,
                                            color = PrimaryOrange,
                                            fontWeight = FontWeight.Medium
                                        )
                                    }
                                }
                                Icon(
                                    imageVector = Icons.Default.ChevronRight,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.3f),
                                    modifier = Modifier.size(18.dp)
                                )
                            }
                        }
                    }
                }
                item {
                    Spacer(modifier = Modifier.height(80.dp))
                }
            }
        }
    }

    if (showCreateDialog) {
        var customTitle by remember { mutableStateOf("") }
        var customSummary by remember { mutableStateOf("") }
        var customKeyPoints by remember { mutableStateOf("") }
        var customTags by remember { mutableStateOf("自定义笔记") }

        AlertDialog(
            onDismissRequest = { showCreateDialog = false },
            title = { Text("手动录入知识笔记", fontWeight = FontWeight.Bold, fontSize = 16.sp) },
            text = {
                Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        value = customTitle,
                        onValueChange = { customTitle = it },
                        label = { Text("笔记标题") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = customSummary,
                        onValueChange = { customSummary = it },
                        label = { Text("核心摘要 / 概要") },
                        maxLines = 3,
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = customKeyPoints,
                        onValueChange = { customKeyPoints = it },
                        label = { Text("要点列表 (每行一条)") },
                        maxLines = 4,
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = customTags,
                        onValueChange = { customTags = it },
                        label = { Text("标签 (逗号隔开)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        if (customTitle.isBlank()) return@Button
                        val now = System.currentTimeMillis()
                        val dateStr = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date(now))
                        val pointsList = customKeyPoints.split("\n").filter { it.isNotBlank() }
                        val tagsList = customTags.split(",", "，").map { it.trim() }.filter { it.isNotBlank() }

                        val note = KnowledgeNoteEntity(
                            id = "custom_${now}",
                            bvid = "CUSTOM",
                            title = customTitle.trim(),
                            summary = customSummary.trim(),
                            keyPointsJson = Gson().toJson(pointsList),
                            mindmapMarkdown = "# $customTitle\n## 知识要点\n" + pointsList.joinToString("\n") { "- $it" },
                            tagsJson = Gson().toJson(tagsList),
                            quizJson = "[]",
                            upName = "我的原创笔记",
                            coverUrl = "",
                            createdAt = now,
                            dateStr = dateStr
                        )

                        scope.launch {
                            database.knowledgeNoteDao().insertNote(note)
                            showCreateDialog = false
                            Toast.makeText(context, "笔记已保存！", Toast.LENGTH_SHORT).show()
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange)
                ) {
                    Text("保存入库")
                }
            },
            dismissButton = {
                TextButton(onClick = { showCreateDialog = false }) {
                    Text("取消")
                }
            }
        )
    }
}
