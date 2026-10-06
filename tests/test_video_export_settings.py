from services.video_to_ppt import PUBLIC_THEME_IDS, THEMES, normalize_theme_name, strip_export_watermarks


def test_public_export_themes_are_claude_plus_ten():
    assert len(PUBLIC_THEME_IDS) == 11
    assert PUBLIC_THEME_IDS[0] == "claude_slides"
    assert set(THEMES) == set(PUBLIC_THEME_IDS)
    assert normalize_theme_name("dark") == "claude_slides"


def test_disabled_watermark_removes_slide_and_fixed_marks():
    html = '<body><div class="slide"><div class="logo-mark">bilibili_learning_bot</div></div>' \
           '<div style="position:fixed">bilibili_learning_bot 视频学习助手</div></body>'
    cleaned = strip_export_watermarks(html)
    assert "logo-mark" not in cleaned
    assert "视频学习助手" not in cleaned
    assert '<div class="slide">' in cleaned
