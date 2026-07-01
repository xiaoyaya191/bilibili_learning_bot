from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "Data"
CONFIG_FILE = DATA_DIR / "config.json"


DEFAULT_MODELS = {
    "chat": "gpt-4.1-mini",
    "vision": "gpt-4.1-mini",
    "image": "gpt-image-1",
    "fast": "gpt-4.1-nano",
    "embedding": "text-embedding-3-small",
}


DEFAULT_FALLBACK_MODELS = {
    "chat": "gpt-4.1-nano",
    "vision": "gpt-4.1-mini",
    "image": "gpt-image-1",
    "fast": "gpt-4.1-nano",
    "embedding": "text-embedding-3-small",
}


MODEL_PRICES = {
    "gpt-4.1-mini": 0.0,
    "gpt-4.1-nano": 0.0,
    "gpt-image-1": 0.0,
    "text-embedding-3-small": 0.0,
}


@dataclass
class BotSettings:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    models: dict[str, str] = field(default_factory=lambda: DEFAULT_MODELS.copy())
    fallback_models: dict[str, str] = field(default_factory=lambda: DEFAULT_FALLBACK_MODELS.copy())
    panel_password: str = ""
    owner_mid: str = ""
    max_daily_actions: int = 20
    dry_run: bool = True
    allow_comment: bool = False
    allow_like: bool = False
    allow_coin: bool = False
    allow_favorite: bool = False
    allow_dynamic: bool = False
    video_mode: str = "smart"
    video_max_duration_seconds: int = 900
    video_frame_count: int = 12
    video_download_interest_threshold: float = 7.0
    video_download_dir: str = ""
    video_delete_after_understand: bool = True
    ai_marker: str = "（内容由AI生成并由AI回复）"
    enable_web_search: bool = True
    enable_proactive: bool = True
    enable_dynamic: bool = True
    enable_personality_evolution: bool = True
    enable_mood: bool = True
    enable_affection: bool = True
    enable_embedding_memory: bool = True
    comment_poll_interval: int = 300
    max_replies_per_check: int = 3
    proactive_video_count: int = 3
    proactive_comment_count: int = 2
    proactive_times_count: int = 2
    sleep_start: str = "02:00"
    sleep_end: str = "08:00"

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.models.get("chat"))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_runtime_config() -> dict[str, Any]:
    DATA_DIR.mkdir(exist_ok=True)
    return _load_json(CONFIG_FILE)


def write_runtime_config(data: dict[str, Any]) -> None:
    _atomic_write_json(CONFIG_FILE, data)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        tmp.write("\n")
        temp_name = tmp.name
    Path(temp_name).replace(path)


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
    return target


def update_runtime_config(patch: dict[str, Any]) -> dict[str, Any]:
    data = read_runtime_config()
    _deep_update(data, patch)
    write_runtime_config(data)
    return data


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y", "enabled", "是", "开"}
    return bool(value)


