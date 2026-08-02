import asyncio

from brain._brain_video import BrainVideoMixin


class _DegradedBrain(BrainVideoMixin):
    @staticmethod
    def _is_ai_degraded():
        return True


def test_degraded_subtitle_verification_can_use_keyword_fallback():
    result = asyncio.run(
        _DegradedBrain()._ai_verify_subtitle_content(
            "Python async tutorial",
            "This Python tutorial explains async functions, await expressions, and tasks.",
        )
    )

    assert len(result) == 3
    assert isinstance(result[0], bool)
    assert 0 <= result[1] <= 1
