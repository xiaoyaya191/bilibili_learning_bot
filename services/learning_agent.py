"""
learning_agent.py — AI Agent 学习引擎

功能：
1. Agent 模式：多轮对话、工具调用（Function Calling）、状态持久化
2. 适用于"出题考试"和"深入了解"两个场景
3. 支持会话继续（没弄好接着整 / 长任务）
4. 多Agent协调：并行处理多个主题/关键词

设计为同时供 CLI（main.py）和 Web（web_panel.py）调用。
"""

from __future__ import annotations

import json
import os
import re
import asyncio
import inspect
import uuid
from pathlib import Path
from typing import Any, Callable
from datetime import datetime

from colorama import Fore, Style

BASE_DIR = Path(__file__).resolve().parent.parent
from core.user_data import DATA_DIR, HTML_EXPORTS_DIR
from core.config import config as _core_config, resolve_knowledge_base_dir

KNOWLEDGE_BASE_DIR = Path(resolve_knowledge_base_dir(_core_config))

SESSION_DIR = DATA_DIR / "learning_sessions"
REPORT_EXPORT_DIR = HTML_EXPORTS_DIR


from services._services_ai import call_ai, call_ai_with_tools, _live_config

# ── B站搜索排序映射 ──
BILI_SORT_OPTIONS = {
    "default":      ("totalrank", "综合排序"),
    "newest":       ("pubdate",   "最新发布"),
    "most_played":  ("click",     "最多播放"),
    "most_faved":   ("stow",      "最多收藏"),
    "most_danmaku": ("dm",        "最多弹幕"),
    "most_comments":("scores",    "最多评论"),
}

# ── Agent 系统提示词 ──
SYSTEM_PROMPT_DEEP_DIVE = """你是一个AI学习助手，能够使用多种工具帮助用户深入了解一个主题。

工作方式：
1. 根据用户想了解的主题，使用 search_bilibili 或 web_search 搜索相关资料
2. 对B站搜索结果，使用 get_video_content 获取视频字幕/内容
3. 在收集到足够资料后，使用 finalize_deep_dive 生成并保存综合学习报告
4. 如果需要更多资料，可以多次搜索不同关键词
5. 搜索时可以指定排序方式（newest=最新, most_played=最多播放, most_faved=最多收藏）

注意：
- 先分析主题，拆解为多个搜索关键词
- 优先使用B站搜索（中文内容更好），必要时使用联网搜索
- 收集到至少 3-5 个有效来源后再生成报告
- 报告应该结构清晰：概念概述 → 关键知识点 → 重点难点 → 进一步学习建议
- 用中文回复用户"""

SYSTEM_PROMPT_QUIZ = """你是一个AI出题助手，能够使用多种工具生成考题。

工作方式：
1. 用户可以选择来源：B站视频(提供BV号) 或 知识库文件
2. 使用 get_video_content 获取视频字幕，或使用 read_kb_file 读取知识库
3. 使用 finalize_quiz 生成并保存考题
4. 可以根据用户反馈调整题目（增加/减少题目、改变难度、换题型等）

注意：
- 题目必须基于原文内容，不要编造
- 在生成考题前先确认内容是否足够
- 用中文回复用户"""

# ── 工具定义 ──
TOOLS_DEEP_DIVE = [
    {
        "type": "function",
        "function": {
            "name": "search_bilibili",
            "description": "搜索B站视频。支持多种排序方式：newest(最新发布), most_played(最多播放), most_faved(最多收藏), most_danmaku(最多弹幕), default(综合排序)",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "count": {"type": "integer", "description": "返回数量，默认8"},
                    "sort_by": {"type": "string", "enum": ["default", "newest", "most_played", "most_faved", "most_danmaku", "most_comments"], "description": "排序方式"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索网页内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "count": {"type": "integer", "description": "返回数量，默认5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_video_content",
            "description": "获取B站视频的字幕文本内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "bvid": {"type": "string", "description": "B站视频BV号"},
                },
                "required": ["bvid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_deep_dive",
            "description": "完成深入学习，保存综合学习报告。在收集到足够资料后调用此工具结束任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "学习主题"},
                    "report": {"type": "string", "description": "完整的Markdown格式学习报告内容"},
                },
                "required": ["topic", "report"],
            },
        },
    },
]

TOOLS_QUIZ = [
    {
        "type": "function",
        "function": {
            "name": "get_video_content",
            "description": "获取B站视频的字幕文本内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "bvid": {"type": "string", "description": "B站视频BV号"},
                },
                "required": ["bvid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_kb_files",
            "description": "列出知识库中的可用文件",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_kb_file",
            "description": "读取知识库文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "文件名或相对路径"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_quiz",
            "description": "完成出题，保存考题。生成考题后调用此工具结束任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_title": {"type": "string", "description": "考题来源标题"},
                    "quiz_content": {"type": "string", "description": "完整的考题内容(Markdown格式)，包含题目和答案"},
                    "question_count": {"type": "integer", "description": "题目数量"},
                    "difficulty": {"type": "string", "description": "难度：easy/medium/hard"},
                },
                "required": ["source_title", "quiz_content"],
            },
        },
    },
]

# ── 工具实现辅助函数 ──

def _load_bili_cookies() -> dict:
    cookie_file = DATA_DIR / "bilibili_cookies.json"
    if cookie_file.exists():
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


async def _search_bilibili_agent(query: str, count: int = 8, sort_by: str = "default") -> list[dict]:
    """Agent工具：B站搜索"""
    try:
        import httpx
        order_param, order_label = BILI_SORT_OPTIONS.get(sort_by, BILI_SORT_OPTIONS["default"])
        cookies = _load_bili_cookies()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.bilibili.com/'
        }
        async with httpx.AsyncClient(http2=True, headers=headers, cookies=cookies, timeout=15.0) as client:
            resp = await client.get(
                'https://api.bilibili.com/x/web-interface/search/type',
                params={'search_type': 'video', 'keyword': query, 'order': order_param, 'page': 1}
            )
            data = resp.json()
            if data.get('code') == 0:
                results = []
                for v in data['data'].get('result', [])[:count]:
                    results.append({
                        "bvid": v.get('bvid', ''),
                        "title": v.get('title', '').replace('<em class="keyword">', '').replace('</em>', ''),
                        "author": v.get('author', ''),
                        "play": v.get('play', 0),
                        "duration": v.get('duration', ''),
                        "description": (v.get('description', '') or '')[:200],
                    })
                return results
    except Exception as e:
        return [{"error": str(e)}]
    return []


async def _web_search_agent(query: str, count: int = 5) -> list[dict]:
    """Agent工具：联网搜索"""
    try:
        from knowledge.web_search import web_search
        results = web_search(query, limit=count)
        if inspect.isawaitable(results):
            results = await results
        return results if isinstance(results, list) else []
    except Exception:
        pass
    try:
        import httpx
        results = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://www.bing.com/search",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            if resp.status_code == 200:
                blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', resp.text, re.DOTALL)
                for block in blocks[:count]:
                    url_m = re.search(r'href="(https?://[^"]+)"', block)
                    title_m = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL)
                    snippet_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
                    if title_m and url_m:
                        results.append({
                            "title": re.sub(r'<[^>]+>', '', title_m.group(1)).strip(),
                            "url": url_m.group(1),
                            "snippet": re.sub(r'<[^>]+>', '', (snippet_m.group(1) if snippet_m else '')).strip()[:500],
                        })
        return results[:count]
    except Exception:
        return []


async def _get_video_content_agent(bvid: str) -> dict:
    """Agent工具：获取视频字幕"""
    try:
        from api.subtitles import fetch_bilibili_subtitles
        cookies = _load_bili_cookies()
        result = await fetch_bilibili_subtitles(bvid, cookies_obj=cookies if cookies else None)
        if result and result.get("subtitle_text"):
            text = result["subtitle_text"]
            return {"bvid": bvid, "content": text, "length": len(text), "status": "ok"}
    except Exception:
        pass
    return {"bvid": bvid, "content": "", "length": 0, "status": "no_subtitles"}


def _list_kb_files_agent() -> list[dict]:
    """Agent工具：列出知识库文件"""
    results = []
    if not KNOWLEDGE_BASE_DIR.exists():
        return results
    for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in files:
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, KNOWLEDGE_BASE_DIR)
            size_kb = round(os.path.getsize(fpath) / 1024, 1)
            results.append({"name": fname, "rel_path": rel_path, "size_kb": size_kb})
    results.sort(key=lambda x: x['rel_path'])
    return results


def _read_kb_file_agent(filename: str, max_chars: int = 15000) -> dict:
    """Agent工具：读取知识库文件"""
    path = KNOWLEDGE_BASE_DIR / filename
    if not path.exists():
        # 尝试全局搜索
        for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
            for fname in files:
                if fname == filename or fname == os.path.basename(filename):
                    path = Path(root) / fname
                    break
    if not path.exists():
        return {"error": f"文件不存在: {filename}"}
    content = path.read_text(encoding='utf-8', errors='replace')
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n... (内容过长已截断)"
    return {"filename": str(path), "content": content, "length": len(content)}


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', '_', name or 'output').strip(' .')[:120] or 'output'


# ── Agent Session 管理 ──

class LearningAgentSession:
    """Agent 会话 — 持久化保存对话历史和上下文"""

    def __init__(self, session_id: str = "", session_type: str = "deep_dive"):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.session_type = session_type  # "deep_dive" | "quiz"
        self.topic = ""
        self.messages: list[dict] = []
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.metadata: dict[str, Any] = {}
        self.results: list[dict] = []

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "session_type": self.session_type,
            "topic": self.topic,
            "messages": self.messages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "results": self.results,
        }

    @staticmethod
    def from_dict(d: dict) -> "LearningAgentSession":
        s = LearningAgentSession(d.get("session_id", ""), d.get("session_type", "deep_dive"))
        s.topic = d.get("topic", "")
        s.messages = d.get("messages", [])
        s.created_at = d.get("created_at", "")
        s.updated_at = d.get("updated_at", "")
        s.metadata = d.get("metadata", {})
        s.results = d.get("results", [])
        return s

    def save(self):
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now().isoformat()
        path = SESSION_DIR / f"{self.session_id}.json"
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')

    @staticmethod
    def load(session_id: str) -> "LearningAgentSession | None":
        path = SESSION_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding='utf-8'))
        return LearningAgentSession.from_dict(d)

    @staticmethod
    def list_sessions(session_type: str = "") -> list[dict]:
        if not SESSION_DIR.exists():
            return []
        sessions = []
        for f in sorted(SESSION_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                d = json.loads(f.read_text(encoding='utf-8'))
                if session_type and d.get("session_type") != session_type:
                    continue
                sessions.append({
                    "session_id": d.get("session_id", f.stem),
                    "session_type": d.get("session_type", "?"),
                    "topic": d.get("topic", "")[:60],
                    "msg_count": len(d.get("messages", [])),
                    "updated_at": d.get("updated_at", ""),
                })
            except Exception:
                pass
        return sessions


# ── Agent 工具调度器 ──

def _make_tool_handler(session: LearningAgentSession, on_finalize: Callable | None = None):
    """创建工具处理函数"""
    async def handler(tool_name: str, tool_args: dict) -> str:
        if tool_name == "search_bilibili":
            query = tool_args.get("query", "")
            count = int(tool_args.get("count", 8))
            sort_by = tool_args.get("sort_by", "default")
            results = await _search_bilibili_agent(query, count, sort_by)
            # 存储到 session metadata 中
            if "searched_videos" not in session.metadata:
                session.metadata["searched_videos"] = []
            session.metadata["searched_videos"].extend(results)
            # 去重
            seen = set()
            unique = []
            for v in session.metadata["searched_videos"]:
                bv = v.get("bvid", "")
                if bv and bv not in seen:
                    seen.add(bv)
                    unique.append(v)
            session.metadata["searched_videos"] = unique
            return json.dumps({"count": len(results), "results": results}, ensure_ascii=False)

        elif tool_name == "web_search":
            query = tool_args.get("query", "")
            count = int(tool_args.get("count", 5))
            results = await _web_search_agent(query, count)
            if "web_results" not in session.metadata:
                session.metadata["web_results"] = []
            session.metadata["web_results"].extend(results)
            return json.dumps({"count": len(results), "results": results}, ensure_ascii=False)

        elif tool_name == "get_video_content":
            bvid = tool_args.get("bvid", "")
            result = await _get_video_content_agent(bvid)
            # 裁剪内容避免过长
            content = result.get("content", "")
            if len(content) > 8000:
                result["content"] = content[:8000] + "\n... (已截断)"
                result["truncated"] = True
            if "video_contents" not in session.metadata:
                session.metadata["video_contents"] = []
            session.metadata["video_contents"].append(result)
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "list_kb_files":
            files = _list_kb_files_agent()
            return json.dumps({"count": len(files), "files": files}, ensure_ascii=False)

        elif tool_name == "read_kb_file":
            filename = tool_args.get("filename", "")
            result = _read_kb_file_agent(filename)
            if "kb_contents" not in session.metadata:
                session.metadata["kb_contents"] = []
            session.metadata["kb_contents"].append(result)
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "finalize_deep_dive":
            topic = tool_args.get("topic", session.topic)
            report = tool_args.get("report", "")
            result = _save_deep_dive_result(session, topic, report)
            if on_finalize:
                on_finalize(result)
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "finalize_quiz":
            source_title = tool_args.get("source_title", "")
            quiz_content = tool_args.get("quiz_content", "")
            question_count = int(tool_args.get("question_count", 0))
            difficulty = tool_args.get("difficulty", "medium")
            result = _save_quiz_result(session, source_title, quiz_content, question_count, difficulty)
            if on_finalize:
                on_finalize(result)
            return json.dumps(result, ensure_ascii=False)

        return json.dumps({"error": f"未知工具: {tool_name}"})

    return handler


def _save_deep_dive_result(session: LearningAgentSession, topic: str, report: str) -> dict:
    """保存深入学习结果"""
    dd_dir = REPORT_EXPORT_DIR / "deep_dives"
    dd_dir.mkdir(parents=True, exist_ok=True)
    safe_topic = _safe_filename(topic)[:40]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"deepdive_agent_{safe_topic}_{timestamp}.md"
    saved_path = dd_dir / filename

    # 从 metadata 提取来源信息
    sources_md = ""
    videos = session.metadata.get("searched_videos", [])
    web_results = session.metadata.get("web_results", [])
    for v in videos:
        sources_md += f"- BV: {v.get('bvid','')} — {v.get('title','')} (UP: {v.get('author','')})\n"
    for w in web_results:
        sources_md += f"- [{w.get('title','')}]({w.get('url','')})\n"

    full_content = f"""# 📚 深入学习报告 (Agent): {topic}

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**模式**: Agent 多轮对话
**会话ID**: {session.session_id}

---

{report}

---

## 📖 参考来源
{sources_md or '(Agent 未记录明确来源)'}

---
*本报告由 AI Agent 自动生成，仅供参考学习*
"""
    saved_path.write_text(full_content, encoding='utf-8')

    # 归档知识库
    try:
        kb_dir = KNOWLEDGE_BASE_DIR / "深入学习"
        kb_dir.mkdir(parents=True, exist_ok=True)
        (kb_dir / filename).write_text(full_content, encoding='utf-8')
    except Exception:
        pass

    result = {
        "status": "saved",
        "topic": topic,
        "saved_path": str(saved_path),
        "report_preview": report[:300] + ("..." if len(report) > 300 else ""),
    }
    session.results.append(result)
    session.save()
    return result


def _save_quiz_result(session: LearningAgentSession, source_title: str, quiz_content: str,
                      question_count: int = 0, difficulty: str = "medium") -> dict:
    """保存考题结果"""
    quiz_dir = REPORT_EXPORT_DIR / "quizzes"
    quiz_dir.mkdir(parents=True, exist_ok=True)
    safe_title = _safe_filename(source_title)[:60]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"quiz_agent_{safe_title}_{timestamp}.md"
    saved_path = quiz_dir / filename

    full_content = f"{quiz_content}\n\n---\n*本考题由 AI Agent 自动生成，来源: {source_title}*"
    saved_path.write_text(full_content, encoding='utf-8')

    result = {
        "status": "saved",
        "source_title": source_title,
        "question_count": question_count,
        "difficulty": difficulty,
        "saved_path": str(saved_path),
    }
    session.results.append(result)
    session.save()
    return result


# ── Agent 运行核心 ──

async def run_learning_agent(
    session: LearningAgentSession,
    user_input: str = "",
    *,
    max_tool_rounds: int = 8,
    verbose: bool = True,
) -> str:
    """
    运行一次 Agent 对话轮次。

    Args:
        session: 会话对象
        user_input: 用户输入（空字符串表示继续当前会话的最后一轮）
        max_tool_rounds: 最大工具调用轮数
        verbose: 是否打印日志

    Returns:
        Agent 的文本回复
    """
    live = _live_config()
    if not live.get("api_key"):
        return "API 未配置，请在用户数据目录的 config.json 中设置 unified_api_key"

    # 选择系统提示词和工具
    if session.session_type == "deep_dive":
        system_prompt = SYSTEM_PROMPT_DEEP_DIVE
        tools = TOOLS_DEEP_DIVE
    else:
        system_prompt = SYSTEM_PROMPT_QUIZ
        tools = TOOLS_QUIZ

    # 首次对话：构建初始 messages
    if not session.messages:
        session.messages = [
            {"role": "system", "content": system_prompt},
        ]
        session.topic = user_input
        session.messages.append({
            "role": "user",
            "content": f"用户请求：{user_input}\n\n请按步骤执行，完成后再调用 finalize 工具结束。"
        })
    elif user_input.strip():
        # 追加用户消息
        session.messages.append({"role": "user", "content": user_input.strip()})

    # 收集 finalize 结果
    finalize_result: dict = {}

    def on_finalize(r: dict):
        nonlocal finalize_result
        finalize_result = r

    tool_handler = _make_tool_handler(session, on_finalize)

    if verbose:
        print(f"{Fore.CYAN}[AGENT] 会话 {session.session_id} | 类型: {session.session_type} | "
              f"历史消息: {len(session.messages)} 条{Style.RESET_ALL}")

    # 执行 Agent 循环
    try:
        reply = await call_ai_with_tools(
            messages=session.messages,
            tools=tools,
            temperature=0.5,
            max_tokens=4096,
            timeout=180.0,
            verbose=verbose,
            max_tool_rounds=max_tool_rounds,
            tool_handler=tool_handler,
        )
    except Exception as e:
        reply = f"❌ Agent 执行出错: {e}"
        if verbose:
            print(f"{Fore.RED}[AGENT] 错误: {e}{Style.RESET_ALL}")

    # 将 AI 回复追加到会话
    session.messages.append({"role": "assistant", "content": reply})
    session.save()

    # 如果有 finalize 结果，追加到回复
    if finalize_result:
        saved = finalize_result.get("saved_path", "")
        if saved:
            reply += f"\n\n✅ 已保存至: {saved}"

    return reply


async def run_multi_agent_deep_dive(
    topics: list[str],
    *,
    mode: str = "search",       # "search" | "bilibili"
    sort_by: str = "default",   # B站搜索排序
    video_count: int = 8,
    additional_context: str = "",
    parallel: bool = True,
    verbose: bool = True,
) -> dict[str, Any]:
    """
    多Agent协调：并行深入了解多个主题。

    Args:
        topics: 主题列表
        mode: 搜索模式
        sort_by: B站排序方式
        video_count: 每个主题的视频/来源数量
        parallel: 是否并行执行
        verbose: 是否打印日志

    Returns:
        {"success": True/False, "results": [...], "combined_report": str}
    """
    from services.deep_dive import run_deep_dive

    results = []

    async def _dive_one(topic: str, idx: int) -> dict:
        if verbose:
            print(f"{Fore.CYAN}[MULTI-AGENT] [{idx+1}/{len(topics)}] 开始探索: {topic}{Style.RESET_ALL}")
        try:
            r = await run_deep_dive(
                topic=topic,
                mode=mode,
                video_count=video_count,
                additional_context=additional_context,
                sort_by=sort_by,
                shortage_policy="continue",
            )
            if verbose:
                status = "✅" if r.get("success") else "❌"
                print(f"{Fore.GREEN if r.get('success') else Fore.RED}[MULTI-AGENT] [{idx+1}/{len(topics)}] {status} {topic}{Style.RESET_ALL}")
            return {"topic": topic, "result": r}
        except Exception as e:
            if verbose:
                print(f"{Fore.RED}[MULTI-AGENT] [{idx+1}/{len(topics)}] ❌ {topic}: {e}{Style.RESET_ALL}")
            return {"topic": topic, "result": {"success": False, "error": str(e)}}

    if parallel and len(topics) > 1:
        tasks = [_dive_one(t, i) for i, t in enumerate(topics)]
        results = await asyncio.gather(*tasks)
    else:
        for i, topic in enumerate(topics):
            results.append(await _dive_one(topic, i))

    # 生成综合报告
    success_count = sum(1 for r in results if r["result"].get("success"))
    combined_sections = []
    for r in results:
        if r["result"].get("success"):
            combined_sections.append(f"## {r['topic']}\n\n{r['result'].get('report', '')[:2000]}\n")

    combined_report = ""
    if len(combined_sections) > 1:
        if verbose:
            print(f"{Fore.CYAN}[MULTI-AGENT] 正在生成综合对比报告...{Style.RESET_ALL}")
        combined_text = "\n\n".join(combined_sections)
        summary_prompt = f"""以下是对 {len(topics)} 个主题的学习报告摘要：

{combined_text[:8000]}

请生成一份综合对比总结：
1. 各主题的核心要点
2. 主题之间的关联和交叉点
3. 整体的知识图谱概览
请用 Markdown 格式输出。"""

        try:
            combined_report = await call_ai(
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0.7,
                max_tokens=3000,
                timeout=120,
            )
        except Exception:
            combined_report = "\n\n".join(combined_sections)

    # 保存综合报告
    dd_dir = REPORT_EXPORT_DIR / "deep_dives"
    dd_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    topics_short = "_".join([_safe_filename(t)[:15] for t in topics[:3]])
    filename = f"deepdive_multi_{topics_short}_{timestamp}.md"
    saved_path = dd_dir / filename

    full_report = f"""# 📚 多主题综合学习报告

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**主题数量**: {len(topics)}
**成功数**: {success_count}
**模式**: {'B站视频' if mode == 'bilibili' else '联网搜索'}

## 主题列表
{chr(10).join(f'- {t}' for t in topics)}

---

{combined_report}

---

## 各主题详细报告
{chr(10).join(combined_sections[:3])}

---
*本报告由多Agent协调生成，仅供参考学习*
"""
    saved_path.write_text(full_report, encoding='utf-8')

    return {
        "success": success_count > 0,
        "total": len(topics),
        "success_count": success_count,
        "results": results,
        "combined_report": combined_report,
        "saved_path": str(saved_path),
    }


# ── CLI 菜单函数 ──

async def learning_agent_menu_cli(agent_type: str = "deep_dive"):
    """
    Agent 模式 CLI 菜单。
    agent_type: "deep_dive" | "quiz"
    """
    type_label = "深入了解" if agent_type == "deep_dive" else "出题考试"
    emoji = "🔬" if agent_type == "deep_dive" else "📝"

    while True:
        print(f"\n{Fore.CYAN}{'='*60}")
        print(f"  🤖 {emoji} {type_label} — Agent 模式")
        print(f"{'='*60}{Style.RESET_ALL}")

        # 列出已有会话
        sessions = LearningAgentSession.list_sessions(agent_type)
        if sessions:
            print(f"\n{Fore.YELLOW}📋 已有会话：{Style.RESET_ALL}")
            for i, s in enumerate(sessions[:10]):
                topic_preview = s.get("topic", "")[:40]
                print(f"  {Fore.GREEN}{i+1}.{Style.RESET_ALL} [{s['session_id']}] {topic_preview} "
                      f"({s['msg_count']}条消息, {s['updated_at'][:16]})")

        print(f"\n{Fore.YELLOW}选择操作：{Style.RESET_ALL}")
        print(f"  {Fore.GREEN}N.{Style.RESET_ALL} 新建会话")
        if sessions:
            print(f"  {Fore.GREEN}C.{Style.RESET_ALL} 继续已有会话（输入编号）")
        print(f"  {Fore.GREEN}M.{Style.RESET_ALL} 🚀 多Agent协调（仅深入了解）" if agent_type == "deep_dive" else "")
        print(f"  {Fore.GREEN}D.{Style.RESET_ALL} 删除会话")
        print(f"  {Fore.RED}0.{Style.RESET_ALL} ↩️ 返回上一级")

        choice = input(f"{Fore.CYAN}请选择: {Style.RESET_ALL}").strip()

        if choice == "0":
            break

        elif choice.lower() == "n":
            # 新建会话
            if agent_type == "deep_dive":
                topic = input(f"{Fore.CYAN}请输入想了解的主题（支持多个，用逗号分隔）: {Style.RESET_ALL}").strip()
                if not topic:
                    print(f"{Fore.RED}[ERROR] 主题不能为空{Style.RESET_ALL}")
                    continue
                ctx = input(f"{Fore.CYAN}补充说明（可选）: {Style.RESET_ALL}").strip()
                full_input = f"深入了解：{topic}"
                if ctx:
                    full_input += f"\n补充说明：{ctx}"
            else:
                # 出题
                print(f"\n{Fore.YELLOW}请选择题目的内容来源：{Style.RESET_ALL}")
                print("  1. 📹 指定 B站视频（BV号）")
                print("  2. 📚 从知识库中选择")

                src_choice = input(f"{Fore.CYAN}请选择 (1/2): {Style.RESET_ALL}").strip()
                if src_choice == "1":
                    bvid = input(f"{Fore.CYAN}请输入 BV 号: {Style.RESET_ALL}").strip()
                    bv_match = re.search(r'(BV[0-9A-Za-z]{10})', bvid)
                    if bv_match:
                        bvid = bv_match.group(1)
                    else:
                        print(f"{Fore.RED}[ERROR] 无效的 BV 号格式{Style.RESET_ALL}")
                        continue
                    diff = input(f"{Fore.CYAN}难度 (easy/medium/hard, 默认medium): {Style.RESET_ALL}").strip() or "medium"
                    count_str = input(f"{Fore.CYAN}题目数量 (默认5): {Style.RESET_ALL}").strip() or "5"
                    full_input = f"请从B站视频 BV{bvid} 的字幕内容中，生成 {count_str} 道{diff}难度的考题。"
                elif src_choice == "2":
                    from services.quiz_generator import scan_kb_files
                    files = scan_kb_files()
                    if not files:
                        print(f"{Fore.YELLOW}[INFO] 知识库为空{Style.RESET_ALL}")
                        continue
                    print(f"\n{Fore.GREEN}知识库文件列表：{Style.RESET_ALL}")
                    for i, f in enumerate(files[:20]):
                        print(f"  {i+1:2d}. [{f['category_path']}] {f['name'][:60]}")
                    idx_str = input(f"{Fore.CYAN}选择编号: {Style.RESET_ALL}").strip()
                    try:
                        idx = int(idx_str) - 1
                        if 0 <= idx < len(files):
                            kb_file = files[idx]['file_path']
                            full_input = f"请从知识库文件 {files[idx]['name']} 中生成考题。文件路径: {kb_file}"
                        else:
                            continue
                    except ValueError:
                        continue
                else:
                    continue

            session = LearningAgentSession(session_type=agent_type)
            print(f"\n{Fore.GREEN}[AGENT] 新建会话: {session.session_id}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}[AGENT] 正在处理...{Style.RESET_ALL}")

            reply = await run_learning_agent(session, full_input, verbose=True)

            print(f"\n{Fore.GREEN}{'='*60}")
            print(reply)
            print(f"{'='*60}{Style.RESET_ALL}")
            print(f"\n{Fore.CYAN}💡 会话ID: {session.session_id} — 可以继续对话或重新编辑{Style.RESET_ALL}")

            # 继续对话循环
            await _continue_chat_loop(session)

        elif choice.lower() == "c" and sessions:
            # 继续已有会话
            try:
                idx = int(choice) if choice.isdigit() else None
            except ValueError:
                idx = None
            if idx is None:
                s_idx_str = input(f"{Fore.CYAN}输入会话编号: {Style.RESET_ALL}").strip()
                try:
                    idx = int(s_idx_str) - 1
                except ValueError:
                    continue
            if 0 <= idx < len(sessions):
                session = LearningAgentSession.load(sessions[idx]["session_id"])
                if not session:
                    print(f"{Fore.RED}[ERROR] 会话加载失败{Style.RESET_ALL}")
                    continue
                print(f"{Fore.GREEN}[AGENT] 已加载会话: {session.session_id}{Style.RESET_ALL}")
                print(f"  主题: {session.topic[:60]}")
                print(f"  历史消息: {len(session.messages)} 条")
                await _continue_chat_loop(session)

        elif choice.lower() == "m" and agent_type == "deep_dive":
            # 多Agent协调
            await _multi_agent_menu_cli()

        elif choice.lower() == "d":
            # 删除会话
            sid = input(f"{Fore.CYAN}输入要删除的会话ID: {Style.RESET_ALL}").strip()
            path = SESSION_DIR / f"{sid}.json"
            if path.exists():
                path.unlink()
                print(f"{Fore.GREEN}[OK] 已删除会话: {sid}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[INFO] 会话不存在{Style.RESET_ALL}")

        else:
            print(f"{Fore.YELLOW}[INFO] 无效选项{Style.RESET_ALL}")


async def _continue_chat_loop(session: LearningAgentSession):
    """Agent 继续对话循环"""
    while True:
        print(f"\n{Fore.CYAN}--- Agent 对话中 (会话: {session.session_id}) ---{Style.RESET_ALL}")
        print(f"  输入消息继续对话 / 输入 'done' 结束 / 输入 'retry' 重新最后一次")
        user_msg = input(f"{Fore.CYAN}✏️ > {Style.RESET_ALL}").strip()

        if not user_msg:
            continue
        if user_msg.lower() == "done":
            print(f"{Fore.GREEN}[AGENT] 会话已保存，会话ID: {session.session_id}{Style.RESET_ALL}")
            break
        if user_msg.lower() == "retry":
            if len(session.messages) >= 2:
                # 移除最后一条 assistant 回复
                if session.messages[-1]["role"] == "assistant":
                    session.messages.pop()
                print(f"{Fore.YELLOW}[AGENT] 已回退最后一条回复，请重新输入{Style.RESET_ALL}")
            continue

        reply = await run_learning_agent(session, user_msg, verbose=True)
        print(f"\n{Fore.GREEN}{'='*60}")
        print(reply)
        print(f"{'='*60}{Style.RESET_ALL}")


async def _multi_agent_menu_cli():
    """多Agent协调菜单"""
    print(f"\n{Fore.CYAN}{'='*60}")
    print("  🚀 多Agent协调 — 并行深入了解多个主题")
    print(f"{'='*60}{Style.RESET_ALL}")

    topics_str = input(f"{Fore.CYAN}请输入多个主题（逗号分隔，如：机器学习,深度学习,强化学习）: {Style.RESET_ALL}").strip()
    if not topics_str:
        return
    topics = [t.strip() for t in topics_str.split(",") if t.strip()]
    if not topics:
        return
    if len(topics) > 10:
        print(f"{Fore.YELLOW}[WARN] 最多10个主题，已截取前10个{Style.RESET_ALL}")
        topics = topics[:10]

    print(f"\n{Fore.GREEN}将并行探索 {len(topics)} 个主题：{', '.join(topics)}{Style.RESET_ALL}")

    print(f"\n{Fore.YELLOW}搜索模式：{Style.RESET_ALL}")
    print("  1. 🔍 联网搜索（推荐）")
    print("  2. 📺 B站视频搜索")
    mode_choice = input(f"{Fore.CYAN}请选择 (1/2, 默认1): {Style.RESET_ALL}").strip()
    mode = "bilibili" if mode_choice == "2" else "search"

    sort_by = "default"
    if mode == "bilibili":
        print(f"\n{Fore.YELLOW}排序方式：{Style.RESET_ALL}")
        print("  1. 综合排序（默认）")
        print("  2. 最新发布")
        print("  3. 最多播放")
        print("  4. 最多收藏")
        sort_map = {"1": "default", "2": "newest", "3": "most_played", "4": "most_faved"}
        sort_choice = input(f"{Fore.CYAN}请选择 (1-4, 默认1): {Style.RESET_ALL}").strip()
        sort_by = sort_map.get(sort_choice, "default")

    count_str = input(f"{Fore.CYAN}每个主题的视频/来源数量 (默认8): {Style.RESET_ALL}").strip()
    try:
        video_count = int(count_str) if count_str else 8
        video_count = max(2, min(20, video_count))
    except ValueError:
        video_count = 8

    ctx = input(f"{Fore.CYAN}补充说明（可选）: {Style.RESET_ALL}").strip()

    print(f"\n{Fore.GREEN}[MULTI-AGENT] 开始并行学习...{Style.RESET_ALL}")
    result = await run_multi_agent_deep_dive(
        topics=topics,
        mode=mode,
        sort_by=sort_by,
        video_count=video_count,
        additional_context=ctx,
        parallel=True,
        verbose=True,
    )

    print(f"\n{Fore.GREEN}{'='*60}")
    print(f"  ✅ 多Agent完成！")
    print(f"  成功: {result['success_count']}/{result['total']}")
    print(f"  综合报告: {result.get('saved_path', 'N/A')}")
    print(f"{'='*60}{Style.RESET_ALL}")

    if result.get("combined_report"):
        print(f"\n{Fore.CYAN}【综合对比报告预览】{Style.RESET_ALL}")
        preview = result["combined_report"][:2000]
        print(preview)
        if len(result["combined_report"]) > 2000:
            print(f"\n{Fore.YELLOW}... (完整报告见保存文件){Style.RESET_ALL}")

    input(f"\n{Fore.CYAN}按 Enter 继续...{Style.RESET_ALL}")


# ── 便捷入口：一次性模式 vs Agent模式 选择 ──

async def deep_dive_with_mode():
    """深入了解 — 选择一次性模式还是Agent模式"""
    print(f"\n{Fore.CYAN}{'='*60}")
    print("  🔬 深入了解 — 选择学习模式")
    print(f"{'='*60}{Style.RESET_ALL}")
    print(f"  {Fore.GREEN}1.{Style.RESET_ALL} ⚡ 一次性对话 — 输入主题→搜索→AI生成报告（适合简单快速查询）")
    print(f"  {Fore.GREEN}2.{Style.RESET_ALL} 🤖 Agent 模式 — 多轮对话、工具调用、可继续编辑（适合长任务/深入探索）")
    print(f"  {Fore.GREEN}3.{Style.RESET_ALL} 🚀 多Agent协调 — 并行探索多个主题（适合对比学习）")
    print(f"  {Fore.GREEN}4.{Style.RESET_ALL} 🔎 深研计划 — 多来源证据链、分歧分析、来源快照与后续验证项")
    print(f"  {Fore.RED}0.{Style.RESET_ALL} ↩️ 返回")

    choice = input(f"{Fore.CYAN}请选择 (1/2/3/4/0): {Style.RESET_ALL}").strip()

    if choice == "0":
        return
    elif choice == "1":
        from services.deep_dive import deep_dive_menu_cli
        await deep_dive_menu_cli()
    elif choice == "2":
        await learning_agent_menu_cli("deep_dive")
    elif choice == "3":
        await _multi_agent_menu_cli()
    elif choice == "4":
        from services.deep_dive import deep_research_menu_cli
        await deep_research_menu_cli()
    else:
        print(f"{Fore.YELLOW}[INFO] 无效选项{Style.RESET_ALL}")


async def quiz_with_mode():
    """出题考试 — 选择一次性模式还是Agent模式"""
    print(f"\n{Fore.CYAN}{'='*60}")
    print("  📝 出题考试 — 选择出题模式")
    print(f"{'='*60}{Style.RESET_ALL}")
    print(f"  {Fore.GREEN}1.{Style.RESET_ALL} ⚡ 一次性对话 — 选择来源→配置→AI生成考题（适合快速出题）")
    print(f"  {Fore.GREEN}2.{Style.RESET_ALL} 🤖 Agent 模式 — 多轮对话、可调整题目、继续编辑（适合反复打磨）")
    print(f"  {Fore.RED}0.{Style.RESET_ALL} ↩️ 返回")

    choice = input(f"{Fore.CYAN}请选择 (1/2/0): {Style.RESET_ALL}").strip()

    if choice == "0":
        return
    elif choice == "1":
        from services.quiz_generator import quiz_menu_cli
        await quiz_menu_cli()
    elif choice == "2":
        await learning_agent_menu_cli("quiz")
    else:
        print(f"{Fore.YELLOW}[INFO] 无效选项{Style.RESET_ALL}")
