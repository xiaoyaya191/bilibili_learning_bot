import collections
import re
from pathlib import Path

import pytest

from core.config import normalize_config
from services.learning_loop import LearningLoopService
from services.like_review import ActionReviewInbox


@pytest.fixture
def panel(monkeypatch, tmp_path):
    import web_panel

    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(web_panel, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(web_panel, 'BOT_RUNTIME_LOG_FILE', tmp_path / 'bot.log')
    monkeypatch.setattr(web_panel, 'MONITOR_RUNTIME_LOG_FILE', tmp_path / 'monitor.log')
    monkeypatch.setattr(web_panel, 'bot_output_lines', ['old bot event'])
    monkeypatch.setattr(web_panel, 'monitor_output_lines', collections.deque(['old monitor event']))
    monkeypatch.setattr(web_panel, '_learning_loop', lambda: LearningLoopService(tmp_path / 'learning.sqlite3', tmp_path / 'kb'))
    web_panel.BOT_RUNTIME_LOG_FILE.write_text('[2026-10-06 12:00:00] old bot event\n', encoding='utf-8')
    web_panel.MONITOR_RUNTIME_LOG_FILE.write_text('[2026-10-06 12:00:01] old monitor event\n', encoding='utf-8')
    return web_panel, web_panel.app.test_client()


@pytest.mark.parametrize('mode', ['learning', 'companion', 'learn_companion', None])
def test_config_modes_always_normalize_to_learning_companion(mode):
    result = normalize_config({'user_experience': {'mode': mode}})
    assert result['user_experience']['mode'] == 'learn_companion'


def test_onboarding_without_topic_creates_no_fake_companion_goal(panel):
    module, client = panel
    result = client.post('/api/onboarding', json={'action': 'configure'}).get_json()
    assert result['ok'] is True
    assert result['learning_mode'] == 'learn_companion'
    assert result['goal'] is None
    assert module._learning_loop().list_goals() == []


def test_legacy_user_experience_get_and_post_do_not_restore_mode(panel):
    module, client = panel
    module.write_json(module.CONFIG_FILE, {'user_experience': {'mode': 'companion', 'topic': 'Python'}})
    assert client.get('/api/user-experience').get_json()['mode'] == 'learn_companion'
    saved = client.post('/api/user-experience', json={'mode': 'companion'}).get_json()
    assert saved['mode'] == 'learn_companion'


def test_goal_api_ignores_legacy_companion_choice(panel):
    _, client = panel
    result = client.post('/api/learning-loop/goals', json={'topic': 'Python', 'mode': 'companion'}).get_json()
    assert result['goal']['mode'] == 'learn_companion'
    assert result['goal']['status'] == 'active'


def test_existing_companion_goal_migrates_without_becoming_active(tmp_path):
    path = tmp_path / 'learning.sqlite3'
    service = LearningLoopService(path)
    goal = service.create_goal('已保存主题')
    with service._connect() as connection:
        connection.execute("UPDATE goals SET mode='companion',status='companion_only' WHERE id=?", (goal['id'],))
    migrated = LearningLoopService(path).get_goal(goal['id'])
    assert migrated['mode'] == 'learn_companion'
    assert migrated['status'] == 'paused'


def test_clear_bot_removes_disk_and_memory_but_preserves_monitor(panel):
    module, client = panel
    response = client.post('/api/logs/clear', json={'source': 'bot'})
    assert response.status_code == 200
    assert response.get_json()['ok'] is True
    assert list(module.bot_output_lines) == []
    assert module.BOT_RUNTIME_LOG_FILE.read_text(encoding='utf-8') == ''
    assert module.MONITOR_RUNTIME_LOG_FILE.read_text(encoding='utf-8') != ''
    assert client.get('/api/logs?source=bot').get_json()['lines'] == []


def test_clear_all_removes_review_audit_without_removing_pending_items(panel):
    module, client = panel
    inbox = ActionReviewInbox(module.DATA_DIR)
    pending = inbox.propose('video_like', '待审核视频', payload={'bvid': 'BV1234567890'})
    inbox.audit_path.write_text('{"action":"old audit"}\n', encoding='utf-8')
    result = client.post('/api/logs/clear', json={'source': 'all'})
    assert result.status_code == 200
    assert result.get_json()['ok'] is True
    assert list(module.bot_output_lines) == []
    assert list(module.monitor_output_lines) == []
    assert inbox.audit_path.read_text(encoding='utf-8') == ''
    assert any(item['id'] == pending['id'] for item in inbox.list(status='pending'))
    assert client.get('/api/logs?source=all').get_json()['lines'] == []


def test_log_clear_reports_io_error_and_preserves_memory(panel, monkeypatch):
    module, client = panel
    original = Path.write_text
    def denied(path, *args, **kwargs):
        if path == module.BOT_RUNTIME_LOG_FILE:
            raise PermissionError('file is busy')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'write_text', denied)
    response = client.post('/api/logs/clear', json={'source': 'bot'})
    assert response.status_code == 500
    assert response.get_json()['ok'] is False
    assert module.bot_output_lines == ['old bot event']


