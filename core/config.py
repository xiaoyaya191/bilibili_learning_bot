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
from utils.display import _append_console_log, mask_secret, redact_sensitive_text
from core.user_data import (
    DATA_DIR as _USER_DATA_DIR,
    HIGHLIGHTS_DIR as _USER_HIGHLIGHTS_DIR,
    KNOWLEDGE_BASE_DIR as _USER_KNOWLEDGE_BASE_DIR,
    USER_DATA_DIR as _USER_DATA_ROOT,
    ensure_user_data_dir,
)

# ===== 路径常量 =====
# BASE_DIR is source code only. All user-specific data is stored outside the project.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_DATA_DIR = str(ensure_user_data_dir())
DATA_DIR = str(_USER_DATA_DIR)
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
KNOWLEDGE_BASE_DIR = str(_USER_KNOWLEDGE_BASE_DIR)
HIGHLIGHTS_DIR = str(_USER_HIGHLIGHTS_DIR)

os.makedirs(DATA_DIR, exist_ok=True)

# ===== 知识库目录解析 =====
# 支持通过 config.json 的 knowledge_base_dir / knowledge.base_dir 自定义知识库目录，
# 未配置时回退到默认的 BASE_DIR/KnowledgeBase。
def resolve_knowledge_base_dir(cfg=None):
    """从配置解析知识库目录；未配置回退默认 KnowledgeBase。"""
    if cfg is None:
        cfg = config
    if cfg and isinstance(cfg, dict):
        kb = cfg.get("knowledge_base_dir") or cfg.get("knowledge", {}).get("base_dir")
        if kb:
            return os.path.join(BASE_DIR, kb) if not os.path.isabs(kb) else kb
    return KNOWLEDGE_BASE_DIR

# ===== 敏感词加密 =====
CIPHER_KEY_FILE = os.path.join(USER_DATA_DIR, ".cipher_key")

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

