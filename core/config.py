"""core/config.py — 配置加载与路径常量

从 new_agent.py 提取，避免循环依赖。
所有全局配置变量仍然在 new_agent.py 中定义，使用时 from core.config import 路径常量。
"""
import os
import json
from colorama import Fore, Style
from json_utils import get_backup_dir

# ===== 路径常量 =====
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
BOT_LOCK_FILE = os.path.join(DATA_DIR, "bot.lock")
BACKUP_DIR = get_backup_dir()
BACKUP_FILE = os.path.join(BACKUP_DIR, "bilibili_claw_export.json")
COOKIE_FILE = os.path.join(DATA_DIR, "bilibili_cookies.json")
INTERESTS_FILE = os.path.join(DATA_DIR, "interests.json")
COMMENT_LOG_FILE = os.path.join(DATA_DIR, "comment_log.json")
PRIVATE_MESSAGE_LOG_FILE = os.path.join(DATA_DIR, "private_message_log.json")
PRIVATE_CONTEXT_FILE = os.path.join(DATA_DIR, "private_context_db.json")
USER_PROFILES_FILE = os.path.join(DATA_DIR, "user_profiles.json")
PERSONAS_FILE = os.path.join(DATA_DIR, "personas.json")
MOOD_STATE_FILE = os.path.join(DATA_DIR, "mood_state.json")
BOT_DIARY_FILE = os.path.join(DATA_DIR, "bot_diary.json")
SELF_EVOLUTION_FILE = os.path.join(DATA_DIR, "self_evolution.json")
AGENT_SKILL_LOG_FILE = os.path.join(DATA_DIR, "agent_skill_log.json")
RUNTIME_STATE_FILE = os.path.join(DATA_DIR, "bot_runtime_state.json")
KNOWLEDGE_BASE_DIR = os.path.join(BASE_DIR, "KnowledgeBase")
HIGHLIGHTS_DIR = os.path.join(BASE_DIR, "highlights")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)

