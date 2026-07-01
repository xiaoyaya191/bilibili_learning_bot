#!/usr/bin/env python3
"""brain/standby.py — 待机模式：评论区@触发总结 + 看视频触发开关 + AI回复评论

v2: 支持在任何视频下被@自动总结（通过 B站 @我通知 API + 评论自带上下文）
用户只需评论 "@bot 总结这个视频" 即可，无需手动提供 BV 号。
"""
import asyncio, json, os, sys, re, time, hashlib, traceback

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import httpx
from colorama import Fore, Style, init as colorama_init
colorama_init(autoreset=True)

DATA_DIR = os.path.join(BASE_DIR, "Data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
COOKIE_FILE = os.path.join(DATA_DIR, "bilibili_cookies.json")
STANDBY_CONFIG_FILE = os.path.join(DATA_DIR, "standby_config.json")
STANDBY_STATS_FILE = os.path.join(DATA_DIR, "standby_stats.json")

# ── 配置 ──
def load_standby_config() -> dict:
    """加载待机模式配置"""
    if os.path.exists(STANDBY_CONFIG_FILE):
        try:
            with open(STANDBY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            sc = cfg.get('standby', {})
            if sc:
                return sc
        except Exception:
            pass
    return {
        "enabled": True,
        "auto_reply": True,
        "at_trigger_enabled": True,
        "at_trigger_keywords": ["总结", "总结一下", "分析", "概括", "讲解", "归纳", "梳理"],
        "monitor_own_videos_only": False,
        "notification_mode": True,
        "comment_check_interval": 60,
        "max_replies_per_check": 5,
        "reply_cooldown_seconds": 120,
        "ppt_auto_generate": False,
        "ppt_theme": "claude",
        "video_trigger_enabled": True,
        "custom_prompt": "",
    }

def save_standby_config(cfg: dict) -> bool:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STANDBY_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def load_stats() -> dict:
    if os.path.exists(STANDBY_STATS_FILE):
        try:
            with open(STANDBY_STATS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"comments_processed": 0, "at_replies": 0, "ppt_generated": 0, "errors": 0, "last_reply_time": 0}

def save_stats(stats: dict):
    try:
        with open(STANDBY_STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ── StandbyBot ──
class StandbyBot:
    def __init__(self):
        self.config = load_standby_config()
        self.stats = load_stats()
        self.cookies = None
        self.api_key = ""
        self.base_url = ""
        self.model = "qwen/qwen3.5-122b-a10b"
        self.processed_comments = set()
        self.running = False
        self.my_mid = 0
        self._load_cookies()
        self._load_api_config()

    def _load_cookies(self):
        if os.path.exists(COOKIE_FILE):
            try:
                with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                    self.cookies = json.load(f)
            except Exception:
                self.cookies = None

    def _load_api_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                api = cfg.get('api', {})
                self.api_key = api.get('unified_api_key', '') or os.getenv('BILI_AI_API_KEY', '')
                self.base_url = api.get('unified_base_url', '') or os.getenv('BILI_AI_BASE_URL', '')
                self.model = api.get('model_brain', self.model)  # 使用 model_brain 而非 model_name
                self.my_mid = cfg.get('account', {}).get('uid', 0)
            except Exception:
                pass

    def _log(self, msg: str, level: str = "INFO"):
        color = {"INFO": Fore.WHITE, "OK": Fore.GREEN, "WARN": Fore.YELLOW, "ERR": Fore.RED,
                 "AT": Fore.MAGENTA, "NTF": Fore.CYAN}.get(level, Fore.WHITE)
        icon = {"INFO": "[SB]", "OK": "[OK]", "WARN": "[WARN]", "ERR": "[ERR]",
                "AT": "[AT]", "NTF": "[NTF]"}.get(level, "[SB]")
        text = f"{icon} {msg}"
        try:
            print(f"{color}{text}{Style.RESET_ALL}")
        except UnicodeEncodeError:
            print(text)

    # ── 通用B站API工具 ──
    async def _aid_to_bvid(self, client: httpx.AsyncClient, aid: int) -> str:
        """aid 转为 bvid"""
        if not aid:
            return ""
        try:
            r = await client.get(f'https://api.bilibili.com/x/web-interface/view', params={'aid': aid})
            d = r.json()
            if d.get('code') == 0:
                return d['data'].get('bvid', '')
        except Exception:
            pass
        return ""

    async def _bvid_to_oid(self, client: httpx.AsyncClient, bvid: str) -> str:
        """BV号转视频aid/oid"""
        try:
            r = await client.get(f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}')
            d = r.json()
            if d.get('code') == 0:
                return str(d['data']['aid'])
        except Exception:
            pass
        return bvid

    async def _post_comment(self, client: httpx.AsyncClient, bvid_or_aid: str, root_rpid: int,
                            parent_rpid: int, content: str) -> bool:
        """回复评论（自动兼容oid=aid和bvid）"""
        try:
            oid = bvid_or_aid
            if not oid.isdigit() or len(oid) > 10:
                oid = await self._bvid_to_oid(client, bvid_or_aid)
            payload = {
                'oid': int(oid), 'type': 1, 'root': root_rpid, 'parent': parent_rpid,
                'message': content, 'plat': 1
            }
            r = await client.post(
                'https://api.bilibili.com/x/v2/reply/add',
                data=payload
            )
            d = r.json()
            if d.get('code') == 0:
                return True
            self._log(f"回复评论失败 code={d.get('code')} msg={d.get('message','')}", "WARN")
        except Exception as e:
            self._log(f"回复评论异常: {e}", "ERR")
        return False

    # ── 核心：@我通知拉取（notification mode）──
    async def _get_at_notifications(self, client: httpx.AsyncClient, page: int = 1) -> list:
        """拉取 B站 @我通知，提取评论类型的@提及。
        返回: [{id, rpid, oid, bvid, aid, content, uname, mid, ctime}]"""
        items = []
        try:
            r = await client.get(
                'https://api.bilibili.com/x/msg/at',
                params={'pn': page, 'ps': 20}
            )
            d = r.json()
            if d.get('code') != 0:
                return items

            raw_items = d.get('data', {}).get('items', [])
            for it in raw_items:
                biz = it.get('business', '')
                if biz not in ('reply', '1', '2', '3', '4', '5', '6', '7'):
                    continue

                i = it.get('item', {})
                # 通知数据结构: subject_id = 视频aid, source_id = 评论源aid, business_id = 评论rpid
                aid = i.get('subject_id') or i.get('source_id', 0)
                rpid_str = str(i.get('business_id', ''))

                # content 是JSON字符串，包含评论消息
                raw_content = i.get('content', '')
                uname = i.get('reply_name', '') or i.get('user', {}).get('nickname', '')
                mid = i.get('reply_mid', 0) or i.get('user', {}).get('mid', 0)

                # 解析content
                comment_text = ""
                try:
                    cj = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
                    comment_text = cj.get('message', '') or cj.get('content', '') or raw_content
                except Exception:
                    comment_text = raw_content

                ctime_val = i.get('reply_time', 0) or it.get('at_time', 0)

                items.append({
                    'id': it.get('id', ''),
                    'rpid': rpid_str,
                    'aid': int(aid) if aid else 0,
                    'bvid': '',  # 后续解析
                    'content': comment_text,
                    'uname': uname if uname else '未知用户',
                    'mid': int(mid) if mid else 0,
                    'ctime': int(ctime_val) if ctime_val else 0,
                })
        except Exception as e:
            self._log(f"获取@我通知失败: {e}", "WARN")
        return items

    async def _get_my_videos(self, client: httpx.AsyncClient) -> list:
        """获取自己的视频列表（legacy模式用）"""
        if not self.cookies:
            return []
        try:
            r = await client.get('https://api.bilibili.com/x/space/arc/search?mid=0&ps=10&pn=1')
            d = r.json()
            if d.get('code') == 0:
                vlist = d.get('data', {}).get('list', {}).get('vlist', [])
                return [{"bvid": v['bvid'], "title": v['title']} for v in vlist[:10]]
        except Exception:
            pass
        return []

    async def _get_comments_for_video(self, client: httpx.AsyncClient, bvid: str, page: int = 1) -> list:
        """获取指定视频的评论（legacy模式用）"""
        comments = []
        try:
            r = await client.get(
                'https://api.bilibili.com/x/v2/reply/main',
                params={'oid': await self._bvid_to_oid(client, bvid), 'type': 1, 'ps': 20, 'pn': page}
            )
            d = r.json()
            if d.get('code') == 0:
                for rep in d.get('data', {}).get('replies', []):
                    comments.append({
                        'rpid': rep['rpid'],
                        'oid': rep['oid'],
                        'content': rep.get('content', {}).get('message', ''),
                        'mid': rep.get('member', {}).get('mid', ''),
                        'uname': rep.get('member', {}).get('uname', ''),
                        'ctime': rep.get('ctime', 0),
                    })
        except Exception as e:
            self._log(f"获取评论失败: {e}", "WARN")
        return comments

    # ── AI 调用 ──
    async def _ai_chat(self, prompt: str, system: str = None) -> str:
        if not self.api_key or not self.base_url:
            self._log("API未配置，无法调用AI", "ERR")
            return ""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            async with httpx.AsyncClient(timeout=120.0) as c:
                r = await c.post(
                    f"{self.base_url}/chat/completions",
                    headers={'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'},
                    json={'model': self.model, 'messages': messages, 'temperature': 0.7, 'max_tokens': 2048}
                )
                if r.status_code >= 400:
                    return ""
                d = r.json()
                choices = d.get('choices', [])
                if choices:
                    return choices[0].get('message', {}).get('content', '')
        except Exception as e:
            self._log(f"AI调用失败: {e}", "ERR")
        return ""

    # ── @触发检测(v2: 不再要求评论里提供BV号，自动用所在视频) ──
    def _check_at_trigger(self, comment_text: str) -> tuple:
        """
        检测评论是否@机器人并要求操作。
        返回 (是否触发, 'auto'或具体BV号, 触发的关键词)

        新版逻辑：只要有 @用户名 + 关键词，且评论自带视频上下文（由通知API提供），
        就自动总结评论所在的视频，无需评论里填写BV号。
        如果评论里有指定BV号则优先用指定的。
        """
        at_keywords = self.config.get('at_trigger_keywords',
                                      ["总结", "总结一下", "分析", "概括", "讲解", "归纳", "梳理"])

        has_at = bool(re.search(r'@[\w\u4e00-\u9fff]+', comment_text))
        if not has_at:
            return False, "", ""

        matched_kw = next((kw for kw in at_keywords if kw in comment_text), "")
        if not matched_kw:
            return False, "", ""

        # 检查评论中是否有明确指定的BV号或链接（可选，有则优先）
        bv_match = re.search(r'(BV[A-Za-z0-9]{10})', comment_text)
        if bv_match:
            return True, bv_match.group(1), matched_kw

        url_match = re.search(r'(https?://(?:www\.)?bilibili\.com/video/(BV[A-Za-z0-9]{10}))', comment_text)
        if url_match:
            return True, url_match.group(2), matched_kw

        # 没有指定BV号 → 返回 'auto'，用评论所在视频
        return True, "auto", matched_kw

    # ── 主循环（v2: 通知模式 + legacy模式双渠道）──
    async def run(self):
        self.running = True

        notification_mode = self.config.get('notification_mode', True)
        monitor_own = self.config.get('monitor_own_videos_only', False)
        interval = self.config.get('comment_check_interval', 60)

        if monitor_own or not notification_mode:
            self._log("待机模式: Legacy（轮询自己视频的评论）", "INFO")
        else:
            self._log("待机模式: 通知模式（B站@我通知）", "OK")
        self._log(f"  @触发: {'开启' if self.config.get('at_trigger_enabled') else '关闭'}", "INFO")
        self._log(f"  触发关键词: {self.config.get('at_trigger_keywords', [])}", "INFO")
        self._log(f"  轮询间隔: {interval}秒", "INFO")
        self._log(f"  自动获取所在视频BV: {'是 (无需手动提供)' if notification_mode else '需手动输入'}", "INFO")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.bilibili.com/'
        }
        cookies_obj = httpx.Cookies()
        if self.cookies:
            for k, v in self.cookies.items():
                cookies_obj.set(k, str(v))

        last_nav_check_time = 0

        while self.running:
            try:
                async with httpx.AsyncClient(http2=True, headers=headers,
                                             cookies=cookies_obj, timeout=30.0) as client:
                    # 定期刷新cookie有效性
                    now = time.time()
                    if now - last_nav_check_time > 300:
                        last_nav_check_time = now
                        try:
                            nav = await client.get('https://api.bilibili.com/x/web-interface/nav')
                            if nav.json().get('code') == -101:
                                self._log("Cookie已过期！请重新登录", "ERR")
                        except Exception:
                            pass

                    if notification_mode and not monitor_own:
                        # ──── 通知模式：拉取 @我 通知 ────
                        await self._process_notifications(client)
                    else:
                        # ──── Legacy模式：轮询自己的视频评论 ────
                        await self._process_own_videos(client)

            except Exception as e:
                self._log(f"主循环异常: {e}", "ERR")
                self.stats['errors'] += 1
                save_stats(self.stats)

            await asyncio.sleep(interval)

    async def _process_notifications(self, client: httpx.AsyncClient):
        """通知模式：处理 @我 通知"""
        notifications = await self._get_at_notifications(client, page=1)
        if not notifications:
            return

        handled = 0
        max_handles = self.config.get('max_replies_per_check', 5)
        cooldown = self.config.get('reply_cooldown_seconds', 120)
        now_ts = int(time.time())

        for ntf in notifications:
            if handled >= max_handles or not self.running:
                break

            # 去重
            dedup_key = str(ntf.get('rpid', '')) or ntf.get('id', '')
            if dedup_key and dedup_key in self.processed_comments:
                continue

            # 冷却
            last = self.stats.get('last_reply_time', 0)
            if now_ts - last < cooldown:
                await asyncio.sleep(1)

            is_at, bv_target, keyword = self._check_at_trigger(ntf.get('content', ''))
            if not (is_at and self.config.get('at_trigger_enabled')):
                if dedup_key:
                    self.processed_comments.add(dedup_key)
                continue

            self._log(f"[AT] {ntf['uname']} @请求: '{keyword}' (视频aid={ntf.get('aid',0)})", "AT")

            # 确定要总结的视频
            if bv_target == "auto" or not bv_target:
                # 自动模式：总结评论所在视频
                target_bv = ntf.get('bvid', '')
                if not target_bv and ntf.get('aid'):
                    target_bv = await self._aid_to_bvid(client, ntf['aid'])
                ntf['bvid'] = target_bv
            else:
                target_bv = bv_target

            if dedup_key:
                self.processed_comments.add(dedup_key)

            if not target_bv:
                self._log(f"[AT] 无法获取目标视频BV号，跳过", "WARN")
                continue

            await self._handle_at_trigger_v2(client, ntf, target_bv)
            handled += 1
            self.stats['last_reply_time'] = int(time.time())

        save_stats(self.stats)

    async def _process_own_videos(self, client: httpx.AsyncClient):
        """Legacy模式：轮询自己视频的评论"""
        videos = await self._get_my_videos(client)
        if not videos:
            self._log("未获取到自己的视频（可能需要登录）", "WARN")
            return

        self._log(f"监控 {len(videos)} 个自己的视频", "INFO")
        check_count = 0

        for vid in videos:
            if not self.running:
                break
            comments = await self._get_comments_for_video(client, vid['bvid'], page=1)
            new_comments = [c for c in comments if c['rpid'] not in self.processed_comments]

            for cmt in new_comments:
                if not self.running:
                    break
                self.processed_comments.add(cmt['rpid'])

                is_at, bv_target, _ = self._check_at_trigger(cmt['content'])
                if is_at and self.config.get('at_trigger_enabled'):
                    if bv_target in ("auto", ""):
                        bv_target = vid['bvid']
                    await self._handle_at_trigger_legacy(client, cmt, bv_target, vid['bvid'])

            check_count += len(new_comments)
            if check_count >= self.config.get('max_replies_per_check', 3):
                break

    # ── @触发处理（v2通知版/legacy版）──
    async def _handle_at_trigger_v2(self, client: httpx.AsyncClient, ntf: dict, target_bv: str):
        """v2: 通知模式处理@触发 - 回复到notify对应的评论区"""
        self._log(f"[AT] 处理: bv={target_bv} from {ntf['uname']}", "AT")

        rpid = ntf.get('rpid', '')
        aid = ntf.get('aid', 0)
        if not rpid:
            rpid = '0'

        aid_str = str(aid) if aid else target_bv

        # 获取视频信息 + 字幕
        video_info = await self._get_video_info(client, target_bv)
        if not video_info:
            reply_text = "抱歉，无法获取该视频的详细信息，请确认视频可访问。"
            await self._post_comment(client, aid_str, int(rpid) if rpid.isdigit() else 0,
                                     int(rpid) if rpid.isdigit() else 0, reply_text)
            return

        subtitle_text = await self._get_subtitles(client, target_bv)
        if not subtitle_text:
            reply_text = f"视频《{video_info.get('title','')[:30]}》暂无可用的AI字幕，无法生成总结〜"
            await self._post_comment(client, aid_str, int(rpid) if rpid.isdigit() else 0,
                                     int(rpid) if rpid.isdigit() else 0, reply_text)
            return

        self._log(f"[AT] AI生成总结中: 《{video_info.get('title','')[:30]}》...", "AT")
        summary = await self._generate_summary(video_info, subtitle_text)
        if not summary:
            reply_text = f"生成视频《{video_info.get('title','')[:30]}》总结时出了问题，请稍后重试〜"
        else:
            reply_text = summary
            self.stats['at_replies'] += 1
            self.stats.setdefault('notifications_handled', 0)
            self.stats['notifications_handled'] = self.stats.get('notifications_handled', 0) + 1

        if len(reply_text) > 500:
            reply_text = reply_text[:480] + "...[完整版请查看私信]"

        success = await self._post_comment(
            client, aid_str,
            int(rpid) if rpid.isdigit() else 0,
            int(rpid) if rpid.isdigit() else 0,
            reply_text
        )
        if success:
            self._log(f"[OK] 已回复 (bv={target_bv})", "OK")
        save_stats(self.stats)

    async def _handle_at_trigger_legacy(self, client: httpx.AsyncClient, comment: dict,
                                         bv_or_topic: str, my_bvid: str):
        """legacy: 在自己视频下的@触发处理"""
        self._log(f"[AT] {comment['uname']} @请求: {bv_or_topic}", "AT")
        target_bv = bv_or_topic if bv_or_topic and bv_or_topic != "auto" else my_bvid

        video_info = await self._get_video_info(client, target_bv)
        if not video_info:
            await self._post_comment(client, my_bvid, int(comment['rpid']),
                                     int(comment['rpid']),
                                     f"无法获取视频 {target_bv} 的信息，请检查。")
            return

        subtitle_text = await self._get_subtitles(client, target_bv)
        if not subtitle_text:
            await self._post_comment(client, my_bvid, int(comment['rpid']),
                                     int(comment['rpid']),
                                     f"视频《{video_info['title'][:30]}》暂无可用的AI字幕，无法生成总结。")
            return

        summary = await self._generate_summary(video_info, subtitle_text)
        if summary:
            self.stats['at_replies'] += 1
            if len(summary) > 500:
                summary = summary[:480] + "...[完整版请查看私信]"
        else:
            summary = f"生成视频《{video_info['title'][:30]}》总结时遇到问题。"

        await self._post_comment(client, my_bvid, int(comment['rpid']), int(comment['rpid']), summary)
        save_stats(self.stats)

    async def _get_video_info(self, client: httpx.AsyncClient, bvid: str) -> dict:
        try:
            r = await client.get(f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}')
            d = r.json()
            if d.get('code') == 0:
                vi = d['data']
                stat = vi.get('stat', {})
                return {
                    'title': vi.get('title', ''),
                    'author': vi.get('owner', {}).get('name', ''),
                    'bvid': bvid,
                    'url': f'https://www.bilibili.com/video/{bvid}',
                    'desc': (vi.get('desc', '') or '')[:500],
                    'duration': vi.get('duration', 0),
                    'stats': {
                        'view': stat.get('view', 0),
                        'like': stat.get('like', 0),
                        'coin': stat.get('coin', 0),
                        'favorite': stat.get('favorite', 0),
                        'danmaku': stat.get('danmaku', 0),
                    }
                }
        except Exception as e:
            self._log(f"获取视频信息失败: {e}", "ERR")
        return None

    async def _get_subtitles(self, client: httpx.AsyncClient, bvid: str) -> str:
        """获取视频AI字幕（使用 player/wbi/v2 确保URL有效）"""
        try:
            # 获取cid
            r = await client.get(f'https://api.bilibili.com/x/player/pagelist?bvid={bvid}')
            d = r.json()
            if d.get('code') != 0:
                return ""
            cid = d['data'][0]['cid'] if d.get('data') else None
            if not cid:
                return ""

            # 获取字幕列表（使用 player/wbi/v2，与主 bot 一致，避免旧接口返回过期缓存）
            p_r = await client.get(
                f'https://api.bilibili.com/x/player/wbi/v2',
                params={'cid': cid, 'bvid': bvid, 'fnver': 0, 'fnval': 4048}
            )
            p_d = p_r.json()
            subs = p_d.get('data', {}).get('subtitle', {}).get('subtitles', [])
            if not subs:
                subs = p_d.get('data', {}).get('subtitles', [])

            if not subs:
                # fallback: player/v2
                p_r2 = await client.get(f'https://api.bilibili.com/x/player/v2?cid={cid}&bvid={bvid}')
                p_d2 = p_r2.json()
                subs = p_d2.get('data', {}).get('subtitle', {}).get('subtitles', [])
                if not subs:
                    subs = p_d2.get('data', {}).get('subtitles', [])

            if not subs:
                return ""

            # 下载字幕内容
            for s in subs:
                url = s.get('subtitle_url', '')
                # 优先 subtitle_url_v2 (player/wbi/v2 专有)
                if not url or url in ('/', ''):
                    url = s.get('subtitle_url_v2', '')
                if url and url not in ('/', ''):
                    if url.startswith('//'):
                        url = 'https:' + url
                    elif url.startswith('/'):
                        url = 'https://api.bilibili.com' + url
                    sr = await client.get(url)
                    if sr.status_code == 200:
                        j = sr.json()
                        body = j.get('body', [])
                        if body:
                            lines = [item.get('content', '') for item in body if item.get('content')]
                            return '\n'.join(lines)
        except Exception:
            pass
        return ""

    async def _generate_summary(self, video_info: dict, subtitle_text: str) -> str:
        """AI 生成视频总结"""
        custom_prompt = self.config.get('custom_prompt', '')

        # 截取字幕
        sub_for_ai = subtitle_text
        if len(sub_for_ai) > 8000:
            sub_for_ai = sub_for_ai[:3000] + "\n...[省略中间]...\n" + sub_for_ai[-3000:]

        stats = video_info.get('stats', {})
        prompt = f"""你是一个专业的内容总结助手。请根据以下视频信息生成一段简洁的总结回复，用于回复B站评论区@你的用户。

【视频信息】
- 标题: {video_info['title']}
- UP主: {video_info['author']}
- 播放: {stats.get('view',0)} | 点赞: {stats.get('like',0)}
- 时长: {video_info.get('duration',0)//60}分钟

【字幕内容（节选）】
{sub_for_ai}

{f"【额外要求】{custom_prompt}" if custom_prompt else ""}

请生成一段回复（不超过500字），格式如下：

【视频总结】...
【核心观点】1. ... 2. ... 3. ...
【值得一看的原因】...

回复要自然、有人情味，像是在跟朋友聊天。不要用markdown格式，用纯文本。"""

        return await self._ai_chat(prompt)

    def stop(self):
        self.running = False


# ── CLI 入口 ──
async def main():
    bot = StandbyBot()
    if not bot.api_key:
        print("[ERR] 请先配置API Key")
        return
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n[SB] 待机模式已停止")
    except Exception as e:
        print(f"[ERR] {e}")
        traceback.print_exc()

if __name__ == '__main__':
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
