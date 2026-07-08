# 更新日志

## 3.0.3 抽帧画质选择 + 平台聚焦 (2026-07-07)

### ✨ 新功能
- **下载画质选择（默认最优质）**：抽帧/视频分析下载 B站视频时支持画质档位 `best`(自动最高) / `1080p` / `720p` / `480p` / `360p`，由配置 `video.quality` 控制，默认 `best`（qn=127，DASH 返回最高可用流）。`xingye_bot/video_modes.py` 的 DASH 与 FLV 下载均接入该配置；`cli/app.py` 视频设置菜单新增「下载画质」显示与交互；`xingye_bot/settings.py` 的 `BotSettings.video_quality` 贯穿到 `VideoUnderstanding`。
- **全平台支持已移除（仅保留 B站）**：已彻底移除 YouTube / 抖音 / 快手 / 网页 / 本地文件等非 B站平台支持。`services/platform_adapter.py` 精简为纯 B站输入识别与归一化（BV号 / 链接 / b23.tv 短链）；`brain/video_analysis.py` 的 `analyze_platform_video_input` 多平台分析链路已删除；主菜单 `V`、Web 面板与配置文件均不再暴露其他平台。

### ✅ 验证
- 改动文件 `py_compile` 全部通过；画质映射 `VIDEO_QUALITY_MAP`（`best→127 / 1080p→80 / 720p→64 / 480p→32 / 360p→16`）与 `_resolve_quality` 非法值回退最高（127）单测通过；`load_settings().video_quality` 默认 `best`、配置中已移除 `platform_adapter` 段（仅保留 B站链路）校验通过。

## 3.0.2 主页智能对话 + 导出目录改造 (2026-07-07)

### ✨ 新功能
- **主页智能对话（AI / Agent 双模式）**：新增 `services/home_chat.py` 与 Web 接口 `POST /api/home/chat`。默认 AI 模式，可在「智能对话」页或仪表盘「主页对话命令」卡片中切换为 Agent 模式。
  - 意图识别支持六类问答：最近刷到的视频、学到的知识、笔记核心观点、总结最近看的视频、根据观看记录画用户画像、以及「我是一个什么样的人」（基于用户自定义 `persona.self_description`）。
  - AI 模式自动汇总学习日志、知识库概况与命中笔记片段作为上下文调用 LLM；Agent 模式委派 `AgentSkillRunner` 执行目标。
- **思维导图目录改造**：默认输出目录由 `Data/MindMaps/` 改为项目根 `MindMaps/`（`core/config.py` 默认、`core/globals.py` `MINDMAP_OUTPUT_DIR`、实时 `Data/config.json` 同步更新）。新增 `mindmap.prompt`（可选 AI 大纲提示词）。
- **Word 文档独立导出**：新增 `document_export` 配置段（`enabled` / `folder_name` / `output_dir` / `prompt`），默认开启、单独输出到 `Word/` 文件夹；知识归档时自动导出 `.docx`（受 `document_export.enabled` 控制）。
- **设置开关**：配置编辑快捷面板新增「思维导图 & 文档导出」段（开关 / 目录 / 提示词）以及人格「自我描述（画像用）」字段。

### 🔧 增强（2026-07-07 追加）：持久多会话 + 上下文模式 + 高度自定义
- **持久多会话**：新增 `Data/HomeChat/<id>.json` 会话存储。支持新建 / 选择 / 重命名 / 删除会话；进入对话页自动恢复最近一次会话；每次问答（含 AI 失败回退）都落盘持久化。新增接口：`GET /api/home/conversations`、`POST /api/home/conversation`、`GET/DELETE /api/home/conversation/<id>`、`POST /api/home/conversation/<id>/rename`。
- **上下文模式**（对话页「上下文」下拉）：
  - `persistent` 持久上下文（默认）：保留最近 20 条消息作为连续对话上下文。
  - `infinite` 无限上下文：全部历史消息都发送给模型（不截断，注意 token 成本）。
  - `none` 无上下文：每次只基于知识库检索，不带入聊天历史（适合独立问答）。
