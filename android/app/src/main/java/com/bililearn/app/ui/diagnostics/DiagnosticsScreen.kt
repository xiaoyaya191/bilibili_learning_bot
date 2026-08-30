package com.bililearn.app.ui.diagnostics

import android.app.ActivityManager
import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.os.StatFs
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.network.research.WebResearchClient
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

private data class CheckResult(val name: String, val ok: Boolean, val detail: String)

@Composable
fun DiagnosticsScreen() {
    val context = LocalContext.current
    val app = BiliLearnApplication.instance
    val scope = rememberCoroutineScope()
    var running by remember { mutableStateOf(false) }
    var results by remember { mutableStateOf(systemChecks(context)) }
    fun runChecks() {
        scope.launch {
            running = true
            val remote = coroutineScope {
                val bili = async { app.botEngine.biliApiClient.fetchNavUserInfo() }
                val models = async { app.botEngine.llmClient.fetchAvailableModels() }
                val research = async { WebResearchClient().searchWikipedia("Bilibili") }
                listOf(
                    bili.await().fold({ CheckResult("B 站账号", true, "已登录: ${it.uname}，UID ${it.uid}") }, { CheckResult("B 站账号", false, it.message ?: "检查失败") }),
                    models.await().fold({ CheckResult("模型服务", true, "连接成功，可用模型 ${it.size} 个") }, { CheckResult("模型服务", false, it.message ?: "检查失败") }),
                    research.await().fold({ CheckResult("资料检索", it.isNotEmpty(), "返回 ${it.size} 条结果") }, { CheckResult("资料检索", false, it.message ?: "检查失败") })
                )
            }
            results = systemChecks(context) + remote
            running = false
        }
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(16.dp)) {
            Column(Modifier.weight(1f)) {
                Text("系统诊断", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text("网络、账号、模型与设备状态", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            FilledIconButton(onClick = ::runChecks, enabled = !running) { Icon(Icons.Default.PlayArrow, "运行全部诊断") }
        }
        if (running) LinearProgressIndicator(Modifier.fillMaxWidth())
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(results, key = { it.name }) { item ->
                Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), tonalElevation = 1.dp) {
                    ListItem(
                        headlineContent = { Text(item.name, fontWeight = FontWeight.SemiBold) },
                        supportingContent = { Text(item.detail) },
                        leadingContent = { Icon(if (item.ok) Icons.Default.CheckCircle else Icons.Default.Error, null, tint = if (item.ok) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error) }
                    )
                }
            }
            item { Text("远程检查仅在点击右上角运行按钮后发起。模型检查会使用当前机器人设置。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(4.dp)) }
        }
    }
}

private fun systemChecks(context: Context): List<CheckResult> {
    val connectivity = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    val network = connectivity.activeNetwork
    val capabilities = network?.let(connectivity::getNetworkCapabilities)
    val connected = capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
    val transport = when {
        capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true -> "Wi-Fi"
        capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true -> "移动网络"
        capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) == true -> "以太网"
        else -> "未知"
    }
    val stat = StatFs(context.filesDir.absolutePath)
    val freeGb = stat.availableBytes / 1024.0 / 1024 / 1024
    val memoryInfo = ActivityManager.MemoryInfo()
    (context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(memoryInfo)
    val memoryGb = memoryInfo.availMem / 1024.0 / 1024 / 1024
    val appVersion = runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName }.getOrDefault("未知")
    return listOf(
        CheckResult("网络连接", connected, if (connected) "已连接，传输类型: $transport" else "当前没有可用网络"),
        CheckResult("应用存储", freeGb > 0.2, "可用空间 %.2f GB".format(freeGb)),
        CheckResult("系统内存", !memoryInfo.lowMemory, "可用内存 %.2f GB%s".format(memoryGb, if (memoryInfo.lowMemory) "，系统处于低内存状态" else "")),
        CheckResult("运行环境", true, "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})，BiliLearn $appVersion")
    )
}
