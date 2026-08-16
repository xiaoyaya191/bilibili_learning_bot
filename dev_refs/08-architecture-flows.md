# 项目架构与代码流程

> 面向二次开发：快速定位入口、服务边界和数据流。

## 项目结构

```text
bilibili_learning_bot/
├── main.py                  # CLI 主入口
├── start_cli.py             # CLI 兼容入口
├── web_panel.py             # Flask Web 后端
├── web_panel.html           # Web 前端模板
├── api/                     # B站 API、登录、字幕、节流
├── brain/                   # 自动学习机器人核心流程
├── cli/                     # CLI 菜单与配置交互
├── core/                    # 配置、路径和运行时全局状态
├── knowledge/               # 知识库分类、检索、整理、重温
├── services/                # 可复用服务模块
│   ├── html_renderer.py     # 统一网页生成入口
│   ├── video_to_ppt.py      # 视频→网页
│   ├── knowledge_tutor.py   # 知识辅导/HTML 输出
│   ├── deep_dive.py         # 深入了解/深研计划
│   ├── quiz_generator.py    # 出题考试
│   ├── mindmap_export.py    # Markdown→markmap
│   └── ...
├── templates/claude/        # 网页提示词和参考页面
├── tests/                   # pytest 测试
├── Data/                    # 运行时数据
├── KnowledgeBase/           # 知识库 Markdown
└── html_exports/            # HTML/报告导出
```

## 分层原则

- `services/`：核心业务能力，尽量可测试、可复用。
- `cli/`：只负责菜单、输入、输出。
- `web_panel.py`：只负责路由、任务调度、JSON 返回。
- `api/`：只封装 B站接口和认证。
- `core/`：配置、路径、全局状态。
- `templates/`：网页设计规则和参考，不写业务逻辑。

## 核心数据流

### 视频学习

```text
用户输入 BV/链接
  -> services.platform_adapter 归一化
  -> api.subtitles 获取字幕和视频信息
  -> brain/video_analysis 或 brain/_brain_video 分析
  -> services._services_ai.call_ai 生成笔记
  -> KnowledgeBase/ 保存 Markdown
  -> 可选 services.video_to_ppt + services.html_renderer 导出 HTML
```

### 视频/知识生成网页

```text
业务模块准备资料
  -> 构造 AI prompt（引用 templates/claude/prompts/claude-style-prompt.md）
  -> LLM 输出 <div class="ppt-container">...</div>
  -> services.html_renderer.render_slide_html()
  -> html_exports/ 或用户指定目录
```

规则：不要在业务模块里复制完整 HTML/CSS/JS。新增网页输出必须走 `services.html_renderer`。

### 深入了解 / 深研计划

```text
CLI: J -> 深入了解/深研计划
Web: /api/action/deep-research
  -> services.deep_dive.run_deep_dive() / run_deep_research()
  -> AI 生成关键词
  -> 联网搜索或 B站搜索
  -> 汇总来源和内容
  -> AI 生成 Markdown 报告
  -> 保存主报告、来源快照、research manifest
  -> services.html_renderer 导出阅读页和幻灯片页
```

### 出题考试

```text
CLI/Web 输入主题或知识来源
  -> services.quiz_generator
  -> 读取字幕或知识库 Markdown
  -> LLM 生成题目
  -> 保存到 html_exports/quizzes/
```

### Web 面板请求

```text
浏览器 fetch
  -> Flask route
  -> 参数校验
  -> 同步调用或后台线程任务
  -> service 函数
  -> TASKS 状态 / jsonify 返回
```

后续建议抽取统一任务调度器，减少路由里重复 `TASKS + threading.Thread`。

## 关键开发约定

### 实时配置读取

不要在模块加载时缓存配置值：

```python
def get_api_key():
    from core.config import config
    return config.get("api", {}).get("unified_api_key", "")
```

### AI 调用

服务层优先使用：

```python
from services._services_ai import call_ai

text = await call_ai(messages=[...], timeout=120, verbose=False)
```

### 网页生成

```python
from services.html_renderer import render_slide_html

html = render_slide_html(fragment, title="学习页面")
```

### 文件写入

重要 JSON 使用 tmp + replace 原子写入。普通 Markdown/HTML 导出可以直接写，但要确保目录存在。

### 验证

```bash
python -m compileall -q api brain cli core knowledge ob_bridge persona security services utils xingye_bot main.py web_panel.py start_cli.py
python -m pytest -q
```
