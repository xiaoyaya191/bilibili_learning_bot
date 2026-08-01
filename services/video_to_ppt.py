"""services/video_to_ppt.py — B站视频 → PPT风格HTML页面（借鉴AI_Animation模板）

特性：
- 多页幻灯片，←→键盘翻页 + 底部导航点 + 触摸滑动
- 粒子Canvas背景 + SVG噪点 + 渐变暗色主题
- animate-item 级联入场动画
- 支持4种配色主题: dark(默认), purple, cyan, claude
- Flask预览服务器：生成后本地预览，保存到指定路径（跨平台）
"""
import os, re, time, json, asyncio, webbrowser, socket, threading
import httpx
from pathlib import Path

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
    "claude": {
        "name": "Claude 暖橙",
        # 浅色暖灰背景 + 微妙径向渐变
        "bg_start": "#f5f0e8", "bg_end": "#ebe5d9",
        # 紫粉渐变主色（标题）
        "primary": "#c77dff", "accent": "#f96",
        # 功能色
        "cyan": "#4dabf7", "purple": "#da77f2",
        # 白色半透明卡片
        "card_bg": "rgba(255,255,255,0.72)",
        "card_border": "rgba(200,190,175,0.45)",
    },
    "claude_slides": {
        "name": "Claude 幻灯片",
        # 纯白背景 + 暖橙点缀 (参考 claude-style-slides.html)
        "bg_start": "#FFFFFF", "bg_end": "#F5F5F5",
        "primary": "#D97757", "accent": "#E8916A",
        "cyan": "#4dabf7", "purple": "#da77f2",
        "card_bg": "rgba(250,250,250,0.9)",
        "card_border": "rgba(229,229,229,0.6)",
    },
}

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
function updateProgress(){var p=document.querySelector('.progress-bar');if(p&&total>0)p.style.width=(total===1?'100%':(cur/(total-1)*100+'%'))}
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
        # fallback: 使用内置精简版
        prompt_text = """【Claude 设计风格核心规范 v1.0】
- 字体: Inter (100-800) 全字重; 标题200-300, 正文400; 禁止600+粗体标题
- 配色: 纯白/黑/灰 + 暖橙点缀 #D97757; 暗色模式精确反转
- 图标: Lucide Icons (stroke-width:1.5), 禁止emoji/Font Awesome/Material Icons
- 卡片: border-radius:14px, padding:36px, border:1px solid var(--border), hover变accent
- 按钮: 黑底白字(亮)/白底黑字(暗), border-radius:8px, padding:12px 28px
- 分割线: width:40px, height:2px, background:var(--accent)
- 标签: font-size:11px, border-radius:20px, background:accent-bg
- 暗色模式: [data-theme="dark"] CSS变量 + localStorage持久化 + 40px圆形切换按钮
- 禁止: 渐变、粗阴影(blur>60px)、彩色阴影、彩色文字、弹跳/旋转/脉冲动画、emoji图标"""

    # 加载参考HTML示例的关键结构信息
    examples_info = _load_examples_info(base_dir)
    if examples_info:
        prompt_text += "\n\n【参考页面结构】\n" + examples_info

    return prompt_text


def _load_examples_info(base_dir: str) -> str:
    """加载参考HTML示例的关键结构摘要（用于AI prompt）"""
    examples_dir = os.path.join(base_dir, "templates", "claude", "examples")
    if not os.path.isdir(examples_dir):
        # 尝试 claude-design-system 目录
        alt_dir = os.path.join(os.path.dirname(base_dir), "claude-design-system", "examples")
        if os.path.isdir(alt_dir):
            examples_dir = alt_dir
        else:
            return ""

    info_parts = []
    example_files = sorted([f for f in os.listdir(examples_dir) if f.endswith('.html')])
    for ef in example_files[:7]:  # 最多取7个
        fpath = os.path.join(examples_dir, ef)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
            # 提取关键结构信息
            has_hero = '<div class="hero' in content or 'class="hero-section"' in content
            has_cards = '<div class="card"' in content or 'class="content-card"' in content
            has_table = '<table' in content
            has_sidebar = 'sidebar' in content.lower()
            has_faq = 'faq' in content.lower() or 'accordion' in content.lower()
            has_form = '<form' in content or '<input' in content
            has_theme = 'data-theme' in content
            has_lucide = 'data-lucide' in content
            has_counter = 'data-target' in content or 'counter' in content

            features = []
            if has_hero: features.append("Hero区")
            if has_cards: features.append("卡片网格")
            if has_table: features.append("数据表格")
            if has_sidebar: features.append("侧边栏布局")
            if has_faq: features.append("折叠面板")
            if has_form: features.append("表单")
            if has_theme: features.append("亮暗切换")
            if has_lucide: features.append("Lucide图标")
            if has_counter: features.append("数字滚动动画")

            name = ef.replace('.html', '').replace('-', ' ').title()
            info_parts.append(f"  {name}: {', '.join(features)}")
        except Exception:
            pass

    if info_parts:
        return "以下为Claude Design System参考页面的组件覆盖：\n" + "\n".join(info_parts)
    return ""

