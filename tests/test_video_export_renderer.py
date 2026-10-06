import re

import pytest

from services.html_renderer import markdown_to_reading_html
from services.video_export_renderer import render_reference_html
from services.video_to_ppt import PUBLIC_THEME_IDS, build_full_html, build_slide_prompt


FRAGMENT = '<div class="ppt-container"><div class="slide active"><h1>测试页面</h1></div><div class="slide"><h2>第二章</h2></div></div>'


@pytest.mark.parametrize('theme_id', PUBLIC_THEME_IDS)
def test_every_saved_style_renders_identical_reference_layout(theme_id):
    assert build_full_html(FRAGMENT, theme_id, True) == build_full_html(FRAGMENT, 'claude_slides', True)


def test_shell_contains_one_set_of_controls_and_offline_icons():
    output = render_reference_html(FRAGMENT)
    for control in ('progressFill', 'chapterDrawer', 'chapterList', 'contentsButton', 'prevButton', 'nextButton', 'readingButton', 'playButton', 'fullscreenButton', 'downloadButton', 'printButton', 'themeToggle'):
        assert output.count(f'id="{control}"') == 1
    assert 'LEARNING / STUDIO' in output
    assert 'lucide.createIcons' in output
    assert not re.search(r'<(?:script|link)\b[^>]*(?:src|href)=["\']https?://', output, re.I)
    assert '@@TITLE@@' not in output
    assert '<div class="ppt-container">' not in output


def test_title_is_escaped_and_fragment_remains_intact():
    output = render_reference_html(FRAGMENT, title='<危险> & "标题"')
    assert '<title>&lt;危险&gt; &amp; &quot;标题&quot;</title>' in output
    assert '<h2>第二章</h2>' in output
    assert '<title>测试页面</title>' in render_reference_html(FRAGMENT)


def test_motion_mode_and_accessible_fallbacks():
    output = render_reference_html(FRAGMENT, enhanced_animations=False)
    assert 'data-motion="light"' in output
    assert 'data-motion="full"' in render_reference_html(FRAGMENT)
    assert 'prefers-reduced-motion: reduce' in output
    assert '@media print' in output
    assert 'role="progressbar"' in output
    assert 'aria-modal="true"' in output
    assert 'slide.inert' in output


def test_reading_exports_use_same_layout_and_preserve_escaped_content():
    output = markdown_to_reading_html('## 一节\n- <内容>', '学习报告')
    assert 'class="reading-mode"' in output
    assert '<li>&lt;内容&gt;</li>' in output
    assert 'id="downloadButton"' in output
    assert 'id="progressFill"' in output


def test_prompt_leaves_navigation_to_reference_engine():
    output = build_slide_prompt({'title': '测试', 'stats': {}}, '字幕', 'terminal')
    assert '不要重复生成导航' in output
    assert 'data-target' in output
    assert 'slide-cover' in output


def test_generic_html_document_export_uses_reading_engine(tmp_path, monkeypatch):
    from pathlib import Path
    from core import user_data
    from services.document_export import export_text

    monkeypatch.setattr(user_data, 'ARTIFACTS_DIR', tmp_path)
    output_path = Path(export_text('## 笔记\n- <安全文本>', '学习笔记', fmt='html'))
    output = output_path.read_text(encoding='utf-8')
    assert output_path.parent == tmp_path / 'exports'
    assert 'id="readingButton"' in output
    assert '&lt;安全文本&gt;' in output


def test_reference_geometry_and_preview_share_canonical_assets():
    from services.video_export_renderer import ROOT, REFERENCE_STYLE_VERSION

    output = render_reference_html(FRAGMENT)
    preview = (ROOT / 'video_html_preview.html').read_text(encoding='utf-8')
    for asset in ('reference.css', 'runtime.js'):
        content = (ROOT / 'templates' / 'video_export' / asset).read_text(encoding='utf-8')
        assert content in output
        assert content in preview
    assert f'data-export-style="{REFERENCE_STYLE_VERSION}"' in preview
    assert 'width:80vw; max-width:960px; height:auto;' in output
    assert 'id="downloadButton"' in output.split('id="chapterDrawer"', 1)[1]
    assert output.count('class="header-actions"') == 1
    assert 'assets/js/lucide.js' in preview


def test_render_slide_html_preserves_requested_document_title():
    from services.html_renderer import render_slide_html

    assert '<title>自定义名称</title>' in render_slide_html(FRAGMENT, title='自定义名称')


def test_mindmap_uses_reference_shell_and_safe_script_data():
    from services.mindmap_export import markdown_to_mindmap_html

    output = markdown_to_mindmap_html('# 测试\n- </script><script>alert(1)</script>', theme='dark')
    assert 'data-export-style="project-intro-2026-10-07"' in output
    assert 'id="mindmap"' in output
    assert 'id="themeToggle"' in output
    assert 'data-theme="dark"' in output
    assert 'ResizeObserver' in output
    assert 'const markdown = "# 测试\\n- \\u003c/script' in output
    assert '<script>alert(1)</script>' not in output
    assert not re.search(r'<script[^>]+src=["\']https?://', output)


def test_reference_prompt_resolves_real_reference_file():
    from services.video_export_renderer import ROOT
    from services.video_to_ppt import _load_examples_info

    assert '唯一视觉参考' in _load_examples_info(str(ROOT))
