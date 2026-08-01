"""
视频语音识别 + 说话人分离模块
支持: whisper 本地ASR、字幕CC解析、AI驱动的说话人识别
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .settings import DATA_DIR

try:
    from utils.helpers import find_ffmpeg
except ImportError:
    find_ffmpeg = None

CACHE_DIR = DATA_DIR / "asr_cache"

# ── 数据结构 ────────────────────────────
@dataclass
class SpeakerSegment:
    """单个说话片段"""
    speaker_id: str = ""          # "speaker_0", "speaker_1" ...
    speaker_label: str = ""       # AI推断的标签如"主持人"、"嘉宾A"
    start_sec: float = 0.0
    end_sec: float = 0.0
    text: str = ""

@dataclass  
class ASRResult:
    """ASR 完整结果"""
    full_text: str = ""           # 纯文字全文
    segments: list[SpeakerSegment] = field(default_factory=list)
    speakers: dict[str, str] = field(default_factory=dict)  # speaker_id -> label
    method: str = "none"          # whisper / subtitle / subtitle_ai_split
    language: str = "zh"
    duration_seconds: float = 0.0

# ── 说话人标签推断 ───────────────────────
SPEAKER_LABEL_PROMPT = """你是说话人识别助手。根据以下对话文本，推断每个说话人的角色标签。

对话文本使用 [speaker_0]、[speaker_1] 等标记区分说话人。
请推断每个说话人的角色，如：主持人、嘉宾、UP主、采访者、旁白、学生、老师 等。

只返回JSON: {"speaker_0": "角色标签", "speaker_1": "角色标签", ...}

对话文本：
{text}"""

# ── 字幕按说话人分割的提示 ──────────────
SUBTITLE_SPLIT_PROMPT = """你是视频字幕分析助手。以下是B站视频的CC字幕文本（时间连续），请分析并分割出不同说话人的发言。

规则：
1. 根据语气转换、话题切换、提问/回答模式判断说话人切换点
2. 输出JSON数组，每项包含 speaker_label（如"主持人"、"嘉宾"、"UP主"）和 text
3. 如果无法确定说话人，使用 "说话人A"、"说话人B" 等
4. 简短回复，不要输出多余内容

字幕文本：
{text}

