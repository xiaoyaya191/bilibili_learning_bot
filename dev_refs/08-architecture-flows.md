# 项目架构与代码流程 (Architecture & Flows)

> 了解整体架构和数据流，方便快速定位代码。

## 项目结构总览

```
测试/
├── main.py              # CLI 主入口（26个菜单命令分发）
├── start_cli.py         # CLI 启动辅助（全局变量定义）
├── web_panel.py         # Flask Web 管理面板
├── web_panel.html       # Web 面板前端（单文件）
├── config.example.json  # 配置文件模板
├── DEV_REFERENCE.txt    # 开发者完整参考手册
├── dev_refs/            # 🆕 API/流程参考文件夹（供 AI 开发参考）
│
├── api/                 # B站 API 封装层
│   ├── client.py        # BiliClient 核心客户端
│   ├── subtitles.py     # 字幕获取与校验
│   └── throttle.py      # 请求限速
│
├── brain/               # AI 大脑（13个 Mixin 组合）
│   ├── _brain_ai.py     # AI 后端（多Provider/多级降级）
│   ├── _brain_video.py  # 视频学习流程
│   ├── _brain_comment.py # 评论互动
│   ├── _brain_curiosity.py # 好奇心搜索
│   ├── _brain_session.py # 会话管理（@通知等）
│   ├── standby.py       # 待机/通知模式
│   ├── video_analysis.py # 手动视频分析
│   └── ...
│
├── cli/                 # CLI 菜单系统
│   └── app.py           # 所有菜单函数（show_main_menu, show_xxx_menu）
│
├── core/                # 核心基础
│   └── config.py        # 配置加载/路径常量/日志
│
├── knowledge/           # 知识库管理
│   ├── browse.py        # 浏览/搜索知识库
│   ├── custom.py        # 自定义知识管理
│   └── web_search.py    # 联网搜索 + AI验证
│
├── services/            # 服务模块（独立功能）
│   ├── video_to_ppt.py  # 视频→精美网页（19种风格）
│   ├── knowledge_tutor.py # AI 知识辅导
│   ├── agent_service.py # Agent 自主学习
│   ├── interest_engine.py # 兴趣引擎
│   ├── quiz_generator.py # 🆕 出题考试
│   ├── deep_dive.py     # 🆕 深入了解
│   └── utils.py         # 服务工具
│
├── utils/               # 通用工具
│   ├── storage.py       # JsonStore（线程安全 JSON）
│   ├── helpers.py       # 通用辅助函数
│   └── display.py       # 显示相关
│
├── persona/             # 人格系统
├── security/            # 安全审核
├── xingye_bot/          # xingye_bot 子系统
├── tests/               # 测试
├── templates/           # HTML 模板
│
├── Data/                # 数据目录
│   ├── config.json      # 主配置
│   └── bilibili_cookies.json # 登录凭证
│
├── KnowledgeBase/       # 知识库文件
├── html_exports/        # HTML 导出
└── highlights/          # 精品归档
```

## 核心数据流

### 视频学习流程

```
用户操作 (CLI/Web)
  ↓
main.py / web_panel.py
  ↓
brain/video_analysis.py → manual_video_analysis(bvid)
  ↓
api/subtitles.py → fetch_bilibili_subtitles(bvid)
  │  ├─ 获取 WBI 签名密钥 (nav API)
  │  ├─ 获取视频信息 (view API)
  │  ├─ 获取字幕 URL (player/wbi/v2 API)
  │  └─ 下载字幕 JSON 内容
  ↓
brain/_brain_ai.py → _call_ai_with_retry()
  │  ├─ 分析字幕内容
  │  ├─ 生成学习笔记
  │  └─ 多级降级容错
  ↓
保存到 KnowledgeBase/
  ↓
(可选) video_to_ppt.py → 生成 HTML 网页
```

### 出题考试流程

```
CLI: J→1 或 Web: /api/quiz/generate
  ↓
services/quiz_generator.py → generate_quiz()
  ↓
选择内容来源:
  ├─ 视频: api/subtitles.py → fetch_bilibili_subtitles(bvid)
  └─ 知识库: 直接读取 .md 文件
  ↓
LLM 调用 (openai):
  ├─ 使用系统提示词模板
  ├─ 传入字幕/知识库内容
  └─ 生成考题
  ↓
保存到 html_exports/quizzes/
```

### 深入了解流程

```
CLI: J→2 或 Web: /api/deep-dive/run
  ↓
services/deep_dive.py → run_deep_dive()
  ↓
AI 分析主题 → 生成 3-5 个搜索关键词
  ↓
选择模式:
  ├─ 联网搜索: knowledge/web_search.py → web_search()
  │    ↓
  │  Bing → 搜狗 → DuckDuckGo → Wikipedia
  │
  └─ B站视频: 搜索B站 → 逐个获取字幕
  ↓
AI 综合所有资料 → 生成学习报告
  ↓
保存到 KnowledgeBase/深入学习/ + html_exports/deep_dives/
```

### Web 面板请求流

```
浏览器 → Flask 路由 (@app.route)
  ↓
request.get_json() → 解析参数
  ↓
asyncio.new_event_loop() → 运行异步函数
  ↓
service 模块 → 核心处理
  ↓
jsonify({"ok": True/False, ...}) → 返回 JSON
  ↓
前端 fetch() → 更新 DOM
```

## 关键设计模式

### 1. 实时配置读取

不要缓存配置值，每次使用时从 `config` 字典实时读取：

```python
# ✅ 正确
def get_api_key():
    from core.config import config
    return config.get("api", {}).get("unified_api_key", "")

# ❌ 错误
API_KEY = config.get("api", {}).get("unified_api_key", "")  # 模块加载时缓存
```

### 2. 异步包装

Flask 是同步框架，调用 async 函数时需要包装：

```python
import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
try:
    result = loop.run_until_complete(async_function())
finally:
    loop.close()
```

### 3. 原子写入

所有重要数据写入使用 tmp+replace 防损坏：

```python
tmp = filepath + '.tmp'
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp, filepath)
```

### 4. 降级容错

多级降级模式，每个环节都有 fallback：
- LLM: 主API → 备用模型 → 备用提供商 → 熔断
- 搜索: Bing → 搜狗 → DuckDuckGo → Wikipedia
- 字幕: wbi/v2 → player/v2 → 无字幕

## 修改 DEV_REFERENCE.txt 规范

每次开发任务完成后必须更新 `DEV_REFERENCE.txt`：
- 新增文件 → 更新文件清单
- 新增功能 → 更新菜单映射 + 变更记录
- 修改文件 → 在变更记录中注明
- 新增 CLI 命令 → 同步到 Web 面板