# ===== 默认配置模板 =====
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
        "coin_threshold": 8.0, "fav_threshold": 8.5, "interest_threshold": 6.5,
        "learn_min_score": 6.0, "learn_min_duration_seconds": 60,
        "max_coins_daily": 2, "max_energy": 100,
        "prob_reply_trigger": 0.15, "prob_coin": 0.25, "prob_fav": 0.8,
        "prob_like_solo": 0.5, "prob_comment_others": 0.3,
        "comment_check_interval": 300, "max_replies_per_check": 3,
        "random_enabled": True
    },
    "energy": {
        "energy_recovery_min": 5, "energy_recovery_max": 10,
        "rounds_min": 3, "rounds_max": 10,
        "round_interval_min": 60, "round_interval_max": 180,
        "video_interval_min": 20, "video_interval_max": 50
    },
    "persona": {"active_persona": "默认人格", "prompt_name": "AI小助手"},
    "mood": {
        "default_mood": "平静", "mood_volatility": 1.0,
        "random_enabled": False, "random_interval_minutes": 5,
        "custom_enabled": False, "custom_mood": ""
    },
    "video": {
        "mode": "smart", "max_duration_seconds": 900, "frame_count": 12,
        "download_interest_threshold": 7.0, "download_dir": "",
        "delete_video_after_understand": True, "filter_mode": "cover_and_title"
    },
    "vision": {
        "frames_enabled": True, "comment_images_enabled": True,
        "max_comment_images": 5, "frame_count": 8
    },
    "asr": {
        "enabled": False, "backend": "funasr", "whisper_model": "base",
        "language": "zh", "speaker_separation": True, "max_audio_duration": 3600,
        "min_confidence": 0.5, "skip_music": True, "keep_audio": False,
        "ffmpeg_path": "", "device": "cpu", "funasr_model_dir": "",
        "funasr_vad_enabled": True, "funasr_punc_enabled": True,
        "funasr_spk_enabled": False, "funasr_batch_size_s": 300, "funasr_hotword": ""
    },
    "private_message": {
        "enabled": True, "auto_reply": True, "check_interval": 120,
        "max_replies_per_check": 3, "only_recent_seconds": 900
    },
    "reply_safety": {
        "enabled": True, "block_on_incoming": True, "block_on_outgoing": True,
        "block_political_video_comments": True,
        "blocked_keywords": [
            "主席", "党", "国家", "政治", "政府", "共产党", "中共", "习近平",
            "毛泽东", "人大", "国务院", "军委", "台湾", "香港", "新疆", "西藏",
            "六四", "法轮", "选举", "民主", "独裁", "宪法", "外交部", "制裁",
            "战争", "俄乌", "以色列", "巴勒斯坦", "日本右翼", "靖国神社",
            "民族主义", "爱国", "辱华", "台独", "港独", "藏独", "疆独",
            "抗议", "游行", "维权", "人权", "警察", "军队", "解放军",
            "武统", "一国两制", "资本主义", "社会主义", "马列", "毛选"
        ]
    },
    "diary": {
        "enabled": True, "auto_enabled": True, "auto_interval_minutes": 60,
        "min_events_for_auto": 3
    },
    "self_evolution": {
        "enabled": True, "auto_enabled": True, "reflect_interval_events": 8,
        "min_events_for_reflect": 3, "auto_apply": True
    },
    "agent": {
        "enabled": True, "auto_enabled": True, "max_steps_per_plan": 5,
        "max_search_results": 8, "max_videos_per_plan": 5,
        "auto_min_score": 7.5, "cooldown_minutes": 60
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
    "session": {"max_videos": 0, "max_duration_minutes": 0},
    "revisit": {
        "enabled": True, "prob_revisit": 0.25, "revisit_cooldown_minutes": 15,
        "min_score": 7.5, "max_per_video": 2, "per_video_cooldown_minutes": 240
    },
    "active_chat": {
        "enabled": True, "prob_initiate": 0.06, "cooldown_minutes": 45,
        "max_initiate_per_session": 3
    },
    "entertainment": {
        "enabled": False, "auto_fortune": False, "prob_fun_action": 0.05,
        "joke_mode": "normal", "max_daily_fortune": 3
    },
    "up_follow": {
        "enabled": True, "auto_follow_prob": 0.08, "max_daily_follows": 3,
        "unfollow_inactive_days": 0, "browse_up_videos_prob": 0.06,
        "max_browse_videos": 3, "cooldown_minutes": 90,
        "favorite_up_browse_prob": 0.25, "favorite_up_uid_list": [],
        "test_mode": False
    },
    "danmaku": {
        "enabled": True, "read_prob": 0.4, "like_prob": 0.15,
        "max_daily_danmaku_likes": 10, "send_prob": 0.03, "max_daily_send": 2
    },
    "fallback_provider": {
        "enabled": False, "name": "备用API", "api_key": "", "base_url": "",
        "models": {"chat": "", "vision": ""}
    },
    "fallback_models": {"chat": "", "vision": "", "fast": ""},
    "knowledge": {
        "auto_reclassify_enabled": True, "auto_reclassify_interval_minutes": 10,
        "auto_reclassify_clean_empty": True
    },
    "knowledge_verify": {
        "enabled": True, "use_web_search": True, "min_reliability_score": 0.7,
        "auto_fix": True
    },
    "curiosity_search": {
        "enabled": True, "max_videos_per_dive": 10, "dive_videos_default": 3,
        "dive_videos_mid": 5, "dive_videos_max": 10, "trigger_min_score": 7.5,
        "prob_trigger": 0.3, "cooldown_minutes": 120
    },
    "dry_goods": {"enabled": False, "min_score": 7.5, "folder_name": "highlights"},
    "ai_subtitle_verify": {"enabled": True, "knowledge_review_interval": 10, "knowledge_review_sample_size": 3},
    "cooldown": {
        "startup_cooldown_min": 5, "startup_cooldown_max": 10,
        "post_comment_cooldown_min": 3, "post_comment_cooldown_max": 8,
        "post_dm_cooldown_min": 3, "post_dm_cooldown_max": 8
    },
    "psycho_engine": {
        "enabled": True, "deep_analyze_interval_videos": 100,
        "heuristic_update_interval": 15, "cocoon_detect_interval": 15,
        "cocoon_warning_threshold": 0.35, "recommend_prob_per_round": 0.08,
        "min_views_before_recommend": 10, "max_surprise_daily": 5,
        "max_explore_daily": 5, "max_anticocoon_daily": 3,
        "min_actions_for_deep_analysis": 50, "deep_analysis_cooldown_seconds": 14400,
        "max_actions_in_log": 2000, "max_recommendation_log": 200,
        "aversion_auto_blacklist_threshold": 3, "aversion_score_block_threshold": 0.7,
        "aversion_score_warn_threshold": 0.4
    }
}


