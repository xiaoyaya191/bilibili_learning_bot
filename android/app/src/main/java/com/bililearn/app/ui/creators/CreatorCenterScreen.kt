package com.bililearn.app.ui.creators

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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.model.CandidateVideo
import com.bililearn.app.data.model.UpProfile
import com.bililearn.app.service.BiliBotService
import kotlinx.coroutines.launch

@Composable
fun CreatorCenterScreen() {
    val app = BiliLearnApplication.instance
    val api = app.botEngine.biliApiClient
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var creators by remember { mutableStateOf(emptyList<UpProfile>()) }
    var selected by remember { mutableStateOf<UpProfile?>(null) }
    var videos by remember { mutableStateOf(emptyList<CandidateVideo>()) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var confirmUnfollow by remember { mutableStateOf<UpProfile?>(null) }
    fun refresh() {
        scope.launch {
            loading = true
            api.fetchFollowingUps().onSuccess { creators = it; error = null }.onFailure { error = it.message }
            loading = false
        }
    }
    fun open(up: UpProfile) {
        selected = up
        scope.launch {
            loading = true
            api.fetchUpVideos(up.mid).onSuccess { videos = it; error = null }.onFailure { error = it.message }
            loading = false
        }
    }
    LaunchedEffect(Unit) { refresh() }
    if (selected == null) {
        Column(Modifier.fillMaxSize()) {
            Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) { Text("UP 关注", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold); Text("关注列表与投稿学习", style = MaterialTheme.typography.bodySmall) }
                IconButton(onClick = ::refresh, enabled = !loading) { Icon(Icons.Default.Refresh, "刷新关注列表") }
            }
            when {
                loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text(error.orEmpty(), color = MaterialTheme.colorScheme.error) }
                creators.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("关注列表为空") }
                else -> LazyColumn(contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(creators, key = { it.mid }) { up ->
                        Surface(onClick = { open(up) }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) {
                            ListItem(
                                headlineContent = { Text(up.name, fontWeight = FontWeight.SemiBold) },
                                supportingContent = { Text(up.sign.ifBlank { "UID ${up.mid}" }, maxLines = 2) },
                                leadingContent = { AsyncImage(up.face, null, Modifier.size(44.dp).clip(RoundedCornerShape(6.dp)), contentScale = ContentScale.Crop) },
                                trailingContent = { IconButton(onClick = { confirmUnfollow = up }) { Icon(Icons.Default.PersonRemove, "取消关注") } }
                            )
                        }
                    }
                }
            }
        }
    } else {
        Column(Modifier.fillMaxSize()) {
            Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { selected = null; videos = emptyList(); error = null }) { Icon(Icons.Default.ArrowBack, "返回关注列表") }
                Column(Modifier.weight(1f)) { Text(selected!!.name, fontWeight = FontWeight.Bold); Text("最新投稿 ${videos.size} 条", style = MaterialTheme.typography.labelSmall) }
                IconButton(onClick = { open(selected!!) }) { Icon(Icons.Default.Refresh, "刷新投稿") }
            }
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            error?.let { Text(it, Modifier.padding(12.dp), color = MaterialTheme.colorScheme.error) }
            LazyColumn(contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(videos, key = { it.bvid }) { video ->
                    Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) {
                        ListItem(
                            headlineContent = { Text(video.title, maxLines = 2) },
                            supportingContent = { Text(video.bvid) },
                            leadingContent = { AsyncImage(video.pic, null, Modifier.size(82.dp, 50.dp).clip(RoundedCornerShape(6.dp)), contentScale = ContentScale.Crop) },
                            trailingContent = { IconButton(onClick = { BiliBotService.start(context); app.botEngine.enqueueUserRequestedVideo(video.bvid); Toast.makeText(context, "已加入学习队列", Toast.LENGTH_SHORT).show() }) { Icon(Icons.Default.PlayArrow, "学习视频") } }
                        )
                    }
                }
            }
        }
    }
    confirmUnfollow?.let { up ->
        AlertDialog(
            onDismissRequest = { confirmUnfollow = null },
            title = { Text("取消关注") },
            text = { Text("确定取消关注“${up.name}”吗？该操作会同步到 B 站账号。") },
            confirmButton = { Button(onClick = {
                confirmUnfollow = null
                scope.launch {
                    api.changeFollow(up.mid, false)
                        .onSuccess { creators = creators.filterNot { it.mid == up.mid }; Toast.makeText(context, "已取消关注", Toast.LENGTH_SHORT).show() }
                        .onFailure { Toast.makeText(context, it.message ?: "操作失败", Toast.LENGTH_SHORT).show() }
                }
            }) { Text("确认") } },
            dismissButton = { TextButton(onClick = { confirmUnfollow = null }) { Text("取消") } }
        )
    }
}
