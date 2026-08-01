# bilibili_learning_bot

> **B站 AI 学习互动机器人** — 自动刷视频、学知识、评论互动、自我进化  
> 版本: 3.0.2 | License: MIT   
> 项目介绍以及使用文档: https://bxya.app/


---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 📺 **智能视频浏览** | AI 驱动的 B站推荐流浏览，自动判断内容价值（评分/收藏/投币） |
| 📚 **知识库系统** | 自动归档高质量视频内容，支持3层分类 + 向量语义检索 |
| 💬 **评论互动** | 真实评论/模拟评论模式，AI 深度回复，支持图片分析 |
| 📩 **私信处理** | 自动回复粉丝私信，保持上下文记忆，支持节奏控制 |
| 📡 **实时监听** | 独立消息监听，只盯私信+评论实时 AI 回复，不刷视频不耗精力 |
| 🔔 **@通知响应** | 在任何视频下评论 "@bot 总结这个视频"，自动识别并总结回复 |
| 🧬 **日记与自我进化** | 记录行为日志，AI 自我反思，人格动态进化 |
| 🎙️ **ASR语音识别** | 视频语音转文字（FunASR / Whisper，可选） |
| 🤖 **Agent技能系统** | 自主规划目标→搜索 B站→看视频→总结知识，全自动闭环 |
| 🔄 **复习回顾** | 定时重温已学知识，优化记忆 |
| 🎓 **知识辅导** | AI 讲解/问答/二次创作/生成 HTML 学习卡片 |
| 🎨 **视频→网页** | 视频生成精美 PPT 风格 HTML，19种视觉风格可选，支持 Claude 主题 |
| 🎯 **智能兴趣引擎** | 多维度评分+同义词+排除词+灵光一闪探索+PsychoProfile同步+AI建议 |
| 🌐 **网页讲解** | 输入 URL，AI 读网页/总结/讲解 |
| 📝 **自定义知识管理** | 增删改查知识条目 + AI 搜索 B站自动整理入库 |
| 😊 **AI心情系统** | 动态心情影响互动风格，支持自定义 |
| 🛡️ **安全审查** | 关键词过滤 + 政治敏感拦截 + 提示词注入防护 |
| 🔄 **备用API降级** | 主 API 连续失败自动切换备用提供商 |
| 📤 **隐私导出** | 一键导出配置（API Key/Cookie 脱敏保护） |
| 🌓 **Web面板暗色模式** | Claude 设计风格 + 亮/暗双主题切换 |
| 🐳 **Docker 部署** | 支持 Docker / docker-compose 一键部署 |

## 🧱 项目结构

