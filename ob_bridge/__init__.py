"""ob_bridge — OpenBiliClaw 集成桥梁

零依赖 brain 核心逻辑的纯工具模块。
所有与 OB 的 HTTP 通信均通过此模块，brain 不得直连 OB API。
"""

from ob_bridge.client import OBClient
from ob_bridge.types import OBMode, RecommendationItem, OBStatus
from ob_bridge.health import detect_ob, launch_ob, ensure_ob_ready, auto_detect_mode

__all__ = [
    "OBClient",
    "OBMode",
    "RecommendationItem",
    "OBStatus",
    "detect_ob",
    "launch_ob",
    "ensure_ob_ready",
    "auto_detect_mode",
]
