#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bilibili_learning_bot · Web 管理面板 
功能：仪表盘 | 机器人启停 | B站扫码登录 | 配置编辑 | 实时日志
     人格管理 | 评论日志 | 用户画像 | 记忆知识库 | 日记进化 | 操作日志
"""
import os, sys, json, time, io, base64, threading, asyncio, subprocess, signal, queue, hashlib, secrets, re
from datetime import datetime
from pathlib import Path
from functools import wraps

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def _disclaimer_confirm_terminal():
    """显示红色免责声明，输入'我同意'后继续。"""
    from colorama import Fore, Style
    _TARGET = "\u6211\u540c\u610f"  # 我同意
    banner = f"""
{Fore.RED}{'=' * 60}
  \u26a0  免责声明 / DISCLAIMER
{'=' * 60}
  本项目仅供学习参考，
  若因使用本项目产生任何后果，本人概不负责。

  This project is for learning purposes only.
  Any consequences are solely your own responsibility.
{'=' * 60}{Style.RESET_ALL}
"""
    print(banner)
    user_input = input(f"{Fore.YELLOW}请输入 '{_TARGET}' 以继续:{Style.RESET_ALL}").strip()
    if user_input != _TARGET:
        print(f"{Fore.RED}\u2717 输入不匹配，程序退出。{Style.RESET_ALL}")
        sys.exit(1)
    print(f"{Fore.GREEN}\u2713 已确认，欢迎使用...{Style.RESET_ALL}\n")
    return True

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

try:
    from flask import Flask, request, jsonify, Response, stream_with_context, session, redirect
except ImportError:
    print("[ERROR] Please install Flask: pip install flask")
    sys.exit(1)

try:
    import qrcode as qrlib
    from qrcode.image.pil import PilImage
except ImportError:
    qrlib = None

# ── 路径（支持环境变量切换账号）──
BASE_DIR = Path(__file__).resolve().parent
# BILI_ACCOUNT_DATA_DIR: 自定义 Data 目录路径，用于多账号隔离，如 "account1/Data" 或 "account2/Data"
_account_data_override = os.getenv('BILI_ACCOUNT_DATA_DIR', '').strip()
if _account_data_override:
    DATA_DIR = BASE_DIR / _account_data_override
else:
    DATA_DIR = BASE_DIR / "Data"
CONFIG_FILE = DATA_DIR / "config.json"
COOKIE_FILE = DATA_DIR / "bilibili_cookies.json"
# 账号标识名（显示在网页标题等处）
ACCOUNT_NAME = os.getenv('BILI_ACCOUNT_NAME', '').strip() or '默认'

app = Flask(__name__, static_folder=None)
app.secret_key = os.urandom(24).hex()
app.permanent = True  # persistent session
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── 安全：路径穿越防护 ──
def safe_join(base: Path, *paths: str) -> Path | None:
    """安全拼接路径，防止穿越。返回 None 表示非法路径。"""
    try:
        result = (base / Path(*paths)).resolve()
        base_resolved = base.resolve()
        if not str(result).startswith(str(base_resolved)):
            return None
        return result
    except (ValueError, RuntimeError):
        return None

def sanitize_filename(name: str) -> str:
    """清洗文件名，只允许字母、数字、下划线、点、横线。"""
    return re.sub(r'[^\w.\-]', '', name)[:255]

# ── 安全：Web面板登录认证 ──
WEB_PASSWORD = os.getenv('BILI_WEB_PASSWORD', '').strip()
if not WEB_PASSWORD:
    print("[FATAL] 致命错误：环境变量 BILI_WEB_PASSWORD 未设置！")
    print("[FATAL] 为了安全，Web 面板拒绝在没有密码的情况下启动。")
    sys.exit(1)
_LOGIN_NONCES: set[str] = set()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('web_authenticated'):
            return jsonify(dict(ok=False, message='未登录', need_login=True)), 401
        return f(*args, **kwargs)
    return decorated

# ── 全局状态 ──
bot_process: subprocess.Popen | None = None
bot_running = False
bot_start_time: datetime | None = None
panel_start = datetime.now()
bot_output_lines: list[str] = []
bot_output_lock = threading.Lock()

# QR 登录状态
qr_state = {"active": False, "url": "", "status": "idle", "message": "", "uid": "", "img_b64": ""}

def log_line(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with bot_output_lock:
        bot_output_lines.append(line)
        if len(bot_output_lines) > 500:
            del bot_output_lines[:-400]
    print(line, flush=True)
    return line

# ── 文件工具 ──
def read_json(path: Path, default=None):
    if default is None: default = {}
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def write_json(path: Path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception as e:
        log_line(f"写入失败 {path.name}: {e}")
        return False

def file_stat(path: Path):
    if not path.exists(): return {"exists": False, "size": 0, "mtime": None, "size_fmt": "0 B"}
    s = path.stat()
    sz = s.st_size
    return {"exists": True, "size": sz, "mtime": datetime.fromtimestamp(s.st_mtime).strftime("%m-%d %H:%M"),
            "size_fmt": f"{sz/1024:.1f}K" if sz<1024*1024 else f"{sz/1048576:.2f}M"}

def _cleanup_qr_images():
    """删除 qr_codes 文件夹中的所有二维码图片"""
    try:
        qr_dir = BASE_DIR / "qr_codes"
        if qr_dir.is_dir():
            for fpath in qr_dir.iterdir():
                if fpath.is_file():
                    fpath.unlink()
                    log_line(f"已删除过期二维码: {fpath}")
    except Exception as e:
        log_line(f"清理二维码失败: {e}")

# ═══════════════════════════════════════════
#  QR 登录流程（在线程中跑 asyncio）
# ═══════════════════════════════════════════
def do_qr_login():
    """在后台线程中执行 B 站扫码登录"""
    global qr_state
    qr_state = {"active": True, "url": "", "status": "generating", "message": "正在生成二维码...", "uid": "", "img_b64": ""}

    async def _login():
        global qr_state
        try:
            from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

            qr = QrCodeLogin()
            await qr.generate_qrcode()
            url = getattr(qr, "_QrCodeLogin__qr_link", None)

            if not url:
                qr_state["status"] = "error"
                qr_state["message"] = "获取登录链接失败"
                qr_state["active"] = False
                return

            qr_state["url"] = url
            # 生成二维码图片 base64 (供 Web 展示) + 保存到 qr_codes 文件夹
            img_b64 = ""
            qr_png_path = None
            try:
                if qrlib is None:
                    raise ImportError("qrcode library not available")
                qr_img = qrlib.QRCode(box_size=8, border=2)
                qr_img.add_data(url)
                qr_img.make(fit=True)
                img = qr_img.make_image(fill_color="black", back_color="white")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                img_b64 = base64.b64encode(buf.getvalue()).decode()
                # 同时保存到 qr_codes 文件夹
                qr_dir = BASE_DIR / "qr_codes"
                qr_dir.mkdir(exist_ok=True)
                qr_png_path = qr_dir / "bilibili_login_qr.png"
                img.save(str(qr_png_path))
                log_line(f"二维码已保存至: {qr_png_path}")
            except Exception as e:
                log_line(f"QR图片生成失败: {e}")

            qr_state["img_b64"] = img_b64
            qr_state["status"] = "waiting_scan"
            qr_state["message"] = "请使用 B站APP 扫描二维码"

            scan_detected = False
            while qr_state["active"]:
                try:
                    status = await qr.check_state()
                    if status == QrCodeLoginEvents.DONE:
                        qr_state["status"] = "success"
                        qr_state["message"] = "登录成功！正在保存..."
                        cred = qr.get_credential()
                        cookies = {
                            "SESSDATA": cred.sessdata,
                            "bili_jct": cred.bili_jct,
                            "DedeUserID": cred.dedeuserid,
                            "buvid3": getattr(cred, "buvid3", ""),
                            "ac_time_value": getattr(cred, "ac_time_value", ""),
                        }
                        qr_state["uid"] = cookies.get("DedeUserID", "")
                        write_json(COOKIE_FILE, cookies)
                        qr_state["message"] = f"登录成功！UID: {cookies.get('DedeUserID', '?')}"
                        qr_state["active"] = False
                        log_line(f"B站扫码登录成功 UID={cookies.get('DedeUserID', '?')}")
                        _cleanup_qr_images()  # 登录成功，删除二维码图片
                        return
                    elif status == QrCodeLoginEvents.SCAN:
                        if not scan_detected:
                            scan_detected = True
                            qr_state["status"] = "scanned"
                            qr_state["message"] = "已扫描，请在手机上确认登录"
                    elif status == QrCodeLoginEvents.CONF:
                        qr_state["status"] = "confirming"
                        qr_state["message"] = "已确认，正在登录..."
                    elif status == QrCodeLoginEvents.TIMEOUT:
                        qr_state["status"] = "timeout"
                        qr_state["message"] = "二维码已过期，请重新生成"
                        qr_state["active"] = False
                        _cleanup_qr_images()  # 超时也删除过期二维码
                        return
                    await asyncio.sleep(1.5)
                except Exception as e:
                    log_line(f"QR状态查询错误: {e}")
                    await asyncio.sleep(2)
        except Exception as e:
            qr_state["status"] = "error"
            qr_state["message"] = f"登录异常: {e}"
            qr_state["active"] = False
            log_line(f"B站登录失败: {e}")

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_login())
    except Exception as e:
        qr_state["status"] = "error"
        qr_state["message"] = str(e)
        qr_state["active"] = False

# ═══════════════════════════════════════════
#  机器人进程管理
# ═══════════════════════════════════════════
def _bot_reader(pipe, prefix=""):
    """读取子进程输出"""
    try:
        for line in iter(pipe.readline, ""):
            if not line: break
            text = line.rstrip()
            if text:
                log_line(prefix + text)
    except OSError: pass
    finally:
        try: pipe.close()
        except OSError: pass

def start_bot_process():
    global bot_process, bot_running, bot_start_time
    if bot_running:
        return False, "机器人已在运行"

    agent_path = BASE_DIR / "new_agent.py"
    if not agent_path.exists():
        return False, f"找不到 {agent_path}"

    log_line("🚀 正在启动机器人进程...")
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"

        bot_process = subprocess.Popen(
            [sys.executable, str(agent_path)],
            cwd=str(BASE_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        bot_running = True
        bot_start_time = datetime.now()

        threading.Thread(target=_bot_reader, args=(bot_process.stdout, ""), daemon=True).start()
        log_line("✅ 机器人进程已启动")
        return True, "机器人已启动"
    except Exception as e:
        log_line(f"❌ 启动失败: {e}")
        return False, str(e)

def stop_bot_process():
    global bot_process, bot_running
    if not bot_running:
        return False, "机器人未在运行"
    try:
        if bot_process:
            log_line("⏹ 正在停止机器人...")
            try:
                if bot_process.stdin:
                    bot_process.stdin.write("0\n")
                    bot_process.stdin.flush()
            except subprocess.TimeoutExpired: pass
            time.sleep(0.5)
            bot_process.terminate()
            try: bot_process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try: bot_process.kill()
                except Exception: pass
            bot_process = None
    except Exception as e:
        log_line(f"停止异常: {e}")
    bot_running = False
    log_line("✅ 机器人已停止")
    return True, "已停止"

# ═══════════════════════════════════════════
#  HTML 模板（从文件加载，回退到内嵌模板）
# ═══════════════════════════════════════════
_HTML_FILE = BASE_DIR / "web_panel.html"

def _load_html() -> str:
    """从 web_panel.html 文件加载模板，不存在则使用内嵌默认"""
    if _HTML_FILE.exists():
        try:
            html = _HTML_FILE.read_text(encoding="utf-8")
        except OSError:
            html = _DEFAULT_HTML
    else:
        html = _DEFAULT_HTML
    # 替换账号相关的占位符
    account_label = f" - {ACCOUNT_NAME}" if ACCOUNT_NAME != '默认' else ""
    html = html.replace('{{ACCOUNT_TITLE}}', f'控制面板{account_label}')
    html = html.replace('{{ACCOUNT_HEADER}}', f'控制面板{account_label}')
    return html

_DEFAULT_HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>{{ACCOUNT_TITLE}}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{
--bg:#0a0e14;--bg2:#131a24;--bg3:#1c2535;--border:#263040;
--text:#dde4f0;--text2:#7888a0;--accent:#5b8def;--accent2:#36d7b7;
--green:#4caf7c;--orange:#f0a040;--red:#e05560;--pink:#e06090;--purple:#9b6dff;
--r:10px;--rs:6px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);display:flex;min-height:100vh}
a{color:var(--accent)}

/* SIDEBAR */
.sidebar{width:230px;min-width:230px;background:var(--bg2);border-right:1px solid var(--border);display:flex;flex-direction:column;position:fixed;top:0;left:0;bottom:0;z-index:100;transition:transform .25s}
.sidebar.hide{transform:translateX(-100%)}
.sb-hd{padding:16px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px}
.sb-av{width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--purple));display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:#fff;flex-shrink:0}
.sb-tt{font-size:15px;font-weight:700;line-height:1.2}
.sb-sub{font-size:10px;color:var(--text2)}
.sb-nav{flex:1;overflow-y:auto;padding:8px 6px}
.ns{font-size:9px;color:var(--text2);text-transform:uppercase;letter-spacing:1.5px;padding:14px 10px 4px}
.ni{display:flex;align-items:center;gap:8px;padding:9px 10px;border-radius:var(--rs);cursor:pointer;color:var(--text2);font-size:13px;border:none;background:none;width:100%;transition:all .15s}
.ni:hover{background:var(--bg3);color:var(--text)}
.ni.ac{background:var(--accent);color:#fff;font-weight:600}
.ni .ic{font-size:16px;width:22px;text-align:center;flex-shrink:0}
.ni .bd{margin-left:auto;background:var(--red);color:#fff;font-size:10px;padding:1px 6px;border-radius:10px;font-weight:600;display:none}
.sb-ft{padding:10px;border-top:1px solid var(--border);font-size:10px;color:var(--text2);text-align:center}

/* MAIN */
.main{margin-left:230px;flex:1;padding:24px 28px;max-width:calc(100vw - 230px);min-width:0}
.page{display:none}
.page.on{display:block}
.ph{margin-bottom:20px}
.ph h1{font-size:22px;font-weight:700}
.ph p{color:var(--text2);font-size:12px;margin-top:2px}

/* CARDS */
.sr{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:20px}
.sc{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:16px;display:flex;align-items:center;gap:12px}
.si{width:42px;height:42px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0}
.si.bl{background:rgba(91,141,239,.15);color:var(--accent)}
.si.gn{background:rgba(76,175,124,.15);color:var(--green)}
.si.or{background:rgba(240,160,64,.15);color:var(--orange)}
.si.pk{background:rgba(224,96,144,.15);color:var(--pink)}
.sv{font-size:20px;font-weight:700}
.sl{font-size:11px;color:var(--text2)}

.pc{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:18px;margin-bottom:16px}
.pc h3{font-size:14px;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.dot.on{background:var(--green)}
.dot.off{background:var(--text2)}

/* TABLE */
.tb{width:100%;border-collapse:collapse;font-size:12px}
.tb th{text-align:left;padding:8px 10px;color:var(--text2);font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border)}
.tb td{padding:8px 10px;border-bottom:1px solid rgba(38,48,64,.5);max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tb tr:hover td{background:rgba(91,141,239,.04)}
.tb .mono{font-family:"SF Mono","Fira Code",monospace;font-size:11px}

/* BUTTONS */
.btn{display:inline-flex;align-items:center;gap:5px;padding:7px 14px;border-radius:var(--rs);font-size:12px;font-weight:600;cursor:pointer;border:none;transition:all .15s;white-space:nowrap}
.btn-pr{background:var(--accent);color:#fff}
.btn-pr:hover{opacity:.85}
.btn-suc{background:var(--green);color:#fff}
.btn-dan{background:var(--red);color:#fff}
.btn-out{background:transparent;border:1px solid var(--border);color:var(--text)}
.btn-out:hover{border-color:var(--accent);color:var(--accent)}
.btn-sm{padding:4px 10px;font-size:11px}
.btn-lg{padding:10px 20px;font-size:14px}
.btn-grp{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.btn:disabled{opacity:.5;cursor:not-allowed}

/* FORMS */
.fg{margin-bottom:12px}
.fg label{display:block;font-size:11px;font-weight:600;color:var(--text2);margin-bottom:3px;text-transform:uppercase;letter-spacing:.3px}
.fg input,.fg textarea,.fg select{width:100%;padding:8px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);color:var(--text);font-size:12px;font-family:inherit;outline:none}
.fg input:focus,.fg textarea:focus,.fg select:focus{border-color:var(--accent)}
.fg textarea{resize:vertical;min-height:70px;font-family:"SF Mono","Fira Code",monospace;font-size:11px}
.fr{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:600px){.fr{grid-template-columns:1fr}}

/* TAGS */
.tg{display:inline-block;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600}
.tg-suc{background:rgba(76,175,124,.15);color:var(--green)}
.tg-war{background:rgba(240,160,64,.15);color:var(--orange)}
.tg-dan{background:rgba(224,85,96,.15);color:var(--red)}
.tg-inf{background:rgba(91,141,239,.15);color:var(--accent)}

/* LOG VIEWER */
.log-box{background:#060a10;border:1px solid var(--border);border-radius:var(--rs);padding:12px;max-height:350px;overflow-y:auto;font-family:"SF Mono","Fira Code",monospace;font-size:11px;line-height:1.55;white-space:pre-wrap;word-break:break-all;color:#b0c0d8}

/* JSON EDITOR */
.je{width:100%;min-height:380px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);color:var(--text);font-family:"SF Mono","Fira Code",monospace;font-size:12px;padding:12px;resize:vertical;outline:none}
.je:focus{border-color:var(--accent)}

/* QR */
.qr-wrap{text-align:center;padding:20px}
.qr-wrap img{max-width:220px;border-radius:8px;border:3px solid #fff;background:#fff}
.qr-wrap .qr-status{margin-top:10px;font-size:13px;font-weight:600}

/* TOAST */
.toast{position:fixed;top:16px;right:16px;z-index:9999;padding:10px 16px;border-radius:var(--rs);font-size:12px;font-weight:600;opacity:0;transform:translateY(-16px);transition:all .25s;pointer-events:none;max-width:300px}
.toast.show{opacity:1;transform:translateY(0)}
.toast.ok{background:var(--green);color:#fff}
.toast.err{background:var(--red);color:#fff}
.toast.inf{background:var(--accent);color:#fff}

/* EMPTY */
.emp{text-align:center;padding:30px;color:var(--text2)}
.emp .ic{font-size:36px;margin-bottom:8px}

/* MOBILE */
.mob-toggle{display:none;position:fixed;top:10px;left:10px;z-index:200;background:var(--bg2);border:1px solid var(--border);color:var(--text);width:38px;height:38px;border-radius:var(--rs);align-items:center;justify-content:center;cursor:pointer;font-size:18px}
.mob-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:99}
@media(max-width:768px){
.sidebar{transform:translateX(-100%)}
.sidebar.show{transform:translateX(0)}
.main{margin-left:0;max-width:100%;padding:14px 12px}
.sr{grid-template-columns:repeat(2,1fr);gap:8px}
.sc{padding:12px;gap:8px}
.mob-toggle{display:flex}
.mob-overlay.show{display:block}
.ph h1{font-size:19px}
.tb{font-size:11px}
.tb td{max-width:140px}
.log-box{max-height:250px}
.je{min-height:250px}
}

/* PULSE */
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.pulse{animation:pulse 1.5s infinite}
</style>
</head>
<body>

<button class="mob-toggle" onclick="toggleSidebar()">☰</button>
<div class="mob-overlay" id="mobOverlay" onclick="toggleSidebar()"></div>

<!-- SIDEBAR -->
<aside class="sidebar" id="sidebar">
<div class="sb-hd">
<div class="sb-av">⚡</div><div><div class="sb-tt">{{ACCOUNT_HEADER}}</div><div class="sb-sub">B站 AI 管理系统</div></div>
</div>
<nav class="sb-nav">
<div class="ns">总览</div>
<button class="ni ac" data-pg="dash" onclick="nav('dash',this)"><span class="ic">📊</span>仪表盘</button>
<button class="ni" data-pg="ctrl" onclick="nav('ctrl',this)"><span class="ic">🎮</span>机器人控制<span class="bd" id="botBadge">●</span></button>
<button class="ni" data-pg="login" onclick="nav('login',this)"><span class="ic">🔑</span>B站登录<span class="bd" id="loginBadge">●</span></button>
<div class="ns">系统配置</div>
<button class="ni" data-pg="conf" onclick="nav('conf',this)"><span class="ic">⚙️</span>配置编辑</button>
<button class="ni" data-pg="psna" onclick="nav('psna',this)"><span class="ic">🎭</span>人格管理</button>
<button class="ni" data-pg="mood" onclick="nav('mood',this)"><span class="ic">💡</span>心情管理</button>
<button class="ni" data-pg="behavior" onclick="nav('behavior',this)"><span class="ic">⚡</span>行为设置</button>
<button class="ni" data-pg="upfu" onclick="nav('upfu',this)"><span class="ic">👥</span>UP主关注</button>
<div class="ns">数据监控</div>
<button class="ni" data-pg="cmts" onclick="nav('cmts',this)"><span class="ic">💬</span>评论日志</button>
<button class="ni" data-pg="usrs" onclick="nav('usrs',this)"><span class="ic">👤</span>用户画像</button>
<button class="ni" data-pg="mem" onclick="nav('mem',this)"><span class="ic">🧠</span>记忆知识库</button>
<button class="ni" data-pg="diary" onclick="nav('diary',this)"><span class="ic">📖</span>日记进化</button>
<button class="ni" data-pg="acts" onclick="nav('acts',this)"><span class="ic">📋</span>操作日志</button>
<div class="ns">工具</div>
<button class="ni" data-pg="tools" onclick="nav('tools',this)"><span class="ic">🔧</span>功能中心</button>
<button class="ni" data-pg="sys" onclick="nav('sys',this)"><span class="ic">💾</span>系统管理</button>
<div class="ns">帮助</div>
<button class="ni" data-pg="about" onclick="nav('about',this)"><span class="ic">ℹ️</span>关于</button>
</nav>
<div class="sb-ft">已运行 <span id="uptime">--</span><div style="color:var(--red);font-size:9px;margin-top:4px">⚡ 仅供学习参考</div></div>
</aside>

<!-- MAIN -->
<main class="main">

<!-- DASHBOARD -->
<div class="page on" id="pg-dash">
<div class="ph"><h1>📊 系统仪表盘</h1><p>实时监控 · 数据可视化 · 运行状态</p></div>
<div class="sr" id="dashStats"></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px">
<div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:18px"><h4 style="font-size:13px;margin-bottom:12px;color:var(--text)">📈 评论活跃度趋势</h4><canvas id="chartComments" style="max-height:220px"></canvas></div>
<div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:18px"><h4 style="font-size:13px;margin-bottom:12px;color:var(--text)">💡 心情/精力指数</h4><canvas id="chartMood" style="max-height:220px"></canvas></div>
<div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:18px"><h4 style="font-size:13px;margin-bottom:12px;color:var(--text)">📅 每日操作统计</h4><canvas id="chartActions" style="max-height:220px"></canvas></div>
<div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:18px"><h4 style="font-size:13px;margin-bottom:12px;color:var(--text)">🔍 视频处理速率</h4><canvas id="chartVideos" style="max-height:220px"></canvas></div>
</div>
<div class="pc"><h3><span class="dot" id="botDot"></span>系统详情</h3><div id="botDetail"></div></div>
<div class="pc"><h3>📁 数据文件状态</h3><div id="fileGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;font-size:12px"></div></div>
<div style="background:rgba(248,81,73,.08);border:1px solid rgba(248,81,73,.25);border-radius:var(--r);padding:10px 16px;margin-top:20px;font-size:11px;color:var(--red);text-align:center;line-height:1.6">⚠ 免责声明：本项目仅供学习参考，若因使用本项目产生的任何后果，本人一律概不负责。</div>
</div>

<!-- CONTROL -->
<div class="page" id="pg-ctrl">
<div class="ph"><h1>🎮 机器人控制</h1><p>启动/停止/重启</p></div>
<div class="pc">
<h3>🤖 运行状态</h3><div id="ctrlStatus" style="margin-bottom:12px"></div>
<div class="btn-grp">
<button class="btn btn-suc btn-lg" id="btnStart" onclick="startBot()">▶ 启动机器人</button>
<button class="btn btn-dan btn-lg" id="btnStop" style="display:none" onclick="stopBot()">⏹ 停止</button>
<button class="btn btn-out" onclick="restartBot()">🔄 重启</button>
<button class="btn btn-out" onclick="clearLog()">🗑 清空日志</button>
</div>
</div>
<div class="pc"><h3>📡 实时输出</h3><div class="log-box" id="botLog">等待输出...</div></div>
<div style="background:rgba(248,81,73,.08);border:1px solid rgba(248,81,73,.25);border-radius:var(--r);padding:10px 16px;margin-top:16px;font-size:11px;color:var(--red);text-align:center;line-height:1.6">⚠ 免责声明：本项目仅供学习参考，若因使用本项目产生的任何后果，本人一律概不负责。</div>
</div>

<!-- LOGIN -->
<div class="page" id="pg-login">
<div class="ph"><h1>🔑 B站登录</h1><p>扫码登录 / 登出 / 状态</p></div>
<div class="pc" id="loginPanel">
<h3>📱 扫码登录</h3>
<div id="loginStatus"></div>
<div id="qrArea" style="display:none">
<div class="qr-wrap"><img id="qrImg" src="" alt="QR码"><div class="qr-status" id="qrStatusText"></div></div>
</div>
<div class="btn-grp">
<button class="btn btn-suc btn-lg" id="btnQR" onclick="startQRLogin()">📷 生成登录二维码</button>
<button class="btn btn-dan" id="btnLogout" onclick="logoutBili()">🚪 退出登录</button>
<button class="btn btn-out" onclick="checkLogin()">🔍 检查状态</button>
</div>
<div id="cookieInfo" style="margin-top:12px;font-size:11px;color:var(--text2)"></div>
</div>
</div>

<!-- CONFIG -->
<div class="page" id="pg-conf">
<div class="ph"><h1>⚙️ 配置编辑</h1><p>Data/config.json</p></div>
<div class="pc">
<textarea class="je" id="confEd"></textarea>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveConf()">💾 保存</button><button class="btn btn-out" onclick="loadConf()">🔄 重新加载</button></div>
</div>
</div>

<!-- PERSONA -->
<div class="page" id="pg-psna">
<div class="ph"><h1>🎭 人格管理</h1><p>管理机器人对话人格</p></div>
<div id="psnaList"></div>
</div>

<!-- COMMENTS -->
<div class="page" id="pg-cmts">
<div class="ph"><h1>💬 评论日志</h1><p>最近评论互动</p></div>
<div class="pc"><div id="cmtTab"></div></div>
</div>

<!-- USERS -->
<div class="page" id="pg-usrs">
<div class="ph"><h1>👤 用户画像</h1><p>好感度与印象</p></div>
<div class="pc"><div id="usrTab"></div></div>
</div>

<!-- MEMORY -->
<div class="page" id="pg-mem">
<div class="ph"><h1>🧠 记忆 & 知识库</h1></div>
<div id="memBox"></div>
</div>

<!-- DIARY -->
<div class="page" id="pg-diary">
<div class="ph"><h1>📖 日记 & 进化</h1></div>
<div id="diaryBox"></div>
</div>

<!-- ACTIONS -->
<div class="page" id="pg-acts">
<div class="ph"><h1>📋 操作日志</h1></div>
<div class="pc"><div id="actTab"></div></div>
</div>

<!-- MOOD -->
<div class="page" id="pg-mood">
<div class="ph"><h1>💡 心情管理</h1><p>查看/切换机器人心情状态</p></div>
<div class="pc"><h3>当前状态</h3><div id="moodStatus"></div></div>
<div class="pc"><h3>⚡ 快速切换心情</h3>
<div class="btn-grp" id="moodQuickBtns"></div>
</div>
<div class="pc"><h3>⚙️ 心情设置</h3>
<div class="fg"><label>默认心情</label><input id="moodDefault" placeholder="平静"></div>
<div class="fr">
<div class="fg"><label><input type="checkbox" id="moodRandom" onchange="moodToggleRandom()"> 随机心情切换</label></div>
<div class="fg"><label>随机间隔(分钟)</label><input id="moodRandInt" type="number" min="1" max="120"></div>
</div>
<div class="fr">
<div class="fg"><label><input type="checkbox" id="moodCustom" onchange="moodToggleCustom()"> 自定义心情</label></div>
<div class="fg"><label>自定义心情文字</label><input id="moodCustomText"></div>
</div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveMood()">💾 保存设置</button></div>
</div>
</div>

<!-- BEHAVIOR -->
<div class="page" id="pg-behavior">
<div class="ph"><h1>⚡ 行为设置</h1><p>AI免责声明 · 精力管理 · 评论模式</p></div>
<div class="pc"><h3>🤖 AI免责声明</h3>
<p style="font-size:11px;color:var(--text2);margin-bottom:10px">所有评论/私信回复末尾会追加免责声明标签。关闭后不再添加，但建议保持开启以遵守平台规定。</p>
<div class="fr" style="align-items:center;margin-bottom:8px">
<label class="toggle-sw"><input type="checkbox" id="aiMarkerOn" onchange="toggleAiMarker()"><span class="toggle-track"></span><span style="margin-left:10px;font-size:13px">启用免责声明</span></label>
</div>
<div class="fg"><label>免责声明文字</label><input id="aiMarkerText" placeholder="（内容由AI生成并由AI回复）" maxlength="50" style="max-width:300px"></div>
<div class="btn-grp"><button class="btn btn-pr" id="btnSaveMarker" onclick="saveAiMarker()">💾 保存</button><span id="aiMarkerMsg" style="font-size:11px;margin-left:8px"></span></div>
</div>
<div class="pc"><h3>⚡ 精力设置</h3>
<p style="font-size:11px;color:var(--text2);margin-bottom:10px">控制AI机器人精力恢复速度和行为间隔。</p>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
<div class="fg"><label>最大精力值</label><input id="engMaxEnergy" type="number" min="50" max="500" style="max-width:100px"></div>
<div class="fg"><label>每轮恢复(最小)</label><input id="engRecoverMin" type="number" min="1" max="50" style="max-width:100px"></div>
<div class="fg"><label>每轮恢复(最大)</label><input id="engRecoverMax" type="number" min="1" max="50" style="max-width:100px"></div>
<div class="fg"><label>恢复轮数(最小)</label><input id="engRoundsMin" type="number" min="1" max="20" style="max-width:100px"></div>
<div class="fg"><label>恢复轮数(最大)</label><input id="engRoundsMax" type="number" min="1" max="20" style="max-width:100px"></div>
<div class="fg"><label>轮间间隔(秒,最小)</label><input id="engRoundIntMin" type="number" min="10" max="600" style="max-width:100px"></div>
<div class="fg"><label>轮间间隔(秒,最大)</label><input id="engRoundIntMax" type="number" min="10" max="600" style="max-width:100px"></div>
<div class="fg"><label>视频间隔(秒,最小)</label><input id="engVideoIntMin" type="number" min="5" max="300" style="max-width:100px"></div>
<div class="fg"><label>视频间隔(秒,最大)</label><input id="engVideoIntMax" type="number" min="5" max="300" style="max-width:100px"></div>
</div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveEnergy()">💾 保存精力设置</button><span id="engMsg" style="font-size:11px;margin-left:8px"></span></div>
</div>
<div class="pc"><h3>💬 评论模式</h3>
<div class="fr" style="align-items:center;gap:12px">
<label style="cursor:pointer"><input type="radio" name="cmtMode" value="real" onchange="saveCommentMode()"> 真实模式 (发送到B站)</label>
<label style="cursor:pointer"><input type="radio" name="cmtMode" value="simulate" onchange="saveCommentMode()"> 模拟模式 (仅记录日志)</label>
</div>
<span id="cmtModeMsg" style="font-size:11px;margin-left:8px"></span>
</div>
</div>

<!-- UPFOLLOW -->
<div class="page" id="pg-upfu">
<div class="ph"><h1>👥 UP主关注列表</h1><p>AI已关注的UP主</p></div>
<div class="pc"><div id="upfuTab"></div></div>
</div>

<!-- TOOLS -->
<div class="page" id="pg-tools">
<div class="ph"><h1>🔧 功能中心</h1><p>手动操作 · 任务队列</p></div>
<div class="pc"><h3>🎬 手动发送弹幕</h3>
<div class="fr"><div class="fg"><label>BV号</label><input id="danmakuBvid" placeholder="BV1xx411c7mD"></div><div class="fg"><label>弹幕内容 (≤20字)</label><input id="danmakuText" maxlength="20" placeholder="第~"></div></div>
<button class="btn btn-pr" onclick="sendDanmaku()">📤 发送弹幕</button>
</div>
<div class="pc"><h3>📹 手动视频分析</h3>
<div class="fg"><label>BV号 / 视频链接</label><input id="analyzeBvid" placeholder="BV1xx411c7mD 或 完整链接"></div>
<button class="btn btn-pr" onclick="analyzeVideo()">🔍 开始分析</button>
</div>
<div class="pc"><h3>🤖 Agent 技能</h3>
<div class="fg"><label>目标描述（用自然语言描述你想让AI做什么）</label><input id="agentGoal" placeholder="例如：搜索"深度学习入门"并总结前3个视频"></div>
<button class="btn btn-pr" onclick="runAgent()">🚀 执行Agent</button>
</div>
<div class="pc"><h3>📚 知识库操作</h3>
<div class="btn-grp">
<button class="btn btn-pr" onclick="kbOrganize()">📂 一键整理知识库</button>
<button class="btn btn-out" onclick="kbRevisit()">📖 复习已学内容</button>
<button class="btn btn-out" onclick="rf_kbStats()">📊 查看统计</button>
</div>
<div id="kbStatBox" style="margin-top:12px;font-size:12px"></div>
</div>
</div>

<div class="pc"><h3>🎙️ ASR 语音识别设置</h3>
<p style="font-size:11px;color:var(--text2);margin-bottom:10px">语音识别引擎配置（FunASR / Whisper）。</p>
<div class="fr">
<div class="fg"><label>启用ASR</label><select id="asrEnabled"><option value="1">开启</option><option value="0">关闭</option></select></div>
<div class="fg"><label>识别引擎</label><select id="asrBackend"><option value="funasr">FunASR（推荐）</option><option value="whisper">Whisper</option></select></div>
<div class="fg"><label>语言</label><input id="asrLang" placeholder="zh" style="max-width:80px"></div>
<div class="fg"><label>说话人分离</label><select id="asrSep"><option value="1">开启</option><option value="0">关闭</option></select></div>
</div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveAsr()">💾 保存ASR设置</button><span id="asrMsg" style="font-size:11px;margin-left:8px"></span></div>
</div>
<div class="pc"><h3>⭐ Highlights 归档设置</h3>
<p style="font-size:11px;color:var(--text2);margin-bottom:10px">高分视频自动备份到 highlights/ 目录。</p>
<div class="fr">
<div class="fg"><label>启用归档</label><select id="dryEnabled"><option value="1">开启</option><option value="0">关闭</option></select></div>
<div class="fg"><label>最低评分门槛</label><input id="dryMinScore" type="number" min="5" max="10" step="0.5" value="8.0" style="max-width:100px"></div>
<div class="fg"><label>归档文件夹名</label><input id="dryFolder" placeholder="highlights" style="max-width:200px"></div>
</div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveDry()">💾 保存归档设置</button><span id="dryMsg" style="font-size:11px;margin-left:8px"></span></div>
</div>
<!-- SYSTEM -->

<div class="page" id="pg-sys">
<div class="ph"><h1>💾 系统管理</h1><p>备份 · 恢复 · 重置</p></div>
<div class="pc"><h3>📤 导出配置</h3><p style="font-size:11px;color:var(--text2)">一键导出全部配置到 C:\bilibili_claw_backup</p>
<button class="btn btn-pr" onclick="exportConfig()">📤 导出全部配置</button>
<div id="exportMsg" style="margin-top:8px;font-size:12px"></div>
</div>
<div class="pc"><h3>📥 导入配置</h3><p style="font-size:11px;color:var(--text2)">从备份文件恢复</p>
<button class="btn btn-out" onclick="listBackups()">🔍 刷新备份列表</button>
<div id="backupList" style="margin:10px 0;font-size:12px"></div>
</div>
<div class="pc" style="border-color:rgba(224,85,96,.3)">
<h3 style="color:var(--red)">⚠ 恢复出厂设置</h3>
<p style="font-size:11px;color:var(--text2)">清除所有配置、登录信息、数据文件。此操作不可逆！</p>
<div class="fg"><label><input type="checkbox" id="resetKB"> 同时删除知识库目录</label></div>
<button class="btn btn-dan" onclick="factoryReset()">🔥 恢复出厂设置</button>
</div>
</div>

<!-- ABOUT -->
<div class="page" id="pg-about">
<div class="ph"><h1>ℹ️ 关于系统</h1><p>版本信息 · 技术栈 · 联系方式</p></div>
<div class="pc" id="aboutBox"></div>
<div style="background:rgba(248,81,73,.08);border:1px solid rgba(248,81,73,.25);border-radius:var(--r);padding:10px 16px;margin-top:16px;font-size:11px;color:var(--red);text-align:center;line-height:1.6">⚠ 免责声明：本项目仅供学习参考，若因使用本项目产生的任何后果，本人一律概不负责。</div>
</div>

</main>

<div class="toast" id="toast"></div>

<script>
// ── NAV ──
function nav(p,el){
document.querySelectorAll('.page').forEach(x=>x.classList.remove('on'));
document.querySelectorAll('.ni').forEach(x=>x.classList.remove('ac'));
document.getElementById('pg-'+p).classList.add('on');
if(el)el.classList.add('ac');
if(window['rf_'+p])window['rf_'+p]();
// 移动端关闭侧边栏
if(window.innerWidth<768)toggleSidebar(true);
}
function toggleSidebar(force){
var s=document.getElementById('sidebar'),o=document.getElementById('mobOverlay');
if(typeof force=='boolean'){s.classList.toggle('show',force);o.classList.toggle('show',force)}
else{s.classList.toggle('show');o.classList.toggle('show')}
}

// ── TOAST ──
function toast(m,t){t=t||'inf';var x=document.getElementById('toast');x.textContent=m;x.className='toast '+t+' show';setTimeout(function(){x.classList.remove('show')},2200)}

// ── API ──
async function api(m,u,b){var o={method:m,headers:{'Content-Type':'application/json'}};if(b)o.body=JSON.stringify(b);var r=await fetch(u,o);return r.json()}

// ── CHART HELPERS ──
var _charts={};
function _destroyC(k){if(_charts[k]){_charts[k].destroy();_charts[k]=null}}
function _makeLine(canvasId,labels,datasets){
_destroyC(canvasId);
var ctx=document.getElementById(canvasId);if(!ctx)return;
_charts[canvasId]=new Chart(ctx,{
type:'line',data:{labels:labels,datasets:datasets},
options:{responsive:true,maintainAspectRatio:false,animation:{duration:600},
plugins:{legend:{labels:{color:'#8b949e',font:{size:11},usePointStyle:true,padding:12}}},
scales:{x:{ticks:{color:'#8b949e',font:{size:10},maxTicksLimit:8},grid:{color:'rgba(38,48,64,.4)'}},y:{ticks:{color:'#8b949e',font:{size:10}},grid:{color:'rgba(38,48,64,.4)'},beginAtZero:true}}
}});
}

// ── DASH ──
async function rf_dash(){
try{
var d=await api('GET','/api/info');
var h='';
h+='<div class="sc"><div class="si bl">🤖</div><div><div class="sv">'+(d.bot_running?'运行中':'已停止')+'</div><div class="sl">机器人状态</div></div></div>';
h+='<div class="sc"><div class="si gn">🔑</div><div><div class="sv">'+(d.bili_logged_in?'已登录':'未登录')+'</div><div class="sl">B站认证</div></div></div>';
h+='<div class="sc"><div class="si or">⚙️</div><div><div class="sv">'+(d.config_sections||0)+'</div><div class="sl">配置项</div></div></div>';
h+='<div class="sc"><div class="si pk">⏱</div><div><div class="sv" id="puptime">--</div><div class="sl">运行时长</div></div></div>';
h+='<div class="sc"><div class="si pp">📦</div><div><div class="sv">'+(d.data_files||0)+'</div><div class="sl">数据文件</div></div></div>';
document.getElementById('dashStats').innerHTML=h;
document.getElementById('puptime').textContent=d.uptime;

var dot=document.getElementById('botDot');dot.className='dot '+(d.bot_running?'on':'off');
var bd='<table class="tb"><tr><th>项目</th><th>值</th><th>项目</th><th>值</th></tr>';
bd+='<tr><td>运行状态</td><td><span class="tg '+(d.bot_running?'tg-suc':'tg-war')+'">'+(d.bot_running?'● 运行中':'○ 已停止')+'</span></td><td>启动时间</td><td>'+(d.bot_start_time||'-')+'</td></tr>';
bd+='<tr><td>API状态</td><td><span class="tg '+(d.api_configured?'tg-suc':'tg-dan')+'">'+(d.api_configured?'已配置':'未配置')+'</span></td>';
if(d.mood)bd+='<td>心情 / 精力</td><td>'+(d.mood.mood||'-')+' / '+(d.mood.energy||'?')+'</td>';
else bd+='<td>心情</td><td>-</td>';
bd+='</tr>';
if(d.persona)bd+='<tr><td>当前人格</td><td>'+esc(d.persona.active||'-')+'</td>';
else bd+='<tr><td>当前人格</td><td>-</td>';
if(d.cost_total!=null)bd+='<td>累计费用</td><td>$'+Number(d.cost_total).toFixed(4)+'</td>';
else bd+='<td>累计费用</td><td>-</td>';
bd+='</tr>';
bd+='</table>';
document.getElementById('botDetail').innerHTML=bd;

var fg='';
var flbs={'config.json':'配置','bilibili_cookies.json':'Cookie','comment_log.json':'评论日志','user_profiles.json':'用户画像','mood_state.json':'心情状态','personas.json':'人格数据','bot_diary.json':'日记','self_evolution.json':'进化记录','agent_skill_log.json':'Agent日志','bot_runtime_state.json':'运行时'};
for(var k in d.files||{}){
var f=d.files[k],lb=flbs[k]||k,cl=f.exists?'tg-suc':'tg-war';
fg+='<div><span class="tg '+cl+'">'+lb+'</span> '+(f.exists?f.size_fmt+' · '+f.mtime:'无')+'</div>';
}
document.getElementById('fileGrid').innerHTML=fg||'<div class="emp">无数据文件</div>';

// badges
document.getElementById('botBadge').style.display=d.bot_running?'':'none';
document.getElementById('botBadge').style.background=d.bot_running?'var(--green)':'';
document.getElementById('loginBadge').style.display=d.bili_logged_in?'':'none';

// Charts
try{
var ch=await api('GET','/api/charts');
if(ch.comments){var ds=[],cs=[];for(var i=0;i<ch.comments.length;i++){ds.push(ch.comments[i].date);cs.push(ch.comments[i].count)}_makeLine('chartComments',ds,[{label:'评论数',data:cs,borderColor:'#58a6ff',backgroundColor:'rgba(88,166,255,.1)',borderWidth:2,tension:.3,fill:true}]);}
if(ch.moods){var md=[],mv=[],me=[];for(var i=0;i<ch.moods.length;i++){md.push(ch.moods[i].date);mv.push(ch.moods[i].valence||50);me.push(ch.moods[i].energy||50)}_makeLine('chartMood',md,[{label:'情绪指数',data:mv,borderColor:'#db61a2',backgroundColor:'rgba(219,97,162,.08)',borderWidth:2,tension:.3,fill:true},{label:'精力指数',data:me,borderColor:'#3fb950',backgroundColor:'rgba(63,185,80,.08)',borderWidth:2,tension:.3,fill:true}]);}
if(ch.actions){var ad=[],ac=[];for(var i=0;i<ch.actions.length;i++){ad.push(ch.actions[i].date);ac.push(ch.actions[i].count)}_makeLine('chartActions',ad,[{label:'操作数',data:ac,borderColor:'#d2991d',backgroundColor:'rgba(210,153,29,.1)',borderWidth:2,tension:.3,fill:true}]);}
if(ch.videos){var vd=[],vc=[];for(var i=0;i<ch.videos.length;i++){vd.push(ch.videos[i].date);vc.push(ch.videos[i].count)}_makeLine('chartVideos',vd,[{label:'处理视频数',data:vc,borderColor:'#a371f7',backgroundColor:'rgba(163,113,247,.1)',borderWidth:2,tension:.3,fill:true}]);}
}catch(e){}
}catch(e){}
}

// ── CONTROL ──
var logPoll=null;
var userScrolledUp=false;
function rf_ctrl(){
upCtrlUI();
pollLog();
var lb=document.getElementById('botLog');
if(lb){
lb.addEventListener('scroll',function(){
var el=lb;
var atBottom=el.scrollHeight - el.scrollTop - el.clientHeight < 30;
userScrolledUp=!atBottom;
});
}
}
async function upCtrlUI(){
var d=await api('GET','/api/info');
document.getElementById('ctrlStatus').innerHTML=d.bot_running?'<span class="tg tg-suc pulse">● 运行中</span> 自 '+esc(d.bot_start_time||''):'<span class="tg tg-war">○ 已停止</span>';
document.getElementById('btnStart').style.display=d.bot_running?'none':'';
document.getElementById('btnStop').style.display=d.bot_running?'':'none';
}
async function startBot(){
var r=await api('POST','/api/bot/start');toast(r.message,r.ok?'ok':'err');upCtrlUI();if(r.ok){userScrolledUp=false;pollLog();rf_dash()}
}
async function stopBot(){
var r=await api('POST','/api/bot/stop');toast(r.message,r.ok?'ok':'err');upCtrlUI();if(r.ok)rf_dash()
}
async function restartBot(){await stopBot();setTimeout(startBot,1200)}
async function clearLog(){await api('POST','/api/bot/clear');document.getElementById('botLog').textContent='日志已清空';userScrolledUp=false;pollLog()}
async function pollLog(){
if(logPoll)clearInterval(logPoll);
var tick=async function(){
try{
var r=await api('GET','/api/bot/output');
var el=document.getElementById('botLog');
var wasAtBottom=el&&(el.scrollHeight-el.scrollTop-el.clientHeight<30);
if(el){
el.textContent=r.output||'无输出';
if(!userScrolledUp||wasAtBottom)el.scrollTop=el.scrollHeight;
}
}catch(e){}
};
tick();
logPoll=setInterval(tick,2000);
}
function stopPoll(){if(logPoll){clearInterval(logPoll);logPoll=null}}

// ── LOGIN ──
var qrTimer=null;
function rf_login(){
checkLogin();
}
async function checkLogin(){
try{
var d=await api('GET','/api/info');
var ci=document.getElementById('cookieInfo');
if(d.bili_logged_in){
document.getElementById('loginStatus').innerHTML='<span class="tg tg-suc">✅ 已登录B站</span>';
ci.innerHTML='Cookie 文件: Data/bilibili_cookies.json';
document.getElementById('btnQR').textContent='🔄 重新登录';
document.getElementById('btnLogout').style.display='';
document.getElementById('loginBadge').style.display='';
} else {
document.getElementById('loginStatus').innerHTML='<span class="tg tg-war">❌ 未登录</span>';
ci.innerHTML='尚未登录B站账号';
document.getElementById('btnQR').textContent='📷 生成登录二维码';
document.getElementById('btnLogout').style.display='none';
document.getElementById('loginBadge').style.display='none';
}
}catch(e){}
}
async function startQRLogin(){
document.getElementById('qrArea').style.display='block';
document.getElementById('qrStatusText').textContent='⏳ 正在生成二维码...';
document.getElementById('qrImg').src='';
var r=await api('POST','/api/bili/qr/start');
if(!r.ok){toast(r.message,'err');return}
document.getElementById('qrImg').src='data:image/png;base64,'+r.img;
document.getElementById('qrStatusText').textContent=r.message;
if(qrTimer)clearInterval(qrTimer);
qrTimer=setInterval(pollQR,2000);
}
async function pollQR(){
try{
var r=await api('GET','/api/bili/qr/status');
document.getElementById('qrStatusText').textContent=r.message;
if(r.status=='success'){
clearInterval(qrTimer);qrTimer=null;
toast('登录成功！UID: '+r.uid,'ok');
setTimeout(function(){document.getElementById('qrArea').style.display='none';checkLogin();rf_dash()},1500);
}else if(r.status=='timeout'||r.status=='error'){
clearInterval(qrTimer);qrTimer=null;
toast(r.message,'err');
document.getElementById('qrArea').style.display='none';
}
}catch(e){clearInterval(qrTimer);qrTimer=null}
}
async function logoutBili(){
if(!confirm('确定退出B站登录？'))return;
var r=await api('POST','/api/bili/logout');toast(r.message,r.ok?'ok':'err');checkLogin();rf_dash()
}

// ── CONFIG ──
function rf_conf(){loadConf()}
async function loadConf(){try{var r=await api('GET','/api/config');document.getElementById('confEd').value=JSON.stringify(r,null,2)}catch(e){toast('加载失败','err')}}
async function saveConf(){try{var v=JSON.parse(document.getElementById('confEd').value);var r=await api('POST','/api/config',v);toast(r.message,r.ok?'ok':'err')}catch(e){toast('JSON格式错误: '+e.message,'err')}}

// ── PERSONA ──
async function rf_psna(){
try{
var r=await api('GET','/api/personas');var h='',items=r.items||{},act=r.active||'';
for(var n in items){
var p=items[n],isA=n===act;
h+=`<div class="pc"><h3>${isA?'<span class="tg tg-suc">● 活跃</span> ':''}${n}</h3><div style="font-size:11px;color:var(--text2)">风格：${p.style||'-'} | 规则：${(p.rules||[]).length}条</div><div class="btn-grp">${isA?'':'<button class="btn btn-sm btn-pr" onclick="actPsna(\''+n+'\')">启用</button>'}<button class="btn btn-sm btn-out" onclick="delPsna(\''+n+'\')" ${Object.keys(items).length<2?'disabled':''}>删除</button></div></div>`;
}
h+=`<div class="pc"><h3>➕ 新建人设</h3><div class="fg"><label>名称</label><input id="npName" placeholder="如: 毒舌模式"></div><div class="fg"><label>系统Prompt</label><textarea id="npPrompt" placeholder="你是..."></textarea></div><div class="fg"><label>风格</label><input id="npStyle" placeholder="幽默、犀利"></div><button class="btn btn-pr" onclick="addPsna()">创建</button></div>`;
document.getElementById('psnaList').innerHTML=h;
}catch(e){}
}
async function addPsna(){
var n=document.getElementById('npName').value.trim(),p=document.getElementById('npPrompt').value.trim(),s=document.getElementById('npStyle').value.trim();
if(!n){toast('请输入名称','err');return}
var r=await api('POST','/api/personas',{name:n,system_prompt:p,style:s});toast(r.message,r.ok?'ok':'err');if(r.ok)rf_psna()
}
async function actPsna(n){var r=await api('POST','/api/personas/activate',{name:n});toast(r.message,r.ok?'ok':'err');if(r.ok)rf_psna()}
async function delPsna(n){if(!confirm('删除"'+n+'"？'))return;var r=await api('DELETE','/api/personas/'+encodeURIComponent(n));toast(r.message,r.ok?'ok':'err');if(r.ok)rf_psna()}

// ── COMMENTS ──
async function rf_cmts(){
try{
var r=await api('GET','/api/comments?limit=50'),its=r.items||[];
if(!its.length){document.getElementById('cmtTab').innerHTML='<div class="emp"><div class="ic">💬</div>暂无评论记录</div>';return}
var h='<table class="tb"><tr><th>时间</th><th>类型</th><th>内容</th><th>来源</th><th>状态</th></tr>';
for(var i=0;i<its.length;i++){var c=its[i];h+=`<tr><td>${c.time||'-'}</td><td><span class="tg tg-inf">${c.type||'-'}</span></td><td title="${esc(c.content||'')}">${(c.content||'').substring(0,50)}</td><td>${c.source||'-'}</td><td>${c.executed?'<span class="tg tg-suc">已执行</span>':'<span class="tg tg-war">草稿</span>'}</td></tr>`}
h+='</table>';document.getElementById('cmtTab').innerHTML=h;
}catch(e){}
}

// ── USERS ──
async function rf_usrs(){
try{
var r=await api('GET','/api/users'),u=r.users||{},ks=Object.keys(u);
if(!ks.length){document.getElementById('usrTab').innerHTML='<div class="emp"><div class="ic">👤</div>暂无用户画像</div>';return}
var h='<table class="tb"><tr><th>用户</th><th>好感度</th><th>关系</th><th>最近印象</th><th>更新时间</th></tr>';
for(var k in u){var p=u[k],a=parseInt(p.affinity)||0,cl=a>=80?'tg-suc':a>=45?'tg-inf':a<=-40?'tg-dan':'tg-war';
h+=`<tr><td>${p.name||k}</td><td><span class="tg ${cl}">${a}</span></td><td>${rel(a)}</td><td>${(p.notes||[]).slice(-2).join('；').substring(0,35)||'-'}</td><td>${p.updated_at||'-'}</td></tr>`}
h+='</table>';document.getElementById('usrTab').innerHTML=h;
}catch(e){}
}
function rel(a){var s=parseInt(a)||0;return s>=80?'挚友':s>=45?'熟人':s>=10?'有点印象':s<=-40?'需谨慎':'普通'}

// ── MEMORY ──
async function rf_mem(){
try{
var r=await api('GET','/api/memory'),h='';
if(r.diary&&r.diary.entries&&r.diary.entries.length){
h+='<div class="pc"><h3>📖 日记 ('+r.diary.entries.length+'条)</h3>';
var es=r.diary.entries.slice(-15).reverse();
for(var i=0;i<es.length;i++){var d=es[i];h+=`<div style="padding:8px;margin:4px 0;background:var(--bg3);border-radius:6px;font-size:11px"><strong>${d.time||''} ${d.mood||''}</strong><div style="color:var(--text2)">${(d.content||'').substring(0,180)}</div></div>`}
h+='</div>'}
if(r.evolution&&r.evolution.events&&r.evolution.events.length){
h+='<div class="pc"><h3>🧬 进化事件 ('+r.evolution.events.length+'条)</h3>';
var evs=r.evolution.events.slice(-15).reverse();
for(var i=0;i<evs.length;i++){var e=evs[i];h+=`<div style="font-size:11px;color:var(--text2);margin:2px 0">${e.time||''} [${e.type||''}] ${(e.detail||'').substring(0,120)}</div>`}
h+='</div>'}
document.getElementById('memBox').innerHTML=h||'<div class="emp"><div class="ic">🧠</div>暂无记忆数据</div>';
}catch(e){}
}

// ── DIARY ──
async function rf_diary(){
try{
var r=await api('GET','/api/diary'),h='';
if(r.diary&&r.diary.entries&&r.diary.entries.length){
h+='<div class="pc"><h3>📖 日记</h3>';
var es=r.diary.entries.slice(-20).reverse();
for(var i=0;i<es.length;i++){var d=es[i];h+=`<div style="border-bottom:1px solid var(--border);padding:8px 0"><div style="font-size:10px;color:var(--accent)">${d.time||''} · ${d.mood||''} · 精力${d.energy||'?'}</div><div style="font-size:11px;line-height:1.4">${(d.content||'').substring(0,200)}</div></div>`}
h+='</div>'}
if(r.evolution&&r.evolution.events&&r.evolution.events.length){
h+='<div class="pc"><h3>🧬 进化</h3><table class="tb"><tr><th>时间</th><th>类型</th><th>详情</th></tr>';
var evs=r.evolution.events.slice(-20).reverse();
for(var i=0;i<evs.length;i++){var e=evs[i];h+=`<tr><td>${e.time||'-'}</td><td>${e.type||'-'}</td><td style="max-width:260px">${(e.detail||'').substring(0,120)}</td></tr>`}
h+='</table></div>'}
document.getElementById('diaryBox').innerHTML=h||'<div class="emp"><div class="ic">📖</div>暂无数据</div>';
}catch(e){}
}

// ── ACTIONS ──
async function rf_acts(){
try{
var r=await api('GET','/api/actions?limit=40'),its=r.items||[];
if(!its.length){document.getElementById('actTab').innerHTML='<div class="emp"><div class="ic">📋</div>暂无操作日志</div>';return}
var h='<table class="tb"><tr><th>时间</th><th>操作</th><th>详情</th><th>状态</th></tr>';
for(var i=0;i<its.length;i++){var a=its[i];h+=`<tr><td>${a.time||'-'}</td><td>${a.action||'-'}</td><td title="${esc(JSON.stringify(a.payload||{}))}">${JSON.stringify(a.payload||{}).substring(0,60)}</td><td>${a.executed?'<span class="tg tg-suc">已执行</span>':'<span class="tg tg-war">草稿</span>'}</td></tr>`}
h+='</table>';document.getElementById('actTab').innerHTML=h;
}catch(e){}
}

// ── ABOUT ──
async function rf_about(){
try{
var d=await api('GET','/api/info');
document.getElementById('aboutBox').innerHTML='<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">'+
'<div style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:14px 16px"><div style="font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">系统版本</div><div style="font-size:15px;color:var(--text);font-weight:500">v1.0</div></div>'+
'<div style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:14px 16px"><div style="font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">面板运行时长</div><div style="font-size:15px;color:var(--text);font-weight:500">'+d.uptime+'</div></div>'+
'<div style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:14px 16px"><div style="font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">Python 版本</div><div style="font-size:15px;color:var(--text);font-weight:500">'+(d.python_version||'-')+'</div></div>'+
'<div style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:14px 16px"><div style="font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">运行平台</div><div style="font-size:15px;color:var(--text);font-weight:500">'+(d.platform||'-')+'</div></div>'+
'<div style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:14px 16px"><div style="font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">工作目录</div><div style="font-size:11px;color:var(--text);font-weight:500;font-family:monospace">'+(d.cwd||'-')+'</div></div>'+
'<div style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:14px 16px"><div style="font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">机器人状态</div><div style="font-size:15px;color:var(--text);font-weight:500">'+(d.bot_running?'● 运行中':'○ 已停止')+'</div></div>'+
'</div>'+
'<hr style="border-color:var(--border);margin:14px 0">'+
'<p style="font-size:12px;color:var(--text2);line-height:2"><strong style="color:var(--text)">B站 AI 智能管理系统</strong><br>基于大语言模型 · 视频理解 · 评论互动 · 私信回复 · 知识沉淀 · 自我进化</p>'+
'<div style="margin-top:14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap"><span style="color:var(--text2);font-size:12px">作者联系方式：</span><span style="display:inline-flex;align-items:center;gap:6px;background:rgba(88,166,255,.08);padding:6px 14px;border-radius:6px;color:var(--accent);font-weight:600;font-size:14px;letter-spacing:.5px">🐧 QQ: 3781960338</span></div>';
}catch(e){}
}

// ── UTIL ──
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}

// ── AUTO REFRESH ──
var autoTmr=null;
function auto(){
if(autoTmr)return;
autoTmr=setInterval(async function(){
var ap=document.querySelector('.page.on');if(!ap)return;
var id=ap.id.replace('pg-','');if(window['rf_'+id])window['rf_'+id]();
try{var d=await api('GET','/api/info');document.getElementById('uptime').textContent=d.uptime}catch(e){}
},8000);
}

// ── MOOD ──
var moodPresets=["开心","平静","好奇","兴奋","沉思","疲惫","慵懒","元气满满"];
function rf_mood(){fetchMood();
var h="";for(var i=0;i<moodPresets.length;i++){h+="<button class=\"btn btn-out btn-sm\" onclick=\"quickMood('"+moodPresets[i]+"')\">"+moodPresets[i]+"</button> "}
document.getElementById("moodQuickBtns").innerHTML=h;}
async function fetchMood(){
try{var r=await api("GET","/api/mood/status");
document.getElementById("moodStatus").innerHTML="<div style=\"font-size:14px\">当前心情: <strong style=\"color:var(--accent);font-size:18px\">"+esc(r.current_mood||"-")+"</strong> | 精力: <strong style=\"color:var(--green)\">"+esc(r.energy||"?")+"</strong></div>";
document.getElementById("moodDefault").value=r.default_mood||"";document.getElementById("moodRandom").checked=r.random_enabled;
document.getElementById("moodRandInt").value=r.random_interval||5;document.getElementById("moodCustom").checked=r.custom_enabled;
document.getElementById("moodCustomText").value=r.custom_mood||"";}catch(e){}}
async function quickMood(m){var r=await api("POST","/api/mood/set",{current_mood:m});toast(r.message,r.ok?"ok":"err");if(r.ok)fetchMood()}
async function saveMood(){
var b={default_mood:document.getElementById("moodDefault").value,random_enabled:document.getElementById("moodRandom").checked,
random_interval_minutes:parseInt(document.getElementById("moodRandInt").value)||5,
custom_enabled:document.getElementById("moodCustom").checked,custom_mood:document.getElementById("moodCustomText").value};
var r=await api("POST","/api/mood/set",b);toast(r.message,r.ok?"ok":"err");if(r.ok)fetchMood()}
function moodToggleRandom(){document.getElementById("moodRandInt").disabled=!document.getElementById("moodRandom").checked}
function moodToggleCustom(){document.getElementById("moodCustomText").disabled=!document.getElementById("moodCustom").checked}

// ── BEHAVIOR ──
var _aiMarkerConfirmed=false;
function rf_behavior(){fetchBehavior()}
async function fetchBehavior(){
try{
var r=await api("GET","/api/behavior/get");
document.getElementById("aiMarkerText").value=r.ai_marker||"（内容由AI生成并由AI回复）";
var on=r.ai_marker&&r.ai_marker.length>0;
document.getElementById("aiMarkerOn").checked=on;
// energy
var e=r.energy||{};
document.getElementById("engMaxEnergy").value=e.max_energy||100;
document.getElementById("engRecoverMin").value=e.energy_recovery_min||5;
document.getElementById("engRecoverMax").value=e.energy_recovery_max||10;
document.getElementById("engRoundsMin").value=e.rounds_min||3;
document.getElementById("engRoundsMax").value=e.rounds_max||10;
document.getElementById("engRoundIntMin").value=e.round_interval_min||60;
document.getElementById("engRoundIntMax").value=e.round_interval_max||180;
document.getElementById("engVideoIntMin").value=e.video_interval_min||20;
document.getElementById("engVideoIntMax").value=e.video_interval_max||50;
// comment mode
var cm=r.comment_mode||"real";
var radios=document.getElementsByName("cmtMode");
for(var i=0;i<radios.length;i++){if(radios[i].value===cm)radios[i].checked=true}
}catch(e){}
}
async function toggleAiMarker(){
var cb=document.getElementById("aiMarkerOn");
if(!cb.checked){
if(confirm("⚠️ 确定要关闭AI免责声明吗？\n\n关闭后，所有评论和私信回复将不再标注AI身份。\n这可能导致平台审核风险。\n\n再次点击设置中的开关可以重新开启。")){
_aiMarkerConfirmed=true;
}else{
cb.checked=true;
return;
}
}
var r=await api("POST","/api/behavior/ai-marker/toggle",{enabled:cb.checked});
document.getElementById("aiMarkerText").value=r.marker||"";
document.getElementById("aiMarkerMsg").textContent=r.message||"";
toast(r.message,r.ok?"ok":"err");
}
async function saveAiMarker(){
var txt=document.getElementById("aiMarkerText").value.trim();
var r=await api("POST","/api/behavior/save",{ai_marker:txt});
document.getElementById("aiMarkerMsg").textContent=r.message||"";
toast(r.message,r.ok?"ok":"err");
}
async function saveEnergy(){
var b={
max_energy:parseInt(document.getElementById("engMaxEnergy").value)||100,
energy_recovery_min:parseInt(document.getElementById("engRecoverMin").value)||5,
energy_recovery_max:parseInt(document.getElementById("engRecoverMax").value)||10,
rounds_min:parseInt(document.getElementById("engRoundsMin").value)||3,
rounds_max:parseInt(document.getElementById("engRoundsMax").value)||10,
round_interval_min:parseInt(document.getElementById("engRoundIntMin").value)||60,
round_interval_max:parseInt(document.getElementById("engRoundIntMax").value)||180,
video_interval_min:parseInt(document.getElementById("engVideoIntMin").value)||20,
video_interval_max:parseInt(document.getElementById("engVideoIntMax").value)||50
};
var r=await api("POST","/api/behavior/save",{energy:b});
document.getElementById("engMsg").textContent=r.message||"";
toast(r.message,r.ok?"ok":"err");
}
async function saveCommentMode(){
var cm=document.querySelector('input[name="cmtMode"]:checked');
if(!cm)return;
var r=await api("POST","/api/behavior/save",{comment_mode:cm.value});
document.getElementById("cmtModeMsg").textContent=r.message||"";
toast(r.message,r.ok?"ok":"err");
}

// ── UPFOLLOW ──
async function rf_upfu(){
try{var r=await api("GET","/api/up-follow/list");var its=r.items||[];
if(!its.length){document.getElementById("upfuTab").innerHTML="<div class=\"emp\"><div class=\"ic\">👥</div>暂无已关注的UP主</div>";return}
its.sort(function(a,b){return (b.avg_score||0)-(a.avg_score||0)});
var h="<table class=\"tb\"><tr><th>#</th><th>UP主</th><th>UID</th><th>评分</th><th>印象次数</th><th>关注时间</th></tr>";
for(var i=0;i<its.length;i++){var u=its[i];h+="<tr><td>"+(i+1)+"</td><td>"+(u.favorited?"⭐ ":"")+u.name+"</td><td class=\"mono\">"+u.uid+"</td><td>"+(u.avg_score||"-")+"</td><td>"+(u.impressions||0)+"</td><td>"+(u.followed_at||"-")+"</td></tr>"}
h+="</table>";document.getElementById("upfuTab").innerHTML=h}catch(e){}}

// ── TOOLS ──
function rf_tools(){rf_kbStats();loadAsrHighlight()}
async function sendDanmaku(){
var b=document.getElementById("danmakuBvid").value.trim(),t=document.getElementById("danmakuText").value.trim();
if(!b||!t){toast("请填写BV号和弹幕内容","err");return}
if(t.length>20){toast("弹幕不能超过20字","err");return}
var r=await api("POST","/api/action/send-danmaku",{bvid:b,text:t});toast(r.message,r.ok?"ok":"err")}
async function analyzeVideo(){
var b=document.getElementById("analyzeBvid").value.trim();
if(!b){toast("请输入BV号","err");return}
var r=await api("POST","/api/action/analyze-video",{bvid:b});toast(r.message,r.ok?"ok":"err")}
async function runAgent(){
var g=document.getElementById("agentGoal").value.trim();
if(!g){toast("请输入目标描述","err");return}
var r=await api("POST","/api/action/agent-skill",{goal:g});toast(r.message,r.ok?"ok":"err")}
async function kbOrganize(){
if(!confirm("将对知识库进行AI自动分类整理，继续？"))return;
var r=await api("POST","/api/action/kb-organize");toast(r.message,"ok")}
async function kbRevisit(){
if(!confirm("将从已学内容中随机挑选进行复习，继续？"))return;
var r=await api("POST","/api/action/kb-revisit");toast(r.message,"ok")}
async function rf_kbStats(){
try{var r=await api("GET","/api/kb/stats");var h="<strong>"+r.total_files+"</strong> 篇知识 · 分类: ";
var cs=Object.keys(r.categories||{}).sort();for(var i=0;i<cs.length;i++){h+=cs[i]+" ("+r.categories[cs[i]]+") "}
document.getElementById("kbStatBox").innerHTML=h||"暂无知识库数据"}catch(e){}}
// ── ASR & Highlights ──
async function saveAsr(){var c=await api("GET","/api/config");if(!c)return;
c.asr=c.asr||{};c.asr.enabled=document.getElementById("asrEnabled").value=="1";
c.asr.backend=document.getElementById("asrBackend").value;
c.asr.language=document.getElementById("asrLang").value;
c.asr.speaker_separation=document.getElementById("asrSep").value=="1";
var r=await api("POST","/api/config",c);
document.getElementById("asrMsg").innerHTML=r.ok?'<span style="color:var(--green)">已保存</span>':'<span style="color:var(--red)">'+esc(r.message||'')+'</span>'}
async function saveDry(){var c=await api("GET","/api/config");if(!c)return;
c.dry_goods=c.dry_goods||{};c.dry_goods.enabled=document.getElementById("dryEnabled").value=="1";
c.dry_goods.min_score=parseFloat(document.getElementById("dryMinScore").value)||8.0;
c.dry_goods.folder_name=document.getElementById("dryFolder").value||"highlights";
var r=await api("POST","/api/config",c);
document.getElementById("dryMsg").innerHTML=r.ok?'<span style="color:var(--green)">已保存</span>':'<span style="color:var(--red)">'+esc(r.message||'')+'</span>'}
async function loadAsrHighlight(){var c=await api("GET","/api/config");if(!c)return;
if(c.asr){document.getElementById("asrEnabled").value=c.asr.enabled?"1":"0";
document.getElementById("asrBackend").value=c.asr.backend||"funasr";
document.getElementById("asrLang").value=c.asr.language||"zh";
document.getElementById("asrSep").value=c.asr.speaker_separation!==false?"1":"0"}
if(c.dry_goods){document.getElementById("dryEnabled").value=c.dry_goods.enabled?"1":"0";
document.getElementById("dryMinScore").value=c.dry_goods.min_score||8.0;
document.getElementById("dryFolder").value=c.dry_goods.folder_name||"highlights"}}


// ── SYSTEM ──
function rf_sys(){listBackups()}
async function exportConfig(){
var r=await api("POST","/api/export");document.getElementById("exportMsg").innerHTML=r.ok?
"<span class=\"tg tg-suc\">"+r.message+"</span>":"<span class=\"tg tg-dan\">"+r.message+"</span>"}
async function listBackups(){
try{var r=await api("GET","/api/import");var fs=r.files||[];
if(!fs.length){document.getElementById("backupList").innerHTML="<div class=\"emp\">暂无备份文件</div>";return}
var h="<table class=\"tb\"><tr><th>文件名</th><th>时间</th><th>大小</th><th>操作</th></tr>";
for(var i=0;i<fs.length;i++){var f=fs[i];h+="<tr><td class=\"mono\">"+f.name+"</td><td>"+f.mtime+"</td><td>"+f.size+"</td><td><button class=\"btn btn-sm btn-pr\" onclick=\"importConfig('"+f.name+"')\">恢复</button></td></tr>"}
h+="</table>";document.getElementById("backupList").innerHTML=h}catch(e){}}
async function importConfig(fn){
if(!confirm("确定从 "+fn+" 恢复所有配置？当前配置将被覆盖！"))return;
var r=await api("POST","/api/import/apply",{filename:fn});toast(r.message,r.ok?"ok":"err");if(r.ok)rf_dash()}
async function factoryReset(){
if(!confirm("确定恢复出厂设置？此操作不可逆！\n将删除所有配置、登录信息、数据文件！"))return;
var delKB=document.getElementById("resetKB").checked;
if(delKB&&!confirm("同时删除知识库目录？此操作不可逆！"))return;
var r=await api("POST","/api/factory-reset",{delete_kb:delKB});toast(r.message,r.ok?"ok":"err");if(r.ok){rf_dash();listBackups()}}

// ── INIT ──
rf_dash();auto();
(async function(){try{var d=await api('GET','/api/info');document.getElementById('uptime').textContent=d.uptime}catch(e){}})();
</script>
</body>
</html>'''

# ═══════════════════════════════════════════
#  API 路由
# ═══════════════════════════════════════════
@app.route('/')
def index():
    return _load_html()

# ── 信息 ──
@app.route('/api/info')
def api_info():
    config = read_json(CONFIG_FILE)
    mood = read_json(DATA_DIR / "mood_state.json") or read_json(DATA_DIR / "web_mood.json")
    persona = read_json(DATA_DIR / "web_personas.json") or read_json(DATA_DIR / "personas.json")
    costs = read_json(DATA_DIR / "web_costs.json")
    api_key = config.get('api', {}).get('unified_api_key', '') or os.getenv('BILI_AI_API_KEY', '')
    bili_token = os.getenv('BILI_REFRESH_TOKEN', '') or config.get('bilibili', {}).get('refresh_token', '')

    files = {}
    for name in ['config.json', 'bilibili_cookies.json', 'comment_log.json', 'private_message_log.json',
                 'user_profiles.json', 'mood_state.json', 'personas.json', 'bot_diary.json',
                 'self_evolution.json', 'agent_skill_log.json', 'bot_runtime_state.json']:
        files[name] = file_stat(DATA_DIR / name)

    upt = datetime.now() - panel_start
    us = f"{upt.days}d{upt.seconds//3600}h{(upt.seconds%3600)//60}m" if upt.days>0 else f"{upt.seconds//3600}h{(upt.seconds%3600)//60}m{upt.seconds%60}s"

    comment_mode = config.get('behavior', {}).get('comment_mode', 'real')
    return jsonify(dict(
        bot_running=bot_running,
        bot_start_time=bot_start_time.strftime('%Y-%m-%d %H:%M:%S') if bot_start_time else None,
        uptime=us,
        api_configured=bool(api_key),
        bili_logged_in=bool(bili_token) or COOKIE_FILE.exists(),
        config_sections=len(config),
        data_files=sum(1 for f in files.values() if f['exists']),
        mood=dict(mood=mood.get('mood','?'), energy=mood.get('energy','?')) if mood else None,
        persona=dict(active=persona.get('active','')) if persona else None,
        cost_total=costs.get('total',0) if costs else 0,
        files=files,
        comment_mode=comment_mode,
        python_version=sys.version.split()[0],
        platform=sys.platform,
        cwd=str(BASE_DIR),
    ))

# ── 配置 ──
@app.route('/api/config', methods=['GET','POST'])
def api_config():
    if request.method=='GET':
        return jsonify(read_json(CONFIG_FILE))
    try:
        data = request.get_json(force=True)
        ok = write_json(CONFIG_FILE, data)
        return jsonify(dict(ok=ok, message='配置已保存' if ok else '保存失败'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

# ── 机器人控制 ──
@app.route('/api/bot/start', methods=['POST'])
def api_bot_start():
    ok, msg = start_bot_process()
    return jsonify(dict(ok=ok, message=msg))

@app.route('/api/bot/stop', methods=['POST'])
def api_bot_stop():
    ok, msg = stop_bot_process()
    return jsonify(dict(ok=ok, message=msg))

@app.route('/api/bot/output')
def api_bot_output():
    with bot_output_lock:
        lines = list(bot_output_lines[-80:])
    return jsonify(dict(output='\n'.join(lines) if lines else '等待输出...'))

@app.route('/api/bot/clear', methods=['POST'])
def api_bot_clear():
    global bot_output_lines
    with bot_output_lock:
        bot_output_lines.clear()
    log_line("日志已清空")
    return jsonify(dict(ok=True, message='日志已清空'))

# ── B站登录 ──
@app.route('/api/bili/qr/start', methods=['POST'])
def api_bili_qr_start():
    global qr_state
    if qr_state.get('active'):
        return jsonify(dict(ok=False, message='已有登录流程进行中'))

    threading.Thread(target=do_qr_login, daemon=True).start()
    # wait for QR code to actually be generated (up to 10s)
    for _ in range(20):
        time.sleep(0.5)
        if qr_state.get('img_b64') or qr_state.get('status') in ('waiting_scan', 'error', 'timeout'):
            break
    return jsonify(dict(
        ok=True,
        img=qr_state.get('img_b64', ''),
        message=qr_state.get('message', ''),
        status=qr_state.get('status', '')
    ))

@app.route('/api/bili/qr/status')
def api_bili_qr_status():
    return jsonify(dict(
        status=qr_state.get('status', 'idle'),
        message=qr_state.get('message', ''),
        uid=qr_state.get('uid', ''),
        active=qr_state.get('active', False),
    ))

@app.route('/api/bili/logout', methods=['POST'])
def api_bili_logout():
    try:
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()
        log_line("B站登录信息已清除")
        return jsonify(dict(ok=True, message='已退出登录'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

# ── 人格管理 ──
@app.route('/api/personas', methods=['GET','POST'])
def api_personas():
    data = read_json(DATA_DIR / "web_personas.json", dict(active="默认人格", items={}))
    if request.method=='GET':
        return jsonify(data)
    try:
        body = request.get_json(force=True)
        name = (body.get('name') or '').strip()
        if not name: return jsonify(dict(ok=False, message='名称不能为空')), 400
        data.setdefault('items', {})[name] = dict(
            name=name, system_prompt=body.get('system_prompt', ''),
            style=body.get('style',''), owner_prompt=body.get('owner_prompt',''),
            rules=body.get('rules',[]))
        write_json(DATA_DIR / "web_personas.json", data)
        return jsonify(dict(ok=True, message=f'人设"{name}"已创建'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/personas/activate', methods=['POST'])
def api_personas_activate():
    data = read_json(DATA_DIR / "web_personas.json", dict(active="默认人格", items={}))
    try:
        body = request.get_json(force=True)
        name = (body.get('name') or '').strip()
        if name not in data.get('items', {}):
            return jsonify(dict(ok=False, message='人设不存在')), 404
        data['active'] = name
        write_json(DATA_DIR / "web_personas.json", data)
        write_json(DATA_DIR / "personas.json", data['items'][name])
        return jsonify(dict(ok=True, message=f'已切换为"{name}"'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/personas/<name>', methods=['DELETE'])
def api_personas_delete(name):
    data = read_json(DATA_DIR / "web_personas.json", dict(active="默认人格", items={}))
    if len(data.get('items', {})) <= 1:
        return jsonify(dict(ok=False, message='至少保留一个人设')), 400
    if name in data.get('items', {}):
        del data['items'][name]
        if data.get('active') == name:
            data['active'] = next(iter(data['items']))
        write_json(DATA_DIR / "web_personas.json", data)
        return jsonify(dict(ok=True, message=f'已删除"{name}"'))
    return jsonify(dict(ok=False, message='不存在')), 404

# ── 评论日志 ──
@app.route('/api/comments')
def api_comments():
    limit = request.args.get('limit', 50, type=int)
    data = read_json(DATA_DIR / "comment_log.json", dict(items=[]))
    items = data.get('items', [])
    result = []
    for it in items[-limit:]:
        if isinstance(it, dict):
            result.append(dict(
                time=it.get('time', it.get('created_at', '')),
                type=it.get('type', it.get('action', '')),
                content=it.get('content', it.get('text', '')),
                source=it.get('source', ''),
                executed=it.get('executed', True),
            ))
    return jsonify(dict(items=result))

# ── 用户画像 ──
@app.route('/api/users')
def api_users():
    data = read_json(DATA_DIR / "user_profiles.json", dict(users={}))
    wu = read_json(DATA_DIR / "web_user_profiles.json", dict(users={}))
    users = {**data.get('users', {}), **wu.get('users', {})}
    return jsonify(dict(users=users))

# ── 记忆 ──
@app.route('/api/memory')
def api_memory():
    return jsonify(dict(
        diary=read_json(DATA_DIR / "bot_diary.json", dict(entries=[])),
        evolution=read_json(DATA_DIR / "self_evolution.json", dict(events=[])),
    ))

# ── 日记进化 ──
@app.route('/api/diary')
def api_diary():
    return jsonify(dict(
        diary=read_json(DATA_DIR / "bot_diary.json", dict(entries=[])),
        evolution=read_json(DATA_DIR / "self_evolution.json", dict(events=[])),
    ))

# ── 操作日志 ──
@app.route('/api/actions')
def api_actions():
    limit = request.args.get('limit', 50, type=int)
    data = read_json(DATA_DIR / "web_action_log.json", dict(items=[]))
    items = data.get('items', [])
    result = []
    for it in items[-limit:]:
        if isinstance(it, dict):
            result.append(dict(
                time=it.get('created_at', it.get('time', '')),
                action=it.get('action', ''),
                payload=it.get('payload', {}),
                executed=it.get('executed', False),
            ))
    return jsonify(dict(items=result))

# ── 图表数据 ──
@app.route('/api/charts')
def api_charts():
    """为仪表盘折线图提供历史统计数据"""
    days = request.args.get('days', 14, type=int)
    # 从 diary 数据提取心情/精力趋势
    diary = read_json(DATA_DIR / "bot_diary.json", dict(entries=[]))
    entries = diary.get('entries', [])
    mood_data = []
    for e in entries[-days*5:]:  # 每天可能有多个条目
        t = e.get('time', '')
        date = t[:10] if len(t) >= 10 else t  # YYYY-MM-DD
        mood_data.append(dict(
            date=date,
            valence=e.get('mood_score', e.get('valence', 50)),
            energy=int(e.get('energy', 50)),
        ))
    # 按天聚合
    daily_moods = {}
    for m in mood_data:
        d = m['date']
        if d not in daily_moods:
            daily_moods[d] = {'vals': [], 'engs': []}
        daily_moods[d]['vals'].append(m['valence'])
        daily_moods[d]['engs'].append(m['energy'])
    mood_result = []
    for d in sorted(daily_moods.keys())[-days:]:
        v = daily_moods[d]
        mood_result.append(dict(
            date=d[5:] if len(d)==10 else d,
            valence=round(sum(v['vals'])/len(v['vals']), 1),
            energy=round(sum(v['engs'])/len(v['engs']), 1),
        ))

    # 从评论日志提取评论趋势
    cmt_log = read_json(DATA_DIR / "comment_log.json", dict(items=[]))
    daily_cmts = {}
    for c in cmt_log.get('items', []):
        t = c.get('time', c.get('created_at', ''))
        date = t[:10] if len(t) >= 10 else t
        daily_cmts[date] = daily_cmts.get(date, 0) + 1
    cmt_result = [dict(date=d[5:] if len(d)==10 else d, count=c) for d, c in sorted(daily_cmts.items())[-days:]]

    # 从操作日志提取操作趋势
    act_log = read_json(DATA_DIR / "web_action_log.json", dict(items=[]))
    daily_acts = {}
    for a in act_log.get('items', []):
        t = a.get('created_at', a.get('time', ''))
        date = t[:10] if len(t) >= 10 else t
        daily_acts[date] = daily_acts.get(date, 0) + 1
    act_result = [dict(date=d[5:] if len(d)==10 else d, count=c) for d, c in sorted(daily_acts.items())[-days:]]

    # 视频处理来自 evolution 事件
    evo = read_json(DATA_DIR / "self_evolution.json", dict(events=[]))
    daily_vids = {}
    for ev in evo.get('events', []):
        t = ev.get('time', '')
        date = t[:10] if len(t) >= 10 else t
        detail = str(ev.get('detail', ''))
        if '视频' in detail or '观看' in detail or 'video' in detail.lower():
            daily_vids[date] = daily_vids.get(date, 0) + 1
    vid_result = [dict(date=d[5:] if len(d)==10 else d, count=c) for d, c in sorted(daily_vids.items())[-days:]]

    return jsonify(dict(
        comments=cmt_result,
        moods=mood_result if mood_result else [],
        actions=act_result,
        videos=vid_result,
    ))

# ── 心情管理 ──
@app.route('/api/mood/status')
def api_mood_status():
    mood = read_json(DATA_DIR / "mood_state.json", {})
    config = read_json(CONFIG_FILE, {})
    mc = config.get('mood', {})
    return jsonify(dict(
        current_mood=mood.get('mood', mc.get('default_mood', '平静')),
        energy=mood.get('energy', 100),
        random_enabled=mc.get('random_enabled', False),
        random_interval=mc.get('random_interval_minutes', 5),
        custom_enabled=mc.get('custom_enabled', False),
        custom_mood=mc.get('custom_mood', ''),
        default_mood=mc.get('default_mood', '平静'),
    ))

@app.route('/api/mood/set', methods=['POST'])
def api_mood_set():
    try:
        body = request.get_json(force=True)
        config = read_json(CONFIG_FILE, {})
        mc = config.setdefault('mood', {})
        if 'random_enabled' in body: mc['random_enabled'] = bool(body['random_enabled'])
        if 'random_interval_minutes' in body: mc['random_interval_minutes'] = int(body['random_interval_minutes'])
        if 'custom_enabled' in body: mc['custom_enabled'] = bool(body['custom_enabled'])
        if 'custom_mood' in body: mc['custom_mood'] = str(body['custom_mood'])
        if 'default_mood' in body: mc['default_mood'] = str(body['default_mood'])
        write_json(CONFIG_FILE, config)
        # 同时更新当前心情
        mood = read_json(DATA_DIR / "mood_state.json", {})
        if 'current_mood' in body:
            mood['mood'] = str(body['current_mood'])
            mood['updated_at'] = datetime.now().isoformat()
            write_json(DATA_DIR / "mood_state.json", mood)
        log_line(f"心情设置已更新")
        return jsonify(dict(ok=True, message='心情设置已更新'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

# ── 导出/导入配置 ──
BACKUP_DIR_EXPORT = Path(r"C:\bilibili_claw_backup") if sys.platform == 'win32' else Path.home() / "bilibili_claw_backup"

@app.route('/api/export', methods=['POST'])
def api_export():
    try:
        BACKUP_DIR_EXPORT.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_data = {}
        for fname in ['config.json', 'bilibili_cookies.json', 'mood_state.json', 'personas.json',
                       'user_profiles.json', 'comment_log.json', 'bot_diary.json',
                       'self_evolution.json', 'agent_skill_log.json', 'bot_runtime_state.json',
                       'history_videos.json', 'interests.json']:
            fp = DATA_DIR / fname
            if fp.exists():
                try:
                    export_data[fname] = json.loads(fp.read_text(encoding='utf-8'))
                except Exception:
                    export_data[fname] = {}
        # memory
        memf = BASE_DIR / "bot_memory.json"
        if memf.exists():
            try: export_data['bot_memory.json'] = json.loads(memf.read_text(encoding='utf-8'))
            except Exception: pass
        # knowledge metadata
        kmf = BASE_DIR / "knowledge_metadata.json"
        if kmf.exists():
            try: export_data['knowledge_metadata.json'] = json.loads(kmf.read_text(encoding='utf-8'))
            except Exception: pass

        out = BACKUP_DIR_EXPORT / f"bilibili_learning_bot_export_{ts}.json"
        out.write_text(json.dumps(export_data, ensure_ascii=False, indent=2), encoding='utf-8')
        log_line(f"配置已导出: {out}")
        return jsonify(dict(ok=True, message=f'配置已导出到 {out}', path=str(out)))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/import', methods=['POST'])
def api_import():
    try:
        files = []
        if BACKUP_DIR_EXPORT.exists():
            files = sorted([f for f in BACKUP_DIR_EXPORT.iterdir() if f.suffix == '.json'], key=lambda x: x.stat().st_mtime, reverse=True)
        # 返回可用备份列表
        flist = [dict(name=f.name, mtime=datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                      size=f"{f.stat().st_size/1024:.1f}K") for f in files[:20]]
        return jsonify(dict(files=flist))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/import/apply', methods=['POST'])
def api_import_apply():
    try:
        body = request.get_json(force=True)
        fname = body.get('filename', '')
        if not fname:
            return jsonify(dict(ok=False, message='未指定文件名')), 400
        # 安全：清洗文件名，防止路径穿越
        fname = sanitize_filename(fname)
        if not fname:
            return jsonify(dict(ok=False, message='非法文件名')), 400
        fpath = safe_join(BACKUP_DIR_EXPORT, fname)
        if not fpath or not fpath.exists():
            return jsonify(dict(ok=False, message='备份文件不存在')), 404
        data = json.loads(fpath.read_text(encoding='utf-8'))
        count = 0
        for key, val in data.items():
            if key == 'bot_memory.json':
                write_json(BASE_DIR / key, val)
            elif key == 'knowledge_metadata.json':
                write_json(BASE_DIR / key, val)
            else:
                write_json(DATA_DIR / key, val)
            count += 1
        log_line(f"配置已导入: {fname} ({count}个文件)")
        return jsonify(dict(ok=True, message=f'已导入 {count} 个文件'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

# ── 恢复出厂设置 ──
@app.route('/api/factory-reset', methods=['POST'])
def api_factory_reset():
    try:
        body = request.get_json(silent=True) or {}
        delete_kb = body.get('delete_kb', False)
        deleted = []
        for fname in ['config.json', 'bilibili_cookies.json', 'mood_state.json', 'personas.json',
                       'user_profiles.json', 'comment_log.json', 'bot_diary.json',
                       'self_evolution.json', 'agent_skill_log.json', 'bot_runtime_state.json',
                       'history_videos.json', 'interests.json', 'web_personas.json']:
            fp = DATA_DIR / fname
            if fp.exists():
                fp.unlink()
                deleted.append(fname)
        for fname in ['bot_memory.json', 'knowledge_metadata.json']:
            fp = BASE_DIR / fname
            if fp.exists():
                fp.unlink()
                deleted.append(fname)
        if delete_kb:
            kb_dir = BASE_DIR / "KnowledgeBase"
            if kb_dir.exists():
                import shutil
                shutil.rmtree(kb_dir, ignore_errors=True)
                deleted.append('KnowledgeBase/')
        # 清除日志
        global bot_output_lines
        with bot_output_lock:
            bot_output_lines.clear()
        log_line(f"恢复出厂设置完成，删除了 {len(deleted)} 个文件/目录" + ("（含知识库）" if delete_kb else ""))
        return jsonify(dict(ok=True, message=f'已清除 {len(deleted)} 个文件', deleted=deleted))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

# ── UP主关注列表 ──
@app.route('/api/up-follow/list')
def api_up_follow_list():
    mem_file = BASE_DIR / "bot_memory.json"
    ups = {}
    followed = []
    if mem_file.exists():
        try:
            mem = json.loads(mem_file.read_text(encoding='utf-8'))
            ups = mem.get('known_ups', {})
            for name, info in ups.items():
                if isinstance(info, dict) and info.get('followed'):
                    followed.append(dict(
                        name=name,
                        uid=info.get('uid', ''),
                        followed_at=info.get('followed_at', ''),
                        impressions=info.get('impressions', 0),
                        avg_score=round(info.get('total_score', 0) / max(info.get('impressions', 1), 1), 1),
                        favorited=info.get('favorited', False)
                    ))
        except Exception:
            pass
    return jsonify(dict(total=len(followed), items=followed))

# ── 知识库统计 ──
@app.route('/api/kb/stats')
def api_kb_stats():
    kb_dir = BASE_DIR / "KnowledgeBase"
    result = dict(exists=kb_dir.exists(), total_files=0, categories={})
    if kb_dir.exists():
        for root, dirs, files in os.walk(kb_dir):
            rel = os.path.relpath(root, kb_dir)
            parts = rel.split(os.sep) if rel != '.' else []
            depth = len(parts)
            md_files = [f for f in files if f.endswith('.md')]
            if md_files and depth <= 3:
                cat = '/'.join(parts[:3]) if parts else '根目录'
                result['categories'][cat] = result['categories'].get(cat, 0) + len(md_files)
            result['total_files'] += len(md_files)
    return jsonify(result)

# ── 功能操作 (桥接 CLI 功能) ──
@app.route('/api/action/analyze-video', methods=['POST'])
def api_action_analyze_video():
    """手动视频分析 — 在后台线程中运行"""
    try:
        body = request.get_json(force=True)
        bvid = (body.get('bvid') or '').strip()
        if not bvid:
            return jsonify(dict(ok=False, message='请输入 BV号')), 400
        import re
        if not re.match(r"^BV[a-zA-Z0-9]{10}$", bvid):
            return jsonify(dict(ok=False, message='请输入合法的 BV 号 (例如: BV1GJ411x7h7)')), 400
        log_line(f"触发手动视频分析: {bvid}")
        # 通过 subprocess 调用 new_agent.py 进行视频分析
        def _run_analysis():
            try:
                import subprocess
                result = subprocess.run(
                    [sys.executable, str(BASE_DIR / "new_agent.py"), "--analyze-once", bvid],
                    cwd=str(BASE_DIR), capture_output=True, text=True, timeout=300
                )
                log_line(f"[分析] {bvid}: {result.stdout[-200:] if result.stdout else result.stderr[-200:]}")
            except Exception as e:
                log_line(f"[分析] 失败: {e}")
        threading.Thread(target=_run_analysis, daemon=True).start()
        return jsonify(dict(ok=True, message=f'已触发视频分析: {bvid}'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/action/send-danmaku', methods=['POST'])
def api_action_send_danmaku():
    """手动发送弹幕 — 桥接到主进程"""
    try:
        body = request.get_json(force=True)
        bvid = (body.get('bvid') or '').strip()
        text = (body.get('text') or '').strip()
        if not bvid or not text:
            return jsonify(dict(ok=False, message='BV号和弹幕内容不能为空')), 400
        if len(text) > 20:
            return jsonify(dict(ok=False, message='弹幕不能超过20字')), 400
        # 写入任务文件让主进程执行
        task_file = DATA_DIR / "web_action_queue.json"
        tasks = read_json(task_file, [])
        tasks.append(dict(type='send_danmaku', bvid=bvid, text=text, time=datetime.now().isoformat()))
        write_json(task_file, tasks)
        log_line(f"弹幕任务已排队: {bvid} -> {text}")
        return jsonify(dict(ok=True, message=f'弹幕"{text}"已加入发送队列'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/action/agent-skill', methods=['POST'])
def api_action_agent_skill():
    """执行 Agent 技能"""
    try:
        body = request.get_json(force=True)
        goal = (body.get('goal') or '').strip()
        if not goal:
            return jsonify(dict(ok=False, message='请输入目标描述')), 400
        task_file = DATA_DIR / "web_action_queue.json"
        tasks = read_json(task_file, [])
        tasks.append(dict(type='agent_skill', goal=goal, time=datetime.now().isoformat()))
        write_json(task_file, tasks)
        log_line(f"Agent技能已排队: {goal}")
        return jsonify(dict(ok=True, message=f'Agent任务已加入队列: {goal}'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/action/kb-organize', methods=['POST'])
def api_action_kb_organize():
    """知识库整理"""
    try:
        task_file = DATA_DIR / "web_action_queue.json"
        tasks = read_json(task_file, [])
        tasks.append(dict(type='kb_organize', time=datetime.now().isoformat()))
        write_json(task_file, tasks)
        log_line("知识库整理任务已排队")
        return jsonify(dict(ok=True, message='知识库整理已加入队列'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/action/kb-revisit', methods=['POST'])
def api_action_kb_revisit():
    """知识库重温"""
    try:
        task_file = DATA_DIR / "web_action_queue.json"
        tasks = read_json(task_file, [])
        tasks.append(dict(type='kb_revisit', time=datetime.now().isoformat()))
        write_json(task_file, tasks)
        log_line("知识库重温任务已排队")
        return jsonify(dict(ok=True, message='知识库重温已加入队列'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

# ── 行为设置 ──
@app.route('/api/behavior/get')
def api_behavior_get():
    config = read_json(CONFIG_FILE, {})
    behavior = config.get('behavior', {})
    energy = config.get('energy', {})
    interaction = config.get('interaction', {})
    return jsonify(dict(
        ai_marker=behavior.get('ai_marker', '（内容由AI生成并由AI回复）'),
        comment_mode=behavior.get('comment_mode', 'real'),
        energy=dict(
            max_energy=interaction.get('max_energy', 100),
            energy_recovery_min=energy.get('energy_recovery_min', 5),
            energy_recovery_max=energy.get('energy_recovery_max', 10),
            rounds_min=energy.get('rounds_min', 3),
            rounds_max=energy.get('rounds_max', 10),
            round_interval_min=energy.get('round_interval_min', 60),
            round_interval_max=energy.get('round_interval_max', 180),
            video_interval_min=energy.get('video_interval_min', 20),
            video_interval_max=energy.get('video_interval_max', 50),
        )
    ))

@app.route('/api/behavior/ai-marker/toggle', methods=['POST'])
def api_behavior_ai_marker_toggle():
    try:
        body = request.get_json(force=True)
        enabled = bool(body.get('enabled', True))
        config = read_json(CONFIG_FILE, {})
        behavior = config.setdefault('behavior', {})
        if enabled:
            behavior['ai_marker'] = body.get('marker') or '（内容由AI生成并由AI回复）'
        else:
            behavior['ai_marker'] = ''
        write_json(CONFIG_FILE, config)
        msg = 'AI免责声明已开启' if enabled else 'AI免责声明已关闭'
        log_line(msg)
        return jsonify(dict(ok=True, message=msg, marker=behavior['ai_marker']))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/behavior/save', methods=['POST'])
def api_behavior_save():
    try:
        body = request.get_json(force=True)
        config = read_json(CONFIG_FILE, {})
        changed = []
        # ai_marker
        if 'ai_marker' in body:
            config.setdefault('behavior', {})['ai_marker'] = str(body['ai_marker'])
            changed.append('AI免责声明')
        # comment_mode
        if 'comment_mode' in body:
            config.setdefault('behavior', {})['comment_mode'] = str(body['comment_mode'])
            changed.append('评论模式')
        # energy settings
        if 'energy' in body:
            eng = body['energy']
            energy = config.setdefault('energy', {})
            interaction = config.setdefault('interaction', {})
            for k in ['energy_recovery_min','energy_recovery_max','rounds_min','rounds_max',
                       'round_interval_min','round_interval_max','video_interval_min','video_interval_max']:
                if k in eng:
                    energy[k] = int(eng[k])
            if 'max_energy' in eng:
                interaction['max_energy'] = int(eng['max_energy'])
            changed.append('精力设置')
        write_json(CONFIG_FILE, config)
        msg = '、'.join(changed) + ' 已保存' if changed else '无变更'
        log_line(msg)
        return jsonify(dict(ok=True, message=msg))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


# ── 登录认证 API（可选，通过 BILI_WEB_PASSWORD 环境变量启用）──
@app.route('/api/login', methods=['POST'])
def api_login():
    body = request.get_json(force=True) if request.is_json else {}
    password = body.get('password', '')
    if not WEB_PASSWORD:
        return jsonify(dict(ok=True, message='未设置密码，无需登录'))
    if password == WEB_PASSWORD:
        session['web_authenticated'] = True
        return jsonify(dict(ok=True, message='登录成功'))
    return jsonify(dict(ok=False, message='密码错误')), 401

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('web_authenticated', None)
    return jsonify(dict(ok=True, message='已退出'))

@app.route('/api/login/status')
def api_login_status():
    return jsonify(dict(
        need_login=bool(WEB_PASSWORD),
        authenticated=bool(session.get('web_authenticated'))
    ))


# ── 免责声明 HTML 页面 ──
def _disclaimer_html():
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>免责声明</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI','Microsoft YaHei',sans-serif;background:#0d1117;color:#c9d1d9;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#161b22;border:2px solid #f85149;border-radius:12px;padding:32px 28px;max-width:520px;width:90%;text-align:center}
.card h2{color:#f85149;font-size:22px;margin-bottom:20px}
.card .lines{background:rgba(248,81,73,.06);border:1px solid rgba(248,81,73,.2);border-radius:8px;padding:16px 20px;margin-bottom:20px;font-size:14px;line-height:1.9;text-align:left}
.card .lines .en{font-size:12px;color:#8b949e;margin-top:6px;display:block}
.inp-row{display:flex;gap:10px}
.inp-row input{flex:1;background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:10px 14px;color:#c9d1d9;font-size:16px;outline:none;transition:border-color .2s}
.inp-row input:focus{border-color:#58a6ff}
.inp-row input.error{border-color:#f85149;animation:shake .4s}
.btn{background:#f85149;color:#fff;border:none;border-radius:8px;padding:10px 24px;font-size:15px;cursor:pointer;transition:opacity .2s}
.btn:hover{opacity:.85}
.btn:disabled{opacity:.4;cursor:not-allowed}
.msg{margin-top:12px;font-size:13px;min-height:20px}
.msg.err{color:#f85149}
.msg.ok{color:#3fb950}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-6px)}75%{transform:translateX(6px)}}
</style>
</head>
<body>
<div class="card">
<h2>⚠ 免责声明 / DISCLAIMER</h2>
<div class="lines">
本项目仅供学习参考，<br>
若因使用本项目产生任何后果，本人一概不负责。
<span class="en">This project is for learning purposes only.<br>Any consequences are solely your own responsibility.</span>
</div>
<div class="inp-row">
<input id="agreeInput" type="text" placeholder="请输入：我同意" autocomplete="off" autofocus>
<button class="btn" id="confirmBtn" onclick="doConfirm()">确认</button>
</div>
<div class="msg" id="msg"></div>
</div>
<script>
var inp=document.getElementById('agreeInput');
var btn=document.getElementById('confirmBtn');
var msg=document.getElementById('msg');
inp.addEventListener('keydown',function(e){if(e.key==='Enter')doConfirm()});
function doConfirm(){
var v=inp.value.trim();
if(!v){msg.textContent='请输入内容';msg.className='msg err';return}
btn.disabled=true;
fetch('/api/disclaimer/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({agree:v})})
.then(function(r){return r.json()})
.then(function(d){
if(d.ok){msg.textContent='✓ 已确认，跳转中...';msg.className='msg ok';setTimeout(function(){location.href='/'},600)}
else{msg.textContent='✗ 请输入"我同意"';msg.className='msg err';btn.disabled=false;inp.classList.add('error');setTimeout(function(){inp.classList.remove('error')},400)}
})
.catch(function(){msg.textContent='请求失败，请重试';msg.className='msg err';btn.disabled=false})
}
</script>
</body>
</html>"""

