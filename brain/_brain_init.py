"""brain/_brain_init.py — AgentBrain 初始化 & 预取 mixin"""
from brain._mixin_imports import *

class BrainInitMixin:
    """AgentBrain __init__ & prefetch"""
    
    def __init__(self):
        self.bili = BiliClient()
        self.energy = MAX_ENERGY
        self.coins_spent = 0
        self.last_coin_at = datetime.min   # 上次投币时间（冷却用）
        self._coin_hour_timestamps = []    # 最近一小时内投币时间戳（每小时上限用）
        self.memory = self._load_memory()
        self.last_energy_recovery = datetime.now()
        
        self.classifier = KnowledgeBaseClassifier()
        self.interest_mgr = InterestManager()
        self.comment_mgr = None
        self.private_message_mgr = None
        self.last_comment_check = None
        self.last_private_message_check = None
        self.last_mention_check = None
        self._normal_mention_monitor = None
        self._last_per_video_check = None      # 看完视频后通知检查冷却
        self._processed_at_ids = set()         # 已处理的@通知ID去重
        self.persona_mgr = PersonaManager()
        self.mood_mgr = MoodManager()
        self.user_profile_mgr = UserProfileManager()
        self.diary_mgr = BotDiaryManager()
        self.evolution_mgr = SelfEvolutionManager()
        self.session_events = []
        self.processed_event_count = 0
        self.events_at_last_evolution = 0
        # Allow the first diary as soon as enough session events accumulate;
        # subsequent entries still follow the configured cooldown.
        self.last_auto_diary_at = datetime.min
        self.agent_runner = AgentSkillRunner(brain=self)
        self.last_agent_run_at = datetime.now()
        self._agent_goal_running = False
        self._recent_watched_titles = []  # 兴趣引擎AI建议追踪
        self._last_video_desc = ""  # 兴趣引擎desc参数传递
        self.session_start_time = datetime.now()
        self.videos_processed = 0
        self.videos_learned = 0
        self._last_interesting_topic = ""
        self._last_video_desc = ""
        self._last_reclassify_at = datetime.min
        self._prefetched_recs = None
        self._prefetch_lock = asyncio.Lock()
        self.runtime_state = load_json_file(RUNTIME_STATE_FILE, {"last_seen_at": "", "current_start_at": "", "current_heartbeat_at": ""})
        self.previous_seen_at = self.runtime_state.get("current_heartbeat_at") or self.runtime_state.get("last_seen_at") or ""
        self.previous_seen_ts = 0
        if self.previous_seen_at:
            try:
                self.previous_seen_ts = int(datetime.fromisoformat(self.previous_seen_at).timestamp())
            except Exception:
                self.previous_seen_ts = 0
        self.video_understander = None
        if VideoUnderstanding and ModelClient and BotState and load_modular_settings:
            try:
                modular_settings = load_modular_settings()
                self.video_understander = VideoUnderstanding(modular_settings, ModelClient(modular_settings, BotState()))
            except Exception as e:
                log(f"视频理解模块初始化失败，将退回字幕模式: {e}", "WARN")

        self.kb_search = None
        if KBSearchEngine and ModelClient and load_modular_settings and BotState:
            try:
                modular_settings = load_modular_settings()
                self.kb_search = KBSearchEngine(ModelClient(modular_settings, BotState()))
            except Exception as e:
                log(f"向量检索引擎初始化失败: {e}", "WARN")

        self.cookies = None
        self.credential = None
        self._ai_errors_consecutive = 0
        self._preferred_ai_method = None
        self._ai_degraded_until = 0.0
        self._ai_primary_failing = 0
        self._ai_using_fallback_provider = False
        self._ai_fallback_recheck_at = 0.0

        self.history_videos = self._load_history_videos()
        self.last_revisit_at = datetime.min
        self._active_chat_count = 0
        self._last_active_chat_at = datetime.min
        
        self._last_curiosity_dive_at = datetime.min
        self._curiosity_dive_count_today = 0
        self._curiosity_dive_date = ""

        self.daily_follows = 0
        self.daily_follows_date = ""
        self.last_follow_at = datetime.min
        self.last_up_browse_at = datetime.min
        
        self.daily_danmaku_likes = 0
        self.daily_danmaku_likes_date = ""
        self.daily_danmaku_sent = 0
        self.daily_danmaku_sent_date = ""
        self._last_danmaku_videos = {}
        self._last_danmaku_cids = {}
        
        self.psycho_profile = None
        self.recommend_engine = None
        self._psycho_profile_analysis_count = 0
        self._knowledge_review_countdown = KNOWLEDGE_REVIEW_INTERVAL
        self._last_recommend_mode = None

        # ── OpenBiliClaw 集成 ──
        self.ob_client = None
        self.ob_enabled = False
        self.ob_ready = False
        self._ob_queue = []  # 预取的 OB 推荐队列
        self._ob_auditor = None      # Phase 4: OB效能审计器
        self._ob_ab_tracker = None   # Phase 4: AB对比跟踪器
        self._ob_last_audit_report = 0  # 上次审计报告时间戳

    async def _init_ob_bridge(self):
        """初始化 OpenBiliClaw 桥梁（在 run() 开始时调用）"""
        try:
            from ob_bridge.client import OBClient
            from ob_bridge.health import ensure_ob_ready, auto_detect_mode

            ob_cfg = config.get("ob", {})
            if not ob_cfg.get("enabled", False):
                log("[OB] 未启用，使用原有推荐流", "INFO")
                return

            base_url = ob_cfg.get("base_url", "http://127.0.0.1:8420")
            auto_launch = ob_cfg.get("auto_launch", False)
            launch_cwd = ob_cfg.get("launch_cwd", "")
            launch_command = ob_cfg.get("launch_command", "openbiliclaw serve")
            health_timeout = ob_cfg.get("health_check_timeout_seconds", 5)

            # 确保 OB 在线
            status = await ensure_ob_ready(
                base_url=base_url,
                auto_launch=auto_launch,
                launch_cwd=launch_cwd,
                launch_command=launch_command,
                wait_seconds=health_timeout * 3,
            )

            if not status.online:
                log(f"[OB] ⚠️ 无法连接，降级为原有推荐流: {status.error}", "WARN")
                self.ob_enabled = False
                self.ob_ready = False
                return

            # 创建客户端
            self.ob_client = OBClient(base_url=base_url, timeout=health_timeout)
            self.ob_ready = True
            self.ob_enabled = True

            # 自动检测模式（有画像→精准，无画像→探索）
            if ob_cfg.get("explore_mode_fallback", True):
                await auto_detect_mode(self.ob_client)
            else:
                log("[OB] 探索模式自动切换已关闭，使用默认精准模式", "INFO")

            log(f"[OB] ✅ 集成就绪 | 模式: {self.ob_client.mode.value} | {base_url}", "SUCCESS")

            # ── Phase 4: 初始化审计 & AB 对比跟踪器 ──
            if ob_cfg.get("audit_enabled", True):
                try:
                    from ob_bridge.audit import OBAuditor
                    self._ob_auditor = OBAuditor()
                    log("[OB] 📊 效能审计器已初始化", "CONFIG")
                except ImportError:
                    pass

            if ob_cfg.get("ab_test_enabled", True):
                try:
                    from ob_bridge.ab_test import ABComparisonTracker
                    self._ob_ab_tracker = ABComparisonTracker(
                        window_size=ob_cfg.get("ab_window_size", 200))
                    log("[OB] ⚖️ AB对比跟踪器已初始化", "CONFIG")
                except ImportError:
                    pass

        except ImportError:
            log("[OB] ob_bridge 模块未安装", "WARN")
            self.ob_enabled = False
        except Exception as e:
            log(f"[OB] 初始化异常: {e}", "WARN")
            self.ob_enabled = False

    async def _prefetch_recommendations(self):
        async with self._prefetch_lock:
            try:
                # 优先从 OB 预取
                if self.ob_enabled and self.ob_client:
                    limit = config.get("ob", {}).get("recommendation_fetch_limit", 20)
                    items = await self.ob_client.get_recommendations(limit=limit)
                    if items:
                        # 转换为 B站兼容格式，并标记来源
                        recs = [item.to_bili_format() for item in items]
                        for r in recs:
                            r["_source"] = "ob"
                        self._prefetched_recs = recs
                        # Phase 4: AB对比记录推荐量
                        if self._ob_ab_tracker:
                            self._ob_ab_tracker.record_recommend("ob", len(recs))
                        return
                    # OB 返回空 → 降级
                    self._prefetched_recs = None
                    return

                # 原有 B站推荐流
                items = await self.bili.get_recommendations()
                if items and isinstance(items, list):
                    for r in items:
                        r["_source"] = "native"
                    self._prefetched_recs = items
                    if self._ob_ab_tracker:
                        self._ob_ab_tracker.record_recommend("native", len(items))
            except Exception:
                self._prefetched_recs = None

    async def _get_cached_recommendations(self):
        async with self._prefetch_lock:
            cached = self._prefetched_recs
            self._prefetched_recs = None

        if cached and isinstance(cached, list):
            log("📡 [预取命中] 使用后台预加载的推荐流", "SCAN")
            return cached

        # 优先从 OB 获取
        if self.ob_enabled and self.ob_client:
            limit = config.get("ob", {}).get("recommendation_fetch_limit", 20)
            items = await self.ob_client.get_recommendations(limit=limit)
            if items:
                log(f"[OB] 直接拉取 {len(items)} 条推荐", "SCAN")
                recs = [item.to_bili_format() for item in items]
                for r in recs:
                    r["_source"] = "ob"
                if self._ob_ab_tracker:
                    self._ob_ab_tracker.record_recommend("ob", len(recs))
                return recs
            # OB 失败 → 降级
            log("[OB] 拉取失败，降级为原有推荐流", "WARN")
            items = await self.bili.get_recommendations()
            if items and isinstance(items, list):
                for r in items:
                    r["_source"] = "native"
                if self._ob_ab_tracker:
                    self._ob_ab_tracker.record_recommend("native", len(items))
            return items if items else []  # OB enabled 但失败 → 降级

        # 原有 B站推荐流（OB 未启用）
        items = await self.bili.get_recommendations()
        if items and isinstance(items, list):
            for r in items:
                r["_source"] = "native"
            if self._ob_ab_tracker:
                self._ob_ab_tracker.record_recommend("native", len(items))
        return items if items else []

    async def _report_to_ob(self, bvid: str, learned: bool, score: float, topic: str = ""):
        """看完视频后回传行为事件到 OB（fire-and-forget）"""
        if not self.ob_enabled or not self.ob_client:
            return
        ob_cfg = config.get("ob", {})
        if not ob_cfg.get("event_report_enabled", True):
            return

        try:
            event_type = "watch" if learned else "skip"
            metadata = {
                "score": score,
                "learned": learned,
                "topic": topic,
            }
            ok = await self.ob_client.report_event(bvid, event_type, metadata)
            if ok:
                log(f"[OB] 事件回传: {bvid} ({event_type})", "DEBUG")
        except Exception:
            pass

    async def _feedback_to_ob(self, ob_id: int, score: float) -> bool:
        """基于 brain 决策分数回传推荐反馈"""
        if not self.ob_enabled or not self.ob_client or not ob_id:
            return False
        ob_cfg = config.get("ob", {})
        if not ob_cfg.get("feedback_enabled", True):
            return False

        # 映射规则
        if self.ob_client.mode.value == "explore":
            # 探索模式：降低阈值，加速画像积累
            if score >= 5.0:
                fb_type, note = "like", "探索中发现不错的内容"
            elif score >= 3.0:
                fb_type, note = "dismiss", "探索中，一般"
            else:
                fb_type, note = "dislike", "探索中，不感兴趣"
        else:
            # 精准模式：正常阈值
            if score >= 7.0:
                fb_type, note = "like", "高质量内容，对我帮助大"
            elif score >= 4.0:
                fb_type, note = "dismiss", "看了但收获不大"
            else:
                fb_type, note = "dislike", "纯浪费时间"

        try:
            ok = await self.ob_client.report_feedback(ob_id, fb_type, note)
            if ok:
                log(f"[OB] 推荐反馈: ID={ob_id} → {fb_type}", "DEBUG")
            return ok
        except Exception:
            return False

    # ── Phase 3: 画像双向同步 ──

    async def _sync_profile_from_ob(self) -> Optional[dict]:
        """读取 OB 画像，用于辅助三层脑决策

        Returns:
            dict 含 profile 和 summary，None 表示读取失败或 OB 未启用
        """
        if not self.ob_enabled or not self.ob_client:
            return None
        ob_cfg = config.get("ob", {})
        if not ob_cfg.get("profile_sync_enabled", True):
            return None

        try:
            profile_data = await self.ob_client.get_profile_summary()
            if profile_data:
                summary = profile_data.get("summary", "")
                surface = profile_data.get("profile", {}).get("surface", {})
                likes = surface.get("primary_interests", [])
                dislikes = surface.get("dislikes", [])
                secondary = surface.get("secondary_interests", [])

                if likes or secondary:
                    log(f"[OB] 画像同步: {len(likes)} 个主兴趣, {len(secondary)} 个副兴趣", "SCAN")
                return profile_data
        except Exception:
            pass
        return None

    async def _inject_ob_profile_to_prompt(self) -> str:
        """构建 OB 画像注入块，追加到 AI 决策 prompt 中

        让理性层可以引用 OB 的兴趣强度作为"好奇心"的量化依据。
        """
        profile = await self._sync_profile_from_ob()
        if not profile:
            return ""

        surface = profile.get("profile", {}).get("surface", {})
        summary = profile.get("summary", "")

        parts = []
        likes = surface.get("primary_interests", [])
        if likes:
            parts.append(f"OB兴趣: {', '.join(likes[:8])}")

        dislikes = surface.get("dislikes", [])
        if dislikes:
            parts.append(f"OB排除: {', '.join(dislikes[:5])}")

        secondary = surface.get("secondary_interests", [])
        if secondary:
            parts.append(f"OB探索方向: {', '.join(secondary[:5])}")

        if summary:
            parts.append(f"OB画像摘要: {summary}")

        if not parts:
            return ""

        block = "\n[📊 OpenBiliClaw 画像] " + " | ".join(parts) + "\n"
        return block

    async def _push_knowledge_gaps_to_ob(self):
        """同步知识盲区到 OB 画像（知识库覆盖率分析）"""
        if not self.ob_enabled or not self.ob_client:
            return

        try:
            from ob_bridge.config_bridge import sync_knowledge_gaps_to_ob

            # 从知识库分类器获取各领域覆盖情况
            gaps = []
            if hasattr(self, "classifier") and self.classifier:
                structure = self.classifier.get_category_structure()
                if structure:
                    for cat_name, cat_info in structure.items():
                        if isinstance(cat_info, dict):
                            file_count = cat_info.get("file_count", 0)
                            # 文件数 < 3 视为盲区
                            if file_count < 3:
                                gaps.append({
                                    "topic": cat_name,
                                    "coverage": min(file_count / 10, 1.0),
                                })

            if gaps:
                count = await sync_knowledge_gaps_to_ob(gaps, self.ob_client)
                if count:
                    log(f"[OB] 知识盲区同步完成: {count} 个领域已调整权重", "CONFIG")
        except ImportError:
            pass
        except Exception as e:
            log(f"[OB] 知识盲区同步失败: {e}", "DEBUG")

    async def _inject_curiosity_from_diary(self, diary_entry: dict):
        """日记生成后，提取知识生长点注入 OB 好奇心关键词"""
        if not self.ob_enabled or not self.ob_client:
            return
        ob_cfg = config.get("ob", {})
        if not ob_cfg.get("profile_sync_enabled", True):
            return

        try:
            from ob_bridge.config_bridge import inject_curiosity_from_diary

            ttl = ob_cfg.get("curiosity_keyword_ttl_hours", 24)
            injected = await inject_curiosity_from_diary(diary_entry, self.ob_client, ttl)
            if injected:
                log(f"[OB] 好奇心关键词已注入 ({len(injected)}个), TTL={ttl}h", "CONFIG")
        except ImportError:
            pass
        except Exception as e:
            log(f"[OB] 好奇心注入异常: {e}", "DEBUG")

    async def _apply_strategy_to_ob(self, evolution_result: dict):
        """进化后，解析新策略并应用到 OB"""
        if not self.ob_enabled or not self.ob_client:
            return

        try:
            from ob_bridge.config_bridge import extract_strategy_lines, parse_and_apply_strategy

            strategy_text = extract_strategy_lines(evolution_result)
            if strategy_text:
                result = await parse_and_apply_strategy(strategy_text, self.ob_client)
                applied = result.get("applied", [])
                if applied:
                    log(f"[OB] 策略同步: {len(applied)} 条已应用", "CONFIG")
        except ImportError:
            pass
        except Exception as e:
            log(f"[OB] 策略同步异常: {e}", "DEBUG")

    async def _apply_strategy_to_ob_v2(self, evolution_result: dict, ab_context: str = ""):
        """Phase 4: 进化策略 → OB 参数联动（含 ε 变化、兴趣偏移、AB上下文）"""
        if not self.ob_enabled or not self.ob_client:
            return

        try:
            from ob_bridge.config_bridge import apply_evolution_to_ob

            result = await apply_evolution_to_ob(
                evolution_result, self.ob_client, ab_context
            )
            applied = result.get("applied", [])
            skipped = result.get("skipped", [])
            if applied:
                log(f"[OB] 进化策略联动: {len(applied)} 条已应用 (+{len(skipped)} 条跳过)", "CONFIG")
        except ImportError:
            pass
        except Exception as e:
            log(f"[OB] 进化联动异常: {e}", "DEBUG")

    # ── Phase 4: 审计 & AB 对比 ──

    def _record_ob_audit(self, source: str, bvid: str = "", title: str = "",
                         score: float = 0.0, learned: bool = False,
                         skip_reason: str = "", topic: str = "",
                         up_name: str = "", duration: int = 0):
        """记录审计和AB对比数据"""
        # OB效能审计
        if self._ob_auditor:
            if score > 0:
                self._ob_auditor.record_decision(
                    source=source, bvid=bvid, title=title,
                    score=score, learned=learned,
                    topic=topic, skip_reason=skip_reason
                )

        # AB对比跟踪
        if self._ob_ab_tracker:
            group = "ob" if source in ("ob",) else "native"
            if score > 0:
                self._ob_ab_tracker.record_decision(
                    group=group, bvid=bvid, title=title,
                    score=score, learned=learned,
                    up_name=up_name, duration=duration, topic=topic
                )

    async def _maybe_audit_report(self):
        """定期输出审计报告"""
        if not self._ob_auditor or not self._ob_auditor.should_report():
            return

        try:
            report = self._ob_auditor.format_report()
            if report:
                log(report, "AUDIT")
            self._ob_auditor.mark_reported()
        except Exception:
            pass

    def _get_ob_audit_context(self) -> str:
        """获取审计 & AB 对比上下文（供进化系统使用）"""
        parts = []

        if self._ob_auditor:
            ctx = self._ob_auditor.get_evolution_context()
            if ctx:
                parts.append(f"[效能审计] {ctx}")

        if self._ob_ab_tracker:
            ctx = self._ob_ab_tracker.evolution_context()
            if ctx:
                parts.append(ctx)

        return "\n".join(parts) if parts else ""
