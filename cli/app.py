# agent_brain.py - 完整版（包含兴趣系统 + 评论互动）
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pyright: basic
import asyncio
import json
import random
import os
import re
import sys
import atexit
import time
import shutil
import qrcode
import httpx
import uuid
from datetime import datetime, timedelta
from io import BytesIO
import openai  # 改为直接导入 openai 包
import colorama
from colorama import Fore, Style

# ===== 模块化导入 =====
from persona.managers import PersonaManager, MoodManager, UserProfileManager, BotDiaryManager, SelfEvolutionManager, PrivateContextDB
from security.guard import ReplySafetyGuard

from services.utils import InterestManager, BiliToolbox
from services.agent_service import AgentSkillRunner
from services.knowledge_tutor import KnowledgeTutor, scan_md_files, read_md_file, write_md_file
# CommentInteractionManager 已移至 brain/comment.py

# ===== 工具函数导入（从 utils/ 模块） =====
from utils.helpers import _mask_urls, sanitize_filename, ensure_ai_marker, unix_to_iso, parse_iso_datetime, human_reply_delay, _clean_ai_output
from utils.lock import _acquire_bot_lock, _release_bot_lock
from utils.display import log, mask_secret

# ===== B站 API 层导入（从 bili/ 模块） =====
from api.throttle import _bili_throttle, _bili_trigger_cooldown, _BILI_API_MIN_GAP
from api.compat import request
from api.client import BiliClient
from api.auth import login_bilibili, is_bili_logged_in, check_login_status, clear_login_info
from api.subtitles import fetch_bilibili_subtitles, _check_subtitle_mismatch

# ===== 知识库模块导入（从 knowledge/ 模块） =====
from knowledge.classifier import KnowledgeBaseClassifier
from knowledge.web_search import web_search, verify_knowledge_with_ai, backup_and_rewrite_knowledge
from knowledge.browse import count_knowledge_categories, browse_kb_structure, search_knowledge_content, cleanup_duplicates
from knowledge.revisit import revisit_knowledge_video, revisit_knowledge_base_menu
from knowledge.organize import organize_knowledge_base
from knowledge.custom import (
    custom_knowledge_menu, _init_custom_knowledge_dir, _get_custom_knowledge_entries,
    _add_custom_knowledge, _list_custom_knowledge, _view_custom_knowledge,
    _edit_custom_knowledge, _delete_custom_knowledge, _search_custom_knowledge,
    _ai_search_bilibili_and_add, _call_ai_with_retry_static,
)

# ===== 大脑模块导入（从 brain/ 模块） =====
from brain.comment import CommentInteractionManager
from brain.private_msg import PrivateMessageManager
from brain.agent_brain import AgentBrain
from brain.video_analysis import manual_video_analysis, up_homepage_learn

def _disclaimer_confirm():
    """显示红色免责声明，输入'我同意'后继续。"""
    _TARGET = "我同意"
    banner = f"""
{Fore.RED}{'='*60}
  ⚠  免责声明 / DISCLAIMER
{'='*60}
  本项目仅供学习参考，
  若因使用本项目产生任何后果，本人概不负责。

  This project is for learning purposes only.
  Any consequences are solely your own responsibility.
{'='*60}{Style.RESET_ALL}
"""
    print(banner)
    user_input = input(f"{Fore.YELLOW}请输入 '{_TARGET}' 以继续:{Style.RESET_ALL}").strip()
    if user_input != _TARGET:
        print(f"{Fore.RED}✗ 输入不匹配，程序退出。{Style.RESET_ALL}")
        sys.exit(1)
    print(f"{Fore.GREEN}✓ 已确认，欢迎使用...{Style.RESET_ALL}\n")
    return True

# [PSYCHO] 智能分析引擎
from utils.storage import get_backup_dir, sanitize_config_for_export
from persona.psycho import (
    PsychoProfile, RecommendationEngine,
    get_mode_emoji, get_mode_label,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

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

# --- 初始化彩色日志 ---
colorama.init(autoreset=True)

# --- 导入 bilibili_api 相关模块 ---
try:
    from bilibili_api import Credential, favorite_list, video, dynamic, Danmaku
    from bilibili_api.video import Video
    from bilibili_api import user, homepage, comment, session as bili_session, search as bili_search
    from bilibili_api.comment import CommentResourceType
    from bilibili_api.login_v2 import QrCodeLoginEvents, QrCodeLogin
except ImportError as e:
    print(f"{Fore.RED}[ERROR] Missing bilibili_api library. Run: pip install bilibili-api-python{Style.RESET_ALL}")
    sys.exit(1)

# [bili/compat.py] request() 兼容层
# 强制网络配置 (v14 不再支持 select_client/request_settings，通过 httpx 参数配置)
# select_client("curl_cffi")
# request_settings.set("impersonate", "chrome110")



# ==============================================================================
# 🎛️ 核心配置
# ==============================================================================
# 配置文件路径（cli/app.py 在子目录，需向上一级到项目根）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
BOT_LOCK_FILE = os.path.join(DATA_DIR, "bot.lock")  # 单实例锁文件
# 一键备份目录：平台自适应路径，与项目文件分离
BACKUP_DIR = get_backup_dir()
BACKUP_FILE = os.path.join(BACKUP_DIR, "bilibili_claw_export.json")
COOKIE_FILE = os.path.join(DATA_DIR, "bilibili_cookies.json")
INTERESTS_FILE = os.path.join(DATA_DIR, "interests.json")  # 兴趣配置文件
COMMENT_LOG_FILE = os.path.join(DATA_DIR, "comment_log.json")  # 评论互动日志
PRIVATE_MESSAGE_LOG_FILE = os.path.join(DATA_DIR, "private_message_log.json")
PRIVATE_CONTEXT_FILE = os.path.join(DATA_DIR, "private_context_db.json")
USER_PROFILES_FILE = os.path.join(DATA_DIR, "user_profiles.json")
PERSONAS_FILE = os.path.join(DATA_DIR, "personas.json")
MOOD_STATE_FILE = os.path.join(DATA_DIR, "mood_state.json")
BOT_DIARY_FILE = os.path.join(DATA_DIR, "bot_diary.json")
SELF_EVOLUTION_FILE = os.path.join(DATA_DIR, "self_evolution.json")
AGENT_SKILL_LOG_FILE = os.path.join(DATA_DIR, "agent_skill_log.json")
SEARCH_HISTORY_FILE = os.path.join(DATA_DIR, "search_history.json")  # 搜索记录
RUNTIME_STATE_FILE = os.path.join(DATA_DIR, "bot_runtime_state.json")

# 确保Data目录存在
os.makedirs(DATA_DIR, exist_ok=True)

# 默认配置
DEFAULT_CONFIG = {
    "api": {
        "unified_api_key": "",
        "unified_base_url": "",
        "model_brain": "",
        "model_vision": "",
        "vision_api_key": "",
        "vision_base_url": ""
    },
    "interaction": {
        "coin_threshold": 8.0,
        "fav_threshold": 8.5,
        "interest_threshold": 6.5,
        "learn_min_score": 6.0,  # 学习归档最低分数门槛，低于此分不归档
        "learn_min_duration_seconds": 60,  # 学习归档最低视频时长(秒)，短于此不归档
        "max_coins_daily": 2,
        "max_energy": 100,
        "prob_reply_trigger": 0.15,
        "prob_coin": 0.25,
        "prob_fav": 0.8,
        "prob_like_solo": 0.5,
        "prob_comment_others": 0.3,  # 评论他人评论的概率
        "comment_check_interval": 300,  # 检查新评论的间隔（秒），默认5分钟
        "max_replies_per_check": 3,  # 每次检查最多回复几条评论
        "random_enabled": True  # 随机数限制开关：True=启用随机检定(更自然), False=关闭随机(只看分数阈值)
    },
    "energy": {
        "energy_recovery_min": 5,
        "energy_recovery_max": 10,
        "rounds_min": 3,
        "rounds_max": 10,
        "round_interval_min": 60,
        "round_interval_max": 180,
        "video_interval_min": 1,
        "video_interval_max": 5
    },
    "persona": {
        "active_persona": "默认人格",
        "prompt_name": "AI小助手"
    },
    "mood": {
        "default_mood": "平静",
        "mood_volatility": 1.0,
        "random_enabled": False,
        "random_interval_minutes": 5,
        "custom_enabled": False,
        "custom_mood": ""
    },
    "video": {
        "mode": "smart",
        "max_duration_seconds": 900,
        "frame_count": 12,
        "download_interest_threshold": 7.0,
        "download_dir": "",
        "delete_video_after_understand": True,
        "filter_mode": "cover_and_title"
    },
    "vision": {
        "_comment": "视觉理解: 视频抽帧+评论图片AI分析",
        "cover_enabled": True,
        "frames_enabled": True,
        "comment_images_enabled": True,
        "max_comment_images": 5,
        "frame_count": 8
    },
    "asr": {
        "enabled": False,
        "backend": "funasr",
        "whisper_model": "base",
        "language": "zh",
        "speaker_separation": True,
        "max_audio_duration": 3600,
        "min_confidence": 0.5,
        "skip_music": True,
        "keep_audio": False,
        "ffmpeg_path": "",
        "device": "cpu",
        "funasr_model_dir": "",
        "funasr_vad_enabled": True,
        "funasr_punc_enabled": True,
        "funasr_spk_enabled": False,
        "funasr_batch_size_s": 300,
        "funasr_hotword": ""
    },
    "private_message": {
        "enabled": True,
        "auto_reply": True,
        "check_interval": 120,
        "max_replies_per_check": 3,
        "only_recent_seconds": 900
    },
    "reply_safety": {
        "enabled": True,
        "block_on_incoming": True,
        "block_on_outgoing": True,
        "block_political_video_comments": True,
        "blocked_keywords": [
            "主席", "党", "国家", "政治", "政府", "共产党", "中共", "习近平", "毛泽东",
            "人大", "国务院", "军委", "台湾", "香港", "新疆", "西藏", "六四", "法轮",
            "选举", "民主", "独裁", "宪法", "外交部", "制裁", "战争", "俄乌", "以色列",
            "巴勒斯坦", "日本右翼", "靖国神社", "民族主义", "爱国", "辱华", "台独", "港独",
            "藏独", "疆独", "抗议", "游行", "维权", "人权", "警察", "军队", "解放军",
            "武统", "一国两制", "资本主义", "社会主义", "马列", "毛选"
        ]
    },
    "diary": {
        "enabled": True,
        "auto_enabled": True,
        "auto_interval_minutes": 60,
        "min_events_for_auto": 3
    },
    "self_evolution": {
        "enabled": True,
        "auto_enabled": True,
        "reflect_interval_events": 8,
        "min_events_for_reflect": 3,
        "auto_apply": True
    },
    "agent": {
        "enabled": True,
        "auto_enabled": True,
        "max_steps_per_plan": 5,
        "max_search_results": 8,
        "max_videos_per_plan": 5,
        "auto_min_score": 7.5,
        "cooldown_minutes": 60
    },
    "behavior": {
        "comment_mode": "real",
        "ai_marker": "（内容由AI生成并由AI回复）",
        "private_reply_cooldown_minutes": 3,
        "comment_user_cooldown_minutes": 60,
        "max_consecutive_ai_replies": 3,
        "min_reply_delay_seconds": 20,
        "max_reply_delay_seconds": 50,
        "prefer_short_replies": True
    },
    "session": {
        "max_videos": 0,
        "max_duration_minutes": 0
    },
    "revisit": {
        "enabled": True,
        "prob_revisit": 0.25,
        "revisit_cooldown_minutes": 15,
        "min_score": 7.5,
        "max_per_video": 2,
        "per_video_cooldown_minutes": 240
    },
    "active_chat": {
        "enabled": True,
        "prob_initiate": 0.06,
        "cooldown_minutes": 45,
        "max_initiate_per_session": 3
    },
    "up_follow": {
        "enabled": True,
        "auto_follow_prob": 0.08,
        "max_daily_follows": 3,
        "unfollow_inactive_days": 0,
        "browse_up_videos_prob": 0.06,
        "max_browse_videos": 3,
        "cooldown_minutes": 90,
        "favorite_up_browse_prob": 0.25,
        "favorite_up_uid_list": [],
        "test_mode": False
    },
    "danmaku": {
        "enabled": True,
        "read_prob": 0.4,
        "like_prob": 0.15,
        "max_daily_danmaku_likes": 10,
        "send_prob": 0.03,
        "max_daily_send": 2
    },
    "fallback_provider": {
        "enabled": False,
        "name": "备用API",
        "api_key": "",
        "base_url": "",
        "models": {
            "chat": "",
            "vision": ""
        }
    },
    "fallback_models": {
        "chat": "",
        "vision": "",
        "fast": ""
    }
}

# 加载配置
def load_config():
    """加载配置文件"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 合并默认配置和新配置
            for key in DEFAULT_CONFIG:
                if key not in config:
                    config[key] = DEFAULT_CONFIG[key]
                elif isinstance(config[key], dict):
                    for sub_key in DEFAULT_CONFIG[key]:
                        if sub_key not in config[key]:
                            config[key][sub_key] = DEFAULT_CONFIG[key][sub_key]
            return config
        except (OSError, json.JSONDecodeError) as e:
            log(f'加载JSON文件失败: {e}', 'DEBUG')
    # 如果配置文件不存在或损坏，使用默认配置
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()

def save_config(config):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 保存配置文件失败: {e}{Style.RESET_ALL}")
        return False

# 加载当前配置
config = load_config()


def get_bot_name():
    """获取可配置的机器人名字，默认'AI小助手'"""
    return config.get("persona", {}).get("prompt_name", "AI小助手")


def get_config_or_env(section, key, env_name):
    """优先使用环境变量，避免把 API Key 等敏感信息写入本地配置。"""
    val = os.getenv(env_name)
    if val is not None:
        return val
    return config.get(section, {}).get(key, "")




def configure_openai_client():
    # 🔧 防御：确保 URL 不为空且有协议
    url = UNIFIED_BASE_URL.strip().rstrip("/")
    if not url or "://" not in url:
        # 尝试从 config 实时读取（绕过可能为空的模块级变量）
        _live = config.get("api", {}).get("unified_base_url", "").strip().rstrip("/")
        if _live and "://" in _live:
            url = _live
        else:
            # 不做无效配置，避免后续调用 crash
            return
    openai.api_key = UNIFIED_API_KEY
    openai.api_base = url
    openai.base_url = url


def is_api_configured():
    return bool(UNIFIED_API_KEY and UNIFIED_BASE_URL and MODEL_BRAIN)

def get_vision_api_key():
    """获取视觉模型 API Key（独立配置优先，否则回退统一配置）"""
    return config["api"].get("vision_api_key") or UNIFIED_API_KEY

def get_vision_base_url():
    """获取视觉模型 API URL（独立配置优先，否则回退统一配置）"""
    return config["api"].get("vision_base_url") or UNIFIED_BASE_URL


# 提取配置变量
UNIFIED_API_KEY = get_config_or_env("api", "unified_api_key", "BILI_AI_API_KEY")
UNIFIED_BASE_URL = get_config_or_env("api", "unified_base_url", "BILI_AI_BASE_URL")
MODEL_BRAIN = get_config_or_env("api", "model_brain", "BILI_AI_MODEL_BRAIN")
MODEL_VISION = get_config_or_env("api", "model_vision", "BILI_AI_MODEL_VISION")

# 🔑 视觉模型独立 API 配置（未设置时回退到统一配置）
VISION_API_KEY = config["api"].get("vision_api_key") or UNIFIED_API_KEY
VISION_BASE_URL = config["api"].get("vision_base_url") or UNIFIED_BASE_URL

# [REFRESH] 备用模型（同一API提供商内的模型级降级）
FALLBACK_MODELS = config.get("fallback_models", {})
FALLBACK_MODEL_CHAT = FALLBACK_MODELS.get("chat", "")
FALLBACK_MODEL_VISION = FALLBACK_MODELS.get("vision", "")
FALLBACK_MODEL_FAST = FALLBACK_MODELS.get("fast", "")

# [REFRESH] 备用API提供商（跨提供商降级，如 chatanywhere 免费API）
_FBP = config.get("fallback_provider", {})
FALLBACK_PROVIDER_ENABLED = _FBP.get("enabled", False)
FALLBACK_PROVIDER_NAME = _FBP.get("name", "chatanywhere")
FALLBACK_PROVIDER_API_KEY = _FBP.get("api_key", "") or os.getenv("BILI_AI_FALLBACK_API_KEY", "")
FALLBACK_PROVIDER_BASE_URL = _FBP.get("base_url", "") or os.getenv("BILI_AI_FALLBACK_BASE_URL", "")
FALLBACK_PROVIDER_MODELS = _FBP.get("models", {})

configure_openai_client()

COIN_THRESHOLD = config["interaction"]["coin_threshold"]
FAV_THRESHOLD = config["interaction"]["fav_threshold"]
INTEREST_THRESHOLD = config["interaction"]["interest_threshold"]
LEARN_MIN_SCORE = config["interaction"].get("learn_min_score", 6.0)  # 学习归档最低分数
LEARN_MIN_DURATION_SECONDS = config["interaction"].get("learn_min_duration_seconds", 60)  # 最低视频时长
MAX_COINS_DAILY = config["interaction"]["max_coins_daily"]
MAX_ENERGY = config["interaction"]["max_energy"]
PROB_REPLY_TRIGGER = config["interaction"]["prob_reply_trigger"]
PROB_COIN = config["interaction"]["prob_coin"]
PROB_FAV = config["interaction"]["prob_fav"]
PROB_LIKE_SOLO = config["interaction"]["prob_like_solo"]
PROB_COMMENT_OTHERS = config["interaction"]["prob_comment_others"]
COMMENT_CHECK_ENABLED = config["interaction"].get("comment_check_enabled", True)
COMMENT_CHECK_INTERVAL = config["interaction"]["comment_check_interval"]
MAX_REPLIES_PER_CHECK = config["interaction"]["max_replies_per_check"]
RANDOM_ENABLED = config["interaction"].get("random_enabled", True)
# [AI] AI字幕内容验证开关：True=语义验证字幕是否与标题匹配，False=仅关键词判断
SUBTITLE_STRICT_CHECK = config.get("subtitle_strict_check", {}).get("enabled", False)  # 字幕严格校验(默认关闭)
QUIET_MODE = config.get("system", {}).get("quiet_mode", False)  # 安静模式：精简日志
AI_SUBTITLE_VERIFY_ENABLED = config.get("ai_subtitle_verify", {}).get("enabled", True)
# [AI] 知识库定期审查：每处理N个视频后随机抽查知识库条目
KNOWLEDGE_REVIEW_INTERVAL = config.get("ai_subtitle_verify", {}).get("knowledge_review_interval", 10)
KNOWLEDGE_REVIEW_SAMPLE_SIZE = config.get("ai_subtitle_verify", {}).get("knowledge_review_sample_size", 3)

ENERGY_RECOVERY_MIN = config["energy"]["energy_recovery_min"]
ENERGY_RECOVERY_MAX = config["energy"]["energy_recovery_max"]
ROUNDS_MIN = config["energy"]["rounds_min"]
ROUNDS_MAX = config["energy"]["rounds_max"]
ROUND_INTERVAL_MIN = config["energy"]["round_interval_min"]
ROUND_INTERVAL_MAX = config["energy"]["round_interval_max"]
VIDEO_INTERVAL_MIN = config["energy"]["video_interval_min"]
VIDEO_INTERVAL_MAX = config["energy"]["video_interval_max"]
VIDEO_UNDERSTANDING_MODE = config.get("video", {}).get("mode", "smart")
VIDEO_MAX_DURATION_SECONDS = config.get("video", {}).get("max_duration_seconds", 900)
VIDEO_FRAME_COUNT = config.get("video", {}).get("frame_count", 12)
VIDEO_DOWNLOAD_INTEREST_THRESHOLD = config.get("video", {}).get("download_interest_threshold", 7.0)
VIDEO_DOWNLOAD_DIR = config.get("video", {}).get("download_dir", "")
VIDEO_DELETE_AFTER_UNDERSTAND = config.get("video", {}).get("delete_video_after_understand", True)
VIDEO_FILTER_MODE = config.get("video", {}).get("filter_mode", "cover_and_title")  # watch_all / cover_and_title
# [VISION] 视觉理解配置
VISION_COVER_ENABLED = config.get("vision", {}).get("cover_enabled", True)
VISION_FRAMES_ENABLED = config.get("vision", {}).get("frames_enabled", True)
VISION_COMMENT_IMAGES_ENABLED = config.get("vision", {}).get("comment_images_enabled", True)
VISION_MAX_COMMENT_IMAGES = config.get("vision", {}).get("max_comment_images", 5)
VISION_FRAME_COUNT = config.get("vision", {}).get("frame_count", 8)
# [SMART_FRAME] AI智能抽帧配置
SMART_FRAME_ENABLED = config.get("vision", {}).get("smart_frame_enabled", True)
SMART_FRAME_MIN = config.get("vision", {}).get("smart_frame_min", 10)
SMART_FRAME_MAX = config.get("vision", {}).get("smart_frame_max", 60)
# [ASR] 语音识别（ASR）配置
ASR_ENABLED = config.get("asr", {}).get("enabled", False)
ASR_BACKEND = config.get("asr", {}).get("backend", "funasr")  # funasr / whisper
ASR_WHISPER_MODEL = config.get("asr", {}).get("whisper_model", "base")  # tiny/base/small/medium/large
ASR_LANGUAGE = config.get("asr", {}).get("language", "zh")
ASR_SPEAKER_SEPARATION = config.get("asr", {}).get("speaker_separation", True)
ASR_MAX_AUDIO_DURATION = config.get("asr", {}).get("max_audio_duration", 3600)
ASR_MIN_CONFIDENCE = config.get("asr", {}).get("min_confidence", 0.5)
ASR_SKIP_MUSIC = config.get("asr", {}).get("skip_music", True)
ASR_KEEP_AUDIO = config.get("asr", {}).get("keep_audio", False)
ASR_FFMPEG_PATH = config.get("asr", {}).get("ffmpeg_path", "")
ASR_DEVICE = config.get("asr", {}).get("device", "cpu")
# FunASR 专用配置
ASR_FUNASR_MODEL_DIR = config.get("asr", {}).get("funasr_model_dir", "")
ASR_FUNASR_VAD_ENABLED = config.get("asr", {}).get("funasr_vad_enabled", True)
ASR_FUNASR_PUNC_ENABLED = config.get("asr", {}).get("funasr_punc_enabled", True)
ASR_FUNASR_SPK_ENABLED = config.get("asr", {}).get("funasr_spk_enabled", False)
ASR_FUNASR_BATCH_SIZE_S = config.get("asr", {}).get("funasr_batch_size_s", 300)
ASR_FUNASR_HOTWORD = config.get("asr", {}).get("funasr_hotword", "")
PRIVATE_MESSAGE_ENABLED = config.get("private_message", {}).get("enabled", True)
PRIVATE_MESSAGE_AUTO_REPLY = config.get("private_message", {}).get("auto_reply", False)
PRIVATE_MESSAGE_CHECK_INTERVAL = config.get("private_message", {}).get("check_interval", 120)
PRIVATE_MESSAGE_MAX_REPLIES = config.get("private_message", {}).get("max_replies_per_check", 3)
PRIVATE_MESSAGE_ONLY_RECENT_SECONDS = config.get("private_message", {}).get("only_recent_seconds", 900)
# [TIME] 冷却时间配置（可调速）
COOLDOWN_STARTUP_MIN = config.get("cooldown", {}).get("startup_cooldown_min", 5)
COOLDOWN_STARTUP_MAX = config.get("cooldown", {}).get("startup_cooldown_max", 10)
COOLDOWN_POST_COMMENT_MIN = config.get("cooldown", {}).get("post_comment_cooldown_min", 3)
COOLDOWN_POST_COMMENT_MAX = config.get("cooldown", {}).get("post_comment_cooldown_max", 8)
COOLDOWN_POST_DM_MIN = config.get("cooldown", {}).get("post_dm_cooldown_min", 3)
COOLDOWN_POST_DM_MAX = config.get("cooldown", {}).get("post_dm_cooldown_max", 8)
REPLY_SAFETY_ENABLED = config.get("reply_safety", {}).get("enabled", True)

# [SPEED] 快速模式：跳过所有模拟真人延迟等待（主菜单 Q 切换）
NO_HUMAN_DELAY = config.get("speed", {}).get("no_human_delay", False)
REPLY_SAFETY_BLOCK_ON_INCOMING = config.get("reply_safety", {}).get("block_on_incoming", True)
REPLY_SAFETY_BLOCK_ON_OUTGOING = config.get("reply_safety", {}).get("block_on_outgoing", True)
REPLY_SAFETY_BLOCK_POLITICAL_VIDEO_COMMENTS = config.get("reply_safety", {}).get("block_political_video_comments", True)
REPLY_SAFETY_BLOCKED_KEYWORDS = config.get("reply_safety", {}).get("blocked_keywords", DEFAULT_CONFIG["reply_safety"]["blocked_keywords"])
DIARY_ENABLED = config.get("diary", {}).get("enabled", True)
DIARY_AUTO_ENABLED = config.get("diary", {}).get("auto_enabled", True)
DIARY_AUTO_INTERVAL_MINUTES = config.get("diary", {}).get("auto_interval_minutes", 60)
DIARY_MIN_EVENTS_FOR_AUTO = config.get("diary", {}).get("min_events_for_auto", 3)
EVOLUTION_ENABLED = config.get("self_evolution", {}).get("enabled", True)
EVOLUTION_AUTO_ENABLED = config.get("self_evolution", {}).get("auto_enabled", True)
EVOLUTION_REFLECT_INTERVAL_EVENTS = config.get("self_evolution", {}).get("reflect_interval_events", 8)
EVOLUTION_MIN_EVENTS_FOR_REFLECT = config.get("self_evolution", {}).get("min_events_for_reflect", 3)
EVOLUTION_AUTO_APPLY = config.get("self_evolution", {}).get("auto_apply", True)
AGENT_ENABLED = config.get("agent", {}).get("enabled", True)
AGENT_AUTO_ENABLED = config.get("agent", {}).get("auto_enabled", False)
AGENT_DIVE_ENABLED = config.get("agent", {}).get("dive_enabled", True)  # Agent深度搜索集成到刷视频主循环
AGENT_MAX_STEPS_PER_PLAN = config.get("agent", {}).get("max_steps_per_plan", 5)
AGENT_MAX_SEARCH_RESULTS = config.get("agent", {}).get("max_search_results", 8)
AGENT_MAX_VIDEOS_PER_PLAN = config.get("agent", {}).get("max_videos_per_plan", 3)
AGENT_DIVE_MAX_VIDEOS = config.get("agent", {}).get("dive_max_videos", 10)  # 深度搜索最多看视频数
AGENT_AUTO_MIN_SCORE = config.get("agent", {}).get("auto_min_score", 8.5)
AGENT_COOLDOWN_MINUTES = config.get("agent", {}).get("cooldown_minutes", 60)
BEHAVIOR_PRIVATE_REPLY_COOLDOWN_MINUTES = config.get("behavior", {}).get("private_reply_cooldown_minutes", 3)
BEHAVIOR_COMMENT_USER_COOLDOWN_MINUTES = config.get("behavior", {}).get("comment_user_cooldown_minutes", 60)
BEHAVIOR_MAX_CONSECUTIVE_AI_REPLIES = config.get("behavior", {}).get("max_consecutive_ai_replies", 3)
BEHAVIOR_MIN_REPLY_DELAY_SECONDS = config.get("behavior", {}).get("min_reply_delay_seconds", 4)
BEHAVIOR_MAX_REPLY_DELAY_SECONDS = config.get("behavior", {}).get("max_reply_delay_seconds", 18)
BEHAVIOR_PREFER_SHORT_REPLIES = config.get("behavior", {}).get("prefer_short_replies", True)
COMMENT_MODE = config.get("behavior", {}).get("comment_mode", "real")  # "real"=真实评论, "simulate"=模拟评论

# 会话限制定时/计数（0=不限制）
SESSION_MAX_VIDEOS = config.get("session", {}).get("max_videos", 0)
SESSION_MAX_DURATION_MINUTES = config.get("session", {}).get("max_duration_minutes", 0)

# 🔁 Revisit review (learn & reinforce)
REVISIT_ENABLED = config.get("revisit", {}).get("enabled", True)
PROB_REVISIT = config.get("revisit", {}).get("prob_revisit", 0.25)
REVISIT_COOLDOWN_MINUTES = config.get("revisit", {}).get("revisit_cooldown_minutes", 15)
REVISIT_MIN_SCORE = config.get("revisit", {}).get("min_score", 7.5)  # only quality videos enter the pool
REVISIT_MAX_PER_VIDEO = config.get("revisit", {}).get("max_per_video", 2)  # max revisits per video
REVISIT_PER_VIDEO_COOLDOWN_MINUTES = config.get("revisit", {}).get("per_video_cooldown_minutes", 240)  # per-video cooldown

# 🔍 知识验证（复习时联网核实知识真实性）
KNOWLEDGE_VERIFY_ENABLED = config.get("knowledge_verify", {}).get("enabled", True)
KNOWLEDGE_VERIFY_USE_WEB = config.get("knowledge_verify", {}).get("use_web_search", True)
KNOWLEDGE_VERIFY_MIN_SCORE = config.get("knowledge_verify", {}).get("min_reliability_score", 0.7)
KNOWLEDGE_VERIFY_AUTO_FIX = config.get("knowledge_verify", {}).get("auto_fix", True)

# 🧭 好奇心驱动深度搜索（遇到不懂/感兴趣的，B站搜索深入学习）
CURIOSITY_DEEP_DIVE_ENABLED = config.get("curiosity_search", {}).get("enabled", True)
CURIOSITY_DEEP_DIVE_MAX_VIDEOS = config.get("curiosity_search", {}).get("max_videos_per_dive", 10)
CURIOSITY_DEEP_DIVE_DEFAULT_VIDEOS = config.get("curiosity_search", {}).get("dive_videos_default", 3)
CURIOSITY_DEEP_DIVE_MID_VIDEOS = config.get("curiosity_search", {}).get("dive_videos_mid", 5)
CURIOSITY_DEEP_DIVE_HIGH_VIDEOS = config.get("curiosity_search", {}).get("dive_videos_max", 10)
CURIOSITY_DEEP_DIVE_MIN_SCORE = config.get("curiosity_search", {}).get("trigger_min_score", 7.5)
CURIOSITY_DEEP_DIVE_PROB = config.get("curiosity_search", {}).get("prob_trigger", 0.3)
CURIOSITY_DEEP_DIVE_COOLDOWN_MINUTES = config.get("curiosity_search", {}).get("cooldown_minutes", 120)

# 📦 Highlights archive (high-quality content saved separately)
DRY_GOODS_ENABLED = config.get("dry_goods", {}).get("enabled", False)
DRY_GOODS_MIN_SCORE = config.get("dry_goods", {}).get("min_score", 7.5)
DRY_GOODS_FOLDER_NAME = config.get("dry_goods", {}).get("folder_name", "highlights")

# [MSG] 主动找人聊天
ACTIVE_CHAT_ENABLED = config.get("active_chat", {}).get("enabled", True)
PROB_INITIATE_CHAT = config.get("active_chat", {}).get("prob_initiate", 0.06)
ACTIVE_CHAT_COOLDOWN_MINUTES = config.get("active_chat", {}).get("cooldown_minutes", 45)
ACTIVE_CHAT_MAX_PER_SESSION = config.get("active_chat", {}).get("max_initiate_per_session", 3)

# [*] UP主关注（AI自动关注喜欢的UP主）
UP_FOLLOW_ENABLED = config.get("up_follow", {}).get("enabled", True)
UP_FOLLOW_AUTO_PROB = config.get("up_follow", {}).get("auto_follow_prob", 0.08)
UP_FOLLOW_MAX_DAILY = config.get("up_follow", {}).get("max_daily_follows", 3)
UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS = config.get("up_follow", {}).get("unfollow_inactive_days", 0)
UP_FOLLOW_BROWSE_PROB = config.get("up_follow", {}).get("browse_up_videos_prob", 0.06)
UP_FOLLOW_MAX_BROWSE = config.get("up_follow", {}).get("max_browse_videos", 3)
UP_FOLLOW_COOLDOWN_MINUTES = config.get("up_follow", {}).get("cooldown_minutes", 90)
# [*] 喜欢的UP主（AI特别喜欢的UP主，会优先浏览其空间）
UP_FOLLOW_FAVORITE_PROB = config.get("up_follow", {}).get("favorite_up_browse_prob", 0.25)
UP_FOLLOW_FAVORITE_UID_LIST = config.get("up_follow", {}).get("favorite_up_uid_list", [])
UP_FOLLOW_TEST_MODE = config.get("up_follow", {}).get("test_mode", False)
# [*] 关注即认可：评分门槛 + 印象积累
UP_FOLLOW_MIN_SCORE = config.get("up_follow", {}).get("min_score", 7.0)          # 最低评分门槛
UP_FOLLOW_MIN_IMPRESSIONS = config.get("up_follow", {}).get("min_impressions", 2) # 最少正面印象次数
UP_FOLLOW_EXCEPTIONAL_SCORE = config.get("up_follow", {}).get("exceptional_score", 8.5) # 特别优秀可首看即关

# [MSG] 弹幕互动（阅读弹幕、点赞弹幕、发送弹幕）
DANMAKU_ENABLED = config.get("danmaku", {}).get("enabled", True)
DANMAKU_READ_PROB = config.get("danmaku", {}).get("read_prob", 0.4)
DANMAKU_LIKE_PROB = config.get("danmaku", {}).get("like_prob", 0.15)
DANMAKU_MAX_DAILY_LIKES = config.get("danmaku", {}).get("max_daily_danmaku_likes", 10)
DANMAKU_SEND_PROB = config.get("danmaku", {}).get("send_prob", 0.03)
DANMAKU_MAX_DAILY_SEND = config.get("danmaku", {}).get("max_daily_send", 2)

# [PSYCHO] 心理画像引擎配置
_PSY = config.get("psycho_engine", {})
PSYCHO_ENGINE_ENABLED = _PSY.get("enabled", True)
PSYCHO_DEEP_ANALYZE_INTERVAL = _PSY.get("deep_analyze_interval_videos", 100)
PSYCHO_HEURISTIC_UPDATE_INTERVAL = _PSY.get("heuristic_update_interval", 15)
PSYCHO_COCOON_DETECT_INTERVAL = _PSY.get("cocoon_detect_interval", 15)
PSYCHO_COCOON_WARNING_THRESHOLD = _PSY.get("cocoon_warning_threshold", 0.35)
PSYCHO_RECOMMEND_PROB = _PSY.get("recommend_prob_per_round", 0.08)
PSYCHO_MIN_VIEWS_BEFORE_RECOMMEND = _PSY.get("min_views_before_recommend", 10)
PSYCHO_MAX_SURPRISE_DAILY = _PSY.get("max_surprise_daily", 5)
PSYCHO_MAX_EXPLORE_DAILY = _PSY.get("max_explore_daily", 5)
PSYCHO_MAX_ANTICOCOON_DAILY = _PSY.get("max_anticocoon_daily", 3)
PSYCHO_MIN_ACTIONS_FOR_DEEP = _PSY.get("min_actions_for_deep_analysis", 50)
PSYCHO_DEEP_COOLDOWN = _PSY.get("deep_analysis_cooldown_seconds", 14400)
PSYCHO_MAX_ACTIONS_LOG = _PSY.get("max_actions_in_log", 2000)
PSYCHO_MAX_RECOMMENDATION_LOG = _PSY.get("max_recommendation_log", 200)
PSYCHO_AVERSION_BLACKLIST_THRESHOLD = _PSY.get("aversion_auto_blacklist_threshold", 3)
PSYCHO_AVERSION_BLOCK_SCORE = _PSY.get("aversion_score_block_threshold", 0.7)
PSYCHO_AVERSION_WARN_SCORE = _PSY.get("aversion_score_warn_threshold", 0.4)

# [MOOD] 心情随机/自定义
MOOD_RANDOM_ENABLED = config.get("mood", {}).get("random_enabled", False)
MOOD_RANDOM_INTERVAL_MINUTES = config.get("mood", {}).get("random_interval_minutes", 5)
MOOD_CUSTOM_ENABLED = config.get("mood", {}).get("custom_enabled", False)
MOOD_CUSTOM_VALUE = config.get("mood", {}).get("custom_mood", "")

# [KB] 自动重分类"未分类"文件夹
AUTO_RECLASSIFY_ENABLED = config.get("knowledge", {}).get("auto_reclassify_enabled", True)
AUTO_RECLASSIFY_INTERVAL_MINUTES = config.get("knowledge", {}).get("auto_reclassify_interval_minutes", 10)
AUTO_RECLASSIFY_CLEAN_EMPTY = config.get("knowledge", {}).get("auto_reclassify_clean_empty", True)


def _load_json_file(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"[WARN] JSON加载失败 {path}: {e}", "WARN")
    return default.copy() if isinstance(default, dict) else default


def _save_json_file(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        log(f"保存运行状态失败: {e}", "WARN") if "log" in globals() else None




# ── 🔒 B站 API 节流器已移至 bili/throttle.py，通过 import 引入 ──

# --- 路径配置 ---
JOURNAL_FILE = os.path.join(BASE_DIR, "bot_journal.md")
MEMORY_FILE = os.path.join(BASE_DIR, "bot_memory.json")
HISTORY_VIDEOS_FILE = os.path.join(DATA_DIR, "history_videos.json")  # 互动过的视频（点赞/收藏），用于回顾复习
KNOWLEDGE_BASE_DIR = os.path.join(BASE_DIR, "KnowledgeBase")
DRY_GOODS_DIR = os.path.join(BASE_DIR, "highlights")
LEARNING_LOG_FILE = os.path.join(BASE_DIR, "learning_log.md")
KB_METADATA_FILE = os.path.join(BASE_DIR, "knowledge_metadata.json")


# ==============================================================================
# [TARGET] 兴趣管理系统
# ==============================================================================
# ==============================================================================
# [brain/comment.py] CommentInteractionManager
# [brain/private_msg.py] PrivateMessageManager
def show_main_menu():
    """显示主菜单"""
    global COMMENT_MODE
    # 获取兴趣数量
    interest_mgr = InterestManager()
    interest_count = len(interest_mgr.get_interests())
    
    comment_mode_text = "真实评论" if COMMENT_MODE == "real" else "模拟评论"
    print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║           bilibili_learning_bot - B站学习互动机器人     ║
    ║               版本: v3.0.1 模块化重构版                  ║
    ║               特性: force_mode + 安静模式 + ASR并行      ║
    ╠══════════════════════════════════════════════════════════╣
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} [START] 启动机器人
    {Fore.YELLOW}2.{Style.RESET_ALL} ⚙️  配置AI参数
    {Fore.BLUE}3.{Style.RESET_ALL} 🔑 配置登录
    {Fore.MAGENTA}4.{Style.RESET_ALL} 📚 管理知识库
    {Fore.LIGHTYELLOW_EX}5.{Style.RESET_ALL} [TARGET] 管理兴趣爱好
    {Fore.LIGHTCYAN_EX}6.{Style.RESET_ALL} [MSG] 评论互动设置
    {Fore.LIGHTGREEN_EX}7.{Style.RESET_ALL} 📩 私信设置
    {Fore.LIGHTMAGENTA_EX}8.{Style.RESET_ALL} 🧬 日记/自我进化
    {Fore.LIGHTBLUE_EX}9.{Style.RESET_ALL} 🛠️  Agent技能
    {Fore.LIGHTBLUE_EX}F.{Style.RESET_ALL} [*][MSG] UP主关注/弹幕设置
    {Fore.LIGHTYELLOW_EX}G.{Style.RESET_ALL} [ASR]  ASR语音识别设置
    {Fore.LIGHTCYAN_EX}A.{Style.RESET_ALL} 🔊 ASR开关快速切换 (当前: {'开启' if ASR_ENABLED else '关闭'})
    {Fore.MAGENTA}M.{Style.RESET_ALL} 😊 AI心情管理
    {Fore.LIGHTCYAN_EX}D.{Style.RESET_ALL} [GOLD] 干货归档 (高分内容单独保存)
    {Fore.LIGHTCYAN_EX}V.{Style.RESET_ALL} 📹 手动视频分析 (输入链接/标题/UP主，AI客观解析)
    {Fore.LIGHTMAGENTA_EX}K.{Style.RESET_ALL} 🔄 知识库重温 (选择已学视频，重新看/优化)
    {Fore.LIGHTCYAN_EX}T.{Style.RESET_ALL} 🎓 知识辅导 (讲解/问答/二次创作/生成HTML)
    {Fore.LIGHTCYAN_EX}U.{Style.RESET_ALL} 📚 UP主主页批量学习 (获取UP主主页视频, AI逐个学习)
    {Fore.LIGHTCYAN_EX}W.{Style.RESET_ALL} 🎨 视频->网页 (将已学视频生成HTML网页)
    {Fore.CYAN}H.{Style.RESET_ALL} 🔍 搜索历史 (查看B站搜索记录)
    {Fore.CYAN}B.{Style.RESET_ALL} 📊 后台任务 (查看后台异步任务状态)
    {Fore.RED}R.{Style.RESET_ALL} 🔄 恢复出厂设置 (清除所有配置/登录/数据)
    {Fore.YELLOW}S.{Style.RESET_ALL} 🛡️ 关键词审查开关 (当前: {'开启' if REPLY_SAFETY_ENABLED else '关闭'})
    {Fore.LIGHTCYAN_EX}Q.{Style.RESET_ALL} ⚡ 快速模式 (跳过真人延迟): {Fore.GREEN + '已开启' + Style.RESET_ALL if NO_HUMAN_DELAY else Fore.YELLOW + '已关闭 (模拟真人)' + Style.RESET_ALL}
    {Fore.LIGHTCYAN_EX}Z.{Style.RESET_ALL} 🔇 安静模式 (精简日志): {Fore.GREEN + '已开启' + Style.RESET_ALL if QUIET_MODE else Fore.YELLOW + '已关闭' + Style.RESET_ALL}
    {Fore.GREEN}E.{Style.RESET_ALL} 📤 导出配置 (备份所有设置到一个文件)
    {Fore.BLUE}I.{Style.RESET_ALL} 📥 导入配置 (从备份文件一键恢复所有设置)
    {Fore.LIGHTYELLOW_EX}O.{Style.RESET_ALL} 📂 一键整理知识库 (非3层文件→AI自动归类到3层)
    {Fore.LIGHTGREEN_EX}N.{Style.RESET_ALL} 📝 自定义知识管理 (增删改查自定义知识条目)
    {Fore.CYAN}C.{Style.RESET_ALL} 👁️ 封面分析开关 (当前: {'开启' if VISION_COVER_ENABLED else '关闭(刷视频更快)'})
    {Fore.MAGENTA}L.{Style.RESET_ALL} 🛋️ 待机模式设置 (@触发总结/ASR/评论区/PPT等)
    {Fore.YELLOW}Y.{Style.RESET_ALL} ⏱️ 视频间隔设置 (当前: {VIDEO_INTERVAL_MIN}-{VIDEO_INTERVAL_MAX}秒)
    {Fore.RED}0.{Style.RESET_ALL} ❌ 退出程序

    {Fore.CYAN}当前配置状态:{Style.RESET_ALL}
    • API状态: {Fore.GREEN + "✓ 已配置" + Style.RESET_ALL if is_api_configured() else Fore.YELLOW + "[WARN] 未完整配置" + Style.RESET_ALL}
    • 登录状态: {Fore.GREEN + "✓ 已登录" + Style.RESET_ALL if is_bili_logged_in() else Fore.RED + "✗ 未登录" + Style.RESET_ALL}
    • 知识库: {Fore.GREEN + "✓ 已启用" + Style.RESET_ALL if os.path.exists(KNOWLEDGE_BASE_DIR) else Fore.YELLOW + "[FILE] 待创建" + Style.RESET_ALL}
    • 干货归档: {Fore.GREEN + f"✓ 已启用 (≥{DRY_GOODS_MIN_SCORE}分)" + Style.RESET_ALL if DRY_GOODS_ENABLED else Fore.YELLOW + "💤 未启用" + Style.RESET_ALL}
    • 兴趣爱好: {Fore.GREEN + f"✓ {interest_count}个" + Style.RESET_ALL if interest_count > 0 else Fore.YELLOW + "[WARN] 未设置" + Style.RESET_ALL}
    • 评论互动: {Fore.GREEN + "✓ " + comment_mode_text + Style.RESET_ALL if PROB_COMMENT_OTHERS > 0 else Fore.YELLOW + "[WARN] 未启用" + Style.RESET_ALL}
    • 私信处理: {Fore.GREEN + ("✓ 自动回复" if PRIVATE_MESSAGE_AUTO_REPLY else "✓ 只拟回复") + Style.RESET_ALL if PRIVATE_MESSAGE_ENABLED else Fore.YELLOW + "[WARN] 未启用" + Style.RESET_ALL}
    • 日记/进化: {Fore.GREEN + "✓ 已启用" + Style.RESET_ALL if DIARY_ENABLED or EVOLUTION_ENABLED else Fore.YELLOW + "[WARN] 未启用" + Style.RESET_ALL}
    • Agent技能: {Fore.GREEN + ("✓ 自动" if AGENT_AUTO_ENABLED else "✓ 手动") + Style.RESET_ALL if AGENT_ENABLED else Fore.YELLOW + "[WARN] 未启用" + Style.RESET_ALL}
    • Agent深度搜索: {Fore.GREEN + "🤖 集成刷视频" + Style.RESET_ALL if AGENT_ENABLED and AGENT_DIVE_ENABLED else Fore.YELLOW + "💤 未开启" + Style.RESET_ALL}
    • 语音识别(ASR): {Fore.GREEN + f"[ASR] {ASR_BACKEND.upper()}" + Style.RESET_ALL if ASR_ENABLED else Fore.YELLOW + "🔇 未启用" + Style.RESET_ALL}
    • 封面分析: {Fore.GREEN + "✓ 已开启" + Style.RESET_ALL if VISION_COVER_ENABLED else Fore.YELLOW + "⏸️ 已关闭(刷视频更快)" + Style.RESET_ALL}
    • 复习回顾: {Fore.GREEN + f"📖 已启用 (≥{REVISIT_MIN_SCORE}分)" + Style.RESET_ALL if REVISIT_ENABLED else Fore.YELLOW + "💤 未开启" + Style.RESET_ALL}
    • 会话限制: {Fore.GREEN + ("不限" if SESSION_MAX_VIDEOS <= 0 and SESSION_MAX_DURATION_MINUTES <= 0 else (f"{SESSION_MAX_VIDEOS}个视频" if SESSION_MAX_VIDEOS > 0 else "") + (" / " if SESSION_MAX_VIDEOS > 0 and SESSION_MAX_DURATION_MINUTES > 0 else "") + (f"{SESSION_MAX_DURATION_MINUTES}分钟" if SESSION_MAX_DURATION_MINUTES > 0 else "")) + Style.RESET_ALL}
    • UP主关注: {Fore.GREEN + "[*] 已开启" + Style.RESET_ALL if UP_FOLLOW_ENABLED else Fore.YELLOW + "💤 未开启" + Style.RESET_ALL}
    • 弹幕互动: {Fore.GREEN + "[MSG] 已开启" + Style.RESET_ALL if DANMAKU_ENABLED else Fore.YELLOW + "💤 未开启" + Style.RESET_ALL}
    • 关键词审查: {Fore.GREEN + "🛡 已启用" + Style.RESET_ALL if REPLY_SAFETY_ENABLED else Fore.YELLOW + "⚠ 已关闭" + Style.RESET_ALL}
    • 快速模式: {Fore.GREEN + "⚡ 已开启 (跳过延迟)" + Style.RESET_ALL if NO_HUMAN_DELAY else Fore.YELLOW + "🐢 已关闭 (模拟真人)" + Style.RESET_ALL}
    • 备用API: {Fore.GREEN + "[REFRESH] " + FALLBACK_PROVIDER_NAME + "(" + (FALLBACK_PROVIDER_MODELS.get('chat','') or '?') + "/" + (FALLBACK_PROVIDER_MODELS.get('vision','') or '?') + ")" + Style.RESET_ALL if FALLBACK_PROVIDER_ENABLED else Fore.YELLOW + "💤 未启用" + Style.RESET_ALL}
    • 随机数限制: {Fore.GREEN + "🎲 已开启 (随机检定)" + Style.RESET_ALL if RANDOM_ENABLED else Fore.YELLOW + "🔒 已关闭 (纯分数)" + Style.RESET_ALL}
    • AI心情: {Fore.GREEN + ("🤖 随机心情" if MOOD_RANDOM_ENABLED else ("✏️ 自定义: " + MOOD_CUSTOM_VALUE if MOOD_CUSTOM_ENABLED and MOOD_CUSTOM_VALUE else "⚙️ 默认")) + Style.RESET_ALL}
    """)