def test_invalid_log_scope_does_not_clear_anything(panel):
    module, client = panel
    assert client.post('/api/logs/clear', json={'source': 'unknown'}).status_code == 400
    assert module.bot_output_lines == ['old bot event']


def test_new_log_events_still_appear_after_clear(panel):
    module, client = panel
    client.post('/api/logs/clear', json={'source': 'bot'})
    new = '[2026-10-06 13:00:00] new event'
    module.bot_output_lines.append(new)
    module.BOT_RUNTIME_LOG_FILE.write_text(new + '\n', encoding='utf-8')
    assert client.get('/api/logs?source=bot').get_json()['lines'][0]['text'] == new


def test_ui_has_complete_guides_and_explicit_learning_goal_urls():
    root = Path(__file__).resolve().parents[1]
    template = (root / 'web_panel.html').read_text(encoding='utf-8')
    guides = (root / 'assets/js/usability.js').read_text(encoding='utf-8')
    learning = (root / 'assets/js/learning-workspace.js').read_text(encoding='utf-8')
    assert 'settingsUseModes' not in template
    assert 'learningGoalMode' not in template
    assert "api=async function(m,u,b,t)" not in template
    assert '新手指南' in guides
    assert 'guideDirectory' in guides
    assert "'?goal_id=' + encodeURIComponent(selected)" in learning
    assert '加入稍后观看' in learning
    assert 'panelConfirm' in learning


def test_review_rules_use_named_weekdays_and_collapsed_advanced_settings():
    root = Path(__file__).resolve().parents[1]
    script = (root / 'assets/js/video-review.js').read_text(encoding='utf-8')
    assert "['周一', '周二', '周三', '周四', '周五', '周六', '周日']" in script
    assert '<details class="review-rule-section">' in script
    assert '示例只填表，不保存、不自动执行' in script


def test_account_workspace_uses_cards_and_in_page_confirmation_dialog():
    root = Path(__file__).resolve().parents[1]
    template = (root / 'templates/accounts.html').read_text(encoding='utf-8')
    script = (root / 'assets/js/accounts.js').read_text(encoding='utf-8')
    assert '<dialog id="accountDialog">' in template
    assert 'account-card' in script
    assert 'prompt(' not in script
    assert 'confirmation !== account.id' in script


def test_log_ui_clears_paused_caches_and_rejects_old_inflight_results():
    template = (Path(__file__).resolve().parents[1] / 'web_panel.html').read_text(encoding='utf-8')
    assert '_pausedLogRenders={};' in template
    assert 'generation!==logClearGeneration' in template
    assert "await clearScopedLogs(fullLogSource)" in template


def test_every_sidebar_feature_has_a_guide_entry():
    root = Path(__file__).resolve().parents[1]
    template = (root / 'web_panel.html').read_text(encoding='utf-8')
    sidebar = template.split('<nav class="sb-nav">', 1)[1].split('</nav>', 1)[0]
    page_ids = set(re.findall(r'data-pg="([^"]+)"', sidebar))
    if "item.dataset.pg='interests'" in template:
        page_ids.add('interests')
    script = (root / 'assets/js/usability.js').read_text(encoding='utf-8')
    keys = {quoted or plain for quoted, plain in re.findall(r"^    (?:'([^']+)'|([\w-]+)): \[", script, re.MULTILINE)}
    assert len(page_ids) == 53
    assert page_ids <= keys


def test_subtitle_switch_is_visible_even_when_asr_is_disabled():
    template = (Path(__file__).resolve().parents[1] / 'web_panel.html').read_text(encoding='utf-8')
    page = template.split('<div class="page" id="pg-asr">', 1)[1]
    assert page.index('id="subtitle-master"') < page.index('id="asrAdvanced"')


def test_invalid_log_request_body_is_rejected(panel):
    _, client = panel
    assert client.post('/api/logs/clear', json=['all']).status_code == 400


def test_review_audit_clear_reports_io_error(panel, monkeypatch):
    _, client = panel
    def denied(_inbox):
        raise PermissionError('audit busy')
    monkeypatch.setattr(ActionReviewInbox, 'clear_audit', denied)
    response = client.post('/api/reviews/audit/clear', json={})
    assert response.status_code == 500
    assert response.get_json()['ok'] is False


def test_config_advanced_inputs_remain_available_but_are_collapsed():
    template = (Path(__file__).resolve().parents[1] / 'web_panel.html').read_text(encoding='utf-8')
    assert "details.className='config-advanced-options'" in template
    assert 'configGroupGuide' in template
