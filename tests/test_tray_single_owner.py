# -*- coding: utf-8 -*-
"""[N1] 托盘单实例回归测试：三个入口共享托盘所有权，杜绝双图标。"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.system_tray import SystemTray, acquire_tray_ownership


def _hold_mutex_child():
    """子进程持有互斥体 6 秒，模拟"已有实例在显示托盘"。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        "import sys, time;"
        "sys.path.insert(0, r'%s');"
        "from utils.system_tray import acquire_tray_ownership as a;"
        "ok = a();"
        "print('held' if ok else 'busy', flush=True);"
        "time.sleep(6)" % root
    )
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)


def test_second_process_cannot_own_tray_on_windows():
    if os.name != "nt":
        # Termux/Linux 无命名互斥体语义，恒允许（由各自开关控制）
        assert acquire_tray_ownership() is True
        return
    proc = _hold_mutex_child()
    try:
        line = proc.stdout.readline().decode("utf-8").strip()
        if line != "held":
            # 本机已有别的 BiliLearn 实例持有托盘所有权（比如正在运行的面板），
            # 子进程抢不到锁：此时跳过而不是误报。
            return
        # 子进程持有期间：本进程不能再抢到托盘所有权
        assert acquire_tray_ownership() is False
        # SystemTray.start()/run() 必须直接拒绝并标记冲突，不创建第二个图标
        tray = SystemTray("http://127.0.0.1:1")
        assert tray.start() is False
        assert tray.last_error == "tray-owner-conflict"
        assert tray._icon is None
        tray2 = SystemTray("http://127.0.0.1:1")
        assert tray2.run() is False
        assert tray2.last_error == "tray-owner-conflict"
    finally:
        proc.kill()
        proc.wait()


def test_owner_process_can_create_tray_or_fail_gracefully():
    """互斥体无人持有时，start() 走正常路径（依赖 pystray 是否安装）。"""
    # 先确认没有其他进程持有（CI 环境通常干净）
    if not acquire_tray_ownership():
        return  # 本机有运行中的 BiliLearn 实例，跳过
    tray = SystemTray("http://127.0.0.1:1")
    started = tray.start()
    # 要么成功启动，要么因缺 pystray 等原因失败——都不能是所有权冲突
    assert tray.last_error != "tray-owner-conflict"
    if started:
        tray.stop()
