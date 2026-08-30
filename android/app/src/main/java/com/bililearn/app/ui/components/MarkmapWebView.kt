package com.bililearn.app.ui.components

import android.annotation.SuppressLint
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun MarkmapWebView(
    markdownContent: String,
    modifier: Modifier = Modifier
) {
    var webViewRef by remember { mutableStateOf<WebView?>(null) }
    var isPageLoaded by remember { mutableStateOf(false) }

    LaunchedEffect(markdownContent, isPageLoaded) {
        if (isPageLoaded && webViewRef != null && markdownContent.isNotEmpty()) {
            val escapedMarkdown = markdownContent
                .replace("\\", "\\\\")
                .replace("`", "\\`")
                .replace("$", "\\$")
                .replace("\n", "\\n")
                .replace("\r", "")
            webViewRef?.evaluateJavascript("renderMarkmap(`$escapedMarkdown`);", null)
        }
    }

    AndroidView(
        factory = { context ->
            WebView(context).apply {
                settings.apply {
                    javaScriptEnabled = true
                    domStorageEnabled = true
                    allowFileAccess = true
                    allowContentAccess = true
                    builtInZoomControls = true
                    displayZoomControls = false
                    useWideViewPort = true
                    loadWithOverviewMode = true
                    cacheMode = WebSettings.LOAD_DEFAULT
                }
                webViewClient = object : WebViewClient() {
                    override fun onPageFinished(view: WebView?, url: String?) {
                        super.onPageFinished(view, url)
                        isPageLoaded = true
                        if (markdownContent.isNotEmpty()) {
                            val escapedMarkdown = markdownContent
                                .replace("\\", "\\\\")
                                .replace("`", "\\`")
                                .replace("$", "\\$")
                                .replace("\n", "\\n")
                                .replace("\r", "")
                            view?.evaluateJavascript("renderMarkmap(`$escapedMarkdown`);", null)
                        }
                    }
                }
                loadUrl("file:///android_asset/markmap/markmap.html")
                webViewRef = this
            }
        },
        modifier = modifier.fillMaxSize()
    )
}
