"""Validated opt-in self-evolution settings; hard boundaries are not configurable by AI."""
import math
from copy import deepcopy

DEFAULTS = {
    "enabled": False, "auto_enabled": False, "auto_apply": False,
    "reflect_interval_events": 100, "min_events_for_reflect": 3,
    "layers": ["parameters", "knowledge", "strategy"], "sources": ["videos", "learning", "diary"],
    "lookback_days": 30, "max_events": 200, "max_source_chars": 18000,
    "parameter_interval_hours": 24, "knowledge_interval_hours": 168, "strategy_interval_hours": 720,
    "trigger_mode": "time_and_events", "weekdays": [0, 1, 2, 3, 4, 5, 6], "time_windows": [],
    "observation_hours": 336, "max_parameter_step": 0.05, "daily_ai_limit": 2, "retry_minutes": 30,
    "model": "", "temperature": 0.2, "max_tokens": 2000, "timeout_seconds": 180,
    "custom_prompt": "", "goal_keywords": [], "auto_apply_parameters": False,
}
PARAMETERS = {"exploration_rate": (0, .3, .12), "novelty_weight": (0, 1, .4),
              "goal_weight": (0, 1, .4), "source_balance_weight": (0, 1, .2)}
LAYERS = {"parameters": "参数微调", "knowledge": "知识结构", "strategy": "策略说明书"}


def validate_settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("进化设置包含未知字段")
    result = dict(deepcopy(DEFAULTS), **value)
    for key in ('enabled', 'auto_enabled', 'auto_apply', 'auto_apply_parameters'):
        if type(result[key]) is not bool:
            raise ValueError(key + ' 必须为开关')
    result['auto_apply'] = False
    ranges = {'reflect_interval_events': (1, 1000), 'min_events_for_reflect': (1, 1000),
              'lookback_days': (1, 365), 'max_events': (5, 1000), 'max_source_chars': (1000, 50000),
              'parameter_interval_hours': (1, 8760), 'knowledge_interval_hours': (1, 8760),
              'strategy_interval_hours': (1, 8760), 'observation_hours': (1, 720),
              'daily_ai_limit': (1, 20), 'retry_minutes': (1, 1440), 'max_tokens': (300, 8000), 'timeout_seconds': (10, 600)}
    for key, (minimum, maximum) in ranges.items():
        if type(result[key]) is not int or not minimum <= result[key] <= maximum:
            raise ValueError(key + ' 超出范围')
    for key, minimum, maximum in [('temperature', 0, 2), ('max_parameter_step', .01, .2)]:
        if type(result[key]) not in (int, float) or not math.isfinite(result[key]) or not minimum <= result[key] <= maximum:
            raise ValueError(key + ' 超出范围')
    for key, choices in [('layers', LAYERS), ('sources', ('videos', 'learning', 'diary'))]:
        if not isinstance(result[key], list) or not result[key] or any(not isinstance(item, str) or item not in choices for item in result[key]):
            raise ValueError(key + ' 至少选择一项有效内容')
        result[key] = list(dict.fromkeys(result[key]))
    if result['trigger_mode'] not in ('time', 'events', 'time_and_events', 'time_or_events'):
        raise ValueError('触发模式无效')
    if not isinstance(result['goal_keywords'], list) or len(result['goal_keywords']) > 30 or any(not isinstance(item, str) or not item.strip() or len(item) > 80 for item in result['goal_keywords']):
        raise ValueError('目标关键词最多30项，每项1-80字符')
    for key, limit in [('model', 200), ('custom_prompt', 4000)]:
        if not isinstance(result[key], str) or len(result[key]) > limit:
            raise ValueError(key + ' 内容无效')
    from services.diary_scheduler import validate_settings as validate_diary
    schedule = validate_diary({'weekdays': result['weekdays'], 'time_windows': result['time_windows']})
    result['weekdays'], result['time_windows'] = schedule['weekdays'], schedule['time_windows']
    return result


def settings(config_data=None):
    if config_data is None:
        from core.config import load_config
        config_data = load_config()
    return validate_settings(config_data.get('self_evolution', {}))
