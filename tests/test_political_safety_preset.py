from core.config import POLITICAL_SAFETY_DEFAULT_KEYWORDS
from security.guard import ReplySafetyGuard


def test_political_preset_is_detailed_and_includes_requested_categories():
    keywords = set(POLITICAL_SAFETY_DEFAULT_KEYWORDS)
    assert {"习近平", "台湾", "台独", "六四", "香港", "新疆", "西藏"} <= keywords
    assert len(keywords) >= 60


def test_political_preset_blocks_each_explicit_term_on_its_own():
    guard = ReplySafetyGuard({
        "reply_safety": {
            "enabled": True,
            "blocked_keywords": list(POLITICAL_SAFETY_DEFAULT_KEYWORDS),
        }
    })

    assert guard.should_block("讨论习近平")
    assert guard.should_block("台湾旅行相关内容")
    assert guard.should_block("普通的 Python 教程") is False
