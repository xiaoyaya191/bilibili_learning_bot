"""core/globals.py — 全局运行时变量

所有从 config 派生的模块级变量集中定义于此。
各模块通过 `from core.globals import *` 获取。
"""
import os, json, re, sys
from datetime import datetime
from colorama import Fore, Style

from core.config import config, load_config as _load_config, save_config as _save_config
from core.config import get_backup_dir, mask_secret, get_config_or_env
from utils.display import log

# ══════════════════════════════════════════════════════════
# 路径变量
# ══════════════════════════════════════════════════════════
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
SEARCH_HISTORY_FILE = os.path.join(DATA_DIR, "search_history.json")
RUNTIME_STATE_FILE = os.path.join(DATA_DIR, "bot_runtime_state.json")
JOURNAL_FILE = os.path.join(BASE_DIR, "bot_journal.md")
MEMORY_FILE = os.path.join(BASE_DIR, "bot_memory.json")
HISTORY_VIDEOS_FILE = os.path.join(DATA_DIR, "history_videos.json")
KNOWLEDGE_BASE_DIR = os.path.join(BASE_DIR, "KnowledgeBase")
DRY_GOODS_DIR = os.path.join(BASE_DIR, "highlights")
LEARNING_LOG_FILE = os.path.join(BASE_DIR, "learning_log.md")
KB_METADATA_FILE = os.path.join(BASE_DIR, "knowledge_metadata.json")

# ══════════════════════════════════════════════════════════
# 配置派生变量 (按原 start_cli.py 顺序)
# ══════════════════════════════════════════════════════════
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
PROB_COMMENT_OTHERS = config["interaction"]["prob_comment_others"]
RANDOM_ENABLED = config["interaction"].get("random_enabled", True)
PROB_LIKE_SOLO = config["interaction"].get("prob_like_solo", 0.5)
COMMENT_CHECK_ENABLED = config.get("comment", {}).get("enabled", True)

PRIVATE_MESSAGE_ENABLED = config.get("private_message", {}).get("enabled", True)
PRIVATE_MESSAGE_CHECK_INTERVAL = config.get("private_message", {}).get("check_interval", 120)
PRIVATE_MESSAGE_AUTO_REPLY = config.get("private_message", {}).get("auto_reply", False)
PRIVATE_MESSAGE_MAX_REPLIES = config.get("private_message", {}).get("max_replies_per_check", 3)
PRIVATE_MESSAGE_ONLY_RECENT_SECONDS = config.get("private_message", {}).get("only_recent_seconds", 900)

DIARY_ENABLED = config.get("diary", {}).get("enabled", True)
DIARY_AUTO_ENABLED = config.get("diary", {}).get("auto_enabled", True)
DIARY_AUTO_INTERVAL_MINUTES = config.get("diary", {}).get("auto_interval_minutes", 60)
DIARY_MIN_EVENTS_FOR_AUTO = config.get("diary", {}).get("min_events_for_auto", 3)

EVOLUTION_ENABLED = config.get("self_evolution", {}).get("enabled", True)
EVOLUTION_AUTO_ENABLED = config.get("self_evolution", {}).get("auto_enabled", True)
EVOLUTION_AUTO_APPLY = config.get("self_evolution", {}).get("auto_apply", True)
EVOLUTION_REFLECT_INTERVAL_EVENTS = config.get("self_evolution", {}).get("reflect_interval_events", 8)
EVOLUTION_MIN_EVENTS_FOR_REFLECT = config.get("self_evolution", {}).get("min_events_for_reflect", 3)

AGENT_ENABLED = config.get("agent", {}).get("enabled", True)
AGENT_AUTO_ENABLED = config.get("agent", {}).get("auto_enabled", True)
AGENT_AUTO_MIN_SCORE = config.get("agent", {}).get("auto_min_score", 7.5)
AGENT_COOLDOWN_MINUTES = config.get("agent", {}).get("cooldown_minutes", 60)
AGENT_DIVE_ENABLED = config.get("agent", {}).get("dive_enabled", True)
AGENT_DIVE_MAX_VIDEOS = config.get("agent", {}).get("dive_max_videos", 10)
AGENT_MAX_SEARCH_RESULTS = config.get("agent", {}).get("max_search_results", 8)
AGENT_MAX_STEPS_PER_PLAN = config.get("agent", {}).get("max_steps_per_plan", 5)
AGENT_MAX_VIDEOS_PER_PLAN = config.get("agent", {}).get("max_videos_per_plan", 3)

