# Claude Learning Web 模板库

用于 `视频→网页`、`知识辅导→HTML`、`深入了解/深研计划` 的统一网页生成规范与参考页面。

## 目录结构

```text
templates/claude/
├── README.md
├── prompts/
│   └── claude-style-prompt.md      # 统一 AI 网页生成提示词
└── examples/
    ├── 01-landing-page.html
    ├── 02-dashboard.html
    ├── 03-pricing-page.html
    ├── 04-blog-article.html
    ├── 05-faq-page.html
    ├── 06-signin-page.html
    ├── 07-warm-slides.html
    ├── 08-learning-summary.html    # 视频/知识学习页参考
    └── 09-research-brief.html      # 深研证据链报告参考
```

## 统一入口

所有新功能都应通过 `services.html_renderer` 接入网页生成：

- `load_claude_prompt()`：读取统一提示词。
- `render_slide_html(fragment, title=...)`：把模型输出的 `.ppt-container` 片段包装成完整 HTML。
- `markdown_to_reading_html(markdown, title)`：把 Markdown 报告导出为阅读页。
- `markdown_to_slides_html(markdown, title)`：把 Markdown 报告导出为幻灯片页。

不要在业务模块里手写完整 HTML、CSS 或 JS。业务模块只负责生成结构化内容片段。

## 提示词原则

`prompts/claude-style-prompt.md` 是单一事实源。修改网页设计规则时优先改这个文件，再让业务提示词引用它。

关键要求：

- 根节点必须是 `<div class="ppt-container">`。
- 只使用项目已有组件类名。
- 只使用 Lucide 图标。
- 内容必须基于输入资料，不编造事实、数字和来源。
- 每页只讲一个主题，避免文字溢出和重复卡片。

## 参考页用途

`examples/` 页面不是运行时依赖，主要用于帮助模型学习布局模式，也方便开发者人工查看视觉标准。

- `08-learning-summary.html`：适合视频总结、知识辅导、学习路线。
- `09-research-brief.html`：适合深研计划、证据表、分歧与待验证问题。
