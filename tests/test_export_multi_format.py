"""Multi-format export: txt/md beyond the old pdf/docx-only surface."""
import asyncio
from pathlib import Path

from services import document_export as de


def test_export_txt_text(tmp_path):
    path = de.export_txt_text("# 标题\n内容", "标题", out_dir=tmp_path)
    assert str(path).endswith(".txt")
    assert "标题" in Path(path).read_text(encoding="utf-8")


def test_export_document_supports_txt_and_md(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "note.md").write_text("# note\nbody", encoding="utf-8")

    txt = de.export_document("note.md", "txt", kb_root=kb, out_dir=tmp_path / "out")
    assert Path(txt).suffix == ".txt"

    md_copy = de.export_document("note.md", "md", kb_root=kb, out_dir=tmp_path / "out2")
    assert Path(md_copy).suffix == ".md"
    assert Path(md_copy).read_text(encoding="utf-8") == "# note\nbody"


def test_export_video_content_supports_txt(monkeypatch, tmp_path):
    captured = {}

    def fake_txt(text, title, out_dir=None):
        captured["text"] = text
        captured["title"] = title
        return str(tmp_path / "video.txt")

    monkeypatch.setattr(de, "export_txt_text", fake_txt)
    result = asyncio.run(de.export_video_content(
        "标题", "UP", "https://bilibili.com/video/BV1xx411c7mD",
        "正文内容", ["txt"], bvid="BV1xx411c7mD",
    ))
    assert result["txt"]["path"].endswith(".txt")
    assert "标题" in captured["text"]
    assert "正文内容" in captured["text"]