- **高度自定义**（对话页「⚙ 自定义」面板）：可填写**系统提示词**（作为人格/约束，自动追加知识上下文）、**模型**（留空=默认）、**温度**（0–1.5 滑块）。这些参数随会话持久化，续聊自动沿用。
- LLM 调用由 `xingye_bot.llm.ModelClient.chat` 切换为 `services._services_ai.call_ai`，以支持自定义 `model` 与 `temperature` 透传（沿用现有统一 API Key/Base URL 配置）。

### 🔧 增强（2026-07-07 追加）：W 命令支持视频内容多格式导出
- **命令 W（视频→网页/导出）**：在生成 HTML 网页并保存后，新增提示「是否同时把该视频内容导出为其他格式」，可多选 `1=Word(.docx)` / `2=PDF(.pdf)` / `3=PPT(.html)`。复用 W 与 V 共用的视频获取流程（指定视频→`understand_video_for_decision` 得到内容 `ctx`），对同一份视频内容导出多格式，无需重复分析。
- 新增 `services/document_export.py` 的 `export_docx_text()` / `export_pdf_text()`：从内存文本直接生成 docx/pdf，绕过知识库目录限制（视频内容无需先落盘到 KnowledgeBase），默认输出到配置的 `Word/` 文件夹。Word/PDF 导出失败会友好提示而非中断；PPT 复用 `services/video_to_ppt.generate_ppt_from_bvid`（自动取配置中的 API Key/Base URL/模型与登录 Cookie）。
- 主菜单 W 项说明更新为「视频->网页/导出 (指定视频生成HTML，并可导出 Word/PDF/PPT)」。
- **命令 V（手动视频分析）同样支持导出**：`brain/video_analysis.py` 的 `manual_video_analysis` 在 B站视频分析完成后，复用共享函数 `services/document_export.export_video_content_interactive` 提示导出 Word/PDF/PPT；主菜单 V 项说明同步更新为「…· 可导出 Word/PDF/PPT」。W/V 共用同一份视频内容理解（`understand_video_for_decision`），导出逻辑抽成两层：`export_video_content()`（非交互，返回 `{fmt:{path|error}}`）与 `export_video_content_interactive()`（CLI 交互包装），CLI 与 Web 共用，避免重复代码。
- **网页端视频导出**：`web_panel.py` 新增 `POST /api/export/video`（解析 BV/链接 → 理解视频内容 → 评论/弹幕 → 调用 `export_video_content` 导出指定格式列表），`web_panel.html` 在「手动视频分析」卡片后新增「📤 视频内容导出」卡片（BV/链接 + Word/PDF/PPT 多选 + 结果路径展示），与 CLI 的 W/V 命令共用同一套内容理解与导出逻辑。

### ✅ 验证
- 所有改动文件 `py_compile` 通过；`home_chat` 意图识别与上下文采集单测通过；`MINDMAP_OUTPUT_DIR`→`MindMaps/`、`DOC_EXPORT_DIR`→`Word/` 解析正确。
- 运行时验证：上下文切片（persistent=20 / infinite=N / none=0）、`home_chat` 在 API 限流(429)下优雅回退且消息仍持久化、会话 list/rename/delete 均正常。

## 3.0.2 知识库路径解析收尾修复 (2026-07-07)

### 🔧 修复（补齐此前仅文档声称、代码未落实的部分）

- **知识库目录真正从配置解析**：`core/config.py` 新增 `resolve_knowledge_base_dir()`，`KNOWLEDGE_BASE_DIR` 在模块导入时（以及 `save_config()` 保存后）从 `knowledge_base_dir` / `knowledge.base_dir` 解析，未配置回退默认 `KnowledgeBase`。
- **`services/knowledge_tutor.py` 不再硬编码**：其 `KNOWLEDGE_BASE_DIR` 改为从 `config.json` 解析，使 `/api/kb/list-files`、`/api/kb/read-file`、`/api/kb/tutor-chat`、`/api/kb/tutor-save` 等端点尊重自定义知识库目录。
- **`/api/kb/files` 修正**：此前硬编码 `BASE_DIR / "KnowledgeBase"`，现改为与 `/api/kb/stats`、`/api/kb/file`、`/api/health` 一致，读取配置路径。
- **`.md` 大小写回退**：`/api/kb/file` 读取时若精确路径不存在，按忽略大小写在知识库目录内查找同名文件，避免大写 `.MD` 导致 404。

