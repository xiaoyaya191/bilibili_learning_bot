from pathlib import Path


def test_tutor_composer_and_resizable_sidebar_are_present():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        'id="sidebarCollapse"',
        'id="sidebarResize"',
        "function initSidebarLayout()",
        "function toggleDesktopSidebar()",
        'class="tutor-composer"',
        'class="tutor-icon-action primary"',
        'id="tutorHtmlStyle"',
        "platformIcons={bilibili:'tv'",
        "data-lucide=\"code-xml\"",
    ):
        assert marker in template

    assert '.sidebar.collapsed{width:64px' in template
    assert '#pg-tutor .chat-log{min-height:160px' in template
