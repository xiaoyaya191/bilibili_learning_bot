"""CLI菜单界面 — 从 new_agent.py 拆出"""
import os, sys, json, time, textwrap
from datetime import datetime
from colorama import Fore, Style, init
init(autoreset=True)

def show_main_menu():
    """显示主菜单"""
    global COMMENT_MODE
    # 获取兴趣数量
    interest_mgr = InterestManager()
    interest_count = len(interest_mgr.get_interests())
    
    comment_mode_text = "真实评论" if COMMENT_MODE == "real" else "模拟评论"
    print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║           bilibili_learning_bot - B站学习互动机器人     ║
    ║               版本: 完整整合版 (兴趣+评论互动)          ║
    ║               特性: 配置菜单 + 自动登录 + 精力系统       ║
    ╠══════════════════════════════════════════════════════════╣
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} [START] 启动机器人
    {Fore.YELLOW}2.{Style.RESET_ALL} ⚙️  配置AI参数
    {Fore.BLUE}3.{Style.RESET_ALL} 🔑 配置登录
    {Fore.MAGENTA}4.{Style.RESET_ALL} 📚 管理知识库
    {Fore.LIGHTYELLOW_EX}5.{Style.RESET_ALL} [TARGET] 管理兴趣爱好
    {Fore.LIGHTCYAN_EX}6.{Style.RESET_ALL} [MSG] 评论互动设置
    {Fore.LIGHTGREEN_EX}7.{Style.RESET_ALL} 📩 私信设置
    {Fore.LIGHTMAGENTA_EX}8.{Style.RESET_ALL} 🧬 日记/自我进化
    {Fore.LIGHTBLUE_EX}9.{Style.RESET_ALL} 🛠️  Agent技能
    {Fore.LIGHTBLUE_EX}F.{Style.RESET_ALL} [*][MSG] UP主关注/弹幕设置
    {Fore.LIGHTYELLOW_EX}G.{Style.RESET_ALL} [ASR]  ASR语音识别设置
    {Fore.MAGENTA}M.{Style.RESET_ALL} 😊 AI心情管理
    {Fore.LIGHTCYAN_EX}D.{Style.RESET_ALL} [GOLD] 干货归档 (高分内容单独保存)
    {Fore.LIGHTCYAN_EX}V.{Style.RESET_ALL} 📹 手动视频分析 (输入链接/标题/UP主，AI客观解析)
    {Fore.LIGHTMAGENTA_EX}K.{Style.RESET_ALL} 🔄 知识库重温 (选择已学视频，重新看/优化)
    {Fore.RED}R.{Style.RESET_ALL} 🔄 恢复出厂设置 (清除所有配置/登录/数据)
    {Fore.YELLOW}S.{Style.RESET_ALL} 🛡️ 关键词审查开关 (当前: {'开启' if REPLY_SAFETY_ENABLED else '关闭'})
    {Fore.GREEN}E.{Style.RESET_ALL} 📤 导出配置 (备份所有设置到一个文件)
    {Fore.BLUE}I.{Style.RESET_ALL} 📥 导入配置 (从备份文件一键恢复所有设置)
    {Fore.LIGHTYELLOW_EX}O.{Style.RESET_ALL} 📂 一键整理知识库 (非3层文件→AI自动归类到3层)
    {Fore.RED}0.{Style.RESET_ALL} ❌ 退出程序

    {Fore.CYAN}当前配置状态:{Style.RESET_ALL}
    • API状态: {Fore.GREEN + "✓ 已配置" + Style.RESET_ALL if is_api_configured() else Fore.YELLOW + "[WARN] 未完整配置" + Style.RESET_ALL}
    • 登录状态: {Fore.GREEN + "✓ 已登录" + Style.RESET_ALL if is_bili_logged_in() else Fore.RED + "✗ 未登录" + Style.RESET_ALL}
    • 知识库: {Fore.GREEN + "✓ 已启用" + Style.RESET_ALL if os.path.exists(KNOWLEDGE_BASE_DIR) else Fore.YELLOW + "[FILE] 待创建" + Style.RESET_ALL}
    • 干货归档: {Fore.GREEN + f"✓ 已启用 (≥{DRY_GOODS_MIN_SCORE}分)" + Style.RESET_ALL if DRY_GOODS_ENABLED else Fore.YELLOW + "💤 未启用" + Style.RESET_ALL}
    • 兴趣爱好: {Fore.GREEN + f"✓ {interest_count}个" + Style.RESET_ALL if interest_count > 0 else Fore.YELLOW + "[WARN] 未设置" + Style.RESET_ALL}
    • 评论互动: {Fore.GREEN + "✓ " + comment_mode_text + Style.RESET_ALL if PROB_COMMENT_OTHERS > 0 else Fore.YELLOW + "[WARN] 未启用" + Style.RESET_ALL}
    • 私信处理: {Fore.GREEN + ("✓ 自动回复" if PRIVATE_MESSAGE_AUTO_REPLY else "✓ 只拟回复") + Style.RESET_ALL if PRIVATE_MESSAGE_ENABLED else Fore.YELLOW + "[WARN] 未启用" + Style.RESET_ALL}
    • 日记/进化: {Fore.GREEN + "✓ 已启用" + Style.RESET_ALL if DIARY_ENABLED or EVOLUTION_ENABLED else Fore.YELLOW + "[WARN] 未启用" + Style.RESET_ALL}
    • Agent技能: {Fore.GREEN + ("✓ 自动" if AGENT_AUTO_ENABLED else "✓ 手动") + Style.RESET_ALL if AGENT_ENABLED else Fore.YELLOW + "[WARN] 未启用" + Style.RESET_ALL}
    • Agent深度搜索: {Fore.GREEN + "🤖 集成刷视频" + Style.RESET_ALL if AGENT_ENABLED and AGENT_DIVE_ENABLED else Fore.YELLOW + "💤 未开启" + Style.RESET_ALL}
    • 语音识别(ASR): {Fore.GREEN + f"[ASR] {ASR_BACKEND.upper()}" + Style.RESET_ALL if ASR_ENABLED else Fore.YELLOW + "🔇 未启用" + Style.RESET_ALL}
    • 复习回顾: {Fore.GREEN + f"📖 已启用 (≥{REVISIT_MIN_SCORE}分)" + Style.RESET_ALL if REVISIT_ENABLED else Fore.YELLOW + "💤 未开启" + Style.RESET_ALL}
    • 会话限制: {Fore.GREEN + ("不限" if SESSION_MAX_VIDEOS <= 0 and SESSION_MAX_DURATION_MINUTES <= 0 else (f"{SESSION_MAX_VIDEOS}个视频" if SESSION_MAX_VIDEOS > 0 else "") + (" / " if SESSION_MAX_VIDEOS > 0 and SESSION_MAX_DURATION_MINUTES > 0 else "") + (f"{SESSION_MAX_DURATION_MINUTES}分钟" if SESSION_MAX_DURATION_MINUTES > 0 else "")) + Style.RESET_ALL}
    • UP主关注: {Fore.GREEN + "[*] 已开启" + Style.RESET_ALL if UP_FOLLOW_ENABLED else Fore.YELLOW + "💤 未开启" + Style.RESET_ALL}
    • 弹幕互动: {Fore.GREEN + "[MSG] 已开启" + Style.RESET_ALL if DANMAKU_ENABLED else Fore.YELLOW + "💤 未开启" + Style.RESET_ALL}
    • 关键词审查: {Fore.GREEN + "🛡 已启用" + Style.RESET_ALL if REPLY_SAFETY_ENABLED else Fore.YELLOW + "⚠ 已关闭" + Style.RESET_ALL}
    • 备用API: {Fore.GREEN + "[REFRESH] " + FALLBACK_PROVIDER_NAME + "(" + (FALLBACK_PROVIDER_MODELS.get('chat','') or '?') + "/" + (FALLBACK_PROVIDER_MODELS.get('vision','') or '?') + ")" + Style.RESET_ALL if FALLBACK_PROVIDER_ENABLED else Fore.YELLOW + "💤 未启用" + Style.RESET_ALL}
    • 随机数限制: {Fore.GREEN + "🎲 已开启 (随机检定)" + Style.RESET_ALL if RANDOM_ENABLED else Fore.YELLOW + "🔒 已关闭 (纯分数)" + Style.RESET_ALL}
    • AI心情: {Fore.GREEN + ("🤖 随机心情" if MOOD_RANDOM_ENABLED else ("✏️ 自定义: " + MOOD_CUSTOM_VALUE if MOOD_CUSTOM_ENABLED and MOOD_CUSTOM_VALUE else "⚙️ 默认")) + Style.RESET_ALL}
    """)


def show_mood_menu():
    """AI心情管理菜单 - 随机心情 / 自定义心情"""
    global config, MOOD_RANDOM_ENABLED, MOOD_RANDOM_INTERVAL_MINUTES
    global MOOD_CUSTOM_ENABLED, MOOD_CUSTOM_VALUE
    
    while True:
        random_text = "🤖 随机心情 (已开启)" if MOOD_RANDOM_ENABLED else "🤖 随机心情 (已关闭)"
        custom_text = f"✏️  自定义心情 ({MOOD_CUSTOM_VALUE})" if MOOD_CUSTOM_ENABLED and MOOD_CUSTOM_VALUE else ("✏️  自定义心情 (已开启)" if MOOD_CUSTOM_ENABLED else "✏️  自定义心情 (已关闭)")
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                😊 AI心情管理设置                          ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前心情模式:{Style.RESET_ALL}
    • 随机心情: {Fore.GREEN + random_text + Style.RESET_ALL}
    • 自定义心情: {Fore.GREEN + custom_text + Style.RESET_ALL}
    • 随机间隔: {Fore.YELLOW}{MOOD_RANDOM_INTERVAL_MINUTES}{Style.RESET_ALL} 分钟

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} {'关闭' if MOOD_RANDOM_ENABLED else '开启'}随机心情
    {Fore.GREEN}2.{Style.RESET_ALL} 设置随机间隔 (分钟)
    {Fore.BLUE}3.{Style.RESET_ALL} {'关闭' if MOOD_CUSTOM_ENABLED else '开启'}自定义心情
    {Fore.BLUE}4.{Style.RESET_ALL} 设置自定义心情文字
    {Fore.YELLOW}5.{Style.RESET_ALL} 重置为默认 (关闭随机+自定义)
    {Fore.RED}0.{Style.RESET_ALL} 返回主菜单
""")
        choice = input(f"{Fore.CYAN}请输入选项: {Style.RESET_ALL}").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            MOOD_RANDOM_ENABLED = not MOOD_RANDOM_ENABLED
            config["mood"]["random_enabled"] = MOOD_RANDOM_ENABLED
            if MOOD_RANDOM_ENABLED:
                MOOD_CUSTOM_ENABLED = False
                config["mood"]["custom_enabled"] = False
                config["mood"]["custom_mood"] = ""
                MOOD_CUSTOM_VALUE = ""
            print(f"{Fore.GREEN}随机心情: {'已开启' if MOOD_RANDOM_ENABLED else '已关闭'}{Style.RESET_ALL}")
        elif choice == "2":
            try:
                val = int(input(f"随机间隔分钟 (当前: {MOOD_RANDOM_INTERVAL_MINUTES}): "))
                if val < 1:
                    val = 1
                MOOD_RANDOM_INTERVAL_MINUTES = val
                config["mood"]["random_interval_minutes"] = val
                print(f"{Fore.GREEN}已更新: {val} 分钟{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "3":
            MOOD_CUSTOM_ENABLED = not MOOD_CUSTOM_ENABLED
            config["mood"]["custom_enabled"] = MOOD_CUSTOM_ENABLED
            if MOOD_CUSTOM_ENABLED:
                MOOD_RANDOM_ENABLED = False
                config["mood"]["random_enabled"] = False
            else:
                config["mood"]["custom_mood"] = ""
                MOOD_CUSTOM_VALUE = ""
            print(f"{Fore.GREEN}自定义心情: {'已开启' if MOOD_CUSTOM_ENABLED else '已关闭'}{Style.RESET_ALL}")
        elif choice == "4":
            val = input(f"请输入自定义心情文字 (当前: {MOOD_CUSTOM_VALUE or '无'}，例: 开心/沮丧/慵懒/好奇): ").strip()
            if val:
                MOOD_CUSTOM_ENABLED = True
                MOOD_RANDOM_ENABLED = False
                config["mood"]["custom_enabled"] = True
                config["mood"]["random_enabled"] = False
                config["mood"]["custom_mood"] = val
                MOOD_CUSTOM_VALUE = val
                print(f"{Fore.GREEN}自定义心情已设置: {val}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}未输入，保持原设置{Style.RESET_ALL}")
        elif choice == "5":
            MOOD_RANDOM_ENABLED = False
            MOOD_CUSTOM_ENABLED = False
            MOOD_CUSTOM_VALUE = ""
            config["mood"]["random_enabled"] = False
            config["mood"]["custom_enabled"] = False
            config["mood"]["custom_mood"] = ""
            # 重置心情状态文件
            if os.path.exists(MOOD_STATE_FILE):
                try:
                    os.remove(MOOD_STATE_FILE)
                except Exception as e:
                    log(f'非预期异常: {e}', 'WARN')
            print(f"{Fore.GREEN}已重置为默认心情模式{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}无效选项{Style.RESET_ALL}")
        
        if choice in ("1","2","3","4","5"):
            save_config(config)


def show_config_menu():
    """显示配置菜单"""
    global UNIFIED_API_KEY, UNIFIED_BASE_URL, MODEL_BRAIN, MODEL_VISION, openai
    global VISION_API_KEY, VISION_BASE_URL
    
    while True:
        vision_has_independent = bool(config["api"].get("vision_api_key", ""))
        vision_key_display = mask_secret(VISION_API_KEY)
        vision_url_display = VISION_BASE_URL
        vision_tag = " 独立" if vision_has_independent else " 共用统一"
        
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                    AI参数配置菜单                        ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前配置:{Style.RESET_ALL}
    • 统一API密钥: {mask_secret(UNIFIED_API_KEY)}
    • 统一API地址: {UNIFIED_BASE_URL}
    • 思考模型: {MODEL_BRAIN}
    • 视觉模型: {MODEL_VISION}

    {Fore.MAGENTA}视觉模型独立API（未配置则自动回退到统一API）:{Style.RESET_ALL}
    • 视觉API密钥: {vision_key_display}{' [NEW]' + vision_tag + '[NEW]' if vision_has_independent else ''}
    • 视觉API地址: {vision_url_display}

    {Fore.CYAN}请选择要配置的项目:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} 🔑 修改统一API密钥
    {Fore.GREEN}2.{Style.RESET_ALL} [NET] 修改统一API地址
    {Fore.GREEN}3.{Style.RESET_ALL} 🤖 修改思考模型
    {Fore.GREEN}4.{Style.RESET_ALL} 👁️  修改视觉模型
    {Fore.MAGENTA}A.{Style.RESET_ALL} 🔑👁️ 设置视觉模型独立API密钥
    {Fore.MAGENTA}B.{Style.RESET_ALL} [NET]👁️ 设置视觉模型独立API地址
    {Fore.MAGENTA}C.{Style.RESET_ALL} [REFRESH] 清除视觉模型独立配置(恢复共用)
    {Fore.YELLOW}5.{Style.RESET_ALL} ⚙️  配置互动参数
    {Fore.YELLOW}6.{Style.RESET_ALL} [FAST] 配置精力系统
    {Fore.BLUE}7.{Style.RESET_ALL} 💾 保存当前配置
    {Fore.BLUE}8.{Style.RESET_ALL} 📋 显示当前配置
    {Fore.YELLOW}9.{Style.RESET_ALL} [VIDEO] 视频下载/抽帧设置
    {Fore.MAGENTA}10.{Style.RESET_ALL} [TIME]  会话限制（定时/计数停止）
    {Fore.MAGENTA}D.{Style.RESET_ALL} [REFRESH] 备用API提供商（跨服务降级）
    {Fore.LIGHTCYAN_EX}M.{Style.RESET_ALL} [LIST] 获取可用模型列表
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-10/A/B/C/D/M): {Style.RESET_ALL}").strip()

        if choice == "0":
            break
        elif choice == "1":
            configure_api_key()
        elif choice == "2":
            configure_api_url()
        elif choice == "3":
            configure_brain_model()
        elif choice == "4":
            configure_vision_model()
        elif choice.upper() == "A":
            configure_vision_api_key()
        elif choice.upper() == "B":
            configure_vision_api_url()
        elif choice.upper() == "C":
            clear_vision_independent_config()
        elif choice == "5":
            configure_interaction_params()
        elif choice == "6":
            configure_energy_params()
        elif choice == "7":
            if save_config(config):
                # 重新加载配置到全局变量
                UNIFIED_API_KEY = config["api"]["unified_api_key"]
                UNIFIED_BASE_URL = config["api"]["unified_base_url"]
                MODEL_BRAIN = config["api"]["model_brain"]
                MODEL_VISION = config["api"]["model_vision"]
                VISION_API_KEY = config["api"].get("vision_api_key") or UNIFIED_API_KEY
                VISION_BASE_URL = config["api"].get("vision_base_url") or UNIFIED_BASE_URL
                configure_openai_client()
                print(f"{Fore.GREEN}[OK] 配置保存成功！{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] 配置保存失败！{Style.RESET_ALL}")
        elif choice == "8":
            show_current_config()
        elif choice == "9":
            configure_video_settings()
        elif choice == "10":
            configure_session_params()
        elif choice.upper() == "D":
            configure_fallback_provider()
        elif choice.upper() == "M":
            _fetch_available_models()
        else:
            print(f"{Fore.RED}[ERROR] 无效选项，请重新选择！{Style.RESET_ALL}")


