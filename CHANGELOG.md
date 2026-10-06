# 更新日志

## 3.1.6 移除独立局域网文件传输工具（2026-10-07）

- 删除独立文件传输服务与桌面入口、专用 HTML 模板、PyInstaller 配置和构建脚本。
- 专用图标、EXE、打包中间文件和 Python 缓存的删除被环境策略拦截，暂时保留；未改动机器人资源、其他构建验收页面及用户数据。
- 同步更新 AGNET.md；静态检查剩余源码与配置无该工具引用，未运行全量测试或重新打包。

## 3.1.6 多API接口池与轮询（2026-10-06）

- 配置编辑 → AI接入新增多API接口池，默认关闭；最多100个接口，支持顺序/加权/随机/优先故障切换，主API可选择参与。
- 轮数、总尝试上限、总超时、等待退避、失败阈值、冷却、重试/切换状态码及每接口地址/密钥/模型/能力/权重/尝试/超时/请求头均可自定义。
- 接入主脑、共享服务和工具调用；按账号持久轮询和健康统计。单接口欠费或限流不会拖住其他可用接口，400/422不重放，全部冷却立即反馈。
- 修复主脑API热更新、网页备用模型未被主脑读取、服务重试次数写死和429冷却局部赋值；池启用时不被旧全局冷却阻塞。
- 密钥与请求头脱敏，按ID保留确保排序不丢失、不串密钥；独立保存防主配置缓存覆盖，接口测试带额度提示，状态重置需确认。
- 全量pytest 653项通过，保留1个既有Windows curl_cffi警告；Python/JavaScript/JSON检查通过。使用模拟请求与真实本地HTTP服务器验证，并实测隔离面板添加/排序/保存/启用和桌面手机布局；未调用真实付费API或重打包。

## 3.1.6 独立视频复习分区（2026-10-06）

- 新增总览“视频复习”分区，自动计划默认关闭；旧配置需保存确认后生效。旧知识库按钮跳转独立分区，旧Web接口改为需确认的持久单次任务。
- 支持历史、点赞记录、已记录的平台收藏、本地收藏来源，以及时间段/星期、类型、关键词、UP主、收藏夹、评分、等待时间、次数和冷却自定义；预览和选片不调用AI。
- 复习任务与总结每账号独立保存，支持中断恢复、待执行取消、失败记录和每日额度；已有观看队列优先，手动任务不会开启自动计划。
- 复习仅理解和总结，不点赞、投币、收藏、评论或关注；可靠完成才增加次数，修复普通观看重置复习次数。
- 验证：最终全量589项通过，1个既有Windows curl_cffi警告；Python/JS/配置语法检查、隔离面板桌面和手机实看、保存规则和创建单次任务通过；未调用真实B站或付费AI，未重新打包。

## 3.1.6 批量视频观看与持久队列（2026-10-06）

- AI 候选筛选由单选改为多选并排序；默认不额外截断入选项，明确无合适内容则进入下一轮。先保存整批队列，再逐条观看完毕，避免每看一条就重新筛选丢掉其余优质视频。
- 顺序调整为标题封面、统计数据、视频内容、评论弹幕、最终评分和行动；转发数量不可用则跳过。默认已入选项不重复兴趣筛选，保留安全拦截及用户原有视觉/字幕/评论设置。
- 稍后再看分区新增本地队列、可配置设置和分页观看历史；支持手动加入、队首优先、移除确认、重新排队、历史重新加入和单独清除去重。
- 每账号独立 SQLite 队列：原子整批入队、单任务领取、异常关闭恢复、有限失败重试；本地保存不依赖 B站网络。看完删除、历史保存/数量、重试/间隔、已看去重等均可配置。
- B站稍后再看保留为独立列表；可选同步入选队列及完成删除，默认关闭，遵守原功能开关。平台同步失败不丢失本地队列。
- 独立尊重 AI 学习/点赞意图；队列投币、评论尝试先落盘，防止中断恢复再次扣币或重发，不绕过现有审核与安全规则。
- 验证：全量 551 项测试通过，最后数据库初始化调整后专项 40 项通过；Python/JavaScript 检查、隔离面板实看和设置/入队/历史恢复操作通过。未调用真实 B站或付费 AI，未重新打包。

## 3.1.6 视频与学习 HTML 参考布局统一（2026-10-06）

