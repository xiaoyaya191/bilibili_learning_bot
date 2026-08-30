package com.bililearn.app

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.bililearn.app.data.database.AppDatabase
import com.bililearn.app.data.database.DatabaseBackupManager
import com.bililearn.app.data.prefs.AppPreferences
import com.bililearn.app.data.prefs.ToolboxStore
import com.bililearn.app.data.prefs.AdvancedStore
import com.bililearn.app.engine.BotEngine
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import com.bililearn.app.service.ReminderWorker
import androidx.room.InvalidationTracker

class BiliLearnApplication : Application() {

    lateinit var database: AppDatabase
        private set

    lateinit var preferences: AppPreferences
        private set

    lateinit var databaseBackupManager: DatabaseBackupManager
        private set

    lateinit var toolboxStore: ToolboxStore
        private set

    lateinit var advancedStore: AdvancedStore
        private set

    lateinit var botEngine: BotEngine
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this

        database = AppDatabase.getDatabase(this)
        databaseBackupManager = DatabaseBackupManager(this, database)
        preferences = AppPreferences(this)
        toolboxStore = ToolboxStore(this)
        advancedStore = AdvancedStore(this)
        botEngine = BotEngine(this, database, preferences, databaseBackupManager)

        database.invalidationTracker.addObserver(
            object : InvalidationTracker.Observer(
                "knowledge_notes",
                "action_reviews",
                "chat_sessions",
                "chat_messages",
                "reminders",
                "diary_entries",
                "permanent_memories"
            ) {
                override fun onInvalidated(tables: Set<String>) {
                    CoroutineScope(Dispatchers.IO).launch { databaseBackupManager.autoBackup() }
                }
            }
        )

        createNotificationChannels()

        // 启动时自动检查并自愈恢复知识库（双保险）
        CoroutineScope(Dispatchers.IO).launch {
            databaseBackupManager.tryAutoRestoreOnStartup()
            database.personalDataDao().pendingReminders().forEach { ReminderWorker.schedule(this@BiliLearnApplication, it) }
        }
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_BOT_ID,
                getString(R.string.channel_name_bot),
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = getString(R.string.channel_desc_bot)
                setShowBadge(false)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
            manager?.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_REMINDER_ID,
                    "待办提醒",
                    NotificationManager.IMPORTANCE_HIGH
                ).apply { description = "学习计划与待办到期提醒" }
            )
        }
    }

    companion object {
        const val CHANNEL_BOT_ID = "channel_bililearn_bot"
        const val CHANNEL_REMINDER_ID = "channel_bililearn_reminders"
        lateinit var instance: BiliLearnApplication
            private set
    }
}
