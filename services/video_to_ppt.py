"""services/video_to_ppt.py — B站视频 → PPT风格HTML页面（借鉴AI_Animation模板）

特性：
- 多页幻灯片，←→键盘翻页 + 底部导航点 + 触摸滑动
- 粒子Canvas背景 + SVG噪点 + 渐变暗色主题
- animate-item 级联入场动画
- 支持多种配色主题: dark(默认), purple, cyan, claude_slides；旧 Claude 主题自动兼容到 claude_slides
- Flask预览服务器：生成后本地预览，保存到指定路径（跨平台）
- claude_slides: 基于 bilibili_learning_bot_slides.html 模板的完整动画系统
"""
import os, re, time, json, sys, asyncio, webbrowser, socket, threading
import httpx
from pathlib import Path


def _safe_flush(stream) -> None:
    """flush 兜底：windowed 冻结环境下 sys.stdout 可能为 None。"""
    if stream is not None:
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass


def _utf8_json_request(payload: dict) -> tuple[bytes, dict[str, str]]:
    """Build a UTF-8 request for OpenAI-compatible gateways."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return body, {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body)),
    }

# ── Flask 预览服务器（全局单例） ──
_preview_server = None
_preview_html = ""
_preview_port = 0

# ── 配色主题 ──
THEMES = {
    "dark": {
        "name": "暗夜粒子",
        "bg_start": "#0a0a1a", "bg_end": "#050510",
        "primary": "#e94560", "accent": "#feca57",
        "cyan": "#00d2d3", "purple": "#7b61ff",
        "card_bg": "rgba(255,255,255,0.05)",
        "card_border": "rgba(233,69,96,0.3)",
    },
    "purple": {
        "name": "紫色幻境",
        "bg_start": "#1a1a2e", "bg_end": "#0a0a0f",
        "primary": "#667eea", "accent": "#a0a0ff",
        "cyan": "#45b7d1", "purple": "#764ba2",
        "card_bg": "rgba(102,126,234,0.1)",
        "card_border": "rgba(102,126,234,0.3)",
    },
    "cyan": {
        "name": "青蓝极光",
        "bg_start": "#0a1628", "bg_end": "#051020",
        "primary": "#00d4ff", "accent": "#48cae4",
        "cyan": "#00d4ff", "purple": "#7b2ff7",
        "card_bg": "rgba(0,212,255,0.08)",
        "card_border": "rgba(0,212,255,0.3)",
    },
    "claude_slides": {
        "name": "Claude 幻灯片",
        # 唯一 Claude 风格：bilibili_learning_bot_slides.html 的白/黑/灰+暖橙体系。
        "bg_start": "#FFFFFF", "bg_end": "#F5F5F5",
        "primary": "#D97757", "accent": "#E8916A",
        "cyan": "#4dabf7", "purple": "#da77f2",
        "card_bg": "rgba(250,250,250,0.9)",
        "card_border": "rgba(229,229,229,0.6)",
    },
}

# Every public selector has a concrete palette. Previously many choices in the
# web picker silently fell back to ``dark``; keeping them here makes the saved
# output deterministic as well as the prompt direction.
THEMES.update({
    "light": {"name":"极简白昼","bg_start":"#f8fafc","bg_end":"#e9edf2","primary":"#2563eb","accent":"#0f766e","cyan":"#0284c7","purple":"#7c3aed","card_bg":"rgba(255,255,255,.92)","card_border":"rgba(15,23,42,.12)"},
    "slide": {"name":"幻灯片叙事","bg_start":"#111827","bg_end":"#0f172a","primary":"#f97316","accent":"#facc15","cyan":"#38bdf8","purple":"#a78bfa","card_bg":"rgba(30,41,59,.72)","card_border":"rgba(148,163,184,.25)"},
    "card": {"name":"卡片画廊","bg_start":"#111827","bg_end":"#172554","primary":"#fb7185","accent":"#fbbf24","cyan":"#22d3ee","purple":"#c084fc","card_bg":"rgba(30,41,59,.82)","card_border":"rgba(251,113,133,.28)"},
    "bento": {"name":"Bento 网格","bg_start":"#0f172a","bg_end":"#1e293b","primary":"#38bdf8","accent":"#a3e635","cyan":"#22d3ee","purple":"#818cf8","card_bg":"rgba(30,41,59,.88)","card_border":"rgba(148,163,184,.24)"},
    "glass": {"name":"玻璃拟态","bg_start":"#172554","bg_end":"#312e81","primary":"#67e8f9","accent":"#f9a8d4","cyan":"#22d3ee","purple":"#c4b5fd","card_bg":"rgba(255,255,255,.12)","card_border":"rgba(255,255,255,.25)"},
    "aurora": {"name":"极光渐变","bg_start":"#052e2b","bg_end":"#172554","primary":"#5eead4","accent":"#c4b5fd","cyan":"#67e8f9","purple":"#a78bfa","card_bg":"rgba(15,23,42,.62)","card_border":"rgba(94,234,212,.25)"},
    "neobrutal": {"name":"新野蛮主义","bg_start":"#fef08a","bg_end":"#fca5a5","primary":"#111827","accent":"#2563eb","cyan":"#0891b2","purple":"#7c3aed","card_bg":"#ffffff","card_border":"#111827"},
    "oled": {"name":"深色 OLED","bg_start":"#000000","bg_end":"#050505","primary":"#22d3ee","accent":"#a3e635","cyan":"#22d3ee","purple":"#c084fc","card_bg":"rgba(17,17,17,.92)","card_border":"rgba(163,230,53,.26)"},
    "cyberpunk": {"name":"赛博朋克","bg_start":"#14001f","bg_end":"#05010d","primary":"#f472b6","accent":"#facc15","cyan":"#22d3ee","purple":"#c084fc","card_bg":"rgba(30,5,52,.86)","card_border":"rgba(244,114,182,.34)"},
    "neumorphism": {"name":"新拟态","bg_start":"#dfe5ec","bg_end":"#cdd5df","primary":"#334155","accent":"#2563eb","cyan":"#0ea5e9","purple":"#7c3aed","card_bg":"#dfe5ec","card_border":"rgba(255,255,255,.7)"},
    "liquid_glass": {"name":"液态玻璃","bg_start":"#0f172a","bg_end":"#164e63","primary":"#e0f2fe","accent":"#67e8f9","cyan":"#22d3ee","purple":"#c4b5fd","card_bg":"rgba(255,255,255,.13)","card_border":"rgba(255,255,255,.30)"},
    "nostalgic": {"name":"复古主义","bg_start":"#1d2a3a","bg_end":"#17212b","primary":"#fbbf24","accent":"#fb7185","cyan":"#67e8f9","purple":"#a78bfa","card_bg":"#223047","card_border":"#fbbf24"},
    "linear": {"name":"Linear 风格","bg_start":"#16122d","bg_end":"#111827","primary":"#a78bfa","accent":"#67e8f9","cyan":"#22d3ee","purple":"#a78bfa","card_bg":"rgba(22,18,45,.78)","card_border":"rgba(167,139,250,.30)"},
    "gradient_new": {"name":"新变风","bg_start":"#3b0764","bg_end":"#0c4a6e","primary":"#f9a8d4","accent":"#fde68a","cyan":"#67e8f9","purple":"#c4b5fd","card_bg":"rgba(15,23,42,.58)","card_border":"rgba(255,255,255,.22)"},
    "soft_pop": {"name":"柔和流行","bg_start":"#fff1f2","bg_end":"#e0f2fe","primary":"#db2777","accent":"#2563eb","cyan":"#0ea5e9","purple":"#8b5cf6","card_bg":"rgba(255,255,255,.88)","card_border":"rgba(219,39,119,.18)"},
    "promptport": {"name":"PromptPort","bg_start":"#020617","bg_end":"#071a1a","primary":"#00e5a8","accent":"#67e8f9","cyan":"#22d3ee","purple":"#a78bfa","card_bg":"rgba(15,23,42,.84)","card_border":"rgba(0,229,168,.30)"},
})

STYLE_ART_DIRECTION = {
    "dark":"深色研究界面，红金点缀和克制粒子；内容以章节和数据卡片组织。",
    "light":"高可读的白昼编辑排版，深色正文、蓝绿强调、留白优先。",
    "slide":"电影分镜式叙事，每页一个结论，前后承接明确。", "card":"高密度可扫描卡片画廊，卡片内有结论和依据。",
    "bento":"不规则但对齐的 Bento 网格，突出一项主结论和多个辅助事实。", "glass":"半透明玻璃层次，只用少量发光边界。",
    "aurora":"深色极光背景上的清晰信息层，背景不能降低正文对比度。", "neobrutal":"粗边框、硬阴影、强对比，但文字必须清晰可读。",
    "oled":"纯黑阅读底板、低亮霓虹点缀，避免大面积白色。", "cyberpunk":"霓虹终端氛围，文字仍以内容优先，不做故障字遮挡。",
    "neumorphism":"柔和浮雕控制台，边界和文字对比必须足够。", "liquid_glass":"高透明玻璃层次，信息块有明确轮廓。",
    "nostalgic":"克制的复古 GUI 和等宽标签，不使用像素噪点干扰正文。", "linear":"精简开发者工具感，细边框与紫青点缀。",
    "gradient_new":"鲜明但节制的潮流背景，正文区域必须稳定可读。", "soft_pop":"柔和活泼但非儿童化，圆润结构与清楚层级。",
    "promptport":"黑底绿青开发者产品界面，模块清晰，禁止营销空话。",
}

# Old saved settings and API callers remain valid, but all Claude variants render
# through the one maintained style above.  Keeping this mapping avoids silently
# falling back to the unrelated dark theme for existing users.
_LEGACY_CLAUDE_THEMES = {"claude", "claude_slides_v2"}


def normalize_theme_name(theme_name: str) -> str:
    """Return the public theme ID, preserving compatibility with old configs."""
    normalized = (theme_name or "").strip().lower()
    return "claude_slides" if normalized in _LEGACY_CLAUDE_THEMES else normalized


def count_slide_elements(html: str) -> int:
    """Count actual deck pages, excluding helpers such as ``slide-content``."""
    return len(re.findall(
        r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*(?<![\w-])slide(?![\w-])',
        html or "",
        flags=re.IGNORECASE,
    ))


def _unwrap_ppt_container(fragment: str) -> str:
    """Remove one generated outer container before adding the engine wrapper.

    Some model responses have historically lost the leading ``<div`` while
    retaining ``class=\"ppt-container\">``. Treat that form as an outer
    wrapper too, otherwise browsers render the residual text on the slide.
    """
    text = (fragment or "").strip()
    opening = re.match(
        r'^(?:<div\s+)?class\s*=\s*(["\'])ppt-container\1\s*>\s*',
        text,
        flags=re.IGNORECASE,
    )
    if not opening:
        return text
    text = text[opening.end():]
    return re.sub(r'\s*</div>\s*$', '', text, count=1)

# ── PPT模板 CSS（暗色主题）──
PPT_CSS = r"""
*{margin:0;padding:0;box-sizing:border-box}
body{
    font-family:system-ui,'PingFang SC','Microsoft YaHei',sans-serif;
    background:radial-gradient(circle at bottom left,var(--bg-start) 0%,transparent 50%),
               radial-gradient(circle at top right,var(--bg-end) 0%,transparent 30%),
               #000;
    min-height:100vh;overflow:hidden;color:#fff;position:relative;
    -webkit-font-smoothing:antialiased;
}
body::before{
    content:"";position:fixed;top:0;left:0;width:100%;height:100%;
    background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    opacity:.12;mix-blend-mode:overlay;pointer-events:none;z-index:1;
    animation:noiseMove 20s linear infinite;
}
@keyframes noiseMove{
    0%,100%{transform:translate(0,0) scale(1.1)}
    25%{transform:translate(-1%,-1%) scale(1.05)}
    50%{transform:translate(0,0) scale(1.1)}
    75%{transform:translate(1%,1%) scale(1.05)}
}
#particlesCanvas{position:fixed;top:0;left:0;width:100%;height:100%;z-index:2;pointer-events:none}
.ppt-container{width:100vw;height:100vh;position:relative;z-index:10}
.slide{
    position:absolute;width:100%;height:100%;
    display:flex;flex-direction:column;justify-content:center;align-items:center;
    padding:40px 60px;
    opacity:0;visibility:hidden;
    transition:opacity .6s ease,visibility .6s ease;
}
.slide.active{opacity:1;visibility:visible}
.slide-content{max-width:1300px;width:100%}
/* 封面 */
.slide-cover{background:radial-gradient(ellipse at center,var(--cover-glow) 0%,transparent 70%)}
.cover-badge{
    display:inline-block;font-size:13px;font-weight:600;letter-spacing:2.5px;text-transform:uppercase;
    color:var(--accent);padding:8px 22px;border-radius:20px;
    background:var(--card-bg);border:1px solid var(--card-border);
    margin-bottom:28px;
}
.main-title{
    font-size:clamp(32px,5vw,64px);font-weight:900;text-align:center;margin-bottom:15px;
    text-shadow:0 0 30px var(--cover-glow);
    background:linear-gradient(90deg,var(--primary),var(--accent),var(--primary));
    background-size:200% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;
    background-clip:text;animation:shine 3s linear infinite;
}
@keyframes shine{to{background-position:200% center}}
.subtitle{font-size:clamp(20px,2.5vw,32px);color:var(--accent);font-weight:600;margin-bottom:10px}
.meta-line{font-size:16px;color:#808090;margin-top:8px}
.meta-line a{color:var(--cyan);text-decoration:none}
/* 章节标题 */
.section-title{
    font-size:clamp(28px,4vw,48px);font-weight:800;margin-bottom:30px;
    text-align:center;color:var(--primary);
    text-shadow:0 0 20px var(--cover-glow);
    display:flex;align-items:center;justify-content:center;gap:12px;
}
/* 卡片 */
.content-card{
    background:var(--card-bg);border-radius:16px;padding:30px 35px;
    border:2px solid var(--card-border);backdrop-filter:blur(10px);
    margin-bottom:20px;
}
.card-title{font-size:24px;font-weight:700;color:var(--accent);margin-bottom:12px}
.card-text{font-size:18px;line-height:1.9;color:#d0d0e0}
/* 要点列表 */
.insight-list{list-style:none;padding:0}
.insight-list li{
    font-size:18px;padding:14px 0 14px 35px;position:relative;
    border-bottom:1px solid rgba(255,255,255,.06);color:#d0d0e0;line-height:1.7;
}
.insight-list li::before{
    content:'\25B6';position:absolute;left:0;font-size:14px;color:var(--primary);
}
/* 金句卡片 */
.quote-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px}
.quote-card{
    background:linear-gradient(135deg,var(--card-bg),rgba(255,255,255,.02));
    border-left:4px solid var(--primary);border-radius:0 12px 12px 0;
    padding:20px 24px;font-size:17px;line-height:1.8;color:#e0e0e8;
    font-style:italic;
}
.quote-card::before{content:'\201C';font-size:40px;color:var(--primary);opacity:.5;display:block;margin-bottom:4px}
/* 数据卡片 */
.data-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:15px;margin-bottom:25px}
.data-item{
    background:var(--card-bg);border-radius:12px;padding:18px;text-align:center;
    border:1px solid var(--card-border);
}
.data-num{font-size:28px;font-weight:800;color:var(--accent)}
.data-label{font-size:13px;color:#808090;margin-top:4px}
/* 视频元信息 */
.video-link-btn{
    display:inline-flex;align-items:center;gap:8px;
    padding:12px 28px;border-radius:25px;
    background:linear-gradient(135deg,var(--primary),var(--purple));
    color:#fff;font-size:16px;font-weight:700;text-decoration:none;
    transition:transform .2s,box-shadow .2s;margin-top:15px;
}
.video-link-btn:hover{transform:translateY(-2px);box-shadow:0 6px 25px var(--cover-glow)}
/* 强调样式 — 统一使用主题强调色，禁止彩色文字 */
.em,.em-red,.em-yellow,.em-cyan,.em-purple{color:var(--primary);font-weight:800}
.highlight-box{
    background:rgba(255,255,255,.06);border-left:4px solid var(--primary);
    padding:15px 20px;border-radius:0 10px 10px 0;margin:15px 0;
    font-size:18px;line-height:1.8;color:#e0e0e8;
}
/* 导航 */
.nav-dots{
    position:fixed;bottom:30px;left:50%;transform:translateX(-50%);
    display:flex;gap:10px;z-index:100;
}
.nav-dot{
    width:12px;height:12px;border-radius:50%;
    background:rgba(255,255,255,.25);cursor:pointer;
    transition:all .3s ease;
}
.nav-dot.active{background:var(--primary);transform:scale(1.5);box-shadow:0 0 12px var(--cover-glow)}
.nav-arrows{
    position:fixed;bottom:28px;right:50px;display:flex;gap:12px;z-index:100;
}
.nav-arrow{
    width:45px;height:45px;border-radius:50%;
    background:rgba(255,255,255,.1);border:2px solid rgba(255,255,255,.2);
    color:#fff;display:flex;align-items:center;justify-content:center;
    cursor:pointer;font-size:20px;font-weight:bold;user-select:none;
    transition:all .2s;
}
.nav-arrow:hover{background:rgba(255,255,255,.2);transform:scale(1.1)}
.page-num{
    position:fixed;bottom:34px;left:50px;font-size:14px;color:#606070;z-index:100;
}
.page-num span{color:var(--primary);font-weight:700;font-size:18px}
/* 入场动画 */
.animate-item{
    opacity:0;transform:translateY(40px);
    transition:all .7s cubic-bezier(.34,1.56,.64,1);
}
.slide.active .animate-item{opacity:1;transform:translateY(0)}
.slide.active .animate-item:nth-child(1){transition-delay:.05s}
.slide.active .animate-item:nth-child(2){transition-delay:.15s}
.slide.active .animate-item:nth-child(3){transition-delay:.25s}
.slide.active .animate-item:nth-child(4){transition-delay:.35s}
.slide.active .animate-item:nth-child(5){transition-delay:.45s}
.slide.active .animate-item:nth-child(6){transition-delay:.55s}
.slide.active .animate-item:nth-child(7){transition-delay:.65s}
.slide.active .animate-item:nth-child(8){transition-delay:.75s}
.slide.active .animate-item:nth-child(9){transition-delay:.85s}
.slide.active .animate-item:nth-child(10){transition-delay:.95s}
/* 响应式 */
@media(max-width:768px){
    .slide{padding:25px 20px}
    .quote-grid{grid-template-columns:1fr}
    .data-grid{grid-template-columns:repeat(2,1fr)}
    .nav-arrows{right:15px;bottom:20px}
    .page-num{left:15px;bottom:24px}
}
@media print{
    .slide{position:relative;opacity:1;visibility:visible;page-break-after:always}
    .nav-dots,.nav-arrows,.page-num{display:none}
}
"""


# ── Claude 风格 CSS（浅色暖调 + Fraunces衬线标题 + Inter无衬线正文）──
#  参考: Anthropic Serif → Fraunces | Anthropic Sans → Inter | Anthropic Mono → JetBrains Mono
CLAUDE_CSS = r"""
*{margin:0;padding:0;box-sizing:border-box}
body{
    font-family:'Inter',-apple-system,'PingFang SC','Noto Sans SC','Microsoft YaHei',sans-serif;
    background:
        radial-gradient(ellipse at 20% 30%, rgba(199,125,255,0.10) 0%, transparent 50%),
        radial-gradient(ellipse at 80% 70%, rgba(255,153,102,0.08) 0%, transparent 50%),
        linear-gradient(165deg, #f5f0e8 0%, #ede7db 40%, #e8e0d4 100%);
    min-height:100vh;overflow:hidden;color:#2d2a26;position:relative;
    -webkit-font-smoothing:antialiased;font-feature-settings:"kern" 1,"liga" 1,"calt" 1;
}
body::before{
    content:"";position:fixed;top:0;left:0;width:100%;height:100%;
    background-image:radial-gradient(circle, rgba(180,170,155,0.08) 1px, transparent 1px);
    background-size:24px 24px;pointer-events:none;z-index:1;
}
.ppt-container{width:100vw;height:100vh;position:relative;z-index:10;overflow-y:auto}
.slide{
    position:absolute;width:100%;min-height:100%;
    display:flex;flex-direction:column;justify-content:center;align-items:center;
    padding:50px 70px;
    opacity:0;visibility:hidden;
    transition:opacity .55s ease, visibility .55s ease, transform .55s ease;
    transform:translateY(12px);
}
.slide.active{opacity:1;visibility:visible;transform:translateY(0)}
.slide-content{max-width:1100px;width:100%}
/* 封面 */
.slide-cover{text-align:center}
.cover-badge{
    display:inline-block;font-size:13px;font-weight:600;letter-spacing:2.5px;text-transform:uppercase;
    color:#9d8c6e;padding:8px 22px;border-radius:20px;
    background:rgba(200,190,175,0.25);border:1px solid rgba(180,165,140,0.3);
    margin-bottom:28px;
}
.main-title{
    font-family:'Fraunces','Georgia','Times New Roman',serif;
    font-size:clamp(36px,5vw,58px);font-weight:600;margin-bottom:18px;line-height:1.15;letter-spacing:0.01em;
    background:linear-gradient(115deg, #c77dff 0%, #e07090 35%, #f96 70%, #ffb347 100%);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.subtitle{
    font-family:'Inter',-apple-system,'PingFang SC',sans-serif;
    font-size:clamp(17px,2.2vw,25px);color:#8a7d65;font-weight:500;margin-bottom:10px;line-height:1.5;
}
.meta-line{font-size:14px;color:#b0a489;margin-top:6px}
.meta-line a{color:#c77dff;text-decoration:none;border-bottom:1px solid rgba(199,125,255,0.3)}
.video-link-btn{
    display:inline-flex;align-items:center;gap:8px;
    padding:13px 30px;border-radius:28px;margin-top:22px;
    background:linear-gradient(135deg,#c77dff, #da77f2);
    color:#fff;font-size:15.5px;font-weight:700;text-decoration:none;
    box-shadow:0 4px 20px rgba(199,125,255,0.35);
    transition:transform .22s ease,box-shadow .22s ease;
}
.video-link-btn:hover{transform:translateY(-2px);box-shadow:0 8px 28px rgba(199,125,255,0.45)}
/* 章节标题 */
.section-title{
    font-family:'Fraunces','Georgia','Times New Roman',serif;
    font-size:clamp(24px,3.5vw,42px);font-weight:600;margin-bottom:28px;letter-spacing:0.01em;
    text-align:center;color:#3d3830;display:flex;align-items:center;justify-content:center;gap:12px;
}
.section-title i{color:#c77dff;font-size:0.85em}
/* 卡片 */
.content-card{
    background:rgba(255,255,255,0.75);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
    border-radius:18px;padding:28px 34px;
    border:1.5px solid rgba(200,190,175,0.35);
    box-shadow:0 4px 24px rgba(120,105,80,0.06), 0 1px 3px rgba(120,105,80,0.04);
    margin-bottom:20px;
}
.card-title{font-family:'Fraunces','Georgia',serif;font-size:21px;font-weight:600;color:#c77dff;margin-bottom:12px}
.card-text{font-size:17px;line-height:1.75;color:#5a5349}
/* 列表 */
.insight-list{list-style:none;padding:0}
.insight-list li{
    font-size:17px;padding:13px 0 13px 32px;position:relative;
    border-bottom:1px solid rgba(180,170,155,0.15);color:#4a453d;line-height:1.8;
}
.insight-list li::before{
    content:'';position:absolute;left:0;top:20px;width:8px;height:8px;border-radius:50%;
    background:linear-gradient(135deg,#c77dff,#f96);
}
/* 金句 */
.quote-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:18px}
.quote-card{
    font-family:'Fraunces','Georgia',serif;
    background:linear-gradient(135deg,rgba(255,255,255,0.72),rgba(250,245,235,0.5));
    border-left:4px solid #c77dff;border-radius:0 14px 14px 0;
    padding:20px 24px;font-size:16.5px;line-height:1.85;color:#4a453d;font-style:italic;
    border:1.5px solid rgba(200,190,175,0.3);border-left:4px solid #c77dff;
    box-shadow:0 3px 16px rgba(120,105,80,0.05);
}
.quote-card::before{content:'\201C';font-size:38px;color:#c77dff;opacity:.45;display:block;margin-bottom:2px;line-height:1}
/* 数据卡片 */
.data-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:16px;margin-bottom:28px}
.data-item{
    background:rgba(255,255,255,0.75);backdrop-filter:blur(12px);
    border-radius:16px;padding:22px 14px;text-align:center;
    border:1.5px solid rgba(200,190,175,0.3);
    box-shadow:0 3px 14px rgba(120,105,80,0.05);
    transition:transform .2s ease,box-shadow .2s ease;
}
.data-item:hover{transform:translateY(-3px);box-shadow:0 8px 24px rgba(120,105,80,0.1)}
/* 数字滚动动画样式 */
.data-item[data-count]{opacity:0;transform:translateY(16px) scale(.96);transition:opacity .6s cubic-bezier(.16,1,.3,1),transform .6s cubic-bezier(.16,1,.3,1)}
.data-item[data-count].counted{opacity:1;transform:translateY(0) scale(1)}
.data-num{font-size:27px;font-weight:800;background:linear-gradient(135deg,#c77dff,#f96);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.data-label{font-size:12.5px;color:#b0a489;margin-top:5px;font-weight:500}
.data-icon{font-size:20px;color:#c77dff;margin-bottom:6px}
/* 强调 — 统一使用主题强调色 */
.em,.em-red,.em-yellow,.em-cyan,.em-purple{color:#c77dff;font-weight:700}
.highlight-box{
    background:linear-gradient(135deg,rgba(199,125,255,0.07),rgba(255,153,102,0.04));
    border-left:4px solid #c77dff;
    padding:16px 22px;border-radius:0 12px 12px 0;margin:16px 0;
    font-size:17.5px;line-height:1.8;color:#4a453d;
    border:1.5px solid rgba(199,125,255,0.18);border-left:4px solid #c77dff;
}
/* 导航 */
.nav-dots{position:fixed;bottom:32px;left:50%;transform:translateX(-50%);display:flex;gap:10px;z-index:100}
.nav-dot{width:11px;height:11px;border-radius:50%;background:rgba(160,150,135,0.35);cursor:pointer;transition:all .3s;border:1.5px solid transparent}
.nav-dot.active{background:linear-gradient(135deg,#c77dff,#f96);transform:scale(1.4);box-shadow:0 2px 10px rgba(199,125,255,0.35)}
.nav-arrows{position:fixed;bottom:30px;right:46px;display:flex;gap:10px;z-index:100}
.nav-arrow{
    width:44px;height:44px;border-radius:50%;background:rgba(255,255,255,0.6);backdrop-filter:blur(8px);
    border:1.5px solid rgba(200,190,175,0.4);color:#7a7060;
    display:flex;align-items:center;justify-content:center;cursor:pointer;
    font-size:18px;font-weight:bold;user-select:none;transition:all .2s;box-shadow:0 2px 10px rgba(120,105,80,0.06);
}
.nav-arrow:hover{background:rgba(255,255,255,0.88);transform:scale(1.08);box-shadow:0 4px 16px rgba(120,105,80,0.1)}
.page-num{position:fixed;bottom:36px;left:46px;font-size:13.5px;color:#b0a489;z-index:100;font-weight:500}
.page-num span{color:#c77dff;font-weight:700;font-size:17px}
/* 动画 */
.animate-item{opacity:0;transform:translateY(28px);transition:all .65s cubic-bezier(.22,1,.36,1)}
.slide.active .animate-item{opacity:1;transform:translateY(0)}
.slide.active .animate-item:nth-child(1){transition-delay:.06s}
.slide.active .animate-item:nth-child(2){transition-delay:.14s}
.slide.active .animate-item:nth-child(3){transition-delay:.22s}
.slide.active .animate-item:nth-child(4){transition-delay:.30s}
.slide.active .animate-item:nth-child(5){transition-delay:.38s}
.slide.active .animate-item:nth-child(6){transition-delay:.46s}
.slide.active .animate-item:nth-child(7){transition-delay:.54s}
.slide.active .animate-item:nth-child(8){transition-delay:.62s}
.slide.active .animate-item:nth-child(9){transition-delay:.70s}
.slide.active .animate-item:nth-child(10){transition-delay:.78s}
.theme-toggle{
    position:fixed;top:20px;right:24px;z-index:200;
    background:rgba(255,255,255,0.6);backdrop-filter:blur(8px);
    border:1.5px solid rgba(200,190,175,0.4);border-radius:20px;
    padding:7px 16px;font-size:13px;color:#8a7d65;cursor:pointer;
    font-family:inherit;font-weight:600;transition:all .2s;box-shadow:0 2px 10px rgba(120,105,80,0.06);
}
.theme-toggle:hover{background:rgba(255,255,255,0.9);color:#c77dff}
@media(max-width:768px){
    .slide{padding:30px 22px}.quote-grid{grid-template-columns:1fr}
    .data-grid{grid-template-columns:repeat(2,1fr)}.nav-arrows{right:14px;bottom:22px}
    .page-num{left:14px;bottom:26px}.theme-toggle{top:12px;right:14px}
}
@media print{
    .slide{position:relative;opacity:1;visibility:visible;page-break-after:always}
    .nav-dots,.nav-arrows,.page-num,.theme-toggle{display:none}
}
"""

CLAUDE_JS = r"""
let cur=0,total=0,locked=false;
function go(n){
    if(locked||n<0||n>=total||n===cur)return;
    locked=true;
    document.querySelectorAll('.slide').forEach(function(s,i){ s.classList.toggle('active',i===n); });
    document.querySelectorAll('.nav-dot').forEach(function(d,i){ d.classList.toggle('active',i===n); });
    document.querySelector('.page-num span').textContent=n+1;
    // 翻到新slide时触发该slide内的数字滚动
    setTimeout(function(){ countAnimateSlide(n); },50);
    cur=n;setTimeout(()=>{locked=false},600);
}
document.addEventListener('keydown',e=>{
    if(e.key==='ArrowRight'||e.key===' '){e.preventDefault();go(cur+1)}
    else if(e.key==='ArrowLeft'){e.preventDefault();go(cur-1)}
    else if(e.key==='Home'){e.preventDefault();go(0)}
    else if(e.key==='End'){e.preventDefault();go(total-1)}
});
document.querySelectorAll('.nav-dot').forEach(d=>{ d.addEventListener('click',()=>go(parseInt(d.dataset.index))); });
let tsX=0;
document.addEventListener('touchstart',e=>{tsX=e.changedTouches[0].screenX});
document.addEventListener('touchend',e=>{ let d=tsX-e.changedTouches[0].screenX;if(Math.abs(d)>50){if(d>0)go(cur+1);else go(cur-1)} });
total=document.querySelectorAll('.slide').length;
document.querySelector('.page-num span').textContent='1';

/* ---- 数字滚动动画（从0递增到目标值，easeOutExpo缓动） ---- */
var countedSlides={};
function countAnimateSlide(idx){
    if(countedSlides[idx])return;
    countedSlides[idx]=true;
    var slide=document.querySelector('.slide.active');
    if(!slide)slide=document.querySelectorAll('.slide')[idx];
    if(!slide)return;
    var nums=slide.querySelectorAll('.data-num[data-target]');
    nums.forEach(function(el){
        var target=parseFloat(el.dataset.target);
        var decimals=parseInt(el.dataset.decimals||'0',10);
        var duration=1500,start=performance.now();
        function tick(now){
            var progress=Math.min((now-start)/duration,1);
            var eased=progress===1?1:1-Math.pow(2,-10*progress);
            var current=(target*eased).toFixed(decimals);
            var span=el.querySelector('span');
            if(span){
                el.textContent=current;
                el.appendChild(span);
            }else{el.textContent=current;}
            if(progress<1)requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
    });
}
// 首屏slide0立即触发
setTimeout(function(){countAnimateSlide(0);},300);
"""

# ── Claude Slides 风格 CSS（纯白+暖橙点缀+亮暗切换，参考 claude-style-slides.html）──
CLAUDE_SLIDES_CSS = r"""
:root{
    --cs-bg-primary:#FFFFFF;--cs-bg-secondary:#F5F5F5;--cs-bg-card:#FAFAFA;
    --cs-text-primary:#0D0D0D;--cs-text-secondary:#666666;--cs-text-tertiary:#999999;
    --cs-accent:#D97757;--cs-accent-hover:#C56545;--cs-accent-bg:rgba(217,119,87,0.08);
    --cs-border:#E5E5E5;--cs-border-light:#F0F0F0;
    --cs-shadow:0 1px 3px rgba(0,0,0,0.06);--cs-shadow-lg:0 20px 60px rgba(0,0,0,0.1);
    --cs-nav-bg:rgba(13,13,13,0.92);--cs-nav-text:#FFFFFF;--cs-divider:#E5E5E5;
    --cs-bg-start:#FFFFFF;--cs-bg-end:#F5F5F5;
    --cs-primary:#D97757;--cs-accent2:#E8916A;
    --cs-cyan:#4dabf7;--cs-purple:#da77f2;
    --cs-card-bg:rgba(250,250,250,0.9);--cs-card-border:rgba(229,229,229,0.6);
}
[data-theme="dark"]{
    --cs-bg-primary:#0D0D0D;--cs-bg-secondary:#1A1A1A;--cs-bg-card:#141414;
    --cs-text-primary:#F5F5F5;--cs-text-secondary:#999999;--cs-text-tertiary:#666666;
    --cs-accent:#E8916A;--cs-accent-hover:#F0A585;--cs-accent-bg:rgba(232,145,106,0.1);
    --cs-border:#2A2A2A;--cs-border-light:#1F1F1F;
    --cs-shadow:0 1px 3px rgba(0,0,0,0.2);--cs-shadow-lg:0 20px 60px rgba(0,0,0,0.5);
    --cs-nav-bg:rgba(245,245,245,0.08);--cs-nav-text:#CCCCCC;--cs-divider:#2A2A2A;
    --cs-bg-start:#0D0D0D;--cs-bg-end:#1A1A1A;
    --cs-accent:#E8916A;--cs-accent2:#F0A585;
    --cs-card-bg:rgba(20,20,20,0.9);--cs-card-border:rgba(42,42,42,0.6);
}
*{margin:0;padding:0;box-sizing:border-box}
body{
    font-family:'Inter',-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
    font-weight:400;background:var(--cs-bg-primary);color:var(--cs-text-primary);
    overflow:hidden;height:100vh;
    transition:background 0.4s ease,color 0.4s ease;
}
.slide-container{
    width:100vw;height:100vh;display:flex;align-items:center;justify-content:center;position:relative;
}
.slide{
    width:88vw;max-width:1200px;height:88vh;max-height:780px;
    background:var(--cs-bg-primary);border-radius:20px;
    box-shadow:var(--cs-shadow-lg);padding:72px 88px;
    display:flex;flex-direction:column;position:absolute;
    top:0;left:0;right:0;bottom:0;margin:auto;
    opacity:0;transform:translateY(16px);pointer-events:none;
    transition:all 0.55s cubic-bezier(0.22,0.61,0.36,1);
    overflow:hidden;border:1px solid var(--cs-border);
}
.slide.active{opacity:1;transform:translateY(0);pointer-events:auto}
.progress-bar{
    position:fixed;top:0;left:0;height:2px;background:var(--cs-accent);z-index:1000;
    transition:width 0.55s cubic-bezier(0.22,0.61,0.36,1);
}
.theme-toggle{
    position:fixed;top:20px;right:24px;z-index:1001;
    width:40px;height:40px;border-radius:50%;border:1px solid var(--cs-border);
    background:var(--cs-bg-secondary);cursor:pointer;
    display:flex;align-items:center;justify-content:center;
    color:var(--cs-text-secondary);font-size:18px;transition:all 0.2s;
}
.theme-toggle:hover{background:var(--cs-accent-bg);color:var(--cs-accent)}
/* 封面 */
.slide-cover{text-align:center;justify-content:center}
.cover-badge{
    display:inline-block;font-size:13px;font-weight:600;letter-spacing:2.5px;text-transform:uppercase;
    color:var(--cs-accent);padding:8px 22px;border-radius:20px;
    background:var(--cs-accent-bg);border:1px solid var(--cs-border);
    margin-bottom:28px;
}
.main-title{
    font-size:clamp(32px,5vw,56px);font-weight:200;text-align:center;margin-bottom:16px;
    line-height:1.2;letter-spacing:-0.02em;
    background:linear-gradient(135deg,var(--cs-accent),var(--cs-accent2));
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.subtitle{
    font-size:clamp(16px,2vw,22px);color:var(--cs-text-secondary);font-weight:400;margin-bottom:8px;
}
.meta-line{font-size:14px;color:var(--cs-text-tertiary);margin-top:6px}
.meta-line a{color:var(--cs-accent);text-decoration:none}
.video-link-btn{
    display:inline-flex;align-items:center;gap:8px;
    padding:12px 28px;border-radius:28px;margin-top:18px;
    background:var(--cs-accent);color:#fff;font-size:15px;font-weight:600;
    text-decoration:none;transition:all 0.2s;
}
.video-link-btn:hover{background:var(--cs-accent-hover);transform:translateY(-1px)}
/* 章节标题 */
.section-title{
    font-size:clamp(22px,3vw,38px);font-weight:300;margin-bottom:24px;letter-spacing:-0.01em;
    text-align:center;color:var(--cs-text-primary);
    display:flex;align-items:center;justify-content:center;gap:10px;
}
.section-title i{color:var(--cs-accent);font-size:0.8em}
/* 卡片 */
.content-card{
    background:var(--cs-card-bg);border-radius:16px;padding:26px 32px;
    border:1px solid var(--cs-card-border);margin-bottom:18px;
    box-shadow:var(--cs-shadow);
}
.card-title{font-size:20px;font-weight:600;color:var(--cs-accent);margin-bottom:10px}
.card-text{font-size:16px;line-height:1.8;color:var(--cs-text-secondary)}
/* 列表 */
.insight-list{list-style:none;padding:0}
.insight-list li{
    font-size:16px;padding:12px 0 12px 30px;position:relative;
    border-bottom:1px solid var(--cs-border-light);color:var(--cs-text-secondary);line-height:1.8;
}
.insight-list li::before{
    content:'';position:absolute;left:0;top:18px;width:7px;height:7px;border-radius:50%;
    background:var(--cs-accent);
}
/* 金句 */
.quote-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.quote-card{
    background:var(--cs-card-bg);border-left:4px solid var(--cs-accent);
    border-radius:0 12px 12px 0;padding:18px 22px;font-size:16px;
    line-height:1.8;color:var(--cs-text-secondary);font-style:italic;
    border:1px solid var(--cs-card-border);border-left:4px solid var(--cs-accent);
    box-shadow:var(--cs-shadow);
}
.quote-card::before{content:'\201C';font-size:36px;color:var(--cs-accent);opacity:.4;display:block;margin-bottom:2px}
/* 数据 */
.data-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:14px;margin-bottom:24px}
.data-item{
    background:var(--cs-card-bg);border-radius:14px;padding:20px 14px;text-align:center;
    border:1px solid var(--cs-card-border);box-shadow:var(--cs-shadow);
    transition:transform 0.2s ease,box-shadow 0.2s ease;
}
.data-item:hover{transform:translateY(-2px);box-shadow:var(--cs-shadow-lg)}
.data-num{font-size:24px;font-weight:700;color:var(--cs-accent)}
.data-label{font-size:12px;color:var(--cs-text-tertiary);margin-top:4px;font-weight:500}
/* 强调 — 统一使用主题强调色 */
.em,.em-red,.em-yellow,.em-cyan,.em-purple{color:var(--cs-accent);font-weight:700}
.highlight-box{
    background:var(--cs-accent-bg);border-left:4px solid var(--cs-accent);
    padding:15px 20px;border-radius:0 10px 10px 0;margin:14px 0;
    font-size:16px;line-height:1.8;color:var(--cs-text-secondary);
}
/* AI content may contain a quote block with an inline light background. Keep
   semantic content readable after users switch the exported deck to dark. */
[data-theme="dark"] .slide blockquote,[data-theme="dark"] .slide .quote,[data-theme="dark"] .slide .quote-card{
    background:var(--cs-accent-bg)!important;color:var(--cs-text-primary)!important;
    border-color:var(--cs-border)!important;border-left:4px solid var(--cs-accent)!important;
}
[data-theme="dark"] .slide pre,[data-theme="dark"] .slide code{background:var(--cs-bg-secondary)!important;color:var(--cs-text-primary)!important;border-color:var(--cs-border)!important}
[data-theme="dark"] .slide [style*="background:#fff"],[data-theme="dark"] .slide [style*="background: #fff"],[data-theme="dark"] .slide [style*="background:white"],[data-theme="dark"] .slide [style*="background: white"]{background:var(--cs-bg-card)!important;color:var(--cs-text-primary)!important}
/* 导航 */
.nav-dots{position:fixed;bottom:32px;left:50%;transform:translateX(-50%);display:flex;gap:10px;z-index:100}
.nav-dot{
    width:10px;height:10px;border-radius:50%;
    background:var(--cs-text-tertiary);cursor:pointer;transition:all 0.3s;
}
.nav-dot.active{background:var(--cs-accent);transform:scale(1.5);box-shadow:0 2px 8px rgba(217,119,87,0.3)}
.nav-arrows{position:fixed;bottom:30px;right:46px;display:flex;gap:10px;z-index:100}
.nav-arrow{
    width:42px;height:42px;border-radius:50%;
    background:var(--cs-card-bg);border:1px solid var(--cs-border);
    color:var(--cs-text-secondary);display:flex;align-items:center;justify-content:center;
    cursor:pointer;font-size:16px;font-weight:bold;user-select:none;transition:all 0.2s;
    box-shadow:var(--cs-shadow);
}
.nav-arrow:hover{background:var(--cs-accent-bg);color:var(--cs-accent);transform:scale(1.06)}
.page-num{position:fixed;bottom:34px;left:46px;font-size:13px;color:var(--cs-text-tertiary);z-index:100;font-weight:500}
.page-num span{color:var(--cs-accent);font-weight:700;font-size:16px}
/* 入场动画 */
.animate-item{opacity:0;transform:translateY(24px);transition:all 0.6s cubic-bezier(0.22,1,0.36,1)}
.slide.active .animate-item{opacity:1;transform:translateY(0)}
.slide.active .animate-item:nth-child(1){transition-delay:.05s}
.slide.active .animate-item:nth-child(2){transition-delay:.13s}
.slide.active .animate-item:nth-child(3){transition-delay:.21s}
.slide.active .animate-item:nth-child(4){transition-delay:.29s}
.slide.active .animate-item:nth-child(5){transition-delay:.37s}
.slide.active .animate-item:nth-child(6){transition-delay:.45s}
.slide.active .animate-item:nth-child(7){transition-delay:.53s}
.slide.active .animate-item:nth-child(8){transition-delay:.61s}
.slide.active .animate-item:nth-child(9){transition-delay:.69s}
.slide.active .animate-item:nth-child(10){transition-delay:.77s}
@media(max-width:768px){
    .slide{padding:28px 20px}.quote-grid{grid-template-columns:1fr}
    .data-grid{grid-template-columns:repeat(2,1fr)}.nav-arrows{right:14px;bottom:22px}
    .page-num{left:14px;bottom:26px}.theme-toggle{top:12px;right:14px}
}
@media print{
    .slide{position:relative;opacity:1;visibility:visible;page-break-after:always}
    .nav-dots,.nav-arrows,.page-num,.theme-toggle{display:none}
}
"""

CLAUDE_SLIDES_JS = r"""
let cur=0,total=0,locked=false;
function updateProgress(){var p=document.querySelector('.progress-bar');if(p&&total>0)p.style.width=(((cur+1)/total)*100)+'%'}
function go(n,instant){
    if(n<0||n>=total||n===cur)return;
    if(!instant&&locked)return;
    if(!instant){locked=true;setTimeout(function(){locked=false},150)}
    document.querySelectorAll('.slide').forEach(function(s,i){s.classList.toggle('active',i===n)});
    document.querySelectorAll('.nav-dot').forEach(function(d,i){d.classList.toggle('active',i===n)});
    document.querySelector('.page-num span').textContent=n+1;
    updateProgress();cur=n;
}
document.addEventListener('keydown',function(e){
    if(e.key==='ArrowRight'||e.key===' '||e.key==='PageDown'){e.preventDefault();go(cur+1)}
    else if(e.key==='ArrowLeft'||e.key==='PageUp'){e.preventDefault();go(cur-1)}
    else if(e.key==='Home'){e.preventDefault();go(0)}
    else if(e.key==='End'){e.preventDefault();go(total-1)}
});
document.querySelectorAll('.nav-dot').forEach(function(d){
    d.addEventListener('click',function(){go(parseInt(this.dataset.index),true)});
});
var tsX=0;
document.addEventListener('touchstart',function(e){tsX=e.changedTouches[0].screenX});
document.addEventListener('touchend',function(e){
    var d=tsX-e.changedTouches[0].screenX;
    if(Math.abs(d)>50){if(d>0)go(cur+1);else go(cur-1)}
});
total=document.querySelectorAll('.slide').length;
document.querySelector('.page-num span').textContent='1';
updateProgress();
// 主题切换
var themeBtn=document.querySelector('.theme-toggle');
if(themeBtn){
    var themeIcon=document.getElementById('themeIcon');
    themeBtn.addEventListener('click',function(){
        var html=document.documentElement;
        var isDark=html.getAttribute('data-theme')==='dark';
        html.setAttribute('data-theme',isDark?'light':'dark');
        if(themeIcon)themeIcon.setAttribute('data-lucide',isDark?'sun':'moon');
        lucide.createIcons({attrs:{'stroke-width':1.5}});
        try{localStorage.setItem('claude-slides-theme',isDark?'light':'dark')}catch(e){}
    });
    try{
        var saved=localStorage.getItem('claude-slides-theme');
        if(saved==='dark'){document.documentElement.setAttribute('data-theme','dark');if(themeIcon)themeIcon.setAttribute('data-lucide','sun')}
    }catch(e){}
}
"""


PPT_JS = r"""
function go(n,instant){
    if(n<0||n>=total||n===cur)return;
    if(!instant&&locked)return;
    if(!instant){locked=true;setTimeout(function(){locked=false},150)}
    document.querySelectorAll('.slide').forEach(function(s,i){
        s.classList.toggle('active',i===n);
    });
    document.querySelectorAll('.nav-dot').forEach(function(d,i){
        d.classList.toggle('active',i===n);
    });
    document.querySelector('.page-num span').textContent=n+1;
    cur=n;
}
document.addEventListener('keydown',e=>{
    if(e.key==='ArrowRight'||e.key===' '||e.key==='PageDown'){e.preventDefault();go(cur+1)}
    else if(e.key==='ArrowLeft'||e.key==='PageUp'){e.preventDefault();go(cur-1)}
    else if(e.key==='Home'){e.preventDefault();go(0)}
    else if(e.key==='End'){e.preventDefault();go(total-1)}
});
document.querySelectorAll('.nav-dot').forEach(d=>{
    d.addEventListener('click',()=>go(parseInt(d.dataset.index),true));
});
let tsX=0;
document.addEventListener('touchstart',e=>{tsX=e.changedTouches[0].screenX});
document.addEventListener('touchend',e=>{
    let d=tsX-e.changedTouches[0].screenX;
    if(Math.abs(d)>50){if(d>0)go(cur+1);else go(cur-1)}
});
// Particles
const cv=document.getElementById('particlesCanvas'),cx=cv.getContext('2d');
function rs(){cv.width=window.innerWidth;cv.height=window.innerHeight}
rs();window.addEventListener('resize',rs);
const ps=[];
for(let i=0;i<80;i++)ps.push({x:Math.random()*2000,y:Math.random()*2000,r:Math.random()*2+.5,
    vx:(Math.random()-.5)*.4,vy:(Math.random()-.5)*.4,a:Math.random()*.4+.1});
function anim(){
    cx.clearRect(0,0,cv.width,cv.height);
    ps.forEach(p=>{
        p.x+=p.vx;p.y+=p.vy;
        if(p.x<0||p.x>cv.width||p.y<0||p.y>cv.height){p.x=Math.random()*cv.width;p.y=Math.random()*cv.height}
        cx.fillStyle='rgba(255,255,255,'+p.a+')';cx.beginPath();cx.arc(p.x,p.y,p.r,0,Math.PI*2);cx.fill()
    });
    requestAnimationFrame(anim)
}
anim();
// Init
total=document.querySelectorAll('.slide').length;
document.querySelector('.page-num span').textContent='1';
"""

# ══════════════════════════════════════════════════════════════
# Claude Slides V2 — 完整动画系统（基于 bilibili_learning_bot_slides.html 模板）
# 包含11种keyframe动画、级联入场、数字滚动、粒子特效、版本翻转
# ══════════════════════════════════════════════════════════════

CLAUDE_SLIDES_V2_CSS = r"""
:root {
  --bg-primary: #FFFFFF;
  --bg-secondary: #F5F5F5;
  --bg-card: #FAFAFA;
  --text-primary: #0D0D0D;
  --text-secondary: #666666;
  --text-tertiary: #999999;
  --accent: #D97757;
  --accent-hover: #C56545;
  --accent-bg: rgba(217,119,87,0.08);
  --border: #E5E5E5;
  --border-light: #F0F0F0;
  --shadow: 0 1px 3px rgba(0,0,0,0.06);
  --shadow-lg: 0 20px 60px rgba(0,0,0,0.08);
  --code-bg: #F5F5F5;
  --code-text: #0D0D0D;
  --code-border: #E5E5E5;
}
[data-theme="dark"] {
  --bg-primary: #0D0D0D;
  --bg-secondary: #1A1A1A;
  --bg-card: #141414;
  --text-primary: #F5F5F5;
  --text-secondary: #999999;
  --text-tertiary: #666666;
  --accent: #E8916A;
  --accent-hover: #F0A585;
  --accent-bg: rgba(232,145,106,0.1);
  --border: #2A2A2A;
  --border-light: #1F1F1F;
  --shadow: 0 1px 3px rgba(0,0,0,0.3);
  --shadow-lg: 0 20px 60px rgba(0,0,0,0.5);
  --code-bg: #1A1A1A;
  --code-text: #E5E5E5;
  --code-border: #2A2A2A;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  font-weight:400; background:var(--bg-primary); color:var(--text-primary);
  overflow:hidden; height:100vh; transition:background .35s,color .35s;
}
.slide-container { width:100vw; height:100vh; display:flex; align-items:center; justify-content:center; position:relative; }
.slide {
  width:80vw; max-width:960px; max-height:88vh; background:var(--bg-primary);
  border-radius:20px; box-shadow:var(--shadow-lg); padding:44px 60px;
  display:flex; flex-direction:column; position:absolute;
  opacity:0; transition:opacity .35s ease, transform .35s ease;
  overflow-y:auto; overflow-x:hidden; border:1px solid var(--border);
}
.slide.active { opacity:1; }
.slide::-webkit-scrollbar { width:4px; }
.slide::-webkit-scrollbar-track { background:transparent; }
.slide::-webkit-scrollbar-thumb { background:var(--border); border-radius:4px; }
.progress-bar {
  position:fixed; top:0; left:0; height:2px; background:var(--accent);
  z-index:1000; transition:width .35s ease;
}
.theme-toggle {
  position:fixed; top:20px; right:24px; z-index:1001;
  width:40px; height:40px; border-radius:50%;
  border:1px solid var(--border); background:var(--bg-secondary);
  cursor:pointer; display:flex; align-items:center; justify-content:center;
  transition:all .2s; color:var(--text-primary); padding:0;
}
.theme-toggle svg { width:18px; height:18px; }
.theme-toggle:hover { background:var(--border); }
/* Typography */
.slide-title { font-size:44px; font-weight:200; line-height:1.12; margin-bottom:16px; letter-spacing:-1.5px; color:var(--text-primary); }
.slide-title.sm { font-size:34px; }
.slide-subtitle { font-size:16px; font-weight:300; color:var(--text-secondary); margin-bottom:24px; line-height:1.55; max-width:80%; letter-spacing:-0.2px; }
.accent-text { color:var(--accent); }
.divider { width:40px; height:2px; background:var(--accent); margin:18px 0 24px; border-radius:1px; }
.divider.center { margin:24px auto 32px; }
.tag { display:inline-block; font-size:11px; font-weight:600; padding:5px 14px; border-radius:20px; background:var(--accent-bg); color:var(--accent); margin-bottom:16px; letter-spacing:1px; text-transform:uppercase; }
.logo-mark { font-size:12px; font-weight:400; color:var(--text-tertiary); margin-top:28px; letter-spacing:2px; text-transform:uppercase; }
/* Grid & Cards */
.content-grid { display:grid; grid-template-columns:1fr 1fr; gap:24px; flex:1; }
.content-grid.three { grid-template-columns:1fr 1fr 1fr; }
.content-grid.four { grid-template-columns:1fr 1fr 1fr 1fr; }
.card { background:var(--bg-card); border-radius:14px; padding:26px 26px 22px; border:1px solid var(--border); transition:border-color .2s, box-shadow .2s; display:flex; flex-direction:column; position:relative; overflow:hidden; }
.card::after { content:''; position:absolute; bottom:0; left:0; width:48px; height:2px; background:var(--accent); opacity:.12; }
.card:hover { border-color:var(--accent); box-shadow:var(--shadow); }
.card-icon { width:24px; height:24px; margin-bottom:14px; display:block; color:var(--accent); }
.card-icon svg { width:24px; height:24px; }
.card h3 { font-size:18px; font-weight:500; margin-bottom:8px; color:var(--text-primary); letter-spacing:-0.3px; }
.card p { font-size:13px; line-height:1.6; color:var(--text-secondary); font-weight:400; }
.card-tags { display:flex; flex-wrap:wrap; gap:6px; margin-top:auto; padding-top:14px; }
.card-tags span { font-size:10px; font-weight:500; color:var(--accent); background:var(--accent-bg); padding:3px 8px; border-radius:20px; letter-spacing:0.2px; }
.card-corner { position:absolute; bottom:-12px; right:-12px; color:var(--accent); opacity:.04; pointer-events:none; }
/* Lists */
.feature-list { list-style:none; flex:1; display:flex; flex-direction:column; gap:14px; margin-top:4px; }
.feature-list li { display:flex; align-items:flex-start; gap:16px; font-size:15px; line-height:1.55; color:var(--text-primary); font-weight:400; padding:14px 0; border-bottom:1px solid var(--border-light); }
.feature-list li:last-child { border-bottom:none; }
.feature-list .num { font-size:11px; font-weight:600; color:var(--accent); min-width:26px; height:26px; background:var(--accent-bg); border-radius:50%; display:flex; align-items:center; justify-content:center; flex-shrink:0; margin-top:1px; }
.feature-list li strong { font-weight:500; letter-spacing:-0.2px; }
/* Misc */
.code-block { background:var(--code-bg); color:var(--code-text); border:1px solid var(--code-border); border-radius:10px; padding:18px 24px; font-size:13px; font-family:'SF Mono','Cascadia Code','Fira Code','Consolas',monospace; line-height:1.7; overflow-x:auto; white-space:pre; margin-top:12px; }
.two-col { display:grid; grid-template-columns:1fr 1fr; gap:36px; flex:1; align-items:start; }
.arch-layer { border-left:3px solid var(--accent); padding:8px 16px; margin-bottom:10px; font-size:14px; line-height:1.5; }
.arch-layer strong { font-size:11px; font-weight:500; color:var(--accent); letter-spacing:1px; text-transform:uppercase; }
.arch-layer span { color:var(--text-secondary); font-size:12px; }
.table-wrap { width:100%; margin-top:8px; }
.table-wrap table { width:100%; border-collapse:separate; border-spacing:0; }
.table-wrap th { font-size:11px; font-weight:500; color:var(--text-tertiary); text-align:left; padding:10px 18px; text-transform:uppercase; letter-spacing:1px; border-bottom:1px solid var(--border); }
.table-wrap td { padding:9px 14px; font-size:14px; border-bottom:1px solid var(--border-light); line-height:1.5; color:var(--text-primary); }
.table-wrap td code { font-size:13px; background:var(--accent-bg); color:var(--accent); padding:2px 8px; border-radius:4px; font-weight:500; }
.table-wrap tr:last-child td { border-bottom:none; }
.end-card { display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; text-align:center; }
.end-card .slide-title { font-size:48px; font-weight:200; letter-spacing:-1.5px; }
.end-card p { font-size:16px; color:var(--text-secondary); font-weight:400; margin-top:14px; }
.big-num { font-size:64px; font-weight:200; color:var(--accent); line-height:1; letter-spacing:-2px; }
.num-label { font-size:14px; color:var(--text-secondary); margin-top:6px; font-weight:400; }
.flow-row { display:flex; align-items:center; gap:10px; margin-top:16px; flex-wrap:wrap; }
.flow-step { background:var(--bg-card); border:1px solid var(--border); border-radius:10px; padding:12px 18px; font-size:13px; font-weight:500; color:var(--text-primary); letter-spacing:-0.2px; }
.flow-arrow { color:var(--accent); font-size:18px; font-weight:200; }
.flow-step.accent { border-color:var(--accent); color:var(--accent); font-weight:600; }
.step-num { display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; border-radius:50%; background:var(--text-primary); color:var(--bg-primary); font-size:13px; font-weight:600; margin-right:10px; flex-shrink:0; }
.pipeline-list { list-style:none; display:flex; flex-direction:column; gap:12px; }
.pipeline-list li { display:flex; align-items:flex-start; gap:12px; font-size:13px; line-height:1.55; color:var(--text-primary); font-weight:400; padding:10px 14px; border-radius:8px; background:var(--bg-card); border:1px solid var(--border-light); }
/* Never let model-provided white quote/code blocks flash in dark mode. */
[data-theme="dark"] .slide blockquote,[data-theme="dark"] .slide .quote,[data-theme="dark"] .slide .quote-card{background:var(--accent-bg)!important;color:var(--text-primary)!important;border-color:var(--border)!important;border-left:4px solid var(--accent)!important}
[data-theme="dark"] .slide pre,[data-theme="dark"] .slide code{background:var(--code-bg)!important;color:var(--code-text)!important;border-color:var(--code-border)!important}
[data-theme="dark"] .slide [style*="background:#fff"],[data-theme="dark"] .slide [style*="background: #fff"],[data-theme="dark"] .slide [style*="background:white"],[data-theme="dark"] .slide [style*="background: white"]{background:var(--bg-card)!important;color:var(--text-primary)!important}
/* === LIGHT ANIMATION (3 keyframes, short stagger, no particles/counters) === */
@keyframes aFadeUp  { from{opacity:0;transform:translateY(16px)} to{opacity:1;transform:translateY(0)} }
@keyframes aFadeIn  { from{opacity:0} to{opacity:1} }
@keyframes aScaleIn { from{opacity:0;transform:scale(.94)} to{opacity:1;transform:scale(1)} }
.slide.animating > * { animation-fill-mode:both; animation-duration:.4s; animation-timing-function:ease-out; animation-name:aFadeUp; }
.slide.animating > *:nth-child(1) { animation-delay:.04s; }
.slide.animating > *:nth-child(2) { animation-delay:.10s; }
.slide.animating > *:nth-child(3) { animation-delay:.16s; }
.slide.animating > *:nth-child(4) { animation-delay:.22s; }
.slide.animating > *:nth-child(n+5) { animation-delay:.28s; }
.slide.animating .content-grid > * { animation-name:aScaleIn; }
.slide.animating .content-grid > *:nth-child(1) { animation-delay:.08s; }
.slide.animating .content-grid > *:nth-child(2) { animation-delay:.16s; }
.slide.animating .content-grid > *:nth-child(3) { animation-delay:.24s; }
.slide.animating .content-grid > *:nth-child(n+4) { animation-delay:.32s; }
.slide.animating .feature-list > li { animation-name:aFadeUp; }
.slide.animating .feature-list > li:nth-child(1) { animation-delay:.08s; }
.slide.animating .feature-list > li:nth-child(2) { animation-delay:.14s; }
.slide.animating .feature-list > li:nth-child(3) { animation-delay:.20s; }
.slide.animating .feature-list > li:nth-child(n+4) { animation-delay:.26s; }
@media (max-width:768px) {
  .slide { padding:36px 24px; border-radius:14px; width:96vw; }
  .slide-title { font-size:32px; letter-spacing:-1px; }
  .slide-title.sm { font-size:28px; }
  .slide-subtitle { font-size:15px; max-width:100%; }
  .content-grid,.content-grid.three,.content-grid.four { grid-template-columns:1fr; gap:14px; }
  .two-col { grid-template-columns:1fr; gap:20px; }
  .logo-mark { margin-top:20px; }
  .big-num { font-size:44px; }
  .flow-row { gap:6px; }
  .flow-step { padding:8px 12px; font-size:11px; }
}
"""
CLAUDE_SLIDES_V2_JS = r"""
var cur=0,total=0,isDark=false;
function updateProgress(){
    var p=document.querySelector('.progress-bar');
    if(p&&total>0)p.style.width=(((cur+1)/total)*100)+'%'
}
function go(n){
    if(n<0||n>=total||n===cur)return;
    // Hide old, show new
    document.querySelectorAll('.slide').forEach(function(s,i){
        s.classList.toggle('active',i===n);
        s.classList.remove('animating');
    });
    document.querySelectorAll('.nav-dot').forEach(function(d,i){
        d.classList.toggle('active',i===n);
    });
    var pn=document.querySelector('.page-num span');
    if(pn)pn.textContent=n+1;
    updateProgress();
    cur=n;
    // Trigger entrance animation on new active slide
    requestAnimationFrame(function(){
        var active=document.querySelector('.slide.active');
        if(active){active.classList.add('animating');}
    });
}
// Theme
function toggleTheme(){
    isDark=!isDark;
    document.documentElement.setAttribute('data-theme',isDark?'dark':'');
    var icon=document.querySelector('.theme-toggle i');
    if(icon){
        icon.setAttribute('data-lucide',isDark?'sun':'moon');
        lucide.createIcons({attrs:{'stroke-width':1.5}});
    }
    try{localStorage.setItem('claude-v2-theme',isDark?'dark':'light')}catch(e){}
}
// Init
window.addEventListener('DOMContentLoaded',function(){
    try{
        var saved=localStorage.getItem('claude-v2-theme');
        if(saved==='dark'){
            isDark=true;
            document.documentElement.setAttribute('data-theme','dark');
            var tIcon=document.querySelector('.theme-toggle i');
            if(tIcon)tIcon.setAttribute('data-lucide','sun');
        }
    }catch(e){}
    lucide.createIcons({attrs:{'stroke-width':1.5}});
    // Nav dots
    var slides=document.querySelectorAll('.slide');
    var dots=document.getElementById('navDots');
    if(dots&&slides.length){
        dots.innerHTML='';
        for(var i=0;i<slides.length;i++){
            var d=document.createElement('div');
            d.className='nav-dot'+(i===0?' active':'');
            d.setAttribute('data-index',i);
            d.addEventListener('click',function(){go(parseInt(this.dataset.index))});
            dots.appendChild(d);
        }
        var pn=document.querySelector('.page-num');
        if(pn)pn.innerHTML='<span>1</span> / '+slides.length;
    }
    total=slides.length;
    updateProgress();
    // Initial animation
    requestAnimationFrame(function(){
        var active=document.querySelector('.slide.active');
        if(active)active.classList.add('animating');
    });
});
// Keyboard
document.addEventListener('keydown',function(e){
    if(e.key==='ArrowRight'||e.key==='ArrowDown'||e.key===' '||e.key==='PageDown'){e.preventDefault();go(cur+1)}
    else if(e.key==='ArrowLeft'||e.key==='ArrowUp'||e.key==='PageUp'){e.preventDefault();go(cur-1)}
    else if(e.key==='Home'){e.preventDefault();go(0)}
    else if(e.key==='End'){e.preventDefault();go(total-1)}
    else if(e.key==='d'||e.key==='D'){toggleTheme()}
});
// Touch swipe
var tsX=0;
document.addEventListener('touchstart',function(e){tsX=e.changedTouches[0].screenX});
document.addEventListener('touchend',function(e){
    var d=tsX-e.changedTouches[0].screenX;
    if(Math.abs(d)>50){if(d>0)go(cur+1);else go(cur-1)}
});
// Bind theme toggle
document.addEventListener('DOMContentLoaded',function(){
    var tb=document.querySelector('.theme-toggle');
    if(tb)tb.addEventListener('click',toggleTheme);
});
"""


def _style_css_override(theme_name: str) -> str:
    """Small, deterministic layout accents for every non-Claude picker choice."""
    if theme_name in {"light", "soft_pop", "neumorphism", "neobrutal"}:
        base = r"""
body{background:linear-gradient(145deg,var(--bg-start),var(--bg-end));color:#172033}
body::before{opacity:.035;mix-blend-mode:multiply}.slide-content{color:#172033}.meta-line,.data-label{color:#5b6472}.card-text,.insight-list li,.highlight-box,.quote-card{color:#273244}.content-card,.data-item,.quote-card,.highlight-box{background:var(--card-bg);border-color:var(--card-border);box-shadow:0 12px 30px rgba(15,23,42,.08)}.nav-arrow{background:rgba(255,255,255,.78);border-color:var(--card-border);color:#172033}.nav-dot{background:rgba(15,23,42,.22)}
"""
        if theme_name == "neobrutal":
            base += r""".content-card,.data-item,.quote-card,.flow-step{border:3px solid #111827!important;border-radius:4px!important;box-shadow:5px 5px 0 #111827!important}.main-title{-webkit-text-fill-color:#111827;background:none}.slide{font-family:Inter,"Microsoft YaHei",sans-serif}.nav-arrow{border:2px solid #111827;border-radius:4px;box-shadow:3px 3px 0 #111827}.nav-dot{border-radius:1px}"""
        elif theme_name == "neumorphism":
            base += r""".content-card,.data-item,.quote-card,.flow-step{border:0!important;box-shadow:10px 10px 22px rgba(72,85,99,.18),-10px -10px 22px rgba(255,255,255,.74)!important}.main-title{-webkit-text-fill-color:#334155;background:none}"""
        elif theme_name == "soft_pop":
            base += r""".content-card,.data-item,.quote-card,.flow-step{border-radius:18px}.main-title{-webkit-text-fill-color:#db2777;background:none}"""
        return base
    if theme_name == "bento":
        return r""".content-grid{grid-template-columns:1.25fr .75fr}.content-grid>.card:first-child{grid-row:span 2}.data-grid{grid-template-columns:repeat(4,1fr)}.content-card,.data-item{border-radius:10px}@media(max-width:768px){.content-grid,.data-grid{grid-template-columns:1fr 1fr}.content-grid>.card:first-child{grid-row:auto}}"""
    if theme_name == "card":
        return r""".content-card,.data-item,.quote-card{transition:transform .22s ease,box-shadow .22s ease}.content-card:hover,.data-item:hover,.quote-card:hover{transform:translateY(-4px);box-shadow:0 18px 38px rgba(0,0,0,.28)}"""
    if theme_name in {"glass", "liquid_glass"}:
        return r""".content-card,.data-item,.quote-card,.flow-step{backdrop-filter:blur(18px) saturate(135%);box-shadow:0 16px 38px rgba(0,0,0,.22)}.slide-cover{background:radial-gradient(circle at 24% 18%,rgba(255,255,255,.16),transparent 42%)}"""
    if theme_name == "linear":
        return r""".content-card,.data-item,.quote-card,.flow-step{border-radius:8px;box-shadow:0 0 0 1px rgba(167,139,250,.10),0 18px 45px rgba(0,0,0,.24)}.card::after{width:100%;opacity:.18}"""
    if theme_name == "nostalgic":
        return r"""body,.slide{font-family:"Cascadia Mono","Consolas","Microsoft YaHei",monospace}.content-card,.data-item,.quote-card,.flow-step{border-radius:0;border:2px solid var(--accent);box-shadow:4px 4px 0 rgba(0,0,0,.35)}.tag{border-radius:0}"""
    if theme_name == "promptport":
        return r""".content-card,.data-item,.quote-card,.flow-step{border-radius:8px;box-shadow:0 0 26px rgba(0,229,168,.08)}.main-title{font-weight:700;letter-spacing:0}.tag{border:1px solid rgba(0,229,168,.35)}"""
    if theme_name == "cyberpunk":
        return r""".content-card,.data-item,.quote-card{box-shadow:0 0 22px rgba(34,211,238,.10),inset 0 0 20px rgba(244,114,182,.04)}.main-title{text-shadow:0 0 18px rgba(34,211,238,.24)}"""
    return ""

# ── AI Prompt 模板 ──
def _load_claude_design_system() -> str:
    """加载 Claude 设计系统提示词（用于注入AI prompt）"""
    import os as _os
    base_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    prompt_path = _os.path.join(base_dir, "templates", "claude", "prompts", "claude-style-prompt.md")

    prompt_text = ""
    try:
        if _os.path.exists(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_text = f.read()
    except Exception:
        pass

    if not prompt_text:
        from services.html_renderer import SLIDE_COMPONENT_CONTRACT
        prompt_text = SLIDE_COMPONENT_CONTRACT

    # 加载参考HTML示例的关键结构信息
    examples_info = _load_examples_info(base_dir)
    if examples_info:
        prompt_text += "\n\n【参考页面结构】\n" + examples_info

    return prompt_text


def _load_examples_info(base_dir: str) -> str:
    """Describe the one canonical reference without injecting an HTML file into the LLM."""
    reference = os.path.join(base_dir, "bilibili_learning_bot_slides.html")
    if not os.path.isfile(reference):
        return ""
    return (
        "唯一视觉参考：项目根目录 bilibili_learning_bot_slides.html。"
        "使用其已有的 slide、tag、slide-title、divider、content-grid、card、"
        "feature-list、two-col、table-wrap、end-card、logo-mark 组件；"
        "页面引擎已提供亮暗切换、进度条、键盘和触摸翻页、Lucide 与响应式布局。"
        "不要参考或混用 templates/claude/examples 中的其他页面。"
    )

def build_slide_prompt(
    video_info: dict,
    subtitle_text: str,
    theme_name: str = "dark",
    detail_level: str = "medium",
    custom_prompt: str = "",
    enhanced_animations: bool = False,
    slide_count: int | None = None,
) -> str:
    """构建AI生成PPT幻灯片内容的提示词。"""
    theme_name = normalize_theme_name(theme_name)
    title = video_info.get('title', '未知视频')
    up_name = video_info.get('author', '未知UP主')
    video_url = video_info.get('url', '')
    bvid = video_info.get('bvid', '')
    stats = video_info.get('stats', {})
    desc = video_info.get('desc', '')[:500]
    is_claude = False
    is_claude_slides = theme_name == "claude_slides"

    # ── 详情级别配置 ──
    _detail_cfg = {
        "simple":   {"label": "简单", "sub_limit": 8000,  "slide_factor": (700, 450), "depth_prompt": "提炼最核心的3-5个观点，每个观点用1-2句话概括即可，不需要长篇展开"},
        "medium":   {"label": "中长", "sub_limit": 15000, "slide_factor": (550, 350), "depth_prompt": "保持适中的内容密度，每个观点展开说明但不要太冗长，兼顾全面性和可读性"},
        "detailed": {"label": "详细", "sub_limit": 30000, "slide_factor": (350, 220), "depth_prompt": "深入详细地展开每个观点，包含具体的例子、论据和细节。充分利用字幕内容，尽可能完整地呈现视频中的所有知识点"},
    }
    _dc = _detail_cfg.get(detail_level, _detail_cfg["medium"])

    # Claude 幻灯片统一使用项目根目录的参考模板与同一份输出契约。
    if is_claude_slides:
        prompt = _build_slide_prompt_v2(
            video_info,
            subtitle_text,
            detail_level=detail_level,
            enhanced_animations=enhanced_animations,
            slide_count=slide_count,
        )
        if custom_prompt.strip():
            prompt += f"\n\n【用户自定义要求（优先遵守，不得破坏HTML结构）】\n{custom_prompt.strip()}"
        return prompt

    # 截取字幕（AI prompt用，根据详情级别保留不同长度的上下文）
    sub_for_ai = subtitle_text
    _sub_limit = _dc["sub_limit"]
    if len(sub_for_ai) > _sub_limit:
        head = _sub_limit // 3
        tail = _sub_limit // 3
        mid_start = max(head, len(sub_for_ai) // 2 - head // 2)
        mid = min(head, len(sub_for_ai) - mid_start)
        sub_for_ai = sub_for_ai[:head] + "\n...[中间部分省略]...\n" + sub_for_ai[mid_start:mid_start+mid] + "\n...[末尾部分]...\n" + sub_for_ai[-tail:]

    # 根据字幕长度 + 详情级别动态计算推荐页数
    _sub_len = len(subtitle_text)
    _sf = _dc["slide_factor"]
    _min_slides = {"simple": 4, "medium": 6, "detailed": 8}.get(detail_level, 6)
    _min_slides = max(_min_slides, _sub_len // _sf[0])
    _max_slides = max(_min_slides + 2, _sub_len // _sf[1])
    _slide_range = str(slide_count) if slide_count else f"{_min_slides}-{_max_slides}"

    # Claude 专属设计规范注入
    claude_guidelines = ""
    if is_claude:
        claude_guidelines = f"""
【🎨 Claude 设计系统 v1.0 — 严格遵从此规范】
{_load_claude_design_system()}

【Claude 主题特殊要求】
- 所有图标使用 Lucide Icons (<i data-lucide="xxx"></i>)，**禁止使用 Font Awesome** (fas fa-xxx)
- 页面加载后调用 lucide.createIcons({{attrs:{{'stroke-width':1.5}}}})
- 数据网格 (.data-grid) 中每个 .data-item 需添加 data-count 属性，配合数字滚动动画
- .data-num 需要添加 data-target="原始数字" data-decimals="小数位数" 属性
- 示例: <div class="data-num" data-target="10.5" data-decimals="1">0<span>万</span></div>
- 所有slide使用 .animate-item 级联入场动画，禁止使用 emoji
- 封面 badge 使用英文大写: DEEP DIVE / INTERVIEW / TUTORIAL / CASE STUDY
- 标题使用 font-weight:200 或 300，正文 400，禁止 600+
- 卡片 border-radius:14px, padding:36px, border:1px solid var(--border)
- 按钮: 黑底白字(亮色模式)，border-radius:8px, padding:12px 28px
- 暗色模式: 右上角40px圆形按钮，moon/sun 图标，localStorage持久化
- 禁止: 渐变背景、彩色阴影、彩色文字、弹跳/旋转/脉冲动画、emoji图标、Font Awesome图标
"""

    style_direction = STYLE_ART_DIRECTION.get(theme_name, STYLE_ART_DIRECTION["dark"])
    prompt = f"""你是顶级知识萃取师和前端设计师。根据以下B站视频信息，生成一个**多页PPT风格HTML页面**的内容。
{claude_guidelines}

【本次风格方向】
{style_direction}

【全风格质量契约】
- 只输出 `<div class="ppt-container">` 到对应闭合标签；禁止输出 Markdown、DOCTYPE、style、script 或解释文字。
- 只使用引擎已提供的 class、CSS 变量和 Lucide 图标。不要在内容元素写 `background:#fff`、`background:white`、固定黑白文字或整页 CSS。
- 每页只服务一个结论：标题、依据、必要的例子/数据和一句可带走的结论。禁止空洞营销文案、重复卡片和虚构事实。
- 深浅主题都必须可读：正文和卡片使用变量；暗色主题不得出现白底大块或低对比灰字。
- 把图片/截图作为证据时要保留来源时间点；没有可靠材料时写“资料不足”，不要编造。

【视频信息】
- 标题: {title}
- UP主: {up_name}
- BV号: {bvid}
- 链接: {video_url}
- 播放: {stats.get('view','?')} | 点赞: {stats.get('like','?')} | 硬币: {stats.get('coin','?')} | 收藏: {stats.get('favorite','?')} | 弹幕: {stats.get('danmaku','?')} | 评论: {stats.get('comment','?')} | 时长: {stats.get('duration','?')}
- ⚠️ 以上数据为B站API实时获取的真实统计数据。**在生成"视频数据概览"slide时，必须严格使用上述数字，绝对禁止编造或修改任何数值！**
- 简介: {desc}

【字幕/对白内容（用于提取干货）】
{sub_for_ai}

【HTML生成规范 — 严格遵守！】

使用以下精确的HTML结构。**你必须生成{_slide_range}个slide**，每个slide的内容用中文撰写，结构清晰：

```html
<!-- ===== 幻灯片容器 ===== -->
<div class="ppt-container">

    <!-- Slide 1: 封面页 — 视频信息展示（标题、UP主、B站链接按钮） -->
    <!-- ⚠️ 此页面必须展示真实视频元数据：标题、UP主、BV号、B站观看链接 -->
    <div class="slide slide-cover active" data-index="0">
        <div class="slide-content" style="text-align:center">
            <div class="animate-item cover-badge">DEEP DIVE</div>
            <h1 class="animate-item main-title">{title}</h1>
            <p class="animate-item subtitle">[一句话概括这个视频的核心价值/主题]</p>
            <p class="animate-item meta-line">UP主: {up_name} | BV: {bvid}</p>
            <div class="animate-item" style="margin-top:22px">
                <a href="{video_url}" target="_blank" class="video-link-btn"><i data-lucide="play-circle"></i> 在B站观看原视频</a>
            </div>
        </div>
    </div>

    <!-- Slide 2: 视频详情信息页 — 数据统计 + 简介 + 元信息 -->
    <!-- ⚠️ 必须使用下方真实统计数据填充，禁止编造或修改任何数值！ -->
    <div class="slide" data-index="1">
        <div class="slide-content">
            <h2 class="animate-item section-title"><i data-lucide="bar-chart-3"></i> 视频数据概览</h2>
            <div class="animate-item data-grid">
                <div class="data-item"><div class="data-icon"><i data-lucide="play"></i></div><div class="data-num">{stats.get('view','?')}</div><div class="data-label">播放量</div></div>
                <div class="data-item"><div class="data-icon"><i data-lucide="heart"></i></div><div class="data-num">{stats.get('like','?')}</div><div class="data-label">点赞数</div></div>
                <div class="data-item"><div class="data-icon"><i data-lucide="coins"></i></div><div class="data-num">{stats.get('coin','?')}</div><div class="data-label">投币数</div></div>
                <div class="data-item"><div class="data-icon"><i data-lucide="bookmark"></i></div><div class="data-num">{stats.get('favorite','?')}</div><div class="data-label">收藏数</div></div>
                <div class="data-item"><div class="data-icon"><i data-lucide="message-square"></i></div><div class="data-num">{stats.get('danmaku','?')}</div><div class="data-label">弹幕数</div></div>
                <div class="data-item"><div class="data-icon"><i data-lucide="messages-square"></i></div><div class="data-num">{stats.get('comment','?')}</div><div class="data-label">评论数</div></div>
                <div class="data-item"><div class="data-icon"><i data-lucide="share-2"></i></div><div class="data-num">{stats.get('share','?')}</div><div class="data-label">分享数</div></div>
                <div class="data-item"><div class="data-icon"><i data-lucide="clock"></i></div><div class="data-num">{stats.get('duration','?')}</div><div class="data-label">时长</div></div>
            </div>
            <div class="animate-item content-card">
                <div class="card-title"><i data-lucide="info"></i> 视频简介</div>
                <p class="card-text">[用2-3句话总结视频简介和定位，基于以下真实简介]
简介原文: {desc}</p>
            </div>
        </div>
    </div>

    <!-- Slide 3: 核心洞察/知识点 -->
    <div class="slide" data-index="2">
        <div class="slide-content">
            <h2 class="animate-item section-title"><i data-lucide="lightbulb"></i> 核心洞察</h2>
            <div class="animate-item content-card">
                <p class="card-text">[一句话总结本视频最核心的干货/观点，20字以内]</p>
            </div>
            <ul class="animate-item insight-list">
                <li><span class="em">[关键词1]</span>：[洞察/知识点1，30-50字]</li>
                <li><span class="em">[关键词2]</span>：[洞察/知识点2，30-50字]</li>
                <li>[洞察/知识点3，30-50字]</li>
                <li>[洞察/知识点4，30-50字]</li>
                <li>[洞察/知识点5，30-50字]</li>
            </ul>
        </div>
    </div>

    <!-- Slide 4-7: 分章节/分主题展开 (至少3-4个slide) -->
    <!-- 每个章节用以下结构 -->
    <div class="slide" data-index="3">
        <div class="slide-content">
            <h2 class="animate-item section-title">[图标] [章节标题1]</h2>
            <div class="animate-item highlight-box">
                [本章节核心观点，1-2句话]
            </div>
            <ul class="animate-item insight-list">
                <li>[详细论点1]</li>
                <li>[详细论点2]</li>
                <li><span class="em">[重点]</span>[详细论点3]</li>
            </ul>
        </div>
    </div>

    <!-- 最后一个Slide: 金句/总结 -->
    <div class="slide" data-index="N">
        <div class="slide-content">
            <h2 class="animate-item section-title">[图标] 金句摘录</h2>
            <div class="animate-item quote-grid">
                <div class="quote-card">[从视频中提取的金句1，原话]</div>
                <div class="quote-card">[金句2]</div>
                <div class="quote-card">[金句3]</div>
                <div class="quote-card">[金句4]</div>
            </div>
            <div class="animate-item content-card" style="text-align:center;margin-top:20px">
                <p class="card-text" style="font-size:22px;color:var(--accent)">
                    [总结性结尾：一句话概括这个视频的价值]
                </p>
            </div>
        </div>
    </div>

</div>

<!-- ===== 导航UI ===== -->
<div class="nav-dots" id="navDots">
    <!-- JS会自动填充 -->
</div>
<div class="page-num"><span>1</span> / [总页数]</div>
<div class="nav-arrows">
    <div class="nav-arrow" onclick="go(cur-1)">&#9664;</div>
    <div class="nav-arrow" onclick="go(cur+1)">&#9654;</div>
</div>
```

【严格要求】
1. **必须生成{_slide_range}个完整slide**，不要偷懒只生成3-4个
2. 内容必须基于字幕/对白实际内容提炼，不要编造
3. **内容深度要求：{_dc['depth_prompt']}**
4. 章节分主题展开，每个章节一个slide，有层次感
5. 图标使用 Lucide Icons: <i data-lucide="xxx"></i>，参考常用映射选择相关图标
6. 强调样式：<span class="em"> 包裹重点关键词，统一使用主题强调色（**禁止使用多种颜色**）
7. **只输出 <div class="ppt-container"> 到 </div> 结束的完整HTML代码块**，包括导航UI
8. 不要输出 markdown 代码块标记，不要输出解释文字
9. 直接从 <div class="ppt-container"> 开始，到最后一个 </div> 结束

现在开始生成："""
    return prompt


def _build_slide_prompt_v2(
    video_info: dict,
    subtitle_text: str,
    detail_level: str = "medium",
    enhanced_animations: bool = True,
    slide_count: int | None = None,
) -> str:
    """构建基于参考页面的 Claude 幻灯片提示词。"""
    title = video_info.get('title', '未知视频')
    up_name = video_info.get('author', '未知UP主')
    video_url = video_info.get('url', '')
    bvid = video_info.get('bvid', '')
    stats = video_info.get('stats', {})
    desc = video_info.get('desc', '')[:500]

    # ── 详情级别配置 ──
    _detail_cfg = {
        "simple":   {"label": "简单", "sub_limit": 8000,  "slide_factor": (700, 500), "depth_prompt": "提炼最核心的3-5个观点，每个观点简要概括，追求极简精炼"},
        "medium":   {"label": "中长", "sub_limit": 15000, "slide_factor": (600, 400), "depth_prompt": "保持适中的内容密度，每个观点展开说明但不要太冗长"},
        "detailed": {"label": "详细", "sub_limit": 30000, "slide_factor": (400, 250), "depth_prompt": "深入详细地展开每个观点，包含具体例子、论据和细节，尽可能完整呈现所有知识点"},
    }
    _dc = _detail_cfg.get(detail_level, _detail_cfg["medium"])

    # 截取字幕
    sub_for_ai = subtitle_text
    _sub_limit = _dc["sub_limit"]
    if len(sub_for_ai) > _sub_limit:
        head = _sub_limit // 3
        tail = _sub_limit // 3
        mid_start = max(head, len(sub_for_ai) // 2 - head // 2)
        mid = min(head, len(sub_for_ai) - mid_start)
        sub_for_ai = sub_for_ai[:head] + "\n...[省略]...\n" + sub_for_ai[mid_start:mid_start+mid] + "\n...[省略]...\n" + sub_for_ai[-tail:]

    # 页数计算
    _sub_len = len(subtitle_text)
    _sf = _dc["slide_factor"]
    _min_slides = {"simple": 4, "medium": 6, "detailed": 8}.get(detail_level, 6)
    _min_slides = max(_min_slides, _sub_len // _sf[0])
    _max_slides = max(_min_slides + 2, _sub_len // _sf[1])
    _slide_range = str(slide_count) if slide_count else f"{_min_slides}-{_max_slides}"

    animation_guidance = (
        "使用参考页面的分段入场节奏：标题/分割线先出现，卡片或列表依次入场；可使用数据卡片、流程步骤、表格行的短暂级联动画。"
        if enhanced_animations
        else "保持轻量入场动画：仅使用标题、正文和卡片的淡入上升，不添加粒子、数字滚动或复杂的逐项动画。"
    )
    prompt = f"""你是知识萃取师和前端设计师。根据B站视频信息，生成多页幻灯片HTML。

【引擎说明】
你生成的内容会被注入基于 `bilibili_learning_bot_slides.html` 的 Claude 幻灯片引擎。只输出幻灯片内容HTML（从<div class="ppt-container">开始），不要写CSS/JS。
引擎提供：亮暗主题切换、进度条、键盘/触摸翻页、Lucide 图标和响应式布局。
动画偏好：{animation_guidance}

【设计与质量要求】
1. 使用克制的白/黑/灰与暖橙强调色，Inter 字体体系；只使用 Lucide 图标，禁止 emoji 和 Font Awesome
2. 标题字重 200-300，正文 400，卡片标题 500；不要使用渐变背景、彩色阴影或夸张动效
3. 每页只讲一个主题，避免溢出、遮挡、超长段落与无意义的重复卡片
4. 内容必须基于字幕、简介和真实统计数据提炼；不可编造事实或修改数据
5. 输出的标签、标题、卡片、列表、表格和总结页必须使用下方列出的既有组件类名

【视频信息】
- 标题: {title}
- UP主: {up_name}
- 链接: {video_url}
- 真实数据: 播放={stats.get('view','?')} | 点赞={stats.get('like','?')} | 硬币={stats.get('coin','?')} | 收藏={stats.get('favorite','?')} | 弹幕={stats.get('danmaku','?')} | 评论={stats.get('comment','?')}
- ⚠️ 以上数据为B站API真实数据，必须严格使用，禁止编造！
- 简介: {desc}

【字幕/对白】
{sub_for_ai}

【可用组件】
## 幻灯片结构
```html
<div class="ppt-container">
  <div class="slide active" data-index="0">
    <!-- 内容 -->
    <div class="logo-mark">bilibili_learning_bot</div>
  </div>
  <div class="slide" data-index="1">...</div>
</div>
```

## 标签
```html
<span class="tag">DEEP DIVE</span>
```

## 标题
```html
<h1 class="slide-title sm">标题 <span class="accent-text">强调</span></h1>
```

## 分割线
```html
<div class="divider"></div>
```

## 卡片 + 网格
```html
<div class="content-grid three">
  <div class="card">
    <i data-lucide="zap" class="card-icon"></i>
    <h3>标题</h3>
    <p>描述...</p>
    <div class="card-tags"><span>标签</span></div>
  </div>
</div>
```
- .content-grid (2列), .content-grid.three, .content-grid.four
- card-icon的Lucide图标: zap/lightbulb/book-open/globe/cpu/eye/thumbs-up/coins/message-square/share-2/heart/brain/shield/code-2/settings/play/clock

## 要点列表
```html
<ul class="feature-list">
  <li><span class="num">01</span> <strong>标题</strong> — 描述</li>
</ul>
```

## 两栏布局
```html
<div class="two-col">
  <div>左</div>
  <div>右</div>
</div>
```

## 表格
```html
<div class="table-wrap"><table>
  <thead><tr><th>列1</th><th>列2</th></tr></thead>
  <tbody><tr><td>数据</td><td>说明</td></tr></tbody>
</table></div>
```

## 总结页
```html
<div class="end-card">
  <span class="tag">SUMMARY</span>
  <h1 class="slide-title">总结标题</h1>
  <p>总结描述</p>
  <div class="divider center"></div>
</div>
```

【页面结构】
Slide 1 (封面): tag + h1标题 + 可选元数据
Slide 2 (数据): 真实统计数据展示
Slide 3-N-1 (内容): 按主题分页，每页一个主题
最后Slide (总结): end-card结构

【严格要求】
1. 生成 {_slide_range} 个完整slide
2. 内容基于字幕提取，禁止编造
3. **内容深度要求：{_dc['depth_prompt']}**
4. 统计数据严格使用真实数值
5. 每页底部必须有 <div class="logo-mark">bilibili_learning_bot</div>
6. 图标仅用 Lucide Icons (<i data-lucide="xxx"></i>)，禁止emoji
7. 只输出 <div class="ppt-container">...最后</div> 的HTML
8. 不要输出markdown代码块标记或解释文字

现在开始："""
    return prompt

def build_full_html(
    slide_html: str,
    theme_name: str = "dark",
    enhanced_animations: bool = False,
) -> str:
    """将AI生成的 slide 内容包装成完整 HTML 页面。"""
    theme_name = normalize_theme_name(theme_name)
    theme = THEMES.get(theme_name, THEMES["dark"])
    is_claude = False
    is_claude_slides = theme_name == "claude_slides"
    is_claude_slides_v2 = is_claude_slides

    # 生成CSS变量
    css_vars = f""":root{{
        --bg-start:{theme['bg_start']};--bg-end:{theme['bg_end']};
        --primary:{theme['primary']};--accent:{theme['accent']};
        --cyan:{theme['cyan']};--purple:{theme['purple']};
        --card-bg:{theme['card_bg']};--card-border:{theme['card_border']};
        --cover-glow:rgba({_hex_to_rgb(theme['primary'])},0.6);
    }}"""

    # 根据主题选择CSS/JS + Google Fonts
    if is_claude_slides_v2:
        # V2: 完整动画系统 (Inter字体 + Lucide图标 + 11种动画 + 亮暗切换)
        use_css = CLAUDE_SLIDES_V2_CSS
        if enhanced_animations:
            use_css += r"""
@keyframes enhancedSlideLeft { from { opacity:0; transform:translateX(-24px); } to { opacity:1; transform:translateX(0); } }
@keyframes enhancedPopIn { 0% { opacity:0; transform:scale(.90); } 70% { opacity:1; transform:scale(1.02); } 100% { opacity:1; transform:scale(1); } }
.slide.animating .feature-list > li { animation:enhancedSlideLeft .45s cubic-bezier(.22,.61,.36,1) both; }
.slide.animating .feature-list > li:nth-child(1) { animation-delay:.10s; }
.slide.animating .feature-list > li:nth-child(2) { animation-delay:.18s; }
.slide.animating .feature-list > li:nth-child(3) { animation-delay:.26s; }
.slide.animating .feature-list > li:nth-child(n+4) { animation-delay:.34s; }
.slide.animating .content-grid > .card { animation:enhancedPopIn .48s cubic-bezier(.22,.61,.36,1) both; }
.slide.animating .content-grid > .card:nth-child(1) { animation-delay:.12s; }
.slide.animating .content-grid > .card:nth-child(2) { animation-delay:.20s; }
.slide.animating .content-grid > .card:nth-child(3) { animation-delay:.28s; }
.slide.animating .content-grid > .card:nth-child(n+4) { animation-delay:.36s; }
"""
        use_js = CLAUDE_SLIDES_V2_JS
        body_extra = '<button class="theme-toggle" aria-label="切换主题"><i data-lucide="moon"></i></button>'
        canvas_tag = '<div class="progress-bar"></div>'
        google_fonts = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@100;200;300;400;500;600;700;800&display=swap" rel="stylesheet">'
        # Strip outer ppt-container wrapper (AI prompt generates it) to avoid double-wrap with slide-container
        _s = _unwrap_ppt_container(slide_html)
        slide_html = f'<div class="slide-container">{_s}</div>'
    elif is_claude_slides:
        # Claude Slides: 纯白+暖橙+亮暗切换+进度条
        use_css = CLAUDE_SLIDES_CSS
        use_js = CLAUDE_SLIDES_JS
        body_extra = '<button class="theme-toggle" aria-label="切换主题"><i data-lucide="moon" id="themeIcon"></i></button>'
        canvas_tag = '<div class="progress-bar"></div>'
        google_fonts = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@100;200;300;400;500;600;700;800&display=swap" rel="stylesheet">'
        # slide container wrap for claude_slides
        slide_html = f'<div class="slide-container">{slide_html}</div>'
    elif is_claude:
        use_css = CLAUDE_CSS
        use_js = CLAUDE_JS
        body_extra = '<div class="theme-toggle" onclick="this.textContent=this.textContent.includes(\'Solarized\')?\'Light\':\'Solarized\'">Solarized</div>'
        canvas_tag = ""
        google_fonts = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@100;200;300;400;500;600;700;800&display=swap" rel="stylesheet">'
    else:
        use_css = PPT_CSS
        use_js = PPT_JS
        body_extra = ""
        canvas_tag = '<canvas id="particlesCanvas"></canvas>'
        google_fonts = ""
    style_override = "" if is_claude_slides_v2 or is_claude_slides else _style_css_override(theme_name)

    # 构建导航点JS
    nav_dots_js = """
// Auto-generate nav dots
(function(){
    var slides=document.querySelectorAll('.slide');
    var dots=document.getElementById('navDots');
    if(dots&&slides.length){
        dots.innerHTML='';
        for(var i=0;i<slides.length;i++){
            var d=document.createElement('div');
            d.className='nav-dot'+(i===0?' active':'');
            d.setAttribute('data-index',i);
            d.addEventListener('click',function(){go(parseInt(this.dataset.index))});
            dots.appendChild(d);
        }
        var pn=document.querySelector('.page-num');
        if(pn)pn.innerHTML='<span>1</span> / '+slides.length;
    }
})();
"""

    full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{theme['name']} Theme - B站视频知识卡片</title>
{google_fonts}
{"<script src=\"https://unpkg.com/lucide@latest/dist/umd/lucide.js\"></script>" if is_claude or is_claude_slides or is_claude_slides_v2 else "<link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css\">"}
<style>
{css_vars}
{use_css}
{style_override}
</style>
</head>
<body>
{canvas_tag}{body_extra}
{slide_html}
<script>
{use_js}
{nav_dots_js}
{"lucide.createIcons({attrs:{'stroke-width':1.5}});" if is_claude or is_claude_slides or is_claude_slides_v2 else ""}
</script>
</body>
</html>"""
    return full_html


def _hex_to_rgb(hex_color: str) -> str:
    """#e94560 -> 233,69,96"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return f"{r},{g},{b}"
    return "233,69,96"


# ── 便捷API ──
async def _heartbeat_dots(interval: float = 2.0):
    """心跳动画：每隔interval秒打印一个点，表示在等待AI响应"""
    try:
        while True:
            await asyncio.sleep(interval)
            print(".", end="", flush=True)
    except asyncio.CancelledError:
        pass
def _find_free_port(start=18800, end=18900) -> int:
    """查找可用端口"""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return port
    return start  # fallback


def start_preview_server(html_content: str, port: int = None) -> str:
    """启动Flask预览服务器，返回访问URL"""
    global _preview_server, _preview_html, _preview_port
    try:
        from flask import Flask, Response
    except ImportError:
        raise ImportError("需要安装 flask: pip install flask")

    # 如果已有服务器在运行，先停止
    stop_preview_server()

    _preview_html = html_content
    _preview_port = port or _find_free_port()

    app = Flask("bilibili_html_preview")

    @app.route('/')
    def preview_index():
        return Response(_preview_html, mimetype='text/html; charset=utf-8')

    @app.errorhandler(404)
    def _404(e):
        return Response(_preview_html, mimetype='text/html; charset=utf-8')

    def _run():
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)  # 静默Flask日志
        app.run(host='127.0.0.1', port=_preview_port, debug=False, use_reloader=False)

    _preview_server = threading.Thread(target=_run, daemon=True)
    _preview_server.start()

    url = f"http://127.0.0.1:{_preview_port}"
    return url


def stop_preview_server():
    """停止预览服务器"""
    global _preview_server, _preview_html, _preview_port
    if _preview_server and _preview_server.is_alive():
        # daemon线程会在主线程退出时自动清理
        _preview_server = None
    _preview_html = ""
    _preview_port = 0


def save_html_to_path(html_content: str, save_path: str = None) -> str:
    """保存HTML到指定路径（跨平台）

    Args:
        html_content: HTML内容
        save_path: 保存路径。支持:
            - 绝对路径: /home/user/page.html 或 C:\\Users\\page.html
            - 相对路径: ./output/page.html
            - 仅目录: ./output/ (自动生成文件名)
            - None: 使用默认路径

    Returns:
        实际保存的完整文件路径
    """
    if save_path is None:
        from core.user_data import HTML_EXPORTS_DIR
        default_dir = HTML_EXPORTS_DIR
        default_dir.mkdir(parents=True, exist_ok=True)
        save_path = str(default_dir)

    sp = Path(save_path)

    # 如果只给了目录路径，自动生成文件名
    if sp.suffix.lower() != '.html':
        sp.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        sp = sp / f"bilibili_video_{timestamp}.html"
    else:
        # 确保父目录存在
        sp.parent.mkdir(parents=True, exist_ok=True)

    # 如果文件已存在，追加时间戳
    if sp.exists():
        ts = int(time.time())
        sp = sp.with_name(f"{sp.stem}_{ts}{sp.suffix}")

    sp.write_text(html_content, encoding='utf-8')
    return str(sp.resolve())


async def generate_ppt_from_bvid(
    bvid: str,
    api_key: str,
    base_url: str,
    model: str,
    cookies_obj=None,
    theme: str = "dark",
    detail_level: str = "medium",
    custom_prompt: str = "",
    enhanced_animations: bool = False,
    slide_count: int = 10,
    output_dir: str = None,
    open_browser: bool = True,
    auto_save: bool = True,
) -> dict:
    """
    一站式: B站BV号 → PPT风格HTML页面

    返回: {
        "success": bool,
        "html_path": str,
        "html_content": str,    # 完整的HTML源码（auto_save=False时可用）
        "title": str,
        "subtitle_chars": int,
        "error": str or None
    }
    """
    from api.subtitles import fetch_bilibili_subtitles

    requested_theme = normalize_theme_name(theme)
    # "auto" must select a maintained high-quality engine, not fall through to
    # the first legacy theme in the mapping.
    theme = "claude_slides" if requested_theme in ("", "auto") else requested_theme
    slide_count = max(4, min(int(slide_count or 10), 20))
    result = {
        "success": False, "html_path": "", "title": "", "subtitle_chars": 0,
        "theme": theme, "slide_count": 0, "requested_slide_count": slide_count,
        "error": None,
    }

    # Step 1: 获取字幕+视频信息
    import httpx as _httpx

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': f'https://www.bilibili.com/video/{bvid}'
    }

    async with _httpx.AsyncClient(http2=True, headers=headers, cookies=cookies_obj, timeout=20.0) as client:
        # 获取视频信息
        import hashlib as _hl, time as _time

        # 获取WBI签名
        _wbi_keys = None
        try:
            nav = await client.get('https://api.bilibili.com/x/web-interface/nav')
            nd = nav.json()
            if nd.get('code') == 0:
                wi = nd['data'].get('wbi_img', {})
                im = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get('img_url', ''))
                sm = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get('sub_url', ''))
                if im and sm:
                    _wbi_keys = (im.group(1), sm.group(1))
        except Exception:
            pass

        def wbi_sign(params):
            if not _wbi_keys:
                return dict(params)
            mixin = _wbi_keys[0] + _wbi_keys[1]
            wts = int(_time.time())
            sp = dict(params)
            sp['wts'] = wts
            si = sorted(sp.items(), key=lambda x: x[0])
            qs = '&'.join(f'{k}={v}' for k, v in si)
            sp['w_rid'] = _hl.md5((qs + mixin).encode()).hexdigest()
            return sp

        v_res = await client.get('https://api.bilibili.com/x/web-interface/view', params=wbi_sign({'bvid': bvid}))
        v_data = v_res.json()
        if v_data.get('code') != 0:
            result["error"] = f"获取视频信息失败: {v_data.get('message','')}"
            return result

        v_info = v_data['data']
        title = v_info.get('title', '')
        result["title"] = title
        stat = v_info.get('stat', {})
        duration_min = v_info.get('duration', 0) // 60

        # 格式化统计数据
        def fmt_num(n):
            if n >= 10000:
                return f"{n/10000:.1f}万"
            elif n >= 1000:
                return f"{n/1000:.1f}千"
            return str(n)

        video_info = {
            'title': title,
            'author': v_info.get('owner', {}).get('name', ''),
            'bvid': bvid,
            'url': f'https://www.bilibili.com/video/{bvid}',
            'desc': v_info.get('desc', '') or '',
            'stats': {
                'view': fmt_num(stat.get('view', 0)),
                'like': fmt_num(stat.get('like', 0)),
                'coin': fmt_num(stat.get('coin', 0)),
                'favorite': fmt_num(stat.get('favorite', 0)),
                'danmaku': fmt_num(stat.get('danmaku', 0)),
                'comment': fmt_num(stat.get('reply', 0)),
                'share': fmt_num(stat.get('share', 0)),
                'duration': f'{duration_min}分钟' if duration_min > 0 else '未知',
            }
        }

        # Step 2: 获取字幕
        try:
            ok, subtitle_text, video_desc, _ = await fetch_bilibili_subtitles(
                bvid, cookies_obj=cookies_obj, title=title)
        except RecursionError:
            # Retry once with a clean cookie jar if a malformed third-party
            # cookie structure makes the HTTP client recurse while encoding it.
            ok, subtitle_text, video_desc, _ = await fetch_bilibili_subtitles(
                bvid, cookies_obj=None, title=title)
        if not ok or not subtitle_text:
            result["error"] = f"字幕获取失败: {subtitle_text}"
            return result

        result["subtitle_chars"] = len(subtitle_text)

    # Step 3: AI 生成PPT内容
    _dl_map = {"simple": "简单", "medium": "中长", "detailed": "详细"}
    prompt = build_slide_prompt(
        video_info,
        subtitle_text,
        theme,
        detail_level=detail_level,
        custom_prompt=custom_prompt,
        enhanced_animations=enhanced_animations,
        slide_count=slide_count,
    )
    _prompt_chars = len(prompt)
    _prompt_k = _prompt_chars / 1000
    print(f"\n[PPT] 正在调用AI生成幻灯片... (详情:{_dl_map.get(detail_level, detail_level)}, prompt {_prompt_k:.1f}K字符, 字幕{result['subtitle_chars']:,}字符, 最长等待5分钟)")
    _safe_flush(sys.stdout)

    messages = [{"role": "user", "content": prompt}]
    request_body, request_headers = _utf8_json_request({
        'model': model, 'messages': messages, 'temperature': 0.7, 'max_tokens': 16384,
    })
    html_content = ""
    _ai_start = time.time()
    _heartbeat = asyncio.ensure_future(_heartbeat_dots(2.0))
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(
                f"{base_url}/chat/completions",
                headers={'Authorization': f'Bearer {api_key}', **request_headers},
                content=request_body,
            )
            _elapsed = time.time() - _ai_start
            if r.status_code >= 400:
                result["error"] = f"API错误 {r.status_code}: {r.text[:300]}"
                return result
            d = r.json()
            choices = d.get('choices', [])
            for ch in choices:
                msg = ch.get('message', {})
                c = msg.get('content', '')
                if c:
                    html_content += c
            print(f"\n[PPT] AI生成完成 ({_elapsed:.1f}秒, {len(html_content):,}字符)")
    except httpx.RequestError as exc:
        result["error"] = f"AI接口连接失败: {exc}"
        return result
    except (ValueError, KeyError, TypeError) as exc:
        result["error"] = f"AI响应格式异常: {exc}"
        return result
    finally:
        _heartbeat.cancel()
        try:
            await _heartbeat
        except asyncio.CancelledError:
            pass

    if not html_content:
        result["error"] = "AI未返回内容"
        return result

    # 清理: 去掉markdown代码块标记和前言
    # 找到 <div class="ppt-container"> 作为起点
    start_idx = html_content.find('<div class="ppt-container"')
    if start_idx == -1:
        start_idx = html_content.find('<div class="ppt-container')
    if start_idx > 0:
        html_content = html_content[start_idx:]

    generated_slide_count = count_slide_elements(html_content)
    if generated_slide_count != slide_count:
        print(f"[PPT] 页数验收未通过：要求 {slide_count} 页，实际 {generated_slide_count} 页，正在请求修复...")
        repair_prompt = f"""你刚才生成的幻灯片页数不符合要求。
目标：严格输出 {slide_count} 个完整的 <div class=\"slide ...\"> 页面，不能少也不能多。
保留原有真实内容并补齐缺少的独立主题页；不要重复封面，不要写 CSS、JS、Markdown 或解释。
只返回完整 <div class=\"ppt-container\">...</div>。

原始任务：
{prompt}

待修复草稿：
{html_content}"""
        try:
            repair_body, repair_headers = _utf8_json_request({
                'model': model,
                'messages': [{'role': 'user', 'content': repair_prompt}],
                'temperature': 0.35,
                'max_tokens': 16384,
            })
            async with httpx.AsyncClient(timeout=300.0) as client:
                repair_response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={'Authorization': f'Bearer {api_key}', **repair_headers},
                    content=repair_body,
                )
            if repair_response.status_code >= 400:
                result["error"] = f"页数修复请求失败：API {repair_response.status_code}"
                return result
            repaired = "".join(
                (choice.get('message') or {}).get('content', '')
                for choice in (repair_response.json().get('choices') or [])
            ).strip()
        except (httpx.RequestError, ValueError, KeyError, TypeError) as exc:
            result["error"] = f"页数修复失败：{exc}"
            return result
        repaired_start = repaired.find('<div class="ppt-container"')
        if repaired_start == -1:
            repaired_start = repaired.find('<div class="ppt-container')
        if repaired_start >= 0:
            repaired = repaired[repaired_start:]
        repaired_count = count_slide_elements(repaired)
        if repaired_count != slide_count:
            result["error"] = (
                f"生成页数不符合要求：要求 {slide_count} 页，修复后仍为 {repaired_count} 页；"
                "未保存该不合格网页。"
            )
            return result
        html_content = repaired
        generated_slide_count = repaired_count
        print(f"[PPT] 页数修复通过：{generated_slide_count}/{slide_count} 页")

    result["slide_count"] = generated_slide_count

    # Step 4: 包装完整HTML
    print("[PPT] 正在组装HTML页面...")
    _safe_flush(sys.stdout)
    full_html = build_full_html(
        html_content,
        theme,
        enhanced_animations=enhanced_animations,
    )
    print(f"[PPT] HTML组装完成 ({len(full_html):,}字符)")

    # Step 5: 保存（可选）
    result["html_content"] = full_html

    if auto_save:
        if output_dir is None:
            from core.user_data import HTML_EXPORTS_DIR
            output_dir = str(HTML_EXPORTS_DIR)
        os.makedirs(output_dir, exist_ok=True)

        safe_title = re.sub(r'[\\/*?:"<>|]', '_', title)[:40]
        timestamp = int(time.time())
        html_path = os.path.join(output_dir, f"{safe_title}_{timestamp}.html")

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(full_html)

        result["html_path"] = html_path
        print(f"[PPT] 已保存: {html_path}")

    result["success"] = True

    if open_browser and result.get("html_path"):
        webbrowser.open(f"file:///{result['html_path'].replace(os.sep, '/')}")

    return result


# ── CLI 测试入口 ──
if __name__ == "__main__":
    import sys
    bvid = sys.argv[1] if len(sys.argv) > 1 else "BV1YR5E6EE9o"
    theme = sys.argv[2] if len(sys.argv) > 2 else "dark"

    # 从config读取API配置
    from core.config import CONFIG_FILE, COOKIE_FILE
    config_path = CONFIG_FILE
    api_key = ""
    base_url = ""
    model = "qwen/qwen3.5-122b-a10b"
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            api_cfg = cfg.get('api', {})
            api_key = api_cfg.get('unified_api_key', '')
            base_url = api_cfg.get('unified_base_url', '')
            model = api_cfg.get('model_name', model)

    if not api_key or not base_url:
        print(f"请在 {CONFIG_FILE} 中配置 unified_api_key 和 unified_base_url")
        sys.exit(1)

    # 加载cookies
    cookie_file = COOKIE_FILE
    cookies = None
    if os.path.exists(cookie_file):
        with open(cookie_file, 'r', encoding='utf-8') as f:
            cookies = json.load(f)

    async def run():
        result = await generate_ppt_from_bvid(bvid, api_key, base_url, model, cookies_obj=cookies, theme=theme)
        if result["success"]:
            print(f"\n[OK] HTML已生成: {result['html_path']}")
            print(f"     标题: {result['title']}")
            print(f"     字幕: {result['subtitle_chars']:,} 字符")
            print(f"     大小: {os.path.getsize(result['html_path']):,} 字节")
        else:
            print(f"\n[ERROR] {result['error']}")

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())
