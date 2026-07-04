# Bilibili AI Learning Bot - Neko Plugin

将 `bilibili_learning_bot` 封装为 Neko 插件。

## 安装

1. 将 `bilibili_learning` 文件夹复制到 Neko 的插件目录：
   ```bash
   cp -r bilibili_learning /path/to/neko/plugin/plugins/
   ```

2. 确保原项目的 Python 包在 PYTHONPATH 中，或者将原项目源码复制到插件目录内。

3. 重启 Neko，插件会自动加载。

## 使用方法

### 通过 Neko API 调用

```python
# 启动AI学习
POST /api/plugin/bilibili_learning/start_learning

# 停止学习
POST /api/plugin/bilibili_learning/stop_learning

# 分析视频
POST /api/plugin/bilibili_learning/analyze_video
{"url": "https://www.bilibili.com/video/BVxxxx"}

# 生成视频网页
POST /api/plugin/bilibili_learning/video_to_html
{"url": "https://www.bilibili.com/video/BVxxxx", "style": "claude"}
```

### LLM Tool Calling 支持

插件注册了以下 LLM 工具，AI 可以直接调用：
- `start_learning` - 启动学习
- `stop_learning` - 停止学习
- `analyze_video` - 分析视频
- `video_to_html` - 生成网页
- `send_comment` - 发送评论
- `reply_private` - 回复私信

## 配置

通过 Neko 的插件thers面板或 API 修改 `config`：

```json
{
  "bilibili_cookie": "",
  "openai_api_key": "",
  "model": "gpt-4o-mini",
  "learning_interval": 30,
  "comment_enabled": true,
  "private_msg_enabled": true
}
```

## 目录结构

```
bilibili_learning/
├── __init__.py          # 插件主文件
├── plugin.toml          # 插件配置
├── static/
│   └── index.html       # 插件 UI
└── README.md            # 本文件
```

## Web 管理面板

插件保留了原项目的完整 Flask Web 面板，可通过以下方式启动：

```python
# 通过 Neko API 启动面板
POST /api/plugin/bilibili_learning/open_web_panel
# 返回: {"success": true, "url": "http://localhost:<port>"}
```

或者让 AI 调用 LLM Tool：`open_web_panel`

面板功能包括：仪表盘、机器人启停、B站扫码登录、配置编辑、实时日志、人格管理、评论日志、用户画像、记忆知识库、日记进化等。

## 与原项目的关系

此插件基于 [bilibili_learning_bot](https://github.com/xiaoyaya191/bilibili_learning_bot) v3.0.0 封装：
- 保留核心功能：自动刷视频、智能理解、评论互动、知识沉淀
- 通过 Neko SDK 暴露为标准插件接口
- 利用 Neko 的进程隔离、生命周期管理、消息总线等特性

## 注意

- 需要确保 `bilibili_learning_bot` 的 Python 依赖已安装
- `AgentBrain` 等核心模块需要正确导入
- B站账号登录请通过插件配置或凭据接口传入
