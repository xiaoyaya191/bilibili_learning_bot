# bilibili_learning_bot

> **B站学习互动机器人** — 自动刷视频、学知识、互动评论、私信回复、自我进化  
> 代码量: ~26,000+ 行 Python | 31 个模块文件  
> 版本: 2.2.0 | License: MIT

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 📺 **智能视频浏览** | AI驱动的B站推荐流浏览，自动判断内容价值（评分/收藏/投币） |
| 📚 **知识库系统** | 自动归档高质量视频内容，支持3层分类 + 向量语义检索 |
| 💬 **评论互动** | 真实评论/模拟评论模式，AI自动生成有深度回复，支持图片分析 |
| 📩 **私信处理** | 自动回复粉丝私信，保持上下文记忆，支持节奏控制 |
| 🧬 **日记与自我进化** | 记录行为日志，AI自我反思，人格动态进化 |
| 🎙️ **ASR语音识别** | 视频语音转文字（FunASR / Whisper，需本地模型） |
| 🤖 **Agent技能系统** | 自主规划目标→搜索B站→看视频→总结知识，全自动闭环 |
| 🔄 **复习回顾** | 定时重温已学知识，优化记忆 |
| 🎓 **知识辅导** | AI讲解/问答/二次创作/生成HTML学习卡片 |
| 🌐 **网页讲解** | 输入URL，AI读网页/总结/讲解 |
| 📝 **自定义知识管理** | 手动增删改查知识条目 + AI搜索B站自动整理入库 |
| 😊 **AI心情系统** | 动态心情影响互动风格，支持自定义 |
| 🛡️ **安全审查** | 关键词过滤 + 政治敏感拦截 + 提示词注入防护 |
| 🔄 **备用API降级** | 主API连续失败自动切换到备用提供商，10分钟后自动恢复 |
| 📤 **隐私导出** | 一键导出配置（API Key/Cookie脱敏保护） |

## 🧱 项目结构

```
├── new_agent.py          # 核心机器人 (~16,400行) AgentBrain + BiliClient
├── web_panel.py          # Flask Web 管理面板
├── psycho_engine.py      # 心理画像引擎 + 推荐系统
├── json_utils.py         # 线程安全JSON存储 + 导出脱敏工具
├── core/
│   └── config.py         # 配置加载/保存
├── services/
│   ├── agent_service.py  # Agent技能执行器
│   ├── interaction_service.py  # 互动服务
│   ├── knowledge_tutor.py      # 知识辅导
│   ├── managers.py       # 人格/心情/日记/进化管理器
│   ├── reply_safety.py   # 回复安全审查
│   └── utils.py          # 兴趣管理/工具函数
├── xingye_bot/           # 模块化组件
│   ├── asr_engine.py     # 语音识别引擎
│   ├── kb_search.py      # 向量知识库检索
│   ├── video_modes.py    # 视频理解模式
│   ├── video_asr.py      # 视频ASR处理
│   ├── diary.py          # 日记系统
│   ├── evolution.py      # 自我进化
│   ├── skills.py         # Agent技能
│   ├── safety.py         # 安全过滤
│   ├── llm.py            # LLM客户端
│   ├── memory.py         # 语义记忆
│   ├── state.py          # 状态管理
│   ├── background.py     # 后台任务
│   ├── bilibili_ops.py   # B站操作
│   ├── owner.py          # 主人识别
│   ├── proactive.py      # 主动行为
│   ├── settings.py       # 设置
│   └── web_search.py     # 网络搜索
├── Data/                 # 运行时数据（自动生成）
│   ├── config.json       # 配置文件
│   ├── bilibili_cookies.json  # B站登录Cookie
│   ├── mood_state.json   # 心情状态
│   └── ...
├── KnowledgeBase/        # 知识库目录
│   ├── 知识收集/         # 待归档知识
│   ├── 科技/             # 按3层分类归档
│   ├── 自定义知识/       # 用户自定义知识
│   └── ...
└── config.example.json   # 配置模板
```

## 🚀 快速开始

### 1️⃣ 安装依赖

```bash
pip install -r requirements.txt
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
python3 new_agent.py
```

**Web管理面板**:
```bash
python3 web_panel.py
# 访问 http://localhost:7860
```

**Termux 一键启动**:
```bash
bash start.sh
```

### 4️⃣ 首次使用

1. 进入菜单后按 `3` 配置B站登录（扫码或Cookie）
2. 按 `1` 启动机器人自动刷视频
3. 按 `V` 手动分析特定视频
4. 按 `N` 管理自定义知识

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
| `F` | 👤 UP主关注/弹幕设置 |
| `G` | 🎙️ ASR语音识别设置 |
| `M` | 😊 AI心情管理 |
| `D` | 🏆 干货归档 |
| `V` | 📹 手动视频分析 |
| `K` | 🔄 知识库重温 |
| `T` | 🎓 知识辅导 |
| `W` | 🌐 网页讲解 |
| `N` | 📝 自定义知识管理 |
| `R` | 🔄 恢复出厂设置 |
| `S` | 🛡️ 关键词审查开关 |
| `E` | 📤 导出配置（脱敏） |
| `I` | 📥 导入配置 |
| `O` | 📂 一键整理知识库 |

## 🔒 隐私安全

- API Key 在菜单显示和导出时自动脱敏（`mask_secret` / `sanitize_config_for_export`）
- 一键恢复出厂设置（`R`）清除所有配置/登录/日志/知识库
- 导出备份自动隐藏敏感字段（API Key、Cookie Token等替换为 `[已隐藏]`）

## 📝 二创说明（二次创作 / Fork）

本项目采用 **MIT 许可证**，欢迎任何人 **Fork、修改、再发布**（二创）！

### 二创时必须做的事 ✅

| # | 要求 | 说明 |
|---|------|------|
| 1 | **保留 LICENSE 文件** | 任何分发包中必须包含  文件，**不得删除或替换**原始版权声明 |
| 2 | **标注原始项目地址** | 在 README / 项目说明中显著位置注明： |
| 3 | **保留署名** | 在你的项目文档或版头保留  |

### 推荐但非强制 🎉

- 如果做了有价值的改进，欢迎提 **Pull Request** 回馈上游
- 可以在 README 致谢区加一句 

### 简单理解

> 💡 **你完全可以用我的代码做任何事（商用也行），唯一的要求是：让人知道你的项目是从我这来的。** 加一行链接即可。

---

## ⚠️ 免责声明

本项目仅供学习参考。若因使用本项目产生任何后果，本人概不负责。

---
*Based on [bilibili_learning_bot](https://github.com/xiaoyaya191/bilibili_learning_bot) · Original author: xiaoyaya191*