只返回JSON数组格式：
[{{"speaker_label": "主持人", "text": "欢迎收看本期..."}}, {{"speaker_label": "嘉宾", "text": "谢谢邀请..."}}]"""


class VideoASR:
    """视频语音识别引擎"""

    def __init__(self, llm_client=None):
        self.llm = llm_client  # 可选的 LLM 客户端用于说话人标签推断
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def whisper_available(self) -> bool:
        """检查 whisper 是否可用"""
        try:
            import whisper
            return True
        except ImportError:
            pass
        # 也检查 faster-whisper
        try:
            from faster_whisper import WhisperModel
            return True
        except ImportError:
            pass
        return False

    @property
    def ffmpeg_available(self) -> bool:
        return ((find_ffmpeg() if find_ffmpeg else None) is not None) or (shutil.which("ffmpeg") is not None)

    # ── 主入口 ──
    async def transcribe(self, video_path: str | Path, 
                         subtitles_text: str = "",
                         duration: float = 0,
                         force_whisper: bool = False) -> ASRResult:
        """
        对视频进行语音识别，智能选择最佳方案：
        1. 如果有字幕且字幕质量好 -> 字幕模式
        2. 如果有whisper + ffmpeg -> 本地ASR
        3. 降级到字幕AI分割
        """
        video_path = Path(video_path)

        # 方案1: 字幕质量好就用字幕
        if subtitles_text and len(subtitles_text) > 100 and not force_whisper:
            return await self._from_subtitles(subtitles_text, duration)

        # 方案2: 本地whisper
        if self.whisper_available and self.ffmpeg_available and video_path.exists():
            try:
                return await self._from_whisper(str(video_path))
            except Exception as e:
                # 降级
                if subtitles_text:
                    return await self._from_subtitles(subtitles_text, duration)
                return ASRResult(full_text=f"[ASR失败: {e}]", method="error")

        # 方案3: 字幕AI分割
        if subtitles_text:
            return await self._from_subtitles(subtitles_text, duration)

        return ASRResult(full_text="[无可用的语音识别方案]", method="none")

    # ── 字幕模式 ──
    async def _from_subtitles(self, text: str, duration: float = 0) -> ASRResult:
        """从CC字幕解析，用AI分割说话人"""
        result = ASRResult(
            full_text=text,
            method="subtitle",
            duration_seconds=duration,
        )

        # 尝试用AI分割说话人
        if self.llm and len(text) > 200:
            try:
                prompt = SUBTITLE_SPLIT_PROMPT.format(text=text[:6000])
                response = await self.llm.chat(
                    [{"role": "user", "content": prompt}],
                    model_role="fast",
                    purpose="subtitle-speaker-split"
                )
                # 解析JSON
                segments_data = self._parse_json_response(response)
                if segments_data:
                    for i, seg in enumerate(segments_data):
                        if isinstance(seg, dict):
                            result.segments.append(SpeakerSegment(
                                speaker_id=f"speaker_{i}",
                                speaker_label=seg.get("speaker_label", f"说话人{chr(65+i)}"),
                                text=seg.get("text", ""),
                            ))
                if result.segments:
                    result.method = "subtitle_ai_split"
            except Exception as e:
                print(f"[ASR] AI说话人分割降级: {e}")

        # 如果没有分割出说话人，创建一个默认的
        if not result.segments:
            result.segments = [SpeakerSegment(
                speaker_id="speaker_0",
                speaker_label="旁白/UP主",
                text=text,
            )]

        return result

    # ── Whisper 模式 ──
    async def _from_whisper(self, video_path: str) -> ASRResult:
        """使用本地 whisper 做语音识别"""
        # 先提取音频
        audio_path = self._extract_audio(video_path)
        if not audio_path:
            raise RuntimeError("音频提取失败")

        try:
            # 尝试 faster-whisper
            try:
                from faster_whisper import WhisperModel
                return self._transcribe_faster_whisper(audio_path)
            except ImportError:
                pass

            # 尝试 openai-whisper
            try:
                import whisper
                return self._transcribe_openai_whisper(audio_path)
            except ImportError:
                pass

            raise RuntimeError("没有可用的 whisper 实现")
        finally:
            # 清理临时音频
            try:
                Path(audio_path).unlink(missing_ok=True)
            except Exception:
                pass

    def _extract_audio(self, video_path: str) -> str:
        """从视频提取音频为16kHz单声道wav"""
        ffmpeg = (find_ffmpeg() if find_ffmpeg else None) or shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg 不可用")

        audio_path = str(CACHE_DIR / f"{Path(video_path).stem}_audio.wav")
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", video_path,
            "-ac", "1", "-ar", "16000",
            "-t", "1800",  # 最多30分钟
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 提取音频失败: {result.stderr[:200]}")
        return audio_path

    def _transcribe_faster_whisper(self, audio_path: str) -> ASRResult:
        """faster-whisper 转写"""
        from faster_whisper import WhisperModel

        # 自动选择模型大小，tiny 用于低资源环境
        model_size = "tiny"
        try:
            import torch
            if torch.cuda.is_available():
                model_size = "small"
        except ImportError:
            pass

        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = model.transcribe(audio_path, language="zh", beam_size=3, vad_filter=True)

        full_text_parts = []
        result = ASRResult(
            method=f"whisper(faster-{model_size})",
            language=info.language,
            duration_seconds=info.duration,
        )

        speaker_map = {}
        last_speaker = None
        current_text = []

        for seg in segments:
            full_text_parts.append(seg.text.strip())

            # 简单的基于停顿的说话人分割（>1.5秒停顿视为换人）
            if last_speaker is not None and seg.start - last_speaker > 1.5:
                if current_text:
                    sid = f"speaker_{len(result.segments)}"
                    result.segments.append(SpeakerSegment(
                        speaker_id=sid,
                        speaker_label=f"说话人{chr(65+len(result.segments))}",
                        text=" ".join(current_text),
                    ))
                current_text = []

            current_text.append(seg.text.strip())
            last_speaker = seg.end if seg.end else seg.start + 1

        # 最后一段
        if current_text:
            sid = f"speaker_{len(result.segments)}"
            result.segments.append(SpeakerSegment(
                speaker_id=sid,
                speaker_label=f"说话人{chr(65+len(result.segments))}",
                text=" ".join(current_text),
            ))

        result.full_text = " ".join(full_text_parts)

        # 用AI推断说话人标签
        if self.llm and len(result.segments) > 1:
            self._infer_speaker_labels(result)

        return result

    def _transcribe_openai_whisper(self, audio_path: str) -> ASRResult:
        """openai-whisper 转写"""
        import whisper

        model = whisper.load_model("tiny")
        transcribe_result = model.transcribe(audio_path, language="zh", verbose=False)

        result = ASRResult(
            method="whisper(openai-tiny)",
            language=transcribe_result.get("language", "zh"),
            full_text=transcribe_result.get("text", ""),
        )

        # 从 segments 创建说话人分割
        segs = transcribe_result.get("segments", [])
        if segs:
            for i, seg in enumerate(segs):
                result.segments.append(SpeakerSegment(
                    speaker_id=f"speaker_{i % 4}",  # 简单轮替
                    speaker_label=f"说话人{chr(65 + (i % 4))}",
                    start_sec=seg.get("start", 0),
                    end_sec=seg.get("end", 0),
                    text=seg.get("text", "").strip(),
                ))

        return result

    def _infer_speaker_labels(self, result: ASRResult):
        """用AI推断说话人标签"""
        if not self.llm:
            return

        # 构建上下文
        text_parts = []
        for seg in result.segments[:20]:  # 最多取前20段
            text_parts.append(f"[{seg.speaker_id}]: {seg.text[:200]}")
        context = "\n".join(text_parts)

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return  # 不在异步上下文中调用
        except RuntimeError:
            pass

    def _parse_json_response(self, text: str) -> list | dict | None:
        """从LLM响应中解析JSON"""
        try:
            # 找第一个 [ 或 {
            text = text.strip()
            start = max(text.find("["), text.find("{"))
            if start == -1:
                return None
            if text[start] == "[":
                end = text.rfind("]")
            else:
                end = text.rfind("}")
            if end > start:
                return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, Exception):
            pass
        return None

    # ── 格式化输出 ──
    def format_for_llm(self, result: ASRResult, max_chars: int = 8000) -> str:
        """将ASR结果格式化为适合LLM的文本"""
        if result.method == "none":
            return "[无可用语音识别]"

        parts = [f"【语音识别方式】{result.method}"]

        if result.segments and len(result.segments) > 1:
            parts.append("\n【说话人分离】")
            for seg in result.segments:
                label = seg.speaker_label or seg.speaker_id
                parts.append(f"  [{label}]: {seg.text}")
        else:
            parts.append(f"\n【全文】{result.full_text[:max_chars]}")

        return "\n".join(parts)


# ── 工具函数 ──
def check_asr_availability() -> dict[str, bool]:
    """检查ASR各组件的可用性"""
    _ff = (find_ffmpeg() if find_ffmpeg else None) or shutil.which("ffmpeg")
    _fp = shutil.which("ffprobe")
    # imageio-ffmpeg 也可能提供 ffprobe
    if not _fp and find_ffmpeg:
        try:
            ffmpeg_exe = find_ffmpeg()
            if ffmpeg_exe:
                import os as _os
                ffmpeg_dir = _os.path.dirname(ffmpeg_exe)
                for name in ["ffprobe", "ffprobe.exe"]:
                    probe_path = _os.path.join(ffmpeg_dir, name)
                    if _os.path.isfile(probe_path):
                        _fp = probe_path
                        break
        except Exception:
            pass
    return {
        "whisper_openai": _check_import("whisper"),
        "whisper_faster": _check_import("faster_whisper"),
        "ffmpeg": _ff is not None,
        "ffprobe": _fp is not None,
    }

def _check_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False
