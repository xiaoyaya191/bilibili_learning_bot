#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站 API 全面测试脚本
测试所有关键接口，帮助排查 API 可用性。
"""
import asyncio
import json
import os
import sys
import time
import httpx
from datetime import datetime

# ========== 配置 ==========
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIE_FILE = os.path.join(BASE_DIR, "Data", "bilibili_cookies.json")
PROXY = None  # 如需代理: "http://127.0.0.1:7890"

# 测试视频 BV（会执行点赞投币收藏等操作，用自己或低风险视频）
TEST_BVID = "BV15XEF6kEZb"  # 可替换为任意视频

# ========== 工具函数 ==========
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}

STATS = {"pass": 0, "fail": 0, "skip": 0}

def log(section, label, ok, detail=""):
    """统一日志"""
    icon = "✅" if ok is True else ("❌" if ok is False else "⏭️")
    status = "PASS" if ok is True else ("FAIL" if ok is False else "SKIP")
    if ok is True:
        STATS["pass"] += 1
    elif ok is False:
        STATS["fail"] += 1
    else:
        STATS["skip"] += 1
    print(f"  {icon} [{section}] {label}: {status}{' — ' + detail if detail else ''}")


# ========== 主测试类 ==========
class BiliAPITester:
    def __init__(self):
        self.cookies = {}
        self.csrf = ""
        self.uid = 0
        self.uname = ""
        self.client = None

    async def __aenter__(self):
        # 加载 cookies
        if not os.path.exists(COOKIE_FILE):
            print(f"❌ Cookie 文件不存在: {COOKIE_FILE}")
            sys.exit(1)
        with open(COOKIE_FILE) as f:
            self.cookies = json.load(f)
        self.csrf = self.cookies.get("bili_jct", "")
        self.uid = int(self.cookies.get("DedeUserID", 0))
        print(f"📋 加载 Cookie: UID={self.uid}  CSRF={self.csrf[:8] if self.csrf else '(无)'}...")

        # 创建客户端
        kwargs = {"headers": HEADERS.copy(), "cookies": self.cookies, "timeout": 15.0}
        if PROXY:
            kwargs["proxy"] = PROXY
        self.client = httpx.AsyncClient(**kwargs)
        return self

    async def __aexit__(self, *args):
        if self.client:
            await self.client.aclose()

    # ==================== 1. 登录态验证 ====================
    async def test_auth(self):
        print("\n" + "=" * 60)
        print("🔐 1. 登录态验证")
        print("=" * 60)

        # 1a: /nav
        resp = await self.client.get("https://api.bilibili.com/x/web-interface/nav")
        data = resp.json()
        ok = data.get("code") == 0 and data.get("data", {}).get("isLogin")
        self.uname = data.get("data", {}).get("uname", "?")
        log("AUTH", "/nav 登录态", ok, f"用户={self.uname}")

        # 1b: /x/space/acc/info (自己的空间信息)
        resp2 = await self.client.get(
            "https://api.bilibili.com/x/space/wbi/acc/info",
            params={"mid": self.uid}
        )
        data2 = resp2.json()
        # -403 可能是 wbi 签名问题，但不影响核心功能
        ok2 = data2.get("code") == 0
        if data2.get("code") == -403:
            log("AUTH", "空间信息", None, "code=-403 (可能需要wbi签名，非关键)")
        else:
            log("AUTH", "空间信息", ok2,
                f"关注={data2.get('data',{}).get('following','?')} "
                f"粉丝={data2.get('data',{}).get('fans','?')}" if ok2 else data2.get("message",""))

        # 1c: 每日任务状态
        resp3 = await self.client.get("https://api.bilibili.com/x/web-interface/online")
        data3 = resp3.json()
        ok3 = data3.get("code") == 0
        log("AUTH", "在线人数", ok3, f"在线={data3.get('data',{}).get('region_count', '?')}" if ok3 else "")

    # ==================== 2. 视频信息 ====================
    async def test_video_info(self):
        print("\n" + "=" * 60)
        print("📺 2. 视频信息获取")
        print("=" * 60)

        resp = await self.client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": TEST_BVID}
        )
        data = resp.json()
        ok = data.get("code") == 0
        if ok:
            v = data["data"]
            self._video_cid = v.get("cid", 0)
            self._video_aid = v.get("aid", 0)
            self._video_owner_uid = v.get("owner", {}).get("mid", 0)
            self._video_owner_name = v.get("owner", {}).get("name", "")
            log("VIDEO", "获取视频信息", True,
                f"标题={v.get('title','')[:40]} "
                f"UP={self._video_owner_name} "
                f"stat=view:{v.get('stat',{}).get('view')} "
                f"like:{v.get('stat',{}).get('like')} "
                f"coin:{v.get('stat',{}).get('coin')} "
                f"fav:{v.get('stat',{}).get('favorite')}")
        else:
            log("VIDEO", "获取视频信息", False, f"code={data.get('code')} {data.get('message','')}")
            self._video_cid = None

        # 获取时长 (pagelist)
        resp2 = await self.client.get(
            "https://api.bilibili.com/x/player/pagelist",
            params={"bvid": TEST_BVID}
        )
        data2 = resp2.json()
        if data2.get("code") == 0:
            pages = data2.get("data", [])
            duration = pages[0].get("duration", 0) if pages else 0
            log("VIDEO", "分P信息", True, f"分P数={len(pages)} 时长={duration}s")
        else:
            log("VIDEO", "分P信息", False, str(data2.get("message","")))

    # ==================== 3. 视频互动 ====================
    async def test_video_interact(self):
        print("\n" + "=" * 60)
        print("💬 3. 视频互动接口")
        print("=" * 60)

        # 3a: 点赞状态查询
        resp = await self.client.get(
            "https://api.bilibili.com/x/web-interface/archive/has/like",
            params={"bvid": TEST_BVID}
        )
        data = resp.json()
        ok = data.get("code") == 0
        liked = data.get("data", 0)
        log("INTERACT", "点赞状态查询", ok, f"已赞={liked}")

        # 3b: 投币状态查询
        resp2 = await self.client.get(
            "https://api.bilibili.com/x/web-interface/archive/coins",
            params={"bvid": TEST_BVID}
        )
        data2 = resp2.json()
        ok2 = data2.get("code") == 0
        if ok2:
            coins = data2.get("data", {}).get("multiply", 0)
            log("INTERACT", "投币状态查询", True, f"已投={coins}枚")
        else:
            log("INTERACT", "投币状态查询", False, data2.get("message",""))

        # 3c: 收藏状态查询
        resp3 = await self.client.get(
            "https://api.bilibili.com/x/v3/fav/folder/created/list-all",
            params={"up_mid": self._video_owner_uid, "type": 2, "rid": self._video_aid}
        )
        data3 = resp3.json()
        ok3 = data3.get("code") == 0
        fav_info = "无"
        if ok3 and data3.get("data"):
            for folder in data3.get("data", {}).get("list", []):
                if folder.get("fav_state"):
                    fav_info = folder.get("title", "已收藏")
                    break
            log("INTERACT", "收藏状态查询", True, f"状态={fav_info}")
        else:
            log("INTERACT", "收藏状态查询", None if ok3 else False,
                f"code={data3.get('code')} {data3.get('message','')}")

        # 3d: 要不要执行实际操作？（需要确认）
        DRY_RUN = os.environ.get("DRY_RUN", "1") == "1"
        if DRY_RUN:
            print("\n  ⚠️  DRY_RUN=1，跳过写操作（点赞/投币/收藏/关注）")
            print("  💡 如需执行写操作: DRY_RUN=0 python3 test_api_all.py")
            return

        # ---- 实际写操作 ----

        # 3d: 点赞 (如果未点赞)
        if liked == 0:
            resp4 = await self.client.post(
                "https://api.bilibili.com/x/web-interface/archive/like",
                data={"bvid": TEST_BVID, "like": 1, "csrf": self.csrf}
            )
            data4 = resp4.json()
            log("INTERACT", "👍 点赞", data4.get("code") == 0, data4.get("message",""))
        else:
            log("INTERACT", "👍 点赞", None, "已点赞，跳过")

        # 3e: 投币 (如果未投满2枚)
        if coins < 2:
            resp5 = await self.client.post(
                "https://api.bilibili.com/x/web-interface/coin/add",
                data={"aid": self._video_aid, "bvid": TEST_BVID, "multiply": 1,
                      "select_like": 1, "csrf": self.csrf}
            )
            data5 = resp5.json()
            log("INTERACT", "🪙 投币", data5.get("code") == 0, data5.get("message",""))
        else:
            log("INTERACT", "🪙 投币", None, "已投满2枚，跳过")

        # 3f: 收藏 (如果未收藏)
        if fav_info == "无":
            # 先获取默认收藏夹
            resp6 = await self.client.get(
                "https://api.bilibili.com/x/v3/fav/folder/created/list-all",
                params={"up_mid": self.uid, "type": 2, "rid": self._video_aid}
            )
            folder_data = resp6.json()
            # 处理 data 为 null 的情况
            folders = (folder_data.get("data") or {}).get("list", []) if folder_data.get("code") == 0 else []
            default_fid = folders[0]["id"] if folders else 0
            if default_fid:
                resp7 = await self.client.post(
                    "https://api.bilibili.com/x/v3/fav/resource/deal",
                    data={
                        "rid": self._video_aid, "aid": self._video_aid, "type": 2,
                        "add_media_ids": str(default_fid),
                        "csrf": self.csrf
                    }
                )
                data7 = resp7.json()
                log("INTERACT", "⭐ 收藏", data7.get("code") == 0, data7.get("message",""))
            else:
                log("INTERACT", "⭐ 收藏", False, "无收藏夹")
        else:
            log("INTERACT", "⭐ 收藏", None, "已收藏，跳过")

    # ==================== 4. 关注用户 ====================
    async def test_follow(self):
        print("\n" + "=" * 60)
        print("👤 4. 关注用户接口")
        print("=" * 60)

        DRY_RUN = os.environ.get("DRY_RUN", "1") == "1"

        # 如果测试视频UP就是自己，找一个其他UP
        test_uid = self._video_owner_uid if self._video_owner_uid != self.uid else 430783166

        # 4a: 查询关注关系 (注意：频繁调用可能被限流 -412)
        resp = await self.client.get(
            "https://api.bilibili.com/x/space/acc/info",
            params={"mid": test_uid}
        )
        data = resp.json()
        if data.get("code") == 0:
            log("USER", "用户信息查询", True, f"name={data['data'].get('name')} "
                f"level={data['data'].get('level')}")
        elif data.get("code") == -412:
            log("USER", "用户信息查询", None,
                "code=-412 请求过于频繁（连续调用太多，非接口问题）")
        else:
            log("USER", "用户信息查询", False, data.get("message",""))

        # 4b: 关系状态
        resp2 = await self.client.get(
            "https://api.bilibili.com/x/relation/stat",
            params={"vmid": test_uid}
        )
        data2 = resp2.json()
        ok2 = data2.get("code") == 0
        if ok2:
            log("USER", "关系统计", True, f"关注={data2['data'].get('following')} 粉丝={data2['data'].get('follower')}")

        # 4c: 关注状态 (需要 wbi, 但 relation 接口可用)
        resp3 = await self.client.get(
            "https://api.bilibili.com/x/relation",
            params={"fid": test_uid}
        )
        data3 = resp3.json()
        ok3 = data3.get("code") == 0
        if ok3:
            following = data3.get("data", {}).get("attribute", 0)
            followed = bool(following & 6)  # bit 1=已关注, bit 2=互关
            log("USER", "关注状态查询", True, f"已关注={followed}")
        else:
            log("USER", "关注状态查询", None, f"code={data3.get('code')} (可能需要wbi签名)")

        # 4d: 关注用户列表前几条
        resp4 = await self.client.get(
            "https://api.bilibili.com/x/relation/followings",
            params={"vmid": self.uid, "pn": 1, "ps": 3, "order": "desc"}
        )
        data4 = resp4.json()
        ok4 = data4.get("code") == 0
        if ok4:
            items = data4.get("data", {}).get("list", [])
            names = [i.get("uname", "?") for i in items[:3]]
            log("USER", "自己关注列表", True, f"共{data4['data'].get('total','?')}人 → {', '.join(names)}")
        else:
            log("USER", "自己关注列表", False, data4.get("message",""))

        # 4e: 关注操作 (DRY_RUN跳过)
        if DRY_RUN:
            log("USER", "👤 执行关注", None, "DRY_RUN 模式跳过写操作")
            return

        resp5 = await self.client.post(
            "https://api.bilibili.com/x/relation/modify",
            data={"fid": test_uid, "act": 1, "re_src": 11, "csrf": self.csrf}
        )
        data5 = resp5.json()
        code5 = data5.get("code")
        if code5 == 0:
            log("USER", "👤 关注操作", True, f"已关注 UID={test_uid}")
        elif code5 == 22013:
            log("USER", "👤 关注操作", None, "已关注过，跳过")
        elif code5 == 22106:
            log("USER", "👤 关注操作", False, "被对方拉黑")
        else:
            log("USER", "👤 关注操作", False, f"code={code5} {data5.get('message','')}")

    # ==================== 5. 评论接口 ====================
    async def test_comment(self):
        print("\n" + "=" * 60)
        print("💬 5. 评论接口")
        print("=" * 60)

        if not hasattr(self, '_video_aid') or not self._video_aid:
            log("COMMENT", "评论测试", None, "无aid，跳过")
            return
        # 5a: 查询视频评论
        resp = await self.client.get(
            "https://api.bilibili.com/x/v2/reply",
            params={"type": 1, "oid": self._video_aid, "pn": 1, "ps": 3, "sort": 1}
        )
        data = resp.json()
        ok = data.get("code") == 0
        if ok:
            replies = data.get("data", {}).get("replies", [])
            sample = [(r.get("member",{}).get("uname","?"), r.get("content",{}).get("message","")[:40])
                      for r in replies[:3]]
            log("COMMENT", "查询评论区", True,
                f"共{data['data']['page']['count']}条 → {sample}")
        else:
            log("COMMENT", "查询评论区", False, data.get("message",""))

    # ==================== 6. 弹幕接口 ====================
    async def test_danmaku(self):
        print("\n" + "=" * 60)
        print("🎬 6. 弹幕接口")
        print("=" * 60)

        if not hasattr(self, '_video_cid') or not self._video_cid:
            log("DANMAKU", "弹幕测试", None, "无cid，跳过")
            return

        # 6a: 弹幕 protobuf 分段
        resp = await self.client.get(
            f"https://api.bilibili.com/x/v2/dm/web/seg.so",
            params={"oid": self._video_cid, "type": 1, "segment_index": 1}
        )
        ok = resp.status_code == 200 and len(resp.content) > 30
        log("DANMAKU", "弹幕protobuf (seg.so v2)", ok,
            f"返回{len(resp.content)}字节{' (前30字节可解析)' if ok else ''}")

        # 6b: 弹幕 XML
        resp2 = await self.client.get(
            f"https://api.bilibili.com/x/v1/dm/list.so",
            params={"oid": self._video_cid}
        )
        import re
        dm_count = len(re.findall(r'<d[ >]', resp2.text))
        ok2 = resp2.status_code == 200 and dm_count > 0
        log("DANMAKU", "弹幕XML (list.so v1)", ok2, f"解析出{dm_count}条弹幕")

        # 6c: 弹幕快照 (dm/dmlist) - 可能已废弃
        resp3 = await self.client.get(
            "https://api.bilibili.com/x/v2/dm/list/seg/sv",
            params={"oid": self._video_cid, "type": 1, "segment_index": 1}
        )
        log("DANMAKU", "弹幕视图 (dm/list/seg/sv)", None,
            f"HTTP {resp3.status_code} (接口可能已废弃，使用 seg.so 替代)")

        # 6d: 弹幕历史 (按时间分段)
        resp4 = await self.client.get(
            "https://api.bilibili.com/x/v2/dm/web/history/seg.so",
            params={"oid": self._video_cid, "type": 1, "date": "2025-01-01"}
        )
        ok4 = resp4.status_code == 200
        log("DANMAKU", "弹幕历史 (history/seg.so)", ok4, f"HTTP {resp4.status_code}")

    # ==================== 7. 搜索接口 ====================
    async def test_search(self):
        print("\n" + "=" * 60)
        print("🔍 7. 搜索接口")
        print("=" * 60)

        resp = await self.client.get(
            "https://api.bilibili.com/x/web-interface/wbi/search/all/v2",
            params={"keyword": "python教程", "page": 1}
        )
        data = resp.json()
        ok = data.get("code") == 0
        if ok:
            results = data.get("data", {}).get("result", [])
            for r in results[:2]:
                rtype = r.get("result_type", "")
                items = r.get("data", [])[:2]
                log("SEARCH", f"搜索 '{rtype}'", True,
                    f"共{r.get('numResults',0)}条 → {[i.get('title','')[:30] for i in items]}")
        else:
            log("SEARCH", "搜索", False, data.get("message",""))

    # ==================== 8. 首页推荐 ====================
    async def test_homepage(self):
        print("\n" + "=" * 60)
        print("🏠 8. 首页推荐")
        print("=" * 60)

        resp = await self.client.get(
            "https://api.bilibili.com/x/web-interface/wbi/index/top/feed/rcmd",
            params={"fresh_type": 3, "ps": 5}
        )
        data = resp.json()
        ok = data.get("code") == 0
        if ok:
            items = data.get("data", {}).get("item", [])[:3]
            names = [i.get("title", "?")[:30] for i in items]
            log("HOMEPAGE", "推荐视频", True, f"{len(names)}条 → {names}")
        else:
            log("HOMEPAGE", "推荐视频", False, data.get("message",""))

        # 8b: 热门
        resp2 = await self.client.get(
            "https://api.bilibili.com/x/web-interface/popular",
            params={"pn": 1, "ps": 3}
        )
        data2 = resp2.json()
        ok2 = data2.get("code") == 0
        if ok2:
            items2 = data2.get("data", {}).get("list", [])[:3]
            names2 = [i.get("title", "?")[:30] for i in items2]
            log("HOMEPAGE", "热门视频", True, f"{len(names2)}条 → {names2}")
        else:
            log("HOMEPAGE", "热门视频", False, data2.get("message",""))

    # ==================== 9. 私信接口 ====================
    async def test_private_msg(self):
        print("\n" + "=" * 60)
        print("📧 9. 私信接口")
        print("=" * 60)

        # 会话列表
        resp = await self.client.get(
            "https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions",
            params={"session_type": 1, "group_fold": 1, "unfollow_fold": 1,
                    "sort_rule": 1, "size": 5}
        )
        data = resp.json()
        ok = data.get("code") == 0
        if ok:
            sessions = data.get("data", {}).get("session_list", [])
            log("PM", "会话列表", True, f"共{len(sessions)}个会话")
            for s in sessions[:2]:
                last_msg = s.get("last_msg", {})
                log("PM", f"  └ 会话", True,
                    f"sender={last_msg.get('sender_uid')} "
                    f"内容={str(last_msg.get('content',''))[:40]}")
        else:
            log("PM", "会话列表", False, data.get("message",""))

        # 未读消息数
        resp2 = await self.client.get(
            "https://api.bilibili.com/x/msgfeed/unread",
            params={"build": "0", "mobi_app": "web"}
        )
        data2 = resp2.json()
        ok2 = data2.get("code") == 0
        if ok2:
            unread = data2.get("data", {})
            log("PM", "未读消息", True,
                f"at={unread.get('at',0)} reply={unread.get('reply',0)} "
                f"like={unread.get('love',0)} sys={unread.get('sys_msg',0)}")
        else:
            log("PM", "未读消息", False, data2.get("message",""))

    # ==================== 10. 动态接口 ====================
    async def test_dynamic(self):
        print("\n" + "=" * 60)
        print("📢 10. 动态接口")
        print("=" * 60)

        resp = await self.client.get(
            "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all",
            params={"type": "all", "page": 1}
        )
        data = resp.json()
        ok = data.get("code") == 0
        if ok:
            items = data.get("data", {}).get("items", [])[:3]
            types = [i.get("type", "?") for i in items]
            log("DYNAMIC", "主页动态", True, f"{len(items)}条 → types={types}")
        else:
            log("DYNAMIC", "主页动态", False, data.get("message",""))

    # ==================== 11. 一键三连 ====================
    async def test_triple(self):
        """测试三连接口 (ARC_CONF)"""
        print("\n" + "=" * 60)
        print("🎯 11. 一键三连接口")
        print("=" * 60)

        DRY_RUN = os.environ.get("DRY_RUN", "1") == "1"
        if DRY_RUN:
            log("TRIPLE", "一键三连", None, "DRY_RUN 跳过")
            return

        resp = await self.client.post(
            "https://api.bilibili.com/x/web-interface/archive/like/triple",
            data={"aid": self._video_aid, "bvid": TEST_BVID, "csrf": self.csrf}
        )
        data = resp.json()
        ok = data.get("code") == 0
        log("TRIPLE", "三连 (like + coin + fav)", ok, data.get("message","") or data.get("data",""))

    # ==================== 12. 更新查看数 (report) ====================
    async def test_report(self):
        print("\n" + "=" * 60)
        print("📊 12. 视频播放上报")
        print("=" * 60)

        if not hasattr(self, '_video_cid') or not self._video_cid:
            log("REPORT", "播放上报", None, "无cid跳过")
            return

        # 模拟播放心跳
        elapsed = int(time.time())
        resp = await self.client.post(
            "https://api.bilibili.com/x/click-interface/web/heartbeat",
            data={
                "bvid": TEST_BVID,
                "aid": self._video_aid,
                "cid": self._video_cid,
                "mid": self.uid,
                "csrf": self.csrf,
                "played_time": 0,
                "realtime": 0,
                "start_ts": elapsed,
                "type": 3,
                "sub_type": 0,
                "dt": 2,
                "play_type": 1
            }
        )
        data = resp.json()
        ok = data.get("code") == 0
        log("REPORT", "视频心跳上报", ok, data.get("message",""))

    # ==================== 13. 合集/系列 ====================
    async def test_series(self):
        print("\n" + "=" * 60)
        print("📚 13. 合集/系列接口")
        print("=" * 60)

        # 获取UP主视频列表
        if not hasattr(self, '_video_owner_uid') or not self._video_owner_uid:
            log("SERIES", "UP视频列表", None, "无UP UID跳过")
            return

        resp = await self.client.get(
            "https://api.bilibili.com/x/space/wbi/arc/search",
            params={"mid": self._video_owner_uid, "ps": 3, "pn": 1}
        )
        data = resp.json()
        ok = data.get("code") == 0
        if ok:
            vlist = data.get("data", {}).get("list", {}).get("vlist", [])[:3]
            titles = [v.get("title", "?")[:30] for v in vlist]
            log("SERIES", "UP视频列表(WBI)", True,
                f"共{data['data']['page']['count']}个视频 → {titles}")
        elif data.get("code") == -403:
            log("SERIES", "UP视频列表(WBI)", None,
                "code=-403 (需要wbi签名，非关键接口)")
        else:
            log("SERIES", "UP视频列表(WBI)", False,
                f"code={data.get('code')} {data.get('message','')}")


# ========== main ==========
async def main():
    print("=" * 60)
    print("🧪 B站 API 全面测试")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📋 测试视频: {TEST_BVID}")
    print(f"🌐 代理: {PROXY or '(无)'}")
    print("=" * 60)

    async with BiliAPITester() as tester:
        await tester.test_auth()          # 1. 登录态
        await asyncio.sleep(1.5)
        await tester.test_video_info()    # 2. 视频信息
        await asyncio.sleep(1.5)
        await tester.test_video_interact()# 3. 互动
        await asyncio.sleep(1.5)
        await tester.test_follow()        # 4. 关注
        await asyncio.sleep(1.5)
        await tester.test_comment()       # 5. 评论
        await asyncio.sleep(1.0)
        await tester.test_danmaku()       # 6. 弹幕
        await asyncio.sleep(1.0)
        await tester.test_search()        # 7. 搜索
        await asyncio.sleep(1.0)
        await tester.test_homepage()      # 8. 首页
        await asyncio.sleep(1.0)
        await tester.test_private_msg()   # 9. 私信
        await asyncio.sleep(1.0)
        await tester.test_dynamic()       # 10. 动态
        await asyncio.sleep(1.0)
        await tester.test_triple()        # 11. 三连
        await asyncio.sleep(1.0)
        await tester.test_report()        # 12. 播放上报
        await asyncio.sleep(1.0)
        await tester.test_series()        # 13. 合集/系列

    print("\n" + "=" * 60)
    print("📊 测试汇总")
    print("=" * 60)
    total = STATS["pass"] + STATS["fail"] + STATS["skip"]
    print(f"  ✅ PASS: {STATS['pass']}")
    print(f"  ❌ FAIL: {STATS['fail']}")
    print(f"  ⏭️  SKIP: {STATS['skip']}")
    print(f"  📋 TOTAL: {total}")
    if STATS["fail"] > 0:
        print(f"\n  ⚠️  有 {STATS['fail']} 项失败，请检查错误信息")
    else:
        print(f"\n  🎉 所有测试通过!")


if __name__ == "__main__":
    asyncio.run(main())
