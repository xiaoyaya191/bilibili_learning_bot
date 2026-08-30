package com.bililearn.app.ui.logs

import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.model.LogEntry
import kotlinx.coroutines.launch

@Composable
fun LogScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val engine = BiliLearnApplication.instance.botEngine
    val logs by engine.logs.collectAsState()
    var query by remember { mutableStateOf("") }
    var level by remember { mutableStateOf("ALL") }
    var pendingExport by remember { mutableStateOf("") }
    val filtered = logs.filter { (level == "ALL" || it.level == level) && (query.isBlank() || it.message.contains(query, true)) }
    val exporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/plain")) { uri: Uri? ->
        if (uri != null) scope.launch {
            val ok = runCatching { context.contentResolver.openOutputStream(uri)?.bufferedWriter()?.use { it.write(pendingExport) } ?: error("write failed") }.isSuccess
            Toast.makeText(context, if (ok) "日志导出成功" else "日志导出失败", Toast.LENGTH_SHORT).show()
        }
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
            Column(Modifier.weight(1f)) {
                Text("运行日志", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Text("当前会话共 ${logs.size} 条", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = {
                pendingExport = filtered.joinToString("\n") { "[${it.timestamp}] [${it.level}] ${it.message}" }
                exporter.launch("bililearn-log.txt")
            }) { Icon(Icons.Default.FileDownload, "导出筛选结果") }
            IconButton(onClick = { engine.clearLogs() }) { Icon(Icons.Default.DeleteSweep, "清空日志") }
        }
        OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth().padding(horizontal = 12.dp), label = { Text("搜索日志") }, singleLine = true, leadingIcon = { Icon(Icons.Default.Search, null) })
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(12.dp)) {
            listOf("ALL" to "全部", "INFO" to "信息", "WARN" to "警告", "ERROR" to "错误").forEachIndexed { index, item ->
                SegmentedButton(selected = level == item.first, onClick = { level = item.first }, shape = SegmentedButtonDefaults.itemShape(index, 4)) { Text(item.second) }
            }
        }
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            itemsIndexed(filtered) { index, item -> LogRow(item, index) }
            item { Spacer(Modifier.height(20.dp)) }
        }
    }
}

@Composable
private fun LogRow(item: LogEntry, index: Int) {
    val color = when (item.level) { "ERROR" -> MaterialTheme.colorScheme.error; "WARN" -> Color(0xFFE89224); else -> MaterialTheme.colorScheme.primary }
    Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(6.dp), tonalElevation = 1.dp) {
        Row(Modifier.padding(10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("%03d".format(index + 1), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Column(Modifier.weight(1f)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(item.timestamp, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.labelSmall)
                    Text(item.level, color = color, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.labelSmall)
                }
                Text(item.message, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