```
├── main.py               # 主入口
├── start_cli.py          # 兼容转发
├── web_panel.py          # 🌐 Flask Web 管理面板
├── web_panel.html        # Web面板模板 (Claude设计风格+亮暗双模式)
│
├── api/                  # 🔌 B站 API 层
│   ├── client.py         # B站客户端
│   ├── auth.py           # 登录认证
│   ├── subtitles.py      # 字幕获取与校验（含412风控fallback）
│   ├── throttle.py       # 请求节流器
│   └── compat.py         # 兼容层
│
├── brain/                # 🧠 核心大脑（Mixin 组合模式）
│   ├── agent_brain.py    # 主调度器（55行，13个 mixin 组合）
│   ├── _mixin_imports.py # 统一导入
│   ├── _brain_init.py    # 初始化
│   ├── _brain_loop.py    # 主循环 (~905行)
│   ├── _brain_video.py   # 视频理解 (~621行)
│   ├── _brain_session.py # 会话管理 (~640行)
│   ├── _brain_ai.py      # AI 调用后端
│   ├── _brain_learn.py   # 学习归档
│   ├── _brain_curiosity.py # 好奇心搜索
│   ├── _brain_auto.py    # 自动日记/进化
│   ├── _brain_journal.py # 日记/学习日志
│   ├── _brain_history.py # 视频历史
│   ├── _brain_ups.py     # UP主管理
│   ├── _brain_runtime.py # 运行时时钟
│   ├── _brain_interact.py # 视觉分析+互动
│   ├── comment.py        # 评论互动
│   ├── private_msg.py    # 私信处理
│   ├── video_analysis.py # 视频分析 (V命令)
│   ├── standby.py        # 待机监听（@通知响应）
│   └── monitor.py        # 实时监听引擎
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
│   ├── managers.py       # 人格/心情/日记管理
│   └── psycho.py         # 心理画像引擎
│
├── security/             # 🛡️ 安全与隐私
│   └── guard.py          # 内容审查
│
├── cli/                  # 💻 命令行界面
│   └── app.py            # 菜单 + 配置 + V/W/P命令
│
├── core/                 # ⚙️ 配置 + 全局变量
│   ├── config.py         # 配置加载/保存 + __getattr__ 动态属性
│   └── globals.py        # 全局变量（动态从 config 读取）
│
├── services/             # 🔧 服务模块
│   ├── agent_service.py  # Agent 技能执行
│   ├── knowledge_tutor.py # 知识辅导
│   ├── video_to_ppt.py   # 视频→HTML网页（19种风格）
│   ├── interest_engine.py # 🎯 智能兴趣引擎 v2.0
│   └── utils.py          # 工具/兴趣管理
│
├── xingye_bot/           # 🤖 扩展组件
│   ├── llm.py, state.py, memory.py, safety.py
│   ├── diary.py, evolution.py, skills.py
│   ├── asr_engine.py, video_modes.py
│   ├── kb_search.py, bilibili_ops.py
│   └── settings.py
│
├── utils/                # 🛠 通用工具
│   ├── helpers.py        # 工具函数
│   ├── storage.py        # JSON 线程安全存储 + 脱敏
│   ├── display.py        # 日志显示
│   └── lock.py           # 单实例锁
│
├── templates/            # 🎨 设计模板
│   └── claude/           # Claude 设计系统
│       ├── prompts/      # AI 设计规范（v1.0）
│       └── examples/     # 7 个参考页面
│
├── Data/                 # 💾 运行时数据（自动生成）
├── KnowledgeBase/        # 📖 知识库目录
├── web/                  # HTML 导出目录
└── tests/                # 🧪 43 个 pytest 测试
```

## 🚀 快速开始

### 1️⃣ 安装依赖

> ⚠️ **重要提示 / 致歉声明**  
> 之前 `requirements.txt` 里 B站 API 写的是 `>=16.0.0`，但之前有用户反馈安装了旧包 `bilibili-api`（最高 v9.1，缺失很多模块）。  
> 正确的包名是 **`bilibili-api-python`**，现已修复为 `>=17.4.1`。  
> **给大家带来困扰，非常抱歉！** 🙇

```bash
pip install -r requirements.txt

# 如果之前装过旧包，先卸载：
# pip uninstall bilibili-api -y

# 推荐安装 ffmpeg（视频帧提取）
# apt install ffmpeg    # Linux
# pkg install ffmpeg    # Termux
```

### 2️⃣ 配置

```bash
cp config.example.json Data/config.json
# 编辑 Data/config.json 填入你的 API Key（统一API或OpenAI兼容接口）
```

### 3️⃣ 启动

**交互式菜单**:
```bash
python3 main.py
```

**Web管理面板**:
```bash
python3 web_panel.py
# 访问 http://localhost:7860
# 包含: 仪表盘 / 机器人控制 / 实时监听 / 配置编辑 / 知识辅导 等页面
```

**Docker 部署（推荐）**:
```bash
docker compose up -d
# 访问 http://localhost:7860
```

默认容器内外端口统一为 `7860`，和 Web 管理面板监听端口一致；运行数据会写入 Docker volumes，升级镜像不丢配置和 Cookie。需要改宿主机端口时只改左侧端口：
```bash
WEB_PORT=17860 docker compose up -d
# 访问 http://localhost:17860，容器内仍是 7860
```

**Termux (Android) 一键启动**:
```bash
bash start.sh
```

