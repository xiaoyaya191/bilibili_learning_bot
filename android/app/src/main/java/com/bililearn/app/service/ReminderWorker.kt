package com.bililearn.app.service

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.bililearn.app.BiliLearnApplication
import com.bililearn.app.R
import com.bililearn.app.data.database.entity.ReminderEntity
import java.util.concurrent.TimeUnit

class ReminderWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val id = inputData.getString(KEY_ID) ?: return Result.failure()
        val item = BiliLearnApplication.instance.database.personalDataDao().reminderById(id)
            ?: return Result.success()
        if (item.completed) return Result.success()

        val notification = NotificationCompat.Builder(applicationContext, BiliLearnApplication.CHANNEL_REMINDER_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle("BiliLearn 待办提醒")
            .setContentText(item.content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(item.content))
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        val canNotify = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        if (canNotify) runCatching {
            NotificationManagerCompat.from(applicationContext).notify(id.hashCode(), notification)
        }
        return Result.success()
    }

    companion object {
        private const val KEY_ID = "reminder_id"

        fun schedule(context: Context, item: ReminderEntity) {
            val delay = (item.dueAt - System.currentTimeMillis()).coerceAtLeast(0L)
            val request = OneTimeWorkRequestBuilder<ReminderWorker>()
                .setInitialDelay(delay, TimeUnit.MILLISECONDS)
                .setInputData(Data.Builder().putString(KEY_ID, item.id).build())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                "reminder-${item.id}",
                androidx.work.ExistingWorkPolicy.REPLACE,
                request
            )
        }

        fun cancel(context: Context, id: String) {
            WorkManager.getInstance(context).cancelUniqueWork("reminder-$id")
        }
    }
}
