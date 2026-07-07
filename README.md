# bilibili_learning_bot

> **B站 AI 学习互动机器人** — 自动刷视频、学知识、评论互动、自我进化  
> 版本: 3.0.2 | License: MIT  
> 项目介绍以及使用文档: https://bot1.bxya.top/

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 📺 **B站视频分析（视觉抽帧）** | 聚焦 B站：统一识别（BV号 / 链接 / b23.tv 短链）、字幕/简介读取、ASR 与视觉抽帧（关键帧 AI 画面分析）；下载支持**画质选择**，默认 `best`=自动最高画质。 |
| 🧪 **Landing 快速识别** | 文档站首页支持平台选择、视频链接输入与 `/api/analyze` 轻量识别 |
| 📺 **智能视频浏览** | AI 驱动的 B站推荐流浏览，自动判断内容价值（评分/收藏/投币） |
| 📚 **知识库系统** | 自动归档高质量视频内容，支持3层分类 + 向量语义检索 |
| 🔒 **章节锁定 + 内容追加** | 长视频分章节稳定归档，重复学习时只追加新增信息，尽量减少“重新总结导致旧信息丢失” |
| 🧭 **思维导图导出** | 支持单篇/批量将知识库 Markdown 导出为 markmap HTML，方便复习和分享 |
| 💬 **评论互动** | 真实评论/模拟评论模式，AI 深度回复，支持图片分析 |
| 📩 **私信处理** | 自动回复粉丝私信，保持上下文记忆，支持节奏控制 |
| 📡 **实时监听** | 独立消息监听，只盯私信+评论实时 AI 回复，不刷视频不耗精力 |
| 🔔 **@通知响应** | 在任何视频下评论 "@bot 总结这个视频"，自动识别并总结回复 |
| 🧬 **日记与自我进化** | 记录行为日志，AI 自我反思，人格动态进化 |
| 🎙️ **ASR语音识别** | 视频语音转文字（FunASR / Whisper，可选） |
| 🤖 **Agent技能系统** | 自主规划目标→搜索 B站→看视频→总结知识，全自动闭环 |
| 🔄 **复习回顾** | 定时重温已学知识，优化记忆 |
| 🎓 **知识辅导** | AI 讲解/问答/二次创作/生成 HTML 学习卡片 |
| 🎨 **视频→网页** | 视频生成精美 PPT 风格 HTML，19种视觉风格可选，支持 Claude 主题 |
| 🎯 **智能兴趣引擎** | 多维度评分+同义词+排除词+灵光一闪探索+PsychoProfile同步+AI建议 |
| 🌐 **网页讲解** | 输入 URL，AI 读网页/总结/讲解 |
| 📝 **自定义知识管理** | 增删改查知识条目 + AI 搜索 B站自动整理入库 |
| 😊 **AI心情系统** | 动态心情影响互动风格，支持自定义 |
| 🛡️ **安全审查** | 关键词过滤 + 政治敏感拦截 + 提示词注入防护 |
| 🔄 **备用API降级** | 主 API 连续失败自动切换备用提供商 |
| 📤 **隐私导出** | 一键导出配置（API Key/Cookie 脱敏保护） |
| 🌓 **Web面板暗色模式** | Claude 设计风格 + 亮/暗双主题切换 |
| 🐳 **Docker 部署** | 支持 Docker / docker-compose 一键部署 |

## 🧱 项目结构