# ── 免责声明确认页（Web端）──
@app.route('/disclaimer')
def disclaimer_page():
    return _disclaimer_html(), 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/api/disclaimer/confirm', methods=['POST'])
def api_disclaimer_confirm():
    data = request.get_json(force=True) if request.is_json else {}
    if data.get('agree') == '我同意':
        session['disclaimer_agreed'] = True
        return jsonify(dict(ok=True))
    return jsonify(dict(ok=False, message='请手动输入 我同意'))

# ── 免责声明拦截 + 登录拦截（未确认则重定向）──
@app.before_request
def _check_disclaimer():
    # 免责声明白名单
    whitelist_endpoints = ('disclaimer_page', 'api_disclaimer_confirm', 'static',
                           'api_login', 'api_login_status', 'login_page')
    whitelist_paths = ('/api/disclaimer', '/disclaimer', '/api/login', '/login')

    # 登录检查（如果设置了密码）
    if WEB_PASSWORD and not session.get('web_authenticated'):
        if request.endpoint not in whitelist_endpoints and not any(request.path.startswith(p) for p in whitelist_paths):
            return jsonify(dict(ok=False, message='未登录', need_login=True)), 401

    if session.get('disclaimer_agreed'):
        return None
    if request.endpoint in whitelist_endpoints:
        return None
    if any(request.path.startswith(p) for p in whitelist_paths):
        return None
    return redirect('/disclaimer')

