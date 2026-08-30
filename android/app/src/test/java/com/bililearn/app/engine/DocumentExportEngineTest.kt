package com.bililearn.app.engine

import com.bililearn.app.data.database.entity.KnowledgeNoteEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.util.zip.ZipInputStream

class DocumentExportEngineTest {
    private val engine = DocumentExportEngine()
    private val note = KnowledgeNoteEntity(
        id = "note-1",
        bvid = "BV1TEST",
        title = "A < B & C",
        summary = "摘要包含 <tag> & 引号 \"内容\"",
        keyPointsJson = "[\"第一点\",\"第二点\"]",
        mindmapMarkdown = "# Root",
        tagsJson = "[\"Kotlin\"]",
        upName = "测试用户",
        dateStr = "2026-08-27"
    )

    @Test
    fun docxContainsRequiredPartsAndEscapedXml() {
        val entries = unzip(engine.buildDocx(note))
        assertEquals(setOf("[Content_Types].xml", "_rels/.rels", "word/document.xml"), entries.keys)
        val xml = entries.getValue("word/document.xml")
        assertTrue(xml.contains("A &lt; B &amp; C"))
        assertFalse(xml.contains("<tag>"))
    }

    @Test
    fun pptxContainsPresentationAndAllSlides() {
        val entries = unzip(engine.buildPptx(note))
        assertTrue(entries.containsKey("ppt/presentation.xml"))
        assertTrue(entries.containsKey("ppt/_rels/presentation.xml.rels"))
        assertTrue(entries.containsKey("ppt/slides/slide1.xml"))
        assertTrue(entries.containsKey("ppt/slides/slide3.xml"))
        assertTrue(entries.getValue("ppt/slides/slide1.xml").contains("A &lt; B &amp; C"))
    }

    @Test
    fun htmlEscapesUserContent() {
        val html = engine.buildHtml(note)
        assertTrue(html.contains("A &lt; B &amp; C"))
        assertTrue(html.contains("&lt;tag&gt;"))
        assertFalse(html.contains("摘要包含 <tag>"))
    }

    private fun unzip(bytes: ByteArray): Map<String, String> {
        val entries = linkedMapOf<String, String>()
        ZipInputStream(ByteArrayInputStream(bytes)).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                entries[entry.name] = zip.readBytes().toString(Charsets.UTF_8)
            }
        }
        return entries
    }
}
