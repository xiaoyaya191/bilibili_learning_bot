# bilibili_learning_bot
一个让你的AI全面接管你的B站的项目


# 📚 bilibili_learning_bot

> ⚠️ **免责声明：仅供学习参考！**
>
> 本项目仅供学习交流使用，请勿用于任何商业用途或违反平台规定的行为。使用者需自行承担一切风险与法律责任。

---

## 📖 项目简介

`bilibili_learning_bot` 是一个**全自动 B 站 AI 学习互动机器人**。它可以：

- 🤖 **自动浏览推荐流**，像真人一样看视频、理解内容
- 💬 **智能评论互动**：读取热门评论，AI 生成回复，分析评论图片
- 📩 **私信自动回复**：管理私信上下文，AI 生成个性化回复
- 🎬 **深度视频理解**：四种模式（纯文本/抽帧视觉/混合/智能），结合 ASR 语音识别
- 🎭 **弹幕互动**：读取弹幕池、AI 生成弹幕、点赞有趣弹幕
- 🧠 **心理画像引擎**：五层深度分析，主动内容推荐，防信息茧房
- 📚 **个人知识库**：自动分类归档学习内容，支持回顾复习
- 📓 **日记与自我进化**：AI 写日记，定期自我反思与人格优化
- 🔒 **内容安全过滤**：敏感词/政治内容自动拦截
- 🌐 **Web 管理控制台**：可视化操作所有功能（启停、配置、心情、数据浏览等）
- ✏️ **完全可自定义**：通过提示词自由设置机器人名字、人格、回复风格

**核心理念**：让 AI 替你"刷 B 站"，从推荐流中学习知识、积累记忆、自我成长，而非沉溺于低质内容。

---

## 🏗️ 项目架构

```
bilibili_learning_bot/
│
├── new_agent.py        🔴 主程序 (~13800行) — 所有核心逻辑
├── psycho_engine.py     🟠 心理画像引擎 — 五层智能分析
├── web_panel.py         🟡 Web 控制台后端 (Flask)
├── web_panel.html       🟡 Web 控制台前端页面
├── asr_engine.py        🟢 语音识别引擎 (FunASR/Whisper)
│
├── bot_modules/         🔵 模块化子包 (17个模块)
│   ├── llm.py           → 多模型 OpenAI 兼容客户端
│   ├── state.py         → 运行时状态管理
│   ├── settings.py      → 配置加载器
│   ├── memory.py        → 语义记忆库
│   ├── video_modes.py   → 四种视频理解模式
│   ├── video_asr.py     → 视频 ASR
│   ├── bilibili_ops.py  → B站操作封装
│   ├── skills.py        → 技能管理
│   ├── diary.py         → 日记管理
│   ├── evolution.py     → 自我进化引擎
│   ├── safety.py        → 内容安全守护
│   ├── owner.py         → 主人识别
│   ├── proactive.py     → 主动规划
│   ├── background.py    → 后台服务
│   ├── web_search.py    → 联网搜索
│   └── __init__.py      → 包定义
│
├── Data/                📁 运行时数据
├── KnowledgeBase/       📚 个人知识库
├── 干货/                ⭐ 精品内容收藏
│
├── config.example.json  📝 示例配置
├── requirements.txt     📦 核心依赖
├── 启动网页版.bat        🚀 一键启动
└── README.md            📄 本文件
```

---

## ✏️ 自定义机器人名称与人格

### 配置方式

在 `Data/config.json` 中配置 `persona` 字段即可自定义一切：

```json
{
  "persona": {
    "active_persona": "学习助手",
    "prompt_name": "我的AI学习伙伴",
    "bot_name": "你想起的名字",
    "user_name": "主人",
    "custom_prompt": "你的自定义提示词……可以完全重塑机器人的说话风格、知识领域和行为模式。"
  }
}
```

### 人格模板系统

支持多个人格模板，可随时切换：

```json
{
  "persona_templates": {
    "学习助手": {
      "name": "小B",
      "greeting": "你好呀！我是小B，你的专属学习伙伴~",
      "style": "热情、专业、鼓励型",
      "system_prompt": "你是一个热情专业的学习助手..."
    },
    "评论员": {
      "name": "B站观察员",
      "greeting": "大家好，我是B站观察员~",
      "style": "客观、幽默、犀利",
      "system_prompt": "你是一个B站资深用户..."
    }
  }
}
```

