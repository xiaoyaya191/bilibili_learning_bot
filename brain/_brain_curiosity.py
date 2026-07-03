"""
BrainCuriosityMixin — 好奇心驱动深度搜索
包含: curiosity_deep_dive
"""
import json
import asyncio
import random

from brain._mixin_imports import *
from api.throttle import _bili_throttle


class BrainCuriosityMixin:
    """好奇心驱动深度搜索"""

    async def curiosity_deep_dive(self, topic, trigger_title="", trigger_bvid=""):
        """好奇心驱动的B站深度搜索。遇到感兴趣/不懂的主题，搜索并动态调整观看视频数量。
        
        默认2-3个，内容中等则3-5个，干货多则5-10个。
        
        参数:
            topic: 搜索主题/关键词
            trigger_title: 触发此深度搜索的视频标题
            trigger_bvid: 触发视频的bvid
        
        返回: (videos_watched: int, key_findings: list)
        """
        if not CURIOSITY_DEEP_DIVE_ENABLED:
            return 0, []
        
        # 动态视频数量：起始默认2-3个，根据AI评估的content_richness逐步提升
        max_videos = CURIOSITY_DEEP_DIVE_DEFAULT_VIDEOS
        log(f"🧭 好奇心驱动深度搜索启动！主题: '{topic}' (初始上限{max_videos}个，按需提升至{CURIOSITY_DEEP_DIVE_HIGH_VIDEOS}个)", "LEARN")
        
        videos_watched = 0
        key_findings = []
        all_subtitles = []
        search_queries_tried = set()
        current_query = topic
        dive_tier = 0  # 0=初始(2-3), 1=中等(3-5), 2=丰富(5-10)
        
        for dive_round in range(4):  # 最多4轮搜索（给更充裕的空间）
            if videos_watched >= max_videos:
                break
            
            # 搜索B站视频
            if current_query not in search_queries_tried:
                search_queries_tried.add(current_query)
                log(f"🔍 B站搜索第{dive_round+1}轮: '{current_query}' (上限:{max_videos}个)", "LEARN")
                
                try:
                    if not self.agent_runner:
                        log("Agent运行器未初始化，无法搜索", "WARN")
                        break
                    search_results = await self.agent_runner._search_videos(current_query, count=min(8, max_videos - videos_watched))
                    if isinstance(search_results, dict) and search_results.get("error"):
                        log(f"搜索失败: {search_results.get('error')}", "WARN")
                        break
                    if not search_results:
                        log("搜索无结果，换个关键词试试...", "INFO")
                        current_query = f"{topic} 科普" if "科普" not in current_query else f"{topic} 介绍"
                        continue
                except Exception as e:
                    log(f"搜索异常: {e}", "WARN")
                    break
                
                # 逐个观看搜索到的视频
                for item in search_results:
                    if videos_watched >= max_videos:
                        break
                    
                    bvid = item.get("bvid")
                    title = item.get("title", "")
                    if not bvid:
                        continue
                    
                    videos_watched += 1
                    log(f"📺 [{videos_watched}/{max_videos}] 深度看: 《{title[:40]}》", "LEARN")
                    
                    try:
                        await _bili_throttle("深度搜索-看视频")
                        ok, subtitle = await self.understand_video_for_decision(bvid)
                        if ok and subtitle and len(subtitle) > 50:
                            all_subtitles.append(f"【{title}】: {subtitle[:1500]}")
                        
                        # [FIX] 深度搜索也要学习归档：每个视频看完后调用learn_from_video
                        if ok and subtitle and len(str(subtitle)) > 30:
                            try:
                                up = item.get("author", "") or item.get("uname", "")
                                video_url = f"https://www.bilibili.com/video/{bvid}"
                                _desc = getattr(self, "_last_video_desc", "")
                                await self.learn_from_video(bvid, title, up, video_url, str(subtitle), topic, video_desc=_desc)
                            except Exception as learn_e:
                                log(f"深度搜索学习归档失败: {learn_e}", "WARN")
                    except Exception as e:
                        log(f"深度看视频失败: {e}", "WARN")
                    
                    await asyncio.sleep(random.uniform(0.3, 0.8))
            
            # 检查是否已经了解足够（至少看了2个后才判断）
            if all_subtitles and videos_watched >= 2:
                try:
                    review_context = (
                        f"学习主题: {topic}\n"
                        f"已看{videos_watched}个相关视频\n"
                        f"视频内容摘要:\n" + "\n---\n".join(all_subtitles[-5:])
                    )
                    resp = await self._call_ai_with_retry(
                        model=MODEL_BRAIN,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT_CURIOSITY_DIVE},
                            {"role": "user", "content": f"{review_context}\n\n{videos_watched}/{max_videos}个视频（上限{videos_watched}/{CURIOSITY_DEEP_DIVE_HIGH_VIDEOS}）。请判断是继续搜索还是已足够，并评估内容丰度。"}
                        ],
                        timeout=90
                    )
                    raw = resp.choices[0].message.content.strip()
                    # [FIX] 嵌套匹配提取JSON
                    start = raw.find("{")
                    if start >= 0:
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
                            dive_decision = json.loads(raw[start:match_end+1])
                        else:
                            end = raw.rfind("}")
                            if end >= start:
                                try:
                                    dive_decision = json.loads(raw[start:end+1])
                                except json.JSONDecodeError:
                                    dive_decision = {"continue_search": False, "reason": "AI返回解析失败"}
                            else:
                                dive_decision = {"continue_search": False, "reason": "AI返回解析失败"}
                    else:
                        dive_decision = {"continue_search": False, "reason": "AI返回解析失败"}
                    
                    key_findings = dive_decision.get("key_takeaways", [])
                    content_richness = dive_decision.get("content_richness", 0.0)
                    
                    # 动态调整max_videos：根据AI评估的内容丰度提升上限
                    if content_richness >= 0.6 and dive_tier < 2:
                        dive_tier = 2
                        max_videos = CURIOSITY_DEEP_DIVE_HIGH_VIDEOS
                        log(f"📈 内容丰度 {content_richness:.0%} -> 上限提升至{max_videos}个 (干货满满！)", "LEARN")
                    elif content_richness >= 0.3 and dive_tier < 1:
                        dive_tier = 1
                        max_videos = CURIOSITY_DEEP_DIVE_MID_VIDEOS
                        log(f"📈 内容丰度 {content_richness:.0%} -> 上限提升至{max_videos}个", "LEARN")
                    
                    if dive_decision.get("continue_search") and dive_decision.get("new_query"):
                        current_query = dive_decision["new_query"]
                        log(f"🧭 继续深度搜索，新关键词: '{current_query}' (满意度: {dive_decision.get('satisfaction', 0):.0%}, 丰度:{content_richness:.0%})", "LEARN")
                        continue
                    else:
                        tier_label = ["浅层","中等","丰富"][dive_tier]
                        log(f"[OK] 深度搜索完成！满意度: {dive_decision.get('satisfaction', 0):.0%} | 丰度:{content_richness:.0%}({tier_label}) | 共看{videos_watched}个 | 原因: {dive_decision.get('reason', '')}", "SUCCESS")
                        break
                except Exception as e:
                    log(f"深度搜索决策失败: {e}", "WARN")
                    break
            else:
                break
        
        # 总结并写入学习日志
        if key_findings:
            summary_text = "\n".join(f"- {f}" for f in key_findings)
            log(f"[NOTE] 深度搜索关键发现:\n{summary_text}", "LEARN")
            try:
                self.write_learning_log(f"深度搜索/{topic}", topic, "")
                # 写入日记
                if hasattr(self, "diary_mgr"):
                    self.diary_mgr.add_entry(
                        f"好奇心深度搜索: {topic}",
                        f"搜索主题「{topic}」观看了{videos_watched}个视频。\n关键发现:\n{summary_text}",
                        mood=self.mood_mgr.get_current() if hasattr(self, 'mood_mgr') else "好奇",
                        tags=["好奇心", "深度搜索", topic],
                        source="curiosity_dive"
                    )
            except Exception as e:
                log(f"记录深度搜索结果失败: {e}", "WARN")
        
        return videos_watched, key_findings