# ═══════════════════════════════════════════
#  启动
# ═══════════════════════════════════════════
def main():
    port = int(os.getenv('WEB_PORT', '8080'))
    host = os.getenv('WEB_HOST', '0.0.0.0')
    account_label = f" [账号: {ACCOUNT_NAME}]" if ACCOUNT_NAME != '默认' else ""

    # ── 免责声明确认（从bat启动时BILI_DISCLAIMER_SKIP=1可跳过）──
    if not os.getenv('BILI_DISCLAIMER_SKIP'):
        _disclaimer_confirm_terminal()

    banner = f"""
╔══════════════════════════════════════════════╗
║     B站 AI 管理系统 · Web 控制面板{account_label}        ║
╠══════════════════════════════════════════════╣
║   本地: http://127.0.0.1:{port}              ║
║   局域网: http://0.0.0.0:{port}             ║
║   数据: {DATA_DIR}
╚══════════════════════════════════════════════╝
"""
    print(banner, flush=True)
    print("(Disclaimer) This project is for learning purposes only. Any consequences are solely your own responsibility.", flush=True)
    log_line(f"[Web] Panel started (account: {ACCOUNT_NAME}, port: {port})")
    app.run(host=host, port=port, debug=False, threaded=True)
if __name__ == '__main__':
    main()
