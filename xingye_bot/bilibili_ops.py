from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from .settings import DATA_DIR
from .state import JsonStore, now_iso


COOKIE_FILE = DATA_DIR / "bilibili_cookies.json"
# AI_MARKER 改为从配置动态读取，不再硬编码
_AI_MARKER_CACHE: str | None = None


def _get_ai_marker() -> str:
    global _AI_MARKER_CACHE
    if _AI_MARKER_CACHE is None:
        from .settings import load_settings
        _AI_MARKER_CACHE = load_settings().ai_marker
    return _AI_MARKER_CACHE


# 高风险关键词：明确政治指向的组合词，单次命中即拦截
POLITICAL_HIGH_RISK = [
    "六四", "法轮", "辱华", "台独", "港独", "藏独", "疆独",
    "靖国神社", "武统", "一国两制", "独裁", "民族主义",
]

# 高频通用词：日常常见词，需 2+ 命中才拦截（单命中不拦，避免误杀）
POLITICAL_COMMON = [
    "主席", "党", "国家", "政治", "政府", "共产党", "中共", "习近平", "毛泽东",
    "人大", "国务院", "军委", "台湾", "香港", "新疆", "西藏",
    "选举", "民主", "宪法", "外交部", "制裁", "战争", "俄乌", "以色列",
    "巴勒斯坦", "抗议", "游行", "维权", "人权", "警察", "军队", "解放军",
]

# 合并列表（向后兼容）
POLITICAL_KEYWORDS = POLITICAL_HIGH_RISK + POLITICAL_COMMON


def _with_ai_marker(text: str) -> str:
    marker = _get_ai_marker()
    text = (text or "").strip()
    if not text:
        return marker
    if marker in text or "(内容由AI生成并由AI回复)" in text:
        return text
    return f"{text}{marker}"


def _political_hits(text: str) -> list[str]:
    """分级检测敏感词：
    - 高风险词：单次命中即计入
    - 通用词：需 2+ 命中才计入（单通用词不拦截）
    """
    compact = "".join(str(text or "").lower().split())
    hits = []
    for word in POLITICAL_HIGH_RISK:
        if word.lower() in compact:
            hits.append(word)
    common_hits = [word for word in POLITICAL_COMMON if word.lower() in compact]
    if len(common_hits) >= 2:
        hits.extend(common_hits)
    return sorted(set(hits))


