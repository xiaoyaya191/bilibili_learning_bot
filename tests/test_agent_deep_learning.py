import asyncio
from types import SimpleNamespace

from brain import _brain_auto
from services import agent_service
from services.agent_service import AgentSkillRunner


def test_agent_watch_uses_real_analysis_pipeline(monkeypatch):
    calls = []

    async def fake_analyze(bvid, force_mode=None, intent=""):
        calls.append((bvid, force_mode, intent))
        return True, f"B站分析完成：{bvid}，评分 8.0/10，归档=是"

    async def no_sleep(_seconds):
        return None

    from brain import video_analysis

    monkeypatch.setattr(video_analysis, "analyze_bilibili_video_input", fake_analyze)
    monkeypatch.setattr(agent_service.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(
        agent_service,
        "_global_config",
        {"agent": {"deep_learning_enabled": True, "deep_learning_max_videos": 2, "deep_learning_timeout_seconds": 30}},
    )

    runner = AgentSkillRunner(brain=SimpleNamespace())
    runner._search_results = [
        {"bvid": "BV1testA", "title": "第一条"},
        {"bvid": "BV1testB", "title": "第二条"},
        {"bvid": "BV1testC", "title": "第三条"},
    ]

    result = asyncio.run(runner._watch_videos(5))

    assert [call[0] for call in calls] == ["BV1testA", "BV1testB"]
    assert all(call[1] is None for call in calls)
    assert result["watched"] == 2
    assert [item["status"] for item in result["videos"]] == ["archived", "archived"]


def test_agent_background_goal_deduplicates_concurrent_runs(monkeypatch):
    class Runner:
        def __init__(self):
            self.calls = 0

        async def run_goal(self, _goal):
            self.calls += 1
            await asyncio.sleep(0.01)
            return {"results": [{"result": {"ok": True}}]}

    runner = Runner()
    brain = SimpleNamespace(agent_runner=runner, _agent_goal_running=False)
    monkeypatch.setattr(_brain_auto, "AGENT_ENABLED", True)
    monkeypatch.setitem(_brain_auto.config, "agent", {"deep_learning_timeout_seconds": 30})

    async def run_both():
        await asyncio.gather(
            _brain_auto.BrainAutoMixin._agent_goal_async(brain, "主题 A"),
            _brain_auto.BrainAutoMixin._agent_goal_async(brain, "主题 B"),
        )

    asyncio.run(run_both())

    assert runner.calls == 1
    assert brain._agent_goal_running is False
