from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_model_actions_are_not_nested_in_a_label_and_manual_entry_is_available():
    panel = (ROOT / "web_panel.html").read_text(encoding="utf-8")
    assert 'class="model-field-actions"' in panel
    assert '<label for="cqModelBrain">模型(对话)</label>' in panel
    assert 'id="cqModelBrain" list="cqModelOptions"' in panel
    assert "api('POST','/api/models/list'" in panel
    assert "api_key='+encodeURIComponent" not in panel
    assert "Array.isArray(window._modelTestSel)" in panel
    assert "sel.length+' 条实际请求" in panel
    assert 'id="mtWorkers" type="number" min="1" max="16" value="1"' in panel
    assert "modelTestPollFailures>=3" in panel


def test_learning_export_keeps_all_settings_with_advanced_fields_collapsed():
    panel = (ROOT / "web_panel.html").read_text(encoding="utf-8")
    page = panel.split('id="pg-learning-tools"', 1)[1].split('id="pg-tokens"', 1)[0]
    assert 'class="learning-export-layout"' in page
    assert '<details class="learning-advanced">' in page
    assert page.index('id="learning-image-content"') < page.index('rag_qa.enabled')
    assert len(re.findall('data-learning-setting=', page)) == 17
    assert '<div>\n    </div>' not in page


def test_persona_page_is_neutral_but_consent_copy_is_red():
    css = (ROOT / "assets/css/persona-evolution.css").read_text(encoding="utf-8")
    assert '#fffbeb' not in css
    assert '#fde68a' not in css
    assert '.pe-consent .pe-dialog-body>p' in css
    assert 'color:var(--red,#c24141)' in css


def test_zero_interest_range_and_config_group_layout_rules():
    panel = (ROOT / "web_panel.html").read_text(encoding="utf-8")
    css = (ROOT / "assets/css/usability.css").read_text(encoding="utf-8")
    assert "range.style.setProperty('--range-value'" in panel
    assert "s.threshold_base==null?6:s.threshold_base" in panel
    assert "f.classList.add('conf-wide')" in panel
    assert '#confQuickContent>.form-hint{grid-column:1/-1' in css
    assert 'var(--range-value,0%)' in css


def test_permission_categories_keep_local_and_platform_distinct():
    script = (ROOT / "assets/js/action-permissions.js").read_text(encoding="utf-8")
    assert "['local', 'platform']" in script
    assert "groups[definition.scope]" in script
    css = (ROOT / "assets/css/action-permissions.css").read_text(encoding="utf-8")
    assert '#5b8def' not in css
    assert '.permission-scope-grid' in css
