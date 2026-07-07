"""知识库 RAG 问答服务。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_BASE_DIR = BASE_DIR / "KnowledgeBase"


def _strip_md(text: str) -> str:
    text = re.sub(r'```.*?```', '', text or '', flags=re.S)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'[#>*_`\-]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _score_text(query: str, text: str) -> float:
    q = [x for x in re.split(r'\s+', query.lower()) if x]
    compact_q = query.lower().replace(' ', '')
    low = text.lower()
    score = 0.0
    if compact_q and compact_q in low.replace(' ', ''):
        score += 5.0
    for token in q:
        if len(token) >= 2 and token in low:
            score += 1.0
    for ch in set(query):
        if '\u4e00' <= ch <= '\u9fff' and ch in text:
            score += 0.08
    return score


def search_note(query: str, max_chunks: int = 5, kb_root: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    """Function Calling 友好的知识检索工具：返回带来源路径的候选笔记片段。"""
    return retrieve_chunks(query, max_chunks=max_chunks, kb_root=kb_root)


def open_note(path: str, kb_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Function Calling 友好的笔记打开工具：按相对路径读取知识库原文。"""
    root = Path(kb_root or KNOWLEDGE_BASE_DIR).resolve()
    target = (root / (path or '')).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return {'ok': False, 'message': '禁止访问知识库外部路径'}
    if not target.exists() or not target.is_file():
        return {'ok': False, 'message': '笔记不存在'}
    try:
        return {'ok': True, 'path': str(target.relative_to(root)), 'content': target.read_text(encoding='utf-8', errors='replace')}
    except Exception as e:
        return {'ok': False, 'message': str(e)}


def get_function_tools() -> list[dict[str, Any]]:
    """返回 OpenAI 兼容 tools 定义，供上层模型调用 search_note/open_note。"""
    return [
        {
            'type': 'function',
            'function': {
                'name': 'search_note',
                'description': '搜索本地知识库 Markdown 笔记，返回标题、路径和片段。',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {'type': 'string', 'description': '搜索问题或关键词'},
                        'max_chunks': {'type': 'integer', 'description': '最多返回片段数', 'default': 5},
                    },
                    'required': ['query'],
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'open_note',
                'description': '按知识库相对路径打开完整 Markdown 笔记。',
                'parameters': {
                    'type': 'object',
                    'properties': {'path': {'type': 'string', 'description': '知识库相对路径'}},
                    'required': ['path'],
                },
            },
        },
    ]


def retrieve_chunks(query: str, max_chunks: int = 5, kb_root: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    root = Path(kb_root or KNOWLEDGE_BASE_DIR)
    if not root.exists() or not query.strip():
        return []
    candidates: list[dict[str, Any]] = []
    for md in root.rglob('*.md'):
        try:
            raw = md.read_text(encoding='utf-8', errors='replace')
            plain = _strip_md(raw)
            if not plain:
                continue
            score = _score_text(query, plain + ' ' + md.stem)
            if score <= 0:
                continue
            pos = max(0, plain.lower().find(query.lower()) - 260)
            snippet = plain[pos:pos + 900]
            candidates.append({
                'score': round(score, 4),
                'title': md.stem,
                'path': str(md.relative_to(root)),
                'snippet': snippet,
            })
        except Exception:
            continue
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:max(1, int(max_chunks or 5))]


async def answer_question(question: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = (cfg or {}).get('rag_qa', {}) if isinstance(cfg, dict) else {}
    if not opts.get('enabled', False):
        return {'ok': False, 'answer': 'RAG 问答未启用，请在 config.json 的 rag_qa.enabled 开启。', 'sources': []}
    max_chunks = int(opts.get('max_context_chunks', 5) or 5)
    sources = retrieve_chunks(question, max_chunks=max_chunks)
    if not sources:
        return {'ok': True, 'answer': '知识库中暂未检索到相关内容。', 'sources': []}

    context = '\n\n'.join(
        f"[来源 {i+1}] {s['title']}\n路径：{s['path']}\n片段：{s['snippet']}"
        for i, s in enumerate(sources)
    )
    prompt = f"""你是 bilibili_learning_bot 的知识库问答助手。请只基于给定知识片段回答用户问题。

要求：
1. 回答要结构化、简洁。
2. 如果片段不足以确定答案，明确说明“不确定”。
3. 末尾列出引用来源路径。

【知识片段】
{context}

【用户问题】
{question}"""
    try:
        from xingye_bot.llm import ModelClient
        from xingye_bot.settings import load_settings
        from xingye_bot.state import BotState
        client = ModelClient(load_settings(), BotState())
        answer = await client.chat([{'role': 'user', 'content': prompt}], model_role='chat', purpose='rag_qa')
    except Exception as e:
        answer = f"已检索到相关片段，但 AI 回答失败：{e}\n\n" + context[:1600]
    return {'ok': True, 'answer': answer, 'sources': sources}
