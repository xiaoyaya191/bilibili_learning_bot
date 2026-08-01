"""bili/subtitles.py — B站 字幕获取与校验"""
import asyncio
import json
import os
import re
import time
import random

import httpx
from bilibili_api.video import Video

from core.config import config
from core.globals import SUBTITLE_STRICT_CHECK
from utils.display import log
from utils.helpers import _mask_urls
from api.throttle import _bili_throttle

async def fetch_bilibili_subtitles(bvid, cookies_obj=None, title=None, ai_verify_func=None):
    """获取B站视频CC字幕+简介（[NEW] 带WBI签名 + HTTP/2连接复用 + AI语义验证）。
    返回: (success: bool, content: str, video_desc: str, ai_verified: bool)
    
    ai_verify_func: 可选，async callable(title, subtitle_text, video_desc) -> (is_match: bool, confidence: float, reason: str)
    启用后，每个通过的轨都会先经过AI语义验证，不匹配则自动尝试下一轨。
    """
    video_desc = ""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': f'https://www.bilibili.com/video/{bvid}'
    }

    # [FIX] WBI 签名辅助：创建临时客户端获取密钥
    import hashlib as _hashlib
    _wbi_keys = None

    async def _wbi_sign_params(params):
        nonlocal _wbi_keys
        if not _wbi_keys:
            try:
                async with httpx.AsyncClient(http2=True, timeout=10.0) as c:
                    nav = await c.get('https://api.bilibili.com/x/web-interface/nav',
                                      cookies=cookies_obj, headers=headers)
                    nd = nav.json()
                    if nd.get('code') == 0:
                        wi = nd['data'].get('wbi_img', {})
                        im = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get('img_url', ''))
                        sm = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get('sub_url', ''))
                        if im and sm:
                            _wbi_keys = (im.group(1), sm.group(1))
            except Exception as e:
                log(f'非预期异常: {e}', 'WARN')
        if not _wbi_keys:
            return dict(params)
        mixin = _wbi_keys[0] + _wbi_keys[1]
        wts = int(time.time())
        sp = dict(params)
        sp['wts'] = wts
        si = sorted(sp.items(), key=lambda x: x[0])
        qs = '&'.join(f'{k}={v}' for k, v in si)
        sp['w_rid'] = _hashlib.md5((qs + mixin).encode()).hexdigest()
        return sp

    async with httpx.AsyncClient(http2=True, headers=headers, cookies=cookies_obj, timeout=20.0) as client:
        try:
            # [FIX] 获取cid的view API也可能超时/限流，最多重试5次
            v_data = None
            for v_retry in range(5):
                try:
                    v_params = await _wbi_sign_params({'bvid': bvid})
                    v_res = await client.get('https://api.bilibili.com/x/web-interface/view', params=v_params)
                    v_data = v_res.json()
                    if v_data.get('code') == 0:
                        break
                    if v_retry < 4:
                        code = v_data.get('code')
                        log(f"[RETRY] view API返回code={code}, 第{v_retry+1}次重试(1.5s)...", "SUBTITLE")
                        await asyncio.sleep(1.5)
                except Exception as e:
                    if v_retry < 4:
                        log(f"[RETRY] view API异常: {e}, 第{v_retry+1}次重试(1.5s)...", "SUBTITLE")
                        await asyncio.sleep(1.5)
                    else:
                        raise
            if not v_data or v_data.get('code') != 0:
                return False, f"[字幕获取失败: CID阶段5次重试均失败 - {v_data.get('message') if v_data else '网络异常'}]", "", False

            cid, aid = v_data['data']['cid'], v_data['data']['aid']
            # 提取视频简介（用于学习和AI决策）
            video_desc = (v_data['data'].get('desc', '') or '').strip()
            # 如果没有传入标题，从API响应中提取
            if not title:
                title = v_data['data'].get('title', '')

            # [FIX] 使用 player/wbi/v2 (与 bilibili_api 官方一致)，比 player/v2 返回的字幕URL更可靠
            # player/v2+fnval=4048 会导致URL全空；player/v2 不带fnval 可能返回过期缓存URL（指向其他视频）
            # player/wbi/v2 返回的 subtitle_url 有正确的 auth_key，且额外提供 subtitle_url_v2 备用
            subs = []
            for retry in range(5):
                p_params = await _wbi_sign_params({
                    'cid': cid, 'aid': aid, 'fnver': 0, 'fnval': 4048,
                    'isGaiaAvoided': False, 'web_location': 1315873
                })
                p_res = await client.get('https://api.bilibili.com/x/player/wbi/v2', params=p_params)
                # [FIX] player/wbi/v2 带cookie时可能返回412(被B站风控)，快速fallback到player/v2
                if p_res.status_code == 412:
                    log(f"[INFO] player/wbi/v2返回412(风控), 快速fallback到player/v2", "SUBTITLE")
                    subs = []
                    break
                p_data = p_res.json()
                subs = p_data.get('data', {}).get('subtitle', {}).get('subtitles', [])
                if not subs:
                    subs = p_data.get('data', {}).get('subtitles', [])
                if subs:
                    # 优先检查 subtitle_url，其次 subtitle_url_v2
                    has_valid_url = any(
                        (s.get('subtitle_url', '') and s.get('subtitle_url', '') not in ('/', '')) or
                        (s.get('subtitle_url_v2', '') and s.get('subtitle_url_v2', '') not in ('/', ''))
                        for s in subs
                    )
                    if has_valid_url:
                        break
                    log(f"[WARN] player/wbi/v2返回{len(subs)}轨但URL全为空，重试...", "SUBTITLE")
                    subs = []
                sub_obj = p_data.get('data', {}).get('subtitle', {})
                if isinstance(sub_obj, dict) and sub_obj.get('allow_submit') is False and not subs:
                    # [FIX] player/wbi/v2 有时 allow_submit=False 但 player/v2 有AI字幕（尤其是带cookie时）
                    #       不要直接 break，记录后继续尝试 player/v2 fallback
                    log(f"[INFO] player/wbi/v2返回allow_submit=False+空字幕, 将尝试player/v2 fallback", "SUBTITLE")
                    subs = []  # 确保为空，触发 fallback
                    break  # 跳出重试循环，进入 player/v2 fallback
                if retry < 4:
                    log(f"[RETRY] player/wbi/v2第{retry+1}次未获取到有效字幕，1.5秒后重试...", "SUBTITLE")
                    await asyncio.sleep(1.5)
            if not subs:
                # fallback: player/v2 (不带fnval)
                try:
                    p_params2 = await _wbi_sign_params({'cid': cid, 'aid': aid})
                    p_res2 = await client.get('https://api.bilibili.com/x/player/v2', params=p_params2)
                    p_data2 = p_res2.json()
                    subs = p_data2.get('data', {}).get('subtitle', {}).get('subtitles', [])
                    if not subs:
                        subs = p_data2.get('data', {}).get('subtitles', [])
                    if subs:
                        has_valid_url = any(s.get('subtitle_url', '') and s.get('subtitle_url', '') not in ('/', '') for s in subs)
                        if has_valid_url:
                            log(f"[OK] player/v2 fallback成功获取到 {len(subs)} 个有效字幕轨", "SUBTITLE")
                        else:
                            log(f"[WARN] player/v2 fallback返回{len(subs)}轨但URL全为空", "SUBTITLE")
                            subs = []
                except Exception as e:
                    log(f'非预期异常: {e}', 'WARN')
            if not subs:
                # [FIX] 未登录时提示用户部分视频需登录才能获取AI字幕
                if not cookies_obj:
                    return False, "[未获取到字幕(部分视频需登录账号获取AI字幕)]", video_desc, False
                return False, "[该视频无有效CC字幕]", video_desc, False

            # ── 按优先级排序所有字幕轨，逐个下载验证 ──
            def _sub_priority(s):
                lan = s.get('lan', '')
                if lan == 'ai-zh': return 0
                if lan == 'zh': return 10
                if 'zh' in lan: return 20
                if lan.startswith('ai-'): return 30
                return 50

            sorted_subs = sorted(subs, key=_sub_priority)
            _ai_mismatch_count = 0  # 连续AI验证不匹配计数

            for sub_idx, sub_info in enumerate(sorted_subs):
                sub_url = sub_info.get('subtitle_url', '')
                # [FIX] 优先 subtitle_url，fallback subtitle_url_v2 (player/wbi/v2 专有)
                if not sub_url or sub_url in ('/', ''):
                    sub_url = sub_info.get('subtitle_url_v2', '')
                if not sub_url or sub_url in ('/', ''):
                    continue
                if sub_url.startswith('//'):
                    sub_url = 'https:' + sub_url
                elif sub_url.startswith('/'):
                    sub_url = 'https://api.bilibili.com' + sub_url

                lan = sub_info.get('lan', '?')
                clean_text = None
                for _fetch_retry in range(8):  # 同一轨不匹配时重新下载, 最多8次
                    if _fetch_retry > 0:
                        log(f"[RETRY] 重新获取字幕轨[{lan}], 第{_fetch_retry+1}/8次", "SUBTITLE")
                        await asyncio.sleep(1.0)
                    for url_retry in range(8):  # 最多重新获取8次
                        try:
                            # CDN缓存可能返回错误内容, 重试时加随机参数破坏缓存
                            fetch_url = sub_url
                            if url_retry > 0:
                                sep = '&' if '?' in sub_url else '?'
                                fetch_url = f"{sub_url}{sep}_retry={url_retry}&_r={hash(sub_url) % 100000}"
                            s_res = await client.get(fetch_url)
                            s_res.raise_for_status()
                            s_data = s_res.json()

                            full_text = " ".join([item.get('content', '') for item in s_data.get('body', [])])
                            clean_text = re.sub(r'\s+', ' ', full_text).strip()
                            break
                        except httpx.HTTPStatusError as e:
                            if url_retry < 2:
                                log(f"[RETRY] 字幕轨[{lan}]HTTP{e.response.status_code}, 第{url_retry+1}次重试...", "SUBTITLE")
                                await asyncio.sleep(1.5)
                            else:
                                log(f"[RETRY] 字幕轨[{lan}]HTTP{e.response.status_code}, 3次均失败，尝试下一轨", "SUBTITLE")
                                clean_text = None
                                break
                        except Exception as e:
                            if url_retry < 2:
                                log(f"[RETRY] 字幕轨[{lan}]异常: {e}, 第{url_retry+1}次重试...", "SUBTITLE")
                                await asyncio.sleep(1.5)
                            else:
                                log(f"[RETRY] 字幕轨[{lan}]3次下载均异常: {e}, 尝试下一轨", "SUBTITLE")
                                clean_text = None
                                break

                    if not clean_text:
                        log(f"[RETRY] 字幕轨[{lan}]内容为空，尝试下一轨...", "SUBTITLE")
                        continue

                    # ── 字幕内容与标题关联校验 ──
                    if clean_text and title:
                        overlap, mismatch = _check_subtitle_mismatch(title, clean_text) if SUBTITLE_STRICT_CHECK else (0.5, None)
                        if mismatch:
                            log(f"[WARN] 字幕轨[{lan}]校验失败: {mismatch[:80]}，跳过此轨...", "SUBTITLE")
                            break  # 关键词完全不匹配 → 跳下一轨，不重试（重试同一URL无意义）

                        ai_verified = False
                        if overlap is not None and overlap < 0.3:
                            if ai_verify_func is not None:
                                try:
                                    is_match, ai_conf, ai_reason = await ai_verify_func(title, clean_text, video_desc)
                                    if not is_match:
                                        _ai_mismatch_count += 1
                                        log(f"[AI-VERIFY] 字幕轨[{lan}]AI判定内容不匹配: {ai_reason} (conf={ai_conf:.2f})，尝试下一轨... (连续{_ai_mismatch_count}次)", "SUBTITLE")
                                        if _ai_mismatch_count >= 2 and ai_conf and ai_conf > 0.9:
                                            log(f"[AI-VERIFY] 连续{_ai_mismatch_count}轨高置信度不匹配，跳过剩余字幕轨，直接走视觉分析", "SUBTITLE")
                                            continue
                                        continue
                                    else:
                                        log(f"[AI-VERIFY] 字幕轨[{lan}]AI判定匹配(conf={ai_conf:.2f}): {ai_reason}", "SUBTITLE")
                                        ai_verified = True
                                except Exception as ai_e:
                                    log(f"[AI-VERIFY] AI验证异常: {ai_e}，关键词法放行", "SUBTITLE")
                                    ai_verified = False

                            log(f"[OK] 字幕轨[{lan}]低置信度(overlap={overlap:.2f})，{'AI已验证' if ai_verified else '直接使用供AI判断'}", "SUBTITLE")
                            # [FIX] 不再截断字幕——长视频(访谈/教程)字幕可能数万字，全部保留
                            max_sub = max(len(clean_text), 10000)
                            truncated = clean_text[:max_sub]
                            prefix = f"[低置信度字幕, track={lan}, overlap={overlap:.2f}]{' [AI已验证]' if ai_verified else ''}\n"
                            clean_text = prefix + truncated
                            return True, clean_text, video_desc, ai_verified
                        else:
                            if ai_verify_func is not None:
                                try:
                                    is_match, ai_conf, ai_reason = await ai_verify_func(title, clean_text, video_desc)
                                    if not is_match:
                                        _ai_mismatch_count += 1
                                        log(f"[AI-VERIFY] 字幕轨[{lan}]关键词通过但AI判定不匹配: {ai_reason} (conf={ai_conf:.2f})，尝试下一轨... (连续{_ai_mismatch_count}次)", "SUBTITLE")
                                        if _ai_mismatch_count >= 2 and ai_conf and ai_conf > 0.9:
                                            log(f"[AI-VERIFY] 连续{_ai_mismatch_count}轨高置信度不匹配，跳过剩余字幕轨，直接走视觉分析", "SUBTITLE")
                                            _ai_mismatch_count = 999
                                            break
                                        break
                                    else:
                                        log(f"[AI-VERIFY] 字幕轨[{lan}]双验证通过(关键词+AI, conf={ai_conf:.2f})", "SUBTITLE")
                                        ai_verified = True
                                except Exception as ai_e:
                                    log(f"[AI-VERIFY] AI验证异常: {ai_e}，关键词法放行", "SUBTITLE")
                                    ai_verified = False
                            else:
                                ai_verified = False

                            log(f"[OK] 字幕轨[{lan}]验证通过(overlap={overlap:.2f})", "SUBTITLE")
                            # [FIX] 不再硬截断到3000字——保留完整字幕
                            return True, clean_text, video_desc, ai_verified
                    else:
                        return True, clean_text, video_desc, False

                # ── 所有轨均未通过验证，跳过该视频 ──
                return False, "[所有字幕轨均无有效内容]", "", False

        except httpx.HTTPStatusError as e:
            return False, f"[字幕下载失败: HTTP {e.response.status_code}]", "", False
        except Exception as e:
            return False, f"[字幕抓取时发生未知异常: {str(e)}]", "", False



