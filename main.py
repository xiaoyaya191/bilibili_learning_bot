#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.py — bilibili_learning_bot 主入口"""

# pyright: reportImplicitRelativeImport=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportPrivateLocalImportUsage=false, reportUnusedCallResult=false, reportDeprecated=false

import asyncio
import os
import traceback

from colorama import Fore, Style

# 导入所有模块（作为独立脚本运行，非包内导入）
from cli.app import (
    _disclaimer_confirm, show_main_menu, show_mood_menu, show_config_menu,
    show_login_menu, show_knowledge_base_menu, show_interest_menu,
    show_comment_menu, show_private_message_menu, show_diary_evolution_menu,
    show_agent_skill_menu, show_up_danmaku_menu, _configure_asr_settings,
    _configure_dry_goods_settings, _configure_standby_settings,
    _configure_video_interval_settings,
    show_knowledge_tutor_menu,
    show_search_history, show_reply_safety_menu,
    factory_reset_all, export_config, import_config, _reload_all_globals,
    save_config, config,
    SUBTITLE_STRICT_CHECK,
    _release_bot_lock,
    _show_bg_tasks,
    video_to_html_bg,
    show_interest_prefs_menu,
    show_coin_settings_menu,
)
from brain.agent_brain import AgentBrain
from brain.video_analysis import manual_video_analysis, up_homepage_learn
from knowledge.revisit import revisit_knowledge_base_menu
from knowledge.custom import custom_knowledge_menu
from knowledge.organize import organize_knowledge_base


def _run_async(coro):
    """安全执行异步协程"""
    return asyncio.run(coro)


def main():
    """主菜单循环"""
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    _disclaimer_confirm()

    # 使用局部引用，避免直接修改全大写"常量"引发 type checker 报错
    import cli.app as _app_mod

    while True:
        show_main_menu()
        choice = input(f"{Fore.CYAN}请输入选项 (0-9/A/B/C/D/E/F/G/H/I/K/L/M/N/O/P/Q/R/S/T/U/V/W/X/Y/Z): {Style.RESET_ALL}").strip()

        if choice == "0":
            print(f"{Fore.YELLOW}👋 再见！{Style.RESET_ALL}")
            break
        elif choice == "1":
            print(f"{Fore.GREEN}[START] 启动机器人...{Style.RESET_ALL}")
            try:
                _run_async(AgentBrain().run())
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[WARN]  机器人被用户中断{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 机器人运行异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
            finally:
                _release_bot_lock()
        elif choice == "2":
            show_config_menu()
        elif choice == "3":
            show_login_menu()
        elif choice == "4":
            show_knowledge_base_menu()
        elif choice == "5":
            show_interest_menu()
        elif choice == "6":
            show_comment_menu()
        elif choice == "7":
            show_private_message_menu()
        elif choice == "8":
            show_diary_evolution_menu()
        elif choice == "9":
            show_agent_skill_menu()
        elif choice.lower() == "f":
            show_up_danmaku_menu()
        elif choice.lower() == "g":
            _configure_asr_settings()
            if save_config(config):
                print(f"{Fore.GREEN}[OK] ASR设置已保存{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] ASR设置保存失败{Style.RESET_ALL}")
        elif choice.lower() == "d":
            _configure_dry_goods_settings()
        elif choice.lower() == "m":
            show_mood_menu()
        elif choice.lower() == "v":
            try:
                _run_async(manual_video_analysis())
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 手动视频分析异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "k":
            try:
                _run_async(revisit_knowledge_base_menu())
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 知识库重温异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "t":
            try:
                _run_async(show_knowledge_tutor_menu())
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 知识辅导异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "w":
            try:
                _run_async(video_to_html_bg())
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 视频->HTML异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "u":
            try:
                _run_async(up_homepage_learn())
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] UP主主页学习异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "n":
            try:
                _run_async(custom_knowledge_menu())
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 自定义知识管理异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "l":
            _configure_standby_settings()
        elif choice.lower() == "y":
            _configure_video_interval_settings()
        elif choice.lower() == "r":
            factory_reset_all()
        elif choice.lower() == "e":
            export_config()
        elif choice.lower() == "i":
            import_config()
        elif choice.lower() == "o":
            try:
                _run_async(organize_knowledge_base())
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 知识库整理异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "q":
            no_human_delay = not config.get("speed", {}).get("no_human_delay", False)
            config.setdefault("speed", {})["no_human_delay"] = no_human_delay
            if save_config(config):
                _reload_all_globals(config)
                state = "⚡ 已开启 (跳过延迟)" if no_human_delay else "🐢 已关闭 (模拟真人)"
                print(f"{Fore.GREEN}[OK] 快速模式: {state}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] 配置保存失败{Style.RESET_ALL}")
        elif choice.lower() == "s":
            show_reply_safety_menu()
        elif choice.lower() == "c":
            _app_mod.VISION_COVER_ENABLED = not _app_mod.VISION_COVER_ENABLED
            config.setdefault("vision", {})["cover_enabled"] = _app_mod.VISION_COVER_ENABLED
            if save_config(config):
                _reload_all_globals(config)
                state = "✓ 已开启" if _app_mod.VISION_COVER_ENABLED else "⏸️ 已关闭(刷视频更快)"
                print(f"{Fore.GREEN}[OK] 封面分析: {state}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] 配置保存失败{Style.RESET_ALL}")
        elif choice.lower() == "a":
            # ASR快速切换
            _app_mod.ASR_ENABLED = not _app_mod.ASR_ENABLED
            config.setdefault("asr", {})["enabled"] = _app_mod.ASR_ENABLED
            if save_config(config):
                _reload_all_globals(config)
                state = "✓ 已开启" if _app_mod.ASR_ENABLED else "⏸️ 已关闭"
                print(f"{Fore.GREEN}[OK] ASR语音识别: {state}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] 配置保存失败{Style.RESET_ALL}")
        elif choice.lower() == "h":
            show_search_history()
        elif choice.lower() == "b":
            try:
                _show_bg_tasks()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 查看后台任务异常: {e}{Style.RESET_ALL}")
        elif choice.lower() == "z":
            # 安静模式切换
            _app_mod.QUIET_MODE = not _app_mod.QUIET_MODE
            config.setdefault("system", {})["quiet_mode"] = _app_mod.QUIET_MODE
            if save_config(config):
                _reload_all_globals(config)
                state = "🔇 已开启 (精简日志)" if _app_mod.QUIET_MODE else "📢 已关闭 (完整日志)"
                print(f"{Fore.GREEN}[OK] 安静模式: {state}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] 配置保存失败{Style.RESET_ALL}")
        elif choice.lower() == "p":
            try:
                show_interest_prefs_menu()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 兴趣偏好设置异常: {e}{Style.RESET_ALL}")
        elif choice.lower() == "x":
            try:
                show_coin_settings_menu()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 投币设置异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        else:
            print(f"{Fore.YELLOW}[INFO] 无效选项，请重新输入{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