**名字完全自由**：修改 `persona.prompt_name` 和 `persona.bot_name` 即可，不需要改任何代码。

---

## 🎯 完整功能 (按模块)

### 1. 推荐流自动浏览（主循环）

系统启动后进入主循环，模拟真人浏览推荐视频：

```
┌─────────────────────────────────────────────────┐
│  启动 → 登录 → 初始化 → 进入主循环              │
│                                                  │
│  for 每个精力周期 (round):                       │
│    ├── for 每个视频:                             │
│    │   ├── 获取推荐流视频列表                    │
│    │   ├── 过滤封面/标题（兴趣匹配）             │
│    │   ├── 标记已观看 → 上报历史记录             │
│    │   ├── 深度视频理解 (视觉/ASR/字幕)          │
│    │   ├── 读取弹幕 → 点赞/发送弹幕              │
│    │   ├── 读取评论 → AI 生成回复               │
│    │   ├── 心理画像评分 → 投币/收藏/关注UP     │
│    │   ├── 知识库分类归档                        │
│    │   ├── 好奇心搜索 (关联内容深度探索)         │
│    │   └── 回顾复习 (随机挑选旧知识重温)         │
│    │                                              │
│    ├── 检查评论/私信消息 → 回复                  │
│    ├── 主动找人聊天 (概率触发)                   │
│    ├── 精力消耗 → 等待恢复                       │
│    └── 自我进化检查 → 反思优化                   │
│                                                  │
│  └── 循环...                                     │
└─────────────────────────────────────────────────┘
```

关键可配置参数：
- `energy.max_energy`: 最大精力值
- `energy.rounds_min/max`: 每轮观看视频数
- `energy.energy_recovery_min/max`: 精力恢复速度
- `interaction.interest_threshold`: 兴趣过滤门槛

### 2. 视频理解 — 四种模式

| 模式 | 原理 | 速度 | 准确度 | 适用场景 |
|------|------|------|--------|----------|
| **subtitle** | 仅读取标题+简介+字幕+评论 | ⚡ 极快 | ⭐⭐ | 知识类视频 |
| **frames** | 下载视频 → ffmpeg 抽帧 → 视觉模型分析 | 🐢 较慢 | ⭐⭐⭐ | 教程/演示 |
| **hybrid** | 字幕 + 抽帧综合分析 | 🐢 慢 | ⭐⭐⭐⭐ | 全面理解 |
| **smart** (默认) | 先预判兴趣，有足够价值才深度分析 | ⚡ 智能 | ⭐⭐⭐ | 推荐流最佳 |

**ASR 语音识别**：支持 FunASR（推荐）和 Whisper，说话人分离、VAD 检测、音乐段跳过。

### 3. 评论互动系统

```
B站评论接口 → 获取热门评论 (最多8条)
  ├── 检查是否已处理过
  ├── 心情影响回复概率
  ├── 安全过滤 (敏感词/政治内容)
  ├── [并行] 视觉AI分析评论图片
  ├── AI 生成回复草稿 (使用当前人格)
  ├── 干运行/真实发送
  └── 记录互动日志 → 更新用户画像
```

关键机制：评论轮询间隔、回复概率控制、用户冷却时间、AI 标记。

### 4. 私信自动回复

轮询新私信 → 过滤已处理 → 加载上下文 → AI 个性化回复 → 保存上下文。支持多用户独立对话、主人识别。

### 5. 弹幕互动系统

| 操作 | 概率 | 每日上限 | 说明 |
|------|------|----------|------|
| 读取弹幕 | 40% | 无限制 | XML 接口获取弹幕池 |
| 点赞弹幕 | 15% | 10 条/天 | 点赞有趣弹幕 |
| 发送弹幕 | 3% | 2 条/天 | AI 生成弹幕 (≤20字) |

### 6. UP 主关注系统

**设计理念**：关注 = 认可，不是抽奖。宁缺毋滥，只关注真正有价值的 UP。

