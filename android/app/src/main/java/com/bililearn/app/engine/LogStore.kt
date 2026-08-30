package com.bililearn.app.engine

import android.content.Context
import com.bililearn.app.data.model.LogEntry
import com.google.gson.Gson
import java.io.File

class LogStore(context: Context) {
    private val gson = Gson()
    private val file = File(File(context.filesDir, "logs").apply { mkdirs() }, "runtime.jsonl")

    @Synchronized
    fun load(limit: Int = 500): List<LogEntry> {
        if (!file.exists()) return emptyList()
        return file.readLines(Charsets.UTF_8).takeLast(limit).mapNotNull {
            runCatching { gson.fromJson(it, LogEntry::class.java) }.getOrNull()
        }
    }

    @Synchronized
    fun append(entry: LogEntry) {
        file.appendText(gson.toJson(entry) + "\n", Charsets.UTF_8)
        if (file.length() > MAX_BYTES) {
            val compact = load(500).joinToString("\n") { gson.toJson(it) } + "\n"
            file.writeText(compact, Charsets.UTF_8)
        }
    }

    @Synchronized
    fun clear() {
        if (file.exists()) file.writeText("", Charsets.UTF_8)
    }

    companion object {
        private const val MAX_BYTES = 2L * 1024 * 1024
    }
}