UP_FOLLOW_ENABLED = config.get("up_follow", {}).get("enabled", True)
UP_FOLLOW_AUTO_PROB = config.get("up_follow", {}).get("auto_follow_prob", 0.08)
UP_FOLLOW_MAX_DAILY = config.get("up_follow", {}).get("max_daily_follows", 3)
UP_FOLLOW_BROWSE_PROB = config.get("up_follow", {}).get("browse_up_videos_prob", 0.06)
UP_FOLLOW_MAX_BROWSE = config.get("up_follow", {}).get("max_browse_videos", 3)
UP_FOLLOW_COOLDOWN_MINUTES = config.get("up_follow", {}).get("cooldown_minutes", 90)
UP_FOLLOW_FAVORITE_PROB = config.get("up_follow", {}).get("favorite_up_browse_prob", 0.25)
UP_FOLLOW_FAVORITE_UID_LIST = config.get("up_follow", {}).get("favorite_up_uid_list", [])
UP_FOLLOW_TEST_MODE = config.get("up_follow", {}).get("test_mode", False)
UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS = config.get("up_follow", {}).get("unfollow_inactive_days", 0)
UP_FOLLOW_MIN_SCORE = config.get("up_follow", {}).get("min_score", 7.0)
UP_FOLLOW_MIN_IMPRESSIONS = config.get("up_follow", {}).get("min_impressions", 3)
UP_FOLLOW_EXCEPTIONAL_SCORE = config.get("up_follow", {}).get("exceptional_score", 9.0)

DANMAKU_ENABLED = config.get("danmaku", {}).get("enabled", True)
DANMAKU_READ_PROB = config.get("danmaku", {}).get("read_prob", 0.4)
DANMAKU_LIKE_PROB = config.get("danmaku", {}).get("like_prob", 0.15)
DANMAKU_MAX_DAILY_LIKES = config.get("danmaku", {}).get("max_daily_danmaku_likes", 10)
DANMAKU_SEND_PROB = config.get("danmaku", {}).get("send_prob", 0.03)
DANMAKU_MAX_DAILY_SEND = config.get("danmaku", {}).get("max_daily_send", 2)

ENERGY_RECOVERY_MIN = config.get("energy", {}).get("energy_recovery_min", 5)
ENERGY_RECOVERY_MAX = config.get("energy", {}).get("energy_recovery_max", 10)
ROUNDS_MIN = config.get("energy", {}).get("rounds_min", 3)
ROUNDS_MAX = config.get("energy", {}).get("rounds_max", 10)
ROUND_INTERVAL_MIN = config.get("energy", {}).get("round_interval_min", 60)
ROUND_INTERVAL_MAX = config.get("energy", {}).get("round_interval_max", 180)
VIDEO_INTERVAL_MIN = config.get("energy", {}).get("video_interval_min", 1)
VIDEO_INTERVAL_MAX = config.get("energy", {}).get("video_interval_max", 5)

VIDEO_UNDERSTANDING_MODE = config.get("video", {}).get("mode", "smart")
VIDEO_MAX_DURATION_SECONDS = config.get("video", {}).get("max_duration_seconds", 900)
VIDEO_FRAME_COUNT = config.get("video", {}).get("frame_count", 12)
VIDEO_DOWNLOAD_INTEREST_THRESHOLD = config.get("video", {}).get("download_interest_threshold", 7.0)
VIDEO_DOWNLOAD_DIR = config.get("video", {}).get("download_dir", "")
VIDEO_DELETE_AFTER_UNDERSTAND = config.get("video", {}).get("delete_video_after_understand", True)
VIDEO_FILTER_MODE = config.get("video", {}).get("filter_mode", "cover_and_title")
SMART_FRAME_ENABLED = config.get("video", {}).get("smart_frame_enabled", False)
SMART_FRAME_MIN = config.get("video", {}).get("smart_frame_min", 10)
SMART_FRAME_MAX = config.get("video", {}).get("smart_frame_max", 60)

