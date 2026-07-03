"""tests/test_reply_safety.py — 测试 services/reply_safety.py"""
import sys
sys.path.insert(0, '.')

from security.guard import ReplySafetyGuard


class TestReplySafety:
    def setup_method(self):
        self.guard = ReplySafetyGuard({
            "reply_safety": {
                "enabled": True,
                "block_on_incoming": True,
                "block_on_outgoing": True,
                "block_political_video_comments": True,
                "blocked_keywords": ["测试敏感词", "违禁词"],
            }
        })

    def test_blocks_single_keyword(self):
        """单通用词不拦截（防误杀）"""
        assert not self.guard.should_block("这里包含测试敏感词在内")

    def test_blocks_multi_keyword(self):
        """2+ 通用词拦截"""
        assert self.guard.should_block("这里包含测试敏感词和违禁词")

    def test_blocks_high_risk(self):
        """高风险词单次即拦截"""
        guard = ReplySafetyGuard({
            "reply_safety": {
                "enabled": True,
                "blocked_keywords": ["台独", "香港", "旅行"],
            }
        })
        assert guard.should_block("讨论台独话题")
        assert not guard.should_block("香港美食攻略")  # 单通用词不拦
        assert guard.should_block("香港旅行攻略")       # 双通用词拦截

    def test_passes_clean_text(self):
        assert not self.guard.should_block("这是正常的评论内容")

    def test_empty_text(self):
        assert not self.guard.should_block("")

    def test_find_hits(self):
        hits = self.guard.find_hits("这句话有测试敏感词和违禁词")
        assert "测试敏感词" in hits
        assert "违禁词" in hits

    def test_find_hits_empty(self):
        assert self.guard.find_hits("正常内容") == []

    def test_review_blocks_incoming(self):
        """2+ 通用词命中触发拦截"""
        ok, reason, hits = self.guard.review(
            incoming="包含测试敏感词和违禁词的消息",
            outgoing="正常回复"
        )
        assert not ok
        assert "测试敏感词" in reason

    def test_review_allows_single_common(self):
        """单通用词不触发拦截"""
        ok, reason, hits = self.guard.review(
            incoming="包含测试敏感词的消息",
            outgoing="正常回复"
        )
        assert ok

    def test_review_passes_clean(self):
        ok, reason, hits = self.guard.review(
            incoming="正常消息",
            outgoing="正常回复"
        )
        assert ok

    def test_disabled_guard(self):
        guard = ReplySafetyGuard({
            "reply_safety": {"enabled": False, "blocked_keywords": ["敏感"]}
        })
        assert not guard.should_block("包含敏感词的文本")

    def test_filter_replies(self):
        replies = [
            {"text": "正常回复"},
            {"text": "包含测试敏感词的回复"},              # 单通用词 → 放行
            {"text": "包含测试敏感词和违禁词的回复"},       # 双通用词 → 拦截
            {"text": "另一个正常回复"},
        ]
        filtered = self.guard.filter_replies(replies)
        assert len(filtered) == 3  # 只拦掉双命中那条

    def test_political_video_blocked_high_risk(self):
        """高风险词单次即拦截"""
        assert not self.guard.is_video_comment_safe(
            "关于台独的视频标题", "视频描述"
        )

    def test_political_video_blocked_multi_hit(self):
        """通用词 2+ 命中才拦截"""
        assert not self.guard.is_video_comment_safe(
            "关于台湾和香港的视频", "讨论政府和政治"
        )

    def test_political_video_single_common_allowed(self):
        """单通用词不拦截"""
        assert self.guard.is_video_comment_safe(
            "台湾美食旅游攻略", "介绍当地小吃"
        )

    def test_normal_video_safe(self):
        assert self.guard.is_video_comment_safe(
            "Python教程", "学习Python编程"
        )
