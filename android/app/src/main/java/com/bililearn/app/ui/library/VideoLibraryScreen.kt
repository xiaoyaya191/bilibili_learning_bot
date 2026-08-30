package com.bililearn.app.ui.library

import android.widget.Toast
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.database.entity.KnowledgeNoteEntity
import com.bililearn.app.data.model.CandidateVideo
import com.bililearn.app.data.model.FavoriteFolder
import com.bililearn.app.service.BiliBotService
import kotlinx.coroutines.launch

private data class LibraryTab(val title: String, val icon: androidx.compose.ui.graphics.vector.ImageVector)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VideoLibraryScreen(onSelectNote: (KnowledgeNoteEntity) -> Unit) {
    val app = BiliLearnApplication.instance
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val learned by app.database.knowledgeNoteDao().getAllNotesFlow().collectAsState(initial = emptyList())
    val tabs = remember { listOf(LibraryTab("稍后", Icons.Default.Schedule), LibraryTab("历史", Icons.Default.History), LibraryTab("收藏", Icons.Default.Favorite), LibraryTab("动态", Icons.Default.DynamicFeed), LibraryTab("本地", Icons.Default.Inventory2)) }
    var tab by remember { mutableIntStateOf(0) }
    var videos by remember { mutableStateOf(emptyList<CandidateVideo>()) }
    var folders by remember { mutableStateOf(emptyList<FavoriteFolder>()) }
    var folder by remember { mutableStateOf<FavoriteFolder?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var confirmClear by remember { mutableStateOf(false) }
    var folderDialog by remember { mutableStateOf<String?>(null) }
    var folderName by remember { mutableStateOf("") }

    fun load(index: Int = tab) {
        if (index == 4) return
        if (!app.preferences.isBiliLoggedIn()) { error = "请先在机器人设置中登录 B 站"; videos = emptyList(); return }
        scope.launch {
            loading = true
            error = null
            val result = when (index) {
                0 -> runCatching { app.botEngine.biliApiClient.fetchToviewList() }
                1 -> app.botEngine.biliApiClient.fetchWatchHistory()
                2 -> {
                    val folderResult = app.botEngine.biliApiClient.fetchFavoriteFolders()
                    folderResult.fold(
                        onSuccess = {
                            folders = it
                            val selected = folder?.takeIf { old -> it.any { value -> value.id == old.id } } ?: it.firstOrNull()
                            folder = selected
                            if (selected == null) Result.success(emptyList()) else app.botEngine.biliApiClient.fetchFavoriteVideos(selected.id)
                        },
                        onFailure = { Result.failure(it) }
                    )
                }
                else -> app.botEngine.biliApiClient.fetchDynamicVideos()
            }
            result.onSuccess { videos = it }.onFailure { error = it.message ?: "加载失败"; videos = emptyList() }
            loading = false
        }
    }

    LaunchedEffect(Unit) { load(0) }
    Scaffold(
        topBar = {
            Column(Modifier.fillMaxWidth().padding(top = 6.dp)) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("视频库", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                        Text("B 站内容与本地学习记录", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (tab == 0 && videos.isNotEmpty()) IconButton(onClick = { confirmClear = true }) { Icon(Icons.Default.DeleteSweep, "清空稍后再看") }
                    if (tab != 4 && videos.isNotEmpty()) IconButton(onClick = {
                        BiliBotService.start(context)
                        videos.forEach { app.botEngine.enqueueUserRequestedVideo(it.bvid) }
                        Toast.makeText(context, "已加入 ${videos.size} 个批量学习任务", Toast.LENGTH_SHORT).show()
                    }) { Icon(Icons.Default.PlaylistAdd, "批量加入学习队列") }
                    if (tab != 4) IconButton(onClick = { load() }, enabled = !loading) { Icon(Icons.Default.Refresh, "刷新") }
                }
                ScrollableTabRow(selectedTabIndex = tab, edgePadding = 8.dp) {
                    tabs.forEachIndexed { index, item ->
                        Tab(selected = tab == index, onClick = { tab = index; load(index) }, icon = { Icon(item.icon, null) }, text = { Text(item.title) })
                    }
                }
            }
        }
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            if (tab == 2 && folders.isNotEmpty()) {
                FolderPicker(
                    folders = folders,
                    selected = folder,
                    onSelect = { selected ->
                        folder = selected
                        scope.launch {
                            loading = true
                            app.botEngine.biliApiClient.fetchFavoriteVideos(selected.id)
                                .onSuccess { videos = it; error = null }
                                .onFailure { error = it.message }
                            loading = false
                        }
                    },
                    onCreate = { folderName = ""; folderDialog = "create" },
                    onRename = { folderName = folder?.title.orEmpty(); folderDialog = "rename" },
                    onDelete = { folderDialog = "delete" }
                )
            }
            when {
                loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                tab == 4 -> LocalHistoryList(learned, onSelectNote)
                error != null -> EmptyState(error.orEmpty(), Icons.Default.ErrorOutline)
                videos.isEmpty() -> EmptyState("这里还没有内容", tabs[tab].icon)
                else -> RemoteVideoList(
                    videos = videos,
                    allowRemove = tab == 0,
                    onLearn = { video ->
                        BiliBotService.start(context)
                        app.botEngine.enqueueUserRequestedVideo(video.bvid)
                        Toast.makeText(context, "已加入学习队列", Toast.LENGTH_SHORT).show()
                    },
                    onRemove = { video ->
                        scope.launch {
                            app.botEngine.biliApiClient.removeFromToview(video.bvid)
                                .onSuccess { videos = videos.filterNot { it.bvid == video.bvid } }
                                .onFailure { Toast.makeText(context, it.message ?: "删除失败", Toast.LENGTH_SHORT).show() }
                        }
                    }
                )
            }
        }
    }
    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text("清空稍后再看") },
            text = { Text("该操作会同步清空 B 站账号中的稍后再看列表，无法在应用内撤销。") },
            confirmButton = {
                Button(onClick = {
                    confirmClear = false
                    scope.launch {
                        app.botEngine.biliApiClient.clearToview()
                            .onSuccess { videos = emptyList() }
                            .onFailure { Toast.makeText(context, it.message ?: "清空失败", Toast.LENGTH_SHORT).show() }
                    }
                }) { Text("确认清空") }
            },
            dismissButton = { TextButton(onClick = { confirmClear = false }) { Text("取消") } }
        )
    }
    folderDialog?.let { mode ->
        AlertDialog(
            onDismissRequest = { folderDialog = null },
            title = { Text(when (mode) { "create" -> "新建收藏夹"; "rename" -> "重命名收藏夹"; else -> "删除收藏夹" }) },
            text = {
                if (mode == "delete") Text("确定删除“${folder?.title.orEmpty()}”吗？该操作会同步到 B 站账号。")
                else OutlinedTextField(folderName, { folderName = it }, label = { Text("收藏夹名称") }, singleLine = true)
            },
            confirmButton = {
                Button(onClick = {
                    val selectedId = folder?.id
                    folderDialog = null
                    scope.launch {
                        val result = when (mode) {
                            "create" -> app.botEngine.biliApiClient.createFavoriteFolder(folderName)
                            "rename" -> if (selectedId != null) app.botEngine.biliApiClient.renameFavoriteFolder(selectedId, folderName) else Result.failure(Exception("未选择收藏夹"))
                            else -> if (selectedId != null) app.botEngine.biliApiClient.deleteFavoriteFolder(selectedId) else Result.failure(Exception("未选择收藏夹"))
                        }
                        result.onSuccess { folder = null; load(2) }.onFailure { Toast.makeText(context, it.message ?: "操作失败", Toast.LENGTH_SHORT).show() }
                    }
                }, enabled = mode == "delete" || folderName.isNotBlank()) { Text("确认") }
            },
            dismissButton = { TextButton(onClick = { folderDialog = null }) { Text("取消") } }
        )
    }
}

