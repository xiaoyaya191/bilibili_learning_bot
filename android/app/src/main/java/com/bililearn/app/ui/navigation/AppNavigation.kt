package com.bililearn.app.ui.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Book
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material.icons.filled.School
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material.icons.filled.AccountBox
import androidx.compose.material.icons.filled.Construction
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.MarkUnreadChatAlt
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.HealthAndSafety
import androidx.compose.material.icons.filled.AutoFixHigh
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material.icons.outlined.Chat
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material.icons.outlined.VideoLibrary
import androidx.compose.material.icons.outlined.AccountBox
import androidx.compose.material.icons.outlined.Construction
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material.icons.outlined.GraphicEq
import androidx.compose.material.icons.outlined.MarkUnreadChatAlt
import androidx.compose.material.icons.outlined.Groups
import androidx.compose.material.icons.outlined.HealthAndSafety
import androidx.compose.material.icons.outlined.AutoFixHigh
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.QrCode
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.outlined.Star
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.QrCode
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.Language

sealed class Screen(val route: String, val title: String, val selectedIcon: ImageVector, val unselectedIcon: ImageVector) {
    data object Dashboard : Screen("dashboard", "\u4eea\u8868\u76d8", Icons.Filled.Dashboard, Icons.Outlined.Dashboard)
    data object Login : Screen("login", "扫码登录", Icons.Filled.QrCode, Icons.Outlined.QrCode)
    data object WatchHistory : Screen("watch-history", "观看历史", Icons.Filled.History, Icons.Outlined.History)
    data object Official : Screen("official", "官网", Icons.Filled.Language, Icons.Outlined.Language)
    data object Knowledge : Screen("knowledge", "\u77e5\u8bc6\u5e93", Icons.Filled.Book, Icons.Outlined.Book)
    data object Workshop : Screen("workshop", "\u5de5\u4f5c\u574a", Icons.Filled.Bolt, Icons.Outlined.Bolt)
    data object Exam : Screen("exam", "\u8003\u8bd5", Icons.Filled.School, Icons.Outlined.School)
    data object Tutor : Screen("tutor", "助手对话", Icons.Filled.Chat, Icons.Outlined.Chat)
    data object Settings : Screen("settings", "机器人设置", Icons.Filled.Tune, Icons.Outlined.Tune)
    data object AppSettings : Screen("app-settings", "软件设置", Icons.Filled.Settings, Icons.Outlined.Settings)
    data object ActionReview : Screen("reviews", "\u884c\u4e3a\u5ba1\u6838", Icons.Filled.Inbox, Icons.Outlined.Inbox)
    data object VideoLibrary : Screen("video-library", "视频库", Icons.Filled.VideoLibrary, Icons.Outlined.VideoLibrary)
    data object PersonalHub : Screen("personal-hub", "个人数据", Icons.Filled.AccountBox, Icons.Outlined.AccountBox)
    data object ToolCenter : Screen("tool-center", "工具中心", Icons.Filled.Construction, Icons.Outlined.Construction)
    data object Logs : Screen("logs", "运行日志", Icons.Filled.Terminal, Icons.Outlined.Terminal)
    data object Asr : Screen("asr", "语音转写", Icons.Filled.GraphicEq, Icons.Outlined.GraphicEq)
    data object Messages : Screen("messages", "B 站私聊", Icons.Filled.MarkUnreadChatAlt, Icons.Outlined.MarkUnreadChatAlt)
    data object Creators : Screen("creators", "UP 关注", Icons.Filled.Groups, Icons.Outlined.Groups)
    data object Diagnostics : Screen("diagnostics", "系统诊断", Icons.Filled.HealthAndSafety, Icons.Outlined.HealthAndSafety)
    data object Advanced : Screen("advanced", "高级中心", Icons.Filled.AutoFixHigh, Icons.Outlined.AutoFixHigh)
    data object Interests : Screen("interests", "兴趣爱好", Icons.Filled.Star, Icons.Outlined.Star)
    data object Personas : Screen("personas", "自定义人格", Icons.Filled.Person, Icons.Outlined.Person)

    companion object {
        val drawerItems = listOf(Dashboard, Login, WatchHistory, Official, VideoLibrary, Creators, Knowledge, Workshop, Tutor, Exam, Interests, Personas, PersonalHub, ToolCenter, Advanced, Messages, Logs, ActionReview, Diagnostics, Settings, AppSettings)
        val drawerGroups = listOf(
            "工作台" to listOf(Dashboard),
            "账号" to listOf(Login, WatchHistory, Official),
            "学习" to listOf(VideoLibrary, Knowledge, Workshop, Exam),
            "AI" to listOf(Tutor, Personas, ToolCenter, Advanced),
            "B站" to listOf(Creators, Messages, ActionReview),
            "个人" to listOf(Interests, PersonalHub),
            "系统" to listOf(Settings, AppSettings, Logs, Diagnostics)
        )
    }
}
