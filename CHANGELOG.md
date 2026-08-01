# 更新日志

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

### 🔧 Bug 修复 (3.0.0 后续补丁)

- **字幕获取 player/wbi/v2 412 风控修复**：B站 `player/wbi/v2` 带 cookie 请求可能返回 412，快速 fallback 到 `player/v2` 获取 AI 字幕
- **V 命令字幕检测修复**：搜索结果字幕检测改为 `player/wbi/v2` + WBI 签名，正确识别 AI 字幕（`lan:ai-zh`）
- **Cookie 扫描增强**：V 命令自动扫描多个兄弟项目目录加载登录 cookie
- **未登录字幕提示**：未登录时明确提示「部分视频需登录账号获取 AI 字幕」
- **W 命令保存路径**：默认保存改为项目根目录 `web/` 文件夹

### ⚠️ 注意事项

- 监听模式与机器人主进程互斥
- 配置文件格式有变动，请参考 `config.example.json`
