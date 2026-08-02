# bilibili_learning_bot

> **B站 AI 学习互动机器人** — AI 自动刷视频、学知识、评论互动、私信回复、自我进化，内置 Web 管理面板，支持一键打包 Windows EXE。
>
> 版本: **3.1.2** | License: MIT | 项目文档: https://bxya.app/

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 📺 **智能视频浏览** | AI 驱动 B站推荐流浏览，自动判断内容价值（评分 / 收藏 / 投币 / 点赞） |
| 📚 **知识库系统** | 自动归档高质量视频，3 层分类 + 语义检索 + 复习回顾 |
| 💬 **评论互动** | 真实/模拟评论模式，AI 深度回复，支持图片分析 |
| 📩 **私信处理** | 自动回复粉丝私信，持久上下文 + 长期记忆，支持节奏控制 |
| 📡 **实时监听** | 独立监听引擎，只盯私信 + 评论实时 AI 回复，不刷视频不耗精力 |
| 🔔 **@通知响应** | 视频下评论 "@bot 总结这个视频"，自动识别并总结回复 |
| 🧬 **日记与自我进化** | 行为日志 + AI 自我反思 + 人格动态进化 |
| 🎙️ **ASR 语音识别** | 视频语音转文字（FunASR / Whisper，可选安装） |
| 🤖 **Agent 技能系统** | 自主规划目标 → 搜索 B站 → 看视频 → 总结知识，全自动闭环 |
| 🎓 **知识辅导** | AI 讲解 / 问答 / 二次创作 / 生成 HTML 学习卡片 |
| 🎨 **视频→网页** | 视频生成 PPT 风格 HTML，19 种视觉风格，支持 Claude 主题 |
| 📊 **思维导图 & Word 导出** | 视频一键导出 `.mindmap.html` 与 `.docx` 文档 |
| 🔍 **深度研习** | 长视频多章节深研，证据链式总结（`services/deep_dive.py`） |
| 🎯 **智能兴趣引擎** | 多维度评分 + 同义词 + 排除词 + 灵光一闪探索 + PsychoProfile 同步 |
| 😊 **AI 心情系统** | 动态心情影响互动风格，支持自定义 |
| 🏆 **干货点赞回顾** | 定期回顾收藏的干货视频，AI 复习（`services/like_review.py`） |
| 🔔 **本地提醒** | 桌面通知 + 待办提醒（`services/reminders.py`） |
| 🛡️ **安全审查** | 关键词过滤 + 政治敏感拦截 + 提示词注入防护 + 操作风控 |
| 🔄 **备用 API 降级** | 主 API 连续失败自动切换备用提供商 / 备用模型 |
| 🖥️ **Windows EXE** | 一键打包免 Python 运行（托盘 + 浏览器面板） |
| 🌓 **Web 面板** | Claude 设计风格，亮/暗双主题，仪表盘 / 机器人控制 / 配置 / 知识管理 |
| 🐳 **Docker 部署** | 支持 Docker / docker-compose 一键部署 |
| 📱 **Termux 支持** | Android 手机一键启动脚本 |

---

## 📊 v3.0.2 → v3.1.x 版本对比

| 维度 | v3.0.2 | v3.1.2+（当前 3.1.2） |
|------|--------|----------------------|
| **代码规模** | 77 个 Python 文件 / ~34k 行 | 113 个 Python 文件 / ~54k 行（+47%） |
| **Windows 桌面版** | ❌ 仅源码运行 | ✅ `desktop_app.py` 一键打包 EXE（托盘图标 + 自动开浏览器） |
| **数据目录** | 项目内 `Data/`（打包/升级易丢） | ✅ `%LOCALAPPDATA%\BiliLearn`（打包产物零隐私数据，升级不丢） |
| **Web 面板** | 基础控制页 | ✅ 仪表盘 / 机器人控制 / 实时监听 / 人格管理 / 知识辅导 / 深研 / 备份还原 |
| **人格管理** | 简单 prompt 配置 | ✅ Web 可视化多人格（创建 / 编辑 / 激活 / 删除），key 与显示名双匹配 |
| **HTML 渲染** | 各模块各自维护模板 | ✅ `services/html_renderer.py` 统一渲染（阅读页 / 幻灯片 / 导出） |
| **服务模块** | 12 个 | ✅ 32 个（新增深度研习、测验生成、思维导图、Word 导出、本地收藏、点赞回顾、提醒、RAG 问答、平台适配、代理配置、版本历史…） |
| **评论回复** | 基础回复 | ✅ 顶层/子回复路由修复、12006 失效处理、AI 选择失效 ID 跳过 |
| **监听引擎** | 基础轮询 | ✅ 上下文合并、超时跳过、`-509` 退避、网页日志可视化 |
| **开放平台桥接** | ❌ | ✅ `ob_bridge/`（开放平台鉴权、AB 测试、审计） |
| **备份与恢复** | 手动导出 | ✅ 分组备份（设置 / 记忆 / 知识 / 产物）+ 恢复 |
| **测试** | 43 个 pytest | ✅ 181 个 pytest（`319 passed` 全量发布验证） |
| **稳定性修复** | — | 人格持久化、Cookie 校验、风控、多实例锁、AI 降级冷却、上下文截断保护 |

> 详细演进见 [CHANGELOG.md](CHANGELOG.md)。

---

## 🧱 项目结构

