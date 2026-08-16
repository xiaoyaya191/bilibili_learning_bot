"""联网搜索能力 —— 给 skills.py 提供 WebSearch 类"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class WebSearch:
    """轻量联网搜索（DuckDuckGo 后备）"""

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """返回搜索结果列表"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    "https://lite.duckduckgo.com/lite/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            if resp.status_code != 200:
                return []
            # 简单 HTML 提取
            results: list[SearchResult] = []
            body = resp.text
            import re
            link_blocks = re.findall(
                r'<a[^>]*href="([^"]*uddg=([^"]+))"[^>]*class="result-link"[^>]*>(.*?)</a>.*?'
                r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
                body, re.DOTALL,
            )
            for _, url_enc, title_raw, snippet_raw in link_blocks:
                if len(results) >= limit:
                    break
                try:
                    from urllib.parse import unquote
                    url = unquote(url_enc)
                except Exception:
                    url = url_enc
                title = re.sub(r"<[^>]+>", "", title_raw).strip()
                snippet = re.sub(r"<[^>]+>", "", snippet_raw).strip()
                if url:
                    results.append(SearchResult(title=title, url=url, snippet=snippet))
            return results
        except Exception as e:
            print(f"[web_search] DuckDuckGo搜索失败: {e}")
            return []
