# 🔥 bilibili_learning_bot v2.0.3 — 融合版

> 创建时间：2026-06-15  
> 基于：`bilibili_learning_bot`（主力版）为底座  
> 融合：`bot2.0` 的 web_panel 增强 + `2.0.0` 的 xingye_bot 完整向量引擎

## 📦 融合说明

| 来源 | 贡献 | 说明 |
|------|------|------|
| **bot** (底座) | 完整模块化架构 | services/ 5文件、core/config.py、xingye_bot/ 17文件、15,100行核心 |
| **bot2.0** | web_panel 增强 | 安全关键词面板、ASR仪表盘、登录鉴权、线程安全JSON、恢复出厂两步确认 |
| **bot2.0** | kb_search 异步优化 | `update_entry` 改为 async/await，支持异步 embedding |
| **2.0.0** | xingye_bot 向量引擎 | kb_search.py (语义搜索)、memory.py (语义记忆)、llm.py (Embedding API) |

## ✨ v2.0.3 新特性

### 1. 🛡️ Web 面板安全增强
- **关键词安全校验面板**：可视化管理敏感关键词，AI 自动过滤
- **登录鉴权系统**：首次设置用户名/密码，后续访问需登录
- **两步确认恢复出厂**：防止误操作，需输入随机令牌
- **API Key 脱敏导出**：备份时自动隐藏敏感凭证

### 2. 🎙️ ASR 仪表盘
- 控制面板显示 ASR 语音识别状态
- 实时开关、后端切换

### 3. 🧵 线程安全 JSON 存储
- `JsonStore` 类：原子写（临时文件+rename）+ 文件锁
- 防止并发写入导致的数据损坏

### 4. 🧠 向量检索引擎异步优化
- `kb_search.py` 的 `update_entry` 改为 `async def`
- embedding 调用使用 `await`，不再阻塞事件循环

## 📊 文件统计

| 文件 | 行数 | 来源 |
|------|------|------|
| `new_agent.py` | 15,100 | bot (底座) |
| `web_panel.py` | 2,317 | bot2.0 (增强) |
| `services/managers.py` | 378 | bot |
| `services/utils.py` | 221 | bot |
| `services/agent_service.py` | 103 | bot |
| `services/interaction_service.py` | 411 | bot |
| `services/reply_safety.py` | 54 | bot |
| `xingye_bot/kb_search.py` | ~11,200 | bot2.0 (异步优化) |
| `xingye_bot/` (17文件) | ~130,000 | bot (完整向量引擎) |

## 🔄 与各版本的差异

| 特性 | bot | 2.0.0 | 2.1.0 | bot2.0 | **2.0.3** |
|------|-----|-------|-------|--------|-----------|
| 模块化 services/ | ✅ | 🟡 | 🟡 | ❌ | ✅ |
| xingye_bot 向量引擎 | ✅ | ✅ | ✅ | ✅ | ✅ |
| web_panel 关键词安全 | ❌ | ❌ | ❌ | ✅ | ✅ |
| web_panel ASR仪表盘 | ❌ | ❌ | ❌ | ✅ | ✅ |
| web_panel 登录鉴权 | ❌ | ✅ | ✅ | ✅ | ✅ |
| web_panel 线程安全JSON | ❌ | ❌ | ❌ | ✅ | ✅ |
| web_panel 两步确认出厂 | ❌ | ❌ | ❌ | ✅ | ✅ |
| kb_search 异步优化 | ❌ | ❌ | ❌ | ✅ | ✅ |
| 代码行数 | 15,100 | 16,536 | 15,580 | 26,046 | ~15,410 |
| 代码重复 | 无 | services重复 | 无 | 9函数×4 | 无 |

## 🚀 启动方式

```bash
cd /storage/emulated/0/.1phone1/bilibili_learning_bot-2.0.3
python new_agent.py
```

Web 面板: `http://localhost:8765`
