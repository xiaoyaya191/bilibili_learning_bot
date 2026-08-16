# bilibili_learning_bot

> **Bilibili AI Learning Bot** — An AI that auto-watches videos, learns knowledge, interacts via comments, replies to DMs, evolves itself, with a built-in Web admin panel, and one-click Windows EXE packaging.
>
> Version: **3.1.2** | License: MIT | Project Docs: https://bxya.app/

> 📘 中文版（Chinese）：[README.md](README.md)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📺 **Smart Video Browsing** | AI-driven browsing of Bilibili's recommendation feed, automatically judging content value (rating / favoriting / coin / like) |
| 📚 **Knowledge Base System** | Auto-archives high-quality videos, with 3-tier categorization + semantic search + review & recap |
| 💬 **Comment Interaction** | Real/simulated comment modes, AI in-depth replies, with image analysis support |
| 📩 **Direct Message Handling** | Auto-replies to fan DMs, with persistent context + long-term memory, and pacing control |
| 📡 **Real-time Listening** | Standalone listening engine that only watches DMs + comments for real-time AI replies — no video watching, low resource use |
| 🔔 **@ Mention Response** | Comments like "@bot summarize this video" are auto-detected and summarized/replied |
| 🧬 **Diary & Self-Evolution** | Behavior logs + AI self-reflection + dynamic persona evolution |
| 🎙️ **ASR Speech Recognition** | Video speech-to-text (FunASR / Whisper, optional install) |
| 🤖 **Agent Skill System** | Autonomously plans goals → searches Bilibili → watches videos → summarizes knowledge, a fully automated loop |
| 🎓 **Knowledge Tutoring** | AI explanations / Q&A / secondary creation / generates HTML study cards |
| 🎨 **Video → Webpage** | Generates PPT-style HTML from videos, 19 visual styles, with Claude theme support |
| 📊 **Mind Map & Word Export** | One-click export of videos to `.mindmap.html` and `.docx` documents |
| 🔍 **Deep Study** | Multi-chapter deep study of long videos, with evidence-chain summaries (`services/deep_dive.py`) |
| 🎯 **Smart Interest Engine** | Multi-dimensional scoring + synonyms + exclusion words + "eureka" exploration + PsychoProfile sync |
| 😊 **AI Mood System** | Dynamic mood affects interaction style, customizable |
| 🏆 **High-Value Like Review** | Periodically reviews favorited high-value videos, AI recap (`services/like_review.py`) |
| 🔔 **Local Reminders** | Desktop notifications + to-do reminders (`services/reminders.py`) |
| 🛡️ **Safety Review** | Keyword filtering + political-sensitivity blocking + prompt-injection protection + operation risk control |
| 🔄 **Fallback API Degradation** | Auto-switches to backup provider / backup model after consecutive primary API failures |
| 🖥️ **Windows EXE** | One-click packaging, runs without Python (tray + browser panel) |
| 🌓 **Web Panel** | Claude design style, light/dark dual themes, dashboard / bot control / config / knowledge management |
| 🐳 **Docker Deployment** | Supports Docker / docker-compose one-click deployment |
| 📱 **Termux Support** | One-click startup script for Android phones |

---

## 📊 Version Comparison: v3.0.2 → v3.1.x

| Dimension | v3.0.2 | v3.1.2+ (current 3.1.2) |
|-----------|--------|--------------------------|
| **Code Size** | 77 Python files / ~34k lines | 113 Python files / ~54k lines (+47%) |
| **Windows Desktop** | ❌ Source-only | ✅ `desktop_app.py` one-click EXE packaging (tray icon + auto-open browser) |
| **Data Directory** | In-project `Data/` (lost on packaging/upgrade) | ✅ `%LOCALAPPDATA%\BiliLearn` (packaged artifact contains zero private data, survives upgrades) |
| **Web Panel** | Basic control page | ✅ Dashboard / Bot Control / Real-time Listening / Persona Management / Knowledge Tutoring / Deep Study / Backup Restore |
| **Persona Management** | Simple prompt config | ✅ Web visual multi-persona (create / edit / activate / delete), key + display-name dual matching |
| **HTML Rendering** | Each module maintained its own templates | ✅ `services/html_renderer.py` unified rendering (reading page / slides / export) |
| **Service Modules** | 12 | ✅ 32 (added deep study, quiz generation, mind map, Word export, local favorites, like review, reminders, RAG Q&A, platform adaptation, proxy config, version history…) |
| **Comment Replies** | Basic reply | ✅ Top-level/child reply routing fix, 12006 failure handling, AI skips invalid selected IDs |
| **Listening Engine** | Basic polling | ✅ Context merging, timeout skip, `-509` backoff, web log visualization |
| **Open Platform Bridge** | ❌ | ✅ `ob_bridge/` (open-platform auth, A/B testing, audit) |
| **Backup & Restore** | Manual export | ✅ Grouped backup (settings / memory / knowledge / artifacts) + restore |
| **Tests** | 43 pytest | ✅ 181 pytest (`319 passed` full release verification) |
| **Stability Fixes** | — | Persona persistence, Cookie validation, risk control, multi-instance lock, AI degradation cooldown, context truncation protection |

