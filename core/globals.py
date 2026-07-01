"""core/globals.py — 全局运行时变量

所有从 config 派生的模块级变量集中定义于此。
各模块通过 `from core.globals import *` 获取。

[FIX] 所有 config 派生变量已改为模块级 __getattr__ 动态属性，
确保用户通过菜单修改配置后实时生效。
"""
import os, json, re, sys
from datetime import datetime
from colorama import Fore, Style

from core.config import config, load_config as _load_config, save_config as _save_config
from core.config import get_backup_dir, mask_secret, get_config_or_env
from utils.display import log

# ══════════════════════════════════════════════════════════
# 动态配置映射表：变量名 → (config键路径, 默认值)
# 格式: (config_path_tuple, default)
# 例如: ("interaction", "coin_threshold") → config["interaction"]["coin_threshold"]
# ══════════════════════════════════════════════════════════
_CONFIG_PATHS = {
    # API
    "UNIFIED_API_KEY":       (("api", "unified_api_key"), None, "BILI_AI_API_KEY"),
    "UNIFIED_BASE_URL":      (("api", "unified_base_url"), None, "BILI_AI_BASE_URL"),
    "MODEL_BRAIN":           (("api", "model_brain"), None, "BILI_AI_MODEL_BRAIN"),
    "MODEL_VISION":          (("api", "model_vision"), None, "BILI_AI_MODEL_VISION"),
    "MODEL_HTML":            (("api", "model_html"), None, "BILI_AI_MODEL_HTML"),
    "VISION_API_KEY":        (("api", "vision_api_key"), None),  # 特殊：回退到 UNIFIED_API_KEY
    "VISION_BASE_URL":       (("api", "vision_base_url"), None),  # 特殊：回退到 UNIFIED_BASE_URL

    # 互动
    "COIN_THRESHOLD":        (("interaction", "coin_threshold"), 8.0),
    "FAV_THRESHOLD":         (("interaction", "fav_threshold"), 8.5),
    "INTEREST_THRESHOLD":    (("interaction", "interest_threshold"), 6.5),
    "MAX_ENERGY":            (("interaction", "max_energy"), 100),
    "COMMENT_MODE":          (("behavior", "comment_mode"), "real"),
    "MAX_COINS_DAILY":       (("interaction", "max_coins_daily"), 2),
    "COIN_COOLDOWN_MINUTES": (("interaction", "coin_cooldown_minutes"), 0),
    "COIN_MAX_PER_HOUR":     (("interaction", "coin_max_per_hour"), 0),
    "PROB_COIN":             (("interaction", "prob_coin"), 0.25),
    "PROB_FAV":              (("interaction", "prob_fav"), 0.8),
    "PROB_REPLY_TRIGGER":    (("interaction", "prob_reply_trigger"), 0.15),
    "LEARN_MIN_SCORE":       (("interaction", "learn_min_score"), 6.0),
    "LEARN_MIN_DURATION_SECONDS": (("interaction", "learn_min_duration_seconds"), 60),
    "AI_MARKER":             (("behavior", "ai_marker"), "（内容由AI生成并由AI回复）"),
    "COMMENT_CHECK_INTERVAL":(("interaction", "comment_check_interval"), 300),
    "MAX_REPLIES_PER_CHECK": (("interaction", "max_replies_per_check"), 3),
    "PROB_COMMENT_OTHERS":   (("interaction", "prob_comment_others"), 0.3),
    "RANDOM_ENABLED":        (("interaction", "random_enabled"), True),
    "PROB_LIKE_SOLO":        (("interaction", "prob_like_solo"), 0.5),
    "COMMENT_CHECK_ENABLED": (("comment", "enabled"), True),

    # 私信
    "PRIVATE_MESSAGE_ENABLED":         (("private_message", "enabled"), True),
    "PRIVATE_MESSAGE_CHECK_INTERVAL":  (("private_message", "check_interval"), 120),
    "PRIVATE_MESSAGE_AUTO_REPLY":      (("private_message", "auto_reply"), False),
    "PRIVATE_MESSAGE_MAX_REPLIES":     (("private_message", "max_replies_per_check"), 3),
    "PRIVATE_MESSAGE_ONLY_RECENT_SECONDS": (("private_message", "only_recent_seconds"), 900),

    # 看完视频后检查通知
    "PER_VIDEO_CHECK_ENABLED":            (("per_video_check", "enabled"), True),
    "PER_VIDEO_CHECK_AT_NOTIFICATIONS":   (("per_video_check", "check_at_notifications"), True),
    "PER_VIDEO_CHECK_PRIVATE_MESSAGES":   (("per_video_check", "check_private_messages"), True),
    "PER_VIDEO_CHECK_OWN_COMMENTS":        (("per_video_check", "check_own_comments"), True),
    "PER_VIDEO_CHECK_MAX_AT":             (("per_video_check", "max_at_per_check"), 5),
    "PER_VIDEO_CHECK_COOLDOWN":           (("per_video_check", "cooldown_seconds"), 30),

    # 日记
    "DIARY_ENABLED":              (("diary", "enabled"), True),
    "DIARY_AUTO_ENABLED":         (("diary", "auto_enabled"), True),
    "DIARY_AUTO_INTERVAL_MINUTES":(("diary", "auto_interval_minutes"), 60),
    "DIARY_MIN_EVENTS_FOR_AUTO":  (("diary", "min_events_for_auto"), 3),

    # 自我进化
    "EVOLUTION_ENABLED":                  (("self_evolution", "enabled"), True),
    "EVOLUTION_AUTO_ENABLED":             (("self_evolution", "auto_enabled"), True),
    "EVOLUTION_AUTO_APPLY":               (("self_evolution", "auto_apply"), True),
    "EVOLUTION_REFLECT_INTERVAL_EVENTS":  (("self_evolution", "reflect_interval_events"), 8),
    "EVOLUTION_MIN_EVENTS_FOR_REFLECT":   (("self_evolution", "min_events_for_reflect"), 3),

    # Agent
    "AGENT_ENABLED":              (("agent", "enabled"), True),
    "AGENT_AUTO_ENABLED":         (("agent", "auto_enabled"), True),
    "AGENT_AUTO_MIN_SCORE":       (("agent", "auto_min_score"), 7.5),
    "AGENT_COOLDOWN_MINUTES":     (("agent", "cooldown_minutes"), 60),
    "AGENT_DIVE_ENABLED":         (("agent", "dive_enabled"), True),
    "AGENT_DIVE_MAX_VIDEOS":      (("agent", "dive_max_videos"), 10),
    "AGENT_MAX_SEARCH_RESULTS":   (("agent", "max_search_results"), 8),
    "AGENT_MAX_STEPS_PER_PLAN":   (("agent", "max_steps_per_plan"), 5),
    "AGENT_MAX_VIDEOS_PER_PLAN":  (("agent", "max_videos_per_plan"), 3),

    # UP主关注
    "UP_FOLLOW_ENABLED":             (("up_follow", "enabled"), True),
    "UP_FOLLOW_AUTO_PROB":           (("up_follow", "auto_follow_prob"), 0.08),
    "UP_FOLLOW_MAX_DAILY":           (("up_follow", "max_daily_follows"), 3),
    "UP_FOLLOW_BROWSE_PROB":         (("up_follow", "browse_up_videos_prob"), 0.06),
    "UP_FOLLOW_MAX_BROWSE":          (("up_follow", "max_browse_videos"), 3),
    "UP_FOLLOW_COOLDOWN_MINUTES":    (("up_follow", "cooldown_minutes"), 90),
    "UP_FOLLOW_FAVORITE_PROB":       (("up_follow", "favorite_up_browse_prob"), 0.25),
    "UP_FOLLOW_FAVORITE_UID_LIST":   (("up_follow", "favorite_up_uid_list"), []),
    "UP_FOLLOW_TEST_MODE":           (("up_follow", "test_mode"), False),
    "UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS": (("up_follow", "unfollow_inactive_days"), 0),
    "UP_FOLLOW_MIN_SCORE":           (("up_follow", "min_score"), 7.0),
    "UP_FOLLOW_MIN_IMPRESSIONS":     (("up_follow", "min_impressions"), 3),
    "UP_FOLLOW_EXCEPTIONAL_SCORE":   (("up_follow", "exceptional_score"), 9.0),

    # 弹幕
    "DANMAKU_ENABLED":       (("danmaku", "enabled"), True),
    "DANMAKU_READ_PROB":     (("danmaku", "read_prob"), 0.4),
    "DANMAKU_LIKE_PROB":     (("danmaku", "like_prob"), 0.15),
    "DANMAKU_MAX_DAILY_LIKES":(("danmaku", "max_daily_danmaku_likes"), 10),
    "DANMAKU_SEND_PROB":     (("danmaku", "send_prob"), 0.03),
    "DANMAKU_MAX_DAILY_SEND":(("danmaku", "max_daily_send"), 2),

    # 精力/视频间隔
    "ENERGY_RECOVERY_MIN": (("energy", "energy_recovery_min"), 5),
    "ENERGY_RECOVERY_MAX": (("energy", "energy_recovery_max"), 10),
    "ROUNDS_MIN":          (("energy", "rounds_min"), 3),
    "ROUNDS_MAX":          (("energy", "rounds_max"), 10),
    "ROUND_INTERVAL_MIN":  (("energy", "round_interval_min"), 60),
    "ROUND_INTERVAL_MAX":  (("energy", "round_interval_max"), 180),
    "VIDEO_INTERVAL_MIN":  (("energy", "video_interval_min"), 1),
    "VIDEO_INTERVAL_MAX":  (("energy", "video_interval_max"), 5),

    # 视频理解
    "VIDEO_UNDERSTANDING_MODE":          (("video", "mode"), "smart"),
    "VIDEO_MAX_DURATION_SECONDS":        (("video", "max_duration_seconds"), 900),
    "VIDEO_FRAME_COUNT":                 (("video", "frame_count"), 12),
    "VIDEO_DOWNLOAD_INTEREST_THRESHOLD": (("video", "download_interest_threshold"), 7.0),
    "VIDEO_DOWNLOAD_DIR":                (("video", "download_dir"), ""),
    "VIDEO_DELETE_AFTER_UNDERSTAND":     (("video", "delete_video_after_understand"), True),
    "VIDEO_FILTER_MODE":                 (("video", "filter_mode"), "cover_and_title"),
    "SMART_FRAME_ENABLED":               (("video", "smart_frame_enabled"), False),
    "SMART_FRAME_MIN":                   (("video", "smart_frame_min"), 10),
    "SMART_FRAME_MAX":                   (("video", "smart_frame_max"), 60),

    # 视觉
    "VISION_COVER_ENABLED":           (("vision", "cover_enabled"), True),
    "VISION_FRAMES_ENABLED":          (("vision", "frames_enabled"), True),
    "VISION_COMMENT_IMAGES_ENABLED":  (("vision", "comment_images_enabled"), True),
    "VISION_MAX_COMMENT_IMAGES":      (("vision", "max_comment_images"), 5),
    "VISION_FRAME_COUNT":             (("vision", "frame_count"), 8),

    # ASR
    "ASR_ENABLED":              (("asr", "enabled"), False),
    "ASR_BACKEND":              (("asr", "backend"), "funasr"),
    "ASR_WHISPER_MODEL":        (("asr", "whisper_model"), "base"),
    "ASR_LANGUAGE":             (("asr", "language"), "zh"),
    "ASR_SPEAKER_SEPARATION":   (("asr", "speaker_separation"), True),
    "ASR_MAX_AUDIO_DURATION":   (("asr", "max_audio_duration"), 3600),
    "ASR_MIN_CONFIDENCE":       (("asr", "min_confidence"), 0.5),
    "ASR_SKIP_MUSIC":           (("asr", "skip_music"), True),
    "ASR_KEEP_AUDIO":           (("asr", "keep_audio"), False),
    "ASR_DEVICE":               (("asr", "device"), "cpu"),
    "ASR_FFMPEG_PATH":          (("asr", "ffmpeg_path"), ""),
    "ASR_FUNASR_MODEL_DIR":     (("asr", "funasr_model_dir"), ""),
    "ASR_FUNASR_VAD_ENABLED":   (("asr", "funasr_vad_enabled"), True),
    "ASR_FUNASR_PUNC_ENABLED":  (("asr", "funasr_punc_enabled"), True),
    "ASR_FUNASR_SPK_ENABLED":   (("asr", "funasr_spk_enabled"), False),
    "ASR_FUNASR_BATCH_SIZE_S":  (("asr", "funasr_batch_size_s"), 300),
    "ASR_FUNASR_HOTWORD":       (("asr", "funasr_hotword"), ""),

    # 关键词安全
    "REPLY_SAFETY_ENABLED":                      (("reply_safety", "enabled"), True),
    "REPLY_SAFETY_BLOCK_ON_INCOMING":            (("reply_safety", "block_on_incoming"), True),
    "REPLY_SAFETY_BLOCK_ON_OUTGOING":            (("reply_safety", "block_on_outgoing"), True),
    "REPLY_SAFETY_BLOCK_POLITICAL_VIDEO_COMMENTS": (("reply_safety", "block_political_video_comments"), True),
    "REPLY_SAFETY_BLOCKED_KEYWORDS":             (("reply_safety", "blocked_keywords"), []),

    # AI心情
    "MOOD_RANDOM_ENABLED":         (("mood", "random_enabled"), False),
    "MOOD_RANDOM_INTERVAL_MINUTES":(("mood", "random_interval_minutes"), 5),
    "MOOD_CUSTOM_ENABLED":         (("mood", "custom_enabled"), False),
    "MOOD_CUSTOM_VALUE":           (("mood", "custom_mood"), ""),

    # 备用API
    "FALLBACK_PROVIDER_ENABLED":  (("fallback_provider", "enabled"), False),
    "FALLBACK_PROVIDER_NAME":     (("fallback_provider", "name"), "备用API"),
    "FALLBACK_PROVIDER_API_KEY":  (("fallback_provider", "api_key"), ""),
    "FALLBACK_PROVIDER_BASE_URL": (("fallback_provider", "base_url"), ""),
    "FALLBACK_PROVIDER_MODELS":   (("fallback_provider", "models"), {}),
    "FALLBACK_MODELS":            (("fallback_models", ), {}),
    "FALLBACK_MODEL_CHAT":        (("fallback_models", "chat"), ""),
    "FALLBACK_MODEL_VISION":      (("fallback_models", "vision"), ""),
    "FALLBACK_MODEL_FAST":        (("fallback_models", "fast"), ""),

    # 行为
    "BEHAVIOR_MIN_REPLY_DELAY_SECONDS":    (("behavior", "min_reply_delay_seconds"), 4),
    "BEHAVIOR_MAX_REPLY_DELAY_SECONDS":    (("behavior", "max_reply_delay_seconds"), 18),
    "BEHAVIOR_COMMENT_USER_COOLDOWN_MINUTES": (("behavior", "comment_user_cooldown_minutes"), 60),
    "BEHAVIOR_PRIVATE_REPLY_COOLDOWN_MINUTES":(("behavior", "private_reply_cooldown_minutes"), 3),
    "BEHAVIOR_MAX_CONSECUTIVE_AI_REPLIES": (("behavior", "max_consecutive_ai_replies"), 3),
    "BEHAVIOR_PREFER_SHORT_REPLIES":       (("behavior", "prefer_short_replies"), True),

    # 会话限制
    "SESSION_MAX_VIDEOS":          (("session", "max_videos"), 0),
    "SESSION_MAX_DURATION_MINUTES":(("session", "max_duration_minutes"), 0),

    # 复习回顾
    "REVISIT_ENABLED":                    (("revisit", "enabled"), True),
    "PROB_REVISIT":                       (("revisit", "prob_revisit"), 0.25),
    "REVISIT_COOLDOWN_MINUTES":           (("revisit", "revisit_cooldown_minutes"), 15),
    "REVISIT_MIN_SCORE":                  (("revisit", "min_score"), 7.5),
    "REVISIT_MAX_PER_VIDEO":              (("revisit", "max_per_video"), 2),
    "REVISIT_PER_VIDEO_COOLDOWN_MINUTES": (("revisit", "per_video_cooldown_minutes"), 240),

    # 主动聊天
    "ACTIVE_CHAT_ENABLED":         (("active_chat", "enabled"), True),
    "PROB_INITIATE_CHAT":          (("active_chat", "prob_initiate"), 0.06),
    "ACTIVE_CHAT_COOLDOWN_MINUTES":(("active_chat", "cooldown_minutes"), 45),
    "ACTIVE_CHAT_MAX_PER_SESSION": (("active_chat", "max_initiate_per_session"), 3),

    # 冷却
    "COOLDOWN_STARTUP_MIN":       (("cooldown", "startup_cooldown_min"), 5),
    "COOLDOWN_STARTUP_MAX":       (("cooldown", "startup_cooldown_max"), 10),
    "COOLDOWN_POST_COMMENT_MIN":  (("cooldown", "post_comment_cooldown_min"), 3),
    "COOLDOWN_POST_COMMENT_MAX":  (("cooldown", "post_comment_cooldown_max"), 8),
    "COOLDOWN_POST_DM_MIN":       (("cooldown", "post_dm_cooldown_min"), 3),
    "COOLDOWN_POST_DM_MAX":       (("cooldown", "post_dm_cooldown_max"), 8),

    # 快速模式
    "NO_HUMAN_DELAY": (("speed", "no_human_delay"), False),

    # 干货归档
    "DRY_GOODS_ENABLED":    (("dry_goods", "enabled"), False),
    "DRY_GOODS_MIN_SCORE":  (("dry_goods", "min_score"), 7.5),
    "DRY_GOODS_FOLDER_NAME":(("dry_goods", "folder_name"), "highlights"),

    # 知识库整理
    "AUTO_RECLASSIFY_ENABLED":         (("knowledge", "auto_reclassify_enabled"), True),
    "AUTO_RECLASSIFY_INTERVAL_MINUTES":(("knowledge", "auto_reclassify_interval_minutes"), 10),
    "AUTO_RECLASSIFY_CLEAN_EMPTY":     (("knowledge", "auto_reclassify_clean_empty"), True),

    # 知识校验
    "KNOWLEDGE_VERIFY_ENABLED":   (("knowledge_verify", "enabled"), True),
    "KNOWLEDGE_VERIFY_USE_WEB":   (("knowledge_verify", "use_web_search"), True),
    "KNOWLEDGE_VERIFY_MIN_SCORE": (("knowledge_verify", "min_reliability_score"), 0.7),
    "KNOWLEDGE_VERIFY_AUTO_FIX":  (("knowledge_verify", "auto_fix"), True),
    "AI_SUBTITLE_VERIFY_ENABLED": (("ai_subtitle_verify", "enabled"), True),
    "KNOWLEDGE_REVIEW_INTERVAL":  (("ai_subtitle_verify", "knowledge_review_interval"), 10),
    "KNOWLEDGE_REVIEW_SAMPLE_SIZE":(("ai_subtitle_verify", "knowledge_review_sample_size"), 3),

    # 好奇心深度探索
    "CURIOSITY_DEEP_DIVE_ENABLED":         (("curiosity_search", "enabled"), True),
    "CURIOSITY_DEEP_DIVE_MAX_VIDEOS":      (("curiosity_search", "max_videos_per_dive"), 10),
    "CURIOSITY_DEEP_DIVE_DEFAULT_VIDEOS":  (("curiosity_search", "dive_videos_default"), 3),
    "CURIOSITY_DEEP_DIVE_MID_VIDEOS":      (("curiosity_search", "dive_videos_mid"), 5),
    "CURIOSITY_DEEP_DIVE_HIGH_VIDEOS":     (("curiosity_search", "dive_videos_max"), 10),
    "CURIOSITY_DEEP_DIVE_MIN_SCORE":       (("curiosity_search", "trigger_min_score"), 7.5),
    "CURIOSITY_DEEP_DIVE_PROB":            (("curiosity_search", "prob_trigger"), 0.3),
    "CURIOSITY_DEEP_DIVE_COOLDOWN_MINUTES":(("curiosity_search", "cooldown_minutes"), 120),

    # 心理分析引擎
    "PSYCHO_ENGINE_ENABLED":            (("psycho_engine", "enabled"), True),
    "PSYCHO_DEEP_ANALYZE_INTERVAL":     (("psycho_engine", "deep_analyze_interval_videos"), 100),
    "PSYCHO_HEURISTIC_UPDATE_INTERVAL": (("psycho_engine", "heuristic_update_interval"), 15),
    "PSYCHO_COCOON_WARNING_THRESHOLD":  (("psycho_engine", "cocoon_warning_threshold"), 0.35),
    "PSYCHO_RECOMMEND_PROB":            (("psycho_engine", "recommend_prob_per_round"), 0.08),
    "PSYCHO_MIN_VIEWS_BEFORE_RECOMMEND":(("psycho_engine", "min_views_before_recommend"), 10),
    "PSYCHO_AVERSION_BLOCK_SCORE":      (("psycho_engine", "aversion_score_block_threshold"), 0.7),
    "PSYCHO_AVERSION_WARN_SCORE":       (("psycho_engine", "aversion_score_warn_threshold"), 0.4),

    # 系统
    "SUBTITLE_STRICT_CHECK": (("subtitle_strict_check", "enabled"), False),
    "QUIET_MODE":            (("system", "quiet_mode"), False),
}