```
├── main.py               # 🚀 主入口（CLI 交互菜单 + 自动化启动）
├── desktop_app.py        # 🖥️ Windows EXE 启动器（托盘 + 面板）
├── web_panel.py          # 🌐 Flask Web 管理面板（后端）
├── web_panel.html        # Web 面板模板（Claude 风格，亮暗双模式）
├── BiliLearn.spec        # 📦 PyInstaller 打包配置
├── build_windows_exe.bat # 📦 一键打包脚本（Windows）
│
├── api/                  # 🔌 B站 API 层（客户端 / 登录 / 字幕 / 节流）
├── brain/                # 🧠 核心大脑（Mixin 组合：主循环 / 视频理解 / AI 调用 / 会话）
├── cli/                  # 💻 命令行菜单
├── core/                 # ⚙️ 配置 / 全局变量 / 用户数据路径 / 恢复出厂
├── knowledge/            # 📚 知识库（分类 / 搜索 / 浏览 / 复习 / 自定义）
├── persona/              # 🎭 人格 + 心理画像引擎
├── security/             # 🛡️ 内容安全审查
├── services/             # 🔧 32 个服务（深研 / 测验 / 思维导图 / Word / 兴趣引擎 / RAG…）
├── ob_bridge/            # 🌉 开放平台桥接（鉴权 / AB 测试 / 审计）
├── xingye_bot/           # 🤖 扩展组件（LLM / 状态 / 记忆 / 进化 / ASR / 网格帧）
├── utils/                # 🛠 通用工具（托盘 / 启动器 / 存储 / 锁）
├── templates/claude/     # 🎨 Claude 设计系统模板 + 7 个参考页
├── tests/                # 🧪 181 个 pytest 测试
├── app-icons/            # 应用图标
└── dev_refs/             # 📖 二次开发参考文档
```

---

## 🚀 快速开始

### 1️⃣ 安装依赖

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

### 2️⃣ 配置

```bash
cp config.example.json Data/config.json   # 源码运行
# 编辑填入 API Key（统一 API 或任意 OpenAI 兼容端点）
```

> Web/EXE 版会自动在 `%LOCALAPPDATA%\BiliLearn` 创建数据目录，无需手动复制。

### 3️⃣ 启动

| 方式 | 命令 |
|------|------|
| **CLI 交互菜单** | `python main.py` |
| **Web 管理面板** | `python web_panel.py` → http://localhost:18083 |
| **Windows EXE** | 运行 `BiliLearn Web.exe`（自动开浏览器 + 托盘） |
| **Docker** | `docker-compose up -d` |
| **Termux** | `bash start.sh` |

### 4️⃣ 首次使用

1. 网页面板「B站登录」扫码登录
2. 「机器人控制」→ 启动机器人（自动刷视频）
3. 「人格管理」配置 AI 人格
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

## 🧪 测试

```bash
python -m pytest -q          # 全部测试
python -m pytest tests/test_web_personas_api.py -q   # 单模块
```

发布前验证基线：**319 passed**。

---

## ❓ 常见问题（FAQ）

**Q: 数据存在哪里？**
源码版：项目根 `Data/`；Web/EXE 版：`%LOCALAPPDATA%\BiliLearn`（Cookie、API Key、知识库、二维码均只在本机，打包产物不含任何隐私数据）。

**Q: 机器人启动后立刻退出，日志报 `ImportError`？**
检查是否用了干净的 Python 环境。若 `PYTHONPATH` 指向了其他 Python 的 site-packages（例如安装了多个 Python），`import PIL` 可能加载到版本不匹配的 Pillow。运行前 `echo %PYTHONPATH%`，为空最稳妥。

**Q: AI 调用报 `'ascii' codec can't encode...`？**
检查 `config.json` 的 `api.vision_api_key` / `unified_api_key` 是否被写成了 `"[已隐藏]"` 之类占位符（导出配置脱敏后勿直接回写）。把该字段清空会回退到 `unified_api_key`。

**Q: 人格保存提示「不存在」？**
旧版数据中人格存储键与显示名不一致导致。3.1.2+ 已支持 key/显示名双匹配；若仍出现，重启面板加载新代码，或删除 `Data/web_personas.json` 让其从 `personas.json` 重新迁移。

**Q: 导出的配置怎么没有 Cookie 和 API Key？**
导出分为两种模式：**脱敏导出**（默认，API Key / Cookie 替换为 `[已隐藏]`，可安全分享给他人）和**完整导出**（含真实 Key 与登录 Cookie，仅限自己迁移备份，文件名带 `_full` 后缀）。网页端导出时会询问选择，CLI 菜单输入 `f` 选完整导出。完整导出导入新机器后登录态与 AI 配置直接可用。

**Q: 导入别人的配置备份后 AI 全挂，报 `'ascii' codec can't encode`？**
备份导出时 API Key / Cookie 会脱敏为 `[已隐藏]`，老版本直接导入会用占位符覆盖真实配置。3.1.2 正式版已修复：导入时自动过滤 `[已隐藏]`（有现有值则保留，否则删除该字段，需重新填写）。已中招的用户请手动编辑 `%LOCALAPPDATA%\BiliLearn\Data\config.json`，把 `unified_api_key` / `vision_api_key` 的 `[已隐藏]` 换成真实 Key。

**Q: 端口被占用？**
默认 18083；被占用时自动顺延。也可 `set WEB_PORT=xxxx && python web_panel.py`。

---

## ⚠️ 免责声明

本项目仅供**学习与个人研究**使用。请遵守 B站用户协议与相关法律法规，合理控制互动频率，任何使用后果由使用者自行承担。

---

## 📄 License

[MIT](LICENSE) © xiaoyaya191
