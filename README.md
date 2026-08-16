# bilibili_learning_bot

> **B站 AI 学习互动机器人** — AI 自动刷视频、学知识、评论互动、私信回复、自我进化，内置 Web 管理面板，支持一键打包 Windows EXE。
>
> 版本: **3.1.3** | License: MIT | 项目文档: https://bxya.app/

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 📺 **智能视频浏览** | AI 驱动 B站推荐流浏览，自动判断内容价值（评分 / 收藏 / 投币 / 点赞） |
| 📚 **知识库系统** | 自动归档高质量视频，3 层分类 + 语义检索 + 复习回顾 |
| 💬 **评论互动** | 真实/模拟评论模式，AI 深度回复，支持图片分析 |
| 📩 **私信处理** | 自动回复粉丝私信，持久上下文 + 长期记忆，支持节奏控制 |
| 🛡️ **黑名单/白名单** | 黑名单用户不响应且自动隐藏；白名单优先回复，面板可视化管理 |
| 📡 **实时监听** | 独立监听引擎，只盯私信 + 评论实时 AI 回复，不刷视频不耗精力 |
| 🔔 **@通知响应** | 视频下评论 "@bot 总结这个视频"，自动识别并总结回复 |
| 🧬 **日记与自我进化** | 行为日志 + AI 自我反思 + 人格动态进化 |
| 🎙️ **ASR 语音识别** | 视频语音转文字（FunASR / Whisper，可选安装） |
| 🤖 **Agent 技能系统** | 自主规划目标 → 搜索 B站 → 看视频 → 总结知识，全自动闭环 |
| 🎓 **知识辅导** | AI 讲解 / 问答 / 二次创作 / 生成 HTML 学习卡片 |
| 🔍 **AI 历史搜索** | 记录 AI 每次搜索的内容/来源/观看数，支持手动补录与删除 |
| 🎲 **节目效果模式** | 实验性随机开关：兴趣判定随机翻转、评分抖动、提示词注入（默认关闭） |
| 🎨 **视频→网页** | 视频生成 PPT 风格 HTML，19 种视觉风格，支持 Claude 主题 |
| 📊 **思维导图 & Word 导出** | 视频一键导出 `.mindmap.html` 与 `.docx` 文档 |
| 🔍 **深度研习** | 长视频多章节深研，证据链式总结（`services/deep_dive.py`） |
| 🎯 **智能兴趣引擎** | 多维度评分 + 同义词 + 排除词 + 灵光一闪探索 + PsychoProfile 同步 |
| 😊 **AI 心情系统** | 动态心情影响互动风格，支持自定义 |
| 🏆 **干货点赞回顾** | 定期回顾收藏的干货视频，AI 复习（`services/like_review.py`） |
| 🔔 **待办与提醒** | 桌面通知 + 提醒联动搜索（AI 识别私信提醒 + 手动创建） |
| 🛡️ **安全审查** | 关键词过滤 + 政治敏感拦截 + 提示词注入防护 + 操作风控 |
| 🔄 **备用 API 降级** | 主 API 连续失败自动切换备用提供商 / 备用模型 |
| 🖥️ **Windows EXE** | 一键打包免 Python 运行（托盘 + 浏览器面板） |
| 🌓 **Web 面板** | Claude 设计风格，亮/暗双主题，40+ 分区，中/英/俄三语 |
| 🆕 **新手教程** | 首次进入自动展开在系统仪表盘，6 步带真实完成状态检测 |
| 🐳 **Docker 部署** | 支持 Docker / docker-compose 一键部署 |
| 💰 **投币预算管控** | 每日/每小时投币上限 + 投币冷却 + 评分阈值；评论三连默认关闭，开启后受审核队列约束（`services/coin_budget.py`） |
| 🎲 **拟人随机搜索** | 三种模式（可控拟人 / 随机放飞 / 关闭），自定义提示词 + 随机种子，综合记忆、私信、评论、观看历史生成真人式搜索词（`services/human_search.py`） |
| 🎯 **学习小目标** | 用户或 AI 设定限时学习目标，定向刷同类视频；重复视频默认不跳过（复习加深记忆）（`services/mini_goal.py`） |
| 👥 **UP主关注画像** | 每个关注 UP 的标签、内容笔记、质量评估与第一印象追踪 |
| 👤 **我的分区** | 面板账号改密 / B站账号登录 / AI 认主人（绑定主人 UID + 昵称，互动语气更亲近） |
| 📤 **知识库导出** | 单条 / 全库导出，系统级路径选择对话框；独立 MCP 服务分区可接入其他 Agent |
| 🔎 **深度搜索配置** | 独立分区配置触发条件与提示词，默认不随机触发 |
| 📱 **Termux 支持** | Android 单文件安装器 + 全局命令启动 |