def _load_cookies() -> dict[str, str]:
    if not COOKIE_FILE.exists():
        return {}
    try:
        return json.loads(COOKIE_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cookies(cookies: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")


class BilibiliAccount:
    def __init__(self):
        self.events = JsonStore("web_bilibili_events.json", {"items": []})

    def _log(self, action: str, ok: bool, detail: str = "") -> None:
        data = self.events.read()
        data.setdefault("items", []).insert(0, {"action": action, "ok": ok, "detail": detail, "created_at": now_iso()})
        data["items"] = data["items"][:200]
        self.events.write(data)

    def credential(self):
        from bilibili_api import Credential

        cookies = _load_cookies()
        if not cookies:
            raise RuntimeError("未找到 Data/bilibili_cookies.json")
        return Credential(
            sessdata=cookies.get("SESSDATA"),
            bili_jct=cookies.get("bili_jct"),
            buvid3=cookies.get("buvid3"),
            buvid4=cookies.get("buvid4"),
            dedeuserid=cookies.get("DedeUserID"),
            ac_time_value=cookies.get("ac_time_value"),
        )

    async def status(self) -> dict[str, Any]:
        cookies = _load_cookies()
        if not cookies:
            return {"logged_in": False, "refresh_available": False, "message": "Cookie 文件不存在", "events": self.events.read()}
        cred = self.credential()
        try:
            valid = await cred.check_valid()
        except Exception as exc:
            self._log("check_valid", False, repr(exc))
            valid = False
        try:
            refresh_needed = await cred.check_refresh() if hasattr(cred, "check_refresh") else False
        except Exception as exc:
            self._log("check_refresh", False, repr(exc))
            refresh_needed = False
        return {
            "logged_in": bool(valid),
            "refresh_available": bool(cookies.get("ac_time_value")),
            "refresh_needed": bool(refresh_needed),
            "uid": cookies.get("DedeUserID", ""),
            "events": self.events.read(),
        }

    async def refresh(self) -> dict[str, Any]:
        cred = self.credential()
        if not getattr(cred, "ac_time_value", None):
            raise RuntimeError("缺少 ac_time_value/refresh_token，无法自动刷新")
        await cred.refresh()
        cookies = cred.get_cookies()
        normalized = {
            "SESSDATA": cookies.get("SESSDATA") or getattr(cred, "sessdata", ""),
            "bili_jct": cookies.get("bili_jct") or getattr(cred, "bili_jct", ""),
            "DedeUserID": cookies.get("DedeUserID") or getattr(cred, "dedeuserid", ""),
            "buvid3": cookies.get("buvid3") or getattr(cred, "buvid3", ""),
            "buvid4": cookies.get("buvid4") or getattr(cred, "buvid4", ""),
            "ac_time_value": getattr(cred, "ac_time_value", ""),
        }
        _save_cookies({k: v for k, v in normalized.items() if v})
        self._log("refresh", True, "Cookie 已刷新")
        return await self.status()

    def logout(self) -> dict[str, Any]:
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()
        self._log("logout", True, "Cookie 已删除")
        return {"logged_in": False, "message": "已退出登录并删除 Cookie", "events": self.events.read()}

    async def send_dynamic(self, text: str, image_path: str = "", dry_run: bool = True, allow_dynamic: bool = False) -> dict[str, Any]:
        if dry_run or not allow_dynamic:
            self._log("dynamic.draft", True, text[:120])
            return {"executed": False, "reason": "dry_run 或 allow_dynamic 未开启", "text": text}
        from bilibili_api import dynamic
        from bilibili_api.dynamic import BuildDynamic

        builder = BuildDynamic()
        builder.add_plain_text(text)
        if image_path:
            from bilibili_api import Picture

            pic = Picture.from_file(Path(image_path))
            uploaded = await dynamic.upload_image(pic, credential=self.credential())
            builder.add_image(uploaded)
        result = await dynamic.send_dynamic(builder, credential=self.credential())
        self._log("dynamic.send", True, str(result)[:200])
        return {"executed": True, "result": result}

    async def video_action(
        self,
        bvid: str,
        action: str,
        text: str = "",
        dry_run: bool = True,
        allow_comment: bool = False,
        allow_like: bool = False,
        allow_coin: bool = False,
        allow_favorite: bool = False,
    ) -> dict[str, Any]:
        action = (action or "").strip().lower()
        payload = {"bvid": bvid, "action": action, "text": text}
        if dry_run:
            self._log(f"video.{action}.dry_run", True, str(payload)[:200])
            return {"executed": False, "reason": "dry_run 已开启", "payload": payload}

        from bilibili_api import comment, favorite_list
        from bilibili_api.comment import CommentResourceType
        from bilibili_api.video import Video

        cred = self.credential()
        video_obj = Video(bvid=bvid, credential=cred)
        if action == "comment":
            if not allow_comment:
                return {"executed": False, "reason": "allow_comment 未开启", "payload": payload}
            info = await video_obj.get_info()
            hits = _political_hits(f"{info.get('title', '')}\n{info.get('desc', '')}\n{text}")
            if hits:
                self._log("video.comment.blocked", False, f"涉政/敏感视频禁止评论: {hits}")
                return {"executed": False, "blocked": True, "reason": "涉政/敏感视频禁止评论", "hits": hits, "payload": payload}
            result = await comment.send_comment(_with_ai_marker(text), oid=info["aid"], type_=CommentResourceType.VIDEO, credential=cred)
        elif action == "like":
            if not allow_like:
                return {"executed": False, "reason": "allow_like 未开启", "payload": payload}
            result = await video_obj.like(True)
        elif action == "coin":
            if not allow_coin:
                return {"executed": False, "reason": "allow_coin 未开启", "payload": payload}
            result = await video_obj.pay_coin(num=1, like=False)
        elif action == "favorite":
            if not allow_favorite:
                return {"executed": False, "reason": "allow_favorite 未开启", "payload": payload}
            folders = await favorite_list.get_video_favorite_list(uid=int(cred.dedeuserid), video=video_obj, credential=cred)
            folder_items = folders.get("list") or []
            if not folder_items:
                raise RuntimeError("未找到可用收藏夹")
            result = await video_obj.set_favorite(add_media_ids=[folder_items[0]["id"]])
        else:
            raise ValueError("未知视频动作，可选 comment/like/coin/favorite")

        self._log(f"video.{action}", True, str(result)[:200])
        return {"executed": True, "result": result}

    async def recommended_videos(self, limit: int = 10) -> list[dict[str, Any]]:
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}
        async with httpx.AsyncClient(http2=True, headers=headers, cookies=_load_cookies(), timeout=20) as client:
            resp = await client.get("https://api.bilibili.com/x/web-interface/index/top/feed/rcmd", params={"ps": limit})
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(data.get("message", "推荐流获取失败"))
        return data.get("data", {}).get("item", [])[:limit]

    async def recent_replies_to_me(self, limit: int = 20) -> list[dict[str, Any]]:
        cookies = _load_cookies()
        if not cookies:
            raise RuntimeError("未找到 Data/bilibili_cookies.json")
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}
        async with httpx.AsyncClient(http2=True, headers=headers, cookies=cookies, timeout=20) as client:
            resp = await client.get(
                "https://api.bilibili.com/x/msgfeed/reply",
                params={"platform": "web", "build": 0, "mobi_app": "web"},
            )
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(data.get("message", "评论消息获取失败"))
        items = data.get("data", {}).get("items", []) or []
        return items[:limit]

    async def send_comment_reply(self, oid: int, root: int, parent: int, text: str, dry_run: bool = True, allow_comment: bool = False) -> dict[str, Any]:
        text = _with_ai_marker(text)
        payload = {"oid": oid, "root": root, "parent": parent, "text": text}
        if dry_run or not allow_comment:
            self._log("comment.reply.dry_run", True, str(payload)[:200])
            return {"executed": False, "reason": "dry_run 或 allow_comment 未开启", "payload": payload}
        from bilibili_api import comment
        from bilibili_api.comment import CommentResourceType

        try:
            async with httpx.AsyncClient(http2=True, timeout=10) as client:
                view = await client.get("https://api.bilibili.com/x/web-interface/view", params={"aid": oid})
                if view.status_code == 200:
                    info = view.json().get("data", {})
                    hits = _political_hits(f"{info.get('title', '')}\n{info.get('desc', '')}\n{text}")
                    if hits:
                        self._log("comment.reply.blocked", False, f"涉政/敏感视频禁止评论: {hits}")
                        return {"executed": False, "blocked": True, "reason": "涉政/敏感视频禁止评论", "hits": hits, "payload": payload}
        except Exception as e:
            self._log("comment.reply.view_fail", False, f"获取视频信息失败: {e}")
            hits = _political_hits(text)
            if hits:
                self._log("comment.reply.blocked", False, f"拟回复命中敏感词: {hits}")
                return {"executed": False, "blocked": True, "reason": "拟回复命中敏感词", "hits": hits, "payload": payload}

        result = await comment.send_comment(
            text,
            oid=oid,
            type_=CommentResourceType.VIDEO,
            root=root or parent,
            parent=parent or root,
            credential=self.credential(),
        )
        self._log("comment.reply", True, str(result)[:200])
        return {"executed": True, "result": result}