@Composable
private fun FolderPicker(
    folders: List<FavoriteFolder>,
    selected: FavoriteFolder?,
    onSelect: (FavoriteFolder) -> Unit,
    onCreate: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth().padding(end = 112.dp)) {
            Icon(Icons.Default.Folder, null)
            Spacer(Modifier.width(8.dp))
            Text(selected?.let { "${it.title} (${it.mediaCount})" } ?: "选择收藏夹", modifier = Modifier.weight(1f))
            Icon(Icons.Default.ArrowDropDown, null)
        }
        Row(Modifier.align(Alignment.CenterEnd)) {
            IconButton(onClick = onCreate) { Icon(Icons.Default.CreateNewFolder, "新建收藏夹") }
            IconButton(onClick = onRename, enabled = selected != null) { Icon(Icons.Default.DriveFileRenameOutline, "重命名收藏夹") }
            IconButton(onClick = onDelete, enabled = selected != null) { Icon(Icons.Default.DeleteOutline, "删除收藏夹") }
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            folders.forEach { value ->
                DropdownMenuItem(text = { Text("${value.title} (${value.mediaCount})") }, onClick = { expanded = false; onSelect(value) })
            }
        }
    }
}

@Composable
private fun RemoteVideoList(videos: List<CandidateVideo>, allowRemove: Boolean, onLearn: (CandidateVideo) -> Unit, onRemove: (CandidateVideo) -> Unit) {
    LazyColumn(
        state = rememberLazyListState(),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        items(videos, key = { "${it.source}-${it.bvid}" }) { video ->
            Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) {
                Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                    AsyncImage(video.pic, null, Modifier.size(96.dp, 60.dp).clip(RoundedCornerShape(6.dp)), contentScale = ContentScale.Crop)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(video.title, maxLines = 2, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                        Text(listOf(video.ownerName, formatDuration(video.duration)).filter { it.isNotBlank() }.joinToString("  "), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    IconButton(onClick = { onLearn(video) }) { Icon(Icons.Default.PlayArrow, "加入学习队列") }
                    if (allowRemove) IconButton(onClick = { onRemove(video) }) { Icon(Icons.Default.DeleteOutline, "从稍后再看删除") }
                }
            }
        }
        item { Spacer(Modifier.height(20.dp)) }
    }
}

