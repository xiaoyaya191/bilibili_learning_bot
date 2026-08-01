"""brain/comment.py — 评论互动管理器"""
import asyncio
import json
import os
import random
import re
import time

from colorama import Fore, Style

from core.config import (
    config, COMMENT_LOG_FILE, COMMENT_MODE, BEHAVIOR_COMMENT_USER_COOLDOWN_MINUTES,
    MAX_REPLIES_PER_CHECK, PROB_COMMENT_OTHERS,
)
# 从 config 实时读取，避免 import * 缓存问题
def _get_model_brain():
    return config.get("api", {}).get("model_brain", "")
from persona.managers import PersonaManager, MoodManager, UserProfileManager
from security.guard import ReplySafetyGuard
from utils.display import log
from datetime import datetime
from openai import OpenAI
from utils.helpers import _mask_urls, parse_iso_datetime, ensure_ai_marker
from api.throttle import _bili_throttle, _bili_trigger_cooldown

# bilibili_api imports (used by the class)
from bilibili_api import comment, user
from bilibili_api.comment import CommentResourceType

# Optional xingye_bot imports
try:
    from xingye_bot.llm import ModelClient
    from xingye_bot.settings import load_settings as load_modular_settings
    from xingye_bot.state import BotState
    from xingye_bot.video_modes import VideoUnderstanding, normalize_mode
    from xingye_bot.kb_search import KBSearchEngine
except ImportError:
    ModelClient = None
    load_modular_settings = None
    BotState = None
    VideoUnderstanding = None
    normalize_mode = None
    KBSearchEngine = None

