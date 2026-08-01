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
        self.last_auto_diary_at = datetime.now()
        self.agent_runner = AgentSkillRunner(brain=self)
        self.last_agent_run_at = datetime.now()
        self._recent_watched_titles = []  # 兴趣引擎AI建议追踪
        self._last_video_desc = ""  # 兴趣引擎desc参数传递
        self.session_start_time = datetime.now()
        self.videos_processed = 0
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

    async def _prefetch_recommendations(self):
        async with self._prefetch_lock:
            try:
                items = await self.bili.get_recommendations()
                if items and isinstance(items, list):
                    self._prefetched_recs = items
            except Exception:
                self._prefetched_recs = None

    async def _get_cached_recommendations(self):
        async with self._prefetch_lock:
            cached = self._prefetched_recs
            self._prefetched_recs = None
        if cached and isinstance(cached, list):
            log("📡 [预取命中] 使用后台预加载的推荐流", "SCAN")
            return cached
        return await self.bili.get_recommendations()
