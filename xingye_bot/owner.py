"""
主人UID识别模块
用于识别主人的B站账号，在互动中区分对待
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .settings import DATA_DIR


@dataclass
class OwnerInfo:
    """主人信息"""
    mid: str = ""              # B站UID
    name: str = ""             # B站昵称
    is_logged_in_owner: bool = False  # 当前登录账号是否就是主人
    configured: bool = False   # 是否配置了 owner_mid
    notes: str = ""            # 备注

    def is_owner(self, uid: str | int) -> bool:
        """检查某个UID是否是主人"""
        if not self.mid:
            return False
        return str(uid) == str(self.mid)

    def is_owner_name(self, name: str) -> bool:
        """检查某个名称是否是主人"""
        if not self.name:
            return False
        return name.strip() == self.name.strip()


class OwnerRecognizer:
    """主人识别器 - 管理主人UID相关的所有逻辑"""

    def __init__(self):
        self._owner_file = DATA_DIR / "owner_profile.json"
        self._owner_info: OwnerInfo | None = None

    @property
    def info(self) -> OwnerInfo:
        if self._owner_info is None:
            self._owner_info = self._load()
        return self._owner_info

    def _load(self) -> OwnerInfo:
        """从配置和数据文件加载主人信息"""
        info = OwnerInfo()

        # 1. 从 config.json 读取 owner_mid
        config = self._read_json(DATA_DIR / "config.json")
        owner_mid = str(config.get("bilibili", {}).get("owner_mid", "")).strip()
        if owner_mid:
            info.mid = owner_mid
            info.configured = True

        # 2. 从 Cookies 读取当前登录的UID
        cookies = self._read_json(DATA_DIR / "bilibili_cookies.json")
        logged_mid = str(cookies.get("DedeUserID", "")).strip()
        
        # 3. 从 owner_profile.json 读取已存储的主人信息
        profile = self._read_json(self._owner_file)
        if profile.get("name"):
            info.name = profile["name"]
        if profile.get("mid") and not info.mid:
            info.mid = str(profile["mid"])
        if profile.get("notes"):
            info.notes = profile["notes"]

        # 4. 判断当前登录账号是否是主人
        if info.mid and logged_mid and str(info.mid) == str(logged_mid):
            info.is_logged_in_owner = True

        # 5. 如果没配置 owner_mid 但登录了，自动填充
        if not info.mid and logged_mid:
            info.mid = logged_mid
            info.configured = False
            # 自动保存
            self._save_profile(logged_mid, info.name or "", "自动检测")

        return info

    def set_owner(self, mid: str, name: str = "", notes: str = "") -> OwnerInfo:
        """手动设置主人UID"""
        self._save_profile(mid, name, notes)
        # 同步到 config.json
        config = self._read_json(DATA_DIR / "config.json")
        config.setdefault("bilibili", {})["owner_mid"] = mid
        self._write_json(DATA_DIR / "config.json", config)
        # 刷新
        self._owner_info = None
        return self.info

    def detect_from_login(self, uid: str, name: str = "") -> OwnerInfo:
        """从登录信息检测主人（如果未配置 owner_mid）"""
        info = self.info
        if info.configured:
            return info  # 已配置，不自动覆盖

        self._save_profile(uid, name or info.name, "从登录自动检测")
        self._owner_info = None
        return self.info

    def owner_context_prompt(self) -> str:
        """生成用于 System Prompt 的主人上下文"""
        info = self.info
        if not info.mid:
            return ""

        parts = [f"【主人信息】B站UID: {info.mid}"]
        if info.name:
            parts.append(f"主人昵称: {info.name}")
        if info.is_logged_in_owner:
            parts.append("当前登录账号即为主人账号")
        parts.append("对主人的评论和私信应更加自然、亲切，但仍需保持边界感。")
        if info.notes:
            parts.append(f"主人备注: {info.notes}")
        return "\n".join(parts)

    def should_skip_interaction(self, up_uid: str | int, up_name: str = "") -> tuple[bool, str]:
        """
        判断是否应该跳过与某个UP主的互动
        返回: (是否跳过, 原因)
        """
        info = self.info
        if not info.mid:
            return False, ""

        # 如果是主人自己的视频
        if info.is_owner(str(up_uid)):
            # 对主人的视频，可以看但不自动互动（避免尴尬）
            return True, "这是主人的视频，跳过自动互动"

        return False, ""

    def is_owner_comment(self, user_uid: str | int) -> bool:
        """检查评论者是否是主人"""
        info = self.info
        if not info.mid:
            return False
        return str(user_uid) == str(info.mid)

    def get_owner_affinity_multiplier(self, user_uid: str | int) -> float:
        """获取对主人互动的好感度倍率"""
        if self.is_owner_comment(user_uid):
            return 1.5  # 对主人的互动好感度变化 ×1.5
        return 1.0

    # ── 工具 ──
    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            if path.exists():
                import json
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[owner] JSON读取失败 {path}: {e}")
        return {}

    def _write_json(self, path: Path, data: dict) -> None:
        try:
            import json
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception as e:
            print(f"[owner] JSON写入失败 {path}: {e}")

    def _save_profile(self, mid: str, name: str, notes: str):
        self._write_json(self._owner_file, {
            "mid": str(mid),
            "name": name,
            "notes": notes,
        })
