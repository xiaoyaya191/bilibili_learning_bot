"""bili/auth.py — B站 登录/认证"""
import asyncio
import json
import os
import time
import random
import qrcode
from io import BytesIO

from colorama import Fore, Style
from bilibili_api import Credential
from bilibili_api.login_v2 import QrCodeLoginEvents, QrCodeLogin

from core.config import COOKIE_FILE, config, save_config
from utils.display import log
from api.throttle import _bili_throttle, _bili_trigger_cooldown

def clear_login_info():
    """清除登录信息"""
    if os.path.exists(COOKIE_FILE):
        try:
            os.remove(COOKIE_FILE)
            print(f"{Fore.GREEN}[OK] 登录信息已清除！{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[ERROR] 清除失败: {e}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}[WARN]  没有找到登录信息！{Style.RESET_ALL}")



def is_bili_logged_in():
    """检查是否已登录（文件存在且含有效 SESSDATA 和 DedeUserID）"""
    if not os.path.exists(COOKIE_FILE):
        return False
    try:
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
        return bool(cookies.get('SESSDATA', '').strip()) and bool(cookies.get('DedeUserID', '').strip())
    except Exception:
        return False


def check_login_status():
    """检查登录状态"""
    if not os.path.exists(COOKIE_FILE):
        print(f"{Fore.RED}[ERROR] Cookie文件不存在！{Style.RESET_ALL}")
        return

    try:
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            cookies = json.load(f)

        print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
        print(f"{Fore.CYAN}                登录状态检查{Style.RESET_ALL}")
        print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")

        print(f"\n{Fore.YELLOW}📋 Cookie信息:{Style.RESET_ALL}")
        for key, value in cookies.items():
            if key in ['SESSDATA', 'bili_jct']:
                print(f"  • {key}: {value[:10]}...{value[-5:]}")
            elif key == 'DedeUserID':
                print(f"  • {key}: {value}")

        print(f"\n{Fore.YELLOW}[FILE] 文件信息:{Style.RESET_ALL}")
        print(f"  • 文件路径: {COOKIE_FILE}")
        print(f"  • 文件大小: {os.path.getsize(COOKIE_FILE)} 字节")
        print(f"  • 修改时间: {time.ctime(os.path.getmtime(COOKIE_FILE))}")

        print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")

    except Exception as e:
        print(f"{Fore.RED}[ERROR] 读取Cookie文件失败: {e}{Style.RESET_ALL}")


# ==============================================================================
# 📚 知识库分类系统
# ==============================================================================