def show_mood_menu():
    """AI心情管理菜单 - 随机心情 / 自定义心情"""
    global config, MOOD_RANDOM_ENABLED, MOOD_RANDOM_INTERVAL_MINUTES
    global MOOD_CUSTOM_ENABLED, MOOD_CUSTOM_VALUE
    
    while True:
        random_text = "🤖 随机心情 (已开启)" if MOOD_RANDOM_ENABLED else "🤖 随机心情 (已关闭)"
        custom_text = f"✏️  自定义心情 ({MOOD_CUSTOM_VALUE})" if MOOD_CUSTOM_ENABLED and MOOD_CUSTOM_VALUE else ("✏️  自定义心情 (已开启)" if MOOD_CUSTOM_ENABLED else "✏️  自定义心情 (已关闭)")
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                😊 AI心情管理设置                          ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前心情模式:{Style.RESET_ALL}
    • 随机心情: {Fore.GREEN + random_text + Style.RESET_ALL}
    • 自定义心情: {Fore.GREEN + custom_text + Style.RESET_ALL}
    • 随机间隔: {Fore.YELLOW}{MOOD_RANDOM_INTERVAL_MINUTES}{Style.RESET_ALL} 分钟

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} {'关闭' if MOOD_RANDOM_ENABLED else '开启'}随机心情
    {Fore.GREEN}2.{Style.RESET_ALL} 设置随机间隔 (分钟)
    {Fore.BLUE}3.{Style.RESET_ALL} {'关闭' if MOOD_CUSTOM_ENABLED else '开启'}自定义心情
    {Fore.BLUE}4.{Style.RESET_ALL} 设置自定义心情文字
    {Fore.YELLOW}5.{Style.RESET_ALL} 重置为默认 (关闭随机+自定义)
    {Fore.RED}0.{Style.RESET_ALL} 返回主菜单
""")
        choice = input(f"{Fore.CYAN}请输入选项: {Style.RESET_ALL}").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            MOOD_RANDOM_ENABLED = not MOOD_RANDOM_ENABLED
            config["mood"]["random_enabled"] = MOOD_RANDOM_ENABLED
            if MOOD_RANDOM_ENABLED:
                MOOD_CUSTOM_ENABLED = False
                config["mood"]["custom_enabled"] = False
                config["mood"]["custom_mood"] = ""
                MOOD_CUSTOM_VALUE = ""
            print(f"{Fore.GREEN}随机心情: {'已开启' if MOOD_RANDOM_ENABLED else '已关闭'}{Style.RESET_ALL}")
        elif choice == "2":
            try:
                val = int(input(f"随机间隔分钟 (当前: {MOOD_RANDOM_INTERVAL_MINUTES}): "))
                if val < 1:
                    val = 1
                MOOD_RANDOM_INTERVAL_MINUTES = val
                config["mood"]["random_interval_minutes"] = val
                print(f"{Fore.GREEN}已更新: {val} 分钟{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "3":
            MOOD_CUSTOM_ENABLED = not MOOD_CUSTOM_ENABLED
            config["mood"]["custom_enabled"] = MOOD_CUSTOM_ENABLED
            if MOOD_CUSTOM_ENABLED:
                MOOD_RANDOM_ENABLED = False
                config["mood"]["random_enabled"] = False
            else:
                config["mood"]["custom_mood"] = ""
                MOOD_CUSTOM_VALUE = ""
            print(f"{Fore.GREEN}自定义心情: {'已开启' if MOOD_CUSTOM_ENABLED else '已关闭'}{Style.RESET_ALL}")
        elif choice == "4":
            val = input(f"请输入自定义心情文字 (当前: {MOOD_CUSTOM_VALUE or '无'}，例: 开心/沮丧/慵懒/好奇): ").strip()
            if val:
                MOOD_CUSTOM_ENABLED = True
                MOOD_RANDOM_ENABLED = False
                config["mood"]["custom_enabled"] = True
                config["mood"]["random_enabled"] = False
                config["mood"]["custom_mood"] = val
                MOOD_CUSTOM_VALUE = val
                print(f"{Fore.GREEN}自定义心情已设置: {val}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}未输入，保持原设置{Style.RESET_ALL}")
        elif choice == "5":
            MOOD_RANDOM_ENABLED = False
            MOOD_CUSTOM_ENABLED = False
            MOOD_CUSTOM_VALUE = ""
            config["mood"]["random_enabled"] = False
            config["mood"]["custom_enabled"] = False
            config["mood"]["custom_mood"] = ""
            # 重置心情状态文件
            if os.path.exists(MOOD_STATE_FILE):
                try:
                    os.remove(MOOD_STATE_FILE)
                except Exception as e:
                    log(f'非预期异常: {e}', 'WARN')
            print(f"{Fore.GREEN}已重置为默认心情模式{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}无效选项{Style.RESET_ALL}")
        
        if choice in ("1","2","3","4","5"):
            save_config(config)

def show_config_menu():
    """显示配置菜单"""
    global UNIFIED_API_KEY, UNIFIED_BASE_URL, MODEL_BRAIN, MODEL_VISION, openai
    global VISION_API_KEY, VISION_BASE_URL
    
    while True:
        vision_has_independent = bool(config["api"].get("vision_api_key", ""))
        vision_key_display = mask_secret(VISION_API_KEY)
        vision_url_display = VISION_BASE_URL
        vision_tag = " 独立" if vision_has_independent else " 共用统一"
        
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                    AI参数配置菜单                        ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前配置:{Style.RESET_ALL}
    • 统一API密钥: {mask_secret(UNIFIED_API_KEY)}
    • 统一API地址: {UNIFIED_BASE_URL}
    • 思考模型: {MODEL_BRAIN}
    • 视觉模型: {MODEL_VISION}

    {Fore.MAGENTA}视觉模型独立API（未配置则自动回退到统一API）:{Style.RESET_ALL}
    • 视觉API密钥: {vision_key_display}{' [NEW]' + vision_tag + '[NEW]' if vision_has_independent else ''}
    • 视觉API地址: {vision_url_display}

    {Fore.CYAN}请选择要配置的项目:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} 🔑 修改统一API密钥
    {Fore.GREEN}2.{Style.RESET_ALL} [NET] 修改统一API地址
    {Fore.GREEN}3.{Style.RESET_ALL} 🤖 修改思考模型
    {Fore.GREEN}4.{Style.RESET_ALL} 👁️  修改视觉模型
    {Fore.MAGENTA}A.{Style.RESET_ALL} 🔑👁️ 设置视觉模型独立API密钥
    {Fore.MAGENTA}B.{Style.RESET_ALL} [NET]👁️ 设置视觉模型独立API地址
    {Fore.MAGENTA}C.{Style.RESET_ALL} [REFRESH] 清除视觉模型独立配置(恢复共用)
    {Fore.YELLOW}5.{Style.RESET_ALL} ⚙️  配置互动参数
    {Fore.YELLOW}6.{Style.RESET_ALL} [FAST] 配置精力系统
    {Fore.BLUE}7.{Style.RESET_ALL} 💾 保存当前配置
    {Fore.BLUE}8.{Style.RESET_ALL} 📋 显示当前配置
    {Fore.YELLOW}9.{Style.RESET_ALL} [VIDEO] 视频下载/抽帧设置
    {Fore.MAGENTA}10.{Style.RESET_ALL} [TIME]  会话限制（定时/计数停止）
    {Fore.MAGENTA}D.{Style.RESET_ALL} [REFRESH] 备用API提供商（跨服务降级）
    {Fore.LIGHTCYAN_EX}M.{Style.RESET_ALL} [LIST] 获取可用模型列表
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-10/A/B/C/D/M): {Style.RESET_ALL}").strip()

        if choice == "0":
            break
        elif choice == "1":
            configure_api_key()
        elif choice == "2":
            configure_api_url()
        elif choice == "3":
            configure_brain_model()
        elif choice == "4":
            configure_vision_model()
        elif choice.upper() == "A":
            configure_vision_api_key()
        elif choice.upper() == "B":
            configure_vision_api_url()
        elif choice.upper() == "C":
            clear_vision_independent_config()
        elif choice == "5":
            configure_interaction_params()
        elif choice == "6":
            configure_energy_params()
        elif choice == "7":
            if save_config(config):
                # 重新加载配置到全局变量
                UNIFIED_API_KEY = config["api"]["unified_api_key"]
                UNIFIED_BASE_URL = config["api"]["unified_base_url"]
                MODEL_BRAIN = config["api"]["model_brain"]
                MODEL_VISION = config["api"]["model_vision"]
                VISION_API_KEY = config["api"].get("vision_api_key") or UNIFIED_API_KEY
                VISION_BASE_URL = config["api"].get("vision_base_url") or UNIFIED_BASE_URL
                configure_openai_client()
                print(f"{Fore.GREEN}[OK] 配置保存成功！{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] 配置保存失败！{Style.RESET_ALL}")
        elif choice == "8":
            show_current_config()
        elif choice == "9":
            configure_video_settings()
        elif choice == "10":
            configure_session_params()
        elif choice.upper() == "D":
            configure_fallback_provider()
        elif choice.upper() == "M":
            _fetch_available_models()
        else:
            print(f"{Fore.RED}[ERROR] 无效选项，请重新选择！{Style.RESET_ALL}")



def _fetch_available_models():
    """从当前统一API地址获取可用模型列表"""
    import httpx

    base = (UNIFIED_BASE_URL or "").strip().rstrip("/")
    if not base:
        print(f"{Fore.RED}[ERROR] 请先配置统一API地址{Style.RESET_ALL}")
        return

    url = f"{base}/models"
    api_key = (UNIFIED_API_KEY or "").strip()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    print(f"\n{Fore.CYAN}[LIST] 正在请求: {url}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}  (部分中转/代理可能不支持此接口){Style.RESET_ALL}")
    try:
        resp = httpx.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"{Fore.RED}[ERROR] HTTP {resp.status_code}: {resp.text[:300]}{Style.RESET_ALL}")
            return
        data = resp.json()
        models_data = data.get("data") or data.get("models") or []
        if not models_data:
            print(f"{Fore.YELLOW}[WARN] 接口返回空模型列表{Style.RESET_ALL}")
            return

        # 提取模型ID列表
        model_ids = []
        for m in models_data:
            if isinstance(m, dict):
                mid = m.get("id") or m.get("model") or ""
            elif isinstance(m, str):
                mid = m
            else:
                mid = str(m)
            if mid:
                model_ids.append(mid)

        # 去重排序
        model_ids = sorted(set(model_ids))

        # 分类展示
        chat_models = [m for m in model_ids if any(k in m.lower() for k in ("chat", "gpt", "claude", "gemini", "qwen", "deepseek", "glm", "moonshot", "kimi", "yi-", "mistral", "llama", "command"))]
        embed_models = [m for m in model_ids if "embed" in m.lower()]
        image_models = [m for m in model_ids if any(k in m.lower() for k in ("vision", "image", "dall", "stable", "flux", "sd-", "midjourney"))]
        other_models = [m for m in model_ids if m not in chat_models and m not in embed_models and m not in image_models]

        print(f"\n{Fore.GREEN}✅ 共获取到 {len(model_ids)} 个模型:{Style.RESET_ALL}")

        if chat_models:
            print(f"\n{Fore.CYAN}📝 对话/思考模型 ({len(chat_models)}):{Style.RESET_ALL}")
            for m in chat_models:
                marker = " ← 当前思考模型" if m == MODEL_BRAIN else (" ← 当前视觉模型" if m == MODEL_VISION else "")
                print(f"  {Fore.GREEN}{m}{Style.RESET_ALL}{Fore.YELLOW}{marker}{Style.RESET_ALL}")

        if image_models:
            print(f"\n{Fore.MAGENTA}🖼️ 视觉/图片模型 ({len(image_models)}):{Style.RESET_ALL}")
            for m in image_models:
                marker = " ← 当前视觉模型" if m == MODEL_VISION else ""
                print(f"  {Fore.GREEN}{m}{Style.RESET_ALL}{Fore.YELLOW}{marker}{Style.RESET_ALL}")

        if embed_models:
            print(f"\n{Fore.BLUE}📊 嵌入模型 ({len(embed_models)}):{Style.RESET_ALL}")
            for m in embed_models:
                print(f"  {Fore.GREEN}{m}{Style.RESET_ALL}")

        all_displayed = chat_models + image_models + embed_models
        if other_models:
            print(f"\n{Fore.LIGHTBLACK_EX}📦 其他模型 ({len(other_models)}):{Style.RESET_ALL}")
            for m in other_models:
                print(f"  {Fore.LIGHTBLACK_EX}{m}{Style.RESET_ALL}")

        print(f"\n{Fore.CYAN}💡 提示: 输入选项 3 或 4 修改模型名，复制上面的模型ID即可{Style.RESET_ALL}")

    except httpx.ConnectError:
        print(f"{Fore.RED}[ERROR] 连接失败: 无法访问 {base}，请检查API地址和网络{Style.RESET_ALL}")
    except httpx.TimeoutException:
        print(f"{Fore.RED}[ERROR] 请求超时 (15s)，请检查网络{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 获取模型列表异常: {e}{Style.RESET_ALL}")

def configure_fallback_provider():
    """配置备用API提供商（跨服务降级，含思考模型和图片模型）。"""
    global FALLBACK_PROVIDER_ENABLED, FALLBACK_PROVIDER_NAME, FALLBACK_PROVIDER_API_KEY
    global FALLBACK_PROVIDER_BASE_URL, FALLBACK_PROVIDER_MODELS

    fbp = config.setdefault("fallback_provider", {})
    fbp.setdefault("name", "备用API")
    fbp.setdefault("api_key", "")
    fbp.setdefault("base_url", "")
    fbp.setdefault("enabled", False)
    fbp.setdefault("models", {})
    fbp["models"].setdefault("chat", "")
    fbp["models"].setdefault("vision", "")

    while True:
        en_label = f"{Fore.GREEN}启用{Style.RESET_ALL}" if FALLBACK_PROVIDER_ENABLED else f"{Fore.RED}停用{Style.RESET_ALL}"
        print(f"""
    {Fore.CYAN}━━━ [REFRESH] 备用API提供商（跨服务降级）━━━{Style.RESET_ALL}

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 总开关: {en_label}
    • 名称: {FALLBACK_PROVIDER_NAME}
    • API密钥: {mask_secret(FALLBACK_PROVIDER_API_KEY)}
    • API地址: {FALLBACK_PROVIDER_BASE_URL}
    • [BRAIN] 思考模型: {FALLBACK_PROVIDER_MODELS.get('chat', '') or '(未设置)'}
    • 👁️  视觉模型: {FALLBACK_PROVIDER_MODELS.get('vision', '') or '(未设置)'}

    {Fore.CYAN}提示:{Style.RESET_ALL}
    备用提供商会使用同一个API地址/密钥，但分别指定思考模型和视觉模型名称。
    主API连续失败3次后自动切换，10分钟后自动尝试恢复主API。

    {Fore.YELLOW}1.{Style.RESET_ALL} 🔁 {'关闭' if FALLBACK_PROVIDER_ENABLED else '开启'}备用提供商
    {Fore.YELLOW}2.{Style.RESET_ALL} 🔑 设置API密钥
    {Fore.YELLOW}3.{Style.RESET_ALL} [NET] 设置API地址
    {Fore.YELLOW}4.{Style.RESET_ALL} [BRAIN] 设置思考模型名称
    {Fore.YELLOW}5.{Style.RESET_ALL} 👁️  设置视觉模型名称
    {Fore.YELLOW}6.{Style.RESET_ALL} ✏️  修改名称
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回上级
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-6): {Style.RESET_ALL}").strip()
        if choice == "0":
            break
        elif choice == "1":
            FALLBACK_PROVIDER_ENABLED = not FALLBACK_PROVIDER_ENABLED
            fbp["enabled"] = FALLBACK_PROVIDER_ENABLED
            save_config(config)
            print(f"{Fore.GREEN}[OK] 备用提供商已{'启用' if FALLBACK_PROVIDER_ENABLED else '停用'}{Style.RESET_ALL}")
        elif choice == "2":
            key = input(f"{Fore.YELLOW}输入备用API密钥 (回车保持): {Style.RESET_ALL}").strip()
            if key:
                fbp["api_key"] = key
                FALLBACK_PROVIDER_API_KEY = key
                save_config(config)
                print(f"{Fore.GREEN}[OK] 备用API密钥已更新{Style.RESET_ALL}")
        elif choice == "3":
            url = input(f"{Fore.YELLOW}输入备用API地址 (回车保持): {Style.RESET_ALL}").strip()
            if url:
                fbp["base_url"] = url
                FALLBACK_PROVIDER_BASE_URL = url
                save_config(config)
                print(f"{Fore.GREEN}[OK] 备用API地址已更新{Style.RESET_ALL}")
        elif choice == "4":
            model = input(f"{Fore.YELLOW}输入备用思考模型名称 (回车保持, 如 deepseek-chat): {Style.RESET_ALL}").strip()
            if model:
                fbp["models"]["chat"] = model
                FALLBACK_PROVIDER_MODELS["chat"] = model
                save_config(config)
                print(f"{Fore.GREEN}[OK] 备用思考模型已更新: {model}{Style.RESET_ALL}")
        elif choice == "5":
            model = input(f"{Fore.YELLOW}输入备用视觉模型名称 (回车保持, 如 qwen-vl-max): {Style.RESET_ALL}").strip()
            if model:
                fbp["models"]["vision"] = model
                FALLBACK_PROVIDER_MODELS["vision"] = model
                save_config(config)
                print(f"{Fore.GREEN}[OK] 备用视觉模型已更新: {model}{Style.RESET_ALL}")
        elif choice == "6":
            name = input(f"{Fore.YELLOW}输入名称 (回车保持): {Style.RESET_ALL}").strip()
            if name:
                fbp["name"] = name
                FALLBACK_PROVIDER_NAME = name
                save_config(config)
                print(f"{Fore.GREEN}[OK] 名称已更新: {name}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")

def configure_api_key():
    global UNIFIED_API_KEY, openai
    print(f"\n{Fore.CYAN}当前API密钥: {UNIFIED_API_KEY}{Style.RESET_ALL}")
    new_key = input(f"{Fore.YELLOW}请输入新的API密钥 (直接回车保持原样): {Style.RESET_ALL}").strip()
    if new_key:
        config["api"]["unified_api_key"] = new_key
        UNIFIED_API_KEY = new_key
        configure_openai_client()
        save_config(config)
        print(f"{Fore.GREEN}[OK] API密钥已更新并自动保存！{Style.RESET_ALL}")

