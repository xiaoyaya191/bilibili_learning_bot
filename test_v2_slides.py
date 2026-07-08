#!/usr/bin/env python3
"""
test_v2_slides.py — 测试优化后的 claude_slides_v2 引擎
1. 获取B站视频 → 2. 构建slide HTML → 3. build_full_html 包装 → 4. 保存
"""
import asyncio, httpx, re, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from services.video_to_ppt import build_full_html

BV = "BV1HXTs6bEzH"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

def _fmt(n):
    if not n or n <= 0: return '0'
    if n >= 1e8: return f"{n/1e8:.1f}亿"
    if n >= 1e4: return f"{n/1e4:.1f}万"
    return str(n)

def _dur(s):
    if not s: return "??"
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"

async def fetch_video_info():
    async with httpx.AsyncClient(http2=True, timeout=15.0) as c:
        r = await c.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": BV},
            headers={"User-Agent": UA, "Referer": f"https://www.bilibili.com/video/{BV}"}
        )
        data = r.json()
        if data.get("code") != 0:
            print(f"API error: {data}")
            return None
        v = data["data"]
        stat = v.get("stat", {})
        owner = v.get("owner", {})
        return {
            "title": v.get("title", ""),
            "up_name": owner.get("name", "未知"),
            "desc": (v.get("desc", "") or "")[:800],
            "duration": _dur(v.get("duration", 0)),
            "stats": {
                "view": _fmt(stat.get("view", 0)),
                "like": _fmt(stat.get("like", 0)),
                "coin": _fmt(stat.get("coin", 0)),
                "favorite": _fmt(stat.get("favorite", 0)),
                "danmaku": _fmt(stat.get("danmaku", 0)),
                "comment": _fmt(stat.get("reply", 0)),
                "share": _fmt(stat.get("share", 0)),
            },
            "bvid": BV,
            "url": f"https://www.bilibili.com/video/{BV}",
        }