### 4️⃣ 首次使用

1. 进入菜单后按 `3` 配置 B站登录（扫码或 Cookie）
2. 按 `1` 启动机器人自动刷视频
3. 按 `V` 手动分析特定视频
4. 按 `W` 将已学视频生成 HTML 网页
5. 按 `N` 管理自定义知识

## 📋 主菜单功能速览

| 按键 | 功能 |
|------|------|
| `1` | 🚀 启动机器人 |
| `2` | ⚙️ 配置AI参数 |
| `3` | 🔑 配置登录 |
| `4` | 📚 管理知识库 |
| `5` | 🎯 管理兴趣爱好 |
| `6` | 💬 评论互动设置 |
| `7` | 📩 私信设置 |
| `8` | 🧬 日记/自我进化 |
| `9` | 🛠️ Agent技能 |
| `L` | 📡 实时监听（不刷视频，只盯私信+评论） |
| `F` | 👤 UP主关注/弹幕设置 |
| `G` | 🎙️ ASR语音识别设置 |
| `M` | 😊 AI心情管理 |
| `D` | 🏆 干货归档 |
| `V` | 📹 手动视频分析 |
| `K` | 🔄 知识库重温 |
| `T` | 🎓 知识辅导 |
| `W` | 🎨 视频→网页（PPT风格HTML，支持Claude主题） |
| `P` | 🎯 兴趣偏好设置（智能引擎 v2.0：多维度评分/同义词/排除词/PsychoProfile同步） |
| `N` | 📝 自定义知识管理 |
| `R` | 🔄 恢复出厂设置（一键清空所有隐私数据） |
| `S` | 🛡️ 关键词审查开关 |
| `E` | 📤 导出配置（脱敏） |
| `I` | 📥 导入配置 |
| `O` | 📂 一键整理知识库 |

## 🎨 Claude 设计主题

项目内置 Claude 设计系统 — 纯白暖橙极简风格，让 HTML 输出像专业网页一样优雅。

**Web 面板**：自动应用 Claude 风格，含亮/暗双模式切换。

**在视频→网页功能中使用**：选择 "Claude Slides" 风格（推荐），生成 HTML 自动应用：
- Inter 字体（100-800 字重）
- Lucide 图标系统（无 emoji，无 Font Awesome）
- 黑底白字按钮 + 14px 卡片圆角 + 标题字重 200
- 暖橙 `#D97757` 强调色 + 纯白/纯黑双主题
- 翻页动画 + 进度条 + 暗色模式切换

**19 种视觉风格**：Claude Slides / Bento 网格 / 玻璃拟态 / 极光渐变 / 新野蛮主义 / 深色OLED / 赛博朋克 / 新拟态 / 液态玻璃 / 复古主义 / Linear / 新变风 / 柔和流行 / PromptPort ...

**模板文件**：`templates/claude/examples/` 下有 7 个参考页面，可直接浏览器打开。


## 🐳 Docker 部署、更新与镜像发布

### 端口说明

Web 管理面板默认监听 `7860`，Docker 里也保持 `7860:7860`，避免“宿主机端口”和“容器内端口”不一致导致排查困难。

```bash
# 默认：宿主机 7860 -> 容器 7860
docker compose up -d

# 如宿主机 7860 被占用，只改左侧宿主机端口
WEB_PORT=17860 docker compose up -d
```

访问地址：
- 默认：`http://localhost:7860`
- 自定义宿主机端口：`http://localhost:17860`

### 数据持久化

`docker-compose.yml` 默认使用 Docker volumes，不把运行数据打进镜像：

| Volume | 容器路径 | 用途 |
|---|---|---|
| `bili_data` | `/app/Data` | 配置、Cookie、日志、状态数据 |
| `bili_knowledge` | `/app/KnowledgeBase` | 知识库 |
| `bili_highlights` | `/app/highlights` | 高光/归档内容 |
| `bili_exports` | `/app/html_exports` | HTML/PPT 导出结果 |