- 以 `project_intro.html` 与上级 `test.html` 为基线重做公共导出布局、样式、导航和进度，不只是增加一个主题；旧布局 ID 全部兼容到同一引擎。
- 视频、知识辅导、深研报告及通用文本 HTML 导出统一使用新外壳；生成入口仅保留统一参考布局，更多动画默认开启。
- 新增章节抽屉、连续阅读、自动播放/倒计时、全屏状态、下载 HTML、打印/PDF、键盘及触摸翻页；进度条流光、卡片错峰入场、数字递增、悬停反馈与减少动态效果支持。
- 优化桌面内容密度、手机单列与长章节滚动；亮暗模式保持一致布局，深色页面打印使用浅色变量；本地 Lucide 图标内嵌，控制功能无需 CDN。
- 新增根目录 `video_html_preview.html` 与可维护预览源片段；历史私人导出文件不覆盖，需重新生成应用新版。
- 验证：516 项测试通过，1 个既有 Windows curl_cffi 警告；Python 与 JavaScript 语法检查、桌面/手机亮暗实看、目录/翻页/阅读/自动播放/下载通过。下载文件离线重开被自动化浏览器 file URL 策略阻止，未实测付费 AI、真实 B 站、PDF 输出或重新打包。

## 3.1.6 独立多账号工作空间（2026-10-06）

- 实现方案 B：最多 10 个账号，各自独立 Web 端口、配置、Cookie、人格、上下文、知识库、日志、SQLite、导出与备份。
- 主面板“配置编辑”新增账号管理入口；支持创建、重命名、改端口、启停、重启、打开和确认删除，副面板无权修改其他账号。
- 新增账号注册表跨进程文件锁与原子保存、损坏索引保护、端口冲突检查和工作空间路径校验。新账号不复制主账号凭据，副账号启动时不继承主账号 AI 环境设置和加密密钥。
- 标准 Web/桌面/CLI 入口首次启动自动创建主工作空间；迁移前备份，旧数据和自定义导出目录复制到主账号，原目录保留。副账号删除前需停止并输入 ID 二次确认，先生成完整 ZIP 备份。
- 会话 Cookie 使用账号专属名称，防止同域名不同端口互相覆盖；后台启动不等待终端输入，浏览器仍要求单独确认免责声明。账号面板不自动启动机器人。
- 文档与思维导图导出、CLI 清理和数据路径遵守工作空间边界；账号端口被占用时拒绝启动而非自动改端口。管理器只终止自己创建的进程树，不接管未知占用进程。
- Compose 持久化统一账号根目录并映射默认子端口；保留宿主机可配置主端口，容器服务固定监听 8080。
- 验证：真实双面板启动/重启/停止及账号路径和会话隔离通过；全量 pytest：495 passed，1 个现有 Windows curl_cffi 事件循环警告；Python 编译与前端 JavaScript 解析通过。未实测真实 B 站登录、付费 AI、EXE 打包或容器部署。

### 多账号入口分区（2026-10-06）

- 侧栏“系统配置”新增固定可见的“账号管理”分区；主账号嵌入管理工作区，副账号显示主账号入口。
- 新增账号上下文接口和 #accounts 直达逻辑；同步独立模板与内嵌模板，侧栏隐藏设置不能移除账号管理入口。
- 浏览器实测入口、嵌入页、新增账号、端口分配、启动和停止；专项测试 15 passed；全量测试 499 passed，1 个既有 Windows asyncio/curl_cffi 警告。

## 3.1.4 favorability, skill bank, and reliability (2026-08-22)

### Added

- True Agent mode: an autonomous Agent Loop where the LLM plans, calls 17 built-in tools (search, watch, analyze, archive, DM, schedule...), reflects on results, and self-terminates; coexists with the classic Pipeline, with full session history in the web panel.
- Favorability system: per-user relationship scores tracked across comments, DMs, and follows, with AI-driven adjustments, manual panel controls, and a default-off feature switch.
- AI Skill Bank: videos are distilled into reusable skill cards on archive, injected into Agent DM replies by relevance, and fully manageable (CRUD) from the web panel.
- Segmented AI DM replies: the bot can first acknowledge ("let me watch it"), then return with a real summary after processing.
- Multi-threaded model availability testing with custom concurrency, timeout, and prompt; vision-capable models are included in fetching and testing.
- Learning mini-goals: AI auto-setting plus manual CRUD and progress tracking.
- Email-based password recovery via verification codes, first-run email setup wizard (skippable), backup email support, and profile email management.
- Custom web panel port and an optional hide-system-tray setting (tray shown by default).
- New-user tutorial now opens with a "View project introduction" step (2-minute illustrated overview, skippable or viewable directly).
- Circular-reveal (View Transitions) theme-switch animation on all auth pages (disclaimer / first-run setup / login / forgot-password), matching the main panel.

### Fixed

