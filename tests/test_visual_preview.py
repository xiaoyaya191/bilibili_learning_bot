import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from xingye_bot import grid_frames, visual_preview
from xingye_bot.settings import BotSettings
from xingye_bot.video_modes import VideoAsset, VideoUnderstanding


def test_half_second_sampling_and_default_first_minute():
    assert grid_frames.select_frame_timestamps(0, 60, 5, 240, []) == list(range(0, 60, 5))
    stamps = grid_frames.select_frame_timestamps(0, 60, 0.5, 240, [])
    assert len(stamps) == 120
    assert stamps[:3] == [0, 0.5, 1]
    assert grid_frames._fmt_ts(0.5) == "00:00.500"


def test_scene_changes_replace_uniform_anchors_within_budget():
    stamps = grid_frames.select_frame_timestamps(0, 20, 5, 240, [6.2, 11.5, 17])
    assert stamps == [0, 6.2, 11.5, 17]
    assert grid_frames.select_frame_timestamps(60, 3600, 5, 10, [])[-1] > 3000


def test_grid_contains_twelve_cells_and_fractional_timestamps(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    timestamps = []
    monkeypatch.setattr(grid_frames, "_get_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(grid_frames, "_probe_duration", lambda *_args: 60)
    monkeypatch.setattr(grid_frames, "detect_scene_changes", lambda *_args: [])

    def extract(_video, timestamp, output, _ffmpeg):
        timestamps.append(timestamp)
        Image.new("RGB", (160, 90), (int(timestamp * 10) % 255, 0, 0)).save(output)
        return output

    monkeypatch.setattr(grid_frames, "extract_single_frame", extract)
    images = grid_frames.extract_grid_frames(source, end_seconds=60, dedup=False)
    assert len(images) == 1
    assert images[0].size == (1920, 810)
    assert timestamps == list(range(0, 60, 5))
    for image in images:
        image.close()


@pytest.mark.parametrize("reply", [
    '{"matches_metadata":false,"interesting":false,"summary":"无关"}',
    '{"matches_metadata":"true","interesting":"false"}',
    "not-json",
])
def test_rejected_preview_never_extracts_remaining_video(monkeypatch, reply):
    ranges = []
    purposes = []

    def extract(_path, _config, **window):
        ranges.append(window)
        return [Image.new("RGB", (40, 30))]

    async def call(_blocks, purpose):
        purposes.append(purpose)
        return '{"skip":false}' if purpose == "video-visual-metadata" else reply

    monkeypatch.setattr(visual_preview, "extract_visual_note_grids", extract)
    result = asyncio.run(visual_preview.analyze_visual_preview("video", "标题", call, duration=300))
    assert result["completed"] is False
    assert ranges == [{"end_seconds": 60}]
    assert purposes == ["video-visual-metadata", "video-visual-preview"]


@pytest.mark.parametrize("gate", [
    '{"matches_metadata":true,"interesting":false,"summary":"主题相符"}',
    '{"matches_metadata":false,"interesting":true,"summary":"感兴趣"}',
])
def test_matching_or_interesting_preview_continues_in_bounded_batches(monkeypatch, gate):
    ranges = []
    batch_sizes = []
    warnings = []

    def extract(_path, _config, **window):
        ranges.append(window)
        return [Image.new("RGB", (40, 30)) for _index in range(9 if "start_seconds" in window else 1)]

    async def call(blocks, purpose):
        if purpose == "video-visual-metadata":
            return '{"skip":false}'
        if purpose == "video-visual-preview":
            return gate
        batch_sizes.append(len(blocks) - 1)
        return "## 深入内容"

    monkeypatch.setattr(visual_preview, "extract_visual_note_grids", extract)
    result = asyncio.run(visual_preview.analyze_visual_preview(
        "video", "标题", call, {"visual_note_frame_interval": 0.5}, duration=300,
        log_message=warnings.append,
    ))
    assert result["completed"] is True
    assert ranges == [{"end_seconds": 60}, {"start_seconds": 60}]
    assert batch_sizes == [4, 4, 1]
    assert "额度消耗警告" in warnings[0]


def test_metadata_rejection_avoids_extracting_any_frames(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("must not extract")

    async def call(_blocks, _purpose):
        return '{"skip":true,"reason":"不适合"}'

    monkeypatch.setattr(visual_preview, "extract_visual_note_grids", forbidden)
    result = asyncio.run(visual_preview.analyze_visual_preview("video", "标题", call, duration=300))
    assert result["reason"] == "不适合"


def test_short_video_needs_no_second_extraction(monkeypatch):
    ranges = []

    def extract(_path, _config, **window):
        ranges.append(window)
        return [Image.new("RGB", (40, 30))]

    async def call(_blocks, purpose):
        return '{"skip":false}' if purpose.endswith("metadata") else '{"matches_metadata":true}'

    monkeypatch.setattr(visual_preview, "extract_visual_note_grids", extract)
    result = asyncio.run(visual_preview.analyze_visual_preview("video", "标题", call, duration=30))
    assert result["completed"] is True
    assert ranges == [{"end_seconds": 30}]


@pytest.mark.parametrize("source", ["subtitle", "asr"])
def test_modular_text_evidence_prevents_visual_calls(monkeypatch, tmp_path, source):
    settings = BotSettings(video_download_dir=str(tmp_path), multimodal_enabled=True)
    instance = VideoUnderstanding(settings, SimpleNamespace())
    asset = VideoAsset(bvid="BV1234567890", duration=120, title="教程")
    downloads = []

    async def metadata(*_args, **_kwargs):
        return asset

    async def subtitles(*_args, **_kwargs):
        asset.subtitles = "有效字幕" * 20 if source == "subtitle" else "[无字幕]"

    async def download(*_args, **_kwargs):
        downloads.append(True)
        path = tmp_path / "video.mp4"
        path.touch()
        return path

    async def transcribe(*_args):
        return "有效ASR" * 20

    async def summary(*_args, **_kwargs):
        return "文本理解"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("must not call vision")

    monkeypatch.setattr(instance, "fetch_metadata", metadata)
    monkeypatch.setattr(instance, "fetch_subtitles", subtitles)
    monkeypatch.setattr(instance, "download_video", download)
    monkeypatch.setattr(instance, "transcribe_if_available", transcribe)
    monkeypatch.setattr(instance, "summarize_text_only", summary)
    monkeypatch.setattr(visual_preview, "analyze_visual_preview", forbidden)
    result = asyncio.run(instance.understand("BV1234567890"))
    assert result.summary == "文本理解"
    assert bool(downloads) is (source == "asr")
    assert not (tmp_path / "video.mp4").exists()


def test_scene_detection_failure_falls_back_without_raising(monkeypatch):
    monkeypatch.setattr(grid_frames.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=1))
    assert grid_frames.detect_scene_changes(Path("video"), "ffmpeg", 0, 60) == []


@pytest.mark.parametrize("asr_success,force_mode,expected_vision,frames_enabled,native_enabled", [
    (True, None, False, True, False), (False, None, True, True, False), (True, "all", True, True, False),
    (False, None, True, False, True), (True, None, False, False, True),
])
def test_brain_finishes_asr_before_optional_vision(monkeypatch, tmp_path, asr_success,
                                                force_mode, expected_vision, frames_enabled, native_enabled):
    monkeypatch.setattr('core.config.load_config', lambda: {'asr': {'enabled': True}})
    from brain import _brain_video
    from xingye_bot import asr_engine

    events = []
    path = tmp_path / "video.mp4"
    path.touch()

    class Engine:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def has_ffmpeg():
            return True

        async def process_video(self, *_args, **_kwargs):
            events.append("asr")
            return asr_engine.ASRResult(success=asr_success,
                                        text="Python 教程内容" if asr_success else "", error="empty")

        @staticmethod
        def format_result(_result):
            return "Python 教程内容"

    class Brain(_brain_video.BrainVideoMixin):
        cookies = {}

        @staticmethod
        def _is_vision_globally_disabled():
            return not frames_enabled

        async def _download_video_for_asr(self, *_args, **_kwargs):
            return str(path), 1, 1

        async def _analyze_timeline_grids(self, *_args, **_kwargs):
            events.append("vision")
            return "视觉笔记"

    async def subtitles(*_args, **_kwargs):
        return False, "", "简介", False

    monkeypatch.setattr(_brain_video, "fetch_bilibili_subtitles", subtitles)
    monkeypatch.setattr(_brain_video, "ASR_ENABLED", True)
    monkeypatch.setattr(_brain_video, "SUBTITLE_STRICT_CHECK", False)
    monkeypatch.setattr(_brain_video, "config", {
        "vision": {"frames_enabled": frames_enabled}, "asr": {"enabled": True},
        "direct_video": {"enabled": native_enabled},
    })
    monkeypatch.setattr(asr_engine, "get_asr_engine", lambda *_args: Engine())
    monkeypatch.setattr(asr_engine.ASREngine, "should_skip_asr", lambda **_kwargs: (False, ""))
    monkeypatch.setattr(asr_engine.ASREngine, "timing_summary", lambda *_args, **_kwargs: "timing")
    result = asyncio.run(Brain().understand_video_for_decision("BV1234567890", "Python", force_mode))
    assert result[0] is True
    assert events == (["asr", "vision"] if expected_vision else ["asr"])
    assert not path.exists()


def test_frame_settings_allow_half_second_and_custom_grid():
    options = grid_frames.visual_note_frame_options({
        "visual_note_frame_interval": "0.5", "visual_note_grid_cols": 6,
        "visual_note_grid_rows": 2,
    })
    assert options["frame_interval"] == 0.5
    assert options["grid"] == (6, 2)


def test_scene_detector_preserves_window_offset(monkeypatch):
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stderr="pts_time:5.5 pts_time:18.25")

    monkeypatch.setattr(grid_frames.subprocess, "run", run)
    assert grid_frames.detect_scene_changes(Path("video"), "ffmpeg", 60, 120) == [65.5, 78.25]
    assert commands[0][commands[0].index("-t") + 1] == "60"
