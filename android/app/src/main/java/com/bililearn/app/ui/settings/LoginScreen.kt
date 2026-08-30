package com.bililearn.app.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun LoginScreen() {
    val showDialog = remember { mutableStateOf(true) }
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("B站账号", style = MaterialTheme.typography.headlineSmall)
        Text("使用手机客户端扫码，或切换到网页登录", modifier = Modifier.padding(top = 8.dp))
        Button(onClick = { showDialog.value = true }, modifier = Modifier.padding(top = 20.dp)) {
            Text("打开登录")
        }
    }
    if (showDialog.value) {
        BiliLoginDialog(
            onDismiss = { showDialog.value = false },
            onLoginSuccess = { showDialog.value = false }
        )
    }
}
