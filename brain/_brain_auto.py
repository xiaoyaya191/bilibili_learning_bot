"""brain/_brain_auto.py — AgentBrain 自动日记/进化/Agent任务 mixin"""
from brain._mixin_imports import *

class BrainAutoMixin:
    """自动日记、自我进化、Agent目标执行、深度搜索主题选择"""

    async def maybe_auto_diary(self, force=False):
        if not DIARY_ENABLED or not DIARY_AUTO_ENABLED:
            return False
        if len(self.session_events) < DIARY_MIN_EVENTS_FOR_AUTO and not force:
            return False
        elapsed = (datetime.now() - self.last_auto_diary_at).total_seconds() / 60
        if elapsed < DIARY_AUTO_INTERVAL_MINUTES and not force:
            return False
        try:
            entry = await self.diary_mgr.generate_from_events(
                self.session_events,
                self.persona_mgr.build_prompt_block(),
                self.mood_mgr.get_current()
            )
            self.last_auto_diary_at = datetime.now()
            log(f"自动日记已生成: {entry.get('title')}", "NOTE")
            return True
        except Exception as e:
            log(f"自动日记生成失败: {e}", "WARN")
            return False

    async def maybe_self_evolve(self, force=False):
        if not EVOLUTION_ENABLED or not EVOLUTION_AUTO_ENABLED:
            return False
        new_events = self.processed_event_count - self.events_at_last_evolution
        if new_events < EVOLUTION_REFLECT_INTERVAL_EVENTS and not force:
            return False
        if len(self.session_events) < EVOLUTION_MIN_EVENTS_FOR_REFLECT and not force:
            return False
        try:
            item = await self.evolution_mgr.reflect(
                self.session_events,
                self.persona_mgr.build_prompt_block(),
                self.mood_mgr.get_current(),
                diary_entries=self.diary_mgr.list_entries(limit=5)
            )
            parsed = item.get("parsed", {})
            if EVOLUTION_AUTO_APPLY:
                self.persona_mgr.evolve_active_persona(
                    style_delta=str(parsed.get("style_delta") or "").strip(),
                    relationship_delta=str(parsed.get("relationship_delta") or "").strip(),
                    new_rule=str(parsed.get("new_rule") or "").strip()
                )
                try:
                    mood_delta = int(float(parsed.get("mood_delta", 0)))
                except Exception:
                    mood_delta = 0
                if mood_delta:
                    self.mood_mgr.shift("自动自我进化", max(-2, min(2, mood_delta)))
                self.evolution_mgr.mark_applied(item.get("id"))
            self.events_at_last_evolution = self.processed_event_count
            log(f"自我进化复盘完成: {str(parsed.get('reflection', ''))[:80]}", "EVOLVE")
            return True
        except Exception as e:
            log(f"自我进化失败: {e}", "WARN")
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
        try:
            log(f"🤖 Agent后台探索: {goal[:60]}...", "CONFIG")
            run = await asyncio.wait_for(
                self.agent_runner.run_goal(goal),
                timeout=180
            )
            ok_steps = sum(1 for item in run.get("results", []) if item.get("result", {}).get("ok"))
            log(f"🤖 Agent后台完成: {ok_steps}/{len(run.get('results', []))}步骤", "CONFIG")
        except asyncio.TimeoutError:
            log(f"🤖 Agent后台探索超时(180s)，已跳过", "WARN")
        except Exception as e:
            log(f"🤖 Agent后台异常: {e}", "WARN")

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