---

## 📊 v3.0.2 → v3.1.3 版本对比

| 维度 | v3.0.2 | v3.1.3（当前） |
|------|--------|----------------|
| **代码规模** | 77 个 Python 文件 / ~34k 行 | 226 个 Python 文件 / ~62k 行（另面板前端 ~6.8k 行） |
| **Windows 桌面版** | ❌ 仅源码运行 | ✅ `desktop_app.py` 一键打包 EXE（托盘图标 + 自动开浏览器） |
| **数据目录** | 项目内 `Data/`（打包/升级易丢） | ✅ `%LOCALAPPDATA%\BiliLearn`，支持面板内迁移位置，打包产物零隐私数据 |
| **Web 面板** | 基础控制页 | ✅ 40+ 分区（机器人控制 / 实时监听 / 学习小目标 / 深度搜索 / UP主关注 / 我的 / MCP 服务 / 备份还原…） |
| **新手引导** | ❌ | ✅ 仪表盘内嵌 6 步新手教程，真实配置状态检测（跳转≠完成） |
| **人格管理** | 简单 prompt 配置 | ✅ Web 可视化多人格（创建 / 编辑 / 激活 / 删除），key 与显示名双匹配 |
| **服务模块** | 12 个 | ✅ 29 个（深度研习、测验生成、思维导图、Word 导出、投币预算、拟人搜索、小目标、点赞回顾、提醒、RAG 问答…） |
| **监听引擎** | 基础轮询 | ✅ 上下文合并、超时跳过、`-509` 退避、网页日志可视化 |
| **开放平台桥接** | ❌ | ✅ `ob_bridge/`（开放平台鉴权、AB 测试、审计） |
| **备份与恢复** | 手动导出 | ✅ 分组备份（设置 / 记忆 / 知识 / 产物）+ 脱敏/完整双模式 + 恢复 |
| **测试** | 43 个 pytest | ✅ 337 个 pytest 全量通过 |
| **稳定性修复** | — | 人格持久化、Cookie 校验、风控、多实例锁、AI 降级冷却、跨进程日志锁、原子写入重试 |

> 详细演进见 [CHANGELOG.md](CHANGELOG.md)。

---

## 🧱 项目结构

