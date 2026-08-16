"""视频文案生成模块 — 复用项目配置的 AI 接口（OpenAI 兼容）生成口播稿/文案。"""

from __future__ import annotations

from typing import Any

import httpx

from core.config import load_config
from mcp_server.bili import fetch_material

STYLE_HINTS = {
    "口播": "口语化口播稿，自然、有节奏、有停顿感，像真人对着镜头说话，多用短句和设问。",
    "解说": "知识解说稿，逻辑清晰、层层递进，先抛问题再给答案，适合配画面讲解。",
    "种草": "种草安利稿，开头抓眼球、突出亮点与使用场景、结尾给行动号召。",
    "盘点": "盘点榜单稿，按序号逐条介绍，每条有记忆点，结尾总结升华。",
    "故事": "故事化文案，有起承转合、有冲突和反转，情绪饱满，适合剧情向视频。",
    "干货": "干货教程稿，步骤分明、要点突出，每步有具体操作和注意事项。",
}

DEFAULT_STYLE = "口播"


def _load_ai_settings() -> dict[str, str]:
    """从项目配置读取当前 AI 接口设置。"""
    cfg = load_config()
    api = cfg.get("api", {})
    base_url = (api.get("unified_base_url") or "").strip().rstrip("/")
    api_key = (api.get("unified_api_key") or "").strip()
    model = (api.get("model_brain") or "").strip()
    if not base_url or not api_key:
        raise RuntimeError("未配置 AI 接口（unified_base_url / unified_api_key），请先在面板配置")
    if not model:
        model = "deepseek-v4-flash"
    return {"base_url": base_url, "api_key": api_key, "model": model}


async def _chat(messages: list[dict[str, str]], temperature: float = 0.8) -> str:
    """调用 OpenAI 兼容接口。"""
    settings = _load_ai_settings()
    url = settings["base_url"] + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"AI 调用失败: {exc}") from exc
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"AI 返回格式异常: {data}") from exc


async def generate_script(
    url: str,
    style: str = DEFAULT_STYLE,
    target_words: int = 800,
    extra_hint: str = "",
) -> str:
    """根据视频素材生成视频文案/口播稿。

    - url: B 站视频链接
    - style: 文案风格（口播/解说/种草/盘点/故事/干货）
    - target_words: 目标字数
    - extra_hint: 额外要求（如目标受众、平台、语气）
    """
    style = style.strip() or DEFAULT_STYLE
    hint = STYLE_HINTS.get(style, STYLE_HINTS[DEFAULT_STYLE])
    material = await fetch_material(url, include_danmaku=True, include_comments=True)

    system = (
        "你是一名资深短视频/中视频文案策划，擅长把视频素材提炼成结构清晰、"
        "口语自然、有传播力的文案。只输出文案正文，不要输出任何解释或前后缀。"
    )
    user = (
        f"请根据下面的视频素材，写一篇【{style}】风格的视频文案。\n"
        f"风格要求：{hint}\n"
        f"目标字数：约 {target_words} 字。\n"
    )
    if extra_hint:
        user += f"额外要求：{extra_hint}\n"
    user += "\n===== 视频素材 =====\n" + material

    return await _chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )
