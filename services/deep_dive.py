"""
deep_dive.py — AI 深入了解引擎

功能：
1. 用户输入想了解的主题（如"向量数据库"）
2. 两种模式：
   - 模式 A: AI 调用搜索 API 搜索关键词 → 了解内容（推荐）
   - 模式 B: AI 在 B站刷视频学习
3. 用户可指定视频数量（默认 10）
4. 生成综合学习报告

设计为同时供 CLI（main.py）和 Web（web_panel.py）调用。
"""

from __future__ import annotations

import json
import os
import re
import asyncio
from pathlib import Path
from typing import Any
from datetime import datetime

from colorama import Fore, Style

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "Data"
KNOWLEDGE_BASE_DIR = BASE_DIR / "KnowledgeBase"
REPORT_EXPORT_DIR = BASE_DIR / "html_exports" / "deep_dives"


from services._services_ai import call_ai, _live_config


def _load_bili_cookies() -> dict:
    cookie_file = DATA_DIR / "bilibili_cookies.json"
    if cookie_file.exists():
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


async def _web_search(query: str, limit: int = 8) -> list[dict[str, str]]:
    """联网搜索（复用项目内 logic）"""
    try:
        from knowledge.web_search import web_search
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, lambda: web_search(query, limit=limit))
        return results
    except Exception:
        pass

    # 降级：直接 httpx
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
                import re as _re
                blocks = _re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', resp.text, re.DOTALL)
                for block in blocks[:limit]:
                    url_m = _re.search(r'href="(https?://[^"]+)"', block)
                    title_m = _re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL)
                    snippet_m = _re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
                    if title_m and url_m:
                        results.append({
                            "title": _re.sub(r'<[^>]+>', '', title_m.group(1)).strip(),
                            "url": url_m.group(1),
                            "snippet": _re.sub(r'<[^>]+>', '', (snippet_m.group(1) if snippet_m else '')).strip()[:500],
                        })
        return results[:limit]
    except Exception:
        return []


async def _search_bilibili(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """搜索 B站视频"""
    try:
        import httpx
        from core.config import config

        cookies = _load_bili_cookies()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.bilibili.com/'
        }

        async with httpx.AsyncClient(http2=True, headers=headers, cookies=cookies, timeout=15.0) as client:
            resp = await client.get(
                'https://api.bilibili.com/x/web-interface/search/type',
                params={'search_type': 'video', 'keyword': query, 'page': 1}
            )
            data = resp.json()
            if data.get('code') == 0:
                results = []
                for v in data['data'].get('result', [])[:limit]:
                    results.append({
                        "bvid": v.get('bvid', ''),
                        "title": v.get('title', '').replace('<em class="keyword">', '').replace('</em>', ''),
                        "author": v.get('author', ''),
                        "play": v.get('play', 0),
                        "duration": v.get('duration', ''),
                        "description": v.get('description', '')[:200],
                        "pic": v.get('pic', ''),
                    })
                return results
    except Exception:
        pass
    return []


async def _fetch_video_subtitles_simple(bvid: str) -> str:
    """获取视频字幕文本"""
    try:
        from api.subtitles import fetch_bilibili_subtitles
        cookies = _load_bili_cookies()
        result = await fetch_bilibili_subtitles(bvid, cookies_obj=cookies if cookies else None)
        if result and result.get("subtitle_text"):
            return result["subtitle_text"]
    except Exception:
        pass
    return ""


async def run_deep_dive(
    *,
    topic: str,
    mode: str = "search",           # "search" 或 "bilibili"
    video_count: int = 10,
    additional_context: str = "",    # 用户额外说明
) -> dict[str, Any]:
    """
    深入了解某个主题

    返回: {
        "success": bool,
        "report": str,            # 综合学习报告
        "sources": list,          # 信息来源列表
        "videos_watched": int,    # 观看的视频数
        "saved_path": str,        # 保存路径
        "error": str or None
    }
    """
    result = {
        "success": False,
        "report": "",
        "sources": [],
        "videos_watched": 0,
        "saved_path": "",
        "error": None,
    }

    live = _live_config()
    if not live.get("api_key"):
        result["error"] = "API 未配置，请在 Data/config.json 中设置 unified_api_key"
        return result

    all_sources = []
    collected_content = []
    videos_watched = 0

    # ── Step 1: AI 生成搜索策略 ──
    print(f"{Fore.CYAN}[DEEP DIVE] 正在分析主题: {topic}{Style.RESET_ALL}")

    strategy_prompt = f"""你是一个学习助手。用户想深入了解以下主题："{topic}"
{f'补充说明：{additional_context}' if additional_context else ''}

请生成 3-5 个有效的搜索关键词（中英文均可），用于在搜索引擎或B站上搜索相关资料。
只需输出关键词列表，每行一个，不要其他内容。"""

    try:
        keywords_text = await call_ai(
            messages=[{"role": "user", "content": strategy_prompt}],
            temperature=0.5,
            max_tokens=300,
            timeout=30,
            verbose=False,  # 步骤内静默
        )
        keywords = [k.strip().strip('0123456789.、)- ').strip() for k in keywords_text.strip().split('\n') if k.strip()]
        keywords = [k for k in keywords if len(k) > 1][:5]
        if not keywords:
            keywords = [topic]
    except Exception:
        keywords = [topic]

    print(f"{Fore.GREEN}[DEEP DIVE] 搜索关键词: {', '.join(keywords)}{Style.RESET_ALL}")

    # ── Step 2: 执行搜索 ──
    if mode == "bilibili":
        # 模式 B: B站视频搜索
        total_videos = []
        for kw in keywords[:3]:
            videos = await _search_bilibili(kw, limit=max(3, video_count // 3))
            for v in videos:
                if v['bvid'] not in [x['bvid'] for x in total_videos]:
                    total_videos.append(v)

        total_videos = total_videos[:video_count]
        print(f"{Fore.GREEN}[DEEP DIVE] 找到 {len(total_videos)} 个视频{Style.RESET_ALL}")

        for i, video in enumerate(total_videos):
            print(f"{Fore.CYAN}[DEEP DIVE] 正在学习视频 {i+1}/{len(total_videos)}: {video['title'][:50]}...{Style.RESET_ALL}")
            subtitles = await _fetch_video_subtitles_simple(video['bvid'])

            source_info = {
                "type": "bilibili",
                "bvid": video['bvid'],
                "title": video['title'],
                "author": video['author'],
                "url": f"https://www.bilibili.com/video/{video['bvid']}",
            }
            all_sources.append(source_info)
            videos_watched += 1

            if subtitles and len(subtitles) > 200:
                collected_content.append(f"## {video['title']}\n作者: {video['author']}\n\n{subtitles[:5000]}")
            else:
                # 只有标题和描述
                collected_content.append(
                    f"## {video['title']}\n作者: {video['author']}\n描述: {video.get('description', '无')[:800]}"
                )

        if not collected_content:
            result["error"] = "未能获取任何视频内容。建议使用搜索模式重试。"
            return result

    else:
        # 模式 A: 联网搜索（推荐）
        all_search_results = []
        for kw in keywords:
            search_results = await _web_search(kw, limit=max(2, video_count // len(keywords)))
            all_search_results.extend(search_results)

        all_search_results = all_search_results[:max(video_count, 15)]
        print(f"{Fore.GREEN}[DEEP DIVE] 搜索到 {len(all_search_results)} 个网页结果{Style.RESET_ALL}")

        for sr in all_search_results:
            source_info = {
                "type": "web",
                "title": sr.get('title', ''),
                "url": sr.get('url', ''),
                "snippet": sr.get('snippet', '')[:500],
            }
            all_sources.append(source_info)
            collected_content.append(
                f"## {source_info['title']}\nURL: {source_info['url']}\n摘要: {source_info['snippet']}"
            )

    # ── Step 3: AI 综合总结 ──
    print(f"{Fore.GREEN}[DEEP DIVE] 正在生成综合报告...{Style.RESET_ALL}")

    content_text = '\n\n'.join(collected_content)
    if len(content_text) > 20000:
        content_text = content_text[:20000] + "\n\n... (内容过长已截断)"

    report_prompt = f"""你是一个知识整理专家。用户想深入了解主题："{topic}"

请根据以下搜索到的资料，生成一份结构化的综合学习报告。

要求：
1. 首先给出主题的核心概念概述
2. 分章节讲解关键知识点
3. 指出重点和难点
4. 提供进一步学习的建议/资源
5. 引用来源（标注出自哪个视频/网页）

-------- 资料内容 --------
{content_text}
-------- 内容结束 --------

请用 Markdown 格式输出完整的学习报告。"""

    try:
        report = await call_ai(
            messages=[
                {"role": "system", "content": "你是一名专业的知识整理和教学专家，擅长将复杂内容整理成清晰易读的学习报告。请用中文回复。"},
                {"role": "user", "content": report_prompt}
            ],
            temperature=0.7,
            max_tokens=6000,
            timeout=180,
        )
    except Exception as e:
        result["error"] = f"AI 生成报告失败: {e}"
        return result

    # ── Step 4: 保存 ──
    REPORT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe_topic = re.sub(r'[\\/:*?"<>|]', '_', topic)[:40]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"deepdive_{safe_topic}_{timestamp}.md"
    saved_path = REPORT_EXPORT_DIR / filename

    sources_md = "\n".join(
        f"- [{s.get('title', '')}]({s.get('url', '')})" if s['type'] == 'web'
        else f"- BV: {s.get('bvid','')} — {s.get('title','')} (UP: {s.get('author','')})"
        for s in all_sources
    )

    full_content = f"""# 📚 深入学习报告: {topic}

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**模式**: {'联网搜索' if mode == 'search' else 'B站视频学习'}
**信息来源数**: {len(all_sources)}
**搜索关键词**: {', '.join(keywords)}

---

{report}

---

## 📖 参考来源
{sources_md}

---
*本报告由 AI 自动生成，仅供参考学习*
"""
    saved_path.write_text(full_content, encoding='utf-8')

    result["success"] = True
    result["report"] = report
    result["sources"] = all_sources
    result["videos_watched"] = videos_watched
    result["saved_path"] = str(saved_path)

    # ── Step 5: 可选归档知识库 ──
    try:
        kb_dir = KNOWLEDGE_BASE_DIR / "深入学习"
        kb_dir.mkdir(parents=True, exist_ok=True)
        kb_file = kb_dir / filename
        kb_file.write_text(full_content, encoding='utf-8')
        print(f"{Fore.GREEN}[DEEP DIVE] 已归档至知识库: {kb_file}{Style.RESET_ALL}")
    except Exception:
        pass

    return result


# ── CLI 菜单函数 ──
async def deep_dive_menu_cli():
    """CLI 深入了解菜单"""
    print(f"\n{Fore.CYAN}{'='*50}")
    print("  🔬 深入了解 — AI 深度学习助手")
    print(f"{'='*50}{Style.RESET_ALL}")

    topic = input(f"{Fore.CYAN}请输入你想了解的主题: {Style.RESET_ALL}").strip()
    if not topic:
        print(f"{Fore.RED}[ERROR] 主题不能为空{Style.RESET_ALL}")
        return

    print(f"\n{Fore.YELLOW}请选择学习模式：{Style.RESET_ALL}")
    print("  1. 🔍 联网搜索模式（推荐）— AI 调用搜索引擎搜索相关资料并总结")
    print("  2. 📺 B站视频模式（不推荐）— AI 在B站搜索视频并逐个观看学习")

    mode_choice = input(f"{Fore.CYAN}请选择 (1/2, 默认1): {Style.RESET_ALL}").strip()
    if mode_choice == "2":
        mode = "bilibili"
        print(f"{Fore.YELLOW}[WARN] B站模式需要已登录且视频有字幕，速度较慢{Style.RESET_ALL}")
    else:
        mode = "search"

    video_count_str = input(f"{Fore.CYAN}搜索/观看数量 (默认10): {Style.RESET_ALL}").strip()
    try:
        video_count = int(video_count_str) if video_count_str else 10
        video_count = max(1, min(50, video_count))
    except ValueError:
        video_count = 10

    ctx = input(f"{Fore.CYAN}补充说明（可选，如入门级别、需要代码示例）: {Style.RESET_ALL}").strip()

    print(f"\n{Fore.GREEN}[DEEP DIVE] 开始学习...")
    print(f"  主题: {topic}")
    print(f"  模式: {'联网搜索' if mode == 'search' else 'B站视频'}")
    print(f"  数量: {video_count}{Style.RESET_ALL}")

    result = await run_deep_dive(
        topic=topic,
        mode=mode,
        video_count=video_count,
        additional_context=ctx,
    )

    if result["success"]:
        print(f"\n{Fore.GREEN}{'='*60}")
        print(result["report"])
        print(f"{'='*60}{Style.RESET_ALL}")
        print(f"\n{Fore.GREEN}[OK] 学习报告已保存至: {result['saved_path']}{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}[ERROR] {result['error']}{Style.RESET_ALL}")

    input(f"\n{Fore.CYAN}按 Enter 继续...{Style.RESET_ALL}")
