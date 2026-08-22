from services.local_favorites import auto_collect_video, backfill_from_history, read_library


def _video(score=9.0):
    return {
        "bvid": "BV1ab411c7mD",
        "title": "有价值的视频",
        "up": "测试UP主",
        "cover": "https://example.test/cover.jpg",
        "duration": 120,
        "score": score,
        "category": "科技",
        "interest_reason": "匹配 AI 兴趣",
    }


def test_auto_collect_creates_ai_folder_and_deduplicates(tmp_path):
    config = {"local_favorites": {
        "auto_collect_enabled": True,
        "min_score": 8.0,
        "folder_name": "AI 精选",
        "require_interest_match": True,
    }}

    first = auto_collect_video(config, _video(), interested=True, data_dir=tmp_path)
    second = auto_collect_video(config, _video(), interested=True, data_dir=tmp_path)
    library = read_library(tmp_path)

    assert first["added"] is True
    assert second == {"added": False, "reason": "duplicate", "folder": first["folder"]}
    assert library["folders"][0]["name"] == "AI 精选"
    assert library["items"][0]["title"] == "有价值的视频"
    assert library["items"][0]["score"] == 9.0


def test_auto_collect_respects_score_and_interest(tmp_path):
    config = {"local_favorites": {"min_score": 8.0, "require_interest_match": True}}

    assert auto_collect_video(config, _video(7.9), interested=True, data_dir=tmp_path)["reason"] == "score"
    assert auto_collect_video(config, _video(9.0), interested=False, data_dir=tmp_path)["reason"] == "interest"
    assert read_library(tmp_path)["items"] == []


def test_backfill_merges_legacy_view_and_interaction_scores(tmp_path):
    history = {"videos": [
        {"bvid": "BV1ab411c7mD", "action": "view", "title": "旧记录", "pic": "cover", "result": "AI 筛选通过"},
        {"bvid": "BV1ab411c7mD", "action": "like", "title": "旧记录", "score": 9.0},
    ]}

    added = backfill_from_history({"local_favorites": {"min_score": 8.0}}, history, data_dir=tmp_path)

    assert added == 1
    item = read_library(tmp_path)["items"][0]
    assert item["score"] == 9.0
    assert item["cover"] == "cover"
