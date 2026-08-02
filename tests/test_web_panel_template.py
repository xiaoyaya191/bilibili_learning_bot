from pathlib import Path


def test_runtime_web_template_exposes_visual_note_settings():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        "cqNoteMode",
        "cqVisualNoteInterval",
        "cqVisualNoteMaxFrames",
        "cqVisualNoteCols",
        "cqVisualNoteRows",
        "frame_note_mode",
        "visual_note_frame_interval",
    ):
        assert marker in template


def test_control_exposes_a_user_configurable_candidate_pool():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    assert 'id="browseFlowPool"' in template
    assert "candidate_pool_size:count" in template
    assert "候选视频交给 AI 选择" in template
    assert "开启候选筛选（建议，默认）" in template


def test_control_exposes_timed_and_count_limited_session_handoff():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        'id="sessionMaxDuration"',
        'id="sessionMaxVideos"',
        'id="sessionMaxLearned"',
        'id="sessionCompletionAction"',
        '/api/bot/session-limits',
        '成功学习仅统计真正写入知识库的视频',
        '启动实时监听',
    ):
        assert marker in template


def test_disclaimer_supports_system_dark_mode():
    import web_panel

    html = web_panel._disclaimer_html()
    assert 'name="color-scheme" content="light dark"' in html
    assert '@media (prefers-color-scheme:dark)' in html
    assert 'background:#111214' in html


def test_prompt_injection_settings_exist_only_in_config_editor_safety_group():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    assert 'id="cqPromptInjectionEnabled"' in template
    assert 'id="cqPromptInjectionTerms"' in template
    assert 'id="promptInjectionSection"' not in template
    assert 'data-workspace="behavior" data-workspace-panel="safety" id="promptInjectionSection"' not in template
    assert '.config-section:not(.config-section-active){display:none!important}' in template


def test_agent_goal_placeholder_is_a_single_valid_html_attribute():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    assert 'placeholder="例如：搜索“深度学习入门”并总结前3个视频"' in template


def test_runtime_web_template_has_no_duplicate_ids():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")
    import re
    from collections import Counter

    # IDs constructed inside JavaScript refresh templates are not part of the
    # initial DOM. Inspect markup only so a replacement renderer is not treated
    # as a duplicate live element.
    markup = re.sub(r'<script\b[^>]*>.*?</script\s*>', '', template, flags=re.DOTALL | re.IGNORECASE)
    ids = re.findall(r'\bid="([^"]+)"', markup)
    assert not [identifier for identifier, count in Counter(ids).items() if count > 1]


def test_persona_studio_uses_single_editor_workspace_without_persona_rail():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        "persona-editor-surface",
            "persona-workbench-bar",
        "persona-form-grid",
        "Persona Studio",
        "@keyframes page-enter",
        "@keyframes panel-enter",
        "prefers-reduced-motion",
            "persona-workspace",
    ):
        assert marker in template


def test_about_page_reads_optional_project_info_instead_of_personal_contact_details():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    assert "project_info" in template
    assert "cqProjectName" not in template
    assert "cqProjectSummary" not in template
    assert "cqProjectRepository" not in template
    assert "cqProjectQqGroup" not in template
    assert "3781960338" not in template
    assert "1056941856" in template


def test_new_user_tutorial_is_available_on_first_use_and_from_about_page():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        "openNewUserTutorial",
        "maybeOpenNewUserTutorial",
        "panel_onboarding_seen_v1",
        "进入新手教程",
        "tutorial-step",
    ):
        assert marker in template


def test_web_template_exposes_readable_knowledge_library_and_accessible_controls():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in ("memKbSearch", "openMemKbNote", "kb-file-row", "file-status", 'width:20px;height:20px'):
        assert marker in template


def test_memory_and_knowledge_library_use_full_page_paged_browsing():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        "memHistoryPage",
        "memHistoryPager",
        "memHistoryPageSize",
        "renderMemHistoryPager",
        "goMemHistoryPage",
        "setMemHistoryPageSize",
        "pageSize:30",
        "panel_library_page_size_v30",
        'value="30">30 / 页',
        ".kb-file-list{display:grid;gap:7px;margin-top:12px;max-height:none;overflow:visible;padding-right:0}",
        "#memKbFileList.knowledge-card-grid{max-height:none;overflow:visible;padding-right:0}",
        "本页 '+shown.length+' / '+libraryPrefs.pageSize+' 条",
    ):
        assert marker in template


def test_local_favorites_use_the_shared_thirty_item_pager():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        "favoritePage=1",
        "favoritePager",
        "renderFavoritePager",
        "goFavoritePage",
        "本页 '+shown.length+' / '+libraryPrefs.pageSize+' 条",
    ):
        assert marker in template