# 特殊处理的 getter：需要回退逻辑或额外计算
def _get_vision_api_key():
    val = config.get("api", {}).get("vision_api_key")
    if val:
        return val
    return get_config_or_env("api", "unified_api_key", "BILI_AI_API_KEY")

def _get_vision_base_url():
    val = config.get("api", {}).get("vision_base_url")
    if val:
        return val
    return get_config_or_env("api", "unified_base_url", "BILI_AI_BASE_URL")

def _get_fallback_models():
    return config.get("fallback_models", {})

def _get_fallback_model_chat():
    return config.get("fallback_models", {}).get("chat", "")

def _get_fallback_model_vision():
    return config.get("fallback_models", {}).get("vision", "")

def _get_fallback_model_fast():
    return config.get("fallback_models", {}).get("fast", "")

_SPECIAL_GETTERS = {
    "VISION_API_KEY": _get_vision_api_key,
    "VISION_BASE_URL": _get_vision_base_url,
    "FALLBACK_MODELS": _get_fallback_models,
    "FALLBACK_MODEL_CHAT": _get_fallback_model_chat,
    "FALLBACK_MODEL_VISION": _get_fallback_model_vision,
    "FALLBACK_MODEL_FAST": _get_fallback_model_fast,
}

# __all__ 让 from module import * 能够触发 __getattr__ 获取动态属性
__all__ = (list(_CONFIG_PATHS.keys()) +
           list(_SPECIAL_GETTERS.keys()) +
           ["BASE_DIR", "DATA_DIR", "CONFIG_FILE", "BOT_LOCK_FILE",
            "BACKUP_DIR", "BACKUP_FILE", "COOKIE_FILE", "INTERESTS_FILE",
            "COMMENT_LOG_FILE", "PRIVATE_MESSAGE_LOG_FILE", "PRIVATE_CONTEXT_FILE",
            "USER_PROFILES_FILE", "PERSONAS_FILE", "MOOD_STATE_FILE",
            "BOT_DIARY_FILE", "SELF_EVOLUTION_FILE", "AGENT_SKILL_LOG_FILE",
            "SEARCH_HISTORY_FILE", "RUNTIME_STATE_FILE", "JOURNAL_FILE",
            "MEMORY_FILE", "HISTORY_VIDEOS_FILE", "KNOWLEDGE_BASE_DIR",
            "DRY_GOODS_DIR", "LEARNING_LOG_FILE", "KB_METADATA_FILE",
            "DEFAULT_CONFIG",
            # 工具函数（需显式列入 __all__ 才能在 from module import * 中使用）
            "save_search_history"])

# 删除静态变量，让 __getattr__ 接管
for _name in list(_CONFIG_PATHS.keys()):
    try:
        del sys.modules[__name__].__dict__[_name]
    except (KeyError, AttributeError):
        pass

def __getattr__(name):
    """Python 3.7+ 模块级动态属性：每次访问时实时从 config 读取。"""
    # 优先检查特殊 getter
    getter = _SPECIAL_GETTERS.get(name)
    if getter is not None:
        return getter()
    # 检查配置路径映射
    path_info = _CONFIG_PATHS.get(name)
    if path_info is not None:
        keys = path_info[0]
        default = path_info[1]
        env_var = path_info[2] if len(path_info) > 2 else None
        if env_var is not None:
            return get_config_or_env(keys[0], keys[1], env_var)
        # 普通嵌套读取
        d = config
        for k in keys:
            if isinstance(d, dict):
                d = d.get(k, default)
            else:
                return default
        return d if d is not None else default
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

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

# [FIX] 以上所有 config 派生变量已改为模块级 __getattr__ 动态属性，
# 见文件顶部的 _CONFIG_PATHS 映射表和 __getattr__ 函数。
# 旧静态赋值已删除，NO_HUMAN_DELAY 等变量现在每次访问时实时从 config 字典读取。

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
