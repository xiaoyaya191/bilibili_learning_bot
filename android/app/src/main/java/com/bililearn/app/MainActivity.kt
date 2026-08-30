package com.bililearn.app

import android.content.Intent
import android.os.Bundle
import android.Manifest
import android.content.pm.PackageManager
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.setContent
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.clickable
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Close
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.lifecycleScope
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.bililearn.app.data.database.entity.KnowledgeNoteEntity
import com.bililearn.app.ui.dashboard.DashboardScreen
import com.bililearn.app.ui.exam.ExamCenterScreen
import com.bililearn.app.ui.knowledge.KnowledgeDetailScreen
import com.bililearn.app.ui.knowledge.KnowledgeListScreen
import com.bililearn.app.ui.library.VideoLibraryScreen
import com.bililearn.app.ui.personal.PersonalHubScreen
import com.bililearn.app.ui.tools.ToolCenterScreen
import com.bililearn.app.ui.logs.LogScreen
import com.bililearn.app.ui.asr.AsrScreen
import com.bililearn.app.ui.messages.PrivateMessagesScreen
import com.bililearn.app.ui.creators.CreatorCenterScreen
import com.bililearn.app.ui.diagnostics.DiagnosticsScreen
import com.bililearn.app.ui.advanced.AdvancedCenterScreen
import com.bililearn.app.ui.navigation.Screen
import com.bililearn.app.ui.reviews.ActionReviewScreen
import com.bililearn.app.ui.settings.SettingsScreen
import com.bililearn.app.ui.settings.AppSettingsScreen
import com.bililearn.app.ui.settings.InterestsScreen
import com.bililearn.app.ui.settings.PersonasScreen
import com.bililearn.app.ui.settings.LoginScreen
import com.bililearn.app.ui.common.BrowserScreen
import com.bililearn.app.ui.theme.BiliLearnTheme
import com.bililearn.app.ui.theme.PrimaryOrange
import com.bililearn.app.ui.tutor.TutorChatScreen
import com.bililearn.app.ui.workshop.WorkshopScreen
import kotlinx.coroutines.launch
import coil.compose.AsyncImage