# ===== 厂商预设（内置官方 OpenAI 兼容格式）=====
# 默认就是 OpenAI 兼容（/v1/chat/completions），各厂商填入其官方 base_url 与默认模型名。
# 选了预设 = 自动填好 Base URL + 思考/视觉/快速模型；API Key 仍需用户自己填。
# 厂商会调整模型名、可用区域和计费；预设提供官方兼容端点的起点，
# 实际可用模型始终以用户厂商控制台中的模型列表为准。
PROVIDER_PRESETS = {
    "openai": {
        "name": "OpenAI 兼容 (自定义/其他)",
        "chat": "gpt-4o", "vision": "gpt-4o", "fast": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1", "format": "openai",
        "note": "通用 OpenAI 兼容格式，适用于任何兼容 /v1/chat/completions 的服务（本地 Ollama、vLLM、第三方中转等）。",
    },
    "deepseek": {
        "name": "DeepSeek 官网",
        "chat": "deepseek-v4-flash", "vision": "deepseek-v4-flash", "fast": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/v1", "format": "openai",
        "note": "DeepSeek 官方 API。base_url 用 https://api.deepseek.com 或 https://api.deepseek.com/v1 均可（v1 与模型版本无关）。默认 deepseek-v4-flash（便宜快）；要更强推理用 deepseek-v4-pro；开启思考模式传 thinking=true。⚠️ deepseek-chat/deepseek-reasoner 将于 2026/07/24 弃用，请尽快切到 v4 系列。DeepSeek 暂无独立视觉模型，视觉/图片任务可能不支持。",
    },
    "qwen": {
        "name": "阿里云百炼 (通义千问 Qwen)",
        "chat": "qwen-plus", "vision": "qwen-vl-max", "fast": "qwen-turbo",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "format": "openai",
        "note": "百炼 DashScope OpenAI 兼容端点。视觉模型可用 qwen-vl-max / qwen2.5-vl-72b-instruct；长文本用 qwen-long。",
    },
    "volcengine": {
        "name": "火山方舟 (豆包 Doubao)",
        "chat": "doubao-seed-1.6-250615", "vision": "doubao-vision-pro-250615", "fast": "doubao-seed-1.6-flash",
        "base_url": "https://ark.cn-beijing.volcesengine.com/api/v3", "format": "openai",
        "note": "火山方舟 Ark OpenAI 兼容端点；model 填你的推理接入点 ID（或豆包模型 ID，如 doubao-seed-1.6-250615）。",
    },
    "moonshot": {
        "name": "Moonshot (Kimi)",
        "chat": "moonshot-v1-8k", "vision": "moonshot-v1-8k", "fast": "moonshot-v1-8k",
        "base_url": "https://api.moonshot.cn/v1", "format": "openai",
        "note": "Kimi 开放平台，OpenAI 兼容。",
    },
    "zhipu": {
        "name": "智谱 AI (GLM)",
        "chat": "glm-4-plus", "vision": "glm-4v-plus", "fast": "glm-4-flash",
        "base_url": "https://open.bigmodel.cn/api/paas/v4", "format": "openai",
        "note": "智谱 BigModel OpenAI 兼容端点。",
    },
    "openrouter": {"name": "OpenRouter", "chat": "openai/gpt-4.1-mini", "vision": "openai/gpt-4.1-mini", "fast": "openai/gpt-4.1-mini", "base_url": "https://openrouter.ai/api/v1", "format": "openai", "note": "聚合模型平台；模型名以 OpenRouter 模型列表为准。"},
    "groq": {"name": "GroqCloud", "chat": "llama-3.3-70b-versatile", "vision": "meta-llama/llama-4-scout-17b-16e-instruct", "fast": "llama-3.1-8b-instant", "base_url": "https://api.groq.com/openai/v1", "format": "openai", "note": "Groq 官方 OpenAI 兼容端点。"},
    "together": {"name": "Together AI", "chat": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "vision": "meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo", "fast": "meta-llama/Llama-3.1-8B-Instruct-Turbo", "base_url": "https://api.together.xyz/v1", "format": "openai", "note": "Together AI 官方 OpenAI 兼容端点。"},
    "fireworks": {"name": "Fireworks AI", "chat": "accounts/fireworks/models/llama-v3p3-70b-instruct", "vision": "accounts/fireworks/models/qwen2-vl-72b-instruct", "fast": "accounts/fireworks/models/llama-v3p1-8b-instruct", "base_url": "https://api.fireworks.ai/inference/v1", "format": "openai", "note": "Fireworks 官方 OpenAI 兼容端点。"},
    "mistral": {"name": "Mistral AI", "chat": "mistral-large-latest", "vision": "pixtral-large-latest", "fast": "ministral-8b-latest", "base_url": "https://api.mistral.ai/v1", "format": "openai", "note": "Mistral 官方 OpenAI 兼容端点。"},
    "cohere": {"name": "Cohere", "chat": "command-a-03-2025", "vision": "command-a-vision-07-2025", "fast": "command-r7b-12-2024", "base_url": "https://api.cohere.com/compatibility/v1", "format": "openai", "note": "Cohere OpenAI compatibility API；请以控制台可用模型为准。"},
    "xai": {"name": "xAI (Grok)", "chat": "grok-3-mini", "vision": "grok-2-vision-1212", "fast": "grok-3-mini", "base_url": "https://api.x.ai/v1", "format": "openai", "note": "xAI 官方 OpenAI 兼容端点。"},
    "gemini": {"name": "Google Gemini", "chat": "gemini-2.5-pro", "vision": "gemini-2.5-pro", "fast": "gemini-2.5-flash", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "format": "openai", "note": "Google Gemini 的 OpenAI 兼容端点。"},
    "perplexity": {"name": "Perplexity", "chat": "sonar-pro", "vision": "sonar-pro", "fast": "sonar", "base_url": "https://api.perplexity.ai", "format": "openai", "note": "Perplexity 官方 OpenAI 兼容端点，适合联网检索。"},
    "cerebras": {"name": "Cerebras", "chat": "llama-3.3-70b", "vision": "llama-3.2-90b-vision", "fast": "llama3.1-8b", "base_url": "https://api.cerebras.ai/v1", "format": "openai", "note": "Cerebras 官方 OpenAI 兼容端点。"},
    "sambanova": {"name": "SambaNova Cloud", "chat": "Meta-Llama-3.3-70B-Instruct", "vision": "Llama-3.2-90B-Vision-Instruct", "fast": "Meta-Llama-3.1-8B-Instruct", "base_url": "https://api.sambanova.ai/v1", "format": "openai", "note": "SambaNova 官方 OpenAI 兼容端点。"},
    "nvidia_nim": {"name": "NVIDIA NIM", "chat": "meta/llama-3.3-70b-instruct", "vision": "microsoft/phi-3.5-vision-instruct", "fast": "meta/llama-3.1-8b-instruct", "base_url": "https://integrate.api.nvidia.com/v1", "format": "openai", "note": "NVIDIA API Catalog/NIM OpenAI 兼容端点。"},
    "deepinfra": {"name": "DeepInfra", "chat": "meta-llama/Meta-Llama-3.3-70B-Instruct", "vision": "meta-llama/Llama-3.2-90B-Vision-Instruct", "fast": "meta-llama/Meta-Llama-3.1-8B-Instruct", "base_url": "https://api.deepinfra.com/v1/openai", "format": "openai", "note": "DeepInfra OpenAI 兼容端点。"},
    "novita": {"name": "Novita AI", "chat": "meta-llama/llama-3.3-70b-instruct", "vision": "qwen/qwen2.5-vl-72b-instruct", "fast": "meta-llama/llama-3.1-8b-instruct", "base_url": "https://api.novita.ai/openai", "format": "openai", "note": "Novita AI OpenAI 兼容端点。"},
    "siliconflow": {"name": "硅基流动 SiliconFlow", "chat": "Qwen/Qwen2.5-72B-Instruct", "vision": "Qwen/Qwen2.5-VL-72B-Instruct", "fast": "Qwen/Qwen2.5-7B-Instruct", "base_url": "https://api.siliconflow.cn/v1", "format": "openai", "note": "硅基流动官方 OpenAI 兼容端点。"},
    "modelscope": {"name": "魔搭 ModelScope", "chat": "Qwen/Qwen2.5-72B-Instruct", "vision": "Qwen/Qwen2.5-VL-72B-Instruct", "fast": "Qwen/Qwen2.5-7B-Instruct", "base_url": "https://api-inference.modelscope.cn/v1", "format": "openai", "note": "魔搭社区推理 API；可用模型因账户和地区而异。"},
    "minimax": {"name": "MiniMax", "chat": "MiniMax-Text-01", "vision": "MiniMax-VL-01", "fast": "MiniMax-Text-01", "base_url": "https://api.minimax.chat/v1", "format": "openai", "note": "MiniMax 官方 OpenAI 兼容端点。"},
    "stepfun": {"name": "阶跃星辰 StepFun", "chat": "step-2-16k", "vision": "step-1v-8k", "fast": "step-1-8k", "base_url": "https://api.stepfun.com/v1", "format": "openai", "note": "阶跃星辰官方 OpenAI 兼容端点。"},
    "baichuan": {"name": "百川智能 Baichuan", "chat": "Baichuan4", "vision": "Baichuan4", "fast": "Baichuan3-Turbo", "base_url": "https://api.baichuan-ai.com/v1", "format": "openai", "note": "百川智能官方 OpenAI 兼容端点。"},
    "yi": {"name": "零一万物 Yi", "chat": "yi-lightning", "vision": "yi-vision", "fast": "yi-lightning", "base_url": "https://api.lingyiwanwu.com/v1", "format": "openai", "note": "零一万物官方 OpenAI 兼容端点。"},
    "infini": {"name": "无问芯穹 Infini", "chat": "Qwen2.5-72B-Instruct", "vision": "Qwen2.5-VL-72B-Instruct", "fast": "Qwen2.5-7B-Instruct", "base_url": "https://cloud.infini-ai.com/maas/v1", "format": "openai", "note": "无问芯穹 MaaS OpenAI 兼容端点。"},
    "ppinfra": {"name": "PPIO 派欧云", "chat": "Qwen2.5-72B-Instruct", "vision": "Qwen2.5-VL-72B-Instruct", "fast": "Qwen2.5-7B-Instruct", "base_url": "https://api.ppinfra.com/v3/openai", "format": "openai", "note": "PPIO 官方 OpenAI 兼容端点。"},
    "github_models": {"name": "GitHub Models", "chat": "openai/gpt-4.1-mini", "vision": "openai/gpt-4.1-mini", "fast": "openai/gpt-4.1-mini", "base_url": "https://models.github.ai/inference", "format": "openai", "note": "需要 GitHub Token；可用模型以 GitHub Models 目录为准。"},
    "ollama": {"name": "本机 Ollama", "chat": "qwen2.5:7b", "vision": "llama3.2-vision", "fast": "qwen2.5:3b", "base_url": "http://127.0.0.1:11434/v1", "format": "openai", "note": "本地 OpenAI 兼容服务；请先在 Ollama 拉取对应模型。"},
    "vllm": {"name": "本地 vLLM", "chat": "your-model-name", "vision": "your-vision-model", "fast": "your-model-name", "base_url": "http://127.0.0.1:8000/v1", "format": "openai", "note": "本地 vLLM 默认服务地址；模型名必须与启动参数一致。"},
    "lmstudio": {"name": "本机 LM Studio", "chat": "local-model", "vision": "local-model", "fast": "local-model", "base_url": "http://127.0.0.1:1234/v1", "format": "openai", "note": "LM Studio Local Server 的常用 OpenAI 兼容地址。"},
    "localai": {"name": "本机 LocalAI", "chat": "gpt-4", "vision": "gpt-4-vision-preview", "fast": "gpt-4", "base_url": "http://127.0.0.1:8080/v1", "format": "openai", "note": "LocalAI OpenAI 兼容地址；模型名取决于本机安装内容。"},
}