def configure_api_url():
    global UNIFIED_BASE_URL, openai
    print(f"\n{Fore.CYAN}当前API地址: {UNIFIED_BASE_URL}{Style.RESET_ALL}")
    new_url = input(f"{Fore.YELLOW}请输入新的API地址 (直接回车保持原样): {Style.RESET_ALL}").strip()
    if new_url:
        config["api"]["unified_base_url"] = new_url
        UNIFIED_BASE_URL = new_url
        # 🔧 同步更新 core.config 和 core.globals 中的模块级变量
        try:
            import core.config as _cfg
            import core.globals as _glo
            _cfg.UNIFIED_BASE_URL = new_url
            _glo.UNIFIED_BASE_URL = new_url
        except Exception:
            pass
        configure_openai_client()
        save_config(config)
        print(f"{Fore.GREEN}[OK] API地址已更新并自动保存！{Style.RESET_ALL}")

def configure_brain_model():
    global MODEL_BRAIN
    print(f"\n{Fore.CYAN}当前思考模型: {MODEL_BRAIN}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}常用模型: gpt-3.5-turbo, gpt-4, gpt-4-turbo, claude-2, claude-instant, kimi-k2{Style.RESET_ALL}")
    new_model = input(f"{Fore.YELLOW}请输入新的思考模型 (直接回车保持原样): {Style.RESET_ALL}").strip()
    if new_model:
        config["api"]["model_brain"] = new_model
        MODEL_BRAIN = new_model
        save_config(config)
        print(f"{Fore.GREEN}[OK] 思考模型已更新并自动保存！{Style.RESET_ALL}")

def configure_vision_model():
    global MODEL_VISION
    print(f"\n{Fore.CYAN}当前视觉模型: {MODEL_VISION}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}常用模型: gpt-4-vision-preview, claude-3-opus, qwen-vl-max{Style.RESET_ALL}")
    new_model = input(f"{Fore.YELLOW}请输入新的视觉模型 (直接回车保持原样): {Style.RESET_ALL}").strip()
    if new_model:
        config["api"]["model_vision"] = new_model
        MODEL_VISION = new_model
        save_config(config)
        print(f"{Fore.GREEN}[OK] 视觉模型已更新并自动保存！{Style.RESET_ALL}")

def configure_vision_api_key():
    """设置视觉模型独立 API 密钥"""
    global VISION_API_KEY
    current = config["api"].get("vision_api_key", "")
    print(f"\n{Fore.CYAN}━━━ 视觉模型独立 API 密钥 ━━━{Style.RESET_ALL}")
    if current:
        print(f"{Fore.YELLOW}当前已配置独立视觉API密钥: {mask_secret(current)}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}留空将恢复使用统一API密钥: {mask_secret(UNIFIED_API_KEY)}{Style.RESET_ALL}")
    else:
        print(f"{Fore.CYAN}当前使用统一API密钥: {mask_secret(UNIFIED_API_KEY)}{Style.RESET_ALL}")
    new_key = input(f"{Fore.YELLOW}视觉API密钥 (留空使用统一密钥): {Style.RESET_ALL}").strip()
    if new_key:
        config["api"]["vision_api_key"] = new_key
        VISION_API_KEY = new_key
        save_config(config)
        print(f"{Fore.GREEN}[OK] 视觉模型独立API密钥已设置！{Style.RESET_ALL}")
    elif current:
        # 用户留空 → 清除独立配置
        config["api"]["vision_api_key"] = ""
        VISION_API_KEY = UNIFIED_API_KEY
        save_config(config)
        print(f"{Fore.GREEN}[OK] 已恢复使用统一API密钥{Style.RESET_ALL}")

def configure_vision_api_url():
    """设置视觉模型独立 API 地址"""
    global VISION_BASE_URL
    current = config["api"].get("vision_base_url", "")
    print(f"\n{Fore.CYAN}━━━ 视觉模型独立 API 地址 ━━━{Style.RESET_ALL}")
    if current:
        print(f"{Fore.YELLOW}当前已配置独立视觉API地址: {current}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}留空将恢复使用统一API地址: {UNIFIED_BASE_URL}{Style.RESET_ALL}")
    else:
        print(f"{Fore.CYAN}当前使用统一API地址: {UNIFIED_BASE_URL}{Style.RESET_ALL}")
    new_url = input(f"{Fore.YELLOW}视觉API地址 (留空使用统一地址): {Style.RESET_ALL}").strip()
    if new_url:
        config["api"]["vision_base_url"] = new_url
        VISION_BASE_URL = new_url
        save_config(config)
        print(f"{Fore.GREEN}[OK] 视觉模型独立API地址已设置！{Style.RESET_ALL}")
    elif current:
        config["api"]["vision_base_url"] = ""
        VISION_BASE_URL = UNIFIED_BASE_URL
        save_config(config)
        print(f"{Fore.GREEN}[OK] 已恢复使用统一API地址{Style.RESET_ALL}")

def clear_vision_independent_config():
    """一键清除视觉模型独立配置"""
    global VISION_API_KEY, VISION_BASE_URL
    print(f"\n{Fore.CYAN}━━━ 清除视觉模型独立配置 ━━━{Style.RESET_ALL}")
    has_key = bool(config["api"].get("vision_api_key", ""))
    has_url = bool(config["api"].get("vision_base_url", ""))
    if not has_key and not has_url:
        print(f"{Fore.YELLOW}[WARN] 当前没有独立视觉配置，无需清除{Style.RESET_ALL}")
        return
    confirm = input(f"{Fore.RED}确认清除视觉模型独立配置？(y/n): {Style.RESET_ALL}").strip().lower()
    if confirm == 'y':
        config["api"]["vision_api_key"] = ""
        config["api"]["vision_base_url"] = ""
        VISION_API_KEY = UNIFIED_API_KEY
        VISION_BASE_URL = UNIFIED_BASE_URL
        save_config(config)
        print(f"{Fore.GREEN}[OK] 已清除，视觉模型恢复使用统一API配置{Style.RESET_ALL}")

def configure_video_settings():
    global VIDEO_UNDERSTANDING_MODE, VIDEO_MAX_DURATION_SECONDS, VIDEO_FRAME_COUNT
    global VIDEO_DOWNLOAD_INTEREST_THRESHOLD, VIDEO_DOWNLOAD_DIR
    global VIDEO_FILTER_MODE
    global SMART_FRAME_ENABLED, SMART_FRAME_MIN, SMART_FRAME_MAX, VISION_FRAME_COUNT
    global VISION_COVER_ENABLED

    video_cfg = config.setdefault("video", {})
    vision_cfg = config.setdefault("vision", {})
    print(f"\n{Fore.CYAN}视频下载/抽帧设置{Style.RESET_ALL}")
    print(f"当前理解模式: {VIDEO_UNDERSTANDING_MODE} (subtitle/frames/hybrid/smart)")
    print(f"当前视频过滤: {VIDEO_FILTER_MODE} (watch_all=全看/cover_and_title=封面+标题判断)")
    print(f"当前封面分析: {'[OK] 开启' if VISION_COVER_ENABLED else '⏸️ 已关闭(刷视频更快)'}")
    print(f"当前下载时长上限: {VIDEO_MAX_DURATION_SECONDS} 秒")
    print(f"当前固定抽帧数量: {VIDEO_FRAME_COUNT} 张")
    print(f"当前视觉抽帧数量: {VISION_FRAME_COUNT} 张")
    print(f"当前智能下载阈值: {VIDEO_DOWNLOAD_INTEREST_THRESHOLD}")
    print(f"当前下载路径: {VIDEO_DOWNLOAD_DIR or '默认 Data/video_cache'}")
    print(f"\n{Fore.MAGENTA}[SMART_FRAME] AI智能抽帧:{Style.RESET_ALL}")
    print(f"  • 智能抽帧开关: {'[OK] 开启' if SMART_FRAME_ENABLED else '⏸️ 关闭'} (AI自行决定是否抽帧+数量)")
    print(f"  • 最小抽帧数: {SMART_FRAME_MIN} 张")
    print(f"  • 最大抽帧数: {SMART_FRAME_MAX} 张")

    cover_input = input(f"{Fore.YELLOW}是否开启封面分析？(y/n, 当前: {'开启' if VISION_COVER_ENABLED else '关闭(刷视频更快)'}, 回车保持): {Style.RESET_ALL}").strip().lower()
    if cover_input:
        if cover_input in {'y', 'n'}:
            VISION_COVER_ENABLED = (cover_input == 'y')
            vision_cfg["cover_enabled"] = VISION_COVER_ENABLED
            print(f"{Fore.GREEN}[OK] 封面分析已{'开启' if VISION_COVER_ENABLED else '关闭(刷视频更快)'}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}[WARN] 输入无效，已保持原样{Style.RESET_ALL}")

    new_mode = input(f"{Fore.YELLOW}请输入理解模式 (subtitle/frames/hybrid/smart, 回车保持): {Style.RESET_ALL}").strip().lower()
    if new_mode:
        if new_mode in {"subtitle", "frames", "hybrid", "smart"}:
            video_cfg["mode"] = new_mode
            VIDEO_UNDERSTANDING_MODE = new_mode
            print(f"{Fore.GREEN}[OK] 理解模式已更新为 {new_mode}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}[WARN] 模式无效，已保持原样{Style.RESET_ALL}")

    new_filter = input(f"{Fore.YELLOW}请输入视频过滤模式 (watch_all/cover_and_title, 回车保持): {Style.RESET_ALL}").strip().lower()
    if new_filter:
        if new_filter in {"watch_all", "cover_and_title"}:
            video_cfg["filter_mode"] = new_filter
            VIDEO_FILTER_MODE = new_filter
            print(f"{Fore.GREEN}[OK] 视频过滤模式已更新为 {new_filter}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}[WARN] 过滤模式无效 (仅支持 watch_all / cover_and_title)，已保持原样{Style.RESET_ALL}")

    raw_duration = input(f"{Fore.YELLOW}请输入最大下载时长秒数 (1-86400, 回车保持): {Style.RESET_ALL}").strip()
    if raw_duration:
        try:
            value = int(raw_duration)
            if 1 <= value <= 24 * 3600:
                video_cfg["max_duration_seconds"] = value
                VIDEO_MAX_DURATION_SECONDS = value
                print(f"{Fore.GREEN}[OK] 下载时长上限已更新为 {value} 秒{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 时长超出范围，已保持原样{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.YELLOW}[WARN] 时长不是整数，已保持原样{Style.RESET_ALL}")

    raw_frames = input(f"{Fore.YELLOW}请输入固定抽帧数量 (1-60, 回车保持): {Style.RESET_ALL}").strip()
    if raw_frames:
        try:
            value = int(raw_frames)
            if 1 <= value <= 60:
                video_cfg["frame_count"] = value
                VIDEO_FRAME_COUNT = value
                print(f"{Fore.GREEN}[OK] 抽帧数量已更新为 {value} 张{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 抽帧数量超出范围，已保持原样{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.YELLOW}[WARN] 抽帧数量不是整数，已保持原样{Style.RESET_ALL}")

    # [SMART_FRAME] AI智能抽帧设置
    print(f"\n{Fore.MAGENTA}--- AI智能抽帧设置 ---{Style.RESET_ALL}")
    smart_enable_input = input(f"{Fore.YELLOW}是否开启AI智能抽帧？(y/n, 当前: {'开启' if SMART_FRAME_ENABLED else '关闭'}, 回车保持): {Style.RESET_ALL}").strip().lower()
    if smart_enable_input in ("y", "n"):
        SMART_FRAME_ENABLED = (smart_enable_input == "y")
        vision_cfg["smart_frame_enabled"] = SMART_FRAME_ENABLED
        print(f"{Fore.GREEN}[OK] AI智能抽帧已{'开启' if SMART_FRAME_ENABLED else '关闭'}{Style.RESET_ALL}")

    raw_min = input(f"{Fore.YELLOW}请输入最小抽帧数 (10-300, 当前: {SMART_FRAME_MIN}, 回车保持): {Style.RESET_ALL}").strip()
    if raw_min:
        try:
            value = int(raw_min)
            if 10 <= value <= 300:
                SMART_FRAME_MIN = value
                vision_cfg["smart_frame_min"] = value
                print(f"{Fore.GREEN}[OK] 最小抽帧数已更新为 {value}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 超出范围(10-300)，已保持原样{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.YELLOW}[WARN] 不是整数，已保持原样{Style.RESET_ALL}")

    raw_max = input(f"{Fore.YELLOW}请输入最大抽帧数 (10-300, 当前: {SMART_FRAME_MAX}, 回车保持): {Style.RESET_ALL}").strip()
    if raw_max:
        try:
            value = int(raw_max)
            if 10 <= value <= 300:
                SMART_FRAME_MAX = value
                vision_cfg["smart_frame_max"] = value
                print(f"{Fore.GREEN}[OK] 最大抽帧数已更新为 {value}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 超出范围(10-300)，已保持原样{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.YELLOW}[WARN] 不是整数，已保持原样{Style.RESET_ALL}")

    raw_vision_frames = input(f"{Fore.YELLOW}请输入视觉兜底抽帧数 (智能抽帧关闭时使用, 1-60, 当前: {VISION_FRAME_COUNT}, 回车保持): {Style.RESET_ALL}").strip()
    if raw_vision_frames:
        try:
            value = int(raw_vision_frames)
            if 1 <= value <= 60:
                vision_cfg["frame_count"] = value
                VISION_FRAME_COUNT = value
                print(f"{Fore.GREEN}[OK] 视觉兜底抽帧数已更新为 {value}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 超出范围(1-60)，已保持原样{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.YELLOW}[WARN] 不是整数，已保持原样{Style.RESET_ALL}")

    raw_threshold = input(f"{Fore.YELLOW}请输入智能下载阈值 (0-10, 回车保持): {Style.RESET_ALL}").strip()
    if raw_threshold:
        try:
            value = float(raw_threshold)
            if 0 <= value <= 10:
                video_cfg["download_interest_threshold"] = value
                VIDEO_DOWNLOAD_INTEREST_THRESHOLD = value
                print(f"{Fore.GREEN}[OK] 智能下载阈值已更新为 {value}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 阈值超出范围，已保持原样{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.YELLOW}[WARN] 阈值不是数字，已保持原样{Style.RESET_ALL}")

    new_path = input(f"{Fore.YELLOW}请输入新下载路径 (回车保持，留空继续用当前路径): {Style.RESET_ALL}").strip().strip('"')
    if new_path:
        video_cfg["download_dir"] = new_path
        VIDEO_DOWNLOAD_DIR = new_path
        print(f"{Fore.GREEN}[OK] 视频下载路径已更新: {new_path}{Style.RESET_ALL}")

    if save_config(config):
        print(f"{Fore.GREEN}[OK] 视频设置已保存{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}[ERROR] 视频设置保存失败{Style.RESET_ALL}")


