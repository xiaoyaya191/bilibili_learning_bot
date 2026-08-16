# BiliNote inspired API / 实现参考

> 目标：供 `G:\code\work\测试` 后续继续实现浏览器插件、字幕直抓、多平台等功能时参考。当前已落地章节锁定、思维导图、笔记风格、RAG 问答、多版本记录、模型预设切换。

## 已接入到本项目的 Web API

### 1. 单文件思维导图导出
- 方法：`POST /api/export/mindmap`
- Body：`{"rel_path":"分类/文件.md"}`
- 返回：`{"ok":true,"path":"...mindmap.html"}`
- 实现：`services/mindmap_export.py` + `web_panel.py`

### 2. 批量思维导图导出
- 方法：`POST /api/export/mindmap/all`
- Body：`{}`
- 返回：`{"ok":true,"total":N,"outputs":[...]}`
- 说明：扫描 `KnowledgeBase/**/*.md`，跳过 `.versions` 与 `.html_exports`。

### 3. RAG 知识库问答
- 方法：`POST /api/knowledge/ask`
- Body：`{"question":"这里写问题"}`
- 返回：`{"ok":true,"answer":"...","sources":[...]}`
- 实现：`services/rag_qa.py`。
- 评论区入口：待机模式下 `@bot 知识库/全库/查资料/以前学过 ...` 会触发问答；`@bot 总结...` 仍触发当前视频总结。

## B站字幕直抓 API（浏览器插件可借鉴）

### 1. 获取视频 CID
```http
GET https://api.bilibili.com/x/player/pagelist?bvid={BV号}
```
- 关键字段：`data[0].cid`

### 2. 获取字幕列表（推荐）
```http
GET https://api.bilibili.com/x/player/wbi/v2?cid={cid}&bvid={bvid}&fnver=0&fnval=4048
```
- 关键字段：`data.subtitle.subtitles[].subtitle_url` 或 `subtitle_url_v2`
- 可能遇到 412 风控；本项目 fallback 到 `x/player/v2`。

### 3. 获取字幕列表（fallback）
```http
GET https://api.bilibili.com/x/player/v2?cid={cid}&bvid={bvid}
```

### 4. 下载字幕 JSON
```http
GET https:{subtitle_url}
```
- 关键字段：`body[].content`
- 插件优势：在 B站页面上下文中携带用户 Cookie，能更稳定访问需要登录的 AI 字幕。

## B站 @我通知 / 评论回复 API

### 1. 拉取 @我通知
```http
GET https://api.bilibili.com/x/msg/at?pn=1&ps=20
```
- 当前项目：`brain/standby.py::_get_at_notifications()`
- 关键字段：`data.items[].item.subject_id` / `business_id` / `content`

### 2. aid 转 BV
```http
GET https://api.bilibili.com/x/web-interface/view?aid={aid}
```
- 关键字段：`data.bvid`

### 3. 发表评论回复
```http
POST https://api.bilibili.com/x/v2/reply/add
Content-Type: application/x-www-form-urlencoded
```
- 参数：`oid`（视频 aid）、`type=1`、`root`、`parent`、`message`、`plat=1`
- 需要 Cookie + CSRF（项目现有 cookie 流程已封装）。

## BiliNote 源码可借鉴方向

- 仓库：`https://github.com/JefferyHcool/BiliNote`
- 可借鉴但本轮未直接复制源码（AGPL-3.0，注意许可证兼容）：
  1. `章节锁定 + 内容追加` 的提示词组织方式
  2. 浏览器插件侧边栏交互：Markdown / mindmap / AI 问答三栏
  3. Function Calling 查阅原文：可在 `services/rag_qa.py` 后续加入 `open_note(path)` / `search_note(query)` 工具调用
  4. 多转写后端抽象：Fast-Whisper / Groq / BCut 可作为 `asr.backend` 扩展

## 后续不属于本轮落地的全平台能力

- YouTube：`youtube-transcript-api`（字幕）+ `pytube` 或 `yt-dlp`（元数据/下载）
- 抖音/快手：建议优先插件 Cookie/页面上下文抓取，公开接口稳定性较低
- 小宇宙：播客 RSS / 页面音频 URL + ASR
- 统一架构：按路线图新增 `services/platforms/base.py` 的 `PlatformAdapter`，再逐步迁移 B站现有逻辑。
