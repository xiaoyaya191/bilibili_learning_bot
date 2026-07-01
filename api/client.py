"""bili/client.py — B站 API 客户端（BiliClient）"""
import asyncio
import json
import os
import re
import time
import random
import hashlib
import uuid as _uuid_mod
from io import BytesIO

import httpx
from bilibili_api import Credential, user, homepage, comment, video, Danmaku
from bilibili_api.comment import CommentResourceType
from bilibili_api.video import Video

from core.config import COOKIE_FILE
from utils.display import log
from utils.helpers import _mask_urls
from api.throttle import _bili_throttle, _bili_trigger_cooldown

class BiliClient:
    def __init__(self):
        self.credential = None
        self.raw_cookies = {}
        self.uid = None
        # [FIX] HTTP/2 连接复用：共享 httpx 客户端，避免每次新建 TCP+TLS 连接
        self._http_client = None
        # [FIX] WBI 签名缓存：每小时内复用，减少 nav 接口调用
        self._wbi_keys = None       # (img_key, sub_key)
        self._wbi_keys_ts = 0.0     # 上次刷新时间戳
        # [FIX] 视频元数据缓存：避免重复 get_video_meta
        self._video_meta_cache = {}  # bvid -> (meta_dict, timestamp)
        self._video_meta_cache_ttl = 300  # 5分钟

    def _load_credential(self):
        if not os.path.exists(COOKIE_FILE):
            log("Cookie文件不存在，需要登录", "LOGIN")
            return None

        try:
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            self.raw_cookies = cookies

            sessdata = cookies.get('SESSDATA', '')
            bili_jct = cookies.get('bili_jct', '')
            buvid3 = cookies.get('buvid3')
            dede = cookies.get('DedeUserID')

            # [WARN] 校验 buvid3 格式：必须是标准 UUID+infoc，否则 B站 永久 -799
            import uuid as _uuid_mod
            buvid3_valid = bool(buvid3 and re.match(
                r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}infoc$',
                buvid3
            ))
            if not buvid3_valid:
                if buvid3:
                    log(f"检测到畸形 buvid3（{buvid3[:20]}...），重新生成...", "WARN")
                else:
                    log("自动补全 buvid3...", "WARN")
                buvid3 = str(_uuid_mod.uuid1()) + "infoc"
                self.raw_cookies['buvid3'] = buvid3
                try:
                    cookies['buvid3'] = buvid3
                    tmp = COOKIE_FILE + '.tmp'
                    with open(tmp, 'w', encoding='utf-8') as f:
                        json.dump(cookies, f, ensure_ascii=False, indent=2)
                    os.replace(tmp, COOKIE_FILE)
                    log(f"buvid3 已写入 cookie 文件: {buvid3}", "SUCCESS")
                except Exception as e:
                    log(f"[WARN] buvid3写入失败: {e}", "WARN")

            if len(sessdata) < 10:
                log("SESSDATA格式错误，需要重新登录", "ERROR")
                return None

            self.credential = Credential(
                sessdata=sessdata,
                bili_jct=bili_jct,
                buvid3=buvid3,
                dedeuserid=dede
            )
            try:
                self.uid = int(dede) if dede else None
            except Exception:
                self.uid = None
            return self.credential
        except Exception as e:
            log(f"读取Cookie失败: {e}", "ERROR")
            return None
    async def init_user_info(self):
        if not self.credential:
            log("凭据无效，无法初始化用户信息", "ERROR")
            return False

        # 登录后稍等，避免cookie校验等请求堆积触发-799
        await asyncio.sleep(random.uniform(3.0, 5.0))
        _logged = False
        for attempt in range(5):
            try:
                await _bili_throttle()  # 🔒 全局节流
                log("正在验证账号有效性...", "LOGIN")
                my_info = await user.get_self_info(self.credential)
                self.uid = my_info.get('mid')
                log(f"登录成功: {my_info.get('name')} (UID: {self.uid})", "SUCCESS")
                return True
            except Exception as e:
                err_msg = str(e)
                if ('-799' in err_msg or '请求过于频繁' in err_msg) and attempt < 4:
                    _bili_trigger_cooldown()  # 🔒 启动全局冷却
                    # 指数退避：2^(attempt+1) * [2, 3.5] 秒
                    wait = (2 ** (attempt + 1)) * random.uniform(2.0, 3.5)
                    if not _logged:
                        log("[WARN] 登录验证触发-799，全局冷却已启动，静默重试...", "WARN")
                        _logged = True
                    await asyncio.sleep(wait)
                else:
                    log(f"登录验证失败: {e}", "ERROR")
                    return False
        return False

    # ── [FIX] HTTP/2 连接复用 + WBI 签名 + 元数据缓存 ─────────────────────
    async def _get_http_client(self):
        """获取/创建共享 httpx.AsyncClient（HTTP/2 + 连接池复用）。
        
        避免每次请求新建 TCP+TLS 连接，显著降低延迟和风控概率。
        """
        if self._http_client is None or getattr(self._http_client, 'is_closed', False):
            self._http_client = httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(20.0, connect=10.0),
                limits=httpx.Limits(
                    max_keepalive_connections=10,
                    max_connections=30,
                    keepalive_expiry=30.0,
                ),
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                }
            )
        return self._http_client

    async def _refresh_wbi_keys(self):
        """获取/刷新 WBI 签名密钥对 (img_key, sub_key)，缓存1小时。"""
        try:
            client = await self._get_http_client()
            resp = await client.get(
                'https://api.bilibili.com/x/web-interface/nav',
                cookies=self.raw_cookies
            )
            data = resp.json()
            if data.get('code') == 0:
                wbi_img = data['data'].get('wbi_img', {})
                img_url = wbi_img.get('img_url', '')
                sub_url = wbi_img.get('sub_url', '')
                # 从 URL 中提取密钥（格式: .../xxx.png 或 .../xxx.svg）
                img_match = re.search(r'/([^/]+)\.(?:png|svg)$', img_url)
                sub_match = re.search(r'/([^/]+)\.(?:png|svg)$', sub_url)
                if img_match and sub_match:
                    self._wbi_keys = (img_match.group(1), sub_match.group(1))
                    self._wbi_keys_ts = time.time()
                    return True
        except Exception as e:
            log(f"WBI 密钥刷新失败: {e}", "WARN")
        return False

    def _wbi_sign(self, params: dict) -> dict:
        """为参数字典添加 WBI 签名 (w_rid + wts)，不修改原字典。

        B站 WBI v3 签名算法：
        1. 拼接 mixin = img_key + sub_key
        2. 对 params 排序后拼接 query string
        3. w_rid = md5(query_string + mixin)
        """
        if not self._wbi_keys:
            return dict(params)
        import hashlib
        img_key, sub_key = self._wbi_keys
        mixin = img_key + sub_key
        wts = int(time.time())
        signed = dict(params)
        signed['wts'] = wts
        # 按 key 字母序排序拼接
        sorted_items = sorted(signed.items(), key=lambda x: x[0])
        query_str = '&'.join(f'{k}={v}' for k, v in sorted_items)
        w_rid = hashlib.md5((query_str + mixin).encode()).hexdigest()
        signed['w_rid'] = w_rid
        return signed

    async def _wbi_get(self, url: str, params: dict = None, **kwargs):
        """带 WBI 签名的 GET 请求（通过共享 HTTP/2 客户端）。"""
        client = await self._get_http_client()
        if self._wbi_keys is None or time.time() - self._wbi_keys_ts > 3600:
            await self._refresh_wbi_keys()
        signed_params = self._wbi_sign(params or {})
        return await client.get(url, params=signed_params, **kwargs)

    async def close(self):
        """关闭共享 HTTP 客户端，释放连接。"""
        if self._http_client and not getattr(self._http_client, 'is_closed', False):
            await self._http_client.aclose()
            self._http_client = None

    def _get_cached_meta(self, bvid: str) -> dict:
        """读取视频元数据缓存。返回 dict 或 {}"""
        entry = self._video_meta_cache.get(bvid)
        if entry:
            meta, ts = entry
            if time.time() - ts < self._video_meta_cache_ttl:
                return meta
            else:
                del self._video_meta_cache[bvid]
        return {}

    def _set_cached_meta(self, bvid: str, meta: dict):
        """写入视频元数据缓存。"""
        if meta:
            self._video_meta_cache[bvid] = (meta, time.time())
            # 限制缓存大小
            if len(self._video_meta_cache) > 50:
                oldest = min(self._video_meta_cache.keys(),
                             key=lambda k: self._video_meta_cache[k][1])
                del self._video_meta_cache[oldest]

    async def get_recommendations(self):
        _logged = False
        for attempt in range(5):
            try:
                await _bili_throttle()  # 🔒 全局节流
                res = await homepage.get_videos(credential=self.credential)
                return [item for item in res['item'] if 'bvid' in item]
            except Exception as e:
                err_msg = str(e)
                if ('-799' in err_msg or '请求过于频繁' in err_msg) and attempt < 4:
                    _bili_trigger_cooldown()  # 🔒 启动全局冷却
                    # 指数退避：2^(attempt+1) * [2, 3.5] 秒
                    wait = (2 ** (attempt + 1)) * random.uniform(2.0, 3.5)
                    if not _logged:
                        log("[WARN] 推荐流触发-799，全局冷却已启动，静默重试...", "WARN")
                        _logged = True
                    await asyncio.sleep(wait)
                else:
                    log(f"获取推荐失败: {e}", "ERROR")
                    return []
        return []

    async def get_hot_comments(self, aid, limit=10):
        _logged = False
        for attempt in range(4):
            try:
                await _bili_throttle()  # 🔒 全局节流（含冷却检查）
                c = await comment.get_comments(
                    oid=aid,
                    type_=CommentResourceType.VIDEO,
                    order=comment.OrderType.LIKE,
                    page_index=1,
                    credential=self.credential
                )
                replies = c.get('replies')
                if replies is None:
                    log(f"评论区无数据 (aid={aid}, 可能评论功能已关闭或API返回空)", "INFO")
                    return []
                return replies[:limit]
            except Exception as e:
                err_msg = str(e)
                if ('-799' in err_msg or '请求过于频繁' in err_msg) and attempt < 3:
                    _bili_trigger_cooldown()  # [NEW] 触发全局冷却
                    wait = 15 + attempt * 20 + random.uniform(0, 10)
                    if not _logged:
                        log(f"[WARN] 热门评论触发-799，全局冷却已启动，{wait:.0f}s后重试…", "WARN")
                        _logged = True
                    await asyncio.sleep(wait)
                elif '12002' in err_msg:
                    log(f"评论区已关闭 (aid={aid}, 错误码12002)", "INFO")
                    return []
                else:
                    log(f"获取评论失败 (aid={aid}): {_mask_urls(str(e)[:120])}", "ERROR")
                    return []
        return []

    async def report_history(self, bvid, played_time=30):
        """上报观看历史（带节流+重试），模拟真实客户端心跳。"""
        await _bili_throttle("上报历史")  # 🔒 全局节流
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Referer": f"https://www.bilibili.com/video/{bvid}",
            "Origin": "https://www.bilibili.com"
        }

        for attempt in range(5):
            try:
                client = await self._get_http_client()
                view_url = "https://api.bilibili.com/x/web-interface/view"
                # WBI 签名
                signed = self._wbi_sign({'bvid': bvid})
                qs = '&'.join(f'{k}={v}' for k, v in signed.items())
                view_resp = await client.get(f"{view_url}?{qs}", cookies=self.raw_cookies, headers=headers)
                view_data = view_resp.json()

                if view_data['code'] != 0:
                    err_msg = str(view_data)
                    if '-799' in err_msg and attempt < 4:
                        _bili_trigger_cooldown()  # 🔒 启动全局冷却
                        wait = (2 ** (attempt + 1)) * random.uniform(2.0, 3.5)
                        await asyncio.sleep(wait)
                        continue
                    return {'code': -1, 'msg': f"无法获取视频信息: {view_data}"}

                aid = view_data['data']['aid']
                cid = view_data['data']['cid']

                ts = int(time.time())
                start_payload = {
                    "aid": aid,
                    "cid": cid,
                    "bvid": bvid,
                    "mid": self.uid,
                    "played_time": 0,
                    "realtime": 0,
                    "start_ts": ts,
                    "type": 3,
                    "dt": 2,
                    "play_type": 1,
                    "csrf": self.raw_cookies.get('bili_jct', '')
                }
                await client.post(
                    "https://api.bilibili.com/x/click-interface/web/heartbeat",
                    data=start_payload,
                    cookies=self.raw_cookies,
                    headers=headers
                )

                end_ts = int(time.time())
                real_start_ts = end_ts - played_time
                final_payload = {
                    "aid": aid,
                    "cid": cid,
                    "bvid": bvid,
                    "mid": self.uid,
                    "played_time": played_time,
                    "realtime": played_time,
                    "start_ts": real_start_ts,
                    "type": 3,
                    "dt": 2,
                    "play_type": 0,
                    "csrf": self.raw_cookies.get('bili_jct', '')
                }

                r = await client.post(
                    "https://api.bilibili.com/x/click-interface/web/heartbeat",
                    data=final_payload,
                    cookies=self.raw_cookies,
                    headers=headers
                )

                res = r.json()
                if res['code'] == 0:
                    return {'code': 0, 'msg': "链路完整上报成功"}
                else:
                    err_msg = str(res)
                    if '-799' in err_msg and attempt < 4:
                        wait = (2 ** (attempt + 1)) * random.uniform(2.0, 3.5)
                        await asyncio.sleep(wait)
                        continue
                    return {'code': -1, 'msg': f"上报失败: {res}"}

            except Exception as e:
                err_msg = str(e)
                if ('-799' in err_msg or '请求过于频繁' in err_msg) and attempt < 4:
                    wait = (2 ** (attempt + 1)) * random.uniform(2.0, 3.5)
                    await asyncio.sleep(wait)
                    continue
                if attempt >= 4:
                    return {'code': -1, 'msg': f"上报异常: {e}"}
        return {'code': -1, 'msg': "上报重试耗尽"}

    # ── [*] UP主关注 / 取关 ──────────────────────────────────────────
    async def follow_up(self, uid: int):
        """关注UP主。uid: UP主的UID"""
        await _bili_throttle("关注UP主")
        try:
            u = user.User(uid, credential=self.credential)
            await u.modify_relation(user.RelationType.SUBSCRIBE)
            return {"code": 0, "msg": f"已关注 UID:{uid}"}
        except Exception as e:
            err_str = str(e)
            # 已经是关注状态（B站错误码22014），不算失败
            err_code = getattr(e, 'code', None) or getattr(e, 'status', None)
            raw_code = (getattr(e, 'raw', {}) or {}).get('code')
            # 多维度检测22014：异常属性code、原始响应code、字符串匹配
            is_22014 = (err_code == 22014 or err_code == -22014 
                        or raw_code == 22014
                        or "22014" in err_str or "已经关注" in err_str or "无法重复关注" in err_str)
            if is_22014:
                return {"code": 22014, "msg": f"已关注(无需重复)"}
            return {"code": -1, "msg": f"关注失败: {e}"}

    async def unfollow_up(self, uid: int):
        """取关UP主。"""
        await _bili_throttle("取关UP主")
        try:
            u = user.User(uid, credential=self.credential)
            await u.modify_relation(user.RelationType.UNSUBSCRIBE)
            return {"code": 0, "msg": f"已取关 UID:{uid}"}
        except Exception as e:
            return {"code": -1, "msg": f"取关失败: {e}"}

    async def get_up_info(self, uid: int):
        """获取UP主信息（名称、签名、粉丝数等）。
        
        [NEW] 敏感接口降频：get_user_info 和 get_relation_info 之间增加延迟，
        避免 space/relation 类接口触发 -412 风控。
        """
        await _bili_throttle("获取UP信息")
        try:
            u = user.User(uid, credential=self.credential)
            info = await u.get_user_info()
            # [FIX] 敏感接口降频：space/relation 类 API 之间增加随机延迟
            await asyncio.sleep(random.uniform(3.0, 6.0))
            relation = await u.get_relation_info()
            return {
                "uid": uid,
                "name": info.get("name", ""),
                "sign": info.get("sign", ""),
                "level": info.get("level", 0),
                "follower": relation.get("follower", 0),
                "video_count": info.get("videos", 0) or relation.get("video_count", 0)
            }
        except Exception as e:
            return {"uid": uid, "error": str(e)}

    async def get_up_videos(self, uid: int, limit: int = 10):
        """获取UP主投稿视频列表。"""
        await _bili_throttle("获取UP视频列表")
        try:
            u = user.User(uid, credential=self.credential)
            data = await u.get_videos(ps=limit)
            items = data.get("list", {}).get("vlist") or data.get("videos") or []
            return [
                {
                    "title": item.get("title", ""),
                    "bvid": item.get("bvid", ""),
                    "aid": item.get("aid", 0),
                    "play": item.get("play", 0),
                    "created": item.get("created", 0),
                    "description": item.get("description", "")[:60]
                }
                for item in items[:limit]
            ]
        except Exception as e:
            return []

    async def search_bilibili(self, query, limit=8):
        """搜索B站视频（供心理画像引擎推荐使用）。"""
        await _bili_throttle("搜索B站视频")
        try:
            from bilibili_api import search as bili_search
            data = await bili_search.search_by_type(
                keyword=query,
                search_type=bili_search.SearchObjectType.VIDEO,
                page=1
            )
            result_block = data.get("result") or data.get("data", {}).get("result") or []
            videos = []
            for item in result_block:
                title = re.sub(r"<.*?>", "", str(item.get("title", "")))
                videos.append({
                    "title": title,
                    "bvid": item.get("bvid"),
                    "author": item.get("author") or item.get("uname", ""),
                    "mid": item.get("mid") or item.get("author_mid", 0),
                    "tag": item.get("tag", ""),
                    "typename": item.get("typename", ""),
                    "play": item.get("play", 0),
                    "duration": item.get("duration", ""),
                    "description": str(item.get("description", ""))[:160],
                    "pic": item.get("pic", ""),
                    "aid": item.get("aid") or item.get("id", 0),
                })
                if len(videos) >= limit:
                    break
            return videos
        except Exception as e:
            log(f"搜索B站视频失败: {e}", "WARN")
            return []

    # ── [MSG] 弹幕相关 ──────────────────────────────────────────────────
    async def _get_video_meta(self, bvid: str) -> dict:
        """获取视频基础元数据（cid, aid）。返回 {"cid": int, "aid": int} 或 {}
        
        [NEW] 优化：WBI签名 + HTTP/2连接复用 + 5分钟缓存
        """
        # [FIX] 缓存命中
        cached = self._get_cached_meta(bvid)
        if cached:
            return cached

        try:
            headers = {
                'Referer': f'https://www.bilibili.com/video/{bvid}'
            }
            cookies = self.raw_cookies or {}
            resp = await self._wbi_get(
                'https://api.bilibili.com/x/web-interface/view',
                params={'bvid': bvid},
                headers=headers,
                cookies=cookies
            )
            data = resp.json()
            if data.get('code') == 0:
                vdata = data['data']
                meta = {"cid": vdata['cid'], "aid": vdata['aid']}
                self._set_cached_meta(bvid, meta)
                return meta
        except Exception as e:
            log(f"获取视频元数据失败: {e}", "WARN")
        return {}

    async def get_danmakus(self, bvid: str, limit: int = 40):
        """获取视频弹幕（seg.so protobuf接口，V1已于2026年废弃412）。
        
        [NEW] 优化：分段遍历 segment_index 1→6（覆盖长视频前36分钟弹幕）
        返回 (cid, danmaku_list)，其中 danmaku_list: [{id_str, text, dm_time, mode, color, uid_crc32}]
        """
        await _bili_throttle("获取弹幕")
        try:
            meta = await self._get_video_meta(bvid)
            cid = meta.get("cid", 0)
            if not cid:
                log(f"获取弹幕失败：未找到视频cid", "WARN")
                return (0, [])

            headers = {
                'Referer': 'https://www.bilibili.com'
            }
            cookies = self.raw_cookies or {}
            
            # [NEW] 分段遍历：segment_index 1→6，每段6分钟
            all_danmakus = []
            max_segments = 6
            for seg_idx in range(1, max_segments + 1):
                params = {'oid': cid, 'type': 1, 'segment_index': seg_idx}
                # seg.so 接口使用 WBI 签名
                client = await self._get_http_client()
                if self._wbi_keys and time.time() - self._wbi_keys_ts < 3600:
                    signed = self._wbi_sign(params)
                else:
                    signed = params
                resp = await client.get(
                    'https://api.bilibili.com/x/v2/dm/web/seg.so',
                    params=signed, headers=headers, cookies=cookies
                )
                data = resp.read()

                if data == b"\x10\x01":
                    # 空段=弹幕关闭或已读完
                    if seg_idx == 1:
                        log(f"弹幕已关闭", "WARN")
                        return (cid, [])
                    break

                seg_danmakus = self._parse_dm_seg(data)
                if not seg_danmakus:
                    break  # 空段，后续也不会有
                all_danmakus.extend(seg_danmakus)
                
                # 分段间稍作延迟避免限流
                if seg_idx < max_segments:
                    await asyncio.sleep(random.uniform(0.5, 1.5))

            # 随机打乱，取 limit 条
            random.shuffle(all_danmakus)
            return (cid, all_danmakus[:limit])
        except Exception as e:
            log(f"获取弹幕异常: {e}", "WARN")
            return (0, [])

    @staticmethod
    def _parse_dm_seg(data: bytes) -> list:
        """解析 seg.so protobuf 数据为弹幕列表。"""
        def _read_varint(reader):
            val = 0; shift = 0
            while True:
                b = reader.read(1)
                if not b:
                    return None
                b = b[0]
                val |= (b & 0x7f) << shift
                if not (b & 0x80):
                    return val
                shift += 7

        reader = BytesIO(data)
        danmakus = []

        while reader.tell() < len(data):
            field = _read_varint(reader)
            if field is None:
                break
            wire_type = field & 0x07
            field_num = field >> 3

            if wire_type != 2:
                if field_num == 4:
                    length = _read_varint(reader)
                    if length is not None:
                        reader.seek(length, 1)
                continue

            length = _read_varint(reader)
            if length is None:
                break
            dm_data = reader.read(length)
            dm_reader = BytesIO(dm_data)

            dm = {}
            while dm_reader.tell() < len(dm_data):
                f = _read_varint(dm_reader)
                if f is None:
                    break
                wt = f & 0x07
                fn = f >> 3

                if fn == 1:    # id
                    dm['id'] = _read_varint(dm_reader)
                elif fn == 2:  # dm_time (ms)
                    v = _read_varint(dm_reader)
                    dm['dm_time'] = (v / 1000) if v is not None else 0.0
                elif fn == 3:  # mode
                    dm['mode'] = _read_varint(dm_reader) or 1
                elif fn == 4:  # font_size
                    dm['font_size'] = _read_varint(dm_reader) or 25
                elif fn == 5:  # color
                    v = _read_varint(dm_reader)
                    dm["color"] = hex(v)[2:] if v else "ffffff"
                elif fn == 6:  # uid_crc32
                    l2 = _read_varint(dm_reader)
                    dm['uid_crc32'] = dm_reader.read(l2).decode('utf-8', errors='replace') if l2 else ''
                elif fn == 7:  # text
                    l2 = _read_varint(dm_reader)
                    dm['text'] = dm_reader.read(l2).decode('utf-8', errors='replace') if l2 else ''
                elif fn == 8:  # send_time
                    dm['send_time'] = _read_varint(dm_reader) or 0
                elif fn == 9:  # weight (skip)
                    _read_varint(dm_reader)
                elif fn == 10:  # action (skip)
                    _read_varint(dm_reader)
                elif fn == 11:  # pool
                    dm['pool'] = _read_varint(dm_reader) or 0
                elif fn == 12:  # id_str
                    l2 = _read_varint(dm_reader)
                    dm['id_str'] = dm_reader.read(l2).decode('utf-8', errors='replace') if l2 else ''
                elif fn == 13:  # attr (skip)
                    _read_varint(dm_reader)
                else:
                    break

            dm.setdefault("id_str", str(dm.get("id", "")))
            dm.setdefault("text", "")
            dm.setdefault("dm_time", 0.0)
            dm.setdefault("mode", 1)
            dm.setdefault("color", "ffffff")
            dm.setdefault("uid_crc32", "")
            dm.setdefault("font_size", 25)
            dm.setdefault("send_time", 0)
            dm.setdefault("pool", 0)
            danmakus.append(dm)

        return danmakus

    async def like_danmaku(self, dmid: str, cid: int, bvid: str = ""):
        """点赞弹幕。dmid: 弹幕字符串ID (id_str), cid: 视频cid"""
        await _bili_throttle("点赞弹幕")
        try:
            # 确保 credential 已加载
            if not self.credential:
                self._load_credential()

            # 优先使用 bilibili_api 的 like_danmaku 方法
            if bvid and self.credential:
                try:
                    v = Video(bvid=bvid, credential=self.credential)
                    if hasattr(v, 'like_danmaku'):
                        await v.like_danmaku(dmid=dmid, cid=cid)
                        return {"code": 0, "msg": f"弹幕 {dmid[:12]}... 点赞成功"}
                except Exception as e:
                    log(f"[WARN] bilibili_api弹幕点赞降级到httpx: {e}", "WARN")

            # 降级：直接用 httpx + cookies
            if not self.raw_cookies:
                self._load_credential()
            csrf = self.raw_cookies.get('bili_jct', '')
            if not csrf:
                return {"code": -1, "msg": "弹幕点赞失败: 缺少 bili_jct (csrf token)"}
            client = await self._get_http_client()
            resp = await client.post('https://api.bilibili.com/x/v2/dm/thumbup/add', data={
                'dmid': dmid,
                'oid': cid,
                'platform': 'web',
                'csrf': csrf
            }, cookies=self.raw_cookies)
            data = resp.json()
            if data.get('code') != 0:
                return {"code": data.get('code', -1), "msg": data.get('message', '未知错误')}
            return {"code": 0, "msg": f"弹幕 {dmid[:12]}... 点赞成功"}
        except Exception as e:
            return {"code": -1, "msg": f"弹幕点赞失败: {e}"}

    async def send_danmaku(self, bvid: str, text: str, dm_time: float = 0.0):
        """发送弹幕到视频。"""
        await _bili_throttle("发送弹幕")
        try:
            # 确保 credential 已加载
            if not self.credential:
                self._load_credential()
            if not self.credential:
                return {"code": -1, "msg": "弹幕发送失败: 凭据未加载"}

            v = Video(bvid=bvid, credential=self.credential)
            dm = Danmaku(text=text, dm_time=dm_time)
            await v.send_danmaku(danmaku=dm, page_index=0)
            return {"code": 0, "msg": f"弹幕发送成功: {text[:30]}"}
        except Exception as e:
            return {"code": -1, "msg": f"弹幕发送失败: {e}"}


# ==============================================================================
# 🎉 娱乐功能模块（默认关闭，需在主菜单手动开启）
# ==============================================================================
# 🔑 登录模块
# ==============================================================================
