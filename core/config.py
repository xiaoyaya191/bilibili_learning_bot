"""core/config.py — 配置加载与路径常量

从 start_cli.py 提取，避免循环依赖。
所有全局配置变量仍然在 start_cli.py 中定义，使用时 from core.config import 路径常量。
"""
import os
import sys
import json
import hashlib, base64, secrets
from colorama import Fore, Style
from utils.storage import get_backup_dir

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

# ===== 敏感词加密 =====
CIPHER_KEY_FILE = os.path.join(BASE_DIR, ".cipher_key")

def _get_or_create_cipher_key():
    """获取或生成加密密钥"""
    env_key = os.getenv("BILI_CIPHER_KEY")
    if env_key:
        return env_key.encode()
    if os.path.exists(CIPHER_KEY_FILE):
        with open(CIPHER_KEY_FILE, "r") as f:
            return f.read().strip().encode()
    key = secrets.token_hex(32).encode()
    try:
        with open(CIPHER_KEY_FILE, "w") as f:
            f.write(key.decode())
        os.chmod(CIPHER_KEY_FILE, 0o600)
    except OSError:
        pass
    return key

def _cipher_encrypt(plaintext: str, key: bytes = None) -> str:
    """加密字符串为base64"""
    if key is None:
        key = _get_or_create_cipher_key()
    data = plaintext.encode("utf-8")
    digest = hashlib.sha256(key).digest()
    encrypted = bytes([data[i] ^ digest[i % len(digest)] for i in range(len(data))])
    return base64.b64encode(encrypted).decode()

def _cipher_decrypt(ciphertext: str, key: bytes = None) -> str:
    """解密base64为原文"""
    if key is None:
        key = _get_or_create_cipher_key()
    try:
        encrypted = base64.b64decode(ciphertext)
        digest = hashlib.sha256(key).digest()
        decrypted = bytes([b ^ digest[i % len(digest)] for i, b in enumerate(encrypted)])
        return decrypted.decode("utf-8")
    except (ValueError, UnicodeDecodeError, Exception):
        return ciphertext  # fallback

os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)