# ===== 配置加载/保存 =====
def load_config():
    """加载配置文件，合并默认值"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            for key in DEFAULT_CONFIG:
                if key not in cfg:
                    cfg[key] = DEFAULT_CONFIG[key]
                elif isinstance(cfg[key], dict):
                    for sub_key in DEFAULT_CONFIG[key]:
                        if sub_key not in cfg[key]:
                            cfg[key][sub_key] = DEFAULT_CONFIG[key][sub_key]
            return cfg
        except (OSError, json.JSONDecodeError):
            pass
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 保存配置文件失败: {e}{Style.RESET_ALL}")
        return False


def get_bot_name():
    return config.get("persona", {}).get("prompt_name", "AI小助手")


def get_config_or_env(section, key, env_name):
    return os.getenv(env_name) or config.get(section, {}).get(key, "")


def mask_secret(value):
    if not value:
        return "(未配置)"
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


# ===== JSON 辅助 =====
def load_json_file(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default.copy() if isinstance(default, dict) else default


def save_json_file(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# 加载当前配置（模块导入时自动加载）
config = load_config()

# ===== 派生配置变量（供其他模块导入） =====
UNIFIED_API_KEY = get_config_or_env("api", "unified_api_key", "BILI_AI_API_KEY")
UNIFIED_BASE_URL = get_config_or_env("api", "unified_base_url", "BILI_AI_BASE_URL")
MODEL_BRAIN = get_config_or_env("api", "model_brain", "BILI_AI_MODEL_BRAIN")
MODEL_VISION = get_config_or_env("api", "model_vision", "BILI_AI_MODEL_VISION")
VISION_API_KEY = config["api"].get("vision_api_key") or UNIFIED_API_KEY
VISION_BASE_URL = config["api"].get("vision_base_url") or UNIFIED_BASE_URL
COIN_THRESHOLD = config["interaction"]["coin_threshold"]
FAV_THRESHOLD = config["interaction"]["fav_threshold"]
INTEREST_THRESHOLD = config["interaction"]["interest_threshold"]
MAX_ENERGY = config["interaction"]["max_energy"]
COMMENT_MODE = config.get("behavior", {}).get("comment_mode", "real")
MAX_COINS_DAILY = config["interaction"]["max_coins_daily"]
PROB_COIN = config["interaction"]["prob_coin"]
PROB_FAV = config["interaction"]["prob_fav"]
PROB_REPLY_TRIGGER = config["interaction"]["prob_reply_trigger"]
LEARN_MIN_SCORE = config["interaction"].get("learn_min_score", 6.0)
LEARN_MIN_DURATION_SECONDS = config["interaction"].get("learn_min_duration_seconds", 60)
AI_MARKER = config.get("behavior", {}).get("ai_marker", "（内容由AI生成并由AI回复）")
COMMENT_CHECK_INTERVAL = config["interaction"]["comment_check_interval"]
MAX_REPLIES_PER_CHECK = config["interaction"]["max_replies_per_check"]
PRIVATE_MESSAGE_ENABLED = config.get("private_message", {}).get("enabled", True)
PRIVATE_MESSAGE_CHECK_INTERVAL = config.get("private_message", {}).get("check_interval", 120)
DIARY_ENABLED = config.get("diary", {}).get("enabled", True)
EVOLUTION_ENABLED = config.get("self_evolution", {}).get("enabled", True)
AGENT_ENABLED = config.get("agent", {}).get("enabled", True)
UP_FOLLOW_ENABLED = config.get("up_follow", {}).get("enabled", True)
DANMAKU_ENABLED = config.get("danmaku", {}).get("enabled", True)
FALLBACK_MODELS = config.get("fallback_models", {})
FALLBACK_PROVIDER_ENABLED = config.get("fallback_provider", {}).get("enabled", False)
FALLBACK_PROVIDER_NAME = config.get("fallback_provider", {}).get("name", "chatanywhere")
DIARY_AUTO_ENABLED = config.get("diary", {}).get("auto_enabled", True)
PSYCHO_ENGINE_ENABLED = config.get("psycho_engine", {}).get("enabled", True)
SESSION_MAX_VIDEOS = config.get("session", {}).get("max_videos", 0)
SESSION_MAX_DURATION_MINUTES = config.get("session", {}).get("max_duration_minutes", 0)
AGENT_SKILL_LOG_FILE = os.path.join(DATA_DIR, "agent_skill_log.json")
AGENT_DIVE_MAX_VIDEOS = config.get("agent", {}).get("dive_max_videos", 10)
AGENT_MAX_SEARCH_RESULTS = config.get("agent", {}).get("max_search_results", 8)
AGENT_MAX_STEPS_PER_PLAN = config.get("agent", {}).get("max_steps_per_plan", 5)
AGENT_MAX_VIDEOS_PER_PLAN = config.get("agent", {}).get("max_videos_per_plan", 3)


# ===== 日志系统（供所有模块共用） =====
def log(msg, level="INFO"):
    """彩色日志输出"""
    colors = {
        "INFO": Fore.WHITE,
        "SUCCESS": Fore.GREEN,
        "WARN": Fore.YELLOW,
        "ERROR": Fore.RED,
        "DEBUG": Fore.CYAN,
        "CONFIG": Fore.CYAN,
        "BRAIN": Fore.MAGENTA,
        "BILI": Fore.BLUE,
        "COMMENT": Fore.GREEN,
        "PRIVATE": Fore.MAGENTA,
        "DANMAKU": Fore.CYAN,
        "EYE": Fore.YELLOW,
        "ASR": Fore.RED,
        "MEMORY": Fore.BLUE,
        "DIARY": Fore.GREEN,
        "EVOLVE": Fore.MAGENTA,
        "ENERGY": Fore.CYAN,
        "SAFETY": Fore.YELLOW,
        "PSYCHO": Fore.MAGENTA,
    }
    from datetime import datetime
    timestamp = datetime.now().strftime("%H:%M:%S")
    color = colors.get(level, Fore.WHITE)
    print(f"{color}[{timestamp}][{level}] {msg}{Style.RESET_ALL}")
