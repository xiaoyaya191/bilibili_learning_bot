package com.bililearn.app.ui.settings

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.network.crypto.BiliCrypto
import com.bililearn.app.ui.theme.PrimaryOrange
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun BiliLoginDialog(
    onDismiss: () -> Unit,
    onLoginSuccess: () -> Unit
) {
    val scope = rememberCoroutineScope()
    val botEngine = BiliLearnApplication.instance.botEngine
    val prefs = botEngine.preferences

    var loginMode by remember { mutableIntStateOf(1) } // 默认扫码登录；可切换网页登录
    var qrBitmap by remember { mutableStateOf<Bitmap?>(null) }
    var qrStatusText by remember { mutableStateOf("正在生成二维码...") }
    var isPollingQr by remember { mutableStateOf(false) }
    var webProgress by remember { mutableFloatStateOf(0f) }
    var isLoadingWeb by remember { mutableStateOf(true) }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            usePlatformDefaultWidth = false,
            decorFitsSystemWindows = true
        )
    ) {
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .padding(12.dp),
            shape = RoundedCornerShape(16.dp),
            color = MaterialTheme.colorScheme.surface,
            tonalElevation = 6.dp
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                // 顶部导航栏
                TopAppBar(
                    title = {
                        Text(
                            text = if (loginMode == 0) "B站 PC电脑端登录" else "B站 APP 扫码登录",
                            fontSize = 16.sp,
                            fontWeight = FontWeight.Bold
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = onDismiss) {
                            Icon(Icons.Default.Close, contentDescription = "关闭")
                        }
                    },
                    actions = {
                        TextButton(onClick = { loginMode = if (loginMode == 0) 1 else 0 }) {
                            Icon(
                                imageVector = if (loginMode == 0) Icons.Default.QrCode else Icons.Default.Language,
                                contentDescription = null,
                                tint = PrimaryOrange,
                                modifier = Modifier.size(18.dp)
                            )
                            Spacer(modifier = Modifier.width(4.dp))
                            Text(
                                text = if (loginMode == 0) "切换扫码" else "切换网页",
                                fontSize = 13.sp,
                                color = PrimaryOrange,
                                fontWeight = FontWeight.SemiBold
                            )
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface)
                )

                if (loginMode == 0 && isLoadingWeb) {
                    LinearProgressIndicator(
                        progress = { webProgress },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(3.dp),
                        color = PrimaryOrange,
                        trackColor = Color.Transparent
                    )
                }

                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f)
                ) {
                    if (loginMode == 0) {
                        // 强制电脑端 PC 网页版登录 (全屏自适应视口与缩放适配)
                        AndroidView(
                            factory = { context ->
                                WebView(context).apply {
                                    settings.javaScriptEnabled = true
                                    settings.domStorageEnabled = true
                                    settings.useWideViewPort = true
                                    settings.loadWithOverviewMode = true
                                    settings.setSupportZoom(true)
                                    settings.builtInZoomControls = true
                                    settings.displayZoomControls = false
                                    settings.textZoom = 100

                                    // 强制使用 Windows 电脑端 Chrome User-Agent
                                    settings.userAgentString =
                                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

                                    webChromeClient = object : WebChromeClient() {
                                        override fun onProgressChanged(view: WebView?, newProgress: Int) {
                                            webProgress = newProgress / 100f
                                            if (newProgress >= 100) {
                                                isLoadingWeb = false
                                            }
                                        }
                                    }

                                    webViewClient = object : WebViewClient() {
                                        override fun onPageFinished(view: WebView?, url: String?) {
                                            super.onPageFinished(view, url)
                                            isLoadingWeb = false

                                            // 注入 JS 适配手机屏幕宽度与居中 PC 端登录框
                                            val jsInject = """
                                                (function() {
                                                    var meta = document.querySelector('meta[name="viewport"]');
                                                    if (!meta) {
                                                        meta = document.createElement('meta');
                                                        meta.name = 'viewport';
                                                        document.getElementsByTagName('head')[0].appendChild(meta);
                                                    }
                                                    meta.content = 'width=1000, initial-scale=' + (window.innerWidth / 1000).toFixed(2) + ', user-scalable=yes';
                                                    
                                                    var style = document.createElement('style');
                                                    style.innerHTML = 'body { display: flex !important; justify-content: center !important; align-items: center !important; min-height: 100vh !important; background: #f6f7f8 !important; margin: 0 !important; } .login-box, .bili-login-card, .login-container { margin: 20px auto !important; box-shadow: 0 6px 24px rgba(0,0,0,0.12) !important; border-radius: 12px !important; }';
                                                    document.head.appendChild(style);
                                                })();
                                            """.trimIndent()
                                            view?.evaluateJavascript(jsInject, null)

                                            val cookieStr = CookieManager.getInstance().getCookie(url) ?: ""
                                            val cookies = BiliCrypto.parseCookieString(cookieStr)
                                            if (cookies.containsKey("SESSDATA") && cookies.containsKey("bili_jct")) {
                                                val sessData = cookies["SESSDATA"] ?: ""
                                                val biliJct = cookies["bili_jct"] ?: ""
                                                val dedeUserId = cookies["DedeUserID"] ?: ""

                                                prefs.saveBiliCookies(sessData, biliJct, dedeUserId)
                                                scope.launch {
                                                    val profileRes = botEngine.biliApiClient.fetchNavUserInfo()
                                                    if (profileRes.isSuccess) {
                                                        val p = profileRes.getOrThrow()
                                                        prefs.saveBiliCookies(sessData, biliJct, dedeUserId, p.uname, p.avatar)
                                                    }
                                                    onLoginSuccess()
                                                }
                                            }
                                        }
                                    }
                                    loadUrl("https://passport.bilibili.com/login")
                                }
                            },
                            modifier = Modifier.fillMaxSize()
                        )
                    } else {
                        // 二维码扫码模式
                        Column(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(24.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.Center
                        ) {
                            if (qrBitmap != null) {
                                Surface(
                                    shape = RoundedCornerShape(16.dp),
                                    tonalElevation = 2.dp,
                                    modifier = Modifier.padding(8.dp)
                                ) {
                                    Image(
                                        bitmap = qrBitmap!!.asImageBitmap(),
                                        contentDescription = "QR Code",
                                        modifier = Modifier
                                            .size(240.dp)
                                            .padding(12.dp)
                                    )
                                }
                                Spacer(modifier = Modifier.height(18.dp))
                                Text(
                                    text = qrStatusText,
                                    fontSize = 14.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = MaterialTheme.colorScheme.primary
                                )
                            } else {
                                CircularProgressIndicator(color = PrimaryOrange)
                                Spacer(modifier = Modifier.height(14.dp))
                                Text(qrStatusText, fontSize = 14.sp)
                            }
                        }

                        LaunchedEffect(loginMode) {
                            if (loginMode == 1) {
                                val qrRes = botEngine.biliApiClient.generateQrCode()
                                if (qrRes.isSuccess) {
                                    val session = qrRes.getOrThrow()
                                    qrBitmap = generateQrBitmap(session.url, 512, 512)
                                    qrStatusText = "请使用 B站 手机客户端扫码"
                                    isPollingQr = true

                                    while (isPollingQr) {
                                        delay(2000)
                                        val pollRes = botEngine.biliApiClient.pollQrCode(session.qrcodeKey)
                                        if (pollRes.isSuccess) {
                                            val (status, cookies) = pollRes.getOrThrow()
                                            when (status) {
                                                "SUCCESS" -> {
                                                    qrStatusText = "登录成功！正在同步数据..."
                                                    isPollingQr = false
                                                    if (cookies != null) {
                                                        val sessData = cookies["SESSDATA"] ?: ""
                                                        val biliJct = cookies["bili_jct"] ?: ""
                                                        val dedeUserId = cookies["DedeUserID"] ?: ""
                                                        prefs.saveBiliCookies(sessData, biliJct, dedeUserId)
                                                        val profileRes = botEngine.biliApiClient.fetchNavUserInfo()
                                                        if (profileRes.isSuccess) {
                                                            val p = profileRes.getOrThrow()
                                                            prefs.saveBiliCookies(sessData, biliJct, dedeUserId, p.uname, p.avatar)
                                                        }
                                                    }
                                                    onLoginSuccess()
                                                }
                                                "TIMEOUT" -> {
                                                    qrStatusText = "二维码已过期，请重新打开"
                                                    isPollingQr = false
                                                }
                                            }
                                        }
                                    }
                                } else {
                                    qrStatusText = "生成二维码失败，请重试"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun generateQrBitmap(content: String, width: Int, height: Int): Bitmap? {
    return try {
        val bitMatrix = QRCodeWriter().encode(content, BarcodeFormat.QR_CODE, width, height)
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.RGB_565)
        for (x in 0 until width) {
            for (y in 0 until height) {
                bitmap.setPixel(x, y, if (bitMatrix[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE)
            }
        }
        bitmap
    } catch (e: Exception) {
        null
    }
}
