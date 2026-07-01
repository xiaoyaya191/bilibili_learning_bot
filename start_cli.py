#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""start_cli.py — 兼容性转发层，实际代码在 cli/app.py

⚠ 请使用 python3 main.py 启动，本文件仅为兼容旧引用。
"""
from cli.app import *  # noqa: F401, F403

if __name__ == "__main__":
    import sys, os
    print("=" * 60)
    print("  ⚠ start_cli.py 已改为转发层，请使用新入口：")
    print()
    print("    python3 main.py")
    print()
    print("  是否自动启动 main.py？(Y/n): ", end="")
    choice = input().strip().lower()
    if choice in ("", "y", "yes"):
        main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
        os.execv(sys.executable, [sys.executable, main_py])
    else:
        print("  已取消。请手动运行 python3 main.py")
