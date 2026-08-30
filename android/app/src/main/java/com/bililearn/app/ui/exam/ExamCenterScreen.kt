package com.bililearn.app.ui.exam

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.data.model.QuizItem

data class ExamQuestion(val source: String, val item: QuizItem)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExamCenterScreen() {
    val notes by BiliLearnApplication.instance.database.knowledgeNoteDao().getAllNotesFlow().collectAsState(initial = emptyList())
    val questions = remember(notes) { notes.flatMap { note -> note.getQuizList().map { ExamQuestion(note.title, it) } } }
    val answers = remember { mutableStateMapOf<Int, String>() }
    var submitted by remember { mutableIntStateOf(0) }
    Scaffold(topBar = { TopAppBar(title = { Text("\u8003\u8bd5\u4e2d\u5fc3") }) }) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item {
                Text("\u72ec\u7acb\u51fa\u9898\u4e0e\u5b66\u4e60\u6d4b\u9a8c", style = MaterialTheme.typography.headlineSmall)
                Text("\u9898\u76ee\u6765\u6e90\uff1a\u5df2\u4fdd\u5b58\u7684\u77e5\u8bc6\u5361\u7247\u3002\u5171 ${questions.size} \u9898", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(8.dp))
            }
            if (questions.isEmpty()) item { Card(Modifier.fillMaxWidth()) { Text("\u6682\u65e0\u6d4b\u9a8c\u9898\u76ee\uff0c\u8bf7\u5148\u5728\u5de5\u4f5c\u574a\u5b66\u4e60\u89c6\u9891\u3002", Modifier.padding(16.dp)) } }
            else {
                itemsIndexed(questions) { index, question ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(14.dp)) {
                            Text("${index + 1}. ${question.item.question}", style = MaterialTheme.typography.titleMedium)
                            Text(question.source, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            question.item.options.forEach { option -> FilterChip(answers[index] == option, { answers[index] = option }, label = { Text(option) }, Modifier.fillMaxWidth().padding(top = 4.dp)) }
                            if (submitted > 0 && answers.containsKey(index)) Text(if (answers[index] == question.item.answer) "\u56de\u7b54\u6b63\u786e" else "\u6b63\u786e\u7b54\u6848\uff1a${question.item.answer}", color = if (answers[index] == question.item.answer) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error, fontSize = 12.sp)
                        }
                    }
                }
                item { Button({ submitted++ }, Modifier.fillMaxWidth()) { Text("\u63d0\u4ea4\u7b54\u6848") }; OutlinedButton({ answers.clear(); submitted = 0 }, Modifier.fillMaxWidth()) { Text("\u91cd\u65b0\u5f00\u59cb") } }
            }
        }
    }
}
