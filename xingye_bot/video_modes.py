from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .llm import ModelClient
from .settings import BotSettings, DATA_DIR

# imageio-ffmpeg 回退检测
try:
    from utils.helpers import find_ffmpeg, find_ffprobe
except ImportError:
    find_ffmpeg = None
    find_ffprobe = None


CACHE_DIR = DATA_DIR / "video_cache"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


@dataclass
class VideoAsset:
    bvid: str = ""
    aid: int = 0
    cid: int = 0
    title: str = ""
    up_name: str = ""
    description: str = ""
    duration: int = 0
    url: str = ""
    cover_url: str = ""
    subtitles: str = ""
    comments: str = ""
    frames: list[Path] = field(default_factory=list)


@dataclass
class UnderstandingResult:
    mode_used: str
    downloaded: bool
    skipped_download_reason: str
    asset: VideoAsset
    summary: str
    gate: dict[str, Any] = field(default_factory=dict)


def normalize_mode(mode: str) -> str:
    value = (mode or "smart").lower().strip()
    aliases = {
        "字幕": "subtitle", "字幕模式": "subtitle",
        "抽帧": "frames", "图片": "frames",
        "混合": "hybrid", "智能": "smart",
    }
    value = aliases.get(value, value)
    return value if value in {"subtitle", "frames", "hybrid", "smart"} else "smart"


def extract_bvid(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"(BV[0-9A-Za-z]{10})", text)
    return match.group(1) if match else text.strip()


