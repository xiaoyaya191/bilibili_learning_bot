package com.bililearn.app.ui.workshop

import com.bililearn.app.data.model.SubtitleItem
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TimelineContextTest {
    @Test
    fun selectsMatchingSegmentAndItsNeighborsWithTimestamps() {
        val subtitles = listOf(
            SubtitleItem(0.0, 4.0, "开场介绍"),
            SubtitleItem(65.0, 70.0, "Transformer 使用注意力机制"),
            SubtitleItem(71.0, 75.0, "这里解释查询和键"),
            SubtitleItem(180.0, 184.0, "结束语")
        )

        val result = selectTimelineContext(subtitles, "注意力机制是什么", limit = 3)

        assertTrue(result.contains("[01:05] Transformer 使用注意力机制"))
        assertTrue(result.contains("[01:11] 这里解释查询和键"))
        assertFalse(result.contains("[03:00] 结束语"))
    }

    @Test
    fun fallsBackToBeginningWhenQuestionHasNoKeywordMatch() {
        val subtitles = (0..4).map { SubtitleItem(it * 10.0, it * 10.0 + 2, "片段 $it") }
        val result = selectTimelineContext(subtitles, "完全无关的问题", limit = 2)
        assertTrue(result.contains("片段 0"))
        assertTrue(result.contains("片段 1"))
        assertFalse(result.contains("片段 2"))
    }
}
