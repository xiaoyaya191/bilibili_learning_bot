"""brain/_brain_session.py — AgentBrain 会话管理 mixin (能量/评论/私信/弹幕/UP关注/登录)"""
from brain._mixin_imports import *
from api.throttle import _bili_throttle

class BrainSessionMixin:
    """能量恢复、评论检查、私信处理、弹幕互动、UP关注、登录初始化"""

    async def watch_and_sync_history(self, bvid):
        sec = random.uniform(VIDEO_INTERVAL_MIN, VIDEO_INTERVAL_MAX)
        log(f"短暂休息 {sec:.1f} 秒后继续...", "INFO")
        try:
            res = await self.bili.report_history(bvid, played_time=random.randint(60,120))
            if res.get('code') == 0:
                log("已同步观看历史 (手机可见)", "NOTE")
            else:
                log(f"历史记录同步失败: {res.get('message')}", "WARN")
        except Exception as e:
            log(f"上报历史时异常: {e}", "ERROR")
        await asyncio.sleep(sec)

    async def energy_recovery_session(self):
        log(f"精力耗尽 ({self.energy}%)，进入恢复模式... [FAST]", "ENERGY")
        recovery_rounds = random.randint(ROUNDS_MIN, ROUNDS_MAX)
        log(f"预计恢复 {recovery_rounds} 轮，请耐心等待...", "ENERGY")
        for round_num in range(1, recovery_rounds + 1):
            energy_gain = random.randint(ENERGY_RECOVERY_MIN, ENERGY_RECOVERY_MAX)
            self.energy = min(MAX_ENERGY, self.energy + energy_gain)
            round_interval = random.randint(ROUND_INTERVAL_MIN, ROUND_INTERVAL_MAX)
            log(f"第 {round_num}/{recovery_rounds} 轮恢复: +{energy_gain}% → {self.energy}% (等待{round_interval}秒)", "ENERGY")
            if round_num < recovery_rounds:
                log(f"下次恢复倒计时: {round_interval}秒...", "ENERGY")
                await asyncio.sleep(round_interval)
            self.last_energy_recovery = datetime.now()
        log(f"恢复完成！当前精力: {self.energy}%，准备继续工作！", "SUCCESS")

    async def check_and_handle_comments(self):
        if not COMMENT_CHECK_ENABLED:
            return 0
        if not self.comment_mgr:
            return 0
        now = datetime.now()
        if self.last_comment_check and (now - self.last_comment_check).total_seconds() < COMMENT_CHECK_INTERVAL:
            return 0
        try:
            processed = await self.comment_mgr.process_new_comments(self.bili)
            if processed > 0:
                log(f"本次处理了 {processed} 条评论互动", "COMMENT")
                self.energy -= processed
                if self.energy < 0:
                    self.energy = 0
                log(f"评论互动消耗 {processed} 点精力，剩余: {self.energy}%", "ENERGY")
            return processed
        except Exception as e:
            log(f"检查评论失败: {e}", "ERROR")
            return 0
        finally:
            self.last_comment_check = now

    async def check_and_handle_private_messages(self):
        if not PRIVATE_MESSAGE_ENABLED:
            return 0
        now = datetime.now()
        if self.last_private_message_check and (now - self.last_private_message_check).total_seconds() < PRIVATE_MESSAGE_CHECK_INTERVAL:
            return 0
        if not self.private_message_mgr:
            return 0
        try:
            processed = await self.private_message_mgr.process_new_messages()
            if processed > 0:
                log(f"本次处理了 {processed} 条私信", "DM")
            return processed
        except Exception as e:
            log(f"检查私信失败: {e}", "ERROR")
            return 0
        finally:
            self.last_private_message_check = now

    # ── 看完视频后检查通知 (@我/私信/自己评论) ──
    async def check_notifications_after_video(self):
        """每看完一个视频后检查通知：@提及 + 私信 + 自己视频评论。
        可配置开关，可配置冷却时间避免频繁API请求。"""
        if not PER_VIDEO_CHECK_ENABLED:
            return

        now = datetime.now()
        if self._last_per_video_check:
            elapsed = (now - self._last_per_video_check).total_seconds()
            if elapsed < PER_VIDEO_CHECK_COOLDOWN:
                return
        self._last_per_video_check = now

        at_count = dm_count = comment_count = 0

        # ── 1. 检查 @通知 ──
        if PER_VIDEO_CHECK_AT_NOTIFICATIONS:
            try:
                at_count = await self._check_at_notifications_quick()
                if at_count > 0:
                    log(f"[Ntf] @通知: 发现 {at_count} 条新@提及", "NOTIFY")
            except Exception as e:
                log(f"[Ntf] @通知检查异常: {e}", "WARN")

        # ── 2. 检查私信（强制检查，忽略冷却） ──
        if PER_VIDEO_CHECK_PRIVATE_MESSAGES and PRIVATE_MESSAGE_ENABLED:
            try:
                # 临时重置冷却以强制检查
                saved_last = self.last_private_message_check
                self.last_private_message_check = None
                dm_count = await self.check_and_handle_private_messages()
                if dm_count == 0:
                    self.last_private_message_check = saved_last
                if dm_count > 0:
                    log(f"[Ntf] 私信: 处理了 {dm_count} 条新私信", "NOTIFY")
            except Exception as e:
                log(f"[Ntf] 私信检查异常: {e}", "WARN")

        # ── 3. 检查自己视频评论（强制检查，忽略冷却） ──
        if PER_VIDEO_CHECK_OWN_COMMENTS and COMMENT_CHECK_ENABLED:
            try:
                saved_last = self.last_comment_check
                self.last_comment_check = None
                comment_count = await self.check_and_handle_comments()
                if comment_count == 0:
                    self.last_comment_check = saved_last
                if comment_count > 0:
                    log(f"[Ntf] 评论: 处理了 {comment_count} 条新评论", "NOTIFY")
            except Exception as e:
                log(f"[Ntf] 评论检查异常: {e}", "WARN")

    async def _check_at_notifications_quick(self) -> int:
        """快速检查@我通知（轻量版，复用 standby.py 逻辑）。
        返回: 发现的新通知数"""
        try:
            cookies = self.bili.cookies if hasattr(self.bili, 'cookies') and self.bili.cookies else {}
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://message.bilibili.com/',
            }
            async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=15.0) as client:
                r = await client.get(
                    'https://api.bilibili.com/x/msg/at',
                    params={'pn': 1, 'ps': PER_VIDEO_CHECK_MAX_AT}
                )
                d = r.json()
                if d.get('code') != 0:
                    return 0

                raw_items = d.get('data', {}).get('items', [])
                new_count = 0
                for it in raw_items:
                    biz = str(it.get('business', ''))
                    if biz not in ('reply', '1', '2', '3', '4', '5', '6', '7'):
                        continue
                    at_id = str(it.get('id', ''))
                    # 检查是否已处理过
                    if not hasattr(self, '_processed_at_ids'):
                        self._processed_at_ids = set()
                    if at_id in self._processed_at_ids:
                        continue
                    self._processed_at_ids.add(at_id)
                    # 限制缓存大小
                    if len(self._processed_at_ids) > 500:
                        # 保留最新的250条
                        self._processed_at_ids = set(sorted(self._processed_at_ids)[-250:])

                    i = it.get('item', {})
                    raw_content = i.get('content', '')
                    uname = i.get('reply_name', '') or '未知用户'
                    comment_text = ""
                    try:
                        cj = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
                        comment_text = cj.get('message', '') or cj.get('content', '') or raw_content
                    except Exception:
                        comment_text = raw_content

                    log(f"[Ntf] @通知 #{new_count+1}: @{uname}: {comment_text[:80]}", "NOTIFY")

                    # 检查是否触发关键词总结
                    standby_cfg = {}
                    standby_file = os.path.join(DATA_DIR, "standby_config.json")
                    if os.path.exists(standby_file):
                        try:
                            with open(standby_file, 'r', encoding='utf-8') as f:
                                standby_cfg = json.load(f)
                        except Exception:
                            pass

                    at_keywords = standby_cfg.get('at_trigger_keywords', ['总结', '总结一下', '分析', '概括', '讲解', '归纳', '梳理'])
                    if standby_cfg.get('at_trigger_enabled', True) and standby_cfg.get('notification_mode', True):
                        lowered = comment_text.lower()
                        for kw in at_keywords:
                            if kw.lower() in lowered:
                                log(f"[Ntf] ⚡ 检测到@触发关键词 '{kw}' — 请用待机模式处理", "NOTIFY")
                                break

                    new_count += 1

                return new_count
        except Exception as e:
            log(f"[Ntf] @通知API调用失败: {e}", "DEBUG")
            return 0

    # ── 主动聊天 ──
    async def maybe_initiate_chat(self):
        if not ACTIVE_CHAT_ENABLED:
            return
        if not PRIVATE_MESSAGE_ENABLED or not PRIVATE_MESSAGE_AUTO_REPLY:
            return
        if not self.private_message_mgr:
            return
        self._active_chat_count += 1
        if self._active_chat_count > ACTIVE_CHAT_MAX_PER_SESSION:
            return
        elapsed = (datetime.now() - self._last_active_chat_at).total_seconds() / 60
        if elapsed < ACTIVE_CHAT_COOLDOWN_MINUTES:
            return
        if random.random() >= PROB_INITIATE_CHAT:
            return
        try:
            target = await self.private_message_mgr.get_chat_target(self.bili)
            if not target:
                return
            target_uid = target.get("uid")
            target_name = target.get("name", str(target_uid))
            log(f"[MSG] 主动发起聊天 @{target_name}", "CHAT")
            await self._compose_active_chat(target_uid, target_name, target)
        except Exception as e:
            log(f"主动聊天异常: {e}", "WARN")

    async def _compose_active_chat(self, target_uid, target_name, target):
        try:
            persona_block = self.persona_mgr.build_prompt_block()
            mood_block = self.mood_mgr.build_prompt_block()
            interests = self.interest_mgr.get_interests()
            interest_str = ", ".join(interests[:5]) if interests else "暂无特定兴趣"
            target_profile_block = ""
            if target:
                target_profile_block = self.user_profile_mgr.build_prompt_block(f"user::{target_uid}", target_name)
            prompt = f"""
你要给B站上的一个用户「{target_name}」发一条初次私信打招呼。
这是主动发起聊天，不是回复别人的消息。

{persona_block}
{mood_block}
你的兴趣: {interest_str}
{target_profile_block}
当前时间: {datetime.now().isoformat(timespec='seconds')}

要求：
1. 自然、轻松、不油腻，像普通B站用户之间的寒暄
2. 🚫 不要聊你自己的兴趣爱好！先看看目标用户的签名和投稿内容——
   - 如果对方投稿了具体领域的视频（游戏/动画/科技/音乐等），围绕对方的创作内容展开话题
   - 如果对方签名里有信息，可以顺着签名聊
   - 只有当对方主页完全空白时，才简单聊聊日常
3. 不要太长，50字以内
4. 不要用客服腔、不要自来熟、不要"大佬""up主"之类刻意恭维
5. 禁止承诺做违法、刷量、侵权的事
6. 结尾带上"{config.get('behavior', {}).get('ai_marker', '（内容由AI生成并由AI回复）')}"
7. 如果看了对方主页实在不知道聊什么，返回空字符串

只返回要发送的内容，不要解释。
"""
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": "你是B站上的一个普通用户。看了对方主页后再开口——围绕对方的投稿内容或签名展开话题。友好、有边界感、不油腻。"},
                    {"role": "user", "content": prompt}
                ],
                timeout=60
            )
            chat_text = resp.choices[0].message.content.strip()
            if not chat_text or chat_text.upper() == "END":
                log(f"AI判断不适合主动聊天 @{target_name}，跳过", "CHAT")
                return
            chat_text = ensure_ai_marker(chat_text)
            ok, reason, hits = ReplySafetyGuard().review("(主动发起聊天)", chat_text)
            if not ok:
                log(f"主动聊天内容被拦截: {reason} | 命中: {', '.join(hits)}", "WARN")
                return
            await asyncio.sleep(human_reply_delay())
            result = await self.private_message_mgr.send_reply(target_uid, chat_text)
            log(f"[MSG] 已主动发消息给 @{target_name}: {chat_text[:60]}", "CHAT")
            self.record_session_event(
                "active_chat",
                target_uid=target_uid,
                target_name=target_name,
                content=chat_text[:120]
            )
        except Exception as e:
            log(f"主动聊天失败: {e}", "WARN")

    # ── [*] UP主关注 ──
    def _reset_daily_follows(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.daily_follows_date != today:
            self.daily_follows = 0
            self.daily_follows_date = today

    def _reset_daily_danmaku_likes(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.daily_danmaku_likes_date != today:
            self.daily_danmaku_likes = 0
            self.daily_danmaku_likes_date = today

    def _reset_daily_danmaku_sent(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self.daily_danmaku_sent_date != today:
            self.daily_danmaku_sent = 0
            self.daily_danmaku_sent_date = today

    async def maybe_follow_up(self, up_uid: int, up_name: str, score: float):
        if not UP_FOLLOW_ENABLED or not up_uid or not up_name:
            return False
        self._reset_daily_follows()
        if self.daily_follows >= UP_FOLLOW_MAX_DAILY:
            return False
        cooldown_ok = (datetime.now() - self.last_follow_at).total_seconds() / 60 >= UP_FOLLOW_COOLDOWN_MINUTES
        if not cooldown_ok:
            return False
        exceptional = score >= UP_FOLLOW_EXCEPTIONAL_SCORE
        if not exceptional and score < UP_FOLLOW_MIN_SCORE:
            return False
        up_entry = self.memory.setdefault("known_ups", {}).get(up_name, {})
        if up_entry.get("followed"):
            return False
        views = up_entry.get("views", 0)
        avg_score = up_entry.get("avg_score", score)
        if not exceptional and views < UP_FOLLOW_MIN_IMPRESSIONS:
            return False
        score_factor = min(score / 5.0, 2.0) if score > 0 else 1.0
        impression_bonus = min(views / max(UP_FOLLOW_MIN_IMPRESSIONS, 1), 2.0)
        adjusted_prob = UP_FOLLOW_AUTO_PROB * score_factor * impression_bonus
        if not exceptional and random.random() >= adjusted_prob:
            return False
        try:
            avg_str = f", 均分:{avg_score:.1f}" if views else ""
            log(f"[*] 正在关注 UP主 @{up_name} (UID:{up_uid})... (评分:{score}, 观看{views}次{avg_str}, 概率:{adjusted_prob:.3f})", "FOLLOW")
            result = await self.bili.follow_up(up_uid)
            if result.get("code") == 0:
                self.daily_follows += 1
                self.last_follow_at = datetime.now()
                up_entry["followed"] = True
                up_entry["followed_at"] = datetime.now().isoformat()
                if not up_entry.get("uid"):
                    up_entry["uid"] = up_uid
                self._save_memory()
                log(f"[OK] 已关注 UP主 @{up_name}！今日已关注 {self.daily_follows}/{UP_FOLLOW_MAX_DAILY}", "SUCCESS")
                self.record_session_event("follow_up", up_uid=up_uid, up_name=up_name, score=score, views=views, avg_score=round(avg_score, 1) if views else score)
                return True
            elif result.get("code") == 22014:
                up_entry["followed"] = True
                if not up_entry.get("uid"):
                    up_entry["uid"] = up_uid
                self._save_memory()
                log(f"已关注过 UP主 @{up_name} (之前已关注，已同步记录)", "INFO")
                return True
            else:
                log(f"关注失败: {result.get('msg')}", "WARN")
        except Exception as e:
            log(f"关注 UP主异常: {e}", "WARN")
        return False

    async def maybe_browse_up_videos(self, force_up_uid=None, up_name_hint=None):
        if not UP_FOLLOW_ENABLED:
            return None
        elapsed = (datetime.now() - self.last_up_browse_at).total_seconds() / 60
        if elapsed < UP_FOLLOW_COOLDOWN_MINUTES and not force_up_uid:
            return None
        target_uid = force_up_uid
        chosen_up_name = up_name_hint
        is_favorite = False
        if not target_uid:
            favorite_ups = self.get_favorite_ups()
            if favorite_ups and random.random() < UP_FOLLOW_FAVORITE_PROB:
                fav = random.choice(favorite_ups)
                fav_uid = fav.get("uid")
                if fav_uid:
                    target_uid = int(fav_uid)
                    chosen_up_name = fav.get("name")
                    is_favorite = True
                elif UP_FOLLOW_FAVORITE_UID_LIST and len(UP_FOLLOW_FAVORITE_UID_LIST) > 0:
                    target_uid = random.choice(UP_FOLLOW_FAVORITE_UID_LIST)
                    is_favorite = True
            if not target_uid:
                if random.random() >= UP_FOLLOW_BROWSE_PROB:
                    return None
                known_ups = self.memory.get("known_ups", {})
                if not known_ups:
                    return None
                chosen_up_name = random.choice(list(known_ups.keys()))
                uid_from_mem = known_ups.get(chosen_up_name, {}).get("uid")
                if uid_from_mem:
                    target_uid = int(uid_from_mem)
                else:
                    profile = self.user_profile_mgr.get_profile(f"up::{chosen_up_name}")
                    if profile and profile.get("uid"):
                        target_uid = int(profile["uid"])
                    else:
                        return None
            if not target_uid:
                return None
        self.last_up_browse_at = datetime.now()
        tag = "[STAR]喜爱" if is_favorite else "📺"
        log(f"{tag} 浏览 UP主 {'@'+chosen_up_name if chosen_up_name else ''} (UID:{target_uid}) 的主页视频...", "BROWSE")
        try:
            videos = await self.bili.get_up_videos(target_uid, limit=UP_FOLLOW_MAX_BROWSE)
            if videos:
                log(f"获取到 {len(videos)} 个视频:", "BROWSE")
                for v in videos:
                    log(f"  • {v.get('title','')[:40]} | 播放:{v.get('play',0)}", "BROWSE")
                chosen = random.choice(videos)
                return {
                    "bvid": chosen.get("bvid", ""),
                    "title": chosen.get("title", ""),
                    "owner": {"name": chosen_up_name or "", "mid": target_uid},
                    "id": chosen.get("aid", 0),
                    "aid": chosen.get("aid", 0),
                    "pic": chosen.get("pic", ""),
                    "_source": "up_browse",
                    "_is_favorite_up": is_favorite
                }
            else:
                log("该UP主暂无视频或获取失败", "INFO")
        except Exception as e:
            log(f"浏览UP主视频异常: {e}", "WARN")
        return None

    # ── [MSG] 弹幕互动 ──
    async def maybe_read_danmaku(self, bvid: str, force: bool = False):
        if not DANMAKU_ENABLED or not bvid:
            return []
        if not force and random.random() >= DANMAKU_READ_PROB:
            return []
        try:
            log("[MSG] 正在读取弹幕...", "DANMAKU")
            cid, danmaku_list = await self.bili.get_danmakus(bvid, limit=30)
            if danmaku_list:
                self._last_danmaku_videos[bvid] = danmaku_list
                self._last_danmaku_cids[bvid] = cid
                if len(self._last_danmaku_videos) > 10:
                    oldest = list(self._last_danmaku_videos.keys())[0]
                    del self._last_danmaku_videos[oldest]
                log(f"读取到 {len(danmaku_list)} 条弹幕 (cid={cid})", "DANMAKU")
                for dm in danmaku_list[:5]:
                    log(f"  弹幕: {dm.get('text','')[:40]}", "DANMAKU")
                await self.maybe_like_danmaku(bvid, danmaku_list, cid)
                await self.maybe_send_danmaku(bvid)
                return danmaku_list
        except Exception as e:
            log(f"读取弹幕异常: {e}", "WARN")
        return []

    async def maybe_like_danmaku(self, bvid: str, danmaku_list: list, cid: int = 0):
        if not DANMAKU_ENABLED or not danmaku_list:
            return False
        if random.random() >= DANMAKU_LIKE_PROB:
            return False
        self._reset_daily_danmaku_likes()
        if self.daily_danmaku_likes >= DANMAKU_MAX_DAILY_LIKES:
            return False
        if not cid:
            cid = self._last_danmaku_cids.get(bvid, 0)
        if not cid:
            return False
        try:
            target_dm = random.choice(danmaku_list)
            dm_id_str = target_dm.get("id_str", "")
            dm_text = target_dm.get("text", "")
            if not dm_id_str:
                return False
            log(f"👍 点赞弹幕: {dm_text[:30]}... (id_str={dm_id_str[:16]}...)", "DANMAKU")
            result = await self.bili.like_danmaku(dmid=dm_id_str, cid=cid, bvid=bvid)
            if result.get("code") == 0:
                self.daily_danmaku_likes += 1
                log(f"弹幕点赞成功！今日已赞 {self.daily_danmaku_likes}/{DANMAKU_MAX_DAILY_LIKES}", "SUCCESS")
                return True
            else:
                log(f"弹幕点赞未成功: {result.get('msg')}", "INFO")
        except Exception as e:
            log(f"弹幕点赞异常: {e}", "WARN")
        return False

    async def maybe_send_danmaku(self, bvid: str, title: str = "", subtitle_text: str = ""):
        if not DANMAKU_ENABLED or not bvid:
            return False
        if random.random() >= DANMAKU_SEND_PROB:
            return False
        self._reset_daily_danmaku_sent()
        if self.daily_danmaku_sent >= DANMAKU_MAX_DAILY_SEND:
            return False
        try:
            context = f"视频标题: {title}\n视频内容摘要: {subtitle_text[:200] if subtitle_text and '[未读取' not in subtitle_text else '未知'}"
            persona_block = self.persona_mgr.build_prompt_block()
            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": f"你是B站上的一个普通观众。{persona_block}请根据视频内容发送一条弹幕。要求：1. 简短（20字以内）2. 符合B站弹幕风格 3. 有趣或表达到位 4. 不要发送引战、敏感内容。只返回弹幕文字，不要解释。"},
                    {"role": "user", "content": f"为这个视频发一条弹幕: {context}"}
                ],
                max_tokens=50,
                request_timeout=60
            )
            dm_text = resp.choices[0].message.content.strip()
            if not dm_text or len(dm_text) > 50:
                return False
            log(f"📤 发送弹幕: {dm_text}", "DANMAKU")
            result = await self.bili.send_danmaku(bvid, dm_text)
            if result.get("code") == 0:
                self.daily_danmaku_sent += 1
                log(f"弹幕发送成功！今日已发 {self.daily_danmaku_sent}/{DANMAKU_MAX_DAILY_SEND}", "SUCCESS")
                self.record_session_event("send_danmaku", bvid=bvid, text=dm_text)
                return True
            else:
                log(f"弹幕发送失败: {result.get('msg')}", "WARN")
        except Exception as e:
            log(f"弹幕发送异常: {e}", "WARN")
        return False

    async def initialize_login(self):
        self.bili.credential = self.bili._load_credential()
        if self.bili.credential and os.path.exists(COOKIE_FILE):
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                self.cookies = json.load(f)
            self.credential = self.bili.credential
            try:
                self.bili.uid = int(self.cookies.get("DedeUserID", 0))
            except Exception:
                self.bili.uid = 0
            log(f"登录已就绪 (UID: {self.bili.uid})", "SUCCESS")
            self._init_psycho_engine()
            self.comment_mgr = CommentInteractionManager(self.credential, self.bili.uid, since_ts=self.previous_seen_ts)
            self.private_message_mgr = PrivateMessageManager(
                self.credential, self.bili.uid,
                since_ts=self.previous_seen_ts,
                previous_seen_at=self.previous_seen_at
            )
            return True
        log("需要登录B站账号", "LOGIN")
        print("\n" + "="*50)
        print("           B站登录向导")
        print("="*50)
        login_success = await login_bilibili()
        if not login_success:
            log("登录失败，程序退出", "ERROR")
            return False
        self.bili.credential = self.bili._load_credential()
        if not self.bili.credential:
            log("登录后加载凭据失败", "ERROR")
            return False
        login_success = await self.bili.init_user_info()
        if not login_success:
            log("登录验证失败", "ERROR")
            return False
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            self.cookies = json.load(f)
        self.credential = Credential(
            sessdata=self.cookies.get("SESSDATA"),
            bili_jct=self.cookies.get("bili_jct"),
            buvid3=self.cookies.get("buvid3"),
            dedeuserid=self.cookies.get("DedeUserID"),
        )
        self._init_psycho_engine()
        self.comment_mgr = CommentInteractionManager(self.credential, self.bili.uid, since_ts=self.previous_seen_ts)
        self.private_message_mgr = PrivateMessageManager(
            self.credential, self.bili.uid,
            since_ts=self.previous_seen_ts,
            previous_seen_at=self.previous_seen_at
        )
        log("登录完成，准备开始工作！", "SUCCESS")
        return True

    def _init_psycho_engine(self):
        try:
            self.psycho_profile = PsychoProfile(ai_caller=self._psycho_ai_caller if PSYCHO_ENGINE_ENABLED else None)
            self.recommend_engine = RecommendationEngine(
                psycho_profile=self.psycho_profile,
                ai_caller=self._psycho_ai_caller if PSYCHO_ENGINE_ENABLED else None,
            )
            status = "[PSYCHO]已激活" if PSYCHO_ENGINE_ENABLED else "[NOTE]仅追踪(无AI分析)"
            log(f"智能分析系统 {status} | 多维度追踪已激活", "SUCCESS")
        except Exception as e:
            log(f"智能分析系统初始化失败: {e}", "ERROR")
            self.psycho_profile = None
            self.recommend_engine = None