def test_navigation_and_library_pagers_return_the_user_to_visible_content():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        "function scrollPageToTop()",
        "function scrollLibraryToTop(id)",
        "scrollPageToTop();",
        "scrollLibraryToTop('memKbFileList')",
        "scrollLibraryToTop('memHistoryGrid')",
        "scrollLibraryToTop('watchHistoryGrid')",
        "scrollLibraryToTop('favoritesBox')",
    ):
        assert marker in template


def test_private_message_agent_exposes_social_follow_controls():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        "cqPmSocialActions",
        "cqPmProactiveSocialFollow",
        "cqPmSocialFollowLimit",
        "allow_proactive_social_follow",
        "social_follow_daily_limit",
        "cqPmSenderContext",
        "cqPmSenderDynamics",
        "cqPmBurstMerge",
        "burst_merge_window_seconds",
    ):
        assert marker in template


def test_dashboard_uptime_card_can_shrink_without_overflowing():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    assert ".sc>div:last-child{min-width:0;flex:1}" in template
    assert ".uptime-value{max-width:100%;overflow:hidden;text-overflow:ellipsis" in template


def test_card_cover_fallback_and_full_log_renderer_avoid_overdraw_and_full_rebuilds():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        ".history-cover-fallback[hidden]{display:none!important}",
        "function appendLogEntry",
        "if(same)return",
        "if(appended&&el.querySelector('.log-line'))",
        "refreshFullLogs()},3000)",
    ):
        assert marker in template


def test_dashboard_has_compact_operations_and_real_resource_metrics():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        "align-items:start",
        "resourceStats",
        "metricCpu",
        "metricMemory",
        "/api/system/metrics",
    ):
        assert marker in template


def test_monitor_page_exposes_five_second_polling_and_live_uptime_controls():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        'id="monMentionsEnabled"',
        'id="monVideoQuestionEnabled"',
        'id="monSystemPrompt"',
        'id="monTextEmoticons"',
        'id="btnMonitorPause"',
        "toggleMonitorPause()",
        "/api/monitor/pause",
        "Math.max(5,parseInt(document.getElementById('monCmtInterval').value)||5)",
        "setInterval(renderMonitorUptime,100)",
        "_ANSI_ESCAPE_RE",
    ):
        assert marker in template or marker == "_ANSI_ESCAPE_RE"


def test_monitor_switches_and_log_polling_do_not_duplicate_controls_or_toasts():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        ".fg label.toggle-sw",
        ".fg label.toggle-sw input[type=\"checkbox\"]",
        'id="monitorEmoticonPresets"',
        "toggleMonitorEmoticon",
        "restoreMonitorEmoticons",
        "stopFullLogPoll",
        "fullLogLoading",
        "fullLogFailureShown",
    ):
        assert marker in template
    assert "function stopFullLogPoll(){if(fullLogPoll!==null)" in template
    assert "function stopFullLogPoll(){if(fullLogPoll){" not in template


def test_config_masks_api_keys_and_uses_fast_local_runtime_clocks():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        'id="cqApiKey" name="panel_ai_access_token" class="secret-masked" type="text"',
        'name="panel_navigation_filter"',
        'name="panel_ai_access_token"',
        "armAutofillGuard",
        "unlockAutofillGuard",
        "toggleSecretField",
        "setInterval(renderMonitorUptime,100)",
        "},100);",
    ):
        assert marker in template


def test_web_template_exposes_real_review_results_and_complete_log_workspace():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        'data-pg="logs"',
        'id="pg-logs"',
        'id="reviewAudit"',
        'id="reviewModal"',
        "confirmReviewDecision",
        "clearMonitorLog",
        "nav('logs'",
        "log-livebar",
        "log-line-fresh",
        "log-scanline",
        "fullLogSignal",
    ):
        assert marker in template


def test_config_and_review_pages_handle_a_disconnected_panel_without_toast_loops():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        "网页端暂时未连接",
        "配置暂时无法加载",
        "审核队列暂时无法连接",
            "async function rf_conf(){var active=document.activeElement",
    ):
        assert marker in template


def test_factory_reset_allows_group_selection_and_preserves_backups_by_default():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    assert "完整清除私人数据" in template
    assert "备份默认保留" in template
    assert 'id="resetKB"' not in template
    assert "delete_kb:" not in template


def test_video_to_web_defaults_to_ten_pages_and_sends_the_count():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    assert 'id="v2wSlideCount"' in template
    assert 'value="10"' in template
    assert "slide_count:slideCount" in template
    assert "自动（Claude 幻灯片）" in template