> See [CHANGELOG.md](CHANGELOG.md) for detailed evolution.

---

## 🧱 Project Structure

```
├── main.py               # 🚀 Main entry (CLI interactive menu + automated startup)
├── desktop_app.py        # 🖥️ Windows EXE launcher (tray + panel)
├── web_panel.py          # 🌐 Flask Web admin panel (backend)
├── web_panel.html        # Web panel template (Claude style, light/dark dual mode)
├── BiliLearn.spec        # 📦 PyInstaller packaging config
├── build_windows_exe.bat # 📦 One-click packaging script (Windows)
│
├── api/                  # 🔌 Bilibili API layer (client / login / subtitles / throttling)
├── brain/                # 🧠 Core brain (Mixin composition: main loop / video understanding / AI calls / session)
├── cli/                  # 💻 Command-line menu
├── core/                 # ⚙️ Config / globals / user data path / factory reset
├── knowledge/            # 📚 Knowledge base (categorization / search / browsing / review / custom)
├── persona/              # 🎭 Persona + psychological profile engine
├── security/             # 🛡️ Content safety review
├── services/             # 🔧 32 services (deep study / quiz / mind map / Word / interest engine / RAG…)
├── ob_bridge/            # 🌉 Open-platform bridge (auth / A/B testing / audit)
├── xingye_bot/           # 🤖 Extension components (LLM / state / memory / evolution / ASR / grid frames)
├── utils/                # 🛠 Common utilities (tray / launcher / storage / locks)
├── templates/claude/     # 🎨 Claude design system templates + 7 reference pages
├── tests/                # 🧪 181 pytest tests
├── app-icons/            # App icons
└── dev_refs/             # 📖 Secondary-development reference docs
```

---

## 🚀 Quick Start

### 1️⃣ Install Dependencies

```bash
pip install -r requirements.txt

# Recommended: install ffmpeg (for video frame extraction)
# apt install ffmpeg        # Linux
# pkg install ffmpeg        # Termux
```

> ⚠️ The Bilibili API package name is **`bilibili-api-python`** (not `bilibili-api`). If you previously installed the old package:
> ```bash
> pip uninstall bilibili-api -y
> ```

### 2️⃣ Configuration

```bash
cp config.example.json Data/config.json   # Source run
# Edit and fill in the API Key (unified API or any OpenAI-compatible endpoint)
```

> The Web/EXE version auto-creates the data directory at `%LOCALAPPDATA%\BiliLearn`, no manual copy needed.

### 3️⃣ Launch

| Method | Command |
|--------|---------|
| **CLI Interactive Menu** | `python main.py` |
| **Web Admin Panel** | `python web_panel.py` → http://localhost:18083 |
| **Windows EXE** | Run `BiliLearn Web.exe` (auto-opens browser + tray) |
| **Docker** | `docker-compose up -d` |
| **Termux** | `bash start.sh` |

### 4️⃣ First Use

1. Web panel "Bilibili Login" → scan QR code to log in
2. "Bot Control" → start the bot (auto-watches videos)
3. "Persona Management" → configure the AI persona
4. Or CLI: `python main.py` → press `3` to log in → press `1` to start

---

## 📦 Windows EXE Packaging Guide

The project has built-in complete PyInstaller config — **no need to hand-write command lines**:

### Prerequisites

```bash
pip install pyinstaller
```

### One-click Packaging

Double-click to run (or execute from command line):

```bat
build_windows_exe.bat
```

Equivalent command:

```bash
python -m PyInstaller --noconfirm --clean BiliLearn.spec
```

Artifact: `dist/BiliLearn Web/BiliLearn Web.exe` (portable, no install needed; copy the whole folder to distribute).

### Key spec Config Points (copy-paste from source)

`BiliLearn.spec` resolves the following packaging pitfalls:

| Pit | Solution |
|-----|----------|
| **Which entry point** | Entry is `desktop_app.py` (not `main.py` / `web_panel.py`): it handles the tray, auto-opens the browser, and launches bot / monitor / standby as sub-modes on demand |
| **Data files** | `datas` explicitly includes `web_panel.html`, `config.example.json`, `VERSION`, `app-icons/`, `templates/` |
| **Flask version metadata** | `copy_metadata('flask') + copy_metadata('werkzeug')`, otherwise Flask fails to start under Python 3.13 |
| **bilibili-api dynamic imports** | `hiddenimports` explicitly declares `bilibili_api.clients.HTTPXClient` etc., otherwise the frozen QR-login/video-analysis fails |
| **Tray** | `pystray._win32` explicit hiddenimport, otherwise no tray in windowed build |
| **Subprocess modules** | `main`, `brain.monitor`, `brain.standby` explicit hiddenimports, for desktop_app to launch via `runpy` |
| **Exclude ML heavyweights** | `excludes` excludes torch / transformers / onnxruntime / faiss and other optional deps, otherwise package size 2GB+ and crashes on launch |
| **Windowed mode** | `console=False` (no black window); subprocess logs captured by panel and written to `%LOCALAPPDATA%\BiliLearn\Data` |

### Common Post-Packaging Errors Quick Reference

