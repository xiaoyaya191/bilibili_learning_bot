package com.bililearn.app.engine

import android.graphics.Paint
import android.graphics.pdf.PdfDocument
import com.bililearn.app.data.database.entity.KnowledgeNoteEntity
import com.google.gson.GsonBuilder
import java.io.ByteArrayOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class DocumentExportEngine {
    fun safeFileName(note: KnowledgeNoteEntity): String =
        note.title.replace(Regex("[\\/:*?\"<>|]"), "_").take(48).ifBlank { note.bvid }

    fun buildMarkdown(note: KnowledgeNoteEntity): String = buildString {
        appendLine("# ${note.title}")
        appendLine()
        appendLine("- BV号: [${note.bvid}](https://www.bilibili.com/video/${note.bvid})")
        appendLine("- UP主: ${note.upName.ifBlank { "未知" }}")
        appendLine("- 生成时间: ${note.dateStr}")
        appendLine("- 标签: ${note.getTagsList().joinToString(", ")}")
        appendLine()
        appendLine("## 核心摘要")
        appendLine()
        appendLine(note.summary)
        appendLine()
        appendLine("## 关键认知要点")
        appendLine()
        note.getKeyPointsList().forEachIndexed { index, point -> appendLine("${index + 1}. $point") }
        if (note.mindmapMarkdown.isNotBlank()) {
            appendLine()
            appendLine("## 思维导图")
            appendLine()
            appendLine("```markmap")
            appendLine(note.mindmapMarkdown)
            appendLine("```")
        }
    }

    fun buildJson(note: KnowledgeNoteEntity): String = GsonBuilder().setPrettyPrinting().create().toJson(note)

    fun buildDocx(note: KnowledgeNoteEntity): ByteArray {
        val paragraphs = buildList {
            add(note.title)
            add("BV号: ${note.bvid}    UP主: ${note.upName.ifBlank { "未知" }}")
            add("核心摘要")
            add(note.summary)
            add("关键认知要点")
            note.getKeyPointsList().forEachIndexed { index, value -> add("${index + 1}. $value") }
            if (note.mindmapMarkdown.isNotBlank()) { add("思维导图"); add(note.mindmapMarkdown) }
        }
        val document = """
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
            ${paragraphs.joinToString("") { "<w:p><w:r><w:t xml:space=\"preserve\">${escapeXml(it)}</w:t></w:r></w:p>" }}
            <w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>
            </w:body></w:document>
        """.trimIndent()
        return zipPackage(
            mapOf(
                "[Content_Types].xml" to """<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>""",
                "_rels/.rels" to """<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>""",
                "word/document.xml" to document
            )
        )
    }

    fun buildPptx(note: KnowledgeNoteEntity): ByteArray {
        val slides = listOf(
            note.title to "UP主: ${note.upName.ifBlank { "未知" }}\nBV号: ${note.bvid}",
            "核心摘要" to note.summary,
            "关键认知要点" to note.getKeyPointsList().mapIndexed { index, text -> "${index + 1}. $text" }.joinToString("\n")
        )
        val contentTypes = buildString {
            append("<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/ppt/presentation.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml\"/>")
            slides.indices.forEach { append("<Override PartName=\"/ppt/slides/slide${it + 1}.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.presentationml.slide+xml\"/>") }
            append("</Types>")
        }
        val presentation = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldIdLst>${slides.indices.joinToString("") { "<p:sldId id=\"${256 + it}\" r:id=\"rId${it + 1}\"/>" }}</p:sldIdLst><p:sldSz cx="12192000" cy="6858000" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>"""
        val presentationRels = """<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${slides.indices.joinToString("") { "<Relationship Id=\"rId${it + 1}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide\" Target=\"slides/slide${it + 1}.xml\"/>" }}</Relationships>"""
        val entries = linkedMapOf(
            "[Content_Types].xml" to contentTypes,
            "_rels/.rels" to """<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>""",
            "ppt/presentation.xml" to presentation,
            "ppt/_rels/presentation.xml.rels" to presentationRels
        )
        slides.forEachIndexed { index, (title, body) -> entries["ppt/slides/slide${index + 1}.xml"] = slideXml(title, body) }
        return zipPackage(entries)
    }

    fun buildPdf(note: KnowledgeNoteEntity): ByteArray {
        val document = PdfDocument()
        val titlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 24f; isFakeBoldText = true }
        val bodyPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 14f }
        val lines = buildList {
            add(note.title)
            add("BV号: ${note.bvid}    UP主: ${note.upName.ifBlank { "未知" }}")
            add("")
            add("核心摘要")
            addAll(wrapText(note.summary, bodyPaint, 515f))
            add("")
            add("关键认知要点")
            note.getKeyPointsList().forEachIndexed { index, value -> addAll(wrapText("${index + 1}. $value", bodyPaint, 515f)) }
        }
        var pageNumber = 1
        var page = document.startPage(PdfDocument.PageInfo.Builder(595, 842, pageNumber).create())
        var y = 52f
        lines.forEachIndexed { index, line ->
            if (y > 795f) {
                document.finishPage(page)
                pageNumber++
                page = document.startPage(PdfDocument.PageInfo.Builder(595, 842, pageNumber).create())
                y = 52f
            }
            val paint = if (index == 0) titlePaint else bodyPaint
            page.canvas.drawText(line, 40f, y, paint)
            y += if (index == 0) 38f else 23f
        }
        document.finishPage(page)
        return ByteArrayOutputStream().use { output -> document.writeTo(output); document.close(); output.toByteArray() }
    }

    fun buildHtml(note: KnowledgeNoteEntity): String {
        val points = note.getKeyPointsList().mapIndexed { index, point -> "<li><strong>#${index + 1}</strong> ${escape(point)}</li>" }.joinToString("\n")
        val tags = note.getTagsList().joinToString(" ") { "<span>#${escape(it)}</span>" }
        return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escape(note.title)} - BiliLearn</title>
<style>
body{font-family:system-ui,sans-serif;background:#f6f6f4;color:#202124;max-width:820px;margin:32px auto;padding:0 18px;line-height:1.7}
header{border-bottom:2px solid #e4e4df;padding-bottom:18px;margin-bottom:20px}h1{font-size:26px;margin:0 0 8px}
.meta{color:#666;font-size:13px}.section{background:#fff;border:1px solid #e4e4df;border-radius:8px;padding:20px;margin:14px 0}
h2{font-size:17px;color:#c45e32;margin-top:0}.tags span{display:inline-block;background:#f6e8e1;color:#a84727;padding:2px 7px;border-radius:5px;margin:4px}
li{margin:8px 0}pre{white-space:pre-wrap;background:#f1f1ed;padding:12px;border-radius:6px}
</style>
</head>
<body>
<header><h1>${escape(note.title)}</h1><div class="meta">UP主: ${escape(note.upName)} · BV号: ${escape(note.bvid)} · ${escape(note.dateStr)}</div><div class="tags">$tags</div></header>
<section class="section"><h2>核心摘要</h2><p>${escape(note.summary)}</p></section>
<section class="section"><h2>关键认知要点</h2><ol>$points</ol></section>
<section class="section"><h2>思维导图</h2><pre>${escape(note.mindmapMarkdown)}</pre></section>
</body>
</html>
        """.trimIndent()
    }

    private fun escape(value: String): String = value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
        .replace("'", "&#39;")

    private fun escapeXml(value: String): String = escape(value)

    private fun zipPackage(entries: Map<String, String>): ByteArray = ByteArrayOutputStream().use { output ->
        ZipOutputStream(output).use { zip ->
            entries.forEach { (path, content) ->
                zip.putNextEntry(ZipEntry(path))
                zip.write(content.toByteArray(Charsets.UTF_8))
                zip.closeEntry()
            }
        }
        output.toByteArray()
    }

    private fun slideXml(title: String, body: String): String {
        fun shape(id: Int, name: String, y: Long, h: Long, text: String, size: Int): String = """
            <p:sp><p:nvSpPr><p:cNvPr id="$id" name="$name"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="$y"/><a:ext cx="10820400" cy="$h"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr><p:txBody><a:bodyPr wrap="square"/><a:lstStyle/>${text.lines().joinToString("") { "<a:p><a:r><a:rPr lang=\"zh-CN\" sz=\"$size\"/><a:t>${escapeXml(it)}</a:t></a:r></a:p>" }}</p:txBody></p:sp>
        """.trimIndent()
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>${shape(2, "Title", 500000, 1000000, title, 2800)}${shape(3, "Content", 1700000, 4300000, body, 1700)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"""
    }

    private fun wrapText(value: String, paint: Paint, width: Float): List<String> {
        if (value.isBlank()) return listOf("")
        return value.lines().flatMap { source ->
            if (source.isBlank()) listOf("") else buildList {
                var rest = source
                while (rest.isNotEmpty()) {
                    val count = paint.breakText(rest, true, width, null).coerceAtLeast(1)
                    add(rest.take(count))
                    rest = rest.drop(count)
                }
            }
        }
    }
}
