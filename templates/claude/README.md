# Claude Design System — 模板库

> 用于「视频→网页」功能生成的 Claude 风格 HTML 页面参考。
> 将此目录下的设计规范文件提供给 AI，可生成风格一致的专业网页。

## 目录结构

```
templates/claude/
├── README.md                              ← 本文件
├── prompts/
│   └── claude-style-prompt.md             ← ★ AI 生成提示词（严格规范）
└── examples/
    ├── 01-landing-page.html               ← 产品落地页（含数字滚动动画）
    ├── 02-dashboard.html                  ← 仪表盘
    ├── 03-pricing-page.html               ← 定价页
    ├── 04-blog-article.html               ← 博客文章
    ├── 05-faq-page.html                   ← FAQ 帮助中心
    └── 06-signin-page.html                ← 登录页
    └── 07-warm-slides.html               ← 暖橙幻灯片（Inter+暖灰背景+紫粉渐变标题）
```

## 使用方式

### 方式一：视频→网页（自动）
在 Web 控制台选择 **Claude** 主题，生成的 PPT 风格 HTML 自动使用 Claude 设计规范（Fraunces + Inter 字体、暖色调背景、卡片式布局）。

### 方式二：作为 AI Prompt 参考
将 `prompts/claude-style-prompt.md` 内容提供给 AI，要求生成特定类型的页面：

```
请参考以下 Claude 设计规范，帮我生成一个用户设置页面：

[粘贴 claude-style-prompt.md 全文]

页面需求：
- 左侧导航栏 + 右侧内容区
- 包含头像上传、昵称修改、通知设置
- 支持亮色/暗色模式切换
```

### 方式三：直接打开示例参考
在浏览器中打开 `examples/` 下的 `.html` 文件，查看视觉效果。

## 设计核心

| 要素 | 规范 |
|------|------|
| 字体 | Inter (100-800)，标题细体 200/300 |
| 图标 | Lucide Icons，stroke-width: 1.5 |
| 配色 | 黑/白/灰 + 暖橙点缀 `#D97757` |
| 圆角 | 卡片 14px，按钮 8px |
| 模式 | 亮色/暗色自动切换 + localStorage 持久化 |
| 动画 | 数字滚动动画（easeOutExpo），入场上浮 |
| 禁止 | ❌ emoji、渐变、粗阴影、衬线体、多彩图标 |
