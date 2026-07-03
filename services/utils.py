"""services/utils.py — 兴趣管理、工具箱等小工具"""
import json, os
from datetime import datetime
from colorama import Fore, Style
import re
from bilibili_api import user, homepage, search as bili_search
from core.config import INTERESTS_FILE

# Log function for standalone use (mirrors start_cli.log)
def _log(msg, level="INFO"):
    print(f"[{level}] {msg}")


class InterestManager:
    """兴趣管理器 - 管理用户自定义的兴趣关键词"""

    def __init__(self):
        self.interests_file = INTERESTS_FILE
        self.interests = self._load_interests()

    def _load_interests(self):
        if os.path.exists(self.interests_file):
            try:
                with open(self.interests_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("interests", [])
            except (OSError, json.JSONDecodeError) as e:
                _log(f'加载JSON文件失败: {e}', 'DEBUG')
        return []

    def _save_interests(self):
        """原子写入 JSON 文件（tmp+replace 防止断电损坏）"""
        try:
            tmp = self.interests_file + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({"interests": self.interests, "updated_at": datetime.now().isoformat()},
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.interests_file)
            return True
        except OSError:
            return False

    def add_interest(self, keyword):
        keyword = keyword.strip().lower()
        if keyword and keyword not in self.interests:
            self.interests.append(keyword)
            self._save_interests()
            _log(f"已添加兴趣: {keyword}", "SUCCESS")
            return True
        return False

    def remove_interest(self, keyword):
        keyword = keyword.strip().lower()
        if keyword in self.interests:
            self.interests.remove(keyword)
            self._save_interests()
            _log(f"已移除兴趣: {keyword}", "SUCCESS")
            return True
        return False

    def get_interests(self):
        return self.interests

    def is_interesting(self, title, content=""):
        if not self.interests:
            return True
        check_text = (title + " " + content).lower()
        for interest in self.interests:
            if interest.lower() in check_text:
                return True
        return False

    def get_matching_interests(self, title, content=""):
        matched = []
        check_text = (title + " " + content).lower()
        for interest in self.interests:
            if interest.lower() in check_text:
                matched.append(interest)
        return matched

    def show_interests(self):
        if self.interests:
            print(f"{Fore.GREEN}[*] 当前兴趣列表:{Style.RESET_ALL}")
            for i, interest in enumerate(self.interests, 1):
                print(f"  {i}. {interest}")
        else:
            print(f"{Fore.YELLOW}[WARN] 兴趣列表为空，机器人将对所有视频感兴趣{Style.RESET_ALL}")
        return len(self.interests)
class BiliToolbox:
    """私信回复前可调用的B站查询工具。"""

    def __init__(self, credential, uid, context_db=None):
        self.credential = credential
        self.uid = int(uid) if uid else 0
        self.context_db = context_db

    async def self_status(self):
        try:
            info = await user.get_self_info(self.credential)
            relation = await user.User(self.uid, self.credential).get_relation_info() if self.uid else {}
            result = {
                "uid": info.get("mid") or self.uid,
                "name": info.get("name"),
                "level": info.get("level"),
                "vip": info.get("vip", {}),
                "following": relation.get("following"),
                "follower": relation.get("follower"),
                "dynamic_count": relation.get("dynamic_count")
            }
            return result
        except Exception as e:
            return {"error": str(e)}

    async def my_videos(self, limit=5):
        try:
            videos = await user.User(self.uid, self.credential).get_videos(ps=limit)
            items = videos.get("list", {}).get("vlist") or videos.get("videos") or []
            return [
                {
                    "title": item.get("title"),
                    "bvid": item.get("bvid"),
                    "aid": item.get("aid"),
                    "play": item.get("play"),
                    "created": item.get("created")
                }
                for item in items[:limit]
            ]
        except Exception as e:
            return {"error": str(e)}

    async def followers_search(self, keyword="", limit=10):
        return await self._relation_search("followers", keyword, limit)

    async def followings_search(self, keyword="", limit=10):
        return await self._relation_search("followings", keyword, limit)

    async def _relation_search(self, kind, keyword="", limit=10):
        try:
            u = user.User(self.uid, self.credential)
            data = await (u.get_followers(ps=50) if kind == "followers" else u.get_followings(ps=50))
            raw_items = data.get("list") or data.get("data", {}).get("list") or []
            keyword_lower = (keyword or "").lower()
            items = []
            for item in raw_items:
                name = str(item.get("uname") or item.get("name") or item.get("nickname") or "")
                mid = item.get("mid") or item.get("uid")
                if keyword_lower and keyword_lower not in name.lower() and keyword_lower not in str(mid):
                    continue
                items.append({"mid": mid, "name": name, "sign": item.get("sign", "")[:80]})
                if len(items) >= limit:
                    break
            return items
        except Exception as e:
            return {"error": str(e)}

    async def video_search(self, query, limit=5):
        query = (query or "").strip()
        if not query:
            return []
        try:
            data = await bili_search.search_by_type(
                keyword=query,
                search_type=bili_search.SearchObjectType.VIDEO,
                page=1
            )
            result_block = data.get("result") or data.get("data", {}).get("result") or []
            videos = []
            for item in result_block:
                title = re.sub(r"<.*?>", "", str(item.get("title", "")))
                videos.append({
                    "title": title,
                    "bvid": item.get("bvid"),
                    "author": item.get("author") or item.get("uname"),
                    "play": item.get("play"),
                    "duration": item.get("duration"),
                    "description": str(item.get("description", ""))[:160]
                })
                if len(videos) >= limit:
                    break
            return videos
        except Exception as e:
            return {"error": str(e)}

    async def recommend_videos(self, limit=5):
        try:
            res = await homepage.get_videos(credential=self.credential)
            items = [item for item in res.get("item", []) if item.get("bvid")]
            return [
                {
                    "title": item.get("title"),
                    "bvid": item.get("bvid"),
                    "up": item.get("owner", {}).get("name"),
                    "duration": item.get("duration"),
                    "desc": str(item.get("desc", ""))[:120]
                }
                for item in items[:limit]
            ]
        except Exception as e:
            return {"error": str(e)}

    async def run_plan(self, plan, message_text, talker_id):
        if not isinstance(plan, dict):
            plan = {}
        tool_results = {}
        if plan.get("self_status"):
            tool_results["self_status"] = await self.self_status()
        if plan.get("my_videos"):
            tool_results["my_videos"] = await self.my_videos(limit=5)
        follower_keyword = str(plan.get("search_followers") or "").strip()
        if follower_keyword:
            tool_results["followers_search"] = await self.followers_search(follower_keyword)
        following_keyword = str(plan.get("search_followings") or "").strip()
        if following_keyword:
            tool_results["followings_search"] = await self.followings_search(following_keyword)
        video_query = str(plan.get("video_search") or "").strip()
        if video_query:
            tool_results["video_search"] = await self.video_search(video_query)
        if plan.get("recommend_videos"):
            tool_results["recommend_videos"] = await self.recommend_videos(limit=5)
        if self.context_db:
            self.context_db.set_tool_cache(talker_id, "last_tool_results", tool_results)
        return tool_results


