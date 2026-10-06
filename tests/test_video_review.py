import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from services.video_review import DEFAULTS, VideoReview, in_schedule, settings, validate_settings

NOW = datetime(2026, 10, 6, 10, 0)


def prefs(**changes):
    result = dict(deepcopy(DEFAULTS), min_age_hours=0, min_score=0)
    result.update(changes)
    return result


def seed(path, *, action="view", index=1, **changes):
    video = dict(bvid=f"BV1AA{index:08d}", title="Python基础", up="测试UP", category="知识", score=9, action=action, time=(NOW - timedelta(days=3)).isoformat(), revisit_count=0, last_revisit=None)
    video.update(changes)
    file = path / "history_videos.json"
    videos = json.loads(file.read_text(encoding="utf-8"))["videos"] if file.exists() else []
    videos.append(video)
    file.write_text(json.dumps({"videos": videos}), encoding="utf-8")
    return video


def test_default_off_and_legacy_enable_requires_rule_confirmation(tmp_path):
    review = VideoReview(tmp_path)
    seed(tmp_path)
    assert not settings({})["enabled"]
    assert not settings({"revisit": {"enabled": True}})["rules_confirmed"]
    assert review.reserve(prefs(), now=NOW) is None
    assert review.reserve(prefs(enabled=True), now=NOW) is None
    assert review.snapshot() == []


@pytest.mark.parametrize("window,hour,minute,expected", [
    ("09:00-10:00", 9, 0, True), ("09:00-10:00", 10, 0, False),
    ("22:00-01:00", 23, 0, True), ("22:00-01:00", 0, 30, True),
    ("22:00-01:00", 12, 0, False),
])
def test_schedule_boundaries_and_midnight(window, hour, minute, expected):
    assert in_schedule(prefs(time_windows=[window]), NOW.replace(hour=hour, minute=minute)) is expected


def test_weekdays_and_unlimited_windows():
    assert in_schedule(prefs(), NOW)
    assert not in_schedule(prefs(weekdays=[]), NOW)
    assert not in_schedule(prefs(weekdays=[0]), NOW)
    assert in_schedule(prefs(weekdays=[1]), NOW)


@pytest.mark.parametrize("changes", [
    {"enabled": "true"}, {"sources": []}, {"sources": ["remote"]},
    {"categories": "知识"}, {"time_windows": ["25:00-01:00"]},
    {"time_windows": ["09:00-09:00"]}, {"weekdays": [True]},
    {"weekdays": [7]}, {"daily_limit": -1}, {"daily_limit": 0.1},
    {"min_score": float("nan")}, {"order": "ai"}, {"unexpected": 1},
])
def test_invalid_rules(changes):
    with pytest.raises(ValueError):
        validate_settings(dict(DEFAULTS, **changes))


def test_sources_dedup_and_local_folder_filters(tmp_path):
    review = VideoReview(tmp_path)
    video = seed(tmp_path)
    seed(tmp_path, action="like")
    seed(tmp_path, action="fav", index=2)
    assert len(review.candidates(prefs(), NOW)) == 1
    assert review.candidates(prefs(sources=["liked"]), NOW)[0]["review_source"] == "liked"
    assert review.candidates(prefs(sources=["favorited"]), NOW)[0]["bvid"] != video["bvid"]
    (tmp_path / "video_favorites.json").write_text(json.dumps({"folders": [{"id": "a", "name": "课程"}], "items": [dict(video, folder_id="a")]}), encoding="utf-8")
    assert len(review.candidates(prefs(sources=["history", "liked", "local_favorites"]), NOW)) == 1
    assert review.candidates(prefs(sources=["local_favorites"], favorite_folders=["其他"]), NOW) == []
    assert len(review.candidates(prefs(sources=["local_favorites"], favorite_folders=["课程"]), NOW)) == 1


def test_types_keywords_authors_score_age_and_orders(tmp_path):
    review = VideoReview(tmp_path)
    seed(tmp_path)
    seed(tmp_path, index=2, title="游戏评测", category="游戏", score=7)
    assert len(review.candidates(prefs(), NOW)) == 2
    assert len(review.candidates(prefs(categories=["知识"]), NOW)) == 1
    assert review.candidates(prefs(categories=["不存在"]), NOW) == []
    assert len(review.candidates(prefs(keywords=["python"]), NOW)) == 1
    assert len(review.candidates(prefs(exclude_keywords=["基础"]), NOW)) == 1
    assert review.candidates(prefs(up_names=["其他"]), NOW) == []
    assert len(review.candidates(prefs(min_score=8), NOW)) == 1
    assert review.candidates(prefs(min_age_hours=100), NOW) == []
    assert review.candidates(prefs(order="score"), NOW)[0]["score"] == 9


def test_manual_task_durable_and_does_not_enable_automatic(tmp_path):
    review = VideoReview(tmp_path)
    video = seed(tmp_path)
    rules = prefs(time_windows=["22:00-23:00"], weekdays=[])
    task = review.reserve(rules, manual=True, bvid=video["bvid"], now=NOW)
    assert task
    assert not rules["enabled"]
    restored = VideoReview(tmp_path)
    target = restored.claim(rules, NOW)
    assert target["_review_id"] == task
    assert restored.claim(rules, NOW) is None
    assert target["_is_revisit"]
    assert restored.candidates(rules, NOW)[0]["review_count"] == 0
    restored.finish(task, success=True, score=9, note="复习知识摘要", now=NOW)
    assert restored.snapshot()[0]["note"] == "复习知识摘要"
    assert restored.candidates(rules, NOW) == []