def show_current_config():
    """显示当前配置"""
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.CYAN}                     当前配置详情{Style.RESET_ALL}")
    print(f"{Fore.CYAN}════════════════════════════════════════════════════════════{Style.RESET_ALL}")

    print(f"\n{Fore.YELLOW}📡 API配置:{Style.RESET_ALL}")
    print(f"  • API密钥: {UNIFIED_API_KEY[:15]}...{UNIFIED_API_KEY[-5:] if len(UNIFIED_API_KEY) > 20 else ''}")
    print(f"  • API地址: {UNIFIED_BASE_URL}")
    print(f"  • 思考模型: {MODEL_BRAIN}")
    print(f"  • 视觉模型: {MODEL_VISION}")

    print(f"\n{Fore.YELLOW}[TARGET] 互动参数:{Style.RESET_ALL}")
    print(f"  • 投币阈值: {COIN_THRESHOLD}")
    print(f"  • 收藏阈值: {FAV_THRESHOLD}")
    print(f"  • 兴趣阈值: {INTEREST_THRESHOLD}（低于此分不互动）")
    print(f"  • 学习归档最低分: {LEARN_MIN_SCORE}（低于此分不归档）")
    print(f"  • 学习归档最低时长: {LEARN_MIN_DURATION_SECONDS}秒")
    print(f"  • 每日最大投币: {MAX_COINS_DAILY}")
    print(f"  • 回复触发概率: {PROB_REPLY_TRIGGER*100}%")
    print(f"  • 评论他人概率: {PROB_COMMENT_OTHERS*100}%")
    print(f"  • 评论检查: {'[OK] 启用' if COMMENT_CHECK_ENABLED else '⏸️ 关闭'} | 间隔: {COMMENT_CHECK_INTERVAL}秒")
    print(f"  • 随机数限制: {'🎲 开启' if RANDOM_ENABLED else '🔒 关闭'} | 关闭时跳过随机检定，只看分数阈值")
    print(f"  • 私信互动: {'[OK] 启用' if PRIVATE_MESSAGE_ENABLED else '⏸️ 关闭'} | {'自动发送' if PRIVATE_MESSAGE_AUTO_REPLY else '仅拟不发送'} | 间隔: {PRIVATE_MESSAGE_CHECK_INTERVAL}秒")

    print(f"\n{Fore.YELLOW}[FAST] 精力系统:{Style.RESET_ALL}")
    print(f"  • 最大精力值: {MAX_ENERGY}")
    print(f"  • 每轮恢复: {ENERGY_RECOVERY_MIN}-{ENERGY_RECOVERY_MAX}点")
    print(f"  • 恢复轮数: {ROUNDS_MIN}-{ROUNDS_MAX}轮")
    print(f"  • 恢复间隔: {ROUND_INTERVAL_MIN}-{ROUND_INTERVAL_MAX}秒")
    print(f"  • 视频间隔: {VIDEO_INTERVAL_MIN}-{VIDEO_INTERVAL_MAX}秒")

    print(f"\n{Fore.YELLOW}[TIME]  防限流冷却:{Style.RESET_ALL}")
    print(f"  • 启动冷却: {COOLDOWN_STARTUP_MIN}-{COOLDOWN_STARTUP_MAX}秒")
    print(f"  • 评论后冷却: {COOLDOWN_POST_COMMENT_MIN}-{COOLDOWN_POST_COMMENT_MAX}秒")
    print(f"  • 私信后冷却: {COOLDOWN_POST_DM_MIN}-{COOLDOWN_POST_DM_MAX}秒")

    print(f"\n{Fore.YELLOW}[VIDEO] 视频理解:{Style.RESET_ALL}")
    print(f"  • 理解模式: {VIDEO_UNDERSTANDING_MODE}")
    print(f"  • 视频过滤: {VIDEO_FILTER_MODE} (watch_all=全看 / cover_and_title=封面+标题判断)")
    print(f"  • 下载时长上限: {VIDEO_MAX_DURATION_SECONDS}秒")
    print(f"  • 固定抽帧数量: {VIDEO_FRAME_COUNT}张")
    print(f"  • 智能下载阈值: {VIDEO_DOWNLOAD_INTEREST_THRESHOLD}")
    print(f"  • 下载路径: {VIDEO_DOWNLOAD_DIR or '默认 Data/video_cache'}")
    print(f"  • AI智能抽帧: {'[OK] 开启' if SMART_FRAME_ENABLED else '⏸️ 关闭'} | 范围: {SMART_FRAME_MIN}-{SMART_FRAME_MAX}帧 | 兜底: {VISION_FRAME_COUNT}帧")

    print(f"\n{Fore.YELLOW}[GOLD] 干货归档:{Style.RESET_ALL}")
    print(f"  • 干货归档: {'[OK] 已启用' if DRY_GOODS_ENABLED else '未启用'} | 最低评分: {DRY_GOODS_MIN_SCORE}")
    print(f"  • 深度看视频: 初始{CURIOSITY_DEEP_DIVE_DEFAULT_VIDEOS}个 | 中等{CURIOSITY_DEEP_DIVE_MID_VIDEOS}个 | 丰富{CURIOSITY_DEEP_DIVE_HIGH_VIDEOS}个")
    print(f"  • 深度看触发: {'[OK] 启用' if CURIOSITY_DEEP_DIVE_ENABLED else '⏸️ 关闭'} | 最低: {CURIOSITY_DEEP_DIVE_MIN_SCORE}分 | 概率: {CURIOSITY_DEEP_DIVE_PROB*100}%")

    print(f"\n{Fore.YELLOW}[TIME]  会话限制:{Style.RESET_ALL}")
    print(f"  • 最多处理视频: {'不限' if SESSION_MAX_VIDEOS <= 0 else f'{SESSION_MAX_VIDEOS}个'}")
    print(f"  • 最长运行时间: {'不限' if SESSION_MAX_DURATION_MINUTES <= 0 else f'{SESSION_MAX_DURATION_MINUTES}分钟'}")

    print(f"\n{Fore.CYAN}════════════════════════════════════════════════════════════{Style.RESET_ALL}")


