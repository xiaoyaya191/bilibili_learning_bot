# BiliLearn MCP Server

让 AI 助手（Claude Desktop / Cherry Studio / TRAE / Cursor 等）直接读取 B 站视频的**元数据、字幕、弹幕、评论**，并一键生成**视频文案/口播稿**，方便后续做选题、二创和文案创作。

复用项目已有的 `api` 层（BiliClient + 字幕抓取）与 AI 配置，与机器人本体行为一致、风控友好。

---

## 提供的工具

| 工具 | 说明 |
|------|------|
| `bili_video_material` | 提取视频文案素材：元数据 + 字幕全文 + 弹幕精选 + 热门评论，输出 Markdown |
| `bili_search_videos` | 搜索 B 站视频，返回结构化列表（标题/BV/UP/播放量/时长） |
| `bili_video_to_script` | 根据视频素材用 AI 生成视频文案（口播/解说/种草/盘点/故事/干货） |

## 快速开始

### 方式一：MCP 客户端（推荐）

在支持 MCP 的客户端中新增一个 stdio 类型 Server，配置为：

- **命令**：`C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe`
- **参数**：`-m mcp_server`
- **工作目录**：`g:\code\work\bilibili_learning_bot-3.1.3`

或在需要 `.bat` 入口时，直接使用根目录的 `run_mcp.bat`。

> 注意：`bili_video_to_script` 会读取面板配置的 AI 接口（`api.unified_base_url` / `api.unified_api_key` / `model_brain`），请先在面板配置好 AI 服务。

### 方式二：命令行自测

```bash
python -m mcp_server
```

## 项目结构

```
mcp_server/
├── __init__.py      # 版本信息
├── __main__.py      # python -m mcp_server 入口
├── server.py        # MCP Server（stdio 传输，注册 3 个工具）
├── bili.py          # B 站数据提取（复用项目 api 层）
└── script.py        # AI 文案生成（复用项目 AI 配置）
run_mcp.bat          # Windows 启动器
```

## 免责声明

本项目仅供个人学习交流使用。B 站接口及服务条款可能随时变更，本项目基于公开接口实现，不保证长期可用。提取的字幕、弹幕、评论等内容的版权归原作者与 B 站所有，仅限个人阅读学习，请勿转载、二次分发、商用。使用即视为同意以上条款。