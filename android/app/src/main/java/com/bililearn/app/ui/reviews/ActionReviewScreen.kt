package com.bililearn.app.ui.reviews

import android.widget.Toast
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
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
import com.bililearn.app.data.database.entity.ActionReviewEntity
import com.bililearn.app.ui.theme.BiliPink
import com.bililearn.app.ui.theme.PrimaryOrange
import com.bililearn.app.ui.theme.PurpleAccent
import com.bililearn.app.ui.theme.SuccessGreen
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ActionReviewScreen(
    onBack: () -> Unit
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val botEngine = BiliLearnApplication.instance.botEngine
    val database = BiliLearnApplication.instance.database

    val pendingReviews by database.actionReviewDao().getPendingReviewsFlow().collectAsState(initial = emptyList())
    val allReviews by database.actionReviewDao().getAllReviewsFlow().collectAsState(initial = emptyList())
    var selectedTab by remember { mutableIntStateOf(0) }
    val displayReviews = if (selectedTab == 0) pendingReviews else allReviews.filter { it.status != "PENDING" }
    var showRejectAllConfirmDialog by remember { mutableStateOf(false) }

    Scaffold(
        topBar = { Column {
            TopAppBar(
                title = {
                    Text(
                        text = "AI 行为审核中心",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    if (selectedTab == 0 && pendingReviews.isNotEmpty()) {
                        TextButton(
                            onClick = { showRejectAllConfirmDialog = true }
                        ) {
                            Text("一键拒绝", color = Color(0xFFD14343), fontWeight = FontWeight.SemiBold)
                        }

                        TextButton(
                            onClick = {
                                scope.launch {
                                    var successCount = 0
                                    pendingReviews.forEach { item ->
                                        if (executeAction(botEngine, item).isSuccess) {
                                            database.actionReviewDao().updateStatus(item.id, "APPROVED")
                                            successCount++
                                        }
                                    }
                                    Toast.makeText(context, "已执行 $successCount/${pendingReviews.size} 项，失败项仍保留待审核", Toast.LENGTH_SHORT).show()
                                }
                            }
                        ) {
                            Text("全部批准", color = PrimaryOrange, fontWeight = FontWeight.Bold)
                        }
                    } else if (selectedTab == 1 && displayReviews.isNotEmpty()) {
                        TextButton(onClick = { scope.launch { database.actionReviewDao().clearHistory() } }) { Text("清空历史") }
                    }
                }
            )
            TabRow(selectedTabIndex = selectedTab) {
                Tab(selected = selectedTab == 0, onClick = { selectedTab = 0 }, text = { Text("待审核 (${pendingReviews.size})") })
                Tab(selected = selectedTab == 1, onClick = { selectedTab = 1 }, text = { Text("互动历史") })
            }
        } }
    ) { padding ->
        if (displayReviews.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(
                        imageVector = Icons.Default.CheckCircleOutline,
                        contentDescription = null,
                        tint = SuccessGreen.copy(alpha = 0.5f),
                        modifier = Modifier.size(64.dp)
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = if (selectedTab == 0) "当前审核队列为空" else "暂无互动历史",
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f)
                    )
                    Text(
                        text = if (selectedTab == 0) "AI 产生的外部操作会在此等待人工确认" else "已批准或拒绝的操作会保留在这里",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.4f)
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
                // 顶部快捷批量操作栏
                item {
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f))
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "共 ${pendingReviews.size} 项互动提议待处理",
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Medium,
                                color = MaterialTheme.colorScheme.onSurface
                            )

                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedButton(
                                    onClick = { showRejectAllConfirmDialog = true },
                                    shape = RoundedCornerShape(8.dp),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                                ) {
                                    Icon(Icons.Default.Close, contentDescription = null, tint = Color(0xFFD14343), modifier = Modifier.size(14.dp))
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Text("一键拒绝", color = Color(0xFFD14343), fontSize = 12.sp)
                                }

                                Button(
                                    onClick = {
                                        scope.launch {
                                            var successCount = 0
                                            pendingReviews.forEach { item ->
                                                if (executeAction(botEngine, item).isSuccess) {
                                                    database.actionReviewDao().updateStatus(item.id, "APPROVED")
                                                    successCount++
                                                }
                                            }
                                            Toast.makeText(context, "已执行 $successCount/${pendingReviews.size} 项，失败项仍保留待审核", Toast.LENGTH_SHORT).show()
                                        }
                                    },
                                    colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange),
                                    shape = RoundedCornerShape(8.dp),
                                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                                ) {
                                    Icon(Icons.Default.Check, contentDescription = null, modifier = Modifier.size(14.dp))
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Text("全部批准", fontSize = 12.sp)
                                }
                            }
                        }
                    }
                }

                items(displayReviews, key = { it.id }) { review ->
                    var isEditing by remember { mutableStateOf(false) }
                    var editedText by remember { mutableStateOf(review.targetText) }

                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(14.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                    ) {
                        Column(modifier = Modifier.padding(14.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                val actionLabel = when (review.actionType) {
                                    "LIKE" -> "点赞视频"
                                    "COIN" -> "投币支持"
                                    "COMMENT" -> "公开评论"
                                    "PRIVATE_MSG" -> "回复私信"
                                    else -> "互动操作"
                                }
                                val badgeColor = when (review.actionType) {
                                    "LIKE" -> PrimaryOrange
                                    "COIN" -> Color(0xFFF59E0B)
                                    "COMMENT" -> BiliPink
                                    else -> PurpleAccent
                                }

                                SuggestionChip(
                                    onClick = {},
                                    label = { Text(actionLabel, fontWeight = FontWeight.Bold, color = badgeColor) }
                                )

                                Text(
                                    text = review.bvid,
                                    fontSize = 12.sp,
                                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f)
                                )
                            }

                            Spacer(modifier = Modifier.height(6.dp))
                            Text(
                                text = "目标视频: 《${review.videoTitle}》",
                                fontSize = 14.sp,
                                fontWeight = FontWeight.SemiBold
                            )

                            if (review.reason.isNotEmpty()) {
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = "提议理由: ${review.reason}",
                                    fontSize = 12.sp,
                                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
                                )
                            }

                            if (review.targetText.isNotEmpty()) {
                                Spacer(modifier = Modifier.height(8.dp))
                                if (isEditing) {
                                    OutlinedTextField(
                                        value = editedText,
                                        onValueChange = { editedText = it },
                                        label = { Text("编辑评论/回复内容") },
                                        modifier = Modifier.fillMaxWidth(),
                                        shape = RoundedCornerShape(8.dp)
                                    )
                                } else {
                                    Card(
                                        shape = RoundedCornerShape(8.dp),
                                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.background)
                                    ) {
                                        Text(
                                            text = editedText,
                                            fontSize = 13.sp,
                                            modifier = Modifier.padding(10.dp),
                                            color = MaterialTheme.colorScheme.onSurface
                                        )
                                    }
                                }
                            }

                            Spacer(modifier = Modifier.height(12.dp))

                            if (review.status != "PENDING") {
                                Text(
                                    text = if (review.status == "APPROVED") "已批准并执行" else "已拒绝",
                                    color = if (review.status == "APPROVED") SuccessGreen else Color.Gray,
                                    fontWeight = FontWeight.SemiBold
                                )
                            } else Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                if (review.targetText.isNotEmpty()) {
                                    TextButton(
                                        onClick = { isEditing = !isEditing }
                                    ) {
                                        Text(if (isEditing) "完成编辑" else "修改文案", fontSize = 12.sp)
                                    }
                                }

                                Spacer(modifier = Modifier.weight(1f))

                                OutlinedButton(
                                    onClick = {
                                        scope.launch {
                                            database.actionReviewDao().updateStatus(review.id, "REJECTED")
                                            Toast.makeText(context, "已拒绝", Toast.LENGTH_SHORT).show()
                                        }
                                    },
                                    shape = RoundedCornerShape(8.dp)
                                ) {
                                    Text("拒绝", color = Color.Gray, fontSize = 13.sp)
                                }

                                Button(
                                    onClick = {
                                        scope.launch {
                                            val finalReview = review.copy(targetText = editedText)
                                            val result = executeAction(botEngine, finalReview)
                                            if (result.isSuccess) {
                                                database.actionReviewDao().updateStatus(review.id, "APPROVED")
                                                Toast.makeText(context, "已批准并执行", Toast.LENGTH_SHORT).show()
                                            } else {
                                                Toast.makeText(
                                                    context,
                                                    result.exceptionOrNull()?.message ?: "执行失败，任务仍保留待审核",
                                                    Toast.LENGTH_LONG
                                                ).show()
                                            }
                                        }
                                    },
                                    colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange),
                                    shape = RoundedCornerShape(8.dp)
                                ) {
                                    Text("批准执行", fontSize = 13.sp)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (showRejectAllConfirmDialog) {
        AlertDialog(
            onDismissRequest = { showRejectAllConfirmDialog = false },
            title = { Text("确认一键拒绝？", fontWeight = FontWeight.Bold) },
            text = { Text("将批量忽略并拒绝当前所有 ${pendingReviews.size} 项 AI 互动提议，不会在 B 站执行任何点赞或评论操作。") },
            confirmButton = {
                Button(
                    onClick = {
                        showRejectAllConfirmDialog = false
                        scope.launch {
                            database.actionReviewDao().rejectAllPending()
                            Toast.makeText(context, "已一键拒绝全部提议", Toast.LENGTH_SHORT).show()
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFD14343))
                ) {
                    Text("确认全部拒绝")
                }
            },
            dismissButton = {
                TextButton(onClick = { showRejectAllConfirmDialog = false }) {
                    Text("取消")
                }
            }
        )
    }
}