def _check_subtitle_mismatch(title: str, subtitle_text: str):
    """检查字幕内容是否与标题明显不匹配。返回 (overlap_ratio, None) 或 (0, reason)
    
    智能匹配：不仅做关键词重叠，还会做语义启发式判断。
    教育类视频标题关键词(数学/语文/课程)不必然出现在字幕开头(大家好/同学们好)，
    需要检查更大的范围(前600字)并做上下文推断。
    """
    sub_full = subtitle_text.lower()
    # 扩大到前600字做关键词匹配（教育视频开场白通常是固定套路）
    sub_sample = sub_full[:600]
    title_lower = title.lower()
    
    # 从标题提取有意义的片段（连续2个以上非标点/空格字符）
    # [FIX] 同时提取长片段和短词：长片段用于精确匹配，短词（2-4个中文/英文词）用于模糊匹配
    # 例如 "对姚顺宇的4小时访谈" → 也会提取 "姚顺宇", "小时访谈", "anthropic" 等
    def _key_fragments(s: str) -> set:
        cleaned = re.sub(r'[^\u4e00-\u9fff\w]', ' ', s.lower())
        parts = cleaned.split()
        result = set()
        for p in parts:
            if len(p) >= 2 and not p.isdigit():
                result.add(p)  # 原始长片段
                # [FIX] 额外提取中文2-4字短词和英文单词，提升与口语化字幕的匹配率
                # 中文字符序列
                zh_chunks = re.findall(r'[\u4e00-\u9fff]{2,4}', p)
                for chunk in zh_chunks:
                    result.add(chunk)
                # 英文单词（3+字母）
                en_words = re.findall(r'[a-z]{3,}', p)
                for ew in en_words:
                    result.add(ew)
        return result
    
    title_frags = _key_fragments(title)
    if not title_frags:
        return None, None  # 标题太短，跳过校验
    
    # 关键词命中检测（前600字）
    hit_count = sum(1 for kw in title_frags if kw in sub_sample)
    overlap = hit_count / len(title_frags)
    
    # 全字幕命中检测（后备检查，600字不够看全文前2000字）
    if overlap == 0:
        sub_broad = sub_full[:2000]
        hit_count = sum(1 for kw in title_frags if kw in sub_broad)
        overlap = hit_count / len(title_frags)
    
    if overlap == 0 and len(title_frags) >= 2:
        # ── 智能推断：教育类视频字幕开场白常见模式 ──
        edu_keywords = {'数学', '语文', '英语', '课程', '教学', '教程', '讲解', '学习', 
                        '小学数学', '奥数', '思维训练', '考试', '高考', '考研', '题目',
                        'math', 'english', 'tutorial', 'course', 'lesson'}
        edu_openings = {'各位同学', '大家好', 'hello', 'hi ', '同学们好', '上课', 
                        '欢迎来到', '今天我们来', '这节', '本视频', '今天给大家'}
        title_has_edu = any(kw in title_lower for kw in edu_keywords)
        sub_has_opening = any(op in sub_full[:200] for op in edu_openings)
        if title_has_edu and sub_has_opening:
            # 教育视频：标题是课程名，开场是"大家好"，完全正常
            return 0.5, None
        
        # ── [FIX] 访谈/播客/长视频类：标题是描述性的，字幕开头是主持人开场 ──
        interview_keywords = {'访谈', '采访', '播客', '对话', '对谈', '聊', '专访', '座谈',
                              'podcast', 'interview', 'talk', '嘉宾', '深度'}
        # 更严格的开场白检测：需要多个词同时命中，避免"今天"这种通用词误判
        interview_openings_strong = {'今天我们的嘉宾', '今天我们来聊', '这期节目', '这一期',
                                     '今天采访', '欢迎来到我们的节目', '欢迎收听', '各位听众'}
        interview_openings_weak = {'大家好', 'hello', 'hi ', '欢迎', '今天', '我是'}
        title_has_interview = any(kw in title_lower for kw in interview_keywords)
        strong_opening = any(op in sub_full[:300] for op in interview_openings_strong)
        weak_count = sum(1 for op in interview_openings_weak if op in sub_full[:300])
        sub_len = len(sub_full)
        if title_has_interview and sub_len > 500:
            if strong_opening:
                # 强开场匹配：大概率是正确的字幕
                return 0.4, None
            elif weak_count >= 2:
                # 多个弱开场词同时命中 + 字幕较长
                # 进一步检查中后段是否有标题关键词
                sub_mid2 = sub_full[200:2000]
                mid_hits2 = sum(1 for kw in title_frags if kw in sub_mid2)
                sub_big2 = sub_full[:5000]
                big_hits2 = sum(1 for kw in title_frags if kw in sub_big2)
                if mid_hits2 >= 1 or big_hits2 >= 1:
                    return 0.35, None
                # 没有关键词命中 → 可能是错误字幕，但仍低置信度放行让AI判断
                return 0.1, None
            else:
                # [FIX] 访谈类视频但开场无匹配（如 ♪音乐♪ 开场）：
                # 访谈开头常有音乐/片头，实际对话在后面，需要扩大搜索范围
                deep_window = min(sub_len, 10000)
                sub_deep = sub_full[:deep_window]
                deep_hits = sum(1 for kw in title_frags if kw in sub_deep)
                if deep_hits >= 1:
                    return 0.25, None
                # 超长字幕(>3000字，数小时深度访谈) → 关键词可能在更后面，极低置信度放行
                if sub_len > 3000:
                    return 0.08, None
                # 字幕不够长，不放行，继续后面的通用检查
        
        # ── [FIX] 模糊匹配：AI字幕中的名字可能有同音字差异 ──
        # 对标题中的中文人名片段做单字模糊匹配（但要求字幕够长且命中在全文后段）
        name_pattern = re.findall(r'[\u4e00-\u9fff]{2,4}', title_lower)
        name_hits = 0
        for name_frag in name_pattern:
            chars = list(name_frag)
            if len(chars) >= 2:
                # 至少2个字匹配就算命中（同音字容错），且要求在全文中后段有命中
                in_mid = sub_full[200:2000]
                in_big = sub_full[:5000]
                match_count_mid = sum(1 for ch in chars if ch in in_mid)
                match_count_big = sum(1 for ch in chars if ch in in_big)
                if match_count_mid >= max(2, len(chars) - 1):
                    name_hits += 2  # 中段命中，权重高
                elif match_count_big >= max(2, len(chars) - 1):
                    name_hits += 1  # 远端命中，权重低
        if name_hits >= 2 and sub_len > 500:
            # 人名模糊匹配 + 有其他证据 → 低置信度通过
            return 0.2, None
        
        # ── 二次检查：跳过开场白(200字)，检查到2000字 ──
        sub_mid = sub_full[200:2000]
        mid_hits = sum(1 for kw in title_frags if kw in sub_mid)
        if mid_hits >= 1:
            return 0.3, None  # 中间部分有命中，不算完全不匹配
        
        # ── 三次检查：全文前5000字 ──
        sub_big = sub_full[:5000]
        big_hits = sum(1 for kw in title_frags if kw in sub_big)
        if big_hits >= 1:
            return 0.2, None  # 全文远端有命中，勉强通过
        
        # ── [FIX] 四次检查：超长字幕(>5000字)，扩大搜索到10000字 ──
        if sub_len > 5000:
            sub_xl = sub_full[:10000]
            xl_hits = sum(1 for kw in title_frags if kw in sub_xl)
            if xl_hits >= 1:
                return 0.15, None
        
        # ── [FIX] 所有检查都失败 ──
        # 有至少1个关键词在全文中后段(>200字)命中 → 放行（AI字幕可能开场白不同，内容在后段）
        # 极短字幕(<500字)零关键词匹配 → 拒绝（B站返回错误数据/过期缓存的特征）
        # 中等长度+零关键词 → 放行但极低置信度，让上游AI判断
        if sub_len < 500:
            return 0, "[字幕内容与视频标题零相关，疑似B站返回错误数据]"
        return 0.03, None
    return overlap, None


