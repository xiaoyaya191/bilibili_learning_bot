import json
from pathlib import Path


from services.platform_adapter import (
    detect_platform,
    download_platform_video,
    extract_bilibili_p_number,
    extract_video_id,
    fetch_platform_metadata,
    normalize_video_input,
)




def test_detect_platforms():
    assert detect_platform("BV1xx411c7mD") == "bilibili"
    assert detect_platform("https://www.bilibili.com/video/BV1xx411c7mD?p=2") == "bilibili"
    assert detect_platform("https://youtu.be/dQw4w9WgXcQ") == "youtube"
    assert detect_platform("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "youtube"
    assert detect_platform("https://www.douyin.com/video/1234567890") == "douyin"
    assert detect_platform("https://www.kuaishou.com/short-video/abc123") == "kuaishou"


def test_extract_ids():
    assert extract_video_id("https://www.bilibili.com/video/BV1xx411c7mD?p=2", "bilibili") == "BV1xx411c7mD"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ", "youtube") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube") == "dQw4w9WgXcQ"
    assert extract_bilibili_p_number("https://www.bilibili.com/video/BV1xx411c7mD?p=36") == 36


def test_normalize_bilibili():
    n = normalize_video_input("https://www.bilibili.com/video/BV1xx411c7mD?p=3")
    assert n["ok"] is True
    assert n["platform"] == "bilibili"
    assert n["video_id"] == "BV1xx411c7mD"
    assert n["url"].endswith("?p=3")


def test_local_video_download_reuse(tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"fake")
    path, _sec, size_mb, meta = download_platform_video(str(video), cfg={})
    assert Path(path) == video
    assert size_mb > 0
    assert meta["ok"] is True
    assert meta["platform"] == "local"
    assert meta["title"] == "demo"


def test_local_metadata_probe(tmp_path):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake")
    meta = fetch_platform_metadata(str(video), cfg={})
    assert meta["ok"] is True
    assert meta["platform"] == "local"
    assert meta["title"] == "lesson"


def test_config_example_platform_adapter_is_valid():
    cfg_path = Path(__file__).resolve().parents[1] / "config.example.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    adapter = cfg["platform_adapter"]
    assert adapter["enabled"] is True
    assert adapter["download_format"].endswith("/best")
    assert adapter["allow_web_local_files"] is False