```
├── main.py               # 🚀 主入口（CLI 交互菜单 + 自动化启动）
├── desktop_app.py        # 🖥️ Windows EXE 启动器（托盘 + 面板）
├── web_panel.py          # 🌐 Flask Web 管理面板（后端）
├── web_panel.html        # Web 面板模板（Claude 风格，亮暗双模式，中英俄三语）
├── install.sh            # 📱 手机端(Termux)单文件安装器（镜像拉取 + 全局命令）
├── deploy_termux.sh      # 📱 Termux 交互式部署脚本
├── start.sh              # 🐧 Linux/macOS 启动脚本
├── BiliLearn.spec        # 📦 PyInstaller 打包配置
├── build_windows_exe.bat # 📦 一键打包脚本（Windows）
│
├── api/                  # 🔌 B站 API 层（客户端 / 登录 / 字幕 / 节流）
├── brain/                # 🧠 核心大脑（Mixin 组合：主循环 / 视频理解 / AI 调用 / 会话）
├── cli/                  # 💻 命令行菜单
├── core/                 # ⚙️ 配置 / 全局变量 / 用户数据路径 / 恢复出厂 / 节目效果
├── knowledge/            # 📚 知识库（分类 / 搜索 / 浏览 / 复习 / 自定义）
├── persona/              # 🎭 人格 + 心理画像引擎
├── security/             # 🛡️ 内容安全审查
├── services/             # 🔧 29 个服务（深研 / 测验 / 思维导图 / Word / 投币预算 / 拟人搜索 / 小目标 / 兴趣引擎 / RAG…）
├── ob_bridge/            # 🌉 开放平台桥接（鉴权 / AB 测试 / 审计）
├── xingye_bot/           # 🤖 扩展组件（LLM / 状态 / 记忆 / 进化 / ASR / 网格帧）
├── utils/                # 🛠 通用工具（托盘 / 启动器 / 原子存储 / 锁）
├── templates/claude/     # 🎨 Claude 设计系统模板 + 7 个参考页
├── tests/                # 🧪 337 个 pytest 测试
├── app-icons/            # 应用图标
└── dev_refs/             # 📖 二次开发参考文档
```

---

## 🚀 快速开始

### 💻 桌面 / 服务器

**1️⃣ 安装依赖**

```bash
pip install -r requirements.txt

# 推荐安装 ffmpeg（视频帧提取）
# apt install ffmpeg        # Linux
# pkg install ffmpeg        # Termux
```

> ⚠️ B站 API 包名是 **`bilibili-api-python`**（不是 `bilibili-api`）。若之前装过旧包：
> ```bash
> pip uninstall bilibili-api -y
> ```

**2️⃣ 配置**

```bash
cp config.example.json Data/config.json   # 源码运行
# 编辑填入 API Key（统一 API 或任意 OpenAI 兼容端点）
```

> Web/EXE 版会自动在 `%LOCALAPPDATA%\BiliLearn` 创建数据目录，无需手动复制。

**3️⃣ 启动**

| 方式 | 命令 |
|------|------|
| **CLI 交互菜单** | `python main.py` |
| **Web 管理面板** | `python web_panel.py` → http://localhost:18083 |
| **Windows EXE** | 运行 `BiliLearn Web.exe`（自动开浏览器 + 托盘） |
| **Docker** | `docker-compose up -d` |

### 📱 手机端（Android Termux）

**一键安装**（自动测速 GitHub 镜像拉取源码）：

```bash
pkg install curl -y
curl -O https://raw.githubusercontent.com/xiaoyaya191/bilibili_learning_bot/main/install.sh
bash install.sh
```

安装流程：询问安装 → 自选路径（默认 `~/bililearn`）→ 免责声明输入「我同意」→ 镜像拉取源码 → 装依赖 → 注册全局命令。

**装完直接启动**（三选一，效果相同）：

```bash
bililearn              # 或
abiligent              # 或
bilibili_learning_bot
```

> 也可用 `deploy_termux.sh`（交互式部署）或源码目录内 `bash install_termux.sh`。

### 4️⃣ 首次使用

首次打开面板，**系统仪表盘**会自动展开新手教程（6 步）：连接 AI → 登录 B 站 → 设置兴趣 → 决定互动审核 → 设置刷视频方式 → 启动观察。每步显示**真实完成状态**——只是跳转过去不算完成，配置真正生效才打勾；全部完成后教程自动收起，之后可从操作中心「新手教程」按钮随时重开。

1. 「配置编辑」填 API Key，「B站登录」扫码
2. 「机器人控制」→ 启动机器人
3. 「人格工作室」配置 AI 人格
4. 或 CLI：`python main.py` → 按 `3` 登录 → 按 `1` 启动

---

## 📦 Windows EXE 打包教程

项目已内置完整的 PyInstaller 配置，**无需手写命令行**：

### 前置条件

```bash
pip install pyinstaller
```

### 一键打包

双击运行（或命令行执行）：

```bat
build_windows_exe.bat
```

等价命令：

