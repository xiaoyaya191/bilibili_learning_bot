package com.bililearn.app.ui.settings

import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Animation
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.SettingsSuggest
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.ui.theme.PrimaryOrange
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppSettingsScreen(onOpenBotSettings: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val prefs = BiliLearnApplication.instance.preferences
    var backgroundUri by remember { mutableStateOf(prefs.getBackgroundUri()) }
    var overlay by remember { mutableFloatStateOf(prefs.getBackgroundOverlay()) }
    var appearanceMode by remember { mutableStateOf(prefs.getAppearanceMode()) }
    var animationsEnabled by remember { mutableStateOf(prefs.areAnimationsEnabled()) }

    val backgroundPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri != null) {
            scope.launch {
                val storedUri = withContext(Dispatchers.IO) {
                    runCatching {
                        val target = File(context.filesDir, "custom_background")
                        context.contentResolver.openInputStream(uri)?.use { input ->
                            target.outputStream().use(input::copyTo)
                        } ?: error("无法读取图片")
                        Uri.fromFile(target).toString()
                    }.getOrNull()
                }
                if (storedUri != null) {
                    backgroundUri = storedUri
                    prefs.setBackgroundUri(storedUri)
                    Toast.makeText(context, "背景图片已更新", Toast.LENGTH_SHORT).show()
                } else {
                    Toast.makeText(context, "背景图片读取失败", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("软件设置") }) }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(8.dp),
                colors = CardDefaults.cardColors()
            ) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Palette, contentDescription = null, tint = PrimaryOrange)
                        Spacer(Modifier.padding(horizontal = 4.dp))
                        Text("外观", fontWeight = FontWeight.Bold)
                    }
                    Text("主题")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("system" to "跟随系统", "light" to "浅色", "dark" to "深色").forEach { (mode, label) ->
                            FilterChip(
                                selected = appearanceMode == mode,
                                onClick = {
                                    appearanceMode = mode
                                    prefs.setAppearanceMode(mode)
                                },
                                label = { Text(label) }
                            )
                        }
                    }

                    if (backgroundUri.isNotBlank()) {
                        AsyncImage(
                            model = backgroundUri,
                            contentDescription = "当前背景图片",
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.fillMaxWidth().height(140.dp)
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = { backgroundPicker.launch(arrayOf("image/*")) },
                            modifier = Modifier.weight(1f),
                            colors = ButtonDefaults.buttonColors(containerColor = PrimaryOrange)
                        ) {
                            Icon(Icons.Default.Image, contentDescription = null)
                            Text(if (backgroundUri.isBlank()) "选择背景" else "更换背景", Modifier.padding(start = 6.dp))
                        }
                        if (backgroundUri.isNotBlank()) {
                            OutlinedButton(onClick = {
                                File(context.filesDir, "custom_background").delete()
                                backgroundUri = ""
                                prefs.setBackgroundUri("")
                            }) {
                                Icon(Icons.Default.DeleteOutline, contentDescription = "清除背景")
                            }
                        }
                    }
                    Text("背景遮罩强度 ${(overlay * 100).toInt()}%")
                    Slider(
                        value = overlay,
                        onValueChange = { overlay = it },
                        onValueChangeFinished = { prefs.setBackgroundOverlay(overlay) },
                        valueRange = 0.2f..0.95f
                    )
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(Icons.Default.Animation, contentDescription = null)
                        Text("界面动画", Modifier.padding(start = 8.dp).weight(1f))
                        Switch(
                            checked = animationsEnabled,
                            onCheckedChange = {
                                animationsEnabled = it
                                prefs.setAnimationsEnabled(it)
                            }
                        )
                    }
                }
            }

            Card(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(Icons.Default.SettingsSuggest, contentDescription = null, tint = PrimaryOrange)
                    Column(Modifier.padding(horizontal = 10.dp).weight(1f)) {
                        Text("机器人与服务配置", fontWeight = FontWeight.Bold)
                        Text("人格、模型、B 站账号、兴趣和自动化策略")
                    }
                    OutlinedButton(onClick = onOpenBotSettings) { Text("打开") }
                }
            }
        }
    }
}