| Error | Cause & Solution |
|-------|------------------|
| `cannot import name '_imaging' from 'PIL'` | Pillow version mismatch with interpreter (cp312 installed into 3.13). `pip uninstall Pillow && pip install Pillow==12.1.0` |
| `ModuleNotFoundError: bilibili_api.clients...` | spec missing hiddenimports, copy the list above |
| No tray after launch | Missing `pystray._win32` hiddenimport |
| Double-click flash crash | Run `BiliLearn Web.exe` from command line first to see the error; or check whether you're running from the whole `dist/BiliLearn Web/` directory (don't copy the exe alone) |
| Subprocess Chinese log garbling/crash | desktop_app already does `utf-8 reconfigure` on stdout/stderr, don't remove it |

---

## 🧪 Testing

```bash
python -m pytest -q          # All tests
python -m pytest tests/test_web_personas_api.py -q   # Single module
```

Pre-release verification baseline: **319 passed**.

---

## ❓ FAQ

**Q: Where is the data stored?**
Source version: project root `Data/`; Web/EXE version: `%LOCALAPPDATA%\BiliLearn` (Cookies, API Keys, knowledge base, and QR codes are all local only; the packaged artifact contains no private data).

**Q: The bot exits immediately after startup, log shows `ImportError`?**
Check whether you're using a clean Python environment. If `PYTHONPATH` points to another Python's site-packages (e.g., multiple Pythons installed), `import PIL` may load a mismatched Pillow. Run `echo %PYTHONPATH%` before running — empty is safest.

**Q: AI call reports `'ascii' codec can't encode...`?**
Check whether `config.json`'s `api.vision_api_key` / `unified_api_key` was written as a placeholder like `"[hidden]"` (don't write back a desensitized config export). Clearing that field falls back to `unified_api_key`.

**Q: Persona save says "does not exist"?**
Caused by old-version data where the persona storage key didn't match the display name. 3.1.2+ already supports key/display-name dual matching; if it still happens, restart the panel to load new code, or delete `Data/web_personas.json` to re-migrate from `personas.json`.

**Q: Why doesn't the exported config include Cookie and API Key?**
Export has two modes: **desensitized export** (default, API Key / Cookie replaced with `[hidden]`, safe to share with others) and **full export** (includes real Key and login Cookie, for your own migration backup only, filename carries `_full` suffix). The web panel asks which to choose on export; the CLI menu enters `f` for full export. A full export imported to a new machine has login state and AI config working immediately.

**Q: After importing someone else's config backup, AI is all broken, reports `'ascii' codec can't encode`?**
On backup export, API Key / Cookie is desensitized to `[hidden]`; old versions would import and overwrite real config with the placeholder. 3.1.2 stable has fixed this: on import it auto-filters `[hidden]` (keeps existing value if present, otherwise deletes the field and you must refill). Already-affected users please manually edit `%LOCALAPPDATA%\BiliLearn\Data\config.json` and replace the `[hidden]` in `unified_api_key` / `vision_api_key` with the real Key.

**Q: Port already in use?**
Default 18083; auto-increments if occupied. Or `set WEB_PORT=xxxx && python web_panel.py`.

---

## 🛡️ Disclaimer (please read carefully)

> The project author knows well that "the tool is innocent, but misuse is culpable." The following disclaimer **stacks as many layers as needed** — please read each item:

1. **Unofficial**: This project has **no relationship** with the official bilibili (B站), is not an official release, and is not endorsed or responsible for by Bilibili. All trademarks and names belong to their respective owners.
2. **Personal learning & exchange only**: This project is for **personal learning purposes** only, to study technologies such as HTTP / MCP / data processing. Any form of commercial use, profit-making, large-scale batch scraping, attacks, or abuse of Bilibili services is **prohibited**.
3. **Legal risk at your own expense**: Bilibili's interfaces and terms of service may change at any time, and Bilibili has taken legal action against similar reverse-engineering projects (e.g., bilibili-api). This project is built on public interfaces and **does not guarantee long-term availability**; any disputes, account bans, or legal liabilities arising from using this project are borne solely by the user.
4. **Account security**: `SESSDATA` is the **highest-privilege credential** of a Bilibili account; this project stores it only in your local user directory. **Never** publicly share QR-login screenshots, auth.json, or Cookie contents — leaking them is handing your account to someone else.
5. **Content copyright**: Extracted subtitles, danmaku, comments, etc. are copyrighted by the original authors and Bilibili, for personal reading/learning only — **do not** repost, redistribute, or use commercially.
6. **Stability & availability**: This project is provided "as is", without any express or implied warranty. Bilibili redesigns, risk control, network conditions, and other factors may all cause it to fail; when interfaces fail, follow the README to re-scan or fix it yourself — **the author does not promise a fix time**.
7. **Not investment advice**: Any content produced by this project does not constitute investment, financial, legal, or other professional advice; quoting others' content does not mean agreeing with their views.
8. **Risk-assumption clause**: Use constitutes agreement to all the above terms. If your region or use case does not allow such tools, please **stop using and delete this project immediately**.

---

## 📄 License

[MIT](LICENSE) © xiaoyaya191
