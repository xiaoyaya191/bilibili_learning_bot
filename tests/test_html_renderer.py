from services.html_renderer import (
    ensure_ppt_container,
    markdown_to_reading_html,
    markdown_to_slides_html,
    render_slide_html,
    strip_markdown_code_fence,
)
from services.video_to_ppt import THEMES, _unwrap_ppt_container, build_full_html, build_slide_prompt, count_slide_elements, normalize_theme_name


def test_strip_markdown_code_fence_html():
    assert strip_markdown_code_fence("```html\n<div>ok</div>\n```") == "<div>ok</div>"


def test_ensure_ppt_container_wraps_plain_text():
    fragment = ensure_ppt_container("hello", title="测试")
    assert fragment.startswith('<div class="ppt-container">')
    assert 'class="slide active"' in fragment
    assert "bilibili_learning_bot" in fragment


def test_markdown_to_reading_html_groups_lists():
    html = markdown_to_reading_html("# 标题\n\n## 小节\n- A\n- B", "报告")
    assert "<!doctype html>" in html
    assert "<ul><li>A</li><li>B</li></ul>" in html
    assert "LEARNING REPORT" in html


def test_markdown_to_slides_html_uses_claude_wrapper():
    html = markdown_to_slides_html("# 标题\n\n## 小节\n- A", "报告")
    assert "slide-container" in html
    assert "DEEP RESEARCH" in html
    assert "lucide.createIcons" in html


def test_render_slide_html_normalizes_fragment():
    html = render_slide_html("plain text", title="普通文本")
    assert "slide-container" in html
    assert "普通文本" in html


def test_legacy_claude_themes_use_the_single_canonical_engine():
    fragment = '<div class="ppt-container"><div class="slide active" data-index="0">x</div></div>'
    html = build_full_html(fragment, "claude_slides_v2")
    assert normalize_theme_name("claude") == "claude_slides"
    assert "claude" not in THEMES
    assert "claude_slides_v2" not in THEMES
    assert "slide-container" in html
    assert "theme-toggle" in html


def test_deck_wrapper_strips_a_truncated_ppt_container_without_rendering_text():
    broken = 'class="ppt-container"><div class="slide active" data-index="0">x</div></div>'
    assert _unwrap_ppt_container(broken).startswith('<div class="slide active"')
    html = build_full_html(broken, "claude_slides")
    assert '<div class="slide-container">class="ppt-container">' not in html
    assert '((cur+1)/total)*100' in html
    assert '[data-theme="dark"] .slide blockquote' in html


def test_canonical_claude_prompt_names_the_reference_template():
    prompt = build_slide_prompt({"title": "测试", "stats": {}}, "字幕", "claude_slides")
    assert "bilibili_learning_bot_slides.html" in prompt


def test_requested_slide_count_is_strict_and_counts_only_slide_elements():
    prompt = build_slide_prompt({"title": "测试", "stats": {}}, "字幕", "claude_slides", slide_count=10)
    assert "生成 10 个完整slide" in prompt
    fragment = '<div class="slide active"></div><div class="slide-content"></div><div class="slide"></div>'
    assert count_slide_elements(fragment) == 2
