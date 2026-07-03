# 🔧 bilibili_learning_bot 重构完成

> 目标达成：16.8K 行单体 → 4 行入口 + 24 个小文件
> 版本：3.0.0 | License: MIT

---

## 📊 最终对比

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| `start_cli.py` | 16,822 行 | **22 行** (-99.9%) |
| `core/globals.py` | 无 | **280 行** (全局变量集中) |
| 菜单测试 | — | **23/23 通过** ✅ |
| `new_agent.py` | 17,212 行 (重复) | **已删除** |
| `main.py` | 无 | **164 行** |
| 模块文件 | 混杂 | **24 个** 职责清晰 |
| 配置系统 | 2 套并行 | **1 套统一** |
| 密码存储 | 明文 | **SHA-256 哈希** |
| 裸 except | 3 处 | **0 处** |
| Session 密钥 | 随机(重启失效) | **持久化** |
| 测试 | 0 | **43 个 (pytest)** |
| 死代码 | `services/interaction_service.py` | **已删除** |

---

## 🗂️ 最终项目结构

```
bilibili_learning_bot/
│
├── main.py               # 🚀 主入口 (164行)
├── start_cli.py          # 📎 兼容转发 (4行)
├── web_panel.py          # 🌐 Web 管理面板
│
├── api/                  # 🔌 B站 API 层
│   ├── client.py         # B站客户端 BiliClient
│   ├── auth.py           # 登录认证
│   ├── subtitles.py      # 字幕获取与校验
│   ├── throttle.py       # 请求节流器
│   └── compat.py         # 兼容层
│
├── brain/                # 🧠 核心大脑
│   ├── agent_brain.py    # 主调度器 AgentBrain
│   ├── comment.py        # 评论互动管理
│   ├── private_msg.py    # 私信处理
│   └── video_analysis.py # 手动视频分析
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
│   ├── managers.py       # 人格/心情/日记/进化管理
│   └── psycho.py         # 心理画像引擎 + 推荐系统
│
├── security/             # 🛡️ 安全与隐私
│   └── guard.py          # 回复内容审查
│
├── cli/                  # 💻 命令行界面
│   └── app.py            # 菜单 + 配置 (~4,200行)
│
├── core/                 # ⚙️ 配置
│   └── config.py         # 统一配置加载/保存
│
├── services/             # 🔧 服务模块
│   ├── agent_service.py  # Agent 技能执行
│   ├── knowledge_tutor.py # 知识辅导
│   └── utils.py          # 兴趣管理/工具
│
├── utils/                # 🛠 通用工具
│   ├── helpers.py        # 工具函数
│   ├── storage.py        # JSON 线程安全存储 + 脱敏
│   ├── display.py        # 日志显示
│   └── lock.py           # 单实例锁
│
├── xingye_bot/           # 🤖 扩展组件
│   ├── llm.py            # LLM 客户端
│   ├── state.py          # 状态管理
│   ├── memory.py         # 语义记忆
│   ├── settings.py       # 设置(从 core.config 读取)
│   ├── diary.py          # 日记系统
│   ├── evolution.py      # 自我进化
│   ├── skills.py         # Agent 技能
│   ├── asr_engine.py     # 语音识别
│   ├── video_modes.py    # 视频理解
│   ├── kb_search.py      # 向量检索
│   └── ...
│
├── Data/                 # 💾 运行时数据（自动生成）
├── KnowledgeBase/        # 📖 知识库文件
├── tests/                # 🧪 43 个测试
└── requirements.txt      # 📦 依赖
```

---

## ✅ 完成清单

