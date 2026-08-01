"""
BrainInteractMixin — 视觉分析与互动
包含: analyze_vision, judge_interest_with_ai, _get_comments_context,
      _analyze_comment_images
"""
import re
import json
import asyncio

from brain._mixin_imports import *
from utils.helpers import _mask_urls


class BrainInteractMixin:
    """视觉分析与互动方法"""

    async def analyze_vision(self, pic_url):
        if not pic_url: return "无封面", 0
        if not VISION_COVER_ENABLED: return "封面分析已关闭", 0
        if self._is_ai_degraded(): return "AI降级,跳过", 0
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_VISION,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_VISION},
                    {"role": "user", "content": [
                        {"type": "text", "text": "评价"},
                        {"type": "image_url", "image_url": {"url": pic_url}}
                    ]}
                ],
                request_timeout=90
            )
            content = resp.choices[0].message.content
            score = 5.0
            if "Score:" in content:
                try:
                    parts = content.split("Score:")
                    desc = parts[0].strip()[:15]
                    score = float(parts[1].strip())
                except (ValueError, IndexError):
                    desc = content[:15]
            else:
                desc = content[:15]
            return desc, score
        except Exception as e:
            log(f"封面分析失败(已重试): {_mask_urls(str(e)[:80])}", "WARN")
            return "分析失败", 0

    async def judge_interest_with_ai(self, title, up, vis_desc, vis_score,
                                      tags: str = "", category: str = "",
                                      desc: str = ""):
        """
        v2.0: 使用智能兴趣引擎 (interest_engine.py)
        管道: 排除词 → 灵光一闪 → 关键词+同义词 → 多维度评分 → AI兜底
        """
        from services.interest_engine import get_engine, MatchResult

        engine = get_engine()

        # 空兴趣 → 全量通过
        if engine.get_interest_count() == 0:
            return True, [], "未设置兴趣，默认通过"

        # 核心匹配管道
        result = engine.match(
            title=title, tags=tags, desc=desc, up_name=up,
            category=category, vis_desc=vis_desc, vis_score=vis_score
        )

        # 结果明确 → 直接返回
        if result.passed is True:
            return True, result.matched_keywords, result.match_reason
        if result.passed is False:
            return False, [], result.match_reason

        # passed=None → 需要AI进一步判断
        interests = engine.get_keywords()
        prompt = f"""
请判断这个B站视频是否符合用户兴趣。

用户兴趣: {", ".join(interests[:20])}
视频标题: {title}
UP主: {up}
封面印象: {vis_desc}
封面印象分: {vis_score}
引擎预评分: {result.total_score:.1f}/10 ({result.match_reason})

要求:
1. 综合标题、UP主、封面印象判断，不要只做关键词匹配。
2. 只输出JSON，格式为:
{{"interested": true, "matched": ["兴趣1"], "reason": "一句话理由"}}
3. 如果明显不相关，interested=false，matched=[]。
"""
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": "你是B站视频兴趣筛选器，只输出合法JSON。"},
                    {"role": "user", "content": prompt}
                ],
                request_timeout=90
            )
            raw = resp.choices[0].message.content.strip()
            start = raw.find("{")
            json_str = raw
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
                    json_str = raw[start:match_end + 1]
                else:
                    end = raw.rfind("}")
                    if end >= start:
                        json_str = raw[start:end + 1]
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                fixed = json_str.replace("'", '"')
                fixed = re.sub(r'\bTrue\b', 'true', fixed)
                fixed = re.sub(r'\bFalse\b', 'false', fixed)
                fixed = re.sub(r'\bNone\b', 'null', fixed)
                data = json.loads(fixed)
            ai_matched = data.get("matched") or []
            if isinstance(ai_matched, str):
                ai_matched = [ai_matched]
            reason = str(data.get("reason") or "AI综合判断")
            # 合并引擎匹配的关键词
            all_matched = list(dict.fromkeys(result.matched_keywords + ai_matched))
            return bool(data.get("interested")), all_matched, reason
        except Exception as e:
            log(f"AI兴趣判断失败(已重试)，退回关键词判断: {str(e)[:80]}", "WARN")
            return len(result.matched_keywords) > 0, result.matched_keywords, "关键词未匹配"

    async def _get_comments_context(self, aid: int):
        c_list_raw = await self.bili.get_hot_comments(aid, limit=8)
        if not c_list_raw: return "暂无评论", []

        # [SPEED] 两阶段并行：先收集所有评论基本信息，再并行分析图片
        comment_entries = []
        image_tasks = []
        for i, c in enumerate(c_list_raw):
            try:
                cid, user, msg = c['rpid'], c['member']['uname'], c['content']['message']
                entry = {"cid": cid, "user": user, "content": msg, "pic_info": ""}
                if VISION_COMMENT_IMAGES_ENABLED:
                    pictures = c.get('content', {}).get('pictures', [])
                    if pictures:
                        img_urls = [p.get('img_src', '') for p in pictures[:3] if p.get('img_src')]
                        if img_urls:
                            image_tasks.append(self._analyze_comment_images(cid, img_urls, user_msg=msg))
                            entry["_img_idx"] = len(image_tasks) - 1
                comment_entries.append(entry)
            except (KeyError, TypeError):
                continue

        # 并行分析所有评论图片
        pic_results = await asyncio.gather(*image_tasks, return_exceptions=True) if image_tasks else []

        # 组装结果
        context_str = "【热门评论】:\n"
        c_list_clean = []
        for entry in comment_entries:
            cid, user, msg = entry["cid"], entry["user"], entry["content"]
            pic_info = ""
            if "_img_idx" in entry:
                result = pic_results[entry["_img_idx"]]
                if isinstance(result, str) and result:
                    pic_info = f" [附图描述: {result}]"
            context_str += f"ID:{cid} User:{user} Msg:{msg}{pic_info}\n"
            c_list_clean.append({"id": cid, "user": user, "content": msg, "pic_info": pic_info.strip()})
        return context_str, c_list_clean

    async def _analyze_comment_images(self, cid, img_urls, user_msg=""):
        """[VISION] 下载评论文图片并用视觉AI描述，同时展示评论文字+图片"""
        if not img_urls or self._is_ai_degraded():
            return ""
        max_images = min(len(img_urls), VISION_MAX_COMMENT_IMAGES)
        import httpx as _httpx, base64 as _b64

        async def _dl_and_analyze(idx, url):
            try:
                async with _httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    r = await client.get(url, headers={
                        'User-Agent': 'Mozilla/5.0',
                        'Referer': 'https://www.bilibili.com'
                    })
                    if r.status_code != 200:
                        return None
                    data_url = "data:image/jpeg;base64," + _b64.b64encode(r.content).decode("ascii")
                resp = await self._call_ai_with_retry(
                    model=MODEL_VISION,
                    messages=[{
                        "role": "system",
                        "content": "你是评论图片分析助手。用一句简短中文描述图片内容（是什么类型的图、主要内容、情绪倾向）。"
                    }, {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "描述这张评论区的图片"},
                            {"type": "image_url", "image_url": {"url": data_url}}
                        ]
                    }],
                    request_timeout=20
                )
                desc = resp.choices[0].message.content.strip()[:80]
                return f"[图{idx+1}]{desc}"
            except Exception as e:
                log(f"评论图片分析失败(cid={cid} img{idx}): {e}", "DEBUG")
                return None

        # [SPEED] 并行下载+分析所有图片
        tasks = [_dl_and_analyze(i, url) for i, url in enumerate(img_urls[:max_images])]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        analyzed = [r for r in results if isinstance(r, str)]
        if analyzed:
            msg_preview = user_msg[:40] + "..." if len(user_msg) > 40 else user_msg
            log(f"[EYE] 评论({msg_preview}) + 附图({len(analyzed)}张): {'; '.join(analyzed)}", "EYE")
        return "; ".join(analyzed)
