"""
BrainLoopMixin — 主循环 run()
"""
import asyncio
import json
import os
import random
import re
from datetime import datetime

from bilibili_api.video import Video
from bilibili_api.comment import CommentResourceType
from bilibili_api import comment
from colorama import Fore, Style

from brain._mixin_imports import *
from utils.helpers import _mask_urls
from utils.helpers import _safe_task_callback
from api.throttle import _bili_throttle
from utils.lock import _acquire_bot_lock, _release_bot_lock
from brain.decision import decode_ai_mapping, parse_video_decision, response_text


async def select_candidate_video(brain, items):
    """Choose one recommendation from a bounded candidate pool, with safe fallbacks."""
    # Candidate metadata is persisted in the web workspace. Keeping the
    # terminal stream concise prevents a busy recommendation loop from making
    # the full-log page expensive to render.
    candidate_log_detail_limit = 5
    video_config = config.get("video", {})
    try:
        from core.config import load_config
        video_config = load_config().get("video", video_config)
    except Exception:
        pass
    pool_size = max(5, min(100, int(video_config.get("candidate_pool_size", 20))))
    pool = []
    seen_bvids = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        bvid = str(item.get("bvid") or "").strip()
        if not bvid or bvid in seen_bvids:
            continue
        seen_bvids.add(bvid)
        pool.append(item)
        if len(pool) >= pool_size:
            break
    # The web panel and current CLI write to interest_engine.json. Re-read the
    # small file for every candidate round: a long-running bot must see a
    # change saved from the web page immediately instead of keeping a stale
    # singleton in memory.
    try:
        from services.interest_engine import InterestEngine
        interest_engine = InterestEngine()
        interests = [str(item).strip() for item in interest_engine.get_keywords() if str(item).strip()]
    except Exception as exc:
        log(f"候选筛选兴趣引擎不可用，回退旧兴趣列表: {exc}", "WARN")
        interests = brain.interest_mgr.get_interests() or []
    if not pool:
        log("候选筛选：推荐流中没有可用 BV 视频", "CANDIDATE")
        return None
    if len(pool) < pool_size:
        log(f"候选筛选：推荐流仅返回 {len(pool)} 条不重复视频（目标 {pool_size} 条）", "CANDIDATE")
    else:
        log(f"候选筛选：将 {len(pool)} 条不重复视频交给 AI", "CANDIDATE")
    for index, item in enumerate(pool[:candidate_log_detail_limit], 1):
        owner = item.get("owner") or {}
        up_name = owner.get("name", "未知") if isinstance(owner, dict) else item.get("author", "未知")
        log(f"{index:02d}. {item['bvid']} | {item.get('title', '无标题')} | @{up_name}", "CANDIDATE")
    omitted_count = len(pool) - candidate_log_detail_limit
    if omitted_count > 0:
        log(f"候选详情已省略 {omitted_count} 条，可在“记忆 & 知识库”的 AI 候选筛选中查看", "CANDIDATE")
    if not interests:
        selected = random.choice(pool)
        log(f"无兴趣偏好，随机选择：{selected['bvid']}《{selected.get('title', '无标题')}》", "CANDIDATE")
        return selected
    log(f"候选兴趣引擎已加载 {len(interests)} 个关键词：{', '.join(interests[:12])}", "CANDIDATE")
    def candidate_keywords(item):
        owner = item.get("owner") or {}
        up_name = owner.get("name", "") if isinstance(owner, dict) else item.get("author", "")
        try:
            result = interest_engine.match(
                title=str(item.get("title", "")),
                tags=str(item.get("tag", "")),
                desc=str(item.get("desc", "")),
                up_name=str(up_name),
                category=str(item.get("tname", "")),
                quality_ai_score=0.0,
            )
            return result.matched_keywords or []
        except Exception:
            # Keep candidate selection usable with a minimal engine implementation.
            text = " ".join((
                str(item.get("title", "")), str(item.get("tname", "")),
                str(item.get("tag", "")), str(item.get("desc", "")), str(up_name),
            )).casefold()
            return [word for word in interests if word.casefold() in text]

    matched = [item for item in pool if candidate_keywords(item)]
    if not matched:
        log("候选池没有命中当前兴趣，跳过本轮推荐流，不随机选择无关视频", "CANDIDATE")
        return None
    summary = "\n".join(f"{item['bvid']} | {item.get('title','')} | {(item.get('owner') or {}).get('name','')}" for item in matched)
    try:
        response = await brain._call_ai_with_retry(messages=[{"role":"system","content":"从候选视频中选择最符合兴趣的一条。仅输出 BV 号。"},
            {"role":"user","content":f"兴趣：{', '.join(interests[:20])}\n候选：\n{summary}"}], temperature=0.1, max_tokens=30)
        chosen = response.choices[0].message.content.strip()
        match = re.search(r"BV[0-9A-Za-z]{10}", chosen)
        if match:
            selected = next((item for item in matched if item["bvid"] == match.group(0)), None)
            if selected:
                log(f"AI 选择：{selected['bvid']}《{selected.get('title', '无标题')}》", "CANDIDATE")
                return selected
            log(f"AI 返回的 {match.group(0)} 不在候选池，改用本地筛选", "WARN")
    except Exception as exc:
        log(f"候选视频 AI 筛选不可用，使用本地兜底: {exc}", "WARN")
    selected = random.choice(matched)
    log(f"本地兴趣匹配选择：{selected['bvid']}《{selected.get('title', '无标题')}》", "CANDIDATE")
    return selected
from core.platform_actions import public_commenting_enabled, video_liking_enabled


