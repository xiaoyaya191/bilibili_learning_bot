"""Self-contained reference-style learning deck renderer."""
from __future__ import annotations

import html
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_STYLE_VERSION = 'project-intro-2026-10-07'


@lru_cache(maxsize=8)
def _asset(name: str) -> str:
    return (ROOT / 'templates' / 'video_export' / name).read_text(encoding='utf-8')


def render_reference_html(fragment: str, *, enhanced_animations: bool = True, reading: bool = False, title: str = '') -> str:
    from services.video_to_ppt import _unwrap_ppt_container
    content = _unwrap_ppt_container(fragment)
    if not title:
        match = re.search(r'<h[12]\b[^>]*>([\s\S]*?)</h[12]>', content, re.I)
        title = html.unescape(re.sub(r'<[^>]+>', ' ', match.group(1))).strip() if match else '视频学习页面'
    icon_path = ROOT / 'assets' / 'js' / 'lucide.js'
    icons = icon_path.read_text(encoding='utf-8') if icon_path.exists() else 'window.lucide={createIcons:function(){}};'
    values = {
        'STYLE_VERSION': REFERENCE_STYLE_VERSION,
        'TITLE': html.escape(title, quote=True), 'CSS': _asset('reference.css'),
        'MOTION': 'full' if enhanced_animations else 'light',
        'BODY_CLASS': 'reading-mode' if reading else '', 'SLIDES': content,
        'ICONS': icons.replace('</script', '<' + chr(92) + '/script'), 'JS': _asset('runtime.js'),
    }
    return re.sub(r'@@([A-Z_]+)@@', lambda match: values[match.group(1)], _asset('shell.html'))