```
├── main.py               # 主入口
├── start_cli.py          # 兼容转发
├── web_panel.py          # 🌐 Flask Web 管理面板
├── web_panel.html        # Web面板模板 (Claude设计风格+亮暗双模式)
│
├── api/                  # 🔌 B站 API 层
│   ├── client.py         # B站客户端
│   ├── auth.py           # 登录认证
│   ├── subtitles.py      # 字幕获取与校验（含412风控fallback）
│   ├── throttle.py       # 请求节流器
│   └── compat.py         # 兼容层
│
├── brain/                # 🧠 核心大脑（Mixin 组合模式）
│   ├── agent_brain.py    # 主调度器（55行，13个 mixin 组合）
│   ├── _mixin_imports.py # 统一导入
│   ├── _brain_init.py    # 初始化
│   ├── _brain_loop.py    # 主循环 (~905行)
│   ├── _brain_video.py   # 视频理解 (~621行)
│   ├── _brain_session.py # 会话管理 (~640行)
│   ├── _brain_ai.py      # AI 调用后端
│   ├── _brain_learn.py   # 学习归档
│   ├── _brain_curiosity.py # 好奇心搜索
│   ├── _brain_auto.py    # 自动日记/进化
│   ├── _brain_journal.py # 日记/学习日志
│   ├── _brain_history.py # 视频历史
│   ├── _brain_ups.py     # UP主管理
│   ├── _brain_runtime.py # 运行时时钟
│   ├── _brain_interact.py # 视觉分析+互动
│   ├── comment.py        # 评论互动
│   ├── private_msg.py    # 私信处理
│   ├── video_analysis.py # 视频分析 (V命令)
│   ├── standby.py        # 待机监听（@通知响应）
│   └── monitor.py        # 实时监听引擎
│
├── knowledge/            # 📚 知识库
│   ├── classifier.py     # 智能分类
│   ├── web_search.py     # 搜索 + AI 验证
│   ├── browse.py         # 浏览整理
│   ├── revisit.py        # 知识重温
│   ├── organize.py       # 一键整理
│   └── custom.py         # 自定义知识
│
├── persona/              # 🎭 人格 + 心理
│   ├── managers.py       # 人格/心情/日记管理
│   └── psycho.py         # 心理画像引擎
│
├── security/             # 🛡️ 安全与隐私
│   └── guard.py          # 内容审查
│
├── cli/                  # 💻 命令行界面
│   └── app.py            # 菜单 + 配置 + V/W/P命令
│
├── core/                 # ⚙️ 配置 + 全局变量
│   ├── config.py         # 配置加载/保存 + __getattr__ 动态属性
│   └── globals.py        # 全局变量（动态从 config 读取）
│
├── services/             # 🔧 服务模块
│   ├── agent_service.py  # Agent 技能执行
│   ├── knowledge_tutor.py # 知识辅导
│   ├── video_to_ppt.py   # 视频→HTML网页（19种风格）
│   ├── platform_adapter.py # B站视频输入识别与归一化（BV号 / 链接 / b23.tv 短链）
│   ├── interest_engine.py # 🎯 智能兴趣引擎 v2.0
│   └── utils.py          # 工具/兴趣管理
│
├── xingye_bot/           # 🤖 扩展组件
│   ├── llm.py, state.py, memory.py, safety.py
│   ├── diary.py, evolution.py, skills.py
│   ├── asr_engine.py, video_modes.py
│   ├── kb_search.py, bilibili_ops.py
│   └── settings.py
│
├── utils/                # 🛠 通用工具
│   ├── helpers.py        # 工具函数
│   ├── storage.py        # JSON 线程安全存储 + 脱敏
│   ├── display.py        # 日志显示
│   └── lock.py           # 单实例锁
│
├── templates/            # 🎨 设计模板
│   └── claude/           # Claude 设计系统
│       ├── prompts/      # AI 设计规范（v1.0）
│       └── examples/     # 7 个参考页面
│
├── Data/                 # 💾 运行时数据（自动生成）
├── KnowledgeBase/        # 📖 知识库目录
├── web/                  # HTML 导出目录
└── tests/                # 🧪 pytest 测试套件
```

## 🚀 快速开始

### 1️⃣ 安装依赖

> ⚠️ **重要提示 / 致歉声明**  
> 之前 `requirements.txt` 里 B站 API 写的是 `>=16.0.0`，但之前有用户反馈安装了旧包 `bilibili-api`（最高 v9.1，缺失很多模块）。  
> 正确的包名是 **`bilibili-api-python`**，现已修复为 `>=17.4.1`。  
> **给大家带来困扰，非常抱歉！** 🙇

```bash
pip install -r requirements.txt

# 如果之前装过旧包，先卸载：
# pip uninstall bilibili-api -y

# 推荐安装 ffmpeg（视频帧提取）
# apt install ffmpeg    # Linux
# pkg install ffmpeg    # Termux

# 可选安装 yt-dlp（历史用于非 B站平台；多平台支持已移除，通常无需安装）
# pip install yt-dlp
```

### 2️⃣ 配置

```bash
cp config.example.json Data/config.json
# 编辑 Data/config.json 填入你的 API Key（统一API或OpenAI兼容接口）
# Web 面板默认禁止分析本地文件路径；确需开启时设置 platform_adapter.allow_web_local_files=true
```

### 3️⃣ 启动

**交互式菜单**:
```bash
python3 main.py
```

**Web管理面板**:
```bash
python3 web_panel.py
# 访问 http://localhost:7860
# 包含: 仪表盘 / 机器人控制 / 实时监听 / 配置编辑 / 知识辅导 等页面
```

**Docker 部署**:
```bash
docker-compose up -d
# 访问 http://localhost:8080
```

**Termux (Android) 一键启动**:
```bash
bash start.sh
```

### 4️⃣ 首次使用

1. 进入菜单后按 `3` 配置 B站登录（扫码或 Cookie）
2. 按 `1` 启动机器人自动刷视频
3. 按 `V` 手动分析特定视频（BV号 / B站链接 / 视频标题 / UP主名）
4. 按 `W` 将已学视频生成 HTML 网页
5. 按 `N` 管理自定义知识

## 📋 主菜单功能速览