class BrainLoopMixin:
    """主循环方法"""

    async def run(self):
        # 🔒 单实例锁：防止多个 bot 进程同时运行
        if not _acquire_bot_lock():
            log("[LOCK] ❌ 已有 bot 实例正在运行，退出", "ERROR")
            return
        log("[LOCK] ✅ 单实例锁已获取", "INFO")
        
        log("bilibili_learning_bot - 启动...", "SUCCESS")
        self.update_runtime_clock(starting=True)
        if self.previous_seen_at:
            log(f"上次运行最后记录时间: {self.previous_seen_at}，本次只处理之后的新评论/私信", "INFO")

        os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
        log(f"知识库模块已加载，路径: {KNOWLEDGE_BASE_DIR}", "INFO")
        
        # 显示兴趣状态（v2.0: 同时检查新旧系统）
        interests_old = self.interest_mgr.get_interests()
        try:
            from services.interest_engine import get_engine
            engine = get_engine()
            interests_new = engine.get_keywords()
        except ImportError:
            interests_new = []
        except Exception as e:
            log(f"兴趣引擎加载异常: {e}", "WARN")
            interests_new = []
        all_interests = list(dict.fromkeys(interests_old + interests_new))
        if all_interests:
            log(f"兴趣列表: {', '.join(all_interests)}", "INTEREST")
        else:
            log("兴趣列表为空，将对所有视频感兴趣", "INTEREST")
        log(f"当前人格: {self.persona_mgr.get_active_persona()} | 当前心情: {self.mood_mgr.get_current()}", "INFO")
        
        print(f"\n{Fore.CYAN}知识库分类系统已初始化:{Style.RESET_ALL}")
        self.classifier.show_category_structure()
        # 启动时清理空文件夹
        cleaned = self.classifier.cleanup_empty_folders()
        if cleaned > 0:
            log(f"已清理 {cleaned} 个空文件夹", "KB")

        login_success = await self.initialize_login()
        if not login_success:
            log("登录失败，程序退出", "ERROR")
            return

        # ── OpenBiliClaw 桥梁初始化 ──
        await self._init_ob_bridge()

        log(f"初始化完成 | 最大精力: {MAX_ENERGY}% | 视频间隔: {VIDEO_INTERVAL_MIN}-{VIDEO_INTERVAL_MAX}秒", "INFO")
        if SESSION_MAX_VIDEOS > 0:
            log(f"会话限制: 最多处理 {SESSION_MAX_VIDEOS} 个视频后自动停止", "SESSION")
        if SESSION_MAX_LEARNED_VIDEOS > 0:
            log(f"会话限制: 成功学习 {SESSION_MAX_LEARNED_VIDEOS} 个视频后结束刷视频", "SESSION")
        if SESSION_MAX_DURATION_MINUTES > 0:
            log(f"会话限制: 最长运行 {SESSION_MAX_DURATION_MINUTES} 分钟后自动停止", "SESSION")
        if any((SESSION_MAX_VIDEOS > 0, SESSION_MAX_LEARNED_VIDEOS > 0, SESSION_MAX_DURATION_MINUTES > 0)):
            action_label = "启动实时监听" if SESSION_COMPLETION_ACTION == "monitor" else "停止机器人"
            log(f"会话结束动作: {action_label}", "SESSION")
        log(f"评论互动: {'已启用' if COMMENT_CHECK_ENABLED else '⏸️ 已关闭'} | 检查间隔: {COMMENT_CHECK_INTERVAL}秒", "COMMENT")
        log(f"私信互动: {'已启用' if PRIVATE_MESSAGE_ENABLED else '⏸️ 已关闭'} | {'自动发送' if PRIVATE_MESSAGE_AUTO_REPLY else '仅拟不发送'} | 检查间隔: {PRIVATE_MESSAGE_CHECK_INTERVAL}秒", "DM")
        log(f"日记: {'自动' if DIARY_ENABLED and DIARY_AUTO_ENABLED else '手动/关闭'} | 自我进化: {'自动应用' if EVOLUTION_ENABLED and EVOLUTION_AUTO_ENABLED and EVOLUTION_AUTO_APPLY else '手动/仅记录'}", "EVOLVE")
        print("="*80)

        # ── 智能省token模式（实时读取 config，避免 import * 缓存）──
        _smart_token = bool(config.get("system", {}).get("smart_token_mode", False))
        _fast_model = (config.get("models", {}).get("fast") or MODEL_BRAIN) if _smart_token else MODEL_BRAIN
        if _smart_token:
            log(f"💡 智能省token模式已启用：跳过封面/ASR、用快速模型({_fast_model})、"
                f"关闭Agent深度搜索/好奇心探索/AI推荐/心理深度分析/知识验证", "INFO")

        # 🔵 Cookie 预热：模拟人类打开App行为，先访问一次首页暖机
        if config.get("speed", {}).get("no_human_delay", False):
            log("⚡ 快速模式：跳过Cookie预热", "INFO")
        else:
            log("🍪 Cookie预热：模拟打开B站首页...", "INFO")
            try:
                warmup_client = await self.bili._get_http_client()
                await warmup_client.get(
                    'https://www.bilibili.com',
                    cookies=self.bili.raw_cookies,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                    timeout=15.0
                )
                log("🍪 Cookie预热完成", "SUCCESS")
            except Exception as e:
                log(f"Cookie预热跳过: {e}", "INFO")

        # [WARN] 启动冷却：等待几秒再进入扫描循环，模拟真人打开App后的浏览节奏
        try:
            startup_cool = max(0.1, random.uniform(float(COOLDOWN_STARTUP_MIN or 1), float(COOLDOWN_STARTUP_MAX or 3)))
        except (ValueError, TypeError):
            startup_cool = 1.5
        if config.get("speed", {}).get("no_human_delay", False):
            log(f"⚡ 快速模式：跳过启动冷却 ({startup_cool:.1f}秒)", "INFO")
        else:
            self.update_activity("启动冷却中", f"模拟真人浏览节奏，等待约 {startup_cool:.1f} 秒", phase="cooldown")
            log(f"启动冷却 {startup_cool:.1f} 秒，模拟真人打开App后的浏览节奏...", "INFO")
            await asyncio.sleep(startup_cool)

        # [FIX] 启动守卫：前几轮主循环强制跳过Agent深度搜索（防止旧pyc缓存或冷却bug导致启动即触发）
        _loop_count = 0
        completion_action = "stop"

        while True:
            try:
                _loop_count += 1
                self.update_runtime_clock()
                self.update_activity("检查互动消息", "正在检查评论续聊、私信和 @我提醒", phase="interaction")

                # ── 会话限制检查 ──
                session_elapsed = (datetime.now() - self.session_start_time).total_seconds() / 60.0
                limit_reached = False
                limit_reason = ""

                if SESSION_MAX_DURATION_MINUTES > 0 and session_elapsed >= SESSION_MAX_DURATION_MINUTES:
                    limit_reached = True
                    limit_reason = f"已达到最长运行时间 {SESSION_MAX_DURATION_MINUTES} 分钟（实际 {session_elapsed:.1f} 分钟）"
                elif SESSION_MAX_LEARNED_VIDEOS > 0 and self.videos_learned >= SESSION_MAX_LEARNED_VIDEOS:
                    limit_reached = True
                    limit_reason = f"已成功学习 {self.videos_learned} 个视频（上限 {SESSION_MAX_LEARNED_VIDEOS}）"
                elif SESSION_MAX_VIDEOS > 0 and self.videos_processed >= SESSION_MAX_VIDEOS:
                    limit_reached = True
                    limit_reason = f"已处理 {self.videos_processed} 个视频（上限 {SESSION_MAX_VIDEOS}）"

                if limit_reached:
                    log(f"⏰ 会话限制触发: {limit_reason}", "SESSION")
                    completion_action = SESSION_COMPLETION_ACTION if SESSION_COMPLETION_ACTION in {"stop", "monitor"} else "stop"
                    action_label = "启动实时监听" if completion_action == "monitor" else "停止机器人"
                    log(f"[STATS] 本次会话统计: 处理 {self.videos_processed} 个视频, 成功学习 {self.videos_learned} 个, 运行 {session_elapsed:.1f} 分钟", "SESSION")
                    log(f"会话限制已完成，下一步: {action_label}", "SESSION")
                    break

                # [SPEED] 评论续聊、私信和 @我提醒并行检查。@我处理使用与
                # realtime monitor 相同的去重和发送路径。
                comments_task = asyncio.create_task(self.check_and_handle_comments())
                msgs_task = asyncio.create_task(self.check_and_handle_private_messages())
                mentions_task = asyncio.create_task(self.check_and_handle_mentions())
                comments_processed, msgs_processed, mentions_processed = await asyncio.gather(
                    comments_task, msgs_task, mentions_task, return_exceptions=True
                )
                # [FIX] gather 返回异常时降级为 0
                if isinstance(comments_processed, Exception):
                    comments_processed = 0
                if isinstance(msgs_processed, Exception):
                    msgs_processed = 0
                if isinstance(mentions_processed, Exception):
                    mentions_processed = 0
                # [FIX] 只有实际处理了评论才睡冷却，无操作则跳过
                if comments_processed > 0:
                    self.update_activity("评论互动冷却中", "刚处理完评论，短暂等待后继续", phase="cooldown")
                    await asyncio.sleep(max(0.1, random.uniform(
                        float(COOLDOWN_POST_COMMENT_MIN or 1), float(COOLDOWN_POST_COMMENT_MAX or 3))))
                
                if self.energy <= 0:
                    self.update_activity("精力恢复中", "当前精力不足，暂停视频学习", phase="recovery")
                    await self.energy_recovery_session()
                    continue

                session_info = ""
                if SESSION_MAX_VIDEOS > 0:
                    session_info += f" | 已看: {self.videos_processed}/{SESSION_MAX_VIDEOS}"
                elif SESSION_MAX_DURATION_MINUTES > 0:
                    session_info += f" | 已看: {self.videos_processed}"
                if SESSION_MAX_LEARNED_VIDEOS > 0:
                    session_info += f" | 已学: {self.videos_learned}/{SESSION_MAX_LEARNED_VIDEOS}"
                log(f"精力: {self.energy}% | 今日已投: {self.coins_spent}/{MAX_COINS_DAILY} | 记忆UP: {len(self.memory['known_ups'])}{session_info}", "INFO")

                # [FIX] 只有实际处理了私信才睡冷却，无操作则跳过
                if msgs_processed > 0:
                    self.update_activity("私信互动冷却中", "刚处理完私信，短暂等待后继续", phase="cooldown")
                    await asyncio.sleep(max(0.1, random.uniform(
                        float(COOLDOWN_POST_DM_MIN or 1), float(COOLDOWN_POST_DM_MAX or 3))))

                # ── 🤖 Agent深度搜索：定期触发，深入了解某个主题 ──
                # [FIX] 启动守卫：前3轮主循环硬跳过（防止旧pyc缓存/冷却bug导致启动即触发）
                if AGENT_ENABLED and AGENT_DIVE_ENABLED and _loop_count > 3 and not _smart_token:
                    agent_dive_elapsed = (datetime.now() - self.last_agent_run_at).total_seconds() / 60
                    # [FIX] 必须至少看过3个视频+冷却到期+精力够+25%随机
                    if (self.videos_processed >= 3 and agent_dive_elapsed >= max(AGENT_COOLDOWN_MINUTES, 5)
                            and self.energy >= 15 and random.random() < 0.25):
                        # 优先用刚看过的感兴趣视频主题，没有则从兴趣/知识库选
                        dive_topic = await self._pick_agent_dive_topic()
                        if dive_topic:
                            log(f"🤖 Agent深度搜索启动！主题: '{dive_topic[:50]}'", "CONFIG")
                            self.last_agent_run_at = datetime.now()  # [FIX] 立即记录，防止重复触发
                            self.energy -= 8  # [FIX] 先扣精力，防止异步并发超扣
                            # [FIX] 异步非阻塞：不卡主循环，后台默默搜索看视频
                            async def _dive_async(topic=dive_topic):
                                try:
                                    run = await self.agent_runner.run_goal(topic)
                                    ok_steps = sum(1 for item in run.get("results", []) if item.get("result", {}).get("ok"))
                                    watched_count = 0
                                    for item in run.get("results", []):
                                        if item.get("step", {}).get("skill") == "watch_bilibili_videos":
                                            watched_count = item.get("result", {}).get("count", 0)
                                    log(f"🤖 Agent深度搜索完成: {ok_steps}/{len(run.get('results', []))}步骤, 看了{watched_count}个视频", "SUCCESS")
                                except Exception as e:
                                    log(f"🤖 Agent深度搜索异常: {e}", "WARN")
                            task = asyncio.create_task(_dive_async())
                            task.add_done_callback(_safe_task_callback("agent_dive_async"))

                # ── 📂 [KB] 自动重分类"未分类"文件夹 ──
                if AUTO_RECLASSIFY_ENABLED and _loop_count > 5:
                    reclass_elapsed = (datetime.now() - getattr(self, '_last_reclassify_at', datetime.min)).total_seconds() / 60
                    if reclass_elapsed >= AUTO_RECLASSIFY_INTERVAL_MINUTES and random.random() < 0.5:
                        try:
                            ok, fail = await self.classifier.reclassify_uncategorized(max_per_run=3)
                            if ok > 0 or fail > 0:
                                self._last_reclassify_at = datetime.now()
                                # 清理空文件夹
                                cleaned = self.classifier.cleanup_empty_folders()
                                if cleaned > 0:
                                    log(f"[KB] 已清理 {cleaned} 个空文件夹", "KB")
                        except Exception as e:
                            log(f"[KB] 自动重分类异常: {e}", "ERROR")

                # ── [SPEED] 并行：回顾复习 + 主动聊天，互不依赖 ──
                revisit_target = None

                async def _do_revisit():
                    if not REVISIT_ENABLED or not self.history_videos.get("videos"):
                        return None
                    revisit_cooldown_ok = (datetime.now() - self.last_revisit_at).total_seconds() / 60 >= REVISIT_COOLDOWN_MINUTES
                    if not revisit_cooldown_ok or random.random() >= PROB_REVISIT:
                        return None
                    candidate = self.get_revisit_candidate()
                    if not candidate:
                        return None
                    try:
                        log(f"📖 学而时习之：回顾复习《{candidate.get('title','')[:30]}》({candidate.get('action')}) ...", "REVISIT")
                        await _bili_throttle("回顾复习-get_info")
                        v = Video(bvid=candidate.get("bvid"), credential=self.credential)
                        vid_info = await v.get_info()
                        if vid_info:
                            target = {
                                "bvid": candidate["bvid"],
                                "title": vid_info.get("title", candidate.get("title", "")),
                                "owner": vid_info.get("owner", {}),
                                "id": vid_info.get("aid") or candidate.get("aid"),
                                "pic": vid_info.get("pic", ""),
                                "aid": vid_info.get("aid") or candidate.get("aid"),
                                "_is_revisit": True,
                                "_original_action": candidate.get("action", "")
                            }
                            self.last_revisit_at = datetime.now()
                            self.mark_revisited(candidate["bvid"])
                            log(f"回顾复习锁定: 《{target['title']}》", "REVISIT")
                            return target
                        else:
                            log(f"获取复习视频信息失败，跳过", "WARN")
                    except Exception as e:
                        log(f"回顾复习异常: {e}", "WARN")
                    return None

                async def _do_chat():
                    try:
                        await self.maybe_initiate_chat()
                    except Exception as e:
                        log(f"主动聊天模块异常(主循环): {e}", "ERROR")

                revisit_target, _ = await asyncio.gather(_do_revisit(), _do_chat(), return_exceptions=True)
                if isinstance(revisit_target, Exception):
                    revisit_target = None

                if revisit_target:
                    # 使用复习视频代替推荐流
                    target = revisit_target
                    self.videos_processed += 1
                    bvid = target['bvid']
                    title = target.get('title', '无标题')
                    up = target.get('owner', {}).get('name', '未知')
                    up_uid = target.get('owner', {}).get('mid', 0)
                    aid = target.get('id') or target.get('aid')
                    pic_url = target.get('pic', '')
                    video_url = f"https://www.bilibili.com/video/{bvid}"
                    log(f"📖 复习目标:《{title}》- @{up}", "REVISIT")
                    # 🔍 知识验证：回顾时联网核实知识的真实性和时效性（带异常回调）
                    if not _smart_token:
                        task = asyncio.create_task(self.verify_knowledge_file(bvid, title))
                        task.add_done_callback(_safe_task_callback("verify_knowledge_file"))
                    # 顺便浏览该UP的视频（副作用：记录到浏览历史）
                    await self.maybe_browse_up_videos(force_up_uid=up_uid if up_uid else None, up_name_hint=up)
                else:
                    # ── [*] 优先浏览喜欢/已知UP主的新视频 ──
                    up_browse_target = await self.maybe_browse_up_videos()
                    if up_browse_target and up_browse_target.get("bvid"):
                        target = up_browse_target
                        self.videos_processed += 1
                        bvid = target['bvid']
                        title = target.get('title', '无标题')
                        up = target.get('owner', {}).get('name', '未知')
                        up_uid = target.get('owner', {}).get('mid', 0)
                        aid = target.get('id') or target.get('aid')
                        pic_url = target.get('pic', '')
                        video_url = f"https://www.bilibili.com/video/{bvid}"
                        source_tag = "[STAR]喜爱UP" if target.get("_is_favorite_up") else "📺已关注UP"
                        log(f"{source_tag} 新视频:《{title}》- @{up}", "BROWSE")
                    else:
                        # [PSYCHO] 主动推荐：每N轮触发一次AI驱动的惊喜/探索/反茧房推荐
                        rec_target = None
                        if (self.recommend_engine 
                            and self._psycho_profile_analysis_count > PSYCHO_MIN_VIEWS_BEFORE_RECOMMEND 
                            and random.random() < PSYCHO_RECOMMEND_PROB
                            and not _smart_token):
                            rec_modes = ["surprise", "explore", "anticocoon", "trend"]
                            # 轮换模式，避免重复
                            if self._last_recommend_mode:
                                try:
                                    idx = rec_modes.index(self._last_recommend_mode)
                                    rec_modes = rec_modes[idx+1:] + rec_modes[:idx+1]
                                except ValueError as e:
                                    log(f'值错误: {e}', 'DEBUG')
                            for mode in rec_modes[:2]:  # 尝试2种模式
                                try:
                                    queries = await self.recommend_engine.generate_search_queries(mode=mode, count=2)
                                    if queries:
                                        log(f"{get_mode_emoji(mode)} {get_mode_label(mode)}: 搜索「{queries[0]}」...", "RECOMMEND")
                                        results = await self.bili.search_bilibili(queries[0])
                                        if results:
                                            # 过滤已看过的
                                            fresh = [r for r in results if r.get("bvid") not in self.recommend_engine._seen_bvids]
                                            if fresh:
                                                chosen = random.choice(fresh[:5])
                                                chosen["_rec_mode"] = mode
                                                chosen["_rec_query"] = queries[0]
                                                rec_target = chosen
                                                self._last_recommend_mode = mode
                                                self.recommend_engine._seen_bvids.add(chosen.get("bvid"))
                                                # 生成推荐理由
                                                chosen["_rec_reason"] = self.recommend_engine.explain_recommendation(
                                                    {"title": chosen.get("title",""), "tags": chosen.get("tag","").split(",") if chosen.get("tag") else [],
                                                     "up_name": chosen.get("author",""), "up_uid": chosen.get("mid",""),
                                                     "category": chosen.get("typename",""), "bvid": chosen.get("bvid","")},
                                                    mode
                                                )
                                                log(f"  → 推荐理由: {chosen['_rec_reason'][:80]}...", "RECOMMEND")
                                                break
                                except Exception as e:
                                    log(f"推荐生成失败({mode}): {e}", "WARN")
                        
                        if rec_target and rec_target.get("bvid"):
                            target = rec_target
                            if not isinstance(target, dict):
                                continue
                            self.videos_processed += 1
                            bvid = target.get('bvid', '')
                            if not bvid:
                                continue
                            title = target.get('title', '无标题')
                            owner = target.get('owner')
                            if isinstance(owner, dict):
                                up = target.get('author') or owner.get('name', '未知')
                                up_uid = target.get('mid') or owner.get('mid', 0)
                            else:
                                up = target.get('author', '未知')
                                up_uid = target.get('mid', 0)
                            aid = target.get('aid') or target.get('id', 0)
                            pic_url = target.get('pic', '')
                            video_url = f"https://www.bilibili.com/video/{bvid}"
                            log(f"{get_mode_emoji(target.get('_rec_mode','surprise'))} 主动推荐:《{title}》- @{up}", "RECOMMEND")
                            if target.get("_rec_reason"):
                                log(f"  [IDEA] 为什么推荐: {target['_rec_reason'][:120]}", "RECOMMEND")
                            # 追踪推荐点击
                            self.psycho_profile.tracker.record("recommend_click", 
                                bvid=bvid, title=title, mode=target.get("_rec_mode",""))
                        else:
                            self.update_activity("刷新推荐流", "正在获取下一批候选视频", phase="scan")
                            log("正在刷新推荐流...", "SCAN")
                            items = await self._get_cached_recommendations()
                            if not items or not isinstance(items, list):
                                self.update_activity("等待推荐流", "暂时没有可用候选，3 秒后重试", phase="wait")
                                await asyncio.sleep(3)
                                continue

                            try:
                                from core.config import load_config
                                browse_mode = load_config().get("video", {}).get("browse_mode", "candidate_review")
                            except Exception:
                                browse_mode = config.get("video", {}).get("browse_mode", "candidate_review")
                            target = await select_candidate_video(self, items) if browse_mode == "candidate_review" else random.choice(items)
                            if not isinstance(target, dict):
                                log(f"推荐流返回异常元素类型: {type(target).__name__}", "WARN")
                                continue
                            self.videos_processed += 1
                            bvid = target.get('bvid', '')
                            if not bvid:
                                log("推荐流元素缺少bvid，跳过", "WARN")
                                continue
                            title = target.get('title', '无标题')
                            owner = target.get('owner')
                            if isinstance(owner, dict):
                                up = owner.get('name', '未知')
                                up_uid = owner.get('mid', 0)
                            else:
                                up = '未知'
                                up_uid = 0
                            aid = target.get('id') or target.get('aid')
                            pic_url = target.get('pic', '')
                            video_url = f"https://www.bilibili.com/video/{bvid}"

                            log(f"锁定目标:《{title}》- @{up}", "SCAN")

                # [SPEED] 锁定后立即后台预取推荐流 + 短暂休息并行
                prefetch_task = asyncio.create_task(self._prefetch_recommendations())
                prefetch_task.add_done_callback(_safe_task_callback("prefetch_recs"))
                self.update_activity("准备分析视频", "已锁定目标，正在安排字幕、评论与弹幕读取", phase="prepare")
                await asyncio.sleep(random.uniform(0.3, 0.8))

                # 提取标签、时长、分类（供心理画像引擎/避雷系统使用）
                tags = []
                raw_tag = target.get('tag', '')
                if isinstance(raw_tag, str) and raw_tag:
                    tags = [t.strip() for t in raw_tag.split(',') if t.strip()]
                elif isinstance(raw_tag, list):
                    tags = raw_tag
                duration = target.get('duration', 0)
                if isinstance(duration, str) and ':' in duration:
                    try:
                        parts = duration.split(':')
                        duration = int(parts[0]) * 60 + int(parts[1])
                    except Exception:
                        duration = 0
                elif isinstance(duration, str):
                    try:
                        duration = int(duration)
                    except Exception:
                        duration = 0
                category = target.get('typename') or target.get('tname') or ''
                if target.get('_is_revisit'):
                    history_source = "复习回顾"
                elif target.get('_rec_mode'):
                    history_source = "AI 主动推荐"
                elif target.get('_is_favorite_up'):
                    history_source = "关注 UP"
                elif config.get("video", {}).get("browse_mode") == "candidate_review":
                    history_source = "AI 候选筛选"
                else:
                    history_source = "推荐流"

                # [ASR] 缓存视频元数据供 ASR AI预判使用
                self._current_video_tags = tags
                self._current_video_category = category
                self._current_video_duration = duration
                video_stat = target.get('stat') if isinstance(target.get('stat'), dict) else {}
                description = str(target.get('desc') or target.get('description') or '').strip()[:500]
                self.update_video_observation(
                    "兴趣筛选中",
                    bvid=bvid, aid=aid or 0, title=title, up=up, up_uid=up_uid or 0,
                    cover=pic_url, duration=duration or 0, category=category,
                    tags=tags, source=history_source, description=description,
                    view_count=video_stat.get('view') or target.get('view_count') or 0,
                    like_count=video_stat.get('like') or target.get('like_count') or 0,
                    favorite_count=video_stat.get('favorite') or target.get('favorite_count') or 0,
                )

                # ── 视频过滤模式 ──
                if VIDEO_FILTER_MODE == "watch_all":
                    vis_desc, vis_score = "全量模式，跳过封面分析", 0
                    log(f"[FAST] 全量模式：不看封面标题，直接看视频", "MODE")
                    interested = True
                    matched_interests = []
                    interest_reason = "全量模式(所有视频都看)"
                else:
                    # cover_and_title 模式：封面分析 + AI兴趣判断
                    if _smart_token:
                        # [SMART] 省token：跳过封面视觉分析，仅用标题/标签做兴趣判断
                        vis_desc, vis_score = "省token模式·跳过封面分析", 0
                    else:
                        vis_desc, vis_score = await self.analyze_vision(pic_url)
                        log(f"封面速览: {vis_desc} [印象分:{vis_score}]", "EYE")
                    # [ASR] 缓存封面描述供 ASR AI预判
                    self._current_video_cover_desc = vis_desc
                    # [DEF] 避雷系统检查
                    if self.psycho_profile:
                        aversion_score, aversion_reasons = self.psycho_profile.aversion.get_aversion_score(
                            title=title, tags=tags, up_uid=up_uid
                        )
                        if aversion_score >= PSYCHO_AVERSION_BLOCK_SCORE:
                            log(f"[DEF] 避雷拦截: {title[:30]}... | 反感度{aversion_score:.1%} | {'; '.join(aversion_reasons)}", "AVERSION")
                            self.psycho_profile.tracker.record_skip(bvid, title, reason=f"避雷: {'; '.join(aversion_reasons)}")
                            self.record_watched_video(
                                bvid, title, up, aid, pic=pic_url, duration=duration,
                                source=history_source, result="避雷策略拦截",
                                interest_reason="；".join(aversion_reasons),
                            )
                            continue
                        elif aversion_score >= PSYCHO_AVERSION_WARN_SCORE:
                            log(f"[DEF] 避雷提示: {title[:30]}... | 反感度{aversion_score:.1%} | {'; '.join(aversion_reasons)} (仍继续判断)", "AVERSION")
                    
                    interested, matched_interests, interest_reason = await self.judge_interest_with_ai(
                        title, up, vis_desc, vis_score,
                        tags=",".join(tags) if tags else "",
                        category=category, desc=getattr(self, "_last_video_desc", "")
                    )
                    if not interested:
                        log(f"视频《{title}》与兴趣不匹配，跳过 | {interest_reason}", "INTEREST")
                        self.record_watched_video(
                            bvid, title, up, aid, pic=pic_url, duration=duration,
                            source=history_source, result="兴趣不匹配，已跳过",
                            interest_reason=interest_reason,
                        )
                        await self.watch_and_sync_history(bvid)
                        await self.check_notifications_after_video()
                        continue
                    # 引擎已合并关键词匹配+AI匹配，直接使用
                    all_matched = list(dict.fromkeys(matched_interests or []))
                    if all_matched:
                        log(f"视频《{title}》匹配兴趣: {', '.join(all_matched)} | {interest_reason}", "INTEREST")
                        # [FIX] 记住这个感兴趣的视频上下文，供Agent深度搜索使用
                        self._last_interesting_topic = f"深入了解「{title[:40]}」（匹配: {', '.join(all_matched[:3])}）"
                    else:
                        log(f"视频《{title}》通过兴趣判断 | {interest_reason}", "INTEREST")

                self.record_watched_video(
                    bvid, title, up, aid, pic=pic_url, duration=duration,
                    source=history_source, result="AI 筛选通过",
                    interest_reason=interest_reason,
                )
                self.update_video_observation(
                    "读取字幕、评论与弹幕",
                    interest_reason=interest_reason,
                )

                subtitle_text = "[未读取字幕]"
                comment_text = "[未读取评论]"
                danmaku_text = ""
                c_list = []

                # [SPEED] 并行读取字幕+评论+弹幕，减少串行等待
                async def _read_subtitles_task():
                    nonlocal subtitle_text
                    self.update_video_observation("读取字幕")
                    mode_label = normalize_mode(VIDEO_UNDERSTANDING_MODE) if normalize_mode else VIDEO_UNDERSTANDING_MODE
                    log(f"开始研究视频内容... 当前视频理解模式: {mode_label}", "BRAIN")
                    success, result = await self.understand_video_for_decision(
                        bvid, title=title,
                        force_mode="subtitle_only" if _smart_token else None)
                    if success:
                        subtitle_text = result
                        # The same CC track used for understanding is exposed to
                        # the learning-status page with its real timestamps.
                        try:
                            from api.subtitles import get_cached_subtitle_timeline
                            timeline = get_cached_subtitle_timeline(bvid)
                            segments = timeline.get("segments", []) if isinstance(timeline, dict) else []
                            self.update_video_observation(
                                "字幕读取完成", subtitle_available=bool(segments),
                                subtitle_total=len(segments), subtitle_track=timeline.get("track", "") if isinstance(timeline, dict) else "",
                            )
                        except Exception:
                            self.update_video_observation("字幕读取完成", subtitle_available=False, subtitle_total=0)
                        log(f"视频理解GET: {subtitle_text[:80].strip()}...", "SUCCESS")
                    else:
                        subtitle_text = "[无可用字幕/语音内容]"
                        log(f"视频理解遇到问题: {result}", "WARN")

                async def _read_comments_task():
                    nonlocal comment_text, c_list, danmaku_text
                    self.update_video_observation("读取评论与弹幕")
                    workflow_cfg = config.get("learning_workflow", {}) if isinstance(config, dict) else {}
                    if workflow_cfg.get("read_comments", True):
                        log("看看大家都在说啥...", "BRAIN")
                        comment_text, c_list = await self._get_comments_context(aid)
                    else:
                        comment_text, c_list = "[评论读取已在学习流程中关闭]", []
                        log("评论读取已在学习流程中关闭", "COMMENT")
                    # 弹幕是否读取和抽样概率由学习流程与弹幕设置共同决定。
                    danmaku_list = await self.maybe_read_danmaku(bvid)
                    danmaku_text = ""
                    if danmaku_list:
                        danmaku_text = f"【视频弹幕（共{len(danmaku_list)}条，随机采样）】:\n" + "\n".join(
                            f"  {dm.get('text','')}" for dm in danmaku_list[:15]
                        )
                    if not c_list:
                        log("评论区空空如也...", "COMMENT")
                    else:
                        preview_parts = []
                        for i, c in enumerate(c_list[:5]):
                            part = f"#{i+1}[{c['user']}]: {c['content'][:30]}"
                            if c.get('pic_info'):
                                # 截取图片描述的前15字作为标签
                                pic_tag = c['pic_info'][:15] + "..." if len(c['pic_info']) > 15 else c['pic_info']
                                part += f" [图:{pic_tag}]"
                            preview_parts.append(part)
                        preview = ", ".join(preview_parts)
                        log(f"评论区速览({len(c_list)}条): {preview}", "COMMENT")

                await asyncio.sleep(random.uniform(0.2, 0.5))
                await asyncio.gather(_read_subtitles_task(), _read_comments_task(), return_exceptions=True)

                self.update_video_observation("信息整合与 AI 判断")
                log("信息整合，AI决策中...", "BRAIN")
                sys_prompt = self.build_dynamic_brain_prompt(up)
                # ── Phase 3: OB 画像注入到决策上下文 ──
                ob_profile_block = await self._inject_ob_profile_to_prompt()
                if ob_profile_block:
                    sys_prompt += "\n" + ob_profile_block
                # [FIX] 当视频理解失败时，提醒AI更多依赖评论区/弹幕/标题做判断
                video_fallback_hint = ""
                _st = str(subtitle_text)
                if any(kw in _st for kw in ["【无字幕无人声】", "无可用字幕", "无可用字幕/语音", "[未读取"]):
                    video_fallback_hint = "\n[WARN] 视频字幕/语音内容不可用，请主要根据评论区讨论、弹幕反应和标题来推断视频质量与价值。\n"
                context = (f"视频标题: {title}\nUP主: {up}\n封面描述: {vis_desc}\n封面印象分: {vis_score}\n"
                           f"{video_fallback_hint}"
                           f"【📺 视频内容字幕】: {subtitle_text}\n"
                           f"{comment_text}"
                           f"{danmaku_text}")

                try:
                    resp = await self._call_ai_with_retry(
                        model=_fast_model,
                        messages=[
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": context}
                        ],
                        request_timeout=60,
                        temperature=0.2,
                        max_tokens=1000,
                    )
                    raw = response_text(resp)
                    decision, used_local_fallback = parse_video_decision(
                        raw,
                        title=title,
                        subtitle_text=str(subtitle_text or ""),
                        comment_text=str(comment_text or ""),
                        danmaku_text=str(danmaku_text or ""),
                        visual_score=vis_score,
                    )
                    if used_local_fallback:
                        preview = _mask_urls((raw or "<空响应>")[:160].replace("\n", " "))
                        log(f"AI决策格式不可解析，已按内容质量本地评分 | 返回片段: {preview}", "WARN")
                except Exception as e:
                    log(f"AI决策不可用，转为本地内容评分: {_mask_urls(str(e)[:160])}", "WARN")
                    decision, _ = parse_video_decision(
                        "",
                        title=title,
                        subtitle_text=str(subtitle_text or ""),
                        comment_text=str(comment_text or ""),
                        danmaku_text=str(danmaku_text or ""),
                        visual_score=vis_score,
                    )

                mode = decision.get('mode', '普通')
                thought = decision.get('thought', '...')
                score = decision.get('score', 0)
                understanding_unavailable = str(subtitle_text).startswith("[视频理解不足:")
                if understanding_unavailable:
                    # A mismatched subtitle is evidence against understanding,
                    # not permission to infer the whole video from comments.
                    score = min(float(score or 0), 4.0)
                    thought = "字幕与视频不匹配，且未完成 ASR/视觉理解；仅记录浏览，不据此学习或互动。"
                    decision.update(score=score, thought=thought, should_learn=False, replies=[])
                    for key in ("like", "coin", "favorite", "comment", "follow", "should_like", "should_coin", "should_favorite", "should_comment"):
                        decision[key] = False
                    log("[WARN] 视频理解不足，已禁用学习归档与平台互动", "BRAIN")
                self.update_video_observation("AI 判断完成", score=score, thought=thought)

                engagement_signal = decision.get("engagement_signal", {})
                engagement_cfg = config.get("engagement", {}) if isinstance(config, dict) else {}
                if engagement_signal.get("keyword_campaign") and not engagement_cfg.get("allow_keyword_comment_campaigns", False):
                    decision["replies"] = []
                    log("互动诉求包含指定口令/领取条件，按安全策略不自动评论", "WARN")

                log(f"[{mode}模式] AI想法: {thought}", "BRAIN")
                log(f"AI最终评分: {score} / 10", "BRAIN")
                self.record_watched_video(
                    bvid, title, up, aid, pic=pic_url, duration=duration,
                    source=history_source, result="AI 筛选通过",
                    interest_reason=interest_reason, score=score,
                )
                try:
                    from services.local_favorites import auto_collect_video
                    local_favorite = auto_collect_video(
                        config,
                        {
                            "bvid": bvid,
                            "title": title,
                            "up": up,
                            "cover": pic_url,
                            "duration": duration,
                            "score": score,
                            "category": category,
                            "interest_reason": interest_reason,
                        },
                        interested=bool(interested),
                    )
                    if local_favorite.get("added"):
                        folder_name = local_favorite.get("folder", {}).get("name", "AI 精选")
                        log(f"[LOCAL_FAVORITE] 已加入本地收藏夹“{folder_name}”: 《{title}》", "SUCCESS")
                except Exception as local_favorite_error:
                    log(f"[LOCAL_FAVORITE] 本地收藏写入失败: {local_favorite_error}", "WARN")
                self.user_profile_mgr.update_impression(f"up::{up}", up, thought)

                # [*] 记录UP主印象 + 决定是否关注
                if up_uid:
                    self.record_up_impression(up, up_uid, score)
                    await self.maybe_follow_up(up_uid, up, score)
                
                # [PSYCHO] 心理画像追踪：记录本次观看
                if self.psycho_profile:
                    self.psycho_profile.tracker.record_view(
                        bvid=bvid, title=title, tags=tags or [],
                        duration=duration, up_name=up, up_uid=up_uid,
                        category=category or "", score=score,
                        interested=(score >= INTEREST_THRESHOLD)
                    )
                    self.psycho_profile.update_surface_interest(
                        title=title, tags=tags, category=category or "",
                        duration=duration, up_uid=up_uid, up_name=up,
                        score=score
                    )
                    # 触发茧房检测 + 启发式L2更新
                    self._psycho_profile_analysis_count += 1
                    if self._psycho_profile_analysis_count % PSYCHO_HEURISTIC_UPDATE_INTERVAL == 0:
                        self.psycho_profile.heuristic_update_l2()
                        metrics = self.psycho_profile.update_cocoon_metrics()
                        if metrics.get("diversity_score", 1.0) < PSYCHO_COCOON_WARNING_THRESHOLD:
                            log(f"[STATS] 内容多样性提醒: {metrics.get('cocoon_risk')} | 多样性={metrics.get('diversity_score')} | 稀少领域={metrics.get('underrepresented_areas', [])}", "WARN")
                    # 触发深度AI分析
                    if self._psycho_profile_analysis_count % PSYCHO_DEEP_ANALYZE_INTERVAL == 0 and not _smart_token:
                        task = asyncio.create_task(self.psycho_profile.deep_analyze())
                        task.add_done_callback(_safe_task_callback("deep_analyze"))
                        self.psycho_profile.detect_interest_shifts()

                self.energy -= 1

                # 🎯 学习归档：只归档高质量内容，低分/短时长/浅内容一律跳过
                learning_topic = decision.get("learning_topic")
                learn_success = False
                comment_knowledge_processed = False
                learn_text = subtitle_text
                if not learn_text or "[未读取字幕]" in str(learn_text) or "[该视频无有效CC字幕]" in str(learn_text):
                    learn_text = ""
                    if title: learn_text += f"【视频标题】{title}\n"
                    if up: learn_text += f"【UP主】{up}\n"
                    if thought: learn_text += f"【AI判断】{thought}\n"
                    if danmaku_text: learn_text += f"【弹幕】{danmaku_text}\n"
                    if comment_text and comment_text != "[未读取评论]": learn_text += f"【评论】{comment_text}\n"
                    learn_text = learn_text.strip()
                
                # 🔒 三层质量门槛：分数 + 时长 + 内容长度
                skip_reason = None
                if score < LEARN_MIN_SCORE:
                    skip_reason = f"分数过低({score:.1f}<{LEARN_MIN_SCORE})"
                elif duration > 0 and duration < LEARN_MIN_DURATION_SECONDS:
                    skip_reason = f"视频太短({duration}s<{LEARN_MIN_DURATION_SECONDS}s)"
                elif not learn_text or len(learn_text) < 150:
                    skip_reason = f"可学内容不足({len(learn_text) if learn_text else 0}字<150)"
                
                if skip_reason:
                    log(f"📭 跳过学习归档: {skip_reason} | 《{title}》", "LEARN")
                elif learning_topic and learn_text and len(learn_text) > 20:
                    try:
                        _desc = getattr(self, "_last_video_desc", "")
                        # 💬 先收集评论区知识（返回摘要文本，不写文件）
                        comment_summ = None
                        if c_list and len(c_list) >= 5 and (comment_text and comment_text != "[未读取评论]"):
                            try:
                                comment_knowledge_processed = True
                                comment_summ, reason = await self.learn_from_comments(
                                    bvid, title, up, video_url, comment_text, c_list,
                                    topic_suggestion=learning_topic, score=score
                                )
                                if comment_summ:
                                    log("评论区知识已提炼，将合并到归档", "LEARN")
                            except Exception as clearn_e:
                                log(f"评论区知识收集异常: {clearn_e}", "WARN")
                        # 归档（评论摘要合并写入视频笔记）
                        learn_success = await self.learn_from_video(
                            bvid, title, up, video_url, learn_text, learning_topic,
                            video_desc=_desc, score=score, comment_summary=comment_summ
                        )
                        if learn_success:
                            self.mood_mgr.shift("学到有价值内容", 2)
                            if score >= INTEREST_THRESHOLD:
                                self.energy -= 2
                                log(f"学习归档消耗2点精力，当前剩余精力: {self.energy}%", "INFO")
                    except Exception as learn_e:
                        log(f"学习归档异常: {learn_e}", "WARN")

                # ★ 评论区知识收集：从讨论中提取有价值的信息
                if (not comment_knowledge_processed and c_list and len(c_list) >= 3
                        and (comment_text and comment_text != "[未读取评论]")):
                    try:
                        comment_summ2, reason2 = await self.learn_from_comments(
                            bvid, title, up, video_url, comment_text, c_list,
                            topic_suggestion=learning_topic or (decision.get("learning_topic") or "评论知识")
                        )
                        if comment_summ2:
                            log("评论区知识收集消耗1点精力", "INFO")
                            self.energy -= 1
                        else:
                            log(f"评论知识跳过: {reason2}", "DEBUG")
                    except Exception as clearn_e:
                        log(f"评论区知识收集异常: {clearn_e}", "WARN")

                if score < INTEREST_THRESHOLD:
                    if learn_success:
                        log(
                            f"视频已学习归档；分数({score})未达到互动阈值({INTEREST_THRESHOLD})，"
                            "本次不点赞、不评论。",
                            "LEARN",
                        )
                        self.record_session_event(
                            "video_learned_no_interaction",
                            title=title,
                            up=up,
                            score=score,
                            thought=thought,
                            reason="已归档但未达到互动阈值",
                            url=video_url,
                        )
                    else:
                        self.mood_mgr.shift("刷到低分视频", -1)
                        log(f"分数({score})未达到学习或互动阈值，划走~ (消耗1点精力, 剩余: {self.energy}%)", "INFO")
                        # [PSYCHO] 只有未学到内容的视频才记录为跳过和避雷。
                        if self.psycho_profile:
                            self.psycho_profile.tracker.record_skip(bvid, title, reason=f"低于兴趣阈值(score={score})")
                            self.psycho_profile.aversion.report_aversion(
                                bvid=bvid, title=title, reason=f"低分({score})",
                                tags=tags, up_uid=up_uid, up_name=up
                            )
                        self.record_session_event(
                            "video_skipped",
                            title=title,
                            up=up,
                            score=score,
                            thought=thought,
                            reason="低于兴趣阈值",
                            url=video_url
                        )
                    await self.maybe_auto_diary()
                    await self.maybe_self_evolve()

                    # ── Phase 3: 定期同步知识盲区 ──
                    if self.ob_enabled and self.ob_client:
                        now_ts = datetime.now().timestamp()
                        if now_ts - getattr(self, '_ob_last_gap_sync', 0) > 3600:
                            self._ob_last_gap_sync = now_ts
                            await self._push_knowledge_gaps_to_ob()

                    await self.watch_and_sync_history(bvid)
                    await self.check_notifications_after_video()
                    # ── OpenBiliClaw 反馈：已学习或跳过 ──
                    ob_id = target.get("_ob_id", 0) if isinstance(target, dict) else 0
                    await self._report_to_ob(bvid, learn_success, score, learning_topic or "")
                    if ob_id:
                        await self._feedback_to_ob(ob_id, score)
                    # ── Phase 4: 审计记录（跳过视频）──
                    video_source = target.get("_source", "native") if isinstance(target, dict) else "native"
                    if hasattr(self, '_record_ob_audit'):
                        self._record_ob_audit(
                            source=video_source, bvid=bvid, title=title,
                            score=score, learned=learn_success,
                            skip_reason=("已归档但未达到互动阈值" if learn_success
                                         else f"低于兴趣阈值(score={score})"),
                            up_name=up, duration=duration
                        )
                        await self._maybe_audit_report()
                    continue

                action_log = []
                v = Video(bvid=bvid, credential=self.credential)

                # 随机检定：RANDOM_ENABLED=False 时全部通过（只看分数阈值），True 时进行概率检定
                # 高分保底：score >= 8.0 时跳过概率检定，AI明确想互动就直接执行
                HIGH_SCORE_GUARANTEE = 8.0
                _high_score = score >= HIGH_SCORE_GUARANTEE
                coin_check = True if (_high_score or not RANDOM_ENABLED) else (random.random() < PROB_COIN)
                fav_check = True if (_high_score or not RANDOM_ENABLED) else (random.random() < PROB_FAV)
                reply_check = True if (_high_score or not RANDOM_ENABLED) else (random.random() < PROB_REPLY_TRIGGER)
                like_solo_check = True if (_high_score or not RANDOM_ENABLED) else (random.random() < PROB_LIKE_SOLO)

                ai_wants_coin = decision.get('coin_intention', False)
                ai_wants_fav = decision.get('fav_intention', False)
                ai_wants_reply = bool(decision.get('replies', []))
                video_comment_allowed, video_comment_reason, video_comment_hits = ReplySafetyGuard().review_video_for_comment(
                    title=title,
                    up=up,
                    subtitle=subtitle_text,
                    comments=json.dumps(c_list[:5], ensure_ascii=False)
                )
                if not video_comment_allowed:
                    if ai_wants_reply:
                        log(f"视频命中涉政/敏感内容，强制清空评论意图: {video_comment_reason} | 命中: {', '.join(video_comment_hits)}", "WARN")
                    decision["replies"] = []
                    ai_wants_reply = False

                # 投币冷却检查
                coin_cooldown_ok = True
                if COIN_COOLDOWN_MINUTES > 0 and hasattr(self, 'last_coin_at'):
                    elapsed = (datetime.now() - self.last_coin_at).total_seconds() / 60
                    coin_cooldown_ok = elapsed >= COIN_COOLDOWN_MINUTES
                
                # 每小时投币上限检查
                coin_hourly_ok = True
                if COIN_MAX_PER_HOUR > 0 and hasattr(self, '_coin_hour_timestamps'):
                    now = datetime.now()
                    # 清理超过1小时的时间戳
                    self._coin_hour_timestamps = [ts for ts in self._coin_hour_timestamps if (now - ts).total_seconds() < 3600]
                    coin_hourly_ok = len(self._coin_hour_timestamps) < COIN_MAX_PER_HOUR
                
                do_coin = ai_wants_coin and score >= COIN_THRESHOLD and self.coins_spent < MAX_COINS_DAILY and coin_check and coin_cooldown_ok and coin_hourly_ok
                do_fav = ai_wants_fav and score >= FAV_THRESHOLD and fav_check
                do_replies = decision.get('replies', []) if (ai_wants_reply and reply_check) else []
                do_like_trigger = do_fav or do_coin or bool(do_replies) or (score >= 6.5 and like_solo_check)

                if RANDOM_ENABLED:
                    coin_limit_reason = ""
                    if not coin_cooldown_ok: coin_limit_reason = " 冷却中"
                    if not coin_hourly_ok: coin_limit_reason = " 小时上限"
                    _guarantee_tag = " 🛡️高分保底" if _high_score else ""
                    log(f"🎲 投币 | 意图:{'✓' if ai_wants_coin else '✗'} 分数:{'✓' if score >= COIN_THRESHOLD else '✗'} 限额:{'✓' if self.coins_spent < MAX_COINS_DAILY else '✗'}{coin_limit_reason} 检定({int(PROB_COIN*100)}%/{'保底' if _high_score else '骰子'}):{'✓' if coin_check else '✗'} => {'执行' if do_coin else '跳过'}{_guarantee_tag}", "DIAG")
                    log(f"🎲 收藏 | 意图:{'✓' if ai_wants_fav else '✗'} 分数:{'✓' if score >= FAV_THRESHOLD else '✗'} 检定({int(PROB_FAV*100)}%/{'保底' if _high_score else '骰子'}):{'✓' if fav_check else '✗'} => {'执行' if do_fav else '跳过'}{_guarantee_tag}", "DIAG")
                    log(f"🎲 评论 | 意图:{'✓' if ai_wants_reply else '✗'} 检定({int(PROB_REPLY_TRIGGER*100)}%/{'保底' if _high_score else '骰子'}):{'✓' if reply_check else '✗'} => {'执行' if bool(do_replies) else '跳过'}{_guarantee_tag}", "DIAG")
                    log(f"🎲 点赞 | 收藏:{'✓' if do_fav else '✗'} 投币:{'✓' if do_coin else '✗'} 评论:{'✓' if bool(do_replies) else '✗'} 单独(分数/检定):{'✓' if score >= 6.5 else '✗'}/{'✓' if like_solo_check else '✗'} => {'执行' if do_like_trigger else '跳过'}", "DIAG")
                else:
                    coin_limit_reason = ""
                    if not coin_cooldown_ok: coin_limit_reason = " 冷却中"
                    if not coin_hourly_ok: coin_limit_reason = " 小时上限"
                    log(f"🔒 投币 | 意图:{'✓' if ai_wants_coin else '✗'} 分数:{'✓' if score >= COIN_THRESHOLD else '✗'} 限额:{'✓' if self.coins_spent < MAX_COINS_DAILY else '✗'}{coin_limit_reason} => {'执行' if do_coin else '跳过'}", "DIAG")
                    log(f"🔒 收藏 | 意图:{'✓' if ai_wants_fav else '✗'} 分数:{'✓' if score >= FAV_THRESHOLD else '✗'} => {'执行' if do_fav else '跳过'}", "DIAG")
                    log(f"🔒 评论 | 意图:{'✓' if ai_wants_reply else '✗'} => {'执行' if bool(do_replies) else '跳过'}", "DIAG")
                    log(f"🔒 点赞 | 收藏:{'✓' if do_fav else '✗'} 投币:{'✓' if do_coin else '✗'} 评论:{'✓' if bool(do_replies) else '✗'} 单独(分数):{'✓' if score >= 6.5 else '✗'} => {'执行' if do_like_trigger else '跳过'}", "DIAG")

                # [FIX] 学习归档已提前执行（在分数门槛之前，所有视频都学）
                if learn_success:
                    if self.private_message_mgr:
                        try:
                            from services.owner_share import OwnerShareService
                            share_result = await OwnerShareService().share_learned_video(
                                lambda receiver_id, text: self.private_message_mgr.send_reply(
                                    receiver_id,
                                    text,
                                    audit_payload={
                                        "owner_share": True,
                                        "owner_share_bvid": bvid,
                                        "owner_share_title": title,
                                    },
                                ),
                                bvid=bvid,
                                title=title,
                                video_url=video_url,
                                score=score,
                                learning_topic=learning_topic or "",
                                thought=thought or "",
                            )
                            if share_result["status"] == "sent":
                                log(f"[Owner share] Sent learned video: {title}", "SUCCESS")
                            elif share_result["status"] == "queued":
                                log(f"[Owner share] Queued for review: {title}", "INFO")
                            elif share_result["status"] == "failed":
                                log(f"[Owner share] Platform send failed: {share_result.get('reason', 'unknown')}", "WARN")
                            else:
                                log(f"[Owner share] Skipped: {share_result.get('reason', 'not triggered')}", "DEBUG")
                        except Exception as share_error:
                            log(f"[Owner share] Share failed without affecting learning: {share_error}", "WARN")
                    action_log.append("学习归档")
                    # 异步非阻塞：后台Agent继续探索
                    self.last_agent_run_at = datetime.now()
                    goal1 = f"继续了解这个主题：{learning_topic}。搜索相关视频，先看1-3个，如果内容有价值再继续多看。"
                    task = asyncio.create_task(self._agent_goal_async(goal1, score=score))
                    task.add_done_callback(_safe_task_callback("agent_goal1"))

                # 🧭 好奇心驱动深度搜索：遇到感兴趣/不了解的内容，B站搜索深入学（动态2-10个视频）
                if CURIOSITY_DEEP_DIVE_ENABLED and not _smart_token and score >= CURIOSITY_DEEP_DIVE_MIN_SCORE:
                    dive_cooldown_ok = (datetime.now() - self._last_curiosity_dive_at).total_seconds() / 60 >= CURIOSITY_DEEP_DIVE_COOLDOWN_MINUTES
                    today_str = datetime.now().strftime("%Y%m%d")
                    if self._curiosity_dive_date != today_str:
                        self._curiosity_dive_count_today = 0
                        self._curiosity_dive_date = today_str
                    
                    # 触发条件：高分视频AND(有学习主题OR AI表示想深入了解OR随机触发)
                    dive_trigger = (learning_topic or
                                   any(w in (thought + title).lower() for w in ["想了解", "深入", "探索", "好奇", "不懂", "学习", "研究"]) or
                                   random.random() < CURIOSITY_DEEP_DIVE_PROB)
                    
                    if dive_trigger and dive_cooldown_ok and self._curiosity_dive_count_today < 3 and self.energy >= 10:
                        dive_topic = learning_topic or title[:20]
                        log(f"🧭 触发好奇心深度搜索！主题: '{dive_topic}' (评分:{score})", "LEARN")
                        self._last_curiosity_dive_at = datetime.now()
                        self._curiosity_dive_count_today += 1
                        self.energy -= 3
                        await self.curiosity_deep_dive(dive_topic, trigger_title=title, trigger_bvid=bvid)

                if not learn_success and score >= AGENT_AUTO_MIN_SCORE and any(word in title.lower() + " " + thought.lower() for word in ["模型", "ai", "gpt", "agent", "机器人", "开源", "教程", "工具", "开发"]):
                    # [FIX] 异步非阻塞：后台探索，不卡主循环
                    self.last_agent_run_at = datetime.now()
                    goal2 = f"深入了解这个主题：{title}。搜索相关视频，先看1-3个，有价值再继续。"
                    task = asyncio.create_task(self._agent_goal_async(goal2, score=score))
                    task.add_done_callback(_safe_task_callback("agent_goal2"))

                if decision.get('remember_up') and up not in self.memory['known_ups']:
                    self.remember_up(up, uid=up_uid)

                # [*] 自动喜欢UP主：高分视频且UP主有趣 → 标记为喜欢
                if score >= 8.0 and up_uid and up and not self.is_favorite_up(up):
                    fav_prob = 0.12 + (score - 8.0) * 0.08  # score=8→12%, score=10→28%
                    if random.random() < fav_prob:
                        self.favorite_up(up, uid=up_uid)
                        action_log.append("[STAR]喜欢UP主")
                        log(f"[STAR] 自动标记喜欢的UP主: @{up} (UID:{up_uid}) [评分:{score}, 概率:{fav_prob:.0%}]", "FAVORITE")

                if do_like_trigger:
                    from services.like_review import LikeReviewInbox, requires_review
                    if requires_review(config, "video_like"):
                        LikeReviewInbox(DATA_DIR).propose(bvid, title, up, score, thought, video_url)
                        log("AI 点赞建议已进入审核收件箱，等待用户决定", "INFO")
                        do_like_trigger = False

                if do_like_trigger and video_liking_enabled():
                    try:
                        await asyncio.sleep(random.uniform(2, 4))
                        has_liked = await v.has_liked()
                        if not has_liked:
                            log("正在尝试点赞...", "ACT")
                            aid = v.get_aid()
                            await _bili_throttle()  # 🔒 全局节流
                            await v.like(status=True)
                            log("点赞成功！", "SUCCESS")
                            action_log.append("点赞")
                            if self.psycho_profile:
                                self.psycho_profile.tracker.record_interaction("like", bvid, title, up)
                                self.psycho_profile.update_surface_interest(
                                    title=title, tags=tags, up_uid=up_uid, up_name=up,
                                    liked=True, score=score
                                )
                            self.user_profile_mgr.adjust_affinity(f"up::{up}", up, 1, "点赞视频")
                            # 存入互动历史，供回顾复习（带评分）
                            self.add_history_video(str(bvid), title, up, aid, "like", score, pic=pic_url)
                        else:
                            log("视频已经点过赞了。", "INFO")
                    except Exception as e:
                        log(f"点赞失败 (可能受限): {e}", "ERROR")

                if do_fav:
                    from services.like_review import ActionReviewInbox, requires_review
                    if requires_review(config, "favorite"):
                        ActionReviewInbox(DATA_DIR).propose(
                            "favorite", f"收藏视频《{title}》", thought,
                            payload={"bvid": bvid}, metadata={"up_name": up, "score": score, "url": video_url},
                            dedupe_key=f"favorite:{bvid}")
                        log("AI 收藏建议已进入行为审核", "INFO")
                        do_fav = False

                if do_fav:
                    try:
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        has_favorited = await v.has_favoured()

                        if not has_favorited:
                            await _bili_throttle("收藏夹列表")  # 🔒 全局节流
                            fav_list_data = await favorite_list.get_video_favorite_list(uid=self.credential.dedeuserid, credential=self.credential)
                            if fav_list_data and fav_list_data.get('list'):
                                default_folder_id = fav_list_data['list'][0]['id']
                                log(f"正在尝试收藏到默认收藏夹...", "ACT")
                                aid = v.get_aid()
                                await _bili_throttle()  # 🔒 全局节流
                                await v.set_favorite(add_media_ids=[default_folder_id])
                                log("收藏成功！", "SUCCESS")
                                action_log.append("收藏")
                                if self.psycho_profile:
                                    self.psycho_profile.tracker.record_interaction("favorite", bvid, title, up)
                                    self.psycho_profile.update_surface_interest(
                                        title=title, tags=tags, up_uid=up_uid, up_name=up,
                                        favorited=True, score=score
                                )
                                self.user_profile_mgr.adjust_affinity(f"up::{up}", up, 2, "收藏视频")
                                # 存入互动历史，供回顾复习（带评分）
                                self.add_history_video(str(bvid), title, up, aid, "fav", score, pic=pic_url)
                            else:
                                log("未能获取到收藏夹列表，无法收藏。", "WARN")
                        else:
                            log("视频已在收藏夹中。", "INFO")
                    except Exception as e:
                        log(f"收藏失败: {e}", "ERROR")

                if do_coin:
                    from services.like_review import ActionReviewInbox, requires_review
                    if requires_review(config, "coin"):
                        ActionReviewInbox(DATA_DIR).propose(
                            "coin", f"为视频《{title}》投币", thought,
                            payload={"bvid": bvid, "num": 1}, metadata={"up_name": up, "score": score, "url": video_url},
                            dedupe_key=f"coin:{bvid}")
                        log("AI 投币建议已进入行为审核", "INFO")
                        do_coin = False

                if do_coin:
                    try:
                        await asyncio.sleep(random.uniform(2, 4))
                        aid = v.get_aid()
                        await _bili_throttle()  # 🔒 全局节流
                        await v.pay_coin(num=1, like=True)
                        self.coins_spent += 1
                        self.last_coin_at = datetime.now()  # 记录投币时间（冷却用）
                        if hasattr(self, '_coin_hour_timestamps'):
                            self._coin_hour_timestamps.append(datetime.now())  # 每小时上限追踪
                            # 清理超过1小时的
                            self._coin_hour_timestamps = [ts for ts in self._coin_hour_timestamps if (datetime.now() - ts).total_seconds() < 3600]
                        log(f"投币成功！今日已投 {self.coins_spent} 枚。", "COIN")
                        action_log.append("投币")
                        if self.psycho_profile:
                            self.psycho_profile.tracker.record_interaction("coin", bvid, title, up)
                            self.psycho_profile.update_surface_interest(
                                title=title, tags=tags, up_uid=up_uid, up_name=up,
                                coined=True, score=score
                            )
                        self.user_profile_mgr.adjust_affinity(f"up::{up}", up, 3, "投币支持")
                    except Exception as e:
                        log(f"投币失败: {e}", "ERROR")

                # 回复他人评论的功能
                if do_replies and PROB_COMMENT_OTHERS > 0 and public_commenting_enabled():
                    for reply in do_replies:
                        try:
                            target_id = reply.get('target_id', 0)
                            reply_content = reply.get('content', '')
                            
                            if target_id and reply_content:
                                target_comment = next((item for item in c_list if str(item.get("id")) == str(target_id)), {})
                                if not target_comment:
                                    # The AI is allowed to choose only from the
                                    # current comment snapshot. Do not post to a
                                    # stale or hallucinated comment ID.
                                    log(f"评论目标已不在当前列表，跳过回复 ID:{target_id}", "WARN")
                                    continue
                                incoming_text = target_comment.get("content", "")
                                pacing_ok, pacing_reason = self.comment_mgr._should_reply_user(target_comment.get("user_id"), incoming_text) if self.comment_mgr else (True, "通过")
                                if not pacing_ok:
                                    log(f"视频评论节奏控制跳过 ID:{target_id}: {pacing_reason}", "COMMENT")
                                    continue
                                reply_content = ensure_ai_marker(reply_content)
                                ok, reason, hits = ReplySafetyGuard().review(incoming_text, reply_content)
                                if not ok:
                                    log(f"已拦截视频评论回复 ID:{target_id}: {reason} | 命中: {', '.join(hits)}", "WARN")
                                    if self.comment_mgr:
                                        self.comment_mgr.log_blocked_reply(target_id, incoming_text, reply_content, reason, hits, target_comment.get("user", "视频评论"))
                                    continue

                                log(f"正在回复评论 ID:{target_id}: {reply_content[:50]}...", "COMMENT")
                                await asyncio.sleep(human_reply_delay())
                                if COMMENT_MODE == "simulate":
                                    log(f"[模拟] 拟回复视频评论 ID:{target_id}: {reply_content[:50]}...", "SIMULATE")
                                else:
                                    await _bili_throttle()  # 🔒 全局节流
                                    await comment.send_comment(
                                        text=reply_content,
                                        oid=aid,
                                        type_=CommentResourceType.VIDEO,
                                        root=target_id,
                                        parent=None,
                                        credential=self.credential
                                    )
                                    log("回复评论成功！", "SUCCESS")
                                action_log.append(f"回复评论({target_id})")
                                self.mood_mgr.shift("成功参与评论区互动", 1)
                                
                                # 记录评论日志
                                if self.comment_mgr:
                                    self.comment_mgr.log_interaction(target_id, "reply", reply_content, "视频评论")
                                    self.comment_mgr._mark_user_replied(target_comment.get("user_id"))
                                
                                await asyncio.sleep(random.uniform(1, 3))
                        except Exception as e:
                            log(f"回复评论失败: {e}", "ERROR")

                if action_log:
                    self.energy -= 3
                    self.mood_mgr.shift("主动互动完成", 1)
                    log(f"深度交互额外消耗3点精力，当前剩余精力: {self.energy}%", "INFO")
                    self.write_journal(title, up, score, f"[{mode}] {thought}", " + ".join(action_log), video_url)
                else:
                    self.mood_mgr.shift("观望未互动", -1)
                    log("所有互动检定均未通过或无需操作，本次不进行额外操作。", "INFO")

                self.record_session_event(
                    "video_processed",
                    title=title,
                    up=up,
                    score=score,
                    mode=mode,
                    thought=thought,
                    actions=action_log,
                    mood=self.mood_mgr.get_current(),
                    url=video_url
                )
                await self.maybe_auto_diary()
                await self.maybe_self_evolve()

                # ── Phase 3: 定期同步知识盲区到 OB（冷却间隔控制）──
                if self.ob_enabled and self.ob_client:
                    now_ts = datetime.now().timestamp()
                    last_sync = getattr(self, '_ob_last_gap_sync', 0)
                    if now_ts - last_sync > 3600:  # 每小时同步一次
                        self._ob_last_gap_sync = now_ts
                        await self._push_knowledge_gaps_to_ob()

                await self.watch_and_sync_history(bvid)
                await self.check_notifications_after_video()

                # ── OpenBiliClaw 反馈回传 ──
                ob_id = target.get("_ob_id", 0) if isinstance(target, dict) else 0
                learned = learn_success
                if learned:
                    self.videos_learned += 1
                await self._report_to_ob(bvid, learned, score, learning_topic or "")
                if ob_id:
                    await self._feedback_to_ob(ob_id, score)

                # ── Phase 4: 审计 & AB 对比记录 ──
                video_source = target.get("_source", "native") if isinstance(target, dict) else "native"
                if hasattr(self, '_record_ob_audit'):
                    self._record_ob_audit(
                        source=video_source, bvid=bvid, title=title,
                        score=score, learned=learn_success,
                        up_name=up, duration=duration,
                        topic=learning_topic or ""
                    )
                    await self._maybe_audit_report()

                # 🎯 记录观看标签（兴趣引擎新颖度追踪）
                try:
                    from services.interest_engine import get_engine
                    engine = get_engine()
                    engine.record_watched(
                        tags=",".join(tags) if tags else "",
                        category=category
                    )
                    # 记录标题供AI关键词建议使用
                    self._recent_watched_titles.append(title)
                    if len(self._recent_watched_titles) > 100:
                        self._recent_watched_titles = self._recent_watched_titles[-50:]
                    # AI关键词建议检查（每N个视频一次）
                    if not _smart_token and engine.should_suggest_keywords():
                        recent_titles = getattr(self, "_recent_watched_titles", [])[-15:]
                        prompt = engine.generate_suggest_prompt(recent_titles)
                        try:
                            resp = await self._call_ai_with_retry(
                                model=MODEL_BRAIN,
                                messages=[
                                    {"role": "system", "content": "你是兴趣建议器，基于观看历史建议新关键词。只输出合法JSON。"},
                                    {"role": "user", "content": prompt}
                                ],
                                request_timeout=60
                            )
                            data = decode_ai_mapping(response_text(resp), ("suggestions",)) or {}
                            suggestions = data.get("suggestions", [])
                            if suggestions:
                                engine.apply_ai_suggestions(suggestions)
                        except Exception as ai_sugg_e:
                            log(f"AI兴趣建议解析异常(非致命): {str(ai_sugg_e)[:120]}", "DEBUG")
                except Exception as engine_e:
                    log(f"兴趣引擎追踪异常(非致命): {str(engine_e)[:120]}", "DEBUG")

                # 📚 知识库定期审查：每N个视频后随机抽查归档质量
                if KNOWLEDGE_REVIEW_INTERVAL > 0 and not _smart_token:
                    self._knowledge_review_countdown -= 1
                    if self._knowledge_review_countdown <= 0:
                        self._knowledge_review_countdown = KNOWLEDGE_REVIEW_INTERVAL
                        try:
                            await self._review_knowledge_periodically()
                        except Exception as review_e:
                            log(f"知识库定期审查异常: {review_e}", "WARN")

            except asyncio.CancelledError:
                log("主循环被取消 (CancelledError)，正常退出", "WARN")
                raise  # 重新抛出，让 asyncio.run() 正确处理
            except KeyboardInterrupt:
                log("主循环收到中断信号，正常退出", "WARN")
                raise
            except Exception as e:
                log(f"主循环发生严重错误: {e}", "ERROR")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(3)

        return completion_action