```bash
python -m PyInstaller --noconfirm --clean BiliLearn.spec
```

产物：`dist/BiliLearn Web/BiliLearn Web.exe`（绿色免安装，复制整个文件夹即可分发）。

### spec 配置要点（源码可抄）

`BiliLearn.spec` 里解决了以下打包坑：

| 坑 | 解法 |
|----|------|
| **入口选谁** | 入口是 `desktop_app.py`（不是 `main.py` / `web_panel.py`）：它负责托盘、自动开浏览器，并按需以子模式拉起 bot / monitor / standby |
| **数据文件** | `datas` 显式带上 `web_panel.html`、`config.example.json`、`VERSION`、`app-icons/`、`templates/` |
| **Flask 版本元数据** | `copy_metadata('flask') + copy_metadata('werkzeug')`，否则 Python 3.13 下 Flask 启动报错 |
| **bilibili-api 动态导入** | `hiddenimports` 显式声明 `bilibili_api.clients.HTTPXClient` 等，否则冻结版二维码登录/视频分析失败 |
| **托盘** | `pystray._win32` 显式 hiddenimport，否则窗口版无托盘 |
| **子进程模块** | `main`、`brain.monitor`、`brain.standby` 显式 hiddenimport，供 desktop_app 以 `runpy` 拉起 |
| **排除 ML 巨物** | `excludes` 排除 torch / transformers / onnxruntime / faiss 等可选依赖，否则打包体积 2GB+ 且启动必崩 |
| **窗口模式** | `console=False`（无黑窗）；子进程日志由面板捕获写入 `%LOCALAPPDATA%\BiliLearn\Data` |

### 打包后常见报错速查

| 报错 | 原因与解法 |
|------|-----------|
| `cannot import name '_imaging' from 'PIL'` | Pillow 与解释器版本不匹配（cp312 装进 3.13）。`pip uninstall Pillow && pip install Pillow==12.1.0` |
| `ModuleNotFoundError: bilibili_api.clients...` | spec 缺 hiddenimports，抄上面的列表 |
| 启动后没有托盘 | 缺 `pystray._win32` hiddenimport |
| 双击闪退 | 先命令行运行 `BiliLearn Web.exe` 看报错；或检查是否从 `dist/BiliLearn Web/` 整个目录运行（不能只拷 exe） |
| 子进程中文日志乱码/崩溃 | desktop_app 已对 stdout/stderr 做 `utf-8 reconfigure`，勿删 |

---

## 📝 更新日志

### 2026-08-15 大版本更新

**✨ 新增功能**
- **新手教程重构**：首次进入自动展开在系统仪表盘（不再弹窗），6 步带进度；完成状态由后端 `/api/guide-status` 按**真实配置**判定（API 已配置 / B站已登录 / 兴趣非空 / 判定规则已自定义 / 机器人启动过 / 有观看记录），跳转仅显示「已前往 · 未配置」；全部真实完成后自动收起，操作中心与关于页可随时重开
- **节目效果模式**（实验性，默认关闭）：兴趣判定随机翻转、评分抖动、提示词随机注入，强度可调，明确标注「不建议开启」
- **AI 历史搜索增强**：支持手动补录搜索记录（自定义内容/类型/日期/时间/来源）与单条删除；`record_search` 支持自定义时间戳
- **手机端单文件安装器 `install.sh`**：询问安装 → 自选路径 → 网页端同款免责声明 → 5 镜像自动测速拉取 GitHub（直连兜底）→ 注册全局命令 `bililearn` / `abiligent` / `bilibili_learning_bot`
- **待办提醒联动**：到期提醒可触发 AI 深度搜索任务

