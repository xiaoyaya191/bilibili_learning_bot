# 开发日志 (DEVLOG)

> bilibili_learning_bot — 开发记录与架构说明  
> 最后更新: 2026-06-11

---

## 项目概述

`new_agent.py` (~7190行) 是核心单体机器人，内含：
- **AgentBrain** — 主调度器，管理推荐流浏览、视频理解、评论互动、私信回复、日记等
- **BiliClient** — B站 API 封装层，处理 credential、弹幕、历史上报等
- **CommentInteractionManager** — 评论拉取与回复管理
- **PrivateMessageManager** — 私信轮询与上下文管理
- **EntertainmentModule** — 运势/段子/热梗/小游戏
- **PersonaManager** / **SkillManager** — 人格系统与技能日志

`web_panel.py` 提供 Flask Web 控制台（端口 7860），功能对应 CLI 机器人。

`xingye_bot/` 包提供模块化组件：LLM、状态、记忆、日记、进化、安全、视频模式等。

---

## 最近修复 (2026-06-13)

### 全面项目完善

**Emoji 编码清理**：
- `asr_engine.py`：所有 print 语句和注释中的 emoji 替换为 ASCII 标签（`[ASR]`、`[WARN]` 等），避免 Windows GBK 终端崩溃
- `new_agent.py` 行56：`❌` → `[ERROR]`
- `web_panel.py` 行21：`❌` → `[ERROR]`；行1192：emoji 免责声明 → 英文文本
- `psycho_engine.py` `__main__` 测试代码：所有 emoji print → 英文标签

**依赖文件补充**：
- `requirements-optional.txt`：funasr、torch、torchaudio、whisper 等可选依赖
- `requirements-dev.txt`：pyright、ruff、pytest 等开发依赖

**临时文件清理**：
- 删除 `_test_asr_download.py`、`_test_asr_standalone.py`、`_test_asr_quick.py`
- 删除 `_asr_result.json`、`_asr_test_output.txt`
- 删除 `_extract_html.py`

**.gitignore 完善**：
- 新增 `model/`、`*.bak`、`backup_*/`、`_test_*.py` 等规则

**ASR 引擎健壮性**（本轮确认通过）：
- FunASR PATH 注入、`_ffmpeg_ok()` 实际验证、`Path | str` 类型接受、emoji 清理

### 1. BiliClient._load_credential() — credential 自赋值

**问题**: 方法仅 `return Credential(...)`，不设置 `self.credential`，调用方需手动 `self.credential = self._load_credential()`。且 `self.uid` 从未自动设置。

**修复** (行 ~4594-4603):
```python
self.credential = Credential(
    sessdata=sessdata, bili_jct=bili_jct,
    buvid3=buvid3, dedeuserid=dede
)
try:
    self.uid = int(dede) if dede else None
except Exception:
    self.uid = None
return self.credential
```
现在 `_load_credential()` 内部直接设置 `self.credential` + `self.uid`，调用方无需再手动赋值。

### 2. BiliClient.like_danmaku() — credential 兜底 + csrf 检查

**问题**:
- 若 `self.credential` 为 None，`Video(bvid=bvid, credential=self.credential)` 会导致 `bilibili_api` 内部 `raise_for_no_sessdata()` 抛异常
- 降级 httpx 路径缺少 `bili_jct` (csrf) 空值检查

**修复** (行 ~4985-5021):
- 入口处自动检测 `self.credential`，若为 None 调 `_load_credential()`
- `bilibili_api` 路径失败时 `pass` 降级到 httpx
- httpx 降级路径增加 `csrf` 空值检查，返回友好错误

### 3. BiliClient.send_danmaku() — Danmaku 对象构造

**问题**:
- `await v.send_danmaku(text)` 传字符串给期望 `Danmaku` 对象的方法，必抛 `ArgsException`
- 同样缺少 credential 兜底

**修复** (行 ~5023-5038):
- 导入 `from bilibili_api.utils.Danmaku import Danmaku` (行 46)
- 构造 `dm = Danmaku(text=text, dm_time=dm_time)` 再传给 `v.send_danmaku(danmaku=dm)`
- 入口自动检测 `self.credential`

### 4. buvid3 格式校验

**修复** (行 ~4569-4588):
新增 buvid3 UUID 格式校验（`UUID+infoc`），畸形的自动用 `uuid.uuid1() + "infoc"` 重新生成并写回 cookie 文件。避免 B站 永久返回 `-799`。