VISION_COVER_ENABLED = config.get("vision", {}).get("cover_enabled", True)
VISION_FRAMES_ENABLED = config.get("vision", {}).get("frames_enabled", True)
VISION_COMMENT_IMAGES_ENABLED = config.get("vision", {}).get("comment_images_enabled", True)
VISION_MAX_COMMENT_IMAGES = config.get("vision", {}).get("max_comment_images", 5)
VISION_FRAME_COUNT = config.get("vision", {}).get("frame_count", 8)

ASR_ENABLED = config.get("asr", {}).get("enabled", False)
ASR_BACKEND = config.get("asr", {}).get("backend", "funasr")
ASR_WHISPER_MODEL = config.get("asr", {}).get("whisper_model", "base")
ASR_LANGUAGE = config.get("asr", {}).get("language", "zh")
ASR_SPEAKER_SEPARATION = config.get("asr", {}).get("speaker_separation", True)
ASR_MAX_AUDIO_DURATION = config.get("asr", {}).get("max_audio_duration", 3600)
ASR_MIN_CONFIDENCE = config.get("asr", {}).get("min_confidence", 0.5)
ASR_SKIP_MUSIC = config.get("asr", {}).get("skip_music", True)
ASR_KEEP_AUDIO = config.get("asr", {}).get("keep_audio", False)
ASR_DEVICE = config.get("asr", {}).get("device", "cpu")
ASR_FFMPEG_PATH = config.get("asr", {}).get("ffmpeg_path", "")
ASR_FUNASR_MODEL_DIR = config.get("asr", {}).get("funasr_model_dir", "")
ASR_FUNASR_VAD_ENABLED = config.get("asr", {}).get("funasr_vad_enabled", True)
ASR_FUNASR_PUNC_ENABLED = config.get("asr", {}).get("funasr_punc_enabled", True)
ASR_FUNASR_SPK_ENABLED = config.get("asr", {}).get("funasr_spk_enabled", False)
ASR_FUNASR_BATCH_SIZE_S = config.get("asr", {}).get("funasr_batch_size_s", 300)
ASR_FUNASR_HOTWORD = config.get("asr", {}).get("funasr_hotword", "")

REPLY_SAFETY_ENABLED = config.get("reply_safety", {}).get("enabled", True)
REPLY_SAFETY_BLOCK_ON_INCOMING = config.get("reply_safety", {}).get("block_on_incoming", True)
REPLY_SAFETY_BLOCK_ON_OUTGOING = config.get("reply_safety", {}).get("block_on_outgoing", True)
REPLY_SAFETY_BLOCK_POLITICAL_VIDEO_COMMENTS = config.get("reply_safety", {}).get("block_political_video_comments", True)
REPLY_SAFETY_BLOCKED_KEYWORDS = config.get("reply_safety", {}).get("blocked_keywords", [])

MOOD_RANDOM_ENABLED = config.get("mood", {}).get("random_enabled", False)
MOOD_RANDOM_INTERVAL_MINUTES = config.get("mood", {}).get("random_interval_minutes", 5)
MOOD_CUSTOM_ENABLED = config.get("mood", {}).get("custom_enabled", False)
MOOD_CUSTOM_VALUE = config.get("mood", {}).get("custom_mood", "")

FALLBACK_PROVIDER_ENABLED = config.get("fallback_provider", {}).get("enabled", False)
FALLBACK_PROVIDER_NAME = config.get("fallback_provider", {}).get("name", "备用API")
FALLBACK_PROVIDER_API_KEY = config.get("fallback_provider", {}).get("api_key", "")
FALLBACK_PROVIDER_BASE_URL = config.get("fallback_provider", {}).get("base_url", "")
FALLBACK_PROVIDER_MODELS = config.get("fallback_provider", {}).get("models", {})
FALLBACK_MODELS = config.get("fallback_models", {})
FALLBACK_MODEL_CHAT = FALLBACK_MODELS.get("chat", "")
FALLBACK_MODEL_VISION = FALLBACK_MODELS.get("vision", "")
FALLBACK_MODEL_FAST = FALLBACK_MODELS.get("fast", "")

