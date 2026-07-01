"""brain/agent_brain.py — 核心大脑（AgentBrain 主调度器）"""
import asyncio
import json
import os
import random
import re
import time
import sys
import uuid
import shutil
from datetime import datetime, timedelta
from io import BytesIO

import httpx
import openai
import qrcode
from colorama import Fore, Style
from bilibili_api import Credential, user, homepage, comment, video, Danmaku, favorite_list
from bilibili_api.comment import CommentResourceType
from bilibili_api.video import Video
from bilibili_api.utils.network import Api

from core.config import *
from core.globals import *  # 运行时全局变量
from api.subtitles import SYSTEM_PROMPT_BRAIN, SYSTEM_PROMPT_VISION, SYSTEM_PROMPT_SUMMARY
from persona.managers import PersonaManager, MoodManager, UserProfileManager, BotDiaryManager, SelfEvolutionManager, PrivateContextDB
from security.guard import ReplySafetyGuard
from services.utils import InterestManager, BiliToolbox
from services.agent_service import AgentSkillRunner
from services.knowledge_tutor import KnowledgeTutor, scan_md_files, read_md_file, write_md_file
from utils.display import log, mask_secret
from utils.helpers import _mask_urls, sanitize_filename, ensure_ai_marker, unix_to_iso, parse_iso_datetime, human_reply_delay, _clean_ai_output, _load_json_file, _save_json_file, _safe_task_callback
from utils.lock import _acquire_bot_lock, _release_bot_lock
from api.throttle import _bili_throttle, _bili_trigger_cooldown
from api.client import BiliClient
from api.auth import login_bilibili, is_bili_logged_in, check_login_status, clear_login_info
from api.subtitles import fetch_bilibili_subtitles, _check_subtitle_mismatch
from brain.comment import CommentInteractionManager
from brain.private_msg import PrivateMessageManager
from knowledge.classifier import KnowledgeBaseClassifier
from knowledge.web_search import web_search, verify_knowledge_with_ai, backup_and_rewrite_knowledge
from knowledge.browse import count_knowledge_categories, browse_kb_structure, search_knowledge_content, cleanup_duplicates
from persona.psycho import PsychoProfile, RecommendationEngine, get_mode_emoji, get_mode_label
from utils.storage import get_backup_dir, sanitize_config_for_export

# Optional xingye_bot imports (may fail in minimal installs)
try:
    from xingye_bot.llm import ModelClient
    from xingye_bot.settings import load_settings as load_modular_settings
    from xingye_bot.state import BotState
    from xingye_bot.video_modes import VideoUnderstanding, normalize_mode
    from xingye_bot.kb_search import KBSearchEngine
except ImportError:
    ModelClient = None
    load_modular_settings = None
    BotState = None
    VideoUnderstanding = None
    normalize_mode = None
    KBSearchEngine = None

# Override log to use utils.display version (icon-based), not core.config's timestamp version
# (imported above from utils.display)