| 条件 | 阈值 | 说明 |
|------|------|------|
| 评分门槛 | ≥ 7.0 | 低于此分数直接拒绝 |
| 印象积累 | ≥ 2 次 | 必须看够 N 个视频才考虑关注 |
| 特别优秀 | ≥ 8.5 | 首看即达可直接关注 |
| 每日上限 | 3 个 | 不超过此数 |
| 冷却时间 | 90 分钟 | 时间内不重复关注 |

### 7. 心理画像引擎

**五层深度分析系统**：

| 层级 | 维度 | 分析内容 |
|------|------|----------|
| L1 表层兴趣 | 行为偏好 | 关键词/标签偏好、内容类型 |
| L2 认知风格 | 思维模式 | 分析型/直觉型、视觉/文本偏好 |
| L3 情感需求 | 情感驱动 | 智识刺激、成就满足、社交连接 |
| L4 深层动机 | 价值观 | 自我提升、好奇心、创作表达 |
| L5 演变趋势 | 成长轨迹 | 兴趣变迁、内在矛盾、成长方向 |

五种推荐类型：惊喜推荐、兴趣探索、内容筛选、内容拓展、趋势推荐。自动防信息茧房。

### 8. 个人知识库系统

```
视频观看完成
  ├── 评分 ≥ 阈值 → 自动分类归档
  │   ├── 教育/ (写作技巧/英语考试/文学素养)
  │   ├── 科技/ (AI工具/半导体/安全/效率工具)
  │   ├── 游戏/ (游戏模组/游戏资讯)
  │   ├── 社会/ (法治/文化现象)
  │   └── 自然/ (动物)
  └── 知识收集/ (评论精华归档)
```

支持知识验证（联网搜索）、回顾复习（随机重温旧知识）。

### 9. 好奇心搜索

遇到感兴趣视频时自动触发深度探索：搜索相关标签、逐层下钻、触发最低评分 7.5、冷却 120 分钟。

### 10. 日记与自我进化

**日记系统**：记录每次视频观看、评论互动，AI 自动生成每日日记总结。

**自我进化**：每 N 个事件触发反思，AI 分析行为模式，自动优化人格提示词。

### 11. 内容安全

多层过滤：敏感词黑名单、政治内容拦截、视频评论政治检测。支持双向拦截（收到/发出）。

### 12. 娱乐模块

每日运势、段子生成、热梗追踪、小游戏。

### 13. Web 控制台（网页端）

Web 面板提供完整的可视化操作界面：

- **仪表盘**：实时状态监控、图表趋势（评论活跃度、心情指数、操作统计、视频处理速率）
- **机器人控制**：启动/停止/重启、实时日志输出
- **B站登录**：扫码登录、登录状态
- **配置编辑**：JSON 编辑器直接修改全部配置
- **人格管理**：创建/切换/删除人设模板
- **功能中心**：手动视频分析、知识库重温/整理、Agent 技能执行
- **心情管理**：查看/切换心情、调整心情参数
- **数据监控**：评论日志、用户画像、记忆知识库、日记进化、操作日志
- **系统管理**：导出/导入配置、恢复出厂设置

所有 CLI 端的功能在网页端均可操作，无需记忆命令。

---

## ⚙️ 完整配置参考 (Data/config.json)