### ✅ 验证

- `python -m py_compile core/config.py services/knowledge_tutor.py web_panel.py` 通过；相关文件 linter 0 诊断。
- `resolve_knowledge_base_dir()` 三种情况验证：相对路径→归并 BASE_DIR、绝对路径→原样、缺省→默认 `KnowledgeBase`。

## 3.0.2 配置同步与运行稳定性修复 (2026-07-07)

### 🔧 修复

- **API 配置运行期同步**：CLI 保存 API Key/Base URL/模型后同步 `core.config.config`，避免菜单显示已配置但刷视频仍提示 `unified_api_key` 未配置。
- **配置字段兼容**：`core.config.normalize_config()` 兼容旧字段 `api_key`/`base_url`/`model`，Web `/api/config` 保存时也会归一化。
- **多账号数据目录统一**：`core/config.py` 支持 `BILI_ACCOUNT_DATA_DIR`，Web 面板启动机器人子进程时传递当前账号目录。
- **Windows 登录二维码路径**：扫码登录仅在 Android/Termux 环境写入 `/storage/emulated/0/Pictures` 并调用 `am broadcast`，Windows 下只保存到项目 `qr_codes/`。
- **主动私信异常**：补齐 `PrivateMessageManager.get_chat_target()`，避免主动聊天时报缺少方法。
- **知识库统计修正**：`/api/kb/stats`、`/api/kb/files`、`/api/kb/file`、`/api/health` 和重置清理逻辑支持配置路径和 `.MD` 后缀。
- **二维码清理路径对齐**：登录成功后清理项目根 `qr_codes/`，与二维码保存路径一致。
- **模型列表错误提示**：模型接口返回非 JSON 时提示检查 `/v1` 地址并展示响应预览。

### ✅ 验证

- `python -m py_compile core\config.py cli\app.py api\auth.py brain\private_msg.py persona\managers.py web_panel.py` 通过。
- 核心配置读取验证：API Key、Base URL、思考模型均可读取到已配置状态。

## 3.0.2 README 对齐与部署健康检查补强 (2026-07-07)

### 🔧 修复

- **Web 默认端口对齐 README**：裸启动 `python3 web_panel.py` 默认使用 `7860`；Docker 通过 `WEB_PORT=7860` 保持 compose 访问 `7860`。
- **健康检查免登录**：`/api/health`、`/deploy_status`、`/api/asr/status` 可被 Docker/部署探针直接访问。
- **首次启动稳定性**：Web 面板启动前先创建 `Data/`，避免首次写入 `.web_secret_key` 失败。
- **README 平台说明对齐**：补充网页链接平台，并明确 CLI `V` 命令开始先选平台、回车默认 B站。

## 3.0.2 PR #17 共享工具去重修复 (2026-07-07)

### 🔧 重构

- **字幕优先级去重**：新增 `utils/subtitles.py`，抽取 `subtitle_priority()`；`api/subtitles.py` 和 `xingye_bot/video_modes.py` 改为复用共享函数。
- **密钥脱敏去重**：`core/config.py` 改为复用 `utils.display.mask_secret`，删除重复实现。
- **配置 getter 去重**：`core/globals.py` 复用 `core.config` 中的 `_get_vision_api_key()`、`_get_vision_base_url()`、`_get_fallback_models()`。
- **BOM 清理**：移除 `xingye_bot/diary.py`、`xingye_bot/skills.py`、`xingye_bot/state.py` 的 UTF-8 BOM，避免 AST/静态解析异常。

### ✅ 验证

- `python -m py_compile api\subtitles.py xingye_bot\video_modes.py core\config.py core\globals.py utils\display.py utils\subtitles.py xingye_bot\diary.py xingye_bot\skills.py xingye_bot\state.py` 通过。
- 已确认所有 Python 文件扫描结果为 `NO_BOM`。
- `core.config` / `core.globals` 导入验证通过。

## 3.0.2 P0 产品化文案与 SEO 补强 (2026-07-07)

### 📝 文档