# ===== 默认配置模板 =====
POLITICAL_SAFETY_DEFAULT_KEYWORDS = [
    # This is an editable outbound-interaction blocklist, not a classifier or
    # a claim that every sensitive topic has been enumerated.
    # Chinese political figures and institutions
    "习近平", "毛泽东", "邓小平", "江泽民", "胡锦涛", "李克强", "温家宝",
    "赵紫阳", "李鹏", "薄熙来", "周永康", "王岐山", "刘少奇", "林彪",
    "中共中央", "中国共产党", "中共", "国务院", "中央军委", "政治局",
    # Taiwan and cross-strait terms
    "台湾", "台独", "台湾独立", "中华民国", "两岸关系", "两岸统一", "统一台湾",
    "武统", "一国两制", "九二共识", "台湾问题", "台海", "中华民国政府",
    # Hong Kong, Xinjiang, Tibet and related separatist terms
    "香港", "反送中", "香港国安法", "港独", "新疆", "再教育营", "东突",
    "疆独", "西藏", "藏独", "达赖", "法轮功", "法轮大法",
    # Historical and protest-related topics
    "六四", "天安门事件", "八九民运", "文化大革命", "反右运动", "大跃进",
    "白纸革命", "乌鲁木齐中路", "非法集会", "暴力抗议", "政治运动",
    # International political figures and conflicts
    "特朗普", "拜登", "普京", "泽连斯基", "内塔尼亚胡", "俄乌战争",
    "以色列", "巴勒斯坦", "加沙", "北约", "制裁",
    # Explicit political and extremist language
    "政治敏感", "政治人物", "政治事件", "政治地区", "分裂主义", "极端主义",
    "恐怖主义", "煽动暴力", "政党攻击", "选举操纵", "仇恨言论", "辱华",
    "靖国神社", "民族主义", "独裁",
]

