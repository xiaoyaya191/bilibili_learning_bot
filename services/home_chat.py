"""services/home_chat.py — 主页智能对话（AI / Agent 双模式）。

支持用户询问：
- 最近 AI 刷到了什么视频
- 学到了什么知识
- 笔记里的核心观点
- 总结最近看的视频
- 根据看的视频画一个用户画像 / 我是一个什么样的人（用户可自定义）

增强能力（2026-07-07）：
- **持久多会话**：会话按 JSON 落盘到 Data/HomeChat/，支持新建/选择/重命名/删除/持久上下文。
- **上下文模式**：persistent(持久上下文，保留最近若干轮) / infinite(无限上下文，全部历史) / none(无上下文，仅知识库检索)。
- **高度自定义**：可自定义系统提示词、调用模型、温度；默认 AI 模式，可切 Agent。
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "Data"
CONV_DIR = DATA_DIR / "HomeChat"
LEARNING_LOG_FILE = BASE_DIR / "learning_log.md"

# 持久上下文模式下保留的最近消息轮数上限（单条消息计 1）
PERSISTENT_HISTORY_LIMIT = 20
DEFAULT_TEMPERATURE = 0.7


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────
#  会话持久化
# ─────────────────────────────────────────────
def _conv_path(conv_id: str) -> Path:
    CONV_DIR.mkdir(parents=True, exist_ok=True)
    return CONV_DIR / f"{conv_id}.json"


def _safe_id(conv_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "", conv_id or "")[:64]


def list_conversations() -> list[dict]:
    """返回会话摘要列表（按更新时间倒序）。"""
    if not CONV_DIR.exists():
        return []
    out = []
    for f in CONV_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "id": d.get("id", f.stem),
                "title": d.get("title", "新对话"),
                "mode": d.get("mode", "ai"),
                "context_mode": d.get("context_mode", "persistent"),
                "message_count": len(d.get("messages", [])),
                "updated_at": d.get("updated_at", ""),
            })
        except Exception:
            continue
    out.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return out


def create_conversation(title: str = "", mode: str = "ai", context_mode: str = "persistent",
                        system_prompt: str = "", model: str = "", temperature: float | None = None) -> dict:
    conv_id = uuid.uuid4().hex[:12]
    conv = {
        "id": conv_id,
        "title": title or "新对话",
        "mode": mode or "ai",
        "context_mode": context_mode or "persistent",
        "system_prompt": system_prompt or "",
        "model": model or "",
        "temperature": temperature if temperature is not None else DEFAULT_TEMPERATURE,
        "created_at": _now(),
        "updated_at": _now(),
        "messages": [],
    }
    _conv_path(conv_id).write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")
    return conv


def get_conversation(conv_id: str) -> dict | None:
    conv_id = _safe_id(conv_id)
    p = _conv_path(conv_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_conversation(conv: dict) -> None:
    conv["updated_at"] = _now()
    _conv_path(conv["id"]).write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")


def rename_conversation(conv_id: str, title: str) -> bool:
    conv = get_conversation(conv_id)
    if not conv:
        return False
    conv["title"] = (title or "新对话").strip() or "新对话"
    save_conversation(conv)
    return True


def delete_conversation(conv_id: str) -> bool:
    conv_id = _safe_id(conv_id)
    p = _conv_path(conv_id)
    if p.exists():
        p.unlink()
        return True
    return False


def _append_message(conv: dict, role: str, content: str) -> None:
    conv.setdefault("messages", []).append({"role": role, "content": content, "ts": _now()})
    # 首条用户消息自动作为会话标题
    if role == "user" and (conv.get("title") in (None, "", "新对话")):
        conv["title"] = content[:24].strip() or "新对话"


# ─────────────────────────────────────────────
#  上下文采集
# ─────────────────────────────────────────────
def _resolve_kb_dir(cfg: dict | None) -> Path:
    if cfg and isinstance(cfg, dict):
        kb = cfg.get("knowledge_base_dir") or (cfg.get("knowledge", {}) or {}).get("base_dir")
        if kb:
            p = Path(kb)
            return p if p.is_absolute() else BASE_DIR / p
    return BASE_DIR / "KnowledgeBase"


def read_recent_videos(limit: int = 20) -> list[dict[str, str]]:
    """解析 learning_log.md，返回最近学习的视频（最新在前）。"""
    if not LEARNING_LOG_FILE.exists():
        return []
    text = LEARNING_LOG_FILE.read_text(encoding="utf-8", errors="replace")
    entries: list[dict[str, str]] = []
    pat = re.compile(
        r"- \*\*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\*\*\s*\|\s*`分类:([^`]*)`\s*\|\s*`([^`]*)`"
    )
    for line in text.splitlines():
        m = pat.search(line)
        if m:
            entries.append({
                "time": m.group(1),
                "category": m.group(2).strip(),
                "title": m.group(3).strip(),
            })
    entries.reverse()
    return entries[:limit]


def kb_stats(kb_dir: Path) -> dict[str, Any]:
    total = 0
    cats: dict[str, int] = {}
    if kb_dir.exists():
        for md in kb_dir.rglob("*.md"):
            total += 1
            rel = md.relative_to(kb_dir)
            top = rel.parts[0] if len(rel.parts) > 1 else "未分类"
            cats[top] = cats.get(top, 0) + 1
    return {"total": total, "categories": cats}


def persona_info(cfg: dict | None) -> dict[str, str]:
    p = (cfg or {}).get("persona", {}) or {}
    return {
        "active_persona": p.get("active_persona", "") or "",
        "prompt_name": p.get("prompt_name", "") or "",
        "self_description": p.get("self_description", "") or "",
    }


def build_context(cfg: dict | None) -> dict[str, Any]:
    kb_dir = _resolve_kb_dir(cfg)
    return {
        "recent_videos": read_recent_videos(),
        "kb": kb_stats(kb_dir),
        "persona": persona_info(cfg),
    }


def _ctx_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "recent_videos": len(ctx.get("recent_videos", [])),
        "kb_total": ctx.get("kb", {}).get("total", 0),
        "kb_categories": len(ctx.get("kb", {}).get("categories", {})),
    }


# ─────────────────────────────────────────────
#  意图识别
# ─────────────────────────────────────────────
def detect_intent(message: str) -> str:
    m = (message or "").lower()
    if any(k in m for k in ["核心观点", "笔记观点", "核心知识", "笔记里", "观点", "笔记核心"]):
        return "core_viewpoints"
    if any(k in m for k in ["画像", "是什么样的人", "什么样的人", "用户画像", "我是个", "我是怎样", "我是什么样"]):
        return "profile"
    if any(k in m for k in ["总结", "最近看的视频", "看了什么视频", "看了哪些", "总结一下"]):
        return "summarize_videos"
    if any(k in m for k in ["学到了", "学了啥", "学到啥", "get到", "get了", "知识"]):
        return "knowledge_learned"
    if any(k in m for k in ["刷到", "刷了什么", "看了什么视频", "最近看", "观看记录", "最近视频", "刷的视频"]):
        return "recent_videos"
    return "general"


# ─────────────────────────────────────────────
#  LLM 调用（支持自定义 model / temperature）
# ─────────────────────────────────────────────
async def _call_llm(system: str, user: str, history: list[dict] | None = None,
                    model: str = "", temperature: float | None = None) -> str:
    from services._services_ai import call_ai
    messages = [{"role": "system", "content": system}]
    if history:
        for h in history:
            if isinstance(h, dict) and h.get("content"):
                messages.append({"role": h.get("role", "user"), "content": h["content"]})
    messages.append({"role": "user", "content": user})
    kwargs = {}
    if model:
        kwargs["model"] = model
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    return await call_ai(messages, **kwargs)


def _retrieve(query: str, cfg: dict | None, n: int = 4) -> list[dict[str, Any]]:
    try:
        from services.rag_qa import retrieve_chunks
        kb_dir = _resolve_kb_dir(cfg)
        return retrieve_chunks(query, max_chunks=n, kb_root=kb_dir)
    except Exception:
        return []


# ─────────────────────────────────────────────
#  系统提示词构建
# ─────────────────────────────────────────────
def _build_system(intent: str, ctx: dict[str, Any], cfg: dict | None, message: str) -> str:
    p = ctx.get("persona", {})
    lines: list[str] = []
    lines.append("你是 bilibili_learning_bot 的主页智能助手。你可以基于用户的「学习日志」和「知识库笔记」回答问题。")
    lines.append("请用简体中文回答，语气自然友好、结构清晰（善用标题与列表）。只基于已有事实回答，不确定处明确说明。")

    if p.get("self_description"):
        lines.append(f"\n【用户自定义画像】用户对自己的描述：{p['self_description']}")

    rv = ctx.get("recent_videos", [])
    if rv:
        lines.append("\n【AI 最近刷到/学习的视频（最新在前）】")
        for v in rv[:15]:
            lines.append(f"- {v['time']} | 分类:{v['category']} | {v['title']}")
    else:
        lines.append("\n【AI 最近刷到的视频】暂无学习日志记录。")

    kb = ctx.get("kb", {})
    cats = kb.get("categories", {})
    cat_str = "、".join(f"{k}({v})" for k, v in list(cats.items())[:12]) or "无"
    lines.append(f"\n【知识库概况】共 {kb.get('total', 0)} 篇笔记，主要分类：{cat_str}")

    knowledge_intents = {"core_viewpoints", "knowledge_learned", "summarize_videos", "profile"}
    if intent in knowledge_intents:
        chunks = _retrieve(message, cfg, n=4)
        if chunks:
            lines.append("\n【相关笔记片段】")
            for i, c in enumerate(chunks):
                lines.append(f"[片段{i+1}] {c.get('title','')}\n{c.get('snippet','')[:400]}")
            lines.append("（可基于以上片段回答）")

    if intent == "core_viewpoints":
        lines.append("\n用户想要「笔记里的核心观点」。请提炼并列出用户知识笔记中反复出现的核心观点/主题（尽量结合上面片段与视频主题），用要点呈现；信息不足时说明可以从哪些方向深入了解。")
    elif intent == "profile":
        lines.append("\n用户想要「用户画像 / 我是一个什么样的人」。请结合【用户自定义画像】、最近观看的视频主题、知识库分类，给用户画一个立体的画像（兴趣领域、认知风格、关注方向、可能的性格特征）。基于已有事实，避免凭空捏造；不确定处注明。")
    elif intent == "summarize_videos":
        lines.append("\n用户想要「总结最近看的视频」。请根据学习日志列出最近观看/学习的视频，并做整体主题总结。")
    elif intent == "knowledge_learned":
        lines.append("\n用户问「学到了什么知识」。请基于知识库分类、相关片段与视频主题，总结用户近期学到的主要知识点与领域。")
    elif intent == "recent_videos":
        lines.append("\n用户问「最近刷到了什么视频」。请直接列出学习日志中最近的视频（标题 + 时间 + 分类）。")
    else:
        lines.append("\n用户提出了一般性问题。请结合上述上下文，尽量基于事实作答；若问题超出上下文范围，礼貌说明并给出建议。")

    return "\n".join(lines)


def _final_system(intent: str, ctx: dict[str, Any], cfg: dict | None, message: str,
                  system_prompt_override: str = "") -> str:
    """组合最终系统提示词：用户自定义提示词优先，其后追加自动知识上下文。"""
    auto = _build_system(intent, ctx, cfg, message)
    override = (system_prompt_override or "").strip()
    if override:
        return override + "\n\n---\n（以下为自动注入的知识上下文，作为参考事实）\n" + auto
    return auto


def _history_for_context(conv: dict, context_mode: str) -> list[dict]:
    msgs = conv.get("messages", [])
    if context_mode == "none":
        return []
    if context_mode == "infinite":
        return list(msgs)
    # persistent：保留最近 N 条
    return msgs[-PERSISTENT_HISTORY_LIMIT:]


# ─────────────────────────────────────────────
#  Agent 模式
# ─────────────────────────────────────────────
async def _agent_mode(message: str, cfg: dict | None, ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        from services.agent_service import AgentSkillRunner
        runner = AgentSkillRunner()
        result = await runner.run_goal(message)
        steps = result.get("results", []) if isinstance(result, dict) else []
        summary_lines = []
        for s in steps:
            step = s.get("step", {})
            res = s.get("result", {})
            status = "成功" if res.get("ok") else "失败"
            detail = ""
            if isinstance(res.get("videos"), list):
                detail = f"（{len(res['videos'])} 个视频）"
            elif res.get("summary"):
                detail = "（已生成总结）"
            summary_lines.append(f"- 技能 {step.get('skill', '?')}: {status}{detail}")
        answer = "🤖 Agent 已完成任务规划与执行：\n" + "\n".join(summary_lines)
        raw = json.dumps(result, ensure_ascii=False)
        if len(raw) > 1800:
            raw = raw[:1800] + "\n…(已截断)"
        answer += f"\n\n```json\n{raw}\n```"
        return {"ok": True, "mode": "agent", "intent": "agent", "answer": answer, "context": _ctx_summary(ctx)}
    except Exception as e:
        return {"ok": False, "mode": "agent", "intent": "agent",
                "answer": f"⚠️ Agent 执行失败：{e}\n\n（Agent 需要有效的 B站登录与运行中的机器人上下文才能搜索/观看视频）",
                "context": _ctx_summary(ctx)}


# ─────────────────────────────────────────────
#  统一入口（支持会话持久化 + 上下文模式 + 自定义）
# ─────────────────────────────────────────────
async def home_chat(message: str, mode: str = "ai", cfg: dict | None = None,
                    history: list[dict] | None = None, conv_id: str | None = None,
                    context_mode: str | None = None, system_prompt: str | None = None,
                    model: str | None = None, temperature: float | None = None) -> dict[str, Any]:
    cfg = cfg or {}
    ctx = build_context(cfg)
    intent = detect_intent(message)

    # 解析会话（没有则自动新建，确保持久化）
    conv = get_conversation(conv_id) if conv_id else None
    if conv is None:
        conv = create_conversation(mode=mode or "ai",
                                   context_mode=context_mode or "persistent",
                                   system_prompt=system_prompt or "",
                                   model=model or "",
                                   temperature=temperature)
    # 用会话元数据 + 调用时覆盖项
    eff_mode = (mode or conv.get("mode") or "ai")
    eff_ctx_mode = (context_mode or conv.get("context_mode") or "persistent")
    eff_system = system_prompt if system_prompt is not None else conv.get("system_prompt", "")
    eff_model = model if model is not None else conv.get("model", "")
    eff_temp = temperature if temperature is not None else conv.get("temperature", DEFAULT_TEMPERATURE)

    conv["mode"] = eff_mode
    conv["context_mode"] = eff_ctx_mode
    if eff_system:
        conv["system_prompt"] = eff_system
    if eff_model:
        conv["model"] = eff_model
    if temperature is not None:
        conv["temperature"] = eff_temp

    _append_message(conv, "user", message)

    if eff_mode == "agent":
        result = await _agent_mode(message, cfg, ctx)
        answer = result.get("answer", "")
        result["conv_id"] = conv["id"]
        result["conv_title"] = conv["title"]
        _append_message(conv, "assistant", answer)
        save_conversation(conv)
        return result

    history_ctx = _history_for_context(conv, eff_ctx_mode)
    system = _final_system(intent, ctx, cfg, message, eff_system)
    try:
        answer = await _call_llm(system, message, history_ctx, model=eff_model, temperature=eff_temp)
    except Exception as e:
        answer = (
            f"⚠️ AI 调用失败：{e}\n\n"
            "请检查设置中的 API Key / Base URL / 模型(对话) 是否已正确配置，"
            "或稍后重试。你也可以切换到 Agent 模式尝试。"
        )
    _append_message(conv, "assistant", answer)
    save_conversation(conv)
    return {"ok": True, "mode": "ai", "intent": intent, "answer": answer,
            "context": _ctx_summary(ctx), "conv_id": conv["id"], "conv_title": conv["title"]}