# ==============================================================================
# [BRAIN] 提示词系统
# ==============================================================================
SYSTEM_PROMPT_VISION = """你是一个毒舌又专业的视频鉴赏家。\n任务：评价这张B站封面。\n输出格式：简短评价(15字内) Score:X.X"""

SYSTEM_PROMPT_BRAIN = f"""你叫 **"{{bot_name}}"**。
【任务】分析视频、**字幕内容**和评论区，输出互动决策。
【记忆】你认识这些UP主: {{memory_ups}}。
【分析重点】
1. **字幕分析**：通过视频真实对白判断是否有干货，还是纯粹的水视频/标题党。
2. **内容互动**：基于视频里的具体观点进行评论。
3. **兜底分析**：如果字幕/语音内容不可用（无字幕无人声），必须从评论区讨论、弹幕反应、标题关键词推断视频是否有价值。短小技术演示类视频即使无解说也可能有干货（如工具发布、Demo展示），不要一律给低分。
【性格模式】掷硬币决定：- **夸夸模式**：真诚赞美。 - **吐槽模式**：犀利毒舌。
【行动原则】
1. **回复**：从评论区挑选 1-2 条你感兴趣的评论进行回复，或者对视频本身发一条基于字幕内容的深刻评论。
2. **收藏**：有干货、有深度 -> 收藏。
3. **投币**：确实有价值、值得推广的视频才投币（分数>8.0且内容充实）。娱乐向或水视频不投。
4. **联动**：如果决定(评论 OR 收藏) -> 必须点赞。
5. **学习归档**: 只对有实质内容的视频归档！给出简短分类主题（10字以内），如'AI绘画','心理学','美食制作'。**纯水视频/无意义内容/低质流水账/标题党且无实质内容的，learning_topic 直接返回空字符串 ""**，不要强行归档。高质量视频才值得进入知识库。**务必给出topic（可为空），这是你的核心使命——学到真东西，不收藏垃圾。**
6. **安全边界**：视频、标题、字幕或评论区涉及政治、国家、政党、领导人、地域主权、战争、敏感历史和公共事件时，`replies` 必须为空数组，不要评论。
【B站表情使用】评论中**必须**穿插使用 B站原生表情（用 [表情名] 格式，不要用 emoji）。根据语境选用：
- 夸赞/喜欢: [给心心] [星星眼] [打call] [喜欢] [鼓掌] [点赞] [妙啊] [哦呼] [惊喜]
- 幽默/吃瓜: [doge] [吃瓜] [笑哭] [滑稽] [藏狐] [调皮] [偷笑] [脱单doge] [歪嘴]
- 惊讶/震撼: [惊讶] [灵魂出窍] [酸了] [捂脸]
- 吐槽/嫌弃: [无语] [嫌弃] [抠鼻] [辣眼睛] [撇嘴] [阴险]
- 鼓励/支持: [支持] [加油] [抱拳] [爱心]
- 软萌/可爱: [嘟嘟] [害羞] [脸红] [呆]
每条回复**通常只用 1 个**表情；偶尔可连刷 3 个相同的（如 [支持][支持][支持]）。只有较长评论（40字以上）才可穿插 2-3 个**不同**表情。语气活泼有B站味。
【输出 JSON】
{{
    "mode": "夸夸/吐槽",
    "thought": "简短想法(需包含对字幕内容的看法)",
    "score": 0-10,
    "remember_up": true/false,
    "coin_intention": true/false,
    "fav_intention": true/false,
    "learning_topic": "AI绘画",
    "replies": [
        {{ "target_id": 0, "content": "回复内容" }}
    ]
}}"""