```jsonc
{
  // ── API 配置 ──
  "api": {
    "unified_api_key": "",        "unified_base_url": "",
    "model_brain": "",            "model_vision": ""
  },

  // ── 人格配置 (自定义名字) ──
  "persona": {
    "active_persona": "学习助手",
    "prompt_name": "我的AI学习伙伴",  // ← 机器人显示名
    "bot_name": "你想起的名字",       // ← 机器人自称
    "user_name": "主人",             // ← 对用户的称呼
    "custom_prompt": "",             // ← 自定义提示词
    "enable_auto_evolution": true
  },

  // ── 互动控制 ──
  "interaction": {
    "coin_threshold": 8.0,         "fav_threshold": 8.5,
    "interest_threshold": 4.5,      "max_coins_daily": 2,
    "prob_reply_trigger": 0.15,    "prob_coin": 0.25,
    "prob_like_solo": 0.5,         "comment_check_interval": 300
  },

  // ── 精力系统 ──
  "energy": {
    "max_energy": 200,             "energy_recovery_min": 15,
    "energy_recovery_max": 25,     "rounds_min": 1,
    "rounds_max": 3,               "round_interval_min": 5,
    "video_interval_min": 1,       "video_interval_max": 2
  },

  // ── 视频理解 ──
  "video": {
    "mode": "smart",               "max_duration_seconds": 900,
    "frame_count": 12,             "download_interest_threshold": 7.0
  },

  // ── 视觉理解 ──
  "vision": {
    "frames_enabled": true,        "comment_images_enabled": true,
    "max_comment_images": 5,       "smart_frame_enabled": true
  },

  // ── 私信配置 ──
  "private_message": {
    "enabled": true,               "auto_reply": true,
    "check_interval": 300,         "only_recent_seconds": 900
  },

  // ── 行为控制 ──
  "behavior": {
    "ai_marker": "（本消息由AI生成）",
    "comment_mode": "real",        "prefer_short_replies": true
  },

  // ── 日记 ──
  "diary": {
    "enabled": true,               "auto_enabled": true,
    "auto_interval_minutes": 60,   "min_events_for_auto": 3
  },

  // ── 自我进化 ──
  "self_evolution": {
    "enabled": true,               "auto_enabled": true,
    "reflect_interval_events": 8,  "auto_apply": true
  },

  // ── 回顾复习 ──
  "revisit": {
    "enabled": true,               "prob_revisit": 0.12,
    "revisit_cooldown_minutes": 25
  },

  // ── 好奇心搜索 ──
  "curiosity_search": {
    "enabled": true,               "trigger_min_score": 7.5,
    "cooldown_minutes": 120,       "prob_trigger": 0.3
  },

  // ── UP 主关注 ──
  "up_follow": {
    "enabled": true,               "auto_follow_prob": 0.08,
    "max_daily_follows": 3,        "cooldown_minutes": 90
  },

  // ── 弹幕互动 ──
  "danmaku": {
    "enabled": true,               "read_prob": 0.4,
    "like_prob": 0.15,             "send_prob": 0.03
  },

  // ── 心理引擎 ──
  "psycho_engine": {
    "enabled": true,               "cocoon_warning_threshold": 0.35,
    "deep_analyze_interval_videos": 100
  },

  // ── ASR 语音识别 ──
  "asr": {
    "enabled": true,               "backend": "funasr",
    "language": "zh",              "speaker_separation": true
  },

  // ── 心情系统 ──
  "mood": {
    "default_mood": "平静",        "mood_volatility": 1.0,
    "random_enabled": false
  },

  // ── Agent 配置 ──
  "agent": {
    "enabled": true,               "auto_enabled": true,
    "max_steps_per_plan": 5
  }
}
```

---

## 📊 数据流完整图

```
                    ┌──────────────┐
                    │  B站 API 层  │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       推荐流视频      评论/私信      弹幕池
              │            │            │
      ┌───────▼───────┐    │            │
      │  封面/标题过滤 │    │            │
      │  (兴趣匹配)    │    │            │
      └───────┬───────┘    │            │
              │            │            │
      ┌───────▼───────┐    │            │
      │  视频理解引擎  │    │            │
      │  字幕/抽帧/ASR │    │            │
      │  视觉AI分析    │    │            │
      └───────┬───────┘    │            │
              │            │            │
      ┌───────▼────────────▼────────────▼───┐
      │           AI 决策中枢               │
      │  评分 → 动作决策                    │
      │  投币? 收藏? 点赞? 关注?           │
      │  评论回复? 弹幕发送?               │
      └───────┬─────────────────────────────┘
              │
     ┌────────┼────────┬──────────┬──────────┐
     ▼        ▼        ▼          ▼          ▼
  执行动作  知识归档  好奇心搜索  心理更新  日记记录
                        │
                ┌───────▼───────┐
                │  自我进化反思  │
                │  人格优化     │
                └───────────────┘
```

---

## 🚀 快速开始

### 环境要求
- Python 3.8+
- Windows / Linux / macOS

### 安装