@Composable
private fun LocalHistoryList(notes: List<KnowledgeNoteEntity>, onSelect: (KnowledgeNoteEntity) -> Unit) {
    if (notes.isEmpty()) { EmptyState("还没有本地学习记录", Icons.Default.Inventory2); return }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(notes, key = { it.id }) { note ->
            Surface(onClick = { onSelect(note) }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) {
                ListItem(
                    headlineContent = { Text(note.title, maxLines = 2, fontWeight = FontWeight.SemiBold) },
                    supportingContent = { Text(listOf(note.upName, note.dateStr.take(16)).filter { it.isNotBlank() }.joinToString("  ")) },
                    leadingContent = {
                        if (note.coverUrl.isNotBlank()) AsyncImage(note.coverUrl, null, Modifier.size(76.dp, 48.dp).clip(RoundedCornerShape(6.dp)), contentScale = ContentScale.Crop)
                        else Icon(Icons.Default.Article, null)
                    }
                )
            }
        }
    }
}

@Composable
private fun EmptyState(message: String, icon: androidx.compose.ui.graphics.vector.ImageVector) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Icon(icon, null, Modifier.size(42.dp), tint = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.3f))
            Text(message, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

private fun formatDuration(seconds: Long): String {
    if (seconds <= 0) return ""
    val h = seconds / 3600
    val m = seconds % 3600 / 60
    val s = seconds % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%02d:%02d".format(m, s)
}
