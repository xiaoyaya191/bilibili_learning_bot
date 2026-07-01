# bilibili_learning_bot

> **B站 AI 学习互动机器人** — 自动刷视频、学知识、评论互动、自我进化  
> 版本: 3.0.0 | License: MIT  
> 更新日志: [CHANGELOG.md](CHANGELOG.md)

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 📺 **智能视频浏览** | AI 驱动的 B站推荐流浏览，自动判断内容价值（评分/收藏/投币） |
| 📚 **知识库系统** | 自动归档高质量视频内容，支持3层分类 + 向量语义检索 |
| 💬 **评论互动** | 真实评论/模拟评论模式，AI 自动生成有深度回复，支持图片分析 |
| 📩 **私信处理** | 自动回复粉丝私信，保持上下文记忆，支持节奏控制 |
| 📡 **实时监听** | 独立消息监听模式，只盯私信+评论实时 AI 回复，不刷视频不耗精力 |
| 🔔 **@通知响应** | 在任何视频下评论 "@bot 总结这个视频"，自动识别并总结回复 |
| 🧬 **日记与自我进化** | 记录行为日志，AI 自我反思，人格动态进化 |
| 🎙️ **ASR语音识别** | 视频语音转文字（FunASR / Whisper，需本地模型） |
| 🤖 **Agent技能系统** | 自主规划目标→搜索 B站→看视频→总结知识，全自动闭环 |
| 🔄 **复习回顾** | 定时重温已学知识，优化记忆 |
| 🎓 **知识辅导** | AI 讲解/问答/二次创作/生成 HTML 学习卡片 |
| 🎨 **视频→网页** | 将已学视频生成精美 PPT 风格 HTML 网页，支持 Claude 设计主题 |
| 🌐 **网页讲解** | 输入 URL，AI 读网页/总结/讲解 |
| 📝 **自定义知识管理** | 手动增删改查知识条目 + AI 搜索 B站自动整理入库 |
| 😊 **AI心情系统** | 动态心情影响互动风格，支持自定义 |
| 🛡️ **安全审查** | 关键词过滤 + 政治敏感拦截 + 提示词注入防护 |
| 🔄 **备用API降级** | 主 API 连续失败自动切换到备用提供商，10分钟后自动恢复 |
| 📤 **隐私导出** | 一键导出配置（API Key/Cookie 脱敏保护） |
| 🐳 **Docker 部署** | 支持 Docker / docker-compose 一键部署 |

## 🧱 项目结构

```
├── main.py               # 主入口
├── start_cli.py          # 兼容转发
├── web_panel.py          # 🌐 Flask Web 管理面板
│
├── api/                  # 🔌 B站 API 层
│   ├── client.py         # B站客户端
│   ├── auth.py           # 登录认证
│   ├── subtitles.py      # 字幕获取与校验
│   ├── throttle.py       # 请求节流器
│   └── compat.py         # 兼容层
│
├── brain/                # 🧠 核心大脑
│   ├── agent_brain.py    # 主调度器 AgentBrain
│   ├── comment.py        # 评论互动
│   ├── private_msg.py    # 私信处理
│   ├── video_analysis.py # 视频分析
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
│   └── app.py            # 菜单 + 配置
│
├── core/                 # ⚙️ 配置
│   └── config.py         # 配置加载/保存
│
├── services/             # 🔧 服务模块
│   ├── agent_service.py  # Agent 技能执行
│   ├── knowledge_tutor.py # 知识辅导
│   ├── video_to_ppt.py   # 视频→HTML网页
│   └── utils.py          # 工具/兴趣管理
│
├── xingye_bot/           # 🤖 扩展组件
│   ├── llm.py            # LLM 客户端
│   ├── state.py          # 状态管理
│   ├── memory.py         # 语义记忆
│   ├── safety.py         # 安全过滤
│   ├── diary.py          # 日记系统
│   ├── evolution.py      # 自我进化
│   ├── skills.py         # Agent 技能
│   ├── asr_engine.py     # 语音识别
│   ├── video_modes.py    # 视频理解
│   ├── kb_search.py      # 向量检索
│   └── bilibili_ops.py   # B站操作
│
├── utils/                # 🛠 通用工具
│   ├── helpers.py        # 工具函数
│   ├── storage.py        # JSON 线程安全存储 + 脱敏
│   ├── display.py        # 日志显示
│   └── lock.py           # 单实例锁
│
├── templates/            # 🎨 设计模板
│   └── claude/           # Claude 设计系统
│       ├── prompts/      # AI 设计规范
│       └── examples/     # 6 个参考页面
│
├── Data/                 # 💾 运行时数据（自动生成）
├── KnowledgeBase/        # 📖 知识库目录
└── tests/                # 🧪 测试
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
```

### 2️⃣ 配置

```bash
cp config.example.json Data/config.json
# 编辑 Data/config.json 填入你的 API Key（统一API或OpenAI兼容接口）
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
3. 按 `V` 手动分析特定视频
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
| `N` | 📝 自定义知识管理 |
| `R` | 🔄 恢复出厂设置 |
| `S` | 🛡️ 关键词审查开关 |
| `E` | 📤 导出配置（脱敏） |
| `I` | 📥 导入配置 |
| `O` | 📂 一键整理知识库 |

## 🎨 Claude 设计主题

项目内置 [Claude Design System](templates/claude/) — 一个让你的网页像 Claude 官网一样优雅的设计系统。

**在视频→网页功能中使用**：Web 面板选择 "Claude" 主题，生成的视频总结页自动应用 Claude 风格：
- Fraunces + Inter 字体组合
- 暖灰背景 + 紫粉渐变标题
- 毛玻璃卡片 + 数字滚动动画
- Font Awesome 图标，无 emoji

**模板文件**：`templates/claude/examples/` 下有 6 个参考页面（落地页、仪表盘、定价页、博客、FAQ、登录页），可直接浏览器打开。

**独立开源项目**：[github.com/yourname/claude-design-system](https://github.com/yourname/claude-design-system)

## 🔒 隐私安全

- API Key 在菜单显示和导出时自动脱敏（`mask_secret` / `sanitize_config_for_export`）
- 一键恢复出厂设置（`R`）清除所有配置/登录/日志/知识库
- 导出备份自动隐藏敏感字段（API Key、Cookie Token等替换为 `[已隐藏]`）
- 所有配置文件和 Cookie 仅本地存储，不上传到任何服务器

## ⚠️ 免责声明

本项目仅供学习参考。使用本项目请遵守 B站用户协议，若因使用本项目产生任何后果，本人概不负责。

## 📄 License

MIT © XingYe contributors

---

📋 **更新日志**: [CHANGELOG.md](CHANGELOG.md) | 🔧 **重构记录**: [REFACTOR_PLAN.md](REFACTOR_PLAN.md)