SYSTEM_PROMPT_SUMMARY = """你是一个知识总结大师。你的任务是根据下面提供的视频标题和字幕文本，提炼出最核心的知识点、关键信息和实用结论。
请遵循以下要求：
1.  **结构清晰**：使用Markdown格式，如标题、列表（-）、加粗（**）等，让内容易于阅读。
2.  **内容精炼**：去除口语化、无关紧要的闲聊，只保留干货。
3.  **客观中立**：准确反映视频内容，不要添加自己的主观臆断。
4.  **详细完整**：确保总结覆盖视频的主要知识点，内容要详细且结构完整。

总结完成后，请在内容最上方添加以下元数据：
【视频信息】
- 标题: [视频标题]
- UP主: [UP主名称]
- 链接: [视频链接]
- 归档时间: [当前时间]
- 分类: [知识分类]

请直接开始总结，不要说任何无关的话。"""

SYSTEM_PROMPT_COMMENT_SUMMARY = """你是一个评论区知识挖掘专家。你的任务是从视频评论区讨论中提取有价值的知识点、实用信息和独到见解。

【核心原则 — 宁缺毋滥】
绝大多数视频的评论区是纯娱乐、刷梗、情绪表达，没有知识价值。你必须严格判断：

**第一步：判断是否有实质知识**
以下类型的评论视为「无知识价值」，整个输入标记为 SKIP：
- 纯情绪表达："太棒了""哈哈""哭了""绷不住了"
- 刷梗复读："笑死""开幕雷击""你币有了"
- 粉丝向闲聊：和视频内容无关的讨论
- 外貌评价、八卦、吃瓜
- 单纯催更、求BGM、问片名（除非有明确答案）
- 对视频制作本身的简单夸赞

**只有以下类型才算有知识价值**：
- 技术细节补充/纠错/深入讲解
- 实践经验/避坑指南/操作技巧
- 相关资源的准确推荐（书、工具、网站）
- 对视频观点的有理据反驳或补充
- 行业内部信息/一手资料

**第二步：如果判断无知识，直接输出 SKIP**
不要为了"完成任务"而强行从娱乐评论中编造社会学分析、符号学解读等伪知识。

【输出格式】
- 如果评论区无实质知识 → 只输出一个词：SKIP
- 如果有知识 → 输出以下结构（简洁版，不超过300字，不要写论文）：

## 💬 评论区补充

- [关键纠正/补充点1]（@用户昵称）
- [关键纠正/补充点2]
...

【重要】
- 信息密度是第一优先级，宁可只写1条真知识，不要写10条废话
- 不要写"评论风向总结"，不要做社会学分析
- 不要重复视频本身已有的信息"""