### 5. UP 主关注「关注即认可」强化 — 评分门槛 + 印象积累

**问题**: 旧 `maybe_follow_up()` 仅依赖概率，评分到线 + 随机命中即可关注，可能关注评分平庸或只看过一次的 UP。

**修复** (行 ~6412-6473, ~5683-5710):
- **新增配置变量**:
  | 变量 | 默认值 | 说明 |
  |------|--------|------|
  | `UP_FOLLOW_MIN_SCORE` | 7.0 | 最低评分门槛，低于此值直接拒绝 |
  | `UP_FOLLOW_MIN_IMPRESSIONS` | 2 | 最少正面印象次数（多看再关） |
  | `UP_FOLLOW_EXCEPTIONAL_SCORE` | 8.5 | 特别优秀，首看即可关注 |
  
- **新增 `record_up_impression()`**: 每次观看 UP 主视频时自动记录 views / total_score / avg_score，为关注决策提供数据基础。

- **`maybe_follow_up()` 重写**:
  1. 评分 < `UP_FOLLOW_MIN_SCORE` → 直接拒绝（不因概率到了就关注）
  2. 已存在 `followed` 标志 → 不重复关注
  3. 观看次数 < `UP_FOLLOW_MIN_IMPRESSIONS` 且非特别优秀 → 拒绝
  4. 特别优秀（≥ `UP_FOLLOW_EXCEPTIONAL_SCORE`）→ 跳过印象积累，直接进入概率关
  5. 概率公式增加印象奖励因子：`基础 × 评分因子 × min(views/min_impressions, 2.0)`

- **`remember_up`/`set_up_uid`/`favorite_up`** 增加 `followed: False` 默认字段
- **内存迁移**: `_load_memory()` 自动补全旧数据缺失的 `followed` 字段
- **菜单扩展**: 新增 8/9/10 号选项，可交互调整三个新参数

---

## 调用链

```
AgentBrain.initialize_login()
  └→ self.bili._load_credential()    # 现在自动设 self.credential + self.uid
  
AgentBrain.maybe_like_danmaku(bvid, danmaku_list, cid)
  └→ self.bili.like_danmaku(dmid, cid, bvid)
       ├→ Video.like_danmaku(dmid, cid)   [bilibili_api 路径]
       └→ httpx POST /x/v2/dm/thumbup/add [降级路径]
  
AgentBrain.maybe_send_danmaku(bvid)
  └→ self.bili.send_danmaku(bvid, text)
       └→ Danmaku(text, dm_time) → Video.send_danmaku(danmaku=dm)
```

---

## 项目架构

```
bilibili_claw/
├── new_agent.py          # 核心机器人 (~7190行)
├── web_panel.py          # Flask Web 控制台 (端口 7860)
├── config.example.json   # 示例配置模板
├── requirements.txt      # Python 依赖
├── 启动网页版.bat         # Windows 启动脚本
│
├── xingye_bot/           # 模块化子包
│   ├── __init__.py
│   ├── llm.py            # 多模型 OpenAI 兼容客户端
│   ├── state.py          # BotState 运行时状态
│   ├── settings.py       # 配置加载
│   ├── video_modes.py    # 四种视频理解模式
│   ├── bilibili_ops.py   # B站操作封装
│   ├── memory.py         # 语义记忆 (embeddings)
│   ├── diary.py          # 日记管理
│   ├── evolution.py      # 自我进化
│   ├── safety.py         # 内容安全
│   ├── skills.py         # 技能管理
│   ├── proactive.py      # 主动动态
│   ├── background.py     # 后台任务
│   ├── owner.py          # 所有者识别
│   └── video_asr.py      # 视频 ASR
│
├── Data/                 # 运行时数据 (gitignore)
│   ├── config.json       # 实际配置 (含API Key)
│   ├── bilibili_cookies.json  # B站 Cookie
│   ├── interests.json    # 兴趣标签
│   ├── bot_runtime_state.json
│   ├── user_profiles.json
│   ├── mood_state.json
│   ├── personas.json
│   ├── bot_diary.json
│   └── ...
│
├── KnowledgeBase/        # 个人知识库 (gitignore)
│   ├── knowledge_metadata.json
│   └── 分类/.../*.md
│
├── bot_journal.md        # 机器人操作日志
├── README.md             # 项目说明
├── SECURITY.md           # 安全说明
├── DEVLOG.md             # 本文件
└── *.zip                 # 分享打包
```

---