# ===== 默认配置模板 =====
DEFAULT_CONFIG = {
    "api": {
        "unified_api_key": "",
        "unified_base_url": "",
        "model_brain": "",
        "model_vision": "",
        "model_html": "",
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
        "random_enabled": True,
        "coin_cooldown_minutes": 0, "coin_max_per_hour": 0
    },
    "energy": {
        "energy_recovery_min": 5, "energy_recovery_max": 10,
        "rounds_min": 3, "rounds_max": 10,
        "round_interval_min": 60, "round_interval_max": 180,
        "video_interval_min": 1, "video_interval_max": 5
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
        "cover_enabled": True, "frames_enabled": True, "comment_images_enabled": True,
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
            "fknIQYvm", "f3Tp", "f2rOQZ39", "fGXMQoHw", "fGXMQYnX",
            "f3TCQInsyfG9", "fkneQbb6", "fkjTTIzayc2U",
            "fF7oQoD2yMy7", "fkvJQZfs", "f2rOQbnqxe2F", "f3foQZTf",
            "f37DQor1", "c1fqQovk", "fGfDQ6XN", "clTMTKTE",
            "f3TeQajQ", "fELmTI7l", "c3H6QIv1", "fEHiQIvw",
            "fXrfTJDK", "f1/ZQoDe", "f1XlQInvxfeP", "f3nFTJDK",
            "fHnrQInC", "fk73QIrH", "fkrWTLr5yfyw", "f0bHQbjZyuKIB89H",
            "fGbWQq/nyfuUBe1d", "c2zlQaj2y9G5BfZf",
            "fEHiQqTEyMycButo", "fXnCQaj2", "ck/CQb7F",
            "f37DQ7jn", "fEncQ7jn", "cmb8Q7jn", "fWf1Q7jn",
            "fHvkTJ3l", "fEnLTJLH", "fUrHQq7I", "fkvJQq7I",
            "clzVQZzU", "f3foTavU", "clbQQqf1yfK8", "fFzVQ4jU",
            "fknzQaj2yMyDB9pX", "ckT3Qq/nyMycButo",
            "fVXNQI/RyMycButo", "c1jfQbvc", "fF7oTbPC"
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
    """加载配置文件，合并默认值，解密敏感词"""
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
            # 解密 blocked_keywords
            kw_list = cfg.get("reply_safety", {}).get("blocked_keywords", [])
            if kw_list and any(len(k) > 10 for k in kw_list):
                cfg["reply_safety"]["blocked_keywords"] = [
                    _cipher_decrypt(k) for k in kw_list
                ]
            return cfg
        except (OSError, json.JSONDecodeError):
            pass
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    """保存配置文件，加密敏感词（原子写入防崩溃损坏）"""
    try:
        # 加密 blocked_keywords 再存盘
        kw_list = cfg.get("reply_safety", {}).get("blocked_keywords", [])
        if kw_list and not all(k.startswith(("enc:", "===")) or len(k) < 3 for k in kw_list):
            cfg["reply_safety"]["blocked_keywords"] = [_cipher_encrypt(k) for k in kw_list]
        tmp = CONFIG_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        os.replace(tmp, CONFIG_FILE)
        # 存完后解密回内存，保持内存中明文
        if kw_list:
            cfg["reply_safety"]["blocked_keywords"] = kw_list
        return True
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 保存配置文件失败: {e}{Style.RESET_ALL}")
        return False


def get_bot_name():
    return config.get("persona", {}).get("prompt_name", "AI小助手")


def get_config_or_env(section, key, env_name):
    # 🔧 优先环境变量，其次配置文件，兜底空字符串
    val = os.getenv(env_name)
    if val is not None:
        return val
    return config.get(section, {}).get(key, "")


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
    """原子写入 JSON 文件（tmp+replace 防止断电损坏）"""
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


# 加载当前配置（模块导入时自动加载）
config = load_config()

# ===== 派生配置变量（供其他模块导入） =====
# [FIX] 改为 __getattr__ 动态属性，确保用户通过菜单修改配置后实时生效。
# 旧静态赋值已删除。所有变量每次访问时实时从 config 字典读取。

_CONFIG_PATHS = {
    "UNIFIED_API_KEY":       (("api", "unified_api_key"), None, "BILI_AI_API_KEY"),
    "UNIFIED_BASE_URL":      (("api", "unified_base_url"), None, "BILI_AI_BASE_URL"),
    "MODEL_BRAIN":           (("api", "model_brain"), None, "BILI_AI_MODEL_BRAIN"),
    "MODEL_VISION":          (("api", "model_vision"), None, "BILI_AI_MODEL_VISION"),
    "MODEL_HTML":            (("api", "model_html"), None, "BILI_AI_MODEL_HTML"),
    "VISION_API_KEY":        (("api", "vision_api_key"), None),  # 特殊：回退到 UNIFIED_API_KEY
    "VISION_BASE_URL":       (("api", "vision_base_url"), None),  # 特殊：回退到 UNIFIED_BASE_URL
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
    "PRIVATE_MESSAGE_ENABLED": (("private_message", "enabled"), True),
    "PRIVATE_MESSAGE_CHECK_INTERVAL": (("private_message", "check_interval"), 120),
    "DIARY_ENABLED":         (("diary", "enabled"), True),
    "DIARY_AUTO_ENABLED":    (("diary", "auto_enabled"), True),
    "EVOLUTION_ENABLED":     (("self_evolution", "enabled"), True),
    "AGENT_ENABLED":         (("agent", "enabled"), True),
    "AGENT_DIVE_MAX_VIDEOS": (("agent", "dive_max_videos"), 10),
    "AGENT_MAX_SEARCH_RESULTS":(("agent", "max_search_results"), 8),
    "AGENT_MAX_STEPS_PER_PLAN":(("agent", "max_steps_per_plan"), 5),
    "AGENT_MAX_VIDEOS_PER_PLAN":(("agent", "max_videos_per_plan"), 3),
    "UP_FOLLOW_ENABLED":     (("up_follow", "enabled"), True),
    "DANMAKU_ENABLED":       (("danmaku", "enabled"), True),
    "FALLBACK_MODELS":       (("fallback_models",), {}),
    "FALLBACK_PROVIDER_ENABLED": (("fallback_provider", "enabled"), False),
    "FALLBACK_PROVIDER_NAME":(("fallback_provider", "name"), "chatanywhere"),
    "PSYCHO_ENGINE_ENABLED": (("psycho_engine", "enabled"), True),
    "SESSION_MAX_VIDEOS":    (("session", "max_videos"), 0),
    "SESSION_MAX_DURATION_MINUTES": (("session", "max_duration_minutes"), 0),
    "BEHAVIOR_COMMENT_USER_COOLDOWN_MINUTES": (("behavior", "comment_user_cooldown_minutes"), 60),
    "BEHAVIOR_PRIVATE_REPLY_COOLDOWN_MINUTES": (("behavior", "private_reply_cooldown_minutes"), 3),
}

_SPECIAL_GETTERS = {}

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

_SPECIAL_GETTERS = {
    "VISION_API_KEY": _get_vision_api_key,
    "VISION_BASE_URL": _get_vision_base_url,
    "FALLBACK_MODELS": _get_fallback_models,
}

# __all__ 让 from module import * 能够触发 __getattr__ 获取动态属性
__all__ = (list(_CONFIG_PATHS.keys()) +
           list(_SPECIAL_GETTERS.keys()) +
           ["BASE_DIR", "DATA_DIR", "CONFIG_FILE", "BOT_LOCK_FILE",
            "BACKUP_DIR", "BACKUP_FILE", "COOKIE_FILE", "INTERESTS_FILE",
            "COMMENT_LOG_FILE", "PRIVATE_MESSAGE_LOG_FILE", "PRIVATE_CONTEXT_FILE",
            "USER_PROFILES_FILE", "PERSONAS_FILE", "MOOD_STATE_FILE",
            "BOT_DIARY_FILE", "SELF_EVOLUTION_FILE", "AGENT_SKILL_LOG_FILE",
            "RUNTIME_STATE_FILE", "KNOWLEDGE_BASE_DIR", "HIGHLIGHTS_DIR",
            "CIPHER_KEY_FILE", "DEFAULT_CONFIG", "config",
            "load_config", "save_config", "get_bot_name",
            "get_config_or_env", "mask_secret", "load_json_file",
            "save_json_file", "log"])

# 删除静态变量，让 __getattr__ 接管
for _name in list(_CONFIG_PATHS.keys()):
    try:
        del sys.modules[__name__].__dict__[_name]
    except (KeyError, AttributeError):
        pass

def __getattr__(name):
    """Python 3.7+ 模块级动态属性：每次访问时实时从 config 读取。"""
    getter = _SPECIAL_GETTERS.get(name)
    if getter is not None:
        return getter()
    path_info = _CONFIG_PATHS.get(name)
    if path_info is not None:
        keys = path_info[0]
        default = path_info[1]
        env_var = path_info[2] if len(path_info) > 2 else None
        if env_var is not None:
            return get_config_or_env(keys[0], keys[1], env_var)
        d = config
        for k in keys:
            if isinstance(d, dict):
                d = d.get(k, default)
            else:
                return default
        return d if d is not None else default
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")



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
