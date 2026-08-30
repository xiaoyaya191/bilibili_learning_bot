package com.bililearn.app.ui.more

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.DataUsage
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MoreScreen(onTutor: () -> Unit, onSettings: () -> Unit, onAppSettings: () -> Unit, onReviews: () -> Unit, onDataCenter: () -> Unit) {
    Scaffold(topBar = { TopAppBar(title = { Text("\u66f4\u591a\u529f\u80fd") }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item { Text("\u529f\u80fd\u4e2d\u5fc3", style = MaterialTheme.typography.headlineSmall) }
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column {
                        ListItem(leadingContent = { Icon(Icons.Default.Chat, null) }, headlineContent = { Text("\u77e5\u8bc6\u5bfc\u5e08") }, supportingContent = { Text("AI \u95ee\u7b54\u548c\u5386\u53f2\u4f1a\u8bdd") }, trailingContent = { TextButton(onClick = onTutor) { Text("\u8fdb\u5165") } })
                        ListItem(leadingContent = { Icon(Icons.Default.DataUsage, null) }, headlineContent = { Text("\u6570\u636e\u4e2d\u5fc3") }, supportingContent = { Text("\u914d\u7f6e\u3001\u5907\u4efd\u548c\u6062\u590d") }, trailingContent = { TextButton(onClick = onDataCenter) { Text("\u8fdb\u5165") } })
                        ListItem(leadingContent = { Icon(Icons.Default.Assessment, null) }, headlineContent = { Text("\u5b66\u4e60\u7edf\u8ba1") }, supportingContent = { Text("\u77e5\u8bc6\u5e93\u548c\u5b66\u4e60\u72b6\u6001") }, trailingContent = { TextButton(onClick = onDataCenter) { Text("\u67e5\u770b") } })
                        ListItem(leadingContent = { Icon(Icons.Default.Inbox, null) }, headlineContent = { Text("\u884c\u4e3a\u5ba1\u6838") }, supportingContent = { Text("\u70b9\u8d5e\u3001\u6295\u5e01\u3001\u6536\u85cf\u548c\u8bc4\u8bba") }, trailingContent = { TextButton(onClick = onReviews) { Text("\u8fdb\u5165") } })
                        ListItem(leadingContent = { Icon(Icons.Default.Settings, null) }, headlineContent = { Text("\u8bbe\u7f6e") }, supportingContent = { Text("AI\u3001B \u7ad9\u548c\u81ea\u52a8\u5b66\u4e60") }, trailingContent = { TextButton(onClick = onSettings) { Text("\u8fdb\u5165") } })
                        ListItem(leadingContent = { Icon(Icons.Default.Settings, null) }, headlineContent = { Text("软件设置") }, supportingContent = { Text("主题、背景图片和界面动画") }, trailingContent = { TextButton(onClick = onAppSettings) { Text("进入") } })
                    }
                }
            }
        }
    }
}
