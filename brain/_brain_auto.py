"""brain/_brain_auto.py — AgentBrain 自动日记/进化/Agent任务 mixin"""
from brain._mixin_imports import *

class BrainAutoMixin:
    """自动日记、自我进化、Agent目标执行、深度搜索主题选择"""

    async def maybe_auto_diary(self, force=False):
        from services.diary_scheduler import DiaryScheduler, settings
        now = datetime.now()
        if not force and (now - getattr(self, "_last_diary_check", datetime.min)).total_seconds() < 60:
            return False
        self._last_diary_check = now
        try:
            scheduler = getattr(self, "_diary_scheduler", None)
            if scheduler is None:
                scheduler = self._diary_scheduler = DiaryScheduler()
            result = await scheduler.generate(settings(), manual=force,
                persona_prompt=self.persona_mgr.build_prompt_block(), mood=self.mood_mgr.get_current())
            if not result.get("ok"):
                if result.get("status") == "failed":
                    log(result["message"], "WARN")
                return False
            self.diary_mgr.recheck()
            self.last_auto_diary_at = datetime.now()
            log(f"自动日记已生成: {result['entry'].get('title')}", "NOTE")
            return True
        except Exception as error:
            log(f"自动日记检查失败: {type(error).__name__}", "WARN")
            return False

    async def maybe_self_evolve(self, force=False):
        from services.evolution_engine import EvolutionEngine
        from services.evolution_settings import settings
        now = datetime.now()
        if not force and (now - getattr(self, "_last_evolution_check", datetime.min)).total_seconds() < 60:
            return False
        self._last_evolution_check = now
        try:
            preferences = settings()
            if not preferences["enabled"] or not preferences["auto_enabled"]:
                return False
            engine = getattr(self, "_evolution_engine", None)
            if engine is None:
                engine = self._evolution_engine = EvolutionEngine()
            layer = engine.due_layer(preferences)
            if layer is None:
                return False
            result = await engine.generate(layer, preferences)
            if result.get("ok"):
                log("进化提案已生成，请在AI进化分区查看审核", "EVOLVE")
            elif result.get("status") == "failed":
                log(result["message"], "WARN")
            return bool(result.get("ok"))
        except Exception as error:
            log("进化检查失败：" + type(error).__name__, "WARN")
            return False

    async def maybe_run_agent_goal(self, goal, score=0, force=False):
        if not AGENT_ENABLED or not AGENT_AUTO_ENABLED:
            return False
        if not force and float(score or 0) < float(AGENT_AUTO_MIN_SCORE):
            return False
        elapsed = (datetime.now() - self.last_agent_run_at).total_seconds() / 60
        if not force and elapsed < AGENT_COOLDOWN_MINUTES:
            return False
        try:
            log(f"Agent开始主动规划: {goal}", "CONFIG")
            run = await self.agent_runner.run_goal(goal)
            self.last_agent_run_at = datetime.now()
            ok_steps = sum(1 for item in run.get("results", []) if item.get("result", {}).get("ok"))
            log(f"Agent执行完成: {ok_steps}/{len(run.get('results', []))} 个步骤成功", "SUCCESS")
            return True
        except Exception as e:
            log(f"Agent执行失败: {e}", "WARN")
            return False

    async def _agent_goal_async(self, goal, score=0):
        if not AGENT_ENABLED:
            return
        if getattr(self, "_agent_goal_running", False):
            log("Agent 后台探索已在运行，本次触发已合并跳过", "INFO")
            return
        self._agent_goal_running = True
        try:
            log(f"Agent后台探索: {goal[:60]}...", "CONFIG")
            agent_cfg = config.get("agent", {}) if isinstance(config, dict) else {}
            timeout_seconds = max(30, min(1800, int(agent_cfg.get("deep_learning_timeout_seconds", 180) or 180)))
            run = await asyncio.wait_for(
                self.agent_runner.run_goal(goal),
                timeout=timeout_seconds
            )
            ok_steps = sum(1 for item in run.get("results", []) if item.get("result", {}).get("ok"))
            log(f"Agent后台完成: {ok_steps}/{len(run.get('results', []))}步骤", "CONFIG")
        except asyncio.TimeoutError:
            log(f"Agent后台探索超时，已跳过", "WARN")
        except Exception as e:
            log(f"Agent后台异常: {e}", "WARN")
        finally:
            self._agent_goal_running = False

    async def _pick_agent_dive_topic(self):
        if getattr(self, "_last_interesting_topic", ""):
            recent = self._last_interesting_topic
            self._last_interesting_topic = ""
            return recent
        topics = []
        if hasattr(self, "interest_mgr") and self.interest_mgr:
            interests = self.interest_mgr.get_interests()[:10]
            for i in interests:
                if isinstance(i, dict):
                    name = i.get("name") or i.get("keyword") or str(i)
                else:
                    name = str(i)
                if name:
                    topics.append(f"深入了解{name}")
        if os.path.exists(KNOWLEDGE_BASE_DIR):
            try:
                for d in os.listdir(KNOWLEDGE_BASE_DIR):
                    dpath = os.path.join(KNOWLEDGE_BASE_DIR, d)
                    if os.path.isdir(dpath) and d not in ("未分类",):
                        topics.append(f"继续学习{d}领域的新知识")
            except OSError as e:
                log(f'文件操作失败: {e}', 'DEBUG')
        if self.memory.get("known_ups"):
            up = random.choice(list(self.memory["known_ups"].keys())[:5])
            topics.append(f"搜索了解UP主{up}的视频风格和代表作")
        if not topics:
            return None
        return random.choice(topics)