**🐛 修复**
- **配置保存失败**（`Unable to save quota alert settings`）：Windows 文件占用导致，全局 JSON 写入改为原子替换 + 4 次重试（`utils/storage.py` / `core/config.py`）
- **系统资源趋势图不显示**：新增后台采样线程（2.5s/次，缓存 5 分钟），不再依赖仪表盘可见才采样
- **判定提示词分区空白**：`pg-judge` 嵌套在 `pg-mood` 内导致，已分离
- **B站登录状态指示**：登录绿点 / 未登录红点
- **恢复出厂残留**：迁移过数据目录后，默认路径残留数据现在也会被覆盖清除（带安全标记防误删）
- **测试隔离**：测试不再污染真实用户数据（`BILI_USER_DATA_DIR` / `LOCALAPPDATA` 隔离）

**🎨 界面**
- 仪表盘状态卡 3 列满行布局；弹性弹出动画升级（含 reduced-motion 豁免）
- 兴趣偏好图标芯片化 + 逐个弹入；避雷词圆角药丸
- 移动端/桌面端响应式与溢出修复

**✅ 质量**：全量 **337 个测试通过**；前端 8 个内联脚本块语法零错误；4 个 shell 脚本结构检查通过。

### 2026-08-12 ~ 08-13 稳定性专项

- 私聊日志跨进程并发彻底修复（Windows `msvcrt.locking` 文件锁覆盖整个读-合-写临界区，多实例并发不再丢消息）
- 用户提示词唯一驱动：私信/评论/主动私信/弹幕/动态草稿全部以用户 `system_prompt/style/rules` 为唯一内容来源，仅保留安全协议；默认人格与模板置空
- 批量修复 10+ 项：动态评论不回复、私信进度标题错乱、长期记忆与 B 友画像两套系统互通、v2w 水印崩溃、ASR 反复下载、主动聊天 NameError、动态发布日志序列化崩溃等
- 日志格式统一 `@名字 (UID:xxx)`；黑名单默认拉黑官方智能机

### 2026-08-11 细查修复

- 侧边栏重复菜单（记忆知识库）；评论空回复保护；评论三连 aid 兜底；视频转网页本地收藏夹 405；全分区导航零 JS 错误回归审计（35 分区 / 139 API 契约核对）

### 2026-08-09 ~ 08-10 功能扩展

- 检查更新（跳过版本）；项目介绍页；手机端主题切换；视频转网页来源选择 + 水印开关；ASR 面板补全 4 个缺失按钮；语言系统完善（侧边栏即时翻译）
- 数据目录可视化迁移（关于页显示所有产物路径，支持非破坏性迁移）；知识笔记多格式导出（md/txt/json/png）；AI 额度邮件告警（SMTP 密码加密存储）；智能安全系统开关；稍后再看/待办提醒/动态发布中心；功能开关扩展至 14 项

### v3.1.3（2026-08-07）

- 仪表盘图表点击放大；新手教程初版；Agent 深度增强（转发分享/伪三连）；私信 AI 答非所问修复；学习实况空状态

<details>
<summary>📜 更早更新（v3.1.2 及以前）</summary>

- **存储与知识导出**：分组备份（脱敏/完整双模式），导入自动过滤 `[已隐藏]` 占位符
- **人格管理**：Web 可视化多人格，key/显示名双匹配
- **HTML 渲染统一**：`services/html_renderer.py` 统一渲染（阅读页/幻灯片/导出）
- **深度研习 / 测验生成 / 思维导图 / Word 导出 / RAG 问答** 等服务模块
- **EXE 打包**：`desktop_app.py` + `BiliLearn.spec` 一键打包，数据迁移至用户目录
</details>

---

## 🧪 测试

```bash
python -m pytest -q          # 全部测试
python -m pytest tests/test_web_personas_api.py -q   # 单模块
```

发布前验证基线：**337 passed**。

---

## ❓ 常见问题（FAQ）

**Q: 数据存在哪里？**
源码版：项目根 `Data/`；Web/EXE 版：`%LOCALAPPDATA%\BiliLearn`（Cookie、API Key、知识库、二维码均只在本机，打包产物不含任何隐私数据）。支持在「关于项目」中迁移数据目录；恢复出厂设置会覆盖默认路径与迁移路径的全部数据。

**Q: 手机端怎么安装？**
Termux 中运行 `bash install.sh`（见上文「手机端」节），装完输入 `bililearn` 即可启动。