- Linux startup crash `ModuleNotFoundError: No module named 'msvcrt'` (#25): platform-conditional file locking (msvcrt on Windows, fcntl on Linux/Termux) in the private-message manager.
- QR login "登录凭据不完整": incomplete callback cookies are now auto-retried 3x via callback redirect before failing, and the account profile is warmed in the background right after login.
- "账号资料暂时无法同步": nav fetch retries once on transient failure and the failure cache TTL dropped 60s→20s so manual re-check recovers faster.
- Files saved as UTF-8 with BOM (Notepad/PowerShell default) no longer break config/cookie/history loading — 141 JSON read points now use BOM-tolerant decoding.
- Bot started from the web panel no longer hangs forever in the terminal QR wizard when Bilibili credentials are missing; it exits immediately with a clear message.
- Expired Bilibili cookies can no longer launch a "zombie run" (AI analysis burning tokens while every interaction fails -101): start now verifies credentials against the nav API first.
- Bilibili API Brotli encoding failures ("Can not decode content-encoding: br") via a three-layer Accept-Encoding and decode fallback in `utils/bili_compat.py`.
- Duplicate system tray icons through a named-mutex single-owner guard.
- Six memory-system bugs: AI-side memories could not really be deleted or edited from the panel, profiles resurrected after deletion, permanent memories were silently dropped by the 1000-entry trim, search results were polluted by unfiltered AI memories, and duplicate deletes reported fake success.
- Follow-action attribute-8 false failure detection (risk-control verdict now verified with delay and retry).
- Watch-history re-fetch that stopped working for some entries.
- All partition "check status" and "refresh" buttons now show loading animation and toast feedback.
- Web panel "all buttons unresponsive": two conflicting global click handlers formed a death loop (every button only spun, `onclick` never fired); loading states are now managed by each handler itself.
- New users never saw the onboarding tutorial: the server-side onboarding state is now authoritative, so residual browser localStorage flags can no longer hide it.
- Auth pages silently broken when CDN is unreachable: local `/assets/` copies of lucide/Chart.js now load first and are exempt from auth redirects (a 302-to-login HTML used to kill JS parsing and freeze every button).

### Optimized

- Redesigned login, about, profile, config editor, learning live, UP-follow, and AI history search partitions; dashboard animations retuned to smooth Apple-style motion.
- Human-readable logs: common WARN/ERROR messages are auto-translated into plain-language hints, unknown issues point to the support QQ group, with dedup to prevent spam.
- Memory/KB and watch-history partitions now cache for 15 seconds and proxy covers from local disk for instant loads.
- Runtime display precision changed from seconds to minutes; installer script updated to v3.1.4; test suite grown to 385 passing pytest cases.

## 3.1.3## 3.1.3 social workspaces and reminder controls (2026-08-09)

- Added the Bilibili watch-later workspace with explicit list, add, remove, and clear operations.
- Added a unified local reminder workspace and a local dynamic draft center.
- Added dynamic publishing to the existing review inbox. Dynamic publishing remains disabled by default.
- Added fine-grained toggles for active DMs, watch later, owner sharing, dynamic drafts, and dynamic publishing.
- Added safe open-folder access for known user-data groups and a bracket-emote preference for generated messages.

## 3.1.3 reliability follow-up (2026-08-09)

- Treat closed-comment error `12002` as terminal so mention delivery does not retry it.
- Fixed Bilibili DM avatar/name lookups and legacy knowledge BV recovery.
- Added universal refresh feedback, mobile DM overflow guards, and `deploy_termux.sh`.

## 3.1.3 visual and alert workflow polish (2026-08-09)

- Added TXT and JSON exports for the currently filtered, redacted full log stream.
- Added an optional, default-off email-review mode. When enabled, quota/spend alerts are persisted as pending review records instead of contacting SMTP.
- Improved grid-frame deduplication with a grayscale visual fingerprint so near-identical consecutive frames do not fill a nine-cell grid.

## 3.1.3 ASR and Agent workspaces (2026-08-09)

- Moved ASR from the generic tool center into its own page with the existing engine, model, device, storage path, dependency status, and real download/load progress controls.
- Added an Agent workspace for task configuration, reusable Skills, and MCP service registration. MCP registration validates HTTP(S) endpoints and never connects during save.
- Added AI-assisted Skill extraction from a specified public BV, using only public metadata and the currently configured model. Skill extraction never performs account actions.

## 3.1.3 dashboard and smart safety polish (2026-08-09)

- Reduced dashboard resource-card spacing so runtime metrics no longer leave artificial vertical gaps.
- Learning Live now keeps only a compact idle state while no bot video is active; subtitle timeline, recent history, and runtime log panels appear only for an active video.
- Replaced editable keyword and prompt-injection fields with one Smart Safety System switch. The server keeps its existing local rules but never returns their text through safety, injection, or general configuration APIs.

## 3.1.3 AI quota email alerts (2026-08-09)

- Added local SMTP configuration and a test-email action under the AI configuration tab. SMTP passwords are encrypted at rest and never exposed from Web APIs.
- Added cooldown-deduplicated alerts for explicit provider billing failures such as HTTP 402, insufficient balance, and quota exhaustion.
- Added an optional alert threshold for locally recorded project spend; it is labelled separately from provider balance because generic OpenAI-compatible APIs do not expose a shared balance API.

## 3.1.3 login status and icon noise fix (2026-08-09)

- Replaced unavailable brand icon names that caused repeated Lucide console warnings during page refreshes.
- Made Bilibili login presentation defensive: it now shows UID fallback and distinguishes a verified profile from locally valid credentials whose public profile cannot be refreshed.
- Replaced the silent login-status catch with a visible, actionable error state.

## 3.1.3 memory and multimodal consolidation (2026-08-09)

- Added managed permanent-memory CRUD and Bilibili contact portraits for UID, nickname, avatar, video topics, chat style, and interest types.
- Injected only relevant stored memories and contact portraits into reply context as untrusted reference data.
- Added a single multimodal master setting that synchronizes cover, comment-image, and frame-analysis compatibility keys.
- Renamed the owner-share probability control to willingness and exposed its cooldown and daily-limit policy through the existing share service.
- Verified Python compilation and authenticated Flask test-client responses for the memory, relationship, vision, and share-status APIs.

## 3.1.3 storage, export, and agent update (2026-08-09)

- Added persistent user-data location selection with optional migration and a restart-required response.
- Added detailed storage inventory and per-group safe export controls in About.
- Added one-note exports as Markdown, TXT, JSON, and locally generated PNG with optional local background/font.
- Restricted the language menu to Chinese, English, and Russian using Lucide icons.
- Cached watch-history cards by source-file modification time and cached KB archive BV lookup to reduce repeated scans.
- Added agent routing for explicit video like, favorite, coin, and pseudo-triple requests through the existing owner/review safeguards.
- Verified with `319 passed`, inline-script parse, and live `/api/health` HTTP 200.

## 3.1.3 maintenance patch (2026-08-08)

- Fixed stale Learning Live video state after the bot stops.
- Fixed refresh buttons that depended on the implicit browser `event` global.
- Fixed the mobile private-message sidebar selector and horizontal overflow guard.
- Kept library pages at a 30-item default and retained lazy/async cover rendering for large card collections.
- Re-read the knowledge-library file list after automatic cover enrichment.
- Added a message-level related-BV preference for private-message video inspection to reduce old-context mixups.
- Verification: 319 tests passed and the live web health endpoint reported version 3.1.3.

## 3.1.3 维护规则与源码备份 (2026-08-08)

- 新增源码小备份约定：备份统一放在 `F:\bililearn`，目录名使用 `bililearn_YYYY_M_D说明`。
- 每个备份目录包含 `更新内容.txt`，记录快照范围、优点、已知问题和验证结果。
- 默认排除真实配置、Cookie、Data、模型、二维码、运行日志和构建产物，避免备份泄露隐私。
- README 增加当前维护状态和备份规则；本次快照为 `F:\bililearn\bililearn_2026_8_8第一个备份`。

## 3.1.2 正式发布版 (2026-08-01)

> 本版本合入了 3.1.3 / 3.1.4 / 3.1.5 内部迭代的所有修复与发布验收内容。

### 🔧 稳定性与上下文
- 修复实时监听私信处理：网页设置的自动回复和每轮数量会实际传入监听器；AI 处理超时会跳过该条并继续轮询，B站 `-509` 会退避 10 秒。
- 主动分享、主动私信和审核后执行的私信都会写入同一份持久上下文与长期记忆；后续追问会回查最近分享的视频 BV。
- 连续短消息可合并处理。需要读取视频时，先发送与视频标题相关的进度回复，再基于可验证资料给出结论。
- 监听日志读取失败会在网页显示错误原因，不再静默留空。
- 按 bilibili-api 的 `send_comment()` 规则修正顶层评论回复：使用 `root=评论ID, parent=None`，不再错误传入相同的根评论和父评论 ID。
- 子回复继续使用 `root=根评论ID, parent=目标子回复ID`；AI 选择已不在当前评论快照中的 ID 时直接跳过。
- `12006 没有该评论` 会作为不可重试的目标失效处理，避免无意义重复发送。

### ✅ 发布验收
- 冻结 EXE 验证了人格创建、启用、编辑、删除，以及兴趣、收藏夹、日记、心情、行为设置和二维码生成。
- 监听模式在未完成 B 站登录时不再先报告启动成功后立即退出，改为直接提示先登录。
- 发布验收覆盖 54 个本地读取接口和 20 个本地写入/撤销流程。
- Windows 网页应用保留所有用户数据在 `%LOCALAPPDATA%\BiliLearn`，打包产物不包含登录 Cookie、API Key、聊天记录、知识库、二维码或 ASR 模型。
- 发布前全量测试：`309 passed`。

## 3.1.2 Windows 网页应用入口 (2026-07-11)

### 🖥️ Windows 应用
- `desktop_app.py` 改为本地 Web 控制面板启动器：启动服务后自动在默认浏览器打开 `http://127.0.0.1:8080`。
- `build_windows_exe.bat` 构建网页应用 EXE，打包界面与现有 Web 面板保持一致。
- 移除 Qt 桌面界面依赖，后续功能和视觉迭代统一在 Web 面板进行。


## 3.1.2 架构收敛与稳定性修复 (2026-07-11)

### 🔧 修复与重构
- 网页生成统一由 `services.html_renderer` 承担包装、阅读页与幻灯片导出；视频、知识辅导和深研模块不再各自维护完整 HTML 模板。
- 修复阅读页 Markdown 列表解析，避免 `-`/`*` 标记被输出到正文。
- Web 面板首次启动先创建数据目录；备份列表接口改为 `GET`；快捷配置预设写入标准 `active_preset`，并兼容历史错误字段。
- 知识辅导同步请求超过三分钟会返回明确超时状态，不再错误报告成功。
- Web Word/PDF 导出改复用 `services.document_export`；`requirements.txt` 纳入 `python-docx` 与 `reportlab`。
- Web 健康检查、部署状态和 Docker 镜像标签统一使用 `VERSION` 的 `3.1.2`；备份路径支持 `BILI_BACKUP_DIR` 并默认使用用户目录。

### 📚 文档与参考页
- 重写 README、开发索引、架构说明和服务模板，明确二次开发边界与统一网页生成入口。
- 升级网页生成提示词，新增学习摘要、深研证据链参考页面。

### ✅ 验证
- `python -m pytest -q`：53 passed。
- 全量 `compileall`、Web 首次启动和备份路径冒烟验证通过。


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

- **Web 默认端口对齐 README**：裸启动 `python3 web_panel.py` 默认使用 `7860`；Docker 通过 `WEB_PORT=8080` 保持 compose 访问 `8080`。
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

- README 更新到 `v3..2`，补充全平台视频分析、Landing 快速识别、`yt-dlp` 依赖与 Web 本地文件安全说明。
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
# 3.1.6 (2026-09-12)

- Fixed interest persistence so manual entries are never removed or replaced by AI suggestions; AI additions only run when explicitly enabled and preserve existing entries.
- Added first-use mode selection, Bilibili Cookie login, account recovery by security question/email, dashboard-first startup, protected settings visibility, and timed disclaimer confirmation.
- Improved the learning loop with multiple selectable topics, guided steps, knowledge-tree/search/learning/quiz tracking, and independent per-topic data.
- Removed the 200-model UI/API limitation, added native model selectors, and made model fetching and availability testing mutually exclusive.
- Filtered legacy free-channel bootstrap noise from the web log viewer and aligned release metadata/documentation to 3.1.6.
# 2026-10-06 智能关键帧与视觉兜底策略

- 智能视频理解改为字幕优先、ASR 次之；ASR 成功后默认不再并行消耗视觉额度，显式视觉/混合模式及画面补充配置仍可启用抽帧。
- 新增共享视觉预览管线：先检查标题/封面/简介/评论/兴趣，再分析前 60 秒；只有主题匹配或感兴趣才继续分析剩余视频。预览失败或不匹配不会触发经典全片抽帧兜底。
- FFmpeg 场景切换优选、近似帧去重；默认 5 秒候选窗口与 4×3（12 帧）拼图，支持 0.5–60 秒及 1–6 列/行配置。低于 1 秒显示额度警告，支持小数时间戳。
- 新增场景检测开关/阈值设置，视觉深入每批最多 4 张拼图，保留每阶段最大帧数预算和临时文件隔离；Web 图文笔记入口复用该策略及清理逻辑。
- 验证：462 个 pytest 测试通过；前端/内嵌 JavaScript 与 Python 语法检查通过；本地合成视频验证真实场景检测和拼图。未调用付费 AI 或真实账号下载。


## 3.1.6 AI日记分区与持久计划（2026-10-06）

- 开放数据监控 → AI日记，新增计划/来源/模型设置、生成状态和动画进度、历史搜索分页；保留补记、全文、编辑和删除，适配手机。
- 新配置默认开启自动日记，每24小时触发；旧账号已有开关/间隔保留。修复保存配置强制关闭日记的问题。
- 支持间隔/每日时间/事件阈值、星期/跨午夜时间段、五类来源、回看时长、数量/字符预算、空周期策略和失败重查；事件模式不重复计入旧来源。
- 面板独立调度和机器人/CLI共用账号SQLite锁；浏览器关闭不影响仍运行的面板服务，所有进程关闭时暂停，重启补查。
- 接入已有共享AI与多接口池，支持写作要求、模型/温度/输出/超时；默认失败不存成功日记，可自选本地摘要兜底。
- 来源隐私和额度确认，默认联系人脱敏；日记不执行B站互动。跨进程原子写入并兼容历史格式，损坏文件不静默清空。
- 隔离临时面板验证来源保存、模拟生成、进度与完成状态、搜索和390×844手机布局；Python/JS/JSON检查通过，不使用真实API或B站账号，未重打包。

## 2026-10-06
- 完善 AI 进化功能：新增默认关闭的三层进化闭环（画像审计、证据提案、审核应用、观察固化、最新版本回滚）。
- 新增进化设置、指标审计和引擎服务；支持按时间/事件触发、来源和隐私提示、预算、周期、运行时间段、目标关键词、模型参数与自定义要求。
- AI输出严格受证据ID、参数白名单、单次变化幅度和安全边界校验；不修改源码、安全配置、API凭据、账号权限、原始知识文件或外部OB配置。
- 新增 Web“数据监控 → AI进化”分区，提供任务进度、完整提案查看、审计基线、观察对比、回滚和响应式样式。
- 新增 46 项进化引擎/Web回归测试；全量测试结果为 715 passed，保留 1 条既有 Windows curl_cffi Proactor 警告。

- 2026-10-06 终验补充：统一CLI进化默认关闭，修复自动应用设置重读及提案/任务状态一致性；进化专项最终48 passed。

- 进化功能最终验收：全量718 passed，进化专项48 passed；隔离模拟AI页面完成保存、生成、审核、观察冻结、回滚全流程。未调用真实AI或触发B站互动。
- 2026-10-06：完善 Agent 分区，新增持续多轮项目助理、账号隔离对话、工具权限、用户画像、观看记录查询、视频推荐证据卡、稍后观看确认入队、联系人脱敏查询和项目功能指南。
- 2026-10-06：修复 Agent 会话级工具隔离与只读写工具拦截；自主任务写操作增加明确确认，补充工具调用超时、停止保护和单步工具数量限制。
- 2026-10-06：新增 Agent 工作台服务/API/UI 与 45 项专项测试；全量测试 750 passed，未调用真实AI或触发B站互动。

## 2026-10-07

- 新增默认关闭的“人格进化”测试功能，位于系统配置 → 人格管理；开启需要服务端强制10秒风险确认。
- 开启前自动保存账号本地原始人格快照；支持查看/下载备份、关闭附加层和恢复基础人格效果。
- 进化采用“基础提示词不变 + 审核后的表达风格附加层”，AI 只生成白名单风格建议，不改变身份、主人关系、长期偏好、硬性规则或安全边界。
- 新增人格实验后端、API、响应式 UI 和专项测试；49 项人格实验/人格 API 回归测试通过，全量795 passed（1条既有Windows curl_cffi警告）。隔离模拟AI面板完成开启、备份、生成、审核应用、关闭停用及恢复基础效果实测；未调用真实AI或操作B站账号，未重新打包EXE。

## SQLite、安全默认与视频输入更新

- 新增账号级 `account_data.sqlite3`、JSON事务迁移、原始字节快照、WAL跨进程写锁、记录版本、数据库检查与确认下载；Data及账号根目录旧记忆/索引共用同一数据库，保留旧JSON兼容镜像和已有专用SQLite。
- 统一配置、通用存储、模块化运行时、人格、上下文、主要历史/日志及Cookie保存等路径；损坏JSON不被默认值覆盖，整批迁移失败回滚，删除Cookie不自动复活。
- 安全缺省全部开启，补充英文/Unicode注入检测、统一回复泄露审查，以及知识写入/导出/邮件审核默认开启；保留用户已明确关闭的设置。
- API设置新增默认关闭的原视频投喂；需要具体视频模型与兼容能力确认，支持大小/时长/超时/输出预算和有条件关键帧回退。视频直传不进入普通轮询、不重试或跟随重定向，不改变字幕/ASR优先。
- 新增“配置编辑 → 数据与数据库”和AI接入内的视频设置卡片，提供敏感数据库下载警告与视频上传费用确认。
- 验证：全量864 passed（1条既有Windows curl_cffi警告），Python/JS/HTML脚本/JSON检查通过；隔离面板保存与迁移流程、桌面和手机布局已检查。未调用真实AI或操作B站账号，未重新打包EXE。

## Token 可观测仪表盘（需求16）
- 新增独立“总览 → Token 仪表盘”和 `/#tokens` 入口，包含8张指标卡、趋势/模型/来源/服务商图表、24小时热力图、月预算进度与明细分页。
- 日期区间、含结束整日、时区/夏令时、模型/域名/来源/结果筛选、自动刷新、完整筛选CSV导出、人民币模型单价、月Token提醒预算与确认式历史清理均可设置。
- 接入主要实际AI请求路径，包括接口池重试、工具循环、视频直传/HTML、大脑、聊天/图片/Embedding、待机、MCP文案和模型测试；读取真实usage，缺失标记未知，缓存/推理不重复累计，不伪造历史Token或账单费用。
- 新增账号隔离的Token SQLite数据库；不记录提示词/正文/凭据/完整URL，遥测失败不打断AI。测试默认目录隔离，tzdata随源码依赖及冻结配置携带。
- 验证：895 passed（1条既有curl_cffi警告），13个Python文件、外置JS和5段面板脚本检查通过；隔离浏览器验证筛选、分页、预算、空数据、错误与390×844移动布局。未产生真实AI费用、未操作B站账号、未重新打包EXE。

## 可靠学习、向量RAG、配置插件与图片导出（需求17–21）

- 兴趣引擎改为SQLite事务三方增量合并，修复旧快照覆盖手工内容和已删除兴趣复活；统一旧兴趣适配器，Unicode去重，自动条目总量/每批建议上限可设置，自动兴趣默认关闭。
- 新增「学习与图片导出」分区，提供账号独立背景上传、尺寸/字号/阅读面板设置、本地PNG分页图片包；CLI 0号导出及知识笔记导出复用同一排版器，多页下载正确使用ZIP扩展名。
- Pydantic v2配置类型/范围校验，不修改调用方敏感词、不覆盖损坏配置；新增可信模型插件注册接口，接入共享服务/主脑/工具/API池/ModelClient聊天；CI配置Python3.11/3.13全量测试与coverage.xml上传。
- RAG持久化分块向量索引与重排，支持已有本地嵌入/CrossEncoder模型，缺模型时明确词法降级；辅导和问答按相关片段与字符预算注入，选定文件范围和来源追踪生效。
- 字幕有限多次获取并比较覆盖度、语义优先选取候选；各轨不匹配切换已安装的本地Whisper，尊重强制观看模式，禁止回退自动下载大模型，缺依赖/权重时明确反馈。
- 验证：915 passed；新增20项回归通过；core/api/services统计覆盖率52%，覆盖率运行有69条历史资源/事件循环警告，已记录AGNET.md。语法、配置、PNG视觉检查及隔离浏览器桌面/手机/亮暗主题检查通过；未实际运行远端CI、未下载/实跑语义模型或Whisper、未调用付费AI或B站动作、未重新打包EXE。

## 需求22–24、26：统一开关、AI API 权限与平台收藏管理（2026-10-07）

- 新增独立“AI API 权限”分区：平台总授权默认关闭，风险平台动作默认关闭；平台写权限按账号保存并在执行时实时复核。
- 统一点赞、投币、收藏、关注、评论、私信、弹幕、动态、稍后再看及收藏夹增删改移清理等 API 权限；未知 B站写请求默认阻断，保留登录、历史上报等必要运行请求。
- 平台收藏夹操作新增严格参数校验、人工审核队列和账号切换保护；支持读取收藏夹、创建/修改/删除收藏夹、视频收藏/移除、复制/移动及清理失效内容。
- 收藏目标统一为项目内收藏夹或 B站平台收藏夹，默认项目内；AI 收藏意图只执行一个目标，项目收藏使用 SQLite 兼容事务存储并去重。
- 清理功能开关中的重复平台动作开关；`enable_asr` 迁移至 `asr.enabled`，新增默认开启的 `subtitles.enabled`，避免多个分区出现不一致状态。
- Agent 新增本地收藏、平台收藏夹只读查询与受审核的平台收藏夹管理工具；前端新增风险提示、操作字段动态显示、暗色主题和移动端响应式样式。
- 新增权限与收藏测试，最终验证覆盖配置校验、后端授权边界、审核撤销、SDK 请求分类、页面保存回读、亮暗主题和 390px 视口。
- 本轮验证不使用真实付费 AI，不执行真实 B站账号写操作；保留的旧警告主要为 SQLite 连接未关闭和 Windows `curl_cffi` 事件循环警告。
- 最终验证：1003 passed；core/api/services 覆盖率 53%，平台收藏夹操作 95%、完整平台管理操作 92%；权限与操作定向测试 88 passed，视频理解及字幕组合定向回归 128 passed。覆盖率运行保留 69 条历史资源/事件循环警告。
- 新增受人工审核约束的完整平台管理工具，覆盖取消点赞、评论删除/点赞、弹幕点赞、动态删除/点赞/转发等；后台拒绝未授权操作及伪造确认字段，平台返回错误不再记录为成功。
- 字幕语义不匹配的 Whisper 回退改为尊重当前 ASR 总开关及实时引擎配置，关闭 ASR 时不下载视频用于识别。
- 最终普通全量回归同样为 1003 passed、1 条既有 Windows curl_cffi 警告；示例配置、Python/JS/spec 校验通过，隔离测试面板已停止。
## 2026-10-07 — 全站可用性重构

- 移除主要使用方式选择，统一默认为学习 + 陪伴；旧配置、旧客户端和旧学习目标兼容归一化。
- 新增全站新手指南和每个分区的使用帮助、示例、前提与风险说明；关于项目、技能库、深度搜索、配置编辑、账号管理等重点页面完成结构与视觉优化。
- 重写学习闭环为目标 → 知识点 → 候选视频 → 记录与复习工作流；候选可进入持久化稍后观看队列。
- 优化视频复习分组、工作日选择和预设；自动复习继续默认关闭。
- 账号管理改为卡片式独立工作区，支持最多 10 个账号的独立端口、配置、数据和页内确认。
- 修复机器人、监听、审核日志清理不彻底及旧请求回填问题；日志改用完整日期并逐行渲染。
- 完成 53 个功能分区的桌面浏览器巡检；账号、技能和复习等重点页追加 `390×844` 移动检查。最终全量 `1025 passed`、1 条既有 Windows 事件循环警告。
- 浏览器实测新手指南搜索、示例填充、本地学习目标创建、复习预设和日志清理；未调用付费 AI 或执行真实 B站写操作。


## 3.1.6 HTML 统一采用项目介绍页布局（2026-10-07）

- 用户指定 `project_intro.html` 为唯一视觉基准，不再使用预览页原有的宽屏固定高度卡片与品牌顶栏。公共 `reference.css` 使用介绍页的基础变量、字号层级、卡片、标签、表格、阴影、圆形按钮、暖橙进度和入场动画；桌面卡片为 80vw / 最大 960px、自适应高度，长内容可在卡片内滚动。
- `video_html_preview.html`、视频正式导出、深入学习报告/幻灯片、通用文档 HTML、知识辅导网页及其错误页面、思维导图导出均复用 `templates/video_export/` 公共框架。参考介绍页本身、管理面板和开发用示例不被内容导出模板覆盖；已保存的用户历史 HTML 不强制重写，重新导出可应用新样式。
- 页顶只保留目录与亮暗模式圆形按钮，下载/打印移到目录抽屉，底部提供翻页、连续阅读、自动播放与全屏。保留键盘、触摸、打印样式和减少动画偏好；手机页码避免换行。阅读滚动同步当前章节，下载恢复时保留当前页并清理临时 inert 状态，目录打开时禁止背景焦点访问。
- 视频、报告等正式导出内联 CSS、JS 和图标；仓库预览使用旁边的本地图标资源。思维导图继续保留 Markmap 拖拽/缩放/折叠功能，本地资源齐全时内联加载，节点连接采用统一暖橙；Markdown 的脚本数据转义避免 `</script>` 提前闭合。
- 修复 `_load_examples_info` 将描述文字拼成文件路径导致参考提示为空的问题；修复通用幻灯片渲染丢失调用者指定文档标题的问题。
- 新增回归覆盖模板/预览资产一致性、布局基准、真实参考路径、标题保留与导图安全数据。定向 30 项通过；全量 `1029 passed, 1 warning`（102.24 秒），警告为既有 Windows curl_cffi Proactor 提示；Python 编译与运行时 JS 语法检查通过。
- 浏览器实际检查介绍页、预览、报告和导图；验证 1280px 桌面与 390×844 手机、目录跳转、亮暗切换、翻页、连续阅读、进度 75% 和无横向溢出。静态校验确认正式导出无远程 script/link 依赖（本地资源齐全的当前环境）。Browser 安全策略阻止 file:// 导航，因此未宣称完成离线浏览器实测；下载、打印系统弹窗与真实付费模型/B站写操作未执行。审美检查样例位于 `build/html-style-qa/`，临时 HTTP 服务在完成后停止。

## 2026-10-07 配置与分区视觉体验修复

- 优化学习与图片导出、AI API 权限分区的层级、卡片、说明和响应式布局。
- 修复配置编辑模型操作按钮的共享高亮、嵌套标签和模型列表兼容性问题；新增手动模型输入、当前模型优先与测试成本确认。
- 修复核心体验/自动化与路径分组显示，规范人格进化配色，并修复兴趣偏好滑块为 0 时仍显示轨道进度。
- 全量测试：`1036 passed, 1 warning`。

## 2026-10-07 恢复出厂与 Agent 工作台体验完善

- 恢复出厂增加完整清理范围预览、全选/全不选、备份保留策略、二次令牌校验、运行任务阻止和路径安全检查。
- 我的分区新增项目数据目录显示、打开文件夹和复制路径。
- Agent 工作台支持 Enter 发送、Shift+Enter 换行；首次发送按当前权限/模型确认，支持撤销授权且保留取消后的消息草稿。
- 新增恢复出厂与 Agent 专项回归覆盖；最终全量测试 `1055 passed, 1 warning`（105.82 秒）。

## 2026-10-07 图片导出水印修复

- 图片导出左上角水印统一为 `BILIBILI_LEARNING_BOT`，替换旧的 `BILIBILI / LEARNING NOTES` 文案；不更改已有用户图片，重新导出后生效。
- 新增水印回归校验，学习升级相关测试 `21 passed`，Python 编译通过。
