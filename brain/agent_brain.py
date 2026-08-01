"""brain/agent_brain.py — 核心大脑（AgentBrain 主调度器）

重构为 mixin 组合模式，将原 4146 行大文件拆分为多个 <1000 行的模块：
  _brain_init.py      — __init__ 和属性初始化
  _brain_ai.py        — AI调用后端
  _brain_runtime.py   — 运行时时钟和内存
  _brain_ups.py       — UP主记忆和喜欢
  _brain_history.py   — 视频历史管理
  _brain_journal.py   — 日记和学习日志
  _brain_auto.py      — 自动日记和自我进化
  _brain_session.py   — 会话管理（精力、评论、私信、弹幕、UP关注）
  _brain_learn.py     — 学习归档
  _brain_curiosity.py — 好奇心深度搜索
  _brain_video.py     — 视频理解（字幕、ASR、视觉帧）
  _brain_interact.py  — 视觉分析与互动
  _brain_loop.py      — 主循环 run()
"""

from brain._brain_init import BrainInitMixin
from brain._brain_ai import BrainAIMixin
from brain._brain_runtime import BrainRuntimeMixin
from brain._brain_ups import BrainUpsMixin
from brain._brain_history import BrainHistoryMixin
from brain._brain_journal import BrainJournalMixin
from brain._brain_auto import BrainAutoMixin
from brain._brain_session import BrainSessionMixin
from brain._brain_learn import BrainLearnMixin
from brain._brain_curiosity import BrainCuriosityMixin
from brain._brain_video import BrainVideoMixin
from brain._brain_interact import BrainInteractMixin
from brain._brain_loop import BrainLoopMixin


class AgentBrain(
    BrainInitMixin,
    BrainAIMixin,
    BrainRuntimeMixin,
    BrainUpsMixin,
    BrainHistoryMixin,
    BrainJournalMixin,
    BrainAutoMixin,
    BrainSessionMixin,
    BrainLearnMixin,
    BrainCuriosityMixin,
    BrainVideoMixin,
    BrainInteractMixin,
    BrainLoopMixin,
):
    """AgentBrain — 核心大脑调度器

    通过多重继承组合所有功能模块。
    原 4146 行单体类已拆分为 13 个 <1000 行的 mixin 模块。
    """
    pass