# Globals now provided by core/globals.py
# ==== AgentBrain class ====
class AgentBrain:
    def __init__(self):
        self.client = openai  # 直接使用全局 openai
        self.bili = BiliClient()
        self.energy = MAX_ENERGY
        self.coins_spent = 0
        self.memory = self._load_memory()
        self.last_energy_recovery = datetime.now()
        
        self.classifier = KnowledgeBaseClassifier()
        self.interest_mgr = InterestManager()  # 兴趣管理器
        self.comment_mgr = None  # 评论管理器，登录后初始化
        self.private_message_mgr = None
        self.last_comment_check = None
        self.last_private_message_check = None
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
        self.last_agent_run_at = datetime.now()  # [FIX] 从启动开始算冷却，避免启动瞬间触发
        self.session_start_time = datetime.now()  # 本次会话开始时间（用于max_duration_minutes）
        self.videos_processed = 0  # 本次会话已处理的视频数（用于max_videos）
        self._last_interesting_topic = ""  # [FIX] 最近感兴趣的上下文，供Agent深度搜索使用
        self._last_video_desc = ""  # [DESC] 最近获取的视频简介，供 learn_from_video 使用
        self._last_reclassify_at = datetime.min  # [KB] 上次自动重分类时间
        self._prefetched_recs = None  # [SPEED] 后台预取推荐流缓存
        self._prefetch_lock = asyncio.Lock()  # [SPEED] 预取并发锁
        self.runtime_state = _load_json_file(RUNTIME_STATE_FILE, {"last_seen_at": "", "current_start_at": "", "current_heartbeat_at": ""})
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

        # 懒初始化向量检索引擎
        self.kb_search = None
        if KBSearchEngine and ModelClient and load_modular_settings and BotState:
            try:
                modular_settings = load_modular_settings()
                self.kb_search = KBSearchEngine(ModelClient(modular_settings, BotState()))
            except Exception as e:
                log(f"向量检索引擎初始化失败: {e}", "WARN")


        self.cookies = None
        self.credential = None
        self._ai_errors_consecutive = 0  # 连续AI错误计数，用于熔断
        self._preferred_ai_method = None  # 当前生效的AI调用后端（None=自动探测，"openai"/"httpx"）
        self._ai_degraded_until = 0.0  # AI降级截止时间戳：在此之前跳过全部AI调用（封面分析/兴趣判断），纯关键词模式
        self._ai_primary_failing = 0  # 主API连续失败计数（触发备用provider切换）
        self._ai_using_fallback_provider = False  # 当前是否已切换到备用provider
        self._ai_fallback_recheck_at = 0.0  # 何时重新检查主API是否恢复

        # 🔁 回顾复习追踪
        self.history_videos = self._load_history_videos()
        self.last_revisit_at = datetime.min  # 上次复习时间
        self._active_chat_count = 0  # 本次会话主动聊天计数
        self._last_active_chat_at = datetime.min  # 上次主动聊天时间
        
        # 🧭 好奇心深度搜索追踪
        self._last_curiosity_dive_at = datetime.min
        self._curiosity_dive_count_today = 0
        self._curiosity_dive_date = ""

        # [*] UP主关注追踪
        self.daily_follows = 0
        self.daily_follows_date = ""
        self.last_follow_at = datetime.min
        self.last_up_browse_at = datetime.min
        
        # [MSG] 弹幕互动追踪
        self.daily_danmaku_likes = 0
        self.daily_danmaku_likes_date = ""
        self.daily_danmaku_sent = 0
        self.daily_danmaku_sent_date = ""
        self._last_danmaku_videos = {}  # bvid -> danmaku_list 缓存
        self._last_danmaku_cids = {}   # bvid -> cid 缓存
        
        # [PSYCHO] 心理画像引擎（登录后初始化，这里先占位）
        self.psycho_profile = None
        self.recommend_engine = None
        self._psycho_profile_analysis_count = 0
        self._knowledge_review_countdown = KNOWLEDGE_REVIEW_INTERVAL  # 知识库定期审查倒计时
        self._last_recommend_mode = None

    # ── [SPEED] 推荐流后台预取 ───────────────────────────────────────
    async def _prefetch_recommendations(self):
        """后台预取推荐流：在当前视频处理期间异步拉取下一批推荐。
        利用视频理解/AI分析的等待时间并行获取，消除下一个循环的API等待。
        """
        async with self._prefetch_lock:
            try:
                items = await self.bili.get_recommendations()
                if items and isinstance(items, list):
                    self._prefetched_recs = items
            except Exception:
                self._prefetched_recs = None  # 失败不阻塞，下次主循环自己获取

    async def _get_cached_recommendations(self):
        """优先返回预取的推荐流，无缓存时实时调用API。"""
        async with self._prefetch_lock:
            cached = self._prefetched_recs
            self._prefetched_recs = None  # 消费后清空
        if cached and isinstance(cached, list):
            log("📡 [预取命中] 使用后台预加载的推荐流", "SCAN")
            return cached
        return await self.bili.get_recommendations()

    # ── AI多后端透明切换 ───────────────────────────────────────────────
    def _get_ai_backends(self):
        """返回按优先级排列的AI调用后端列表（当前优选排第一）。"""
        all_backends = ["openai", "httpx"]
        if self._preferred_ai_method and self._preferred_ai_method in all_backends:
            return [self._preferred_ai_method] + [m for m in all_backends if m != self._preferred_ai_method]
        return all_backends

    def _is_ai_degraded(self):
        """检查 AI 是否处于降级模式（连续失败后的冷却期，跳过所有 AI 调用）。"""
        if self._ai_degraded_until and time.time() < self._ai_degraded_until:
            remaining = int(self._ai_degraded_until - time.time())
            if not getattr(self, '_ai_degraded_logged', False):
                log(f"🔻 AI处于降级模式（跳过封面分析/兴趣判断，纯关键词匹配），剩余 {remaining}s", "WARN")
                self._ai_degraded_logged = True
            return True
        if self._ai_degraded_until and time.time() >= self._ai_degraded_until:
            # 降级到期，清除标记，重新尝试 AI
            self._ai_degraded_until = 0.0
            self._ai_degraded_logged = False
            log("🔺 AI降级模式已解除，恢复AI调用", "INFO")
        return False

    async def _call_ai_via_openai(self, **kwargs):
        """通过 openai 库调用（同步阻塞，兼容现有逻辑）。"""
        # 兼容新版 openai：request_timeout → timeout
        if "request_timeout" in kwargs:
            kwargs["timeout"] = kwargs.pop("request_timeout")
        else:
            kwargs.setdefault("timeout", 120)  # 默认120秒超时，防止无限阻塞
        return openai.ChatCompletion.create(**kwargs)

    async def _call_ai_via_httpx(self, **kwargs):
        """通过 httpx 直接 POST 到 OpenAI 兼容端点（备选方案）。
        
        支持 _override_api_key / _override_base_url 覆盖，用于：
        - 视觉模型独立 API
        - 备用provider（chatanywhere等）跨提供商降级
        """
        model = kwargs.get("model", MODEL_BRAIN)
        messages = kwargs.get("messages", [])
        timeout = kwargs.get("request_timeout", 120)
        extra_body = {}
        if "max_tokens" in kwargs:
            extra_body["max_tokens"] = kwargs["max_tokens"]
        
        # 🔑 动态 API 凭据覆盖（优先级：_override > _vision > 统一配置）
        api_key = (kwargs.pop("_override_api_key", None) 
                   or kwargs.pop("_vision_api_key", None) 
                   or UNIFIED_API_KEY)
        base_url = (kwargs.pop("_override_base_url", None) 
                    or kwargs.pop("_vision_base_url", None) 
                    or UNIFIED_BASE_URL)

        # 🔧 防御：base_url 为空或缺少协议时，回退到全局配置或报错
        if not base_url or "://" not in str(base_url):
            # 尝试从 config 实时读取（绕过模块级缓存的旧值）
            from core.config import config as _cfg
            _live_url = _cfg.get("api", {}).get("unified_base_url", "")
            if _live_url and "://" in str(_live_url):
                base_url = _live_url
            else:
                raise RuntimeError(
                    f"API地址无效: '{base_url}'，请在配置菜单中设置有效的API地址（如 http://127.0.0.1:18767/v1）"
                )

        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {"model": model, "messages": messages}
        if extra_body:
            payload.update(extra_body)

        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # 模拟 openai 库的返回结构，使调用方 .choices[0].message.content 一致
        class _Msg:
            def __init__(self, d): self.content = d.get("content", "")
        class _Choice:
            def __init__(self, d): self.message = _Msg(d.get("message", {}))
        class _Resp:
            def __init__(self, d): self.choices = [_Choice(c) for c in d.get("choices", [])]
        return _Resp(data)

    async def _call_ai_with_retry(self, **kwargs):
        """多级降级AI调用：后端切换 → 模型降级 → 备用提供商。
        
        三级降级策略：
        1️⃣ 同一API提供商内切换后端（openai↔httpx）
        2️⃣ 同一API提供商内切换备选模型（fallback_models）
        3️⃣ 切换到备用API提供商（如 chatanywhere 免费API）
        
        熔断+降级：连续失败>5次熔断60s，熔断后仍失败→5分钟降级。
        视觉模型自动使用独立配置，备用提供商使用 chatanywhere 等。
        """
        max_retries = 11  # 10次重试 + 1次最终尝试
        last_error = None
        _was_cooled_down = False
        
        # 🔻 降级模式检查
        if self._is_ai_degraded():
            raise RuntimeError("AI处于降级模式，跳过调用")
        
        # 🔑 检测视觉模型（含备用模型）
        _is_vision = (
            kwargs.get("model") == MODEL_VISION
            or kwargs.get("model") == FALLBACK_MODEL_VISION
            or "vision" in str(kwargs.get("model", "")).lower()
        )
        
        # 🔑 构建模型尝试列表（主模型 + 备用模型）
        _primary_model = kwargs.get("model", MODEL_BRAIN)
        _fallback_model = FALLBACK_MODEL_VISION if _is_vision else FALLBACK_MODEL_CHAT
        _models_to_try = [_primary_model]
        if _fallback_model and _fallback_model != _primary_model:
            _models_to_try.append(_fallback_model)
        # [REFRESH] 备用模型重试次数（用尽后回退到默认主模型）
        _fallback_retries = 10  # 备用模型最多10次重试
        _primary_retries = 11   # 主模型11次重试
        
        # 🔑 构建provider尝试列表（主provider + 备用provider）
        _providers = [{
            "name": "primary",
            "api_key": (VISION_API_KEY if _is_vision and VISION_API_KEY else UNIFIED_API_KEY),
            "base_url": (VISION_BASE_URL if _is_vision and VISION_BASE_URL else UNIFIED_BASE_URL),
        }]
        
        # 备用provider（如chatanywhere）
        if (FALLBACK_PROVIDER_ENABLED 
            and FALLBACK_PROVIDER_API_KEY 
            and FALLBACK_PROVIDER_BASE_URL):
            fb_model_key = "vision" if _is_vision else "chat"
            fb_model = FALLBACK_PROVIDER_MODELS.get(fb_model_key, "gpt-3.5-turbo")
            _providers.append({
                "name": FALLBACK_PROVIDER_NAME,
                "api_key": FALLBACK_PROVIDER_API_KEY,
                "base_url": FALLBACK_PROVIDER_BASE_URL,
                "models": [fb_model],
                "is_fallback": True,
            })
        
        # [WARN] API Key 检查
        if not _providers[0]["api_key"]:
            log("[WARN] 未配置 API Key，跳过 AI 调用（请在配置菜单设置 unified_api_key）", "WARN")
            raise RuntimeError("API Key 未配置，无法调用 AI")
        
        # [REFRESH] 如果之前已切换到备用provider，先检查主provider是否恢复
        if self._ai_using_fallback_provider and self._ai_fallback_recheck_at:
            if time.time() >= self._ai_fallback_recheck_at:
                # 重新排序：先试主provider
                self._ai_using_fallback_provider = False
                log("🔍 尝试恢复主API提供商...", "INFO")
            else:
                # 还在等待期，跳过主provider
                _providers = [p for p in _providers if p.get("is_fallback")]
                if not _providers:
                    raise RuntimeError("主API不可用且无可用备用提供商")
        
        # 视觉模型：httpx直连（openai后端使用全局配置无法切换provider）
        if _is_vision:
            backends = ["httpx"]
        else:
            backends = self._get_ai_backends()
        
        # 熔断检查
        if self._ai_errors_consecutive >= 5:
            cooldown = 60
            log(f"[WARN] AI服务器连续{self._ai_errors_consecutive}次失败，进入{cooldown}秒熔断冷却...", "WARN")
            await asyncio.sleep(cooldown)
            self._ai_errors_consecutive = 0
            _was_cooled_down = True
        
        # [TARGET] 三层嵌套降级：provider → model → backend → retry
        for pi, provider in enumerate(_providers):
            _is_fallback_provider = provider.get("is_fallback", False)
            _prov_models = provider.get("models", _models_to_try)
            _prov_api_key = provider["api_key"]
            _prov_base_url = provider["base_url"]
            
            if _is_fallback_provider and not self._ai_using_fallback_provider:
                log(f"[REFRESH] 主API不可用，切换到备用提供商: {provider['name']}", "WARN")
                self._ai_using_fallback_provider = True
            
            for mi, model in enumerate(_prov_models):
                if mi > 0:
                    log(f"[REFRESH] 模型降级: {_prov_models[0]} → {model}", "WARN")
                
                kwargs["model"] = model
                if _is_fallback_provider:
                    kwargs["_override_api_key"] = _prov_api_key
                    kwargs["_override_base_url"] = _prov_base_url
                elif _is_vision:
                    kwargs["_vision_api_key"] = _prov_api_key
                    kwargs["_vision_base_url"] = _prov_base_url
                
                # [REFRESH] 备用模型(非主provider)用_fallback_retries次；主模型用_primary_retries
                _cur_retries = _fallback_retries if (_is_fallback_provider or mi > 0) else _primary_retries
                
                for attempt in range(_cur_retries):
                    for bi, backend in enumerate(backends):
                        is_last_backend = (bi == len(backends) - 1)
                        try:
                            if backend == "openai" and not _is_fallback_provider:
                                resp = await self._call_ai_via_openai(**kwargs)
                            else:
                                resp = await self._call_ai_via_httpx(**kwargs)
                            
                            # [OK] 成功
                            self._ai_errors_consecutive = 0
                            self._ai_primary_failing = 0
                            if self._preferred_ai_method != backend:
                                self._preferred_ai_method = backend
                            if self._ai_degraded_until:
                                self._ai_degraded_until = 0.0
                                self._ai_degraded_logged = False
                                log("🔺 AI调用恢复，降级模式已解除", "INFO")
                            if self._ai_using_fallback_provider:
                                log(f"[WARN] 当前仍使用备用提供商({provider['name']})，将在稍后重试主API", "INFO")
                                self._ai_fallback_recheck_at = time.time() + 300
                            return resp
                        except Exception as e:
                            if is_last_backend:
                                last_error = e
                                err_msg = str(e).lower()
                                # [FIX] 永久性失败：模型不存在/无可用渠道 → 立刻换模型，不重试
                                is_model_gone = any(kw in err_msg for kw in
                                    ['model_not_found', '无可用渠道', 'model is not found', 'unsupported model'])
                                is_overload = any(kw in err_msg for kw in 
                                    ['overload', 'not ready', 'too many', 'rate limit', '429', '503', '502', '522', 'timeout'])
                                if is_model_gone:
                                    log(f"[SKIP] 模型不可用({err_msg[:120]})，跳过重试直接切换", "WARN")
                                    break  # 跳出重试循环 → 尝试下一个模型
                                if attempt < _cur_retries - 1:
                                    wait = (attempt + 1) * 3.0
                                    short_err = _mask_urls(str(e)[:120]) or type(e).__name__
                                    if is_overload:
                                        log(f"⏳ AI服务器繁忙{short_err}，第{attempt+1}次重试，等待{wait:.0f}秒...", "WARN")
                                    else:
                                        log(f"⏳ AI调用异常{short_err}，第{attempt+1}次重试，等待{wait:.0f}秒...", "WARN")
                                    await asyncio.sleep(wait)
                                    break  # 跳出后端循环，进入下一次重试
                                else:
                                    # 最后一次重试仍失败 → 尝试下一个模型/provider
                                    break  # 跳出重试循环
                            continue  # 非最后后端：静默切换
                    else:
                        # retry循环正常结束（break未执行）→ 所有重试耗尽但没更多后端
                        pass
                    # 重试耗尽 → 继续下一个模型
                    continue
                # [REFRESH] 备用模型重试耗尽 → 回退到默认主模型
                if mi > 0 and not _is_fallback_provider:
                    log(f"[REFRESH] 备用模型{model}重试耗尽，回退到默认模型: {_primary_model}", "WARN")
                    kwargs["model"] = _primary_model
                    # 用主模型再试一次（最后一次机会）
                    for attempt in range(1):  # 只试1次
                        for bi, backend in enumerate(backends):
                            is_last_backend = (bi == len(backends) - 1)
                            try:
                                if backend == "openai":
                                    resp = await self._call_ai_via_openai(**kwargs)
                                else:
                                    resp = await self._call_ai_via_httpx(**kwargs)
                                self._ai_errors_consecutive = 0
                                self._ai_primary_failing = 0
                                if self._preferred_ai_method != backend:
                                    self._preferred_ai_method = backend
                                if self._ai_degraded_until:
                                    self._ai_degraded_until = 0.0
                                    self._ai_degraded_logged = False
                                    log("🔺 AI调用恢复，降级模式已解除", "INFO")
                                log(f"[OK] 回退到默认模型{_primary_model}成功", "INFO")
                                return resp
                            except Exception as e2:
                                if is_last_backend:
                                    last_error = e2
                                continue
                
                # 模型耗尽 → 继续下一个provider
                continue
        
        # 🚨 全部provider+模型+重试都失败
        self._ai_errors_consecutive += 1
        self._ai_primary_failing += 1
        
        # 主API连续失败3次 → 标记切换到备用provider
        if self._ai_primary_failing >= 3 and not self._ai_using_fallback_provider:
            if FALLBACK_PROVIDER_ENABLED and FALLBACK_PROVIDER_API_KEY:
                self._ai_using_fallback_provider = True
                self._ai_fallback_recheck_at = time.time() + 600
                log(f"🔻 主API连续失败{self._ai_primary_failing}次，将在下次调用切换到备用提供商", "WARN")
        
        # 熔断冷却后首次调用仍失败 → 5分钟降级
        if _was_cooled_down:
            degrade_sec = 300
            self._ai_degraded_until = time.time() + degrade_sec
            self._ai_degraded_logged = False
            log(f"🔻 熔断恢复后仍失败，进入{degrade_sec}s AI降级模式（跳过封面分析/兴趣判断）", "WARN")
        
        raise last_error or RuntimeError("AI调用全部失败，原因未知")

    # [PSYCHO] 心理画像引擎专用AI调用器（桥接到主AI多级降级系统）
    async def _psycho_ai_caller(self, **kwargs):
        """心理画像引擎的AI调用桥接，复用主Agent的多级降级/provider切换"""
        return await self._call_ai_with_retry(**kwargs)

    def update_runtime_clock(self, starting=False):
        now_text = datetime.now().isoformat(timespec="seconds")
        state = _load_json_file(RUNTIME_STATE_FILE, {})
        if starting:
            state["previous_seen_at"] = self.previous_seen_at
            state["current_start_at"] = now_text
        state["current_heartbeat_at"] = now_text
        state["last_seen_at"] = now_text
        _save_json_file(RUNTIME_STATE_FILE, state)
        self.runtime_state = state
        return state

    def _load_memory(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 迁移旧格式：known_ups 从 list[str] → dict{name: {uid, favorited, followed}}
                if isinstance(data.get("known_ups"), list):
                    old_list = data["known_ups"]
                    new_dict = {}
                    for item in old_list:
                        if isinstance(item, str):
                            new_dict[item] = {"uid": None, "favorited": False, "followed": False}
                        elif isinstance(item, dict) and "name" in item:
                            new_dict[item["name"]] = {
                                "uid": item.get("uid"),
                                "favorited": item.get("favorited", False),
                                "followed": item.get("followed", False)
                            }
                    data["known_ups"] = new_dict
                    self._save_memory_to_disk(data)
                # 补全缺失的 followed 字段
                if isinstance(data.get("known_ups"), dict):
                    for k, v in data["known_ups"].items():
                        if isinstance(v, dict) and "followed" not in v:
                            v["followed"] = False
                return data
            except (OSError, json.JSONDecodeError) as e:
                log(f'加载JSON文件失败: {e}', 'DEBUG')
        return {"known_ups": {}, "history": []}
    
    def _save_memory_to_disk(self, data=None):
        if data is None:
            data = self.memory
        try:
            tmp = MEMORY_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, MEMORY_FILE)
        except OSError as e:
            log(f'文件操作失败: {e}', 'DEBUG')

    def _save_memory(self):
        self._save_memory_to_disk(self.memory)

    def record_up_impression(self, up_name, uid, score):
        """记录对UP主的一次观看印象（积累正面印象用于关注决策）。
        
        关注理念：不因一次偶然高分就关注，需要多次正面印象积累。
        每次观看都会更新 views / total_score / avg_score。
        """
        ups = self.memory.setdefault("known_ups", {})
        if up_name not in ups:
            ups[up_name] = {
                "uid": uid,
                "favorited": False,
                "followed": False,
                "views": 1,
                "total_score": score,
                "avg_score": round(score, 2),
                "first_seen": datetime.now().isoformat(),
                "last_viewed_at": datetime.now().isoformat()
            }
        else:
            entry = ups[up_name]
            entry["views"] = entry.get("views", 0) + 1
            entry["total_score"] = entry.get("total_score", 0) + score
            entry["avg_score"] = round(entry["total_score"] / entry["views"], 2)
            entry["last_viewed_at"] = datetime.now().isoformat()
            if uid and not entry.get("uid"):
                entry["uid"] = uid
        self._save_memory()

    def remember_up(self, up_name, uid=None):
        """记住UP主，可选记录UID。保留已有字段（followed/favorited/views等）。"""
        ups = self.memory.setdefault("known_ups", {})
        if up_name not in ups:
            ups[up_name] = {"uid": uid, "favorited": False, "followed": False, "first_seen": datetime.now().isoformat()}
            self._save_memory()
            log(f"已记住UP主: {up_name}" + (f" (UID:{uid})" if uid else ""), "MEM")
        elif uid and not ups[up_name].get("uid"):
            ups[up_name]["uid"] = uid
            ups[up_name].setdefault("followed", False)
            ups[up_name]["updated_at"] = datetime.now().isoformat()
            self._save_memory()
            log(f"补充UP主UID: {up_name} → {uid}", "MEM")

    def get_known_up_names(self):
        """返回已知UP主名称列表（用于prompt等）。"""
        return list(self.memory.get("known_ups", {}).keys())

    def get_up_uid(self, up_name):
        """从记忆中获取UP主的UID。"""
        return self.memory.get("known_ups", {}).get(up_name, {}).get("uid")

    def set_up_uid(self, up_name, uid):
        """设置/更新UP主的UID。保留已有followed/favorited状态。"""
        ups = self.memory.setdefault("known_ups", {})
        if up_name not in ups:
            ups[up_name] = {"uid": uid, "favorited": False, "followed": False, "first_seen": datetime.now().isoformat()}
        else:
            ups[up_name]["uid"] = uid
            ups[up_name].setdefault("followed", False)
            ups[up_name]["updated_at"] = datetime.now().isoformat()
        self._save_memory()
        log(f"UP主 {up_name} UID已更新: {uid}", "MEM")

    # ── [*] 喜欢的UP主管理 ──
    def favorite_up(self, up_name, uid=None):
        """将UP主标记为喜欢（AI特别关注）。"""
        ups = self.memory.setdefault("known_ups", {})
        if up_name not in ups:
            ups[up_name] = {"uid": uid, "favorited": True, "followed": False, "first_seen": datetime.now().isoformat()}
        else:
            ups[up_name]["favorited"] = True
            ups[up_name].setdefault("followed", False)
            if uid and not ups[up_name].get("uid"):
                ups[up_name]["uid"] = uid
        ups[up_name]["favorited_at"] = datetime.now().isoformat()
        self._save_memory()
        # 同时更新全局配置中的 favorite_up_uid_list
        global UP_FOLLOW_FAVORITE_UID_LIST, config
        if uid and uid not in UP_FOLLOW_FAVORITE_UID_LIST:
            UP_FOLLOW_FAVORITE_UID_LIST.append(uid)
            config.setdefault("up_follow", {})["favorite_up_uid_list"] = UP_FOLLOW_FAVORITE_UID_LIST
            save_config(config)
        log(f"[STAR] 已标记为喜欢的UP主: {up_name}" + (f" (UID:{uid})" if uid else ""), "FAVORITE")

    def unfavorite_up(self, up_name):
        """取消喜欢UP主。"""
        ups = self.memory.get("known_ups", {})
        if up_name in ups:
            ups[up_name]["favorited"] = False
            ups[up_name]["unfavorited_at"] = datetime.now().isoformat()
            self._save_memory()
        # 从配置列表中移除
        global UP_FOLLOW_FAVORITE_UID_LIST, config
        uid = ups.get(up_name, {}).get("uid")
        if uid and uid in UP_FOLLOW_FAVORITE_UID_LIST:
            UP_FOLLOW_FAVORITE_UID_LIST.remove(uid)
            config.setdefault("up_follow", {})["favorite_up_uid_list"] = UP_FOLLOW_FAVORITE_UID_LIST
            save_config(config)
        log(f"💔 已取消喜欢UP主: {up_name}", "FAVORITE")

    def get_favorite_ups(self):
        """获取所有喜欢的UP主列表 [{name, uid, ...}]。"""
        ups = self.memory.get("known_ups", {})
        result = []
        for name, info in ups.items():
            if info.get("favorited"):
                result.append({"name": name, "uid": info.get("uid"), **info})
        # 也加入配置中显式列出但尚未在记忆中的
        global UP_FOLLOW_FAVORITE_UID_LIST
        return result

    def is_favorite_up(self, up_name):
        """检查UP主是否为喜欢的。"""
        return self.memory.get("known_ups", {}).get(up_name, {}).get("favorited", False)

    async def resolve_up_uid(self, up_name):
        """通过B站搜索API解析UP主名称→UID。"""
        # 先从记忆查找
        uid = self.get_up_uid(up_name)
        if uid:
            return uid
        # 从user_profile查找
        profile = self.user_profile_mgr.get_profile(f"up::{up_name}")
        if profile and profile.get("uid"):
            uid = int(profile["uid"])
            self.set_up_uid(up_name, uid)
            return uid
        # 调用搜索API
        try:
            await _bili_throttle("搜索UP主")
            from bilibili_api import search as bili_search
            data = await bili_search.search_by_type(
                up_name,
                search_type=bili_search.SearchObjectType.USER,
                page=1
            )
            items = data.get("result") or []
            if items:
                best = items[0]
                uid = best.get("mid") or best.get("uid")
                if uid:
                    uid = int(uid)
                    self.set_up_uid(up_name, uid)
                    log(f"🔍 搜索解析 UP主: {up_name} → UID: {uid}", "RESOLVE")
                    return uid
        except Exception as e:
            log(f"搜索UP主 {up_name} 失败: {e}", "WARN")
        return None

    # ── 🔁 互动视频历史（储存点赞/收藏的视频，用于回顾复习） ──
    def _load_history_videos(self):
        if os.path.exists(HISTORY_VIDEOS_FILE):
            try:
                with open(HISTORY_VIDEOS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data.setdefault("videos", [])
                    return data
            except (OSError, json.JSONDecodeError) as e:
                log(f'加载JSON文件失败: {e}', 'DEBUG')
        return {"videos": []}

    def _save_history_videos(self):
        try:
            tmp = HISTORY_VIDEOS_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.history_videos, f, ensure_ascii=False, indent=2)
            os.replace(tmp, HISTORY_VIDEOS_FILE)
        except OSError as e:
            log(f'文件操作失败: {e}', 'DEBUG')

    def add_history_video(self, bvid, title, up, aid, action, score=0):
        """记录互动过的视频（用于回顾复习）。action: like/fav/coin。
        score: AI评分，用于复习时过滤低质量视频。
        """
        # 评分门槛：低于 REVISIT_MIN_SCORE 的视频不值得复习，直接不入池
        if score < REVISIT_MIN_SCORE:
            return
        videos = self.history_videos.get("videos", [])
        # 去重：按 bvid+action 防重复
        key = f"{bvid}_{action}"
        if any(f"{v.get('bvid')}_{v.get('action')}" == key for v in videos):
            return
        entry = {
            "bvid": bvid,
            "title": title,
            "up": up,
            "aid": aid,
            "action": action,
            "score": score,
            "time": datetime.now().isoformat(),
            "revisit_count": 0,  # 被回顾次数
            "last_revisit": None
        }
        videos.append(entry)
        # 最多保留 200 条
        self.history_videos["videos"] = videos[-200:]
        self._save_history_videos()

    def get_revisit_candidate(self):
        """获取一个回顾复习候选视频。
        
        策略：
        - 只复习评分 >= REVISIT_MIN_SCORE 的视频（好视频才值得复习）
        - 最多复习 REVISIT_MAX_PER_VIDEO 次（默认2次），超过的不再选
        - 评分越高的视频权重越大（好视频更值得反复看）
        - 优先从未复习过的（last_revisit=None）
        - 已复习过的按复习次数加权：复习次数越多，被选中概率越低
        - 单视频复习冷却：距上次复习不足 REVISIT_PER_VIDEO_COOLDOWN_MINUTES 分钟的跳过
        """
        videos = self.history_videos.get("videos", [])
        if not videos:
            return None
        
        max_per_video = REVISIT_MAX_PER_VIDEO
        per_video_cooldown = REVISIT_PER_VIDEO_COOLDOWN_MINUTES
        min_score = REVISIT_MIN_SCORE
        
        # 过滤1：评分低于门槛的剔除（好视频才值得复习）
        eligible = [v for v in videos if v.get("score", 0) >= min_score]
        if not eligible:
            return None
        
        # 过滤2：超过复习上限的剔除
        eligible = [v for v in eligible if v.get("revisit_count", 0) < max_per_video]
        if not eligible:
            return None
        
        # 过滤3：单视频冷却未过的剔除
        now = datetime.now()
        cooldown_ok = []
        for v in eligible:
            last = v.get("last_revisit")
            if last is None:
                cooldown_ok.append(v)
            else:
                try:
                    last_dt = datetime.fromisoformat(last)
                    if (now - last_dt).total_seconds() / 60 >= per_video_cooldown:
                        cooldown_ok.append(v)
                except (ValueError, TypeError):
                    cooldown_ok.append(v)
        
        if not cooldown_ok:
            return None
        
        # 分组：从未复习过的优先（70%概率）
        never = [v for v in cooldown_ok if v.get("last_revisit") is None]
        reviewed = [v for v in cooldown_ok if v.get("last_revisit") is not None]
        
        if never and random.random() < 0.7:
            # 从未复习的中，高分优先
            return max(never, key=lambda v: v.get("score", 0))
        
        # 加权随机：综合考虑评分和复习次数
        # 权重公式: w = score * (1 / (1 + revisit_count))
        #   → 高分视频权重高，复习次数多的权重低
        weights = [v.get("score", 0) * (1.0 / (1.0 + v.get("revisit_count", 0))) for v in cooldown_ok]
        total_w = sum(weights)
        if total_w <= 0:
            return None
        # 轮盘赌选择
        r = random.random() * total_w
        cum = 0
        for i, w in enumerate(weights):
            cum += w
            if r <= cum:
                return cooldown_ok[i]
        return cooldown_ok[-1]

    def mark_revisited(self, bvid):
        """标记某个视频已被回顾。"""
        for v in self.history_videos.get("videos", []):
            if v.get("bvid") == bvid:
                v["revisit_count"] = v.get("revisit_count", 0) + 1
                v["last_revisit"] = datetime.now().isoformat()
                self._save_history_videos()
                return

    def build_dynamic_brain_prompt(self, up_name):
        persona_block = self.persona_mgr.build_prompt_block()
        mood_block = self.mood_mgr.build_prompt_block()
        up_profile = self.user_profile_mgr.build_prompt_block(f"up::{up_name}", up_name)
        return (
            SYSTEM_PROMPT_BRAIN.replace("{bot_name}", get_bot_name()).replace("{memory_ups}", str(self.get_known_up_names()))
            + "\n\n"
            + persona_block
            + "\n"
            + mood_block
            + "\n"
            + up_profile
            + "\n【额外要求】结合当前人格、心情和对该UP主的印象做决策，不要机械重复。"
        )

    def write_journal(self, title, up, score, thought, action_str, url):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"## {timestamp}\n- **视频**: {title} [链接]({url}) (@{up})\n- **评分**: {score}\n- **想法**: {thought}\n- **操作**: {action_str}\n---\n"
        try:
            with open(JOURNAL_FILE, 'a', encoding='utf-8') as f:
                f.write(entry)
            log("日常日记已记录", "NOTE")
        except OSError as e:
            log(f'文件操作失败: {e}', 'DEBUG')

    def record_session_event(self, event_type, **payload):
        item = {
            "time": datetime.now().isoformat(),
            "type": event_type,
            **payload
        }
        self.session_events.append(item)
        self.session_events = self.session_events[-100:]
        self.processed_event_count += 1
        return item

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
        """[FIX] 异步执行Agent目标（fire-and-forget），不阻塞主循环"""
        if not AGENT_ENABLED:
            return
        try:
            log(f"🤖 Agent后台探索: {goal[:60]}...", "CONFIG")
            # [FIX] 总超时180秒，防止Agent探索卡住主循环
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
        """优选刚看过的感兴趣视频主题，没有则从兴趣/知识库/当前记忆中选择"""
        # [FIX] 优先用刚看过的感兴趣视频作为主题（用户真正想要的行为）
        if getattr(self, "_last_interesting_topic", ""):
            recent = self._last_interesting_topic
            self._last_interesting_topic = ""  # 用后清空，避免重复
            return recent
        # 后备：从兴趣/知识库/当前记忆中选择
        topics = []
        # 从兴趣中选
        if hasattr(self, "interest_mgr") and self.interest_mgr:
            interests = self.interest_mgr.get_interests()[:10]
            for i in interests:
                if isinstance(i, dict):
                    name = i.get("name") or i.get("keyword") or str(i)
                else:
                    name = str(i)
                if name:
                    topics.append(f"深入了解{name}")
        # 从知识库分类中选
        if os.path.exists(KNOWLEDGE_BASE_DIR):
            try:
                for d in os.listdir(KNOWLEDGE_BASE_DIR):
                    dpath = os.path.join(KNOWLEDGE_BASE_DIR, d)
                    if os.path.isdir(dpath) and d not in ("未分类",):
                        topics.append(f"继续学习{d}领域的新知识")
            except OSError as e:
                log(f'文件操作失败: {e}', 'DEBUG')
        # 从当前记忆UP主中选
        if self.memory.get("known_ups"):
            up = random.choice(list(self.memory["known_ups"].keys())[:5])
            topics.append(f"搜索了解UP主{up}的视频风格和代表作")
        if not topics:
            return None
        return random.choice(topics)

    def write_learning_log(self, category, title, file_path):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(os.path.dirname(LEARNING_LOG_FILE), exist_ok=True)
        relative_path = os.path.relpath(file_path, KNOWLEDGE_BASE_DIR)
        entry = f"- **{timestamp}** | `分类:{category}` | `{title}` | [查看笔记]({relative_path.replace(os.sep, '/')})\n"
        try:
            with open(LEARNING_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(entry)
            log("学习日志已记录", "LEARN")
        except Exception as e:
            log(f"记录学习日志失败: {e}", "ERROR")

    async def learn_from_video(self, bvid, title, up, url, subtitle_text, topic_suggestion, video_desc="", score=None, comment_summary=None):
        # 🔒 二次守卫：分数不达标直接拒绝归档
        if score is not None and score < LEARN_MIN_SCORE:
            log(f"📭 learn_from_video 拒绝低分归档: score={score:.1f}<{LEARN_MIN_SCORE} | 《{title}》", "LEARN")
            return False
        # 🔒 内容守卫：可学文本过短拒绝归档
        if not subtitle_text or len(subtitle_text.strip()) < 100:
            log(f"📭 learn_from_video 拒绝内容不足归档: {len(subtitle_text) if subtitle_text else 0}字<100 | 《{title}》", "LEARN")
            return False
        # 🔒 AI语义守卫：字幕内容是否与标题真正匹配？（归档前最后一道防线）
        if AI_SUBTITLE_VERIFY_ENABLED and title and subtitle_text:
            is_match, ai_conf, ai_reason = await self._ai_verify_subtitle_content(
                title, subtitle_text, video_desc
            )
            if not is_match and ai_conf >= 0.7:
                log(f"📭 learn_from_video 拒绝归档（AI语义不匹配）: conf={ai_conf:.2f} | {ai_reason} | 《{title}》", "LEARN")
                return False
            elif not is_match:
                log(f"⚠️ AI语义验证低置信不匹配(conf={ai_conf:.2f})，仍放行归档: {ai_reason} | 《{title}》", "WARN")
            else:
                log(f"✅ AI语义验证通过: conf={ai_conf:.2f} | {ai_reason} | 《{title}》", "LEARN")
        log(f"触发学习机制！主题建议: '{topic_suggestion}'", "LEARN")

        try:
            # 简介也参与分类（含项目链接等关键信息）
            classify_text = subtitle_text
            if video_desc:
                classify_text = f"[视频简介] {video_desc[:500]}\n\n[视频内容] {subtitle_text}"
            category_path = self.classifier.classify_content(title, classify_text, bvid, topic_suggestion)
            log(f"智能分类结果: '{category_path}'", "KB")
            
            category_folder = self.classifier.get_or_create_folder(category_path)
            
            clean_title = sanitize_filename(title)
            file_name = f"[{bvid}] - {clean_title}.md"
            file_path = os.path.join(category_folder, file_name)
            
            if os.path.exists(file_path):
                log(f"知识已存在: {file_path}", "INFO")
                return False

            log("正在调用AI总结视频核心内容...", "BRAIN")
            desc_context = f"【视频简介】\n{video_desc}\n\n" if video_desc else ""
            summary_context = f"视频标题: {title}\nUP主: {up}\n链接: {url}\n\n{desc_context}【视频字幕全文】:\n{subtitle_text}"

            resp = openai.ChatCompletion.create(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_SUMMARY},
                    {"role": "user", "content": summary_context}
                ]
            )
            summary_content = resp.choices[0].message.content
            
            desc_section = f"- **简介**: {video_desc}\n" if video_desc else ""
            file_header = (
                f"# 📚 知识归档\n\n"
                f"【视频信息】\n"
                f"- **标题**: {title}\n"
                f"- **UP主**: {up}\n"
                f"- **链接**: {url}\n"
                f"{desc_section}"
                f"- **归档时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"- **分类**: {category_path}\n"
                f"- **视频ID**: {bvid}\n\n"
                f"---\n\n"
                f"## [BRAIN] AI内容总结\n\n"
            )

            full_content = file_header + summary_content
            
            # 💬 评论区补充：合并在同一归档文件末尾
            if comment_summary and len(comment_summary.strip()) > 5:
                full_content += f"\n\n---\n\n{comment_summary.strip()}\n"
                log(f"评论区补充已合并到归档", "LEARN")

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(full_content)

            log(f"知识已总结并保存到: {file_path}", "SUCCESS")
            self.write_learning_log(category_path, title, file_path)
            
            self.classifier.show_category_structure()

            # 📦 Highlights archive: save high-quality content to highlights/ folder
            if DRY_GOODS_ENABLED and score is not None and score >= DRY_GOODS_MIN_SCORE:
                try:
                    dry_category_folder = os.path.join(DRY_GOODS_DIR, category_path)
                    os.makedirs(dry_category_folder, exist_ok=True)
                    dry_file_path = os.path.join(dry_category_folder, file_name)
                    if not os.path.exists(dry_file_path):
                        dry_file_header = (
                            f"# 🔥 Highlights\n\n"
                            f"【Video Info】\n"
                            f"- **Title**: {title}\n"
                            f"- **Author**: {up}\n"
                            f"- **Link**: {url}\n"
                            f"- **Score**: {score}/10\n"
                            f"- **Archived**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"- **Category**: {category_path}\n"
                            f"- **Video ID**: {bvid}\n\n"
                            f"---\n\n"
                            f"## [BRAIN] AI Summary\n\n"
                        )
                        with open(dry_file_path, 'w', encoding='utf-8') as f:
                            dry_content = dry_file_header + summary_content
                            if comment_summary and len(comment_summary.strip()) > 5:
                                dry_content += f"\n\n---\n\n{comment_summary.strip()}\n"
                            f.write(dry_content)
                        log(f"[GOLD] Highlights archived! Score {score}/10 -> {dry_file_path}", "SUCCESS")
                except Exception as dry_e:
                    log(f"Highlights archive failed: {dry_e}", "WARN")

            # 🧠 更新向量索引
            if self.kb_search:
                try:
                    await self.kb_search.update_entry(file_path)
                except Exception as ve:
                    log(f"向量索引更新失败: {ve}", "WARN")

            return True

        except Exception as e:
            log(f"学习与归档过程中发生错误: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return False

    async def learn_from_comments(self, bvid, title, up, video_url, comment_text, c_list, topic_suggestion, score=None):
        """从评论区提取有价值知识，返回摘要文本（不再写独立文件）。
        
        返回: (comment_summary: str | None, skipped_reason: str)
        - 有知识 → ("## 💬 评论区补充\n- xxx", "")
        - 无知识/skip → (None, "原因")
        """
        # ── 质量门槛 ──
        if score is not None and score < LEARN_MIN_SCORE:
            return None, f"视频评分过低({score:.1f}<{LEARN_MIN_SCORE})，跳过评论收集"
        if not c_list or len(c_list) < 5:
            return None, f"评论数不足({len(c_list) if c_list else 0}<5)"
        total_text_len = sum(len(c.get('content','')) for c in c_list)
        if total_text_len < 150:
            return None, f"评论总字数太少({total_text_len}<150)，信息密度必然低"

        log(f"从评论区挖掘知识... ({len(c_list)}条评论, {total_text_len}字)", "LEARN")

        try:
            comments_ctx = f"【视频信息】\n标题: {title}\nUP主: {up}\n链接: {video_url}\n\n【评论区内容】:\n"
            for i, c in enumerate(c_list):
                comments_ctx += f"#{i+1} [{c.get('user','?')}]: {c.get('content','')}\n"
                if c.get('pic_info'):
                    comments_ctx += f"    [附图]: {c['pic_info']}\n"
            # 附加现有决策文本
            if comment_text and comment_text != "[未读取评论]" and "【热门评论】" in str(comment_text):
                comments_ctx += f"\n【AI预分析】:\n{comment_text}"

            comments_ctx = comments_ctx[:5000]

            resp = openai.ChatCompletion.create(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_COMMENT_SUMMARY},
                    {"role": "user", "content": comments_ctx}
                ]
            )
            summary = resp.choices[0].message.content.strip()

            # 无知识 → 跳过
            if not summary or summary.upper().startswith("SKIP") or "无实质" in summary:
                return None, f"AI判断评论区无实质知识内容"

            # 清理掉可能的 markdown 标题标记（保持简洁）
            summary = summary.replace("## 💬 评论区知识精华", "## 💬 评论区补充")
            log(f"评论区知识提炼成功 ({len(summary)}字)，将合并到视频归档", "SUCCESS")
            return summary, ""

        except Exception as e:
            return None, f"评论区知识收集出错: {e}"

    async def verify_knowledge_file(self, bvid, video_title):
        """回顾复习时验证知识文件真实性。如果发现虚假/错误，备份原文件并重写。
        
        返回: (verified: bool, issues_count: int, action: str)
        """
        if not KNOWLEDGE_VERIFY_ENABLED:
            return True, 0, "知识验证未启用"
        
        # 在知识库中查找对应的文件
        found_files = []
        if os.path.exists(KNOWLEDGE_BASE_DIR):
            for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
                for f in files:
                    if f.endswith('.md') and bvid in f and not f.startswith('备份_'):
                        found_files.append(os.path.join(root, f))
        
        if not found_files:
            return True, 0, "未找到对应知识文件"
        
        file_path = found_files[0]
        log(f"🔍 开始验证知识文件: {os.path.basename(file_path)}", "KB")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                knowledge_content = f.read()
            
            # 联网搜索（如果启用）
            web_results = []
            if KNOWLEDGE_VERIFY_USE_WEB:
                log(f"[NET] 联网搜索验证关键词: {video_title[:40]}...", "KB")
                web_results = await web_search(video_title[:60], limit=5)
                if web_results:
                    log(f"[NET] 获取到 {len(web_results)} 条搜索结果", "INFO")
                else:
                    log("[NET] 联网搜索未获取到结果，仅使用AI知识库验证", "INFO")
            
            # AI验证
            verify_result = await verify_knowledge_with_ai(knowledge_content, video_title, web_results)
            
            overall_score = verify_result.get("overall_score", 0.7)
            is_reliable = verify_result.get("overall_reliable", True)
            issues = verify_result.get("issues", [])
            supplements = verify_result.get("supplements", [])
            needs_rewrite = verify_result.get("recommend_rewrite", False) or overall_score < KNOWLEDGE_VERIFY_MIN_SCORE
            
            # 打印验证结果
            issues_bad = [i for i in issues if i.get("verdict") in ("存疑", "错误", "过时")]
            if issues_bad:
                for issue in issues_bad[:3]:
                    log(f"  [WARN] 问题: {issue.get('claim','')[:50]} → {issue.get('verdict')}", "WARN")
            if supplements:
                log(f"  [NOTE] 建议补充 {len(supplements)} 条知识", "INFO")
            
            if needs_rewrite:
                corrected = verify_result.get("corrected_content")
                if corrected and KNOWLEDGE_VERIFY_AUTO_FIX:
                    log(f"🚨 知识可靠性不足(评分:{overall_score:.0%})，备份原文件并重写...", "WARN")
                    backup_and_rewrite_knowledge(file_path, corrected, verify_result)
                    return False, len(issues_bad), f"已修正（评分{overall_score:.0%}）"
                else:
                    log(f"[WARN] 知识存疑(评分:{overall_score:.0%})，但AI未提供修正内容，保留原文件", "WARN")
                    return False, len(issues_bad), f"存疑但无修正内容（评分{overall_score:.0%}）"
            else:
                log(f"[OK] 知识验证通过（可靠性评分: {overall_score:.0%}）", "SUCCESS")
                return True, 0, f"验证通过（评分{overall_score:.0%}）"
                
        except Exception as e:
            log(f"知识验证过程出错: {e}", "WARN")
            return True, 0, f"验证失败跳过: {e}"

    async def curiosity_deep_dive(self, topic, trigger_title="", trigger_bvid=""):
        """好奇心驱动的B站深度搜索。遇到感兴趣/不懂的主题，搜索并动态调整观看视频数量。
        
        默认2-3个，内容中等则3-5个，干货多则5-10个。
        
        参数:
            topic: 搜索主题/关键词
            trigger_title: 触发此深度搜索的视频标题
            trigger_bvid: 触发视频的bvid
        
        返回: (videos_watched: int, key_findings: list)
        """
        if not CURIOSITY_DEEP_DIVE_ENABLED:
            return 0, []
        
        # 动态视频数量：起始默认2-3个，根据AI评估的content_richness逐步提升
        max_videos = CURIOSITY_DEEP_DIVE_DEFAULT_VIDEOS
        log(f"🧭 好奇心驱动深度搜索启动！主题: '{topic}' (初始上限{max_videos}个，按需提升至{CURIOSITY_DEEP_DIVE_HIGH_VIDEOS}个)", "LEARN")
        
        videos_watched = 0
        key_findings = []
        all_subtitles = []
        search_queries_tried = set()
        current_query = topic
        dive_tier = 0  # 0=初始(2-3), 1=中等(3-5), 2=丰富(5-10)
        
        for dive_round in range(4):  # 最多4轮搜索（给更充裕的空间）
            if videos_watched >= max_videos:
                break
            
            # 搜索B站视频
            if current_query not in search_queries_tried:
                search_queries_tried.add(current_query)
                log(f"🔍 B站搜索第{dive_round+1}轮: '{current_query}' (上限:{max_videos}个)", "LEARN")
                
                try:
                    if not self.agent_runner or not hasattr(self.agent_runner, 'toolbox'):
                        log("Agent运行器未初始化，无法搜索", "WARN")
                        break
                    search_results = await self.agent_runner.toolbox.video_search(current_query, limit=min(8, max_videos - videos_watched))
                    if isinstance(search_results, dict) and search_results.get("error"):
                        log(f"搜索失败: {search_results.get('error')}", "WARN")
                        break
                    if not search_results:
                        log("搜索无结果，换个关键词试试...", "INFO")
                        current_query = f"{topic} 科普" if "科普" not in current_query else f"{topic} 介绍"
                        continue
                except Exception as e:
                    log(f"搜索异常: {e}", "WARN")
                    break
                
                # 逐个观看搜索到的视频
                for item in search_results:
                    if videos_watched >= max_videos:
                        break
                    
                    bvid = item.get("bvid")
                    title = item.get("title", "")
                    if not bvid:
                        continue
                    
                    videos_watched += 1
                    log(f"📺 [{videos_watched}/{max_videos}] 深度看: 《{title[:40]}》", "LEARN")
                    
                    try:
                        await _bili_throttle("深度搜索-看视频")
                        ok, subtitle = await self.understand_video_for_decision(bvid)
                        if ok and subtitle and len(subtitle) > 50:
                            all_subtitles.append(f"【{title}】: {subtitle[:1500]}")
                        
                        # [FIX] 深度搜索也要学习归档：每个视频看完后调用learn_from_video
                        if ok and subtitle and len(str(subtitle)) > 30:
                            try:
                                up = item.get("author", "") or item.get("uname", "")
                                video_url = f"https://www.bilibili.com/video/{bvid}"
                                _desc = getattr(self, "_last_video_desc", "")
                                await self.learn_from_video(bvid, title, up, video_url, str(subtitle), topic, video_desc=_desc)
                            except Exception as learn_e:
                                log(f"深度搜索学习归档失败: {learn_e}", "WARN")
                    except Exception as e:
                        log(f"深度看视频失败: {e}", "WARN")
                    
                    await asyncio.sleep(random.uniform(0.3, 0.8))
            
            # 检查是否已经了解足够（至少看了2个后才判断）
            if all_subtitles and videos_watched >= 2:
                try:
                    review_context = (
                        f"学习主题: {topic}\n"
                        f"已看{videos_watched}个相关视频\n"
                        f"视频内容摘要:\n" + "\n---\n".join(all_subtitles[-5:])
                    )
                    resp = openai.ChatCompletion.create(
                        model=MODEL_BRAIN,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT_CURIOSITY_DIVE},
                            {"role": "user", "content": f"{review_context}\n\n{videos_watched}/{max_videos}个视频（上限{videos_watched}/{CURIOSITY_DEEP_DIVE_HIGH_VIDEOS}）。请判断是继续搜索还是已足够，并评估内容丰度。"}
                        ],
                        timeout=90
                    )
                    raw = resp.choices[0].message.content.strip()
                    # [FIX] 嵌套匹配提取JSON
                    start = raw.find("{")
                    if start >= 0:
                        depth = 0
                        match_end = -1
                        for i in range(start, len(raw)):
                            if raw[i] == '{':
                                depth += 1
                            elif raw[i] == '}':
                                depth -= 1
                                if depth == 0:
                                    match_end = i
                                    break
                        if match_end >= 0:
                            dive_decision = json.loads(raw[start:match_end+1])
                        else:
                            end = raw.rfind("}")
                            if end >= start:
                                try:
                                    dive_decision = json.loads(raw[start:end+1])
                                except json.JSONDecodeError:
                                    dive_decision = {"continue_search": False, "reason": "AI返回解析失败"}
                            else:
                                dive_decision = {"continue_search": False, "reason": "AI返回解析失败"}
                    else:
                        dive_decision = {"continue_search": False, "reason": "AI返回解析失败"}
                    
                    key_findings = dive_decision.get("key_takeaways", [])
                    content_richness = dive_decision.get("content_richness", 0.0)
                    
                    # 动态调整max_videos：根据AI评估的内容丰度提升上限
                    if content_richness >= 0.6 and dive_tier < 2:
                        dive_tier = 2
                        max_videos = CURIOSITY_DEEP_DIVE_HIGH_VIDEOS
                        log(f"📈 内容丰度 {content_richness:.0%} -> 上限提升至{max_videos}个 (干货满满！)", "LEARN")
                    elif content_richness >= 0.3 and dive_tier < 1:
                        dive_tier = 1
                        max_videos = CURIOSITY_DEEP_DIVE_MID_VIDEOS
                        log(f"📈 内容丰度 {content_richness:.0%} -> 上限提升至{max_videos}个", "LEARN")
                    
                    if dive_decision.get("continue_search") and dive_decision.get("new_query"):
                        current_query = dive_decision["new_query"]
                        log(f"🧭 继续深度搜索，新关键词: '{current_query}' (满意度: {dive_decision.get('satisfaction', 0):.0%}, 丰度:{content_richness:.0%})", "LEARN")
                        continue
                    else:
                        tier_label = ["浅层","中等","丰富"][dive_tier]
                        log(f"[OK] 深度搜索完成！满意度: {dive_decision.get('satisfaction', 0):.0%} | 丰度:{content_richness:.0%}({tier_label}) | 共看{videos_watched}个 | 原因: {dive_decision.get('reason', '')}", "SUCCESS")
                        break
                except Exception as e:
                    log(f"深度搜索决策失败: {e}", "WARN")
                    break
            else:
                break
        
        # 总结并写入学习日志
        if key_findings:
            summary_text = "\n".join(f"- {f}" for f in key_findings)
            log(f"[NOTE] 深度搜索关键发现:\n{summary_text}", "LEARN")
            try:
                self.write_learning_log(f"深度搜索/{topic}", topic, "")
                # 写入日记
                if hasattr(self, "diary_mgr"):
                    self.diary_mgr.add_entry(
                        f"好奇心深度搜索: {topic}",
                        f"搜索主题「{topic}」观看了{videos_watched}个视频。\n关键发现:\n{summary_text}",
                        mood=self.mood_mgr.get_current() if hasattr(self, 'mood_mgr') else "好奇",
                        tags=["好奇心", "深度搜索", topic],
                        source="curiosity_dive"
                    )
            except Exception as e:
                log(f"记录深度搜索结果失败: {e}", "WARN")
        
        return videos_watched, key_findings

    async def understand_video_for_decision(self, bvid, title=None, force_mode=None):
        """[VIDEO] 超级智能视频理解：字幕优先 → AI判断是否需要下载 → 必要时ASR → 理解后删除
        force_mode: None=默认智能流程 | 'subtitle_only'|'asr_only'|'vision_only'|
                    'subtitle+asr'|'subtitle+vision'|'asr+vision'|'all'
        """
        return await self._understand_super_smart(bvid, title, force_mode=force_mode)

    async def _understand_super_smart(self, bvid, title=None, force_mode=None):
        """
        [BRAIN] 超级智能理解链（v3.0.1）：
        1. 先抓字幕
        2. 字幕有内容 → AI判断字幕是否足够覆盖视频核心
        3. 字幕足够 → 直接用字幕，不下载视频 [OK]
        4. 字幕不足/无字幕 → 下载视频 → 同时ASR+抽关键帧 → 合并分析
           - 不再依赖AI"人声判断"来决定是否下载，统一下载
           - ASR结果为空 → 纯视觉帧理解
           - ASR有结果 → 合并ASR+视觉帧 → 更全面的理解
        force_mode: None=默认智能流程 | 'subtitle_only'|'asr_only'|'vision_only'|
                    'subtitle+asr'|'subtitle+vision'|'asr+vision'|'all'
        """
        # ── 解析 force_mode 标志 ──
        do_subtitle = True
        do_asr = True
        do_vision = True
        skip_subtitle_check = False  # 跳过AI判断字幕是否足够，强制下载
        if force_mode:
            fm = force_mode.lower()
            if fm == "subtitle_only":
                do_asr = False; do_vision = False
            elif fm == "asr_only":
                do_subtitle = False; do_vision = False; skip_subtitle_check = True
            elif fm == "vision_only":
                do_subtitle = False; do_asr = False; skip_subtitle_check = True
            elif fm == "subtitle+asr":
                do_vision = False; skip_subtitle_check = True
            elif fm == "subtitle+vision":
                do_asr = False; skip_subtitle_check = True
            elif fm == "asr+vision":
                do_subtitle = False; skip_subtitle_check = True
            # "all" or None: 默认智能流程

        # ═══ 第一步：抓字幕+简介 ═══
        subtitle_text = ""
        has_subtitle = False
        content = ""
        video_desc = ""
        if do_subtitle:
            ok, content, video_desc, subtitle_ai_verified = await fetch_bilibili_subtitles(
                bvid, self.cookies, title=title,
                ai_verify_func=self._ai_verify_subtitle_content if (AI_SUBTITLE_VERIFY_ENABLED and SUBTITLE_STRICT_CHECK) else None
            )
            self._last_video_desc = video_desc  # 存下来，供 learn_from_video 使用
            subtitle_text = content if ok else ""
            has_subtitle = ok and len(subtitle_text.strip()) > 30
        else:
            self._last_video_desc = video_desc

        # ═══ 第二步：AI判断字幕是否足够 ═══
        video_tags = getattr(self, "_current_video_tags", None) or []
        video_category = getattr(self, "_current_video_category", "") or ""
        video_duration = getattr(self, "_current_video_duration", 0) or 0
        cover_desc = getattr(self, "_current_video_cover_desc", "") or ""

        # [force_mode] subtitle_only → 拿完字幕直接返回
        if force_mode == "subtitle_only":
            if has_subtitle:
                log(f"[OK] 仅字幕模式，字幕获取成功 ({len(subtitle_text)}字)", "BRAIN")
                return True, subtitle_text
            else:
                log(f"[WARN] 仅字幕模式，但无可用字幕: {content[:80] if content else 'N/A'}", "BRAIN")
                return False, content or "[无可用字幕]"

        if has_subtitle and not skip_subtitle_check:
            # [FIX] 低置信度字幕：单轨弱关联→跳过AI二次判断直接使用
            # 所有轨校验均失败→字幕完全不可信，必须回退到ASR+视觉
            is_low_confidence = subtitle_text.startswith("[低置信度字幕") or subtitle_text.startswith("[极低置信度字幕")
            if is_low_confidence:
                is_all_failed = "轮重试均失败" in subtitle_text or "所有轨校验均失败" in subtitle_text
                if is_all_failed:
                    log(f"[WARN] 所有字幕轨校验均失败，字幕不可信，回退到ASR+视觉理解", "BRAIN")
                    # 不return，继续往下尝试ASR/视觉帧
                else:
                    log(f"[OK] 低置信度字幕(有关键词弱关联)，跳过AI二次判断，直接使用供AI分析", "BRAIN")
                    return True, subtitle_text
            
            # AI评估：字幕是否足以理解视频
            subtitle_sufficient, sufficiency_reason = await self._ai_judge_subtitle_sufficiency(
                title=title or "",
                subtitle=subtitle_text[:2000],
                tags=video_tags,
                category=video_category,
                duration=video_duration,
                cover_desc=cover_desc,
                video_desc=video_desc
            )
            if subtitle_sufficient:
                log(f"[OK] AI判断字幕充分: {sufficiency_reason} | 无需下载视频", "BRAIN")
                return True, subtitle_text
            else:
                # [FIX] 快速预检：如果字幕主要是音乐符号/纯噪声，直接兜底，不浪费下载视频
                if self._is_music_only_subtitle(subtitle_text):
                    log(f"[WARN] 字幕以音乐标记为主，跳过视频下载，直接使用字幕兜底", "BRAIN")
                    return True, subtitle_text
                log(f"[WARN] AI判断字幕不足: {sufficiency_reason} | 将下载视频进行ASR+视觉联合理解...", "BRAIN")
                # 字幕不够 → 下载视频，同时ASR+视觉帧
        else:
            log(f"📭 无可用字幕: {content[:80] if content else 'N/A'}", "BRAIN")

        # ═══ 第三步：force_mode + ASR总开关检查 ═══
        if not do_asr or not ASR_ENABLED:
            reason = "force_mode指定跳过" if not do_asr else "ASR未开启"
            log(f"⚙️ {reason}，跳过语音识别", "INFO")
            if do_vision:
                # [VISION] 尝试画面理解兜底
                vis_fallback = await self._understand_with_vision_frames(bvid, title, subtitle_text)
                if vis_fallback:
                    return True, vis_fallback
            if has_subtitle:
                return True, subtitle_text
            return False, content or f"[{reason}]"

        # ═══ 第四步：规则快速过滤（纯音乐/游戏集锦等确定无人声的跳过ASR） ═══
        from xingye_bot.asr_engine import ASREngine
        skip, skip_reason = ASREngine.should_skip_asr(
            title=title or "",
            tags=video_tags,
            category=video_category,
            cover_desc=cover_desc,
            duration=video_duration,
        )
        if skip:
            log(f"🤖 规则预判跳过ASR: {skip_reason}", "BRAIN")
            if has_subtitle:
                is_all_failed = "轮重试均失败" in subtitle_text or "所有轨校验均失败" in subtitle_text
                if not is_all_failed:
                    return True, subtitle_text
                log(f"[WARN] 规则跳过ASR但字幕所有轨校验失败或AI判定不相关，尝试视觉帧理解", "BRAIN")
            # 规则明确跳过（纯音乐等）→ 视觉帧理解兜底
            if do_vision:
                vis_fallback = await self._understand_with_vision_frames(bvid, title, subtitle_text)
                if vis_fallback:
                    return True, vis_fallback
            return False, f"{content} | [ASR跳过: {skip_reason}]"

        # ═══ 第五步：下载视频 → 同时ASR + 抽关键帧 → 合并分析 ═══
        # 一次下载获得语音+画面双重信息，更准确高效
        mode_desc = "ASR" if do_asr else ""
        if do_vision:
            mode_desc += "+VISION" if mode_desc else "VISION"
        log(f"[{mode_desc}] 下载视频进行理解: 《{title}》", "CONFIG")
        from pathlib import Path as _Path
        video_path = None
        vision_result = None
        asr_text = ""
        
        try:
            from xingye_bot.asr_engine import get_asr_engine
            asr_cfg = config.get("asr", {})
            asr = get_asr_engine(asr_cfg)

            # 下载视频（只下载一次）
            video_path_str = await self._download_video_for_asr(bvid)
            if not video_path_str:
                log(f"[{mode_desc}] 视频下载失败", "WARN")
                if has_subtitle:
                    return True, subtitle_text
                return False, f"{content} | [下载失败]"
            
            video_path = _Path(video_path_str)
            
            # [SMART_FRAME] AI智能决定是否抽帧 + 抽多少帧
            should_extract = False; smart_frame_count = 0; frame_reason = ""
            if do_vision:
                should_extract, smart_frame_count, frame_reason = await self._ai_decide_frame_count(
                    title=title or "",
                    duration=video_duration,
                    tags=video_tags,
                    category=video_category,
                    subtitle_text=subtitle_text
                )
                if not should_extract:
                    log(f"[SMART_FRAME] AI决定不抽帧: {frame_reason}", "EYE")
                else:
                    log(f"[SMART_FRAME] AI决定抽{smart_frame_count}帧: {frame_reason}", "EYE")
            
            # --- 并行：ASR语音识别 + 视觉帧抽取 ---
            asr_task = None
            if do_asr and asr.is_available():
                if not asr.has_ffmpeg():
                    log(f"[WARN] ffmpeg 未在PATH找到，将用 torchaudio 兜底提取音频", "DEBUG")
                asr_task = asyncio.create_task(asr.process_video(video_path, title=title or ""))
            
            # 同时抽关键帧（复用已下载的视频，不再单独下载）
            vision_task = None
            if do_vision and VISION_FRAMES_ENABLED and should_extract:
                vision_task = asyncio.create_task(self._extract_and_analyze_frames(
                    video_path, bvid, title, subtitle_text, frame_count=smart_frame_count
                ))
            
            # 等待两个任务完成
            if asr_task:
                try:
                    asr_result = await asr_task
                    if asr_result.success:
                        asr_text = asr.format_result(asr_result)
                        speaker_count = len(set(s.speaker for s in asr_result.segments if s.speaker))
                        if speaker_count > 0:
                            log(f"[ASR] ASR完成！识别 {len(asr_result.segments)} 片段，{speaker_count} 位说话人", "SUCCESS")
                        else:
                            log(f"[ASR] ASR完成！识别 {len(asr_result.segments)} 片段", "SUCCESS")
                        # ── ASR-标题匹配校验：防止ASR张冠李戴（仅在"字幕严格校验"开启时）──
                        asr_plain = asr_result.text or asr_text or ""
                        if SUBTITLE_STRICT_CHECK and asr_plain and title:
                            _, mismatch = _check_subtitle_mismatch(title, asr_plain)
                            if mismatch:
                                log(f"[ASR] ⚠️ ASR内容可能与视频不匹配: {mismatch} | ASR开头: {asr_plain[:60]}...", "WARN")
                                # 标记但继续使用（由AI自行判断）
                                asr_text = f"[⚠️ ASR内容可能与视频标题不匹配] {asr_text}"
                    else:
                        log(f"[ASR] ASR识别失败: {asr_result.error}", "WARN")
                except Exception as asr_e:
                    log(f"[ASR] ASR异常: {asr_e}", "WARN")
            
            if vision_task:
                try:
                    vision_result = await vision_task
                    if vision_result:
                        log(f"[EYE] 视觉帧理解完成 ({len(vision_result)}字)", "SUCCESS")
                except Exception as vis_e:
                    log(f"[EYE] 视觉帧理解异常: {vis_e}", "WARN")
            
            # --- 合并结果 ---
            # 构建最终理解文本
            parts = []
            if asr_text:
                parts.append(f"【ASR语音识别】\n{asr_text}")
            if vision_result:
                parts.append(f"【视觉画面理解】\n{vision_result}")
            if has_subtitle:
                parts.insert(0, f"【CC字幕（不完整）】\n{subtitle_text[:2000]}")
            
            if parts:
                combined = "\n\n---\n\n".join(parts)
                return True, combined
            elif has_subtitle:
                return True, subtitle_text
            else:
                # 都失败了，返回基本信息
                basic = f"【理解失败】标题: {title or ''}\n分区: {video_category}\n时长: {video_duration}s"
                return False, basic
                
        except ImportError as e:
            log(f"ASR依赖缺失: {e}", "WARN")
            if has_subtitle:
                return True, subtitle_text
            vis_fallback = await self._understand_with_vision_frames(bvid, title, subtitle_text)
            if vis_fallback:
                return True, vis_fallback
            return False, f"{content} | [ASR依赖缺失: {e}]"
        except Exception as e:
            log(f"联合理解流程异常: {e}", "WARN")
            if has_subtitle:
                return True, subtitle_text
            vis_fallback = await self._understand_with_vision_frames(bvid, title, subtitle_text)
            if vis_fallback:
                return True, vis_fallback
            return False, f"{content} | [异常: {e}]"
        finally:
            # 🧹 清理：删除视频文件
            if video_path and video_path.exists():
                try:
                    video_path.unlink()
                    log(f"🗑️ 已删除下载的视频文件: {video_path.name}", "DEBUG")
                except Exception as del_e:
                    log(f"删除视频文件失败: {del_e}", "DEBUG")

    async def _extract_and_analyze_frames(self, video_path, bvid, title=None, subtitle_text="", frame_count=None):
        """[VISION v2] 从已下载的视频文件抽帧→视觉AI分析→返回画面描述。
        与 _understand_with_vision_frames 的区别：不重新下载视频，直接使用已有文件。
        frame_count: AI智能决定的抽帧数量，None则使用默认VISION_FRAME_COUNT"""
        if not VISION_FRAMES_ENABLED:
            return None
        # 使用AI决定的帧数，否则用默认值
        actual_frame_count = frame_count if frame_count and frame_count > 0 else VISION_FRAME_COUNT
        from pathlib import Path as _VP
        frames = []
        frames_dir = None
        try:
            video_path = _VP(str(video_path))
            if not video_path.exists():
                return None
            
            import subprocess as _sp
            frames_dir = video_path.parent / "vision_frames"
            frames_dir.mkdir(exist_ok=True)
            for old in frames_dir.glob("frame_*.jpg"):
                old.unlink()
            
            # 获取时长
            ffprobe = shutil.which("ffprobe")
            ffmpeg = shutil.which("ffmpeg")
            duration = 0
            if ffprobe:
                try:
                    dur_out = _sp.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                        capture_output=True, text=True, timeout=15)
                    duration = int(float(dur_out.stdout.strip())) if dur_out.stdout.strip() else 0
                except Exception:
                    duration = 0
            if not ffmpeg:
                return None
            
            # [SMART_FRAME] 使用AI决定的帧数
            interval = max(1, duration // max(1, actual_frame_count)) if duration else 5
            pattern = str(frames_dir / "frame_%03d.jpg")
            _sp.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(video_path), "-vf", f"fps=1/{interval},scale=640:-1",
                "-frames:v", str(actual_frame_count), pattern],
                timeout=120, capture_output=True)
            frames = sorted(frames_dir.glob("frame_*.jpg"))
            if not frames:
                return None
            
            # [SMART_FRAME] 帧数较多时智能抽样：均匀选取不超过max_frames_for_ai张发送给视觉AI
            # 避免一次发送太多图片导致API超限/成本过高
            max_frames_for_ai = min(actual_frame_count, 60)
            if len(frames) > max_frames_for_ai:
                step = len(frames) / max_frames_for_ai
                sampled = [frames[int(i * step)] for i in range(max_frames_for_ai)]
                log(f"[EYE] 抽取 {len(frames)} 帧，智能抽样 {len(sampled)} 帧发送视觉AI分析...", "EYE")
                frames_to_analyze = sampled
            else:
                log(f"[EYE] 抽取 {len(frames)} 帧，发送视觉AI分析...", "EYE")
                frames_to_analyze = frames
            
            # 构建多模态请求
            content_blocks = [{
                "type": "text",
                "text": (
                    f"你正在通过关键帧画面理解一个B站视频。\n"
                    f"标题: {title or '未知'}\n"
                    f"以下是均匀采样的{len(frames_to_analyze)}张关键帧截图（从总共{len(frames)}帧中选取）。\n"
                    f"{'【参考字幕】: ' + subtitle_text[:1500] if subtitle_text else ''}\n"
                    "请输出: 视频主题、核心内容、画面风格、知识密度评估。用中文简述。"
                )
            }]
            import base64 as _b64_vis
            for frame in frames_to_analyze:
                data_url = "data:image/jpeg;base64," + _b64_vis.b64encode(frame.read_bytes()).decode("ascii")
                content_blocks.append({"type": "image_url", "image_url": {"url": data_url}})
            
            resp = await self._call_ai_with_retry(
                model=MODEL_VISION,
                messages=[{
                    "role": "system",
                    "content": "你是视频内容分析助手，通过关键帧截图理解视频。请仔细看每张图，综合判断内容。"
                }, {
                    "role": "user",
                    "content": content_blocks
                }],
                request_timeout=180
            )
            result = resp.choices[0].message.content.strip()
            return result
        except Exception as e:
            log(f"[EYE] 视觉帧分析异常: {e}", "WARN")
            return None
        finally:
            # 清理帧文件和目录（但不删视频，由调用方统一清理）
            try:
                if frames and frames_dir and frames_dir.exists():
                    import shutil as _sh
                    _sh.rmtree(str(frames_dir), ignore_errors=True)
            except Exception as e:
                log(f'非预期异常: {e}', 'WARN')

    async def _ai_decide_frame_count(self, title="", duration=0, tags=None, category="", subtitle_text=""):
        """[SMART_FRAME] AI根据视频信息智能决定：是否抽帧 + 抽多少帧(10-300)。
        返回 (should_extract: bool, frame_count: int, reason: str)"""
        if not SMART_FRAME_ENABLED:
            # 未开启智能抽帧，使用固定数量
            return True, VISION_FRAME_COUNT, "智能抽帧关闭，使用固定数量"
        
        # 如果是AI降级状态，用规则判断
        if self._is_ai_degraded():
            # 规则：短视频(<60s)少抽，中视频(60-600s)中等，长视频(>600s)多抽
            if duration <= 60:
                count = min(SMART_FRAME_MAX, max(SMART_FRAME_MIN, 10))
            elif duration <= 300:
                count = min(SMART_FRAME_MAX, max(SMART_FRAME_MIN, duration // 10))
            elif duration <= 900:
                count = min(SMART_FRAME_MAX, max(SMART_FRAME_MIN, duration // 8))
            else:
                count = min(SMART_FRAME_MAX, max(SMART_FRAME_MIN, duration // 6))
            return True, count, f"AI降级，按规则(duration={duration}s)决定抽{count}帧"
        
        tags_str = ", ".join(tags[:10]) if tags else "无"
        prompt = (
            "你是视频关键帧抽取策略专家。根据视频元信息判断：是否需要抽取关键帧？如果需要，抽多少帧最合适？\n"
            "抽帧目的：用关键帧截图让视觉AI理解视频画面内容。\n"
            "判断原则：\n"
            "- 纯文字/PPT/录屏类：少量帧(10-30)即可，画面变化小\n"
            "- 教程/知识讲解：中等帧数(20-60)，需要看关键步骤\n"
            "- Vlog/生活/旅游：较多帧(40-100)，场景切换多\n"
            "- 影视/动画/游戏实况：多帧(60-150)，画面信息密度高\n"
            "- 混剪/MAD/快节奏：很多帧(100-200)，画面切换极快\n"
            "- 评测/开箱/产品展示：中多帧(40-80)，需要看细节\n"
            "- 新闻/访谈/纪录片：中等帧(30-80)，人物+场景结合\n"
            "- 纯音乐/MV/演唱会：不抽帧(0)，画面意义不大\n"
            "- 音频节目/播客/ASMR：不抽帧(0)，画面无信息量\n"
            f"视频标题: {title}\n"
            f"视频时长: {duration}秒\n"
            f"分区: {category}\n"
            f"标签: {tags_str}\n"
            f"字幕预览: {subtitle_text[:300] if subtitle_text else '无'}\n\n"
            "只返回JSON，不要其他文字:\n"
            '{"should_extract": true/false, "frame_count": 整数(10-300), "reason": "简短理由(15字内)"}'
        )
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[{
                    "role": "system",
                    "content": "你是视频分析策略专家。只返回JSON。"
                }, {
                    "role": "user",
                    "content": prompt
                }],
                request_timeout=30
            )
            text = resp.choices[0].message.content.strip()
            # 提取JSON
            import json as _json_sf
            json_match = re.search(r'\{[^}]+\}', text)
            if json_match:
                data = _json_sf.loads(json_match.group())
                should_extract = data.get("should_extract", True)
                frame_count = int(data.get("frame_count", VISION_FRAME_COUNT))
                reason = data.get("reason", "AI判断")
                # 限制范围
                frame_count = max(SMART_FRAME_MIN, min(SMART_FRAME_MAX, frame_count))
                if not should_extract:
                    return False, 0, reason
                return True, frame_count, reason
            else:
                return True, VISION_FRAME_COUNT, "AI返回格式异常，使用默认值"
        except Exception as e:
            log(f"[SMART_FRAME] AI决策异常: {e}", "WARN")
            return True, VISION_FRAME_COUNT, f"异常回退: {e}"

    async def _understand_with_vision_frames(self, bvid, title=None, subtitle_text=""):
        """[VISION] 下载视频→抽帧→视觉AI理解→返回画面描述（ASR/字幕都不可用时的兜底方案）"""
        if not VISION_FRAMES_ENABLED:
            return None
        log(f"[EYE] 尝试视觉帧理解: 《{title or bvid}》", "EYE")
        from pathlib import Path as _VP
        video_path = None
        frames = []
        try:
            # 1. 下载视频
            video_path_str = await self._download_video_for_asr(bvid)
            if not video_path_str:
                log(f"[EYE] 视觉理解: 视频下载失败", "WARN")
                return None
            video_path = _VP(video_path_str)
            # [SMART_FRAME] AI智能决定是否抽帧 + 抽多少帧
            video_tags = getattr(self, "_current_video_tags", None) or []
            video_category = getattr(self, "_current_video_category", "") or ""
            video_duration = getattr(self, "_current_video_duration", 0) or 0
            should_extract, smart_fc, fc_reason = await self._ai_decide_frame_count(
                title=title or "",
                duration=video_duration,
                tags=video_tags,
                category=video_category,
                subtitle_text=subtitle_text or ""
            )
            if not should_extract:
                log(f"[SMART_FRAME] AI决定不抽帧: {fc_reason}", "EYE")
                return None
            log(f"[SMART_FRAME] AI决定抽{smart_fc}帧: {fc_reason}", "EYE")
            actual_frame_count = smart_fc if smart_fc > 0 else VISION_FRAME_COUNT
            
            # 2. 抽帧 (直接用 ffmpeg，避免引入 VideoUnderstanding 的复杂依赖)
            import subprocess as _sp
            frames_dir = video_path.parent / "vision_frames"
            frames_dir.mkdir(exist_ok=True)
            for old in frames_dir.glob("frame_*.jpg"):
                old.unlink()
            # 用 ffprobe 获取时长
            ffprobe = shutil.which("ffprobe")
            ffmpeg = shutil.which("ffmpeg")
            duration = 0
            if ffprobe:
                try:
                    dur_out = _sp.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                        capture_output=True, text=True, timeout=15)
                    duration = int(float(dur_out.stdout.strip())) if dur_out.stdout.strip() else 0
                except Exception:
                    duration = 0
            if not ffmpeg:
                log(f"[EYE] 视觉理解: ffmpeg 未安装，无法抽帧", "WARN")
                return None
            interval = max(1, duration // max(1, actual_frame_count)) if duration else 5
            pattern = str(frames_dir / "frame_%03d.jpg")
            _sp.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(video_path), "-vf", f"fps=1/{interval},scale=640:-1",
                "-frames:v", str(actual_frame_count), pattern],
                timeout=120, capture_output=True)
            frames = sorted(frames_dir.glob("frame_*.jpg"))
            if not frames:
                log(f"[EYE] 视觉理解: 抽帧失败 (无输出文件)", "WARN")
                return None
            
            # [SMART_FRAME] 智能抽样：帧太多时均匀选取不超过max_frames_for_ai张
            max_frames_for_ai = min(actual_frame_count, 60)
            if len(frames) > max_frames_for_ai:
                step = len(frames) / max_frames_for_ai
                frames_to_analyze = [frames[int(i * step)] for i in range(max_frames_for_ai)]
                log(f"[EYE] 抽取 {len(frames)} 帧，智能抽样 {len(frames_to_analyze)} 帧发送视觉AI分析...", "EYE")
            else:
                log(f"[EYE] 抽取 {len(frames)} 帧，发送视觉AI分析...", "EYE")
                frames_to_analyze = frames
            
            # 3. 构建多模态请求
            content_blocks = [{
                "type": "text",
                "text": (
                    f"你正在通过关键帧画面理解一个B站视频。\n"
                    f"标题: {title or '未知'}\n"
                    f"以下是均匀采样的{len(frames_to_analyze)}张关键帧截图（从总共{len(frames)}帧中选取）。\n"
                    f"{'【参考字幕】: ' + subtitle_text[:1500] if subtitle_text else ''}\n"
                    "请输出: 视频主题、核心内容、画面风格、知识密度评估。用中文简述。"
                )
            }]
            import base64 as _b64_vis
            for frame in frames_to_analyze:
                data_url = "data:image/jpeg;base64," + _b64_vis.b64encode(frame.read_bytes()).decode("ascii")
                content_blocks.append({"type": "image_url", "image_url": {"url": data_url}})
            # 4. 调用视觉模型
            resp = await self._call_ai_with_retry(
                model=MODEL_VISION,
                messages=[{
                    "role": "system",
                    "content": "你是视频内容分析助手，通过关键帧截图理解视频。请仔细看每张图，综合判断内容。"
                }, {
                    "role": "user",
                    "content": content_blocks
                }],
                request_timeout=180
            )
            result = resp.choices[0].message.content.strip()
            log(f"[EYE] 视觉理解完成 ({len(result)}字): {result[:100]}...", "SUCCESS")
            return f"【视觉画面理解】\n{result}"
        except Exception as e:
            log(f"[EYE] 视觉理解异常: {e}", "WARN")
            return None
        finally:
            # 清理临时文件: 删除视频 + 帧文件 + 帧目录
            try:
                if video_path and video_path.exists():
                    video_path.unlink()
                if frames:
                    # 删除帧文件和帧目录
                    frames_dir = frames[0].parent if frames else None
                    if frames_dir and frames_dir.exists():
                        import shutil as _sh
                        _sh.rmtree(str(frames_dir), ignore_errors=True)
            except Exception as e:
                log(f'非预期异常: {e}', 'WARN')

    @staticmethod
    def _is_music_only_subtitle(text: str) -> bool:
        """快速检测字幕是否几乎全是音乐标记（♪ ♪ 音乐 ♪ 等），避免浪费下载视频。
        当字幕中音乐/无意义标记占比超过70%时返回True。"""
        if not text or len(text) < 20:
            return False
        # 统计音乐/空白标记的字符数
        music_pattern = re.compile(r'[♪♫♩♬🎵🎶🎼🎹🎸🎺🎻🥁🎤🎧]')
        music_chars = len(music_pattern.findall(text))
        # 移除所有音乐标记后的有效文本长度
        clean = music_pattern.sub('', text)
        # 再去掉纯空白
        meaningful = re.sub(r'\s+', '', clean)
        total = len(text)
        # 如果音乐符号占比超过30%，或者有效内容不足30%
        if music_chars / max(total, 1) > 0.3:
            return True
        if len(meaningful) / max(total, 1) < 0.3:
            return True
        # 检测连续的音乐标记+短词模式：如 "♪ 音乐 ♪ ♪ 音乐 ♪"
        clean_words = [w for w in re.split(r'\s+', clean) if len(w) > 1]
        if len(clean_words) <= 3 and music_chars > 10:
            return True
        return False

    async def _ai_judge_subtitle_sufficiency(self, title, subtitle, tags, category, duration, cover_desc, video_desc=""):
        """
        🤖 AI判断：现有字幕是否足以理解视频核心内容？
        同时检测字幕是否与标题/简介匹配（防止B站API返回错位字幕）。
        返回 (是否足够, 理由)
        """
        # 关键词匹配检测已关闭 — 访谈/对话类视频标题描述性短语不会出现在字幕对话中，误判率过高

        if self._is_ai_degraded():
            # AI降级：字幕超过200字就认为足够
            return len(subtitle) > 200, "AI降级，按长度判断"

        desc_line = f"视频简介: {video_desc[:300]}\n" if video_desc else ""
        prompt = (
            "你是视频内容评估专家。判断一段视频的字幕是否足以理解其核心内容。\n"
            "如果视频主要是画面演示/操作过程，字幕少也足够；如果是知识讲解/访谈/教程，需要字幕覆盖核心观点。\n"
            f"标题: {title}\n分区: {category}\n时长: {duration}s\n标签: {', '.join(tags[:8])}\n封面描述: {cover_desc}\n{desc_line}"
            f"字幕内容(前2000字):\n{subtitle}\n\n"
            "只返回JSON: {\"sufficient\": true/false, \"reason\": \"简短理由(10字内)\", \"video_type\": \"讲解/演示/访谈/教程/娱乐/操作/评测/其他\"}"
        )
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[{"role": "user", "content": prompt}],
                request_timeout=30
            )
            raw = resp.choices[0].message.content
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end >= start:
                data = json.loads(raw[start:end+1])
                return data.get("sufficient", True), data.get("reason", "AI判断完成")
        except Exception as e:
            log(f"字幕充分性AI判断失败: {e}", "WARN")
        # 默认：字幕超过150字就认为足够
        return len(subtitle) > 150, "默认规则(>150字)"

    async def _ai_judge_has_human_voice(self, title, subtitle, tags, category, duration, cover_desc):
        """
        🎤 AI深度判断：视频里肯定有人声讲话吗？
        返回 (是否有人声, 理由)
        """
        if self._is_ai_degraded():
            # AI降级：用简单规则判断
            voice_keywords = ["讲解", "说", "聊", "访谈", "教程", "播客", "吐槽", "测评", "开箱", "vlog", "脱口秀", "演讲", "辩论", "教学", "课程", "科普", "评测", "review", "talk", "讨论", "分享"]
            no_voice_keywords = ["纯音乐", "BGM", "集锦", "highlight", "速通", "speedrun", "ASMR", "助眠", "白噪音", "延时摄影", "time-lapse", "风景", "混剪", "mad"]
            text = f"{title} {' '.join(tags)} {category} {cover_desc}".lower()
            if any(kw in text for kw in voice_keywords):
                return True, "AI降级-关键词命中"
            if any(kw in text for kw in no_voice_keywords):
                return False, "AI降级-无人声关键词"
            return False, "AI降级-默认跳过"

        prompt = (
            "你是视频内容分析师。判断一个视频是否「肯定包含人声讲话/对话/解说」。\n"
            "需要非常确定有人说话才返回true。纯BGM+画面、纯操作演示无解说、纯风景/延时摄影→false。\n"
            f"标题: {title}\n分区: {category}\n时长: {duration}s\n标签: {', '.join(tags[:8])}\n封面描述: {cover_desc}\n"
            f"已有字幕片段(前1500字):\n{subtitle or '(无字幕)'}\n\n"
            "只返回JSON: {\"has_voice\": true/false, \"confidence\": 0-10, \"reason\": \"简短理由(15字内)\"}"
        )
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[{"role": "user", "content": prompt}],
                request_timeout=30
            )
            raw = resp.choices[0].message.content
            if not raw:
                return False, "AI返回空内容"
            # [FIX] 清除非法控制字符（AI偶尔在JSON中插入换行/退格等）
            import re as _re
            raw = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
            # [FIX] 多策略JSON提取：先尝试最后一个}，失败则用第一个匹配的{}对
            start = raw.find("{")
            if start >= 0:
                # 尝试找嵌套匹配的}（从第一个{开始计数）
                depth = 0
                match_end = -1
                for i in range(start, len(raw)):
                    if raw[i] == '{':
                        depth += 1
                    elif raw[i] == '}':
                        depth -= 1
                        if depth == 0:
                            match_end = i
                            break
                if match_end >= 0:
                    try:
                        data = json.loads(raw[start:match_end+1])
                    except json.JSONDecodeError:
                        # 兜底：用rfind
                        end = raw.rfind("}")
                        if end >= start:
                            data = json.loads(raw[start:end+1])
                        else:
                            raise
                else:
                    end = raw.rfind("}")
                    if end >= start:
                        data = json.loads(raw[start:end+1])
                    else:
                        raise ValueError("无法提取JSON")
                confidence = data.get("confidence", 5)
                has_voice = data.get("has_voice", False) and confidence >= 4
                return has_voice, data.get("reason", "AI判断完成")
            else:
                return False, "AI返回无JSON"
        except Exception as e:
            log(f"人声AI判断失败: {e}", "WARN")
        # 默认：不确定就不下载
        return False, "AI判断异常-默认跳过"

    async def _ai_verify_subtitle_content(self, title, subtitle_text, video_desc=""):
        """
        🤖 AI语义验证：字幕/语音内容是否与视频标题真正匹配？
        
        与 _check_subtitle_mismatch (纯关键词重叠) 不同，这里用AI做深度语义理解：
        - 访谈类视频：标题可能是描述性短语(如"对XX的4小时深度访谈")，
          字幕开头常是主持人开场白，关键词法会误判为不匹配。
        - AI能理解上下文：即使关键词不重叠，也能判断内容是否与标题主题一致。
        
        返回 (is_match: bool, confidence: float 0-1, reason: str)
        """
        if self._is_ai_degraded():
            # AI降级：用关键词法兜底
            overlap, mismatch = _check_subtitle_mismatch(title, subtitle_text)
            if mismatch:
                return True, 0.3, "AI降级-关键词法放行"
            return overlap >= 0.15, max(overlap, 0.3) if overlap else 0.3, f"AI降级-关键词重叠{overlap:.2f}"
        
        sub_sample = subtitle_text[:2500]
        desc_line = f"视频简介: {video_desc[:300]}\n" if video_desc else ""
        prompt = (
            "你是视频内容审核专家。判断以下「字幕/语音内容」是否与「视频标题」语义匹配。\n\n"
            "重要规则：\n"
            "1. 访谈/播客类视频：标题常为描述性总结(如包含人名/话题)，字幕开头可能是主持人开场白、\n"
            "   音乐前奏、闲聊寒暄。请判断**整体内容主题**是否与标题一致，而非仅看前几句。\n"
            "2. 教程/教学类视频：标题是课程名，字幕可能是\"大家好今天讲XX\"，这也算匹配。\n"
            "3. 娱乐/vlog类：标题可能是梗或比喻，字幕内容只要在讨论同一件事即算匹配。\n"
            "4. 明显不匹配：标题说\"Python教程\"但字幕在讲\"美食制作\"、标题说\"数学课\"但字幕是游戏解说。\n\n"
            f"视频标题: {title}\n{desc_line}"
            f"字幕/语音内容(前2500字):\n{sub_sample}\n\n"
            "只返回JSON: {\"match\": true/false, \"confidence\": 0.0-1.0, \"reason\": \"简短理由(15字内)\", "
            "\"content_summary\": \"内容实际在讲什么(10字内)\"}"
        )
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[{"role": "user", "content": prompt}],
                request_timeout=25
            )
            raw = resp.choices[0].message.content
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end >= start:
                data = json.loads(raw[start:end+1])
                is_match = data.get("match", True)
                confidence = float(data.get("confidence", 0.5))
                reason = data.get("reason", "AI判断完成")
                content_summary = data.get("content_summary", "")
                if content_summary:
                    reason = f"{reason} | 实际内容:{content_summary}"
                return is_match, confidence, reason
        except Exception as e:
            log(f"字幕内容AI验证失败: {e}", "WARN")
        # 异常时默认放行（宁可不拒绝，交给后续AI决策）
        return True, 0.4, "AI验证异常-默认放行"

    async def _review_knowledge_periodically(self):
        """
        📚 知识库定期审查：随机抽查归档条目，AI判断标题与内容摘要是否匹配。
        不匹配的条目会被标记（前缀[待审查]）并记录日志，供人工复核。
        每 KNOWLEDGE_REVIEW_INTERVAL 个视频触发一次。
        """
        if not os.path.exists(KNOWLEDGE_BASE_DIR):
            return
        # 收集所有 .md 文件
        all_files = []
        for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
            for f in files:
                if f.endswith('.md'):
                    all_files.append(os.path.join(root, f))
        if len(all_files) < 2:
            return  # 太少了，没必要查
        
        import random as _random
        sample_size = min(KNOWLEDGE_REVIEW_SAMPLE_SIZE, len(all_files))
        samples = _random.sample(all_files, sample_size)
        
        log(f"📚 知识库定期审查: 共{len(all_files)}个归档，抽查{sample_size}个...", "KB")
        
        quarantined = 0
        for file_path in samples:
            try:
                rel = os.path.relpath(file_path, KNOWLEDGE_BASE_DIR)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # 提取标题（第一行 # 或 **标题** 字段）
                title_match = re.search(r'(?:^#\s*|-\s*\*\*标题\*\*:\s*)(.+)', content, re.MULTILINE)
                if not title_match:
                    title_match = re.search(r'\[(BV[0-9A-Za-z]+)\]\s*-\s*(.+)', rel)
                if not title_match:
                    continue
                title = title_match.group(1) if 'BV' in title_match.group(1)[:2] else title_match.group(2) if title_match.lastindex >= 2 else title_match.group(1)
                # 二次提取：如果是BV号匹配，取第二个捕获组
                if title.startswith('BV'):
                    _m2 = re.search(r'\[BV[0-9A-Za-z]+\]\s*-\s*(.+)', rel)
                    if _m2:
                        title = _m2.group(1)
                
                # 提取AI总结部分
                summary = ""
                sum_match = re.search(r'##\s*\[BRAIN\]\s*AI内容总结\s*\n+(.*?)(?:\n##\s|\Z)', content, re.DOTALL)
                if sum_match:
                    summary = sum_match.group(1).strip()[:2000]
                else:
                    # 回退：取文件后半部分（跳过元数据头）
                    header_end = content.find('## [BRAIN]')
                    if header_end > 0:
                        summary = content[header_end:][:2000]
                    else:
                        summary = content[-2000:]
                
                if not summary or len(summary) < 50:
                    log(f"  ⏭️ 跳过审查（无有效内容）: {rel}", "KB")
                    continue
                
                # AI验证
                is_match, conf, reason = await self._ai_verify_subtitle_content(
                    title=title, subtitle_text=summary, video_desc=""
                )
                
                if not is_match and conf >= 0.75:
                    log(f"  ❌ 知识库垃圾条目: conf={conf:.2f} | {reason} | {rel}", "KB")
                    # 标记文件：文件名前加 [待审查]
                    dir_name = os.path.dirname(file_path)
                    base_name = os.path.basename(file_path)
                    if not base_name.startswith('[待审查]'):
                        new_name = f"[待审查] {base_name}"
                        new_path = os.path.join(dir_name, new_name)
                        try:
                            os.rename(file_path, new_path)
                            log(f"    → 已标记: {os.path.relpath(new_path, KNOWLEDGE_BASE_DIR)}", "KB")
                            quarantined += 1
                        except OSError as re_e:
                            log(f"    → 重命名失败: {re_e}", "WARN")
                elif not is_match:
                    log(f"  ⚠️ 知识库可疑条目(低置信): conf={conf:.2f} | {reason} | {rel}", "KB")
                else:
                    log(f"  ✅ 知识库条目正常: conf={conf:.2f} | {reason} | {rel}", "KB")
                    
            except Exception as e:
                log(f"  ⚠️ 审查单条失败: {e}", "KB")
        
        if quarantined > 0:
            log(f"📚 知识库审查完成: 已标记 {quarantined} 个垃圾条目（文件名前缀[待审查]），请人工复核后删除", "KB")
        else:
            log(f"📚 知识库审查完成: 抽查 {sample_size} 个条目全部通过", "KB")

    async def _download_video_for_asr(self, bvid):
        """为ASR下载视频（完全对齐video_modes.py的下载逻辑：http2/Origin/Referer/长超时）"""
        try:
            import tempfile, hashlib as _h, time as _t
            referer = f'https://www.bilibili.com/video/{bvid}'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': referer,
                'Origin': 'https://www.bilibili.com',
            }
            async with httpx.AsyncClient(
                http2=True,
                headers=headers, cookies=self.cookies,
                timeout=90.0, follow_redirects=True
            ) as client:
                # [FIX] WBI签名：独立获取，不依赖 self.bili._wbi_keys 避免 AttributeError
                wkeys = None
                try:
                    nav = await client.get('https://api.bilibili.com/x/web-interface/nav')
                    nd = nav.json()
                    if nd.get('code') == 0:
                        wi = nd['data'].get('wbi_img', {})
                        im = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get('img_url', ''))
                        sm = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get('sub_url', ''))
                        if im and sm:
                            wkeys = (im.group(1), sm.group(1))
                            # 顺便缓存到 bili 实例（如果可用）
                            bili = getattr(self, 'bili', None)
                            if bili and hasattr(bili, '_wbi_keys'):
                                try:
                                    bili._wbi_keys = wkeys
                                    bili._wbi_keys_ts = time.time()
                                except Exception as e:
                                    log(f'非预期异常: {e}', 'WARN')
                except Exception as e:
                    log(f"[WARN] ASR下载WBI密钥获取失败: {e}", "WARN")

                params = {'bvid': bvid}
                if wkeys:
                    wts = int(_t.time())
                    sp = dict(params)
                    sp['wts'] = wts
                    si = sorted(sp.items(), key=lambda x: x[0])
                    qs = '&'.join(f'{k}={v}' for k, v in si)
                    sp['w_rid'] = _h.md5((qs + wkeys[0] + wkeys[1]).encode()).hexdigest()
                    params = sp

                v_res = await client.get('https://api.bilibili.com/x/web-interface/view', params=params)
                v_data = v_res.json()
                if v_data.get('code') != 0:
                    return None
                info = v_data['data']
                cid = info.get('cid', 0)

                # 获取视频流
                play_params = {'bvid': bvid, 'cid': cid, 'qn': 32, 'fnval': 0, 'fourk': 0}
                if wkeys:
                    wts = int(_t.time())
                    sp = dict(play_params)
                    sp['wts'] = wts
                    si = sorted(sp.items(), key=lambda x: x[0])
                    qs = '&'.join(f'{k}={v}' for k, v in si)
                    sp['w_rid'] = _h.md5((qs + wkeys[0] + wkeys[1]).encode()).hexdigest()
                    play_params = sp
                play = await client.get(
                    'https://api.bilibili.com/x/player/playurl',
                    params=play_params
                )
                play_data = play.json()
                durls = play_data.get('data', {}).get('durl', [])
                if not durls:
                    return None
                video_url = durls[0]['url']

                # 下载
                out_dir = os.path.join(tempfile.gettempdir(), "bilibili_asr", bvid)
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, f"{bvid}.mp4")

                async with client.stream("GET", video_url, headers=headers) as resp:
                    resp.raise_for_status()
                    with open(out_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(1024 * 256):
                            f.write(chunk)

                return out_path
        except Exception as e:
            log(f"ASR视频下载失败: {e}", "WARN")
            return None

    async def analyze_vision(self, pic_url):
        if not pic_url: return "无封面", 0
        if not VISION_COVER_ENABLED: return "封面分析已关闭", 0
        if self._is_ai_degraded(): return "AI降级,跳过", 0
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_VISION,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_VISION},
                    {"role": "user", "content": [
                        {"type": "text", "text": "评价"},
                        {"type": "image_url", "image_url": {"url": pic_url}}
                    ]}
                ],
                request_timeout=90
            )
            content = resp.choices[0].message.content
            score = 5.0
            if "Score:" in content:
                try:
                    parts = content.split("Score:")
                    desc = parts[0].strip()[:15]
                    score = float(parts[1].strip())
                except (ValueError, IndexError):
                    desc = content[:15]
            else:
                desc = content[:15]
            return desc, score
        except Exception as e:
            log(f"封面分析失败(已重试): {_mask_urls(str(e)[:80])}", "WARN")
            return "分析失败", 0

    async def judge_interest_with_ai(self, title, up, vis_desc, vis_score):
        interests = self.interest_mgr.get_interests()
        if not interests:
            return True, [], "未设置兴趣，默认通过"

        matched = self.interest_mgr.get_matching_interests(title, up)
        if matched:
            return True, matched, f"关键词匹配: {', '.join(matched)}"

        prompt = f"""
请判断这个B站视频是否符合用户兴趣。

用户兴趣: {", ".join(interests)}
视频标题: {title}
UP主: {up}
封面印象: {vis_desc}
封面印象分: {vis_score}

要求:
1. 综合标题、UP主、封面印象判断，不要只做关键词匹配。
2. 只输出JSON，格式为:
{{"interested": true, "matched": ["兴趣1"], "reason": "一句话理由"}}
3. 如果明显不相关，interested=false，matched=[]。
"""
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": "你是B站视频兴趣筛选器，只输出合法JSON。"},
                    {"role": "user", "content": prompt}
                ],
                request_timeout=90
            )
            raw = resp.choices[0].message.content.strip()
            # [FIX] 多策略JSON提取：嵌套匹配 + rfind兜底
            start = raw.find("{")
            json_str = raw
            if start >= 0:
                # 嵌套匹配找闭合的 }
                depth = 0
                match_end = -1
                for i in range(start, len(raw)):
                    if raw[i] == '{':
                        depth += 1
                    elif raw[i] == '}':
                        depth -= 1
                        if depth == 0:
                            match_end = i
                            break
                if match_end >= 0:
                    json_str = raw[start:match_end + 1]
                else:
                    end = raw.rfind("}")
                    if end >= start:
                        json_str = raw[start:end + 1]
            # ── 修复模型偶尔用单引号/不规范JSON的错误 ──
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # 尝试修复常见问题：单引号→双引号
                fixed = json_str.replace("'", '"')
                # 修复 True/False/None 大小写（replace单引号后可能被误改）
                fixed = re.sub(r'\bTrue\b', 'true', fixed)
                fixed = re.sub(r'\bFalse\b', 'false', fixed)
                fixed = re.sub(r'\bNone\b', 'null', fixed)
                data = json.loads(fixed)
            ai_matched = data.get("matched") or []
            if isinstance(ai_matched, str):
                ai_matched = [ai_matched]
            reason = str(data.get("reason") or "AI综合判断")
            return bool(data.get("interested")), ai_matched, reason
        except Exception as e:
            log(f"AI兴趣判断失败(已重试)，退回关键词判断: {str(e)[:80]}", "WARN")
            return False, [], "关键词未匹配"

    async def _get_comments_context(self, aid: int):
        c_list_raw = await self.bili.get_hot_comments(aid, limit=8)
        if not c_list_raw: return "暂无评论", []

        # [SPEED] 两阶段并行：先收集所有评论基本信息，再并行分析图片
        comment_entries = []
        image_tasks = []
        for i, c in enumerate(c_list_raw):
            try:
                cid, user, msg = c['rpid'], c['member']['uname'], c['content']['message']
                entry = {"cid": cid, "user": user, "content": msg, "pic_info": ""}
                if VISION_COMMENT_IMAGES_ENABLED:
                    pictures = c.get('content', {}).get('pictures', [])
                    if pictures:
                        img_urls = [p.get('img_src', '') for p in pictures[:3] if p.get('img_src')]
                        if img_urls:
                            image_tasks.append(self._analyze_comment_images(cid, img_urls, user_msg=msg))
                            entry["_img_idx"] = len(image_tasks) - 1
                comment_entries.append(entry)
            except (KeyError, TypeError):
                continue

        # 并行分析所有评论图片
        pic_results = await asyncio.gather(*image_tasks, return_exceptions=True) if image_tasks else []

        # 组装结果
        context_str = "【热门评论】:\n"
        c_list_clean = []
        for entry in comment_entries:
            cid, user, msg = entry["cid"], entry["user"], entry["content"]
            pic_info = ""
            if "_img_idx" in entry:
                result = pic_results[entry["_img_idx"]]
                if isinstance(result, str) and result:
                    pic_info = f" [附图描述: {result}]"
            context_str += f"ID:{cid} User:{user} Msg:{msg}{pic_info}\n"
            c_list_clean.append({"id": cid, "user": user, "content": msg, "pic_info": pic_info.strip()})
        return context_str, c_list_clean

    async def _analyze_comment_images(self, cid, img_urls, user_msg=""):
        """[VISION] 下载评论文图片并用视觉AI描述，同时展示评论文字+图片"""
        if not img_urls or self._is_ai_degraded():
            return ""
        max_images = min(len(img_urls), VISION_MAX_COMMENT_IMAGES)
        import httpx as _httpx, base64 as _b64

        async def _dl_and_analyze(idx, url):
            try:
                async with _httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    r = await client.get(url, headers={
                        'User-Agent': 'Mozilla/5.0',
                        'Referer': 'https://www.bilibili.com'
                    })
                    if r.status_code != 200:
                        return None
                    data_url = "data:image/jpeg;base64," + _b64.b64encode(r.content).decode("ascii")
                resp = await self._call_ai_with_retry(
                    model=MODEL_VISION,
                    messages=[{
                        "role": "system",
                        "content": "你是评论图片分析助手。用一句简短中文描述图片内容（是什么类型的图、主要内容、情绪倾向）。"
                    }, {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "描述这张评论区的图片"},
                            {"type": "image_url", "image_url": {"url": data_url}}
                        ]
                    }],
                    request_timeout=20
                )
                desc = resp.choices[0].message.content.strip()[:80]
                return f"[图{idx+1}]{desc}"
            except Exception as e:
                log(f"评论图片分析失败(cid={cid} img{idx}): {e}", "DEBUG")
                return None

        # [SPEED] 并行下载+分析所有图片
        tasks = [_dl_and_analyze(i, url) for i, url in enumerate(img_urls[:max_images])]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        analyzed = [r for r in results if isinstance(r, str)]
        if analyzed:
            msg_preview = user_msg[:40] + "..." if len(user_msg) > 40 else user_msg
            log(f"[EYE] 评论({msg_preview}) + 附图({len(analyzed)}张): {'; '.join(analyzed)}", "EYE")
        return "; ".join(analyzed)

    async def watch_and_sync_history(self, bvid):
        sec = random.uniform(VIDEO_INTERVAL_MIN, VIDEO_INTERVAL_MAX)
        log(f"短暂休息 {sec:.1f} 秒后继续...", "INFO")
        try:
            res = await self.bili.report_history(bvid, played_time=random.randint(60,120))
            if res.get('code') == 0:
                log("已同步观看历史 (手机可见)", "NOTE")
            else:
                log(f"历史记录同步失败: {res.get('message')}", "WARN")
        except Exception as e:
            log(f"上报历史时异常: {e}", "ERROR")

        await asyncio.sleep(sec)

    async def energy_recovery_session(self):
        log(f"精力耗尽 ({self.energy}%)，进入恢复模式... [FAST]", "ENERGY")

        recovery_rounds = random.randint(ROUNDS_MIN, ROUNDS_MAX)
        log(f"预计恢复 {recovery_rounds} 轮，请耐心等待...", "ENERGY")

        for round_num in range(1, recovery_rounds + 1):
            energy_gain = random.randint(ENERGY_RECOVERY_MIN, ENERGY_RECOVERY_MAX)
            self.energy = min(MAX_ENERGY, self.energy + energy_gain)

            round_interval = random.randint(ROUND_INTERVAL_MIN, ROUND_INTERVAL_MAX)

            log(f"第 {round_num}/{recovery_rounds} 轮恢复: +{energy_gain}% → {self.energy}% (等待{round_interval}秒)", "ENERGY")

            if round_num < recovery_rounds:
                # [SPEED] 一次性睡眠替代逐10秒循环
                log(f"下次恢复倒计时: {round_interval}秒...", "ENERGY")
                await asyncio.sleep(round_interval)

            self.last_energy_recovery = datetime.now()

        log(f"恢复完成！当前精力: {self.energy}%，准备继续工作！", "SUCCESS")

    async def check_and_handle_comments(self):
        """检查并处理新评论，返回处理数量"""
        if not COMMENT_CHECK_ENABLED:
            return 0
        if not self.comment_mgr:
            return 0
        
        now = datetime.now()
        if self.last_comment_check and (now - self.last_comment_check).total_seconds() < COMMENT_CHECK_INTERVAL:
            return 0
        
        try:
            processed = await self.comment_mgr.process_new_comments(self.bili)
            if processed > 0:
                log(f"本次处理了 {processed} 条评论互动", "COMMENT")
                # 消耗精力
                self.energy -= processed
                if self.energy < 0:
                    self.energy = 0
                log(f"评论互动消耗 {processed} 点精力，剩余: {self.energy}%", "ENERGY")
            return processed
        except Exception as e:
            log(f"检查评论失败: {e}", "ERROR")
            return 0
        finally:
            self.last_comment_check = now

    async def check_and_handle_private_messages(self):
        """检查并处理新私信"""
        if not PRIVATE_MESSAGE_ENABLED:
            return 0

        now = datetime.now()
        if self.last_private_message_check and (now - self.last_private_message_check).total_seconds() < PRIVATE_MESSAGE_CHECK_INTERVAL:
            return 0

        if not self.private_message_mgr:
            return 0

        try:
            processed = await self.private_message_mgr.process_new_messages()
            if processed > 0:
                log(f"本次处理了 {processed} 条私信", "DM")
            return processed
        except Exception as e:
            log(f"检查私信失败: {e}", "ERROR")
            return 0
        finally:
            self.last_private_message_check = now

    async def maybe_initiate_chat(self):
        """[MSG] 偶尔主动找人聊天（学而时习之的社交版）。"""
        if not ACTIVE_CHAT_ENABLED:
            return
        if not PRIVATE_MESSAGE_ENABLED or not PRIVATE_MESSAGE_AUTO_REPLY:
            return
        if not self.private_message_mgr:
            return
        if self._active_chat_count >= ACTIVE_CHAT_MAX_PER_SESSION:
            return
        cooldown_ok = (datetime.now() - self._last_active_chat_at).total_seconds() / 60 >= ACTIVE_CHAT_COOLDOWN_MINUTES
        if not cooldown_ok:
            return
        # [FIX] 时间段守卫：深夜/凌晨不主动打扰别人（23:00-07:00）
        hour = datetime.now().hour
        if hour >= 23 or hour < 7:
            return
        if random.random() >= PROB_INITIATE_CHAT:
            return

        try:
            # 随机从关注/粉丝列表里挑一个人
            target_uid = None
            target_name = ""
            try:
                # 优先从粉丝里找
                followers = await self.private_message_mgr.toolbox.followers_search("", limit=20)
                if followers and isinstance(followers, list) and len(followers) > 0:
                    pick = random.choice(followers)
                    target_uid = int(pick.get("mid") or 0)
                    target_name = str(pick.get("name", ""))
            except Exception as e:
                log(f"[WARN] 获取粉丝列表失败: {e}", "WARN")
            if not target_uid:
                try:
                    followings = await self.private_message_mgr.toolbox.followings_search("", limit=20)
                    if followings and isinstance(followings, list) and len(followings) > 0:
                        pick = random.choice(followings)
                        target_uid = int(pick.get("mid") or 0)
                        target_name = str(pick.get("name", ""))
                except Exception as e:
                    log(f"[WARN] 获取关注列表失败: {e}", "WARN")
            if not target_uid or target_uid == self.bili.uid:
                return

            self._active_chat_count += 1
            self._last_active_chat_at = datetime.now()
            log(f"[MSG] 主动找 @{target_name}(uid:{target_uid}) 聊聊天... (第{self._active_chat_count}次)", "CHAT")

            # ── 🔍 先看对方主页：拉取个人信息 + 最近投稿 ──
            target_profile = {}
            target_videos = []
            try:
                target_profile = await self.bili.get_up_info(target_uid) or {}
                if not target_profile.get("error"):
                    log(f"   📋 {target_name} 主页: Lv.{target_profile.get('level',0)} "
                        f"签名={str(target_profile.get('sign',''))[:40]}", "DEBUG")
            except Exception as e:
                log(f"   [WARN] 无法获取 {target_name} 主页: {e}", "DEBUG")

            try:
                target_videos = await self.bili.get_up_videos(target_uid, limit=5) or []
                if target_videos:
                    titles = [v.get("title","")[:40] for v in target_videos[:3]]
                    log(f"   [VIDEO] {target_name} 最近投稿: {'; '.join(titles)}", "DEBUG")
            except Exception as e:
                log(f"   [WARN] 无法获取 {target_name} 视频: {e}", "DEBUG")

            # 构建目标用户画像
            target_sign = str(target_profile.get("sign", "")).strip()
            target_level = target_profile.get("level", 0)
            target_follower = target_profile.get("follower", 0)
            target_video_count = target_profile.get("video_count", 0)

            video_summary = ""
            if target_videos:
                video_summary = "对方最近投稿: " + "；".join(
                    [v.get("title","")[:50] for v in target_videos[:5]]
                )

            target_profile_block = f"""【目标用户主页信息】
用户名: {target_name}
个性签名: {target_sign if target_sign else "（无）"}
B站等级: Lv.{target_level}
粉丝数: {target_follower}
投稿数: {target_video_count}
{video_summary if video_summary else "（未拉取到投稿信息）"}
"""

            # 生成开场白
            interests = self.interest_mgr.get_interests()
            interest_str = "、".join(interests[:5]) if interests else "随便聊聊"
            persona_block = self.persona_mgr.build_prompt_block()
            mood_block = self.mood_mgr.build_prompt_block()

            prompt = f"""
你要给B站上的一个用户「{target_name}」发一条初次私信打招呼。
这是主动发起聊天，不是回复别人的消息。

{persona_block}
{mood_block}
你的兴趣: {interest_str}
{target_profile_block}
当前时间: {datetime.now().isoformat(timespec='seconds')}

要求：
1. 自然、轻松、不油腻，像普通B站用户之间的寒暄
2. 🚫 不要聊你自己的兴趣爱好！先看看目标用户的签名和投稿内容——
   - 如果对方投稿了具体领域的视频（游戏/动画/科技/音乐等），围绕对方的创作内容展开话题
   - 如果对方签名里有信息，可以顺着签名聊
   - 只有当对方主页完全空白时，才简单聊聊日常
3. 不要太长，50字以内
4. 不要用客服腔、不要自来熟、不要"大佬""up主"之类刻意恭维
5. 禁止承诺做违法、刷量、侵权的事
6. 结尾带上"{config.get('behavior', {}).get('ai_marker', '（内容由AI生成并由AI回复）')}"
7. 如果看了对方主页实在不知道聊什么，返回空字符串

只返回要发送的内容，不要解释。
"""
            # [FIX] 用线程池异步执行，防止同步AI调用阻塞事件循环导致崩溃
            resp = await asyncio.to_thread(
                openai.ChatCompletion.create,
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": "你是B站上的一个普通用户。看了对方主页后再开口——围绕对方的投稿内容或签名展开话题。友好、有边界感、不油腻。"},
                    {"role": "user", "content": prompt}
                ],
                timeout=60
            )
            chat_text = resp.choices[0].message.content.strip()
            if not chat_text or chat_text.upper() == "END":
                log(f"AI判断不适合主动聊天 @{target_name}，跳过", "CHAT")
                return

            chat_text = ensure_ai_marker(chat_text)
            ok, reason, hits = ReplySafetyGuard().review("(主动发起聊天)", chat_text)
            if not ok:
                log(f"主动聊天内容被拦截: {reason} | 命中: {', '.join(hits)}", "WARN")
                return

            await asyncio.sleep(human_reply_delay())
            result = await self.private_message_mgr.send_reply(target_uid, chat_text)
            log(f"[MSG] 已主动发消息给 @{target_name}: {chat_text[:60]}", "CHAT")

            # 记录到日记
            self.record_session_event(
                "active_chat",
                target_uid=target_uid,
                target_name=target_name,
                content=chat_text[:120]
            )
        except Exception as e:
            log(f"主动聊天失败: {e}", "WARN")

    # ── [*] UP主关注（AI自动关注喜欢的UP主）───────────────────────────────
    def _reset_daily_follows(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.daily_follows_date != today:
            self.daily_follows = 0
            self.daily_follows_date = today

    def _reset_daily_danmaku_likes(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.daily_danmaku_likes_date != today:
            self.daily_danmaku_likes = 0
            self.daily_danmaku_likes_date = today

    def _reset_daily_danmaku_sent(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.daily_danmaku_sent_date != today:
            self.daily_danmaku_sent = 0
            self.daily_danmaku_sent_date = today

    async def maybe_follow_up(self, up_uid: int, up_name: str, score: float):
        """根据AI评分和印象积累决定是否关注UP主。
        
        关注即认可，不是抽奖——设计理念：
        1. 评分 ≥ UP_FOLLOW_MIN_SCORE（默认7分）才进入候选池
        2. 需积累 ≥ UP_FOLLOW_MIN_IMPRESSIONS 次正面印象（首次观看不计）
        3. 特别优秀（≥ UP_FOLLOW_EXCEPTIONAL_SCORE）可首看即关注
        4. 已关注的不重复关注（followed 标志）
        """
        if not UP_FOLLOW_ENABLED or not up_uid or not up_name:
            return False
        
        self._reset_daily_follows()
        if self.daily_follows >= UP_FOLLOW_MAX_DAILY:
            return False
        
        # 冷却检查
        cooldown_ok = (datetime.now() - self.last_follow_at).total_seconds() / 60 >= UP_FOLLOW_COOLDOWN_MINUTES
        if not cooldown_ok:
            return False
        
        # ── [*] 核心强化：评分门槛 ──
        # 不得因概率到了就关注评分平庸的 UP
        exceptional = score >= UP_FOLLOW_EXCEPTIONAL_SCORE
        if not exceptional and score < UP_FOLLOW_MIN_SCORE:
            return False  # 评分不达标，直接拒绝
        
        # ── [*] 核心强化：已关注不重复 ──
        up_entry = self.memory.setdefault("known_ups", {}).get(up_name, {})
        if up_entry.get("followed"):
            return False  # 已关注过
        
        # ── [*] 核心强化：印象积累 ──
        views = up_entry.get("views", 0)
        avg_score = up_entry.get("avg_score", score)
        if not exceptional and views < UP_FOLLOW_MIN_IMPRESSIONS:
            # 看的次数不够，不关注（但记录印象）
            return False
        
        # ── 概率计算 ──
        # 基础概率 × 评分因子 × 印象奖励（看得越多越可能关注，但有上限）
        score_factor = min(score / 5.0, 2.0) if score > 0 else 1.0
        impression_bonus = min(views / max(UP_FOLLOW_MIN_IMPRESSIONS, 1), 2.0)
        adjusted_prob = UP_FOLLOW_AUTO_PROB * score_factor * impression_bonus
        if not exceptional and random.random() >= adjusted_prob:
            return False
        
        try:
            avg_str = f", 均分:{avg_score:.1f}" if views else ""
            log(f"[*] 正在关注 UP主 @{up_name} (UID:{up_uid})... (评分:{score}, 观看{views}次{avg_str}, 概率:{adjusted_prob:.3f})", "FOLLOW")
            result = await self.bili.follow_up(up_uid)
            if result.get("code") == 0:
                self.daily_follows += 1
                self.last_follow_at = datetime.now()
                # 设置 followed 标志
                up_entry["followed"] = True
                up_entry["followed_at"] = datetime.now().isoformat()
                if not up_entry.get("uid"):
                    up_entry["uid"] = up_uid
                self._save_memory()
                log(f"[OK] 已关注 UP主 @{up_name}！今日已关注 {self.daily_follows}/{UP_FOLLOW_MAX_DAILY}", "SUCCESS")
                self.record_session_event("follow_up", up_uid=up_uid, up_name=up_name, score=score, views=views, avg_score=round(avg_score, 1) if views else score)
                return True
            elif result.get("code") == 22014:
                # 已经关注过（比如之前网页/App上关注的），同步本地内存即可
                up_entry["followed"] = True
                if not up_entry.get("uid"):
                    up_entry["uid"] = up_uid
                self._save_memory()
                log(f"已关注过 UP主 @{up_name} (之前已关注，已同步记录)", "INFO")
                return True
            else:
                log(f"关注失败: {result.get('msg')}", "WARN")
        except Exception as e:
            log(f"关注 UP主异常: {e}", "WARN")
        return False

    async def maybe_browse_up_videos(self, force_up_uid=None, up_name_hint=None):
        """浏览UP主的主页视频，优先浏览喜欢的UP主，可作为推荐流替代目标。
        
        Returns: 单个视频dict（格式兼容主循环target）或 None
        """
        if not UP_FOLLOW_ENABLED:
            return None
        
        # 冷却检查（force_up_uid 可跳过冷却）
        elapsed = (datetime.now() - self.last_up_browse_at).total_seconds() / 60
        if elapsed < UP_FOLLOW_COOLDOWN_MINUTES and not force_up_uid:
            return None
        
        target_uid = force_up_uid
        chosen_up_name = up_name_hint
        is_favorite = False
        
        if not target_uid:
            # ── [*] 优先浏览喜欢的UP主（更高概率）──
            favorite_ups = self.get_favorite_ups()
            if favorite_ups and random.random() < UP_FOLLOW_FAVORITE_PROB:
                fav = random.choice(favorite_ups)
                fav_uid = fav.get("uid")
                if fav_uid:
                    target_uid = int(fav_uid)
                    chosen_up_name = fav.get("name")
                    is_favorite = True
                # 也检查全局配置中的喜爱UID列表
                elif UP_FOLLOW_FAVORITE_UID_LIST and len(UP_FOLLOW_FAVORITE_UID_LIST) > 0:
                    target_uid = random.choice(UP_FOLLOW_FAVORITE_UID_LIST)
                    is_favorite = True
            
            # 回退：随机浏览已知UP主
            if not target_uid:
                if random.random() >= UP_FOLLOW_BROWSE_PROB:
                    return None
                known_ups = self.memory.get("known_ups", {})
                if not known_ups:
                    return None
                # 随机选择一个已关注的UP主
                chosen_up_name = random.choice(list(known_ups.keys()))
                uid_from_mem = known_ups.get(chosen_up_name, {}).get("uid")
                if uid_from_mem:
                    target_uid = int(uid_from_mem)
                else:
                    # 尝试从user_profile获取UID
                    profile = self.user_profile_mgr.get_profile(f"up::{chosen_up_name}")
                    if profile and profile.get("uid"):
                        target_uid = int(profile["uid"])
                    else:
                        return None
            
            if not target_uid:
                return None
        
        self.last_up_browse_at = datetime.now()
        tag = "[STAR]喜爱" if is_favorite else "📺"
        log(f"{tag} 浏览 UP主 {'@'+chosen_up_name if chosen_up_name else ''} (UID:{target_uid}) 的主页视频...", "BROWSE")
        
        try:
            videos = await self.bili.get_up_videos(target_uid, limit=UP_FOLLOW_MAX_BROWSE)
            if videos:
                log(f"获取到 {len(videos)} 个视频:", "BROWSE")
                for v in videos:
                    log(f"  • {v.get('title','')[:40]} | 播放:{v.get('play',0)}", "BROWSE")
                # 返回一个随机视频作为可用的目标
                chosen = random.choice(videos)
                return {
                    "bvid": chosen.get("bvid", ""),
                    "title": chosen.get("title", ""),
                    "owner": {"name": chosen_up_name or "", "mid": target_uid},
                    "id": chosen.get("aid", 0),
                    "aid": chosen.get("aid", 0),
                    "pic": chosen.get("pic", ""),
                    "_source": "up_browse",
                    "_is_favorite_up": is_favorite
                }
            else:
                log("该UP主暂无视频或获取失败", "INFO")
        except Exception as e:
            log(f"浏览UP主视频异常: {e}", "WARN")
        return None

    # ── [MSG] 弹幕互动 ──────────────────────────────────────────────────
    async def maybe_read_danmaku(self, bvid: str, force: bool = False):
        """读取视频弹幕，融入AI决策上下文。
        
        Args:
            bvid: 视频BV号
            force: 为True时跳过概率门控，强制读取（手动分析模式使用）
        """
        if not DANMAKU_ENABLED or not bvid:
            return []
        
        if not force and random.random() >= DANMAKU_READ_PROB:
            return []
        
        try:
            log("[MSG] 正在读取弹幕...", "DANMAKU")
            cid, danmaku_list = await self.bili.get_danmakus(bvid, limit=30)
            if danmaku_list:
                self._last_danmaku_videos[bvid] = danmaku_list
                self._last_danmaku_cids[bvid] = cid
                # 清理旧缓存（保留最近10个视频的弹幕）
                if len(self._last_danmaku_videos) > 10:
                    oldest = list(self._last_danmaku_videos.keys())[0]
                    del self._last_danmaku_videos[oldest]
                
                log(f"读取到 {len(danmaku_list)} 条弹幕 (cid={cid})", "DANMAKU")
                # 显示几条代表性弹幕
                for dm in danmaku_list[:5]:
                    log(f"  弹幕: {dm.get('text','')[:40]}", "DANMAKU")
                
                # 同时触发点赞和发送
                await self.maybe_like_danmaku(bvid, danmaku_list, cid)
                await self.maybe_send_danmaku(bvid)
                return danmaku_list
        except Exception as e:
            log(f"读取弹幕异常: {e}", "WARN")
        return []

    async def maybe_like_danmaku(self, bvid: str, danmaku_list: list, cid: int = 0):
        """对有趣的弹幕进行点赞。cid 由 get_danmakus 返回。"""
        if not DANMAKU_ENABLED or not danmaku_list:
            return False
        
        if random.random() >= DANMAKU_LIKE_PROB:
            return False
        
        self._reset_daily_danmaku_likes()
        if self.daily_danmaku_likes >= DANMAKU_MAX_DAILY_LIKES:
            return False
        
        if not cid:
            # 降级尝试从缓存获取 cid
            cid = self._last_danmaku_cids.get(bvid, 0)
        if not cid:
            return False
        
        try:
            # 随机选一条弹幕点赞（必须用 id_str 字符串ID）
            target_dm = random.choice(danmaku_list)
            dm_id_str = target_dm.get("id_str", "")
            dm_text = target_dm.get("text", "")
            if not dm_id_str:
                return False
            
            log(f"👍 点赞弹幕: {dm_text[:30]}... (id_str={dm_id_str[:16]}...)", "DANMAKU")
            result = await self.bili.like_danmaku(dmid=dm_id_str, cid=cid, bvid=bvid)
            if result.get("code") == 0:
                self.daily_danmaku_likes += 1
                log(f"弹幕点赞成功！今日已赞 {self.daily_danmaku_likes}/{DANMAKU_MAX_DAILY_LIKES}", "SUCCESS")
                return True
            else:
                log(f"弹幕点赞未成功: {result.get('msg')}", "INFO")
        except Exception as e:
            log(f"弹幕点赞异常: {e}", "WARN")
        return False

    async def maybe_send_danmaku(self, bvid: str, title: str = "", subtitle_text: str = ""):
        """生成并发送一条B站风格弹幕。"""
        if not DANMAKU_ENABLED or not bvid:
            return False
        
        if random.random() >= DANMAKU_SEND_PROB:
            return False
        
        self._reset_daily_danmaku_sent()
        if self.daily_danmaku_sent >= DANMAKU_MAX_DAILY_SEND:
            return False
        
        try:
            # 用AI生成一条弹幕
            context = f"视频标题: {title}\n视频内容摘要: {subtitle_text[:200] if subtitle_text and '[未读取' not in subtitle_text else '未知'}"
            persona_block = self.persona_mgr.build_prompt_block()
            
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": f"你是B站上的一个普通观众。{persona_block}请根据视频内容发送一条弹幕。要求：1. 简短（20字以内）2. 符合B站弹幕风格 3. 有趣或表达到位 4. 不要发送引战、敏感内容。只返回弹幕文字，不要解释。"},
                    {"role": "user", "content": f"为这个视频发一条弹幕: {context}"}
                ],
                max_tokens=50,
                request_timeout=60
            )
            dm_text = resp.choices[0].message.content.strip()
            if not dm_text or len(dm_text) > 50:
                return False
            
            log(f"📤 发送弹幕: {dm_text}", "DANMAKU")
            result = await self.bili.send_danmaku(bvid, dm_text)
            if result.get("code") == 0:
                self.daily_danmaku_sent += 1
                log(f"弹幕发送成功！今日已发 {self.daily_danmaku_sent}/{DANMAKU_MAX_DAILY_SEND}", "SUCCESS")
                self.record_session_event("send_danmaku", bvid=bvid, text=dm_text)
                return True
            else:
                log(f"弹幕发送失败: {result.get('msg')}", "WARN")
        except Exception as e:
            log(f"弹幕发送异常: {e}", "WARN")
        return False

    async def initialize_login(self):
        self.bili.credential = self.bili._load_credential()

        # 有 cookie 文件直接加载，跳过网络验证，秒进
        if self.bili.credential and os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                self.cookies = json.load(f)
            self.credential = self.bili.credential
            try:
                self.bili.uid = int(self.cookies.get("DedeUserID", 0))
            except Exception:
                self.bili.uid = 0
            log(f"登录已就绪 (UID: {self.bili.uid})", "SUCCESS")
            self._init_psycho_engine()
            self.comment_mgr = CommentInteractionManager(self.credential, self.bili.uid, since_ts=self.previous_seen_ts)
            self.private_message_mgr = PrivateMessageManager(
                self.credential,
                self.bili.uid,
                since_ts=self.previous_seen_ts,
                previous_seen_at=self.previous_seen_at
            )
            return True

        # 没有 cookie → 走完整登录流程
        log("需要登录B站账号", "LOGIN")
        print("\n" + "="*50)
        print("           B站登录向导")
        print("="*50)

        login_success = await login_bilibili()
        if not login_success:
            log("登录失败，程序退出", "ERROR")
            return False

        self.bili.credential = self.bili._load_credential()
        if not self.bili.credential:
            log("登录后加载凭据失败", "ERROR")
            return False

        login_success = await self.bili.init_user_info()
        if not login_success:
            log("登录验证失败", "ERROR")
            return False

        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            self.cookies = json.load(f)

        self.credential = Credential(
            sessdata=self.cookies.get("SESSDATA"),
            bili_jct=self.cookies.get("bili_jct"),
            buvid3=self.cookies.get("buvid3"),
            dedeuserid=self.cookies.get("DedeUserID"),
        )
        
        # 初始化评论管理器
        self._init_psycho_engine()
        self.comment_mgr = CommentInteractionManager(self.credential, self.bili.uid, since_ts=self.previous_seen_ts)
        self.private_message_mgr = PrivateMessageManager(
            self.credential,
            self.bili.uid,
            since_ts=self.previous_seen_ts,
            previous_seen_at=self.previous_seen_at
        )

        log("登录完成，准备开始工作！", "SUCCESS")
        return True

    def _init_psycho_engine(self):
        """初始化心理画像引擎（登录后调用）
        
        即使 PSYCHO_ENGINE_ENABLED=False，也会初始化基础追踪和避雷系统，
        只是跳过 AI 深度分析和智能推荐。
        """
        try:
            self.psycho_profile = PsychoProfile(ai_caller=self._psycho_ai_caller if PSYCHO_ENGINE_ENABLED else None)
            self.recommend_engine = RecommendationEngine(
                psycho_profile=self.psycho_profile,
                ai_caller=self._psycho_ai_caller if PSYCHO_ENGINE_ENABLED else None,
            )
            status = "[PSYCHO]已激活" if PSYCHO_ENGINE_ENABLED else "[NOTE]仅追踪(无AI分析)"
            log(f"智能分析系统 {status} | 多维度追踪已激活", "SUCCESS")
        except Exception as e:
            log(f"智能分析系统初始化失败: {e}", "ERROR")
            self.psycho_profile = None
            self.recommend_engine = None

    async def run(self):
        # 🔒 单实例锁：防止多个 bot 进程同时运行
        if not _acquire_bot_lock():
            log("[LOCK] ❌ 已有 bot 实例正在运行，退出", "ERROR")
            return
        log("[LOCK] ✅ 单实例锁已获取", "INFO")
        
        log("bilibili_learning_bot - 启动...", "SUCCESS")
        self.update_runtime_clock(starting=True)
        if self.previous_seen_at:
            log(f"上次运行最后记录时间: {self.previous_seen_at}，本次只处理之后的新评论/私信", "INFO")

        os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
        log(f"知识库模块已加载，路径: {KNOWLEDGE_BASE_DIR}", "INFO")
        
        # 显示兴趣状态
        interests = self.interest_mgr.get_interests()
        if interests:
            log(f"兴趣列表: {', '.join(interests)}", "INTEREST")
        else:
            log("兴趣列表为空，将对所有视频感兴趣", "INTEREST")
        log(f"当前人格: {self.persona_mgr.get_active_persona()} | 当前心情: {self.mood_mgr.get_current()}", "INFO")
        
        print(f"\n{Fore.CYAN}知识库分类系统已初始化:{Style.RESET_ALL}")
        self.classifier.show_category_structure()
        # 启动时清理空文件夹
        cleaned = self.classifier.cleanup_empty_folders()
        if cleaned > 0:
            log(f"已清理 {cleaned} 个空文件夹", "KB")

        login_success = await self.initialize_login()
        if not login_success:
            log("登录失败，程序退出", "ERROR")
            return

        log(f"初始化完成 | 最大精力: {MAX_ENERGY}% | 视频间隔: {VIDEO_INTERVAL_MIN}-{VIDEO_INTERVAL_MAX}秒", "INFO")
        if SESSION_MAX_VIDEOS > 0:
            log(f"会话限制: 最多处理 {SESSION_MAX_VIDEOS} 个视频后自动停止", "SESSION")
        if SESSION_MAX_DURATION_MINUTES > 0:
            log(f"会话限制: 最长运行 {SESSION_MAX_DURATION_MINUTES} 分钟后自动停止", "SESSION")
        log(f"评论互动: {'已启用' if COMMENT_CHECK_ENABLED else '⏸️ 已关闭'} | 检查间隔: {COMMENT_CHECK_INTERVAL}秒", "COMMENT")
        log(f"私信互动: {'已启用' if PRIVATE_MESSAGE_ENABLED else '⏸️ 已关闭'} | {'自动发送' if PRIVATE_MESSAGE_AUTO_REPLY else '仅拟不发送'} | 检查间隔: {PRIVATE_MESSAGE_CHECK_INTERVAL}秒", "DM")
        log(f"日记: {'自动' if DIARY_ENABLED and DIARY_AUTO_ENABLED else '手动/关闭'} | 自我进化: {'自动应用' if EVOLUTION_ENABLED and EVOLUTION_AUTO_ENABLED and EVOLUTION_AUTO_APPLY else '手动/仅记录'}", "EVOLVE")
        print("="*80)

        # 🔵 Cookie 预热：模拟人类打开App行为，先访问一次首页暖机
        if NO_HUMAN_DELAY:
            log("⚡ 快速模式：跳过Cookie预热", "INFO")
        else:
            log("🍪 Cookie预热：模拟打开B站首页...", "INFO")
            try:
                warmup_client = await self.bili._get_http_client()
                await warmup_client.get(
                    'https://www.bilibili.com',
                    cookies=self.bili.raw_cookies,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                    timeout=15.0
                )
                log("🍪 Cookie预热完成", "SUCCESS")
            except Exception as e:
                log(f"Cookie预热跳过: {e}", "INFO")

        # [WARN] 启动冷却：等待几秒再进入扫描循环，模拟真人打开App后的浏览节奏
        try:
            startup_cool = max(0.1, random.uniform(float(COOLDOWN_STARTUP_MIN or 1), float(COOLDOWN_STARTUP_MAX or 3)))
        except (ValueError, TypeError):
            startup_cool = 1.5
        log(f"启动冷却 {startup_cool:.1f} 秒，模拟真人打开App后的浏览节奏...", "INFO")
        if NO_HUMAN_DELAY:
            log("⚡ 快速模式：跳过启动冷却", "INFO")
        else:
            await asyncio.sleep(startup_cool)

        # [FIX] 启动守卫：前几轮主循环强制跳过Agent深度搜索（防止旧pyc缓存或冷却bug导致启动即触发）
        _loop_count = 0

        while True:
            try:
                _loop_count += 1
                self.update_runtime_clock()

                # ── 会话限制检查 ──
                session_elapsed = (datetime.now() - self.session_start_time).total_seconds() / 60.0
                limit_reached = False
                limit_reason = ""

                if SESSION_MAX_DURATION_MINUTES > 0 and session_elapsed >= SESSION_MAX_DURATION_MINUTES:
                    limit_reached = True
                    limit_reason = f"已达到最长运行时间 {SESSION_MAX_DURATION_MINUTES} 分钟（实际 {session_elapsed:.1f} 分钟）"
                elif SESSION_MAX_VIDEOS > 0 and self.videos_processed >= SESSION_MAX_VIDEOS:
                    limit_reached = True
                    limit_reason = f"已处理 {self.videos_processed} 个视频（上限 {SESSION_MAX_VIDEOS}）"

                if limit_reached:
                    log(f"⏰ 会话限制触发: {limit_reason}", "SESSION")
                    log(f"[STATS] 本次会话统计: 处理 {self.videos_processed} 个视频, 运行 {session_elapsed:.1f} 分钟", "SESSION")
                    break

                # [SPEED] 并行检查评论和私信（独立API，可并发提速）
                comments_task = asyncio.create_task(self.check_and_handle_comments())
                msgs_task = asyncio.create_task(self.check_and_handle_private_messages())
                comments_processed, msgs_processed = await asyncio.gather(comments_task, msgs_task, return_exceptions=True)
                # [FIX] gather 返回异常时降级为 0
                if isinstance(comments_processed, Exception):
                    comments_processed = 0
                if isinstance(msgs_processed, Exception):
                    msgs_processed = 0
                # [FIX] 只有实际处理了评论才睡冷却，无操作则跳过
                if comments_processed > 0:
                    await asyncio.sleep(max(0.1, random.uniform(
                        float(COOLDOWN_POST_COMMENT_MIN or 1), float(COOLDOWN_POST_COMMENT_MAX or 3))))
                
                if self.energy <= 0:
                    await self.energy_recovery_session()
                    continue

                session_info = ""
                if SESSION_MAX_VIDEOS > 0:
                    session_info += f" | 已看: {self.videos_processed}/{SESSION_MAX_VIDEOS}"
                elif SESSION_MAX_DURATION_MINUTES > 0:
                    session_info += f" | 已看: {self.videos_processed}"
                log(f"精力: {self.energy}% | 今日已投: {self.coins_spent}/{MAX_COINS_DAILY} | 记忆UP: {len(self.memory['known_ups'])}{session_info}", "INFO")

                # [FIX] 只有实际处理了私信才睡冷却，无操作则跳过
                if msgs_processed > 0:
                    await asyncio.sleep(max(0.1, random.uniform(
                        float(COOLDOWN_POST_DM_MIN or 1), float(COOLDOWN_POST_DM_MAX or 3))))

                # ── 🤖 Agent深度搜索：定期触发，深入了解某个主题 ──
                # [FIX] 启动守卫：前3轮主循环硬跳过（防止旧pyc缓存/冷却bug导致启动即触发）
                if AGENT_ENABLED and AGENT_DIVE_ENABLED and _loop_count > 3:
                    agent_dive_elapsed = (datetime.now() - self.last_agent_run_at).total_seconds() / 60
                    # [FIX] 必须至少看过3个视频+冷却到期+精力够+25%随机
                    if (self.videos_processed >= 3 and agent_dive_elapsed >= max(AGENT_COOLDOWN_MINUTES, 5)
                            and self.energy >= 15 and random.random() < 0.25):
                        # 优先用刚看过的感兴趣视频主题，没有则从兴趣/知识库选
                        dive_topic = await self._pick_agent_dive_topic()
                        if dive_topic:
                            log(f"🤖 Agent深度搜索启动！主题: '{dive_topic[:50]}'", "CONFIG")
                            self.last_agent_run_at = datetime.now()  # [FIX] 立即记录，防止重复触发
                            self.energy -= 8  # [FIX] 先扣精力，防止异步并发超扣
                            # [FIX] 异步非阻塞：不卡主循环，后台默默搜索看视频
                            async def _dive_async(topic=dive_topic):
                                try:
                                    run = await self.agent_runner.run_goal(topic)
                                    ok_steps = sum(1 for item in run.get("results", []) if item.get("result", {}).get("ok"))
                                    watched_count = 0
                                    for item in run.get("results", []):
                                        if item.get("step", {}).get("skill") == "watch_bilibili_videos":
                                            watched_count = item.get("result", {}).get("count", 0)
                                    log(f"🤖 Agent深度搜索完成: {ok_steps}/{len(run.get('results', []))}步骤, 看了{watched_count}个视频", "SUCCESS")
                                except Exception as e:
                                    log(f"🤖 Agent深度搜索异常: {e}", "WARN")
                            task = asyncio.create_task(_dive_async())
                            task.add_done_callback(_safe_task_callback("agent_dive_async"))

                # ── 📂 [KB] 自动重分类"未分类"文件夹 ──
                if AUTO_RECLASSIFY_ENABLED and _loop_count > 5:
                    reclass_elapsed = (datetime.now() - getattr(self, '_last_reclassify_at', datetime.min)).total_seconds() / 60
                    if reclass_elapsed >= AUTO_RECLASSIFY_INTERVAL_MINUTES and random.random() < 0.5:
                        try:
                            ok, fail = self.classifier.reclassify_uncategorized(max_per_run=3)
                            if ok > 0 or fail > 0:
                                self._last_reclassify_at = datetime.now()
                                # 清理空文件夹
                                cleaned = self.classifier.cleanup_empty_folders()
                                if cleaned > 0:
                                    log(f"[KB] 已清理 {cleaned} 个空文件夹", "KB")
                        except Exception as e:
                            log(f"[KB] 自动重分类异常: {e}", "ERROR")

                # ── [SPEED] 并行：回顾复习 + 主动聊天，互不依赖 ──
                revisit_target = None

                async def _do_revisit():
                    if not REVISIT_ENABLED or not self.history_videos.get("videos"):
                        return None
                    revisit_cooldown_ok = (datetime.now() - self.last_revisit_at).total_seconds() / 60 >= REVISIT_COOLDOWN_MINUTES
                    if not revisit_cooldown_ok or random.random() >= PROB_REVISIT:
                        return None
                    candidate = self.get_revisit_candidate()
                    if not candidate:
                        return None
                    try:
                        log(f"📖 学而时习之：回顾复习《{candidate.get('title','')[:30]}》({candidate.get('action')}) ...", "REVISIT")
                        await _bili_throttle("回顾复习-get_info")
                        v = Video(bvid=candidate.get("bvid"), credential=self.credential)
                        vid_info = await v.get_info()
                        if vid_info:
                            target = {
                                "bvid": candidate["bvid"],
                                "title": vid_info.get("title", candidate.get("title", "")),
                                "owner": vid_info.get("owner", {}),
                                "id": vid_info.get("aid") or candidate.get("aid"),
                                "pic": vid_info.get("pic", ""),
                                "aid": vid_info.get("aid") or candidate.get("aid"),
                                "_is_revisit": True,
                                "_original_action": candidate.get("action", "")
                            }
                            self.last_revisit_at = datetime.now()
                            self.mark_revisited(candidate["bvid"])
                            log(f"回顾复习锁定: 《{target['title']}》", "REVISIT")
                            return target
                        else:
                            log(f"获取复习视频信息失败，跳过", "WARN")
                    except Exception as e:
                        log(f"回顾复习异常: {e}", "WARN")
                    return None

                async def _do_chat():
                    try:
                        await self.maybe_initiate_chat()
                    except Exception as e:
                        log(f"主动聊天模块异常(主循环): {e}", "ERROR")

                revisit_target, _ = await asyncio.gather(_do_revisit(), _do_chat(), return_exceptions=True)
                if isinstance(revisit_target, Exception):
                    revisit_target = None

                if revisit_target:
                    # 使用复习视频代替推荐流
                    target = revisit_target
                    self.videos_processed += 1
                    bvid = target['bvid']
                    title = target.get('title', '无标题')
                    up = target.get('owner', {}).get('name', '未知')
                    up_uid = target.get('owner', {}).get('mid', 0)
                    aid = target.get('id') or target.get('aid')
                    pic_url = target.get('pic', '')
                    video_url = f"https://www.bilibili.com/video/{bvid}"
                    log(f"📖 复习目标:《{title}》- @{up}", "REVISIT")
                    # 🔍 知识验证：回顾时联网核实知识的真实性和时效性（带异常回调）
                    task = asyncio.create_task(self.verify_knowledge_file(bvid, title))
                    task.add_done_callback(_safe_task_callback("verify_knowledge_file"))
                    # 顺便浏览该UP的视频（副作用：记录到浏览历史）
                    await self.maybe_browse_up_videos(force_up_uid=up_uid if up_uid else None, up_name_hint=up)
                else:
                    # ── [*] 优先浏览喜欢/已知UP主的新视频 ──
                    up_browse_target = await self.maybe_browse_up_videos()
                    if up_browse_target and up_browse_target.get("bvid"):
                        target = up_browse_target
                        self.videos_processed += 1
                        bvid = target['bvid']
                        title = target.get('title', '无标题')
                        up = target.get('owner', {}).get('name', '未知')
                        up_uid = target.get('owner', {}).get('mid', 0)
                        aid = target.get('id') or target.get('aid')
                        pic_url = target.get('pic', '')
                        video_url = f"https://www.bilibili.com/video/{bvid}"
                        source_tag = "[STAR]喜爱UP" if target.get("_is_favorite_up") else "📺已关注UP"
                        log(f"{source_tag} 新视频:《{title}》- @{up}", "BROWSE")
                    else:
                        # [PSYCHO] 主动推荐：每N轮触发一次AI驱动的惊喜/探索/反茧房推荐
                        rec_target = None
                        if (self.recommend_engine 
                            and self._psycho_profile_analysis_count > PSYCHO_MIN_VIEWS_BEFORE_RECOMMEND 
                            and random.random() < PSYCHO_RECOMMEND_PROB):
                            rec_modes = ["surprise", "explore", "anticocoon", "trend"]
                            # 轮换模式，避免重复
                            if self._last_recommend_mode:
                                try:
                                    idx = rec_modes.index(self._last_recommend_mode)
                                    rec_modes = rec_modes[idx+1:] + rec_modes[:idx+1]
                                except ValueError as e:
                                    log(f'值错误: {e}', 'DEBUG')
                            for mode in rec_modes[:2]:  # 尝试2种模式
                                try:
                                    queries = await self.recommend_engine.generate_search_queries(mode=mode, count=2)
                                    if queries:
                                        log(f"{get_mode_emoji(mode)} {get_mode_label(mode)}: 搜索「{queries[0]}」...", "RECOMMEND")
                                        results = await self.bili.search_bilibili(queries[0])
                                        if results:
                                            # 过滤已看过的
                                            fresh = [r for r in results if r.get("bvid") not in self.recommend_engine._seen_bvids]
                                            if fresh:
                                                chosen = random.choice(fresh[:5])
                                                chosen["_rec_mode"] = mode
                                                chosen["_rec_query"] = queries[0]
                                                rec_target = chosen
                                                self._last_recommend_mode = mode
                                                self.recommend_engine._seen_bvids.add(chosen.get("bvid"))
                                                # 生成推荐理由
                                                chosen["_rec_reason"] = self.recommend_engine.explain_recommendation(
                                                    {"title": chosen.get("title",""), "tags": chosen.get("tag","").split(",") if chosen.get("tag") else [],
                                                     "up_name": chosen.get("author",""), "up_uid": chosen.get("mid",""),
                                                     "category": chosen.get("typename",""), "bvid": chosen.get("bvid","")},
                                                    mode
                                                )
                                                log(f"  → 推荐理由: {chosen['_rec_reason'][:80]}...", "RECOMMEND")
                                                break
                                except Exception as e:
                                    log(f"推荐生成失败({mode}): {e}", "WARN")
                        
                        if rec_target and rec_target.get("bvid"):
                            target = rec_target
                            if not isinstance(target, dict):
                                continue
                            self.videos_processed += 1
                            bvid = target.get('bvid', '')
                            if not bvid:
                                continue
                            title = target.get('title', '无标题')
                            owner = target.get('owner')
                            if isinstance(owner, dict):
                                up = target.get('author') or owner.get('name', '未知')
                                up_uid = target.get('mid') or owner.get('mid', 0)
                            else:
                                up = target.get('author', '未知')
                                up_uid = target.get('mid', 0)
                            aid = target.get('aid') or target.get('id', 0)
                            pic_url = target.get('pic', '')
                            video_url = f"https://www.bilibili.com/video/{bvid}"
                            log(f"{get_mode_emoji(target.get('_rec_mode','surprise'))} 主动推荐:《{title}》- @{up}", "RECOMMEND")
                            if target.get("_rec_reason"):
                                log(f"  [IDEA] 为什么推荐: {target['_rec_reason'][:120]}", "RECOMMEND")
                            # 追踪推荐点击
                            self.psycho_profile.tracker.record("recommend_click", 
                                bvid=bvid, title=title, mode=target.get("_rec_mode",""))
                        else:
                            log("正在刷新推荐流...", "SCAN")
                            items = await self._get_cached_recommendations()
                            if not items or not isinstance(items, list):
                                await asyncio.sleep(3)
                                continue

                            target = random.choice(items)
                            if not isinstance(target, dict):
                                log(f"推荐流返回异常元素类型: {type(target).__name__}", "WARN")
                                continue
                            self.videos_processed += 1
                            bvid = target.get('bvid', '')
                            if not bvid:
                                log("推荐流元素缺少bvid，跳过", "WARN")
                                continue
                            title = target.get('title', '无标题')
                            owner = target.get('owner')
                            if isinstance(owner, dict):
                                up = owner.get('name', '未知')
                                up_uid = owner.get('mid', 0)
                            else:
                                up = '未知'
                                up_uid = 0
                            aid = target.get('id') or target.get('aid')
                            pic_url = target.get('pic', '')
                            video_url = f"https://www.bilibili.com/video/{bvid}"

                            log(f"锁定目标:《{title}》- @{up}", "SCAN")

                # [SPEED] 锁定后立即后台预取推荐流 + 短暂休息并行
                prefetch_task = asyncio.create_task(self._prefetch_recommendations())
                prefetch_task.add_done_callback(_safe_task_callback("prefetch_recs"))
                await asyncio.sleep(random.uniform(0.3, 0.8))

                # 提取标签、时长、分类（供心理画像引擎/避雷系统使用）
                tags = []
                raw_tag = target.get('tag', '')
                if isinstance(raw_tag, str) and raw_tag:
                    tags = [t.strip() for t in raw_tag.split(',') if t.strip()]
                elif isinstance(raw_tag, list):
                    tags = raw_tag
                duration = target.get('duration', 0)
                if isinstance(duration, str) and ':' in duration:
                    try:
                        parts = duration.split(':')
                        duration = int(parts[0]) * 60 + int(parts[1])
                    except Exception:
                        duration = 0
                elif isinstance(duration, str):
                    try:
                        duration = int(duration)
                    except Exception:
                        duration = 0
                category = target.get('typename') or target.get('tname') or ''

                # [ASR] 缓存视频元数据供 ASR AI预判使用
                self._current_video_tags = tags
                self._current_video_category = category
                self._current_video_duration = duration

                # ── 视频过滤模式 ──
                if VIDEO_FILTER_MODE == "watch_all":
                    vis_desc, vis_score = "全量模式，跳过封面分析", 0
                    log(f"[FAST] 全量模式：不看封面标题，直接看视频", "MODE")
                    interested = True
                    matched_interests = []
                    interest_reason = "全量模式(所有视频都看)"
                else:
                    # cover_and_title 模式：封面分析 + AI兴趣判断
                    vis_desc, vis_score = await self.analyze_vision(pic_url)
                    log(f"封面速览: {vis_desc} [印象分:{vis_score}]", "EYE")
                    # [ASR] 缓存封面描述供 ASR AI预判
                    self._current_video_cover_desc = vis_desc
                    # [DEF] 避雷系统检查
                    if self.psycho_profile:
                        aversion_score, aversion_reasons = self.psycho_profile.aversion.get_aversion_score(
                            title=title, tags=tags, up_uid=up_uid
                        )
                        if aversion_score >= PSYCHO_AVERSION_BLOCK_SCORE:
                            log(f"[DEF] 避雷拦截: {title[:30]}... | 反感度{aversion_score:.1%} | {'; '.join(aversion_reasons)}", "AVERSION")
                            self.psycho_profile.tracker.record_skip(bvid, title, reason=f"避雷: {'; '.join(aversion_reasons)}")
                            continue
                        elif aversion_score >= PSYCHO_AVERSION_WARN_SCORE:
                            log(f"[DEF] 避雷提示: {title[:30]}... | 反感度{aversion_score:.1%} | {'; '.join(aversion_reasons)} (仍继续判断)", "AVERSION")
                    
                    interested, matched_interests, interest_reason = await self.judge_interest_with_ai(title, up, vis_desc, vis_score)
                    if not interested:
                        log(f"视频《{title}》与兴趣不匹配，跳过 | {interest_reason}", "INTEREST")
                        await self.watch_and_sync_history(bvid)
                        continue
                    # 补充关键词匹配结果到展示列表中（确保所有命中兴趣都显示）
                    kw_matched = self.interest_mgr.get_matching_interests(title, up)
                    all_matched = list(dict.fromkeys((matched_interests or []) + kw_matched))  # 去重合并
                    if all_matched:
                        log(f"视频《{title}》匹配兴趣: {', '.join(all_matched)} | {interest_reason}", "INTEREST")
                        # [FIX] 记住这个感兴趣的视频上下文，供Agent深度搜索使用
                        self._last_interesting_topic = f"深入了解「{title[:40]}」（匹配: {', '.join(all_matched[:3])}）"
                    else:
                        log(f"视频《{title}》通过兴趣判断 | {interest_reason}", "INTEREST")

                subtitle_text = "[未读取字幕]"
                comment_text = "[未读取评论]"
                danmaku_text = ""
                c_list = []

                # [SPEED] 并行读取字幕+评论+弹幕，减少串行等待
                async def _read_subtitles_task():
                    nonlocal subtitle_text
                    mode_label = normalize_mode(VIDEO_UNDERSTANDING_MODE) if normalize_mode else VIDEO_UNDERSTANDING_MODE
                    log(f"开始研究视频内容... 当前视频理解模式: {mode_label}", "BRAIN")
                    success, result = await self.understand_video_for_decision(bvid, title=title)
                    if success:
                        subtitle_text = result
                        log(f"视频理解GET: {subtitle_text[:80].strip()}...", "SUCCESS")
                    else:
                        subtitle_text = "[无可用字幕/语音内容]"
                        log(f"视频理解遇到问题: {result}", "WARN")

                async def _read_comments_task():
                    nonlocal comment_text, c_list, danmaku_text
                    log("看看大家都在说啥...", "BRAIN")
                    comment_text, c_list = await self._get_comments_context(aid)
                    # [MSG] 同时读取弹幕
                    danmaku_list = await self.maybe_read_danmaku(bvid)
                    danmaku_text = ""
                    if danmaku_list:
                        danmaku_text = f"【视频弹幕（共{len(danmaku_list)}条，随机采样）】:\n" + "\n".join(
                            f"  {dm.get('text','')}" for dm in danmaku_list[:15]
                        )
                    if not c_list:
                        log("评论区空空如也...", "COMMENT")
                    else:
                        preview_parts = []
                        for i, c in enumerate(c_list[:5]):
                            part = f"#{i+1}[{c['user']}]: {c['content'][:30]}"
                            if c.get('pic_info'):
                                # 截取图片描述的前15字作为标签
                                pic_tag = c['pic_info'][:15] + "..." if len(c['pic_info']) > 15 else c['pic_info']
                                part += f" [图:{pic_tag}]"
                            preview_parts.append(part)
                        preview = ", ".join(preview_parts)
                        log(f"评论区速览({len(c_list)}条): {preview}", "COMMENT")

                await asyncio.sleep(random.uniform(0.2, 0.5))
                await asyncio.gather(_read_subtitles_task(), _read_comments_task(), return_exceptions=True)

                log("信息整合，AI决策中...", "BRAIN")
                sys_prompt = self.build_dynamic_brain_prompt(up)
                # [FIX] 当视频理解失败时，提醒AI更多依赖评论区/弹幕/标题做判断
                video_fallback_hint = ""
                _st = str(subtitle_text)
                if any(kw in _st for kw in ["【无字幕无人声】", "无可用字幕", "无可用字幕/语音", "[未读取"]):
                    video_fallback_hint = "\n[WARN] 视频字幕/语音内容不可用，请主要根据评论区讨论、弹幕反应和标题来推断视频质量与价值。\n"
                context = (f"视频标题: {title}\nUP主: {up}\n封面描述: {vis_desc}\n封面印象分: {vis_score}\n"
                           f"{video_fallback_hint}"
                           f"【📺 视频内容字幕】: {subtitle_text}\n"
                           f"{comment_text}"
                           f"{danmaku_text}")

                try:
                    resp = await self._call_ai_with_retry(
                        model=MODEL_BRAIN,
                        messages=[
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": context}
                        ],
                        request_timeout=60
                    )
                    raw = resp.choices[0].message.content
                    # ── 提取JSON（模型可能返回前缀文本）──
                    start = raw.find("{")
                    end = raw.rfind("}")
                    if start >= 0 and end >= start:
                        json_str = raw[start:end + 1]
                    else:
                        raise ValueError(f"AI返回未找到JSON结构，原始内容: {raw[:200]}")
                    # ── 修复模型偶尔用单引号/不规范JSON ──
                    try:
                        decision = json.loads(json_str)
                    except json.JSONDecodeError:
                        try:
                            fixed = json_str.replace("'", '"')
                            fixed = re.sub(r'\bTrue\b', 'true', fixed)
                            fixed = re.sub(r'\bFalse\b', 'false', fixed)
                            fixed = re.sub(r'\bNone\b', 'null', fixed)
                            decision = json.loads(fixed)
                        except (json.JSONDecodeError, Exception):
                            # 二次修复仍失败，使用安全默认值
                            decision = {"mode": "普通", "score": 5, "thought": "AI返回格式异常，使用默认决策", "comment_intent": False, "coin_intent": False, "like_intent": False, "collect_intent": False}
                except Exception as e:
                    log(f"AI决策模块异常(已重试): {_mask_urls(str(e)[:120])}", "ERROR")
                    continue

                mode = decision.get('mode', '普通')
                thought = decision.get('thought', '...')
                score = decision.get('score', 0)

                log(f"[{mode}模式] AI想法: {thought}", "BRAIN")
                log(f"AI最终评分: {score} / 10", "BRAIN")
                self.user_profile_mgr.update_impression(f"up::{up}", up, thought)

                # [*] 记录UP主印象 + 决定是否关注
                if up_uid:
                    self.record_up_impression(up, up_uid, score)
                    await self.maybe_follow_up(up_uid, up, score)
                
                # [PSYCHO] 心理画像追踪：记录本次观看
                if self.psycho_profile:
                    self.psycho_profile.tracker.record_view(
                        bvid=bvid, title=title, tags=tags or [],
                        duration=duration, up_name=up, up_uid=up_uid,
                        category=category or "", score=score,
                        interested=(score >= INTEREST_THRESHOLD)
                    )
                    self.psycho_profile.update_surface_interest(
                        title=title, tags=tags, category=category or "",
                        duration=duration, up_uid=up_uid, up_name=up,
                        score=score
                    )
                    # 触发茧房检测 + 启发式L2更新
                    self._psycho_profile_analysis_count += 1
                    if self._psycho_profile_analysis_count % PSYCHO_HEURISTIC_UPDATE_INTERVAL == 0:
                        self.psycho_profile.heuristic_update_l2()
                        metrics = self.psycho_profile.update_cocoon_metrics()
                        if metrics.get("diversity_score", 1.0) < PSYCHO_COCOON_WARNING_THRESHOLD:
                            log(f"[STATS] 内容多样性提醒: {metrics.get('cocoon_risk')} | 多样性={metrics.get('diversity_score')} | 稀少领域={metrics.get('underrepresented_areas', [])}", "WARN")
                    # 触发深度AI分析
                    if self._psycho_profile_analysis_count % PSYCHO_DEEP_ANALYZE_INTERVAL == 0:
                        task = asyncio.create_task(self.psycho_profile.deep_analyze())
                        task.add_done_callback(_safe_task_callback("deep_analyze"))
                        self.psycho_profile.detect_interest_shifts()

                self.energy -= 1

                # 🎯 学习归档：只归档高质量内容，低分/短时长/浅内容一律跳过
                learning_topic = decision.get("learning_topic")
                learn_success = False
                learn_text = subtitle_text
                if not learn_text or "[未读取字幕]" in str(learn_text) or "[该视频无有效CC字幕]" in str(learn_text):
                    learn_text = ""
                    if title: learn_text += f"【视频标题】{title}\n"
                    if up: learn_text += f"【UP主】{up}\n"
                    if thought: learn_text += f"【AI判断】{thought}\n"
                    if danmaku_text: learn_text += f"【弹幕】{danmaku_text}\n"
                    if comment_text and comment_text != "[未读取评论]": learn_text += f"【评论】{comment_text}\n"
                    learn_text = learn_text.strip()
                
                # 🔒 三层质量门槛：分数 + 时长 + 内容长度
                skip_reason = None
                if score < LEARN_MIN_SCORE:
                    skip_reason = f"分数过低({score:.1f}<{LEARN_MIN_SCORE})"
                elif duration > 0 and duration < LEARN_MIN_DURATION_SECONDS:
                    skip_reason = f"视频太短({duration}s<{LEARN_MIN_DURATION_SECONDS}s)"
                elif not learn_text or len(learn_text) < 150:
                    skip_reason = f"可学内容不足({len(learn_text) if learn_text else 0}字<150)"
                
                if skip_reason:
                    log(f"📭 跳过学习归档: {skip_reason} | 《{title}》", "LEARN")
                elif learning_topic and learn_text and len(learn_text) > 20:
                    try:
                        _desc = getattr(self, "_last_video_desc", "")
                        # 💬 先收集评论区知识（返回摘要文本，不写文件）
                        comment_summ = None
                        if c_list and len(c_list) >= 5 and (comment_text and comment_text != "[未读取评论]"):
                            try:
                                comment_summ, reason = await self.learn_from_comments(
                                    bvid, title, up, video_url, comment_text, c_list,
                                    topic_suggestion=learning_topic, score=score
                                )
                                if comment_summ:
                                    log("评论区知识已提炼，将合并到归档", "LEARN")
                            except Exception as clearn_e:
                                log(f"评论区知识收集异常: {clearn_e}", "WARN")
                        # 归档（评论摘要合并写入视频笔记）
                        learn_success = await self.learn_from_video(
                            bvid, title, up, video_url, learn_text, learning_topic,
                            video_desc=_desc, score=score, comment_summary=comment_summ
                        )
                        if learn_success:
                            self.mood_mgr.shift("学到有价值内容", 2)
                            if score >= INTEREST_THRESHOLD:
                                self.energy -= 2
                                log(f"学习归档消耗2点精力，当前剩余精力: {self.energy}%", "INFO")
                    except Exception as learn_e:
                        log(f"学习归档异常: {learn_e}", "WARN")

                # ★ 评论区知识收集：从讨论中提取有价值的信息
                if c_list and len(c_list) >= 3 and (comment_text and comment_text != "[未读取评论]"):
                    try:
                        comment_learn_success = await self.learn_from_comments(
                            bvid, title, up, video_url, comment_text, c_list,
                            topic_suggestion=learning_topic or (decision.get("learning_topic") or "评论知识")
                        )
                        if comment_learn_success:
                            log("评论区知识收集消耗1点精力", "INFO")
                            self.energy -= 1
                    except Exception as clearn_e:
                        log(f"评论区知识收集异常: {clearn_e}", "WARN")

                if score < INTEREST_THRESHOLD:
                    self.mood_mgr.shift("刷到低分视频", -1)
                    log(f"分数({score})过低，不感兴趣，划走~ (消耗1点精力, 剩余: {self.energy}%)", "INFO")
                    # [PSYCHO] 心理画像：记录跳过 + 避雷学习
                    if self.psycho_profile:
                        self.psycho_profile.tracker.record_skip(bvid, title, reason=f"低于兴趣阈值(score={score})")
                        self.psycho_profile.aversion.report_aversion(
                            bvid=bvid, title=title, reason=f"低分({score})",
                            tags=tags, up_uid=up_uid, up_name=up
                        )
                    self.record_session_event(
                        "video_skipped",
                        title=title,
                        up=up,
                        score=score,
                        thought=thought,
                        reason="低于兴趣阈值",
                        url=video_url
                    )
                    await self.maybe_auto_diary()
                    await self.maybe_self_evolve()
                    await self.watch_and_sync_history(bvid)
                    continue

                action_log = []
                v = Video(bvid=bvid, credential=self.credential)

                # 随机检定：RANDOM_ENABLED=False 时全部通过（只看分数阈值），True 时进行概率检定
                coin_check = random.random() < PROB_COIN if RANDOM_ENABLED else True
                fav_check = random.random() < PROB_FAV if RANDOM_ENABLED else True
                reply_check = random.random() < PROB_REPLY_TRIGGER if RANDOM_ENABLED else True
                like_solo_check = random.random() < PROB_LIKE_SOLO if RANDOM_ENABLED else True

                ai_wants_coin = decision.get('coin_intention', False)
                ai_wants_fav = decision.get('fav_intention', False)
                ai_wants_reply = bool(decision.get('replies', []))
                video_comment_allowed, video_comment_reason, video_comment_hits = ReplySafetyGuard().review_video_for_comment(
                    title=title,
                    up=up,
                    subtitle=subtitle_text,
                    comments=json.dumps(c_list[:5], ensure_ascii=False)
                )
                if not video_comment_allowed:
                    if ai_wants_reply:
                        log(f"视频命中涉政/敏感内容，强制清空评论意图: {video_comment_reason} | 命中: {', '.join(video_comment_hits)}", "WARN")
                    decision["replies"] = []
                    ai_wants_reply = False

                do_coin = ai_wants_coin and score >= COIN_THRESHOLD and self.coins_spent < MAX_COINS_DAILY and coin_check
                do_fav = ai_wants_fav and score >= FAV_THRESHOLD and fav_check
                do_replies = decision.get('replies', []) if (ai_wants_reply and reply_check) else []
                do_like_trigger = do_fav or do_coin or bool(do_replies) or (score >= 6.5 and like_solo_check)

                if RANDOM_ENABLED:
                    log(f"🎲 投币 | 意图:{'✓' if ai_wants_coin else '✗'} 分数:{'✓' if score >= COIN_THRESHOLD else '✗'} 限额:{'✓' if self.coins_spent < MAX_COINS_DAILY else '✗'} 检定({int(PROB_COIN*100)}%):{'✓' if coin_check else '✗'} => {'执行' if do_coin else '跳过'}", "DIAG")
                    log(f"🎲 收藏 | 意图:{'✓' if ai_wants_fav else '✗'} 分数:{'✓' if score >= FAV_THRESHOLD else '✗'} 检定({int(PROB_FAV*100)}%):{'✓' if fav_check else '✗'} => {'执行' if do_fav else '跳过'}", "DIAG")
                    log(f"🎲 评论 | 意图:{'✓' if ai_wants_reply else '✗'} 检定({int(PROB_REPLY_TRIGGER*100)}%):{'✓' if reply_check else '✗'} => {'执行' if bool(do_replies) else '跳过'}", "DIAG")
                    log(f"🎲 点赞 | 收藏:{'✓' if do_fav else '✗'} 投币:{'✓' if do_coin else '✗'} 评论:{'✓' if bool(do_replies) else '✗'} 单独(分数/检定):{'✓' if score >= 6.5 else '✗'}/{'✓' if like_solo_check else '✗'} => {'执行' if do_like_trigger else '跳过'}", "DIAG")
                else:
                    log(f"🔒 投币 | 意图:{'✓' if ai_wants_coin else '✗'} 分数:{'✓' if score >= COIN_THRESHOLD else '✗'} 限额:{'✓' if self.coins_spent < MAX_COINS_DAILY else '✗'} => {'执行' if do_coin else '跳过'}", "DIAG")
                    log(f"🔒 收藏 | 意图:{'✓' if ai_wants_fav else '✗'} 分数:{'✓' if score >= FAV_THRESHOLD else '✗'} => {'执行' if do_fav else '跳过'}", "DIAG")
                    log(f"🔒 评论 | 意图:{'✓' if ai_wants_reply else '✗'} => {'执行' if bool(do_replies) else '跳过'}", "DIAG")
                    log(f"🔒 点赞 | 收藏:{'✓' if do_fav else '✗'} 投币:{'✓' if do_coin else '✗'} 评论:{'✓' if bool(do_replies) else '✗'} 单独(分数):{'✓' if score >= 6.5 else '✗'} => {'执行' if do_like_trigger else '跳过'}", "DIAG")

                # [FIX] 学习归档已提前执行（在分数门槛之前，所有视频都学）
                if learn_success:
                    action_log.append("学习归档")
                    # 异步非阻塞：后台Agent继续探索
                    self.last_agent_run_at = datetime.now()
                    goal1 = f"继续了解这个主题：{learning_topic}。搜索相关视频，先看1-3个，如果内容有价值再继续多看。"
                    task = asyncio.create_task(self._agent_goal_async(goal1, score=score))
                    task.add_done_callback(_safe_task_callback("agent_goal1"))

                # 🧭 好奇心驱动深度搜索：遇到感兴趣/不了解的内容，B站搜索深入学（动态2-10个视频）
                if CURIOSITY_DEEP_DIVE_ENABLED and score >= CURIOSITY_DEEP_DIVE_MIN_SCORE:
                    dive_cooldown_ok = (datetime.now() - self._last_curiosity_dive_at).total_seconds() / 60 >= CURIOSITY_DEEP_DIVE_COOLDOWN_MINUTES
                    today_str = datetime.now().strftime("%Y%m%d")
                    if self._curiosity_dive_date != today_str:
                        self._curiosity_dive_count_today = 0
                        self._curiosity_dive_date = today_str
                    
                    # 触发条件：高分视频AND(有学习主题OR AI表示想深入了解OR随机触发)
                    dive_trigger = (learning_topic or
                                   any(w in (thought + title).lower() for w in ["想了解", "深入", "探索", "好奇", "不懂", "学习", "研究"]) or
                                   random.random() < CURIOSITY_DEEP_DIVE_PROB)
                    
                    if dive_trigger and dive_cooldown_ok and self._curiosity_dive_count_today < 3 and self.energy >= 10:
                        dive_topic = learning_topic or title[:20]
                        log(f"🧭 触发好奇心深度搜索！主题: '{dive_topic}' (评分:{score})", "LEARN")
                        self._last_curiosity_dive_at = datetime.now()
                        self._curiosity_dive_count_today += 1
                        self.energy -= 3
                        await self.curiosity_deep_dive(dive_topic, trigger_title=title, trigger_bvid=bvid)

                if score >= AGENT_AUTO_MIN_SCORE and any(word in title.lower() + " " + thought.lower() for word in ["模型", "ai", "gpt", "agent", "机器人", "开源", "教程", "工具", "开发"]):
                    # [FIX] 异步非阻塞：后台探索，不卡主循环
                    self.last_agent_run_at = datetime.now()
                    goal2 = f"深入了解这个主题：{title}。搜索相关视频，先看1-3个，有价值再继续。"
                    task = asyncio.create_task(self._agent_goal_async(goal2, score=score))
                    task.add_done_callback(_safe_task_callback("agent_goal2"))

                if decision.get('remember_up') and up not in self.memory['known_ups']:
                    self.remember_up(up, uid=up_uid)

                # [*] 自动喜欢UP主：高分视频且UP主有趣 → 标记为喜欢
                if score >= 8.0 and up_uid and up and not self.is_favorite_up(up):
                    fav_prob = 0.12 + (score - 8.0) * 0.08  # score=8→12%, score=10→28%
                    if random.random() < fav_prob:
                        self.favorite_up(up, uid=up_uid)
                        action_log.append("[STAR]喜欢UP主")
                        log(f"[STAR] 自动标记喜欢的UP主: @{up} (UID:{up_uid}) [评分:{score}, 概率:{fav_prob:.0%}]", "FAVORITE")

                if do_like_trigger:
                    try:
                        await asyncio.sleep(random.uniform(2, 4))
                        has_liked = await v.has_liked()
                        if not has_liked:
                            log("正在尝试点赞...", "ACT")
                            aid = v.get_aid()
                            await _bili_throttle()  # 🔒 全局节流
                            await v.like(status=True)
                            log("点赞成功！", "SUCCESS")
                            action_log.append("点赞")
                            if self.psycho_profile:
                                self.psycho_profile.tracker.record_interaction("like", bvid, title, up)
                                self.psycho_profile.update_surface_interest(
                                    title=title, tags=tags, up_uid=up_uid, up_name=up,
                                    liked=True, score=score
                                )
                            self.user_profile_mgr.adjust_affinity(f"up::{up}", up, 1, "点赞视频")
                            # 存入互动历史，供回顾复习（带评分）
                            self.add_history_video(str(bvid), title, up, aid, "like", score)
                        else:
                            log("视频已经点过赞了。", "INFO")
                    except Exception as e:
                        log(f"点赞失败 (可能受限): {e}", "ERROR")

                if do_fav:
                    try:
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        has_favorited = await v.has_favoured()

                        if not has_favorited:
                            await _bili_throttle("收藏夹列表")  # 🔒 全局节流
                            fav_list_data = await favorite_list.get_video_favorite_list(uid=self.credential.dedeuserid, credential=self.credential)
                            if fav_list_data and fav_list_data.get('list'):
                                default_folder_id = fav_list_data['list'][0]['id']
                                log(f"正在尝试收藏到默认收藏夹...", "ACT")
                                aid = v.get_aid()
                                await _bili_throttle()  # 🔒 全局节流
                                await v.set_favorite(add_media_ids=[default_folder_id])
                                log("收藏成功！", "SUCCESS")
                                action_log.append("收藏")
                                if self.psycho_profile:
                                    self.psycho_profile.tracker.record_interaction("favorite", bvid, title, up)
                                    self.psycho_profile.update_surface_interest(
                                        title=title, tags=tags, up_uid=up_uid, up_name=up,
                                        favorited=True, score=score
                                )
                                self.user_profile_mgr.adjust_affinity(f"up::{up}", up, 2, "收藏视频")
                                # 存入互动历史，供回顾复习（带评分）
                                self.add_history_video(str(bvid), title, up, aid, "fav", score)
                            else:
                                log("未能获取到收藏夹列表，无法收藏。", "WARN")
                        else:
                            log("视频已在收藏夹中。", "INFO")
                    except Exception as e:
                        log(f"收藏失败: {e}", "ERROR")

                if do_coin:
                    try:
                        await asyncio.sleep(random.uniform(2, 4))
                        aid = v.get_aid()
                        await _bili_throttle()  # 🔒 全局节流
                        await v.pay_coin(num=1, like=True)
                        self.coins_spent += 1
                        log(f"投币成功！今日已投 {self.coins_spent} 枚。", "COIN")
                        action_log.append("投币")
                        if self.psycho_profile:
                            self.psycho_profile.tracker.record_interaction("coin", bvid, title, up)
                            self.psycho_profile.update_surface_interest(
                                title=title, tags=tags, up_uid=up_uid, up_name=up,
                                coined=True, score=score
                            )
                        self.user_profile_mgr.adjust_affinity(f"up::{up}", up, 3, "投币支持")
                    except Exception as e:
                        log(f"投币失败: {e}", "ERROR")

                # 回复他人评论的功能
                if do_replies and PROB_COMMENT_OTHERS > 0:
                    for reply in do_replies:
                        try:
                            target_id = reply.get('target_id', 0)
                            reply_content = reply.get('content', '')
                            
                            if target_id and reply_content:
                                target_comment = next((item for item in c_list if str(item.get("id")) == str(target_id)), {})
                                incoming_text = target_comment.get("content", "")
                                pacing_ok, pacing_reason = self.comment_mgr._should_reply_user(target_comment.get("user_id"), incoming_text) if self.comment_mgr else (True, "通过")
                                if not pacing_ok:
                                    log(f"视频评论节奏控制跳过 ID:{target_id}: {pacing_reason}", "COMMENT")
                                    continue
                                reply_content = ensure_ai_marker(reply_content)
                                ok, reason, hits = ReplySafetyGuard().review(incoming_text, reply_content)
                                if not ok:
                                    log(f"已拦截视频评论回复 ID:{target_id}: {reason} | 命中: {', '.join(hits)}", "WARN")
                                    if self.comment_mgr:
                                        self.comment_mgr.log_blocked_reply(target_id, incoming_text, reply_content, reason, hits, target_comment.get("user", "视频评论"))
                                    continue

                                log(f"正在回复评论 ID:{target_id}: {reply_content[:50]}...", "COMMENT")
                                await asyncio.sleep(human_reply_delay())
                                if COMMENT_MODE == "simulate":
                                    log(f"[模拟] 拟回复视频评论 ID:{target_id}: {reply_content[:50]}...", "SIMULATE")
                                else:
                                    await _bili_throttle()  # 🔒 全局节流
                                    await comment.send_comment(
                                        text=reply_content,
                                        oid=aid,
                                        type_=CommentResourceType.VIDEO,
                                        root=target_id,
                                        parent=target_id,
                                        credential=self.credential
                                    )
                                    log("回复评论成功！", "SUCCESS")
                                action_log.append(f"回复评论({target_id})")
                                self.mood_mgr.shift("成功参与评论区互动", 1)
                                
                                # 记录评论日志
                                if self.comment_mgr:
                                    self.comment_mgr.log_interaction(target_id, "reply", reply_content, "视频评论")
                                    self.comment_mgr._mark_user_replied(target_comment.get("user_id"))
                                
                                await asyncio.sleep(random.uniform(1, 3))
                        except Exception as e:
                            log(f"回复评论失败: {e}", "ERROR")

                if action_log:
                    self.energy -= 3
                    self.mood_mgr.shift("主动互动完成", 1)
                    log(f"深度交互额外消耗3点精力，当前剩余精力: {self.energy}%", "INFO")
                    self.write_journal(title, up, score, f"[{mode}] {thought}", " + ".join(action_log), video_url)
                else:
                    self.mood_mgr.shift("观望未互动", -1)
                    log("所有互动检定均未通过或无需操作，本次不进行额外操作。", "INFO")

                self.record_session_event(
                    "video_processed",
                    title=title,
                    up=up,
                    score=score,
                    mode=mode,
                    thought=thought,
                    actions=action_log,
                    mood=self.mood_mgr.get_current(),
                    url=video_url
                )
                await self.maybe_auto_diary()
                await self.maybe_self_evolve()

                await self.watch_and_sync_history(bvid)

                # 📚 知识库定期审查：每N个视频后随机抽查归档质量
                if KNOWLEDGE_REVIEW_INTERVAL > 0:
                    self._knowledge_review_countdown -= 1
                    if self._knowledge_review_countdown <= 0:
                        self._knowledge_review_countdown = KNOWLEDGE_REVIEW_INTERVAL
                        try:
                            await self._review_knowledge_periodically()
                        except Exception as review_e:
                            log(f"知识库定期审查异常: {review_e}", "WARN")

            except asyncio.CancelledError:
                log("主循环被取消 (CancelledError)，正常退出", "WARN")
                raise  # 重新抛出，让 asyncio.run() 正确处理
            except KeyboardInterrupt:
                log("主循环收到中断信号，正常退出", "WARN")
                raise
            except Exception as e:
                log(f"主循环发生严重错误: {e}", "ERROR")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(3)


# ==============================================================================
# [V] 手动视频分析 — 用户输入链接/标题/UP主名，AI客观解析
# ==============================================================================
