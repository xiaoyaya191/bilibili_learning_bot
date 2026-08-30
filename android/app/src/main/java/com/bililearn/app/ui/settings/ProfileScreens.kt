package com.bililearn.app.ui.settings

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.model.PersonaProfile
import com.bililearn.app.engine.InterestTag
import java.util.UUID

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun InterestsScreen() {
    val app = BiliLearnApplication.instance
    val engine = app.botEngine.interestEngine
    val tags by engine.interestsFlow.collectAsState()
    val exclusions by engine.exclusionsFlow.collectAsState()
    var newInterest by remember { mutableStateOf("") }
    var newExclusion by remember { mutableStateOf("") }
    Scaffold(topBar = { CenterAlignedTopAppBar(title = { Text("兴趣爱好") }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { Text("兴趣标签", style = MaterialTheme.typography.titleLarge) }
            item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { OutlinedTextField(newInterest, { newInterest = it }, Modifier.weight(1f), label = { Text("添加兴趣") }, singleLine = true); IconButton(onClick = { if (newInterest.isNotBlank()) { engine.addInterest(newInterest.trim()); newInterest = "" } }) { Icon(Icons.Default.Add, "添加") } } }
            items(tags, key = { it.name }) { tag -> ListItem(leadingContent = { Icon(Icons.Default.Favorite, null, tint = MaterialTheme.colorScheme.primary) }, headlineContent = { Text(tag.name) }, supportingContent = { Text("权重 %.1f · 命中 %d 次".format(tag.weight, tag.hitCount)) }, trailingContent = { IconButton(onClick = { engine.removeInterest(tag.name) }) { Icon(Icons.Default.DeleteOutline, "删除") } }) }
            item { HorizontalDivider(); Text("排除关键词", style = MaterialTheme.typography.titleLarge) }
            item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { OutlinedTextField(newExclusion, { newExclusion = it }, Modifier.weight(1f), label = { Text("添加排除词") }, singleLine = true); IconButton(onClick = { if (newExclusion.isNotBlank()) { engine.addExclusion(newExclusion.trim()); newExclusion = "" } }) { Icon(Icons.Default.Add, "添加") } } }
            items(exclusions, key = { it }) { word -> ListItem(headlineContent = { Text(word) }, trailingContent = { IconButton(onClick = { engine.removeExclusion(word) }) { Icon(Icons.Default.DeleteOutline, "删除") } }) }
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun PersonasScreen() {
    val prefs = BiliLearnApplication.instance.preferences
    val profiles by prefs.personaProfilesFlow.collectAsState()
    val active by prefs.activePersonaKeyFlow.collectAsState()
    var editing by remember { mutableStateOf<PersonaProfile?>(null) }
    var showEditor by remember { mutableStateOf(false) }
    Scaffold(topBar = { CenterAlignedTopAppBar(title = { Text("自定义人格") }) }) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            Button(onClick = { editing = null; showEditor = true }, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Default.Add, null); Spacer(Modifier.width(8.dp)); Text("新建人格") }
            Spacer(Modifier.height(12.dp))
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) { items(profiles, key = { it.id }) { profile -> Card(shape = RoundedCornerShape(8.dp)) { ListItem(leadingContent = { Icon(Icons.Default.Person, null) }, headlineContent = { Text(profile.name) }, supportingContent = { Text(profile.description.ifBlank { "未填写简介" }) }, trailingContent = { Row { if (active == profile.id) Text("当前", color = MaterialTheme.colorScheme.primary); IconButton(onClick = { prefs.setActivePersonaKey(profile.id) }) { Icon(Icons.Default.Favorite, "启用") }; IconButton(onClick = { editing = profile; showEditor = true }) { Icon(Icons.Default.Edit, "编辑") }; IconButton(onClick = { prefs.deletePersona(profile.id) }) { Icon(Icons.Default.DeleteOutline, "删除") } } }) } } }
        }
    }
    if (showEditor) PersonaEditorDialog(editing) { showEditor = false }
}

@Composable
private fun PersonaEditorDialog(existing: PersonaProfile?, onDismiss: () -> Unit) {
    val prefs = BiliLearnApplication.instance.preferences
    var name by remember(existing) { mutableStateOf(existing?.name.orEmpty()) }
    var description by remember(existing) { mutableStateOf(existing?.description.orEmpty()) }
    var prompt by remember(existing) { mutableStateOf(existing?.systemPrompt.orEmpty()) }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(if (existing == null) "新建人格" else "编辑人格") }, text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) { OutlinedTextField(name, { name = it }, label = { Text("名称") }, singleLine = true); OutlinedTextField(description, { description = it }, label = { Text("简介") }, singleLine = true); OutlinedTextField(prompt, { prompt = it }, label = { Text("系统提示词") }, minLines = 5) } }, confirmButton = { TextButton(onClick = { if (name.isNotBlank() && prompt.isNotBlank()) { val id = existing?.id ?: "custom-" + UUID.randomUUID(); prefs.savePersona(PersonaProfile(id, name.trim(), description.trim(), prompt.trim(), isBuiltIn = false)); prefs.setActivePersonaKey(id); onDismiss() } }) { Text("保存") } }, dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } })
}