def _int(value: Any, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if min_value is not None:
        result = max(min_value, result)
    if max_value is not None:
        result = min(max_value, result)
    return result


def _float(value: Any, default: float, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if min_value is not None:
        result = max(min_value, result)
    if max_value is not None:
        result = min(max_value, result)
    return result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_settings() -> BotSettings:
    """从统一配置源 (core.config) 构建 BotSettings。
    
    不再独立读取 config.json，而是使用 core.config 已加载的配置，
    确保所有模块共享同一份配置。
    """
    import core.config as _root_cfg
    raw = _root_cfg.config
    DATA_DIR.mkdir(exist_ok=True)
    api = _dict(raw.get("api"))
    # 回退：如果 config dict 未同步，从模块级属性取
    if not api.get("unified_api_key"):
        api["unified_api_key"] = getattr(_root_cfg, "UNIFIED_API_KEY", "")
    if not api.get("unified_base_url"):
        api["unified_base_url"] = getattr(_root_cfg, "UNIFIED_BASE_URL", "")
    if not api.get("model_brain"):
        api["model_brain"] = getattr(_root_cfg, "MODEL_BRAIN", "")
    if not api.get("model_vision"):
        api["model_vision"] = getattr(_root_cfg, "MODEL_VISION", "")
    automation = _dict(raw.get("automation"))
    web = _dict(raw.get("web"))
    video = _dict(raw.get("video"))
    behavior = _dict(raw.get("behavior"))

    models = DEFAULT_MODELS.copy()
    if api.get("model_brain"):
        models["chat"] = api["model_brain"]
        models["fast"] = api["model_brain"]
    if api.get("model_vision"):
        models["vision"] = api["model_vision"]
    models.update(_dict(raw.get("models")))

    fallback_models = DEFAULT_FALLBACK_MODELS.copy()
    if api.get("model_brain"):
        fallback_models["chat"] = api["model_brain"]
        fallback_models["fast"] = api["model_brain"]
    if api.get("model_vision"):
        fallback_models["vision"] = api["model_vision"]
    fallback_models.update(_dict(raw.get("fallback_models")))

    video_mode = str(video.get("mode", "smart")).strip().lower()
    if video_mode not in {"subtitle", "frames", "hybrid", "smart"}:
        video_mode = "smart"

    return BotSettings(
        api_key=os.getenv("BILI_AI_API_KEY") or api.get("unified_api_key", ""),
        base_url=os.getenv("BILI_AI_BASE_URL") or api.get("unified_base_url") or "https://api.openai.com/v1",
        models={
            "chat": os.getenv("BILI_AI_MODEL_CHAT") or models["chat"],
            "vision": os.getenv("BILI_AI_MODEL_VISION") or models["vision"],
            "image": os.getenv("BILI_AI_MODEL_IMAGE") or models["image"],
            "fast": os.getenv("BILI_AI_MODEL_FAST") or models["fast"],
            "embedding": os.getenv("BILI_AI_MODEL_EMBEDDING") or models.get("embedding", DEFAULT_MODELS["embedding"]),
        },
        fallback_models={
            "chat": os.getenv("BILI_AI_MODEL_CHAT_FALLBACK") or fallback_models["chat"],
            "vision": os.getenv("BILI_AI_MODEL_VISION_FALLBACK") or fallback_models["vision"],
            "image": os.getenv("BILI_AI_MODEL_IMAGE_FALLBACK") or fallback_models["image"],
            "fast": os.getenv("BILI_AI_MODEL_FAST_FALLBACK") or fallback_models["fast"],
            "embedding": os.getenv("BILI_AI_MODEL_EMBEDDING_FALLBACK") or fallback_models.get("embedding", DEFAULT_FALLBACK_MODELS["embedding"]),
        },
        panel_password=os.getenv("BILI_LEARNING_PANEL_PASSWORD") or web.get("password", ""),
        owner_mid=str(_dict(raw.get("bilibili")).get("owner_mid", "")),
        max_daily_actions=_int(automation.get("max_daily_actions"), 20, 0, 1000),
        dry_run=_bool(automation.get("dry_run"), True),
        allow_comment=_bool(automation.get("allow_comment")),
        allow_like=_bool(automation.get("allow_like")),
        allow_coin=_bool(automation.get("allow_coin")),
        allow_favorite=_bool(automation.get("allow_favorite")),
        allow_dynamic=_bool(automation.get("allow_dynamic")),
        video_mode=video_mode,
        video_max_duration_seconds=_int(video.get("max_duration_seconds"), 900, 1, 24 * 3600),
        video_frame_count=_int(video.get("frame_count"), 12, 1, 60),
        video_download_interest_threshold=_float(video.get("download_interest_threshold"), 7.0, 0.0, 10.0),
        video_download_dir=str(video.get("download_dir", "")).strip(),
        video_delete_after_understand=_bool(video.get("delete_video_after_understand"), True),
        ai_marker=os.getenv("BILI_AI_MARKER") or str(behavior.get("ai_marker", "（内容由AI生成并由AI回复）")),
        enable_web_search=_bool(automation.get("enable_web_search"), True),
        enable_proactive=_bool(automation.get("enable_proactive"), True),
        enable_dynamic=_bool(automation.get("enable_dynamic"), True),
        enable_personality_evolution=_bool(automation.get("enable_personality_evolution"), True),
        enable_mood=_bool(automation.get("enable_mood"), True),
        enable_affection=_bool(automation.get("enable_affection"), True),
        enable_embedding_memory=_bool(automation.get("enable_embedding_memory"), True),
        comment_poll_interval=_int(automation.get("comment_poll_interval"), 300, 10, 24 * 3600),
        max_replies_per_check=_int(automation.get("max_replies_per_check"), 3, 0, 100),
        proactive_video_count=_int(automation.get("proactive_video_count"), 3, 0, 100),
        proactive_comment_count=_int(automation.get("proactive_comment_count"), 2, 0, 100),
        proactive_times_count=_int(automation.get("proactive_times_count"), 2, 0, 24),
        sleep_start=str(automation.get("sleep_start", "02:00")),
        sleep_end=str(automation.get("sleep_end", "08:00")),
    )


def public_config(settings: BotSettings) -> dict[str, Any]:
    return {
        "base_url": settings.base_url,
        "configured": settings.configured,
        "models": settings.models,
        "fallback_models": settings.fallback_models,
        "auth_required": bool(settings.panel_password),
        "owner_mid": settings.owner_mid,
        "dry_run": settings.dry_run,
        "permissions": {
            "comment": settings.allow_comment,
            "like": settings.allow_like,
            "coin": settings.allow_coin,
            "favorite": settings.allow_favorite,
            "dynamic": settings.allow_dynamic,
        },
        "video": {
            "mode": settings.video_mode,
            "max_duration_seconds": settings.video_max_duration_seconds,
            "frame_count": settings.video_frame_count,
            "download_interest_threshold": settings.video_download_interest_threshold,
            "download_dir": settings.video_download_dir,
            "delete_video_after_understand": settings.video_delete_after_understand,
        },
        "proactive": {
            "video_count": settings.proactive_video_count,
            "comment_count": settings.proactive_comment_count,
            "times_count": settings.proactive_times_count,
            "sleep_start": settings.sleep_start,
            "sleep_end": settings.sleep_end,
        },
        "features": {
            "web_search": settings.enable_web_search,
            "proactive": settings.enable_proactive,
            "dynamic": settings.enable_dynamic,
            "personality_evolution": settings.enable_personality_evolution,
            "mood": settings.enable_mood,
            "affection": settings.enable_affection,
            "embedding_memory": settings.enable_embedding_memory,
            "comment_poll_interval": settings.comment_poll_interval,
            "max_replies_per_check": settings.max_replies_per_check,
        },
        "ai_marker": settings.ai_marker,
    }