def build_slide_prompt(video_info: dict, subtitle_text: str, theme_name: str = "dark") -> str:
    """构建AI生成PPT幻灯片内容的提示词"""
    title = video_info.get('title', '未知视频')
    up_name = video_info.get('author', '未知UP主')
    video_url = video_info.get('url', '')
    bvid = video_info.get('bvid', '')
    stats = video_info.get('stats', {})
    desc = video_info.get('desc', '')[:500]
    is_claude = (theme_name == "claude")

    # 截取字幕（AI prompt用，保留足够上下文）
    sub_for_ai = subtitle_text
    if len(sub_for_ai) > 15000:
        # 保留前5000 + 中间5000 + 末尾5000
        third = len(sub_for_ai) // 3
        sub_for_ai = sub_for_ai[:5000] + "\n...[中间部分省略]...\n" + sub_for_ai[third:third+5000] + "\n...[末尾部分]...\n" + sub_for_ai[-5000:]

    # 根据字幕长度动态计算推荐页数（约350~500字/slide）
    _sub_len = len(subtitle_text)
    _min_slides = max(6, _sub_len // 550)
    _max_slides = max(10, _sub_len // 350)
    _slide_range = f"{_min_slides}-{_max_slides}"

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

    prompt = f"""你是顶级知识萃取师和前端设计师。根据以下B站视频信息，生成一个**多页PPT风格HTML页面**的内容。
{claude_guidelines}

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
1. **必须生成6-8个完整slide**，不要偷懒只生成3-4个
2. 内容必须基于字幕/对白实际内容提炼，不要编造
3. 章节分主题展开，每个章节一个slide，有层次感
4. 图标使用 Lucide Icons: <i data-lucide="xxx"></i>，参考常用映射选择相关图标
5. 强调样式：<span class="em"> 包裹重点关键词，统一使用主题强调色（**禁止使用多种颜色**）
6. **只输出 <div class="ppt-container"> 到 </div> 结束的完整HTML代码块**，包括导航UI
7. 不要输出 markdown 代码块标记，不要输出解释文字
8. 直接从 <div class="ppt-container"> 开始，到最后一个 </div> 结束

现在开始生成："""
    return prompt


def build_full_html(slide_html: str, theme_name: str = "dark") -> str:
    """将AI生成的slide内容包装成完整HTML页面"""
    theme = THEMES.get(theme_name, THEMES["dark"])
    is_claude = (theme_name == "claude")
    is_claude_slides = (theme_name == "claude_slides")

    # 生成CSS变量
    css_vars = f""":root{{
        --bg-start:{theme['bg_start']};--bg-end:{theme['bg_end']};
        --primary:{theme['primary']};--accent:{theme['accent']};
        --cyan:{theme['cyan']};--purple:{theme['purple']};
        --card-bg:{theme['card_bg']};--card-border:{theme['card_border']};
        --cover-glow:rgba({_hex_to_rgb(theme['primary'])},0.6);
    }}"""

    # 根据主题选择CSS/JS + Google Fonts
    if is_claude_slides:
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
{"<script src=\"https://unpkg.com/lucide@latest/dist/umd/lucide.js\"></script>" if is_claude or is_claude_slides else "<link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css\">"}
<style>
{css_vars}
{use_css}
</style>
</head>
<body>
{canvas_tag}{body_extra}
{slide_html}
<script>
{use_js}
{nav_dots_js}
{"lucide.createIcons({attrs:{'stroke-width':1.5}});" if is_claude or is_claude_slides else ""}
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
        # 默认路径（跨平台）
        if os.name == 'nt':  # Windows
            default_dir = Path(os.environ.get('USERPROFILE', os.path.expanduser('~'))) / 'Documents' / 'bilibili_html_exports'
        elif os.uname().sysname == 'Darwin':  # macOS
            default_dir = Path.home() / 'Documents' / 'bilibili_html_exports'
        else:  # Linux
            default_dir = Path.home() / 'bilibili_html_exports'
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

    result = {"success": False, "html_path": "", "title": "", "subtitle_chars": 0, "error": None}

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
        ok, subtitle_text, video_desc, _ = await fetch_bilibili_subtitles(bvid, cookies_obj=cookies_obj, title=title)
        if not ok or not subtitle_text:
            result["error"] = f"字幕获取失败: {subtitle_text}"
            return result

        result["subtitle_chars"] = len(subtitle_text)

    # Step 3: AI 生成PPT内容
    prompt = build_slide_prompt(video_info, subtitle_text, theme)
    messages = [{"role": "user", "content": prompt}]

    html_content = ""
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(
            f"{base_url}/chat/completions",
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': model, 'messages': messages, 'temperature': 0.7, 'max_tokens': 16384}
        )
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

    # Step 4: 包装完整HTML
    full_html = build_full_html(html_content, theme)

    # Step 5: 保存（可选）
    result["html_content"] = full_html

    if auto_save:
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "html_exports")
        os.makedirs(output_dir, exist_ok=True)

        safe_title = re.sub(r'[\\/*?:"<>|]', '_', title)[:40]
        timestamp = int(time.time())
        html_path = os.path.join(output_dir, f"{safe_title}_{timestamp}.html")

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(full_html)

        result["html_path"] = html_path

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
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data", "config.json")
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
        print("请在 Data/config.json 中配置 unified_api_key 和 unified_base_url")
        sys.exit(1)

    # 加载cookies
    cookie_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data", "bilibili_cookies.json")
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