def build_slides(video: dict) -> str:
    """手写多页幻灯片（模拟AI生成的内容）"""
    t = video["title"]
    up = video["up_name"]
    s = video["stats"]
    d = video["desc"]
    du = video["duration"]
    url = video["url"]
    parts = t.split("｜")
    main = parts[0].strip() if parts else t
    sub = parts[1].strip() if len(parts) > 1 else ""

    return f"""<div class="ppt-container">

<div class="slide active" data-index="0">
  <span class="tag">PODCAST</span>
  <h1 class="slide-title sm">{main}</h1>
  <div class="slide-subtitle">{sub}<br><span style="color:var(--text-tertiary);font-size:13px;display:block;margin-top:8px;">UP: @{up} | 时长: {du}</span></div>
  <div class="divider"></div>
  <div class="content-grid" style="margin-top:4px;">
    <div class="card"><i data-lucide="eye" class="card-icon"></i><h3>播放</h3><p style="font-size:24px;font-weight:200;color:var(--accent);">{s['view']}</p></div>
    <div class="card"><i data-lucide="thumbs-up" class="card-icon"></i><h3>点赞</h3><p style="font-size:24px;font-weight:200;color:var(--accent);">{s['like']}</p></div>
  </div>
  <div class="logo-mark">bilibili_learning_bot</div>
</div>

<div class="slide" data-index="1">
  <span class="tag">STATS</span>
  <h1 class="slide-title sm">数据概览</h1>
  <div class="slide-subtitle">B站API实时统计</div>
  <div class="divider"></div>
  <div class="content-grid three" style="margin-top:4px;">
    <div class="card"><i data-lucide="eye" class="card-icon"></i><h3>播放</h3><p style="font-size:20px;color:var(--accent);">{s['view']}</p></div>
    <div class="card"><i data-lucide="thumbs-up" class="card-icon"></i><h3>点赞</h3><p style="font-size:20px;color:var(--accent);">{s['like']}</p></div>
    <div class="card"><i data-lucide="coins" class="card-icon"></i><h3>硬币</h3><p style="font-size:20px;color:var(--accent);">{s['coin']}</p></div>
    <div class="card"><i data-lucide="bookmark" class="card-icon"></i><h3>收藏</h3><p style="font-size:20px;">{s['favorite']}</p></div>
    <div class="card"><i data-lucide="message-square" class="card-icon"></i><h3>弹幕+评论</h3><p style="font-size:20px;">{s['danmaku']}/{s['comment']}</p></div>
    <div class="card"><i data-lucide="share-2" class="card-icon"></i><h3>分享</h3><p style="font-size:20px;">{s['share']}</p></div>
  </div>
  <div class="logo-mark">bilibili_learning_bot</div>
</div>

<div class="slide" data-index="2">
  <span class="tag">ABOUT</span>
  <h1 class="slide-title sm">视频简介</h1>
  <div class="slide-subtitle">UP主 @{up} 的原始简介</div>
  <div class="divider"></div>
  <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:20px 24px;font-size:14px;line-height:1.8;color:var(--text-secondary);">{d if d else '(暂无简介)'}</div>
  <div class="logo-mark">bilibili_learning_bot</div>
</div>

<div class="slide" data-index="3">
  <span class="tag">KEY POINTS</span>
  <h1 class="slide-title sm">Nathan Lambert <span class="accent-text">谈中国 AI</span></h1>
  <div class="slide-subtitle">美国AI研究员的观察与思考</div>
  <div class="divider"></div>
  <div class="content-grid" style="margin-top:4px;">
    <div class="card"><i data-lucide="users" class="card-icon"></i><h3>年轻人</h3><p>中国AI从业者年轻化趋势明显，大量高校人才涌入赛道。</p><div class="card-tags"><span>人才</span></div></div>
    <div class="card"><i data-lucide="zap" class="card-icon"></i><h3>追赶者</h3><p>DeepSeek/Qwen表现亮眼，与GPT差距持续缩小。</p><div class="card-tags"><span>LLM</span></div></div>
    <div class="card"><i data-lucide="cpu" class="card-icon"></i><h3>算力焦虑</h3><p>GPU出口管制下的困局，国产芯片替代紧迫。</p><div class="card-tags"><span>芯片</span></div></div>
    <div class="card"><i data-lucide="monitor" class="card-icon"></i><h3>AGI展示厅</h3><p>从助手到Agent全覆盖，应用生态丰富。</p><div class="card-tags"><span>应用</span></div></div>
  </div>
  <div class="logo-mark">bilibili_learning_bot</div>
</div>

<div class="slide" data-index="4">
  <span class="tag">DEEP DIVE</span>
  <h1 class="slide-title sm">中美AI对比</h1>
  <div class="slide-subtitle">发展路径与核心差异</div>
  <div class="divider"></div>
  <div class="two-col" style="margin-top:4px;">
    <ul class="feature-list">
      <li><span class="num">01</span> <strong>芯片封锁下的创新</strong> — 华为昇腾等国产路线</li>
      <li><span class="num">02</span> <strong>开源生态崛起</strong> — 中国开源模型获全球关注</li>
      <li><span class="num">03</span> <strong>应用层领先</strong> — 中国市场AI落地速度更快</li>
    </ul>
    <ul class="feature-list">
      <li><span class="num">04</span> <strong>人才双向流动</strong> — 硅谷↔中国 AI人才迁移</li>
      <li><span class="num">05</span> <strong>资本持续押注</strong> — 风投对中国AI长期看好</li>
      <li><span class="num">06</span> <strong>监管环境差异</strong> — 中美AI监管框架对比</li>
    </ul>
  </div>
  <div class="logo-mark">bilibili_learning_bot</div>
</div>

<div class="slide" data-index="5">
  <div class="end-card">
    <span class="tag">SUMMARY</span>
    <h1 class="slide-title">全球AI视角</h1>
    <p>Nathan Lambert的中国之旅揭示了中美AI竞合的真实面貌</p>
    <div class="divider center"></div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:20px;">
      <div><div class="big-num">{s['view']}</div><div class="num-label">播放</div></div>
      <div><div class="big-num">{s['like']}</div><div class="num-label">点赞</div></div>
      <div><div class="big-num">{s['favorite']}</div><div class="num-label">收藏</div></div>
      <div><div class="big-num">{s['danmaku']}</div><div class="num-label">弹幕</div></div>
    </div>
    <div style="font-size:12px;color:var(--text-tertiary);margin-top:18px;">
      <a href="{url}" style="color:var(--accent);">B站观看</a>
    </div>
    <div class="logo-mark">bilibili_learning_bot · {up}</div>
  </div>
</div>

</div>"""

async def main():
    print("[1/3] 获取视频信息...")
    video = await fetch_video_info()
    if not video:
        print("获取失败")
        return
    print(f"  {video['title'][:60]}...")
    print(f"  UP: {video['up_name']} | 播放: {video['stats']['view']}")

    print("\n[2/3] 构建slide内容 + build_full_html(claude_slides_v2)...")
    slides = build_slides(video)
    full = build_full_html(slides, theme_name="claude_slides_v2")

    print("\n[3/3] 保存...")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "html_exports")
    os.makedirs(out, exist_ok=True)
    safe = re.sub(r'[\\/*?:"<>|]', '_', video["title"])[:40]
    path = os.path.join(out, f"v2_{safe}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(full)

    print(f"\n[Done] {path}")
    print(f"  大小: {len(full):,}B | 主题: claude_slides_v2 (轻量)")
    print(f"  CSS: 3 keyframe | JS: 无锁/无粒子/无计数器")
    print(f"  翻页: 方向键←→ / 点击导航点 / 触摸滑动")

if __name__ == "__main__":
    asyncio.run(main())
