"""xingye_bot/grid_frames.py

复刻 JefferyHcool/BiliNote 的「图文 + 目录」管线，作为默认视频理解逻辑。

三段式流程：
1. extract_grid_frames: 按固定时间间隔抽帧 → 相邻帧 MD5 去重 → 每 grid_size 张拼成
   一张网格图，并在每张左上角打上 mm:ss 时间戳 → 返回 PIL.Image 列表（发给多模态 LLM）。
2. 调用方把网格图 + 约束 prompt 发给 LLM，LLM 在正文插入：
   - `*Screenshot-[mm:ss]`：在该位置配一张「该时间点」的真实截图
   - `*Content-[mm:ss]`：提示读者回到原片某处
   并输出基于 `##` 二级标题的目录结构。
3. replace_markers_with_screenshots: 扫描标记，用 ffmpeg 按精确时间戳截单图，
   替换成内联 `![](data:image/jpeg;base64,...)`（网页/本地通用，无需静态服务器）。

可通过设置 frame_anchor_mode='legacy' 关闭，回退到原逻辑（帧仅作理解素材）。
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from utils.helpers import find_ffmpeg, find_ffprobe
except ImportError:  # pragma: no cover
    find_ffmpeg = None
    find_ffprobe = None


# ───────────────────────────────────────────────────────────────────────────
# 底层工具
# ───────────────────────────────────────────────────────────────────────────
def _get_ffmpeg() -> Optional[str]:
    ff = (find_ffmpeg() if find_ffmpeg else None) or shutil.which("ffmpeg")
    return ff


def _get_ffprobe() -> Optional[str]:
    fp = (find_ffprobe() if find_ffprobe else None) or shutil.which("ffprobe")
    return fp


def _probe_duration(video_path: Path, ffmpeg: str) -> int:
    """返回视频时长（秒），失败返回 0。"""
    fp = _get_ffprobe()
    if fp:
        try:
            out = subprocess.run(
                [fp, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                capture_output=True, text=True, timeout=20)
            d = out.stdout.strip()
            if d:
                return int(float(d))
        except Exception:
            pass
    if ffmpeg:
        try:
            out = subprocess.run([ffmpeg, "-i", str(video_path), "-f", "null", "-"],
                                 capture_output=True, text=True, timeout=40)
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", out.stderr)
            if m:
                h, mi, s, ms = map(int, m.groups())
                return h * 3600 + mi * 60 + s + (1 if ms > 0 else 0)
        except Exception:
            pass
    return 0


def _fmt_ts(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _load_font(size: int):
    from PIL import ImageFont
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def extract_single_frame(video_path: Path, ts: int, out_path: Path, ffmpeg: str) -> Optional[Path]:
    """在 ts 秒处截一张单帧；成功返回路径，失败返回 None。"""
    try:
        subprocess.run(
            [ffmpeg, "-ss", str(ts), "-i", str(video_path), "-frames:v", "1",
             "-q:v", "2", "-y", str(out_path), "-hide_banner", "-loglevel", "error"],
            check=True, capture_output=True, text=True, timeout=60)
        return out_path if out_path.exists() else None
    except Exception:
        return None


# ───────────────────────────────────────────────────────────────────────────
# 阶段一：按时间间隔抽帧 + 去重 + 拼网格（带时间戳）
# ───────────────────────────────────────────────────────────────────────────
def extract_grid_frames(
    video_path,
    frame_interval: int = 6,
    grid: Tuple[int, int] = (3, 3),
    dedup: bool = True,
    unit: Tuple[int, int] = (960, 540),
    max_frames: int = 240,
) -> List:
    """返回网格 PIL.Image 列表（可能为空）。

    - 默认每 6s 抽一帧（贴近真实时间轴，省帧）
    - 相邻帧画面相同（MD5 一致）则去重
    - 每 grid 张拼成一张图，单帧左上角打 mm:ss
    """
    from PIL import Image, ImageDraw
    ffmpeg = _get_ffmpeg()
    if not ffmpeg:
        return []
    video_path = Path(video_path)
    if not video_path.exists():
        return []

    duration = _probe_duration(video_path, ffmpeg)
    if not duration or duration <= 0:
        duration = frame_interval * max_frames
    interval = max(1, int(frame_interval))
    timestamps = list(range(0, int(duration), interval))
    if len(timestamps) > max_frames:
        step = len(timestamps) / max_frames
        timestamps = [timestamps[int(i * step)] for i in range(max_frames)]
    if not timestamps:
        return []

    tmp_dir = video_path.parent / "grid_frames_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for old in tmp_dir.glob("gf_*.jpg"):
        old.unlink(missing_ok=True)

    frame_files: List[Tuple[int, Path]] = []
    last_hash = None
    for ts in timestamps:
        out = tmp_dir / f"gf_{ts:06d}.jpg"
        p = extract_single_frame(video_path, ts, out, ffmpeg)
        if not p:
            continue
        if dedup:
            try:
                h = hashlib.md5(Path(p).read_bytes()).hexdigest()
            except Exception:
                h = None
            if h == last_hash:
                p.unlink(missing_ok=True)
                continue
            last_hash = h
        frame_files.append((ts, Path(p)))

    if not frame_files:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
        return []

    cols, rows = grid
    group_size = cols * rows
    font = _load_font(max(18, unit[1] // 14))
    grid_imgs = []
    for i in range(0, len(frame_files), group_size):
        group = frame_files[i:i + group_size]
        cells = []
        for ts, fp in group:
            try:
                img = Image.open(fp).convert("RGB").resize(unit, Image.Resampling.LANCZOS)
            except Exception:
                continue
            draw = ImageDraw.Draw(img)
            draw.text((10, 10), _fmt_ts(ts), fill="yellow", font=font,
                      stroke_width=2, stroke_fill="black")
            cells.append(img)
        if not cells:
            continue
        grid_img = Image.new("RGB", (unit[0] * cols, unit[1] * rows), (255, 255, 255))
        for idx, c in enumerate(cells):
            x = (idx % cols) * unit[0]
            y = (idx // cols) * unit[1]
            grid_img.paste(c, (x, y))
        grid_imgs.append(grid_img)

    shutil.rmtree(str(tmp_dir), ignore_errors=True)
    return grid_imgs


def grid_images_to_base64(images) -> List[str]:
    out = []
    for im in images:
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=82)
        out.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"))
    return out


# ───────────────────────────────────────────────────────────────────────────
# 阶段三：把 LLM 写出的标记替换为真实截图
# ───────────────────────────────────────────────────────────────────────────
_SCREENSHOT_RE = re.compile(r"\*?Screenshot-\[(\d{1,2}):(\d{2})\]")
_CONTENT_RE = re.compile(r"\*?Content-\[(\d{1,2}):(\d{2})\]")


def replace_markers_with_screenshots(markdown: str, video_path, inline: bool = True) -> Tuple[str, int]:
    """把 `*Screenshot-[mm:ss]` 替换为真实截图（默认内联 base64），
    `*Content-[mm:ss]` 替换为可见的「原片时间点」标记。返回 (markdown, 截图数)。"""
    ffmpeg = _get_ffmpeg()
    video_path = Path(video_path)
    count = 0

    def shot_repl(m: re.Match) -> str:
        nonlocal count
        if not ffmpeg or not video_path.exists():
            return m.group(0)
        ts = int(m.group(1)) * 60 + int(m.group(2))
        out = video_path.parent / f"shot_{ts:06d}.jpg"
        p = extract_single_frame(video_path, ts, out, ffmpeg)
        if not p:
            return m.group(0)
        count += 1
        try:
            data = base64.b64encode(Path(p).read_bytes()).decode("ascii")
        finally:
            p.unlink(missing_ok=True)  # 已内联，清理临时文件
        if inline:
            return f"![](data:image/jpeg;base64,{data})"
        return f"![]({out})"

    md = _SCREENSHOT_RE.sub(shot_repl, markdown)
    md = _CONTENT_RE.sub(lambda m: f"⏱ 原片时间点 {m.group(1)}:{m.group(2)}", md)
    return md, count


def strip_image_data(markdown: str) -> str:
    """移除内联 base64 图片（用于把图文笔记喂给评分/摘要 LLM 时避免 token 爆炸）。"""
    return re.sub(r"!\[[^\]]*\]\(data:image/[^)]*\)", "[配图]", markdown)


# ───────────────────────────────────────────────────────────────────────────
# 约束 prompt（复刻 BiliNote prompt_builder 的 toc/screenshot/link 三段）
# ───────────────────────────────────────────────────────────────────────────
def bilinote_prompt_suffix() -> str:
    return (
        "\n请按「Bilibili 图文笔记」风格输出 Markdown，遵循以下三点：\n"
        "1. 目录：用 `##` 二级标题划分章节（至少 3 章），系统会据此生成目录。\n"
        "2. 原片截图：你看到的网格图每张是一个时间点，左上角标有 mm:ss。"
        "请在正文最合适的位置插入 `*Screenshot-[mm:ss]` 标记（例如 *Screenshot-[02:15]），"
        "系统会自动把它替换成该时间点的真实截图。关键画面务必配图。\n"
        "3. 原片时间点：如需提示读者回到原片某处，使用 `*Content-[mm:ss]` 标记。\n"
        "请直接输出 Markdown，不要使用代码块包裹整个内容。"
    )
