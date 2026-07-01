"""
BrainVideoMixin — 视频理解（字幕、ASR、视觉帧）
包含: understand_video_for_decision, _understand_super_smart,
      _extract_and_analyze_frames, _ai_decide_frame_count,
      _understand_with_vision_frames, _is_music_only_subtitle,
      _ai_judge_subtitle_sufficiency, _ai_judge_has_human_voice,
      _ai_verify_subtitle_content, _review_knowledge_periodically,
      _download_video_for_asr
"""
import os
import re
import json
import time
import shutil
import asyncio
import random
from datetime import datetime
from pathlib import Path as _Path

from brain._mixin_imports import *


class BrainVideoMixin:
    """视频理解方法"""

    async def understand_video_for_decision(self, bvid, title=None, force_mode=None):
        """[VIDEO] 超级智能视频理解：字幕优先 → AI判断是否需要下载 → 必要时ASR → 理解后删除
        force_mode: None=默认智能流程 | 'subtitle_only'|'asr_only'|'vision_only'|
                    'subtitle+asr'|'subtitle+vision'|'asr+vision'|'all'
        """
        return await self._understand_super_smart(bvid, title, force_mode=force_mode)

    async def _understand_super_smart(self, bvid, title=None, force_mode=None):
        """
        [BRAIN] 超级智能理解链（v3.0.0）：
        1. 先抓字幕
        2. 字幕有内容 → AI判断字幕是否足够覆盖视频核心
        3. 字幕足够 → 直接用字幕，不下载视频 [OK]
        4. 字幕不足/无字幕 → 下载视频 → 同时ASR+抽关键帧 → 合并分析
           - 不再依赖AI"人声判断"来决定是否下载，统一下载
           - ASR结果为空 → 纯视觉帧理解
           - ASR有结果 → 合并ASR+视觉帧 → 更全面的理解
        force_mode: None=默认智能流程 | 'subtitle_only'|'asr_only'|'vision_only'|
                    'subtitle+asr'|'subtitle+vision'|'asr+vision'|'all'
        """
        # ── 解析 force_mode 标志 ──
        do_subtitle = True
        do_asr = True
        do_vision = True
        skip_subtitle_check = False  # 跳过AI判断字幕是否足够，强制下载
        if force_mode:
            fm = force_mode.lower()
            if fm == "subtitle_only":
                do_asr = False; do_vision = False
            elif fm == "asr_only":
                do_subtitle = False; do_vision = False; skip_subtitle_check = True
            elif fm == "vision_only":
                do_subtitle = False; do_asr = False; skip_subtitle_check = True
            elif fm == "subtitle+asr":
                do_vision = False; skip_subtitle_check = True
            elif fm == "subtitle+vision":
                do_asr = False; skip_subtitle_check = True
            elif fm == "asr+vision":
                do_subtitle = False; skip_subtitle_check = True
            # "all" or None: 默认智能流程

        # ═══ 第一步：抓字幕+简介 ═══
        subtitle_text = ""
        has_subtitle = False
        content = ""
        video_desc = ""
        if do_subtitle:
            ok, content, video_desc, subtitle_ai_verified = await fetch_bilibili_subtitles(
                bvid, self.cookies, title=title,
                ai_verify_func=self._ai_verify_subtitle_content if (AI_SUBTITLE_VERIFY_ENABLED and SUBTITLE_STRICT_CHECK) else None
            )
            self._last_video_desc = video_desc  # 存下来，供 learn_from_video 使用
            subtitle_text = content if ok else ""
            has_subtitle = ok and len(subtitle_text.strip()) > 30
        else:
            self._last_video_desc = video_desc

        # ═══ 第二步：AI判断字幕是否足够 ═══
        video_tags = getattr(self, "_current_video_tags", None) or []
        video_category = getattr(self, "_current_video_category", "") or ""
        video_duration = getattr(self, "_current_video_duration", 0) or 0
        cover_desc = getattr(self, "_current_video_cover_desc", "") or ""

        # [force_mode] subtitle_only → 拿完字幕直接返回
        if force_mode == "subtitle_only":
            if has_subtitle:
                log(f"[OK] 仅字幕模式，字幕获取成功 ({len(subtitle_text)}字)", "BRAIN")
                return True, subtitle_text
            else:
                log(f"[WARN] 仅字幕模式，但无可用字幕: {content[:80] if content else 'N/A'}", "BRAIN")
                return False, content or "[无可用字幕]"

        if has_subtitle and not skip_subtitle_check:
            # [FIX] 低置信度字幕：单轨弱关联→跳过AI二次判断直接使用
            # 所有轨校验均失败→字幕完全不可信，必须回退到ASR+视觉
            is_low_confidence = subtitle_text.startswith("[低置信度字幕") or subtitle_text.startswith("[极低置信度字幕")
            if is_low_confidence:
                is_all_failed = "轮重试均失败" in subtitle_text or "所有轨校验均失败" in subtitle_text
                if is_all_failed:
                    log(f"[WARN] 所有字幕轨校验均失败，字幕不可信，回退到ASR+视觉理解", "BRAIN")
                    # 不return，继续往下尝试ASR/视觉帧
                else:
                    log(f"[OK] 低置信度字幕(有关键词弱关联)，跳过AI二次判断，直接使用供AI分析", "BRAIN")
                    return True, subtitle_text
            
            # AI评估：字幕是否足以理解视频
            subtitle_sufficient, sufficiency_reason = await self._ai_judge_subtitle_sufficiency(
                title=title or "",
                subtitle=subtitle_text[:2000],
                tags=video_tags,
                category=video_category,
                duration=video_duration,
                cover_desc=cover_desc,
                video_desc=video_desc
            )
            if subtitle_sufficient:
                log(f"[OK] AI判断字幕充分: {sufficiency_reason} | 无需下载视频", "BRAIN")
                return True, subtitle_text
            else:
                # [FIX] 快速预检：如果字幕主要是音乐符号/纯噪声，直接兜底，不浪费下载视频
                if self._is_music_only_subtitle(subtitle_text):
                    log(f"[WARN] 字幕以音乐标记为主，跳过视频下载，直接使用字幕兜底", "BRAIN")
                    return True, subtitle_text
                log(f"[WARN] AI判断字幕不足: {sufficiency_reason} | 将下载视频进行ASR+视觉联合理解...", "BRAIN")
                # 字幕不够 → 下载视频，同时ASR+视觉帧
        else:
            log(f"📭 无可用字幕: {content[:80] if content else 'N/A'}", "BRAIN")

        # ═══ 第三步：force_mode + ASR总开关检查 ═══
        if not do_asr or not ASR_ENABLED:
            reason = "force_mode指定跳过" if not do_asr else "ASR未开启"
            log(f"⚙️ {reason}，跳过语音识别", "INFO")
            if do_vision:
                # [VISION] 尝试画面理解兜底
                vis_fallback = await self._understand_with_vision_frames(bvid, title, subtitle_text)
                if vis_fallback:
                    return True, vis_fallback
            if has_subtitle:
                return True, subtitle_text
            return False, content or f"[{reason}]"

        # ═══ 第四步：规则快速过滤（纯音乐/游戏集锦等确定无人声的跳过ASR） ═══
        from xingye_bot.asr_engine import ASREngine
        skip, skip_reason = ASREngine.should_skip_asr(
            title=title or "",
            tags=video_tags,
            category=video_category,
            cover_desc=cover_desc,
            duration=video_duration,
        )
        if skip:
            log(f"🤖 规则预判跳过ASR: {skip_reason}", "BRAIN")
            if has_subtitle:
                is_all_failed = "轮重试均失败" in subtitle_text or "所有轨校验均失败" in subtitle_text
                if not is_all_failed:
                    return True, subtitle_text
                log(f"[WARN] 规则跳过ASR但字幕所有轨校验失败或AI判定不相关，尝试视觉帧理解", "BRAIN")
            # 规则明确跳过（纯音乐等）→ 视觉帧理解兜底
            if do_vision:
                vis_fallback = await self._understand_with_vision_frames(bvid, title, subtitle_text)
                if vis_fallback:
                    return True, vis_fallback
            return False, f"{content} | [ASR跳过: {skip_reason}]"

        # ═══ 第五步：下载视频 → 同时ASR + 抽关键帧 → 合并分析 ═══
        # 一次下载获得语音+画面双重信息，更准确高效
        mode_desc = "ASR" if do_asr else ""
        if do_vision:
            mode_desc += "+VISION" if mode_desc else "VISION"
        log(f"[{mode_desc}] 下载视频进行理解: 《{title}》", "CONFIG")
        video_path = None
        vision_result = None
        asr_text = ""
        
        try:
            from xingye_bot.asr_engine import get_asr_engine, ASREngine
            asr_cfg = config.get("asr", {})
            asr = get_asr_engine(asr_cfg)

            # 下载视频（只下载一次）
            download_result = await self._download_video_for_asr(bvid)
            video_path_str, download_sec, download_size_mb = download_result
            if not video_path_str:
                log(f"[{mode_desc}] 视频下载失败(耗时{download_sec:.1f}s)", "WARN")
                if has_subtitle:
                    return True, subtitle_text
                return False, f"{content} | [下载失败]"
            
            video_path = _Path(video_path_str)
            
            # [SMART_FRAME] AI智能决定是否抽帧 + 抽多少帧
            should_extract = False; smart_frame_count = 0; frame_reason = ""
            if do_vision:
                should_extract, smart_frame_count, frame_reason = await self._ai_decide_frame_count(
                    title=title or "",
                    duration=video_duration,
                    tags=video_tags,
                    category=video_category,
                    subtitle_text=subtitle_text
                )
                if not should_extract:
                    log(f"[SMART_FRAME] AI决定不抽帧: {frame_reason}", "EYE")
                else:
                    log(f"[SMART_FRAME] AI决定抽{smart_frame_count}帧: {frame_reason}", "EYE")
            
            # 记录全流程开始时间
            import time as _full_time
            _full_start = _full_time.time()
            
            # --- 并行：ASR语音识别 + 视觉帧抽取 ---
            asr_task = None
            if do_asr and asr.is_available():
                if not asr.has_ffmpeg():
                    log(f"[WARN] ffmpeg 未在PATH找到，将用 torchaudio 兜底提取音频", "DEBUG")
                asr_task = asyncio.create_task(asr.process_video(video_path, title=title or ""))
            
            # 同时抽关键帧（复用已下载的视频，不再单独下载）
            vision_task = None
            if do_vision and VISION_FRAMES_ENABLED and should_extract:
                vision_task = asyncio.create_task(self._extract_and_analyze_frames(
                    video_path, bvid, title, subtitle_text, frame_count=smart_frame_count
                ))
            
            # 等待两个任务完成
            asr_result = None
            if asr_task:
                try:
                    asr_result = await asr_task
                    if asr_result.success:
                        asr_text = asr.format_result(asr_result)
                        speaker_count = len(set(s.speaker for s in asr_result.segments if s.speaker))
                        if speaker_count > 0:
                            log(f"[ASR] ASR完成！识别 {len(asr_result.segments)} 片段，{speaker_count} 位说话人", "SUCCESS")
                        else:
                            log(f"[ASR] ASR完成！识别 {len(asr_result.segments)} 片段", "SUCCESS")
                        # ── ASR-标题匹配校验：防止ASR张冠李戴（仅在"字幕严格校验"开启时）──
                        asr_plain = asr_result.text or asr_text or ""
                        if SUBTITLE_STRICT_CHECK and asr_plain and title:
                            _, mismatch = _check_subtitle_mismatch(title, asr_plain)
                            if mismatch:
                                log(f"[ASR] ⚠️ ASR内容可能与视频不匹配: {mismatch} | ASR开头: {asr_plain[:60]}...", "WARN")
                                # 标记但继续使用（由AI自行判断）
                                asr_text = f"[⚠️ ASR内容可能与视频标题不匹配] {asr_text}"
                    else:
                        log(f"[ASR] ASR识别失败: {asr_result.error}", "WARN")
                except Exception as asr_e:
                    log(f"[ASR] ASR异常: {asr_e}", "WARN")
            
            if vision_task:
                try:
                    vision_result = await vision_task
                    if vision_result:
                        log(f"[EYE] 视觉帧理解完成 ({len(vision_result)}字)", "SUCCESS")
                except Exception as vis_e:
                    log(f"[EYE] 视觉帧理解异常: {vis_e}", "WARN")
            
            # ── 耗时汇总 ──
            if asr_result and asr_result.success:
                # 汇总全流程耗时到 ASR result
                asr_result.timing["total_elapsed_seconds"] = round(_full_time.time() - _full_start, 2)
                timing_summary = ASREngine.timing_summary(asr_result, download_sec=download_sec, download_size_mb=download_size_mb)
                print(timing_summary)
            
            # --- 合并结果 ---
            # 构建最终理解文本
            parts = []
            if asr_text:
                parts.append(f"【ASR语音识别】\n{asr_text}")
            if vision_result:
                parts.append(f"【视觉画面理解】\n{vision_result}")
            if has_subtitle:
                parts.insert(0, f"【CC字幕（不完整）】\n{subtitle_text[:2000]}")
            
            if parts:
                combined = "\n\n---\n\n".join(parts)
                return True, combined
            elif has_subtitle:
                return True, subtitle_text
            else:
                # 都失败了，返回基本信息
                basic = f"【理解失败】标题: {title or ''}\n分区: {video_category}\n时长: {video_duration}s"
                return False, basic
                
        except ImportError as e:
            log(f"ASR依赖缺失: {e}", "WARN")
            if has_subtitle:
                return True, subtitle_text
            vis_fallback = await self._understand_with_vision_frames(bvid, title, subtitle_text)
            if vis_fallback:
                return True, vis_fallback
            return False, f"{content} | [ASR依赖缺失: {e}]"
        except Exception as e:
            log(f"联合理解流程异常: {e}", "WARN")
            if has_subtitle:
                return True, subtitle_text
            vis_fallback = await self._understand_with_vision_frames(bvid, title, subtitle_text)
            if vis_fallback:
                return True, vis_fallback
            return False, f"{content} | [异常: {e}]"
        finally:
            # 🧹 清理：删除视频文件
            if video_path and video_path.exists():
                try:
                    video_path.unlink()
                    log(f"🗑️ 已删除下载的视频文件: {video_path.name}", "DEBUG")
                except Exception as del_e:
                    log(f"删除视频文件失败: {del_e}", "DEBUG")

    async def _extract_and_analyze_frames(self, video_path, bvid, title=None, subtitle_text="", frame_count=None):
        """[VISION v2] 从已下载的视频文件抽帧→视觉AI分析→返回画面描述。
        与 _understand_with_vision_frames 的区别：不重新下载视频，直接使用已有文件。
        frame_count: AI智能决定的抽帧数量，None则使用默认VISION_FRAME_COUNT"""
        if not VISION_FRAMES_ENABLED:
            return None
        # 使用AI决定的帧数，否则用默认值
        actual_frame_count = frame_count if frame_count and frame_count > 0 else VISION_FRAME_COUNT
        frames = []
        frames_dir = None
        try:
            video_path = _Path(str(video_path))
            if not video_path.exists():
                return None
            
            import subprocess as _sp
            frames_dir = video_path.parent / "vision_frames"
            frames_dir.mkdir(exist_ok=True)
            for old in frames_dir.glob("frame_*.jpg"):
                old.unlink()
            
            # 获取时长
            ffprobe = find_ffprobe()
            ffmpeg = find_ffmpeg()
            duration = 0
            if ffprobe:
                try:
                    dur_out = _sp.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                        capture_output=True, text=True, timeout=15)
                    duration = int(float(dur_out.stdout.strip())) if dur_out.stdout.strip() else 0
                except Exception:
                    duration = 0
            if not ffmpeg:
                return None
            
            # [SMART_FRAME] 使用AI决定的帧数
            interval = max(1, duration // max(1, actual_frame_count)) if duration else 5
            pattern = str(frames_dir / "frame_%03d.jpg")
            _sp.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(video_path), "-vf", f"fps=1/{interval},scale=640:-1",
                "-frames:v", str(actual_frame_count), pattern],
                timeout=120, capture_output=True)
            frames = sorted(frames_dir.glob("frame_*.jpg"))
            if not frames:
                return None
            
            # [SMART_FRAME] 帧数较多时智能抽样：均匀选取不超过max_frames_for_ai张发送给视觉AI
            # 避免一次发送太多图片导致API超限/成本过高
            max_frames_for_ai = min(actual_frame_count, 60)
            if len(frames) > max_frames_for_ai:
                step = len(frames) / max_frames_for_ai
                sampled = [frames[int(i * step)] for i in range(max_frames_for_ai)]
                log(f"[EYE] 抽取 {len(frames)} 帧，智能抽样 {len(sampled)} 帧发送视觉AI分析...", "EYE")
                frames_to_analyze = sampled
            else:
                log(f"[EYE] 抽取 {len(frames)} 帧，发送视觉AI分析...", "EYE")
                frames_to_analyze = frames
            
            # 构建多模态请求
            content_blocks = [{
                "type": "text",
                "text": (
                    f"你正在通过关键帧画面理解一个B站视频。\n"
                    f"标题: {title or '未知'}\n"
                    f"以下是均匀采样的{len(frames_to_analyze)}张关键帧截图（从总共{len(frames)}帧中选取）。\n"
                    f"{'【参考字幕】: ' + subtitle_text[:1500] if subtitle_text else ''}\n"
                    "请输出: 视频主题、核心内容、画面风格、知识密度评估。用中文简述。"
                )
            }]
            import base64 as _b64_vis
            for frame in frames_to_analyze:
                data_url = "data:image/jpeg;base64," + _b64_vis.b64encode(frame.read_bytes()).decode("ascii")
                content_blocks.append({"type": "image_url", "image_url": {"url": data_url}})
            
            resp = await self._call_ai_with_retry(
                model=MODEL_VISION,
                messages=[{
                    "role": "system",
                    "content": "你是视频内容分析助手，通过关键帧截图理解视频。请仔细看每张图，综合判断内容。"
                }, {
                    "role": "user",
                    "content": content_blocks
                }],
                request_timeout=180
            )
            result = resp.choices[0].message.content.strip()
            return result
        except Exception as e:
            log(f"[EYE] 视觉帧分析异常: {e}", "WARN")
            return None
        finally:
            # 清理帧文件和目录（但不删视频，由调用方统一清理）
            try:
                if frames and frames_dir and frames_dir.exists():
                    import shutil as _sh
                    _sh.rmtree(str(frames_dir), ignore_errors=True)
            except Exception as e:
                log(f'非预期异常: {e}', 'WARN')

    async def _ai_decide_frame_count(self, title="", duration=0, tags=None, category="", subtitle_text=""):
        """[SMART_FRAME] AI根据视频信息智能决定：是否抽帧 + 抽多少帧(10-300)。
        返回 (should_extract: bool, frame_count: int, reason: str)"""
        if not SMART_FRAME_ENABLED:
            # 未开启智能抽帧，使用固定数量
            return True, VISION_FRAME_COUNT, "智能抽帧关闭，使用固定数量"
        
        # 如果是AI降级状态，用规则判断
        if self._is_ai_degraded():
            # 规则：短视频(<60s)少抽，中视频(60-600s)中等，长视频(>600s)多抽
            if duration <= 60:
                count = min(SMART_FRAME_MAX, max(SMART_FRAME_MIN, 10))
            elif duration <= 300:
                count = min(SMART_FRAME_MAX, max(SMART_FRAME_MIN, duration // 10))
            elif duration <= 900:
                count = min(SMART_FRAME_MAX, max(SMART_FRAME_MIN, duration // 8))
            else:
                count = min(SMART_FRAME_MAX, max(SMART_FRAME_MIN, duration // 6))
            return True, count, f"AI降级，按规则(duration={duration}s)决定抽{count}帧"
        
        tags_str = ", ".join(tags[:10]) if tags else "无"
        prompt = (
            "你是视频关键帧抽取策略专家。根据视频元信息判断：是否需要抽取关键帧？如果需要，抽多少帧最合适？\n"
            "抽帧目的：用关键帧截图让视觉AI理解视频画面内容。\n"
            "判断原则：\n"
            "- 纯文字/PPT/录屏类：少量帧(10-30)即可，画面变化小\n"
            "- 教程/知识讲解：中等帧数(20-60)，需要看关键步骤\n"
            "- Vlog/生活/旅游：较多帧(40-100)，场景切换多\n"
            "- 影视/动画/游戏实况：多帧(60-150)，画面信息密度高\n"
            "- 混剪/MAD/快节奏：很多帧(100-200)，画面切换极快\n"
            "- 评测/开箱/产品展示：中多帧(40-80)，需要看细节\n"
            "- 新闻/访谈/纪录片：中等帧(30-80)，人物+场景结合\n"
            "- 纯音乐/MV/演唱会：不抽帧(0)，画面意义不大\n"
            "- 音频节目/播客/ASMR：不抽帧(0)，画面无信息量\n"
            f"视频标题: {title}\n"
            f"视频时长: {duration}秒\n"
            f"分区: {category}\n"
            f"标签: {tags_str}\n"
            f"字幕预览: {subtitle_text[:300] if subtitle_text else '无'}\n\n"
            "只返回JSON，不要其他文字:\n"
            '{"should_extract": true/false, "frame_count": 整数(10-300), "reason": "简短理由(15字内)"}'
        )
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[{
                    "role": "system",
                    "content": "你是视频分析策略专家。只返回JSON。"
                }, {
                    "role": "user",
                    "content": prompt
                }],
                request_timeout=30
            )
            text = resp.choices[0].message.content.strip()
            # 提取JSON
            import json as _json_sf
            json_match = re.search(r'\{[^}]+\}', text)
            if json_match:
                data = _json_sf.loads(json_match.group())
                should_extract = data.get("should_extract", True)
                frame_count = int(data.get("frame_count", VISION_FRAME_COUNT))
                reason = data.get("reason", "AI判断")
                # 限制范围
                frame_count = max(SMART_FRAME_MIN, min(SMART_FRAME_MAX, frame_count))
                if not should_extract:
                    return False, 0, reason
                return True, frame_count, reason
            else:
                return True, VISION_FRAME_COUNT, "AI返回格式异常，使用默认值"
        except Exception as e:
            log(f"[SMART_FRAME] AI决策异常: {e}", "WARN")
            return True, VISION_FRAME_COUNT, f"异常回退: {e}"

    async def _understand_with_vision_frames(self, bvid, title=None, subtitle_text=""):
        """[VISION] 下载视频→抽帧→视觉AI理解→返回画面描述（ASR/字幕都不可用时的兜底方案）"""
        if not VISION_FRAMES_ENABLED:
            return None
        log(f"[EYE] 尝试视觉帧理解: 《{title or bvid}》", "EYE")
        video_path = None
        frames = []
        try:
            # 1. 下载视频
            dl_result = await self._download_video_for_asr(bvid)
            video_path_str, _, _ = dl_result  # 解包新返回格式
            if not video_path_str:
                log(f"[EYE] 视觉理解: 视频下载失败", "WARN")
                return None
            video_path = _Path(video_path_str)
            # [SMART_FRAME] AI智能决定是否抽帧 + 抽多少帧
            video_tags = getattr(self, "_current_video_tags", None) or []
            video_category = getattr(self, "_current_video_category", "") or ""
            video_duration = getattr(self, "_current_video_duration", 0) or 0
            should_extract, smart_fc, fc_reason = await self._ai_decide_frame_count(
                title=title or "",
                duration=video_duration,
                tags=video_tags,
                category=video_category,
                subtitle_text=subtitle_text or ""
            )
            if not should_extract:
                log(f"[SMART_FRAME] AI决定不抽帧: {fc_reason}", "EYE")
                return None
            log(f"[SMART_FRAME] AI决定抽{smart_fc}帧: {fc_reason}", "EYE")
            actual_frame_count = smart_fc if smart_fc > 0 else VISION_FRAME_COUNT
            
            # 2. 抽帧 (直接用 ffmpeg，避免引入 VideoUnderstanding 的复杂依赖)
            import subprocess as _sp
            frames_dir = video_path.parent / "vision_frames"
            frames_dir.mkdir(exist_ok=True)
            for old in frames_dir.glob("frame_*.jpg"):
                old.unlink()
            # 用 ffprobe 获取时长
            ffprobe = find_ffprobe()
            ffmpeg = find_ffmpeg()
            duration = 0
            if ffprobe:
                try:
                    dur_out = _sp.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                        capture_output=True, text=True, timeout=15)
                    duration = int(float(dur_out.stdout.strip())) if dur_out.stdout.strip() else 0
                except Exception:
                    duration = 0
            if not ffmpeg:
                log(f"[EYE] 视觉理解: ffmpeg 未安装，无法抽帧", "WARN")
                return None
            interval = max(1, duration // max(1, actual_frame_count)) if duration else 5
            pattern = str(frames_dir / "frame_%03d.jpg")
            _sp.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(video_path), "-vf", f"fps=1/{interval},scale=640:-1",
                "-frames:v", str(actual_frame_count), pattern],
                timeout=120, capture_output=True)
            frames = sorted(frames_dir.glob("frame_*.jpg"))
            if not frames:
                log(f"[EYE] 视觉理解: 抽帧失败 (无输出文件)", "WARN")
                return None
            
            # [SMART_FRAME] 智能抽样：帧太多时均匀选取不超过max_frames_for_ai张
            max_frames_for_ai = min(actual_frame_count, 60)
            if len(frames) > max_frames_for_ai:
                step = len(frames) / max_frames_for_ai
                frames_to_analyze = [frames[int(i * step)] for i in range(max_frames_for_ai)]
                log(f"[EYE] 抽取 {len(frames)} 帧，智能抽样 {len(frames_to_analyze)} 帧发送视觉AI分析...", "EYE")
            else:
                log(f"[EYE] 抽取 {len(frames)} 帧，发送视觉AI分析...", "EYE")
                frames_to_analyze = frames
            
            # 3. 构建多模态请求
            content_blocks = [{
                "type": "text",
                "text": (
                    f"你正在通过关键帧画面理解一个B站视频。\n"
                    f"标题: {title or '未知'}\n"
                    f"以下是均匀采样的{len(frames_to_analyze)}张关键帧截图（从总共{len(frames)}帧中选取）。\n"
                    f"{'【参考字幕】: ' + subtitle_text[:1500] if subtitle_text else ''}\n"
                    "请输出: 视频主题、核心内容、画面风格、知识密度评估。用中文简述。"
                )
            }]
            import base64 as _b64_vis
            for frame in frames_to_analyze:
                data_url = "data:image/jpeg;base64," + _b64_vis.b64encode(frame.read_bytes()).decode("ascii")
                content_blocks.append({"type": "image_url", "image_url": {"url": data_url}})
            # 4. 调用视觉模型
            resp = await self._call_ai_with_retry(
                model=MODEL_VISION,
                messages=[{
                    "role": "system",
                    "content": "你是视频内容分析助手，通过关键帧截图理解视频。请仔细看每张图，综合判断内容。"
                }, {
                    "role": "user",
                    "content": content_blocks
                }],
                request_timeout=180
            )
            result = resp.choices[0].message.content.strip()
            log(f"[EYE] 视觉理解完成 ({len(result)}字): {result[:100]}...", "SUCCESS")
            return f"【视觉画面理解】\n{result}"
        except Exception as e:
            log(f"[EYE] 视觉理解异常: {e}", "WARN")
            return None
        finally:
            # 清理临时文件: 删除视频 + 帧文件 + 帧目录
            try:
                if video_path and video_path.exists():
                    video_path.unlink()
                if frames:
                    # 删除帧文件和帧目录
                    frames_dir = frames[0].parent if frames else None
                    if frames_dir and frames_dir.exists():
                        import shutil as _sh
                        _sh.rmtree(str(frames_dir), ignore_errors=True)
            except Exception as e:
                log(f'非预期异常: {e}', 'WARN')

    @staticmethod
    def _is_music_only_subtitle(text: str) -> bool:
        """快速检测字幕是否几乎全是音乐标记（♪ ♪ 音乐 ♪ 等），避免浪费下载视频。
        当字幕中音乐/无意义标记占比超过70%时返回True。"""
        if not text or len(text) < 20:
            return False
        # 统计音乐/空白标记的字符数
        music_pattern = re.compile(r'[♪♫♩♬🎵🎶🎼🎹🎸🎺🎻🥁🎤🎧]')
        music_chars = len(music_pattern.findall(text))
        # 移除所有音乐标记后的有效文本长度
        clean = music_pattern.sub('', text)
        # 再去掉纯空白
        meaningful = re.sub(r'\s+', '', clean)
        total = len(text)
        # 如果音乐符号占比超过30%，或者有效内容不足30%
        if music_chars / max(total, 1) > 0.3:
            return True
        if len(meaningful) / max(total, 1) < 0.3:
            return True
        # 检测连续的音乐标记+短词模式：如 "♪ 音乐 ♪ ♪ 音乐 ♪"
        clean_words = [w for w in re.split(r'\s+', clean) if len(w) > 1]
        if len(clean_words) <= 3 and music_chars > 10:
            return True
        return False

    async def _ai_judge_subtitle_sufficiency(self, title, subtitle, tags, category, duration, cover_desc, video_desc=""):
        """
        🤖 AI判断：现有字幕是否足以理解视频核心内容？
        同时检测字幕是否与标题/简介匹配（防止B站API返回错位字幕）。
        返回 (是否足够, 理由)
        """
        if self._is_ai_degraded():
            # AI降级：字幕超过200字就认为足够
            return len(subtitle) > 200, "AI降级，按长度判断"

        desc_line = f"视频简介: {video_desc[:300]}\n" if video_desc else ""
        prompt = (
            "你是视频内容评估专家。判断一段视频的字幕是否足以理解其核心内容。\n"
            "如果视频主要是画面演示/操作过程，字幕少也足够；如果是知识讲解/访谈/教程，需要字幕覆盖核心观点。\n"
            f"标题: {title}\n分区: {category}\n时长: {duration}s\n标签: {', '.join(tags[:8])}\n封面描述: {cover_desc}\n{desc_line}"
            f"字幕内容(前2000字):\n{subtitle}\n\n"
            "只返回JSON: {\"sufficient\": true/false, \"reason\": \"简短理由(10字内)\", \"video_type\": \"讲解/演示/访谈/教程/娱乐/操作/评测/其他\"}"
        )
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[{"role": "user", "content": prompt}],
                request_timeout=30
            )
            raw = resp.choices[0].message.content
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end >= start:
                data = json.loads(raw[start:end+1])
                return data.get("sufficient", True), data.get("reason", "AI判断完成")
        except Exception as e:
            log(f"字幕充分性AI判断失败: {e}", "WARN")
        # 默认：字幕超过150字就认为足够
        return len(subtitle) > 150, "默认规则(>150字)"

    async def _ai_judge_has_human_voice(self, title, subtitle, tags, category, duration, cover_desc):
        """
        🎤 AI深度判断：视频里肯定有人声讲话吗？
        返回 (是否有人声, 理由)
        """
        if self._is_ai_degraded():
            # AI降级：用简单规则判断
            voice_keywords = ["讲解", "说", "聊", "访谈", "教程", "播客", "吐槽", "测评", "开箱", "vlog", "脱口秀", "演讲", "辩论", "教学", "课程", "科普", "评测", "review", "talk", "讨论", "分享"]
            no_voice_keywords = ["纯音乐", "BGM", "集锦", "highlight", "速通", "speedrun", "ASMR", "助眠", "白噪音", "延时摄影", "time-lapse", "风景", "混剪", "mad"]
            text = f"{title} {' '.join(tags)} {category} {cover_desc}".lower()
            if any(kw in text for kw in voice_keywords):
                return True, "AI降级-关键词命中"
            if any(kw in text for kw in no_voice_keywords):
                return False, "AI降级-无人声关键词"
            return False, "AI降级-默认跳过"

        prompt = (
            "你是视频内容分析师。判断一个视频是否「肯定包含人声讲话/对话/解说」。\n"
            "需要非常确定有人说话才返回true。纯BGM+画面、纯操作演示无解说、纯风景/延时摄影→false。\n"
            f"标题: {title}\n分区: {category}\n时长: {duration}s\n标签: {', '.join(tags[:8])}\n封面描述: {cover_desc}\n"
            f"已有字幕片段(前1500字):\n{subtitle or '(无字幕)'}\n\n"
            "只返回JSON: {\"has_voice\": true/false, \"confidence\": 0-10, \"reason\": \"简短理由(15字内)\"}"
        )
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[{"role": "user", "content": prompt}],
                request_timeout=30
            )
            raw = resp.choices[0].message.content
            if not raw:
                return False, "AI返回空内容"
            # [FIX] 清除非法控制字符（AI偶尔在JSON中插入换行/退格等）
            import re as _re
            raw = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
            # [FIX] 多策略JSON提取：先尝试最后一个}，失败则用第一个匹配的{}对
            start = raw.find("{")
            if start >= 0:
                # 尝试找嵌套匹配的}（从第一个{开始计数）
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
                    try:
                        data = json.loads(raw[start:match_end+1])
                    except json.JSONDecodeError:
                        # 兜底：用rfind
                        end = raw.rfind("}")
                        if end >= start:
                            data = json.loads(raw[start:end+1])
                        else:
                            raise
                else:
                    end = raw.rfind("}")
                    if end >= start:
                        data = json.loads(raw[start:end+1])
                    else:
                        raise ValueError("无法提取JSON")
                confidence = data.get("confidence", 5)
                has_voice = data.get("has_voice", False) and confidence >= 4
                return has_voice, data.get("reason", "AI判断完成")
            else:
                return False, "AI返回无JSON"
        except Exception as e:
            log(f"人声AI判断失败: {e}", "WARN")
        # 默认：不确定就不下载
        return False, "AI判断异常-默认跳过"

    async def _ai_verify_subtitle_content(self, title, subtitle_text, video_desc=""):
        """
        🤖 AI语义验证：字幕/语音内容是否与视频标题真正匹配？
        
        与 _check_subtitle_mismatch (纯关键词重叠) 不同，这里用AI做深度语义理解：
        - 访谈类视频：标题可能是描述性短语(如"对XX的4小时深度访谈")，
          字幕开头常是主持人开场白，关键词法会误判为不匹配。
        - AI能理解上下文：即使关键词不重叠，也能判断内容是否与标题主题一致。
        
        返回 (is_match: bool, confidence: float 0-1, reason: str)
        """
        if self._is_ai_degraded():
            # AI降级：用关键词法兜底
            overlap, mismatch = _check_subtitle_mismatch(title, subtitle_text)
            if mismatch:
                return True, 0.3, "AI降级-关键词法放行"
            return overlap >= 0.15, max(overlap, 0.3) if overlap else 0.3, f"AI降级-关键词重叠{overlap:.2f}"
        
        sub_sample = subtitle_text[:2500]
        desc_line = f"视频简介: {video_desc[:300]}\n" if video_desc else ""
        prompt = (
            "你是视频内容审核专家。判断以下「字幕/语音内容」是否与「视频标题」语义匹配。\n\n"
            "重要规则：\n"
            "1. 访谈/播客类视频：标题常为描述性总结(如包含人名/话题)，字幕开头可能是主持人开场白、\n"
            "   音乐前奏、闲聊寒暄。请判断**整体内容主题**是否与标题一致，而非仅看前几句。\n"
            "2. 教程/教学类视频：标题是课程名，字幕可能是\"大家好今天讲XX\"，这也算匹配。\n"
            "3. 娱乐/vlog类：标题可能是梗或比喻，字幕内容只要在讨论同一件事即算匹配。\n"
            "4. 明显不匹配：标题说\"Python教程\"但字幕在讲\"美食制作\"、标题说\"数学课\"但字幕是游戏解说。\n\n"
            f"视频标题: {title}\n{desc_line}"
            f"字幕/语音内容(前2500字):\n{sub_sample}\n\n"
            "只返回JSON: {\"match\": true/false, \"confidence\": 0.0-1.0, \"reason\": \"简短理由(15字内)\", "
            "\"content_summary\": \"内容实际在讲什么(10字内)\"}"
        )
        try:
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[{"role": "user", "content": prompt}],
                request_timeout=25
            )
            raw = resp.choices[0].message.content
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end >= start:
                data = json.loads(raw[start:end+1])
                is_match = data.get("match", True)
                confidence = float(data.get("confidence", 0.5))
                reason = data.get("reason", "AI判断完成")
                content_summary = data.get("content_summary", "")
                if content_summary:
                    reason = f"{reason} | 实际内容:{content_summary}"
                return is_match, confidence, reason
        except Exception as e:
            log(f"字幕内容AI验证失败: {e}", "WARN")
        # 异常时默认放行（宁可不拒绝，交给后续AI决策）
        return True, 0.4, "AI验证异常-默认放行"

    async def _review_knowledge_periodically(self):
        """
        📚 知识库定期审查：随机抽查归档条目，AI判断标题与内容摘要是否匹配。
        不匹配的条目会被标记（前缀[待审查]）并记录日志，供人工复核。
        每 KNOWLEDGE_REVIEW_INTERVAL 个视频触发一次。
        """
        if not os.path.exists(KNOWLEDGE_BASE_DIR):
            return
        # 收集所有 .md 文件
        all_files = []
        for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
            for f in files:
                if f.endswith('.md'):
                    all_files.append(os.path.join(root, f))
        if len(all_files) < 2:
            return  # 太少了，没必要查
        
        import random as _random
        sample_size = min(KNOWLEDGE_REVIEW_SAMPLE_SIZE, len(all_files))
        samples = _random.sample(all_files, sample_size)
        
        log(f"📚 知识库定期审查: 共{len(all_files)}个归档，抽查{sample_size}个...", "KB")
        
        quarantined = 0
        for file_path in samples:
            try:
                rel = os.path.relpath(file_path, KNOWLEDGE_BASE_DIR)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # 提取标题（第一行 # 或 **标题** 字段）
                title_match = re.search(r'(?:^#\s*|-\s*\*\*标题\*\*:\s*)(.+)', content, re.MULTILINE)
                if not title_match:
                    title_match = re.search(r'\[(BV[0-9A-Za-z]+)\]\s*-\s*(.+)', rel)
                if not title_match:
                    continue
                title = title_match.group(1) if 'BV' in title_match.group(1)[:2] else title_match.group(2) if title_match.lastindex >= 2 else title_match.group(1)
                # 二次提取：如果是BV号匹配，取第二个捕获组
                if title.startswith('BV'):
                    _m2 = re.search(r'\[BV[0-9A-Za-z]+\]\s*-\s*(.+)', rel)
                    if _m2:
                        title = _m2.group(1)
                
                # 提取AI总结部分
                summary = ""
                sum_match = re.search(r'##\s*\[BRAIN\]\s*AI内容总结\s*\n+(.*?)(?:\n##\s|\Z)', content, re.DOTALL)
                if sum_match:
                    summary = sum_match.group(1).strip()[:2000]
                else:
                    # 回退：取文件后半部分（跳过元数据头）
                    header_end = content.find('## [BRAIN]')
                    if header_end > 0:
                        summary = content[header_end:][:2000]
                    else:
                        summary = content[-2000:]
                
                if not summary or len(summary) < 50:
                    log(f"  ⏭️ 跳过审查（无有效内容）: {rel}", "KB")
                    continue
                
                # AI验证
                is_match, conf, reason = await self._ai_verify_subtitle_content(
                    title=title, subtitle_text=summary, video_desc=""
                )
                
                if not is_match and conf >= 0.75:
                    log(f"  ❌ 知识库垃圾条目: conf={conf:.2f} | {reason} | {rel}", "KB")
                    # 标记文件：文件名前加 [待审查]
                    dir_name = os.path.dirname(file_path)
                    base_name = os.path.basename(file_path)
                    if not base_name.startswith('[待审查]'):
                        new_name = f"[待审查] {base_name}"
                        new_path = os.path.join(dir_name, new_name)
                        try:
                            os.rename(file_path, new_path)
                            log(f"    → 已标记: {os.path.relpath(new_path, KNOWLEDGE_BASE_DIR)}", "KB")
                            quarantined += 1
                        except OSError as re_e:
                            log(f"    → 重命名失败: {re_e}", "WARN")
                elif not is_match:
                    log(f"  ⚠️ 知识库可疑条目(低置信): conf={conf:.2f} | {reason} | {rel}", "KB")
                else:
                    log(f"  ✅ 知识库条目正常: conf={conf:.2f} | {reason} | {rel}", "KB")
                    
            except Exception as e:
                log(f"  ⚠️ 审查单条失败: {e}", "KB")
        
        if quarantined > 0:
            log(f"📚 知识库审查完成: 已标记 {quarantined} 个垃圾条目（文件名前缀[待审查]），请人工复核后删除", "KB")
        else:
            log(f"📚 知识库审查完成: 抽查 {sample_size} 个条目全部通过", "KB")

    async def _download_video_for_asr(self, bvid):
        """为ASR下载视频（完全对齐video_modes.py的下载逻辑：http2/Origin/Referer/长超时）。
        返回 (视频路径, 下载耗时秒, 文件大小MB)"""
        import time as _t2
        _dl_start = _t2.time()
        file_size_mb = 0.0
        try:
            import tempfile, hashlib as _h
            import httpx as _httpx
            referer = f'https://www.bilibili.com/video/{bvid}'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': referer,
                'Origin': 'https://www.bilibili.com',
            }
            async with _httpx.AsyncClient(
                http2=True,
                headers=headers, cookies=self.cookies,
                timeout=90.0, follow_redirects=True
            ) as client:
                # [FIX] WBI签名：独立获取，不依赖 self.bili._wbi_keys 避免 AttributeError
                wkeys = None
                try:
                    nav = await client.get('https://api.bilibili.com/x/web-interface/nav')
                    nd = nav.json()
                    if nd.get('code') == 0:
                        wi = nd['data'].get('wbi_img', {})
                        im = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get('img_url', ''))
                        sm = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get('sub_url', ''))
                        if im and sm:
                            wkeys = (im.group(1), sm.group(1))
                            # 顺便缓存到 bili 实例（如果可用）
                            bili = getattr(self, 'bili', None)
                            if bili and hasattr(bili, '_wbi_keys'):
                                try:
                                    bili._wbi_keys = wkeys
                                    bili._wbi_keys_ts = time.time()
                                except Exception as e:
                                    log(f'非预期异常: {e}', 'WARN')
                except Exception as e:
                    log(f"[WARN] ASR下载WBI密钥获取失败: {e}", "WARN")

                params = {'bvid': bvid}
                if wkeys:
                    wts = int(_t2.time())
                    sp = dict(params)
                    sp['wts'] = wts
                    si = sorted(sp.items(), key=lambda x: x[0])
                    qs = '&'.join(f'{k}={v}' for k, v in si)
                    sp['w_rid'] = _h.md5((qs + wkeys[0] + wkeys[1]).encode()).hexdigest()
                    params = sp

                v_res = await client.get('https://api.bilibili.com/x/web-interface/view', params=params)
                v_data = v_res.json()
                if v_data.get('code') != 0:
                    return None, 0, 0
                info = v_data['data']
                cid = info.get('cid', 0)

                # 获取视频流
                play_params = {'bvid': bvid, 'cid': cid, 'qn': 32, 'fnval': 0, 'fourk': 0}
                if wkeys:
                    wts = int(_t2.time())
                    sp = dict(play_params)
                    sp['wts'] = wts
                    si = sorted(sp.items(), key=lambda x: x[0])
                    qs = '&'.join(f'{k}={v}' for k, v in si)
                    sp['w_rid'] = _h.md5((qs + wkeys[0] + wkeys[1]).encode()).hexdigest()
                    play_params = sp
                play = await client.get(
                    'https://api.bilibili.com/x/player/playurl',
                    params=play_params
                )
                play_data = play.json()
                durls = play_data.get('data', {}).get('durl', [])
                if not durls:
                    return None, 0, 0
                video_url = durls[0]['url']

                # 下载
                out_dir = os.path.join(tempfile.gettempdir(), "bilibili_asr", bvid)
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, f"{bvid}.mp4")

                async with client.stream("GET", video_url, headers=headers) as resp:
                    resp.raise_for_status()
                    with open(out_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(1024 * 256):
                            f.write(chunk)

                file_size_mb = os.path.getsize(out_path) / (1024 * 1024) if os.path.exists(out_path) else 0
                download_sec = _t2.time() - _dl_start
                log(f"[ASR下载] 耗时 {download_sec:.1f}s, 文件大小 {file_size_mb:.1f}MB", "DEBUG")
                return out_path, download_sec, file_size_mb
        except Exception as e:
            download_sec = _t2.time() - _dl_start
            log(f"ASR视频下载失败({download_sec:.1f}s): {e}", "WARN")
            return None, download_sec, 0