class CommentInteractionManager:
    """评论互动管理器 - 管理评论回复和点赞"""
    
    def __init__(self, credential, uid, since_ts=0):
        self.credential = credential
        self.uid = uid
        self.since_ts = int(since_ts or 0)
        self.comment_log = self._load_comment_log()
        self.processed_comments = set(self.comment_log.get("processed_comments", []))
        self.last_check_time = None
        self.persona_mgr = PersonaManager()
        self.mood_mgr = MoodManager()
        self.user_profile_mgr = UserProfileManager()
        self.safety_guard = ReplySafetyGuard()
        self.video_understander = None
        self.kb_search = None  # 懒初始化，kb_search.py 向量检索引擎
        if VideoUnderstanding and ModelClient and BotState and load_modular_settings:
            try:
                modular_settings = load_modular_settings()
                self.video_understander = VideoUnderstanding(modular_settings, ModelClient(modular_settings, BotState()))
            except Exception as e:
                log(f"视频理解模块初始化失败，将退回字幕模式: {e}", "WARN")

        # 懒初始化向量检索引擎
        if KBSearchEngine and ModelClient and load_modular_settings and BotState:
            try:
                modular_settings = load_modular_settings()
                self.kb_search = KBSearchEngine(ModelClient(modular_settings, BotState()))
            except Exception as e:
                log(f"向量检索引擎初始化失败: {e}", "WARN")
    
    def _load_comment_log(self):
        """加载评论日志"""
        if os.path.exists(COMMENT_LOG_FILE):
            try:
                with open(COMMENT_LOG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data.setdefault("processed_comments", [])
                    data.setdefault("replied_comments", [])
                    data.setdefault("liked_comments", [])
                    data.setdefault("history", [])
                    data.setdefault("user_reply_state", {})
                    return data
            except (json.JSONDecodeError, OSError) as e:
                log(f"[WARN] 评论日志加载失败: {e}", "WARN")
        return {"processed_comments": [], "replied_comments": [], "liked_comments": [], "history": [], "user_reply_state": {}}
    
    def _save_comment_log(self):
        """保存评论日志"""
        try:
            self.comment_log["processed_comments"] = list(self.processed_comments)
            tmp = COMMENT_LOG_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.comment_log, f, ensure_ascii=False, indent=2)
            os.replace(tmp, COMMENT_LOG_FILE)
        except OSError as e:
            log(f'文件操作失败: {e}', 'DEBUG')
    
    def _is_comment_processed(self, comment_id):
        """检查评论是否已处理"""
        return str(comment_id) in self.processed_comments
    
    def _mark_comment_processed(self, comment_id):
        """标记评论为已处理"""
        self.processed_comments.add(str(comment_id))
        self._save_comment_log()

    def _should_reply_user(self, user_id, content=""):
        key = str(user_id or "unknown")
        state = self.comment_log.setdefault("user_reply_state", {}).get(key, {})
        last_reply_at = parse_iso_datetime(state.get("last_reply_at"))
        if last_reply_at:
            elapsed = (datetime.now() - last_reply_at).total_seconds() / 60
            direct = any(marker in (content or "") for marker in ["?", "？", "吗", "怎么", "为什么", "求", "帮"])
            if elapsed < BEHAVIOR_COMMENT_USER_COOLDOWN_MINUTES and not direct:
                return False, f"同一评论用户 {elapsed:.1f} 分钟内已回复过"
        return True, "通过"

    def _mark_user_replied(self, user_id):
        key = str(user_id or "unknown")
        state = self.comment_log.setdefault("user_reply_state", {}).setdefault(key, {})
        state["last_reply_at"] = datetime.now().isoformat()
        state["count"] = int(state.get("count") or 0) + 1
        self._save_comment_log()
    
    def log_interaction(self, comment_id, action, content, target_user):
        """记录互动日志"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "comment_id": comment_id,
            "action": action,
            "content": content,
            "target_user": target_user
        }
        self.comment_log["history"].append(entry)
        if action == "reply":
            self.comment_log["replied_comments"].append(comment_id)
        elif action == "like":
            self.comment_log["liked_comments"].append(comment_id)
        self._save_comment_log()

    def log_blocked_reply(self, comment_id, incoming, outgoing, reason, hits, target_user):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "comment_id": comment_id,
            "action": "blocked_reply",
            "content": outgoing,
            "incoming": incoming,
            "target_user": target_user,
            "reason": reason,
            "hits": hits
        }
        self.comment_log.setdefault("history", []).append(entry)
        self.comment_log.setdefault("blocked_replies", []).append(comment_id)
        self._save_comment_log()
    
    async def _api_with_retry(self, api_call, name, max_retries=5):
        """通用API调用重试，专门处理-799限流。使用指数退避+随机抖动。
        
        [NEW] 集成全局节流：调用 API 前确保最小间隔，从源头减少 -799。
        [NEW] 日志静默化：仅首次命中 -799 时打印一句，后续静默等待。
        """
        _logged_hit = False  # 本轮只报一次 -799
        for attempt in range(max_retries):
            try:
                await _bili_throttle()  # 🔒 全局节流
                return await api_call()
            except Exception as e:
                err_msg = str(e)
                if '-799' in err_msg or '请求过于频繁' in err_msg:
                    _bili_trigger_cooldown()  # 🔒 启动全局冷却，暂停所有API
                    if attempt < max_retries - 1:
                        # 指数退避：2^(attempt+1) * [2, 3.5] 秒
                        base = 2 ** (attempt + 1)
                        wait = base * random.uniform(2.0, 3.5)
                        if not _logged_hit:
                            log(f"[WARN] {name} 触发-799限流，全局冷却已启动，静默重试中...", "WARN")
                            _logged_hit = True
                        await asyncio.sleep(wait)
                    else:
                        log(f"[ERROR] {name} 重试{max_retries}次仍限流，放弃", "ERROR")
                        raise e
                else:
                    raise e

    async def get_new_comments(self, bili_client):
        """获取账号的新评论（别人评论我的）"""
        try:
            # 获取动态评论通知
            # 这里使用bilibili_api获取用户收到的评论
            # 由于API限制，这里实现一个简化版本：检查最近视频的评论
            
            # [SPEED] 大幅削减初始等待（原10-20s → 0.3-0.8s），涡轮模式下去除冗余延迟
            await asyncio.sleep(random.uniform(0.3, 0.8))
            
            # 使用 init_user_info() 已缓存的 uid，避免重复调用 get_self_info 浪费配额
            uid = getattr(self, 'uid', None) or (await self._api_with_retry(
                lambda: user.get_self_info(self.credential),
                "get_self_info"
            )).get('mid')
            
            # 获取用户投稿视频列表
            await asyncio.sleep(random.uniform(0.3, 0.8))
            videos = await self._api_with_retry(
                lambda: user.User(uid, self.credential).get_videos(ps=5),
                "get_videos"
            )
            new_comments = []
            
            vlist = videos.get('list', {}).get('vlist') or videos.get('videos') or []
            if vlist:
                vlist_to_check = vlist[:5]  # 检查最近5个视频
                for idx, v in enumerate(vlist_to_check):
                    aid = v.get('aid')
                    if aid:
                        # [SPEED] 视频间微延迟（原10-20s → 0.5-1.5s），_bili_throttle已做节流
                        if idx > 0:
                            await asyncio.sleep(random.uniform(0.5, 1.5))
                        # 获取视频评论（带重试，应对-799限流，指数退避）
                        comments = None
                        _logged_hit = False  # 每个视频只报一次 -799
                        for retry in range(4):
                            try:
                                await _bili_throttle()  # 🔒 全局节流
                                comments = await comment.get_comments(
                                    oid=aid,
                                    type_=CommentResourceType.VIDEO,
                                    order=comment.OrderType.TIME,
                                    page_index=1,
                                    credential=self.credential
                                )
                                break
                            except Exception as e:
                                err_msg = str(e)
                                if '-799' in err_msg or '请求过于频繁' in err_msg:
                                    _bili_trigger_cooldown()  # 🔒 启动全局冷却
                                    wait = (2 ** (retry + 1)) * random.uniform(2.0, 3.5)
                                    if not _logged_hit:
                                        log(f"[WARN] 视频{aid}评论触发-799，全局冷却已启动，静默重试...", "WARN")
                                        _logged_hit = True
                                    await asyncio.sleep(wait)
                                elif '12002' in err_msg:
                                    # 评论区已关闭，正常现象，静默跳过
                                    break
                                else:
                                    log(f"跳过视频 {aid} 的评论检查: {e}", "WARN")
                                    break
                        if comments is None:
                            continue
                         
                        if comments and 'replies' in comments:
                            for cmt in comments['replies']:
                                cmt_id = cmt.get('rpid')
                                
                                # 只处理别人对我的评论（不是自己的评论）
                                if cmt.get('member', {}).get('mid') != uid:
                                    ctime = int(cmt.get('ctime') or 0)
                                    if self.since_ts and ctime and ctime <= self.since_ts:
                                        continue
                                    if not self._is_comment_processed(cmt_id):
                                        new_comments.append({
                                            "id": cmt_id,
                                            "aid": aid,
                                            "bvid": v.get('bvid'),
                                            "content": cmt.get('content', {}).get('message', ''),
                                            "user": cmt.get('member', {}).get('uname', '未知'),
                                            "user_id": cmt.get('member', {}).get('mid'),
                                            "time": ctime,
                                            "replies": cmt.get('replies', [])
                                        })
            
            return new_comments
            
        except Exception as e:
            log(f"获取新评论失败: {e}", "ERROR")
            return []
    
    async def reply_to_comment(self, bili_client, comment_data, ai_response):
        """回复评论（支持模拟/真实模式）"""
        try:
            comment_id = comment_data['id']
            aid = comment_data['aid']
            ok, reason, hits = self.safety_guard.review(comment_data.get("content", ""), ai_response)
            if not ok:
                self.log_blocked_reply(comment_id, comment_data.get("content", ""), ai_response, reason, hits, comment_data.get("user", "未知"))
                log(f"已拦截评论回复 @{comment_data.get('user', '未知')}: {reason} | 命中: {', '.join(hits)}", "WARN")
                return False
            
            final_response = ensure_ai_marker(ai_response)
            
            # 模拟模式：只记录日志，不实际发送
            if COMMENT_MODE == "simulate":
                self.log_interaction(comment_id, "reply_simulated", final_response, comment_data['user'])
                self._mark_user_replied(comment_data.get("user_id"))
                log(f"[模拟] 拟回复评论 @{comment_data['user']}: {final_response[:50]}...", "SIMULATE")
                return True
            
            # 真实模式：发送到B站
            await _bili_throttle()  # 🔒 全局节流
            await comment.send_comment(
                text=final_response,
                oid=aid,
                type_=CommentResourceType.VIDEO,
                root=comment_id,
                parent=comment_id,
                credential=self.credential
            )
            
            self.log_interaction(comment_id, "reply", final_response, comment_data['user'])
            self._mark_user_replied(comment_data.get("user_id"))
            log(f"已回复评论 @{comment_data['user']}: {final_response[:50]}...", "SUCCESS")
            return True
            
        except Exception as e:
            log(f"回复评论失败: {e}", "ERROR")
            return False
    
    async def like_comment(self, bili_client, comment_data):
        """点赞评论"""
        try:
            comment_id = comment_data['id']
            aid = comment_data['aid']
            
            comment_obj = comment.Comment(
                oid=aid,
                type_=CommentResourceType.VIDEO,
                rpid=comment_id,
                credential=self.credential
            )
            await comment_obj.like(status=True)
            
            self.log_interaction(comment_id, "like", "点赞", comment_data['user'])
            log(f"已点赞评论 @{comment_data['user']}", "SUCCESS")
            return True
            
        except Exception as e:
            log(f"点赞评论失败: {e}", "ERROR")
            return False
    
    async def process_new_comments(self, bili_client):
        """处理新评论"""
        global openai  # 确保使用全局的 openai
        log("正在检查是否有新评论...", "SCAN")
        
        new_comments = await self.get_new_comments(bili_client)
        
        if not new_comments:
            log("没有新评论需要处理", "INFO")
            return 0
        
        log(f"发现 {len(new_comments)} 条新评论", "SUCCESS")
        
        processed = 0
        for comment_data in new_comments[:MAX_REPLIES_PER_CHECK]:
            try:
                incoming_hits = self.safety_guard.find_hits(comment_data.get("content", "")) if self.safety_guard.block_on_incoming else []
                if incoming_hits:
                    self.log_blocked_reply(
                        comment_data["id"],
                        comment_data.get("content", ""),
                        "",
                        "来信/评论命中敏感词",
                        incoming_hits,
                        comment_data.get("user", "未知")
                    )
                    log(f"跳过敏感评论 @{comment_data.get('user', '未知')}: 命中 {', '.join(incoming_hits)}", "WARN")
                    self._mark_comment_processed(comment_data['id'])
                    continue

                # 随机决定是回复还是点赞
                action = random.choices(
                    ['reply', 'like', 'none'],
                    weights=[PROB_COMMENT_OTHERS, 0.3, 0.2]
                )[0]
                
                if action == 'reply':
                    pacing_ok, pacing_reason = self._should_reply_user(comment_data.get("user_id"), comment_data.get("content", ""))
                    if not pacing_ok:
                        log(f"评论节奏控制跳过 @{comment_data.get('user', '未知')}: {pacing_reason}", "COMMENT")
                        self._mark_comment_processed(comment_data['id'])
                        continue
                    # 使用AI生成回复（旧版 API）
                    user_block = self.user_profile_mgr.build_prompt_block(comment_data.get("user_id"), comment_data.get("user"))
                    persona_block = self.persona_mgr.build_prompt_block()
                    mood_block = self.mood_mgr.build_prompt_block()
                    prompt = f"""
                    用户评论: {comment_data['content']}
                    {user_block}
                    {persona_block}
                    {mood_block}
                    
                    请判断是否值得回复，再根据这条评论生成一个自然回复。
                    要求：
                    1. 对方只是表情、路过、结束语、无实质内容时返回 END
                    2. 回复要自然、亲切，可以适当幽默，但不要客服腔
                    3. 字数控制在35字以内
                    4. 不要每次都反问
                    5. 必须用 B站原生表情（[表情名] 格式，不是 emoji），**通常只 1 个**；偶尔连发 3 个相同（如 [doge][doge][doge]）；只有长句才用 2-3 个不同表情：
                       夸赞: [给心心][星星眼][打call][妙啊]  幽默: [doge][吃瓜][笑哭][滑稽][调皮][偷笑]
                       震惊: [惊讶][灵魂出窍][酸了]  吐槽: [无语][嫌弃][抠鼻]  鼓励: [支持][加油][抱拳]
                    6. 结尾带上"{config.get('behavior', {}).get('ai_marker', '（内容由AI生成并由AI回复）')}"
                     
                    只返回回复内容，不要有其他文字。
                    """
                    
                    client = OpenAI(
                        api_key=config.get("api", {}).get("unified_api_key", ""),
                        base_url=config.get("api", {}).get("unified_base_url", ""),
                        timeout=120
                    )
                    resp = client.chat.completions.create(
                        model=_get_model_brain(),
                        messages=[
                            {"role": "system", "content": "你是一个友好的B站用户，正在回复别人的评论。"},
                            {"role": "user", "content": prompt}
                        ]
                    )
                    
                    reply_content = resp.choices[0].message.content.strip()
                    if reply_content.strip().upper() == "END":
                        log(f"AI判断评论 @{comment_data.get('user', '未知')} 无需回复", "COMMENT")
                        self._mark_comment_processed(comment_data['id'])
                        continue
                    reply_content = ensure_ai_marker(reply_content)
                    sent = await self.reply_to_comment(bili_client, comment_data, reply_content)
                    if sent:
                        self.user_profile_mgr.adjust_affinity(comment_data.get("user_id"), comment_data.get("user"), 2, "成功回复评论")
                        self.mood_mgr.shift("评论互动成功", 1)
                        processed += 1
                    
                elif action == 'like':
                    await self.like_comment(bili_client, comment_data)
                    self.user_profile_mgr.adjust_affinity(comment_data.get("user_id"), comment_data.get("user"), 1, "点赞评论")
                    processed += 1
                
                # 标记为已处理
                self._mark_comment_processed(comment_data['id'])
                
                # [SPEED] 评论处理间微延迟（原10-25s → 1-3s），满足1-2秒/动作目标
                await asyncio.sleep(random.uniform(1, 3))
                
            except Exception as e:
                log(f"处理评论失败: {e}", "ERROR")
                self._mark_comment_processed(comment_data['id'])
        
        self.last_check_time = datetime.now()
        return processed