- **README 补强长视频学习卖点**：新增“章节锁定 + 内容追加”“零信息丢失导向”“思维导图导出”说明。
- **README 新增 FAQ**：补充项目区别、长视频防遗漏、多平台输入、知识库能力等常见问题。
- **Web 面板 SEO**：`web_panel.html` 新增 `meta description` 和 `FAQPage` JSON-LD 结构化数据。
- **差别文档更新**：`G:\code\work\差别.md` 已标记 P0 产品化文案与 FAQPage JSON-LD 为已完成。

## 3.0.2 P0 修复与批量导图 API (2026-07-07)

### 🔧 修复

- **版本号统一**：`VERSION`、`start.sh`、`requirements.txt`、`install_termux.sh`、`docker-compose.yml` 统一到 `3.0.2`。
- **批量思维导图路由补齐**：`web_panel.py` 新增 `POST /api/export/mindmap/all`，扫描 `KnowledgeBase/**/*.md` 批量调用 `export_mindmap()`，返回总数、成功数、失败数、输出路径和错误列表。
- **差别文档更新**：`G:\code\work\差别.md` 已标记版本统一和批量导图 API 为 P0 已完成。

## 3.0.2 文档与 Landing 更新 (2026-07-07)

### 🆕 新增

- **Landing 快速识别页**：文档站首页新增平台选择器（默认 B站）、视频链接/本地路径输入、快捷示例和识别结果展示。
- **轻量识别 API**：`vitepress-demo-main/main.py` 新增 `POST /api/analyze`，支持 BV号、B站链接、YouTube、抖音、快手、网页链接和本地文件路径识别。
- **使用文档**：新增 `docs/guide/usage.md`，覆盖环境准备、启动方式、CLI `V` 命令、Web 面板、Landing 页面和常见问题。
- **区别文档**：新增 `docs/guide/differences.md`，说明 v3.0.2 相比旧版在全平台适配、Web 安全、Landing 页面、@通知响应、知识输出方面的变化。

### 🔧 更新

- README 更新到 `v3.0.2`，补充全平台视频分析、Landing 快速识别、`yt-dlp` 依赖与 Web 本地文件安全说明。
- VitePress 侧边栏加入“使用文档”和“与旧版区别”。
- 文档站首页、功能特点、部署快速开始同步补充新能力。

## 2.2.1 → 3.0.0

### 🏗️ 架构重构
- 16.8K 行单体 `start_cli.py` → 4 行入口 + 24 个职责清晰的模块文件
- 新增 `main.py` 主入口，统一 CLI 和 Web 面板启动
- 拆分为 `api/` / `brain/` / `knowledge/` / `persona/` / `security/` / `services/` / `utils/` / `xingye_bot/`
- 删除重复代码 `new_agent.py`（17K 行）、死代码 `interaction_service.py`
- 统一配置系统，`xingye_bot/settings.py` → 从 `core/config.py` 读取
- 密码 SHA-256 哈希存储

### 🆕 新增功能

- **🔔 @通知响应**：在任何视频下评论 "@bot 总结这个视频"，bot 自动识别所在视频并总结回复
  - 通过 B站 `x/msg/at` API 拉取 @我通知
  - 无需手动提供 BV 号，从评论上下文自动提取
  - 双模式支持：通知模式 + legacy 模式

- **📡 实时监听模式**：独立于视频刷取的消息监听引擎
  - 只盯私信和评论，有新消息立刻 AI 回复，不刷视频、不消耗精力
  - Web面板新增「📡 实时监听」页面，含启停控制、配置、统计、实时日志

- **🎨 视频→网页 + Claude 设计系统**：将已学视频生成精美 PPT 风格 HTML
  - 支持多主题，内置 Claude 设计主题
  - 毛玻璃卡片 + 数字滚动动画（easeOutExpo 缓动）
  - `templates/claude/` 含 6 个参考页面 + AI 设计规范

- **🌐 Web面板UI全面重设计**
  - 毛玻璃效果、渐变按钮、动画过渡、响应式布局
  - 侧边栏 active 状态渐变背景、页面切换动画、自定义滚动条

- **🛡️ 安全审查**：关键词过滤 + 政治敏感拦截 + 提示词注入防护

