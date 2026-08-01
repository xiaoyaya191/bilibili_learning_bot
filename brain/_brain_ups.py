"""brain/_brain_ups.py — AgentBrain UP主管理 mixin"""
from brain._mixin_imports import *
from api.throttle import _bili_throttle

class BrainUpsMixin:
    """UP主管理"""
    
    def record_up_impression(self, up_name, uid, score):
        """记录对UP主的一次观看印象（积累正面印象用于关注决策）。"""
        ups = self.memory.setdefault("known_ups", {})
        if up_name not in ups:
            ups[up_name] = {
                "uid": uid,
                "favorited": False,
                "followed": False,
                "views": 1,
                "total_score": score,
                "avg_score": round(score, 2),
                "first_seen": datetime.now().isoformat(),
                "last_viewed_at": datetime.now().isoformat()
            }
        else:
            entry = ups[up_name]
            entry["views"] = entry.get("views", 0) + 1
            entry["total_score"] = entry.get("total_score", 0) + score
            entry["avg_score"] = round(entry["total_score"] / entry["views"], 2)
            entry["last_viewed_at"] = datetime.now().isoformat()
            if uid and not entry.get("uid"):
                entry["uid"] = uid
        self._save_memory()

    def remember_up(self, up_name, uid=None):
        """记住UP主，可选记录UID。保留已有字段（followed/favorited/views等）。"""
        ups = self.memory.setdefault("known_ups", {})
        if up_name not in ups:
            ups[up_name] = {"uid": uid, "favorited": False, "followed": False, "first_seen": datetime.now().isoformat()}
            self._save_memory()
            log(f"已记住UP主: {up_name}" + (f" (UID:{uid})" if uid else ""), "MEM")
        elif uid and not ups[up_name].get("uid"):
            ups[up_name]["uid"] = uid
            ups[up_name].setdefault("followed", False)
            ups[up_name]["updated_at"] = datetime.now().isoformat()
            self._save_memory()
            log(f"补充UP主UID: {up_name} → {uid}", "MEM")

    def get_known_up_names(self):
        """返回已知UP主名称列表（用于prompt等）。"""
        return list(self.memory.get("known_ups", {}).keys())

    def get_up_uid(self, up_name):
        """从记忆中获取UP主的UID。"""
        return self.memory.get("known_ups", {}).get(up_name, {}).get("uid")

    def set_up_uid(self, up_name, uid):
        """设置/更新UP主的UID。保留已有followed/favorited状态。"""
        ups = self.memory.setdefault("known_ups", {})
        if up_name not in ups:
            ups[up_name] = {"uid": uid, "favorited": False, "followed": False, "first_seen": datetime.now().isoformat()}
        else:
            ups[up_name]["uid"] = uid
            ups[up_name].setdefault("followed", False)
            ups[up_name]["updated_at"] = datetime.now().isoformat()
        self._save_memory()
        log(f"UP主 {up_name} UID已更新: {uid}", "MEM")

    def favorite_up(self, up_name, uid=None):
        """将UP主标记为喜欢（AI特别关注）。"""
        ups = self.memory.setdefault("known_ups", {})
        if up_name not in ups:
            ups[up_name] = {"uid": uid, "favorited": True, "followed": False, "first_seen": datetime.now().isoformat()}
        else:
            ups[up_name]["favorited"] = True
            ups[up_name].setdefault("followed", False)
            if uid and not ups[up_name].get("uid"):
                ups[up_name]["uid"] = uid
        ups[up_name]["favorited_at"] = datetime.now().isoformat()
        self._save_memory()
        global UP_FOLLOW_FAVORITE_UID_LIST, config
        if uid and uid not in UP_FOLLOW_FAVORITE_UID_LIST:
            UP_FOLLOW_FAVORITE_UID_LIST.append(uid)
            config.setdefault("up_follow", {})["favorite_up_uid_list"] = UP_FOLLOW_FAVORITE_UID_LIST
            save_config(config)
        log(f"[STAR] 已标记为喜欢的UP主: {up_name}" + (f" (UID:{uid})" if uid else ""), "FAVORITE")

    def unfavorite_up(self, up_name):
        """取消喜欢UP主。"""
        ups = self.memory.get("known_ups", {})
        if up_name in ups:
            ups[up_name]["favorited"] = False
            ups[up_name]["unfavorited_at"] = datetime.now().isoformat()
            self._save_memory()
        global UP_FOLLOW_FAVORITE_UID_LIST, config
        uid = ups.get(up_name, {}).get("uid")
        if uid and uid in UP_FOLLOW_FAVORITE_UID_LIST:
            UP_FOLLOW_FAVORITE_UID_LIST.remove(uid)
            config.setdefault("up_follow", {})["favorite_up_uid_list"] = UP_FOLLOW_FAVORITE_UID_LIST
            save_config(config)
        log(f"💔 已取消喜欢UP主: {up_name}", "FAVORITE")

    def get_favorite_ups(self):
        """获取所有喜欢的UP主列表 [{name, uid, ...}]。"""
        ups = self.memory.get("known_ups", {})
        result = []
        for name, info in ups.items():
            if info.get("favorited"):
                result.append({"name": name, "uid": info.get("uid"), **info})
        return result

    def is_favorite_up(self, up_name):
        """检查UP主是否为喜欢的。"""
        return self.memory.get("known_ups", {}).get(up_name, {}).get("favorited", False)

    async def resolve_up_uid(self, up_name):
        """通过B站搜索API解析UP主名称→UID。"""
        uid = self.get_up_uid(up_name)
        if uid:
            return uid
        profile = self.user_profile_mgr.get_profile(f"up::{up_name}")
        if profile and profile.get("uid"):
            uid = int(profile["uid"])
            self.set_up_uid(up_name, uid)
            return uid
        try:
            await _bili_throttle("搜索UP主")
            from bilibili_api import search as bili_search
            data = await bili_search.search_by_type(
                up_name,
                search_type=bili_search.SearchObjectType.USER,
                page=1
            )
            items = data.get("result") or []
            if items:
                best = items[0]
                uid = best.get("mid") or best.get("uid")
                if uid:
                    uid = int(uid)
                    self.set_up_uid(up_name, uid)
                    log(f"🔍 搜索解析 UP主: {up_name} → UID: {uid}", "RESOLVE")
                    return uid
        except Exception as e:
            log(f"搜索UP主 {up_name} 失败: {e}", "WARN")
        return None