def show_login_menu():
    """显示登录配置菜单"""
    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                    登录配置菜单                          ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前状态:{Style.RESET_ALL}
    • Cookie文件: {Fore.GREEN + "✓ 有效" + Style.RESET_ALL if is_bili_logged_in() else (Fore.YELLOW + "⚠ 存在但无效" + Style.RESET_ALL if os.path.exists(COOKIE_FILE) else Fore.RED + "✗ 不存在" + Style.RESET_ALL)}

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} 🔑 重新登录（扫码）
    {Fore.YELLOW}2.{Style.RESET_ALL} 🗑️  清除登录信息
    {Fore.BLUE}3.{Style.RESET_ALL} 📋 检查登录状态
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-3): {Style.RESET_ALL}").strip()

        if choice == "0":
            break
        elif choice == "1":
            try:
                asyncio.run(login_bilibili())
            except json.decoder.JSONDecodeError as e:
                log(f"登录过程JSON解析错误（网络异常）: {e}", "ERROR")
                print(f"\n{Fore.YELLOW}[WARN]  登录失败：B站服务器返回异常，请检查网络后重试{Style.RESET_ALL}\n")
            except Exception as e:
                log(f"登录过程异常: {e}", "ERROR")
                print(f"\n{Fore.YELLOW}[WARN]  登录失败: {e}{Style.RESET_ALL}\n")
        elif choice == "2":
            clear_login_info()
        elif choice == "3":
            check_login_status()
        else:
            print(f"{Fore.RED}[ERROR] 无效选项，请重新选择！{Style.RESET_ALL}")


def show_interest_menu():
    """显示兴趣管理菜单"""
    interest_mgr = InterestManager()
    
    while True:
        interests = interest_mgr.get_interests()
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                   兴趣管理菜单                           ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前兴趣列表 ({len(interests)}个):{Style.RESET_ALL}
    """)
        
        if interests:
            for i, interest in enumerate(interests, 1):
                print(f"  {i}. {interest}")
        else:
            print(f"  {Fore.YELLOW}(空) 机器人将对所有视频感兴趣{Style.RESET_ALL}")
        
        print(f"""
    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} ➕ 添加兴趣关键词
    {Fore.YELLOW}2.{Style.RESET_ALL} ➖ 移除兴趣关键词
    {Fore.BLUE}3.{Style.RESET_ALL} 📋 清空所有兴趣
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)
        
        choice = input(f"{Fore.CYAN}请输入选项 (0-3): {Style.RESET_ALL}").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            keyword = input(f"{Fore.YELLOW}请输入兴趣关键词 (如: AI, 科技, 游戏): {Style.RESET_ALL}").strip()
            if keyword:
                interest_mgr.add_interest(keyword)
            else:
                print(f"{Fore.RED}[ERROR] 关键词不能为空！{Style.RESET_ALL}")
        elif choice == "2":
            if interests:
                try:
                    idx = int(input(f"{Fore.YELLOW}请输入要移除的编号: {Style.RESET_ALL}").strip())
                    if 1 <= idx <= len(interests):
                        removed = interest_mgr.remove_interest(interests[idx-1])
                    else:
                        print(f"{Fore.RED}[ERROR] 无效编号！{Style.RESET_ALL}")
                except (ValueError, TypeError):
                    print(f"{Fore.RED}[ERROR] 请输入有效数字！{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 兴趣列表为空！{Style.RESET_ALL}")
        elif choice == "3":
            confirm = input(f"{Fore.RED}确认清空所有兴趣？(y/N): {Style.RESET_ALL}").strip().lower()
            if confirm == 'y':
                for interest in interests[:]:
                    interest_mgr.remove_interest(interest)
                print(f"{Fore.GREEN}[OK] 已清空所有兴趣！{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项！{Style.RESET_ALL}")


