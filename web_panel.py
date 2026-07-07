#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pyright: reportImplicitRelativeImport=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportPrivateLocalImportUsage=false, reportUnusedCallResult=false, reportDeprecated=false, reportMissingTypeStubs=false, reportMissingImports=false, reportAny=false
"""
bilibili_learning_bot · Web 管理面板 
功能：仪表盘 | 机器人启停 | B站扫码登录 | 配置编辑 | 实时日志
     人格管理 | 评论日志 | 用户画像 | 记忆知识库 | 日记进化 | 操作日志
"""
import os, sys, json, time, io, base64, threading, asyncio, subprocess, signal, queue, hashlib, uuid as _uuid_module, collections
from datetime import datetime
from pathlib import Path

# ── 线程安全 JSON 工具 ──
from utils.storage import JsonStore, sanitize_config_for_export, is_safe_path, get_backup_dir

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
APP_VERSION = '3.0.2'  # 与 cli/app.py 横幅一致，避免网页端显示过时占位版本

app = Flask(__name__, static_folder=None)

# ── 🔐 密码哈希（SHA-256 + salt，不引入额外依赖） ──
def _hash_password(password: str) -> str:
    """对密码做 salted hash，格式: $sha256$<salt>$<hash_hex>"""
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000)
    return f'$sha256${salt}${h.hex()}'

def _verify_password(password: str, stored: str) -> bool:
    """验证密码是否匹配存储的哈希"""
    if not stored or not stored.startswith('$sha256$'):
        # 兼容旧版明文密码：直接比较（已废弃，建议重新设置密码以启用加密存储）
        import warnings
        warnings.warn("检测到旧版明文密码存储，建议进入 Web 面板重新设置密码以启用安全哈希", DeprecationWarning)
        return password == stored
    _, _, salt, hash_hex = stored.split('$', 3)
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000)
    return h.hex() == hash_hex

# ── 🔑 Session 密钥持久化（避免重启后所有用户被踢出） ──
SECRET_KEY_FILE = DATA_DIR / ".web_secret_key"
if SECRET_KEY_FILE.exists():
    app.secret_key = SECRET_KEY_FILE.read_text().strip()
else:
    app.secret_key = os.urandom(24).hex()
    SECRET_KEY_FILE.write_text(app.secret_key)

DATA_DIR.mkdir(parents=True, exist_ok=True)

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

# ── 文件工具（线程安全）──
def read_json(path: Path, default=None):
    """线程安全读取 JSON（通过 JsonStore）。"""
    return JsonStore(path).read(default if default is not None else {})

def write_json(path: Path, data):
    """线程安全写入 JSON（原子写临时文件再 rename）。"""
    return JsonStore(path).write(data)

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
    except OSError as e:
        log_line(f"⚠ 读取子进程输出异常: {e}")
    finally:
        try: pipe.close()
        except OSError as e:
            log_line(f"⚠ 关闭管道异常: {e}")

