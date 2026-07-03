"""knowledge/web_search.py — 网络搜索 + AI 知识验证"""
import re
import json
import os
import shutil
import httpx
from datetime import datetime
from html.parser import HTMLParser

from core.config import config, KNOWLEDGE_BASE_DIR
# 从 config 实时读取，避免 import * 缓存问题
def _get_model_brain():
    return config.get("api", {}).get("model_brain", "")
from utils.display import log
from utils.helpers import _mask_urls
from api.subtitles import SYSTEM_PROMPT_KNOWLEDGE_VERIFY
from openai import OpenAI

async def _fetch_search_page(client, url, params=None, headers_extra=None):
    """通用搜索页面抓取（带超时和异常处理）。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    if headers_extra:
        headers.update(headers_extra)
    try:
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        log(f"[WARN] B站搜索页获取失败: {e}", "WARN")
    return None


def _parse_bing_html(html: str, limit: int) -> list:
    """从 Bing 搜索结果 HTML 中提取结果。"""
    results = []
    try:
        import re
        blocks = re.findall(r'<li class="b_algo".*?</li>', html, re.DOTALL)
        if not blocks:
            blocks = re.findall(r'<li class="b_ans".*?</li>', html, re.DOTALL)
        if not blocks:
            blocks = re.findall(r'<h2[^>]*>.*?</h2>.*?<p[^>]*>.*?</p>', html, re.DOTALL)
        for block in blocks[:limit]:
            url_match = re.search(r'<a[^>]*href="(https?://[^"]+)"', block)
            title_match = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL) or re.search(r'<a[^>]*>(.*?)</a>', block, re.DOTALL)
            snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
            title = re.sub(r'<[^>]+>', '', title_match.group(1) if title_match else "").strip()
            snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1) if snippet_match else "").strip()
            url = url_match.group(1) if url_match else ""
            if title and (snippet or url):
                results.append({"title": title[:120], "snippet": snippet[:300], "url": url})
    except Exception as e:
        log(f"[WARN] Bing搜索解析失败: {e}", "WARN")
    return results


def _parse_sogou_html(html: str, limit: int) -> list:
    """从搜狗搜索 HTML 中提取结果。"""
    results = []
    try:
        import re
        titles = re.findall(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL)
        snippets = re.findall(r'<p class="(?:star-wiki|str_info|str-text|str_info_ws)[^"]*">(.*?)</p>', html, re.DOTALL)
        for i, (url, title_raw) in enumerate(titles[:limit]):
            title = re.sub(r'<[^>]+>', '', title_raw).strip()
            snippet = re.sub(r'<[^>]+>', '', snippets[i] if i < len(snippets) else "").strip()
            if title:
                results.append({"title": title[:120], "snippet": snippet[:300], "url": url})
    except Exception as e:
        log(f"[WARN] 搜狗搜索解析失败: {e}", "WARN")
    return results


async def web_search(query: str, limit: int = 5) -> list:
    """多引擎联网搜索（自动切换可用引擎）。
    搜索顺序: Bing → 搜狗 → DuckDuckGo → Wikipedia
    返回: [{"title": "...", "snippet": "...", "url": "..."}, ...]
    """
    results = []
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        # --- 引擎1: Bing ---
        html = await _fetch_search_page(client, "https://www.bing.com/search", params={"q": query, "count": limit})
        if html:
            results = _parse_bing_html(html, limit)
            if results:
                return results
        # --- 引擎2: 搜狗 ---
        html = await _fetch_search_page(client, "https://m.sogou.com/web/sl", params={"keyword": query, "vr": "1"}, headers_extra={"Referer": "https://m.sogou.com/"})
        if html:
            results = _parse_sogou_html(html, limit)
            if results:
                return results
        # --- 引擎3: DuckDuckGo Lite ---
        html = await _fetch_search_page(client, "https://lite.duckduckgo.com/lite/", params={"q": query})
        if html:
            from html.parser import HTMLParser
            class DDHtmlParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.results, self._in_link, self._in_snippet = [], False, False
                    self._current, self._text_buf = {"title": "", "snippet": "", "url": ""}, ""
                def handle_starttag(self, tag, attrs):
                    d = dict(attrs)
                    if tag == "a" and "result-link" in d.get("class", ""):
                        self._in_link = True; self._current["url"] = d.get("href", "")
                    elif tag == "td" and "result-snippet" in d.get("class", ""):
                        self._in_snippet = True
                def handle_endtag(self, tag):
                    if tag == "a" and self._in_link:
                        self._in_link = False; self._current["title"] = self._text_buf.strip(); self._text_buf = ""
                    elif tag == "td" and self._in_snippet:
                        self._in_snippet = False; self._current["snippet"] = self._text_buf.strip(); self._text_buf = ""
                        if self._current["title"] or self._current["snippet"]:
                            self.results.append(dict(self._current))
                        self._current = {"title": "", "snippet": "", "url": ""}
                def handle_data(self, data):
                    if self._in_link or self._in_snippet: self._text_buf += data
            try:
                parser = DDHtmlParser(); parser.feed(html)
                results = parser.results[:limit]
            except Exception as e:
                log(f"[WARN] DuckDuckGo搜索解析失败: {e}", "WARN")
            if results: return results
    # --- 引擎4: Wikipedia ---
    if not results:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get("https://en.wikipedia.org/w/api.php", params={"action": "opensearch", "search": query, "limit": limit, "format": "json"}, headers={"User-Agent": "TermuxBot/1.0"})
                if resp.status_code == 200:
                    data = resp.json()
                    for t, s, u in zip(data[1] if len(data)>1 else [], data[2] if len(data)>2 else [], data[3] if len(data)>3 else []):
                        results.append({"title": t, "snippet": s, "url": u})
        except Exception as e:
            log(f"[WARN] Wikipedia搜索失败: {e}", "WARN")
    return results

async def verify_knowledge_with_ai(knowledge_content: str, video_title: str, web_results: list = None) -> dict:
    """使用AI验证知识的真实性（结合联网搜索结果）。
    
    参数:
        knowledge_content: 知识文件的完整内容
        video_title: 视频标题
        web_results: 联网搜索结果（可选）
    
    返回: 验证结果 dict
    """
    web_context = ""
    if web_results:
        web_context = "\n\n【联网搜索结果】:\n" + "\n".join(
            f"- [{r.get('title', '')}] {r.get('snippet', '')[:200]}\n  URL: {r.get('url', '')}"
            for r in web_results[:5] if r.get('snippet')
        )
    
    verify_context = f"""请验证以下从B站视频学到的知识是否真实可靠：