private suspend fun executeAction(botEngine: com.bililearn.app.engine.BotEngine, review: ActionReviewEntity): Result<Boolean> {
    return when (review.actionType) {
        "LIKE" -> {
            val result = botEngine.biliApiClient.sendLike(review.bvid, like = 1)
            if (result.isSuccess) botEngine.addLog("已点赞：${review.videoTitle}")
            result
        }
        "COIN" -> {
            val result = botEngine.biliApiClient.sendCoin(review.bvid, multiply = 1)
            if (result.isSuccess) botEngine.addLog("已投币：${review.videoTitle}")
            result
        }
        "FAVORITE" -> {
            val detailRes = botEngine.biliApiClient.fetchVideoDetail(review.bvid)
            if (detailRes.isFailure) return Result.failure(detailRes.exceptionOrNull() ?: Exception("获取视频详情失败"))
            val result = botEngine.biliApiClient.sendFavorite(detailRes.getOrThrow().aid)
            if (result.isSuccess) botEngine.addLog("已收藏：${review.videoTitle}")
            result
        }
        "COMMENT" -> {
            val detailRes = botEngine.biliApiClient.fetchVideoDetail(review.bvid)
            if (detailRes.isFailure) return Result.failure(detailRes.exceptionOrNull() ?: Exception("获取视频详情失败"))
            val result = botEngine.biliApiClient.sendComment(detailRes.getOrThrow().aid, review.targetText)
            if (result.isSuccess) botEngine.addLog("已发表评论：${review.targetText.take(20)}...")
            result
        }
        else -> Result.failure(Exception("暂不支持的操作：${review.actionType}"))
    }
}
