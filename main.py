    #!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.py — bilibili_learning_bot 主入口"""

# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportPrivateLocalImportUsage=false, reportUnusedCallResult=false, reportDeprecated=false

import asyncio
import os
import traceback

from colorama import Fore, Style

# 导入所有模块（作为独立脚本运行，非包内导入）
from cli.app import (
    _disclaimer_confirm, show_main_menu, show_mood_menu, show_config_menu,
    show_login_menu, show_knowledge_base_menu, show_interest_menu,
    show_comment_menu, show_private_message_menu,
    show_agent_skill_menu, show_up_danmaku_menu, _configure_asr_settings,
    _configure_dry_goods_settings, _configure_standby_settings,
    _configure_video_interval_settings,
    show_knowledge_tutor_menu,
    show_search_history, show_reply_safety_menu,
    quick_factory_reset_all, export_config, import_config, _reload_all_globals,
    save_config, config,
    SUBTITLE_STRICT_CHECK,
    _release_bot_lock,
    _show_bg_tasks,
    video_to_html_bg,
    show_interest_prefs_menu,
    show_coin_settings_menu,
    show_learning_tools_menu,
    show_mindmap_menu,
    open_web_panel,
    manual_visual_note_analysis,
    show_shared_settings_menu,
)
from brain.monitor import configure_monitor_cli
from brain.agent_brain import AgentBrain
from brain.video_analysis import manual_video_analysis, up_homepage_learn
from knowledge.revisit import revisit_knowledge_base_menu
from knowledge.custom import custom_knowledge_menu
from knowledge.organize import organize_knowledge_base
from utils.system_tray import SystemTray
from utils.web_launcher import get_web_port, panel_url


_tray_controller: SystemTray | None = None


def _exit_from_tray() -> None:
    """The tray exit action is an explicit request to terminate this process."""
    _release_bot_lock()
    os._exit(0)


def _run_async(coro):
    """安全执行异步协程"""
    return asyncio.run(coro)


def _safe_async(name, coro, *, finally_cb=None):
    """统一的异步操作包装器：错误捕获 + 可选清理回调"""
    try:
        _run_async(coro)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] {name}异常: {e}{Style.RESET_ALL}")
        traceback.print_exc()
    finally:
        if finally_cb:
            finally_cb()


