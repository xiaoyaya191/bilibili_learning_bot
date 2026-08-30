package com.bililearn.app.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.MainActivity
import com.bililearn.app.R
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.collectLatest

class BiliBotService : Service() {

    private val serviceScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        startForeground(NOTIFICATION_ID, buildNotification("BiliLearn 机器人服务运行中", "正在就绪..."))

        val botEngine = BiliLearnApplication.instance.botEngine
        serviceScope.launch {
            botEngine.status.collectLatest { status ->
                val title = if (status.isRunning) "学习机器人运行中" else "机器人已暂停"
                val content = "${status.observation.activity} (今日已沉淀: ${status.processedCount} 篇)"
                val notification = buildNotification(title, content)
                val manager = getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
                manager.notify(NOTIFICATION_ID, notification)
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                BiliLearnApplication.instance.botEngine.startBot()
            }
            ACTION_STOP -> {
                BiliLearnApplication.instance.botEngine.stopBot()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_STICKY
    }

    private fun buildNotification(title: String, content: String): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, BiliLearnApplication.CHANNEL_BOT_ID)
            .setContentTitle(title)
            .setContentText(content)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    override fun onDestroy() {
        super.onDestroy()
        serviceScope.cancel()
    }

    companion object {
        const val NOTIFICATION_ID = 1001
        const val ACTION_START = "com.bililearn.app.ACTION_START"
        const val ACTION_STOP = "com.bililearn.app.ACTION_STOP"

        fun start(context: Context) {
            val intent = Intent(context, BiliBotService::class.java).apply {
                action = ACTION_START
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            val intent = Intent(context, BiliBotService::class.java).apply {
                action = ACTION_STOP
            }
            context.startService(intent)
        }
    }
}