def _configure_video_interval_settings():
    """配置视频间隔（短暂休息的随机最小/最大秒数）"""
    global config, VIDEO_INTERVAL_MIN, VIDEO_INTERVAL_MAX
    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                ⏱️ 视频间隔设置                            ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 最小间隔: {Fore.YELLOW}{VIDEO_INTERVAL_MIN}{Style.RESET_ALL} 秒
    • 最大间隔: {Fore.YELLOW}{VIDEO_INTERVAL_MAX}{Style.RESET_ALL} 秒
    • 实际间隔在 [{VIDEO_INTERVAL_MIN}, {VIDEO_INTERVAL_MAX}] 之间随机

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} 设置最小间隔 (秒)
    {Fore.BLUE}2.{Style.RESET_ALL} 设置最大间隔 (秒)
    {Fore.YELLOW}3.{Style.RESET_ALL} 快速预设: 慢速 (60-120秒, 模拟真人)
    {Fore.YELLOW}4.{Style.RESET_ALL} 快速预设: 中速 (20-50秒)
    {Fore.YELLOW}5.{Style.RESET_ALL} 快速预设: 快速 (5-15秒, 激进)
    {Fore.YELLOW}6.{Style.RESET_ALL} 快速预设: 极速 (1-3秒, 刷屏)\n    {Fore.GREEN}   ★ 当前默认: 极速 (1-5秒){Style.RESET_ALL}
    {Fore.RED}0.{Style.RESET_ALL} 返回主菜单
    """)
        choice = input(f"{Fore.CYAN}请输入选项: {Style.RESET_ALL}").strip()
        if choice == "0":
            break
        elif choice == "1":
            try:
                val = int(input(f"最小间隔秒数 (当前: {VIDEO_INTERVAL_MIN}): "))
                if val < 1:
                    val = 1
                if val > VIDEO_INTERVAL_MAX:
                    print(f"{Fore.YELLOW}[WARN] 最小值({val})不能大于最大值({VIDEO_INTERVAL_MAX})，已自动调整最大值{Style.RESET_ALL}")
                    VIDEO_INTERVAL_MAX = val
                VIDEO_INTERVAL_MIN = val
                config["energy"]["video_interval_min"] = val
                if save_config(config):
                    _reload_all_globals(config)
                    print(f"{Fore.GREEN}[OK] 最小间隔已更新为 {val} 秒{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}[ERROR] 请输入有效数字{Style.RESET_ALL}")
        elif choice == "2":
            try:
                val = int(input(f"最大间隔秒数 (当前: {VIDEO_INTERVAL_MAX}): "))
                if val < 1:
                    val = 1
                if val < VIDEO_INTERVAL_MIN:
                    print(f"{Fore.YELLOW}[WARN] 最大值({val})不能小于最小值({VIDEO_INTERVAL_MIN})，已自动调整最小值{Style.RESET_ALL}")
                    VIDEO_INTERVAL_MIN = val
                VIDEO_INTERVAL_MAX = val
                config["energy"]["video_interval_max"] = val
                if save_config(config):
                    _reload_all_globals(config)
                    print(f"{Fore.GREEN}[OK] 最大间隔已更新为 {val} 秒{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}[ERROR] 请输入有效数字{Style.RESET_ALL}")
        elif choice == "3":
            VIDEO_INTERVAL_MIN, VIDEO_INTERVAL_MAX = 60, 120
        elif choice == "4":
            VIDEO_INTERVAL_MIN, VIDEO_INTERVAL_MAX = 20, 50
        elif choice == "5":
            VIDEO_INTERVAL_MIN, VIDEO_INTERVAL_MAX = 5, 15
        elif choice == "6":
            VIDEO_INTERVAL_MIN, VIDEO_INTERVAL_MAX = 1, 3
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")
            continue
        if choice in ("3", "4", "5", "6"):
            config["energy"]["video_interval_min"] = VIDEO_INTERVAL_MIN
            config["energy"]["video_interval_max"] = VIDEO_INTERVAL_MAX
            if save_config(config):
                _reload_all_globals(config)
                print(f"{Fore.GREEN}[OK] 视频间隔已更新为 {VIDEO_INTERVAL_MIN}-{VIDEO_INTERVAL_MAX} 秒{Style.RESET_ALL}")


def _configure_asr_settings():
    """ASR语音识别子设置"""
    global ASR_ENABLED, ASR_BACKEND, ASR_WHISPER_MODEL, ASR_LANGUAGE, ASR_SPEAKER_SEPARATION
    global ASR_MAX_AUDIO_DURATION, ASR_MIN_CONFIDENCE, ASR_SKIP_MUSIC, ASR_KEEP_AUDIO, ASR_DEVICE
    global ASR_FUNASR_MODEL_DIR, ASR_FUNASR_VAD_ENABLED, ASR_FUNASR_PUNC_ENABLED
    global ASR_FUNASR_SPK_ENABLED, ASR_FUNASR_BATCH_SIZE_S, ASR_FUNASR_HOTWORD

    asr_cfg = config.setdefault("asr", {})

    # ═══ 引擎选择 ═══
    print(f"  识别引擎: {Fore.CYAN}{ASR_BACKEND.upper()}{Style.RESET_ALL} (funasr=Paraformer中文最优 / whisper=多语言通用)")
    new_backend = input(f"{Fore.YELLOW}切换引擎？(funasr/whisper, 回车保持): {Style.RESET_ALL}").strip().lower()
    if new_backend in ("funasr", "whisper"):
        ASR_BACKEND = new_backend
        asr_cfg["backend"] = new_backend
        # 清除缓存
        from xingye_bot.asr_engine import _asr_engine as _eng
        if _eng:
            _eng._model = None
            _eng._backend_loaded = ""
            _eng._funasr_available = None
        print(f"{Fore.GREEN}[OK] 引擎已切换为 {ASR_BACKEND.upper()}{Style.RESET_ALL}")

    # ═══ FunASR 专用配置 ═══
    if ASR_BACKEND == "funasr":
        print(f"\n  {Fore.CYAN}── FunASR (Paraformer) 配置 ──{Style.RESET_ALL}")
        print(f"  模型目录: {ASR_FUNASR_MODEL_DIR or '(自动检测)'}")
        print(f"  VAD语音检测: {'✓ 启用' if ASR_FUNASR_VAD_ENABLED else '✗ 关闭'}")
        print(f"  自动标点: {'✓ 启用' if ASR_FUNASR_PUNC_ENABLED else '✗ 关闭'}")
        print(f"  说话人分离(cam++): {'✓ 启用' if ASR_FUNASR_SPK_ENABLED else '✗ 关闭'}")
        print(f"  批处理时长: {ASR_FUNASR_BATCH_SIZE_S}s")
        print(f"  热词: {ASR_FUNASR_HOTWORD or '(无)'}")

        new_dir = input(f"{Fore.YELLOW}模型目录路径 (回车保持自动检测): {Style.RESET_ALL}").strip().strip('"')
        if new_dir:
            if os.path.isdir(new_dir):
                asr_cfg["funasr_model_dir"] = new_dir
                ASR_FUNASR_MODEL_DIR = new_dir
                print(f"{Fore.GREEN}[OK] 模型目录已更新{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] 目录不存在: {new_dir}{Style.RESET_ALL}")

        toggle_vad = input(f"{Fore.YELLOW}切换VAD语音检测？(y/N): {Style.RESET_ALL}").strip().lower()
        if toggle_vad == "y":
            ASR_FUNASR_VAD_ENABLED = not ASR_FUNASR_VAD_ENABLED
            asr_cfg["funasr_vad_enabled"] = ASR_FUNASR_VAD_ENABLED

        toggle_punc = input(f"{Fore.YELLOW}切换自动标点？(y/N): {Style.RESET_ALL}").strip().lower()
        if toggle_punc == "y":
            ASR_FUNASR_PUNC_ENABLED = not ASR_FUNASR_PUNC_ENABLED
            asr_cfg["funasr_punc_enabled"] = ASR_FUNASR_PUNC_ENABLED

        toggle_spk = input(f"{Fore.YELLOW}切换cam++说话人分离？(y/N): {Style.RESET_ALL}").strip().lower()
        if toggle_spk == "y":
            ASR_FUNASR_SPK_ENABLED = not ASR_FUNASR_SPK_ENABLED
            asr_cfg["funasr_spk_enabled"] = ASR_FUNASR_SPK_ENABLED

        raw_batch = input(f"{Fore.YELLOW}批处理时长秒数 (60-600, 回车保持): {Style.RESET_ALL}").strip()
        if raw_batch:
            try:
                v = int(raw_batch)
                if 60 <= v <= 600:
                    asr_cfg["funasr_batch_size_s"] = v
                    ASR_FUNASR_BATCH_SIZE_S = v
            except ValueError as e:
                log(f'值错误: {e}', 'DEBUG')

        raw_hw = input(f"{Fore.YELLOW}热词（逗号分隔，如: 魔搭,AI,算法）: {Style.RESET_ALL}").strip()
        if raw_hw:
            asr_cfg["funasr_hotword"] = raw_hw
            ASR_FUNASR_HOTWORD = raw_hw

        # 清除 FunASR 缓存
        from xingye_bot.asr_engine import _asr_engine as _eng
        if _eng:
            _eng._model = None
            _eng._backend_loaded = ""
            _eng._funasr_available = None

    # ═══ 通用配置 ═══
    print(f"\n  {Fore.CYAN}── 通用配置 ──{Style.RESET_ALL}")
    print(f"  总开关: {'✓ 启用' if ASR_ENABLED else '✗ 关闭'}")
    print(f"  识别语言: {ASR_LANGUAGE} (zh=中文/en=英文/auto=自动)")
    print(f"  音频时长上限: {ASR_MAX_AUDIO_DURATION}s")
    print(f"  最低置信度: {ASR_MIN_CONFIDENCE}")
    print(f"  跳过音乐类: {'✓ 是' if ASR_SKIP_MUSIC else '✗ 否'}")
    print(f"  保留音频文件: {'✓ 是' if ASR_KEEP_AUDIO else '✗ 否'}")
    print(f"  运行设备: {ASR_DEVICE} (cpu/cuda)")

    toggle = input(f"{Fore.YELLOW}切换ASR总开关？(y/N): {Style.RESET_ALL}").strip().lower()
    if toggle == "y":
        ASR_ENABLED = not ASR_ENABLED
        asr_cfg["enabled"] = ASR_ENABLED
        print(f"{Fore.GREEN}[OK] ASR已{'启用' if ASR_ENABLED else '关闭'}{Style.RESET_ALL}")

    new_lang = input(f"{Fore.YELLOW}识别语言 (zh/en/auto, 回车保持): {Style.RESET_ALL}").strip().lower()
    if new_lang in ("zh", "en", "auto"):
        asr_cfg["language"] = new_lang
        ASR_LANGUAGE = new_lang

    raw_dur = input(f"{Fore.YELLOW}音频时长上限秒数 (60-14400, 回车保持): {Style.RESET_ALL}").strip()
    if raw_dur:
        try:
            v = int(raw_dur)
            if 60 <= v <= 14400:
                asr_cfg["max_audio_duration"] = v
                ASR_MAX_AUDIO_DURATION = v
        except ValueError as e:
            log(f'值错误: {e}', 'DEBUG')

    raw_conf = input(f"{Fore.YELLOW}最低置信度 (0.0-1.0, 回车保持): {Style.RESET_ALL}").strip()
    if raw_conf:
        try:
            v = float(raw_conf)
            if 0 <= v <= 1:
                asr_cfg["min_confidence"] = v
                ASR_MIN_CONFIDENCE = v
        except ValueError as e:
            log(f'值错误: {e}', 'DEBUG')

    toggle_music = input(f"{Fore.YELLOW}切换跳过音乐类视频？(y/N): {Style.RESET_ALL}").strip().lower()
    if toggle_music == "y":
        ASR_SKIP_MUSIC = not ASR_SKIP_MUSIC
        asr_cfg["skip_music"] = ASR_SKIP_MUSIC

    toggle_keep = input(f"{Fore.YELLOW}切换保留音频文件？(y/N): {Style.RESET_ALL}").strip().lower()
    if toggle_keep == "y":
        ASR_KEEP_AUDIO = not ASR_KEEP_AUDIO
        asr_cfg["keep_audio"] = ASR_KEEP_AUDIO

    new_dev = input(f"{Fore.YELLOW}运行设备 (cpu/cuda, 回车保持): {Style.RESET_ALL}").strip().lower()
    if new_dev in ("cpu", "cuda"):
        asr_cfg["device"] = new_dev
        ASR_DEVICE = new_dev
        from xingye_bot.asr_engine import _asr_engine as _eng
        if _eng:
            _eng.device = new_dev
            _eng._model = None

    # ═══ Whisper 模型选择（仅在 whisper 后端时显示）═══
    if ASR_BACKEND == "whisper":
        print(f"\n  {Fore.CYAN}── Whisper 模型选择 ──{Style.RESET_ALL}")
        print(f"  当前模型: {ASR_WHISPER_MODEL}")
        new_model = input(f"{Fore.YELLOW}Whisper模型 (tiny/base/small/medium/large, 回车保持): {Style.RESET_ALL}").strip().lower()
        if new_model in ("tiny", "base", "small", "medium", "large"):
            asr_cfg["whisper_model"] = new_model
            ASR_WHISPER_MODEL = new_model
            print(f"{Fore.GREEN}[OK] Whisper模型已更新为 {new_model}{Style.RESET_ALL}")
            from xingye_bot.asr_engine import _asr_engine as _eng
            if _eng:
                _eng._model = None
                _eng._backend_loaded = ""

    # 说话人分离（通用开关）
    toggle_sp = input(f"{Fore.YELLOW}切换说话人分离（通用开关）？(y/N): {Style.RESET_ALL}").strip().lower()
    if toggle_sp == "y":
        ASR_SPEAKER_SEPARATION = not ASR_SPEAKER_SEPARATION
        asr_cfg["speaker_separation"] = ASR_SPEAKER_SEPARATION

def _configure_dry_goods_settings():
    """Highlights archive settings: toggle + minimum score threshold"""
    global DRY_GOODS_ENABLED, DRY_GOODS_MIN_SCORE, DRY_GOODS_FOLDER_NAME

    dg = config.setdefault("dry_goods", {})
    dg.setdefault("enabled", False)
    dg.setdefault("min_score", 7.5)
    dg.setdefault("folder_name", "highlights")

    while True:
        status = Fore.GREEN + "✓ Enabled" + Style.RESET_ALL if DRY_GOODS_ENABLED else Fore.YELLOW + "💤 Disabled" + Style.RESET_ALL
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║              [GOLD] 干货归档设置                            ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前:{Style.RESET_ALL}
    • 状态: {status}
    • 最低评分: {Fore.YELLOW}>= {DRY_GOODS_MIN_SCORE}{Style.RESET_ALL}
    • 归档目录: {Fore.CYAN}{DRY_GOODS_DIR}{Style.RESET_ALL}

    {Fore.CYAN}说明:{Style.RESET_ALL}
    AI评分 >= 阈值的视频会自动复制到 highlights/ 目录，方便快速访问优质内容。
    不影响常规知识库归档。

    {Fore.CYAN}请选择:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} 🔄 切换 ({'关闭' if DRY_GOODS_ENABLED else '开启'})
    {Fore.YELLOW}2.{Style.RESET_ALL} ⚙️  修改最低评分门槛
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}Enter option (0-2): {Style.RESET_ALL}").strip()
        if choice == "0":
            break
        elif choice == "1":
            DRY_GOODS_ENABLED = not DRY_GOODS_ENABLED
            dg["enabled"] = DRY_GOODS_ENABLED
            save_config(config)
            print(f"{Fore.GREEN}[OK] 干货归档已{'开启' if DRY_GOODS_ENABLED else '关闭'}{Style.RESET_ALL}")
        elif choice == "2":
            raw = input(f"{Fore.YELLOW}最低评分门槛 (0-10, 当前 {DRY_GOODS_MIN_SCORE}): {Style.RESET_ALL}").strip()
            if raw:
                try:
                    val = max(0.0, min(10.0, float(raw)))
                    DRY_GOODS_MIN_SCORE = val
                    dg["min_score"] = val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] Min score updated to >= {val}{Style.RESET_ALL}")
                except (ValueError, TypeError):
                    print(f"{Fore.YELLOW}[WARN] Invalid input, unchanged{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] Invalid option{Style.RESET_ALL}")

def configure_session_params():
    """配置会话限制（定时/计数停止）"""
    global SESSION_MAX_VIDEOS, SESSION_MAX_DURATION_MINUTES

    session_cfg = config.setdefault("session", {})
    print(f"\n{Fore.CYAN}[TIME]  会话限制设置{Style.RESET_ALL}")
    print(f"当前最多处理视频: {'不限' if SESSION_MAX_VIDEOS <= 0 else f'{SESSION_MAX_VIDEOS}个'}")
    print(f"当前最长运行时间: {'不限' if SESSION_MAX_DURATION_MINUTES <= 0 else f'{SESSION_MAX_DURATION_MINUTES}分钟'}")
    print(f"{Fore.YELLOW}（设为0表示不限制，两个条件任一触发即停止）{Style.RESET_ALL}")

    raw_videos = input(f"{Fore.YELLOW}请输入最多处理视频数 (0=不限, 回车保持): {Style.RESET_ALL}").strip()
    if raw_videos:
        try:
            value = int(raw_videos)
            if value >= 0:
                session_cfg["max_videos"] = value
                SESSION_MAX_VIDEOS = value
                print(f"{Fore.GREEN}[OK] 最多处理视频数已更新为 {'不限' if value <= 0 else f'{value}个'}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 数值无效，已保持原样{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.YELLOW}[WARN] 不是整数，已保持原样{Style.RESET_ALL}")

    raw_duration = input(f"{Fore.YELLOW}请输入最长运行分钟数 (0=不限, 回车保持): {Style.RESET_ALL}").strip()
    if raw_duration:
        try:
            value = int(raw_duration)
            if value >= 0:
                session_cfg["max_duration_minutes"] = value
                SESSION_MAX_DURATION_MINUTES = value
                print(f"{Fore.GREEN}[OK] 最长运行时间已更新为 {'不限' if value <= 0 else f'{value}分钟'}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 数值无效，已保持原样{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.YELLOW}[WARN] 不是整数，已保持原样{Style.RESET_ALL}")

    if save_config(config):
        print(f"{Fore.GREEN}[OK] 会话限制设置已保存{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}[ERROR] 会话限制设置保存失败{Style.RESET_ALL}")

def configure_interaction_params():
    global PROB_COMMENT_OTHERS, COMMENT_CHECK_INTERVAL, PROB_REPLY_TRIGGER, PROB_COIN, PROB_FAV, PROB_LIKE_SOLO, COMMENT_CHECK_ENABLED, PRIVATE_MESSAGE_ENABLED, RANDOM_ENABLED
    
    print(f"\n{Fore.CYAN}互动参数配置{Style.RESET_ALL}")
    print(f"当前投币阈值: {COIN_THRESHOLD}")
    try:
        new_value = float(input(f"{Fore.YELLOW}请输入新的投币阈值 (0-10, 直接回车保持原样): {Style.RESET_ALL}").strip())
        if 0 <= new_value <= 10:
            config["interaction"]["coin_threshold"] = new_value
            print(f"{Fore.GREEN}[OK] 投币阈值已更新为 {new_value}!{Style.RESET_ALL}")
    except (ValueError, TypeError) as e:
        log(f'类型转换失败: {e}', 'DEBUG')

    print(f"\n当前收藏阈值: {FAV_THRESHOLD}")
    try:
        new_value = float(input(f"{Fore.YELLOW}请输入新的收藏阈值 (0-10, 直接回车保持原样): {Style.RESET_ALL}").strip())
        if 0 <= new_value <= 10:
            config["interaction"]["fav_threshold"] = new_value
            print(f"{Fore.GREEN}[OK] 收藏阈值已更新为 {new_value}!{Style.RESET_ALL}")
    except (ValueError, TypeError) as e:
        log(f'类型转换失败: {e}', 'DEBUG')
    
    print(f"\n当前兴趣阈值 (低于此分跳过): {INTEREST_THRESHOLD}")
    try:
        new_value = float(input(f"{Fore.YELLOW}请输入新的兴趣阈值 (0-10, 直接回车保持原样): {Style.RESET_ALL}").strip())
        if 0 <= new_value <= 10:
            config["interaction"]["interest_threshold"] = new_value
            print(f"{Fore.GREEN}[OK] 兴趣阈值已更新为 {new_value}!{Style.RESET_ALL}")
    except (ValueError, TypeError) as e:
        log(f'类型转换失败: {e}', 'DEBUG')
    
    print(f"\n当前学习归档最低分 (低于此分不归档): {LEARN_MIN_SCORE}")
    try:
        new_value = float(input(f"{Fore.YELLOW}请输入学习归档最低分 (0-10, 直接回车保持原样): {Style.RESET_ALL}").strip())
        if 0 <= new_value <= 10:
            config["interaction"]["learn_min_score"] = new_value
            print(f"{Fore.GREEN}[OK] 学习归档最低分已更新为 {new_value}!{Style.RESET_ALL}")
    except (ValueError, TypeError) as e:
        log(f'类型转换失败: {e}', 'DEBUG')
    
    print(f"\n当前学习归档最低视频时长: {LEARN_MIN_DURATION_SECONDS}秒")
    try:
        new_value = int(input(f"{Fore.YELLOW}请输入最低时长(秒, 直接回车保持原样): {Style.RESET_ALL}").strip())
        if new_value >= 0:
            config["interaction"]["learn_min_duration_seconds"] = new_value
            print(f"{Fore.GREEN}[OK] 最低视频时长已更新为 {new_value}秒!{Style.RESET_ALL}")
    except (ValueError, TypeError) as e:
        log(f'类型转换失败: {e}', 'DEBUG')
    
    print(f"\n当前评论他人评论概率: {PROB_COMMENT_OTHERS*100}%")
    try:
        new_value = float(input(f"{Fore.YELLOW}请输入新的评论概率 (0-1, 直接回车保持原样): {Style.RESET_ALL}").strip())
        if 0 <= new_value <= 1:
            config["interaction"]["prob_comment_others"] = new_value
            PROB_COMMENT_OTHERS = new_value
            print(f"{Fore.GREEN}[OK] 评论概率已更新为 {new_value*100}%!{Style.RESET_ALL}")
    except (ValueError, TypeError) as e:
        log(f'类型转换失败: {e}', 'DEBUG')
    
    print(f"\n当前检查评论间隔: {COMMENT_CHECK_INTERVAL}秒")
    try:
        new_value = int(input(f"{Fore.YELLOW}请输入新的检查间隔 (秒, 直接回车保持原样): {Style.RESET_ALL}").strip())
        if new_value > 0:
            config["interaction"]["comment_check_interval"] = new_value
            COMMENT_CHECK_INTERVAL = new_value
            print(f"{Fore.GREEN}[OK] 检查间隔已更新为 {new_value}秒!{Style.RESET_ALL}")
    except (ValueError, TypeError) as e:
        log(f'类型转换失败: {e}', 'DEBUG')

    print(f"\n当前评论检查总开关: {'[OK] 启用' if COMMENT_CHECK_ENABLED else '⏸️ 关闭'}")
    toggle = input(f"{Fore.YELLOW}切换？(y=切换, 直接回车保持): {Style.RESET_ALL}").strip().lower()
    if toggle == 'y':
        COMMENT_CHECK_ENABLED = not COMMENT_CHECK_ENABLED
        config["interaction"]["comment_check_enabled"] = COMMENT_CHECK_ENABLED
        print(f"{Fore.GREEN}[OK] 评论检查已{'启用' if COMMENT_CHECK_ENABLED else '关闭'}!{Style.RESET_ALL}")

    print(f"\n当前随机数限制: {'🎲 已开启' if RANDOM_ENABLED else '🔒 已关闭'}")
    print(f"  {'开启时：AI意图需通过随机概率检定才执行（更自然、更像真人）' if RANDOM_ENABLED else '关闭时：只看AI意图和分数阈值，跳过随机检定（更激进）'}")
    toggle_rand = input(f"{Fore.YELLOW}切换？(y=切换, 直接回车保持): {Style.RESET_ALL}").strip().lower()
    if toggle_rand == 'y':
        RANDOM_ENABLED = not RANDOM_ENABLED
        config["interaction"]["random_enabled"] = RANDOM_ENABLED
        print(f"{Fore.GREEN}[OK] 随机数限制已{'开启 (随机检定)' if RANDOM_ENABLED else '关闭 (纯分数)'}!{Style.RESET_ALL}")

    print(f"\n当前私信互动总开关: {'[OK] 启用' if PRIVATE_MESSAGE_ENABLED else '⏸️ 关闭'}")
    toggle_pm = input(f"{Fore.YELLOW}切换？(y=切换, 直接回车保持): {Style.RESET_ALL}").strip().lower()
    if toggle_pm == 'y':
        PRIVATE_MESSAGE_ENABLED = not PRIVATE_MESSAGE_ENABLED
        config.setdefault("private_message", {})["enabled"] = PRIVATE_MESSAGE_ENABLED
        print(f"{Fore.GREEN}[OK] 私信互动已{'启用' if PRIVATE_MESSAGE_ENABLED else '关闭'}!{Style.RESET_ALL}")

    # 自动保存
    save_config(config)

def configure_energy_params():
    global MAX_ENERGY
    print(f"\n{Fore.CYAN}精力系统参数配置{Style.RESET_ALL}")
    print(f"当前精力最大值: {MAX_ENERGY}")
    try:
        new_value = int(input(f"{Fore.YELLOW}请输入新的精力最大值 (1-1000, 直接回车保持原样): {Style.RESET_ALL}").strip())
        if 1 <= new_value <= 1000:
            config["interaction"]["max_energy"] = new_value
            MAX_ENERGY = new_value
            print(f"{Fore.GREEN}[OK] 精力最大值已更新为 {new_value}!{Style.RESET_ALL}")
    except (ValueError, TypeError) as e:
        log(f'类型转换失败: {e}', 'DEBUG')
    
    # 自动保存
    save_config(config)

def show_current_config():
    """显示当前配置"""
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.CYAN}                     当前配置详情{Style.RESET_ALL}")
    print(f"{Fore.CYAN}════════════════════════════════════════════════════════════{Style.RESET_ALL}")

    print(f"\n{Fore.YELLOW}📡 API配置:{Style.RESET_ALL}")
    print(f"  • API密钥: {UNIFIED_API_KEY[:15]}...{UNIFIED_API_KEY[-5:] if len(UNIFIED_API_KEY) > 20 else ''}")
    print(f"  • API地址: {UNIFIED_BASE_URL}")
    print(f"  • 思考模型: {MODEL_BRAIN}")
    print(f"  • 视觉模型: {MODEL_VISION}")

    print(f"\n{Fore.YELLOW}[TARGET] 互动参数:{Style.RESET_ALL}")
    print(f"  • 投币阈值: {COIN_THRESHOLD}")
    print(f"  • 收藏阈值: {FAV_THRESHOLD}")
    print(f"  • 兴趣阈值: {INTEREST_THRESHOLD}（低于此分不互动）")
    print(f"  • 学习归档最低分: {LEARN_MIN_SCORE}（低于此分不归档）")
    print(f"  • 学习归档最低时长: {LEARN_MIN_DURATION_SECONDS}秒")
    print(f"  • 每日最大投币: {MAX_COINS_DAILY}")
    print(f"  • 回复触发概率: {PROB_REPLY_TRIGGER*100}%")
    print(f"  • 评论他人概率: {PROB_COMMENT_OTHERS*100}%")
    print(f"  • 评论检查: {'[OK] 启用' if COMMENT_CHECK_ENABLED else '⏸️ 关闭'} | 间隔: {COMMENT_CHECK_INTERVAL}秒")
    print(f"  • 随机数限制: {'🎲 开启' if RANDOM_ENABLED else '🔒 关闭'} | 关闭时跳过随机检定，只看分数阈值")
    print(f"  • 私信互动: {'[OK] 启用' if PRIVATE_MESSAGE_ENABLED else '⏸️ 关闭'} | {'自动发送' if PRIVATE_MESSAGE_AUTO_REPLY else '仅拟不发送'} | 间隔: {PRIVATE_MESSAGE_CHECK_INTERVAL}秒")

    print(f"\n{Fore.YELLOW}[FAST] 精力系统:{Style.RESET_ALL}")
    print(f"  • 最大精力值: {MAX_ENERGY}")
    print(f"  • 每轮恢复: {ENERGY_RECOVERY_MIN}-{ENERGY_RECOVERY_MAX}点")
    print(f"  • 恢复轮数: {ROUNDS_MIN}-{ROUNDS_MAX}轮")
    print(f"  • 恢复间隔: {ROUND_INTERVAL_MIN}-{ROUND_INTERVAL_MAX}秒")
    print(f"  • 视频间隔: {VIDEO_INTERVAL_MIN}-{VIDEO_INTERVAL_MAX}秒")

    print(f"\n{Fore.YELLOW}[TIME]  防限流冷却:{Style.RESET_ALL}")
    print(f"  • 启动冷却: {COOLDOWN_STARTUP_MIN}-{COOLDOWN_STARTUP_MAX}秒")
    print(f"  • 评论后冷却: {COOLDOWN_POST_COMMENT_MIN}-{COOLDOWN_POST_COMMENT_MAX}秒")
    print(f"  • 私信后冷却: {COOLDOWN_POST_DM_MIN}-{COOLDOWN_POST_DM_MAX}秒")

    print(f"\n{Fore.YELLOW}[VIDEO] 视频理解:{Style.RESET_ALL}")
    print(f"  • 理解模式: {VIDEO_UNDERSTANDING_MODE}")
    print(f"  • 视频过滤: {VIDEO_FILTER_MODE} (watch_all=全看 / cover_and_title=封面+标题判断)")
    print(f"  • 下载时长上限: {VIDEO_MAX_DURATION_SECONDS}秒")
    print(f"  • 固定抽帧数量: {VIDEO_FRAME_COUNT}张")
    print(f"  • 智能下载阈值: {VIDEO_DOWNLOAD_INTEREST_THRESHOLD}")
    print(f"  • 下载路径: {VIDEO_DOWNLOAD_DIR or '默认 Data/video_cache'}")
    print(f"  • 封面分析: {'[OK] 开启' if VISION_COVER_ENABLED else '⏸️ 关闭(刷视频更快)'}")
    print(f"  • AI智能抽帧: {'[OK] 开启' if SMART_FRAME_ENABLED else '⏸️ 关闭'} | 范围: {SMART_FRAME_MIN}-{SMART_FRAME_MAX}帧 | 兜底: {VISION_FRAME_COUNT}帧")

    print(f"\n{Fore.YELLOW}[GOLD] 干货归档:{Style.RESET_ALL}")
    print(f"  • 干货归档: {'[OK] 已启用' if DRY_GOODS_ENABLED else '未启用'} | 最低评分: {DRY_GOODS_MIN_SCORE}")
    print(f"  • 深度看视频: 初始{CURIOSITY_DEEP_DIVE_DEFAULT_VIDEOS}个 | 中等{CURIOSITY_DEEP_DIVE_MID_VIDEOS}个 | 丰富{CURIOSITY_DEEP_DIVE_HIGH_VIDEOS}个")
    print(f"  • 深度看触发: {'[OK] 启用' if CURIOSITY_DEEP_DIVE_ENABLED else '⏸️ 关闭'} | 最低: {CURIOSITY_DEEP_DIVE_MIN_SCORE}分 | 概率: {CURIOSITY_DEEP_DIVE_PROB*100}%")

    print(f"\n{Fore.YELLOW}[TIME]  会话限制:{Style.RESET_ALL}")
    print(f"  • 最多处理视频: {'不限' if SESSION_MAX_VIDEOS <= 0 else f'{SESSION_MAX_VIDEOS}个'}")
    print(f"  • 最长运行时间: {'不限' if SESSION_MAX_DURATION_MINUTES <= 0 else f'{SESSION_MAX_DURATION_MINUTES}分钟'}")

    print(f"\n{Fore.CYAN}════════════════════════════════════════════════════════════{Style.RESET_ALL}")

def show_login_menu():
    """显示登录配置菜单"""
    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                    登录配置菜单                          ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前状态:{Style.RESET_ALL}
    • Cookie文件: {Fore.GREEN + "✓ 有效" + Style.RESET_ALL if is_bili_logged_in() else (Fore.YELLOW + "⚠ 存在但无效" + Style.RESET_ALL if os.path.exists(COOKIE_FILE) else Fore.RED + "✗ 不存在" + Style.RESET_ALL)}

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} 🔑 重新登录（扫码）
    {Fore.YELLOW}2.{Style.RESET_ALL} 🗑️  清除登录信息
    {Fore.BLUE}3.{Style.RESET_ALL} 📋 检查登录状态
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-3): {Style.RESET_ALL}").strip()

        if choice == "0":
            break
        elif choice == "1":
            try:
                asyncio.run(login_bilibili())
            except json.decoder.JSONDecodeError as e:
                log(f"登录过程JSON解析错误（网络异常）: {e}", "ERROR")
                print(f"\n{Fore.YELLOW}[WARN]  登录失败：B站服务器返回异常，请检查网络后重试{Style.RESET_ALL}\n")
            except Exception as e:
                log(f"登录过程异常: {e}", "ERROR")
                print(f"\n{Fore.YELLOW}[WARN]  登录失败: {e}{Style.RESET_ALL}\n")
        elif choice == "2":
            clear_login_info()
        elif choice == "3":
            check_login_status()
        else:
            print(f"{Fore.RED}[ERROR] 无效选项，请重新选择！{Style.RESET_ALL}")

def show_interest_menu():
    """显示兴趣管理菜单"""
    interest_mgr = InterestManager()
    
    while True:
        interests = interest_mgr.get_interests()
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                   兴趣管理菜单                           ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前兴趣列表 ({len(interests)}个):{Style.RESET_ALL}
    """)
        
        if interests:
            for i, interest in enumerate(interests, 1):
                print(f"  {i}. {interest}")
        else:
            print(f"  {Fore.YELLOW}(空) 机器人将对所有视频感兴趣{Style.RESET_ALL}")
        
        print(f"""
    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} ➕ 添加兴趣关键词
    {Fore.YELLOW}2.{Style.RESET_ALL} ➖ 移除兴趣关键词
    {Fore.BLUE}3.{Style.RESET_ALL} 📋 清空所有兴趣
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)
        
        choice = input(f"{Fore.CYAN}请输入选项 (0-3): {Style.RESET_ALL}").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            keyword = input(f"{Fore.YELLOW}请输入兴趣关键词 (如: AI, 科技, 游戏): {Style.RESET_ALL}").strip()
            if keyword:
                interest_mgr.add_interest(keyword)
            else:
                print(f"{Fore.RED}[ERROR] 关键词不能为空！{Style.RESET_ALL}")
        elif choice == "2":
            if interests:
                try:
                    idx = int(input(f"{Fore.YELLOW}请输入要移除的编号: {Style.RESET_ALL}").strip())
                    if 1 <= idx <= len(interests):
                        removed = interest_mgr.remove_interest(interests[idx-1])
                    else:
                        print(f"{Fore.RED}[ERROR] 无效编号！{Style.RESET_ALL}")
                except (ValueError, TypeError):
                    print(f"{Fore.RED}[ERROR] 请输入有效数字！{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 兴趣列表为空！{Style.RESET_ALL}")
        elif choice == "3":
            confirm = input(f"{Fore.RED}确认清空所有兴趣？(y/N): {Style.RESET_ALL}").strip().lower()
            if confirm == 'y':
                for interest in interests[:]:
                    interest_mgr.remove_interest(interest)
                print(f"{Fore.GREEN}[OK] 已清空所有兴趣！{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项！{Style.RESET_ALL}")

def show_comment_menu():
    """显示评论互动设置菜单"""
    global PROB_COMMENT_OTHERS, COMMENT_CHECK_INTERVAL, MAX_REPLIES_PER_CHECK, COMMENT_MODE, COMMENT_CHECK_ENABLED
    global RANDOM_ENABLED
    
    while True:
        mode_icon = "[NET]" if COMMENT_MODE == "real" else "🎭"
        mode_text = "真实评论（实际发送到B站）" if COMMENT_MODE == "real" else "模拟评论（仅日志记录，不真发）"
        check_status = "[OK] 启用" if COMMENT_CHECK_ENABLED else "⏸️ 关闭"
        random_status = "🎲 已开启 (随机检定)" if RANDOM_ENABLED else "🔒 已关闭 (纯分数)"
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                  评论互动设置菜单                        ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 评论模式: {mode_icon} {mode_text}
    • 评论检查总开关: {check_status}
    • 评论他人评论概率: {PROB_COMMENT_OTHERS*100}%
    • 检查新评论间隔: {COMMENT_CHECK_INTERVAL}秒 ({COMMENT_CHECK_INTERVAL/60:.1f}分钟)
    • 每次最大回复数: {MAX_REPLIES_PER_CHECK}条
    • 随机数限制: {random_status}
    • 回复审查: {'启用' if REPLY_SAFETY_ENABLED else '关闭'} | 敏感词 {len(REPLY_SAFETY_BLOCKED_KEYWORDS)} 个

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}0.{Style.RESET_ALL} 🔁 切换评论模式（真实/模拟）
    {Fore.CYAN}7.{Style.RESET_ALL} 🔌 评论检查总开关（当前: {check_status}）
    {Fore.GREEN}1.{Style.RESET_ALL} [STATS] 查看评论互动日志
    {Fore.YELLOW}2.{Style.RESET_ALL} ⚙️  修改评论概率
    {Fore.YELLOW}3.{Style.RESET_ALL} ⏰ 修改检查间隔
    {Fore.YELLOW}4.{Style.RESET_ALL} 🔢 修改最大回复数
    {Fore.YELLOW}5.{Style.RESET_ALL} [DEF]  回复审查设置
    {Fore.MAGENTA}8.{Style.RESET_ALL} 🎲 切换随机数限制（当前: {random_status}）
    {Fore.RED}9.{Style.RESET_ALL} ↩️  返回主菜单
        """)
        
        choice = input(f"{Fore.CYAN}请输入选项 (0-5,7-9=返回): {Style.RESET_ALL}").strip()
        
        if choice == "9":
            break
        elif choice == "0":
            # 切换评论模式
            if COMMENT_MODE == "real":
                COMMENT_MODE = "simulate"
                config["behavior"]["comment_mode"] = "simulate"
            else:
                COMMENT_MODE = "real"
                config["behavior"]["comment_mode"] = "real"
            save_config(config)
            log(f"评论模式已切换为: {COMMENT_MODE}", "INFO")
            print(f"{Fore.GREEN}[OK] 评论模式已切换为: {COMMENT_MODE}{Style.RESET_ALL}")
        elif choice == "7":
            # 评论检查总开关
            COMMENT_CHECK_ENABLED = not COMMENT_CHECK_ENABLED
            config["interaction"]["comment_check_enabled"] = COMMENT_CHECK_ENABLED
            save_config(config)
            status = "启用" if COMMENT_CHECK_ENABLED else "关闭"
            log(f"评论检查总开关已{status}", "INFO")
            print(f"{Fore.GREEN}[OK] 评论检查已{status}！重启后生效。{Style.RESET_ALL}")
        elif choice == "1":
            show_comment_log()
        elif choice == "2":
            try:
                new_val = float(input(f"{Fore.YELLOW}请输入新的评论概率 (0-1): {Style.RESET_ALL}").strip())
                if 0 <= new_val <= 1:
                    config["interaction"]["prob_comment_others"] = new_val
                    PROB_COMMENT_OTHERS = new_val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新！{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入！{Style.RESET_ALL}")
        elif choice == "3":
            try:
                new_val = int(input(f"{Fore.YELLOW}请输入新的检查间隔 (秒, 建议60-600): {Style.RESET_ALL}").strip())
                if new_val > 0:
                    config["interaction"]["comment_check_interval"] = new_val
                    COMMENT_CHECK_INTERVAL = new_val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新！{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入！{Style.RESET_ALL}")
        elif choice == "4":
            try:
                new_val = int(input(f"{Fore.YELLOW}请输入每次最大回复数 (1-10): {Style.RESET_ALL}").strip())
                if 1 <= new_val <= 10:
                    config["interaction"]["max_replies_per_check"] = new_val
                    MAX_REPLIES_PER_CHECK = new_val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新！{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入！{Style.RESET_ALL}")
        elif choice == "5":
            show_reply_safety_menu()
        elif choice == "8":
            RANDOM_ENABLED = not RANDOM_ENABLED
            config["interaction"]["random_enabled"] = RANDOM_ENABLED
            save_config(config)
            new_status = "🎲 已开启 (随机检定)" if RANDOM_ENABLED else "🔒 已关闭 (纯分数)"
            print(f"{Fore.GREEN}[OK] 随机数限制已切换为: {new_status}{Style.RESET_ALL}")
            if RANDOM_ENABLED:
                print(f"{Fore.CYAN}   AI意图需通过随机概率检定才执行 → 更自然、更像真人{Style.RESET_ALL}")
            else:
                print(f"{Fore.CYAN}   只看AI意图和分数阈值，跳过随机检定 → 更激进{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项！{Style.RESET_ALL}")

def show_comment_log():
    """显示评论互动日志"""
    if not os.path.exists(COMMENT_LOG_FILE):
        print(f"{Fore.YELLOW}[WARN] 暂无评论互动日志{Style.RESET_ALL}")
        return
    
    try:
        with open(COMMENT_LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        history = data.get("history", [])
        
        if not history:
            print(f"{Fore.YELLOW}[WARN] 暂无互动记录{Style.RESET_ALL}")
            return
        
        print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
        print(f"{Fore.CYAN}              评论互动日志 (最近20条){Style.RESET_ALL}")
        print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
        
        for entry in history[-20:]:
            timestamp = entry.get("timestamp", "")[:19]
            action = entry.get("action", "")
            content = entry.get("content", "")[:50]
            target = entry.get("target_user", "")
            
            if action == "reply":
                print(f"  {timestamp} [MSG] 回复 @{target}: {content}...")
            elif action == "like":
                print(f"  {timestamp} ❤️ 点赞 @{target}")
            elif action == "blocked_reply":
                hits = ", ".join(entry.get("hits", []))
                print(f"  {timestamp} [DEF] 拦截 @{target}: {entry.get('reason', '')} ({hits})")
        
        print(f"\n{Fore.YELLOW}[STATS] 总计互动: {len(history)} 次{Style.RESET_ALL}")
        print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
        
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 读取日志失败: {e}{Style.RESET_ALL}")


def show_reply_safety_menu():
    """评论/私信回复审查设置"""
    global REPLY_SAFETY_ENABLED, REPLY_SAFETY_BLOCK_ON_INCOMING, REPLY_SAFETY_BLOCK_ON_OUTGOING, REPLY_SAFETY_BLOCKED_KEYWORDS

    safety_cfg = config.setdefault("reply_safety", {})
    safety_cfg.setdefault("blocked_keywords", list(REPLY_SAFETY_BLOCKED_KEYWORDS))

    while True:
        REPLY_SAFETY_BLOCKED_KEYWORDS = safety_cfg.get("blocked_keywords", [])
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                    回复审查设置                          ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 总开关: {'启用' if REPLY_SAFETY_ENABLED else '关闭'}
    • 检查收到的评论/私信: {'启用' if REPLY_SAFETY_BLOCK_ON_INCOMING else '关闭'}
    • 检查拟发送回复: {'启用' if REPLY_SAFETY_BLOCK_ON_OUTGOING else '关闭'}
    • 敏感词: {', '.join(REPLY_SAFETY_BLOCKED_KEYWORDS) if REPLY_SAFETY_BLOCKED_KEYWORDS else '(空)'}

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} 🔁 开关总审查
    {Fore.GREEN}2.{Style.RESET_ALL} 📥 开关检查收到内容
    {Fore.GREEN}3.{Style.RESET_ALL} 📤 开关检查拟发送回复
    {Fore.YELLOW}4.{Style.RESET_ALL} ➕ 添加敏感词
    {Fore.YELLOW}5.{Style.RESET_ALL} ➖ 删除敏感词
    {Fore.BLUE}6.{Style.RESET_ALL} 🧪 测试一句话
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回上级
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-6): {Style.RESET_ALL}").strip()
        if choice == "0":
            break
        elif choice == "1":
            REPLY_SAFETY_ENABLED = not REPLY_SAFETY_ENABLED
            safety_cfg["enabled"] = REPLY_SAFETY_ENABLED
            save_config(config)
        elif choice == "2":
            REPLY_SAFETY_BLOCK_ON_INCOMING = not REPLY_SAFETY_BLOCK_ON_INCOMING
            safety_cfg["block_on_incoming"] = REPLY_SAFETY_BLOCK_ON_INCOMING
            save_config(config)
        elif choice == "3":
            REPLY_SAFETY_BLOCK_ON_OUTGOING = not REPLY_SAFETY_BLOCK_ON_OUTGOING
            safety_cfg["block_on_outgoing"] = REPLY_SAFETY_BLOCK_ON_OUTGOING
            save_config(config)
        elif choice == "4":
            word = input(f"{Fore.YELLOW}输入要添加的敏感词: {Style.RESET_ALL}").strip()
            if word and word not in safety_cfg["blocked_keywords"]:
                safety_cfg["blocked_keywords"].append(word)
                REPLY_SAFETY_BLOCKED_KEYWORDS = safety_cfg["blocked_keywords"]
                save_config(config)
                print(f"{Fore.GREEN}[OK] 已添加: {word}{Style.RESET_ALL}")
        elif choice == "5":
            words = safety_cfg.get("blocked_keywords", [])
            for i, word in enumerate(words, 1):
                print(f"  {i}. {word}")
            try:
                idx = int(input(f"{Fore.YELLOW}输入要删除的编号: {Style.RESET_ALL}").strip())
                if 1 <= idx <= len(words):
                    removed = words.pop(idx - 1)
                    REPLY_SAFETY_BLOCKED_KEYWORDS = words
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已删除: {removed}{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入{Style.RESET_ALL}")
        elif choice == "6":
            text = input(f"{Fore.YELLOW}输入测试文本: {Style.RESET_ALL}").strip()
            hits = ReplySafetyGuard().find_hits(text)
            if hits:
                print(f"{Fore.YELLOW}[WARN] 会拦截，命中: {', '.join(hits)}{Style.RESET_ALL}")
            else:
                print(f"{Fore.GREEN}[OK] 会通过{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")


def show_private_message_menu():
    """显示私信设置菜单"""
    global PRIVATE_MESSAGE_ENABLED, PRIVATE_MESSAGE_AUTO_REPLY, PRIVATE_MESSAGE_CHECK_INTERVAL, PRIVATE_MESSAGE_MAX_REPLIES

    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                    私信设置菜单                          ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 私信检查: {'启用' if PRIVATE_MESSAGE_ENABLED else '关闭'}
    • 自动发送回复: {'[OK] 启用（AI拟好就发）' if PRIVATE_MESSAGE_AUTO_REPLY else '✗ 关闭（拟好但不发）'}
    • 检查间隔: {PRIVATE_MESSAGE_CHECK_INTERVAL}秒
    • 每次最大处理: {PRIVATE_MESSAGE_MAX_REPLIES}条

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} 🔁 开关私信检查
    {Fore.YELLOW}2.{Style.RESET_ALL} [START] 开关自动发送回复
    {Fore.YELLOW}3.{Style.RESET_ALL} ⏰ 修改检查间隔
    {Fore.YELLOW}4.{Style.RESET_ALL} 🔢 修改最大处理数
    {Fore.BLUE}5.{Style.RESET_ALL} 📋 查看私信日志
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-5): {Style.RESET_ALL}").strip()
        pm_config = config.setdefault("private_message", {})

        if choice == "0":
            break
        elif choice == "1":
            PRIVATE_MESSAGE_ENABLED = not PRIVATE_MESSAGE_ENABLED
            pm_config["enabled"] = PRIVATE_MESSAGE_ENABLED
            save_config(config)
            print(f"{Fore.GREEN}[OK] 私信检查已{'启用' if PRIVATE_MESSAGE_ENABLED else '关闭'}{Style.RESET_ALL}")
        elif choice == "2":
            PRIVATE_MESSAGE_AUTO_REPLY = not PRIVATE_MESSAGE_AUTO_REPLY
            pm_config["auto_reply"] = PRIVATE_MESSAGE_AUTO_REPLY
            save_config(config)
            print(f"{Fore.GREEN}[OK] 自动发送回复已{'启用' if PRIVATE_MESSAGE_AUTO_REPLY else '关闭'}{Style.RESET_ALL}")
        elif choice == "3":
            try:
                new_val = int(input(f"{Fore.YELLOW}请输入新的检查间隔 (秒, 建议60-600): {Style.RESET_ALL}").strip())
                if new_val > 0:
                    PRIVATE_MESSAGE_CHECK_INTERVAL = new_val
                    pm_config["check_interval"] = new_val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新！{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入！{Style.RESET_ALL}")
        elif choice == "4":
            try:
                new_val = int(input(f"{Fore.YELLOW}请输入每次最大处理数 (1-10): {Style.RESET_ALL}").strip())
                if 1 <= new_val <= 10:
                    PRIVATE_MESSAGE_MAX_REPLIES = new_val
                    pm_config["max_replies_per_check"] = new_val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新！{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入！{Style.RESET_ALL}")
        elif choice == "5":
            show_private_message_log()
        else:
            print(f"{Fore.RED}[ERROR] 无效选项！{Style.RESET_ALL}")


def show_private_message_log():
    if not os.path.exists(PRIVATE_MESSAGE_LOG_FILE):
        print(f"{Fore.YELLOW}[WARN] 暂无私信日志{Style.RESET_ALL}")
        return

    try:
        with open(PRIVATE_MESSAGE_LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        history = data.get("history", [])
        if not history:
            print(f"{Fore.YELLOW}[WARN] 暂无私信记录{Style.RESET_ALL}")
            return

        print(f"\n{Fore.CYAN}📋 最近私信记录:{Style.RESET_ALL}")
        for item in history[-10:]:
            if item.get("blocked"):
                sent = "已拦截"
            else:
                sent = "已发送" if item.get("sent") else "未发送"
            print(f"{Fore.GREEN}[{item.get('timestamp')}] @{item.get('talker_id')} ({sent}){Style.RESET_ALL}")
            print(f"  收到: {item.get('incoming', '')[:80]}")
            if item.get("blocked"):
                print(f"  原因: {item.get('reason', '')} | 命中: {', '.join(item.get('hits', []))}")
            print(f"  回复: {item.get('reply', '')[:80]}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 读取私信日志失败: {e}{Style.RESET_ALL}")


def _load_recent_journal_events(limit=20):
    if not os.path.exists(JOURNAL_FILE):
        return []
    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return []

    entries = []
    for block in content.split("---"):
        block = block.strip()
        if not block:
            continue
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        entries.append({"source": "bot_journal", "text": "\n".join(lines[-8:])})
    return entries[-limit:]


def _print_diary_entries(entries):
    if not entries:
        print(f"{Fore.YELLOW}[WARN] 暂无日记{Style.RESET_ALL}")
        return
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.CYAN}              日记列表{Style.RESET_ALL}")
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    for i, entry in enumerate(entries, 1):
        created = entry.get("created_at", "")[:19]
        title = entry.get("title", "未命名")
        mood = entry.get("mood", "")
        content = entry.get("content", "").replace("\n", " ")[:120]
        print(f"{i}. [{created}] {title} {f'({mood})' if mood else ''}")
        print(f"   {content}...")
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")


def _print_evolution_items(items):
    if not items:
        print(f"{Fore.YELLOW}[WARN] 暂无自我进化记录{Style.RESET_ALL}")
        return
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.CYAN}              自我进化记录{Style.RESET_ALL}")
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    for i, item in enumerate(items, 1):
        created = item.get("created_at", "")[:19]
        parsed = item.get("parsed", {})
        reflection = str(parsed.get("reflection") or item.get("raw", ""))[:140].replace("\n", " ")
        print(f"{i}. [{created}] {'已应用' if item.get('applied') else '未应用'}")
        print(f"   {reflection}...")
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")


async def run_manual_diary_generation(extra_note=""):
    diary_mgr = BotDiaryManager()
    persona_mgr = PersonaManager()
    mood_mgr = MoodManager()
    events = _load_recent_journal_events(limit=20)
    if not events:
        print(f"{Fore.YELLOW}[WARN] 暂无机器人互动日志，无法自动生成日记。可以先手动写一篇。{Style.RESET_ALL}")
        return
    entry = await diary_mgr.generate_from_events(
        events,
        persona_mgr.build_prompt_block(),
        mood_mgr.get_current(),
        extra_note=extra_note
    )
    print(f"{Fore.GREEN}[OK] 已生成日记: {entry['title']}{Style.RESET_ALL}")
    print(entry["content"][:500])


async def run_manual_self_evolution(apply_result=True):
    diary_mgr = BotDiaryManager()
    evolution_mgr = SelfEvolutionManager()
    persona_mgr = PersonaManager()
    mood_mgr = MoodManager()
    events = _load_recent_journal_events(limit=20)
    diary_entries = diary_mgr.list_entries(limit=5)
    if not events and not diary_entries:
        print(f"{Fore.YELLOW}[WARN] 暂无日记或互动日志，无法进化。{Style.RESET_ALL}")
        return

    item = await evolution_mgr.reflect(
        events or [{"source": "diary", "text": e.get("content", "")} for e in diary_entries],
        persona_mgr.build_prompt_block(),
        mood_mgr.get_current(),
        diary_entries=diary_entries
    )
    parsed = item.get("parsed", {})
    print(f"{Fore.GREEN}[OK] 自我复盘完成{Style.RESET_ALL}")
    print(f"复盘: {parsed.get('reflection', '')}")
    print(f"风格调整: {parsed.get('style_delta', '') or '无'}")
    print(f"关系边界调整: {parsed.get('relationship_delta', '') or '无'}")
    print(f"新增约束: {parsed.get('new_rule', '') or '无'}")

    if apply_result and EVOLUTION_AUTO_APPLY:
        persona_mgr.evolve_active_persona(
            style_delta=str(parsed.get("style_delta") or "").strip(),
            relationship_delta=str(parsed.get("relationship_delta") or "").strip(),
            new_rule=str(parsed.get("new_rule") or "").strip()
        )
        mood_delta = parsed.get("mood_delta", 0)
        try:
            mood_delta = int(float(mood_delta))
        except Exception:
            mood_delta = 0
        if mood_delta:
            mood_mgr.shift("自我进化复盘", max(-2, min(2, mood_delta)))
        evolution_mgr.mark_applied(item.get("id"))
        print(f"{Fore.GREEN}[OK] 已应用到当前人格/心情{Style.RESET_ALL}")


def show_diary_evolution_menu():
    """显示日记和自我进化菜单"""
    global DIARY_ENABLED, DIARY_AUTO_ENABLED, DIARY_AUTO_INTERVAL_MINUTES, DIARY_MIN_EVENTS_FOR_AUTO
    global EVOLUTION_ENABLED, EVOLUTION_AUTO_ENABLED, EVOLUTION_REFLECT_INTERVAL_EVENTS
    global EVOLUTION_MIN_EVENTS_FOR_REFLECT, EVOLUTION_AUTO_APPLY

    diary_mgr = BotDiaryManager()
    evolution_mgr = SelfEvolutionManager()

    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                  日记 / 自我进化菜单                    ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 日记: {'启用' if DIARY_ENABLED else '关闭'} | 自动日记: {'启用' if DIARY_AUTO_ENABLED else '关闭'} | 间隔: {DIARY_AUTO_INTERVAL_MINUTES}分钟
    • 自我进化: {'启用' if EVOLUTION_ENABLED else '关闭'} | 自动进化: {'启用' if EVOLUTION_AUTO_ENABLED else '关闭'} | 自动应用: {'启用' if EVOLUTION_AUTO_APPLY else '关闭'}
    • 进化触发: 每 {EVOLUTION_REFLECT_INTERVAL_EVENTS} 个事件检查一次，最少 {EVOLUTION_MIN_EVENTS_FOR_REFLECT} 个事件

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} ✍️  手动写日记
    {Fore.GREEN}2.{Style.RESET_ALL} 📖 查看最近日记
    {Fore.GREEN}3.{Style.RESET_ALL} 🔎 搜索日记
    {Fore.YELLOW}4.{Style.RESET_ALL} 🤖 立即生成自动日记
    {Fore.YELLOW}5.{Style.RESET_ALL} 🧬 立即自我进化
    {Fore.BLUE}6.{Style.RESET_ALL} 📋 查看进化记录
    {Fore.BLUE}7.{Style.RESET_ALL} ⚙️  修改自动设置
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-9): {Style.RESET_ALL}").strip()

        if choice == "0":
            break
        elif choice == "1":
            title = input(f"{Fore.YELLOW}标题: {Style.RESET_ALL}").strip() or "手动日记"
            print(f"{Fore.YELLOW}内容，输入空行结束:{Style.RESET_ALL}")
            lines = []
            while True:
                line = input()
                if not line:
                    break
                lines.append(line)
            try:
                entry = diary_mgr.add_entry(title, "\n".join(lines), mood=MoodManager().get_current(), tags=["手动"], source="manual")
                print(f"{Fore.GREEN}[OK] 已保存日记: {entry['id']}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 保存失败: {e}{Style.RESET_ALL}")
        elif choice == "2":
            _print_diary_entries(diary_mgr.list_entries(limit=20))
        elif choice == "3":
            query = input(f"{Fore.YELLOW}搜索关键词: {Style.RESET_ALL}").strip()
            _print_diary_entries(diary_mgr.search(query, limit=20))
        elif choice == "4":
            note = input(f"{Fore.YELLOW}额外备注 (可空): {Style.RESET_ALL}").strip()
            try:
                asyncio.run(run_manual_diary_generation(note))
                diary_mgr = BotDiaryManager()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 自动日记失败: {e}{Style.RESET_ALL}")
        elif choice == "5":
            try:
                asyncio.run(run_manual_self_evolution(apply_result=True))
                evolution_mgr = SelfEvolutionManager()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 自我进化失败: {e}{Style.RESET_ALL}")
        elif choice == "6":
            _print_evolution_items(evolution_mgr.list_items(limit=20))
        elif choice == "7":
            diary_cfg = config.setdefault("diary", {})
            evolution_cfg = config.setdefault("self_evolution", {})
            DIARY_ENABLED = not DIARY_ENABLED if input(f"{Fore.YELLOW}切换日记总开关？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else DIARY_ENABLED
            diary_cfg["enabled"] = DIARY_ENABLED
            DIARY_AUTO_ENABLED = not DIARY_AUTO_ENABLED if input(f"{Fore.YELLOW}切换自动日记？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else DIARY_AUTO_ENABLED
            diary_cfg["auto_enabled"] = DIARY_AUTO_ENABLED
            raw = input(f"{Fore.YELLOW}自动日记间隔分钟 (回车保持): {Style.RESET_ALL}").strip()
            if raw:
                try:
                    DIARY_AUTO_INTERVAL_MINUTES = max(5, int(raw))
                    diary_cfg["auto_interval_minutes"] = DIARY_AUTO_INTERVAL_MINUTES
                except (ValueError, TypeError):
                    print(f"{Fore.YELLOW}[WARN] 间隔无效，保持原样{Style.RESET_ALL}")

            EVOLUTION_ENABLED = not EVOLUTION_ENABLED if input(f"{Fore.YELLOW}切换自我进化总开关？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else EVOLUTION_ENABLED
            evolution_cfg["enabled"] = EVOLUTION_ENABLED
            EVOLUTION_AUTO_ENABLED = not EVOLUTION_AUTO_ENABLED if input(f"{Fore.YELLOW}切换自动进化？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else EVOLUTION_AUTO_ENABLED
            evolution_cfg["auto_enabled"] = EVOLUTION_AUTO_ENABLED
            EVOLUTION_AUTO_APPLY = not EVOLUTION_AUTO_APPLY if input(f"{Fore.YELLOW}切换自动应用进化结果？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else EVOLUTION_AUTO_APPLY
            evolution_cfg["auto_apply"] = EVOLUTION_AUTO_APPLY
            raw = input(f"{Fore.YELLOW}进化检查事件间隔 (回车保持): {Style.RESET_ALL}").strip()
            if raw:
                try:
                    EVOLUTION_REFLECT_INTERVAL_EVENTS = max(1, int(raw))
                    evolution_cfg["reflect_interval_events"] = EVOLUTION_REFLECT_INTERVAL_EVENTS
                except (ValueError, TypeError):
                    print(f"{Fore.YELLOW}[WARN] 事件间隔无效，保持原样{Style.RESET_ALL}")
            save_config(config)
            print(f"{Fore.GREEN}[OK] 设置已保存{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项！{Style.RESET_ALL}")


async def run_manual_agent_goal(goal):
    brain = AgentBrain()
    login_success = await brain.initialize_login()
    if not login_success:
        print(f"{Fore.RED}[ERROR] 登录失败，无法运行需要B站上下文的Agent技能{Style.RESET_ALL}")
        return
    runner = AgentSkillRunner(brain=brain)
    run = await runner.run_goal(goal)
    print(f"{Fore.GREEN}[OK] Agent执行完成{Style.RESET_ALL}")
    print(f"目标: {run.get('goal')}")
    for idx, item in enumerate(run.get("results", []), 1):
        step = item.get("step", {})
        result = item.get("result", {})
        print(f"{idx}. {step.get('skill')} | ok={result.get('ok')}")
        if result.get("videos"):
            for video_item in result["videos"][:5]:
                print(f"   - {video_item.get('title')} ({video_item.get('bvid')})")
        if result.get("watched"):
            for watched in result["watched"]:
                print(f"   - 已看: {watched.get('title')} ({watched.get('bvid')})")
        if result.get("error"):
            print(f"   错误: {result.get('error')}")


def show_agent_skill_menu():
    """Agent技能菜单"""
    global AGENT_ENABLED, AGENT_AUTO_ENABLED, AGENT_DIVE_ENABLED, AGENT_MAX_STEPS_PER_PLAN
    global AGENT_MAX_SEARCH_RESULTS, AGENT_MAX_VIDEOS_PER_PLAN, AGENT_DIVE_MAX_VIDEOS, AGENT_AUTO_MIN_SCORE, AGENT_COOLDOWN_MINUTES

    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                      Agent技能菜单                       ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 总开关: {'启用' if AGENT_ENABLED else '关闭'}
    • 自动触发: {'启用' if AGENT_AUTO_ENABLED else '关闭'}
    • 🤖 深度搜索(集成刷视频): {'启用' if AGENT_DIVE_ENABLED else '关闭'}
    • 每次最多步骤: {AGENT_MAX_STEPS_PER_PLAN}
    • 搜索结果上限: {AGENT_MAX_SEARCH_RESULTS}
    • 每次最多看视频: {AGENT_MAX_VIDEOS_PER_PLAN}
    • 深度搜索最多看视频: {AGENT_DIVE_MAX_VIDEOS}
    • 自动触发最低评分: {AGENT_AUTO_MIN_SCORE}
    • 自动触发冷却: {AGENT_COOLDOWN_MINUTES}分钟

    {Fore.CYAN}可用技能:{Style.RESET_ALL}
    - search_bilibili_videos: 搜索B站视频
    - watch_bilibili_videos: 理解/观看搜索到的视频
    - write_memory: 写入本轮本地记忆
    - write_diary: 写入Agent日记

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} [START] 运行一个Agent目标
    {Fore.BLUE}2.{Style.RESET_ALL} 📋 查看最近Agent记录
    {Fore.YELLOW}3.{Style.RESET_ALL} ⚙️  修改限制/开关
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-3): {Style.RESET_ALL}").strip()
        if choice == "0":
            break
        elif choice == "1":
            goal = input(f'{Fore.YELLOW}输入Agent目标，例如「了解gpt-5.2这个新模型，看5个相关视频」: {Style.RESET_ALL}').strip()
            if goal:
                try:
                    asyncio.run(run_manual_agent_goal(goal))
                except Exception as e:
                    print(f"{Fore.RED}[ERROR] Agent运行失败: {e}{Style.RESET_ALL}")
        elif choice == "2":
            runner = AgentSkillRunner()
            runs = runner.list_runs(limit=10)
            if not runs:
                print(f"{Fore.YELLOW}[WARN] 暂无Agent记录{Style.RESET_ALL}")
            for run in runs:
                print(f"[{run.get('created_at', '')[:19]}] {run.get('goal')} | 步骤: {len(run.get('results', []))}")
        elif choice == "3":
            agent_cfg = config.setdefault("agent", {})
            AGENT_ENABLED = not AGENT_ENABLED if input(f"{Fore.YELLOW}切换Agent总开关？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else AGENT_ENABLED
            agent_cfg["enabled"] = AGENT_ENABLED
            AGENT_AUTO_ENABLED = not AGENT_AUTO_ENABLED if input(f"{Fore.YELLOW}切换自动触发？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else AGENT_AUTO_ENABLED
            agent_cfg["auto_enabled"] = AGENT_AUTO_ENABLED
            AGENT_DIVE_ENABLED = not AGENT_DIVE_ENABLED if input(f"{Fore.YELLOW}切换深度搜索(集成刷视频)？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else AGENT_DIVE_ENABLED
            agent_cfg["dive_enabled"] = AGENT_DIVE_ENABLED

            fields = [
                ("max_steps_per_plan", "每次最多步骤", "AGENT_MAX_STEPS_PER_PLAN", 1, 20),
                ("max_search_results", "搜索结果上限", "AGENT_MAX_SEARCH_RESULTS", 1, 30),
                ("max_videos_per_plan", "每次最多看视频", "AGENT_MAX_VIDEOS_PER_PLAN", 1, 10),
                ("dive_max_videos", "深度搜索最多看视频", "AGENT_DIVE_MAX_VIDEOS", 1, 50),
                ("cooldown_minutes", "自动触发冷却分钟", "AGENT_COOLDOWN_MINUTES", 1, 1440),
            ]
            for key, label, global_name, min_v, max_v in fields:
                raw = input(f"{Fore.YELLOW}{label} (回车保持): {Style.RESET_ALL}").strip()
                if raw:
                    try:
                        value = max(min_v, min(max_v, int(raw)))
                        agent_cfg[key] = value
                        globals()[global_name] = value
                    except (ValueError, TypeError):
                        print(f"{Fore.YELLOW}[WARN] {label}无效，保持原样{Style.RESET_ALL}")
            raw = input(f"{Fore.YELLOW}自动触发最低评分 (0-10, 回车保持): {Style.RESET_ALL}").strip()
            if raw:
                try:
                    AGENT_AUTO_MIN_SCORE = max(0.0, min(10.0, float(raw)))
                    agent_cfg["auto_min_score"] = AGENT_AUTO_MIN_SCORE
                except (ValueError, TypeError):
                    print(f"{Fore.YELLOW}[WARN] 分数无效，保持原样{Style.RESET_ALL}")
            save_config(config)
            print(f"{Fore.GREEN}[OK] Agent设置已保存{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")

async def _manual_send_danmaku(bvid: str, text: str) -> dict:
    """手动发送弹幕（供菜单直接调用）。"""
    try:
        from bilibili_api import Credential, Danmaku
        from bilibili_api.video import Video
    except ImportError as e:
        return {"code": -1, "msg": f"bilibili_api 导入失败: {e}"}
    if not os.path.exists(COOKIE_FILE):
        return {"code": -1, "msg": "未登录，请先扫码登录"}
    with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
        cookies = json.load(f)
    cred = Credential(
        sessdata=cookies.get('SESSDATA', ''),
        bili_jct=cookies.get('bili_jct', ''),
        buvid3=cookies.get('buvid3', ''),
        dedeuserid=cookies.get('DedeUserID', '')
    )
    try:
        v = Video(bvid=bvid, credential=cred)
        info = await v.get_info()
        cid = info.get('cid', 0)
        if not cid:
            return {"code": -1, "msg": f"未找到视频cid (bvid={bvid})"}
        dm = Danmaku(text=text, dm_time=0.0)
        await v.send_danmaku(danmaku=dm, page_index=0)
        return {"code": 0, "msg": f"弹幕发送成功: {text[:30]}"}
    except Exception as e:
        return {"code": -1, "msg": f"弹幕发送失败: {e}"}

def show_up_danmaku_menu():
    """显示UP主关注/弹幕互动设置菜单"""
    global config, UP_FOLLOW_ENABLED, UP_FOLLOW_AUTO_PROB, UP_FOLLOW_MAX_DAILY
    global UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS, UP_FOLLOW_BROWSE_PROB, UP_FOLLOW_MAX_BROWSE
    global UP_FOLLOW_COOLDOWN_MINUTES, UP_FOLLOW_FAVORITE_PROB
    global UP_FOLLOW_MIN_SCORE, UP_FOLLOW_MIN_IMPRESSIONS, UP_FOLLOW_EXCEPTIONAL_SCORE
    global DANMAKU_ENABLED, DANMAKU_READ_PROB, DANMAKU_LIKE_PROB, DANMAKU_MAX_DAILY_LIKES
    global DANMAKU_SEND_PROB, DANMAKU_MAX_DAILY_SEND
    
    while True:
        up_enabled_text = "[*] 已开启" if UP_FOLLOW_ENABLED else "💤 已关闭"
        danmaku_enabled_text = "[MSG] 已开启" if DANMAKU_ENABLED else "💤 已关闭"
        
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║            [*] UP主关注 + [MSG] 弹幕互动设置                 ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}▶ UP主关注设置:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} {'关闭' if UP_FOLLOW_ENABLED else '开启'}UP主关注功能 → 当前: {Fore.YELLOW + up_enabled_text + Style.RESET_ALL}
    {Fore.GREEN}2.{Style.RESET_ALL} 自动关注概率: {Fore.YELLOW}{UP_FOLLOW_AUTO_PROB}{Style.RESET_ALL}
    {Fore.GREEN}3.{Style.RESET_ALL} 每日关注上限: {Fore.YELLOW}{UP_FOLLOW_MAX_DAILY}{Style.RESET_ALL}
    {Fore.GREEN}4.{Style.RESET_ALL} 关注冷却(分钟): {Fore.YELLOW}{UP_FOLLOW_COOLDOWN_MINUTES}{Style.RESET_ALL}
    {Fore.GREEN}5.{Style.RESET_ALL} 浏览主页概率: {Fore.YELLOW}{UP_FOLLOW_BROWSE_PROB}{Style.RESET_ALL}
    {Fore.GREEN}6.{Style.RESET_ALL} 每次浏览视频数: {Fore.YELLOW}{UP_FOLLOW_MAX_BROWSE}{Style.RESET_ALL}
    {Fore.GREEN}7.{Style.RESET_ALL} 取关不活跃天数(0=关闭): {Fore.YELLOW}{UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS}{Style.RESET_ALL}
    {Fore.GREEN}8.{Style.RESET_ALL} 最低评分门槛(关注底线): {Fore.YELLOW}{UP_FOLLOW_MIN_SCORE}{Style.RESET_ALL}
    {Fore.GREEN}9.{Style.RESET_ALL} 最少印象次数(多看再关): {Fore.YELLOW}{UP_FOLLOW_MIN_IMPRESSIONS}{Style.RESET_ALL}
    {Fore.GREEN}10.{Style.RESET_ALL} 特别优秀分数(首看即关): {Fore.YELLOW}{UP_FOLLOW_EXCEPTIONAL_SCORE}{Style.RESET_ALL}

    {Fore.CYAN}▶ 弹幕互动设置:{Style.RESET_ALL}
    {Fore.BLUE}11.{Style.RESET_ALL} {'关闭' if DANMAKU_ENABLED else '开启'}弹幕互动功能 → 当前: {Fore.YELLOW + danmaku_enabled_text + Style.RESET_ALL}
    {Fore.BLUE}12.{Style.RESET_ALL} 读取弹幕概率: {Fore.YELLOW}{DANMAKU_READ_PROB}{Style.RESET_ALL}
    {Fore.BLUE}13.{Style.RESET_ALL} 点赞弹幕概率: {Fore.YELLOW}{DANMAKU_LIKE_PROB}{Style.RESET_ALL}
    {Fore.BLUE}14.{Style.RESET_ALL} 每日点赞上限: {Fore.YELLOW}{DANMAKU_MAX_DAILY_LIKES}{Style.RESET_ALL}
    {Fore.BLUE}15.{Style.RESET_ALL} 发送弹幕概率: {Fore.YELLOW}{DANMAKU_SEND_PROB}{Style.RESET_ALL}
    {Fore.BLUE}16.{Style.RESET_ALL} 每日发送上限: {Fore.YELLOW}{DANMAKU_MAX_DAILY_SEND}{Style.RESET_ALL}
    {Fore.MAGENTA}17.{Style.RESET_ALL} ✏️  手动发送弹幕 (输入BV号+内容)

    {Fore.CYAN}▶ 查看:{Style.RESET_ALL}
    {Fore.LIGHTBLUE_EX}V.{Style.RESET_ALL} [PEOPLE] 查看AI已关注的UP主列表

    {Fore.YELLOW}S.{Style.RESET_ALL} 💾 保存配置
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)
        
        choice = input(f"{Fore.CYAN}请输入选项 (0-17/V/S): {Style.RESET_ALL}").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            UP_FOLLOW_ENABLED = not UP_FOLLOW_ENABLED
            config["up_follow"]["enabled"] = UP_FOLLOW_ENABLED
            print(f"\n{Fore.GREEN}UP主关注功能已{'开启' if UP_FOLLOW_ENABLED else '关闭'}{Style.RESET_ALL}")
        elif choice == "2":
            try:
                val = float(input(f"自动关注概率 (0-1, 当前: {UP_FOLLOW_AUTO_PROB}): "))
                val = max(0.0, min(1.0, val))
                UP_FOLLOW_AUTO_PROB = val
                config["up_follow"]["auto_follow_prob"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "3":
            try:
                val = int(input(f"每日关注上限 (当前: {UP_FOLLOW_MAX_DAILY}): "))
                UP_FOLLOW_MAX_DAILY = val
                config["up_follow"]["max_daily_follows"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "4":
            try:
                val = int(input(f"关注冷却分钟 (当前: {UP_FOLLOW_COOLDOWN_MINUTES}): "))
                UP_FOLLOW_COOLDOWN_MINUTES = val
                config["up_follow"]["cooldown_minutes"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "5":
            try:
                val = float(input(f"浏览主页概率 (0-1, 当前: {UP_FOLLOW_BROWSE_PROB}): "))
                val = max(0.0, min(1.0, val))
                UP_FOLLOW_BROWSE_PROB = val
                config["up_follow"]["browse_up_videos_prob"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "6":
            try:
                val = int(input(f"每次浏览视频数 (当前: {UP_FOLLOW_MAX_BROWSE}): "))
                UP_FOLLOW_MAX_BROWSE = val
                config["up_follow"]["max_browse_videos"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "7":
            try:
                val = int(input(f"取关不活跃天数 (0=关闭, 当前: {UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS}): "))
                UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS = val
                config["up_follow"]["unfollow_inactive_days"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "8":
            try:
                val = float(input(f"最低评分门槛 (当前: {UP_FOLLOW_MIN_SCORE}): "))
                val = max(0.0, min(10.0, val))
                UP_FOLLOW_MIN_SCORE = val
                config["up_follow"]["min_score"] = val
                print(f"{Fore.GREEN}已更新: {val} (评分 ≥ {val} 才进入关注候选池){Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "9":
            try:
                val = int(input(f"最少印象次数 (当前: {UP_FOLLOW_MIN_IMPRESSIONS}): "))
                val = max(1, min(10, val))
                UP_FOLLOW_MIN_IMPRESSIONS = val
                config["up_follow"]["min_impressions"] = val
                print(f"{Fore.GREEN}已更新: {val} (至少看 {val} 次才可能关注){Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "10":
            try:
                val = float(input(f"特别优秀分数 (当前: {UP_FOLLOW_EXCEPTIONAL_SCORE}): "))
                val = max(5.0, min(10.0, val))
                UP_FOLLOW_EXCEPTIONAL_SCORE = val
                config["up_follow"]["exceptional_score"] = val
                print(f"{Fore.GREEN}已更新: {val} (首看评分 ≥ {val} 即可直接关注){Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "11":
            DANMAKU_ENABLED = not DANMAKU_ENABLED
            config["danmaku"]["enabled"] = DANMAKU_ENABLED
            print(f"\n{Fore.GREEN}弹幕互动功能已{'开启' if DANMAKU_ENABLED else '关闭'}{Style.RESET_ALL}")
        elif choice == "12":
            try:
                val = float(input(f"读取弹幕概率 (0-1, 当前: {DANMAKU_READ_PROB}): "))
                val = max(0.0, min(1.0, val))
                DANMAKU_READ_PROB = val
                config["danmaku"]["read_prob"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "13":
            try:
                val = float(input(f"点赞弹幕概率 (0-1, 当前: {DANMAKU_LIKE_PROB}): "))
                val = max(0.0, min(1.0, val))
                DANMAKU_LIKE_PROB = val
                config["danmaku"]["like_prob"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "14":
            try:
                val = int(input(f"每日点赞上限 (当前: {DANMAKU_MAX_DAILY_LIKES}): "))
                DANMAKU_MAX_DAILY_LIKES = val
                config["danmaku"]["max_daily_danmaku_likes"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "15":
            try:
                val = float(input(f"发送弹幕概率 (0-1, 当前: {DANMAKU_SEND_PROB}): "))
                val = max(0.0, min(1.0, val))
                DANMAKU_SEND_PROB = val
                config["danmaku"]["send_prob"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "16":
            try:
                val = int(input(f"每日发送上限 (当前: {DANMAKU_MAX_DAILY_SEND}): "))
                DANMAKU_MAX_DAILY_SEND = val
                config["danmaku"]["max_daily_send"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "17":
            # 手动发送弹幕
            bvid = input(f"{Fore.CYAN}请输入BV号: {Style.RESET_ALL}").strip()
            if not bvid:
                print(f"{Fore.RED}BV号不能为空{Style.RESET_ALL}")
            else:
                text = input(f"{Fore.CYAN}请输入弹幕内容 (建议20字内): {Style.RESET_ALL}").strip()
                if not text:
                    print(f"{Fore.RED}弹幕内容不能为空{Style.RESET_ALL}")
                else:
                    try:
                        result = asyncio.run(_manual_send_danmaku(bvid, text))
                        if result.get("code") == 0:
                            print(f"{Fore.GREEN}[OK] {result.get('msg')}{Style.RESET_ALL}")
                        else:
                            print(f"{Fore.RED}[ERROR] {result.get('msg')}{Style.RESET_ALL}")
                    except Exception as e:
                        print(f"{Fore.RED}[ERROR] 发送失败: {e}{Style.RESET_ALL}")
        elif choice.upper() == "V":
            _show_followed_ups()
        elif choice.upper() == "S":
            save_config(config)
            print(f"{Fore.GREEN}[OK] 配置已保存！{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")

def _show_followed_ups():
    """从 bot_memory.json 读取并显示 AI 已关注的UP主列表。"""
    mem_file = os.path.join(BASE_DIR, "bot_memory.json")
    if not os.path.exists(mem_file):
        print(f"{Fore.YELLOW}[WARN]  暂无关注记录（bot_memory.json 不存在）{Style.RESET_ALL}")
        return
    try:
        with open(mem_file, 'r', encoding='utf-8') as f:
            mem = json.load(f)
    except (OSError, json.JSONDecodeError):
        print(f"{Fore.RED}[ERROR] 读取关注记录失败{Style.RESET_ALL}")
        return

    ups = mem.get("known_ups", {})
    # 筛选出已关注的UP主
    followed = {name: info for name, info in ups.items() if isinstance(info, dict) and info.get("followed")}
    favorite = {name: info for name, info in ups.items() if isinstance(info, dict) and info.get("favorited")}

    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════╗
║              [PEOPLE] AI 关注的UP主                              ║
╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}""")

    if not followed:
        print(f"{Fore.YELLOW}  AI 暂未关注任何UP主{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}  已关注 {len(followed)} 位UP主:{Style.RESET_ALL}")
        # 按关注时间排序（最近关注的排前面）
        sorted_followed = sorted(followed.items(), key=lambda x: x[1].get("followed_at", ""), reverse=True)
        for i, (name, info) in enumerate(sorted_followed, 1):
            uid = info.get("uid", "?")
            followed_at = info.get("followed_at", "未知")[:16] if info.get("followed_at") else "未知"
            views = info.get("views", "?")
            avg = info.get("avg_score", "?")
            is_fav = "[STAR]" if info.get("favorited") else ""
            print(f"  {Fore.YELLOW}{i}.{Style.RESET_ALL} {Fore.CYAN}{name}{Style.RESET_ALL} {is_fav}"
                  f" | UID:{uid} | 观看{views}次 | 均分{avg} | 关注于 {followed_at}")

    if favorite:
        # 显示收藏但尚未关注的UP主
        only_fav = {name: info for name, info in favorite.items() if not info.get("followed")}
        if only_fav:
            print(f"\n{Fore.MAGENTA}  [STAR] 已收藏但未关注的UP主:{Style.RESET_ALL}")
            for name, info in sorted(only_fav.items(), key=lambda x: x[1].get("favorited_at", ""), reverse=True):
                uid = info.get("uid", "?")
                print(f"    {Fore.CYAN}{name}{Style.RESET_ALL} | UID:{uid} | 观看{info.get('views','?')}次 | 均分{info.get('avg_score','?')}")

    print()  # 空行
    input(f"{Fore.CYAN}按回车返回...{Style.RESET_ALL}")

def show_knowledge_base_menu():
    """显示知识库管理菜单"""
    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                   知识库管理菜单                         ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前状态:{Style.RESET_ALL}
    • 知识库路径: {KNOWLEDGE_BASE_DIR}
    • 分类数量: {count_knowledge_categories()}

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} [STATS] 查看知识库统计
    {Fore.GREEN}2.{Style.RESET_ALL} 📂 浏览知识库结构
    {Fore.YELLOW}3.{Style.RESET_ALL} 🔍 搜索知识内容
    {Fore.YELLOW}4.{Style.RESET_ALL} 🗑️  清理重复内容
    {Fore.BLUE}5.{Style.RESET_ALL} [UP] 查看学习记录
    {Fore.MAGENTA}6.{Style.RESET_ALL} 🤖 AI整理分类 (统一3层结构)
    {Fore.LIGHTBLUE_EX}7.{Style.RESET_ALL} 🧠 重建向量索引 (语义搜索)
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-7): {Style.RESET_ALL}").strip()

        if choice == "0":
            break
        elif choice == "1":
            show_kb_statistics()
        elif choice == "2":
            browse_kb_structure()
        elif choice == "3":
            search_knowledge_content()
        elif choice == "4":
            cleanup_duplicates()
        elif choice == "5":
            show_learning_log()
        elif choice == "6":
            print(f"\n{Fore.CYAN}🤖 正在调用AI重新规划知识库分类（统一3层）...{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}[WARN] 这将重新组织所有文件的分类路径，可能需要1-2分钟{Style.RESET_ALL}")
            confirm = input(f"{Fore.CYAN}确认执行? (y/n): {Style.RESET_ALL}").strip().lower()
            if confirm == "y":
                try:
                    classifier = KnowledgeBaseClassifier()
                    moved, total = asyncio.run(classifier.reclassify_all_three_levels())
                    print(f"{Fore.GREEN}[OK] AI整理完成: 迁移{moved}/{total}个文件{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}[ERROR] AI整理失败: {e}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}已取消{Style.RESET_ALL}")
        elif choice == "7":
            print(f"\n{Fore.CYAN}🧠 正在重建知识库向量索引...{Style.RESET_ALL}")
            try:
                if KBSearchEngine:
                    from xingye_bot.settings import load_settings as _ls
                    from xingye_bot.state import BotState as _bs
                    _s = _ls()
                    _engine = KBSearchEngine(ModelClient(_s, _bs()))
                    count = _engine.build_index()
                    stats = _engine.stats()
                    print(f"{Fore.GREEN}[OK] 索引构建完成: {stats['vectorized']}/{stats['total_entries']} 条已向量化{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}[WARN] 向量引擎不可用（请先配置 API Key）{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 构建向量索引失败: {e}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项，请重新选择！{Style.RESET_ALL}")

# ═══════════════════════════════════════════════════════════════
# 🎓 知识辅导菜单 (v2.0.3)
# ═══════════════════════════════════════════════════════════════
def _parse_multi_choice(choice_str: str, max_idx: int) -> list[int]:
    """解析多选输入，支持: 单个(5), 逗号(1,3,7), 范围(1-5), 混合(1-3,7,9-11), all"""
    choice_str = choice_str.strip().lower()
    if choice_str == 'all':
        return list(range(1, max_idx + 1))
    
    result = set()
    parts = [p.strip() for p in choice_str.split(',')]
    for part in parts:
        if not part:
            continue
        if '-' in part:
            range_parts = part.split('-', 1)
            try:
                start = int(range_parts[0])
                end = int(range_parts[1])
                if start < 1 or end > max_idx or start > end:
                    return []
                result.update(range(start, end + 1))
            except (ValueError, IndexError):
                return []
        else:
            try:
                val = int(part)
                if val < 1 or val > max_idx:
                    return []
                result.add(val)
            except ValueError:
                return []
    
    return sorted(result)

async def show_knowledge_tutor_menu():
    """知识辅导菜单：选择知识文件 → 讲解/问答/二次创作/生成HTML"""
    print(f"\n{Fore.CYAN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}|        🎓 知识辅导 - AI讲解/问答/二次创作                    |{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+============================================================+{Style.RESET_ALL}")

    # 扫描知识库
    md_files = scan_md_files()
    if not md_files:
        print(f"{Fore.YELLOW}[WARN] 知识库中没有找到学习归档文件！{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[INFO] 请先让机器人学习一些视频，或手动分析视频并归档{Style.RESET_ALL}")
        input(f"\n{Fore.CYAN}按回车返回...{Style.RESET_ALL}")
        return

    # 检查 AI 是否可用
    tutor = KnowledgeTutor()
    if not tutor.is_available():
        print(f"{Fore.RED}[ERROR] AI 接口不可用，请先配置 API Key！{Style.RESET_ALL}")
        input(f"\n{Fore.CYAN}按回车返回...{Style.RESET_ALL}")
        return

    # 按分类分组展示
    from collections import defaultdict
    by_category = defaultdict(list)
    for item in md_files:
        by_category[item['category_path']].append(item)

    print(f"\n{Fore.GREEN}共找到 {len(md_files)} 个知识文件，分布在 {len(by_category)} 个分类:{Style.RESET_ALL}\n")

    all_items = []
    idx = 1
    for cat in sorted(by_category.keys()):
        items = by_category[cat]
        print(f"{Fore.CYAN}[{cat}] ({len(items)}个){Style.RESET_ALL}")
        for item in items:
            up_str = f" @{item['up_name']}" if item['up_name'] else ""
            print(f"  {Fore.YELLOW}{idx:3d}.{Style.RESET_ALL} {item['title'][:45]}{up_str} ({item['size_kb']}KB)")
            all_items.append(item)
            idx += 1
        print()

    print(f"  {Fore.YELLOW}  0.{Style.RESET_ALL} 返回主菜单")

    print(f"\n{Fore.YELLOW}[提示] 支持多选: 逗号分隔(1,3,7) / 范围(1-5) / 全部(all){Style.RESET_ALL}")
    try:
        choice = input(f"\n{Fore.CYAN}请选择要辅导的知识文件 (1-{len(all_items)}): {Style.RESET_ALL}").strip()
        if not choice or choice == "0":
            print(f"{Fore.YELLOW}[INFO] 已取消{Style.RESET_ALL}")
            return

        # 解析多选输入
        selected_indices = _parse_multi_choice(choice, len(all_items))
        if not selected_indices:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")
            return

        selected_files = [(all_items[i-1]['file_path'], all_items[i-1]['title']) for i in selected_indices]

        print(f"\n{Fore.GREEN}已选择 {len(selected_files)} 个文件:{Style.RESET_ALL}")
        for fp, ttl in selected_files:
            sel_info = all_items[selected_indices[selected_files.index((fp, ttl))] - 1]
            print(f"  {Fore.YELLOW}•{Style.RESET_ALL} {ttl[:45]}  [{sel_info['category_path']}] ({sel_info['size_kb']}KB){' @'+sel_info['up_name'] if sel_info['up_name'] else ''}")

        # 进入辅导会话
        await _tutor_session(selected_files)

    except ValueError:
        print(f"{Fore.RED}[ERROR] 请输入数字{Style.RESET_ALL}")
        input(f"\n{Fore.CYAN}按回车返回...{Style.RESET_ALL}")
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 辅导异常: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
        input(f"\n{Fore.CYAN}按回车返回...{Style.RESET_ALL}")


async def _tutor_session(files: list[tuple[str, str]]):
    """知识辅导交互会话（CLI）- 支持单文件和多文件"""
    tutor = KnowledgeTutor()
    conversation_history: list[dict[str, str]] = []
    is_multi = len(files) > 1
    file_paths = [f[0] for f in files]
    titles = [f[1] for f in files]

    print(f"\n{Fore.CYAN}╔══════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
    if is_multi:
        print(f"{Fore.CYAN}║  📚 多文件辅导 ({len(files)}个文件)".ljust(59) + "║")
        for i, (fp, ttl) in enumerate(files):
            print(f"{Fore.CYAN}║    {i+1}. {ttl[:45]}".ljust(59) + "║")
    else:
        print(f"{Fore.CYAN}║  📖 {titles[0][:40]}".ljust(59) + "║")
    print(f"{Fore.CYAN}╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}")
    print(f"\n{Fore.GREEN}AI导师已就绪！你可以：{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}•{Style.RESET_ALL} 直接提问 → AI讲解知识点" + (f"（跨{len(files)}个文件综合分析）" if is_multi else ""))
    print(f"  {Fore.YELLOW}•{Style.RESET_ALL} 输入 {Fore.CYAN}:rewrite{Style.RESET_ALL} → AI二次创作（优化改写）")
    if is_multi:
        print(f"  {Fore.YELLOW}•{Style.RESET_ALL} 输入 {Fore.CYAN}:rewrite N{Style.RESET_ALL} → 改写第N个文件（如 :rewrite 2）")
    print(f"  {Fore.YELLOW}•{Style.RESET_ALL} 输入 {Fore.CYAN}:rewrite [要求]{Style.RESET_ALL} → 带自定义要求的改写")
    print(f"  {Fore.YELLOW}•{Style.RESET_ALL} 输入 {Fore.CYAN}:html{Style.RESET_ALL} → 生成HTML可视化网页")
    print(f"  {Fore.YELLOW}•{Style.RESET_ALL} 输入 {Fore.CYAN}:html dark/light/modern{Style.RESET_ALL} → 指定风格生成HTML")
    print(f"  {Fore.YELLOW}•{Style.RESET_ALL} 输入 {Fore.CYAN}:view{Style.RESET_ALL} → 查看原始文件内容")
    if is_multi:
        print(f"  {Fore.YELLOW}•{Style.RESET_ALL} 输入 {Fore.CYAN}:view N{Style.RESET_ALL} → 查看第N个文件（如 :view 2）")
    print(f"  {Fore.YELLOW}•{Style.RESET_ALL} 输入 {Fore.CYAN}:quit{Style.RESET_ALL} → 退出辅导")
    print()

    def _pick_file(cmd: str) -> tuple[str, str] | None:
        """从命令中解析文件编号（多文件模式下使用）"""
        if is_multi:
            parts = cmd.split(maxsplit=1)
            if len(parts) > 1:
                try:
                    n = int(parts[0])
                    if 1 <= n <= len(files):
                        return files[n - 1]
                except ValueError:
                    pass
            # 列出文件让用户选择
            print(f"\n{Fore.YELLOW}请选择要操作的文件:{Style.RESET_ALL}")
            for i, (fp, ttl) in enumerate(files):
                print(f"  {Fore.CYAN}{i+1}.{Style.RESET_ALL} {ttl[:50]}")
            try:
                n = int(input(f"{Fore.CYAN}输入编号 (1-{len(files)}): {Style.RESET_ALL}").strip())
                if 1 <= n <= len(files):
                    return files[n - 1]
            except (ValueError, EOFError):
                pass
            return None
        else:
            return files[0]

    while True:
        try:
            user_input = input(f"{Fore.GREEN}💬 你: {Style.RESET_ALL}").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{Fore.YELLOW}[INFO] 退出辅导{Style.RESET_ALL}")
            break

        if not user_input:
            continue

        if user_input.lower() == ":quit":
            print(f"{Fore.YELLOW}[INFO] 退出辅导{Style.RESET_ALL}")
            break

        # ── 查看原始内容 ──
        if user_input.lower().startswith(":view"):
            if is_multi:
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    try:
                        n = int(parts[1])
                        if 1 <= n <= len(files):
                            view_file = files[n - 1]
                        else:
                            view_file = _pick_file("view")
                    except ValueError:
                        view_file = _pick_file("view")
                else:
                    view_file = _pick_file("view")
                if view_file is None:
                    continue
                fp, ttl = view_file
            else:
                fp, ttl = files[0]

            content = read_md_file(fp)
            print(f"\n{Fore.CYAN}── 文件原始内容: {ttl[:40]} ──{Style.RESET_ALL}")
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if i >= 80:
                    print(f"{Fore.YELLOW}... (共 {len(lines)} 行，仅显示前80行) ...{Style.RESET_ALL}")
                    break
                print(f"  {Fore.LIGHTBLACK_EX}{line}{Style.RESET_ALL}")
            print()
            continue

        # ── 二次创作 ──
        if user_input.lower().startswith(":rewrite"):
            extra = user_input[len(":rewrite"):].strip()
            if is_multi:
                # 尝试解析文件编号，如 ":rewrite 2 请优化"
                parts = extra.split(maxsplit=1) if extra else [""]
                try:
                    n = int(parts[0])
                    if 1 <= n <= len(files):
                        rewrite_file = files[n - 1]
                        extra = parts[1] if len(parts) > 1 else ""
                    else:
                        rewrite_file = _pick_file("rewrite " + extra)
                except ValueError:
                    rewrite_file = _pick_file("rewrite " + extra)
                if rewrite_file is None:
                    continue
                fp, ttl = rewrite_file
            else:
                fp, ttl = files[0]

            print(f"\n{Fore.CYAN}✍️ AI正在二次创作: {ttl[:40]}...{Style.RESET_ALL}")
            summary, new_content = await tutor.rewrite_file(fp, extra)
            print(f"\n{Fore.GREEN}📝 修改说明:{Style.RESET_ALL}")
            print(f"  {summary}")

            if new_content:
                print(f"\n{Fore.CYAN}── 改写后的内容（前40行预览）──{Style.RESET_ALL}")
                new_lines = new_content.split('\n')
                for i, line in enumerate(new_lines[:40]):
                    print(f"  {Fore.LIGHTBLACK_EX}{line}{Style.RESET_ALL}")
                if len(new_lines) > 40:
                    print(f"  {Fore.YELLOW}... (共 {len(new_lines)} 行) ...{Style.RESET_ALL}")

                save = input(f"\n{Fore.CYAN}是否保存改写结果到文件？(y/N): {Style.RESET_ALL}").strip().lower()
                if save == 'y':
                    if write_md_file(fp, new_content):
                        print(f"{Fore.GREEN}[OK] 文件已更新！（原文件已备份为 .md.bak）{Style.RESET_ALL}")
                        conversation_history = []
                    else:
                        print(f"{Fore.RED}[ERROR] 保存失败{Style.RESET_ALL}")
            print()
            continue

        # ── 生成 HTML ──
        if user_input.lower().startswith(":html"):
            # 多文件总是生成综合HTML
            parts = user_input.split(maxsplit=1)
            style = parts[1].strip().lower() if len(parts) > 1 else "dark"
            if style not in ("dark", "light", "modern"):
                style = "dark"

            file_label = f"{len(files)}个文件" if is_multi else titles[0]
            print(f"\n{Fore.CYAN}🎨 正在生成HTML网页 [{file_label}] (风格: {style})...{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}[INFO] 这可能需要30-60秒，请耐心等待...{Style.RESET_ALL}")

            html_content = await tutor.generate_html(file_paths, style)

            html_dir = os.path.join(KNOWLEDGE_BASE_DIR, ".html_exports")
            os.makedirs(html_dir, exist_ok=True)
            if is_multi:
                safe_title = f"multi_{len(files)}files"
            else:
                safe_title = re.sub(r'[\\/*?:"<>|]', '_', titles[0])[:40]
            html_path = os.path.join(html_dir, f"{safe_title}_{style}.html")
            try:
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                print(f"{Fore.GREEN}[OK] HTML已保存到: {html_path}{Style.RESET_ALL}")

                print(f"{Fore.CYAN}正在尝试打开HTML文件...{Style.RESET_ALL}")
                try:
                    import webbrowser
                    webbrowser.open(f"file://{html_path}")
                    print(f"{Fore.GREEN}[OK] 已用默认浏览器打开{Style.RESET_ALL}")
                except Exception:
                    print(f"{Fore.YELLOW}[INFO] 无法自动打开，请手动用浏览器打开: {html_path}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 保存HTML失败: {e}{Style.RESET_ALL}")
            print()
            continue

        # ── 普通问答 ──
        print(f"\n{Fore.CYAN}🤔 AI思考中...{Style.RESET_ALL}")
        reply = await tutor.chat_about_file(file_paths, user_input, conversation_history)

        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": reply})
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]

        print(f"\n{Fore.MAGENTA}🎓 AI导师:{Style.RESET_ALL}")
        print(f"  {reply}")
        print()


async def video_to_html_bg():
    """🎨 视频→网页: 搜索B站视频, AI生成HTML分析页面"""
    from pathlib import Path

    print(f"\n{Fore.CYAN}+{'='*60}+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}|        🎨 视频→网页 — AI生成HTML分析页面                    |{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+{'='*60}+{Style.RESET_ALL}")
    
    brain = AgentBrain()
    brain.bili._load_credential()
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, encoding='utf-8') as f:
            brain.cookies = json.load(f)
    
    q = input(f"\n{Fore.CYAN}请输入视频链接/标题/UP主名字: {Style.RESET_ALL}").strip()
    if not q: return
    
    # same search flow as V
    bvid = title = up_name = ""
    # 智能提取BV号：支持纯BV号、链接、标题+链接混合输入
    import re as _re
    bvid_match = _re.search(r'BV[a-zA-Z0-9]{10}', q)
    if bvid_match:
        bvid = bvid_match.group(0)
        print(f"{Fore.GREEN}[OK] 检测到BV号: {bvid}{Style.RESET_ALL}")
        title = ""  # 稍后从 API 获取真实标题
    elif q.startswith("http") or q.startswith("BV"):
        bvid = q.split("/video/")[-1].split("?")[0] if "/" in q else q
        # 再次清洗确保是纯BV号
        bvid = _re.search(r'BV[a-zA-Z0-9]{10}', bvid)
        bvid = bvid.group(0) if bvid else ""
        if bvid:
            print(f"{Fore.GREEN}[OK] 直接使用: {bvid}{Style.RESET_ALL}")
            title = ""
    else:
        print(f"\n{Fore.CYAN}正在B站搜索: {q}...{Style.RESET_ALL}")
        results = await brain.bili.search_bilibili(q, limit=12)
        if not results:
            print(f"{Fore.RED}[ERROR] 未找到相关视频{Style.RESET_ALL}")
            return
        save_search_history(q, len(results))
        print(f"\n{Fore.GREEN}found {len(results)} results:{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{chr(9472)*80}{Style.RESET_ALL}")
        for i, r in enumerate(results):
            print(f"  {Fore.YELLOW}{i+1:>2}.{Style.RESET_ALL} {r['title'][:50]}")
            print(f"      {Fore.LIGHTBLACK_EX}@{r.get('author','?')}  |  ▶ {r.get('play',0)}  |  ⏱ {r.get('duration','??')}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{chr(9472)*80}{Style.RESET_ALL}")
        print(f"  {Fore.YELLOW}0.{Style.RESET_ALL} 取消")
        loop = asyncio.get_running_loop()
        choice = (await loop.run_in_executor(None, input, f"\n{Fore.CYAN}select (1-{len(results)}): {Style.RESET_ALL}")).strip()
        if choice == "0" or choice == "": return
        try:
            idx = int(choice)-1
            if 0<=idx<len(results):
                r = results[idx]; bvid = r['bvid']; title = r['title']; up_name = r.get('author','')
            else:
                print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}"); return
        except ValueError:
            print(f"{Fore.RED}[ERROR] 请输入数字编号{Style.RESET_ALL}"); return
    
    # 直接BV模式：从API补全标题和UP主信息
    if not title or not up_name:
        try:
            _headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com/"
            }
            async with httpx.AsyncClient(http2=True, timeout=10.0) as _hc:
                _vr = await _hc.get(
                    f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
                    headers=_headers, cookies=getattr(brain, 'cookies', None)
                )
                _vd = _vr.json()
                if _vd.get('code') == 0:
                    _v = _vd['data']
                    title = title or _v.get('title', '')
                    up_name = up_name or _v.get('owner', {}).get('name', '')
        except Exception:
            pass

    video_url = f"https://www.bilibili.com/video/{bvid}"
    print(f"\n{Fore.GREEN}video: {title[:40]}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}UP主: @{up_name}  |  {video_url}{Style.RESET_ALL}")
    
    # 模板选择
    print(f"\n{Fore.CYAN}🎨 视觉风格 (0=auto):{Style.RESET_ALL}")
    print(f"  1.🌙 暗夜粒子 — 暗色+红金粒子Canvas动画+科技感")
    print(f"  2.💡 极简白昼 — 亮色现代+干净排版+阅读优先")
    print(f"  3.🎞️ 幻灯片叙事 — 多页翻页+章节导航+动画入场")
    print(f"  4.🃏 卡片画廊 — 卡片网格+悬停动效+信息密度高")
    print(f"  5.🍊 Claude 暖橙 — Inter字体+暖灰背景+紫粉渐变标题")
    loop = asyncio.get_running_loop()
    t = (await loop.run_in_executor(None, input, f"{Fore.CYAN}> {Style.RESET_ALL}")).strip()
    styles = {'1':'dark','2':'light','3':'slide','4':'card','5':'claude'}
    style = styles.get(t, 'auto')

    # 输出格式选择
    print(f"\n{Fore.CYAN}📄 输出格式 (0=auto/AI自动判断):{Style.RESET_ALL}")
    print(f"  1.📄 正常网页 — 标准文章/知识卡片布局")
    print(f"  2.🎞️ PPT演示 — 多页幻灯片+键盘翻页+动画")
    print(f"  3.🎬 动画讲解 — 步骤动画+渐进展示+叙事节奏")
    print(f"  4.🤖 AI建议 — 让AI分析内容后推荐最佳格式")
    fmt_input = (await loop.run_in_executor(None, input, f"{Fore.CYAN}> {Style.RESET_ALL}")).strip()
    fmt_map = {'1':'webpage','2':'ppt','3':'animation','4':'ai_suggest'}
    output_format = fmt_map.get(fmt_input, 'auto')

    # 自定义页数 (仅PPT/动画/auto格式有意义)
    page_count = 0  # 0=AI自动
    if output_format in ('ppt', 'animation', 'auto', 'ai_suggest'):
        print(f"\n{Fore.CYAN}📑 页数设置 (0=AI自动, 回车跳过):{Style.RESET_ALL}")
        print(f"  输入数字指定页数，如 5-10 表示5~10页，回车则AI自动决定")
        pc_input = (await loop.run_in_executor(None, input, f"{Fore.CYAN}> {Style.RESET_ALL}")).strip()
        if pc_input:
            try:
                if '-' in pc_input:
                    parts = pc_input.split('-')
                    min_p = int(parts[0].strip())
                    max_p = int(parts[1].strip())
                    page_count = (min_p, max_p)
                    print(f"  {Fore.GREEN}✓ 页数范围: {min_p}~{max_p} 页{Style.RESET_ALL}")
                else:
                    page_count = int(pc_input)
                    print(f"  {Fore.GREEN}✓ 页数: {page_count} 页{Style.RESET_ALL}")
            except ValueError:
                print(f"  {Fore.YELLOW}⚠ 格式无效，使用AI自动决定{Style.RESET_ALL}")
                page_count = 0

    # 自定义提示词
    print(f"\n{Fore.CYAN}✏️ 自定义提示词 (可选, 回车跳过):{Style.RESET_ALL}")
    custom = (await loop.run_in_executor(None, input, f"{Fore.CYAN}> {Style.RESET_ALL}")).strip()
    
    # get content
    print(f"\n{Fore.CYAN}[1/3] 获取视频字幕...{Style.RESET_ALL}")
    ok, subs, desc, _ = await fetch_bilibili_subtitles(bvid, cookies_obj=getattr(brain,'cookies',None), title=title)

    if ok and subs and len(subs) > 30:
        ctx = subs
    else:
        # ── 字幕不可用 → 尝试 ASR 下载音频转文字（复用 V 命令的完整管道）──
        _aid = 0
        print(f"  {Fore.YELLOW}⚠ 无字幕，尝试 ASR 语音识别...{Style.RESET_ALL}")
        try:
            # 先补全元数据
            _headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Referer": "https://www.bilibili.com/"
            }
            async with httpx.AsyncClient(http2=True, timeout=12.0) as _hc:
                _vr = await _hc.get(
                    f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
                    headers=_headers, cookies=getattr(brain, 'cookies', None)
                )
                _vd = _vr.json()
                if _vd.get('code') == 0:
                    _v = _vd['data']
                    _aid = _v.get('aid', 0)
                    if not title:
                        title = _v.get('title', '')
                    if not up_name:
                        up_name = _v.get('owner', {}).get('name', '')
                    if not desc:
                        desc = (_v.get('desc', '') or '').strip()
            print(f"  {Fore.GREEN}✓ 元数据补全: {title[:30]} / @{up_name} / aid={_aid}{Style.RESET_ALL}")
        except Exception as _e:
            print(f"  {Fore.YELLOW}⚠ 元数据获取失败: {_e}{Style.RESET_ALL}")

        # 走完整 ASR 管道：下载音频→FunASR/Whisper转录
        ctx = f"[视频标题] {title}\n\n[视频简介] {desc or '(无简介)'}"
        asr_success = False
        try:
            print(f"  {Fore.CYAN}🎙️ 启动语音识别管道 (下载视频→ASR转文字)...{Style.RESET_ALL}")
            # 复用 brain 的超级智能理解链，它会自动下载视频+ASR
            success, asr_text = await brain.understand_video_for_decision(bvid, title=title)
            if success and asr_text and len(asr_text) > 100:
                ctx = asr_text
                asr_success = True
                print(f"  {Fore.GREEN}✓ ASR 语音识别成功 ({len(asr_text)}字){Style.RESET_ALL}")
            else:
                print(f"  {Fore.YELLOW}⚠ ASR 结果不足 ({len(asr_text) if asr_text else 0}字)，启用评论补充{Style.RESET_ALL}")
        except Exception as _e:
            print(f"  {Fore.YELLOW}⚠ ASR 管道失败: {_e}，回退到评论模式{Style.RESET_ALL}")

        # 拉取热门评论丰富上下文（ASR失败或内容太短时）
        if not asr_success and _aid > 0:
            try:
                print(f"  {Fore.CYAN}📝 获取热门评论...{Style.RESET_ALL}")
                comments = await brain.bili.get_hot_comments(_aid, limit=10)
                if comments:
                    lines = []
                    for c in comments[:10]:
                        uname = c.get('member', {}).get('uname', '')
                        msg = c.get('content', {}).get('message', '')
                        if msg:
                            lines.append(f"@{uname}: {msg}")
                    if lines:
                        ctx += f"\n\n[热门评论 Top{len(lines)}]\n" + "\n".join(lines)
                        print(f"  {Fore.GREEN}✓ 获取到 {len(lines)} 条热门评论{Style.RESET_ALL}")
                else:
                    print(f"  {Fore.YELLOW}⚠ 该视频暂无评论{Style.RESET_ALL}")
            except Exception as _e:
                print(f"  {Fore.YELLOW}⚠ 评论获取失败 (跳过): {_e}{Style.RESET_ALL}")
    
    # generate HTML (同步等待，不再用不可靠的后台任务)
    print(f"{Fore.CYAN}[2/3] AI正在生成HTML...{Style.RESET_ALL}")
    sp = f"使用 {style} 视觉风格" if style!='auto' else "自动选择最合适的视觉风格"
    
    # 构建格式指令
    if output_format == 'webpage':
        fmt_instruction = "输出格式：标准网页文章布局，适合阅读。包含导航、内容区、侧边栏或底部推荐。"
    elif output_format == 'ppt':
        fmt_instruction = "输出格式：多页PPT幻灯片风格。每页一个主题，支持键盘←→翻页、底部导航点、入场动画。"
    elif output_format == 'animation':
        fmt_instruction = "输出格式：动画讲解风格。内容分步骤渐进展示，带滚动触发动画、打字机效果、步骤编号，像一场讲解演出。"
    elif output_format == 'ai_suggest':
        fmt_instruction = "输出格式：请AI你先分析这个视频的内容类型（教程/访谈/观点/新闻/Vlog等），然后在回复开头用一行 `<!--FORMAT:xxx-->` 说明你推荐的格式（webpage/ptt/animation），接着生成对应格式的HTML。"
    else:
        fmt_instruction = "输出格式：请AI你根据视频内容自动判断最佳呈现方式（教程→PPT、观点→文章、故事→动画等）。"
    
    prompt = f"""你是一个顶级网页设计师和知识萃取师。根据以下B站视频信息生成一个完整的HTML页面(内嵌CSS,响应式)。

视觉风格要求：{sp}
{fmt_instruction}

页面必须包含：视频标题、UP主、内容总结、关键要点/知识点、金句摘录。
要求：代码完整可独立运行，CSS内嵌，响应式设计，美观专业。
只输出完整HTML代码，不要额外解释。

Video title: {title}
UP主: {up_name}
Link: {video_url}
Content: {ctx[:1500]}"""
    if page_count:
        if isinstance(page_count, tuple):
            prompt += f"\n\n页面数量要求：生成 {page_count[0]}~{page_count[1]} 页（幻灯片/章节），不要少于{page_count[0]}页，不要超过{page_count[1]}页。"
        else:
            prompt += f"\n\n页面数量要求：严格生成 {page_count} 页（幻灯片/章节），不多不少正好 {page_count} 页。"
    if custom:
        prompt += f"\n\n用户额外要求: {custom}"
    try:
        from xingye_bot.settings import load_settings as _ls
        from xingye_bot.llm import ModelClient as _MC
        from xingye_bot.state import BotState as _BS
        _s = _ls()
        client = _MC(_s, _BS())
        resp = await client.chat([{"role":"user","content":prompt}], purpose="html_gen")
        html = resp.strip()
        if html.startswith('```'):
            parts = html.split('```', 2)
            html = parts[1].strip() if len(parts)>1 else html
            if html.lower().startswith('html'):
                html = html[4:].strip()

        print(f"\n{Fore.GREEN}[3/3] HTML已生成! 文件大小: {len(html)} 字符{Style.RESET_ALL}")

        # ── Flask 预览 ──
        try:
            from services.video_to_ppt import start_preview_server, stop_preview_server
            preview_url = start_preview_server(html)
            print(f"\n{Fore.CYAN}🌐 Flask预览服务已启动: {preview_url}{Style.RESET_ALL}")

            # 浏览器打开预览
            try:
                import webbrowser
                webbrowser.open(preview_url)
                print(f"{Fore.CYAN}[INFO] 已在浏览器中打开预览页面{Style.RESET_ALL}")
            except Exception:
                print(f"{Fore.YELLOW}[WARN] 无法自动打开浏览器，请手动访问: {preview_url}{Style.RESET_ALL}")
        except ImportError as e:
            print(f"{Fore.YELLOW}[WARN] Flask未安装，无法启动预览: {e}{Style.RESET_ALL}")
            preview_url = ""

        # ── 询问是否保存 ──
        print(f"\n{Fore.CYAN}{'─'*50}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}💾 是否保存此网页？{Style.RESET_ALL}")
        print(f"{Fore.CYAN}   按 Enter 跳过保存，输入路径保存到指定位置{Style.RESET_ALL}")

        # 默认保存到项目目录下的 web 文件夹
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_save_dir = os.path.join(project_root, 'web')
        # 确保 web 目录存在
        os.makedirs(default_save_dir, exist_ok=True)

        safe_title = re.sub(r'[\\/*?:"<>|]', '_', title)[:30]
        ts = int(time.time())
        default_filename = f"{safe_title}_{style}_{ts}.html"

        print(f"{Fore.LIGHTBLACK_EX}   默认保存路径: {os.path.join(default_save_dir, default_filename)}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}   支持: 完整路径 | 目录(自动命名) | 直接 Enter=跳过{Style.RESET_ALL}")
        save_input = input(f"{Fore.GREEN}> {Style.RESET_ALL}").strip()

        if save_input:
            save_path = Path(save_input)
            # 如果输入以 / 或 \ 结尾，视为目录，自动生成文件名
            if save_input.endswith('/') or save_input.endswith('\\'):
                save_path = save_path / default_filename
            elif save_path.suffix.lower() != '.html':
                # 没有后缀，也视为目录
                save_path = save_path / default_filename
            # else: 完整的 .html 文件路径，直接使用

            # 确保父目录存在
            save_path.parent.mkdir(parents=True, exist_ok=True)

            # 如果文件已存在，追加时间戳
            if save_path.exists():
                ts2 = int(time.time())
                save_path = save_path.with_name(f"{save_path.stem}_{ts2}{save_path.suffix}")

            save_path.write_text(html, encoding='utf-8')
            print(f"{Fore.GREEN}[OK] 已保存到: {save_path.resolve()}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}[SKIP] 未保存文件（预览页面仍可访问）{Style.RESET_ALL}")

        # 提示：预览服务器将在程序退出时自动关闭
        if preview_url:
            print(f"{Fore.LIGHTBLACK_EX}   💡 Flask预览服务器将持续运行 ({preview_url})，退出程序时自动停止{Style.RESET_ALL}")

    except Exception as e:
        import traceback
        print(f"{Fore.RED}[ERROR] HTML生成失败: {e}{Style.RESET_ALL}")
        traceback.print_exc()
        return
    


# [knowledge/browse.py] count_knowledge_categories
def show_kb_statistics():
    """显示知识库统计信息"""
    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        print(f"{Fore.YELLOW}[WARN]  知识库目录不存在！{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.CYAN}                知识库统计信息{Style.RESET_ALL}")
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    
    total_files = 0
    total_size = 0
    categories = {}
    
    for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        rel_path = os.path.relpath(root, KNOWLEDGE_BASE_DIR)
        if rel_path == '.':
            category = "根目录"
        else:
            depth = len(rel_path.split(os.sep))
            category = f"{'  ' * (depth-1)}[FILE] {rel_path}"
        
        txt_files = [f for f in files if f.endswith('.txt') or f.endswith('.md')]
        if txt_files:
            categories[category] = len(txt_files)
            total_files += len(txt_files)
            
            for file in txt_files:
                file_path = os.path.join(root, file)
                total_size += os.path.getsize(file_path)
    
    print(f"\n{Fore.YELLOW}[STATS] 总体统计:{Style.RESET_ALL}")
    print(f"  • 知识库路径: {KNOWLEDGE_BASE_DIR}")
    print(f"  • 总文件数: {total_files} 个")
    print(f"  • 总大小: {total_size / 1024:.1f} KB")
    print(f"  • 分类数量: {len(categories)} 个")
    
    if categories:
        print(f"\n{Fore.YELLOW}[FILE] 分类详情:{Style.RESET_ALL}")
        for category, count in sorted(categories.items()):
            print(f"  • {category}: {count} 个文件")
    
    if os.path.exists(LEARNING_LOG_FILE):
        with open(LEARNING_LOG_FILE, 'r', encoding='utf-8') as f:
            log_lines = len(f.readlines())
        print(f"\n{Fore.YELLOW}[NOTE] 学习日志:{Style.RESET_ALL}")
        print(f"  • 学习记录: {log_lines} 条")
    
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")

# [knowledge/browse.py] browse_kb_structure
# [knowledge/browse.py] search_knowledge_content
# [knowledge/browse.py] cleanup_duplicates
def show_learning_log():
    """显示学习日志"""
    if not os.path.exists(LEARNING_LOG_FILE):
        print(f"{Fore.YELLOW}[WARN]  学习日志文件不存在！{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.CYAN}                  学习记录日志{Style.RESET_ALL}")
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    
    try:
        with open(LEARNING_LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        if lines:
            for line in lines[-20:]:
                print(f"  • {line.strip()}")
        else:
            print(f"{Fore.YELLOW}暂无学习记录{Style.RESET_ALL}")
        
        print(f"\n{Fore.YELLOW}[STATS] 总计: {len(lines)} 条学习记录{Style.RESET_ALL}")
        
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 读取学习日志失败: {e}{Style.RESET_ALL}")
    
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")

# [bili/auth.py] clear_login_info
def save_search_history(query, results_count):
    """保存搜索记录"""
    try:
        history = []
        if os.path.exists(SEARCH_HISTORY_FILE):
            with open(SEARCH_HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
        history.append({
            "time": datetime.now().isoformat(),
            "query": query,
            "results": results_count
        })
        # 只保留最近100条
        if len(history) > 100:
            history = history[-100:]
        tmp = SEARCH_HISTORY_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SEARCH_HISTORY_FILE)
    except Exception as e:
        log(f"保存搜索记录失败: {e}", "WARN")

_bg_tasks = []
_bg_next_id = [1]

def _add_bg_task(tt, title):
    tid = _bg_next_id[0]; _bg_next_id[0] += 1
    from datetime import datetime
    _bg_tasks.append({"id": tid, "type": tt, "title": title, "status": "running", "result": "", "time": datetime.now().strftime("%H:%M:%S")})
    return tid

def _bg_done(tid, ok, result=""):
    for t in _bg_tasks:
        if t["id"] == tid: t["status"] = "done" if ok else "failed"; t["result"] = result[:200]; break

def _show_bg_tasks():
    if not _bg_tasks:
        print(f"\n{Fore.YELLOW}[INFO] 没有后台任务{Style.RESET_ALL}")
        return
    print(f"\n{Fore.CYAN}后台任务 ({len(_bg_tasks)}个):{Style.RESET_ALL}")
    for t in _bg_tasks[-10:]:
        icon = {"running":"[RUN]","done":"[OK]","failed":"[FAIL]"}.get(t["status"],"?")
        print(f"  {icon} [{t['id']}] {t['time']} {t['type']}: {t['title'][:50]}")
        if t["result"]: print(f"      -> {t['result'][:100]}")

async def _bg_html_gen(tid, bvid, title, up_name, style, custom):
    try:
        from xingye_bot.settings import load_settings as _ls
        from xingye_bot.llm import ModelClient as _MC
        from xingye_bot.state import BotState as _BS
        _s, _st = _ls(), _BS(); _mc = _MC(_s, _st)
        ok, subs, desc, _ = await fetch_bilibili_subtitles(bvid, title=title)
        ctx = subs if ok and subs and len(subs)>30 else f"{title}. {desc}"
        sp = f"{style} style" if style != "auto" else "auto style"
        p = f"Generate complete single-file HTML page (inline CSS, responsive). {sp}. Title: {title}\nUP: {up_name}\nContent: {ctx[:1000]}\nOutput ONLY HTML code."
        if custom: p += f"\n\nUser request: {custom}"
        resp = await _mc.chat([{"role":"user","content":p}], purpose="html_gen")
        html = resp.strip()
        if html.startswith("```"): html = html.split("```", 2)[1].strip()
        if html.lower().startswith("html"): html = html[4:].strip()
        d = os.path.join(BASE_DIR, "html_exports"); os.makedirs(d, exist_ok=True)
        sf = re.sub(r'[\\/*?:"<>|]', '_', title)[:30]
        hp = os.path.join(d, f"{sf}_{style}_{tid}.html")
        with open(hp, 'w') as f: f.write(html)
        _bg_done(tid, True, f"OK: {os.path.basename(hp)}")
    except Exception as e:
        _bg_done(tid, False, str(e)[:150])

def show_search_history():
    """显示搜索记录"""
    if not os.path.exists(SEARCH_HISTORY_FILE):
        print(f"{Fore.YELLOW}[INFO] 暂无搜索记录{Style.RESET_ALL}")
        return
    try:
        with open(SEARCH_HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
        if not history:
            print(f"{Fore.YELLOW}[INFO] 搜索记录为空{Style.RESET_ALL}")
            return
        print(f"\n{Fore.CYAN}📋 搜索历史 (最近{len(history)}条):{Style.RESET_ALL}")
        print(f"{Fore.LIGHTBLACK_EX}{'─' * 60}{Style.RESET_ALL}")
        for i, h in enumerate(reversed(history[-20:])):  # 最近20条
            t = h.get('time','')[:16].replace('T',' ')
            q = h.get('query','')[:40]
            n = h.get('results',0)
            print(f"  {Fore.YELLOW}{i+1:>2}.{Style.RESET_ALL} [{t}] {q} ({n}条结果)")
        print(f"{Fore.LIGHTBLACK_EX}{'─' * 60}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 读取搜索记录失败: {e}{Style.RESET_ALL}")


def factory_reset_all():
    """[FACTORY RESET] 一键恢复所有配置为默认值，清除登录/状态/日志等一切数据"""
    global config
    import shutil as _shu
    import glob as _glob

    print(f"\n{Fore.RED}╔════════════════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"{Fore.RED}║  ⚠️  危险操作：彻底恢复出厂设置              ║{Style.RESET_ALL}")
    print(f"{Fore.RED}║  将清除: 配置/登录/状态/日志/UP主记忆/心理画像║{Style.RESET_ALL}")
    print(f"{Fore.RED}║  含: 主人信息/推荐记录/行为日志/向量索引等  ║{Style.RESET_ALL}")
    print(f"{Fore.RED}║  含: 待机监控/二维码/HTML导出/知识库等      ║{Style.RESET_ALL}")
    print(f"{Fore.RED}║  AI模型文件不受影响                           ║{Style.RESET_ALL}")
    print(f"{Fore.RED}╚════════════════════════════════════════════════╝{Style.RESET_ALL}")

    confirm = input(f"\n{Fore.RED}确认恢复？输入 YES 继续: {Style.RESET_ALL}").strip()
    if confirm.upper() != "YES":
        print(f"{Fore.YELLOW}已取消{Style.RESET_ALL}")
        return

    # ── 第一问：知识库 ──
    clear_kb = input(f"{Fore.YELLOW}是否也删除知识库目录 (KnowledgeBase/)？(y/N): {Style.RESET_ALL}").strip().lower()
    clear_kb = clear_kb in ("y", "yes")

    # ── 第二问：干货 ──
    clear_dry = False
    if os.path.exists(DRY_GOODS_DIR):
        clear_dry = input(f"{Fore.YELLOW}是否也删除干货目录 (highlights/)？(y/N): {Style.RESET_ALL}").strip().lower()
        clear_dry = clear_dry in ("y", "yes")

    # ── 第三问：HTML 导出 ──
    clear_html = False
    html_dir = os.path.join(BASE_DIR, "html_exports")
    if os.path.exists(html_dir):
        clear_html = input(f"{Fore.YELLOW}是否也删除HTML导出目录 (html_exports/)？(y/N): {Style.RESET_ALL}").strip().lower()
        clear_html = clear_html in ("y", "yes")

    deleted_count = 0

    # ═══════════════════════════════════════════════════════════
    # 1) 单文件 — Data/ 下的 JSON/MD 数据
    # ═══════════════════════════════════════════════════════════
    files_to_delete = [
        # 核心配置 & 登录
        ("登录Cookie",           COOKIE_FILE),
        ("运行时状态",           RUNTIME_STATE_FILE),
        ("机器人锁",             BOT_LOCK_FILE),
        # 用户数据
        ("搜索记录",             SEARCH_HISTORY_FILE),
        ("兴趣配置",             INTERESTS_FILE),
        ("人设配置",             PERSONAS_FILE),
        ("用户画像",             USER_PROFILES_FILE),
        # 互动日志
        ("评论日志",             COMMENT_LOG_FILE),
        ("私信日志",             PRIVATE_MESSAGE_LOG_FILE),
        ("私信上下文",           PRIVATE_CONTEXT_FILE),
        ("视频互动记录",         HISTORY_VIDEOS_FILE),
        # Agent & 进化
        ("Agent技能日志",        AGENT_SKILL_LOG_FILE),
        ("自我进化记录",         SELF_EVOLUTION_FILE),
        ("心情状态",             MOOD_STATE_FILE),
        ("机器人日记",           BOT_DIARY_FILE),
        # 知识 & 记忆
        ("学习日志",             LEARNING_LOG_FILE),
        ("知识库元数据",         KB_METADATA_FILE),
        ("UP主关注记忆",         MEMORY_FILE),
        ("机器人日志",           JOURNAL_FILE),
        # 心理画像
        ("心理画像",             os.path.join(DATA_DIR, "psycho_profile.json")),
        ("心理推荐日志",         os.path.join(DATA_DIR, "recommendation_log.json")),
        ("心理行为日志",         os.path.join(DATA_DIR, "action_log.json")),
        ("内容避雷",             os.path.join(DATA_DIR, "content_aversions.json")),
        ("主人信息",             os.path.join(DATA_DIR, "owner_profile.json")),
        # 向量 & 检索
        ("向量检索索引",         os.path.join(DATA_DIR, "kb_vector_index.json")),
        # 待机/监控 (v3.0.1+)
        ("待机配置",             os.path.join(DATA_DIR, "standby_config.json")),
        ("待机统计",             os.path.join(DATA_DIR, "standby_stats.json")),
        ("监控配置",             os.path.join(DATA_DIR, "monitor_config.json")),
        ("监控统计",             os.path.join(DATA_DIR, "monitor_stats.json")),
        # 评论区缓存 (legacy)
        ("评论区回复缓存",       os.path.join(DATA_DIR, "reply_cache.json")),
        ("评论已处理列表",       os.path.join(DATA_DIR, "processed_comments.json")),
    ]

    for name, path in files_to_delete:
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已删除: {name} ({os.path.basename(path)})")
                deleted_count += 1
            except Exception as e:
                print(f"  {Fore.RED}✗{Style.RESET_ALL} 删除失败: {name} - {e}")
        else:
            print(f"  {Fore.LIGHTBLACK_EX}- {name}: 不存在,跳过{Style.RESET_ALL}")

    # ═══════════════════════════════════════════════════════════
    # 2) Data/ 下所有子目录 (video_cache / feedback / 等)
    # ═══════════════════════════════════════════════════════════
    if os.path.isdir(DATA_DIR):
        for item in os.listdir(DATA_DIR):
            item_path = os.path.join(DATA_DIR, item)
            if os.path.isdir(item_path):
                try:
                    _shu.rmtree(item_path, ignore_errors=True)
                    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已删除目录: Data/{item}")
                    deleted_count += 1
                except Exception as e:
                    print(f"  {Fore.RED}✗{Style.RESET_ALL} 删除目录失败: Data/{item} - {e}")

    # ═══════════════════════════════════════════════════════════
    # 3) 知识库目录 (KnowledgeBase/)
    # ═══════════════════════════════════════════════════════════
    if clear_kb and os.path.exists(KNOWLEDGE_BASE_DIR):
        try:
            _shu.rmtree(KNOWLEDGE_BASE_DIR, ignore_errors=True)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已删除: 知识库目录")
            deleted_count += 1
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} 知识库删除失败: {e}")

    # ═══════════════════════════════════════════════════════════
    # 4) 干货目录 (highlights/)
    # ═══════════════════════════════════════════════════════════
    if clear_dry and os.path.exists(DRY_GOODS_DIR):
        try:
            _shu.rmtree(DRY_GOODS_DIR, ignore_errors=True)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已删除: 干货目录")
            deleted_count += 1
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} 干货目录删除失败: {e}")

    # ═══════════════════════════════════════════════════════════
    # 5) HTML 导出目录 (html_exports/)
    # ═══════════════════════════════════════════════════════════
    if clear_html and os.path.exists(html_dir):
        try:
            _shu.rmtree(html_dir, ignore_errors=True)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已删除: HTML导出目录")
            deleted_count += 1
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} HTML导出目录删除失败: {e}")

    # ═══════════════════════════════════════════════════════════
    # 6) 二维码临时目录 (qr_codes/)
    # ═══════════════════════════════════════════════════════════
    qr_dir = os.path.join(BASE_DIR, "qr_codes")
    if os.path.exists(qr_dir):
        try:
            _shu.rmtree(qr_dir, ignore_errors=True)
            os.makedirs(qr_dir, exist_ok=True)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已清空: qr_codes/")
            deleted_count += 1
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} 清理 qr_codes 失败: {e}")

    # ═══════════════════════════════════════════════════════════
    # 7) 根目录临时 HTML 文件 (web_explain_*.html)
    # ═══════════════════════════════════════════════════════════
    for html_file in _glob.glob(os.path.join(BASE_DIR, "web_explain_*.html")):
        try:
            os.remove(html_file)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已删除: {os.path.basename(html_file)}")
            deleted_count += 1
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} 删除失败: {html_file} - {e}")

    # ═══════════════════════════════════════════════════════════
    # 8) 根目录 ID 列表文件 (html_ids.txt / js_ids.txt)
    # ═══════════════════════════════════════════════════════════
    for id_file in ("html_ids.txt", "js_ids.txt"):
        id_path = os.path.join(BASE_DIR, id_file)
        if os.path.exists(id_path):
            try:
                os.remove(id_path)
                print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已删除: {id_file}")
                deleted_count += 1
            except Exception as e:
                print(f"  {Fore.RED}✗{Style.RESET_ALL} 删除失败: {id_file} - {e}")

    # ═══════════════════════════════════════════════════════════
    # 9) KnowledgeBase/.html_exports (知识库内嵌HTML缓存)
    # ═══════════════════════════════════════════════════════════
    kb_html_dir = os.path.join(KNOWLEDGE_BASE_DIR, ".html_exports") if KNOWLEDGE_BASE_DIR else None
    if kb_html_dir and os.path.exists(kb_html_dir) and not clear_kb:
        try:
            _shu.rmtree(kb_html_dir, ignore_errors=True)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已删除: KnowledgeBase/.html_exports/")
            deleted_count += 1
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} 删除 KnowledgeBase/.html_exports 失败: {e}")

    # ═══════════════════════════════════════════════════════════
    # 10) 重新生成默认配置文件
    # ═══════════════════════════════════════════════════════════
    config = DEFAULT_CONFIG.copy()
    save_config(config)
    _reload_all_globals(config)

    print(f"\n{Fore.GREEN}════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.GREEN}[OK] 恢复出厂设置完成！已重置 {deleted_count} 项，配置已恢复默认{Style.RESET_ALL}")
    print(f"{Fore.GREEN}    现在需要重新配置 AI Key 并重新登录才能使用{Style.RESET_ALL}")
    print(f"{Fore.GREEN}════════════════════════════════════════════════{Style.RESET_ALL}")
    input(f"\n{Fore.CYAN}按回车继续...{Style.RESET_ALL}")


def export_config():
    """[EXPORT] 一键导出所有配置/状态到备份目录，与项目文件分离"""
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.CYAN}[EXPORT] 一键导出所有配置和状态数据{Style.RESET_ALL}")
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")

    # 确保备份目录存在
    os.makedirs(BACKUP_DIR, exist_ok=True)
    export_path = BACKUP_FILE
    print(f"\n{Fore.GREEN}备份路径: {export_path}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}(与项目文件分离，项目删除/移动不影响备份){Style.RESET_ALL}")

    # 允许自定义路径（高级用法）
    custom = input(f"\n{Fore.YELLOW}回车=一键导出到默认备份目录 | 或输入自定义路径 (0=取消): {Style.RESET_ALL}").strip()
    if custom == "0":
        print(f"{Fore.YELLOW}已取消{Style.RESET_ALL}")
        return
    if custom:
        export_path = custom

    # 收集所有数据
    export_data = {
        "version": "2.0",
        "exported_at": datetime.now().isoformat(),
        "description": "bilibili_learning_bot 全量配置文件导出 - 导入时将恢复所有设置/登录/状态",
        "config": {},
        "bilibili_cookies": None,
        "mood_state": None,
        "personas": None,
        "user_profiles": None,
        "interests": None,
        "comment_log": None,
        "private_message_log": None,
        "history_videos": None,
        "agent_skill_log": None,
        "self_evolution": None,
        "bot_diary": None,
        "bot_runtime_state": None,
        "bot_memory": None,
        "knowledge_metadata": None,
        "learning_log": None,
        "psycho_profile": None,
        "content_aversions": None,
        "private_context_db": None,
        "bot_journal": None,
        "recommendation_log": None,
        "action_log": None,
        "owner_profile": None,
        "kb_vector_index": None,
    }

    # 🔒 导出时对敏感数据脱敏
    def _sanitize_export_data(data, key):
        if key in ("config", "bilibili_cookies") and data is not None:
            return sanitize_config_for_export(data)
        return data

    file_map = [
        ("config", CONFIG_FILE),
        ("bilibili_cookies", COOKIE_FILE),
        ("mood_state", MOOD_STATE_FILE),
        ("personas", PERSONAS_FILE),
        ("user_profiles", USER_PROFILES_FILE),
        ("interests", INTERESTS_FILE),
        ("comment_log", COMMENT_LOG_FILE),
        ("private_message_log", PRIVATE_MESSAGE_LOG_FILE),
        ("history_videos", HISTORY_VIDEOS_FILE),
        ("agent_skill_log", AGENT_SKILL_LOG_FILE),
        ("self_evolution", SELF_EVOLUTION_FILE),
        ("bot_diary", BOT_DIARY_FILE),
        ("bot_runtime_state", RUNTIME_STATE_FILE),
        ("bot_memory", MEMORY_FILE),
        ("private_context_db", PRIVATE_CONTEXT_FILE),
    ]

    exported_files = 0
    for key, path in file_map:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    export_data[key] = _sanitize_export_data(json.load(f), key)
                print(f"  {Fore.GREEN}✓{Style.RESET_ALL} {key} ({os.path.basename(path)})")
                exported_files += 1
            except Exception as e:
                print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} 读取失败 {os.path.basename(path)}: {e}")

    # 知识库元数据
    kb_metadata_file = os.path.join(BASE_DIR, "knowledge_metadata.json")
    if os.path.exists(kb_metadata_file):
        try:
            with open(kb_metadata_file, "r", encoding="utf-8") as f:
                export_data["knowledge_metadata"] = json.load(f)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} knowledge_metadata")
            exported_files += 1
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} 知识库元数据: {e}")

    # 学习日志 (纯文本)
    if os.path.exists(LEARNING_LOG_FILE):
        try:
            with open(LEARNING_LOG_FILE, "r", encoding="utf-8") as f:
                export_data["learning_log"] = f.read()
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} learning_log.md")
            exported_files += 1
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} 学习日志: {e}")

    # 心理画像
    psycho_file = os.path.join(DATA_DIR, "psycho_profile.json")
    if os.path.exists(psycho_file):
        try:
            with open(psycho_file, "r", encoding="utf-8") as f:
                export_data["psycho_profile"] = json.load(f)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} psycho_profile.json")
            exported_files += 1
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} 心理画像: {e}")

    # 内容厌恶记录
    aversions_file = os.path.join(DATA_DIR, "content_aversions.json")
    if os.path.exists(aversions_file):
        try:
            with open(aversions_file, "r", encoding="utf-8") as f:
                export_data["content_aversions"] = json.load(f)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} content_aversions.json")
            exported_files += 1
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} 内容厌恶记录: {e}")

    # Bot日志 (纯文本)
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
                export_data["bot_journal"] = f.read()
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} bot_journal.md")
            exported_files += 1
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} Bot日志: {e}")

    # 心理推荐日志
    rec_log_file = os.path.join(DATA_DIR, "recommendation_log.json")
    if os.path.exists(rec_log_file):
        try:
            with open(rec_log_file, "r", encoding="utf-8") as f:
                export_data["recommendation_log"] = json.load(f)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} recommendation_log.json")
            exported_files += 1
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} 推荐日志: {e}")

    # 心理行为日志
    action_log_file = os.path.join(DATA_DIR, "action_log.json")
    if os.path.exists(action_log_file):
        try:
            with open(action_log_file, "r", encoding="utf-8") as f:
                export_data["action_log"] = json.load(f)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} action_log.json")
            exported_files += 1
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} 行为日志: {e}")

    # 主人信息 (含UID)
    owner_file = os.path.join(DATA_DIR, "owner_profile.json")
    if os.path.exists(owner_file):
        try:
            with open(owner_file, "r", encoding="utf-8") as f:
                export_data["owner_profile"] = json.load(f)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} owner_profile.json")
            exported_files += 1
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} 主人信息: {e}")

    # 知识库向量索引
    vector_index_file = os.path.join(DATA_DIR, "kb_vector_index.json")
    if os.path.exists(vector_index_file):
        try:
            with open(vector_index_file, "r", encoding="utf-8") as f:
                export_data["kb_vector_index"] = json.load(f)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} kb_vector_index.json")
            exported_files += 1
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠{Style.RESET_ALL} 向量索引: {e}")

    # 写入导出文件
    try:
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        print(f"\n{Fore.GREEN}[OK] 导出完成！共 {exported_files} 项 → {export_path}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}提示: 新环境只需将此文件放到 {BACKUP_DIR}，再用「导入配置」一键恢复{Style.RESET_ALL}")
    except Exception as e:
        print(f"\n{Fore.RED}[ERROR] 导出文件写入失败: {e}{Style.RESET_ALL}")

    input(f"\n{Fore.CYAN}按回车继续...{Style.RESET_ALL}")


def import_config():
    """[IMPORT] 一键从备份目录恢复所有配置/状态/登录数据"""
    global config

    print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.CYAN}[IMPORT] 一键导入配置 - 从备份恢复所有设置{Style.RESET_ALL}")
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")

    import_path = BACKUP_FILE
    print(f"\n{Fore.GREEN}默认读取: {import_path}{Style.RESET_ALL}")

    # 允许自定义路径（如果备份在其他位置）
    custom = input(f"\n{Fore.YELLOW}回车=一键导入 | 或输入自定义路径 (0=取消): {Style.RESET_ALL}").strip()
    if custom == "0":
        print(f"{Fore.YELLOW}已取消{Style.RESET_ALL}")
        return
    if custom:
        import_path = custom

    if not os.path.exists(import_path):
        print(f"{Fore.RED}[ERROR] 文件不存在: {import_path}{Style.RESET_ALL}")
        return

    try:
        with open(import_path, "r", encoding="utf-8") as f:
            import_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"{Fore.RED}[ERROR] JSON解析失败: {e}{Style.RESET_ALL}")
        return
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 读取文件失败: {e}{Style.RESET_ALL}")
        return

    version = import_data.get("version", "?")
    exported_at = import_data.get("exported_at", "?")
    print(f"\n{Fore.CYAN}导出文件信息: 版本 {version}, 导出时间 {exported_at}{Style.RESET_ALL}")

    confirm = input(f"\n{Fore.YELLOW}确认导入？将覆盖当前所有配置/登录/状态！输入 YES 继续: {Style.RESET_ALL}").strip()
    if confirm.upper() != "YES":
        print(f"{Fore.YELLOW}已取消{Style.RESET_ALL}")
        return

    restored = 0
    file_map = [
        ("config", CONFIG_FILE),
        ("bilibili_cookies", COOKIE_FILE),
        ("mood_state", MOOD_STATE_FILE),
        ("personas", PERSONAS_FILE),
        ("user_profiles", USER_PROFILES_FILE),
        ("interests", INTERESTS_FILE),
        ("comment_log", COMMENT_LOG_FILE),
        ("private_message_log", PRIVATE_MESSAGE_LOG_FILE),
        ("history_videos", HISTORY_VIDEOS_FILE),
        ("agent_skill_log", AGENT_SKILL_LOG_FILE),
        ("self_evolution", SELF_EVOLUTION_FILE),
        ("bot_diary", BOT_DIARY_FILE),
        ("bot_runtime_state", RUNTIME_STATE_FILE),
        ("bot_memory", MEMORY_FILE),
    ]

    for key, path in file_map:
        data = import_data.get(key)
        if data is not None:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已恢复: {os.path.basename(path)}")
                restored += 1
            except Exception as e:
                print(f"  {Fore.RED}✗{Style.RESET_ALL} 恢复失败 {os.path.basename(path)}: {e}")

    # 知识库元数据
    kb_metadata_file = os.path.join(BASE_DIR, "knowledge_metadata.json")
    kb_data = import_data.get("knowledge_metadata")
    if kb_data is not None:
        try:
            with open(kb_metadata_file, "w", encoding="utf-8") as f:
                json.dump(kb_data, f, ensure_ascii=False, indent=2)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已恢复: knowledge_metadata.json")
            restored += 1
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} 知识库元数据: {e}")

    # 学习日志
    log_data = import_data.get("learning_log")
    if log_data is not None:
        try:
            with open(LEARNING_LOG_FILE, "w", encoding="utf-8") as f:
                f.write(log_data)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已恢复: learning_log.md")
            restored += 1
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} 学习日志: {e}")

    # 心理画像
    psycho_data = import_data.get("psycho_profile")
    if psycho_data is not None:
        psycho_file = os.path.join(DATA_DIR, "psycho_profile.json")
        try:
            with open(psycho_file, "w", encoding="utf-8") as f:
                json.dump(psycho_data, f, ensure_ascii=False, indent=4)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已恢复: psycho_profile.json")
            restored += 1
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} 心理画像: {e}")

    # 内容厌恶记录
    aversions_data = import_data.get("content_aversions")
    if aversions_data is not None:
        aversions_file = os.path.join(DATA_DIR, "content_aversions.json")
        try:
            with open(aversions_file, "w", encoding="utf-8") as f:
                json.dump(aversions_data, f, ensure_ascii=False, indent=4)
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} 已恢复: content_aversions.json")
            restored += 1
        except Exception as e:
            print(f"  {Fore.RED}✗{Style.RESET_ALL} 内容厌恶记录: {e}")

    # 重新加载配置（尤其重要：config 全局变量）
    new_config = load_config()
    config = new_config
    _reload_all_globals(config)

    print(f"\n{Fore.GREEN}════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.GREEN}[OK] 导入完成！成功恢复 {restored} 项，所有配置/登录/状态已恢复{Style.RESET_ALL}")
    print(f"{Fore.GREEN}    建议重启程序以确保所有模块正常运行{Style.RESET_ALL}")
    print(f"{Fore.GREEN}════════════════════════════════════════════════{Style.RESET_ALL}")

    input(f"\n{Fore.CYAN}按回车继续...{Style.RESET_ALL}")


# ═══════════════════════════════════════════════════════════════
# 🛋️ 待机模式设置 (Standby Mode Config)
# ═══════════════════════════════════════════════════════════════
def _configure_standby_settings():
    """待机模式完整设置：ASR/总结/评论区/PPT/视频触发 等全部选项"""
    from brain.standby import load_standby_config, save_standby_config, load_stats
    sc = load_standby_config()
    st = load_stats()

    # 确保所有键存在
    sc.setdefault("enabled", True)
    sc.setdefault("auto_reply", True)
    sc.setdefault("at_trigger_enabled", True)
    sc.setdefault("at_trigger_keywords", ["总结", "总结一下", "分析", "概括", "讲解", "归纳", "梳理"])
    sc.setdefault("comment_check_interval", 60)
    sc.setdefault("max_replies_per_check", 3)
    sc.setdefault("reply_cooldown_seconds", 120)
    sc.setdefault("ppt_auto_generate", False)
    sc.setdefault("ppt_theme", "claude")
    sc.setdefault("video_trigger_enabled", True)
    sc.setdefault("custom_prompt", "")
    # 新增：ASR/视觉/评论模式等正常刷视频的选项
    sc.setdefault("asr_enabled", config.get("asr", {}).get("enabled", False))
    sc.setdefault("asr_backend", config.get("asr", {}).get("backend", "funasr"))
    sc.setdefault("vision_enabled", config.get("vision", {}).get("cover_vision_enabled", True))
    sc.setdefault("comment_mode", "real")  # real/simulated
    sc.setdefault("comment_fetch_enabled", True)  # 是否获取评论区
    sc.setdefault("summary_style", "structured")  # structured/concise/chatty
    sc.setdefault("summary_max_length", 500)
    sc.setdefault("monitor_own_videos_only", False)  # 只监控自己视频的评论
    sc.setdefault("notification_mode", True)  # 通知模式：通过B站@我通知检测

    while True:
        enabled_text = f"{Fore.GREEN}✓ 已启用{Style.RESET_ALL}" if sc.get("enabled") else f"{Fore.RED}✗ 已禁用{Style.RESET_ALL}"
        at_text = f"{Fore.GREEN}✓{Style.RESET_ALL}" if sc.get("at_trigger_enabled") else f"{Fore.RED}✗{Style.RESET_ALL}"
        video_text = f"{Fore.GREEN}✓{Style.RESET_ALL}" if sc.get("video_trigger_enabled") else f"{Fore.RED}✗{Style.RESET_ALL}"
        reply_text = f"{Fore.GREEN}✓{Style.RESET_ALL}" if sc.get("auto_reply") else f"{Fore.RED}✗{Style.RESET_ALL}"
        asr_text = f"{Fore.GREEN}✓{Style.RESET_ALL}" if sc.get("asr_enabled") else f"{Fore.RED}✗{Style.RESET_ALL}"
        vision_text = f"{Fore.GREEN}✓{Style.RESET_ALL}" if sc.get("vision_enabled") else f"{Fore.RED}✗{Style.RESET_ALL}"
        ppt_text = f"{Fore.GREEN}✓{Style.RESET_ALL}" if sc.get("ppt_auto_generate") else f"{Fore.RED}✗{Style.RESET_ALL}"

        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║         🛋️  待机模式设置 (Standby Configuration)          ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}📊 统计: 已处理 {st.get('comments_processed',0)} 条评论
               @总结回复 {st.get('at_replies',0)} 次 | PPT生成 {st.get('ppt_generated',0)} 次
               错误 {st.get('errors',0)} 次{Style.RESET_ALL}

    {Fore.CYAN}▶ 基础开关:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} {'关闭' if sc.get('enabled') else '开启'}待机模式总开关 → {enabled_text}
    {Fore.GREEN}2.{Style.RESET_ALL} {'关闭' if sc.get('auto_reply') else '开启'}自动回复 → {reply_text}

    {Fore.CYAN}▶ @触发总结:{Style.RESET_ALL}
    {Fore.YELLOW}3.{Style.RESET_ALL} {'关闭' if sc.get('at_trigger_enabled') else '开启'}评论区@触发 → {at_text}
    {Fore.YELLOW}4.{Style.RESET_ALL} 修改触发关键词 (当前: {', '.join(sc.get('at_trigger_keywords',[]))})

    {Fore.CYAN}▶ 视频触发 + 总结:{Style.RESET_ALL}
    {Fore.MAGENTA}5.{Style.RESET_ALL} {'关闭' if sc.get('video_trigger_enabled') else '开启'}看视频时触发总结 → {video_text}
    {Fore.MAGENTA}6.{Style.RESET_ALL} 总结风格 (当前: {sc.get('summary_style','structured')})
    {Fore.MAGENTA}7.{Style.RESET_ALL} 总结最大字数 (当前: {sc.get('summary_max_length',500)})
    {Fore.MAGENTA}8.{Style.RESET_ALL} 自定义提示词 ({'已设置' if sc.get('custom_prompt') else '未设置'})

    {Fore.CYAN}▶ 评论/内容获取:{Style.RESET_ALL}
    {Fore.LIGHTBLUE_EX}9.{Style.RESET_ALL}  {'关闭' if sc.get('comment_fetch_enabled') else '开启'}获取评论区 → {Fore.GREEN + '✓' if sc.get('comment_fetch_enabled') else Fore.RED + '✗'}{Style.RESET_ALL}
    {Fore.LIGHTBLUE_EX}10.{Style.RESET_ALL} 评论检查间隔 (当前: {sc.get('comment_check_interval',60)}秒)
    {Fore.LIGHTBLUE_EX}11.{Style.RESET_ALL} 每次最大回复数 (当前: {sc.get('max_replies_per_check',3)})
    {Fore.LIGHTBLUE_EX}12.{Style.RESET_ALL} 回复冷却时间 (当前: {sc.get('reply_cooldown_seconds',120)}秒)

    {Fore.CYAN}▶ ASR + 视觉:{Style.RESET_ALL}
    {Fore.LIGHTCYAN_EX}13.{Style.RESET_ALL} {'关闭' if sc.get('asr_enabled') else '开启'}ASR语音识别 → {asr_text}
    {Fore.LIGHTCYAN_EX}14.{Style.RESET_ALL} ASR引擎 (当前: {sc.get('asr_backend','funasr')}) {'[继承主配置]' if sc.get('asr_backend') == config.get('asr',{}).get('backend') else ''}
    {Fore.LIGHTCYAN_EX}15.{Style.RESET_ALL} {'关闭' if sc.get('vision_enabled') else '开启'}封面视觉分析 → {vision_text}

    {Fore.CYAN}▶ PPT自动生成:{Style.RESET_ALL}
    {Fore.LIGHTMAGENTA_EX}16.{Style.RESET_ALL} {'关闭' if sc.get('ppt_auto_generate') else '开启'}自动生成PPT → {ppt_text}
    {Fore.LIGHTMAGENTA_EX}17.{Style.RESET_ALL} PPT主题 (当前: {sc.get('ppt_theme','claude')})

    {Fore.CYAN}▶ 数据管理:{Style.RESET_ALL}
    {Fore.YELLOW}V.{Style.RESET_ALL} [STATS] 查看待机统计数据
    {Fore.YELLOW}S.{Style.RESET_ALL} 💾 保存配置到文件
    {Fore.RED}R.{Style.RESET_ALL} 🔄 恢复待机默认配置
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-17/V/S/R): {Style.RESET_ALL}").strip()

        if choice == "0":
            break
        elif choice == "1":
            sc["enabled"] = not sc.get("enabled", True)
            print(f"{Fore.GREEN}[OK] 待机模式总开关已{'开启' if sc['enabled'] else '关闭'}{Style.RESET_ALL}")
        elif choice == "2":
            sc["auto_reply"] = not sc.get("auto_reply", True)
            print(f"{Fore.GREEN}[OK] 自动回复已{'开启' if sc['auto_reply'] else '关闭'}{Style.RESET_ALL}")
        elif choice == "3":
            sc["at_trigger_enabled"] = not sc.get("at_trigger_enabled", True)
            print(f"{Fore.GREEN}[OK] @触发总结已{'开启' if sc['at_trigger_enabled'] else '关闭'}{Style.RESET_ALL}")
        elif choice == "4":
            cur_kw = ", ".join(sc.get("at_trigger_keywords", []))
            print(f"{Fore.CYAN}当前触发关键词: {cur_kw}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}输入新关键词（逗号分隔，如: 总结,分析,概括,讲解）: {Style.RESET_ALL}")
            new_kw = input().strip()
            if new_kw:
                sc["at_trigger_keywords"] = [k.strip() for k in new_kw.split(",") if k.strip()]
                print(f"{Fore.GREEN}[OK] 已更新: {', '.join(sc['at_trigger_keywords'])}{Style.RESET_ALL}")
        elif choice == "5":
            sc["video_trigger_enabled"] = not sc.get("video_trigger_enabled", True)
            print(f"{Fore.GREEN}[OK] 视频触发总结已{'开启' if sc['video_trigger_enabled'] else '关闭'}{Style.RESET_ALL}")
        elif choice == "6":
            styles = {"1": "structured", "2": "concise", "3": "chatty"}
            print(f"{Fore.CYAN}总结风格:{Style.RESET_ALL}")
            print(f"  1. 结构化 (分段+标题+要点)")
            print(f"  2. 简洁 (简短精炼)")
            print(f"  3. 闲聊式 (自然像朋友聊天)")
            s = input(f"{Fore.YELLOW}选择 (1-3, 回车保持): {Style.RESET_ALL}").strip()
            if s in styles:
                sc["summary_style"] = styles[s]
                print(f"{Fore.GREEN}[OK] 总结风格已设为: {styles[s]}{Style.RESET_ALL}")
        elif choice == "7":
            raw = input(f"{Fore.YELLOW}总结最大字数 (100-2000, 当前{sc.get('summary_max_length',500)}): {Style.RESET_ALL}").strip()
            if raw:
                try:
                    v = max(100, min(2000, int(raw)))
                    sc["summary_max_length"] = v
                    print(f"{Fore.GREEN}[OK] 已更新: {v}字{Style.RESET_ALL}")
                except ValueError:
                    print(f"{Fore.RED}[ERROR] 无效数字{Style.RESET_ALL}")
        elif choice == "8":
            cur = sc.get("custom_prompt", "")
            print(f"{Fore.CYAN}当前自定义提示词: {cur if cur else '(未设置)'}{Style.RESET_ALL}")
            new_p = input(f"{Fore.YELLOW}输入新提示词 (回车清除, q取消): {Style.RESET_ALL}").strip()
            if new_p and new_p.lower() != 'q':
                sc["custom_prompt"] = new_p
                print(f"{Fore.GREEN}[OK] 已更新{Style.RESET_ALL}")
            elif new_p != 'q':
                sc["custom_prompt"] = ""
                print(f"{Fore.GREEN}[OK] 已清除{Style.RESET_ALL}")
        elif choice == "9":
            sc["comment_fetch_enabled"] = not sc.get("comment_fetch_enabled", True)
            print(f"{Fore.GREEN}[OK] 评论获取已{'开启' if sc['comment_fetch_enabled'] else '关闭'}{Style.RESET_ALL}")
        elif choice == "10":
            try:
                v = int(input(f"{Fore.YELLOW}评论检查间隔秒数 (30-600): {Style.RESET_ALL}").strip())
                if 30 <= v <= 600:
                    sc["comment_check_interval"] = v
                    print(f"{Fore.GREEN}[OK] 已更新: {v}秒{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}[ERROR] 无效输入{Style.RESET_ALL}")
        elif choice == "11":
            try:
                v = int(input(f"{Fore.YELLOW}每次最大回复数 (1-10): {Style.RESET_ALL}").strip())
                if 1 <= v <= 10:
                    sc["max_replies_per_check"] = v
                    print(f"{Fore.GREEN}[OK] 已更新: {v}{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}[ERROR] 无效输入{Style.RESET_ALL}")
        elif choice == "12":
            try:
                v = int(input(f"{Fore.YELLOW}回复冷却秒数 (30-3600): {Style.RESET_ALL}").strip())
                if 30 <= v <= 3600:
                    sc["reply_cooldown_seconds"] = v
                    print(f"{Fore.GREEN}[OK] 已更新: {v}秒{Style.RESET_ALL}")
            except ValueError:
                print(f"{Fore.RED}[ERROR] 无效输入{Style.RESET_ALL}")
        elif choice == "13":
            sc["asr_enabled"] = not sc.get("asr_enabled", False)
            print(f"{Fore.GREEN}[OK] ASR语音识别已{'开启' if sc['asr_enabled'] else '关闭'}{Style.RESET_ALL}")
        elif choice == "14":
            print(f"{Fore.CYAN}ASR引擎:{Style.RESET_ALL}")
            print(f"  1. funasr (Paraformer, 中文最优, 需GPU)")
            print(f"  2. whisper (多语言通用, 较慢)")
            s = input(f"{Fore.YELLOW}选择 (1-2, 回车保持): {Style.RESET_ALL}").strip()
            if s == "1":
                sc["asr_backend"] = "funasr"
            elif s == "2":
                sc["asr_backend"] = "whisper"
            if s in ("1", "2"):
                print(f"{Fore.GREEN}[OK] 已更新: {sc['asr_backend']}{Style.RESET_ALL}")
        elif choice == "15":
            sc["vision_enabled"] = not sc.get("vision_enabled", True)
            print(f"{Fore.GREEN}[OK] 封面视觉分析已{'开启' if sc['vision_enabled'] else '关闭'}{Style.RESET_ALL}")
        elif choice == "16":
            sc["ppt_auto_generate"] = not sc.get("ppt_auto_generate", False)
            print(f"{Fore.GREEN}[OK] PPT自动生成已{'开启' if sc['ppt_auto_generate'] else '关闭'}{Style.RESET_ALL}")
        elif choice == "17":
            from services.video_to_ppt import THEMES
            print(f"{Fore.CYAN}可用PPT主题:{Style.RESET_ALL}")
            for i, (k, v) in enumerate(THEMES.items(), 1):
                sel = " ← 当前" if k == sc.get("ppt_theme") else ""
                print(f"  {i}. {v['name']} ({k}){sel}")
            s = input(f"{Fore.YELLOW}输入主题ID (如 claude/dark/purple/cyan): {Style.RESET_ALL}").strip().lower()
            if s in THEMES:
                sc["ppt_theme"] = s
                print(f"{Fore.GREEN}[OK] 已更新: {s}{Style.RESET_ALL}")
            elif s:
                print(f"{Fore.RED}[ERROR] 未知主题: {s}{Style.RESET_ALL}")
        elif choice.upper() == "V":
            print(f"\n{Fore.CYAN}── 待机模式统计数据 ──{Style.RESET_ALL}")
            print(f"  已处理评论: {st.get('comments_processed', 0)}")
            print(f"  @总结回复: {st.get('at_replies', 0)}")
            print(f"  PPT生成: {st.get('ppt_generated', 0)}")
            print(f"  错误次数: {st.get('errors', 0)}")
            print()
            input(f"{Fore.CYAN}按回车返回...{Style.RESET_ALL}")
        elif choice.upper() == "S":
            if save_standby_config(sc):
                print(f"{Fore.GREEN}[OK] 待机配置已保存到 Data/standby_config.json{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] 保存失败{Style.RESET_ALL}")
        elif choice.upper() == "R":
            conf = input(f"{Fore.RED}确认恢复待机默认配置？(y/N): {Style.RESET_ALL}").strip().lower()
            if conf == "y":
                sc = load_standby_config()
                try:
                    standby_file = os.path.join(DATA_DIR, "standby_config.json")
                    if os.path.exists(standby_file):
                        os.remove(standby_file)
                    print(f"{Fore.GREEN}[OK] 已恢复默认配置（重启后生效）{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}[ERROR] 恢复失败: {e}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")

    # 退出时自动保存
    save_standby_config(sc)


def _reload_all_globals(new_config: dict):
    """重置后尝试更新运行时全局变量。由于变量名与模块级定义可能不同，
    部分变量通过 config 引用，真正生效需要重启。这里做 best-effort 更新。"""
    global UNIFIED_API_KEY, UNIFIED_BASE_URL, MODEL_BRAIN, MODEL_VISION, VISION_COVER_ENABLED
    global VISION_API_KEY, VISION_BASE_URL
    global AI_MARKER, SUBTITLE_STRICT_CHECK
    global COIN_THRESHOLD, FAV_THRESHOLD, INTEREST_THRESHOLD, MAX_COINS_DAILY, MAX_ENERGY
    global PROB_REPLY_TRIGGER, PROB_COIN, PROB_FAV, PROB_LIKE_SOLO, PROB_COMMENT_OTHERS
    global COMMENT_CHECK_ENABLED, COMMENT_CHECK_INTERVAL, MAX_REPLIES_PER_CHECK, RANDOM_ENABLED
    global ENERGY_RECOVERY_MIN, ENERGY_RECOVERY_MAX, ROUNDS_MIN, ROUNDS_MAX
    global ROUND_INTERVAL_MIN, ROUND_INTERVAL_MAX, VIDEO_INTERVAL_MIN, VIDEO_INTERVAL_MAX
    global VIDEO_UNDERSTANDING_MODE, VIDEO_MAX_DURATION_SECONDS, VIDEO_FRAME_COUNT
    global VIDEO_DOWNLOAD_INTEREST_THRESHOLD, VIDEO_DOWNLOAD_DIR
    global VIDEO_DELETE_AFTER_UNDERSTAND, VIDEO_FILTER_MODE
    global VISION_FRAMES_ENABLED, VISION_COMMENT_IMAGES_ENABLED, VISION_MAX_COMMENT_IMAGES, VISION_FRAME_COUNT
    global ASR_ENABLED, ASR_BACKEND, ASR_WHISPER_MODEL, ASR_LANGUAGE, ASR_SPEAKER_SEPARATION
    global ASR_MAX_AUDIO_DURATION, ASR_MIN_CONFIDENCE, ASR_SKIP_MUSIC, ASR_KEEP_AUDIO
    global ASR_FFMPEG_PATH, ASR_DEVICE
    global ASR_FUNASR_MODEL_DIR, ASR_FUNASR_VAD_ENABLED, ASR_FUNASR_PUNC_ENABLED
    global ASR_FUNASR_SPK_ENABLED, ASR_FUNASR_BATCH_SIZE_S, ASR_FUNASR_HOTWORD
    global PRIVATE_MESSAGE_ENABLED, PRIVATE_MESSAGE_AUTO_REPLY, PRIVATE_MESSAGE_CHECK_INTERVAL
    global PRIVATE_MESSAGE_MAX_REPLIES, PRIVATE_MESSAGE_ONLY_RECENT_SECONDS
    global COOLDOWN_STARTUP_MIN, COOLDOWN_STARTUP_MAX, NO_HUMAN_DELAY
    global COOLDOWN_POST_COMMENT_MIN, COOLDOWN_POST_COMMENT_MAX
    global COOLDOWN_POST_DM_MIN, COOLDOWN_POST_DM_MAX
    global REPLY_SAFETY_ENABLED, REPLY_SAFETY_BLOCK_ON_INCOMING, REPLY_SAFETY_BLOCK_ON_OUTGOING
    global REPLY_SAFETY_BLOCK_POLITICAL_VIDEO_COMMENTS, REPLY_SAFETY_BLOCKED_KEYWORDS
    global DIARY_ENABLED, DIARY_AUTO_ENABLED, DIARY_AUTO_INTERVAL_MINUTES, DIARY_MIN_EVENTS_FOR_AUTO
    global EVOLUTION_ENABLED, EVOLUTION_AUTO_ENABLED
    global EVOLUTION_REFLECT_INTERVAL_EVENTS, EVOLUTION_MIN_EVENTS_FOR_REFLECT, EVOLUTION_AUTO_APPLY
    global AGENT_ENABLED, AGENT_AUTO_ENABLED, AGENT_DIVE_ENABLED
    global AGENT_MAX_STEPS_PER_PLAN, AGENT_MAX_SEARCH_RESULTS, AGENT_MAX_VIDEOS_PER_PLAN
    global AGENT_DIVE_MAX_VIDEOS, AGENT_AUTO_MIN_SCORE, AGENT_COOLDOWN_MINUTES
    global BEHAVIOR_PRIVATE_REPLY_COOLDOWN_MINUTES, BEHAVIOR_COMMENT_USER_COOLDOWN_MINUTES
    global BEHAVIOR_MAX_CONSECUTIVE_AI_REPLIES
    global BEHAVIOR_MIN_REPLY_DELAY_SECONDS, BEHAVIOR_MAX_REPLY_DELAY_SECONDS
    global BEHAVIOR_PREFER_SHORT_REPLIES, COMMENT_MODE
    global SESSION_MAX_VIDEOS, SESSION_MAX_DURATION_MINUTES
    global REVISIT_ENABLED, PROB_REVISIT, REVISIT_COOLDOWN_MINUTES
    global REVISIT_MIN_SCORE, REVISIT_MAX_PER_VIDEO, REVISIT_PER_VIDEO_COOLDOWN_MINUTES
    global KNOWLEDGE_VERIFY_ENABLED, KNOWLEDGE_VERIFY_USE_WEB, KNOWLEDGE_VERIFY_MIN_SCORE, KNOWLEDGE_VERIFY_AUTO_FIX
    global CURIOSITY_DEEP_DIVE_ENABLED, CURIOSITY_DEEP_DIVE_MAX_VIDEOS, CURIOSITY_DEEP_DIVE_MIN_SCORE
    global CURIOSITY_DEEP_DIVE_PROB, CURIOSITY_DEEP_DIVE_COOLDOWN_MINUTES
    global CURIOSITY_DEEP_DIVE_DEFAULT_VIDEOS, CURIOSITY_DEEP_DIVE_MID_VIDEOS, CURIOSITY_DEEP_DIVE_HIGH_VIDEOS
    global DRY_GOODS_ENABLED, DRY_GOODS_MIN_SCORE, DRY_GOODS_FOLDER_NAME
    global ACTIVE_CHAT_ENABLED, PROB_INITIATE_CHAT, ACTIVE_CHAT_COOLDOWN_MINUTES, ACTIVE_CHAT_MAX_PER_SESSION
    # Entertainment globals are commented out in source, skip
    global UP_FOLLOW_ENABLED, UP_FOLLOW_AUTO_PROB, UP_FOLLOW_MAX_DAILY, UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS
    global UP_FOLLOW_BROWSE_PROB, UP_FOLLOW_MAX_BROWSE, UP_FOLLOW_COOLDOWN_MINUTES
    global UP_FOLLOW_FAVORITE_PROB, UP_FOLLOW_FAVORITE_UID_LIST, UP_FOLLOW_TEST_MODE
    global UP_FOLLOW_MIN_SCORE, UP_FOLLOW_MIN_IMPRESSIONS, UP_FOLLOW_EXCEPTIONAL_SCORE
    global DANMAKU_ENABLED, DANMAKU_READ_PROB, DANMAKU_LIKE_PROB
    global DANMAKU_MAX_DAILY_LIKES, DANMAKU_SEND_PROB, DANMAKU_MAX_DAILY_SEND
    global PSYCHO_ENGINE_ENABLED, PSYCHO_DEEP_ANALYZE_INTERVAL, PSYCHO_HEURISTIC_UPDATE_INTERVAL
    global PSYCHO_COCOON_DETECT_INTERVAL, PSYCHO_COCOON_WARNING_THRESHOLD
    global PSYCHO_RECOMMEND_PROB, PSYCHO_MIN_VIEWS_BEFORE_RECOMMEND
    global PSYCHO_MAX_SURPRISE_DAILY, PSYCHO_MAX_EXPLORE_DAILY, PSYCHO_MAX_ANTICOCOON_DAILY
    global PSYCHO_MIN_ACTIONS_FOR_DEEP, PSYCHO_DEEP_COOLDOWN, PSYCHO_MAX_ACTIONS_LOG
    global PSYCHO_MAX_RECOMMENDATION_LOG, PSYCHO_AVERSION_BLACKLIST_THRESHOLD
    global PSYCHO_AVERSION_BLOCK_SCORE, PSYCHO_AVERSION_WARN_SCORE
    global MOOD_RANDOM_ENABLED, MOOD_RANDOM_INTERVAL_MINUTES, MOOD_CUSTOM_ENABLED, MOOD_CUSTOM_VALUE
    global FALLBACK_MODELS, FALLBACK_MODEL_CHAT, FALLBACK_MODEL_VISION, FALLBACK_MODEL_FAST
    global FALLBACK_PROVIDER_ENABLED, FALLBACK_PROVIDER_NAME, FALLBACK_PROVIDER_API_KEY
    global FALLBACK_PROVIDER_BASE_URL, FALLBACK_PROVIDER_MODELS
    global AUTO_RECLASSIFY_ENABLED, AUTO_RECLASSIFY_INTERVAL_MINUTES, AUTO_RECLASSIFY_CLEAN_EMPTY

    api = new_config.get("api", {})
    UNIFIED_API_KEY = api.get("unified_api_key", "")
    UNIFIED_BASE_URL = api.get("unified_base_url", "")
    MODEL_BRAIN = api.get("model_brain", "")
    MODEL_VISION = api.get("model_vision", "")
    VISION_API_KEY = api.get("vision_api_key", "") or UNIFIED_API_KEY
    VISION_BASE_URL = api.get("vision_base_url", "") or UNIFIED_BASE_URL

    # 🔧 同步更新 core.config 和 core.globals 中的模块级变量
    try:
        import core.config as _cfg
        import core.globals as _glo
        _cfg.UNIFIED_API_KEY = UNIFIED_API_KEY
        _cfg.UNIFIED_BASE_URL = UNIFIED_BASE_URL
        _cfg.MODEL_BRAIN = MODEL_BRAIN
        _cfg.MODEL_VISION = MODEL_VISION
        # 🔧 同步 config dict (xingye_bot 从此读取)
        _cfg.config["api"]["unified_api_key"] = UNIFIED_API_KEY
        _cfg.config["api"]["unified_base_url"] = UNIFIED_BASE_URL
        _cfg.config["api"]["model_brain"] = MODEL_BRAIN
        _cfg.config["api"]["model_vision"] = MODEL_VISION
        _glo.UNIFIED_API_KEY = UNIFIED_API_KEY
        _glo.UNIFIED_BASE_URL = UNIFIED_BASE_URL
        _glo.MODEL_BRAIN = MODEL_BRAIN
        _glo.MODEL_VISION = MODEL_VISION
        _glo.VIDEO_INTERVAL_MIN = VIDEO_INTERVAL_MIN
        _glo.VIDEO_INTERVAL_MAX = VIDEO_INTERVAL_MAX
    except Exception:
        pass

    # fallback models (same-provider model-level fallback)
    fm = new_config.get("fallback_models", {})
    FALLBACK_MODELS = fm
    FALLBACK_MODEL_CHAT = fm.get("chat", "")
    FALLBACK_MODEL_VISION = fm.get("vision", "")
    FALLBACK_MODEL_FAST = fm.get("fast", "")

    # fallback provider (cross-provider fallback)
    fbp = new_config.get("fallback_provider", {})
    FALLBACK_PROVIDER_ENABLED = fbp.get("enabled", False)
    FALLBACK_PROVIDER_NAME = fbp.get("name", "chatanywhere")
    FALLBACK_PROVIDER_API_KEY = fbp.get("api_key", "") or os.getenv("BILI_AI_FALLBACK_API_KEY", "")
    FALLBACK_PROVIDER_BASE_URL = fbp.get("base_url", "") or os.getenv("BILI_AI_FALLBACK_BASE_URL", "")
    FALLBACK_PROVIDER_MODELS = fbp.get("models", {})

    inter = new_config.get("interaction", {})
    COIN_THRESHOLD = inter.get("coin_threshold", 9.5)
    FAV_THRESHOLD = inter.get("fav_threshold", 8.5)
    INTEREST_THRESHOLD = inter.get("interest_threshold", 6.5)
    LEARN_MIN_SCORE = inter.get("learn_min_score", 6.0)
    LEARN_MIN_DURATION_SECONDS = inter.get("learn_min_duration_seconds", 60)
    MAX_COINS_DAILY = inter.get("max_coins_daily", 2)
    MAX_ENERGY = inter.get("max_energy", 100)
    PROB_REPLY_TRIGGER = inter.get("prob_reply_trigger", 0.15)
    PROB_COIN = inter.get("prob_coin", 0.1)
    PROB_FAV = inter.get("prob_fav", 0.8)
    PROB_LIKE_SOLO = inter.get("prob_like_solo", 0.5)
    PROB_COMMENT_OTHERS = inter.get("prob_comment_others", 0.3)
    COMMENT_CHECK_ENABLED = inter.get("comment_check_enabled", True)
    COMMENT_CHECK_INTERVAL = inter.get("comment_check_interval", 300)
    MAX_REPLIES_PER_CHECK = inter.get("max_replies_per_check", 3)
    RANDOM_ENABLED = inter.get("random_enabled", True)

    ene = new_config.get("energy", {})
    ENERGY_RECOVERY_MIN = ene.get("energy_recovery_min", 5)
    ENERGY_RECOVERY_MAX = ene.get("energy_recovery_max", 10)
    ROUNDS_MIN = ene.get("rounds_min", 3)
    ROUNDS_MAX = ene.get("rounds_max", 10)
    ROUND_INTERVAL_MIN = ene.get("round_interval_min", 60)
    ROUND_INTERVAL_MAX = ene.get("round_interval_max", 180)
    VIDEO_INTERVAL_MIN = ene.get("video_interval_min", 1)
    VIDEO_INTERVAL_MAX = ene.get("video_interval_max", 5)

    vid = new_config.get("video", {})
    VIDEO_UNDERSTANDING_MODE = vid.get("mode", "smart")
    VIDEO_MAX_DURATION_SECONDS = vid.get("max_duration_seconds", 900)
    VIDEO_FRAME_COUNT = vid.get("frame_count", 12)
    VIDEO_DOWNLOAD_INTEREST_THRESHOLD = vid.get("download_interest_threshold", 7.0)
    VIDEO_DOWNLOAD_DIR = vid.get("download_dir", "")
    VIDEO_DELETE_AFTER_UNDERSTAND = vid.get("delete_video_after_understand", True)
    VIDEO_FILTER_MODE = vid.get("filter_mode", "cover_and_title")

    vis = new_config.get("vision", {})
    VISION_COVER_ENABLED = vis.get("cover_enabled", True)
    VISION_FRAMES_ENABLED = vis.get("frames_enabled", True)
    VISION_COMMENT_IMAGES_ENABLED = vis.get("comment_images_enabled", True)
    VISION_MAX_COMMENT_IMAGES = vis.get("max_comment_images", 5)
    VISION_FRAME_COUNT = vis.get("frame_count", 8)
    SMART_FRAME_ENABLED = vis.get("smart_frame_enabled", True)
    SMART_FRAME_MIN = vis.get("smart_frame_min", 10)
    SMART_FRAME_MAX = vis.get("smart_frame_max", 60)

    asr_cfg = new_config.get("asr", {})
    ASR_ENABLED = asr_cfg.get("enabled", False)
    ASR_BACKEND = asr_cfg.get("backend", "funasr")
    ASR_WHISPER_MODEL = asr_cfg.get("whisper_model", "base")
    ASR_LANGUAGE = asr_cfg.get("language", "zh")
    ASR_SPEAKER_SEPARATION = asr_cfg.get("speaker_separation", True)
    ASR_MAX_AUDIO_DURATION = asr_cfg.get("max_audio_duration", 3600)
    ASR_MIN_CONFIDENCE = asr_cfg.get("min_confidence", 0.5)
    ASR_SKIP_MUSIC = asr_cfg.get("skip_music", True)
    ASR_KEEP_AUDIO = asr_cfg.get("keep_audio", False)
    ASR_FFMPEG_PATH = asr_cfg.get("ffmpeg_path", "")
    ASR_DEVICE = asr_cfg.get("device", "cpu")
    ASR_FUNASR_MODEL_DIR = asr_cfg.get("funasr_model_dir", "")
    ASR_FUNASR_VAD_ENABLED = asr_cfg.get("funasr_vad_enabled", True)
    ASR_FUNASR_PUNC_ENABLED = asr_cfg.get("funasr_punc_enabled", True)
    ASR_FUNASR_SPK_ENABLED = asr_cfg.get("funasr_spk_enabled", False)
    ASR_FUNASR_BATCH_SIZE_S = asr_cfg.get("funasr_batch_size_s", 300)
    ASR_FUNASR_HOTWORD = asr_cfg.get("funasr_hotword", "")

    pm = new_config.get("private_message", {})
    PRIVATE_MESSAGE_ENABLED = pm.get("enabled", True)
    PRIVATE_MESSAGE_AUTO_REPLY = pm.get("auto_reply", False)
    PRIVATE_MESSAGE_CHECK_INTERVAL = pm.get("check_interval", 120)
    PRIVATE_MESSAGE_MAX_REPLIES = pm.get("max_replies_per_check", 3)
    PRIVATE_MESSAGE_ONLY_RECENT_SECONDS = pm.get("only_recent_seconds", 900)

    cd = new_config.get("cooldown", {})
    COOLDOWN_STARTUP_MIN = cd.get("startup_cooldown_min", 5)
    COOLDOWN_STARTUP_MAX = cd.get("startup_cooldown_max", 10)
    COOLDOWN_POST_COMMENT_MIN = cd.get("post_comment_cooldown_min", 3)
    COOLDOWN_POST_COMMENT_MAX = cd.get("post_comment_cooldown_max", 8)
    COOLDOWN_POST_DM_MIN = cd.get("post_dm_cooldown_min", 3)
    COOLDOWN_POST_DM_MAX = cd.get("post_dm_cooldown_max", 8)

    rs = new_config.get("reply_safety", {})
    REPLY_SAFETY_ENABLED = rs.get("enabled", True)
    REPLY_SAFETY_BLOCK_ON_INCOMING = rs.get("block_on_incoming", True)
    REPLY_SAFETY_BLOCK_ON_OUTGOING = rs.get("block_on_outgoing", True)
    REPLY_SAFETY_BLOCK_POLITICAL_VIDEO_COMMENTS = rs.get("block_political_video_comments", True)
    REPLY_SAFETY_BLOCKED_KEYWORDS = rs.get("blocked_keywords", DEFAULT_CONFIG["reply_safety"]["blocked_keywords"])

    diary_cfg = new_config.get("diary", {})
    DIARY_ENABLED = diary_cfg.get("enabled", True)
    DIARY_AUTO_ENABLED = diary_cfg.get("auto_enabled", True)
    DIARY_AUTO_INTERVAL_MINUTES = diary_cfg.get("auto_interval_minutes", 60)
    DIARY_MIN_EVENTS_FOR_AUTO = diary_cfg.get("min_events_for_auto", 3)

    evo = new_config.get("self_evolution", {})
    EVOLUTION_ENABLED = evo.get("enabled", True)
    EVOLUTION_AUTO_ENABLED = evo.get("auto_enabled", True)
    EVOLUTION_REFLECT_INTERVAL_EVENTS = evo.get("reflect_interval_events", 8)
    EVOLUTION_MIN_EVENTS_FOR_REFLECT = evo.get("min_events_for_reflect", 3)
    EVOLUTION_AUTO_APPLY = evo.get("auto_apply", True)

    ag = new_config.get("agent", {})
    AGENT_ENABLED = ag.get("enabled", True)
    AGENT_AUTO_ENABLED = ag.get("auto_enabled", False)
    AGENT_DIVE_ENABLED = ag.get("dive_enabled", True)
    AGENT_MAX_STEPS_PER_PLAN = ag.get("max_steps_per_plan", 5)
    AGENT_MAX_SEARCH_RESULTS = ag.get("max_search_results", 8)
    AGENT_MAX_VIDEOS_PER_PLAN = ag.get("max_videos_per_plan", 3)
    AGENT_DIVE_MAX_VIDEOS = ag.get("dive_max_videos", 10)
    AGENT_AUTO_MIN_SCORE = ag.get("auto_min_score", 8.5)
    AGENT_COOLDOWN_MINUTES = ag.get("cooldown_minutes", 60)

    bh = new_config.get("behavior", {})
    BEHAVIOR_PRIVATE_REPLY_COOLDOWN_MINUTES = bh.get("private_reply_cooldown_minutes", 3)
    BEHAVIOR_COMMENT_USER_COOLDOWN_MINUTES = bh.get("comment_user_cooldown_minutes", 60)
    BEHAVIOR_MAX_CONSECUTIVE_AI_REPLIES = bh.get("max_consecutive_ai_replies", 3)
    BEHAVIOR_MIN_REPLY_DELAY_SECONDS = bh.get("min_reply_delay_seconds", 4)
    BEHAVIOR_MAX_REPLY_DELAY_SECONDS = bh.get("max_reply_delay_seconds", 18)
    BEHAVIOR_PREFER_SHORT_REPLIES = bh.get("prefer_short_replies", True)
    COMMENT_MODE = bh.get("comment_mode", "real")

    sess = new_config.get("session", {})
    SESSION_MAX_VIDEOS = sess.get("max_videos", 0)
    SESSION_MAX_DURATION_MINUTES = sess.get("max_duration_minutes", 0)

    rev = new_config.get("revisit", {})
    REVISIT_ENABLED = rev.get("enabled", True)
    PROB_REVISIT = rev.get("prob_revisit", 0.25)
    REVISIT_COOLDOWN_MINUTES = rev.get("revisit_cooldown_minutes", 15)
    REVISIT_MIN_SCORE = rev.get("min_score", 7.5)
    REVISIT_MAX_PER_VIDEO = rev.get("max_per_video", 2)
    REVISIT_PER_VIDEO_COOLDOWN_MINUTES = rev.get("per_video_cooldown_minutes", 240)

    kv = new_config.get("knowledge_verify", {})
    KNOWLEDGE_VERIFY_ENABLED = kv.get("enabled", True)
    KNOWLEDGE_VERIFY_USE_WEB = kv.get("use_web_search", True)
    KNOWLEDGE_VERIFY_MIN_SCORE = kv.get("min_reliability_score", 0.7)
    KNOWLEDGE_VERIFY_AUTO_FIX = kv.get("auto_fix", True)

    cs = new_config.get("curiosity_search", {})
    CURIOSITY_DEEP_DIVE_ENABLED = cs.get("enabled", True)
    CURIOSITY_DEEP_DIVE_MAX_VIDEOS = cs.get("max_videos_per_dive", 10)
    CURIOSITY_DEEP_DIVE_DEFAULT_VIDEOS = cs.get("dive_videos_default", 3)
    CURIOSITY_DEEP_DIVE_MID_VIDEOS = cs.get("dive_videos_mid", 5)
    CURIOSITY_DEEP_DIVE_HIGH_VIDEOS = cs.get("dive_videos_max", 10)
    CURIOSITY_DEEP_DIVE_MIN_SCORE = cs.get("trigger_min_score", 7.5)
    CURIOSITY_DEEP_DIVE_PROB = cs.get("prob_trigger", 0.3)
    CURIOSITY_DEEP_DIVE_COOLDOWN_MINUTES = cs.get("cooldown_minutes", 120)

    dg = new_config.get("dry_goods", {})
    DRY_GOODS_ENABLED = dg.get("enabled", False)
    DRY_GOODS_MIN_SCORE = dg.get("min_score", 7.5)
    DRY_GOODS_FOLDER_NAME = dg.get("folder_name", "highlights")

    # [AI] AI字幕内容验证 & 知识库定期审查
    aiv = new_config.get("ai_subtitle_verify", {})
    AI_SUBTITLE_VERIFY_ENABLED = aiv.get("enabled", True)
    KNOWLEDGE_REVIEW_INTERVAL = aiv.get("knowledge_review_interval", 10)
    KNOWLEDGE_REVIEW_SAMPLE_SIZE = aiv.get("knowledge_review_sample_size", 3)

    ac = new_config.get("active_chat", {})
    ACTIVE_CHAT_ENABLED = ac.get("enabled", True)
    PROB_INITIATE_CHAT = ac.get("prob_initiate", 0.06)
    ACTIVE_CHAT_COOLDOWN_MINUTES = ac.get("cooldown_minutes", 45)
    ACTIVE_CHAT_MAX_PER_SESSION = ac.get("max_initiate_per_session", 3)

    uf = new_config.get("up_follow", {})
    UP_FOLLOW_ENABLED = uf.get("enabled", True)
    UP_FOLLOW_AUTO_PROB = uf.get("auto_follow_prob", 0.08)
    UP_FOLLOW_MAX_DAILY = uf.get("max_daily_follows", 3)
    UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS = uf.get("unfollow_inactive_days", 0)
    UP_FOLLOW_BROWSE_PROB = uf.get("browse_up_videos_prob", 0.06)
    UP_FOLLOW_MAX_BROWSE = uf.get("max_browse_videos", 3)
    UP_FOLLOW_COOLDOWN_MINUTES = uf.get("cooldown_minutes", 90)
    UP_FOLLOW_FAVORITE_PROB = uf.get("favorite_up_browse_prob", 0.25)
    UP_FOLLOW_FAVORITE_UID_LIST = uf.get("favorite_up_uid_list", [])
    UP_FOLLOW_TEST_MODE = uf.get("test_mode", False)
    UP_FOLLOW_MIN_SCORE = uf.get("min_score", 7.0)
    UP_FOLLOW_MIN_IMPRESSIONS = uf.get("min_impressions", 2)
    UP_FOLLOW_EXCEPTIONAL_SCORE = uf.get("exceptional_score", 8.5)

    dm = new_config.get("danmaku", {})
    DANMAKU_ENABLED = dm.get("enabled", True)
    DANMAKU_READ_PROB = dm.get("read_prob", 0.4)
    DANMAKU_LIKE_PROB = dm.get("like_prob", 0.15)
    DANMAKU_MAX_DAILY_LIKES = dm.get("max_daily_danmaku_likes", 10)
    DANMAKU_SEND_PROB = dm.get("send_prob", 0.03)
    DANMAKU_MAX_DAILY_SEND = dm.get("max_daily_send", 2)

    psy = new_config.get("psycho_engine", {})
    PSYCHO_ENGINE_ENABLED = psy.get("enabled", True)
    PSYCHO_DEEP_ANALYZE_INTERVAL = psy.get("deep_analyze_interval_videos", 100)
    PSYCHO_HEURISTIC_UPDATE_INTERVAL = psy.get("heuristic_update_interval", 15)
    PSYCHO_COCOON_DETECT_INTERVAL = psy.get("cocoon_detect_interval", 15)
    PSYCHO_COCOON_WARNING_THRESHOLD = psy.get("cocoon_warning_threshold", 0.35)
    PSYCHO_RECOMMEND_PROB = psy.get("recommend_prob_per_round", 0.08)
    PSYCHO_MIN_VIEWS_BEFORE_RECOMMEND = psy.get("min_views_before_recommend", 10)
    PSYCHO_MAX_SURPRISE_DAILY = psy.get("max_surprise_daily", 5)
    PSYCHO_MAX_EXPLORE_DAILY = psy.get("max_explore_daily", 5)
    PSYCHO_MAX_ANTICOCOON_DAILY = psy.get("max_anticocoon_daily", 3)
    PSYCHO_MIN_ACTIONS_FOR_DEEP = psy.get("min_actions_for_deep_analysis", 50)
    PSYCHO_DEEP_COOLDOWN = psy.get("deep_analysis_cooldown_seconds", 14400)
    PSYCHO_MAX_ACTIONS_LOG = psy.get("max_actions_in_log", 2000)
    PSYCHO_MAX_RECOMMENDATION_LOG = psy.get("max_recommendation_log", 200)
    PSYCHO_AVERSION_BLACKLIST_THRESHOLD = psy.get("aversion_auto_blacklist_threshold", 3)
    PSYCHO_AVERSION_BLOCK_SCORE = psy.get("aversion_score_block_threshold", 0.7)
    PSYCHO_AVERSION_WARN_SCORE = psy.get("aversion_score_warn_threshold", 0.4)

    mood = new_config.get("mood", {})
    MOOD_RANDOM_ENABLED = mood.get("random_enabled", False)
    MOOD_RANDOM_INTERVAL_MINUTES = mood.get("random_interval_minutes", 5)
    MOOD_CUSTOM_ENABLED = mood.get("custom_enabled", False)
    MOOD_CUSTOM_VALUE = mood.get("custom_mood", "")

    kb = new_config.get("knowledge", {})
    AUTO_RECLASSIFY_ENABLED = kb.get("auto_reclassify_enabled", True)
    AUTO_RECLASSIFY_INTERVAL_MINUTES = kb.get("auto_reclassify_interval_minutes", 10)
    AUTO_RECLASSIFY_CLEAN_EMPTY = kb.get("auto_reclassify_clean_empty", True)

    sp = new_config.get("speed", {})
    import api.throttle
    api.throttle._BILI_API_MIN_GAP = float(sp.get("api_min_gap", 0.3))
    NO_HUMAN_DELAY = sp.get("no_human_delay", False)
    try:
        import core.globals as _glo_speed
        _glo_speed.NO_HUMAN_DELAY = NO_HUMAN_DELAY
    except Exception:
        pass

    behavior = new_config.get("behavior", {})
    AI_MARKER = behavior.get("ai_marker", "（内容由AI生成并由AI回复）")

    subtitle_cfg = new_config.get("subtitle_strict_check", {})
    SUBTITLE_STRICT_CHECK = subtitle_cfg.get("enabled", False)

# [bili/auth.py] is_bili_logged_in
# [bili/auth.py] check_login_status
# [knowledge/classifier.py] KnowledgeBaseClassifier
# [knowledge/web_search.py] _fetch_search_page
# [knowledge/web_search.py] _parse_bing_html
# [knowledge/web_search.py] _parse_sogou_html
# [knowledge/web_search.py] web_search
# [knowledge/web_search.py] verify_knowledge_with_ai
# [knowledge/web_search.py] backup_and_rewrite_knowledge
# [brain/video_analysis.py] 视频分析
# [knowledge/revisit.py] 知识重温
# [knowledge/organize.py] 知识整理