def test_failure_cancel_and_interruption_never_count_completion(tmp_path):
    review = VideoReview(tmp_path)
    seed(tmp_path)
    rules = prefs(daily_limit=0)
    task = review.reserve(rules, manual=True, now=NOW)
    review.claim(rules, NOW)
    review.finish(task, success=False, interrupted=True, now=NOW)
    assert review.snapshot()[0]["status"] == "pending"
    review.claim(rules, NOW)
    VideoReview(tmp_path).recover()
    assert review.snapshot()[0]["status"] == "pending"
    review.claim(rules, NOW)
    review.finish(task, success=False, note="内容不可用", now=NOW)
    assert review.candidates(rules, NOW)[0]["review_count"] == 0
    next_task = review.reserve(rules, manual=True, now=NOW)
    review.cancel(next_task)
    assert review.snapshot()[0]["status"] == "cancelled"
    with pytest.raises(ValueError):
        review.cancel(next_task)


def test_daily_budget_counts_failures_and_cooldown(tmp_path):
    review = VideoReview(tmp_path)
    seed(tmp_path)
    rules = prefs(enabled=True, rules_confirmed=True, daily_limit=1)
    task = review.reserve(rules, now=NOW)
    review.claim(rules, NOW)
    review.finish(task, success=False, now=NOW)
    assert review.reserve(rules, now=NOW + timedelta(hours=2)) is None
    assert review.reserve(rules, now=NOW + timedelta(days=1))


def test_video_limit_and_cooldown(tmp_path):
    review = VideoReview(tmp_path)
    seed(tmp_path, revisit_count=2)
    assert review.candidates(prefs(max_per_video=2), NOW) == []
    assert review.candidates(prefs(max_per_video=0), NOW)


def test_atomic_single_task_and_account_isolation(tmp_path):
    first = VideoReview(tmp_path / "first")
    second = VideoReview(tmp_path / "second")
    seed(first.data_dir)
    seed(second.data_dir, index=2)
    def reserve(_index):
        try:
            return first.reserve(prefs(), manual=True, now=NOW)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(reserve, range(5)))
    assert sum(bool(result) for result in results) == 1
    assert second.snapshot() == []
    assert first.path != second.path


def test_corrupt_source_is_not_silently_cleared(tmp_path):
    review = VideoReview(tmp_path)
    path = tmp_path / "history_videos.json"
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        review.candidates(prefs(), NOW)
    assert path.read_text() == "broken"


def test_history_updates_preserve_counts_and_category(monkeypatch):
    from brain._brain_history import BrainHistoryMixin
    brain = BrainHistoryMixin()
    brain.history_videos = {"videos": [{"bvid": "BV1AA00000001", "action": "view", "revisit_count": 2, "last_revisit": "2026-10-01"}]}
    monkeypatch.setattr(brain, "_save_history_videos", lambda: None)
    brain.record_watched_video("BV1AA00000001", "测试", "UP", 1, category="知识")
    item = brain.history_videos["videos"][0]
    assert item["revisit_count"] == 2
    assert item["last_revisit"] == "2026-10-01"
    assert item["category"] == "知识"

def test_disabled_review_does_not_read_sources(tmp_path, monkeypatch):
    review = VideoReview(tmp_path)
    def forbidden(*args):
        raise AssertionError("关闭时不读取候选来源")
    monkeypatch.setattr(review, "candidates", forbidden)
    assert review.reserve(prefs(), now=NOW) is None
    assert review.claim(prefs(), NOW) is None


def test_auto_pending_pauses_and_revalidates_changed_rules(tmp_path):
    review = VideoReview(tmp_path)
    seed(tmp_path)
    rules = prefs(enabled=True, rules_confirmed=True)
    task_id = review.reserve(rules, now=NOW)
    assert review.claim(prefs(), NOW) is None
    assert review.snapshot()[0]["status"] == "pending"
    assert review.claim(prefs(enabled=True, rules_confirmed=True, categories=["游戏"]), NOW) is None
    assert review.snapshot()[0]["status"] == "cancelled"
    assert review.snapshot()[0]["id"] == task_id


def test_global_attempt_interval_and_successful_video_cooldown(tmp_path):
    review = VideoReview(tmp_path)
    seed(tmp_path)
    rules = prefs(enabled=True, rules_confirmed=True, daily_limit=0)
    task_id = review.reserve(rules, now=NOW)
    review.claim(rules, NOW)
    review.finish(task_id, success=False, now=NOW)
    assert review.reserve(rules, now=NOW + timedelta(minutes=59)) is None
    next_id = review.reserve(rules, now=NOW + timedelta(minutes=60))
    assert next_id
    review.claim(rules, NOW + timedelta(minutes=60))
    review.finish(next_id, success=True, now=NOW + timedelta(minutes=60))
    assert review.candidates(rules, NOW + timedelta(minutes=299)) == []
    candidates = review.candidates(rules, NOW + timedelta(minutes=300))
    assert candidates[0]["review_count"] == 1
