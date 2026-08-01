"""
ASR Engine — Speech Recognition Engine
- FunASR (Paraformer) primary — best Chinese ASR, local offline
- Whisper fallback — auto switch when FunASR unavailable
- fsmn-vad voice endpoint detection
- ct-punc auto punctuation recovery
- cam++ speaker separation (optional)
- AI pre-check: decide if video needs ASR based on metadata
"""
import io
import os
import shutil
import asyncio
import subprocess
import contextlib
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

# ── 运行时延迟导入（避免无依赖时崩溃）──

def _get_funasr():
    """延迟加载 FunASR"""
    try:
        from funasr import AutoModel
        return AutoModel
    except ImportError:
        return None

def _get_whisper():
    """延迟加载 openai-whisper"""
    try:
        import whisper
        return whisper
    except ImportError:
        return None

def _get_pyannote_pipeline():
    """延迟加载 pyannote 说话人分离"""
    try:
        from pyannote.audio import Pipeline
        return Pipeline
    except ImportError:
        return None

def _normalize_spaced_text(text: str) -> str:
    """FunASR 风格的空格规范化"""
    text = (text or "").strip()
    if " " not in text:
        return text
    parts = [p for p in text.split(" ") if p]
    if len(parts) < 4:
        return text
    single_count = sum(1 for p in parts if len(p) == 1)
    if single_count / max(1, len(parts)) < 0.6:
        return text
    return "".join(parts)


@dataclass
class ASRSegment:
    """单段语音识别结果"""
    start: float = 0.0          # 开始时间（秒）
    end: float = 0.0            # 结束时间（秒）
    text: str = ""              # 识别文字
    confidence: float = 0.0     # 置信度
    speaker: str = ""           # 说话人标签（如 SPEAKER_00）

@dataclass
class ASRResult:
    """语音识别完整结果"""
    success: bool = False
    text: str = ""                          # 全文
    segments: list[ASRSegment] = field(default_factory=list)
    speakers: dict[str, str] = field(default_factory=dict)
    duration: float = 0.0
    model_used: str = ""
    backend: str = ""                       # funasr / whisper
    error: str = ""
    skipped_reason: str = ""
    # ── 耗时统计 ──
    timing: dict[str, float] = field(default_factory=dict)  # 各阶段耗时(秒)