PROMPT_INJECTION_DEFAULT_TERMS = [
    "system", "system prompt", "developer message", "提示词", "系统提示",
    "忽略之前指令", "越狱", "jailbreak", "开发者模式", "管理模式",
    "超级用户", "超级管理员", "管理员", "切换模式", "内部设定",
]

DEFAULT_CONFIG = {
    "api": {
        "unified_api_key": "", "max_retries": 3, "fallback_retries": 2,
        "unified_base_url": "",
        "model_brain": "",
        "model_vision": "",
        "model_html": "",
        "vision_api_key": "",
        "vision_base_url": ""
    },
    "model_presets": PROVIDER_PRESETS,
    "active_preset": "",
    "project_info": {
        "name": "Bilibili Learning Bot",
        "summary": "本地运行的 B 站智能学习与互动工作台",
        "homepage": "https://bxya.app/",
        "repository": "https://github.com/xiaoyaya191/bilibili_learning_bot",
        "license": "", "contact": "", "qq_group_url": "https://qun.qq.com/join.html?gc=1056941856"
    },
    "interaction": {
        "coin_threshold": 8.0, "fav_threshold": 8.5, "interest_threshold": 6.5,
        "learn_min_score": 6.0, "learn_min_duration_seconds": 60,
        "max_coins_daily": 2, "max_energy": 100,
        "prob_reply_trigger": 0.15, "prob_coin": 0.25, "prob_fav": 0.8,
        "prob_like_solo": 0.5, "prob_comment_others": 0.3,
        "comment_check_interval": 300, "max_replies_per_check": 3,
        "random_enabled": True, "comment_check_enabled": True,
        "coin_cooldown_minutes": 0, "coin_max_per_hour": 0,
        "comment_reply_three_actions": {
            "enabled": True, "like": True, "coin": True, "favorite": True
        }
    },
    "energy": {
        "energy_recovery_min": 5, "energy_recovery_max": 10,
        "rounds_min": 3, "rounds_max": 10,
        "round_interval_min": 60, "round_interval_max": 180,
        "video_interval_min": 1, "video_interval_max": 5
    },
    "persona": {"active_persona": "默认人格", "prompt_name": "AI小助手", "self_description": ""},
    "mood": {
        "default_mood": "平静", "mood_volatility": 1.0,
        "random_enabled": False, "random_interval_minutes": 5,
        "custom_enabled": False, "custom_mood": ""
    },
    "video": {
        "mode": "smart", "browse_mode": "candidate_review", "max_duration_seconds": 900, "frame_count": 12,
        "download_interest_threshold": 7.0, "download_dir": "",
        "delete_video_after_understand": True,         "filter_mode": "cover_and_title",
        "frame_note_mode": "visual_note",
        "visual_note_frame_interval": 6,
        "visual_note_max_frames": 240,
        "visual_note_grid_cols": 3,
        "visual_note_grid_rows": 3,
        "candidate_pool_size": 20,
        "quality": "best",  # 下载画质: best=自动最高/1080p/720p/480p/360p
        "custom_video_prompt": "请完整覆盖视频全过程，像教程/部署文档一样逐步讲解，保留关键细节、命令、参数、配置和截图，不要省略步骤。"
    },
    "vision": {
        # Disabled by default because many OpenAI-compatible text endpoints do
        # not accept image_url content blocks. Users can opt in after choosing
        # a vision-capable provider/model.
        "multimodal_enabled": False,
        "cover_enabled": True, "frames_enabled": True, "comment_images_enabled": True,
        "analyze_frames_with_sufficient_subtitles": False,
        "max_comment_images": 5, "frame_count": 8,
        "smart_frame_enabled": False, "smart_frame_min": 10, "smart_frame_max": 60
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
        "max_replies_per_check": 3, "only_recent_seconds": 900,
        "agent": {
            "enabled": True,
            "allow_account_actions": True,
            "allow_social_follow_actions": True,
            "allow_proactive_social_follow": True,
            "social_follow_daily_limit": 2,
            "sender_public_context_enabled": True,
            "sender_dynamics_enabled": True,
            "sender_public_context_refresh_hours": 12,
            "burst_merge_enabled": True,
            "burst_merge_window_seconds": 3,
            "coin_reserve": 5,
            "coin_abundant_threshold": 50,
        },
    },
    "per_video_check": {
        "enabled": True,
        "check_at_notifications": True,
        "check_private_messages": True,
        "check_own_comments": True,
        "max_at_per_check": 5,
        "cooldown_seconds": 10,
    },
    "approval_review": {
        "enabled": True,
        "action_types": {
            "video_like": True, "follow_up": True, "send_danmaku": True,
            "public_comment": True, "private_reply": True, "coin": True,
            "favorite": True, "knowledge_write": False, "file_export": False
        }
    },
    "up_learning": {
        "per_video_timeout_seconds": 600
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
    "prompt_injection": {
        "enabled": True,
        "custom_terms": PROMPT_INJECTION_DEFAULT_TERMS.copy(),
    },
    "diary": {
        "enabled": False, "auto_enabled": False, "auto_interval_minutes": 60,
        "min_events_for_auto": 3
    },
    "self_evolution": {
        "enabled": False, "auto_enabled": False, "reflect_interval_events": 8,
        "min_events_for_reflect": 3, "auto_apply": True
    },
    "agent": {
        "enabled": True, "auto_enabled": True, "max_steps_per_plan": 5,
        "max_search_results": 8, "max_videos_per_plan": 5,
        "auto_min_score": 7.5, "cooldown_minutes": 60,
        "deep_learning_enabled": True, "deep_learning_max_videos": 2,
        "deep_learning_timeout_seconds": 180,
    },
    "learning_workflow": {
        "read_comments": True,
        "read_danmaku": True,
    },
    "engagement": {
        "recognize_calls_to_action": True,
        "allow_keyword_comment_campaigns": False,
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
        "max_learned_videos": 0,
        "max_duration_minutes": 0,
        "completion_action": "stop",
    },
    "revisit": {
        "enabled": True, "prob_revisit": 0.25, "revisit_cooldown_minutes": 15,
        "min_score": 7.5, "max_per_video": 2, "per_video_cooldown_minutes": 240
    },
    "active_chat": {
        "enabled": False, "prob_initiate": 0.06, "cooldown_minutes": 45,
        "max_initiate_per_session": 3, "quiet_hours_enabled": True,
        "quiet_start_hour": 22, "quiet_end_hour": 8,
        "whitelist_enabled": False, "whitelist_uids": []
    },
    "owner_share": {
        "enabled": False,
        "owner_bili_uid": "",
        "share_learned": True,
        "share_fun": True,
        "min_score": 7.5,
        "probability": 0.35,
        "extra_message_probability": 0.65,
        "daily_limit": 3,
        "cooldown_minutes": 30,
        "custom_prompt": "",
    },
    "local_favorites": {
        "auto_collect_enabled": True,
        "min_score": 8.0,
        "folder_name": "AI 精选",
        "require_interest_match": True,
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
    "chapter_lock": {
        "enabled": True,
        "min_duration_minutes": 15,
        "model": "auto",
        "max_chapters_per_video": 12,
        "chapter_strategy": "ai_split"
    },
        "mindmap": {
            "enabled": True,
            "auto_generate": True,
            "output_dir": "MindMaps/",
            "theme": "default",
            "max_depth": 3,
            "inline_assets": False,
            "include_images": True,
            "prompt": ""
        },
    "document_export": {
        "enabled": True,
        "folder_name": "Word",
        "output_dir": "Word/",
        "formats": ["docx"],
        "prompt": ""
    },
    "export": {"formats": ["markdown", "mindmap"], "auto_export_on_save": True},
    "note_style": {
        "enabled": True,
        "active_style": "balanced",
        "styles": {
            "academic": {"name": "学术严谨", "prompt_suffix": "请使用学术论文风格，引用原文数据，标注时间戳。", "output_language": "zh-CN"},
            "conversational": {"name": "口语化", "prompt_suffix": "请用通俗易懂的口语化表达，像朋友聊天一样解释概念。", "output_language": "zh-CN"},
            "key_points": {"name": "重点提取", "prompt_suffix": "只提取核心观点和关键数据，忽略铺垫和废话，用 bullet points。", "output_language": "zh-CN"},
            "balanced": {"name": "平衡模式", "prompt_suffix": "结构清晰、重点突出、适当保留细节。", "output_language": "zh-CN"}
        }
    },
    "rag_qa": {"enabled": False, "model": "auto", "max_context_chunks": 5, "enable_function_calling": True, "sources": ["knowledge_base", "single_video"]},
    "version_history": {"enabled": False, "max_versions": 5, "diff_on_regenerate": True},
    "platform_adapter": {
        "enabled": True,
        "ui_platforms": ["bilibili", "youtube", "douyin", "kuaishou", "web", "local"],
        "supported": ["bilibili", "youtube", "douyin", "kuaishou", "web", "local"],
        "prefer_platform_subtitles": True,
        "subtitle_langs": ["zh-Hans", "zh", "zh-CN", "en"],
        "download_format": "bv*+ba/best/best",
        "proxy": "",
        "allow_web_local_files": False,
    },
    "network": {
        "proxy": {"enabled": False, "url": ""},
    },
    "browser_extension": {"enabled": False, "port": 9527, "subtitle_direct_capture": True},
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
    },
    "ob": {
        "enabled": False,
        "base_url": "http://127.0.0.1:8420",
        "auto_launch": False,
        "launch_command": "openbiliclaw serve",
        "launch_cwd": "",
        "health_check_timeout_seconds": 5,
        "recommendation_fetch_limit": 20,
        "feedback_enabled": True,
        "event_report_enabled": True,
        "profile_sync_enabled": True,
        "explore_mode_fallback": True,
        "explore_pools": ["科技", "编程", "物理", "数学", "历史", "哲学"],
        "curiosity_keyword_ttl_hours": 24,
        "audit_enabled": True,
        "ab_test_enabled": True,
        "ab_window_size": 200
    }
}


DEFAULT_CONFIG["reply_safety"]["blocked_keywords"] = POLITICAL_SAFETY_DEFAULT_KEYWORDS.copy()


def normalize_config(cfg):
    """归一化旧字段，避免不同入口读写的 API 配置字段漂移。"""
    if not isinstance(cfg, dict):
        cfg = {}
    api_cfg = cfg.setdefault("api", {})
    if isinstance(api_cfg, dict):
        legacy_pairs = {
            "api_key": "unified_api_key",
            "base_url": "unified_base_url",
            "api_base": "unified_base_url",
            "model": "model_brain",
        }
        for old_key, new_key in legacy_pairs.items():
            if not api_cfg.get(new_key) and api_cfg.get(old_key):
                api_cfg[new_key] = api_cfg.get(old_key)
    # Diary and persona evolution are still internal preview features.  Keep
    # them disabled even when an older web page submits a full, stale config.
    # This prevents background jobs from running or emitting preview-only logs.
    diary = cfg.setdefault("diary", {})
    if isinstance(diary, dict):
        diary["enabled"] = False
        diary["auto_enabled"] = False
    evolution = cfg.setdefault("self_evolution", {})
    if isinstance(evolution, dict):
        evolution["enabled"] = False
        evolution["auto_enabled"] = False
        evolution["auto_apply"] = False
    return cfg


# ===== 配置加载/保存 =====
def load_config():
    """加载配置文件，合并默认值，解密敏感词"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            cfg = normalize_config(cfg)
            # 清洗脱敏占位符：'[已隐藏]' 视为未配置（避免被当真实 key 使用）
            _api = cfg.setdefault("api", {})
            for _k in ("unified_api_key", "vision_api_key"):
                if _api.get(_k) == "[已隐藏]":
                    _api[_k] = ""
            _fb = cfg.setdefault("fallback_provider", {})
            if _fb.get("api_key") == "[已隐藏]":
                _fb["api_key"] = ""
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
        cfg = normalize_config(cfg)
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
        # 知识库目录可能随配置变化，重新解析（供 core.config 动态访问者使用）
        global KNOWLEDGE_BASE_DIR
        KNOWLEDGE_BASE_DIR = resolve_knowledge_base_dir(cfg)
        os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
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


# ===== JSON 辅助 =====
def load_json_file(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 加载 JSON 文件失败: {path} - {e}", flush=True)
    return default.copy() if isinstance(default, dict) else default


def save_json_file(path, data):
    """原子写入 JSON 文件（tmp+replace 防止断电损坏）"""
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[WARN] 保存 JSON 文件失败: {path} - {e}", flush=True)
        return False


# 加载当前配置（模块导入时自动加载）
config = load_config()

# 根据配置解析知识库目录（支持 knowledge_base_dir / knowledge.base_dir 自定义），
# 覆盖上面的默认回退值，使所有 `from core.config import KNOWLEDGE_BASE_DIR` 获取到正确路径。
KNOWLEDGE_BASE_DIR = resolve_knowledge_base_dir(config)
os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)

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
    "DIARY_ENABLED":         (("diary", "enabled"), False),
    "DIARY_AUTO_ENABLED":    (("diary", "auto_enabled"), False),
    "EVOLUTION_ENABLED":     (("self_evolution", "enabled"), False),
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
    "SESSION_MAX_LEARNED_VIDEOS": (("session", "max_learned_videos"), 0),
    "SESSION_MAX_DURATION_MINUTES": (("session", "max_duration_minutes"), 0),
    "SESSION_COMPLETION_ACTION": (("session", "completion_action"), "stop"),
    "BEHAVIOR_COMMENT_USER_COOLDOWN_MINUTES": (("behavior", "comment_user_cooldown_minutes"), 60),
    "BEHAVIOR_PRIVATE_REPLY_COOLDOWN_MINUTES": (("behavior", "private_reply_cooldown_minutes"), 3),
    "OB_ENABLED":              (("ob", "enabled"), False),
    "OB_BASE_URL":             (("ob", "base_url"), "http://127.0.0.1:8420"),
    "OB_AUTO_LAUNCH":          (("ob", "auto_launch"), False),
    "OB_LAUNCH_CWD":           (("ob", "launch_cwd"), ""),
    "OB_LAUNCH_COMMAND":       (("ob", "launch_command"), "openbiliclaw serve"),
    "OB_REC_FETCH_LIMIT":      (("ob", "recommendation_fetch_limit"), 20),
    "OB_FEEDBACK_ENABLED":     (("ob", "feedback_enabled"), True),
    "OB_EVENT_REPORT_ENABLED": (("ob", "event_report_enabled"), True),
    "OB_PROFILE_SYNC_ENABLED":     (("ob", "profile_sync_enabled"), True),
    "OB_CURIOSITY_TTL_HOURS": (("ob", "curiosity_keyword_ttl_hours"), 24),
    "OB_AUDIT_ENABLED":       (("ob", "audit_enabled"), True),
    "OB_AB_TEST_ENABLED":     (("ob", "ab_test_enabled"), True),
    "OB_AB_WINDOW_SIZE":      (("ob", "ab_window_size"), 200),
}

_SPECIAL_GETTERS = {}

def _get_vision_api_key():
    val = config.get("api", {}).get("vision_api_key")
    if val and val != "[已隐藏]":
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
           "normalize_config", "load_config", "save_config", "get_bot_name",
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
    _append_console_log(f"[{timestamp}][{level}] {redact_sensitive_text(msg)}")