## 关键配置项 (Data/config.json)

```jsonc
{
  "danmaku": {
    "enabled": true,           // 弹幕互动总开关
    "read_prob": 0.3,          // 观看视频后读取弹幕的概率
    "like_prob": 0.15,         // 点赞单条弹幕的概率
    "max_daily_danmaku_likes": 10,  // 每日最大点赞数
    "send_prob": 0.03,         // 发送弹幕的概率
    "max_daily_send": 2        // 每日最大发送数
  },
  "dry_run": true,             // 干运行模式 (只记录不执行)
  "video": { "mode": "smart" } // 视频理解模式
}
```

---

## 📌 UP主关注设计理念

**核心原则：关注 = 认可，不是抽奖。只关注真正有价值、你真心喜欢的 UP 主。**

### 实现机制（2026-06-11 已强化）

| 条件 | 说明 |
|------|------|
| **评分门槛** | `UP_FOLLOW_MIN_SCORE`（默认 7.0）。评分低于此值直接拒绝，不进入候选池 |
| **印象积累** | `UP_FOLLOW_MIN_IMPRESSIONS`（默认 2）。必须看够 N 次才可能触发关注 |
| **特别优秀豁免** | `UP_FOLLOW_EXCEPTIONAL_SCORE`（默认 8.5）。首次观看评分达此线即可直接关注 |
| 已关注过滤 | `followed` 标志避免重复关注 |
| 每日上限 | `UP_FOLLOW_MAX_DAILY`（默认 3） |
| 冷却时间 | `UP_FOLLOW_COOLDOWN_MINUTES` 分钟内不重复关注 |
| 喜爱系统 | `mark_up_like()` 标记喜爱 UP，优先浏览其视频 |
| 概率公式 | `基础概率 × min(评分/5, 2.0) × min(观看次数/最少印象, 2.0)` |

**`record_up_impression()`** 记录每次观看的 views / total_score / avg_score，构成关注决策的数据基础。

**设计约束（已落地）：**
- ✅ 评分 ≥ `UP_FOLLOW_MIN_SCORE` 才进入候选池（不因概率到了就关注平庸 UP）
- ✅ 需积累多次正面印象才触发关注（默认至少 2 次）
- ✅ 特别优秀内容首看即关注（≥ 8.5 分）
- ✅ 关注列表宁缺毋滥，保持小而精

---

## 弹幕模块实现细节

### 弹幕读取 (get_danmakus)
- 使用 B站 V1 XML 接口: `GET /x/v1/dm/list.so?oid={cid}`
- 正则解析 `<d p="...">` XML 标签
- 返回 `id_str` (字符串ID，用于点赞) + `text` + `dm_time` 等字段
- 只取弹幕池 0 (普通弹幕)，过滤池 1 (字幕弹幕)

### 弹幕点赞 (like_danmaku)
- 优先 `bilibili_api.Video.like_danmaku(dmid=id_str, cid=cid)`
- 降级 `httpx.POST /x/v2/dm/thumbup/add` (需 csrf=bili_jct)
- `dmid` 必须是 `id_str` (字符串)，不是整数 id

### 弹幕发送 (send_danmaku)
- 使用 `bilibili_api.Video.send_danmaku(danmaku=Danmaku(...))`
- AI 生成弹幕文本 (≤20字，B站风格)
- 概率控制 + 每日上限

---

## 已知限制

1. **弹幕点赞/发送依赖有效 SESSDATA** — 无 cookie 时无法操作
2. **-799 风控** — 频繁请求会触发，已实现指数退避重试
3. **buvid3 格式** — 必须是 `UUID+infoc`，否则永久 -799
4. **Android/Termux 运行** — ffmpeg 抽帧需要额外安装
5. **弹幕发送仅支持普通弹幕** — 不支持高级弹幕/彩色弹幕

---

## 依赖

```
bilibili-api-python  # B站 API SDK
httpx                # HTTP 客户端 (bilibili_api 底层)
openai               # OpenAI 兼容 SDK
colorama             # 终端彩色输出
qrcode               # 二维码生成 (登录)
requests             # HTTP 请求 (部分场景)
```

---

## 安全提醒

- ❌ 不要提交 `Data/`、`KnowledgeBase/`、`__pycache__/`
- ❌ 不要在示例配置中写入真实 API Key / Cookie
- ❌ 自动操作建议保持 `dry_run=true`
- ❌ 频繁弹幕点赞/发送可能触发 B站 风控