查看数据卷：
```bash
docker volume ls | grep bili_
```

备份示例：
```bash
docker run --rm   -v bili_data:/data   -v "$PWD":/backup   alpine tar czf /backup/bili_data_backup.tar.gz -C /data .
```

### 本地源码构建

适合开发者或还没发布镜像时使用：

```bash
docker compose build
docker compose up -d
```

常用检查：
```bash
docker compose ps
docker compose logs -f bilibili-bot
```

### 使用已发布镜像

发布到 Docker Hub 或 GHCR 后，可以通过 `DOCKER_IMAGE` 指定镜像，不必本地 build：

```bash
DOCKER_IMAGE=yourname/bilibili_learning_bot:latest docker compose up -d
```

也可以写入 `.env`：
```env
DOCKER_IMAGE=yourname/bilibili_learning_bot:latest
WEB_PORT=7860
APP_VERSION=3.0.1
UPDATE_CHECK_URL=
```

然后启动：
```bash
docker compose up -d
```

### 在线更新提示

Web 面板“关于系统”会显示：
- 当前版本：来自 `APP_VERSION` 环境变量，未设置时读取 `VERSION` 文件
- 最新版本：来自 `UPDATE_CHECK_URL`
- 有新版时：提示执行 `docker compose pull && docker compose up -d`

默认 `UPDATE_CHECK_URL` 为空，不主动联网。发布者可以填 GitHub raw `VERSION`、自托管 version.txt，或其它只返回版本号的文本地址：

```bash
UPDATE_CHECK_URL=https://example.com/bilibili_learning_bot/VERSION docker compose up -d
```

更新流程：
```bash
docker compose pull
docker compose up -d
```

如果是本地源码构建镜像：
```bash
git pull
docker compose build
docker compose up -d
```

### 推送到 Docker Hub / GHCR

仓库已包含 GitHub Actions 工作流 `.github/workflows/docker-publish.yml`，支持自动构建并推送：

1. 如需推送 Docker Hub，在 GitHub 仓库 Settings → Secrets and variables → Actions 中添加：
   - `DOCKERHUB_USERNAME`
   - `DOCKERHUB_TOKEN`
2. GHCR 使用仓库自带的 `GITHUB_TOKEN`，不需要额外配置。
3. push 到 `main` 或打 `v*.*.*` tag 后自动构建多架构镜像：
   - `latest`
   - `VERSION` 文件里的版本号
   - Git tag 版本

注意：凭据只放 GitHub Secrets，不要写进代码、compose、README 或镜像。

### 常见问题

**1. 访问不到 Web 面板**
```bash
docker compose ps
docker compose logs --tail=100 bilibili-bot
```
确认容器健康状态，以及端口是否是 `7860:7860` 或你自定义的 `WEB_PORT:7860`。

**2. 更新后配置丢失？**
正常不会。配置和 Cookie 在 Docker volumes 里，不在镜像里。不要手动删除 `bili_data` volume。

**3. 版本检查失败但面板能用？**
正常。`UPDATE_CHECK_URL` 为空或网络不可达时只是不显示远端最新版，不影响机器人运行。

## 🔒 隐私安全

- API Key 在菜单显示和导出时自动脱敏（`mask_secret` / `sanitize_config_for_export`）
- 一键恢复出厂设置（`R` → `YES`）清空全部隐私数据：配置/登录/状态/日志/记忆/心理画像/网页面板/知识库/导出/备份/加密密钥
- 导出备份自动隐藏敏感字段（API Key、Cookie Token等替换为 `[已隐藏]`）
- 所有配置文件和 Cookie 仅本地存储，不上传到任何服务器

## ⚠️ 免责声明

本项目仅供学习参考。使用本项目请遵守 B站用户协议，若因使用本项目产生任何后果，本人概不负责。

## 📄 License

MIT © XingYe contributors

---

📋 **更新日志**: [CHANGELOG.md](CHANGELOG.md) | 🔧 **重构记录**: [REFACTOR_PLAN.md](REFACTOR_PLAN.md)