```powershell
# 1. 进入项目目录
cd G:\code\bilibili_learning_bot

# 2. 安装核心依赖
pip install -r requirements.txt

# 3. (可选) 安装 ASR 依赖
pip install -r requirements-optional.txt

# 4. (可选) 安装 ffmpeg (用于视频抽帧)
# Windows: 下载 https://ffmpeg.org 并加入 PATH
```

### 配置

编辑 `Data/config.json`，填入 API Key，并自定义机器人名字：

```json
{
  "api": {
    "unified_api_key": "你的API Key",
    "unified_base_url": "https://api.openai.com/v1",
    "model_brain": "gpt-4.1-mini",
    "model_vision": "gpt-4.1-mini"
  },
  "persona": {
    "active_persona": "学习助手",
    "prompt_name": "你的机器人名字",
    "bot_name": "机器人自称",
    "user_name": "主人",
    "custom_prompt": "自定义提示词……"
  }
}
```

推荐使用环境变量（更安全）：

```powershell
$env:BILI_AI_API_KEY="你的 API Key"
$env:BILI_AI_BASE_URL="https://api.openai.com/v1"
$env:BILI_BOT_NAME="你的机器人名字"
```

### 启动

**Web 控制台（推荐）**：

```powershell
python web_panel.py
```

然后打开 `http://127.0.0.1:8080`，所有功能均可在网页上完成。

**命令行机器人**：

```powershell
python new_agent.py
```

首次运行需要扫码登录 B站。

---

## 📦 依赖列表

### 核心依赖

`bilibili-api-python` `httpx` `openai` `colorama` `qrcode` `Flask`

### 可选依赖 (ASR)

`funasr` `torch` `torchaudio` `whisper`

---

## 🔒 安全说明

### 不要公开的文件

| 文件/目录 | 原因 |
|-----------|------|
| `Data/config.json` | 含 API Key |
| `Data/bilibili_cookies.json` | 含登录 Cookie |
| `Data/` | 运行数据 |
| `KnowledgeBase/` | 个人知识库 |

### 风险提示

⚠️ 自动评论、点赞、投币、收藏、弹幕等行为可能触发 B站风控。

建议：
- 长期保持 `comment_mode: "dry_run"`（干运行模式）
- 先人工确认 AI 生成内容再决定是否真实执行
- 控制操作频率，避免异常行为模式
- Cookie 泄露可能导致账号被盗，请妥善保管

---

## 📈 性能优化

经过多轮持续优化，核心指标：

| 指标 | 优化后 |
|------|--------|
| 主循环纯等待 | 2~5s |
| 评论检查 | 1.5~5s |
| 评论处理/条 | 1~3s |
| 弹幕获取 | 0.5~1s |
| 图片分析 (并行) | 2~4s/组 |

核心优化：并行任务、延迟大幅削减、AI 超时优化、预取推荐流。

---

## 📝 日志系统

| 标签 | 用途 |
|------|------|
| `[BRAIN]` | 主决策日志 |
| `[BILI]` | B站 API 调用 |
| `[COMMENT]` | 评论互动 |
| `[PRIVATE]` | 私信处理 |
| `[DANMAKU]` | 弹幕操作 |
| `[EYE]` | 视觉分析 |
| `[ASR]` | 语音识别 |
| `[MEMORY]` | 记忆操作 |
| `[DIARY]` | 日记系统 |
| `[EVOLVE]` | 自我进化 |
| `[ENERGY]` | 精力系统 |
| `[SAFETY]` | 安全过滤 |
| `[PSYCHO]` | 心理引擎 |

---

## 🧠 核心设计理念

- **精力系统**：模拟人类精力耗损与恢复，避免无节制刷视频
- **评分驱动**：所有行为由 AI 评分决定，高质量内容投币/收藏，低质量快速跳过
- **心理画像**：五层分析，深度理解用户偏好，主动推荐+防信息茧房
- **并行效率**：所有无依赖任务通过 asyncio.gather 并行执行
- **安全第一**：多层过滤，干运行模式，保护账号安全
- **自我进化**：通过反思优化人格，让 AI 逐渐变得更懂你
- **名字自由**：`persona.prompt_name` 和 `bot_name` 完全自定义，无需改代码

---

## 📄 许可证

MIT License

## 👤 联系方式

QQ: 3781960338 | 交流群: 1056941856

*最后更新: 2026-06-13*
