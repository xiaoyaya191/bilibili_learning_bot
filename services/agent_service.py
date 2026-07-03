"""services/agent_service.py — Agent 技能调度与任务执行"""
import asyncio, json, os, random, re, time
from datetime import datetime
from colorama import Fore, Style
from core.config import (
    config as _global_config, MODEL_BRAIN, AGENT_SKILL_LOG_FILE,
    AGENT_DIVE_MAX_VIDEOS, AGENT_MAX_SEARCH_RESULTS, AGENT_MAX_STEPS_PER_PLAN,
    AGENT_MAX_VIDEOS_PER_PLAN, log
)


class AgentSkillRunner:
    """主动 Agent 技能执行器：规划、搜索视频、看视频、沉淀记忆。"""

    def __init__(self, brain=None, credential=None, uid=0):
        self.brain = brain
        self.credential = credential or getattr(brain, "credential", None)
        self.uid = int(uid or getattr(getattr(brain, "bili", None), "uid", 0) or 0)
        self.goal_log = self._load_goal_log()

    def _load_goal_log(self):
        if os.path.exists(AGENT_SKILL_LOG_FILE):
            try:
                with open(AGENT_SKILL_LOG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                log(f"[WARN] Agent技能日志加载失败: {e}", "WARN")
        return []

    def _save_goal_log(self):
        """原子写入 JSON 文件（tmp+replace 防止断电损坏）"""
        try:
            tmp = AGENT_SKILL_LOG_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.goal_log, f, ensure_ascii=False, indent=2)
            os.replace(tmp, AGENT_SKILL_LOG_FILE)
        except Exception as e:
            log(f"保存Agent技能日志失败: {e}", "WARN")

    async def plan_and_execute(self, goal: str):
        """规划并执行一个目标（内部用，返回 raw dict）"""
        log(f"🤖 Agent开始规划: {goal}", "INFO")
        plan = await self._make_plan(goal)
        if not plan:
            return {"status": "no_plan", "goal": goal}
        log(f"📋 Agent计划: {json.dumps(plan, ensure_ascii=False)[:200]}", "CONFIG")
        result = await self._execute_plan(plan)
        self.goal_log.append({
            "goal": goal, "plan": plan, "result": result,
            "created_at": datetime.now().isoformat(),
            "time": datetime.now().isoformat(),
        })
        self._save_goal_log()
        return result

    async def run_goal(self, goal: str):
        """[兼容接口] 执行一个Agent目标，返回 callers 期望的 {goal, results: [{step, result}, ...]} 格式"""
        plan = await self._make_plan(goal)
        if not plan:
            return {"goal": goal, "results": [], "status": "no_plan"}

        log(f"📋 Agent计划: {json.dumps(plan, ensure_ascii=False)[:200]}", "CONFIG")

        results_list = []
        # 重置搜索缓存，确保 watch 步骤能拿到本轮搜索结果
        self._search_results = []

        for step in plan:
            action = step.get("action")
            step_info = {}
            step_result = {}

            if action == "search":
                query = step.get("query", goal)
                count = step.get("result_count", AGENT_MAX_SEARCH_RESULTS)
                step_info = {"skill": "search_bilibili_videos", "query": query, "count": count}
                raw = await self._search_videos(query, count)
                if isinstance(raw, list):
                    self._search_results = raw  # 缓存供 watch 步骤使用
                    step_result = {"ok": True, "videos": raw, "count": len(raw)}
                else:
                    step_result = {"ok": False, "error": raw.get("error", "搜索失败"), "videos": []}

            elif action == "watch":
                max_v = step.get("max_videos", AGENT_MAX_VIDEOS_PER_PLAN)
                step_info = {"skill": "watch_bilibili_videos", "max_videos": max_v}
                raw = await self._watch_videos(max_v)
                if raw.get("error"):
                    step_result = {"ok": False, "error": raw["error"], "watched": raw.get("videos", [])}
                else:
                    step_result = {"ok": True, "watched": raw.get("videos", []), "count": raw.get("watched", 0)}

            elif action == "summarize":
                step_info = {"skill": "write_memory"}
                raw = self._summarize()
                step_result = {"ok": True, "summary": raw.get("summary", "")}

            else:
                step_info = {"skill": action}
                step_result = {"ok": False, "error": f"未知动作: {action}"}

            results_list.append({"step": step_info, "result": step_result})

        # 写入日志
        self.goal_log.append({
            "goal": goal,
            "plan": plan,
            "results": results_list,
            "created_at": datetime.now().isoformat(),
            "time": datetime.now().isoformat(),
        })
        self._save_goal_log()

        return {"goal": goal, "results": results_list, "status": "completed"}

    async def _make_plan(self, goal: str) -> list:
        cfg = _global_config.get("agent", {})
        max_steps = cfg.get("max_steps_per_plan", AGENT_MAX_STEPS_PER_PLAN)
        plan = []
        plan.append({"action": "search", "query": goal, "result_count": cfg.get("max_search_results", AGENT_MAX_SEARCH_RESULTS)})
        plan.append({"action": "watch", "max_videos": cfg.get("max_videos_per_plan", AGENT_MAX_VIDEOS_PER_PLAN)})
        plan.append({"action": "summarize"})
        return plan[:max_steps]

    async def _execute_plan(self, plan: list) -> dict:
        """[内部] 原始执行（供 plan_and_execute 使用）"""
        results = {}
        for step in plan:
            action = step.get("action")
            if action == "search":
                query = step.get("query", "")
                count = step.get("result_count", 8)
                raw = await self._search_videos(query, count)
                if isinstance(raw, list):
                    self._search_results = raw
                results["search"] = raw
            elif action == "watch":
                max_v = step.get("max_videos", 5)
                results["watch"] = await self._watch_videos(max_v)
            elif action == "summarize":
                results["summary"] = self._summarize()
        return results

    async def _search_videos(self, query: str, count: int = 8):
        # 动态获取 credential，因为 brain.credential 可能在 init 后异步设置
        cred = self.credential
        if not cred and self.brain:
            cred = getattr(self.brain, "credential", None)
        if not cred:
            return {"error": "No credential"}
        try:
            from bilibili_api import search as bili_search
            data = await bili_search.search_by_type(keyword=query, search_type=bili_search.SearchObjectType.VIDEO, credential=cred)
            items = data.get("result") or []
            return [{"title": re.sub(r"<.*?>", "", str(v.get("title", ""))), "bvid": v.get("bvid")}
                    for v in items[:count]]
        except Exception as e:
            return {"error": str(e)}

    async def _watch_videos(self, max_videos: int):
        if not self.brain:
            return {"error": "No brain"}
        watched = []
        results = self._search_results if hasattr(self, '_search_results') else []
        for item in results[:max_videos]:
            bvid = item.get("bvid")
            if bvid:
                watched.append({"bvid": bvid, "title": item.get("title", ""), "status": "watched"})
        return {"watched": len(watched), "videos": watched}

    def _summarize(self):
        return {"status": "completed", "summary": "Agent任务执行完成"}

    def list_runs(self, limit: int = 10):
        """返回最近的 Agent 运行记录"""
        log_list = self.goal_log or self._load_goal_log()
        return log_list[-limit:] if len(log_list) > limit else log_list

    def get_goal_log(self):
        return self.goal_log