| 按键 | 功能 |
|------|------|
| `1` | 🚀 启动机器人 |
| `2` | ⚙️ 配置AI参数 |
| `3` | 🔑 配置登录 |
| `4` | 📚 管理知识库 |
| `5` | 🎯 管理兴趣爱好 |
| `6` | 💬 评论互动设置 |
| `7` | 📩 私信设置 |
| `8` | 🧬 日记/自我进化 |
| `9` | 🛠️ Agent技能 |
| `L` | 📡 实时监听（不刷视频，只盯私信+评论） |
| `F` | 👤 UP主关注/弹幕设置 |
| `G` | 🎙️ ASR语音识别设置 |
| `M` | 😊 AI心情管理 |
| `D` | 🏆 干货归档 |
| `V` | 📹 手动视频分析 |
| `K` | 🔄 知识库重温 |
| `T` | 🎓 知识辅导 |
| `W` | 🎨 视频→网页（PPT风格HTML，支持Claude主题） |
| `P` | 🎯 兴趣偏好设置（智能引擎 v2.0：多维度评分/同义词/排除词/PsychoProfile同步） |
| `N` | 📝 自定义知识管理 |
| `R` | 🔄 恢复出厂设置（一键清空所有隐私数据） |
| `S` | 🛡️ 关键词审查开关 |
| `E` | 📤 导出配置（脱敏） |
| `I` | 📥 导入配置 |
| `O` | 📂 一键整理知识库 |

## 🎨 Claude 设计主题

项目内置 Claude 设计系统 — 纯白暖橙极简风格，让 HTML 输出像专业网页一样优雅。

**Web 面板**：自动应用 Claude 风格，含亮/暗双模式切换。

**在视频→网页功能中使用**：选择 "Claude Slides" 风格（推荐），生成 HTML 自动应用：
- Inter 字体（100-800 字重）
- Lucide 图标系统（无 emoji，无 Font Awesome）
- 黑底白字按钮 + 14px 卡片圆角 + 标题字重 200
- 暖橙 `#D97757` 强调色 + 纯白/纯黑双主题
- 翻页动画 + 进度条 + 暗色模式切换

**19 种视觉风格**：Claude Slides / Bento 网格 / 玻璃拟态 / 极光渐变 / 新野蛮主义 / 深色OLED / 赛博朋克 / 新拟态 / 液态玻璃 / 复古主义 / Linear / 新变风 / 柔和流行 / PromptPort ...

**模板文件**：`templates/claude/examples/` 下有 7 个参考页面，可直接浏览器打开。

## 🎯 为什么适合长视频学习

普通视频总结经常会把长视频压缩成一段摘要，二次学习时还可能覆盖掉旧笔记。`bilibili_learning_bot` 的策略是：

- **章节锁定**：按章节/主题固定内容边界，降低长视频总结跑偏概率。
- **内容追加**：重温同一视频时优先追加新增弹幕、评论、补充理解，而不是简单覆盖原文。
- **零信息丢失导向**：尽量保留关键定义、论证过程、例子、结论和可执行步骤，让知识库更像长期笔记而不是一次性摘要。
- **复习友好**：Markdown、HTML 学习卡片、markmap 思维导图可以互相配合，适合回看、检索和二次创作。

## ❓ 常见问题

### 这个项目和普通 B站总结工具有什么区别？

它不只是“输入一个链接然后总结”。它可以自动浏览推荐流、判断内容价值、收藏投币、评论互动、归档知识，并通过 @通知、Web 面板和 CLI 多入口持续学习。

### 长视频会不会漏掉后半段内容？

项目已接入“章节锁定 + 内容追加”策略：长视频会尽量按章节组织内容，后续重温时追加新增信息，目标是减少信息覆盖和遗漏。

### 支持哪些输入？

支持 B站 BV号/链接（含 b23.tv 短链）。

### 知识库能做什么？

可以自动三层分类归档、搜索、预览、AI 讲解、问答、改写、生成 HTML 学习卡片，并支持单篇/批量导出思维导图。

## 🔒 隐私安全

- API Key 在菜单显示和导出时自动脱敏（`mask_secret` / `sanitize_config_for_export`）
- 一键恢复出厂设置（`R` → `YES`）清空全部隐私数据：配置/登录/状态/日志/记忆/心理画像/网页面板/知识库/导出/备份/加密密钥
- 导出备份自动隐藏敏感字段（API Key、Cookie Token等替换为 `[已隐藏]`）
- 所有配置文件和 Cookie 仅本地存储，不上传到任何服务器

## ⚠️ 免责声明

本项目仅供学习参考。使用本项目请遵守 B站用户协议，若因使用本项目产生任何后果，本人概不负责。

## 📄 License

MIT © XingYe contributors

---

📋 **更新日志**: [CHANGELOG.md](CHANGELOG.md) | 🔧 **重构记录**: [REFACTOR_PLAN.md](REFACTOR_PLAN.md)