【视频标题】: {video_title}

【已学习的知识内容】:
{knowledge_content[:4000]}
{web_context}

请逐条核实，判断是否有错误、过时或需要补充的内容。"""
    
    try:
        client = OpenAI(api_key=config.get("api", {}).get("unified_api_key", ""), base_url=config.get("api", {}).get("unified_base_url", ""), timeout=120)
        resp = client.chat.completions.create(
            model=_get_model_brain(),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_KNOWLEDGE_VERIFY},
                {"role": "user", "content": verify_context}
            ]
        )
        raw = resp.choices[0].message.content.strip()
        start = raw.find("{")
        # [FIX] 嵌套匹配提取JSON，防止 rfind 被多花括号干扰
        if start >= 0:
            depth = 0
            match_end = -1
            for i in range(start, len(raw)):
                if raw[i] == '{':
                    depth += 1
                elif raw[i] == '}':
                    depth -= 1
                    if depth == 0:
                        match_end = i
                        break
            if match_end >= 0:
                raw = raw[start:match_end + 1]
            else:
                end = raw.rfind("}")
                if end >= start:
                    raw = raw[start:end + 1]
        result = json.loads(raw)
        # 防御：如果 AI 返回的是非 dict（如纯字符串），用默认值兜底
        if not isinstance(result, dict):
            log(f"知识验证AI返回非dict类型({type(result).__name__})，使用默认值", "WARN")
            return {"overall_reliable": True, "overall_score": 0.7, "issues": [], "supplements": [], "recommend_rewrite": False, "rewrite_reason": "", "corrected_content": None}
        return result
    except json.JSONDecodeError as e:
        log(f"知识验证JSON解析失败: {e}", "WARN")
        return {"overall_reliable": True, "overall_score": 0.7, "issues": [], "supplements": [], "recommend_rewrite": False, "rewrite_reason": "", "corrected_content": None}
    except Exception as e:
        log(f"知识验证失败: {e}", "WARN")
        return {"overall_reliable": True, "overall_score": 0.7, "issues": [], "supplements": [], "recommend_rewrite": False, "rewrite_reason": "", "corrected_content": None}


def backup_and_rewrite_knowledge(file_path: str, corrected_content: str, verify_result: dict):
    """备份原知识文件（添加"备份_"前缀），然后写入修正后的内容。
    
    参数:
        file_path: 原知识文件路径
        corrected_content: 修正后的完整Markdown内容
        verify_result: 验证结果（用于日志）
    """
    dir_name = os.path.dirname(file_path)
    base_name = os.path.basename(file_path)
    backup_name = f"备份_{base_name}"
    backup_path = os.path.join(dir_name, backup_name)
    
    try:
        # 备份原文件
        shutil.copy2(file_path, backup_path)
        log(f"📦 原知识文件已备份: {backup_path}", "KB")
        
        # 添加验证标记到新内容
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        verify_header = (
            f"\n\n---\n\n"
            f"## 🔍 知识验证记录\n\n"
            f"- **验证时间**: {timestamp}\n"
            f"- **可靠性评分**: {verify_result.get('overall_score', 0):.0%}\n"
            f"- **发现的问题**: {len(verify_result.get('issues', []))} 处\n"
        )
        for issue in verify_result.get("issues", []):
            if issue.get("verdict") in ("存疑", "错误", "过时"):
                verify_header += f"  - [ERROR] {issue.get('claim', '')[:60]}: {issue.get('verdict')}\n"
        
        full_content = corrected_content + verify_header
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(full_content)
        
        log(f"[OK] 知识文件已修正并重写: {file_path}", "SUCCESS")
        return True
    except Exception as e:
        log(f"备份/重写知识文件失败: {e}", "ERROR")
        return False


# ==============================================================================
# 🔑 BiliClient 类
# ==============================================================================
# [bili/client.py] BiliClient
# [bili/auth.py] login_bilibili
