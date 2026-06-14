#!/usr/bin/env python3
"""测试两个修复：
1. AgentSkillRunner.run_goal / list_runs  => 修复 'AgentSkillRunner' object has no attribute 'run_goal'
2. request() 包装器是否注入 csrf                  => 修复 csrf 校验失败 / CSRF 校验失败
"""
import asyncio, json, sys, os

# ── 确保当前目录在 sys.path ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("  测试 1: AgentSkillRunner.run_goal & list_runs")
print("=" * 60)

# 不触发 openai / bilibili_api 导入的轻量测试
from services.agent_service import AgentSkillRunner

# 1a) 方法存在性
runner = AgentSkillRunner()
assert hasattr(runner, "run_goal"), "FAIL: run_goal 不存在！"
assert callable(runner.run_goal), "FAIL: run_goal 不可调用！"
assert hasattr(runner, "list_runs"), "FAIL: list_runs 不存在！"
assert callable(runner.list_runs), "FAIL: list_runs 不可调用！"
print("✅ run_goal 和 list_runs 方法均已存在且可调用")

# 1b) list_runs 返回正确类型
runs = runner.list_runs(limit=5)
assert isinstance(runs, list), f"FAIL: list_runs 应返回 list，实际返回 {type(runs)}"
print(f"✅ list_runs(5) 返回 {len(runs)} 条记录 (类型=列表)")

# 1c) 模拟 run_goal 的返回结构（不实际调用 bilibili_api）
# 手动构造 goal_log 条目来验证返回格式
async def _test_run_goal_return_format():
    runner2 = AgentSkillRunner()
    # 注入假的 _search_videos 避免真实 API 调用
    async def fake_search(query, count=8):
        return [{"title": f"测试视频 {i}", "bvid": f"BVtest{i}"} for i in range(count)]
    runner2._search_videos = fake_search

    result = await runner2.run_goal("测试目标")
    assert isinstance(result, dict), f"run_goal 应返回 dict，实际 {type(result)}"
    assert "goal" in result, "run_goal 返回缺少 'goal'"
    assert "results" in result, "run_goal 返回缺少 'results'"
    assert isinstance(result["results"], list), "results 应为列表"

    for item in result["results"]:
        assert "step" in item, f"results 条目缺少 'step': {item}"
        assert "result" in item, f"results 条目缺少 'result': {item}"
        step = item["step"]
        assert "skill" in step, f"step 缺少 'skill': {step}"

    ok_count = sum(1 for i in result["results"] if i["result"].get("ok"))
    print(f"  run_goal 返回 {len(result['results'])} 个步骤, {ok_count} 个成功")
    print(f"  goal_log 已写入 {len(runner2.goal_log)} 条记录")
    print("✅ run_goal 返回格式正确")

asyncio.run(_test_run_goal_return_format())

# 1d) list_runs 读取刚才写入的 log
runner3 = AgentSkillRunner()
log = runner3.list_runs(limit=10)
print(f"✅ list_runs 可从磁盘读取 goal_log ({len(log)} 条)")

print()
print("=" * 60)
print("  测试 2: request() 包装器 csrf 注入")
print("=" * 60)

# 模拟 bilibili_api 的 Api 类行为
from unittest.mock import MagicMock, AsyncMock, patch
from bilibili_api.utils.network import Api, Credential

async def _test_request_csrf_injection():
    # 创建一个假的 credential（有 bili_jct）
    cred = Credential(
        sessdata="fake_sessdata_1234567890",
        bili_jct="fake_bili_jct_token_abc123",
        buvid3="00000000-0000-0000-0000-000000000000infoc",
        dedeuserid="12345"
    )

    # 导入 new_agent 的 request 函数
    # （monkey-patch Api.request 为 fake 版本，捕获实际发出的 data）
    original_api_request = Api.request

    captured_data = {}

    async def fake_api_request(self, **kwargs):
        # 调用 _prepare_request 来看最终数据
        config = await self._prepare_request()
        captured_data["final_data"] = config.get("data", {})
        captured_data["final_params"] = config.get("params", {})
        captured_data["method"] = config.get("method", "")
        # 返回一个模拟响应
        return {"code": 0, "message": "ok", "data": {}}

    # patch
    Api.request = fake_api_request

    try:
        from new_agent import request

        # 测试 POST 请求（点赞、收藏等操作的典型调用方式）
        result = await request(
            "POST",
            "https://api.bilibili.com/x/web-interface/archive/like",
            data={"aid": 123456, "bvid": "BVtest123", "like": 1},
            credential=cred
        )

        print(f"  request() 返回值: {json.dumps(result, ensure_ascii=False)}")
        print(f"  捕获到的 final_data: {json.dumps(captured_data.get('final_data', {}), ensure_ascii=False)}")

        # 验证 csrf 是否被注入
        final_data = captured_data.get("final_data", {})
        assert "csrf" in final_data, (
            f"FAIL: csrf 未被注入到 POST data 中！\n"
            f"  final_data 内容: {final_data}\n"
            f"  这说明 request() 未设置 verify=True 或 Api 未自动添加 csrf"
        )
        assert final_data["csrf"] == "fake_bili_jct_token_abc123", (
            f"FAIL: csrf 值不正确！期望 fake_bili_jct_token_abc123，实际 {final_data.get('csrf')}"
        )
        print("✅ csrf 已正确注入到 POST 请求数据中")

        # 测试 GET 请求（不应要求 csrf，但 verify=True 会检查 sessdata）
        captured_data.clear()
        result2 = await request(
            "GET",
            "https://api.bilibili.com/x/web-interface/view",
            data={"bvid": "BVtest123"},
            credential=cred
        )
        print(f"  GET 请求返回值 code: {result2.get('code')}")
        print("✅ GET 请求未崩溃")

    finally:
        Api.request = original_api_request

asyncio.run(_test_request_csrf_injection())

print()
print("=" * 60)
print("  测试 3: request() 无 credential 时不崩溃")
print("=" * 60)

async def _test_request_no_credential():
    original_api_request = Api.request
    called = False
    async def fake_no_cred(self, **kwargs):
        nonlocal called
        called = True
        config = await self._prepare_request()
        return {"code": 0, "data": config.get("data", {})}

    Api.request = fake_no_cred
    try:
        from new_agent import request
        result = await request("GET", "https://api.bilibili.com/x/web-interface/view",
                               data={"bvid": "BVtest"})
        assert called, "Api.request 未被调用"
        print("✅ 无 credential 的 request() 调用正常")
    finally:
        Api.request = original_api_request

asyncio.run(_test_request_no_credential())

print()
print("=" * 60)
print("  全部测试通过 ✅")
print("=" * 60)
print()
print("修复摘要:")
print("  1. services/agent_service.py: 新增 run_goal() 方法（返回 {goal, results} 格式）")
print("     + 新增 list_runs(limit) 方法")
print("     + _execute_plan 内部正确缓存 _search_results 供 watch 步骤使用")
print("  2. new_agent.py request() 包装器: credential 存在时设置 api.verify = True")
print("     → Api._prepare_request 自动向 POST 请求注入 csrf/csrf_token")