class ASREngine:
    """
    语音识别引擎：视频→音频→文字→说话人

    支持双引擎：
    - funasr (Paraformer): 中文效果最好，内置 VAD + 标点 + 说话人分离
    - whisper: 降级方案，支持多语言
    """

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.enabled = cfg.get("enabled", True)
        self.backend = cfg.get("backend", "funasr")  # funasr / whisper
        self.whisper_model_name = cfg.get("whisper_model", "base")
        self.language = cfg.get("language", "zh")
        self.speaker_separation = cfg.get("speaker_separation", True)
        self.max_audio_duration = cfg.get("max_audio_duration", 3600)
        self.min_confidence = cfg.get("min_confidence", 0.5)
        self.skip_music = cfg.get("skip_music", True)
        self.keep_audio = cfg.get("keep_audio", False)
        self.ffmpeg_path = cfg.get("ffmpeg_path", "") or "ffmpeg"
        self.device = cfg.get("device", "cpu")
        # FunASR 专用配置
        self.funasr_model_dir = cfg.get("funasr_model_dir", "")
        self.funasr_vad_enabled = cfg.get("funasr_vad_enabled", True)
        self.funasr_punc_enabled = cfg.get("funasr_punc_enabled", True)
        self.funasr_spk_enabled = cfg.get("funasr_spk_enabled", False)
        self.funasr_batch_size_s = cfg.get("funasr_batch_size_s", 300)
        self.funasr_hotword = cfg.get("funasr_hotword", "")
        self.num_workers = max(1, int(cfg.get("num_workers", 3)))  # 并行worker数（长音频切块并行）

        # 模型缓存
        self._model = None
        self._backend_loaded = ""  # 当前加载的后端
        self._funasr_available = None

    # ═══════════════════════════════════════════════════════════════
    # Utilities
    # ═══════════════════════════════════════════════════════════════

    _cached_ffmpeg_path: str | None = None  # [SPEED] class-level cache

    def _find_ffmpeg(self) -> str:
        """查找 ffmpeg 路径（搜多个常见位置 + imageio-ffmpeg），首次查找后缓存"""
        if ASREngine._cached_ffmpeg_path is not None:
            cached = ASREngine._cached_ffmpeg_path
            if os.path.isfile(cached) or shutil.which(cached):
                return cached
            ASREngine._cached_ffmpeg_path = None  # invalidated
        
        if self.ffmpeg_path and shutil.which(self.ffmpeg_path):
            ASREngine._cached_ffmpeg_path = self.ffmpeg_path
            return self.ffmpeg_path
        if self.ffmpeg_path and os.path.isfile(self.ffmpeg_path):
            ASREngine._cached_ffmpeg_path = self.ffmpeg_path
            return self.ffmpeg_path
        for candidate in ["ffmpeg", "ffmpeg.exe"]:
            if shutil.which(candidate):
                ASREngine._cached_ffmpeg_path = candidate
                return candidate
        # imageio-ffmpeg 内嵌
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and (os.path.isfile(exe) or shutil.which(exe)):
                ASREngine._cached_ffmpeg_path = exe
                return exe
        except (ImportError, RuntimeError):
            pass
        # 常见安装位置
        candidates = [
            Path(__file__).parent.parent / "ffmpeg" / "bin" / "ffmpeg.exe",
            Path(os.environ.get("APPDATA", "")) / "bilibili" / "ffmpeg" / "ffmpeg.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "JianyingPro" / "Apps",
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Live2D Cubism 4.1" / "tools" / "ffmpeg" / "ffmpeg.exe",
            Path("C:\\ffmpeg\\bin\\ffmpeg.exe"),
        ]
        # 剪映目录版本号可变，glob 匹配
        jianying_base = Path(os.environ.get("LOCALAPPDATA", "")) / "JianyingPro" / "Apps"
        if jianying_base.exists():
            for subdir in sorted(jianying_base.iterdir(), reverse=True):
                ff = subdir / "ffmpeg.exe"
                if ff.exists():
                    candidates.insert(2, ff)
                    break
        for p in candidates:
            if p.exists():
                result = str(p)
                ASREngine._cached_ffmpeg_path = result
                return result
        return "ffmpeg"
    
    def _ffmpeg_ok(self) -> bool:
        """检查 ffmpeg 是否可使用（实际运行验证），结果缓存"""
        if hasattr(self, '_ffmpeg_ok_cache'):
            return self._ffmpeg_ok_cache
        ffmpeg = self._find_ffmpeg()
        if not (shutil.which(ffmpeg) or os.path.isfile(ffmpeg)):
            self._ffmpeg_ok_cache = False
            return False
        try:
            subprocess.run(
                [ffmpeg, "-version"], check=False,
                capture_output=True, timeout=10,
            )
            self._ffmpeg_ok_cache = True
            return True
        except (subprocess.TimeoutExpired, OSError):
            self._ffmpeg_ok_cache = False
            return False

    def _get_model_dir(self) -> str:
        """获取 FunASR 模型目录（自动创建，供 AutoModel 下载模型）"""
        if self.funasr_model_dir and os.path.isdir(self.funasr_model_dir):
            return self.funasr_model_dir
        # 默认路径：项目下的 model/asr，自动创建目录
        default = Path(__file__).parent.parent / "model" / "asr"
        os.makedirs(str(default), exist_ok=True)
        return str(default)

    def _check_funasr_available(self) -> bool:
        """检查 FunASR 是否可用（仅检查包是否安装，模型由 AutoModel 自动下载）"""
        if self._funasr_available is not None:
            return self._funasr_available

        if _get_funasr() is None:
            self._funasr_available = False
            return False

        # 只要 funasr 包已安装，就判为可用（AutoModel 首次调用会自动从 ModelScope 下载模型）
        self._funasr_available = True
        return True

    def is_available(self) -> bool:
        """检查 ASR 是否可用"""
        if not self.enabled:
            return False
        
        if self.backend == "funasr":
            return self._check_funasr_available()
        else:
            return _get_whisper() is not None
    
    def has_ffmpeg(self) -> bool:
        """检查 ffmpeg 是否可用（用于音频提取）"""
        return self._ffmpeg_ok()

    # ═══════════════════════════════════════════════════════════════
    # AI Pre-check: decide if ASR is needed based on video metadata
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def should_skip_asr(
        title: str = "",
        tags: list[str] | None = None,
        category: str = "",
        cover_desc: str = "",
        duration: int = 0,
    ) -> tuple[bool, str]:
        """AI预判：返回 (是否跳过, 原因)"""
        tags_lower = [t.lower() for t in (tags or [])]
        text = f"{title} {' '.join(tags_lower)} {category} {cover_desc}".lower()

        # 音乐类关键词（中英双语）
        music_keywords = [
            "pure music", "piano", "bgm", "ost", "原声带", "钢琴曲", "小提琴",
            "演奏", "演唱会", "live", "翻唱", "cover", "remix",
            "电音", "dj", "混音", "伴奏", "karaoke", "卡拉ok",
            "asmr", "白噪音", "雨声", "助眠", "冥想音乐",
            "mv", "music video", "音乐视频", "音mad", "纯音乐",
            "guitar", "cello", "violin", "flute", "instrumental",
        ]
        if any(kw in text for kw in music_keywords):
            return True, "音乐/演奏类视频，无对话识别意义"

        # 纯游戏操作
        game_only = ["speedrun", "速通", "集锦", "highlight", "击杀", "操作集锦", "no hit", "wr", "world record"]
        if any(kw in text for kw in game_only):
            return True, "游戏纯操作集锦，可能无对话"

        # 时长判断
        if duration and duration < 30:
            return True, f"视频太短({duration}s)，不值得语音识别"
        if duration and duration > 7200:
            return True, f"视频太长({duration}s)，语音识别太耗时"

        # 播客/访谈/教程/知识类 -> 非常适合
        podcast_keywords = [
            "podcast", "播客", "访谈", "采访", "对话", "聊天",
            "教程", "tutorial", "讲解", "课程", "教学", "科普", "知识",
            "talkshow", "脱口秀", "讲座", "演讲", "辩论",
            "vlog", "评测", "review", "开箱",
        ]
        if any(kw in text for kw in podcast_keywords):
            return False, ""

        return False, ""

    # ═══════════════════════════════════════════════════════════════
    # 🎬 视频→音频提取（ffmpeg）
    # ═══════════════════════════════════════════════════════════════

    def extract_audio(self, video_path: Path | str, output_dir: Path | str | None = None) -> tuple[Path | None, float]:
        """用 ffmpeg 从视频提取 16kHz 单声道 WAV（FunASR 推荐格式），ffmpeg 不可用时用 torchaudio 兜底。
        返回 (音频路径, 耗时秒)"""
        import time as _time
        _start = _time.time()
        try:
            video_path = Path(video_path)
            out_dir = Path(output_dir) if output_dir else video_path.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            audio_path = out_dir / f"{video_path.stem}_audio.wav"

            if audio_path.exists() and audio_path.stat().st_size > 1024:
                return audio_path, _time.time() - _start

            ffmpeg = self._find_ffmpeg()
            if os.path.isfile(ffmpeg) or shutil.which(ffmpeg):
                # ✅ ffmpeg 可用，标准提取
                cmd = [
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(video_path),
                    "-vn",
                    "-acodec", "pcm_s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    str(audio_path),
                ]
                try:
                    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
                    if audio_path.exists() and audio_path.stat().st_size > 1024:
                        return audio_path, _time.time() - _start
                    return None, _time.time() - _start
                except subprocess.CalledProcessError as e:
                    stderr_text = (e.stderr[:500] if e.stderr else "(无stderr)")
                    raise RuntimeError(f"ffmpeg 提取音频失败: {stderr_text}")
                except subprocess.TimeoutExpired:
                    raise RuntimeError("ffmpeg 提取音频超时（10分钟）")
            else:
                # 🔧 ffmpeg 不可用，尝试 torchaudio 兜底
                try:
                    import torchaudio
                    import torchaudio.functional as F
                    print(f"⚠️ ffmpeg 未找到，使用 torchaudio 提取音频: {video_path.name}")
                    waveform, sample_rate = torchaudio.load(str(video_path))
                    # 转单声道
                    if waveform.shape[0] > 1:
                        waveform = waveform.mean(dim=0, keepdim=True)
                    # 重采样到 16kHz
                    if sample_rate != 16000:
                        resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
                        waveform = resampler(waveform)
                    torchaudio.save(str(audio_path), waveform, 16000)
                    if audio_path.exists() and audio_path.stat().st_size > 1024:
                        return audio_path, _time.time() - _start
                    return None, _time.time() - _start
                except ImportError:
                    raise RuntimeError("ffmpeg 未安装且 torchaudio 不可用，无法提取音频。请安装 ffmpeg: https://ffmpeg.org/download.html")
                except Exception as e:
                    raise RuntimeError(f"torchaudio 提取音频失败: {e}")
        except Exception:
            _elapsed = _time.time() - _start
            raise

    # ═══════════════════════════════════════════════════════════════
    # FunASR (Paraformer) Primary Engine
    # ═══════════════════════════════════════════════════════════════

    def _load_funasr_model(self):
        """加载 FunASR 模型（含 VAD + 标点 + 可选说话人分离）"""
        AutoModel = _get_funasr()
        if AutoModel is None:
            raise RuntimeError("funasr 未安装，请 pip install funasr")

        model_dir = self._get_model_dir()
        # 检测是否需要首次下载模型
        model_exists = False
        iic_dir = os.path.join(model_dir, "models", "iic")
        if os.path.isdir(iic_dir):
            for root, _, files in os.walk(iic_dir):
                if "model.pt" in files:
                    model_exists = True
                    break
        if model_exists:
            print(f"[ASR] Loading FunASR model (cached: {model_dir})...")
        else:
            print(f"[ASR] [FIRST-TIME] 首次使用，正在从 ModelScope 下载模型 (~2GB, 约5-10分钟)...")
            print(f"[ASR]  模型缓存目录: {model_dir}")
            print(f"[ASR]  下载进度请稍候，后续使用将跳过此步骤...")

        # 设置模型缓存路径
        os.environ["TQDM_DISABLE"] = "1"
        prev_modelscope = os.environ.get("MODELSCOPE_CACHE")
        prev_funasr = os.environ.get("FUNASR_HOME")
        prev_path = os.environ.get("PATH", "")
        os.environ["MODELSCOPE_CACHE"] = model_dir
        os.environ["FUNASR_HOME"] = os.path.dirname(model_dir)

        # 注入 ffmpeg 路径到 PATH，确保 FunASR 内部 _load_audio_ffmpeg 能找到
        ffmpeg_path = self._find_ffmpeg()
        if ffmpeg_path and os.path.isfile(ffmpeg_path):
            ffmpeg_dir = os.path.dirname(os.path.abspath(ffmpeg_path))
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + prev_path
            print(f"  ffmpeg path injected: {ffmpeg_dir}")

        try:
            model = AutoModel(
                model="paraformer-zh",
                vad_model="fsmn-vad" if self.funasr_vad_enabled else None,
                punc_model="ct-punc" if self.funasr_punc_enabled else None,
                spk_model="cam++" if self.funasr_spk_enabled else None,
                device="cuda" if self._check_cuda() else "cpu",
                disable_update=True,
            )
            # 禁用进度条
            try:
                if isinstance(getattr(model, "kwargs", None), dict):
                    model.kwargs["disable_pbar"] = True
                if isinstance(getattr(model, "vad_kwargs", None), dict):
                    model.vad_kwargs["disable_pbar"] = True
                if isinstance(getattr(model, "punc_kwargs", None), dict):
                    model.punc_kwargs["disable_pbar"] = True
                if isinstance(getattr(model, "spk_kwargs", None), dict):
                    model.spk_kwargs["disable_pbar"] = True
            except Exception:
                pass

            self._model = model
            self._backend_loaded = "funasr"
            print("[ASR] FunASR model loaded (Paraformer + VAD + Punc)")
            return model
        finally:
            if prev_modelscope is not None:
                os.environ["MODELSCOPE_CACHE"] = prev_modelscope
            else:
                os.environ.pop("MODELSCOPE_CACHE", None)
            if prev_funasr is not None:
                os.environ["FUNASR_HOME"] = prev_funasr
            else:
                os.environ.pop("FUNASR_HOME", None)
            # 恢复 PATH
            os.environ["PATH"] = prev_path

    def _check_cuda(self) -> bool:
        """检查 CUDA 是否可用"""
        try:
            import torch
            return torch.cuda.is_available()
        except Exception as e:
            print(f"[ASR] CUDA检查失败: {e}")
            return False

    def _transcribe_funasr_core(self, audio_path: Path) -> ASRResult:
        """FunASR 单文件识别核心（前提：模型已加载，ffmpeg PATH已注入）"""
        try:
            duration = self._get_audio_duration(audio_path)
        except Exception:
            duration = 0
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = self._model.generate(
                    input=str(audio_path),
                    batch_size_s=self.funasr_batch_size_s,
                    hotword=self.funasr_hotword or "",
                    disable_pbar=True,
                )

            if not result or len(result) == 0:
                return ASRResult(
                    success=False, duration=duration,
                    error="FunASR 识别结果为空",
                    backend="funasr"
                )

            segments = []
            for seg in result:
                text = seg.get("text", "").strip()
                text = _normalize_spaced_text(text)
                if not text:
                    continue

                start = seg.get("start", seg.get("timestamp", [[0, 0]])[0][0] if "timestamp" in seg else 0)
                if isinstance(start, list):
                    start = start[0] if start else 0
                end = seg.get("end", seg.get("timestamp", [[0, 0]])[0][1] if "timestamp" in seg else 0)
                if isinstance(end, list):
                    end = end[-1] if end else 0

                confidence = seg.get("confidence", seg.get("score", 0.8))
                speaker = seg.get("spk", seg.get("speaker", ""))

                def _safe_ts(val):
                    try:
                        f = float(val)
                        return f / 1000.0 if f > 100 else f
                    except (ValueError, TypeError):
                        return 0.0

                s = ASRSegment(
                    start=_safe_ts(start),
                    end=_safe_ts(end),
                    text=text,
                    confidence=float(confidence),
                    speaker=str(speaker) if speaker else ("UP主" if not self.funasr_spk_enabled else ""),
                )
                if s.confidence >= self.min_confidence:
                    segments.append(s)

            if not self.funasr_spk_enabled:
                full_text = "\n".join(s.text for s in segments)
            else:
                full_text = "\n".join(
                    (f"[{s.speaker}] " if s.speaker else "") + s.text
                    for s in segments
                )

            return ASRResult(
                success=True,
                text=full_text[:10000],
                segments=segments,
                duration=duration,
                model_used="Paraformer-large (FunASR)",
                backend="funasr",
            )
        except Exception as e:
            return ASRResult(
                success=False, duration=0,
                error=f"FunASR 识别异常: {e}",
                backend="funasr"
            )

    def _transcribe_funasr_parallel(self, audio_path: Path) -> ASRResult:
        """[PARALLEL] 长音频切块 → 多线程并行识别 → 合并去重
        PyTorch CPU推理时释放GIL，多线程可以真正并行（约2-3x加速）
        """
        import concurrent.futures

        duration = self._get_audio_duration(audio_path)
        if duration <= 0:
            return self._transcribe_funasr_core(audio_path)

        nw = self.num_workers
        min_chunk_s = 30
        num_chunks = max(1, min(nw, max(1, int(duration / min_chunk_s))))
        if num_chunks <= 1:
            return self._transcribe_funasr_core(audio_path)

        chunk_s = duration / num_chunks

        ffmpeg = self._find_ffmpeg()
        if not (os.path.isfile(ffmpeg) or shutil.which(ffmpeg)):
            return self._transcribe_funasr_core(audio_path)

        # ── 切分音频 ──
        chunk_info = []
        for i in range(num_chunks):
            start = i * chunk_s
            length = min(chunk_s + 3, duration - start)
            if length <= 0:
                break
            chunk_path = audio_path.parent / f"{audio_path.stem}_c{i}.wav"
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(audio_path), "-ss", str(start), "-t", str(length),
                "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(chunk_path),
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=120)
            except subprocess.TimeoutExpired:
                continue
            if chunk_path.exists() and chunk_path.stat().st_size > 1024:
                chunk_info.append((chunk_path, start))
            else:
                try: chunk_path.unlink(missing_ok=True)
                except OSError: pass

        if len(chunk_info) <= 1:
            for cp, _ in chunk_info:
                try: cp.unlink(missing_ok=True)
                except OSError: pass
            return self._transcribe_funasr_core(audio_path)

        print(f"[ASR] ⚡ 并行模式: {duration:.0f}s音频 → {len(chunk_info)}块×{len(chunk_info)}线程...")

        model = self._model
        _saved_omp = os.environ.get("OMP_NUM_THREADS", "")
        _saved_mkl = os.environ.get("MKL_NUM_THREADS", "")

        def _process_one(chunk_path, idx):
            os.environ["OMP_NUM_THREADS"] = "1"
            os.environ["MKL_NUM_THREADS"] = "1"
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result = model.generate(
                        input=str(chunk_path),
                        batch_size_s=self.funasr_batch_size_s,
                        hotword=self.funasr_hotword or "",
                        disable_pbar=True,
                    )
                if not result:
                    return None
                segments = []
                for seg in result:
                    text = seg.get("text", "").strip()
                    text = _normalize_spaced_text(text)
                    if not text:
                        continue
                    s = ASRSegment(
                        start=seg.get("start", 0),
                        end=seg.get("end", 0),
                        text=text,
                        confidence=float(seg.get("confidence", seg.get("score", 0.8))),
                    )
                    if s.confidence >= self.min_confidence:
                        segments.append(s)
                return segments
            except Exception as e:
                print(f"[ASR] 并行块 {idx} 失败: {e}")
                return None

        all_segments = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(chunk_info)) as executor:
            futures = {}
            for i, (chunk_path, start_offset) in enumerate(chunk_info):
                fut = executor.submit(_process_one, chunk_path, i)
                futures[fut] = (chunk_path, start_offset)

            for fut in concurrent.futures.as_completed(futures):
                chunk_path, start_offset = futures[fut]
                try:
                    chunk_segs = fut.result(timeout=600)
                    if chunk_segs:
                        for seg in chunk_segs:
                            seg.start += start_offset
                            seg.end += start_offset
                        all_segments.extend(chunk_segs)
                except Exception as e:
                    print(f"[ASR] 并行块超时/异常: {e}")
                finally:
                    try: chunk_path.unlink(missing_ok=True)
                    except OSError: pass

        # 恢复环境变量
        if _saved_omp:
            os.environ["OMP_NUM_THREADS"] = _saved_omp
        else:
            os.environ.pop("OMP_NUM_THREADS", None)
        if _saved_mkl:
            os.environ["MKL_NUM_THREADS"] = _saved_mkl
        else:
            os.environ.pop("MKL_NUM_THREADS", None)

        all_segments.sort(key=lambda s: s.start)
        deduped = []
        for seg in all_segments:
            if deduped and seg.text.strip() == deduped[-1].text.strip() and seg.start - deduped[-1].start < 5:
                deduped[-1].end = max(deduped[-1].end, seg.end)
            else:
                deduped.append(seg)

        if not deduped:
            return self._transcribe_funasr_core(audio_path)

        if not self.funasr_spk_enabled:
            full_text = "\n".join(s.text for s in deduped)
        else:
            full_text = "\n".join(
                (f"[{s.speaker}] " if s.speaker else "") + s.text
                for s in deduped
            )

        return ASRResult(
            success=True,
            text=full_text[:10000],
            segments=deduped,
            duration=duration,
            model_used=f"Paraformer-large (FunASR Parallel x{len(chunk_info)})",
            backend="funasr",
        )

    def transcribe_funasr(self, audio_path: Path | str) -> ASRResult:
        """使用 FunASR/Paraformer 进行语音识别（长音频自动并行切块）"""
        import time as _time
        _t_start = _time.time()
        audio_path = Path(audio_path)
        if not self._check_funasr_available():
            result = ASRResult(
                success=False,
                error="FunASR 不可用（模型文件缺失或依赖未安装）",
                backend="funasr"
            )
            result.timing["transcribe_seconds"] = _time.time() - _t_start
            return result

        if not audio_path.exists():
            result = ASRResult(
                success=False,
                error=f"音频文件不存在: {audio_path}",
                backend="funasr"
            )
            result.timing["transcribe_seconds"] = _time.time() - _t_start
            return result

        try:
            duration = self._get_audio_duration(audio_path)
            if duration > self.max_audio_duration:
                result = ASRResult(
                    success=False, duration=duration,
                    error=f"音频时长 {duration:.0f}s 超过上限 {self.max_audio_duration}s",
                    backend="funasr"
                )
                result.timing["transcribe_seconds"] = _time.time() - _t_start
                return result
        except Exception:
            duration = 0

        # ── 确保 ffmpeg 在 PATH ──
        ffmpeg_path = self._find_ffmpeg()
        prev_path = os.environ.get("PATH", "")
        if ffmpeg_path and os.path.isfile(ffmpeg_path):
            ffmpeg_dir = os.path.dirname(os.path.abspath(ffmpeg_path))
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + prev_path

        # ── 加载模型 ──
        if self._model is None or self._backend_loaded != "funasr":
            self._load_funasr_model()

        try:
            # [PARALLEL] 长音频(>120s)且worker≥2 → 并行切块处理
            if duration > 120 and self.num_workers >= 2:
                result = self._transcribe_funasr_parallel(audio_path)
            else:
                result = self._transcribe_funasr_core(audio_path)
        finally:
            os.environ["PATH"] = prev_path
        
        result.timing["transcribe_seconds"] = _time.time() - _t_start
        return result

    # ═══════════════════════════════════════════════════════════════
    # 🎙️ Whisper 降级引擎
    # ═══════════════════════════════════════════════════════════════

    def transcribe_whisper(self, audio_path: Path | str) -> ASRResult:
        """使用 Whisper 将音频转为文字（降级方案）"""
        import time as _time
        _t_start = _time.time()
        audio_path = Path(audio_path)
        whisper = _get_whisper()
        if whisper is None:
            result = ASRResult(
                success=False,
                error="whisper 未安装，请 pip install openai-whisper",
                backend="whisper"
            )
            result.timing["transcribe_seconds"] = _time.time() - _t_start
            return result

        if not audio_path.exists():
            result = ASRResult(
                success=False,
                error=f"音频文件不存在: {audio_path}",
                backend="whisper"
            )
            result.timing["transcribe_seconds"] = _time.time() - _t_start
            return result

        try:
            duration = self._get_audio_duration(audio_path)
            if duration > self.max_audio_duration:
                result = ASRResult(
                    success=False, duration=duration,
                    error=f"音频时长 {duration:.0f}s 超过上限",
                    backend="whisper"
                )
                result.timing["transcribe_seconds"] = _time.time() - _t_start
                return result
        except Exception:
            duration = 0

        try:
            if self._model is None or self._backend_loaded != "whisper":
                print(f"🎙️ 正在加载 Whisper 模型: {self.whisper_model_name}")
                self._model = whisper.load_model(self.whisper_model_name, device=self.device)
                self._backend_loaded = "whisper"

            result = self._model.transcribe(
                str(audio_path),
                language=self.language if self.language != "auto" else None,
                verbose=False,
                word_timestamps=False,
            )

            segments = []
            for seg in result.get("segments", []):
                confidence = seg.get("confidence", seg.get("avg_logprob", 0))
                if isinstance(confidence, float) and confidence < 0:
                    confidence = max(0, min(1, (confidence + 2) / 2))

                s = ASRSegment(
                    start=seg.get("start", 0),
                    end=seg.get("end", 0),
                    text=seg.get("text", "").strip(),
                    confidence=round(confidence, 3),
                )
                if s.confidence >= self.min_confidence and s.text:
                    segments.append(s)

            full_text = " ".join(s.text for s in segments)

            asr_result = ASRResult(
                success=True,
                text=full_text[:10000],
                segments=segments,
                duration=duration,
                model_used=self.whisper_model_name,
                backend="whisper",
            )
            asr_result.timing["transcribe_seconds"] = _time.time() - _t_start
            return asr_result

        except Exception as e:
            result = ASRResult(
                success=False, duration=duration,
                error=str(e), backend="whisper"
            )
            result.timing["transcribe_seconds"] = _time.time() - _t_start
            return result

    # ═══════════════════════════════════════════════════════════════
    # 👥 说话人分离（pyannote.audio，Whisper 降级时使用）
    # FunASR 内置 cam++ 说话人分离，无需额外调用
    # ═══════════════════════════════════════════════════════════════

    def separate_speakers(self, audio_path: Path, segments: list[ASRSegment]) -> list[ASRSegment]:
        """
        说话人分离（仅用于 Whisper 后端，FunASR 已内置）
        """
        if not self.speaker_separation:
            return segments
        if self.backend == "funasr":
            # FunASR 已在 transcribe 时完成说话人分离
            return segments

        Pipeline = _get_pyannote_pipeline()
        if Pipeline is None:
            return segments

        try:
            hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token,
            )
            if self.device != "cpu":
                import torch
                pipeline.to(torch.device(self.device))

            diarization = pipeline(str(audio_path))
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                for seg in segments:
                    if seg.start <= turn.end and seg.end >= turn.start:
                        seg.speaker = speaker
            return segments
        except Exception as e:
            print(f"[WARN] Speaker separation failed (non-critical): {e}")
            return segments

    # ═══════════════════════════════════════════════════════════════
    # Format Output
    # ═══════════════════════════════════════════════════════════════

    def format_result(self, result: ASRResult) -> str:
        """将识别结果格式化为可读文本"""
        if not result.success:
            return f"[语音识别失败: {result.error}]"
        if not result.segments:
            return "[语音识别完成，但无有效片段]"

        lines = [
            f"[ASR] engine={result.backend.upper()} model={result.model_used} duration={result.duration:.0f}s"
        ]

        speakers = set(s.speaker for s in result.segments if s.speaker)
        if speakers:
            lines.append(f"[ASR] {len(speakers)} speakers detected")

        # 按说话人分段
        current_speaker = None
        buffer = []
        for seg in result.segments:
            if seg.speaker and seg.speaker != current_speaker:
                if buffer:
                    lines.append(f"[{current_speaker or 'UP主'}] {' '.join(buffer)}")
                    buffer = []
                current_speaker = seg.speaker
            buffer.append(seg.text)

        if buffer:
            lines.append(f"[{current_speaker or 'UP主'}] {' '.join(buffer)}")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════
    # One-click Pipeline: Video -> Audio -> ASR -> Speaker Sep
    # ═══════════════════════════════════════════════════════════════

    async def process_video(self, video_path: Path, title: str = "") -> ASRResult:
        """完整 ASR 流程：提取音频 → 识别 → 说话人分离（含耗时统计）"""
        import time as _time
        _pipeline_start = _time.time()
        loop = asyncio.get_event_loop()

        # 1. 提取音频
        audio_extract_sec = 0.0
        try:
            audio_path, audio_extract_sec = await loop.run_in_executor(None, self.extract_audio, video_path, None)
        except Exception as e:
            result = ASRResult(success=False, error=f"音频提取失败: {e}")
            result.timing["audio_extract_seconds"] = _time.time() - _pipeline_start
            result.timing["total_pipeline_seconds"] = result.timing["audio_extract_seconds"]
            return result

        if not audio_path:
            result = ASRResult(success=False, error="音频提取结果为空")
            result.timing["audio_extract_seconds"] = audio_extract_sec
            result.timing["total_pipeline_seconds"] = _time.time() - _pipeline_start
            return result

        # 2. 选择引擎执行识别
        if self.backend == "funasr" and self._check_funasr_available():
            result = await loop.run_in_executor(None, self.transcribe_funasr, audio_path)
        else:
            if self.backend == "funasr":
                print("[WARN] FunASR unavailable, falling back to Whisper")
            result = await loop.run_in_executor(None, self.transcribe_whisper, audio_path)

        # 3. 说话人分离（仅 Whisper 需要额外处理）
        if not result.success:
            self._cleanup_audio(audio_path)
            result.timing["audio_extract_seconds"] = audio_extract_sec
            result.timing["total_pipeline_seconds"] = _time.time() - _pipeline_start
            return result

        if self.speaker_separation and result.backend == "whisper" and result.segments:
            result.segments = await loop.run_in_executor(
                None, self.separate_speakers, audio_path, result.segments
            )
            result.text = self.format_result(result)

        # 4. 清理音频
        self._cleanup_audio(audio_path)

        # ── 汇总耗时 ──
        result.timing["audio_extract_seconds"] = round(audio_extract_sec, 2)
        result.timing["total_pipeline_seconds"] = round(_time.time() - _pipeline_start, 2)
        return result

    def _cleanup_audio(self, audio_path: Path):
        """清理音频文件"""
        if not self.keep_audio and audio_path.exists():
            try:
                audio_path.unlink()
            except OSError:
                pass

    @staticmethod
    def timing_summary(result: ASRResult, download_sec: float = 0, download_size_mb: float = 0) -> str:
        """生成ASR全流程耗时汇总字符串。
        
        Args:
            result: ASR结果
            download_sec: 视频下载耗时（秒）
            download_size_mb: 下载文件大小（MB）
        Returns:
            格式化的耗时汇总文本
        """
        t = result.timing
        lines = ["\n⏱️ 【ASR耗时详情】"]
        
        if download_sec > 0:
            lines.append(f"   视频下载: {download_sec:.1f}s ({download_size_mb:.1f}MB)" if download_size_mb > 0 else f"   视频下载: {download_sec:.1f}s")
        
        audio_extract = t.get("audio_extract_seconds", 0)
        if audio_extract > 0:
            lines.append(f"   音频提取: {audio_extract:.1f}s")
        
        transcribe = t.get("transcribe_seconds", 0)
        if transcribe > 0:
            lines.append(f"   ASR识别:  {transcribe:.1f}s (引擎: {result.backend.upper()})")
        
        pipeline = t.get("total_pipeline_seconds", 0)
        if pipeline > 0:
            lines.append(f"   ASR流水线: {pipeline:.1f}s (音频→识别→说话人)")
        
        total = t.get("total_elapsed_seconds", 0)
        if total > 0:
            lines.append(f"   全流程总计: {total:.1f}s")
        elif pipeline > 0:
            total = pipeline + download_sec
            if download_sec > 0:
                lines.append(f"   全流程总计: {total:.1f}s")
        
        # 效率对比
        if result.duration > 0 and transcribe > 0:
            speed = result.duration / transcribe
            lines.append(f"   识别效率: {speed:.1f}x (音频{result.duration:.0f}s / 识别{transcribe:.1f}s)")
        
        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════════
    # ⏱️ 辅助：获取音频时长
    # ═══════════════════════════════════════════════════════════════

    def _get_audio_duration(self, audio_path: Path) -> float:
        # 优先使用 _find_ffmpeg 找到的路径推导 ffprobe
        ffmpeg = self._find_ffmpeg()
        ffprobe = None
        if ffmpeg and ffmpeg != "ffmpeg":
            ff_dir = os.path.dirname(os.path.abspath(ffmpeg))
            candidates = [
                os.path.join(ff_dir, "ffprobe.exe"),
                os.path.join(ff_dir, "ffprobe"),
            ]
            for c in candidates:
                if os.path.isfile(c):
                    ffprobe = c
                    break
        if not ffprobe:
            ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return 0
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
            dur = float(result.stdout.strip())
            if dur > 0:
                return dur
        except (ValueError, subprocess.TimeoutExpired):
            pass
        return 0


# ═══════════════════════════════════════════════════════════════
# Global Singleton
# ═══════════════════════════════════════════════════════════════

_asr_engine: ASREngine | None = None


def get_asr_engine(config: dict[str, Any] | None = None) -> ASREngine:
    """获取 ASR 引擎单例"""
    global _asr_engine
    if _asr_engine is None:
        _asr_engine = ASREngine(config)
    return _asr_engine