class MainActivity : ComponentActivity() {

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) {
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {
            val prefs = BiliLearnApplication.instance.preferences
            val appearanceMode by prefs.appearanceModeFlow.collectAsState()
            val backgroundUri by prefs.backgroundUriFlow.collectAsState()
            val systemDark = isSystemInDarkTheme()
            val darkTheme = when (appearanceMode) {
                "light" -> false
                "dark" -> true
                else -> systemDark
            }
            BiliLearnTheme(darkTheme = darkTheme, hasBackground = backgroundUri.isNotBlank()) {
                MainAppContainer()
            }
        }

        requestNotificationPermissionIfNeeded()
        handleIncomingIntent(intent)
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun handleIncomingIntent(intent: Intent?) {
        if (intent?.action == Intent.ACTION_SEND && intent.type == "text/plain") {
            val sharedText = intent.getStringExtra(Intent.EXTRA_TEXT) ?: ""
            if (sharedText.isNotBlank()) {
                val botEngine = BiliLearnApplication.instance.botEngine
                lifecycleScope.launch {
                    val bvid = botEngine.biliApiClient.resolveAndExtractBvid(sharedText) ?: botEngine.biliApiClient.extractBvid(sharedText)
                    if (bvid != null) {
                        Toast.makeText(this@MainActivity, "收到主人指定视频: $bvid，已加入最高优先级队列！", Toast.LENGTH_SHORT).show()
                        com.bililearn.app.service.BiliBotService.start(this@MainActivity)
                        botEngine.enqueueUserRequestedVideo(bvid)
                    }
                }
            }
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun MainAppContainer() {
    val prefs = BiliLearnApplication.instance.preferences
    val backgroundUri by prefs.backgroundUriFlow.collectAsState()
    val backgroundOverlay by prefs.backgroundOverlayFlow.collectAsState()
    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val contentBlur by animateDpAsState(
        targetValue = if (drawerState.isOpen || drawerState.targetValue == DrawerValue.Open) 14.dp else 0.dp,
        animationSpec = tween(240),
        label = "drawer-content-blur"
    )

    var selectedNoteForDetail by remember { mutableStateOf<KnowledgeNoteEntity?>(null) }

    ModalNavigationDrawer(
        drawerState = drawerState,
        scrimColor = Color.Black.copy(alpha = 0.42f),
        drawerContent = {
            ModalDrawerSheet(
                modifier = Modifier.fillMaxWidth(0.84f),
                drawerShape = androidx.compose.foundation.shape.RoundedCornerShape(topEnd = 8.dp, bottomEnd = 8.dp)
            ) {
                Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(vertical = 16.dp)) {
                    Text("BiliLearn", style = MaterialTheme.typography.headlineSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold, modifier = Modifier.padding(horizontal = 20.dp))
                    Text("\${Screen.drawerItems.size} 项功能", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(horizontal = 20.dp, vertical = 3.dp))
                    HorizontalDivider(Modifier.padding(vertical = 12.dp))
                    Screen.drawerGroups.forEach { (groupTitle, screens) ->
                        Text(groupTitle.uppercase(), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(start = 20.dp, top = 10.dp, bottom = 4.dp))
                        screens.forEach { screen ->
                            val selected = currentRoute == screen.route
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 2.dp)
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f) else Color.Transparent)
                                    .clickable {
                                        navController.navigate(screen.route) { launchSingleTop = true; restoreState = true }
                                        scope.launch { drawerState.close() }
                                    }
                                    .padding(horizontal = 12.dp, vertical = 10.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Icon(if (selected) screen.selectedIcon else screen.unselectedIcon, null, tint = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(20.dp))
                                Text(screen.title, modifier = Modifier.padding(start = 14.dp), color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface, fontWeight = if (selected) androidx.compose.ui.text.font.FontWeight.SemiBold else androidx.compose.ui.text.font.FontWeight.Normal)
                            }
                        }
                    }
                }
            }
        }
    ) {
        Box(Modifier.fillMaxSize()) {
            if (backgroundUri.isNotBlank()) {
                AsyncImage(
                    model = backgroundUri,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize()
                )
            }
            Box(
                Modifier.fillMaxSize().background(
                    MaterialTheme.colorScheme.background.copy(
                        alpha = if (backgroundUri.isBlank()) 1f else backgroundOverlay
                    )
                )
            )
            Scaffold(
                modifier = Modifier.fillMaxSize().blur(contentBlur),
                containerColor = Color.Transparent,
                topBar = {
                    TopAppBar(
                        title = {
                            Text(
                                Screen.drawerItems.firstOrNull { it.route == currentRoute }?.title ?: "工作台",
                                style = MaterialTheme.typography.titleLarge
                            )
                        },
                        navigationIcon = {
                            IconButton(onClick = { scope.launch { drawerState.open() } }) {
                                Icon(androidx.compose.material.icons.Icons.Default.Menu, contentDescription = "打开导航菜单")
                            }
                        },
                        colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.82f))
                    )
                },
            ) { innerPadding ->
                if (selectedNoteForDetail != null) {
            KnowledgeDetailScreen(
                note = selectedNoteForDetail!!,
                onBack = { selectedNoteForDetail = null }
            )
                } else {
            NavHost(
                navController = navController,
                startDestination = Screen.Dashboard.route,
                modifier = Modifier.padding(innerPadding)
            ) {
                composable(Screen.Dashboard.route) {
                    DashboardScreen(
                        onNavigateToReviews = { navController.navigate(Screen.ActionReview.route) }
                    )
                }
                composable(Screen.Knowledge.route) {
                    KnowledgeListScreen(
                        onSelectNote = { note ->
                            selectedNoteForDetail = note
                        }
                    )
                }
                composable(Screen.Workshop.route) {
                    WorkshopScreen(
                        onNavigateToDetail = { note ->
                            selectedNoteForDetail = note
                        }
                    )
                }
                composable(Screen.Tutor.route) {
                    TutorChatScreen()
                }
                composable(Screen.Exam.route) {
                    ExamCenterScreen()
                }
                composable(Screen.Settings.route) {
                    SettingsScreen(
                        onNavigateToReviews = { navController.navigate(Screen.ActionReview.route) }
                    )
                }
                composable(Screen.Login.route) {
                    LoginScreen()
                }
                composable(Screen.WatchHistory.route) {
                    VideoLibraryScreen(onSelectNote = { note -> selectedNoteForDetail = note })
                }
                composable(Screen.Official.route) {
                    BrowserScreen("https://bxya.app/", Modifier.fillMaxSize())
                }
                composable(Screen.VideoLibrary.route) {
                    VideoLibraryScreen(
                        onSelectNote = { note -> selectedNoteForDetail = note }
                    )
                }
                composable(Screen.PersonalHub.route) {
                    PersonalHubScreen()
                }
                composable(Screen.Interests.route) {
                    InterestsScreen()
                }
                composable(Screen.Personas.route) {
                    PersonasScreen()
                }
                composable(Screen.ToolCenter.route) {
                    ToolCenterScreen()
                }
                composable(Screen.Logs.route) {
                    LogScreen()
                }
                composable(Screen.Asr.route) {
                    AsrScreen()
                }
                composable(Screen.Messages.route) {
                    PrivateMessagesScreen()
                }
                composable(Screen.Creators.route) {
                    CreatorCenterScreen()
                }
                composable(Screen.Diagnostics.route) {
                    DiagnosticsScreen()
                }
                composable(Screen.Advanced.route) {
                    AdvancedCenterScreen()
                }
                composable(Screen.AppSettings.route) {
                    AppSettingsScreen(
                        onOpenBotSettings = { navController.navigate(Screen.Settings.route) }
                    )
                }
                composable(Screen.ActionReview.route) {
                    ActionReviewScreen(
                        onBack = { navController.popBackStack() }
                    )
                }
            }
                }
            }
        }
    }
}

