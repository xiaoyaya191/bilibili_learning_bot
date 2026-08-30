package com.bililearn.app.ui.dashboard

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.service.BiliBotService
import com.bililearn.app.ui.theme.AccentOrangeBg
import com.bililearn.app.ui.theme.BiliPink
import com.bililearn.app.ui.theme.PrimaryOrange
import com.bililearn.app.ui.theme.PurpleAccent
import com.bililearn.app.ui.theme.SuccessGreen

@Composable
fun DashboardScreen(
    onNavigateToReviews: () -> Unit = {}
) {
    val context = LocalContext.current
    val botEngine = BiliLearnApplication.instance.botEngine
    val database = BiliLearnApplication.instance.database
    val botStatus by botEngine.status.collectAsState()
    val logs by botEngine.logs.collectAsState()
    val pendingTasks by botEngine.pendingTasks.collectAsState()
    val prefs = botEngine.preferences
    val isBiliLoggedIn by prefs.biliLoggedInFlow.collectAsState()
    var currentUname by remember { mutableStateOf(prefs.getUserName()) }
    var currentAvatar by remember { mutableStateOf(prefs.getUserAvatar()) }

    val miniGoalProgress by botEngine.miniGoalEngine.progressFlow.collectAsState()
    val pendingReviewCount by database.actionReviewDao().getPendingCountFlow().collectAsState(initial = 0)

    var manualBvInput by remember { mutableStateOf("") }
    var showGoalEditor by remember { mutableStateOf(false) }
    var targetVideosInput by remember { mutableStateOf("") }
    var targetMinutesInput by remember { mutableStateOf("") }
    val logListState = rememberLazyListState()

    if (showGoalEditor) {
        AlertDialog(
            onDismissRequest = { showGoalEditor = false },
            icon = { Icon(Icons.Default.Edit, contentDescription = null) },
            title = { Text("编辑每日学习目标") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        value = targetVideosInput,
                        onValueChange = { targetVideosInput = it.filter(Char::isDigit) },
                        label = { Text("目标视频数") },
                        singleLine = true
                    )
                    OutlinedTextField(
                        value = targetMinutesInput,
                        onValueChange = { targetMinutesInput = it.filter(Char::isDigit) },
                        label = { Text("目标学习分钟") },
                        singleLine = true
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val videos = targetVideosInput.toIntOrNull()
                        val minutes = targetMinutesInput.toIntOrNull()
                        if (videos != null && videos > 0 && minutes != null && minutes > 0) {
                            botEngine.miniGoalEngine.setTarget(videos, minutes)
                            showGoalEditor = false
                        } else {
                            Toast.makeText(context, "目标必须是大于 0 的整数", Toast.LENGTH_SHORT).show()
                        }
                    }
                ) { Text("保存") }
            },
            dismissButton = {
                TextButton(onClick = { showGoalEditor = false }) { Text("取消") }
            }
        )
    }

    LaunchedEffect(isBiliLoggedIn) {
        if (isBiliLoggedIn && currentUname.isBlank()) {
            val res = botEngine.biliApiClient.fetchNavUserInfo()
            if (res.isSuccess) {
                val p = res.getOrThrow()
                prefs.saveBiliCookies(prefs.getSessData(), prefs.getBiliJct(), prefs.getDedeUserId(), p.uname, p.avatar)
                currentUname = p.uname
                currentAvatar = p.avatar
            }
        }
    }

    val displayName = if (currentUname.isNotBlank()) currentUname else if (prefs.getDedeUserId().isNotBlank()) "UID: ${prefs.getDedeUserId()}" else "已连接"

    LaunchedEffect(logs.size) {
        if (logs.isNotEmpty()) {
            logListState.animateScrollToItem(logs.size - 1)
        }
    }

    Scaffold(
        topBar = {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 18.dp, vertical = 14.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "BiliLearn",
                        fontSize = 24.sp,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Text(
                        text = if (isBiliLoggedIn) "已绑定 B站: $displayName" else "未登录 B站",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.6f)
                    )
                }

                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (pendingReviewCount > 0) {
                        Button(
                            onClick = onNavigateToReviews,
                            colors = ButtonDefaults.buttonColors(containerColor = BiliPink),
                            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                            shape = RoundedCornerShape(20.dp)
                        ) {
                            Icon(Icons.Default.NotificationsActive, contentDescription = null, modifier = Modifier.size(16.dp))
                            Spacer(modifier = Modifier.width(4.dp))
                            Text("待审核 ($pendingReviewCount)", fontSize = 12.sp)
                        }
                        Spacer(modifier = Modifier.width(8.dp))
                    }

                    if (isBiliLoggedIn && currentAvatar.isNotEmpty()) {
                        AsyncImage(
                            model = currentAvatar,
                            contentDescription = "Avatar",
                            modifier = Modifier
                                .size(36.dp)
                                .clip(CircleShape)
                        )
                    } else {
                        Box(
                            modifier = Modifier
                                .size(36.dp)
                                .clip(CircleShape)
                                .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.15f)),
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(
                                imageVector = Icons.Default.Person,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary
                            )
                        }
                    }
                }
            }
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            // 1. 主人指定视频学习 (最高优先级入口)
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Bolt, contentDescription = null, tint = PrimaryOrange, modifier = Modifier.size(20.dp))
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("指定视频学习 (最高优先级)", fontSize = 14.sp, fontWeight = FontWeight.Bold)
                        }

                        Spacer(modifier = Modifier.height(8.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            OutlinedTextField(
                                value = manualBvInput,
                                onValueChange = { manualBvInput = it },
                                placeholder = { Text("粘贴 BV号 或 B站视频链接...", fontSize = 12.sp) },
                                singleLine = true,
                                shape = RoundedCornerShape(12.dp),
                                modifier = Modifier.weight(1f)
                            )

                            Spacer(modifier = Modifier.width(8.dp))

                            Button(
                                onClick = {
                                    val text = manualBvInput.trim()
                                    if (text.isNotBlank()) {
                                        BiliBotService.start(context)
                                        botEngine.enqueueUserRequestedVideo(text)
                                        manualBvInput = ""
                                        Toast.makeText(context, "已加入最高优先级队列！", Toast.LENGTH_SHORT).show()
                                    }
                                },
                                colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange),
                                shape = RoundedCornerShape(12.dp)
                            ) {
                                Text("立即研读", fontSize = 12.sp)
                            }
                        }
                        if (pendingTasks.isNotEmpty()) {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text(
                                text = "待处理 ${pendingTasks.size} 项: ${pendingTasks.take(3).joinToString(", ")}",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 2
                            )
                        }
                    }
                }
            }

            // 2. 每日学习小目标与打卡卡片
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
                                Icon(
                                    Icons.Default.Flag,
                                    contentDescription = null,
                                    tint = PrimaryOrange,
                                    modifier = Modifier.size(20.dp)
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(
                                    text = "今日学习目标 (${miniGoalProgress.streakDays}天连续打卡)",
                                    fontSize = 15.sp,
                                    fontWeight = FontWeight.Bold
                                )
                            }
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    text = "${(miniGoalProgress.progressPercent * 100).toInt()}%",
                                    fontSize = 14.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = PrimaryOrange
                                )
                                IconButton(
                                    onClick = {
                                        targetVideosInput = miniGoalProgress.targetVideos.toString()
                                        targetMinutesInput = miniGoalProgress.targetMinutes.toString()
                                        showGoalEditor = true
                                    },
                                    modifier = Modifier.size(36.dp)
                                ) {
                                    Icon(
                                        Icons.Default.Edit,
                                        contentDescription = "编辑每日学习目标",
                                        modifier = Modifier.size(18.dp)
                                    )
                                }
                            }
                        }

                        Spacer(modifier = Modifier.height(10.dp))

                        LinearProgressIndicator(
                            progress = { miniGoalProgress.progressPercent },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(8.dp)
                                .clip(RoundedCornerShape(4.dp)),
                            color = PrimaryOrange,
                            trackColor = PrimaryOrange.copy(alpha = 0.15f)
                        )

                        Spacer(modifier = Modifier.height(8.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(
                                text = "进度: ${miniGoalProgress.completedVideos} / ${miniGoalProgress.targetVideos} 篇 (${miniGoalProgress.completedMinutes} 分钟)",
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f)
                            )
                            if (miniGoalProgress.isCompleted) {
                                Text(
                                    text = "今日目标已达成",
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = SuccessGreen
                                )
                            }
                        }
                    }
                }
            }

            // 3. 机器人状态与主控制卡片
            item {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = if (botStatus.isRunning) AccentOrangeBg else MaterialTheme.colorScheme.surface
                    )
                ) {
                    Column(modifier = Modifier.padding(18.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Box(
                                    modifier = Modifier
                                        .size(10.dp)
                                        .clip(CircleShape)
                                        .background(if (botStatus.isRunning) SuccessGreen else Color.Gray)
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(
                                    text = if (botStatus.isRunning) "智能巡检中" else "已暂停",
                                    fontWeight = FontWeight.SemiBold,
                                    fontSize = 16.sp
                                )
                            }
                            Text(
                                text = "启动: ${botStatus.startTimeStr}",
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f)
                            )
                        }

                        Spacer(modifier = Modifier.height(10.dp))

                        Text(
                            text = "学习优先级: 主人指定 > 稍后再看 > 主页推荐 (兴趣打分排序)",
                            fontSize = 11.sp,
                            color = PrimaryOrange,
                            fontWeight = FontWeight.Medium
                        )

                        Spacer(modifier = Modifier.height(8.dp))

                        val obs = botStatus.observation
                        Text(
                            text = "当前动态: ${obs.activity}",
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Medium,
                            color = MaterialTheme.colorScheme.primary
                        )
                        if (obs.title.isNotEmpty()) {
                            Text(
                                text = "《${obs.title}》",
                                fontSize = 13.sp,
                                maxLines = 1,
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.8f)
                            )
                        }

                        Spacer(modifier = Modifier.height(16.dp))

                        // 控制按钮组
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            if (!botStatus.isRunning) {
                                Button(
                                    onClick = { BiliBotService.start(context) },
                                    modifier = Modifier.weight(1f),
                                    colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange),
                                    shape = RoundedCornerShape(10.dp)
                                ) {
                                    Icon(Icons.Default.PlayArrow, contentDescription = null)
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Text("启动机器人")
                                }
                            } else {
                                Button(
                                    onClick = { BiliBotService.stop(context) },
                                    modifier = Modifier.weight(1f),
                                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFD14343)),
                                    shape = RoundedCornerShape(10.dp)
                                ) {
                                    Icon(Icons.Default.Stop, contentDescription = null)
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Text("停止运行")
                                }
                            }

                            OutlinedButton(
                                onClick = { botEngine.clearLogs() },
                                shape = RoundedCornerShape(10.dp)
                            ) {
                                Icon(Icons.Default.DeleteOutline, contentDescription = null)
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("清日志")
                            }
                        }
                    }
                }
            }

            // 4. 数据指标卡片 (3列)
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    StatCard(
                        modifier = Modifier.weight(1f),
                        title = "今日已学",
                        value = "${botStatus.processedCount} 篇",
                        icon = Icons.Default.CheckCircle,
                        tint = SuccessGreen
                    )
                    StatCard(
                        modifier = Modifier.weight(1f),
                        title = "知识库总数",
                        value = "${botStatus.kbItemsCount} 篇",
                        icon = Icons.Default.Book,
                        tint = PurpleAccent
                    )
                    StatCard(
                        modifier = Modifier.weight(1f),
                        title = "当前人设",
                        value = botEngine.personaEngine.getActivePersona().name,
                        icon = Icons.Default.Mood,
                        tint = PrimaryOrange
                    )
                }
            }

            // 5. 实时运行日志瀑布流
            item {
                Text(
                    text = "实时运行日志",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(vertical = 4.dp)
                )
            }

            item {
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(260.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                ) {
                    LazyColumn(
                        state = logListState,
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(10.dp)
                    ) {
                        items(logs) { log ->
                            Row(modifier = Modifier.padding(vertical = 2.dp)) {
                                Text(
                                    text = "[${log.timestamp}] ",
                                    fontSize = 12.sp,
                                    fontFamily = FontFamily.Monospace,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                                val textColor = when (log.level) {
                                    "ERROR" -> Color(0xFFE53935)
                                    "WARN" -> Color(0xFFFB8C00)
                                    else -> MaterialTheme.colorScheme.onSurface.copy(alpha = 0.85f)
                                }
                                Text(
                                    text = log.message,
                                    fontSize = 12.sp,
                                    fontFamily = FontFamily.Monospace,
                                    color = textColor
                                )
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
}

@Composable
fun StatCard(
    modifier: Modifier = Modifier,
    title: String,
    value: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    tint: Color
) {
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = tint,
                modifier = Modifier.size(20.dp)
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = title,
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.55f)
            )
            Text(
                text = value,
                fontSize = 14.sp,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface
            )
        }
    }
}