def main():
    """主菜单循环"""
    global _tray_controller
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    _disclaimer_confirm()
    _tray_controller = SystemTray(
        panel_url(get_web_port()), on_exit=_exit_from_tray, on_show_panel=open_web_panel,
    )
    if os.getenv("BILI_TRAY_DISABLED", "0") != "1" and _tray_controller.start():
        os.environ["BILI_PARENT_TRAY"] = "1"
        print(f"{Fore.GREEN}[OK] 系统托盘图标已启动（右键可打开网页或退出）{Style.RESET_ALL}")
    elif os.name == 'nt':
        print(f"{Fore.YELLOW}[INFO] 系统托盘不可用：请安装 pystray 后重试{Style.RESET_ALL}")

    # 网页端/自动化启动：跳过交互菜单，直接以指定/已配置模式运行机器人
    if os.getenv("BILI_AUTO_START"):
        _mode_env = (os.getenv("BILI_AUTO_START_MODE") or "").strip().lower()
        if _mode_env == "smart":
            _smart = True
        elif _mode_env == "current":
            _smart = False
        else:
            _smart = bool(config.get("system", {}).get("smart_token_mode", False))
        print(f"{Fore.GREEN}[AUTO-START] 以{'智能省token' if _smart else '当前'}模式启动机器人...{Style.RESET_ALL}")
        completion_action = "stop"
        try:
            completion_action = _run_async(AgentBrain().run()) or "stop"
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}[WARN] 机器人被用户中断{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[ERROR] 机器人运行异常: {e}{Style.RESET_ALL}")
            traceback.print_exc()
        finally:
            _release_bot_lock()
        if completion_action == "monitor":
            # The Web panel owns the monitor process so its status and controls
            # remain accurate after the browsing child exits.
            print("[SESSION] HANDOFF_MONITOR_REQUESTED", flush=True)
        return

    # 使用局部引用，避免直接修改全大写"常量"引发 type checker 报错
    import cli.app as _app_mod

    _first_menu = True
    while True:
        if not _first_menu:
            # 任何操作执行完后，先按回车确认看完结果，再重绘主菜单
            input(f"{Fore.CYAN}按回车返回主菜单...{Style.RESET_ALL}")
        _first_menu = False
        show_main_menu()
        choice = input(f"{Fore.CYAN}请输入选项 (0-7/9/A-Z/ALL/AR/BN/MM/RT/WB): {Style.RESET_ALL}").strip()

        if choice == "0":
            print(f"{Fore.YELLOW}👋 再见！{Style.RESET_ALL}")
            break
        elif choice == "1":
            # ── 启动模式选择：智能省token / 当前模式（两个总选择）──
            _smart_cur = bool(config.get("system", {}).get("smart_token_mode", False))
            print(f"""
    {Fore.CYAN}╔══════════════════════════════════════════════════════════╗
    ║              选择启动模式                             ║
    ╠══════════════════════════════════════════════════════════╣
    {Fore.GREEN}1.{Style.RESET_ALL} 💡 智能省token模式 (长时挂机/省钱：跳过封面与ASR、用快速模型、关深度搜索/推荐/心理深度分析/知识验证)
    {Fore.YELLOW}2.{Style.RESET_ALL} 🎯 按已保存配置运行 (默认)
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
    当前默认: {Fore.GREEN + '智能省token' + Style.RESET_ALL if _smart_cur else Fore.YELLOW + '按已保存配置' + Style.RESET_ALL}
    {Style.RESET_ALL}""")
            _mode = input(f"{Fore.CYAN}请选择 (1/2，回车=当前模式): {Style.RESET_ALL}").strip()
            if _mode == "0":
                continue
            _want_smart = (_mode == "1")
            if _want_smart != _smart_cur:
                config.setdefault("system", {})["smart_token_mode"] = _want_smart
                if save_config(config):
                    _reload_all_globals(config)
                    print(f"{Fore.GREEN}[OK] 启动模式已更新为: {'智能省token' if _want_smart else '按已保存配置'}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}[ERROR] 配置保存失败{Style.RESET_ALL}")
            video_cfg = config.setdefault("video", {})
            browse_current = video_cfg.get("browse_mode", "candidate_review")
            print("\n刷视频选择：")
            print("  1. 推荐流随机选择")
            print("  2. AI 候选筛选（建议，默认）")
            browse_choice = input(
                f"选择 (1/2，回车保持 {'AI候选筛选（建议）' if browse_current == 'candidate_review' else '推荐流随机选择'}): "
            ).strip()
            if browse_choice in {"1", "2"}:
                video_cfg["browse_mode"] = "candidate_review" if browse_choice == "2" else "direct"
                if browse_choice == "2":
                    raw_pool = input(f"候选数量 (5-100，回车保持 {video_cfg.get('candidate_pool_size', 20)}): ").strip()
                    if raw_pool:
                        try:
                            video_cfg["candidate_pool_size"] = max(5, min(100, int(raw_pool)))
                        except ValueError:
                            print(f"{Fore.YELLOW}[WARN] 候选数量无效，保持原设置{Style.RESET_ALL}")
                if save_config(config):
                    _reload_all_globals(config)
            print(f"{Fore.GREEN}[START] 启动机器人...{Style.RESET_ALL}")
            completion_action = "stop"
            try:
                completion_action = _run_async(AgentBrain().run()) or "stop"
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[WARN]  机器人被用户中断{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 机器人运行异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
            finally:
                _release_bot_lock()
            if completion_action == "monitor":
                print(f"{Fore.CYAN}[SESSION] 刷视频会话已结束，切换到实时监听模式...{Style.RESET_ALL}")
                try:
                    from brain.monitor import main as monitor_main
                    _run_async(monitor_main())
                except KeyboardInterrupt:
                    print(f"\n{Fore.YELLOW}[WARN] 实时监听被用户中断{Style.RESET_ALL}")
        elif choice == "2":
            show_config_menu()
        elif choice == "3":
            show_login_menu()
        elif choice == "4":
            show_knowledge_base_menu()
        elif choice == "5":
            show_interest_menu()
        elif choice == "6":
            print(f"{Fore.YELLOW}[WARN] 评论互动已被全局安全策略禁用。{Style.RESET_ALL}")
        elif choice == "7":
            show_private_message_menu()
        # BETA: option 8 (diary / self-evolution) is intentionally not exposed.
        # Keep the implementation in cli.app for internal testing only.
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
            # 仅支持 B站视频分析
            try:
                _run_async(manual_video_analysis(force_platform="bilibili"))
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
        elif choice.lower() == "ar":
            from services.like_review import ACTION_TYPES, review_settings
            while True:
                settings = review_settings(config)
                print("\nAI behavior review settings")
                print("  1. Review queue: " + ("on" if settings["enabled"] else "off"))
                print("  2. New review desktop notification: " + ("on" if settings["desktop_notification"] else "off"))
                print("  3. Toggle a review action")
                print("  0. Back")
                review_choice = input("Choose (0-3): ").strip().lower()
                if review_choice == "0":
                    break
                if review_choice == "1":
                    config.setdefault("approval_review", {})["enabled"] = not settings["enabled"]
                elif review_choice == "2":
                    config.setdefault("approval_review", {})["desktop_notification"] = not settings["desktop_notification"]
                elif review_choice == "3":
                    keys = list(ACTION_TYPES)
                    for index, key in enumerate(keys, 1):
                        state = "on" if settings["action_types"].get(key) else "off"
                        print(f"  {index}. {key}: {state}")
                    raw_action = input("Action number (blank to cancel): ").strip()
                    if not raw_action:
                        continue
                    try:
                        action_key = keys[int(raw_action) - 1]
                    except (ValueError, IndexError):
                        print("Invalid action number")
                        continue
                    action_types = config.setdefault("approval_review", {}).setdefault("action_types", {})
                    action_types[action_key] = not settings["action_types"].get(action_key, False)
                else:
                    print("Invalid option")
                    continue
                if save_config(config):
                    _reload_all_globals(config)
                    print("Review settings saved")
                else:
                    print("Failed to save review settings")
        elif choice.lower() == "r":
            quick_factory_reset_all()
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
        elif choice.lower() == "all":
            show_shared_settings_menu()
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
        elif choice.lower() == "h":
            show_search_history()
        elif choice.lower() == "b":
            try:
                _show_bg_tasks()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 查看后台任务异常: {e}{Style.RESET_ALL}")
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
        elif choice.lower() == "j":
            try:
                show_learning_tools_menu()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 学习工具异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "mm":
            try:
                show_mindmap_menu()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 思维导图异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "bn":
            try:
                _run_async(manual_visual_note_analysis())
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 图文学习笔记异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "wb":
            try:
                open_web_panel()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 打开网页端异常: {e}{Style.RESET_ALL}")
                traceback.print_exc()
        elif choice.lower() == "rt":
            configure_monitor_cli()
        else:
            print(f"{Fore.YELLOW}[INFO] 无效选项，请重新输入{Style.RESET_ALL}")


def run_cli() -> None:
    """Keep Ctrl+C and closed terminals from printing an implementation traceback."""
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[INFO] 已取消，程序已退出。{Style.RESET_ALL}")
    except EOFError:
        print(f"\n{Fore.YELLOW}[INFO] 输入流已关闭，程序已退出。{Style.RESET_ALL}")
    finally:
        if _tray_controller:
            _tray_controller.stop()


if __name__ == "__main__":
    run_cli()
