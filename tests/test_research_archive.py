import json

from services.research_archive import ResearchArchive


def test_research_archive_preserves_source_and_ai_boundary(tmp_path):
    archive = ResearchArchive(tmp_path)
    project = archive.create_project("模型调研", "公开视频研究")
    record = archive.save_visual_note({
        "title": "演示视频", "up_name": "研究者", "url": "https://www.bilibili.com/video/BV1QNKw6uE3L",
        "markdown": "## 结论\n*Screenshot-[01:23]\n*Content-[01:23]",
    }, "这是原始字幕", project["id"])
    assert record["source"]["author"] == "研究者"
    assert record["materials"]["original_subtitles"] == "这是原始字幕"
    assert "AI" in record["materials"]["notice"]
    assert record["evidence"][0]["timestamp_seconds"] == 83
    assert archive.records(project_id=project["id"])[0]["id"] == record["id"]


def test_research_archive_exports_csv_and_json(tmp_path):
    archive = ResearchArchive(tmp_path)
    archive.save_visual_note({"title": "导出测试", "url": "https://example.test/video", "markdown": ""})
    data, mime = archive.export("json")
    assert json.loads(data)["records"][0]["source"]["title"] == "导出测试"
    csv_data, csv_mime = archive.export("csv")
    assert "导出测试" in csv_data and csv_mime.startswith("text/csv")
