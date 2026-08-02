# 二次开发路线图

> 本文替代旧版一次性重构记录，用于开源维护和后续深度开发。历史变更请看 `CHANGELOG.md`。

## 当前状态

- CLI 入口：`main.py`、`cli/app.py`
- Web 入口：`web_panel.py` + `web_panel.html`
- 核心服务：`services/`
- B站 API：`api/`
- 知识库：`knowledge/`、`KnowledgeBase/`
- 统一网页生成：`services/html_renderer.py` + `templates/claude/`
- 测试：`tests/`

## 已完成的结构收敛

- `services/html_renderer.py` 成为 AI 网页输出的统一入口。
- `services.deep_dive` 的阅读页和 PPT 风格 HTML 导出已转发到统一渲染器。
- `services.knowledge_tutor` 的 HTML 生成提示词和包装逻辑已转发到统一渲染器。
- `services.video_to_ppt` 的 Claude 提示词 fallback 已复用统一组件契约。
- Claude 提示词升级到 `templates/claude/prompts/claude-style-prompt.md` v2.0。
- 新增 `08-learning-summary.html` 和 `09-research-brief.html` 作为学习页与深研报告参考。

## 后续优先级

### P0：稳定性和可验证性

- 已为 `services/html_renderer.py` 增加单元测试，覆盖代码块清理、容器补全、Markdown 转阅读页、Markdown 转幻灯片。
- 已为 `services.deep_dive.run_deep_research()` 增加 mock 测试，验证来源数量限幅、manifest 写入、导出格式和失败传递。
- 已为 Web API 的长任务路由抽取公共任务调度器，统一任务创建、线程异常处理、终态写入、轮询快照和过期回收，并新增路由级回归测试。

### P1：模块拆分

- 拆分 `web_panel.py`：按配置、知识库、视频分析、学习工具、导出任务分 Blueprint。
- 拆分 `cli/app.py`：把菜单层和服务调用层分离，减少全局变量依赖。
- 将导出目录、文件命名和清理逻辑集中到 `services/export_manager.py`。

### P2：AI 调用统一

- 所有服务层调用优先走 `services._services_ai.call_ai()`。
- 移除散落的旧 OpenAI SDK 调用写法。
- 给所有网络/LLM 调用设置 timeout、重试和清晰错误返回。

### P3：文档和开源体验

- README 只保留用户最关心的安装、配置、启动、常用功能和 FAQ。
- `dev_refs/` 保留给开发者，按接口和流程拆分，不再维护巨型重复手册。
- `CHANGELOG.md` 只记录版本变化，不放长篇架构说明。

## 开发约定

1. 新功能先放到 `services/`，提供可测试的纯函数或异步函数。
2. CLI/Web 只做参数解析、任务调度和结果展示。
3. 生成网页必须调用 `services.html_renderer`，不要在业务模块里复制 HTML/CSS 模板。
4. 写入重要 JSON 时使用原子写入。
5. 修改后至少运行：

```bash
python -m compileall -q api brain cli core knowledge ob_bridge persona security services utils xingye_bot main.py web_panel.py start_cli.py
python -m pytest -q
```