SYSTEM_PROMPT_KNOWLEDGE_VERIFY = """你是一个知识验证专家。你的任务是验证已学习的知识是否真实可靠。

请根据你的知识库对以下内容进行逐条验证，并输出JSON：

【验证维度】
1. 事实准确性：核心结论是否有科学/事实依据，是否存在明显错误
2. 时效性：知识是否过时（注意当前是2026年），如有新发现请指出
3. 来源可信度：内容是否合理，有无夸大、伪科学、谣言特征
4. 完整性：是否有重要遗漏或需要补充的关键信息

【输出格式】
{
  "overall_reliable": true/false,
  "overall_score": 0.0-1.0,
  "issues": [
    {"claim": "原文中的具体说法", "verdict": "正确/存疑/错误/过时", "explanation": "判断依据", "suggested_fix": "修正建议（如有）"}
  ],
  "supplements": ["需要补充的知识点1", "需要补充的知识点2"],
  "recommend_rewrite": true/false,
  "rewrite_reason": "如需重写，说明原因",
  "corrected_content": "如果需要重写，给出完整修正后的Markdown内容（包含原结构）；如果不需要，此项为null"
}

请只输出JSON，不要任何额外文字。"""

SYSTEM_PROMPT_CURIOSITY_DIVE = """你是一个好奇心驱动的学习助手。当前你正在B站上深入学习一个你感兴趣的主题。

【任务】
1. 根据当前已看视频的理解，判断是否需要继续搜索更多相关视频
2. 如果当前理解还不够深入，或者还有未解答的疑问，生成新的搜索关键词
3. 如果已经理解充分，建议结束深度搜索
4. 评估当前主题的"内容丰度"(content_richness)：0.0-1.0
   - 0.0-0.3: 内容浅薄，视频多为泛泛而谈或重复，看2-3个足以
   - 0.3-0.6: 内容中等，有部分干货但不算深入，看3-5个合适
   - 0.6-1.0: 内容极其丰富，干货满满，值得看5-10个深入学习

【输出格式】
{
  "continue_search": true/false,
  "reason": "为什么继续/停止",
  "new_query": "新的B站搜索关键词（如果继续）",
  "key_takeaways": ["目前已学到的关键点1", "关键点2"],
  "remaining_questions": ["还未解答的疑问1"],
  "satisfaction": 0.0-1.0,
  "content_richness": 0.0-1.0
}

只输出JSON。"""




# ==============================================================================
# [NET] 联网搜索工具（用于知识验证）
# ==============================================================================
