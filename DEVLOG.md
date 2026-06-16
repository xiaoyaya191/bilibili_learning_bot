# 开发日志 (DEVLOG)

> bilibili_learning_bot — 开发记录与架构说明
> 最后更新: 2026-06-11

## 项目概述

`new_agent.py` (~15000行) 是核心单体机器人，内含：
- **AgentBrain** — 主调度器
- **BiliClient** — B站 API 封装层
- **CommentInteractionManager** — 评论拉取与回复管理
- **PrivateMessageManager** — 私信轮询与上下文管理
- **EntertainmentModule** — 运势/段子/热梗/小游戏

`web_panel.py` 提供 Flask Web 控制台（端口 7860）。
`xingye_bot/` 包提供模块化组件：LLM、状态、记忆、日记、进化等。
