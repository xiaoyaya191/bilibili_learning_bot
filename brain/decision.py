"""Parsing and conservative fallback policies for video decisions."""
from __future__ import annotations

import ast
import json
import re
from typing import Any


def response_text(response: Any) -> str:
    """Read text from OpenAI-compatible responses, including reasoning models."""
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""
    for name in ("content", "reasoning_content", "reasoning"):
        value = getattr(message, name, None)
        if not value and isinstance(message, dict):
            value = message.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
            text = "".join(parts).strip()
            if text:
                return text
    return ""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是", "需要"}


def _as_score(value: Any, default: float) -> float:
    try:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        score = float(match.group(0)) if match else default
    except (TypeError, ValueError):
        score = default
    return round(max(0.0, min(10.0, score)), 1)


def _derive_topic(title: str) -> str:
    cleaned = re.sub(r"[【】\[\]《》<>#|]+", " ", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_:：")
    return cleaned[:10] or "视频知识"


def local_fallback_decision(
    *, title: str, subtitle_text: str, comment_text: str = "",
    danmaku_text: str = "", visual_score: Any = 5,
) -> dict[str, Any]:
    """Estimate content value when the model's structure cannot be parsed."""
    subtitle_len = len((subtitle_text or "").strip())
    comment_len = len((comment_text or "").strip())
    score = 4.7
    if subtitle_len >= 150:
        score += 0.9
    if subtitle_len >= 500:
        score += 0.5
    if subtitle_len >= 1200:
        score += 0.4
    if comment_len >= 150:
        score += 0.2
    if comment_len >= 500:
        score += 0.2
    if danmaku_text and len(danmaku_text.strip()) >= 80:
        score += 0.1
    try:
        score += max(-0.5, min(0.5, (float(visual_score) - 5.0) * 0.15))
    except (TypeError, ValueError):
        pass

    haystack = f"{title}\n{subtitle_text[:800]}".lower()
    knowledge_terms = (
        "教程", "原理", "分析", "研究", "科普", "技术", "代码", "编程", "维修",
        "实验", "方法", "指南", "经验", "评测", "简历", "医学", "历史", "经济",
    )
    entertainment_terms = ("搞笑", "整活", "鬼畜", "高光", "集锦", "对局", "抽卡", "reaction")
    if any(term in haystack for term in knowledge_terms):
        score += 0.6
    if any(term in haystack for term in entertainment_terms):
        score -= 0.6

    score = round(max(3.0, min(7.5, score)), 1)
    has_learnable_content = subtitle_len >= 150 and score >= 6.0
    return {
        "mode": "本地兜底",
        "thought": f"AI结构化结果不可用；按字幕({subtitle_len}字)和讨论信息保守评估",
        "score": score,
        "remember_up": False,
        "coin_intention": False,
        "fav_intention": False,
        "learning_topic": _derive_topic(title) if has_learnable_content else "",
        "replies": [],
        "engagement_signal": {"asks_for_support": False, "keyword_campaign": False, "suggested_action": "none", "reason": "local fallback"},
    }


def _read_member_value(text: str, start: int) -> tuple[Any, int] | None:
    """Read one JSON-like value without requiring a complete outer object."""
    length = len(text)
    while start < length and text[start].isspace():
        start += 1
    if start >= length:
        return None

    first = text[start]
    if first in {'"', "'"}:
        quote = first
        escaped = False
        end = start + 1
        while end < length:
            char = text[end]
            if char == quote and not escaped:
                fragment = text[start:end + 1]
                try:
                    return (json.loads(fragment) if quote == '"' else ast.literal_eval(fragment)), end + 1
                except (json.JSONDecodeError, SyntaxError, ValueError):
                    return text[start + 1:end], end + 1
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
            end += 1
        return text[start + 1:].strip(), length

    if first in "[{":
        closing = "]" if first == "[" else "}"
        depth = 0
        quote = ""
        escaped = False
        for end in range(start, length):
            char = text[end]
            if quote:
                if char == quote and not escaped:
                    quote = ""
                escaped = char == "\\" and not escaped
                if char != "\\":
                    escaped = False
                continue
            if char in {'"', "'"}:
                quote = char
            elif char == first:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    fragment = text[start:end + 1]
                    try:
                        return json.loads(fragment), end + 1
                    except json.JSONDecodeError:
                        try:
                            return ast.literal_eval(fragment), end + 1
                        except (SyntaxError, ValueError):
                            return None
        return None

    end_match = re.search(r"[,\n\r}]", text[start:])
    end = start + end_match.start() if end_match else length
    fragment = text[start:end].strip()
    if not fragment:
        return None
    try:
        return json.loads(fragment), end
    except json.JSONDecodeError:
        lowered = fragment.lower()
        if lowered in {"true", "yes"}:
            return True, end
        if lowered in {"false", "no"}:
            return False, end
        if lowered in {"null", "none"}:
            return None, end
        return fragment, end


def _extract_members(text: str, field_names: tuple[str, ...]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in field_names:
        match = re.search(rf"[\"']?{re.escape(field)}[\"']?\s*:\s*", text, re.IGNORECASE)
        if not match:
            continue
        parsed = _read_member_value(text, match.end())
        if parsed is not None:
            values[field] = parsed[0]
    return values


def decode_ai_mapping(raw: str, field_names: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """Decode a model object, including gateways that strip its outer braces."""
    text = (raw or "").strip().lstrip("\ufeff")
    if not text:
        return None
    text = re.sub(r"^```(?:json|javascript|python)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    start = text.find("{")
    if start >= 0:
        candidates.insert(0, text[start:])
    elif re.search(r'"?(?:mode|score|thought|reason|learning_topic)"?\s*:', text):
        candidates.insert(0, "{" + text.strip().strip(",") + "}")
    for candidate in candidates:
        candidate = candidate.strip()
        try:
            value, _ = json.JSONDecoder().raw_decode(candidate)
            if isinstance(value, dict):
                return value
            if isinstance(value, str) and value.strip() and value != candidate:
                candidates.append(value.strip())
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            value = ast.literal_eval(candidate)
            if isinstance(value, dict):
                return value
        except (SyntaxError, ValueError, TypeError):
            pass
        fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
        fixed = re.sub(r"\bTrue\b", "true", fixed)
        fixed = re.sub(r"\bFalse\b", "false", fixed)
        fixed = re.sub(r"\bNone\b", "null", fixed)
        try:
            value = json.loads(fixed)
            if isinstance(value, dict):
                return value
        except (json.JSONDecodeError, TypeError):
            pass
    members = _extract_members(text, field_names)
    return members or None


def _decode_mapping(raw: str) -> dict[str, Any] | None:
    return decode_ai_mapping(raw, (
        "mode", "thought", "reason", "score", "remember_up", "follow_up", "remember",
        "coin_intention", "coin_intent", "coin", "fav_intention", "favorite_intention",
        "collect_intent", "favorite", "learning_topic", "replies", "engagement_signal",
    ))


def parse_video_decision(raw: str, **fallback_context: Any) -> tuple[dict[str, Any], bool]:
    """Return a normalized decision and whether local fallback was required."""
    fallback = local_fallback_decision(**fallback_context)
    data = _decode_mapping(raw)
    if data is None:
        return fallback, True
    aliases = {
        "coin_intention": ("coin_intention", "coin_intent", "coin"),
        "fav_intention": ("fav_intention", "favorite_intention", "collect_intent", "favorite"),
        "remember_up": ("remember_up", "follow_up", "remember"),
    }
    normalized = dict(data)
    for target, names in aliases.items():
        normalized[target] = _as_bool(next((data[name] for name in names if name in data), False))
    normalized["score"] = _as_score(data.get("score"), fallback["score"])
    normalized["mode"] = str(data.get("mode") or "普通")[:20]
    normalized["thought"] = str(data.get("thought") or data.get("reason") or "AI已完成内容判断")[:500]
    topic = data.get("learning_topic", "")
    normalized["learning_topic"] = str(topic).strip()[:30] if topic is not None else ""
    replies = data.get("replies", [])
    normalized["replies"] = replies if isinstance(replies, list) else []
    signal = data.get("engagement_signal", {})
    signal = signal if isinstance(signal, dict) else {}
    action = str(signal.get("suggested_action") or "none").strip().lower()
    normalized["engagement_signal"] = {
        "asks_for_support": _as_bool(signal.get("asks_for_support", False)),
        "keyword_campaign": _as_bool(signal.get("keyword_campaign", False)),
        "suggested_action": action if action in {"like", "coin", "favorite", "comment", "none"} else "none",
        "reason": str(signal.get("reason") or "")[:240],
    }
    return normalized, False
