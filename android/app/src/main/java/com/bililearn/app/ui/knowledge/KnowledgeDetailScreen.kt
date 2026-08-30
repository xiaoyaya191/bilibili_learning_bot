package com.bililearn.app.ui.knowledge

import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.database.entity.KnowledgeNoteEntity
import com.bililearn.app.ui.components.MarkmapWebView
import com.bililearn.app.ui.theme.PrimaryOrange

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KnowledgeDetailScreen(
    note: KnowledgeNoteEntity,
    onBack: () -> Unit
) {
    val context = LocalContext.current
    val botEngine = BiliLearnApplication.instance.botEngine
    var selectedTab by remember { mutableIntStateOf(0) }
    val tabs = listOf("知识笔记", "思维导图", "AI测验")
    var showMenu by remember { mutableStateOf(false) }
    var markdownContent by remember { mutableStateOf("") }
    var htmlContent by remember { mutableStateOf("") }
    var jsonContent by remember { mutableStateOf("") }
    var docxContent by remember { mutableStateOf(ByteArray(0)) }
    var pdfContent by remember { mutableStateOf(ByteArray(0)) }
    var pptxContent by remember { mutableStateOf(ByteArray(0)) }

    fun writeExport(uri: Uri?, content: String) {
        if (uri == null) return
        val ok = runCatching {
            context.contentResolver.openOutputStream(uri)?.bufferedWriter()?.use { it.write(content) }
                ?: error("write failed")
        }.isSuccess
        Toast.makeText(context, if (ok) "导出成功" else "导出失败", Toast.LENGTH_SHORT).show()
    }
    fun writeBinaryExport(uri: Uri?, content: ByteArray) {
        if (uri == null) return
        val ok = runCatching {
            context.contentResolver.openOutputStream(uri)?.use { it.write(content) } ?: error("write failed")
        }.isSuccess
        Toast.makeText(context, if (ok) "导出成功" else "导出失败", Toast.LENGTH_SHORT).show()
    }
    val markdownExporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/markdown")) { writeExport(it, markdownContent) }
    val htmlExporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/html")) { writeExport(it, htmlContent) }
    val jsonExporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { writeExport(it, jsonContent) }
    val docxExporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/vnd.openxmlformats-officedocument.wordprocessingml.document")) { writeBinaryExport(it, docxContent) }
    val pdfExporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/pdf")) { writeBinaryExport(it, pdfContent) }
    val pptxExporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/vnd.openxmlformats-officedocument.presentationml.presentation")) { writeBinaryExport(it, pptxContent) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = note.title,
                        maxLines = 1,
                        fontSize = 16.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { showMenu = true }) {
                        Icon(Icons.Default.MoreVert, contentDescription = "更多")
                    }

                    DropdownMenu(
                        expanded = showMenu,
                        onDismissRequest = { showMenu = false }
                    ) {
                        DropdownMenuItem(
                            text = { Text("导出 Markdown 文件") },
                            onClick = {
                                showMenu = false
                                markdownContent = botEngine.documentExportEngine.buildMarkdown(note)
                                markdownExporter.launch("${botEngine.documentExportEngine.safeFileName(note)}.md")
                            }
                        )

                        DropdownMenuItem(
                            text = { Text("导出网页报告 (HTML)") },
                            onClick = {
                                showMenu = false
                                htmlContent = botEngine.documentExportEngine.buildHtml(note)
                                htmlExporter.launch("${botEngine.documentExportEngine.safeFileName(note)}.html")
                            }
                        )

                        DropdownMenuItem(
                            text = { Text("导出结构化数据 (JSON)") },
                            onClick = {
                                showMenu = false
                                jsonContent = botEngine.documentExportEngine.buildJson(note)
                                jsonExporter.launch("${botEngine.documentExportEngine.safeFileName(note)}.json")
                            }
                        )

                        DropdownMenuItem(
                            text = { Text("导出 Word 文档 (DOCX)") },
                            onClick = {
                                showMenu = false
                                docxContent = botEngine.documentExportEngine.buildDocx(note)
                                docxExporter.launch("${botEngine.documentExportEngine.safeFileName(note)}.docx")
                            }
                        )

                        DropdownMenuItem(
                            text = { Text("导出 PDF 报告") },
                            onClick = {
                                showMenu = false
                                pdfContent = botEngine.documentExportEngine.buildPdf(note)
                                pdfExporter.launch("${botEngine.documentExportEngine.safeFileName(note)}.pdf")
                            }
                        )

                        DropdownMenuItem(
                            text = { Text("导出演示文稿 (PPTX)") },
                            onClick = {
                                showMenu = false
                                pptxContent = botEngine.documentExportEngine.buildPptx(note)
                                pptxExporter.launch("${botEngine.documentExportEngine.safeFileName(note)}.pptx")
                            }
                        )

                        HorizontalDivider()

                        DropdownMenuItem(
                            text = { Text("系统分享") },
                            onClick = {
                                showMenu = false
                                val shareText = "【BiliLearn 知识沉淀】\n《${note.title}》\n\n核心摘要:\n${note.summary}\n\n关键要点:\n${note.getKeyPointsList().joinToString("\n") { "- $it" }}"
                                val sendIntent = Intent().apply {
                                    action = Intent.ACTION_SEND
                                    putExtra(Intent.EXTRA_TEXT, shareText)
                                    type = "text/plain"
                                }
                                context.startActivity(Intent.createChooser(sendIntent, "分享知识笔记"))
                            }
                        )
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            TabRow(
                selectedTabIndex = selectedTab,
                contentColor = PrimaryOrange,
                containerColor = MaterialTheme.colorScheme.surface
            ) {
                tabs.forEachIndexed { index, title ->
                    Tab(
                        selected = selectedTab == index,
                        onClick = { selectedTab = index },
                        text = {
                            Text(
                                text = title,
                                fontWeight = if (selectedTab == index) FontWeight.Bold else FontWeight.Normal
                            )
                        }
                    )
                }
            }

            when (selectedTab) {
                0 -> {
                    // 知识笔记 (摘要 + 要点 + 标签)
                    LazyColumn(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        item {
                            Card(
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(12.dp),
                                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                            ) {
                                Column(modifier = Modifier.padding(16.dp)) {
                                    Text(
                                        text = "核心摘要",
                                        fontSize = 15.sp,
                                        fontWeight = FontWeight.Bold,
                                        color = PrimaryOrange
                                    )
                                    Spacer(modifier = Modifier.height(8.dp))
                                    Text(
                                        text = note.summary,
                                        fontSize = 14.sp,
                                        lineHeight = 22.sp,
                                        color = MaterialTheme.colorScheme.onSurface
                                    )
                                }
                            }
                        }

                        item {
                            Text(
                                text = "关键认知要点",
                                fontSize = 16.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }

                        val keyPoints = note.getKeyPointsList()
                        itemsIndexed(keyPoints) { idx, point ->
                            Card(
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(10.dp),
                                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                            ) {
                                Row(
                                    modifier = Modifier.padding(12.dp),
                                    verticalAlignment = Alignment.Top
                                ) {
                                    Box(
                                        modifier = Modifier
                                            .size(22.dp)
                                            .clip(RoundedCornerShape(6.dp))
                                            .background(PrimaryOrange.copy(alpha = 0.15f)),
                                        contentAlignment = Alignment.Center
                                    ) {
                                        Text(
                                            text = "${idx + 1}",
                                            fontSize = 11.sp,
                                            fontWeight = FontWeight.Bold,
                                            color = PrimaryOrange
                                        )
                                    }
                                    Spacer(modifier = Modifier.width(10.dp))
                                    Text(
                                        text = point,
                                        fontSize = 13.sp,
                                        lineHeight = 20.sp,
                                        color = MaterialTheme.colorScheme.onSurface
                                    )
                                }
                            }
                        }

                        item {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                note.getTagsList().forEach { tag ->
                                    SuggestionChip(
                                        onClick = {},
                                        label = { Text("# $tag", fontSize = 12.sp) }
                                    )
                                }
                            }
                        }
                    }
                }

                1 -> {
                    // 交互式 Markmap 思维导图
                    Box(modifier = Modifier.fillMaxSize()) {
                        MarkmapWebView(markdownContent = note.mindmapMarkdown)
                    }
                }

                2 -> {
                    // AI 测验闯关
                    val quizList = note.getQuizList()
                    if (quizList.isEmpty()) {
                        Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = "当前视频未提取到测验题目",
                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f)
                            )
                        }
                    } else {
                        LazyColumn(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(14.dp)
                        ) {
                            itemsIndexed(quizList) { qIdx, qItem ->
                                var selectedOption by remember { mutableStateOf<String?>(null) }
                                var showAnalysis by remember { mutableStateOf(false) }

                                Card(
                                    modifier = Modifier.fillMaxWidth(),
                                    shape = RoundedCornerShape(12.dp),
                                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
                                ) {
                                    Column(modifier = Modifier.padding(16.dp)) {
                                        Text(
                                            text = "第 ${qIdx + 1} 题: ${qItem.question}",
                                            fontWeight = FontWeight.Bold,
                                            fontSize = 15.sp
                                        )
                                        Spacer(modifier = Modifier.height(10.dp))

                                        qItem.options.forEach { opt ->
                                            val isSelected = selectedOption == opt
                                            OutlinedButton(
                                                onClick = {
                                                    selectedOption = opt
                                                    showAnalysis = true
                                                },
                                                modifier = Modifier.fillMaxWidth(),
                                                colors = ButtonDefaults.outlinedButtonColors(
                                                    containerColor = if (isSelected) PrimaryOrange.copy(alpha = 0.1f) else Color.Transparent
                                                ),
                                                shape = RoundedCornerShape(8.dp)
                                            ) {
                                                Text(
                                                    text = opt,
                                                    fontSize = 13.sp,
                                                    color = if (isSelected) PrimaryOrange else MaterialTheme.colorScheme.onSurface
                                                )
                                            }
                                            Spacer(modifier = Modifier.height(4.dp))
                                        }

                                        if (showAnalysis) {
                                            Spacer(modifier = Modifier.height(10.dp))
                                            Text(
                                                text = "正确答案: ${qItem.answer}",
                                                fontWeight = FontWeight.Bold,
                                                color = Color(0xFF2D8A4E),
                                                fontSize = 13.sp
                                            )
                                            Text(
                                                text = "解析: ${qItem.analysis}",
                                                fontSize = 12.sp,
                                                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.7f),
                                                lineHeight = 18.sp
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
