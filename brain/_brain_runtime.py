"""brain/_brain_runtime.py — AgentBrain 运行时 & 记忆持久化 mixin"""
from brain._mixin_imports import *
from utils.helpers import _load_json_file, _save_json_file

class BrainRuntimeMixin:
    """Runtime clock, memory load/save"""

    def update_runtime_clock(self, starting=False):
        now_text = datetime.now().isoformat(timespec="seconds")
        state = _load_json_file(RUNTIME_STATE_FILE, {})
        if starting:
            state["previous_seen_at"] = self.previous_seen_at
            state["current_start_at"] = now_text
        state["current_heartbeat_at"] = now_text
        state["last_seen_at"] = now_text
        _save_json_file(RUNTIME_STATE_FILE, state)
        self.runtime_state = state
        return state

    def _load_memory(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data.get("known_ups"), list):
                    old_list = data["known_ups"]
                    new_dict = {}
                    for item in old_list:
                        if isinstance(item, str):
                            new_dict[item] = {"uid": None, "favorited": False, "followed": False}
                        elif isinstance(item, dict) and "name" in item:
                            new_dict[item["name"]] = {
                                "uid": item.get("uid"),
                                "favorited": item.get("favorited", False),
                                "followed": item.get("followed", False)
                            }
                    data["known_ups"] = new_dict
                    self._save_memory_to_disk(data)
                if isinstance(data.get("known_ups"), dict):
                    for k, v in data["known_ups"].items():
                        if isinstance(v, dict) and "followed" not in v:
                            v["followed"] = False
                return data
            except (OSError, json.JSONDecodeError) as e:
                log(f'加载JSON文件失败: {e}', 'DEBUG')
        return {"known_ups": {}, "history": []}
    
    def _save_memory_to_disk(self, data=None):
        if data is None:
            data = self.memory
        try:
            tmp = MEMORY_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, MEMORY_FILE)
        except OSError as e:
            log(f'文件操作失败: {e}', 'DEBUG')

    def _save_memory(self):
        self._save_memory_to_disk(self.memory)
