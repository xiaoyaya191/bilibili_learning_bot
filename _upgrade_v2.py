#!/usr/bin/env python3
"""一键优化 V2 CSS/JS/Prompt：精简动画、修复翻页、简化提示词"""
import re

TARGET = r"G:\code\abiligent-code\bilibili_learning_bot-3.0.2\services\video_to_ppt.py"
with open(TARGET, "r", encoding="utf-8") as f:
    content = f.read()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 替换 CLAUDE_SLIDES_V2_CSS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEW_V2_CSS = r'''CLAUDE_SLIDES_V2_CSS = r"""
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
"""'''

# Find CLAUDE_SLIDES_V2_CSS start and end
css_start = content.find("CLAUDE_SLIDES_V2_CSS = r")
css_end_marker = content.find('\nCLAUDE_SLIDES_V2_JS = r"""', css_start)
if css_start == -1 or css_end_marker == -1:
    print("ERROR: Cannot find CLAUDE_SLIDES_V2_CSS boundaries")
    exit(1)

content = content[:css_start] + NEW_V2_CSS + content[css_end_marker:]
print("[1/3] CSS replaced (11 keyframes -> 3, no particles/counters)")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 替换 CLAUDE_SLIDES_V2_JS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEW_V2_JS = r'''CLAUDE_SLIDES_V2_JS = r"""
var cur=0,total=0,isDark=false;
function updateProgress(){
    var p=document.querySelector('.progress-bar');
    if(p&&total>0)p.style.width=(total===1?'100%':(cur/(total-1)*100+'%'))
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
"""'''

js_start = content.find("CLAUDE_SLIDES_V2_JS = r")
js_end_marker = content.find('\n\n# ── AI Prompt', js_start)
if js_start == -1 or js_end_marker == -1:
    print("ERROR: Cannot find CLAUDE_SLIDES_V2_JS boundaries")
    exit(1)

content = content[:js_start] + NEW_V2_JS + content[js_end_marker:]
print("[2/3] JS replaced (no lock, no particles, no counters, no version roll)")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 替换 _build_slide_prompt_v2
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEW_PROMPT = r'''def _build_slide_prompt_v2(video_info: dict, subtitle_text: str) -> str:
    """构建V2动画幻灯片prompt — 轻量动画 + 专注内容质量"""
    title = video_info.get('title', '未知视频')
    up_name = video_info.get('author', '未知UP主')
    video_url = video_info.get('url', '')
    bvid = video_info.get('bvid', '')
    stats = video_info.get('stats', {})
    desc = video_info.get('desc', '')[:500]

    # 截取字幕
    sub_for_ai = subtitle_text
    if len(sub_for_ai) > 15000:
        third = len(sub_for_ai) // 3
        sub_for_ai = sub_for_ai[:5000] + "\n...[省略]...\n" + sub_for_ai[third:third+5000] + "\n...[省略]...\n" + sub_for_ai[-5000:]

    # 页数计算
    _sub_len = len(subtitle_text)
    _min_slides = max(6, _sub_len // 600)
    _max_slides = max(10, _sub_len // 400)
    _slide_range = f"{_min_slides}-{_max_slides}"

    prompt = f"""你是知识萃取师和前端设计师。根据B站视频信息，生成多页幻灯片HTML。

【引擎说明】
你生成的内容会被注入到一套轻量CSS/JS引擎中。你只需输出幻灯片内容HTML（从<div class="ppt-container">开始），不需要写CSS/JS。
引擎自动提供：淡入上升动画、卡片缩放动画、进度条、亮暗主题切换、键盘翻页。

【⚠️ 重要约束】
1. 字号不超过当前大小，不要使用超大字体
2. 每页内容密度适中，不要把多个话题挤在一页
3. 内容基于字幕提炼，不要编造

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
3. 统计数据严格使用真实数值
4. 每页底部必须有 <div class="logo-mark">bilibili_learning_bot</div>
5. 图标仅用 Lucide Icons (<i data-lucide="xxx"></i>)，禁止emoji
6. 只输出 <div class="ppt-container">...最后</div> 的HTML
7. 不要输出markdown代码块标记或解释文字

现在开始："""
    return prompt'''

prompt_start = content.find("def _build_slide_prompt_v2(video_info:")
prompt_end = content.find("\n\ndef build_full_html(", prompt_start)
if prompt_start == -1 or prompt_end == -1:
    print("ERROR: Cannot find _build_slide_prompt_v2 boundaries")
    exit(1)

content = content[:prompt_start] + NEW_PROMPT + content[prompt_end:]
print("[3/3] Prompt replaced (simplified, focused on content quality)")

# Write back
with open(TARGET, "w", encoding="utf-8") as f:
    f.write(content)

print("\n[Done] CLAUDE_SLIDES_V2_CSS, JS, and _build_slide_prompt_v2 all upgraded.")
print("Changes: 11 keyframes -> 3, removed lock/particles/counters, simplified prompt")
