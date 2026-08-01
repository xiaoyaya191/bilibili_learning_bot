"""brain/_brain_journal.py — AgentBrain prompt构建 & 日记 & 事件记录 mixin"""
from brain._mixin_imports import *

class BrainJournalMixin:
    """Prompt构建、日记、事件记录、学习日志"""

    def build_dynamic_brain_prompt(self, up_name):
        persona_block = self.persona_mgr.build_prompt_block()
        mood_block = self.mood_mgr.build_prompt_block()
        up_profile = self.user_profile_mgr.build_prompt_block(f"up::{up_name}", up_name)
        return (
            SYSTEM_PROMPT_BRAIN.replace("{bot_name}", get_bot_name()).replace("{memory_ups}", str(self.get_known_up_names()))
            + "\n\n"
            + persona_block
            + "\n"
            + mood_block
            + "\n"
            + up_profile
            + "\n【额外要求】结合当前人格、心情和对该UP主的印象做决策，不要机械重复。"
        )

    def write_journal(self, title, up, score, thought, action_str, url):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"## {timestamp}\n- **视频**: {title} [链接]({url}) (@{up})\n- **评分**: {score}\n- **想法**: {thought}\n- **操作**: {action_str}\n---\n"
        try:
            with open(JOURNAL_FILE, 'a', encoding='utf-8') as f:
                f.write(entry)
            log("日常日记已记录", "NOTE")
        except OSError as e:
            log(f'文件操作失败: {e}', 'DEBUG')

    def record_session_event(self, event_type, **payload):
        item = {
            "time": datetime.now().isoformat(),
            "type": event_type,
            **payload
        }
        self.session_events.append(item)
        self.session_events = self.session_events[-100:]
        self.processed_event_count += 1
        return item

    def write_learning_log(self, category, title, file_path):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(os.path.dirname(LEARNING_LOG_FILE), exist_ok=True)
        relative_path = os.path.relpath(file_path, KNOWLEDGE_BASE_DIR)
        entry = f"- **{timestamp}** | `分类:{category}` | `{title}` | [查看笔记]({relative_path.replace(os.sep, '/')})\n"
        try:
            with open(LEARNING_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(entry)
            log("学习日志已记录", "LEARN")
        except Exception as e:
            log(f"记录学习日志失败: {e}", "ERROR")