- [x] 删除 `new_agent.py`（17K 行重复副本）
- [x] 删除 `services/interaction_service.py`（死代码）
- [x] 统一配置：`xingye_bot/settings.py` → 从 `core.config` 读取
- [x] 批量修复提取模块的缺失 import（shutil, datetime, _load_json_file 等）
- [x] 创建 `core/globals.py` 集中管理 206 个运行时全局变量
- [x] `start_cli.py` 16,822 → 22 行（转发+友好提示）
- [x] 创建 `main.py` 164 行入口
- [x] 拆分 `brain/`：AgentBrain + 评论 + 私信 + 视频分析
- [x] 拆分 `knowledge/`：分类 + 搜索 + 浏览 + 重温 + 整理 + 自定义
- [x] 拆分 `api/`：客户端 + 认证 + 字幕 + 节流
- [x] 创建 `security/`：内容审查
- [x] 创建 `persona/`：人格管理 + 心理画像
- [x] `json_utils.py` → `utils/storage.py`
- [x] `psycho_engine.py` → `persona/psycho.py`
- [x] `services/managers.py` → `persona/managers.py`
- [x] `services/reply_safety.py` → `security/guard.py`
- [x] 密码 SHA-256 哈希存储
- [x] 裸 except 清零
- [x] Flask session 密钥持久化
- [x] 43 个 pytest 测试
- [x] `requirements.txt` 锁定版本
- [x] `README.md` 更新
- [x] `start.sh` 更新
- [x] `web_panel.py` 引用更新

---

## 🔜 后续可选

| 事项 | 说明 |
|------|------|
| CLI 菜单拆分 | `cli/app.py` 中 `show_*_menu`/`configure_*` 函数使用 `global`，需先重构 |
| 测试扩展 | 为核心模块（BiliClient、分类器等）添加 mock 测试 |
| CI/CD | 添加 GitHub Actions 自动测试 |
| 类型注解 | 逐步添加 type hints |

---

## 📋 更新日志

### v2.2.2 — 2026-06-21（Bug 修复 + 功能增强）

#### 🎯 新功能
| 功能 | 说明 |
|------|------|
| 封面分析开关 | 主菜单 `C` 快捷键，关闭后跳过封面 AI 分析，刷视频更快 |
| UP主主页批量学习 | 主菜单 `U` 命令，输入UP主名字/UID，获取主页视频列表逐个AI学习归档 |

#### 🔴 崩溃级 Bug 修复（3 个）
| Bug | 文件 | 修复 |
|-----|------|------|
| 按 Q 切换快速模式崩溃 `NameError: bili` | `cli/app.py` | `bili.throttle` → `api.throttle` |
| 主循环 `_safe_task_callback` 未定义崩溃 | `brain/agent_brain.py` | 移至 `utils/helpers.py` 共享 |
| 快速模式切换失败重复打印错误 | `main.py` | 删除冗余 print |

#### 🔴 导入缺失修复（2 个）
| Bug | 文件 | 影响 | 修复 |
|-----|------|------|------|
| 缺少 `datetime`/`parse_iso_datetime` 导入 | `brain/comment.py` | 评论节奏控制静默失效 | 添加导入 |
| 缺少 `datetime`/`parse_iso_datetime`/`is_api_configured` 导入 | `brain/private_msg.py` | 私信节奏控制和工具规划静默失效 | 添加导入 |

#### 🟡 全局变量遗漏修复（1 个）
| Bug | 文件 | 修复 |
|-----|------|------|
| `_reload_all_globals` 遗漏 `AI_MARKER` 和 `SUBTITLE_STRICT_CHECK` | `cli/app.py` | 添加 global 声明和赋值 |

#### 🟡 asyncio 并发修复（2 个）
| Bug | 文件 | 修复 |
|-----|------|------|
| `asyncio.gather` 无 `return_exceptions=True` | `brain/agent_brain.py:3200` | 添加参数 + 异常降级为 0 |
| `asyncio.gather` 无 `return_exceptions=True` | `brain/agent_brain.py:3557` | 添加参数 |

#### 🟡 非原子 JSON 写入修复（13 处）
所有关键 `.json` 文件统一改为 **tmp+replace 原子写入**，防止 Android 环境断电/被杀时数据损坏：