class VideoUnderstanding:
    # ── WBI 签名：类级别缓存密钥，避免重复请求 ──
    _wbi_keys_cache: tuple | None = None

    def __init__(self, settings: BotSettings, model: ModelClient):
        self.settings = settings
        self.model = model
        self.download_root.mkdir(parents=True, exist_ok=True)

    @property
    def download_root(self) -> Path:
        configured = (self.settings.video_download_dir or "").strip()
        if not configured:
            return CACHE_DIR
        return Path(configured).expanduser()

    # ═══════════════════════════════════════════════════════════════
    # 🔐 WBI 签名（防 B站 API 返回错误字幕数据）
    # ═══════════════════════════════════════════════════════════════
    async def _get_wbi_keys(self, cookies: dict[str, str] | None = None) -> tuple | None:
        """获取 WBI 签名密钥（类级别缓存，一次获取全局复用）。"""
        if VideoUnderstanding._wbi_keys_cache:
            return VideoUnderstanding._wbi_keys_cache
        headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com"}
        try:
            async with httpx.AsyncClient(http2=True, headers=headers, cookies=cookies, timeout=10) as client:
                nav = await client.get("https://api.bilibili.com/x/web-interface/nav")
                nd = nav.json()
                if nd.get("code") == 0:
                    wi = nd["data"].get("wbi_img", {})
                    im = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get("img_url", ""))
                    sm = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get("sub_url", ""))
                    if im and sm:
                        VideoUnderstanding._wbi_keys_cache = (im.group(1), sm.group(1))
        except Exception:
            pass
        return VideoUnderstanding._wbi_keys_cache

    @staticmethod
    def _wbi_sign_params(params: dict, wbi_keys: tuple | None) -> dict:
        """使用 WBI 密钥对请求参数签名。"""
        if not wbi_keys:
            return dict(params)
        mixin = wbi_keys[0] + wbi_keys[1]
        wts = int(time.time())
        sp = dict(params)
        sp["wts"] = wts
        si = sorted(sp.items(), key=lambda x: x[0])
        qs = "&".join(f"{k}={v}" for k, v in si)
        sp["w_rid"] = hashlib.md5((qs + mixin).encode()).hexdigest()
        return sp

    # ═══════════════════════════════════════════════════════════════
    # 📡 主入口
    # ═══════════════════════════════════════════════════════════════
    async def understand(self, bvid_or_url: str, mode: str = "", cookies: dict[str, str] | None = None) -> UnderstandingResult:
        selected = normalize_mode(mode or self.settings.video_mode)
        bvid = extract_bvid(bvid_or_url)
        if not bvid:
            raise ValueError("请提供 BV 号或 B 站视频链接")

        asset = await self.fetch_metadata(bvid, cookies=cookies)
        await self.fetch_subtitles(asset, cookies=cookies)

        if selected != "subtitle" and asset.duration and asset.duration > self.settings.video_max_duration_seconds:
            summary = await self.summarize_text_only(asset)
            reason = f"视频时长 {asset.duration}s 超过上限 {self.settings.video_max_duration_seconds}s，已跳过下载抽帧"
            return UnderstandingResult(selected, False, reason, asset, summary)

        if selected == "subtitle":
            summary = await self.summarize_text_only(asset)
            return UnderstandingResult("subtitle", False, "字幕模式不下载视频", asset, summary)

        gate: dict[str, Any] = {}
        if selected == "smart":
            gate = await self.smart_gate(asset)
            if not gate.get("download", False):
                summary = await self.summarize_text_only(asset, gate=gate)
                return UnderstandingResult("smart", False, gate.get("reason", "智能判断无需下载"), asset, summary, gate)
            selected = "hybrid"

        download_reason = ""
        video_path: Path | None = None
        try:
            video_path = await self.download_video(asset, cookies=cookies)
            asset.frames = self.extract_frames(video_path, self.settings.video_frame_count)
        except Exception as exc:
            download_reason = f"下载或抽帧失败，已降级到字幕模式：{exc}"

        if asset.frames:
            summary = await self.summarize_with_frames(asset, include_subtitles=selected in {"hybrid", "smart"})
            if video_path and self.settings.video_delete_after_understand:
                self.delete_downloaded_video(video_path)
            return UnderstandingResult(selected, True, "", asset, summary, gate)

        summary = await self.summarize_text_only(asset, gate=gate)
        return UnderstandingResult(selected, False, download_reason or "没有可用抽帧", asset, summary, gate)

    def delete_downloaded_video(self, video_path: Path) -> None:
        try:
            if video_path.exists() and video_path.is_file():
                video_path.unlink()
        except OSError:
            pass

    # ═══════════════════════════════════════════════════════════════
    # 🔍 fetch_metadata — 获取视频元数据（🆕 带 WBI 签名 + HTTP/2）
    # ═══════════════════════════════════════════════════════════════
    async def fetch_metadata(self, bvid: str, cookies: dict[str, str] | None = None) -> VideoAsset:
        headers = {"User-Agent": USER_AGENT, "Referer": f"https://www.bilibili.com/video/{bvid}"}
        wbi_keys = await self._get_wbi_keys(cookies=cookies)
        params = self._wbi_sign_params({"bvid": bvid}, wbi_keys)
        async with httpx.AsyncClient(http2=True, headers=headers, cookies=cookies, timeout=20) as client:
            resp = await client.get("https://api.bilibili.com/x/web-interface/view", params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"B 站视频信息获取失败：{data.get('message')}")
        info = data["data"]
        return VideoAsset(
            bvid=info.get("bvid", bvid),
            aid=int(info.get("aid", 0)),
            cid=int(info.get("cid", 0)),
            title=info.get("title", ""),
            up_name=info.get("owner", {}).get("name", ""),
            description=info.get("desc", ""),
            duration=int(info.get("duration", 0)),
            url=f"https://www.bilibili.com/video/{info.get('bvid', bvid)}",
            cover_url=info.get("pic", ""),
        )

    # ═══════════════════════════════════════════════════════════════
    # 📝 fetch_subtitles — 获取 CC 字幕（🆕 带 WBI 签名 + HTTP/2）
    # ═══════════════════════════════════════════════════════════════
    async def fetch_subtitles(self, asset: VideoAsset, cookies: dict[str, str] | None = None) -> None:
        headers = {"User-Agent": USER_AGENT, "Referer": asset.url}
        wbi_keys = await self._get_wbi_keys(cookies=cookies)
        params = self._wbi_sign_params({"cid": asset.cid, "aid": asset.aid}, wbi_keys)
        async with httpx.AsyncClient(http2=True, headers=headers, cookies=cookies, timeout=20) as client:
            # [FIX] 使用 player/wbi/v2 避免旧接口返回过期缓存
            resp = await client.get("https://api.bilibili.com/x/player/wbi/v2", params=params)
            resp.raise_for_status()
            data = resp.json()
            subs = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
            if not subs:
                # fallback: player/v2
                resp2 = await client.get("https://api.bilibili.com/x/player/v2", params=params)
                resp2.raise_for_status()
                data2 = resp2.json()
                subs = data2.get("data", {}).get("subtitle", {}).get("subtitles", [])
            if not subs:
                asset.subtitles = "[该视频没有可用 CC 字幕]"
                return
            # [AI字幕] 优先选AI中文 > 人工中文 > 其他中文
            def _sub_priority(s):
                lan = s.get('lan', '')
                if lan == 'ai-zh': return 0
                if lan == 'zh': return 10
                if 'zh' in lan: return 20
                if lan.startswith('ai-'): return 30
                return 50
            best_sub = min(subs, key=_sub_priority)
            sub_url = best_sub.get("subtitle_url", '')
            # [FIX] player/wbi/v2 返回的 URL 可能为空但 subtitle_url_v2 有效
            if not sub_url or sub_url in ('/', ''):
                sub_url = best_sub.get("subtitle_url_v2", '')
            if not sub_url:
                sub_url = next((s.get("subtitle_url") or s.get("subtitle_url_v2", '') for s in subs if "zh" in s.get("lan", "")), subs[0].get("subtitle_url") or subs[0].get("subtitle_url_v2", ''))
            if not sub_url:
                asset.subtitles = "[字幕地址为空]"
                return
            if sub_url.startswith("//"):
                sub_url = "https:" + sub_url
            elif sub_url.startswith("/"):
                sub_url = "https://api.bilibili.com" + sub_url
            sub_resp = await client.get(sub_url)
            sub_resp.raise_for_status()
        sub_data = sub_resp.json()
        text = " ".join(item.get("content", "") for item in sub_data.get("body", []))
        text = re.sub(r"\s+", " ", text).strip() or "[字幕为空]"

        # ── 字幕内容与标题关联校验：防止B站AI字幕张冠李戴 ──
        if text and not text.startswith("[") and asset.title:
            if not self._subtitle_matches_title(asset.title, text):
                asset.subtitles = f"[字幕疑似与视频不匹配(标题:{asset.title[:30]}...), 字幕开头: {text[:60]}...]"
                return

        asset.subtitles = text

    @staticmethod
    def _subtitle_matches_title(title: str, subtitle_text: str) -> bool:
        """智能字幕-标题匹配检查。教育类视频标题(数学/课程)不必然出现在开场白(大家好)中。"""
        def _key_fragments(s: str) -> set:
            cleaned = re.sub(r'[^\u4e00-\u9fff\w]', ' ', s.lower())
            parts = cleaned.split()
            return {p for p in parts if len(p) >= 2 and not p.isdigit()}
        title_frags = _key_fragments(title)
        if not title_frags:
            return True  # 标题太短，跳过校验
        
        sub_lower = subtitle_text.lower()
        sub_sample = sub_lower[:600]
        title_lower = title.lower()
        
        hit_count = sum(1 for frag in title_frags if frag in sub_sample)
        overlap = hit_count / len(title_frags)
        
        # 600字不够看全文2000字
        if overlap == 0:
            sub_broad = sub_lower[:2000]
            hit_count = sum(1 for frag in title_frags if frag in sub_broad)
            overlap = hit_count / len(title_frags)
        
        if overlap == 0 and len(title_frags) >= 2:
            # 教育类视频开场白推断
            edu_keywords = {'数学', '语文', '英语', '课程', '教学', '教程', '讲解', '学习',
                            '小学数学', '奥数', '思维训练', '考试', '高考', '考研', '题目',
                            'math', 'english', 'tutorial', 'course', 'lesson'}
            edu_openings = {'各位同学', '大家好', 'hello', 'hi ', '同学们好', '上课',
                            '欢迎来到', '今天我们来', '这节', '本视频', '今天给大家'}
            if any(kw in title_lower for kw in edu_keywords) and any(op in sub_lower[:200] for op in edu_openings):
                return True
            # 中间部分有命中(200-2000字)
            sub_mid = sub_lower[200:2000]
            mid_hits = sum(1 for frag in title_frags if frag in sub_mid)
            if mid_hits >= 1:
                return True
            # 全文字幕远端检查(前5000字)
            sub_big = sub_lower[:5000]
            big_hits = sum(1 for frag in title_frags if frag in sub_big)
            if big_hits >= 1:
                return True
            return False
        return overlap > 0

    # ═══════════════════════════════════════════════════════════════
    # ⬇️ download_video — 下载视频文件
    # ═══════════════════════════════════════════════════════════════
    async def download_video(self, asset: VideoAsset, cookies: dict[str, str] | None = None) -> Path:
        if asset.duration and asset.duration > self.settings.video_max_duration_seconds:
            raise RuntimeError(f"视频时长 {asset.duration}s 超过下载上限 {self.settings.video_max_duration_seconds}s")

        headers = {"User-Agent": USER_AGENT, "Referer": asset.url, "Origin": "https://www.bilibili.com"}
        async with httpx.AsyncClient(http2=True, headers=headers, cookies=cookies, timeout=90, follow_redirects=True) as client:
            play = await client.get(
                "https://api.bilibili.com/x/player/playurl",
                params={"bvid": asset.bvid, "cid": asset.cid, "qn": 32, "fnval": 0, "fourk": 0},
            )
            play.raise_for_status()
            play_data = play.json()
            durls = play_data.get("data", {}).get("durl", [])
            if not durls:
                raise RuntimeError("没有拿到可下载视频流，可能需要登录 Cookie")
            video_url = durls[0]["url"]

            out_dir = self.download_root / asset.bvid
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", asset.title).strip()[:80] or asset.bvid
            out_path = out_dir / f"{asset.bvid}_{safe_title}.mp4"

            async with client.stream("GET", video_url, headers=headers) as resp:
                resp.raise_for_status()
                with out_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(1024 * 256):
                        f.write(chunk)
        return out_path

    # ═══════════════════════════════════════════════════════════════
    # 🎞️ extract_frames — ffmpeg 抽帧（主方案）
    # ═══════════════════════════════════════════════════════════════
    def extract_frames(self, video_path: Path, frame_count: int) -> list[Path]:
        ffmpeg = (find_ffmpeg() if find_ffmpeg else None) or shutil.which("ffmpeg")
        out_dir = video_path.parent / "frames"
        out_dir.mkdir(exist_ok=True)
        for old in out_dir.glob("frame_*.jpg"):
            old.unlink()

        if not ffmpeg:
            return self.extract_frames_with_opencv(video_path, frame_count, out_dir)

        duration = self.probe_duration(video_path)
        interval = max(1, math.floor(duration / max(1, frame_count))) if duration else 5
        pattern = str(out_dir / "frame_%03d.jpg")
        command = [
            ffmpeg,
            "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video_path),
            "-vf", f"fps=1/{interval},scale=640:-1",
            "-frames:v", str(frame_count),
            pattern,
        ]
        subprocess.run(command, check=True)
        return sorted(out_dir.glob("frame_*.jpg"))

    # ═══════════════════════════════════════════════════════════════
    # 🎞️ extract_frames_with_opencv — OpenCV 回退方案
    # ═══════════════════════════════════════════════════════════════
    def extract_frames_with_opencv(self, video_path: Path, frame_count: int, out_dir: Path) -> list[Path]:
        try:
            import cv2
        except ImportError:
            raise RuntimeError("OpenCV (cv2) 未安装，无法抽帧。请安装: pip install opencv-python，或安装 ffmpeg")
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise RuntimeError("OpenCV 无法打开视频文件")

        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total_frames <= 0:
            capture.release()
            raise RuntimeError("OpenCV 无法读取视频帧数")

        count = max(1, min(frame_count, total_frames))
        indexes = [int(i * max(1, total_frames - 1) / count) for i in range(count)]
        paths: list[Path] = []
        for output_index, frame_index in enumerate(indexes, start=1):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            path = out_dir / f"frame_{output_index:03d}.jpg"
            cv2.imwrite(str(path), frame)
            paths.append(path)

        capture.release()
        if not paths:
            raise RuntimeError("OpenCV 未能抽取任何视频帧")
        return paths

    # ═══════════════════════════════════════════════════════════════
    # ⏱️ probe_duration — ffprobe 获取时长
    # ═══════════════════════════════════════════════════════════════
    def probe_duration(self, video_path: Path) -> int:
        ffprobe = (find_ffprobe() if find_ffprobe else None) or shutil.which("ffprobe")
        if not ffprobe:
            return 0
        command = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(command, check=False, text=True, capture_output=True)
        try:
            return int(float(result.stdout.strip()))
        except ValueError:
            return 0

    # ═══════════════════════════════════════════════════════════════
    # 🧠 smart_gate — AI 智能筛选门
    # ═══════════════════════════════════════════════════════════════
    async def smart_gate(self, asset: VideoAsset) -> dict[str, Any]:
        prompt = (
            "你是视频筛选器。先根据标题、简介和字幕判断这个视频是否值得下载抽帧深度观看。\n"
            "只返回 JSON：score 0-10，download true/false，reason 简短理由，visual_need 0-10。\n"
            f"下载阈值：{self.settings.video_download_interest_threshold}\n"
            f"标题：{asset.title}\nUP：{asset.up_name}\n时长：{asset.duration}s\n"
            f"简介：{asset.description[:1000]}\n字幕：{asset.subtitles[:5000]}"
        )
        text = await self.model.chat(
            [{"role": "user", "content": prompt}],
            model_role="fast", purpose="video-smart-gate"
        )
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {"score": 0, "download": False, "reason": text[:120], "visual_need": 0}
        try:
            score = float(data.get("score", 0))
        except (ValueError, TypeError):
            score = 0.0
        try:
            visual_need = float(data.get("visual_need", 0))
        except (ValueError, TypeError):
            visual_need = 0.0
        data["download"] = bool(data.get("download")) \
                            and score >= self.settings.video_download_interest_threshold \
                            and visual_need >= 5
        if asset.duration and asset.duration > self.settings.video_max_duration_seconds:
            data["download"] = False
            data["reason"] = "超过最高时长限制"
        return data

    # ═══════════════════════════════════════════════════════════════
    # 📝 summarize_text_only — 纯文本总结
    # ═══════════════════════════════════════════════════════════════
    async def summarize_text_only(self, asset: VideoAsset, gate: dict[str, Any] | None = None) -> str:
        content = (
            f"模式：字幕模式\n标题：{asset.title}\nUP：{asset.up_name}\n"
            f"时长：{asset.duration}s\n简介：{asset.description[:1200]}\n"
            f"智能筛选：{json.dumps(gate or {}, ensure_ascii=False)}\n"
            f"字幕：{asset.subtitles[:8000]}\n评论：{asset.comments[:2000]}"
        )
        return await self.model.chat([
            {"role": "system", "content": "你通过标题、简介、字幕和评论理解视频。要说明判断依据和不确定性。"},
            {"role": "user", "content": content + "\n\n请输出：内容理解、关键画面缺口、干货评分、互动建议、学习归档建议。"},
        ], purpose="video-subtitle-understand")

    # ═══════════════════════════════════════════════════════════════
    # 🖼️ summarize_with_frames — 多模态（帧+字幕）总结
    # ═══════════════════════════════════════════════════════════════
    async def summarize_with_frames(self, asset: VideoAsset, include_subtitles: bool) -> str:
        text = (
            "你正在模拟真正观看 B 站视频。请结合抽帧图片、基础信息"
            f"{'、字幕' if include_subtitles else ''}判断视频内容。\n"
            f"标题：{asset.title}\nUP：{asset.up_name}\n时长：{asset.duration}s\n"
            f"简介：{asset.description[:1000]}\n"
            f"字幕：{(asset.subtitles if include_subtitles else '[本模式不使用字幕]')[:6000]}\n"
            "请输出：逐段画面观察、字幕和画面的互证、可能看漏的内容、综合评分、是否值得收藏/评论。"
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for frame in asset.frames:
            data_url = "data:image/jpeg;base64," + base64.b64encode(frame.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        return await self.model.chat([
            {"role": "system", "content": "你是视频理解助手，必须同时参考画面证据和文本证据。"},
            {"role": "user", "content": content},
        ], model_role="vision", purpose="video-frame-understand")