**Q: 机器人启动后立刻退出，日志报 `ImportError`？**
检查是否用了干净的 Python 环境。若 `PYTHONPATH` 指向了其他 Python 的 site-packages（例如安装了多个 Python），`import PIL` 可能加载到版本不匹配的 Pillow。运行前 `echo %PYTHONPATH%`，为空最稳妥。

**Q: AI 调用报 `'ascii' codec can't encode...`？**
检查 `config.json` 的 `api.vision_api_key` / `unified_api_key` 是否被写成了 `"[已隐藏]"` 之类占位符（导出配置脱敏后勿直接回写）。把该字段清空会回退到 `unified_api_key`。

**Q: 人格保存提示「不存在」？**
旧版数据中人格存储键与显示名不一致导致。3.1.2+ 已支持 key/显示名双匹配；若仍出现，重启面板加载新代码，或删除 `Data/web_personas.json` 让其从 `personas.json` 重新迁移。

**Q: 导出的配置怎么没有 Cookie 和 API Key？**
导出分为两种模式：**脱敏导出**（默认，API Key / Cookie 替换为 `[已隐藏]`，可安全分享给他人）和**完整导出**（含真实 Key 与登录 Cookie，仅限自己迁移备份，文件名带 `_full` 后缀）。网页端导出时会询问选择，CLI 菜单输入 `f` 选完整导出。

**Q: 配置保存报错 `Unable to save...`？**
3.1.3 已修复：Windows 下文件被占用时的原子写入重试机制。若仍出现，确认没有多个面板实例同时运行。

**Q: 端口被占用？**
默认 18083；被占用时自动顺延。也可 `set WEB_PORT=xxxx && python web_panel.py`。

**Q: 节目效果模式是什么？**
实验性随机模式（判定分区可开）：AI 的兴趣判定和评分会随机翻转/抖动，模拟"不按剧本"的行为，仅供娱乐，不稳定，不建议长期开启。

---

## ⚠️ 免责声明（叠甲区，认真看）

> 本项目作者深知"工具无罪、乱用有责"，以下免责声明**有多层就叠几层**，请逐条阅读：

1. **非官方出品**：本项目与哔哩哔哩（B 站）官方**没有任何关系**，非官方发布，B 站不背书、不负责。所有商标、名称归其各自所有者所有。
2. **仅限个人学习交流**：本项目仅供学习 HTTP / 数据处理 / AI 应用等技术的**个人学习用途**。**禁止**任何形式的商业用途、牟利行为、大规模批量爬取、攻击或滥用 B 站服务。
3. **法律风险自负**：B 站接口及服务条款可能随时变更，且 B 站已对同类逆向项目（如 bilibili-api）采取过法律行动。本项目基于公开接口实现，**不保证长期可用**，因使用本项目导致的任何纠纷、封号、法律责任均由使用者自行承担。
4. **账号安全**：`SESSDATA` / Cookie 是 B 站账号的**最高权限凭证**，本项目仅将其保存在你本机用户目录。**严禁**公开分享扫码二维码截图、auth.json 或 Cookie 内容，泄露等于把账号交给别人。
5. **内容版权**：提取的字幕、弹幕、评论、封面等内容的版权归原作者与 B 站所有，仅限个人阅读学习，**请勿**转载、二次分发、商用。
6. **稳定性与可用性**：本项目按"现状"提供，不提供任何明示或默示的保证。B 站改版、风控、网络环境等因素都可能使其失效；接口失效时按 README 指引重新扫码或自行修复，**作者不承诺修复时间**。
7. **不构成建议**：本项目产出的任何内容均不构成投资、理财、法律或其他专业建议；引用他人内容不代表赞同其观点。
8. **风险自担条款**：使用即视为同意以上全部条款。如果你所在地区或你的使用场景不允许此类工具，请**立即停止使用并删除本项目**。

**看视频一时爽，一直看一直爽 🫡**

---

## 📄 License

[MIT](LICENSE) © xiaoyaya191