| 文件 | 目标文件 | 修复方式 |
|------|----------|----------|
| `core/config.py` `save_config()` | `config.json`（最核心） | tmp+replace |
| `core/config.py` `save_json_file()` | 所有调用者 | tmp+replace |
| `api/client.py` | Cookie 文件 buvid3 补全 | tmp+replace |
| `knowledge/custom.py` (4处) | `knowledge_metadata.json` | `_atomic_write_json()` |
| `knowledge/browse.py` | `knowledge_metadata.json` | tmp+replace |
| `persona/managers.py` | `private_context_db.json` | tmp+replace |
| `persona/psycho.py` | `psycho_profile.json` | tmp+replace |
| `services/utils.py` | `interests.json` | tmp+replace |
| `services/agent_service.py` | `agent_skill_log.json` | tmp+replace |
| `cli/app.py` | `search_history.json` | tmp+replace |
| `brain/agent_brain.py` (2处) | 记忆 + 历史视频 | tmp+replace（之前已修复） |
| `brain/comment.py` | 评论日志 | tmp+replace（之前已修复） |
| `brain/private_msg.py` | 私信日志 | tmp+replace（之前已修复） |
| `api/auth.py` | Cookie 文件 | tmp+replace（之前已修复） |
| `knowledge/classifier.py` | 知识库元数据 | tmp+replace（之前已修复） |

### 🔍 代码审查与优化建议（待实施）

#### 🔴 严重问题
- **God Class**: `brain/agent_brain.py` 的 `AgentBrain` 类 4000+ 行、70+ 方法，涵盖视频处理/AI推理/知识归档/评论互动/弹幕/追UP主/日记/自我进化。建议按职责拆分为 `brain/video_processor.py`、`brain/knowledge_manager.py`、`brain/interaction.py`、`brain/agent_loop.py`
- **LLM 同步阻塞事件循环**: `brain/agent_brain.py:212-217` 的 `_call_ai_via_openai` 在 `async def` 中直接调用同步的 `openai.ChatCompletion.create()`，每次 LLM 请求阻塞事件循环 5-30 秒，9+ 处调用都有此问题
- **废弃 OpenAI SDK API**: 全项目使用 `openai.ChatCompletion.create()`（v1.0 之前旧 API），涉及 `brain/agent_brain.py`、`knowledge/classifier.py`、`knowledge/custom.py`、`brain/comment.py`、`brain/private_msg.py` 等 9+ 处，应迁移到 `openai>=1.0` 的 `client.chat.completions.create()`

#### 🟡 重要问题
- **双系统未整合**: `xingye_bot/llm.py` 有干净的 `ModelClient` + fallback，`xingye_bot/state.py` 有 `BotState` + `JsonStore`，但 `AgentBrain` 完全没用，自己重写了 200 行重试逻辑
- **通配符导入**: `from core.globals import *` 导入 200+ 全局变量（`brain/agent_brain.py:16`、`brain/video_analysis.py:12`），无法追踪变量来源
- **JSON 提取逻辑重复**: `brain/agent_brain.py:1340-1370`、`knowledge/classifier.py:118-155`、`knowledge/web_search.py:162-185` 各自手写 `find("{")` → 花括号匹配 → `json.loads()`，应提取为 `utils/json_extract.py`
- **部分 API 无重试**: `api/client.py` 中 `follow_up`、`unfollow_up`、`search_bilibili` 无重试逻辑，而其他方法有完善退避
- **LLM 调用缺 timeout**: `brain/agent_brain.py:1032`、`knowledge/classifier.py:96,635` 无 timeout 参数，API 挂起无限阻塞

#### 🟢 次要问题
- **main.py 重复 try/except**: `try/except KeyboardInterrupt/except Exception` 模式重复 10+ 次，应抽取 `run_async(coro)` 辅助函数
- **HTTP Client 未关闭**: `BiliClient.close()` 已定义但从未调用，连接池泄漏
- **`known_ups` 无限增长**: `brain/agent_brain.py:534-560` 无淘汰机制，长期运行内存膨胀
- **main.py 重复打印**: 快速模式切换失败时连续两行相同错误输出（已修复）