def start_bot_process(mode=None):
    global bot_process, bot_running, bot_start_time
    if bot_running:
        return False, "机器人已在运行"

    agent_path = BASE_DIR / "main.py"
    if not agent_path.exists():
        return False, f"找不到 {agent_path}"

    log_line("🚀 正在启动机器人进程...")
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        # 设置环境变量跳过子进程的免责声明交互
        env["BILI_DISCLAIMER_SKIP"] = "1"
        # 关键：自动启动模式——子进程直接以已配置模式运行机器人，
        # 不再走交互菜单（此前只喂 "1\n" 会卡在二级"选择启动模式"子菜单，机器人永不真正运行）
        env["BILI_AUTO_START"] = "1"
        # 由网页端下拉选择启动模式（smart=智能省token / current=当前模式）
        if mode == "smart":
            env["BILI_AUTO_START_MODE"] = "smart"
        elif mode == "current":
            env["BILI_AUTO_START_MODE"] = "current"

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
                if bot_process.stdin and not bot_process.stdin.closed:
                    bot_process.stdin.write("0\n")
                    bot_process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as e:
                log_line(f"⚠ 发送退出命令失败 (管道断开): {e}")
            time.sleep(0.5)
            bot_process.terminate()
            try: bot_process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                log_line("⚠ 进程未响应 terminate，尝试 kill...")
                try: bot_process.kill()
                except Exception as e: log_line(f"⚠ kill 失败: {e}")
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
<script>if(typeof Chart==='undefined'){document.write('<script src="https://cdn.bootcdn.net/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"><\/script>')}</script>
<script>if(typeof Chart==='undefined'){document.write('<script src="https://unpkg.com/chart.js@4.4.0/dist/chart.umd.min.js"><\/script>')}</script>
<style>
/* ===== 多主题系统 (inspired by xiongdaa-card) ===== */
:root,[data-theme="aurora"]{
--bg:#0b0f19;--bg2:rgba(17,24,39,.55);--bg3:rgba(30,41,59,.5);--bg4:rgba(40,53,72,.5);
--border:rgba(42,58,80,.5);--border2:rgba(55,72,96,.6);
--text:#e8f0ff;--text2:rgba(200,215,240,.75);--text3:rgba(100,120,150,.7);
--accent:#6ee7b7;--accent2:#60a5fa;
--accent-g:linear-gradient(135deg,#6ee7b7 0%,#60a5fa 100%);
--green:#34d399;--green-g:linear-gradient(135deg,#34d399 0%,#06b6d4 100%);
--orange:#fbbf24;--red:#f87171;--pink:#f472b6;--purple:#a78bfa;
--glow:rgba(110,231,183,.25);--glow2:rgba(96,165,250,.2);
--r:16px;--rs:10px;--rs2:14px;
--shadow:0 4px 24px rgba(0,0,0,.35);--shadow-lg:0 12px 48px rgba(0,0,0,.5);
--glass:rgba(15,20,40,.45);--glass-border:rgba(110,200,255,.12);
--glass-blur:blur(24px) saturate(160%);
--sidebar-bg:rgba(12,16,30,.65);--overlay:radial-gradient(ellipse at 30% 20%,rgba(110,231,183,.06) 0%,transparent 50%),radial-gradient(ellipse at 70% 80%,rgba(96,165,250,.05) 0%,transparent 50%);
}
[data-theme="cyberpunk"]{
--bg:#0a0014;--bg2:rgba(20,0,40,.55);--bg3:rgba(40,10,60,.5);--bg4:rgba(60,20,80,.5);
--border:rgba(255,0,128,.15);--border2:rgba(255,0,128,.25);
--text:#fff0f5;--text2:rgba(255,200,220,.65);--text3:rgba(180,100,130,.6);
--accent:#ff2d7b;--accent2:#00f0ff;
--accent-g:linear-gradient(135deg,#ff2d7b 0%,#00f0ff 100%);
--green:#00f0ff;--green-g:linear-gradient(135deg,#00f0ff 0%,#ff2d7b 100%);
--glow:rgba(255,45,123,.3);--glow2:rgba(0,240,255,.2);
--r:8px;--rs:6px;--rs2:10px;
--shadow:0 4px 24px rgba(255,0,128,.15);--shadow-lg:0 12px 48px rgba(0,0,0,.5);
--glass:rgba(10,0,25,.55);--glass-border:rgba(255,0,128,.2);
--glass-blur:blur(20px) saturate(200%);
--sidebar-bg:rgba(10,0,20,.7);--overlay:radial-gradient(ellipse at 50% 0%,rgba(255,0,128,.08) 0%,transparent 60%);
}
[data-theme="sakura"]{
--bg:#1a0a10;--bg2:rgba(40,15,25,.55);--bg3:rgba(60,25,40,.5);--bg4:rgba(80,35,55,.5);
--border:rgba(255,182,193,.18);--border2:rgba(255,182,193,.28);
--text:#fff0f3;--text2:rgba(255,200,210,.7);--text3:rgba(200,120,140,.6);
--accent:#ff9eb5;--accent2:#ffd1dc;
--accent-g:linear-gradient(135deg,#ff9eb5 0%,#ffd1dc 100%);
--green:#ffd1dc;--green-g:linear-gradient(135deg,#ffd1dc 0%,#ff9eb5 100%);
--glow:rgba(255,158,181,.25);--glow2:rgba(255,209,220,.2);
--r:20px;--rs:12px;--rs2:16px;
--shadow:0 4px 24px rgba(200,100,130,.15);--shadow-lg:0 12px 48px rgba(0,0,0,.4);
--glass:rgba(30,10,20,.5);--glass-border:rgba(255,182,193,.2);
--glass-blur:blur(22px) saturate(140%);
--sidebar-bg:rgba(25,8,15,.7);--overlay:radial-gradient(ellipse at 40% 30%,rgba(255,158,181,.06) 0%,transparent 50%);
}
[data-theme="galaxy"]{
--bg:#050010;--bg2:rgba(15,5,40,.55);--bg3:rgba(25,15,60,.5);--bg4:rgba(40,25,80,.5);
--border:rgba(147,130,255,.15);--border2:rgba(147,130,255,.25);
--text:#e8e0ff;--text2:rgba(180,170,220,.7);--text3:rgba(130,120,180,.6);
--accent:#b388ff;--accent2:#ff80ab;
--accent-g:linear-gradient(135deg,#b388ff 0%,#ff80ab 100%);
--green:#b388ff;--green-g:linear-gradient(135deg,#b388ff 0%,#ff80ab 100%);
--glow:rgba(179,136,255,.25);--glow2:rgba(255,128,171,.2);
--r:18px;--rs:10px;--rs2:14px;
--shadow:0 4px 24px rgba(100,50,200,.15);--shadow-lg:0 12px 48px rgba(0,0,0,.5);
--glass:rgba(10,5,30,.5);--glass-border:rgba(147,130,255,.15);
--glass-blur:blur(28px) saturate(140%);
--sidebar-bg:rgba(8,3,25,.7);--overlay:radial-gradient(ellipse at 60% 20%,rgba(179,136,255,.06) 0%,transparent 50%);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:'Noto Sans SC',system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);display:flex;min-height:100vh;line-height:1.5;-webkit-font-smoothing:antialiased;transition:background .6s cubic-bezier(.4,0,.2,1)}

/* ── BACKGROUND LAYERS ── */
.bg-layer{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}
.bg-layer img,.bg-layer video{width:100%;height:100%;object-fit:cover;opacity:.35;transition:opacity .8s}
.bg-layer .bg-default{width:100%;height:100%;background:linear-gradient(135deg,#0a0e1a 0%,#0d1b2a 40%,#1b2838 100%);transition:opacity .6s}
.overlay{position:fixed;inset:0;z-index:1;pointer-events:none;background:var(--overlay);transition:background .6s}
#ambientCanvas{position:fixed;inset:0;z-index:2;pointer-events:none;opacity:.4}
a{color:var(--accent);text-decoration:none;transition:color .2s}
a:hover{color:var(--purple)}

/* SCROLLBAR */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:var(--border2)}

/* ── SIDEBAR ── */
.sidebar{width:240px;min-width:240px;background:var(--sidebar-bg);backdrop-filter:var(--glass-blur);-webkit-backdrop-filter:var(--glass-blur);border-right:1px solid var(--glass-border);display:flex;flex-direction:column;position:fixed;top:0;left:0;bottom:0;z-index:100;transition:transform .3s cubic-bezier(.4,0,.2,1)}
.sidebar.hide{transform:translateX(-100%)}
.sb-hd{padding:20px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px}
.sb-av{width:40px;height:40px;border-radius:12px;background:var(--accent-g);display:flex;align-items:center;justify-content:center;font-size:20px;box-shadow:0 4px 15px rgba(108,159,255,.3)}
.sb-tt{font-size:15px;font-weight:700;line-height:1.2;background:var(--accent-g);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sb-sub{font-size:10px;color:var(--text3);margin-top:2px}
.sb-nav{flex:1;overflow-y:auto;padding:10px 8px}
.ns{font-size:9px;color:var(--text3);text-transform:uppercase;letter-spacing:1.5px;padding:16px 12px 6px;font-weight:600}
.ni{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:var(--rs);cursor:pointer;color:var(--text2);font-size:13px;border:none;background:none;width:100%;transition:all .2s;position:relative;font-weight:500}
.ni:hover{background:var(--bg3);color:var(--text);transform:translateX(3px)}
.ni.ac{background:linear-gradient(135deg,rgba(108,159,255,.15),rgba(167,139,250,.1));color:var(--accent);font-weight:600;box-shadow:inset 3px 0 0 var(--accent)}
.ni .ic{font-size:17px;width:24px;text-align:center;flex-shrink:0}
.ni .bd{margin-left:auto;background:var(--red);color:#fff;font-size:9px;padding:2px 7px;border-radius:10px;font-weight:700;display:none;animation:badgePop .3s}
.sb-ft{padding:12px;border-top:1px solid var(--border);font-size:10px;color:var(--text3);text-align:center;line-height:1.5}
@keyframes badgePop{0%{transform:scale(0)}50%{transform:scale(1.2)}100%{transform:scale(1)}}

/* ── MAIN ── */
.main{margin-left:240px;flex:1;padding:28px 32px;max-width:calc(100vw - 240px);min-width:0;position:relative;z-index:10;animation:fadeIn .3s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.page{display:none}
.page.on{display:block}
.ph{margin-bottom:24px}
.ph h1{font-size:24px;font-weight:800;letter-spacing:-.3px}
.ph p{color:var(--text2);font-size:12px;margin-top:4px}

/* ── STAT CARDS ── */
.sr{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px;margin-bottom:24px}
.sc{background:var(--glass);backdrop-filter:var(--glass-blur);-webkit-backdrop-filter:var(--glass-blur);border:1px solid var(--glass-border);border-radius:var(--r);padding:18px;display:flex;align-items:center;gap:14px;transition:all .3s cubic-bezier(.4,0,.2,1);cursor:default;position:relative;overflow:hidden}
.sc:hover{transform:translateY(-2px);box-shadow:var(--shadow-lg);border-color:var(--border2)}
.si{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;transition:transform .2s}
.sc:hover .si{transform:scale(1.1)}
.si.bl{background:linear-gradient(135deg,rgba(108,159,255,.2),rgba(108,159,255,.05));color:var(--accent)}
.si.gn{background:linear-gradient(135deg,rgba(52,211,153,.2),rgba(52,211,153,.05));color:var(--green)}
.si.or{background:linear-gradient(135deg,rgba(251,191,36,.2),rgba(251,191,36,.05));color:var(--orange)}
.si.pk{background:linear-gradient(135deg,rgba(244,114,182,.2),rgba(244,114,182,.05));color:var(--pink)}
.si.rd{background:linear-gradient(135deg,rgba(248,113,113,.2),rgba(248,113,113,.05));color:var(--red)}
.si.pp{background:linear-gradient(135deg,rgba(167,139,250,.2),rgba(167,139,250,.05));color:var(--purple)}
.sv{font-size:22px;font-weight:800;letter-spacing:-.5px;line-height:1}
.sl{font-size:11px;color:var(--text3);margin-top:2px;font-weight:500}

/* ── PANEL CARDS ── */
.pc{background:var(--glass);backdrop-filter:var(--glass-blur);-webkit-backdrop-filter:var(--glass-blur);border:1px solid var(--glass-border);border-radius:var(--r);padding:20px;margin-bottom:16px;transition:all .3s cubic-bezier(.4,0,.2,1);position:relative;overflow:hidden}
.pc:hover{border-color:var(--border2)}
.pc h3{font-size:14px;margin-bottom:14px;display:flex;align-items:center;gap:8px;font-weight:700}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;transition:background .3s}
.dot.on{background:var(--green);box-shadow:0 0 8px rgba(52,211,153,.5)}
.dot.off{background:var(--text3)}

/* ── TABLE ── */
.tb{width:100%;border-collapse:collapse;font-size:12px}
.tb th{text-align:left;padding:10px 12px;color:var(--text3);font-weight:700;font-size:10px;text-transform:uppercase;letter-spacing:.8px;border-bottom:2px solid var(--border);background:rgba(30,41,59,.5)}
.tb td{padding:10px 12px;border-bottom:1px solid rgba(42,58,80,.3);max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;transition:background .15s}
.tb tr:hover td{background:rgba(108,159,255,.05)}
.tb .mono{font-family:"SF Mono","Fira Code","JetBrains Mono",monospace;font-size:11px;color:var(--text2)}

/* ── BUTTONS ── */
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:var(--rs);font-size:12px;font-weight:600;cursor:pointer;border:none;transition:all .2s cubic-bezier(.4,0,.2,1);white-space:nowrap;position:relative;overflow:hidden}
.btn::after{content:'';position:absolute;inset:0;background:rgba(255,255,255,0);transition:background .2s}
.btn:hover::after{background:rgba(255,255,255,.1)}
.btn:active{transform:scale(.97)}
.btn-pr{background:var(--accent-g);color:#fff;box-shadow:0 2px 10px rgba(108,159,255,.3)}
.btn-pr:hover{box-shadow:0 4px 20px rgba(108,159,255,.4);transform:translateY(-1px)}
.btn-suc{background:var(--green-g);color:#fff;box-shadow:0 2px 10px rgba(52,211,153,.3)}
.btn-suc:hover{box-shadow:0 4px 20px rgba(52,211,153,.4);transform:translateY(-1px)}
.btn-dan{background:linear-gradient(135deg,#f87171,#e05560);color:#fff;box-shadow:0 2px 10px rgba(248,113,113,.3)}
.btn-dan:hover{box-shadow:0 4px 20px rgba(248,113,113,.4);transform:translateY(-1px)}
.btn-out{background:transparent;border:1px solid var(--border);color:var(--text2)}
.btn-out:hover{border-color:var(--accent);color:var(--accent);background:rgba(108,159,255,.05)}
.btn-sm{padding:5px 12px;font-size:11px;border-radius:6px}
.btn-lg{padding:11px 24px;font-size:14px;border-radius:var(--rs2)}
.btn-grp{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none!important;box-shadow:none!important}
.mode-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:6px 0 2px}
.mode-row label{font-size:13px;font-weight:700;color:var(--text2)}
.sel{background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;cursor:pointer;outline:none}
.sel:focus{border-color:var(--accent)}
.mode-hint{font-size:11px;color:var(--text3)}

/* ── FORMS ── */
.fg{margin-bottom:14px}
.fg label{display:block;font-size:11px;font-weight:700;color:var(--text3);margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px}
.fg input,.fg textarea,.fg select{width:100%;padding:9px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);color:var(--text);font-size:13px;font-family:inherit;outline:none;transition:all .2s}
.fg input:focus,.fg textarea:focus,.fg select:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(108,159,255,.15);background:var(--bg4)}
.fg input:hover,.fg textarea:hover,.fg select:hover{border-color:var(--border2)}
.fg textarea{resize:vertical;min-height:80px;font-family:"SF Mono","Fira Code","JetBrains Mono",monospace;font-size:12px;line-height:1.5}
.fg select{cursor:pointer;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238899b0' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center}
.fr{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:600px){.fr{grid-template-columns:1fr}}

/* ── TOGGLE SWITCH ── */
.toggle-sw{display:flex;align-items:center;gap:10px;cursor:pointer;user-select:none}
.toggle-sw input{display:none}
.toggle-track{width:40px;height:22px;background:var(--bg4);border-radius:11px;position:relative;transition:all .25s cubic-bezier(.4,0,.2,1);border:1px solid var(--border);flex-shrink:0}
.toggle-track::after{content:'';position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:var(--text3);transition:all .25s cubic-bezier(.68,-.55,.265,1.55);box-shadow:0 1px 3px rgba(0,0,0,.3)}
.toggle-sw input:checked+.toggle-track{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;box-shadow:0 0 16px rgba(108,159,255,.35)}
.toggle-sw input:checked+.toggle-track::after{left:20px;background:#fff;transform:scale(1.1)}
.toggle-sw .toggle-label{font-size:13px;color:var(--text2);font-weight:500}

/* ── TAGS ── */
.tg{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;letter-spacing:.3px}
.tg-suc{background:rgba(52,211,153,.12);color:var(--green)}
.tg-war{background:rgba(251,191,36,.12);color:var(--orange)}
.tg-dan{background:rgba(248,113,113,.12);color:var(--red)}
.tg-inf{background:rgba(108,159,255,.12);color:var(--accent)}

/* ── LOG VIEWER ── */
.log-box{background:#060a12;border:1px solid var(--border);border-radius:var(--rs);padding:14px;max-height:360px;overflow-y:auto;font-family:"SF Mono","Fira Code","JetBrains Mono",monospace;font-size:11px;line-height:1.6;white-space:pre-wrap;word-break:break-all;color:#8fa8c8}
.log-box::-webkit-scrollbar-thumb{background:#1a2535}

/* ── JSON EDITOR ── */
.je{width:100%;min-height:400px;background:#060a12;border:1px solid var(--border);border-radius:var(--rs);color:var(--green);font-family:"SF Mono","Fira Code","JetBrains Mono",monospace;font-size:12px;padding:14px;resize:vertical;outline:none;line-height:1.6;transition:border-color .2s}
.je:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(108,159,255,.1)}

/* ── CONFIG QUICK EDIT ── */
.fs{border:1px solid var(--border);border-radius:var(--rs);padding:16px;margin-bottom:14px}
.fs legend{font-size:14px;font-weight:700;padding:0 8px;color:var(--accent)}

/* ── QR ── */
.qr-wrap{text-align:center;padding:24px}
.qr-wrap img{max-width:220px;border-radius:12px;border:4px solid #fff;box-shadow:var(--shadow-lg)}
.qr-wrap .qr-status{margin-top:12px;font-size:14px;font-weight:700}

/* ── TOAST ── */
.toast{position:fixed;top:20px;right:20px;z-index:9999;padding:12px 20px;border-radius:var(--rs2);font-size:13px;font-weight:600;opacity:0;transform:translateY(-16px) scale(.95);transition:all .3s cubic-bezier(.4,0,.2,1);pointer-events:none;max-width:320px;box-shadow:var(--shadow-lg);backdrop-filter:blur(12px)}
.toast.show{opacity:1;transform:translateY(0) scale(1)}
.toast.ok{background:rgba(52,211,153,.9);color:#fff}
.toast.err{background:rgba(248,113,113,.9);color:#fff}
.toast.inf{background:rgba(108,159,255,.9);color:#fff}

/* ── EMPTY STATE ── */
.emp{text-align:center;padding:40px 20px;color:var(--text3)}
.emp .ic{font-size:40px;margin-bottom:10px;display:block}
.emp p{font-size:13px}

/* ── MOBILE ── */
.mob-toggle{display:none;position:fixed;top:12px;left:12px;z-index:200;background:var(--glass);backdrop-filter:blur(12px);border:1px solid var(--glass-border);color:var(--text);width:40px;height:40px;border-radius:var(--rs);align-items:center;justify-content:center;cursor:pointer;font-size:18px;transition:all .2s}
.mob-toggle:hover{background:var(--bg3)}
.mob-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(4px);z-index:99}
@media(max-width:768px){
.sidebar{transform:translateX(-100%)}
.sidebar.show{transform:translateX(0)}
.main{margin-left:0;max-width:100%;padding:16px 14px;padding-top:56px;padding-bottom:max(16px,env(safe-area-inset-bottom));position:relative;z-index:10}
.sr{grid-template-columns:repeat(2,1fr);gap:10px}
.sc{padding:14px;gap:10px;min-height:50px}
.si{width:36px;height:36px;font-size:17px}
.sv{font-size:17px}
.mob-toggle{display:flex}
.mob-overlay.show{display:block}
.ph h1{font-size:20px}
.tb{font-size:11px}
.tb td{max-width:120px;padding:7px 8px}
.pc{padding:14px}
.btn{padding:9px 18px;font-size:13px}
.btn-sm{padding:6px 12px}
.fg input,.fg textarea,.fg select{padding:10px 12px;font-size:13px}
.ni{padding:12px 14px;font-size:14px}
.log-box{max-height:220px;font-size:10px}
.je{min-height:260px}
.toast{left:14px;right:14px;max-width:none;top:auto;bottom:16px;transform:translateY(16px) scale(.95)}
.toast.show{transform:translateY(0) scale(1)}
}
@media(max-width:400px){
.sr{grid-template-columns:1fr}
.sc{padding:12px}
.main{padding:12px 10px;padding-top:56px;position:relative;z-index:10}
.ph h1{font-size:18px}
}

/* ── ANIMATIONS ── */
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.pulse{animation:pulse 1.5s ease-in-out infinite}
@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}

/* ── MONITOR GRID ── */
.mon-grid{display:grid;grid-template-columns:320px 1fr;gap:20px;align-items:start}
@media(max-width:768px){.mon-grid{grid-template-columns:1fr}}

/* ── TOGGLE SWITCH ── */
.toggle-sw{display:inline-flex;align-items:center;cursor:pointer;user-select:none;gap:6px}
.toggle-sw input{display:none}
.toggle-track{position:relative;width:40px;height:22px;border-radius:11px;background:var(--bg3);border:1px solid var(--glass-border);transition:all .3s ease;flex-shrink:0}
.toggle-track::after{content:'';position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:var(--text3);transition:all .3s cubic-bezier(.68,-.55,.265,1.55)}
.toggle-sw input:checked+.toggle-track{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;box-shadow:0 0 12px rgba(91,141,239,.4)}
.toggle-sw input:checked+.toggle-track::after{left:20px;background:#fff;transform:scale(1.1)}

/* ── PAGE ANIMATIONS ── */
@keyframes slideUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}

/* ── SCROLLBAR ── */
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--glass-border);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:var(--text3)}
.log-box::-webkit-scrollbar{width:4px}
.log-box::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* ── SELECTION ── */
::selection{background:rgba(91,141,239,.3);color:#fff}

/* ── EXTRA REFINEMENTS ── */
.ph h1{color:var(--accent)}
.sc{transition:all .25s ease}
.sc:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.3)}
.pc{transition:border-color .3s ease,box-shadow .3s ease}
.pc:hover{border-color:rgba(91,141,239,.2)}
.log-box{background:rgba(6,10,16,.8);backdrop-filter:blur(4px)}

/* ── CHART GRID ── */
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}
.chart-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:18px;transition:all .2s;overflow:hidden;position:relative}
.chart-card:hover{border-color:var(--accent);box-shadow:0 0 20px rgba(91,141,239,.08)}
.chart-card h4{font-size:13px;margin:0 0 12px;color:var(--text);font-weight:500}
.chart-card canvas{max-height:220px;width:100%!important;height:200px!important}
@media(max-width:768px){.chart-grid{grid-template-columns:1fr;gap:12px}}
@media(max-width:400px){.chart-card{padding:12px}.chart-card canvas{max-height:180px;height:160px!important}}
</style>
</head>
<body>
<div class="bg-layer" id="bgLayer"><div class="bg-default"></div></div>
<div class="overlay" id="overlay"></div>
<canvas id="ambientCanvas"></canvas>

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
<button class="ni" data-pg="monitor" onclick="nav('monitor',this)"><span class="ic">📡</span>实时监听<span class="bd" id="monitorBadge">●</span></button>
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
<button class="ni" data-pg="tutor" onclick="nav('tutor',this)"><span class="ic">🎓</span>知识辅导</button>
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
<div class="chart-grid">
<div class="chart-card"><h4>📈 评论活跃度趋势</h4><canvas id="chartComments"></canvas></div>
<div class="chart-card"><h4>💡 心情/精力指数</h4><canvas id="chartMood"></canvas></div>
<div class="chart-card"><h4>📅 每日操作统计</h4><canvas id="chartActions"></canvas></div>
<div class="chart-card"><h4>🔍 视频处理速率</h4><canvas id="chartVideos"></canvas></div>
</div>
<div class="pc"><h3><span class="dot" id="botDot"></span>系统详情</h3><div id="botDetail"></div></div>
<div class="pc"><h3>📁 数据文件状态</h3><div id="fileGrid" class="file-grid"></div></div>
<div class="disclaimer">⚠ 免责声明：本项目仅供学习参考，若因使用本项目产生的任何后果，本人一律概不负责。</div>
</div>

<!-- MONITOR -->
<div class="page" id="pg-monitor">
<div class="ph"><h1>📡 实时监听</h1><p>不刷视频 · 专盯私信+评论 · 实时AI回复</p></div>

<!-- 状态卡片 -->
<div class="sr" id="monitorStats"></div>

<!-- 控制栏 -->
<div class="pc" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
<div style="display:flex;align-items:center;gap:12px">
<div id="monitorStatus"></div>
<div id="monitorUptime" class="msg-inline"></div>
</div>
<div class="btn-grp" style="margin:0">
<button class="btn btn-suc btn-lg" id="btnMonitorStart" onclick="startMonitor()">▶ 启动监听</button>
<button class="btn btn-dan btn-lg" id="btnMonitorStop" style="display:none" onclick="stopMonitor()">⏹ 停止</button>
<button class="btn btn-out" onclick="refreshMonitor()">🔄 刷新</button>
</div>
</div>

<!-- 配置 + 日志 双栏 -->
<div class="mon-grid">
<!-- 左：配置 -->
<div>
<div class="pc">
<h3>⚙️ 监听配置</h3>
<div class="fg"><label>评论检查间隔 (秒)</label><input id="monCmtInterval" type="number" min="30" value="120"></div>
<div class="fg"><label>私信检查间隔 (秒)</label><input id="monMsgInterval" type="number" min="10" value="60"></div>
<div class="fg"><label>每次最大回复数</label><input id="monMaxReplies" type="number" min="1" max="20" value="5"></div>
<div class="fg"><label>自动回复</label>
<select id="monAutoReply"><option value="true">✅ 开启 — AI拟好直接发送</option><option value="false">📝 关闭 — 仅拟回复不发送</option></select>
</div>
<div style="display:flex;align-items:center;gap:10px;margin-top:14px">
<button class="btn btn-pr" onclick="saveMonitorConfig()">💾 保存配置</button>
<span id="monCfgMsg" class="msg-inline"></span>
</div>
</div>
<div class="pc">
<h3>💡 说明</h3>
<p class="form-hint" style="line-height:1.7">
独立于视频刷取的监听模式。<br>
启动后只盯私信和评论，有新消息立刻AI回复。<br>
不会刷视频、不消耗精力。<br>
<span style="color:var(--orange)">⚠ 与机器人主进程互斥，不能同时运行。</span>
</p>
</div>
</div>
<!-- 右：日志 -->
<div class="pc" style="min-height:420px;display:flex;flex-direction:column">
<h3 style="display:flex;align-items:center;justify-content:space-between">
<span>📡 实时日志</span>
<span id="monitorLogCount" class="msg-inline" style="font-weight:400"></span>
</h3>
<div class="log-box" id="monitorLog" style="flex:1;min-height:340px">等待启动...</div>
</div>
</div>
</div>

<!-- CONTROL -->
<div class="page" id="pg-ctrl">
<div class="ph"><h1>🎮 机器人控制</h1><p>启动/停止/重启</p></div>
<div class="pc">
<h3>🤖 运行状态</h3><div id="ctrlStatus" style="margin-bottom:12px"></div>
<div class="mode-row">
  <label for="botMode">启动模式：</label>
  <select id="botMode" class="sel">
    <option value="current">🎯 当前模式（完整功能，默认）</option>
    <option value="smart">💡 智能省token（长时挂机/省钱）</option>
  </select>
  <span class="mode-hint">按已保存的配置运行</span>
</div>
<div class="btn-grp">
<button class="btn btn-suc btn-lg" id="btnStart" onclick="startBot()">▶ 启动机器人</button>
<button class="btn btn-dan btn-lg" id="btnStop" style="display:none" onclick="stopBot()">⏹ 停止</button>
<button class="btn btn-out" onclick="restartBot()">🔄 重启</button>
<button class="btn btn-out" onclick="clearLog()">🗑 清空日志</button>
</div>
</div>
<div class="pc"><h3>📡 实时输出</h3><div class="log-box" id="botLog">等待输出...</div></div>
<div class="disclaimer">⚠ 免责声明：本项目仅供学习参考，若因使用本项目产生的任何后果，本人一律概不负责。</div>
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
<!-- 可视化快捷配置 -->
<div class="pc" id="confQuickBox">
<h3>📋 快捷配置 <span style="font-size:11px;font-weight:400;color:var(--text2);margin-left:10px">
<button class="btn btn-sm btn-out" onclick="toggleConfMode()" style="font-size:10px;padding:2px 8px">📝 切换到 JSON 编辑器</button>
</span></h3>
<div id="confQuickContent"></div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveConfQuick()">💾 保存快捷配置</button><span id="confQuickMsg" class="msg-inline"></span></div>
</div>
<!-- 原始 JSON 编辑器（默认隐藏） -->
<div class="pc" id="confJsonBox" style="display:none">
<h3>📄 原始 JSON <span style="font-size:11px;font-weight:400;color:var(--text2);margin-left:10px">
<button class="btn btn-sm btn-out" onclick="toggleConfMode()" style="font-size:10px;padding:2px 8px">🔙 切换到快捷配置</button>
</span></h3>
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
<p class="form-hint">所有评论/私信回复末尾会追加免责声明标签。关闭后不再添加，但建议保持开启以遵守平台规定。</p>
<div class="fr" style="align-items:center;margin-bottom:8px">
<label class="toggle-sw"><input type="checkbox" id="aiMarkerOn" onchange="toggleAiMarker()"><span class="toggle-track"></span><span style="margin-left:10px;font-size:13px">启用免责声明</span></label>
</div>
<div class="fg"><label>免责声明文字</label><input id="aiMarkerText" placeholder="（内容由AI生成并由AI回复）" maxlength="50" style="max-width:300px"></div>
<div class="btn-grp"><button class="btn btn-pr" id="btnSaveMarker" onclick="saveAiMarker()">💾 保存</button><span id="aiMarkerMsg" class="msg-inline"></span></div>
</div>
<div class="pc"><h3>⚡ 精力设置</h3>
<p class="form-hint">控制AI机器人精力恢复速度和行为间隔。</p>
<div class="energy-grid">
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
<div class="btn-grp"><button class="btn btn-pr" onclick="saveEnergy()">💾 保存精力设置</button><span id="engMsg" class="msg-inline"></span></div>
</div>
<div class="pc"><h3>💬 评论模式</h3>
<div class="radio-group">
<label><input type="radio" name="cmtMode" value="real" onchange="saveCommentMode()"> 真实模式 (发送到B站)</label>
<label><input type="radio" name="cmtMode" value="simulate" onchange="saveCommentMode()"> 模拟模式 (仅记录日志)</label>
</div>
<span id="cmtModeMsg" class="msg-inline"></span>
</div>

	<div class="pc"><h3>🛡️ 关键词安全校验</h3>
	<p class="form-hint">开启后AI会过滤涉及敏感关键词的评论和回复。关闭后不再进行关键词检查（风险自负）。</p>
	<div class="fr" style="align-items:center;margin-bottom:10px">
	<label class="toggle-sw"><input type="checkbox" id="safetyEnabled" onchange="toggleSafety()"><span class="toggle-track"></span><span style="margin-left:10px;font-size:13px">启用关键词校验</span></label>
	</div>
	<div id="safetyKwSection" style="display:none">
	<p class="form-hint" style="margin-bottom:6px">当前屏蔽关键词（一行一个）：</p>
	<textarea id="safetyKeywords" class="kw-textarea"></textarea>
	<div class="btn-grp" style="margin-top:8px">
	<button class="btn btn-pr" onclick="saveSafetyKeywords()">💾 保存关键词</button>
	<button class="btn btn-out btn-sm" onclick="addSafetyKeyword()">+ 添加关键词</button>
	</div>
	<div class="fg" style="margin-top:8px"><label>快速添加关键词</label>
	<div style="display:flex;gap:6px"><input id="newSafetyKw" placeholder="输入新关键词" style="flex:1"><button class="btn btn-out btn-sm" onclick="addSafetyKeyword()">添加</button></div>
	</div>
	<span id="safetyMsg" class="msg-inline"></span>
	</div>
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

<div class="pc"><h3>🎙️ ASR 语音识别设置</h3>
<p class="form-hint">语音识别引擎配置（FunASR / Whisper）。</p>
<div class="fr">
<div class="fg"><label>启用ASR</label><select id="asrEnabled"><option value="1">开启</option><option value="0">关闭</option></select></div>
<div class="fg"><label>识别引擎</label><select id="asrBackend"><option value="funasr">FunASR（推荐）</option><option value="whisper">Whisper</option></select></div>
<div class="fg"><label>语言</label><input id="asrLang" placeholder="zh" style="max-width:80px"></div>
<div class="fg"><label>说话人分离</label><select id="asrSep"><option value="1">开启</option><option value="0">关闭</option></select></div>
</div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveAsr()">💾 保存ASR设置</button><span id="asrMsg" class="msg-inline"></span></div>
</div>
<div class="pc"><h3>⭐ Highlights 归档设置</h3>
<p class="form-hint">高分视频自动备份到 highlights/ 目录。</p>
<div class="fr">
<div class="fg"><label>启用归档</label><select id="dryEnabled"><option value="1">开启</option><option value="0">关闭</option></select></div>
<div class="fg"><label>最低评分门槛</label><input id="dryMinScore" type="number" min="5" max="10" step="0.5" value="8.0" style="max-width:100px"></div>
<div class="fg"><label>归档文件夹名</label><input id="dryFolder" placeholder="highlights" style="max-width:200px"></div>
</div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveDry()">💾 保存归档设置</button><span id="dryMsg" class="msg-inline"></span></div>
</div>
</div>

<!-- TUTOR (v2.0.3) -->
<div class="page" id="pg-tutor">
<div class="ph"><h1>🎓 知识辅导</h1><p>选择知识文件 → AI讲解/问答/二次创作/生成HTML</p></div>

<div class="pc"><h3>📂 选择知识文件</h3>
<div style="display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap">
<select id="tutorFileSelect" multiple size="8" class="tutor-select">
</select>
<div style="display:flex;flex-direction:column;gap:5px">
<button class="btn btn-pr btn-sm" onclick="tutorLoadFile()">📖 加载选中</button>
<button class="btn btn-out btn-sm" onclick="tutorSelectAll()">☑ 全选</button>
<button class="btn btn-out btn-sm" onclick="tutorSelectNone()">☐ 取消</button>
<button class="btn btn-out btn-sm" onclick="rf_tutor()" style="margin-top:4px">🔄 刷新</button>
</div>
</div>
<div id="tutorFileInfo" style="margin-top:8px;font-size:11px;color:var(--text2)"></div>
<div class="btn-grp" id="tutorFileActions" style="margin-top:6px;display:none">
<button class="btn btn-pr btn-sm" onclick="tutorLoadFile()">📖 加载选中</button>
<button class="btn btn-out btn-sm" onclick="tutorSelectAll()">☑ 全选</button>
</div>
</div>

<div class="pc" id="tutorContentBox" style="display:none">
<h3>📄 文件内容预览 <span class="expand-toggle" onclick="var p=document.getElementById('tutorContentPre');p.style.display=p.style.display==='none'?'block':'none'">[展开/折叠]</span></h3>
<pre id="tutorContentPre" class="preview-pre" style="display:none"></pre>
</div>

<div class="pc" id="tutorChatBox" style="display:none">
<h3>💬 AI 辅导对话</h3>
<div id="tutorChatLog" class="chat-log">
<div style="color:var(--text2);text-align:center;padding:20px">AI导师已就绪，开始提问吧！</div>
</div>
<div class="tutor-input-wrap">
<textarea id="tutorInput" class="tutor-textarea" placeholder="输入你的问题..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();tutorSend('chat')}"></textarea>
<div class="tutor-btn-col">
<button class="btn btn-pr btn-sm" onclick="tutorSend('chat')">📤 提问</button>
<button class="btn btn-out btn-sm" onclick="tutorSend('rewrite')">✍️ 改写</button>
<button class="btn btn-out btn-sm" onclick="tutorSend('html')">🎨 HTML</button>
</div>
</div>
<div style="display:flex;gap:8px;align-items:center;margin-top:6px">
<span style="font-size:11px;color:var(--text2)">HTML风格:</span>
<select id="tutorHtmlStyle" class="tutor-select" style="padding:4px 8px;font-size:11px">
<option value="dark">暗色科技风</option>
<option value="light">清新白底风</option>
<option value="modern">现代极简风</option>
</select>
<span id="tutorStatus" class="msg-inline"></span>
</div>
</div>

<div class="pc" id="tutorResultBox" style="display:none">
<h3>📝 操作结果</h3>
<div id="tutorResultContent" style="font-size:12px"></div>
<div class="btn-grp" id="tutorResultActions" style="display:none"></div>
</div>
</div>

<!-- SYSTEM -->

<div class="page" id="pg-sys">
<div class="ph"><h1>💾 系统管理</h1><p>备份 · 恢复 · 重置</p></div>
<div class="pc"><h3>📤 导出配置</h3><p class="form-hint" style="margin-bottom:10px">一键导出全部配置到 C:\bilibili_claw_backup</p>
<button class="btn btn-pr" onclick="exportConfig()">📤 导出全部配置</button>
<div id="exportMsg" style="margin-top:8px;font-size:12px"></div>
</div>
<div class="pc"><h3>📥 导入配置</h3><p class="form-hint" style="margin-bottom:10px">从备份文件恢复</p>
<button class="btn btn-out" onclick="listBackups()">🔍 刷新备份列表</button>
<div id="backupList" style="margin:10px 0;font-size:12px"></div>
</div>

<!-- THEME & BACKGROUND SETTINGS -->
<div class="pc" id="themeSettings">
<h3>🎨 主题 & 背景设置</h3>
<p class="form-hint">选择面板主题风格和自定义背景</p>
<div class="fg"><label>主题风格</label>
<select id="themeSelect" onchange="switchTheme(this.value)">
<option value="aurora">🌌 极光 (默认)</option>
<option value="cyberpunk">🤖 赛博朋克</option>
<option value="sakura">🌸 樱花</option>
<option value="galaxy">🌌 星空</option>
</select>
</div>
<div class="fg"><label>背景图片 URL</label>
<input id="bgImage" placeholder="https://example.com/bg.jpg 或留空使用默认渐变">
<p class="form-hint" style="margin-top:4px;margin-bottom:0">支持 JPG/PNG/GIF，建议分辨率 1920×1080+</p>
</div>
<div class="fg"><label>背景视频 URL</label>
<input id="bgVideo" placeholder="https://example.com/bg.mp4 (优先于图片)">
<p class="form-hint" style="margin-top:4px;margin-bottom:0">支持 MP4/WebM，优先级高于背景图片</p>
</div>
<div class="fg"><label>背景透明度</label>
<input id="bgOpacity" type="range" min="0" max="100" value="35" oninput="document.getElementById('bgOpacityVal').textContent=this.value+'%'">
<span id="bgOpacityVal" style="font-size:11px;color:var(--text2);margin-left:8px">35%</span>
</div>
<div class="btn-grp">
<button class="btn btn-pr" onclick="saveThemeSettings()">💾 保存设置</button>
<button class="btn btn-out" onclick="resetThemeSettings()">🔄 恢复默认</button>
<span id="themeMsg" class="msg-inline"></span>
</div>
</div>

<div class="pc danger-zone">
<h3 style="color:var(--red)">⚠ 恢复出厂设置</h3>
<p style="font-size:11px;color:var(--text2)">清除所有配置、登录信息、数据文件。此操作不可逆！</p>
<div class="fg"><label><input type="checkbox" id="resetKB"> 同时删除知识库目录</label></div>
<div class="fg"><label><input type="checkbox" id="resetWeb"> 同时删除web/导出目录</label></div>
<div class="fg"><label><input type="checkbox" id="resetBackup"> 同时删除导出备份目录</label></div>
<button class="btn btn-dan" onclick="factoryReset()">🔥 恢复出厂设置</button>
</div>
</div>

<!-- ABOUT -->
<div class="page" id="pg-about">
<div class="ph"><h1>ℹ️ 关于系统</h1><p>版本信息 · 技术栈 · 联系方式</p></div>
<div class="pc" id="aboutBox"></div>
<div class="disclaimer">⚠ 免责声明：本项目仅供学习参考，若因使用本项目产生的任何后果，本人一律概不负责。</div>
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
if(typeof Chart==='undefined'){var el=document.getElementById(canvasId);if(el)el.parentElement.querySelector('h4').textContent+=' ⚠(CDN加载失败)';return}
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
h+='<div class="sc"><div class="si or">🛡</div><div><div class="sv">'+(d.safety_enabled?'已开启':'已关闭')+'</div><div class="sl">安全校验</div></div></div>';
h+='<div class="sc"><div class="si pk">⏱</div><div><div class="sv" id="puptime">--</div><div class="sl">运行时长</div></div></div>';
h+='<div class="sc"><div class="si pp">📦</div><div><div class="sv">'+(d.data_files||0)+'</div><div class="sl">数据文件</div></div></div>';
h+='<div class="sc"><div class="si '+(d.comment_mode=='real'?'gn':'or')+'">💬</div><div><div class="sv">'+(d.comment_mode=='real'?'真实模式':'模拟模式')+'</div><div class="sl">评论模式</div></div></div>';
h+='<div class="sc" id="asrDashCard"><div class="si '+(d.asr_enabled?'gn':'rd')+'">🎙️</div><div><div class="sv">'+(d.asr_enabled?'开启':'关闭')+'</div><div class="sl">ASR语音识别</div></div></div>';
h+='<div class="sc"><div class="si '+(d.pm_enabled?'gn':'rd')+'">📩</div><div><div class="sv">'+(d.pm_enabled?'开启':'关闭')+'</div><div class="sl">私信功能</div></div></div>';
document.getElementById('dashStats').innerHTML=h;
document.getElementById('puptime').textContent=d.uptime;

var dot=document.getElementById('botDot');dot.className='dot '+(d.bot_running?'on':'off');
var bd='<table class="tb"><tr><th>项目</th><th>值</th><th>项目</th><th>值</th></tr>';
bd+='<tr><td>运行状态</td><td><span class="tg '+(d.bot_running?'tg-suc':'tg-war')+'">'+(d.bot_running?'● 运行中':'○ 已停止')+'</span></td><td>启动时间</td><td>'+(d.bot_start_time||'-')+'</td></tr>';
bd+='<tr><td>API状态</td><td><span class="tg '+(d.api_configured?'tg-suc':'tg-dan')+'">'+(d.api_configured?'已配置':'未配置')+'</span></td>';
if(d.mood)bd+='<td>心情 / 精力</td><td>'+(d.mood.mood||'-')+' / '+(d.mood.energy||'?')+'</td>';
else bd+='<td>心情</td><td>-</td>';
bd+='</tr>';
if(d.persona)bd+='<tr><td>当前人格</td><td>'+(d.persona.active||'-')+'</td>';
else bd+='<tr><td>当前人格</td><td>-</td>';
if(d.cost_total!=null)bd+='<td>累计费用</td><td>$'+Number(d.cost_total).toFixed(4)+'</td>';
else bd+='<td>累计费用</td><td>-</td>';
bd+='</tr>';
bd+='<tr><td>评论模式</td><td><span class="tg '+(d.comment_mode=='real'?'tg-suc':'tg-war')+'">'+(d.comment_mode=='real'?'真实模式':'模拟模式')+'</span></td>';
bd+='<td>安全校验</td><td><span class="tg '+(d.safety_enabled?'tg-suc':'tg-dan')+'">'+(d.safety_enabled?'● 已开启':'○ 已关闭')+'</span></td>';
bd+='</tr>';
bd+='<tr><td>AI模型</td><td>'+(d.model_brain||'-')+'</td>';
bd+='<td>私信功能</td><td><span class="tg '+(d.pm_enabled?'tg-suc':'tg-war')+'">'+(d.pm_enabled?'开启':'关闭')+'</span></td>';
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
document.getElementById('ctrlStatus').innerHTML=d.bot_running?'<span class="tg tg-suc pulse">● 运行中</span> 自 '+d.bot_start_time:'<span class="tg tg-war">○ 已停止</span>';
document.getElementById('btnStart').style.display=d.bot_running?'none':'';
document.getElementById('btnStop').style.display=d.bot_running?'':'none';
}
async function startBot(){
var sel=document.getElementById('botMode');
var mode=sel?sel.value:'current';
if(mode!=='smart'&&mode!=='current')mode='current';
var r=await api('POST','/api/bot/start',{mode:mode});
if(r.ok){
  var label=mode==='smart'?'智能省token':'当前';
  toast('已以「'+label+'」模式启动','ok');
  userScrolledUp=false;pollLog();rf_dash();
  var lb=document.getElementById('botLog');if(lb){lb.scrollTop=lb.scrollHeight;lb.scrollIntoView({behavior:'smooth',block:'nearest'});}
}else{
  toast(r.message||'启动失败','err');
}
upCtrlUI();
}
var _botModeSynced=false;
async function syncBotMode(){
if(_botModeSynced)return;_botModeSynced=true;
try{var c=await api('GET','/api/config');var m=(c&&c.system&&c.system.smart_token_mode)?'smart':'current';var sel=document.getElementById('botMode');if(sel)sel.value=m;}catch(e){}
}
async function stopBot(){
var r=await api('POST','/api/bot/stop');toast(r.message,r.ok?'ok':'err');upCtrlUI();if(r.ok)rf_dash()
}
async function restartBot(){
toast('正在重启机器人...','ok');
await stopBot();
setTimeout(startBot,1200);
}
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

// ── MONITOR ──
var monitorLogPoll=null;
var monitorUserScrolledUp=false;
function rf_monitor(){
refreshMonitor();
pollMonitorLog();
var lb=document.getElementById('monitorLog');
if(lb){
lb.addEventListener('scroll',function(){
var el=lb;
var atBottom=el.scrollHeight - el.scrollTop - el.clientHeight < 30;
monitorUserScrolledUp=!atBottom;
});
}
}
async function refreshMonitor(){
try{
var r=await api('GET','/api/monitor/status');
document.getElementById('monitorStatus').innerHTML=r.running?'<span class="tg tg-suc pulse" style="font-size:13px;padding:5px 12px">● 监听中</span>':'<span class="tg tg-war" style="font-size:13px;padding:5px 12px">○ 已停止</span>';
document.getElementById('monitorUptime').textContent=r.running&&r.uptime?'已运行 '+r.uptime:'';
document.getElementById('btnMonitorStart').style.display=r.running?'none':'';
document.getElementById('btnMonitorStop').style.display=r.running?'':'none';
document.getElementById('monitorBadge').style.display=r.running?'':'none';
document.getElementById('monitorBadge').style.background=r.running?'var(--green)':'';
// 配置
if(r.config){
document.getElementById('monCmtInterval').value=r.config.comment_check_interval||120;
document.getElementById('monMsgInterval').value=r.config.private_msg_check_interval||60;
document.getElementById('monMaxReplies').value=r.config.max_replies_per_check||5;
document.getElementById('monAutoReply').value=r.config.auto_reply!==false?'true':'false';
}
// 统计卡片
var s=r.stats||{};
var h='';
h+='<div class="sc"><div class="si bl">💬</div><div><div class="sv">'+(s.comments_processed||0)+'</div><div class="sl">评论处理</div></div></div>';
h+='<div class="sc"><div class="si gn">📩</div><div><div class="sv">'+(s.messages_processed||0)+'</div><div class="sl">私信处理</div></div></div>';
h+='<div class="sc"><div class="si or">🔄</div><div><div class="sv">'+(s.total_replies||0)+'</div><div class="sl">总回复数</div></div></div>';
h+='<div class="sc"><div class="si pk">⏱</div><div><div class="sv">'+(r.uptime||'-')+'</div><div class="sl">运行时长</div></div></div>';
h+='<div class="sc"><div class="si '+(s.errors>0?'or':'gn')+'">⚡</div><div><div class="sv">'+(s.errors||0)+'</div><div class="sl">错误次数</div></div></div>';
document.getElementById('monitorStats').innerHTML=h;
// badges
document.getElementById('botBadge').style.display=!r.running?'none':'';
document.getElementById('loginBadge').style.display=r.running?'none':'';
}catch(e){}
}
async function startMonitor(){
var r=await api('POST','/api/monitor/start');
toast(r.message,r.ok?'ok':'err');
refreshMonitor();
if(r.ok){monitorUserScrolledUp=false;pollMonitorLog()}
}
async function stopMonitor(){
var r=await api('POST','/api/monitor/stop');
toast(r.message,r.ok?'ok':'err');
refreshMonitor();
}
async function saveMonitorConfig(){
var cfg={
comment_check_interval:parseInt(document.getElementById('monCmtInterval').value)||120,
private_msg_check_interval:parseInt(document.getElementById('monMsgInterval').value)||60,
max_replies_per_check:parseInt(document.getElementById('monMaxReplies').value)||5,
auto_reply:document.getElementById('monAutoReply').value==='true'
};
var r=await api('POST','/api/monitor/config',cfg);
document.getElementById('monCfgMsg').innerHTML=r.ok?'<span style="color:var(--green)">✓ 已保存</span>':'<span style="color:var(--red)">'+r.message+'</span>';
toast(r.message,r.ok?'ok':'err');
}
async function pollMonitorLog(){
if(monitorLogPoll)clearInterval(monitorLogPoll);
var tick=async function(){
try{
var r=await api('GET','/api/monitor/output');
var el=document.getElementById('monitorLog');
var wasAtBottom=el&&(el.scrollHeight-el.scrollTop-el.clientHeight<30);
if(el){
el.textContent=r.output||'等待启动...';
if(!monitorUserScrolledUp||wasAtBottom)el.scrollTop=el.scrollHeight;
var lines=(r.output||'').split('\n').filter(function(l){return l.trim()});
document.getElementById('monitorLogCount').textContent=lines.length+' 行';
}
}catch(e){}
};
tick();
monitorLogPoll=setInterval(tick,2000);
}

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
var _confMode='quick',_confData=null;
function rf_conf(){loadConf()}
function toggleConfMode(){
_confMode=_confMode==='quick'?'json':'quick';
document.getElementById('confQuickBox').style.display=_confMode==='quick'?'':'none';
document.getElementById('confJsonBox').style.display=_confMode==='json'?'':'none';
if(_confMode==='json')loadConf();
else loadConfQuick();
}
async function loadConf(){try{var r=await api('GET','/api/config');_confData=r;document.getElementById('confEd').value=JSON.stringify(r,null,2)}catch(e){toast('加载失败','err')}}
async function saveConf(){try{var v=JSON.parse(document.getElementById('confEd').value);var r=await api('POST','/api/config',v);toast(r.message,r.ok?'ok':'err');_confData=v;if(_confMode=='quick')loadConfQuick()}catch(e){toast('JSON格式错误: '+e.message,'err')}}
async function applyPreset(){
var sel=document.getElementById('cqPreset');if(!sel)return;
var key=sel.value;if(!key)return;
try{var ps=await api('GET','/api/ai/presets');var p=(ps.presets&&ps.presets[key])||ps[key];if(!p)return;
document.getElementById('cqBaseUrl').value=p.base_url||'';
document.getElementById('cqModelBrain').value=p.chat||'';
document.getElementById('cqModelVision').value=p.vision||'';
toast('已填入预设: '+(p.name||key),'ok');
}catch(e){toast('读取预设失败: '+e.message,'err')}
}
async function loadConfQuick(){
if(!_confData){var r=await api('GET','/api/config');_confData=r}
var c=_confData;
var h='';
// API
h+='<fieldset class="fs"><legend>🔑 API 设置</legend>';
h+='<div class="fg"><label>厂商预设 (一键填入官方格式)</label><select id="cqPreset" onchange="applyPreset()"><option value="">— 自定义 / OpenAI 兼容 —</option></select></div>';
h+='<div class="fg"><label>API Key</label><input id="cqApiKey" value="'+(c.api?c.api.unified_api_key||'':'')+'" placeholder="sk-..."></div>';
h+='<div class="fg"><label>Base URL</label><input id="cqBaseUrl" value="'+(c.api?c.api.unified_base_url||'':'')+'" placeholder="https://api.openai.com/v1"></div>';
h+='<div class="fg"><label>模型(对话)</label><input id="cqModelBrain" value="'+(c.api?c.api.model_brain||'':'')+'" placeholder="gpt-4o"></div>';
h+='<div class="fg"><label>模型(视觉)</label><input id="cqModelVision" value="'+(c.api?c.api.model_vision||'':'')+'" placeholder="gpt-4o"></div>';
h+='</fieldset>';
// 交互
h+='<fieldset class="fs"><legend>🤝 交互设置</legend>';
h+='<div class="fg"><label>最大精力值</label><input id="cqMaxEnergy" type="number" value="'+((c.interaction?c.interaction.max_energy:0)||100)+'"></div>';
h+='<div class="fg"><label>评论检查间隔(秒)</label><input id="cqCmtInterval" type="number" value="'+((c.interaction?c.interaction.comment_check_interval:0)||300)+'"></div>';
h+='<div class="fg"><label>每次最大回复数</label><input id="cqMaxReplies" type="number" value="'+((c.interaction?c.interaction.max_replies_per_check:0)||3)+'"></div>';
h+='</fieldset>';
// 人格
h+='<fieldset class="fs"><legend>🎭 人格设置</legend>';
h+='<div class="fg"><label>活跃人格</label><input id="cqPersona" value="'+(c.persona?c.persona.active_persona||c.persona.prompt_name||'':'')+'" placeholder="默认人格"></div>';
h+='<div class="fg"><label>提示词名称</label><input id="cqPromptName" value="'+(c.persona?c.persona.prompt_name||'':'')+'" placeholder="AI小助手"></div>';
h+='</fieldset>';
// 视频
h+='<fieldset class="fs"><legend>🎬 视频设置</legend>';
h+='<div class="fg"><label>视频模式</label><select id="cqVideoMode"><option value="smart"'+(c.video&&c.video.mode=='smart'?' selected':'')+'>智能</option><option value="random"'+(c.video&&c.video.mode=='random'?' selected':'')+'>随机</option><option value="hot"'+(c.video&&c.video.mode=='hot'?' selected':'')+'>热门</option></select></div>';
h+='<div class="fg"><label>最大时长(秒)</label><input id="cqMaxDuration" type="number" value="'+((c.video?c.video.max_duration_seconds:0)||900)+'"></div>';
h+='</fieldset>';
// 行为
h+='<fieldset class="fs"><legend>⚡ 行为设置</legend>';
h+='<div class="fg"><label>评论模式</label><select id="cqCommentMode"><option value="real"'+(c.behavior&&c.behavior.comment_mode=='real'?' selected':'')+'>真实模式</option><option value="simulate"'+(c.behavior&&c.behavior.comment_mode=='simulate'?' selected':'')+'>模拟模式</option></select></div>';
h+='<div class="fg"><label>AI免责声明</label><input id="cqAiMarker" value="'+(c.behavior?c.behavior.ai_marker||'':'')+'" placeholder="（内容由AI生成并由AI回复）"></div>';
h+='</fieldset>';
// 安全
h+='<fieldset class="fs"><legend>🛡 安全设置</legend>';
h+='<div class="fg"><label>安全校验</label><select id="cqSafety"><option value="1"'+(c.reply_safety&&c.reply_safety.enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.reply_safety&&c.reply_safety.enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='<div class="fg"><label>屏蔽关键词(逗号分隔)</label><textarea id="cqBlockedKw" style="width:100%;min-height:60px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:12px;padding:8px;font-family:inherit;resize:vertical">'+((c.reply_safety&&c.reply_safety.blocked_keywords?c.reply_safety.blocked_keywords.join(', '):''))+'</textarea></div>';
h+='</fieldset>';
// 私信
h+='<fieldset class="fs"><legend>📩 私信设置</legend>';
h+='<div class="fg"><label>私信功能</label><select id="cqPmEnabled"><option value="1"'+(c.private_message&&c.private_message.enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.private_message&&c.private_message.enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='<div class="fg"><label>自动回复</label><select id="cqPmAuto"><option value="1"'+(c.private_message&&c.private_message.auto_reply!==false?' selected':'')+'>启用</option><option value="0"'+(c.private_message&&c.private_message.auto_reply===false?' selected':'')+'>禁用</option></select></div>';
h+='</fieldset>';
// 日记 & 进化
h+='<fieldset class="fs"><legend>📖 日记 & 进化</legend>';
h+='<div class="fg"><label>日记</label><select id="cqDiary"><option value="1"'+(c.diary&&c.diary.enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.diary&&c.diary.enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='<div class="fg"><label>自我进化</label><select id="cqEvolution"><option value="1"'+(c.self_evolution&&c.self_evolution.enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.self_evolution&&c.self_evolution.enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='</fieldset>';
// Agent
h+='<fieldset class="fs"><legend>🤖 Agent 设置</legend>';
h+='<div class="fg"><label>Agent</label><select id="cqAgent"><option value="1"'+(c.agent&&c.agent.enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.agent&&c.agent.enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='<div class="fg"><label>自动Agent</label><select id="cqAgentAuto"><option value="1"'+(c.agent&&c.agent.auto_enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.agent&&c.agent.auto_enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='</fieldset>';
// 视觉/ASR
h+='<fieldset class="fs"><legend>👁 视觉 & ASR</legend>';
h+='<div class="fg"><label>ASR语音识别</label><select id="cqAsr"><option value="1"'+(c.asr&&c.asr.enabled?' selected':'')+'>启用</option><option value="0"'+(c.asr&&!c.asr||!c.asr.enabled?' selected':'')+'>禁用</option></select></div>';
h+='<div class="fg"><label>视觉理解</label><select id="cqVision"><option value="1"'+(c.vision&&c.vision.cover_enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.vision&&c.vision.cover_enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='</fieldset>';
document.getElementById('confQuickContent').innerHTML=h;
try{var _ps=await api('GET','/api/ai/presets');var _sel=document.getElementById('cqPreset');if(_sel&&_ps){var _pr=_ps.presets||_ps;for(var _k in _pr){var _o=document.createElement('option');_o.value=_k;_o.textContent=_pr[_k].name;_sel.appendChild(_o);}if(_ps.active_preset)_sel.value=_ps.active_preset;}}catch(e){}
}
async function saveConfQuick(){
try{
if(!_confData)_confData=await api('GET','/api/config');
var c=JSON.parse(JSON.stringify(_confData));
// API
c.api=c.api||{};
c.api.unified_api_key=document.getElementById('cqApiKey').value.trim();
c.api.unified_base_url=document.getElementById('cqBaseUrl').value.trim();
c.api.model_brain=document.getElementById('cqModelBrain').value.trim();
c.api.model_vision=document.getElementById('cqModelVision').value.trim();
var _psel=document.getElementById('cqPreset');if(_psel)c.api.active_preset=_psel.value;
// Interaction
c.interaction=c.interaction||{};
c.interaction.max_energy=parseInt(document.getElementById('cqMaxEnergy').value)||100;
c.interaction.comment_check_interval=parseInt(document.getElementById('cqCmtInterval').value)||300;
c.interaction.max_replies_per_check=parseInt(document.getElementById('cqMaxReplies').value)||3;
// Persona
c.persona=c.persona||{};
c.persona.active_persona=document.getElementById('cqPersona').value.trim()||'默认人格';
c.persona.prompt_name=document.getElementById('cqPromptName').value.trim()||'AI小助手';
// Video
c.video=c.video||{};
c.video.mode=document.getElementById('cqVideoMode').value;
c.video.max_duration_seconds=parseInt(document.getElementById('cqMaxDuration').value)||900;
// Behavior
c.behavior=c.behavior||{};
c.behavior.comment_mode=document.getElementById('cqCommentMode').value;
c.behavior.ai_marker=document.getElementById('cqAiMarker').value.trim();
// Safety
c.reply_safety=c.reply_safety||{};
c.reply_safety.enabled=document.getElementById('cqSafety').value==='1';
var kwRaw=document.getElementById('cqBlockedKw').value;
c.reply_safety.blocked_keywords=kwRaw.split(/[,，\n]/).map(function(s){return s.trim()}).filter(function(s){return s.length>0});
// Private message
c.private_message=c.private_message||{};
c.private_message.enabled=document.getElementById('cqPmEnabled').value==='1';
c.private_message.auto_reply=document.getElementById('cqPmAuto').value==='1';
// Diary & evolution
c.diary=c.diary||{};
c.diary.enabled=document.getElementById('cqDiary').value==='1';
c.self_evolution=c.self_evolution||{};
c.self_evolution.enabled=document.getElementById('cqEvolution').value==='1';
// Agent
c.agent=c.agent||{};
c.agent.enabled=document.getElementById('cqAgent').value==='1';
c.agent.auto_enabled=document.getElementById('cqAgentAuto').value==='1';
// ASR
c.asr=c.asr||{};
c.asr.enabled=document.getElementById('cqAsr').value==='1';
// Vision
c.vision=c.vision||{};
c.vision.cover_enabled=document.getElementById('cqVision').value==='1';
var r=await api('POST','/api/config',c);
_confData=c;
document.getElementById('confQuickMsg').innerHTML=r.ok?'<span style="color:var(--green)">✅ '+r.message+'</span>':'<span style="color:var(--red)">❌ '+r.message+'</span>';
toast(r.message,r.ok?'ok':'err');
}catch(e){toast('保存失败: '+e.message,'err')}
}

// ── PERSONA ──
async function rf_psna(){
try{
var r=await api('GET','/api/personas');var h='',items=r.items||{},act=r.active||'';
for(var n in items){
var p=items[n],isA=n===act;
h+=`<div class="pc" data-persona="${esc(n)}"><h3>${isA?'<span class="tg tg-suc">● 活跃</span> ':''}${esc(n)}</h3><div style="font-size:11px;color:var(--text2)">风格：${esc(p.style||'-')} | 规则：${(p.rules||[]).length}条</div><div class="btn-grp">${isA?'':'<button class="btn btn-sm btn-pr" data-act-psna="${esc(n)}">启用</button>'}<button class="btn btn-sm btn-out" data-del-psna="${esc(n)}" ${Object.keys(items).length<2?'disabled':''}>删除</button></div></div>`;
}
h+=`<div class="pc"><h3>➕ 新建人设</h3><div class="fg"><label>名称</label><input id="npName" placeholder="如: 毒舌模式"></div><div class="fg"><label>系统Prompt</label><textarea id="npPrompt" placeholder="你是..."></textarea></div><div class="fg"><label>风格</label><input id="npStyle" placeholder="幽默、犀利"></div><button class="btn btn-pr" onclick="addPsna()">创建</button></div>`;
document.getElementById('psnaList').innerHTML=h;
// Event delegation for persona buttons
document.getElementById('psnaList').onclick=function(e){
var t=e.target;
if(t.dataset.actPsna){actPsna(t.dataset.actPsna);return}
if(t.dataset.delPsna){delPsna(t.dataset.delPsna);return}
};
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
function aboutCard(label,value,mono){
return '<div class="info-card"><div class="il">'+label+'</div><div class="iv'+(mono?' style=\"font-family:monospace;font-size:12px\'"':'')+'">'+value+'</div></div>';
}
document.getElementById('aboutBox').innerHTML='<div class="info-grid">'+
aboutCard('系统版本','v1.0')+
aboutCard('面板运行时长',d.uptime)+
aboutCard('Python 版本',d.python_version||'-')+
aboutCard('运行平台',d.platform||'-')+
aboutCard('工作目录',d.cwd||'-',true)+
aboutCard('机器人状态',d.bot_running?'● 运行中':'○ 已停止')+
'</div>'+
'<div class="sec-divider"></div>'+
'<p style="font-size:12px;color:var(--text2);line-height:2"><strong style="color:var(--text)">B站 AI 智能管理系统</strong><br>基于大语言模型 · 视频理解 · 评论互动 · 私信回复 · 知识沉淀 · 自我进化</p>'+
'<div style="margin-top:14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap"><span style="color:var(--text2);font-size:12px">作者联系方式：</span><span style="display:inline-flex;align-items:center;gap:6px;background:rgba(88,166,255,.08);padding:6px 14px;border-radius:6px;color:var(--accent);font-weight:600;font-size:14px;letter-spacing:.5px">🐧 QQ: 3781960338</span><span style="display:inline-flex;align-items:center;gap:6px;background:rgba(88,166,255,.08);padding:6px 14px;border-radius:6px;color:var(--accent);font-weight:600;font-size:14px;letter-spacing:.5px">👥 交流群: 1056941856</span></div>';
}catch(e){}
}

// ── UTIL ──
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}

// ── AUTO REFRESH ──
var autoTmr=null;
function auto(){
if(autoTmr)return;
autoTmr=setInterval(async function(){
if(document.hidden)return;
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
document.getElementById("moodStatus").innerHTML="<div style=\"font-size:14px\">当前心情: <strong style=\"color:var(--accent);font-size:18px\">"+(r.current_mood||"-")+"</strong> | 精力: <strong style=\"color:var(--green)\">"+(r.energy||"?")+"</strong></div>";
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
function rf_behavior(){fetchBehavior();fetchSafety()}
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
document.getElementById("engVideoIntMin").value=e.video_interval_min||1;
document.getElementById("engVideoIntMax").value=e.video_interval_max||5;
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
video_interval_min:parseInt(document.getElementById("engVideoIntMin").value)||1,
video_interval_max:parseInt(document.getElementById("engVideoIntMax").value)||5
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

	// ── SAFETY KEYWORDS ──
	var _safetyLoaded=false;
	async function fetchSafety(){
	try{
	var r=await api("GET","/api/behavior/safety");
	document.getElementById("safetyEnabled").checked=r.enabled||false;
	var kws=r.keywords||[];
	document.getElementById("safetyKeywords").value=kws.join("\n");
	document.getElementById("safetyKwSection").style.display=r.enabled?"":"none";
	_safetyLoaded=true;
	}catch(e){}
	}
	async function toggleSafety(){
	if(!_safetyLoaded){await fetchSafety();}
	var cb=document.getElementById("safetyEnabled");
	if(!cb.checked){
	if(!confirm("⚠ 确定要关闭关键词安全校验吗？\n\n关闭后AI将不再过滤任何评论和回复。\n这可能导致账号风险。\n\n你可以随时在设置中重新开启。")){
	cb.checked=true;
	return;
	}
	}
	var r=await api("POST","/api/behavior/safety/toggle",{enabled:cb.checked});
	document.getElementById("safetyKwSection").style.display=cb.checked?"":"none";
	document.getElementById("safetyMsg").textContent=r.message||"";
	toast(r.message,r.ok?"ok":"err");
	}
	async function saveSafetyKeywords(){
	var txt=document.getElementById("safetyKeywords").value.trim();
	var kws=txt.split(/[\n,]/).map(function(s){return s.trim()}).filter(function(s){return s.length>0});
	var r=await api("POST","/api/behavior/safety/save",{keywords:kws});
	document.getElementById("safetyMsg").textContent=r.message||"";
	toast(r.message,r.ok?"ok":"err");
	}
	async function addSafetyKeyword(){
	var inp=document.getElementById("newSafetyKw");
	var kw=inp.value.trim();
	if(!kw){toast("请输入关键词","err");return}
	var ta=document.getElementById("safetyKeywords");
	var kws=ta.value.split("\n").map(function(s){return s.trim()}).filter(function(s){return s.length>0});
	if(kws.indexOf(kw)>=0){toast("关键词已存在","err");inp.value="";return}
	kws.push(kw);
	ta.value=kws.join("\n");
	inp.value="";
	await saveSafetyKeywords();
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
document.getElementById("asrMsg").innerHTML=r.ok?'<span style="color:var(--green)">已保存</span>':'<span style="color:var(--red)">'+r.message+'</span>'}
async function saveDry(){var c=await api("GET","/api/config");if(!c)return;
c.dry_goods=c.dry_goods||{};c.dry_goods.enabled=document.getElementById("dryEnabled").value=="1";
c.dry_goods.min_score=parseFloat(document.getElementById("dryMinScore").value)||8.0;
c.dry_goods.folder_name=document.getElementById("dryFolder").value||"highlights";
var r=await api("POST","/api/config",c);
document.getElementById("dryMsg").innerHTML=r.ok?'<span style="color:var(--green)">已保存</span>':'<span style="color:var(--red)">'+r.message+'</span>'}
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
// 🔒 服务端两步确认
var req=await api("POST","/api/factory-reset/request");
if(!req.ok){toast(req.message,"err");return}
var token=prompt("⚠ 最后确认：输入确认令牌以执行\n\n令牌: "+req.token+"\n（直接复制粘贴上面的令牌）");
if(!token||token!==req.token){toast("令牌不匹配，已取消","err");return}
var delKB=document.getElementById("resetKB").checked;
var delWeb=document.getElementById("resetWeb").checked;
var delBackup=document.getElementById("resetBackup").checked;
if(delKB&&!confirm("同时删除知识库目录？此操作不可逆！"))return;
if(delWeb&&!confirm("同时删除web/导出目录？此操作不可逆！"))return;
if(delBackup&&!confirm("同时删除导出备份目录？此操作不可逆！"))return;
var r=await api("POST","/api/factory-reset",{delete_kb:delKB,delete_web:delWeb,delete_backup:delBackup,confirm_token:token});toast(r.message,r.ok?"ok":"err");if(r.ok){rf_dash();listBackups()}}

// ── TUTOR (v2.0.3) ──
var _tutorHistory=[],_tutorRelPaths=[];
function rf_tutor(){
var sel=document.getElementById("tutorFileSelect");
fetch("/api/kb/list-files").then(function(r){return r.json()}).then(function(d){
if(!d.ok){toast(d.message,"err");return}
sel.innerHTML='';
for(var i=0;i<d.files.length;i++){
var f=d.files[i],up=f.up_name?" @"+f.up_name:"";
sel.innerHTML+='<option value="'+esc(f.rel_path)+'">['+f.category_path+'] '+esc(f.title)+up+' ('+f.size_kb+'KB)</option>';
}
}).catch(function(e){toast("加载文件列表失败","err")});
}
function tutorSelectAll(){
var sel=document.getElementById("tutorFileSelect");
for(var i=0;i<sel.options.length;i++)sel.options[i].selected=true;
}
function tutorSelectNone(){
var sel=document.getElementById("tutorFileSelect");
for(var i=0;i<sel.options.length;i++)sel.options[i].selected=false;
}
function _tutorGetSelected(){
var sel=document.getElementById("tutorFileSelect");
var out=[];
for(var i=0;i<sel.options.length;i++){
if(sel.options[i].selected)out.push(sel.options[i].value);
}
return out;
}
async function tutorLoadFile(){
var rps=_tutorGetSelected();
if(rps.length===0){toast("请至少选择一个知识文件","err");return}
_tutorRelPaths=rps;_tutorHistory=[];
document.getElementById("tutorChatLog").innerHTML='<div style="color:var(--text2);text-align:center;padding:20px">AI导师已就绪'+(rps.length>1?'（'+rps.length+'个文件）':'')+'，开始提问吧！</div>';
try{
var r=await api("POST","/api/kb/read-file",{rel_paths:rps});
if(!r.ok){toast(r.message,"err");return}
document.getElementById("tutorFileInfo").innerHTML='<span class="tg tg-suc">已加载 '+rps.length+' 个文件</span> ('+r.total_size+' 字符)';
document.getElementById("tutorContentPre").textContent=r.content||"(多文件内容已合并)";
document.getElementById("tutorContentBox").style.display="";
document.getElementById("tutorChatBox").style.display="";
document.getElementById("tutorResultBox").style.display="none";
}catch(e){toast("加载失败: "+e.message,"err")}
}
async function tutorSend(mode){
if(_tutorRelPaths.length===0){toast("请先加载文件","err");return}
var inp=document.getElementById("tutorInput");
var msg=inp.value.trim();
if(mode!="rewrite"&&mode!="html"&&!msg){toast("请输入问题","err");return}
if(mode=="rewrite"){
if(_tutorRelPaths.length>1){
if(!msg){toast("多文件改写请输入改写要求","err");return}
}else{msg=msg||"请优化结构、补充缺失知识点、修正不准确表述。"}
}
if(mode=="html")msg=msg||"请生成知识讲解网页。";

var log=document.getElementById("tutorChatLog");
if(mode=="chat"){
log.innerHTML+='<div class="chat-bubble user"><span style="color:var(--accent);font-weight:600">💬 你:</span> '+esc(msg)+'</div>';
inp.value="";
}
var stat=document.getElementById("tutorStatus");
stat.textContent="⏳ AI思考中...";

try{
var r=await api("POST","/api/kb/tutor-chat",{
rel_paths:_tutorRelPaths, message:msg,
history:_tutorHistory, mode:mode,
style:document.getElementById("tutorHtmlStyle").value
});
if(!r.ok){stat.textContent="";toast(r.message,"err");log.innerHTML+='<div class="chat-bubble" style="color:var(--red);border-left-color:var(--red)">❌ '+esc(r.message)+'</div>';return}
stat.textContent="";

if(mode=="chat"){
_tutorHistory.push({role:"user",content:msg},{role:"assistant",content:r.reply});
if(_tutorHistory.length>20)_tutorHistory=_tutorHistory.slice(-20);
log.innerHTML+='<div class="chat-bubble ai"><span style="color:var(--accent2);font-weight:600">🎓 导师:</span> '+esc(r.reply).replace(/\n/g,"<br>")+'</div>';
log.scrollTop=log.scrollHeight;
}else if(mode=="rewrite"){
var rb=document.getElementById("tutorResultBox");
var rc=document.getElementById("tutorResultContent");
rc.innerHTML='<div style="background:rgba(76,175,124,.08);border:1px solid rgba(76,175,124,.25);border-radius:6px;padding:10px;margin-bottom:10px"><strong>修改说明:</strong> '+esc(r.summary)+'</div><pre class="preview-pre" style="max-height:300px">'+esc(r.new_content||"")+'</pre>';
rb.style.display="";
var ra=document.getElementById("tutorResultActions");
ra.style.display="";
ra.innerHTML='<button class="btn btn-suc" onclick="tutorSaveRewrite()">💾 保存改写（覆盖原文件）</button>';
window._tutorRewriteContent=r.new_content||"";
}else if(mode=="html"){
var rb=document.getElementById("tutorResultBox");
var rc=document.getElementById("tutorResultContent");
rc.innerHTML='<div style="background:rgba(91,141,239,.08);border:1px solid rgba(91,141,239,.25);border-radius:6px;padding:10px;margin-bottom:10px"><strong>HTML已生成</strong></div><pre style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:10px;max-height:200px;overflow:auto;font-size:10px;white-space:pre-wrap">'+esc((r.html||"").substring(0,2000))+'...</pre>';
rb.style.display="";
var ra=document.getElementById("tutorResultActions");
ra.style.display="";
ra.innerHTML='<button class="btn btn-pr" onclick="tutorSaveHtml()">💾 保存HTML文件</button> <button class="btn btn-out" onclick="tutorPreviewHtml()">👁 预览HTML</button>';
window._tutorHtmlContent=r.html||"";
}
}catch(e){stat.textContent="";toast("请求失败: "+e.message,"err")}
}
async function tutorSaveRewrite(){
if(!window._tutorRewriteContent||_tutorRelPaths.length===0){toast("没有可保存的内容","err");return}
try{
var r=await api("POST","/api/kb/tutor-save",{rel_path:_tutorRelPaths[0],content:window._tutorRewriteContent});
toast(r.message,r.ok?"ok":"err");
}catch(e){toast("保存失败","err")}
}
async function tutorSaveHtml(){
if(!window._tutorHtmlContent){toast("没有可保存的HTML","err");return}
try{
var title=_tutorRelPaths.length>1?"multi_"+_tutorRelPaths.length+"files":(_tutorRelPaths[0]||"knowledge").split("/").pop().replace(".md","");
var r=await api("POST","/api/kb/tutor-html-save",{html:window._tutorHtmlContent,title:title});
toast(r.message,r.ok?"ok":"err");
if(r.ok&&r.path){document.getElementById("tutorResultContent").innerHTML+='<div style="margin-top:8px;font-size:11px;color:var(--green)">文件: '+esc(r.path)+'</div>'}
}catch(e){toast("保存失败","err")}
}
function tutorPreviewHtml(){
if(!window._tutorHtmlContent){toast("没有可预览的HTML","err");return}
var w=window.open("","_blank");
if(w){w.document.write(window._tutorHtmlContent);w.document.close()}
else{toast("请允许弹窗以预览HTML","err")}
}

// ── THEME SYSTEM ──
function switchTheme(t){
document.body.classList.add('theme-transition');
document.documentElement.setAttribute('data-theme',t);
localStorage.setItem('xiongda_theme',t);
setTimeout(()=>document.body.classList.remove('theme-transition'),600);
}
function applyTheme(){
var t;try{t=localStorage.getItem('xiongda_theme')}catch(e){t='aurora'};t=t||'aurora';
document.documentElement.setAttribute('data-theme',t);
var sel=document.getElementById('themeSelect');
if(sel)sel.value=t;
}
function applyBg(){
var cfg;try{cfg=JSON.parse(localStorage.getItem('xiongda_bg')||'{}')}catch(e){cfg={}};
var layer=document.getElementById('bgLayer');
if(!layer)return;
layer.innerHTML='';
var hasVideo=cfg.video&&cfg.video.trim();
var hasImage=cfg.image&&cfg.image.trim();
var opacity=(cfg.opacity!=null?cfg.opacity:35)/100;
if(hasVideo){
var v=document.createElement('video');
v.src=cfg.video;v.autoplay=true;v.loop=true;v.muted=true;v.playsInline=true;
v.style.cssText='width:100%;height:100%;object-fit:cover;opacity:'+opacity;
v.onerror=function(){layer.innerHTML='<div class="bg-default"></div>';};
layer.appendChild(v);
}else if(hasImage){
var img=document.createElement('img');
img.src=cfg.image;img.alt='';
img.style.cssText='width:100%;height:100%;object-fit:cover;opacity:'+opacity;
img.onerror=function(){layer.innerHTML='<div class="bg-default"></div>';};
layer.appendChild(img);
}else{
layer.innerHTML='<div class="bg-default"></div>';
}
var opEl=document.getElementById('bgOpacity');
var opVal=document.getElementById('bgOpacityVal');
if(opEl)opEl.value=(cfg.opacity!=null?cfg.opacity:35);
if(opVal)opVal.textContent=(cfg.opacity!=null?cfg.opacity:35)+'%';
}
function saveThemeSettings(){
var cfg={
image:document.getElementById('bgImage').value.trim(),
video:document.getElementById('bgVideo').value.trim(),
opacity:parseInt(document.getElementById('bgOpacity').value)||35
};
localStorage.setItem('xiongda_bg',JSON.stringify(cfg));
applyTheme();applyBg();
var msg=document.getElementById('themeMsg');
if(msg){msg.textContent='✅ 已保存';msg.style.color='var(--green)';setTimeout(()=>msg.textContent='',2000);}
}
function resetThemeSettings(){
localStorage.removeItem('xiongda_bg');
document.getElementById('bgImage').value='';
document.getElementById('bgVideo').value='';
document.getElementById('bgOpacity').value=35;
document.getElementById('bgOpacityVal').textContent='35%';
switchTheme('aurora');
applyBg();
var msg=document.getElementById('themeMsg');
if(msg){msg.textContent='✅ 已恢复默认';msg.style.color='var(--green)';setTimeout(()=>msg.textContent='',2000);}
}

// ── INIT ──
applyTheme();applyBg();
rf_dash();auto();syncBotMode();
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


# 项目图标（网页左上角 logo / favicon）—— 从仓库根目录的 image.png 提供
_ICON_FILE = BASE_DIR / "image.png"


@app.route('/app-icon')
def app_icon():
    if _ICON_FILE.exists():
        return Response(_ICON_FILE.read_bytes(), mimetype='image/png')
    return Response(status=404)

@app.route('/ppt')
def ppt_panel():
    """PPT生成面板页面"""
    ppt_html = BASE_DIR / "ppt_panel.html"
    if ppt_html.exists():
        return ppt_html.read_text(encoding='utf-8')
    return "<h1>PPT面板文件不存在</h1>", 404

def _has_valid_bili_cookies():
    """检查 bili cookie 文件是否存在且包含有效字段（DedeUserID + bili_jct）"""
    if not COOKIE_FILE.exists():
        return False
    try:
        c = read_json(COOKIE_FILE)
        return bool(c and c.get('DedeUserID') and c.get('bili_jct'))
    except Exception:
        return False

# ── 信息 ──
@app.route('/api/info')
def api_info():
    config = read_json(CONFIG_FILE)
    mood = read_json(DATA_DIR / "mood_state.json") or read_json(DATA_DIR / "web_mood.json")
    persona = read_json(DATA_DIR / "web_personas.json") or read_json(DATA_DIR / "personas.json")
    # fallback: 从 config.json 的 persona 段获取活跃人格
    if not persona or not persona.get('active'):
        cfg_persona = config.get('persona', {})
        active_name = cfg_persona.get('active_persona', '') or cfg_persona.get('prompt_name', '')
        if active_name:
            persona = dict(active=active_name, items={active_name: dict(name=active_name)})
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
    ai_marker = config.get('behavior', {}).get('ai_marker', '')
    safety_enabled = config.get('reply_safety', {}).get('enabled', False)
    diary_enabled = config.get('diary', {}).get('enabled', False)
    evolution_enabled = config.get('self_evolution', {}).get('enabled', False)
    agent_enabled = config.get('agent', {}).get('enabled', False)
    pm_enabled = config.get('private_message', {}).get('enabled', False)
    notification_mode = config.get('standby', {}).get('notification_mode', True) if config.get('standby') else True
    model_brain = config.get('api', {}).get('model_brain', '') or config.get('api', {}).get('model', '')
    # 尝试读取待机状态
    standby_running_info = standby_running
    try:
        from brain.standby import load_stats
        standby_stats = load_stats()
    except Exception:
        standby_stats = {}
    return jsonify(dict(
        bot_running=bot_running,
        bot_start_time=bot_start_time.strftime('%Y-%m-%d %H:%M:%S') if bot_start_time else None,
        uptime=us,
        version=APP_VERSION,
        api_configured=bool(api_key),
        bili_logged_in=bool(bili_token) or _has_valid_bili_cookies(),
        config_sections=len(config),
        data_files=sum(1 for f in files.values() if f['exists']),
        mood=dict(mood=mood.get('mood','?'), energy=mood.get('energy','?')) if mood else None,
        persona=dict(active=persona.get('active','')) if persona else None,
        cost_total=costs.get('total',0) if costs else 0,
        files=files,
        comment_mode=comment_mode,
        ai_marker=ai_marker,
        safety_enabled=safety_enabled,
        diary_enabled=diary_enabled,
        evolution_enabled=evolution_enabled,
        agent_enabled=agent_enabled,
        pm_enabled=pm_enabled,
        notification_mode=notification_mode,
        standby_running=standby_running_info,
        standby_stats=standby_stats,
        model_brain=model_brain,
        python_version=sys.version.split()[0],
        platform=sys.platform,
        cwd=str(BASE_DIR),
        asr_enabled=config.get('asr', {}).get('enabled', False),
        asr_backend=config.get('asr', {}).get('backend', 'funasr'),
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

# ── 模型列表 ──
@app.route('/api/ai/presets')
def api_ai_presets():
    try:
        from core.config import PROVIDER_PRESETS
    except Exception:
        PROVIDER_PRESETS = {}
    active = ""
    try:
        active = read_json(CONFIG_FILE, {}).get("active_preset", "")
    except Exception:
        pass
    return jsonify(dict(presets=PROVIDER_PRESETS, active_preset=active))

# ── 模型列表 ──
@app.route('/api/models/list')
def api_models_list():
    """从配置的 API 端点获取可用模型列表"""
    config = read_json(CONFIG_FILE)
    api_key = config.get('api', {}).get('unified_api_key', '') or os.getenv('BILI_AI_API_KEY', '')
    base_url = config.get('api', {}).get('unified_base_url', '') or os.getenv('BILI_AI_BASE_URL', '')
    if not api_key or not base_url:
        return jsonify(dict(ok=False, message='请先配置 API Key 和 Base URL', models=[]))
    
    import urllib.request, ssl
    url = base_url.rstrip('/') + '/models'
    try:
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'bilibili_learning_bot/3.0',
        })
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read())
        raw_models = data.get('data', data if isinstance(data, list) else [])
        models = []
        for m in raw_models:
            mid = m.get('id', '') if isinstance(m, dict) else str(m)
            if mid and 'embed' not in mid.lower() and 'moderation' not in mid.lower() and 'dall-e' not in mid.lower() and 'tts' not in mid.lower() and 'whisper' not in mid.lower():
                models.append(dict(
                    id=mid,
                    owned_by=m.get('owned_by', '') if isinstance(m, dict) else '',
                ))
        models.sort(key=lambda x: x['id'])
        return jsonify(dict(ok=True, models=models, count=len(models)))
    except Exception as e:
        return jsonify(dict(ok=False, message=f'获取模型列表失败: {str(e)}', models=[], error=str(e)))

# ── 机器人控制 ──
@app.route('/api/bot/start', methods=['POST'])
def api_bot_start():
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    mode = data.get("mode", "current")
    if mode not in ("smart", "current"):
        mode = "current"
    ok, msg = start_bot_process(mode=mode)
    return jsonify(dict(ok=ok, message=msg, mode=mode))

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

# ── 实时监听 ──
monitor_process = None
monitor_running = False
monitor_output_lines = collections.deque(maxlen=500)
monitor_output_lock = threading.Lock()

def _monitor_reader(pipe, prefix=""):
    """读取监听进程输出"""
    try:
        for line in iter(pipe.readline, ""):
            if not line: break
            text = line.rstrip()
            if text:
                with monitor_output_lock:
                    monitor_output_lines.append(prefix + text)
    except OSError:
        pass
    finally:
        try: pipe.close()
        except OSError: pass

@app.route('/api/monitor/start', methods=['POST'])
def api_monitor_start():
    global monitor_process, monitor_running
    if monitor_running:
        return jsonify(dict(ok=False, message='监听已在运行'))
    if bot_running:
        return jsonify(dict(ok=False, message='机器人主进程运行中，请先停止'))

    monitor_script = BASE_DIR / "brain" / "monitor.py"
    if not monitor_script.exists():
        return jsonify(dict(ok=False, message=f'找不到 {monitor_script}'))

    log_line("📡 正在启动实时监听...")
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"

        monitor_process = subprocess.Popen(
            [sys.executable, str(monitor_script)],
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
        monitor_running = True
        threading.Thread(target=_monitor_reader, args=(monitor_process.stdout, ""), daemon=True).start()
        log_line("✅ 实时监听已启动")
        return jsonify(dict(ok=True, message='实时监听已启动'))
    except Exception as e:
        log_line(f"❌ 启动监听失败: {e}")
        return jsonify(dict(ok=False, message=str(e)))

@app.route('/api/monitor/stop', methods=['POST'])
def api_monitor_stop():
    global monitor_process, monitor_running
    if not monitor_running:
        return jsonify(dict(ok=False, message='监听未在运行'))
    try:
        if monitor_process:
            log_line("⏹ 正在停止监听...")
            try:
                if monitor_process.stdin and not monitor_process.stdin.closed:
                    monitor_process.stdin.write("0\n")
                    monitor_process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            time.sleep(0.5)
            monitor_process.terminate()
            try: monitor_process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                monitor_process.kill()
            monitor_process = None
    except Exception as e:
        log_line(f"停止监听异常: {e}")
    monitor_running = False
    log_line("✅ 实时监听已停止")
    return jsonify(dict(ok=True, message='已停止'))

@app.route('/api/monitor/status')
def api_monitor_status():
    from brain.monitor import load_monitor_config, is_monitor_running
    cfg = load_monitor_config()
    # 从日志中读取统计
    stats = {"comments_processed": 0, "messages_processed": 0, "total_replies": 0, "errors": 0}
    stats_file = DATA_DIR / "monitor_stats.json"
    if stats_file.exists():
        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                stats = data.get("stats", stats)
        except Exception:
            pass
    return jsonify(dict(
        running=monitor_running,
        start_time=None,
        config=cfg,
        stats=stats,
        uptime='-'
    ))

@app.route('/api/monitor/config', methods=['POST'])
def api_monitor_config():
    from brain.monitor import save_monitor_config, load_monitor_config
    cfg = load_monitor_config()
    data = request.get_json(silent=True) or {}
    # 更新配置
    for key in ['comment_check_interval', 'private_msg_check_interval', 'auto_reply', 'max_replies_per_check', 'enabled']:
        if key in data:
            cfg[key] = data[key]
    if save_monitor_config(cfg):
        return jsonify(dict(ok=True, message='监听配置已保存', config=cfg))
    return jsonify(dict(ok=False, message='保存失败'))

@app.route('/api/monitor/output')
def api_monitor_output():
    with monitor_output_lock:
        lines = list(monitor_output_lines)[-80:]
    return jsonify(dict(output='\n'.join(lines) if lines else '等待输出...'))

# ── 待机模式（Standby） ──
standby_process: subprocess.Popen | None = None
standby_running = False
standby_output_lines: list = []
standby_output_lock = threading.Lock()

def _standby_reader(stream, tag=""):
    global standby_output_lines
    for line in iter(stream.readline, ''):
        if not line:
            break
        with standby_output_lock:
            standby_output_lines.append(line.rstrip('\n'))
            if len(standby_output_lines) > 500:
                standby_output_lines = standby_output_lines[-200:]

@app.route('/api/standby/start', methods=['POST'])
def api_standby_start():
    global standby_process, standby_running, standby_output_lines
    if standby_running:
        return jsonify(dict(ok=False, message='待机模式已在运行'))
    if bot_running:
        return jsonify(dict(ok=False, message='主Bot运行中，请先停止'))

    standby_script = BASE_DIR / "brain" / "standby.py"
    if not standby_script.exists():
        return jsonify(dict(ok=False, message=f'找不到 {standby_script}'))

    # 先保存最新配置
    data = request.get_json(silent=True) or {}
    if data:
        from brain.standby import save_standby_config, load_standby_config
        cfg = load_standby_config()
        for key in ['auto_reply', 'at_trigger_enabled', 'at_trigger_keywords',
                     'comment_check_interval', 'max_replies_per_check', 'reply_cooldown_seconds',
                     'ppt_auto_generate', 'ppt_theme', 'video_trigger_enabled', 'custom_prompt',
                     'asr_enabled', 'asr_backend', 'vision_enabled', 'comment_mode',
                     'comment_fetch_enabled', 'summary_style', 'summary_max_length',
                     'monitor_own_videos_only', 'enabled']:
            if key in data:
                cfg[key] = data[key]
        save_standby_config(cfg)

    log_line("[SB] 正在启动待机模式...")
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        standby_output_lines = []

        standby_process = subprocess.Popen(
            [sys.executable, str(standby_script)],
            cwd=str(BASE_DIR),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        standby_running = True
        threading.Thread(target=_standby_reader, args=(standby_process.stdout, ""), daemon=True).start()
        log_line("[OK] 待机模式已启动")
        return jsonify(dict(ok=True, message='待机模式已启动'))
    except Exception as e:
        log_line(f"[ERR] 启动待机失败: {e}")
        return jsonify(dict(ok=False, message=str(e)))

@app.route('/api/standby/stop', methods=['POST'])
def api_standby_stop():
    global standby_process, standby_running
    if not standby_running:
        return jsonify(dict(ok=False, message='待机模式未在运行'))
    try:
        if standby_process:
            log_line("[SB] 正在停止待机...")
            try:
                if standby_process.stdin and not standby_process.stdin.closed:
                    standby_process.stdin.write("0\n")
                    standby_process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            time.sleep(0.5)
            standby_process.terminate()
            try: standby_process.wait(timeout=8)
            except subprocess.TimeoutExpired: standby_process.kill()
            standby_process = None
    except Exception as e:
        log_line(f"[ERR] 停止待机异常: {e}")
    standby_running = False
    log_line("[OK] 待机模式已停止")
    return jsonify(dict(ok=True, message='已停止'))

@app.route('/api/standby/status')
def api_standby_status():
    from brain.standby import load_standby_config, load_stats
    cfg = load_standby_config()
    st = load_stats()
    return jsonify(dict(running=standby_running, config=cfg, stats=st))

@app.route('/api/standby/config', methods=['POST'])
def api_standby_config():
    from brain.standby import save_standby_config, load_standby_config
    cfg = load_standby_config()
    data = request.get_json(silent=True) or {}
    # 所有可配置字段
    for key in ['auto_reply', 'at_trigger_enabled', 'at_trigger_keywords',
                 'comment_check_interval', 'max_replies_per_check', 'reply_cooldown_seconds',
                 'ppt_auto_generate', 'ppt_theme', 'video_trigger_enabled', 'custom_prompt',
                 'asr_enabled', 'asr_backend', 'vision_enabled', 'comment_mode',
                 'comment_fetch_enabled', 'summary_style', 'summary_max_length',
                 'monitor_own_videos_only', 'notification_mode', 'enabled']:
        if key in data:
            cfg[key] = data[key]
    # 确保新字段有默认值
    cfg.setdefault("asr_enabled", False)
    cfg.setdefault("vision_enabled", True)
    cfg.setdefault("comment_fetch_enabled", True)
    cfg.setdefault("summary_style", "structured")
    cfg.setdefault("summary_max_length", 500)
    cfg.setdefault("monitor_own_videos_only", False)
    cfg.setdefault("notification_mode", True)
    if save_standby_config(cfg):
        return jsonify(dict(ok=True, message='待机配置已保存', config=cfg))
    return jsonify(dict(ok=False, message='保存失败'))

@app.route('/api/standby/output')
def api_standby_output():
    with standby_output_lock:
        lines = list(standby_output_lines)[-80:]
    return jsonify(dict(output='\n'.join(lines) if lines else '等待输出...'))

# ── PPT生成面板 API ──
@app.route('/api/ppt/generate', methods=['POST'])
def api_ppt_generate():
    """异步生成PPT风格HTML"""
    data = request.get_json(silent=True) or {}
    bvid = data.get('bvid', '').strip()
    themes = data.get('themes', ['claude'])
    mode = data.get('mode', 'ppt')  # 'ppt' or 'default'
    custom_prompt = data.get('custom_prompt', '')

    if not bvid:
        return jsonify(dict(ok=False, message='请提供BV号'))

    if isinstance(themes, str):
        themes = [themes]

    def _do_generate():
        api_key = ""
        base_url = ""
        model = "qwen/qwen3.5-122b-a10b"
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                api_cfg = cfg.get('api', {})
                api_key = api_cfg.get('unified_api_key', '') or os.getenv('BILI_AI_API_KEY', '')
                base_url = api_cfg.get('unified_base_url', '') or os.getenv('BILI_AI_BASE_URL', '')
                model = api_cfg.get('model_name', model)
            except Exception:
                pass

        if not api_key or not base_url:
            log_line("[PPT] API未配置，无法生成")
            return

        cookies = None
        if COOKIE_FILE.exists():
            try:
                with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
            except Exception:
                pass

        async def run():
            from services.video_to_ppt import generate_ppt_from_bvid
            for theme in themes:
                try:
                    result = await generate_ppt_from_bvid(
                        bvid, api_key, base_url, model,
                        cookies_obj=cookies, theme=theme,
                        open_browser=False
                    )
                    if result['success']:
                        log_line(f"[PPT] {theme} 主题已生成: {result['html_path']}")
                    else:
                        log_line(f"[PPT] {theme} 主题失败: {result.get('error','')}")
                except Exception as e:
                    log_line(f"[PPT] {theme} 异常: {e}")

        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(run())

    threading.Thread(target=_do_generate, daemon=True).start()
    return jsonify(dict(ok=True, message=f'正在生成 {len(themes)} 个主题的PPT...'))

@app.route('/api/ppt/list')
def api_ppt_list():
    """列出已生成的HTML文件"""
    export_dir = BASE_DIR / "html_exports"
    files = []
    if export_dir.exists():
        for f in sorted(export_dir.glob("*.html"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
            files.append({
                'name': f.name,
                'size': f.stat().st_size,
                'time': datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'path': str(f.relative_to(BASE_DIR)),
            })
    return jsonify(dict(files=files))

@app.route('/api/ppt/themes')
def api_ppt_themes():
    """返回可用主题列表"""
    from services.video_to_ppt import THEMES
    return jsonify(dict(themes=[
        {'id': k, 'name': v['name'], 'preview_colors': [v['primary'], v['accent'], v['bg_start']]}
        for k, v in THEMES.items()
    ]))

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
    data = read_json(DATA_DIR / "web_personas.json")
    if not data or not data.get('items'):
        fallback = read_json(DATA_DIR / "personas.json")
        if fallback and isinstance(fallback, dict) and fallback.get('name'):
            data = dict(active=fallback.get('name','默认人格'), items={fallback['name']: fallback})
        else:
            # 从 config.json persona 段读取
            config = read_json(CONFIG_FILE, {})
            cfg_p = config.get('persona', {})
            active = cfg_p.get('active_persona', '') or cfg_p.get('prompt_name', '') or '默认人格'
            data = dict(active=active, items={})
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
BACKUP_DIR_EXPORT = get_backup_dir()

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
        # 🔒 API Key 脱敏处理
        if 'config.json' in export_data:
            export_data['config.json'] = sanitize_config_for_export(export_data['config.json'])
        if 'bilibili_cookies.json' in export_data:
            export_data['bilibili_cookies.json'] = sanitize_config_for_export(export_data['bilibili_cookies.json'])
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
        # 🔒 路径穿越防护：校验 filename 不包含 ../ 且在备份目录下
        if not is_safe_path(fname, BACKUP_DIR_EXPORT):
            log_line(f"⛔ 拒绝路径穿越尝试: {fname}")
            return jsonify(dict(ok=False, message='文件名包含非法路径')), 403
        fpath = BACKUP_DIR_EXPORT / fname
        if not fpath.exists():
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
# 🔒 服务端二次确认：需要前端先生成确认令牌
_factory_reset_pending_token = None

@app.route('/api/factory-reset/request', methods=['POST'])
def api_factory_reset_request():
    """请求恢复出厂设置，返回确认令牌（60秒有效）"""
    global _factory_reset_pending_token
    _factory_reset_pending_token = _uuid_module.uuid4().hex
    log_line("⚠ 收到恢复出厂设置请求，等待二次确认...")
    return jsonify(dict(ok=True, token=_factory_reset_pending_token,
                        message='请在60秒内输入确认令牌完成操作'))

@app.route('/api/factory-reset', methods=['POST'])
def api_factory_reset():
    global _factory_reset_pending_token
    try:
        body = request.get_json(silent=True) or {}
        confirm_token = body.get('confirm_token', '')
        # 🔒 必须有有效确认令牌
        if not _factory_reset_pending_token or confirm_token != _factory_reset_pending_token:
            _factory_reset_pending_token = None
            return jsonify(dict(ok=False, message='操作未确认，请先调用 /api/factory-reset/request 获取令牌')), 403
        _factory_reset_pending_token = None  # 一次性使用
        delete_kb = body.get('delete_kb', False)
        delete_web = body.get('delete_web', False)
        delete_backup = body.get('delete_backup', False)
        deleted = []
        for fname in ['config.json', 'bilibili_cookies.json', 'mood_state.json', 'personas.json',
                       'user_profiles.json', 'comment_log.json', 'bot_diary.json',
                       'self_evolution.json', 'agent_skill_log.json', 'bot_runtime_state.json',
                       'history_videos.json', 'interests.json', 'web_personas.json',
                       'web_persona.json', 'web_mood.json', 'web_user_profiles.json',
                       'web_action_log.json', 'web_prompt_templates.json', 'web_costs.json',
                       '.web_secret_key', 'search_history.json', 'private_message_log.json',
                       'private_context_db.json', 'standby_config.json', 'standby_stats.json',
                       'monitor_config.json', 'monitor_stats.json', 'reply_cache.json',
                       'processed_comments.json', 'psycho_profile.json', 'recommendation_log.json',
                       'action_log.json', 'content_aversions.json', 'owner_profile.json',
                       'kb_vector_index.json', 'interest_engine.json']:
            fp = DATA_DIR / fname
            if fp.exists():
                fp.unlink()
                deleted.append(fname)
        for fname in ['bot_memory.json', 'knowledge_metadata.json', 'bot_journal.md',
                       'learning_log.md', '.cipher_key']:
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
        if delete_web:
            web_dir = BASE_DIR / "web"
            if web_dir.exists():
                import shutil
                shutil.rmtree(web_dir, ignore_errors=True)
                deleted.append('web/')
        if delete_backup:
            backup_dir = get_backup_dir()
            if backup_dir.exists():
                import shutil
                shutil.rmtree(backup_dir, ignore_errors=True)
                deleted.append(f'{backup_dir}')
        # 清除日志
        global bot_output_lines
        with bot_output_lock:
            bot_output_lines.clear()
        log_line(f"恢复出厂设置完成，删除了 {len(deleted)} 个文件/目录" + ("（含知识库）" if delete_kb else "") + ("（含web/）" if delete_web else "") + ("（含备份）" if delete_backup else ""))
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
    """手动视频分析 — 多平台输入识别，B站完整分析，其他标注暂不支持。"""
    try:
        body = request.get_json(force=True)
        raw = (body.get('bvid') or body.get('url') or '').strip()
        platform = (body.get('platform') or 'auto').strip().lower()
        if not raw:
            return jsonify(dict(ok=False, message='请输入视频链接 / BV号')), 400
        from services.platform_adapter import (
            SUPPORTED_PLATFORMS,
            PLATFORM_LABELS,
            normalize_video_input,
        )
        norm = normalize_video_input(raw)
        if platform not in ('auto', ''):
            norm = dict(norm)
            norm['platform'] = platform
            norm['ok'] = norm['platform'] in SUPPORTED_PLATFORMS
        plat = norm.get('platform')
        if plat != 'bilibili':
            label = PLATFORM_LABELS.get(plat, plat)
            result = dict(norm)
            result['ok'] = False
            result['message'] = f'{label} 已识别，但当前阶段暂不支持分析（仅 B站可用）'
            return jsonify(result), 400
        bvid = norm.get('video_id') or raw
        mode = (body.get('mode') or '').strip()
        intent = (body.get('intent') or '').strip()
        _mode_map = {"1": "subtitle_only", "2": "asr_only", "3": "vision_only",
                     "4": "subtitle+asr", "5": "subtitle+vision", "6": "asr+vision", "7": "all"}
        force_mode = _mode_map.get(mode, None)  # None = 默认智能流程
        _mode_label = {'subtitle_only': '仅字幕', 'asr_only': '仅ASR', 'vision_only': '仅视觉',
                       'subtitle+asr': '字幕+ASR', 'subtitle+vision': '字幕+视觉',
                       'asr+vision': 'ASR+视觉', 'all': '全部', None: '智能流程'}.get(force_mode)
        log_line(f"触发 B站视频分析: {bvid} (模式={_mode_label}, 意图={'有' if intent else '无'})")

        def _run_analysis():
            try:
                sys.path.insert(0, str(BASE_DIR))
                import asyncio as _asyncio
                from brain.video_analysis import analyze_bilibili_video_input
                loop = _asyncio.new_event_loop()
                _asyncio.set_event_loop(loop)
                ok, msg = loop.run_until_complete(
                    analyze_bilibili_video_input(bvid, force_mode=force_mode, intent=intent))
                log_line(f"[分析] {'完成' if ok else '失败'}: {msg}")
            except Exception as e:
                log_line(f"[分析] 失败: {e}")

        threading.Thread(target=_run_analysis, daemon=True).start()
        result = dict(norm)
        result['ok'] = True
        result['message'] = f'已触发 B站视频分析: {bvid}（{_mode_label}）'
        return jsonify(result)
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/mindmap', methods=['POST'])
def api_action_mindmap():
    """思维导图导出 — 单文件或整个知识库 → 可交互 HTML（复用 services.mindmap_export）。"""
    try:
        body = request.get_json(force=True)
        mode = (body.get('mode') or 'single').strip().lower()
        rel = (body.get('file') or '').strip()
        from services.knowledge_tutor import KNOWLEDGE_BASE_DIR
        from services.mindmap_export import export_mindmap
        cfg = read_json(CONFIG_FILE, {})
        if mode == 'library':
            md_files = sorted(KNOWLEDGE_BASE_DIR.rglob('*.md'))
            if not md_files:
                return jsonify(dict(ok=False, message='知识库为空，无法导出')), 400
            ok_cnt = 0
            out = []
            for p in md_files:
                try:
                    o = export_mindmap(p, cfg=cfg)
                    ok_cnt += 1
                    out.append(o)
                except Exception as e:
                    out.append({'error': str(e), 'file': str(p)})
            return jsonify(dict(ok=True, message=f'批量导出完成：成功 {ok_cnt}/{len(md_files)}',
                                mode='library', files=out))
        # single
        if not rel:
            return jsonify(dict(ok=False, message='请选择知识文件')), 400
        target = (KNOWLEDGE_BASE_DIR / rel).resolve()
        kb_root = KNOWLEDGE_BASE_DIR.resolve()
        if target != kb_root and kb_root not in target.parents:
            return jsonify(dict(ok=False, message='非法路径')), 400
        if not target.exists():
            return jsonify(dict(ok=False, message='文件不存在')), 400
        out_path = export_mindmap(target, cfg=cfg)
        html = Path(out_path).read_text(encoding='utf-8', errors='replace')
        return jsonify(dict(ok=True, message='思维导图已生成', mode='single',
                            path=out_path, html=html))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/toggle-flag', methods=['POST'])
def api_action_toggle_flag():
    """通用开关：封面分析 / 快速模式 / 安静模式 / ASR（写入 config.json，并尽力热重载本进程全局）。"""
    try:
        body = request.get_json(force=True)
        key = (body.get('key') or '').strip()
        allowed = {
            'cover_enabled': ('vision', 'cover_enabled', 'VISION_COVER_ENABLED'),
            'quick_mode': ('speed', 'no_human_delay', 'NO_HUMAN_DELAY'),
            'quiet_mode': ('system', 'quiet_mode', 'QUIET_MODE'),
            'asr_enabled': ('asr', 'enabled', 'ASR_ENABLED'),
        }
        if key not in allowed:
            return jsonify(dict(ok=False, message='未知开关')), 400
        section, field, gname = allowed[key]
        config = read_json(CONFIG_FILE, {})
        sec = config.setdefault(section, {})
        new_val = not bool(sec.get(field, False))
        sec[field] = new_val
        write_json(CONFIG_FILE, config)
        try:
            import cli.app as _app
            setattr(_app, gname, new_val)
        except Exception:
            pass
        label = {'cover_enabled': '封面分析', 'quick_mode': '快速模式',
                 'quiet_mode': '安静模式', 'asr_enabled': 'ASR语音识别'}[key]
        return jsonify(dict(ok=True, key=key, value=new_val,
                            message=f'{label}已{"开启" if new_val else "关闭"}'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/flags')
def api_action_flags():
    """读取快捷开关当前状态（封面分析 / 快速模式 / 安静模式 / ASR）。"""
    try:
        config = read_json(CONFIG_FILE, {})
        return jsonify(dict(
            cover_enabled=bool(config.get('vision', {}).get('cover_enabled', False)),
            quick_mode=bool(config.get('speed', {}).get('no_human_delay', False)),
            quiet_mode=bool(config.get('system', {}).get('quiet_mode', False)),
            asr_enabled=bool(config.get('asr', {}).get('enabled', False)),
        ))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


# ─────────────────────────────────────────────────────────────────────────────
# 长任务机制（UP学习 / 视频转网页 / 出题 / 深入了解 都是耗时任务，前端轮询）
# ─────────────────────────────────────────────────────────────────────────────
import asyncio as _asyncio
import threading
import uuid as _uuid
import re as _re
import json as _json
from datetime import datetime as _dt
from flask import send_file

TASKS = {}  # task_id -> {status, message, result, error}


def _run_coro(coro):
    loop = _asyncio.new_event_loop()
    try:
        _asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mode_map():
    return {"1": "subtitle_only", "2": "asr_only", "3": "vision_only",
            "4": "subtitle+asr", "5": "subtitle+vision", "6": "asr+vision", "7": "all"}


# ── UP主搜索 / 视频列表 / 批量学习 ──
@app.route('/api/action/up-search', methods=['POST'])
def api_action_up_search():
    """搜索UP主（按名字/UID）。"""
    try:
        body = request.get_json(force=True)
        q = (body.get('query') or '').strip()
        if not q:
            return jsonify(dict(ok=False, message='请输入UP主名字或UID')), 400
        try:
            uid_candidate = int(q)
            return jsonify(dict(ok=True, ups=[dict(uid=uid_candidate, name=q, sign='', fans=0, is_uid=True)]))
        except ValueError:
            pass
        from bilibili_api import search as bili_search
        data = _run_coro(bili_search.search_by_type(
            q, search_type=bili_search.SearchObjectType.USER, page=1))
        items = (data or {}).get('result') or []
        out = []
        for u in items[:10]:
            out.append(dict(uid=int(u.get('mid') or u.get('uid', 0) or 0),
                            name=u.get('uname') or u.get('name', ''),
                            sign=(u.get('usign') or u.get('sign', ''))[:40],
                            fans=u.get('fans', 0)))
        return jsonify(dict(ok=True, ups=out))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/up-videos', methods=['POST'])
def api_action_up_videos():
    """获取UP主投稿视频列表。"""
    try:
        body = request.get_json(force=True)
        uid = int(body.get('uid') or 0)
        limit = int(body.get('limit') or 20)
        if not uid:
            return jsonify(dict(ok=False, message='缺少 uid')), 400
        sys.path.insert(0, str(BASE_DIR))
        from brain.agent_brain import AgentBrain
        brain = AgentBrain()
        brain.bili._load_credential()
        info = _run_coro(brain.bili.get_up_info(uid)) or {}
        vids = _run_coro(brain.bili.get_up_videos(uid, limit=min(limit, 50))) or []
        return jsonify(dict(ok=True, up=info, videos=vids))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/up-learn', methods=['POST'])
def api_action_up_learn():
    """批量学习选中的UP主视频（后台任务，逐个调用视频分析）。"""
    try:
        body = request.get_json(force=True)
        bvids = body.get('bvids') or []
        mode = (body.get('mode') or '').strip()
        intent = (body.get('intent') or '').strip()
        if not bvids:
            return jsonify(dict(ok=False, message='请至少选择一个视频')), 400
        force_mode = _mode_map().get(mode)
        tid = _uuid.uuid4().hex
        TASKS[tid] = dict(status='running', message=f'准备学习 {len(bvids)} 个视频...', result=None, error=None)

        def _work():
            sys.path.insert(0, str(BASE_DIR))
            from brain.video_analysis import analyze_bilibili_video_input
            ok_cnt = 0
            for i, bvid in enumerate(bvids, 1):
                try:
                    TASKS[tid]['message'] = f'[{i}/{len(bvids)}] 分析中: {bvid}'
                    loop = _asyncio.new_event_loop()
                    _asyncio.set_event_loop(loop)
                    ok, msg = loop.run_until_complete(
                        analyze_bilibili_video_input(bvid, force_mode=force_mode, intent=intent))
                    loop.close()
                    if ok:
                        ok_cnt += 1
                    TASKS[tid]['message'] = f'[{i}/{len(bvids)}] {"✓ 完成" if ok else "✗ 失败"}: {msg}'
                except Exception as e:
                    TASKS[tid]['message'] = f'[{i}/{len(bvids)}] 异常: {e}'
            TASKS[tid]['status'] = 'done'
            TASKS[tid]['result'] = dict(ok=ok_cnt, total=len(bvids))

        threading.Thread(target=_work, daemon=True).start()
        return jsonify(dict(ok=True, task_id=tid, message=f'已启动学习 {len(bvids)} 个视频'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


# ── 视频 → 网页（多风格）/ 导出 ──
@app.route('/api/action/video2web', methods=['POST'])
def api_action_video2web():
    """生成视频学习网页（幻灯片风格 HTML）。"""
    try:
        body = request.get_json(force=True)
        raw = (body.get('bvid') or '').strip()
        theme = (body.get('theme') or 'auto').strip()
        if not raw:
            return jsonify(dict(ok=False, message='请输入视频 BV号/链接')), 400
        m = _re.search(r'(BV[0-9A-Za-z]{10})', raw)
        bvid = m.group(1) if m else raw
        tid = _uuid.uuid4().hex
        TASKS[tid] = dict(status='running', message='AI 正在生成网页...', result=None, error=None)

        def _work():
            try:
                cfg = read_json(CONFIG_FILE, {})
                api_key = cfg.get('api', {}).get('unified_api_key', '') or os.getenv('BILI_AI_API_KEY', '')
                base_url = cfg.get('api', {}).get('unified_base_url', '') or os.getenv('BILI_AI_BASE_URL', '')
                model = cfg.get('api', {}).get('model_brain', '') or cfg.get('api', {}).get('model', '')
                cookies = None
                if COOKIE_FILE.exists():
                    try:
                        cookies = _json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
                    except Exception:
                        cookies = None
                sys.path.insert(0, str(BASE_DIR))
                from services.video_to_ppt import generate_ppt_from_bvid
                res = _run_coro(generate_ppt_from_bvid(
                    bvid, api_key=api_key, base_url=base_url, model=model,
                    cookies_obj=cookies, theme=theme, open_browser=False, auto_save=True))
                if res.get('success'):
                    TASKS[tid]['status'] = 'done'
                    TASKS[tid]['result'] = dict(html=res.get('html_content', ''),
                                                path=res.get('html_path', ''),
                                                title=res.get('title', ''))
                else:
                    TASKS[tid]['status'] = 'error'
                    TASKS[tid]['error'] = res.get('error', '生成失败')
            except Exception as e:
                TASKS[tid]['status'] = 'error'
                TASKS[tid]['error'] = str(e)

        threading.Thread(target=_work, daemon=True).start()
        return jsonify(dict(ok=True, task_id=tid, message='已启动网页生成'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


def _html_to_plain_text(html):
    t = _re.sub(r'<script.*?</script>', '', html, flags=_re.S | _re.I)
    t = _re.sub(r'<style.*?</style>', '', t, flags=_re.S | _re.I)
    t = _re.sub(r'<[^>]+>', ' ', t)
    for a, b in [('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"')]:
        t = t.replace(a, b)
    t = _re.sub(r'[ \t]+', ' ', t)
    t = _re.sub(r'\n\s*\n+', '\n\n', t)
    return t.strip()


@app.route('/api/action/export-docx', methods=['POST'])
def api_action_export_docx():
    """把生成的网页 HTML 导出为 Word（提取正文）。"""
    try:
        body = request.get_json(force=True)
        html = body.get('html', '')
        title = (body.get('title') or '视频学习页').strip() or '视频学习页'
        from docx import Document
        doc = Document()
        doc.add_heading(title, level=0)
        for line in _html_to_plain_text(html).split('\n'):
            line = line.strip()
            if not line:
                doc.add_paragraph('')
            else:
                doc.add_paragraph(line)
        out = DATA_DIR / 'DocumentExports'
        out.mkdir(parents=True, exist_ok=True)
        fn = out / (_re.sub(r'[^\w\-.\u4e00-\u9fff]+', '_', title)[:60] + '.docx')
        doc.save(str(fn))
        return send_file(str(fn), as_attachment=True, download_name=fn.name)
    except ImportError:
        return jsonify(dict(ok=False, message='缺少 python-docx，请先 pip install python-docx')), 500
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/export-pdf', methods=['POST'])
def api_action_export_pdf():
    """把生成的网页 HTML 导出为 PDF（提取正文）。"""
    try:
        body = request.get_json(force=True)
        html = body.get('html', '')
        title = (body.get('title') or '视频学习页').strip() or '视频学习页'
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
        out = DATA_DIR / 'DocumentExports'
        out.mkdir(parents=True, exist_ok=True)
        fn = out / (_re.sub(r'[^\w\-.\u4e00-\u9fff]+', '_', title)[:60] + '.pdf')
        c = canvas.Canvas(str(fn), pagesize=A4)
        w, h = A4
        # 尽量用中文字体
        font_path = None
        for cand in ['C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf',
                     'C:/Windows/Fonts/simsun.ttc']:
            if os.path.exists(cand):
                font_path = cand
                break
        if font_path:
            try:
                pdfmetrics.registerFont(TTFont('cn', font_path))
                c.setFont('cn', 11)
            except Exception:
                c.setFont('Helvetica', 11)
        else:
            c.setFont('Helvetica', 11)
        y = h - 50
        c.drawString(40, y, title[:60])
        y -= 24
        for line in _html_to_plain_text(html).split('\n'):
            line = line.strip()
            if not line:
                y -= 8
                continue
            # 简单换行
            while len(line) > 0:
                chunk = line[:48]
                line = line[48:]
                if y < 50:
                    c.showPage()
                    y = h - 50
                c.drawString(40, y, chunk)
                y -= 16
            y -= 4
        c.save()
        return send_file(str(fn), as_attachment=True, download_name=fn.name)
    except ImportError:
        return jsonify(dict(ok=False, message='缺少 reportlab，请先 pip install reportlab')), 500
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


# ── 学习工具：出题 / 深入了解 ──
@app.route('/api/action/quiz', methods=['POST'])
def api_action_quiz():
    """AI 出题考试。"""
    try:
        body = request.get_json(force=True)
        source_type = body.get('source_type', 'video')
        tid = _uuid.uuid4().hex
        TASKS[tid] = dict(status='running', message='AI 正在出题...', result=None, error=None)

        def _work():
            try:
                sys.path.insert(0, str(BASE_DIR))
                from services.quiz_generator import generate_quiz
                kw = dict(
                    source_type=source_type,
                    bvid=body.get('bvid', ''),
                    kb_file_path=body.get('kb_file_path', ''),
                    kb_file_content=body.get('kb_file_content', ''),
                    question_count=int(body.get('question_count') or 5),
                    difficulty=body.get('difficulty', 'medium'),
                    question_type=body.get('question_type', 'mixed'),
                    style=body.get('style', 'standard'),
                    custom_prompt=body.get('custom_prompt', ''),
                )
                res = _run_coro(generate_quiz(**kw))
                if res.get('success'):
                    TASKS[tid]['status'] = 'done'
                    TASKS[tid]['result'] = dict(content=res.get('quiz_content', ''),
                                                path=res.get('saved_path', ''),
                                                title=res.get('source_title', ''))
                else:
                    TASKS[tid]['status'] = 'error'
                    TASKS[tid]['error'] = res.get('error', '出题失败')
            except Exception as e:
                TASKS[tid]['status'] = 'error'
                TASKS[tid]['error'] = str(e)

        threading.Thread(target=_work, daemon=True).start()
        return jsonify(dict(ok=True, task_id=tid, message='已启动出题'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/deep-dive', methods=['POST'])
def api_action_deep_dive():
    """AI 深入了解 / 深度学习。"""
    try:
        body = request.get_json(force=True)
        topic = (body.get('topic') or '').strip()
        if not topic:
            return jsonify(dict(ok=False, message='请输入想了解的主题')), 400
        tid = _uuid.uuid4().hex
        TASKS[tid] = dict(status='running', message='AI 正在深入学习...', result=None, error=None)

        def _work():
            try:
                sys.path.insert(0, str(BASE_DIR))
                from services.deep_dive import run_deep_dive
                res = _run_coro(run_deep_dive(
                    topic=topic, mode=body.get('mode', 'search'),
                    video_count=int(body.get('video_count') or 10),
                    additional_context=body.get('context', '')))
                if res.get('success'):
                    TASKS[tid]['status'] = 'done'
                    TASKS[tid]['result'] = dict(report=res.get('report', ''),
                                                path=res.get('saved_path', ''))
                else:
                    TASKS[tid]['status'] = 'error'
                    TASKS[tid]['error'] = res.get('error', '深入了解失败')
            except Exception as e:
                TASKS[tid]['status'] = 'error'
                TASKS[tid]['error'] = str(e)

        threading.Thread(target=_work, daemon=True).start()
        return jsonify(dict(ok=True, task_id=tid, message='已启动深入了解'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/task')
def api_action_task():
    """轮询长任务状态。"""
    tid = request.args.get('id', '')
    t = TASKS.get(tid)
    if not t:
        return jsonify(dict(status='notfound'))
    return jsonify(t)


# ── 自定义知识管理 CRUD ──
def _custom_paths():
    try:
        from services.knowledge_tutor import KNOWLEDGE_BASE_DIR
    except Exception:
        from pathlib import Path as _P
        KNOWLEDGE_BASE_DIR = _P(BASE_DIR) / 'KnowledgeBase'
    return KNOWLEDGE_BASE_DIR / '自定义知识', BASE_DIR / 'knowledge_metadata.json'


def _custom_init():
    cdir, _ = _custom_paths()
    cdir.mkdir(parents=True, exist_ok=True)
    return cdir


def _custom_sanitize(name):
    return _re.sub(r'[\\/:*?"<>|\n\r]+', '_', name).strip()[:80] or 'untitled'


def _custom_meta():
    _, mpath = _custom_paths()
    if mpath.exists():
        try:
            meta = _json.loads(mpath.read_text(encoding='utf-8'))
        except Exception:
            meta = {}
    else:
        meta = {}
    meta.setdefault('file_index', {})
    meta.setdefault('categories', {})
    meta['file_index'].setdefault('自定义知识', [])
    meta['categories'].setdefault('自定义知识', {})
    return meta, mpath


def _custom_find(bvid, title):
    cdir = _custom_init()
    fn = f"[{bvid}] - {_custom_sanitize(title)}.md"
    fp = cdir / fn
    if not fp.exists():
        for f in cdir.iterdir():
            if f.is_file() and bvid in f.name:
                return f
        return None
    return fp


@app.route('/api/kb/custom-list')
def api_kb_custom_list():
    try:
        cdir = _custom_init()
        meta, _ = _custom_meta()
        out = []
        for e in meta['file_index'].get('自定义知识', []):
            bvid = e.get('bvid', '')
            title = e.get('title', '无标题')
            fp = _custom_find(bvid, title)
            if not fp:
                continue
            out.append(dict(bvid=bvid, title=title, added=e.get('added', ''),
                            category=e.get('category', '自定义知识'),
                            size_kb=round(fp.stat().st_size / 1024, 1)))
        return jsonify(dict(ok=True, entries=out))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/kb/custom-get', methods=['POST'])
def api_kb_custom_get():
    try:
        body = request.get_json(force=True)
        fp = _custom_find(body.get('bvid', ''), body.get('title', ''))
        if not fp:
            return jsonify(dict(ok=False, message='文件不存在')), 404
        return jsonify(dict(ok=True, content=fp.read_text(encoding='utf-8', errors='replace'),
                            filename=fp.name))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/kb/custom-add', methods=['POST'])
def api_kb_custom_add():
    try:
        body = request.get_json(force=True)
        title = (body.get('title') or '').strip()
        content = (body.get('content') or '').strip()
        category = (body.get('category') or '自定义知识').strip() or '自定义知识'
        if not title:
            return jsonify(dict(ok=False, message='标题不能为空')), 400
        if len(content) < 10:
            return jsonify(dict(ok=False, message='内容至少 10 字')), 400
        cdir = _custom_init()
        import hashlib as _hl
        bvid = 'custom_' + _hl.md5(title.encode()).hexdigest()[:8]
        now = _dt.now().isoformat()
        fp = cdir / f"[{bvid}] - {_custom_sanitize(title)}.md"
        full = (f"# 📝 {title}\n\n【信息】\n- 标题: {title}\n- 分类: {category}\n"
                f"- 创建时间: {now}\n\n---\n\n## 内容\n\n{content}\n")
        fp.write_text(full, encoding='utf-8')
        meta, mpath = _custom_meta()
        lst = [x for x in meta['file_index']['自定义知识'] if x.get('bvid') != bvid]
        lst.append(dict(bvid=bvid, title=title, category=category, added=now))
        meta['file_index']['自定义知识'] = lst
        meta['last_updated'] = now
        mpath.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify(dict(ok=True, bvid=bvid, title=title, message='已新增自定义知识'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/kb/custom-update', methods=['POST'])
def api_kb_custom_update():
    try:
        body = request.get_json(force=True)
        bvid = body.get('bvid', '')
        title = (body.get('title') or '').strip()
        content = (body.get('content') or '').strip()
        category = (body.get('category') or '自定义知识').strip() or '自定义知识'
        if not bvid or not title:
            return jsonify(dict(ok=False, message='缺少参数')), 400
        fp = _custom_find(bvid, title)
        if not fp:
            return jsonify(dict(ok=False, message='文件不存在')), 404
        now = _dt.now().isoformat()
        full = (f"# 📝 {title}\n\n【信息】\n- 标题: {title}\n- 分类: {category}\n"
                f"- 更新时间: {now}\n\n---\n\n## 内容\n\n{content}\n")
        fp.write_text(full, encoding='utf-8')
        meta, mpath = _custom_meta()
        lst = [x for x in meta['file_index']['自定义知识'] if x.get('bvid') != bvid]
        lst.append(dict(bvid=bvid, title=title, category=category, added=now))
        meta['file_index']['自定义知识'] = lst
        meta['last_updated'] = now
        mpath.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify(dict(ok=True, message='已更新'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/kb/custom-delete', methods=['POST'])
def api_kb_custom_delete():
    try:
        body = request.get_json(force=True)
        bvid = body.get('bvid', '')
        fp = _custom_find(bvid, body.get('title', ''))
        if fp and fp.exists():
            fp.unlink()
        meta, mpath = _custom_meta()
        meta['file_index']['自定义知识'] = [
            x for x in meta['file_index']['自定义知识'] if x.get('bvid') != bvid]
        meta['last_updated'] = _dt.now().isoformat()
        mpath.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify(dict(ok=True, message='已删除'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/kb/custom-search', methods=['POST'])
def api_kb_custom_search():
    try:
        body = request.get_json(force=True)
        q = (body.get('q') or '').strip().lower()
        if not q:
            return api_kb_custom_list()
        cdir = _custom_init()
        out = []
        for f in cdir.glob('*.md'):
            txt = f.read_text(encoding='utf-8', errors='replace')
            if q in txt.lower():
                mh = _re.search(r'^#\s+(.*)$', txt, _re.M)
                out.append(dict(filename=f.name, title=mh.group(1) if mh else f.name,
                                size_kb=round(f.stat().st_size / 1024, 1)))
        return jsonify(dict(ok=True, entries=out))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/platform/probe', methods=['POST'])
def api_platform_probe():
    """多平台视频链接识别与归一化（借鉴 BiliNote 平台识别机制）。"""
    try:
        body = request.get_json(force=True)
        url = (body.get('url') or body.get('bvid') or '').strip()
        if not url:
            return jsonify(dict(ok=False, message='请输入视频链接 / BV号')), 400
        from services.platform_adapter import fetch_platform_metadata
        cfg = read_json(CONFIG_FILE, {})
        result = fetch_platform_metadata(url, cfg=cfg)
        return jsonify(result), (200 if result.get('ok') else 400)
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

# ── 知识辅导 (v2.0.3) ──
@app.route('/api/kb/list-files')
def api_kb_list_files():
    """列出 KnowledgeBase 下所有 .md 文件"""
    try:
        from services.knowledge_tutor import scan_md_files
        files = scan_md_files()
        return jsonify(dict(ok=True, files=files, total=len(files)))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/kb/read-file', methods=['POST'])
def api_kb_read_file():
    """读取指定 .md 文件的内容（支持单文件或多文件）"""
    try:
        body = request.get_json(force=True)
        rel_paths = body.get('rel_paths') or body.get('rel_path')
        if isinstance(rel_paths, str):
            rel_paths = [rel_paths]
        if not rel_paths:
            return jsonify(dict(ok=False, message='请提供文件路径')), 400
        from services.knowledge_tutor import read_md_file, KNOWLEDGE_BASE_DIR
        parts = []
        total_size = 0
        for rp in rel_paths:
            full_path = KNOWLEDGE_BASE_DIR / rp.strip()
            if not full_path.exists():
                return jsonify(dict(ok=False, message=f'文件不存在: {rp}')), 404
            c = read_md_file(full_path)
            total_size += len(c)
            fname = os.path.basename(str(full_path))
            parts.append(f'=== {fname} ===\n{c}')
        combined = '\n\n'.join(parts)
        return jsonify(dict(ok=True, content=combined, paths=[str(KNOWLEDGE_BASE_DIR / rp.strip()) for rp in rel_paths], total_size=total_size, file_count=len(rel_paths)))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/kb/tutor-chat', methods=['POST'])
def api_kb_tutor_chat():
    """知识辅导：AI 对话（支持单文件或多文件）"""
    try:
        body = request.get_json(force=True)
        rel_paths = body.get('rel_paths') or body.get('rel_path')
        if isinstance(rel_paths, str):
            rel_paths = [rel_paths]
        message = (body.get('message') or '').strip()
        history = body.get('history') or []
        mode = (body.get('mode') or 'chat').strip()  # chat / rewrite / html
        style = (body.get('style') or 'dark').strip()

        if not rel_paths:
            return jsonify(dict(ok=False, message='请提供文件路径')), 400
        if not message and mode == 'chat':
            return jsonify(dict(ok=False, message='请输入问题')), 400

        from services.knowledge_tutor import KNOWLEDGE_BASE_DIR, get_tutor
        full_paths = []
        for rp in rel_paths:
            fp = KNOWLEDGE_BASE_DIR / rp.strip()
            if not fp.exists():
                return jsonify(dict(ok=False, message=f'文件不存在: {rp}')), 404
            full_paths.append(str(fp))

        tutor = get_tutor()
        if not tutor.is_available():
            return jsonify(dict(ok=False, message='AI 接口不可用，请先配置 API Key')), 503

        # 在后台线程中运行异步任务
        import threading
        result = {}
        error = None

        def _run():
            nonlocal result, error
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                if mode == 'rewrite':
                    # rewrite 只支持单文件
                    summary, new_content = loop.run_until_complete(
                        tutor.rewrite_file(full_paths[0], message)
                    )
                    result = dict(mode='rewrite', summary=summary, new_content=new_content)
                elif mode == 'html':
                    # html 支持多文件拼接
                    if len(full_paths) == 1:
                        html = loop.run_until_complete(
                            tutor.generate_html(full_paths[0], style)
                        )
                    else:
                        html = loop.run_until_complete(
                            tutor.generate_html(full_paths, style)
                        )
                    result = dict(mode='html', html=html, style=style)
                else:
                    # chat 支持多文件
                    if len(full_paths) == 1:
                        reply = loop.run_until_complete(
                            tutor.chat_about_file(full_paths[0], message, history)
                        )
                    else:
                        reply = loop.run_until_complete(
                            tutor.chat_about_file(full_paths, message, history)
                        )
                    result = dict(mode='chat', reply=reply)
            except Exception as e:
                error = str(e)
            finally:
                if loop is not None and not loop.is_closed():
                    loop.close()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=180)  # 最多等3分钟

        if error:
            return jsonify(dict(ok=False, message=error)), 500
        return jsonify(dict(ok=True, **result))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/kb/tutor-save', methods=['POST'])
def api_kb_tutor_save():
    """保存改写后的知识文件"""
    try:
        body = request.get_json(force=True)
        rel_path = (body.get('rel_path') or '').strip()
        content = (body.get('content') or '').strip()
        if not rel_path or not content:
            return jsonify(dict(ok=False, message='请提供文件路径和内容')), 400
        from services.knowledge_tutor import write_md_file, KNOWLEDGE_BASE_DIR
        full_path = KNOWLEDGE_BASE_DIR / rel_path
        if not full_path.exists():
            return jsonify(dict(ok=False, message='文件不存在')), 404
        success = write_md_file(full_path, content)
        if success:
            return jsonify(dict(ok=True, message='文件已保存（原文件已备份）'))
        else:
            return jsonify(dict(ok=False, message='保存失败')), 500
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/kb/tutor-html-save', methods=['POST'])
def api_kb_tutor_html_save():
    """保存生成的 HTML 文件"""
    try:
        body = request.get_json(force=True)
        html = (body.get('html') or '').strip()
        title = (body.get('title') or 'knowledge').strip()
        if not html:
            return jsonify(dict(ok=False, message='HTML内容为空')), 400
        from services.knowledge_tutor import KNOWLEDGE_BASE_DIR
        import re as _re
        html_dir = KNOWLEDGE_BASE_DIR / ".html_exports"
        html_dir.mkdir(parents=True, exist_ok=True)
        safe_title = _re.sub(r'[\\/*?:"<>|]', '_', title)[:40]
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        html_path = html_dir / f"{safe_title}_{ts}.html"
        html_path.write_text(html, encoding='utf-8')
        return jsonify(dict(ok=True, path=str(html_path), message='HTML已保存'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

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
            video_interval_min=energy.get('video_interval_min', 1),
            video_interval_max=energy.get('video_interval_max', 5),
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


# ── 安全关键词 ──
@app.route('/api/behavior/safety')
def api_behavior_safety():
    config = read_json(CONFIG_FILE, {})
    safety = config.get('reply_safety', {})
    return jsonify(dict(
        enabled=safety.get('enabled', False),
        keywords=safety.get('blocked_keywords', []),
    ))


@app.route('/api/behavior/safety/toggle', methods=['POST'])
def api_behavior_safety_toggle():
    try:
        body = request.get_json(force=True)
        enabled = bool(body.get('enabled', True))
        config = read_json(CONFIG_FILE, {})
        safety = config.setdefault('reply_safety', {})
        safety['enabled'] = enabled
        write_json(CONFIG_FILE, config)
        msg = '关键词安全校验已开启' if enabled else '关键词安全校验已关闭'
        return jsonify(dict(ok=True, message=msg))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/behavior/safety/save', methods=['POST'])
def api_behavior_safety_save():
    try:
        body = request.get_json(force=True)
        keywords = body.get('keywords', [])
        config = read_json(CONFIG_FILE, {})
        safety = config.setdefault('reply_safety', {})
        safety['blocked_keywords'] = [str(k).strip() for k in keywords if str(k).strip()]
        write_json(CONFIG_FILE, config)
        return jsonify(dict(ok=True, message=f'已保存 {len(safety["blocked_keywords"])} 个关键词'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


# ── 免责声明 HTML 页面 ──
def _disclaimer_html():
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>免责声明 — B站 AI 管理系统</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#f7f7f7;color:#0d0d0d;display:flex;align-items:center;justify-content:center;min-height:100vh;-webkit-font-smoothing:antialiased}
.card{background:#fff;border:1px solid #e6e6e6;border-radius:16px;padding:40px 36px;max-width:480px;width:90%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.06)}
.card .icon{font-size:36px;margin-bottom:16px}
.card h2{color:#D14343;font-size:20px;font-weight:600;margin-bottom:8px;letter-spacing:-.3px}
.card .sub{font-size:13px;color:#999;margin-bottom:24px}
.card .lines{background:rgba(209,67,67,.04);border:1px solid rgba(209,67,67,.15);border-radius:10px;padding:18px 20px;margin-bottom:24px;font-size:14px;line-height:1.9;text-align:left;font-weight:400}
.card .lines .en{font-size:12px;color:#999;margin-top:8px;display:block}
.inp-row{display:flex;gap:10px}
.inp-row input{flex:1;background:#f7f7f7;border:1px solid #e6e6e6;border-radius:8px;padding:10px 14px;color:#0d0d0d;font-size:15px;outline:none;transition:border-color .2s;font-family:inherit}
.inp-row input:focus{border-color:#D97757;box-shadow:0 0 0 3px rgba(217,119,87,.1)}
.inp-row input.error{border-color:#D14343;animation:shake .4s}
.btn{background:#D14343;color:#fff;border:none;border-radius:8px;padding:10px 24px;font-size:14px;font-weight:500;cursor:pointer;transition:all .2s;font-family:inherit}
.btn:hover{background:#B53535;box-shadow:0 4px 12px rgba(209,67,67,.25)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.msg{margin-top:12px;font-size:13px;min-height:20px;font-weight:500}
.msg.err{color:#D14343}
.msg.ok{color:#2D8A4E}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-6px)}75%{transform:translateX(6px)}}
</style>
</head>
<body>
<div class="card">
<div class="icon">⚠</div>
<h2>免责声明 / DISCLAIMER</h2>
<p class="sub">请阅读并确认以下声明</p>
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
if(d.ok){msg.textContent='\u2713 已确认，跳转中...';msg.className='msg ok';setTimeout(function(){location.href='/'},600)}
else{msg.textContent='\u2717 请输入"我同意"';msg.className='msg err';btn.disabled=false;inp.classList.add('error');setTimeout(function(){inp.classList.remove('error')},400)}
})
.catch(function(){msg.textContent='请求失败，请重试';msg.className='msg err';btn.disabled=false})
}
</script>
</body>
</html>"""

# ── 首次设置页面（配置用户名和密码）──
def _setup_html():
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>首次设置 · 管理面板</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#f7f7f7;color:#0d0d0d;display:flex;align-items:center;justify-content:center;min-height:100vh;-webkit-font-smoothing:antialiased}
.card{background:#fff;border:1px solid #e6e6e6;border-radius:16px;padding:40px 36px;max-width:420px;width:90%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.06)}
.card .icon{font-size:36px;margin-bottom:16px}
.card h2{color:#0d0d0d;font-size:20px;font-weight:600;margin-bottom:6px;letter-spacing:-.3px}
.card .sub{font-size:13px;color:#999;margin-bottom:28px;line-height:1.6}
.fg{margin-bottom:16px;text-align:left}
.fg label{display:block;font-size:11px;font-weight:600;color:#999;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
.fg input{width:100%;background:#f7f7f7;border:1px solid #e6e6e6;border-radius:8px;padding:10px 14px;color:#0d0d0d;font-size:15px;outline:none;transition:border-color .2s;font-family:inherit}
.fg input:focus{border-color:#D97757;box-shadow:0 0 0 3px rgba(217,119,87,.1)}
.fg input.error{border-color:#D14343;animation:shake .4s}
.hint{font-size:11px;color:#999;margin-top:4px}
.btn{background:#D97757;color:#fff;border:none;border-radius:8px;padding:11px 24px;font-size:14px;font-weight:500;cursor:pointer;transition:all .2s;width:100%;margin-top:4px;font-family:inherit}
.btn:hover{background:#C56545;box-shadow:0 4px 12px rgba(217,119,87,.25)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.msg{margin-top:12px;font-size:13px;min-height:20px;font-weight:500}
.msg.err{color:#D14343}
.msg.ok{color:#2D8A4E}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-6px)}75%{transform:translateX(6px)}}
</style>
</head>
<body>
<div class="card">
<div class="icon">🔐</div>
<h2>首次设置</h2>
<p class="sub">欢迎使用 B站 AI 管理系统<br>请设置管理面板的用户名和密码</p>
<div class="fg"><label>用户名</label><input id="setupUser" type="text" placeholder="设置用户名" autocomplete="off" autofocus></div>
<div class="fg"><label>密码</label><input id="setupPass" type="password" placeholder="设置密码（至少4位）" autocomplete="off"></div>
<div class="fg"><label>确认密码</label><input id="setupPass2" type="password" placeholder="再次输入密码" autocomplete="off"></div>
<button class="btn" id="setupBtn" onclick="doSetup()">完成设置</button>
<div class="msg" id="msg"></div>
</div>
<script>
var inpU=document.getElementById('setupUser'),inpP=document.getElementById('setupPass'),inpP2=document.getElementById('setupPass2');
var btn=document.getElementById('setupBtn'),msg=document.getElementById('msg');
[inpU,inpP,inpP2].forEach(function(el){el.addEventListener('keydown',function(e){if(e.key==='Enter')doSetup()})});
async function doSetup(){
var u=inpU.value.trim(),p=inpP.value,p2=inpP2.value;
if(!u){msg.textContent='请输入用户名';msg.className='msg err';inpU.classList.add('error');setTimeout(function(){inpU.classList.remove('error')},400);return}
if(u.length<2){msg.textContent='用户名至少2个字符';msg.className='msg err';return}
if(p.length<4){msg.textContent='密码至少4位';msg.className='msg err';inpP.classList.add('error');setTimeout(function(){inpP.classList.remove('error')},400);return}
if(p!==p2){msg.textContent='两次输入的密码不一致';msg.className='msg err';inpP2.classList.add('error');setTimeout(function(){inpP2.classList.remove('error')},400);return}
btn.disabled=true;btn.textContent='正在保存...';
try{
var r=await fetch('/api/auth/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
var d=await r.json();
if(d.ok){msg.textContent='\u2713 设置成功！正在跳转...';msg.className='msg ok';setTimeout(function(){location.href='/login'},800)}
else{msg.textContent='\u2717 '+d.message;msg.className='msg err';btn.disabled=false;btn.textContent='完成设置'}
}catch(e){msg.textContent='请求失败，请重试';msg.className='msg err';btn.disabled=false;btn.textContent='完成设置'}
}
</script>
</body>
</html>"""

# ── 登录页面 ──
def _login_html():
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>登录 · 管理面板</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#f7f7f7;color:#0d0d0d;display:flex;align-items:center;justify-content:center;min-height:100vh;-webkit-font-smoothing:antialiased}
.card{background:#fff;border:1px solid #e6e6e6;border-radius:16px;padding:40px 36px;max-width:400px;width:90%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.06)}
.card .icon{font-size:36px;margin-bottom:16px}
.card h2{color:#0d0d0d;font-size:20px;font-weight:600;margin-bottom:6px;letter-spacing:-.3px}
.card .sub{font-size:13px;color:#999;margin-bottom:28px}
.fg{margin-bottom:16px;text-align:left}
.fg label{display:block;font-size:11px;font-weight:600;color:#999;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
.fg input{width:100%;background:#f7f7f7;border:1px solid #e6e6e6;border-radius:8px;padding:10px 14px;color:#0d0d0d;font-size:15px;outline:none;transition:border-color .2s;font-family:inherit}
.fg input:focus{border-color:#D97757;box-shadow:0 0 0 3px rgba(217,119,87,.1)}
.fg input.error{border-color:#D14343;animation:shake .4s}
.btn{background:#D97757;color:#fff;border:none;border-radius:8px;padding:11px 24px;font-size:14px;font-weight:500;cursor:pointer;transition:all .2s;width:100%;margin-top:4px;font-family:inherit}
.btn:hover{background:#C56545;box-shadow:0 4px 12px rgba(217,119,87,.25)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.msg{margin-top:12px;font-size:13px;min-height:20px;font-weight:500}
.msg.err{color:#D14343}
.msg.ok{color:#2D8A4E}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-6px)}75%{transform:translateX(6px)}}
</style>
</head>
<body>
<div class="card">
<div class="icon">⚡</div>
<h2>管理面板登录</h2>
<p class="sub">B站 AI 管理系统</p>
<div class="fg"><label>用户名</label><input id="loginUser" type="text" placeholder="输入用户名" autocomplete="off" autofocus></div>
<div class="fg"><label>密码</label><input id="loginPass" type="password" placeholder="输入密码" autocomplete="off"></div>
<button class="btn" id="loginBtn" onclick="doLogin()">登录</button>
<div class="msg" id="msg"></div>
</div>
<script>
var inpU=document.getElementById('loginUser'),inpP=document.getElementById('loginPass');
var btn=document.getElementById('loginBtn'),msg=document.getElementById('msg');
[inpU,inpP].forEach(function(el){el.addEventListener('keydown',function(e){if(e.key==='Enter')doLogin()})});
async function doLogin(){
var u=inpU.value.trim(),p=inpP.value;
if(!u||!p){msg.textContent='请输入用户名和密码';msg.className='msg err';return}
btn.disabled=true;btn.textContent='验证中...';
try{
var r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
var d=await r.json();
if(d.ok){msg.textContent='\u2713 登录成功，跳转中...';msg.className='msg ok';setTimeout(function(){location.href='/'},500)}
else{msg.textContent='\u2717 '+d.message;msg.className='msg err';btn.disabled=false;btn.textContent='登录';inpP.value='';inpP.classList.add('error');setTimeout(function(){inpP.classList.remove('error')},400)}
}catch(e){msg.textContent='请求失败，请重试';msg.className='msg err';btn.disabled=false;btn.textContent='登录'}
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

# ── 首次设置页面 ──
@app.route('/setup')
def setup_page():
    return _setup_html(), 200, {'Content-Type': 'text/html; charset=utf-8'}

# ── 登录页面 ──
@app.route('/login')
def login_page():
    return _login_html(), 200, {'Content-Type': 'text/html; charset=utf-8'}

# ── 认证 API ──
@app.route('/api/auth/setup', methods=['POST'])
def api_auth_setup():
    """首次设置：保存用户名和密码到 config.json"""
    data = request.get_json(force=True) if request.is_json else {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '')
    if len(username) < 2:
        return jsonify(dict(ok=False, message='用户名至少2个字符'))
    if len(password) < 4:
        return jsonify(dict(ok=False, message='密码至少4位'))
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.setdefault('web', {})
    web_cfg['username'] = username
    web_cfg['password'] = _hash_password(password)
    if write_json(CONFIG_FILE, config):
        # 设置成功后自动登录
        session['disclaimer_agreed'] = True
        session['panel_authenticated'] = True
        log_line(f"面板首次设置完成，用户: {username}")
        return jsonify(dict(ok=True, message='设置成功'))
    return jsonify(dict(ok=False, message='保存配置失败'))

@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """登录验证"""
    data = request.get_json(force=True) if request.is_json else {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.get('web', {})
    saved_user = web_cfg.get('username', '')
    saved_pass = web_cfg.get('password', '')
    if not saved_user or not saved_pass:
        return jsonify(dict(ok=False, message='面板尚未设置，请先完成首次配置'))
    if username == saved_user and _verify_password(password, saved_pass):
        session['panel_authenticated'] = True
        log_line(f"面板登录成功，用户: {username}")
        return jsonify(dict(ok=True, message='登录成功'))
    import time as _time
    _time.sleep(0.8)
    return jsonify(dict(ok=False, message='用户名或密码错误'))

@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    """退出登录"""
    session.pop('panel_authenticated', None)
    session.pop('disclaimer_agreed', None)
    return jsonify(dict(ok=True, message='已退出登录'))

@app.route('/api/auth/status')
def api_auth_status():
    """检查登录状态"""
    return jsonify(dict(authenticated=bool(session.get('panel_authenticated'))))

# ── 面板认证检查（免责声明 + 首次设置 + 登录）──
@app.before_request
def _check_auth():
    # 1. 先检查免责声明
    if not session.get('disclaimer_agreed'):
        if request.endpoint in ('disclaimer_page', 'api_disclaimer_confirm', 'static', 'app_icon'):
            return None
        if request.path.startswith('/api/disclaimer'):
            return None
        if request.path == '/disclaimer':
            return None
        return redirect('/disclaimer')

    # 2. 检查面板是否已配置（首次使用）
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.get('web', {})
    has_credentials = bool(web_cfg.get('username')) and bool(web_cfg.get('password'))
    if not has_credentials:
        allowed = ('setup_page', 'api_auth_setup', 'api_auth_logout', 'static', 'app_icon')
        if request.endpoint in allowed:
            return None
        if request.path in ('/setup', '/api/auth/setup', '/api/auth/logout'):
            return None
        return redirect('/setup')

    # 3. 检查登录状态
    if session.get('panel_authenticated'):
        return None
    allowed = ('login_page', 'api_auth_login', 'api_auth_setup', 'api_auth_logout', 'static', 'app_icon')
    if request.endpoint in allowed:
        return None
    if request.path in ('/login', '/api/auth/login', '/api/auth/logout', '/api/auth/status'):
        return None
    return redirect('/login')

# ═══════════════════════════════════════════
#  启动
# ═══════════════════════════════════════════
def main():
    port = int(os.getenv('WEB_PORT', '8080'))
    host = os.getenv('WEB_HOST', '0.0.0.0')
    account_label = f" [账号: {ACCOUNT_NAME}]" if ACCOUNT_NAME != '默认' else ""

    # ── 免责声明确认（从bat启动时BILI_DISCLAIMER_SKIP=1可跳过）──
    if not os.getenv('BILI_DISCLAIMER_SKIP'):
        if sys.stdin.isatty():
            _disclaimer_confirm_terminal()
        else:
            print("[Disclaimer] 非交互环境，自动确认免责声明。", flush=True)
    # 终端已确认免责声明，直接标记 session 跳过网页端再次确认
    with app.test_request_context():
        session['disclaimer_agreed'] = True

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
