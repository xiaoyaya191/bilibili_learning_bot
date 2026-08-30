package com.bililearn.app.engine

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.text.SimpleDateFormat
import java.util.*

data class MiniGoalProgress(
    val targetVideos: Int = 3,
    val completedVideos: Int = 0,
    val targetMinutes: Int = 45,
    val completedMinutes: Int = 0,
    val streakDays: Int = 1,
    val isCompleted: Boolean = false,
    val progressPercent: Float = 0f
)

class MiniGoalEngine(context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences("bililearn_minigoal", Context.MODE_PRIVATE)

    private val _progressFlow = MutableStateFlow(loadTodayProgress())
    val progressFlow: StateFlow<MiniGoalProgress> = _progressFlow.asStateFlow()

    private fun getTodayDateStr(): String {
        return SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
    }

    fun loadTodayProgress(): MiniGoalProgress {
        val today = getTodayDateStr()
        val lastDate = prefs.getString("last_date", "") ?: ""

        val targetVideos = prefs.getInt("target_videos", 3)
        val targetMinutes = prefs.getInt("target_minutes", 45)
        var streak = prefs.getInt("streak_days", 1)

        val completedVideos = if (lastDate == today) prefs.getInt("completed_videos", 0) else 0
        val completedMinutes = if (lastDate == today) prefs.getInt("completed_minutes", 0) else 0

        val isCompleted = completedVideos >= targetVideos
        val percent = (completedVideos.toFloat() / targetVideos.coerceAtLeast(1)).coerceIn(0f, 1f)

        return MiniGoalProgress(
            targetVideos = targetVideos,
            completedVideos = completedVideos,
            targetMinutes = targetMinutes,
            completedMinutes = completedMinutes,
            streakDays = streak,
            isCompleted = isCompleted,
            progressPercent = percent
        )
    }

    fun onVideoLearned(durationSeconds: Long) {
        val today = getTodayDateStr()
        val lastDate = prefs.getString("last_date", "") ?: ""

        var completedVideos = if (lastDate == today) prefs.getInt("completed_videos", 0) else 0
        var completedMinutes = if (lastDate == today) prefs.getInt("completed_minutes", 0) else 0
        var streak = prefs.getInt("streak_days", 1)

        completedVideos += 1
        completedMinutes += (durationSeconds / 60).toInt()

        val targetVideos = prefs.getInt("target_videos", 3)
        if (completedVideos >= targetVideos && lastDate != today) {
            streak += 1
        }

        prefs.edit()
            .putString("last_date", today)
            .putInt("completed_videos", completedVideos)
            .putInt("completed_minutes", completedMinutes)
            .putInt("streak_days", streak)
            .apply()

        _progressFlow.value = loadTodayProgress()
    }

    fun setTarget(videos: Int, minutes: Int) {
        prefs.edit()
            .putInt("target_videos", videos)
            .putInt("target_minutes", minutes)
            .apply()
        _progressFlow.value = loadTodayProgress()
    }

    fun reloadFromDisk() {
        _progressFlow.value = loadTodayProgress()
    }

    fun clearAll() {
        prefs.edit().clear().commit()
        reloadFromDisk()
    }
}