async def login_bilibili():
    log("正在初始化登录...", "LOGIN")
    
    log("正在请求二维码数据...", "LOGIN")
    try:
        qr_login = QrCodeLogin()
        await qr_login.generate_qrcode()
        login_key = qr_login._QrCodeLogin__qr_key
        url = qr_login._QrCodeLogin__qr_link
    except json.decoder.JSONDecodeError as e:
        log(f"B站API返回空响应（网络问题或API限制）: {e}", "ERROR")
        print(f"\n{Fore.YELLOW}[WARN]  无法获取登录二维码：B站服务器返回异常{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}   可能原因：网络不通、IP被限制、或API接口变更{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}   建议：检查网络连接后重试，或用手机热点{Style.RESET_ALL}\n")
        return False
    except Exception as e:
        log(f"获取二维码失败: {e}", "ERROR")
        print(f"\n{Fore.YELLOW}[WARN]  无法获取登录二维码: {e}{Style.RESET_ALL}\n")
        return False
    log(f"获取到登录链接", "LOGIN")

    print("\n" + "="*50)
    print("           📱 B站登录二维码")
    print("="*50)

    # 💾 保存高清二维码图片到独立 qr_codes 文件夹（方便管理，登录后自动删除）
    base_dir = os.path.dirname(os.path.abspath(__file__))
    qr_dir = os.path.join(base_dir, "qr_codes")
    qr_path = os.path.join(qr_dir, "bilibili_login_qr.png")
    # 也存到手机相册（Android 环境）
    gallery_dir = "/storage/emulated/0/Pictures"
    gallery_path = os.path.join(gallery_dir, "bilibili_login_qr.png")
    for target_dir, target_path in [(qr_dir, qr_path), (gallery_dir, gallery_path)]:
        try:
            os.makedirs(target_dir, exist_ok=True)
            qr_png = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=12,
                border=4,
            )
            qr_png.add_data(url)
            qr_png.make(fit=True)
            qr_png.make_image(fill_color="black", back_color="white").save(target_path)
            log(f"二维码已保存: {target_path}", "LOGIN")
        except Exception as e:
            log(f"保存二维码到 {target_dir} 失败: {e}", "WARN")

    # 📲 通知 Android 系统扫描图片（让相册 APP 能看到）
    try:
        import subprocess
        subprocess.run([
            "am", "broadcast",
            "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d", f"file://{gallery_path}"
        ], capture_output=True, timeout=10)
    except Exception as e:
        log(f'非预期异常: {e}', 'WARN')

    if os.path.exists(gallery_path):
        print(f"\n📸 二维码图片已保存到相册：")
        print(f"   📷 {gallery_path}")
        print(f"   → 打开手机「相册/图库」APP 即可看到，用 B站APP 扫码登录")
        print()
    print(f"📁 二维码已保存至: {qr_path}")
    print()

    # 📱 终端二维码预览（纯 Unicode，无 ANSI 转义，日志/重定向友好）
    print("📱 终端二维码预览：")
    print()
    qr_term = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        border=1,
    )
    qr_term.add_data(url)
    qr_term.make(fit=True)
    qr_term.print_ascii(invert=True)
    print()

    print("\n" + "="*50)
    print("📱 扫描二维码后，请在手机上确认登录")
    print("="*50 + "\n")

    scan_detected = False
    cred = None
    poll_errors = 0  # 连续错误计数
    max_poll_errors = 10  # 最多允许 10 次连续网络错误
    while True:
        try:
            status = await qr_login.check_state()
            poll_errors = 0  # 成功则重置

            if status == QrCodeLoginEvents.DONE:
                log("扫码成功！登录完成！", "SUCCESS")
                cred = qr_login.get_credential()
                break
            elif status == QrCodeLoginEvents.SCAN:
                # SCAN = 未扫码
                print("⏳ 等待扫码...", end="\r")
            elif status == QrCodeLoginEvents.CONF:
                # CONF = 已扫码，等待确认
                if not scan_detected:
                    log("[OK] 二维码已扫描，请在手机上确认登录...", "LOGIN")
                    scan_detected = True
                print("📱 请在手机上点击确认...", end="\r")
            elif status == QrCodeLoginEvents.TIMEOUT:
                # TIMEOUT = 已失效
                log("二维码已过期，请重新运行", "ERROR")
                return False

            await asyncio.sleep(2)

        except json.decoder.JSONDecodeError as e:
            poll_errors += 1
            log(f"状态查询返回空响应 ({poll_errors}/{max_poll_errors}): {e}", "WARN")
            if poll_errors >= max_poll_errors:
                log("连续网络错误过多，请检查网络后重试", "ERROR")
                return False
            await asyncio.sleep(3)
        except Exception as e:
            poll_errors += 1
            log(f"状态查询出错 ({poll_errors}/{max_poll_errors}): {e}", "ERROR")
            if poll_errors >= max_poll_errors:
                log("连续网络错误过多，登录中止", "ERROR")
                return False
            await asyncio.sleep(3)

    if cred is None:
        log("登录失败：未获取到凭据", "ERROR")
        return False

    # 🧹 登录成功后自动删除 qr_codes 文件夹中的二维码图片
    try:
        qr_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qr_codes")
        if os.path.isdir(qr_dir):
            for fname in os.listdir(qr_dir):
                fpath = os.path.join(qr_dir, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    log(f"已删除过期二维码: {fpath}", "LOGIN")
    except Exception as e:
        log(f"删除二维码图片失败: {e}", "WARN")

    log("正在提取并保存 Cookie...", "LOGIN")
    try:
        cookies = {
            "SESSDATA": cred.sessdata,
            "bili_jct": cred.bili_jct,
            "DedeUserID": cred.dedeuserid,
            "buvid3": getattr(cred, 'buvid3', ''),
            "ac_time_value": getattr(cred, 'ac_time_value', '')
        }

        os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
        tmp = COOKIE_FILE + '.tmp'
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=4)
        os.replace(tmp, COOKIE_FILE)

        log(f"成功！Cookie 已保存至: {COOKIE_FILE}", "SUCCESS")
        return True

    except Exception as e:
        log(f"保存失败: {e}", "ERROR")
        return False


# ==============================================================================
# [FIX] 安全Task回调：防止 asyncio.create_task 异常静默丢失
# ==============================================================================