BEHAVIOR_MIN_REPLY_DELAY_SECONDS = config.get("behavior", {}).get("min_reply_delay_seconds", 4)
BEHAVIOR_MAX_REPLY_DELAY_SECONDS = config.get("behavior", {}).get("max_reply_delay_seconds", 18)
BEHAVIOR_COMMENT_USER_COOLDOWN_MINUTES = config.get("behavior", {}).get("comment_user_cooldown_minutes", 60)
BEHAVIOR_PRIVATE_REPLY_COOLDOWN_MINUTES = config.get("behavior", {}).get("private_reply_cooldown_minutes", 3)
BEHAVIOR_MAX_CONSECUTIVE_AI_REPLIES = config.get("behavior", {}).get("max_consecutive_ai_replies", 3)
BEHAVIOR_PREFER_SHORT_REPLIES = config.get("behavior", {}).get("prefer_short_replies", True)

SESSION_MAX_VIDEOS = config.get("session", {}).get("max_videos", 0)
SESSION_MAX_DURATION_MINUTES = config.get("session", {}).get("max_duration_minutes", 0)

REVISIT_ENABLED = config.get("revisit", {}).get("enabled", True)
PROB_REVISIT = config.get("revisit", {}).get("prob_revisit", 0.25)
REVISIT_COOLDOWN_MINUTES = config.get("revisit", {}).get("revisit_cooldown_minutes", 15)
REVISIT_MIN_SCORE = config.get("revisit", {}).get("min_score", 7.5)
REVISIT_MAX_PER_VIDEO = config.get("revisit", {}).get("max_per_video", 2)
REVISIT_PER_VIDEO_COOLDOWN_MINUTES = config.get("revisit", {}).get("per_video_cooldown_minutes", 240)

ACTIVE_CHAT_ENABLED = config.get("active_chat", {}).get("enabled", True)
PROB_INITIATE_CHAT = config.get("active_chat", {}).get("prob_initiate", 0.06)
ACTIVE_CHAT_COOLDOWN_MINUTES = config.get("active_chat", {}).get("cooldown_minutes", 45)
ACTIVE_CHAT_MAX_PER_SESSION = config.get("active_chat", {}).get("max_initiate_per_session", 3)

COOLDOWN_STARTUP_MIN = config.get("cooldown", {}).get("startup_cooldown_min", 5)
COOLDOWN_STARTUP_MAX = config.get("cooldown", {}).get("startup_cooldown_max", 10)
COOLDOWN_POST_COMMENT_MIN = config.get("cooldown", {}).get("post_comment_cooldown_min", 3)
COOLDOWN_POST_COMMENT_MAX = config.get("cooldown", {}).get("post_comment_cooldown_max", 8)
COOLDOWN_POST_DM_MIN = config.get("cooldown", {}).get("post_dm_cooldown_min", 3)
COOLDOWN_POST_DM_MAX = config.get("cooldown", {}).get("post_dm_cooldown_max", 8)

# [SPEED] 快速模式：跳过所有模拟真人延迟等待（主菜单 Q 切换）
NO_HUMAN_DELAY = config.get("speed", {}).get("no_human_delay", False)

DRY_GOODS_ENABLED = config.get("dry_goods", {}).get("enabled", False)
DRY_GOODS_MIN_SCORE = config.get("dry_goods", {}).get("min_score", 7.5)
DRY_GOODS_FOLDER_NAME = config.get("dry_goods", {}).get("folder_name", "highlights")

AUTO_RECLASSIFY_ENABLED = config.get("knowledge", {}).get("auto_reclassify_enabled", True)
AUTO_RECLASSIFY_INTERVAL_MINUTES = config.get("knowledge", {}).get("auto_reclassify_interval_minutes", 10)
AUTO_RECLASSIFY_CLEAN_EMPTY = config.get("knowledge", {}).get("auto_reclassify_clean_empty", True)