def show_comment_menu():
    """显示评论互动设置菜单"""
    global PROB_COMMENT_OTHERS, COMMENT_CHECK_INTERVAL, MAX_REPLIES_PER_CHECK, COMMENT_MODE, COMMENT_CHECK_ENABLED
    global RANDOM_ENABLED
    
    while True:
        mode_icon = "[NET]" if COMMENT_MODE == "real" else "🎭"
        mode_text = "真实评论（实际发送到B站）" if COMMENT_MODE == "real" else "模拟评论（仅日志记录，不真发）"
        check_status = "[OK] 启用" if COMMENT_CHECK_ENABLED else "⏸️ 关闭"
        random_status = "🎲 已开启 (随机检定)" if RANDOM_ENABLED else "🔒 已关闭 (纯分数)"
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                  评论互动设置菜单                        ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 评论模式: {mode_icon} {mode_text}
    • 评论检查总开关: {check_status}
    • 评论他人评论概率: {PROB_COMMENT_OTHERS*100}%
    • 检查新评论间隔: {COMMENT_CHECK_INTERVAL}秒 ({COMMENT_CHECK_INTERVAL/60:.1f}分钟)
    • 每次最大回复数: {MAX_REPLIES_PER_CHECK}条
    • 随机数限制: {random_status}
    • 回复审查: {'启用' if REPLY_SAFETY_ENABLED else '关闭'} | 敏感词 {len(REPLY_SAFETY_BLOCKED_KEYWORDS)} 个

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}0.{Style.RESET_ALL} 🔁 切换评论模式（真实/模拟）
    {Fore.CYAN}7.{Style.RESET_ALL} 🔌 评论检查总开关（当前: {check_status}）
    {Fore.GREEN}1.{Style.RESET_ALL} [STATS] 查看评论互动日志
    {Fore.YELLOW}2.{Style.RESET_ALL} ⚙️  修改评论概率
    {Fore.YELLOW}3.{Style.RESET_ALL} ⏰ 修改检查间隔
    {Fore.YELLOW}4.{Style.RESET_ALL} 🔢 修改最大回复数
    {Fore.YELLOW}5.{Style.RESET_ALL} [DEF]  回复审查设置
    {Fore.MAGENTA}8.{Style.RESET_ALL} 🎲 切换随机数限制（当前: {random_status}）
    {Fore.RED}9.{Style.RESET_ALL} ↩️  返回主菜单
        """)
        
        choice = input(f"{Fore.CYAN}请输入选项 (0-5,7-9=返回): {Style.RESET_ALL}").strip()
        
        if choice == "9":
            break
        elif choice == "0":
            # 切换评论模式
            if COMMENT_MODE == "real":
                COMMENT_MODE = "simulate"
                config["behavior"]["comment_mode"] = "simulate"
            else:
                COMMENT_MODE = "real"
                config["behavior"]["comment_mode"] = "real"
            save_config(config)
            log(f"评论模式已切换为: {COMMENT_MODE}", "INFO")
            print(f"{Fore.GREEN}[OK] 评论模式已切换为: {COMMENT_MODE}{Style.RESET_ALL}")
        elif choice == "7":
            # 评论检查总开关
            COMMENT_CHECK_ENABLED = not COMMENT_CHECK_ENABLED
            config["interaction"]["comment_check_enabled"] = COMMENT_CHECK_ENABLED
            save_config(config)
            status = "启用" if COMMENT_CHECK_ENABLED else "关闭"
            log(f"评论检查总开关已{status}", "INFO")
            print(f"{Fore.GREEN}[OK] 评论检查已{status}！重启后生效。{Style.RESET_ALL}")
        elif choice == "1":
            show_comment_log()
        elif choice == "2":
            try:
                new_val = float(input(f"{Fore.YELLOW}请输入新的评论概率 (0-1): {Style.RESET_ALL}").strip())
                if 0 <= new_val <= 1:
                    config["interaction"]["prob_comment_others"] = new_val
                    PROB_COMMENT_OTHERS = new_val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新！{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入！{Style.RESET_ALL}")
        elif choice == "3":
            try:
                new_val = int(input(f"{Fore.YELLOW}请输入新的检查间隔 (秒, 建议60-600): {Style.RESET_ALL}").strip())
                if new_val > 0:
                    config["interaction"]["comment_check_interval"] = new_val
                    COMMENT_CHECK_INTERVAL = new_val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新！{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入！{Style.RESET_ALL}")
        elif choice == "4":
            try:
                new_val = int(input(f"{Fore.YELLOW}请输入每次最大回复数 (1-10): {Style.RESET_ALL}").strip())
                if 1 <= new_val <= 10:
                    config["interaction"]["max_replies_per_check"] = new_val
                    MAX_REPLIES_PER_CHECK = new_val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新！{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入！{Style.RESET_ALL}")
        elif choice == "5":
            show_reply_safety_menu()
        elif choice == "8":
            RANDOM_ENABLED = not RANDOM_ENABLED
            config["interaction"]["random_enabled"] = RANDOM_ENABLED
            save_config(config)
            new_status = "🎲 已开启 (随机检定)" if RANDOM_ENABLED else "🔒 已关闭 (纯分数)"
            print(f"{Fore.GREEN}[OK] 随机数限制已切换为: {new_status}{Style.RESET_ALL}")
            if RANDOM_ENABLED:
                print(f"{Fore.CYAN}   AI意图需通过随机概率检定才执行 → 更自然、更像真人{Style.RESET_ALL}")
            else:
                print(f"{Fore.CYAN}   只看AI意图和分数阈值，跳过随机检定 → 更激进{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项！{Style.RESET_ALL}")


def show_comment_log():
    """显示评论互动日志"""
    if not os.path.exists(COMMENT_LOG_FILE):
        print(f"{Fore.YELLOW}[WARN] 暂无评论互动日志{Style.RESET_ALL}")
        return
    
    try:
        with open(COMMENT_LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        history = data.get("history", [])
        
        if not history:
            print(f"{Fore.YELLOW}[WARN] 暂无互动记录{Style.RESET_ALL}")
            return
        
        print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
        print(f"{Fore.CYAN}              评论互动日志 (最近20条){Style.RESET_ALL}")
        print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
        
        for entry in history[-20:]:
            timestamp = entry.get("timestamp", "")[:19]
            action = entry.get("action", "")
            content = entry.get("content", "")[:50]
            target = entry.get("target_user", "")
            
            if action == "reply":
                print(f"  {timestamp} [MSG] 回复 @{target}: {content}...")
            elif action == "like":
                print(f"  {timestamp} ❤️ 点赞 @{target}")
            elif action == "blocked_reply":
                hits = ", ".join(entry.get("hits", []))
                print(f"  {timestamp} [DEF] 拦截 @{target}: {entry.get('reason', '')} ({hits})")
        
        print(f"\n{Fore.YELLOW}[STATS] 总计互动: {len(history)} 次{Style.RESET_ALL}")
        print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
        
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 读取日志失败: {e}{Style.RESET_ALL}")



def show_reply_safety_menu():
    """评论/私信回复审查设置"""
    global REPLY_SAFETY_ENABLED, REPLY_SAFETY_BLOCK_ON_INCOMING, REPLY_SAFETY_BLOCK_ON_OUTGOING, REPLY_SAFETY_BLOCKED_KEYWORDS

    safety_cfg = config.setdefault("reply_safety", {})
    safety_cfg.setdefault("blocked_keywords", list(REPLY_SAFETY_BLOCKED_KEYWORDS))

    while True:
        REPLY_SAFETY_BLOCKED_KEYWORDS = safety_cfg.get("blocked_keywords", [])
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                    回复审查设置                          ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 总开关: {'启用' if REPLY_SAFETY_ENABLED else '关闭'}
    • 检查收到的评论/私信: {'启用' if REPLY_SAFETY_BLOCK_ON_INCOMING else '关闭'}
    • 检查拟发送回复: {'启用' if REPLY_SAFETY_BLOCK_ON_OUTGOING else '关闭'}
    • 敏感词: {', '.join(REPLY_SAFETY_BLOCKED_KEYWORDS) if REPLY_SAFETY_BLOCKED_KEYWORDS else '(空)'}

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} 🔁 开关总审查
    {Fore.GREEN}2.{Style.RESET_ALL} 📥 开关检查收到内容
    {Fore.GREEN}3.{Style.RESET_ALL} 📤 开关检查拟发送回复
    {Fore.YELLOW}4.{Style.RESET_ALL} ➕ 添加敏感词
    {Fore.YELLOW}5.{Style.RESET_ALL} ➖ 删除敏感词
    {Fore.BLUE}6.{Style.RESET_ALL} 🧪 测试一句话
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回上级
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-6): {Style.RESET_ALL}").strip()
        if choice == "0":
            break
        elif choice == "1":
            REPLY_SAFETY_ENABLED = not REPLY_SAFETY_ENABLED
            safety_cfg["enabled"] = REPLY_SAFETY_ENABLED
            save_config(config)
        elif choice == "2":
            REPLY_SAFETY_BLOCK_ON_INCOMING = not REPLY_SAFETY_BLOCK_ON_INCOMING
            safety_cfg["block_on_incoming"] = REPLY_SAFETY_BLOCK_ON_INCOMING
            save_config(config)
        elif choice == "3":
            REPLY_SAFETY_BLOCK_ON_OUTGOING = not REPLY_SAFETY_BLOCK_ON_OUTGOING
            safety_cfg["block_on_outgoing"] = REPLY_SAFETY_BLOCK_ON_OUTGOING
            save_config(config)
        elif choice == "4":
            word = input(f"{Fore.YELLOW}输入要添加的敏感词: {Style.RESET_ALL}").strip()
            if word and word not in safety_cfg["blocked_keywords"]:
                safety_cfg["blocked_keywords"].append(word)
                REPLY_SAFETY_BLOCKED_KEYWORDS = safety_cfg["blocked_keywords"]
                save_config(config)
                print(f"{Fore.GREEN}[OK] 已添加: {word}{Style.RESET_ALL}")
        elif choice == "5":
            words = safety_cfg.get("blocked_keywords", [])
            for i, word in enumerate(words, 1):
                print(f"  {i}. {word}")
            try:
                idx = int(input(f"{Fore.YELLOW}输入要删除的编号: {Style.RESET_ALL}").strip())
                if 1 <= idx <= len(words):
                    removed = words.pop(idx - 1)
                    REPLY_SAFETY_BLOCKED_KEYWORDS = words
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已删除: {removed}{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入{Style.RESET_ALL}")
        elif choice == "6":
            text = input(f"{Fore.YELLOW}输入测试文本: {Style.RESET_ALL}").strip()
            hits = ReplySafetyGuard().find_hits(text)
            if hits:
                print(f"{Fore.YELLOW}[WARN] 会拦截，命中: {', '.join(hits)}{Style.RESET_ALL}")
            else:
                print(f"{Fore.GREEN}[OK] 会通过{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")



def show_private_message_menu():
    """显示私信设置菜单"""
    global PRIVATE_MESSAGE_ENABLED, PRIVATE_MESSAGE_AUTO_REPLY, PRIVATE_MESSAGE_CHECK_INTERVAL, PRIVATE_MESSAGE_MAX_REPLIES

    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                    私信设置菜单                          ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 私信检查: {'启用' if PRIVATE_MESSAGE_ENABLED else '关闭'}
    • 自动发送回复: {'[OK] 启用（AI拟好就发）' if PRIVATE_MESSAGE_AUTO_REPLY else '✗ 关闭（拟好但不发）'}
    • 检查间隔: {PRIVATE_MESSAGE_CHECK_INTERVAL}秒
    • 每次最大处理: {PRIVATE_MESSAGE_MAX_REPLIES}条

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} 🔁 开关私信检查
    {Fore.YELLOW}2.{Style.RESET_ALL} [START] 开关自动发送回复
    {Fore.YELLOW}3.{Style.RESET_ALL} ⏰ 修改检查间隔
    {Fore.YELLOW}4.{Style.RESET_ALL} 🔢 修改最大处理数
    {Fore.BLUE}5.{Style.RESET_ALL} 📋 查看私信日志
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-5): {Style.RESET_ALL}").strip()
        pm_config = config.setdefault("private_message", {})

        if choice == "0":
            break
        elif choice == "1":
            PRIVATE_MESSAGE_ENABLED = not PRIVATE_MESSAGE_ENABLED
            pm_config["enabled"] = PRIVATE_MESSAGE_ENABLED
            save_config(config)
            print(f"{Fore.GREEN}[OK] 私信检查已{'启用' if PRIVATE_MESSAGE_ENABLED else '关闭'}{Style.RESET_ALL}")
        elif choice == "2":
            PRIVATE_MESSAGE_AUTO_REPLY = not PRIVATE_MESSAGE_AUTO_REPLY
            pm_config["auto_reply"] = PRIVATE_MESSAGE_AUTO_REPLY
            save_config(config)
            print(f"{Fore.GREEN}[OK] 自动发送回复已{'启用' if PRIVATE_MESSAGE_AUTO_REPLY else '关闭'}{Style.RESET_ALL}")
        elif choice == "3":
            try:
                new_val = int(input(f"{Fore.YELLOW}请输入新的检查间隔 (秒, 建议60-600): {Style.RESET_ALL}").strip())
                if new_val > 0:
                    PRIVATE_MESSAGE_CHECK_INTERVAL = new_val
                    pm_config["check_interval"] = new_val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新！{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入！{Style.RESET_ALL}")
        elif choice == "4":
            try:
                new_val = int(input(f"{Fore.YELLOW}请输入每次最大处理数 (1-10): {Style.RESET_ALL}").strip())
                if 1 <= new_val <= 10:
                    PRIVATE_MESSAGE_MAX_REPLIES = new_val
                    pm_config["max_replies_per_check"] = new_val
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新！{Style.RESET_ALL}")
            except (ValueError, TypeError):
                print(f"{Fore.RED}[ERROR] 无效输入！{Style.RESET_ALL}")
        elif choice == "5":
            show_private_message_log()
        else:
            print(f"{Fore.RED}[ERROR] 无效选项！{Style.RESET_ALL}")



def show_private_message_log():
    if not os.path.exists(PRIVATE_MESSAGE_LOG_FILE):
        print(f"{Fore.YELLOW}[WARN] 暂无私信日志{Style.RESET_ALL}")
        return

    try:
        with open(PRIVATE_MESSAGE_LOG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        history = data.get("history", [])
        if not history:
            print(f"{Fore.YELLOW}[WARN] 暂无私信记录{Style.RESET_ALL}")
            return

        print(f"\n{Fore.CYAN}📋 最近私信记录:{Style.RESET_ALL}")
        for item in history[-10:]:
            if item.get("blocked"):
                sent = "已拦截"
            else:
                sent = "已发送" if item.get("sent") else "未发送"
            print(f"{Fore.GREEN}[{item.get('timestamp')}] @{item.get('talker_id')} ({sent}){Style.RESET_ALL}")
            print(f"  收到: {item.get('incoming', '')[:80]}")
            if item.get("blocked"):
                print(f"  原因: {item.get('reason', '')} | 命中: {', '.join(item.get('hits', []))}")
            print(f"  回复: {item.get('reply', '')[:80]}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 读取私信日志失败: {e}{Style.RESET_ALL}")



def show_diary_evolution_menu():
    """显示日记和自我进化菜单"""
    global DIARY_ENABLED, DIARY_AUTO_ENABLED, DIARY_AUTO_INTERVAL_MINUTES, DIARY_MIN_EVENTS_FOR_AUTO
    global EVOLUTION_ENABLED, EVOLUTION_AUTO_ENABLED, EVOLUTION_REFLECT_INTERVAL_EVENTS
    global EVOLUTION_MIN_EVENTS_FOR_REFLECT, EVOLUTION_AUTO_APPLY

    diary_mgr = BotDiaryManager()
    evolution_mgr = SelfEvolutionManager()

    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                  日记 / 自我进化菜单                    ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 日记: {'启用' if DIARY_ENABLED else '关闭'} | 自动日记: {'启用' if DIARY_AUTO_ENABLED else '关闭'} | 间隔: {DIARY_AUTO_INTERVAL_MINUTES}分钟
    • 自我进化: {'启用' if EVOLUTION_ENABLED else '关闭'} | 自动进化: {'启用' if EVOLUTION_AUTO_ENABLED else '关闭'} | 自动应用: {'启用' if EVOLUTION_AUTO_APPLY else '关闭'}
    • 进化触发: 每 {EVOLUTION_REFLECT_INTERVAL_EVENTS} 个事件检查一次，最少 {EVOLUTION_MIN_EVENTS_FOR_REFLECT} 个事件

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} ✍️  手动写日记
    {Fore.GREEN}2.{Style.RESET_ALL} 📖 查看最近日记
    {Fore.GREEN}3.{Style.RESET_ALL} 🔎 搜索日记
    {Fore.YELLOW}4.{Style.RESET_ALL} 🤖 立即生成自动日记
    {Fore.YELLOW}5.{Style.RESET_ALL} 🧬 立即自我进化
    {Fore.BLUE}6.{Style.RESET_ALL} 📋 查看进化记录
    {Fore.BLUE}7.{Style.RESET_ALL} ⚙️  修改自动设置
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-9): {Style.RESET_ALL}").strip()

        if choice == "0":
            break
        elif choice == "1":
            title = input(f"{Fore.YELLOW}标题: {Style.RESET_ALL}").strip() or "手动日记"
            print(f"{Fore.YELLOW}内容，输入空行结束:{Style.RESET_ALL}")
            lines = []
            while True:
                line = input()
                if not line:
                    break
                lines.append(line)
            try:
                entry = diary_mgr.add_entry(title, "\n".join(lines), mood=MoodManager().get_mood(), tags=["手动"], source="manual")
                print(f"{Fore.GREEN}[OK] 已保存日记: {entry['id']}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 保存失败: {e}{Style.RESET_ALL}")
        elif choice == "2":
            _print_diary_entries(diary_mgr.list_entries(limit=20))
        elif choice == "3":
            query = input(f"{Fore.YELLOW}搜索关键词: {Style.RESET_ALL}").strip()
            _print_diary_entries(diary_mgr.search(query, limit=20))
        elif choice == "4":
            note = input(f"{Fore.YELLOW}额外备注 (可空): {Style.RESET_ALL}").strip()
            try:
                asyncio.run(run_manual_diary_generation(note))
                diary_mgr = BotDiaryManager()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 自动日记失败: {e}{Style.RESET_ALL}")
        elif choice == "5":
            try:
                asyncio.run(run_manual_self_evolution(apply_result=True))
                evolution_mgr = SelfEvolutionManager()
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 自我进化失败: {e}{Style.RESET_ALL}")
        elif choice == "6":
            _print_evolution_items(evolution_mgr.list_items(limit=20))
        elif choice == "7":
            diary_cfg = config.setdefault("diary", {})
            evolution_cfg = config.setdefault("self_evolution", {})
            DIARY_ENABLED = not DIARY_ENABLED if input(f"{Fore.YELLOW}切换日记总开关？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else DIARY_ENABLED
            diary_cfg["enabled"] = DIARY_ENABLED
            DIARY_AUTO_ENABLED = not DIARY_AUTO_ENABLED if input(f"{Fore.YELLOW}切换自动日记？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else DIARY_AUTO_ENABLED
            diary_cfg["auto_enabled"] = DIARY_AUTO_ENABLED
            raw = input(f"{Fore.YELLOW}自动日记间隔分钟 (回车保持): {Style.RESET_ALL}").strip()
            if raw:
                try:
                    DIARY_AUTO_INTERVAL_MINUTES = max(5, int(raw))
                    diary_cfg["auto_interval_minutes"] = DIARY_AUTO_INTERVAL_MINUTES
                except (ValueError, TypeError):
                    print(f"{Fore.YELLOW}[WARN] 间隔无效，保持原样{Style.RESET_ALL}")

            EVOLUTION_ENABLED = not EVOLUTION_ENABLED if input(f"{Fore.YELLOW}切换自我进化总开关？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else EVOLUTION_ENABLED
            evolution_cfg["enabled"] = EVOLUTION_ENABLED
            EVOLUTION_AUTO_ENABLED = not EVOLUTION_AUTO_ENABLED if input(f"{Fore.YELLOW}切换自动进化？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else EVOLUTION_AUTO_ENABLED
            evolution_cfg["auto_enabled"] = EVOLUTION_AUTO_ENABLED
            EVOLUTION_AUTO_APPLY = not EVOLUTION_AUTO_APPLY if input(f"{Fore.YELLOW}切换自动应用进化结果？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else EVOLUTION_AUTO_APPLY
            evolution_cfg["auto_apply"] = EVOLUTION_AUTO_APPLY
            raw = input(f"{Fore.YELLOW}进化检查事件间隔 (回车保持): {Style.RESET_ALL}").strip()
            if raw:
                try:
                    EVOLUTION_REFLECT_INTERVAL_EVENTS = max(1, int(raw))
                    evolution_cfg["reflect_interval_events"] = EVOLUTION_REFLECT_INTERVAL_EVENTS
                except (ValueError, TypeError):
                    print(f"{Fore.YELLOW}[WARN] 事件间隔无效，保持原样{Style.RESET_ALL}")
            save_config(config)
            print(f"{Fore.GREEN}[OK] 设置已保存{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项！{Style.RESET_ALL}")


async def run_manual_agent_goal(goal):
    brain = AgentBrain()
    login_success = await brain.initialize_login()
    if not login_success:
        print(f"{Fore.RED}[ERROR] 登录失败，无法运行需要B站上下文的Agent技能{Style.RESET_ALL}")
        return
    runner = AgentSkillRunner(brain=brain)
    run = await runner.run_goal(goal)
    print(f"{Fore.GREEN}[OK] Agent执行完成{Style.RESET_ALL}")
    print(f"目标: {run.get('goal')}")
    for idx, item in enumerate(run.get("results", []), 1):
        step = item.get("step", {})
        result = item.get("result", {})
        print(f"{idx}. {step.get('skill')} | ok={result.get('ok')}")
        if result.get("videos"):
            for video_item in result["videos"][:5]:
                print(f"   - {video_item.get('title')} ({video_item.get('bvid')})")
        if result.get("watched"):
            for watched in result["watched"]:
                print(f"   - 已看: {watched.get('title')} ({watched.get('bvid')})")
        if result.get("error"):
            print(f"   错误: {result.get('error')}")



def show_agent_skill_menu():
    """Agent技能菜单"""
    global AGENT_ENABLED, AGENT_AUTO_ENABLED, AGENT_DIVE_ENABLED, AGENT_MAX_STEPS_PER_PLAN
    global AGENT_MAX_SEARCH_RESULTS, AGENT_MAX_VIDEOS_PER_PLAN, AGENT_DIVE_MAX_VIDEOS, AGENT_AUTO_MIN_SCORE, AGENT_COOLDOWN_MINUTES

    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                      Agent技能菜单                       ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前设置:{Style.RESET_ALL}
    • 总开关: {'启用' if AGENT_ENABLED else '关闭'}
    • 自动触发: {'启用' if AGENT_AUTO_ENABLED else '关闭'}
    • 🤖 深度搜索(集成刷视频): {'启用' if AGENT_DIVE_ENABLED else '关闭'}
    • 每次最多步骤: {AGENT_MAX_STEPS_PER_PLAN}
    • 搜索结果上限: {AGENT_MAX_SEARCH_RESULTS}
    • 每次最多看视频: {AGENT_MAX_VIDEOS_PER_PLAN}
    • 深度搜索最多看视频: {AGENT_DIVE_MAX_VIDEOS}
    • 自动触发最低评分: {AGENT_AUTO_MIN_SCORE}
    • 自动触发冷却: {AGENT_COOLDOWN_MINUTES}分钟

    {Fore.CYAN}可用技能:{Style.RESET_ALL}
    - search_bilibili_videos: 搜索B站视频
    - watch_bilibili_videos: 理解/观看搜索到的视频
    - write_memory: 写入本轮本地记忆
    - write_diary: 写入Agent日记

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} [START] 运行一个Agent目标
    {Fore.BLUE}2.{Style.RESET_ALL} 📋 查看最近Agent记录
    {Fore.YELLOW}3.{Style.RESET_ALL} ⚙️  修改限制/开关
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-3): {Style.RESET_ALL}").strip()
        if choice == "0":
            break
        elif choice == "1":
            goal = input(f'{Fore.YELLOW}输入Agent目标，例如「了解gpt-5.2这个新模型，看5个相关视频」: {Style.RESET_ALL}').strip()
            if goal:
                try:
                    asyncio.run(run_manual_agent_goal(goal))
                except Exception as e:
                    print(f"{Fore.RED}[ERROR] Agent运行失败: {e}{Style.RESET_ALL}")
        elif choice == "2":
            runner = AgentSkillRunner()
            runs = runner.list_runs(limit=10)
            if not runs:
                print(f"{Fore.YELLOW}[WARN] 暂无Agent记录{Style.RESET_ALL}")
            for run in runs:
                print(f"[{run.get('created_at', '')[:19]}] {run.get('goal')} | 步骤: {len(run.get('results', []))}")
        elif choice == "3":
            agent_cfg = config.setdefault("agent", {})
            AGENT_ENABLED = not AGENT_ENABLED if input(f"{Fore.YELLOW}切换Agent总开关？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else AGENT_ENABLED
            agent_cfg["enabled"] = AGENT_ENABLED
            AGENT_AUTO_ENABLED = not AGENT_AUTO_ENABLED if input(f"{Fore.YELLOW}切换自动触发？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else AGENT_AUTO_ENABLED
            agent_cfg["auto_enabled"] = AGENT_AUTO_ENABLED
            AGENT_DIVE_ENABLED = not AGENT_DIVE_ENABLED if input(f"{Fore.YELLOW}切换深度搜索(集成刷视频)？(y/N): {Style.RESET_ALL}").strip().lower() == "y" else AGENT_DIVE_ENABLED
            agent_cfg["dive_enabled"] = AGENT_DIVE_ENABLED

            fields = [
                ("max_steps_per_plan", "每次最多步骤", "AGENT_MAX_STEPS_PER_PLAN", 1, 20),
                ("max_search_results", "搜索结果上限", "AGENT_MAX_SEARCH_RESULTS", 1, 30),
                ("max_videos_per_plan", "每次最多看视频", "AGENT_MAX_VIDEOS_PER_PLAN", 1, 10),
                ("dive_max_videos", "深度搜索最多看视频", "AGENT_DIVE_MAX_VIDEOS", 1, 50),
                ("cooldown_minutes", "自动触发冷却分钟", "AGENT_COOLDOWN_MINUTES", 1, 1440),
            ]
            for key, label, global_name, min_v, max_v in fields:
                raw = input(f"{Fore.YELLOW}{label} (回车保持): {Style.RESET_ALL}").strip()
                if raw:
                    try:
                        value = max(min_v, min(max_v, int(raw)))
                        agent_cfg[key] = value
                        globals()[global_name] = value
                    except (ValueError, TypeError):
                        print(f"{Fore.YELLOW}[WARN] {label}无效，保持原样{Style.RESET_ALL}")
            raw = input(f"{Fore.YELLOW}自动触发最低评分 (0-10, 回车保持): {Style.RESET_ALL}").strip()
            if raw:
                try:
                    AGENT_AUTO_MIN_SCORE = max(0.0, min(10.0, float(raw)))
                    agent_cfg["auto_min_score"] = AGENT_AUTO_MIN_SCORE
                except (ValueError, TypeError):
                    print(f"{Fore.YELLOW}[WARN] 分数无效，保持原样{Style.RESET_ALL}")
            save_config(config)
            print(f"{Fore.GREEN}[OK] Agent设置已保存{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")

# ==============================================================================
# 🎉 娱乐模式菜单
# ==============================================================================

def show_entertainment_menu():
    """显示娱乐模式菜单"""
    global config, ENTERTAINMENT_ENABLED, ENTERTAINMENT_AUTO_FORTUNE
    global ENTERTAINMENT_PROB_FUN_ACTION, ENTERTAINMENT_JOKE_MODE, ENTERTAINMENT_MAX_DAILY_FORTUNE
    
    ent_mgr = EntertainmentModule()
    
    while True:
        enabled_text = "🎉 已开启" if ENTERTAINMENT_ENABLED else "💤 已关闭"
        fortune_text = "✓ 自动" if ENTERTAINMENT_AUTO_FORTUNE else "✗ 手动"
        
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                    🎉 娱乐模式                           ║
    ║              (所有功能需先开启娱乐模式才能使用)           ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前状态:{Style.RESET_ALL}
    • 娱乐模式: {Fore.GREEN + enabled_text + Style.RESET_ALL}
    • 运势自动推送: {Fore.GREEN + fortune_text + Style.RESET_ALL}
    • 搞笑动作概率: {Fore.YELLOW}{ENTERTAINMENT_PROB_FUN_ACTION}{Style.RESET_ALL}
    • 段子模式: {Fore.MAGENTA}{ENTERTAINMENT_JOKE_MODE}{Style.RESET_ALL}
    • 每日运势上限: {Fore.BLUE}{ENTERTAINMENT_MAX_DAILY_FORTUNE}次{Style.RESET_ALL}

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} [REFRESH]  {'关闭' if ENTERTAINMENT_ENABLED else '开启'}娱乐模式
    {Fore.GREEN}2.{Style.RESET_ALL} 🌟 抽取今日运势
    {Fore.GREEN}3.{Style.RESET_ALL} 😂 听个段子
    {Fore.GREEN}4.{Style.RESET_ALL} 🎲 生成整活评论
    {Fore.GREEN}5.{Style.RESET_ALL} 📖 B站热梗词典
    {Fore.GREEN}6.{Style.RESET_ALL} 🎮 猜UP主小游戏
    {Fore.YELLOW}7.{Style.RESET_ALL} ⚙️  娱乐设置
    {Fore.YELLOW}8.{Style.RESET_ALL} [REFRESH] {'关闭' if ENTERTAINMENT_AUTO_FORTUNE else '开启'}运势自动推送
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)
        
        choice = input(f"{Fore.CYAN}请输入选项 (0-8): {Style.RESET_ALL}").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            if ENTERTAINMENT_ENABLED:
                config["entertainment"]["enabled"] = False
                ENTERTAINMENT_ENABLED = False
                save_config(config)
                print(f"\n{Fore.YELLOW}💤 娱乐模式已关闭！恢复正经模式~{Style.RESET_ALL}")
            else:
                config["entertainment"]["enabled"] = True
                ENTERTAINMENT_ENABLED = True
                save_config(config)
                print(f"\n{Fore.GREEN}🎉 娱乐模式已开启！来整活吧！{Style.RESET_ALL}")
        
        elif choice == "2":
            if not ENTERTAINMENT_ENABLED:
                print(f"\n{Fore.RED}[WARN] 请先开启娱乐模式！{Style.RESET_ALL}")
                continue
            result = ent_mgr.draw_fortune()
            if result["type"] == "limit":
                print(f"\n{Fore.YELLOW}[WARN] {result['msg']}{Style.RESET_ALL}")
            else:
                print(f"\n{'='*40}")
                print(f"  {result['icon']} {result['level']} {result['icon']}")
                print(f"  {result['msg']}")
                print(f"  今日已抽: {result['count']}/{result['max']}")
                print(f"{'='*40}")
        
        elif choice == "3":
            if not ENTERTAINMENT_ENABLED:
                print(f"\n{Fore.RED}[WARN] 请先开启娱乐模式！{Style.RESET_ALL}")
                continue
            print(f"\n{Fore.CYAN}🤔 AI正在构思段子...{Style.RESET_ALL}")
            try:
                joke = asyncio.run(ent_mgr.generate_joke())
                print(f"\n{Fore.YELLOW}😂 {joke}{Style.RESET_ALL}")
            except Exception as e:
                print(f"\n{Fore.RED}段子生成失败: {e}{Style.RESET_ALL}")
        
        elif choice == "4":
            if not ENTERTAINMENT_ENABLED:
                print(f"\n{Fore.RED}[WARN] 请先开启娱乐模式！{Style.RESET_ALL}")
                continue
            title = input(f"{Fore.CYAN}📹 输入视频标题 (回车生成随机): {Style.RESET_ALL}").strip()
            up = input(f"{Fore.CYAN}👤 输入UP主名称 (可选): {Style.RESET_ALL}").strip()
            print(f"\n{Fore.CYAN}🤔 正在生成整活评论...{Style.RESET_ALL}")
            try:
                comment = asyncio.run(ent_mgr.fun_comment(title or "未知视频", up_name=up))
                print(f"\n{Fore.LIGHTGREEN_EX}[MSG] 整活评论:{Style.RESET_ALL}")
                print(f"  {comment}")
            except Exception as e:
                print(f"\n{Fore.RED}生成失败: {e}{Style.RESET_ALL}")
        
        elif choice == "5":
            if not ENTERTAINMENT_ENABLED:
                print(f"\n{Fore.RED}[WARN] 请先开启娱乐模式！{Style.RESET_ALL}")
                continue
            print(f"\n{Fore.CYAN}📖 B站热梗词典 ({len(ent_mgr.BILIBILI_MEMES)}条){Style.RESET_ALL}")
            print(f"{'-'*60}")
            for i, meme in enumerate(ent_mgr.BILIBILI_MEMES, 1):
                print(f"  {i:2d}. {meme}")
            print(f"{'-'*60}")
            print(f"\n{Fore.LIGHTGREEN_EX}[IDEA] 随机一条: {ent_mgr.random_meme()}{Style.RESET_ALL}")
        
        elif choice == "6":
            if not ENTERTAINMENT_ENABLED:
                print(f"\n{Fore.RED}[WARN] 请先开启娱乐模式！{Style.RESET_ALL}")
                continue
            print(f"\n{Fore.CYAN}🎮 猜B站UP主小游戏{Style.RESET_ALL}")
            print(f"  规则：根据描述猜出对应的B站UP主名称")
            
            while True:
                game_result = ent_mgr.guess_up_game_start()
                print(f"\n{Fore.YELLOW}[MSG] 提示: {game_result['hint']}{Style.RESET_ALL}")
                guess = input(f"{Fore.CYAN}🤔 你的答案 (回车跳过): {Style.RESET_ALL}").strip()
                if not guess:
                    print(f"{Fore.LIGHTMAGENTA_EX}答案揭晓: {ent_mgr.game_state.get('guess_answer','未知')}{Style.RESET_ALL}")
                    break
                check = ent_mgr.guess_up_game_check(guess)
                print(f"\n{Fore.GREEN if check['correct'] else Fore.YELLOW}{check['msg']}{Style.RESET_ALL}")
                if check['correct']:
                    break
                again = input(f"{Fore.CYAN}再玩一次？(y/n): {Style.RESET_ALL}").strip().lower()
                if again != 'y':
                    break
        
        elif choice == "7":
            print(f"\n{Fore.CYAN}⚙️  娱乐设置{Style.RESET_ALL}")
            print(f"  1. 搞笑动作概率 (当前: {ENTERTAINMENT_PROB_FUN_ACTION})")
            print(f"  2. 段子模式 (当前: {ENTERTAINMENT_JOKE_MODE})")
            print(f"  3. 每日运势上限 (当前: {ENTERTAINMENT_MAX_DAILY_FORTUNE})")
            sub = input(f"{Fore.CYAN}选择 (0返回): {Style.RESET_ALL}").strip()
            if sub == "1":
                raw = input(f"概率 (0.0-1.0): ").strip()
                try:
                    val = float(raw)
                    if 0 <= val <= 1:
                        config["entertainment"]["prob_fun_action"] = val
                        ENTERTAINMENT_PROB_FUN_ACTION = val
                        save_config(config)
                        print(f"{Fore.GREEN}[OK] 已更新{Style.RESET_ALL}")
                except (ValueError, TypeError) as e:
                    log(f'类型转换失败: {e}', 'DEBUG')
            elif sub == "2":
                print("  normal / spicy / chaos")
                raw = input("模式: ").strip()
                if raw in ("normal", "spicy", "chaos"):
                    config["entertainment"]["joke_mode"] = raw
                    ENTERTAINMENT_JOKE_MODE = raw
                    save_config(config)
                    print(f"{Fore.GREEN}[OK] 已更新{Style.RESET_ALL}")
            elif sub == "3":
                raw = input("每日上限次数: ").strip()
                try:
                    val = int(raw)
                    if val > 0:
                        config["entertainment"]["max_daily_fortune"] = val
                        ENTERTAINMENT_MAX_DAILY_FORTUNE = val
                        save_config(config)
                        print(f"{Fore.GREEN}[OK] 已更新{Style.RESET_ALL}")
                except (ValueError, TypeError) as e:
                    log(f'类型转换失败: {e}', 'DEBUG')
        
        elif choice == "8":
            if ENTERTAINMENT_AUTO_FORTUNE:
                config["entertainment"]["auto_fortune"] = False
                ENTERTAINMENT_AUTO_FORTUNE = False
                save_config(config)
                print(f"\n{Fore.YELLOW}📴 运势自动推送已关闭{Style.RESET_ALL}")
            else:
                config["entertainment"]["auto_fortune"] = True
                ENTERTAINMENT_AUTO_FORTUNE = True
                save_config(config)
                print(f"\n{Fore.GREEN}🔔 运势自动推送已开启，机器人运行时会随机推送运势~{Style.RESET_ALL}")
        
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")

async def _manual_send_danmaku(bvid: str, text: str) -> dict:
    """手动发送弹幕（供菜单直接调用）。"""
    try:
        from bilibili_api import Credential, Danmaku
        from bilibili_api.video import Video
    except ImportError as e:
        return {"code": -1, "msg": f"bilibili_api 导入失败: {e}"}
    if not os.path.exists(COOKIE_FILE):
        return {"code": -1, "msg": "未登录，请先扫码登录"}
    with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
        cookies = json.load(f)
    cred = Credential(
        sessdata=cookies.get('SESSDATA', ''),
        bili_jct=cookies.get('bili_jct', ''),
        buvid3=cookies.get('buvid3', ''),
        dedeuserid=cookies.get('DedeUserID', '')
    )
    try:
        v = Video(bvid=bvid, credential=cred)
        info = await v.get_info()
        cid = info.get('cid', 0)
        if not cid:
            return {"code": -1, "msg": f"未找到视频cid (bvid={bvid})"}
        dm = Danmaku(text=text, dm_time=0.0)
        await v.send_danmaku(danmaku=dm, page_index=0)
        return {"code": 0, "msg": f"弹幕发送成功: {text[:30]}"}
    except Exception as e:
        return {"code": -1, "msg": f"弹幕发送失败: {e}"}


def show_up_danmaku_menu():
    """显示UP主关注/弹幕互动设置菜单"""
    global config, UP_FOLLOW_ENABLED, UP_FOLLOW_AUTO_PROB, UP_FOLLOW_MAX_DAILY
    global UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS, UP_FOLLOW_BROWSE_PROB, UP_FOLLOW_MAX_BROWSE
    global UP_FOLLOW_COOLDOWN_MINUTES, UP_FOLLOW_FAVORITE_PROB
    global UP_FOLLOW_MIN_SCORE, UP_FOLLOW_MIN_IMPRESSIONS, UP_FOLLOW_EXCEPTIONAL_SCORE
    global DANMAKU_ENABLED, DANMAKU_READ_PROB, DANMAKU_LIKE_PROB, DANMAKU_MAX_DAILY_LIKES
    global DANMAKU_SEND_PROB, DANMAKU_MAX_DAILY_SEND
    
    while True:
        up_enabled_text = "[*] 已开启" if UP_FOLLOW_ENABLED else "💤 已关闭"
        danmaku_enabled_text = "[MSG] 已开启" if DANMAKU_ENABLED else "💤 已关闭"
        
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║            [*] UP主关注 + [MSG] 弹幕互动设置                 ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}▶ UP主关注设置:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} {'关闭' if UP_FOLLOW_ENABLED else '开启'}UP主关注功能 → 当前: {Fore.YELLOW + up_enabled_text + Style.RESET_ALL}
    {Fore.GREEN}2.{Style.RESET_ALL} 自动关注概率: {Fore.YELLOW}{UP_FOLLOW_AUTO_PROB}{Style.RESET_ALL}
    {Fore.GREEN}3.{Style.RESET_ALL} 每日关注上限: {Fore.YELLOW}{UP_FOLLOW_MAX_DAILY}{Style.RESET_ALL}
    {Fore.GREEN}4.{Style.RESET_ALL} 关注冷却(分钟): {Fore.YELLOW}{UP_FOLLOW_COOLDOWN_MINUTES}{Style.RESET_ALL}
    {Fore.GREEN}5.{Style.RESET_ALL} 浏览主页概率: {Fore.YELLOW}{UP_FOLLOW_BROWSE_PROB}{Style.RESET_ALL}
    {Fore.GREEN}6.{Style.RESET_ALL} 每次浏览视频数: {Fore.YELLOW}{UP_FOLLOW_MAX_BROWSE}{Style.RESET_ALL}
    {Fore.GREEN}7.{Style.RESET_ALL} 取关不活跃天数(0=关闭): {Fore.YELLOW}{UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS}{Style.RESET_ALL}
    {Fore.GREEN}8.{Style.RESET_ALL} 最低评分门槛(关注底线): {Fore.YELLOW}{UP_FOLLOW_MIN_SCORE}{Style.RESET_ALL}
    {Fore.GREEN}9.{Style.RESET_ALL} 最少印象次数(多看再关): {Fore.YELLOW}{UP_FOLLOW_MIN_IMPRESSIONS}{Style.RESET_ALL}
    {Fore.GREEN}10.{Style.RESET_ALL} 特别优秀分数(首看即关): {Fore.YELLOW}{UP_FOLLOW_EXCEPTIONAL_SCORE}{Style.RESET_ALL}

    {Fore.CYAN}▶ 弹幕互动设置:{Style.RESET_ALL}
    {Fore.BLUE}11.{Style.RESET_ALL} {'关闭' if DANMAKU_ENABLED else '开启'}弹幕互动功能 → 当前: {Fore.YELLOW + danmaku_enabled_text + Style.RESET_ALL}
    {Fore.BLUE}12.{Style.RESET_ALL} 读取弹幕概率: {Fore.YELLOW}{DANMAKU_READ_PROB}{Style.RESET_ALL}
    {Fore.BLUE}13.{Style.RESET_ALL} 点赞弹幕概率: {Fore.YELLOW}{DANMAKU_LIKE_PROB}{Style.RESET_ALL}
    {Fore.BLUE}14.{Style.RESET_ALL} 每日点赞上限: {Fore.YELLOW}{DANMAKU_MAX_DAILY_LIKES}{Style.RESET_ALL}
    {Fore.BLUE}15.{Style.RESET_ALL} 发送弹幕概率: {Fore.YELLOW}{DANMAKU_SEND_PROB}{Style.RESET_ALL}
    {Fore.BLUE}16.{Style.RESET_ALL} 每日发送上限: {Fore.YELLOW}{DANMAKU_MAX_DAILY_SEND}{Style.RESET_ALL}
    {Fore.MAGENTA}17.{Style.RESET_ALL} ✏️  手动发送弹幕 (输入BV号+内容)

    {Fore.CYAN}▶ 查看:{Style.RESET_ALL}
    {Fore.LIGHTBLUE_EX}V.{Style.RESET_ALL} [PEOPLE] 查看AI已关注的UP主列表

    {Fore.YELLOW}S.{Style.RESET_ALL} 💾 保存配置
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)
        
        choice = input(f"{Fore.CYAN}请输入选项 (0-17/V/S): {Style.RESET_ALL}").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            UP_FOLLOW_ENABLED = not UP_FOLLOW_ENABLED
            config["up_follow"]["enabled"] = UP_FOLLOW_ENABLED
            print(f"\n{Fore.GREEN}UP主关注功能已{'开启' if UP_FOLLOW_ENABLED else '关闭'}{Style.RESET_ALL}")
        elif choice == "2":
            try:
                val = float(input(f"自动关注概率 (0-1, 当前: {UP_FOLLOW_AUTO_PROB}): "))
                val = max(0.0, min(1.0, val))
                UP_FOLLOW_AUTO_PROB = val
                config["up_follow"]["auto_follow_prob"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "3":
            try:
                val = int(input(f"每日关注上限 (当前: {UP_FOLLOW_MAX_DAILY}): "))
                UP_FOLLOW_MAX_DAILY = val
                config["up_follow"]["max_daily_follows"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "4":
            try:
                val = int(input(f"关注冷却分钟 (当前: {UP_FOLLOW_COOLDOWN_MINUTES}): "))
                UP_FOLLOW_COOLDOWN_MINUTES = val
                config["up_follow"]["cooldown_minutes"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "5":
            try:
                val = float(input(f"浏览主页概率 (0-1, 当前: {UP_FOLLOW_BROWSE_PROB}): "))
                val = max(0.0, min(1.0, val))
                UP_FOLLOW_BROWSE_PROB = val
                config["up_follow"]["browse_up_videos_prob"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "6":
            try:
                val = int(input(f"每次浏览视频数 (当前: {UP_FOLLOW_MAX_BROWSE}): "))
                UP_FOLLOW_MAX_BROWSE = val
                config["up_follow"]["max_browse_videos"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "7":
            try:
                val = int(input(f"取关不活跃天数 (0=关闭, 当前: {UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS}): "))
                UP_FOLLOW_UNFOLLOW_INACTIVE_DAYS = val
                config["up_follow"]["unfollow_inactive_days"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "8":
            try:
                val = float(input(f"最低评分门槛 (当前: {UP_FOLLOW_MIN_SCORE}): "))
                val = max(0.0, min(10.0, val))
                UP_FOLLOW_MIN_SCORE = val
                config["up_follow"]["min_score"] = val
                print(f"{Fore.GREEN}已更新: {val} (评分 ≥ {val} 才进入关注候选池){Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "9":
            try:
                val = int(input(f"最少印象次数 (当前: {UP_FOLLOW_MIN_IMPRESSIONS}): "))
                val = max(1, min(10, val))
                UP_FOLLOW_MIN_IMPRESSIONS = val
                config["up_follow"]["min_impressions"] = val
                print(f"{Fore.GREEN}已更新: {val} (至少看 {val} 次才可能关注){Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "10":
            try:
                val = float(input(f"特别优秀分数 (当前: {UP_FOLLOW_EXCEPTIONAL_SCORE}): "))
                val = max(5.0, min(10.0, val))
                UP_FOLLOW_EXCEPTIONAL_SCORE = val
                config["up_follow"]["exceptional_score"] = val
                print(f"{Fore.GREEN}已更新: {val} (首看评分 ≥ {val} 即可直接关注){Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "11":
            DANMAKU_ENABLED = not DANMAKU_ENABLED
            config["danmaku"]["enabled"] = DANMAKU_ENABLED
            print(f"\n{Fore.GREEN}弹幕互动功能已{'开启' if DANMAKU_ENABLED else '关闭'}{Style.RESET_ALL}")
        elif choice == "12":
            try:
                val = float(input(f"读取弹幕概率 (0-1, 当前: {DANMAKU_READ_PROB}): "))
                val = max(0.0, min(1.0, val))
                DANMAKU_READ_PROB = val
                config["danmaku"]["read_prob"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "13":
            try:
                val = float(input(f"点赞弹幕概率 (0-1, 当前: {DANMAKU_LIKE_PROB}): "))
                val = max(0.0, min(1.0, val))
                DANMAKU_LIKE_PROB = val
                config["danmaku"]["like_prob"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "14":
            try:
                val = int(input(f"每日点赞上限 (当前: {DANMAKU_MAX_DAILY_LIKES}): "))
                DANMAKU_MAX_DAILY_LIKES = val
                config["danmaku"]["max_daily_danmaku_likes"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "15":
            try:
                val = float(input(f"发送弹幕概率 (0-1, 当前: {DANMAKU_SEND_PROB}): "))
                val = max(0.0, min(1.0, val))
                DANMAKU_SEND_PROB = val
                config["danmaku"]["send_prob"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "16":
            try:
                val = int(input(f"每日发送上限 (当前: {DANMAKU_MAX_DAILY_SEND}): "))
                DANMAKU_MAX_DAILY_SEND = val
                config["danmaku"]["max_daily_send"] = val
                print(f"{Fore.GREEN}已更新: {val}{Style.RESET_ALL}")
            except (ValueError, TypeError): print(f"{Fore.RED}输入无效{Style.RESET_ALL}")
        elif choice == "17":
            # 手动发送弹幕
            bvid = input(f"{Fore.CYAN}请输入BV号: {Style.RESET_ALL}").strip()
            if not bvid:
                print(f"{Fore.RED}BV号不能为空{Style.RESET_ALL}")
            else:
                text = input(f"{Fore.CYAN}请输入弹幕内容 (建议20字内): {Style.RESET_ALL}").strip()
                if not text:
                    print(f"{Fore.RED}弹幕内容不能为空{Style.RESET_ALL}")
                else:
                    try:
                        result = asyncio.run(_manual_send_danmaku(bvid, text))
                        if result.get("code") == 0:
                            print(f"{Fore.GREEN}[OK] {result.get('msg')}{Style.RESET_ALL}")
                        else:
                            print(f"{Fore.RED}[ERROR] {result.get('msg')}{Style.RESET_ALL}")
                    except Exception as e:
                        print(f"{Fore.RED}[ERROR] 发送失败: {e}{Style.RESET_ALL}")
        elif choice.upper() == "V":
            _show_followed_ups()
        elif choice.upper() == "S":
            save_config(config)
            print(f"{Fore.GREEN}[OK] 配置已保存！{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")


def show_knowledge_base_menu():
    """显示知识库管理菜单"""
    while True:
        print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                   知识库管理菜单                         ║
    ╚══════════════════════════════════════════════════════════╝

    {Fore.CYAN}当前状态:{Style.RESET_ALL}
    • 知识库路径: {KNOWLEDGE_BASE_DIR}
    • 分类数量: {count_knowledge_categories()}

    {Fore.CYAN}请选择操作:{Style.RESET_ALL}
    {Fore.GREEN}1.{Style.RESET_ALL} [STATS] 查看知识库统计
    {Fore.GREEN}2.{Style.RESET_ALL} 📂 浏览知识库结构
    {Fore.YELLOW}3.{Style.RESET_ALL} 🔍 搜索知识内容
    {Fore.YELLOW}4.{Style.RESET_ALL} 🗑️  清理重复内容
    {Fore.BLUE}5.{Style.RESET_ALL} [UP] 查看学习记录
    {Fore.MAGENTA}6.{Style.RESET_ALL} 🤖 AI整理分类 (统一3层结构)
    {Fore.LIGHTBLUE_EX}7.{Style.RESET_ALL} 🧠 重建向量索引 (语义搜索)
    {Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)

        choice = input(f"{Fore.CYAN}请输入选项 (0-7): {Style.RESET_ALL}").strip()

        if choice == "0":
            break
        elif choice == "1":
            show_kb_statistics()
        elif choice == "2":
            browse_kb_structure()
        elif choice == "3":
            search_knowledge_content()
        elif choice == "4":
            cleanup_duplicates()
        elif choice == "5":
            show_learning_log()
        elif choice == "6":
            print(f"\n{Fore.CYAN}🤖 正在调用AI重新规划知识库分类（统一3层）...{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}[WARN] 这将重新组织所有文件的分类路径，可能需要1-2分钟{Style.RESET_ALL}")
            confirm = input(f"{Fore.CYAN}确认执行? (y/n): {Style.RESET_ALL}").strip().lower()
            if confirm == "y":
                try:
                    classifier = KnowledgeBaseClassifier()
                    moved, total = asyncio.run(classifier.reclassify_all_three_levels())
                    print(f"{Fore.GREEN}[OK] AI整理完成: 迁移{moved}/{total}个文件{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}[ERROR] AI整理失败: {e}{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}已取消{Style.RESET_ALL}")
        elif choice == "7":
            print(f"\n{Fore.CYAN}🧠 正在重建知识库向量索引...{Style.RESET_ALL}")
            try:
                if KBSearchEngine:
                    from xingye_bot.settings import load_settings as _ls
                    from xingye_bot.state import BotState as _bs
                    _s = _ls()
                    _engine = KBSearchEngine(ModelClient(_s, _bs()))
                    count = _engine.build_index()
                    stats = _engine.stats()
                    print(f"{Fore.GREEN}[OK] 索引构建完成: {stats['vectorized']}/{stats['total_entries']} 条已向量化{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}[WARN] 向量引擎不可用（请先配置 API Key）{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 构建向量索引失败: {e}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 无效选项，请重新选择！{Style.RESET_ALL}")


def show_kb_statistics():
    """显示知识库统计信息"""
    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        print(f"{Fore.YELLOW}[WARN]  知识库目录不存在！{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.CYAN}                知识库统计信息{Style.RESET_ALL}")
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    
    total_files = 0
    total_size = 0
    categories = {}
    
    for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        rel_path = os.path.relpath(root, KNOWLEDGE_BASE_DIR)
        if rel_path == '.':
            category = "根目录"
        else:
            depth = len(rel_path.split(os.sep))
            category = f"{'  ' * (depth-1)}[FILE] {rel_path}"
        
        txt_files = [f for f in files if f.endswith('.txt') or f.endswith('.md')]
        if txt_files:
            categories[category] = len(txt_files)
            total_files += len(txt_files)
            
            for file in txt_files:
                file_path = os.path.join(root, file)
                total_size += os.path.getsize(file_path)
    
    print(f"\n{Fore.YELLOW}[STATS] 总体统计:{Style.RESET_ALL}")
    print(f"  • 知识库路径: {KNOWLEDGE_BASE_DIR}")
    print(f"  • 总文件数: {total_files} 个")
    print(f"  • 总大小: {total_size / 1024:.1f} KB")
    print(f"  • 分类数量: {len(categories)} 个")
    
    if categories:
        print(f"\n{Fore.YELLOW}[FILE] 分类详情:{Style.RESET_ALL}")
        for category, count in sorted(categories.items()):
            print(f"  • {category}: {count} 个文件")
    
    if os.path.exists(LEARNING_LOG_FILE):
        with open(LEARNING_LOG_FILE, 'r', encoding='utf-8') as f:
            log_lines = len(f.readlines())
        print(f"\n{Fore.YELLOW}[NOTE] 学习日志:{Style.RESET_ALL}")
        print(f"  • 学习记录: {log_lines} 条")
    
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")


def show_learning_log():
    """显示学习日志"""
    if not os.path.exists(LEARNING_LOG_FILE):
        print(f"{Fore.YELLOW}[WARN]  学习日志文件不存在！{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    print(f"{Fore.CYAN}                  学习记录日志{Style.RESET_ALL}")
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")
    
    try:
        with open(LEARNING_LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        if lines:
            for line in lines[-20:]:
                print(f"  • {line.strip()}")
        else:
            print(f"{Fore.YELLOW}暂无学习记录{Style.RESET_ALL}")
        
        print(f"\n{Fore.YELLOW}[STATS] 总计: {len(lines)} 条学习记录{Style.RESET_ALL}")
        
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 读取学习日志失败: {e}{Style.RESET_ALL}")
    
    print(f"{Fore.CYAN}════════════════════════════════════════════════{Style.RESET_ALL}")