- **🔄 备用API降级**：主 API 连续失败自动切换备用提供商，10分钟后自动恢复

- **📤 隐私导出**：一键导出配置，API Key/Cookie 脱敏保护

### 🔧 Bug 修复

- 按 Q 切换快速模式时 `bili.throttle` 引用错误崩溃
- 主循环 `_safe_task_callback` 未定义崩溃
- 评论/私信节奏控制静默失效（缺少 datetime 导入）
- `_reload_all_globals` 遗漏 `AI_MARKER` 全局变量
- `asyncio.gather` 无 `return_exceptions=True` 导致并发异常
- 13 处 JSON 写入改为 tmp+replace 原子操作，防止断电数据损坏
- Flask session 密钥持久化

### 📁 新增文件

- `main.py` — 主入口
- `brain/standby.py` — 待机监听引擎 v2
- `brain/monitor.py` — 实时监听引擎
- `services/video_to_ppt.py` — 视频→HTML 网页生成
- `services/agent_service.py` — Agent 技能执行
- `services/knowledge_tutor.py` — 知识辅导
- `templates/claude/` — Claude 设计系统
- `tests/` — 43 个 pytest 测试

### 🆕 功能增强 (2026-07-06 BiliNote inspired)

- **章节锁定 + 内容追加**：长视频自动启用分章笔记流程，先锁定章节大纲，再逐段追加知识点，降低长视频总结遗漏。
- **笔记风格定制**：新增 balanced / academic / conversational / key_points 四种风格，可在配置和 Web 快捷配置切换。
- **思维导图导出**：新增 `services/mindmap_export.py`，知识归档后可自动生成 markmap HTML；Web API：`POST /api/export/mindmap`。
- **RAG 知识库问答**：新增 `services/rag_qa.py` 与 Web API：`POST /api/knowledge/ask`，支持基于 KnowledgeBase 的检索问答。
- **配置扩展**：新增 `chapter_lock`、`mindmap`、`export`、`note_style`、`rag_qa`、`version_history`、`browser_extension` 配置段。
- **全平台适配层**：新增 `services/platform_adapter.py`，借鉴 BiliNote 的平台识别逻辑，支持 B站 / YouTube / 抖音 / 快手 / 本地文件输入识别；Web 新增 `POST /api/platform/probe`，非 B站优先用 `yt-dlp` 读取元数据/字幕，并已接入下载、ASR、视觉抽帧、AI评分与知识归档链路。
- **模型预设切换**：新增 `model_presets` + `active_preset`，Web 快捷配置可一键套用 GPT-4o / Claude / Gemini / DeepSeek。
- **批量导图与版本记录**：新增 `POST /api/export/mindmap/all` 批量导图；启用 `version_history.enabled` 后同名笔记重新生成会保存 `.versions/` 历史与 diff。

### 🔧 Bug 修复 (3.0.0 后续补丁)

- **字幕获取 player/wbi/v2 412 风控修复**：B站 `player/wbi/v2` 带 cookie 请求可能返回 412，快速 fallback 到 `player/v2` 获取 AI 字幕
- **V 命令字幕检测修复**：搜索结果字幕检测改为 `player/wbi/v2` + WBI 签名，正确识别 AI 字幕（`lan:ai-zh`）
- **Cookie 扫描增强**：V 命令自动扫描多个兄弟项目目录加载登录 cookie
- **配置模板修复**：修复 `config.example.json` 中 `platform_adapter` 后缺逗号导致示例配置无法解析的问题，并新增测试防回归
- **Web 本地文件安全**：`/api/platform/probe` 与 `/api/action/analyze-video` 默认禁止处理本地文件路径，需显式开启 `platform_adapter.allow_web_local_files`
- **全平台下载兼容性**：默认 `download_format` 调整为 `bv*+ba/best/best`，为非 YouTube 平台保留 `best` fallback
- **未登录字幕提示**：未登录时明确提示「部分视频需登录账号获取 AI 字幕」
- **W 命令保存路径**：默认保存改为项目根目录 `web/` 文件夹

### ⚠️ 注意事项

- 监听模式与机器人主进程互斥
- 配置文件格式有变动，请参考 `config.example.json`