KNOWLEDGE_VERIFY_ENABLED = config.get("knowledge_verify", {}).get("enabled", True)
KNOWLEDGE_VERIFY_USE_WEB = config.get("knowledge_verify", {}).get("use_web_search", True)
KNOWLEDGE_VERIFY_MIN_SCORE = config.get("knowledge_verify", {}).get("min_reliability_score", 0.7)
KNOWLEDGE_VERIFY_AUTO_FIX = config.get("knowledge_verify", {}).get("auto_fix", True)
AI_SUBTITLE_VERIFY_ENABLED = config.get("ai_subtitle_verify", {}).get("enabled", True)
KNOWLEDGE_REVIEW_INTERVAL = config.get("ai_subtitle_verify", {}).get("knowledge_review_interval", 10)
KNOWLEDGE_REVIEW_SAMPLE_SIZE = config.get("ai_subtitle_verify", {}).get("knowledge_review_sample_size", 3)

CURIOSITY_DEEP_DIVE_ENABLED = config.get("curiosity_search", {}).get("enabled", True)
CURIOSITY_DEEP_DIVE_MAX_VIDEOS = config.get("curiosity_search", {}).get("max_videos_per_dive", 10)
CURIOSITY_DEEP_DIVE_DEFAULT_VIDEOS = config.get("curiosity_search", {}).get("dive_videos_default", 3)
CURIOSITY_DEEP_DIVE_MID_VIDEOS = config.get("curiosity_search", {}).get("dive_videos_mid", 5)
CURIOSITY_DEEP_DIVE_HIGH_VIDEOS = config.get("curiosity_search", {}).get("dive_videos_max", 10)
CURIOSITY_DEEP_DIVE_MIN_SCORE = config.get("curiosity_search", {}).get("trigger_min_score", 7.5)
CURIOSITY_DEEP_DIVE_PROB = config.get("curiosity_search", {}).get("prob_trigger", 0.3)
CURIOSITY_DEEP_DIVE_COOLDOWN_MINUTES = config.get("curiosity_search", {}).get("cooldown_minutes", 120)

PSYCHO_ENGINE_ENABLED = config.get("psycho_engine", {}).get("enabled", True)
PSYCHO_DEEP_ANALYZE_INTERVAL = config.get("psycho_engine", {}).get("deep_analyze_interval_videos", 100)
PSYCHO_HEURISTIC_UPDATE_INTERVAL = config.get("psycho_engine", {}).get("heuristic_update_interval", 15)
PSYCHO_COCOON_WARNING_THRESHOLD = config.get("psycho_engine", {}).get("cocoon_warning_threshold", 0.35)
PSYCHO_RECOMMEND_PROB = config.get("psycho_engine", {}).get("recommend_prob_per_round", 0.08)
PSYCHO_MIN_VIEWS_BEFORE_RECOMMEND = config.get("psycho_engine", {}).get("min_views_before_recommend", 10)
PSYCHO_AVERSION_BLOCK_SCORE = config.get("psycho_engine", {}).get("aversion_score_block_threshold", 0.7)
PSYCHO_AVERSION_WARN_SCORE = config.get("psycho_engine", {}).get("aversion_score_warn_threshold", 0.4)

SUBTITLE_STRICT_CHECK = config.get("subtitle_strict_check", {}).get("enabled", False)
QUIET_MODE = config.get("system", {}).get("quiet_mode", False)  # 安静模式：精简日志
DEFAULT_CONFIG = config  # 引用默认配置模板

# ══════════════════════════════════════════════════════════
# JSON 辅助
# ══════════════════════════════════════════════════════════
def _load_json_file(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return default.copy() if isinstance(default, dict) else default

def _save_json_file(path, data):
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return True
    except OSError:
        return False


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
        if len(history) > 100:
            history = history[-100:]
        with open(SEARCH_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"保存搜索记录失败: {e}", "WARN")
