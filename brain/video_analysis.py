"""brain/video_analysis.py — 手动视频分析"""
import asyncio, json, os, re, time, random, httpx, hashlib
from bilibili_api.video import Video
from colorama import Fore, Style
from core.config import config
from core.globals import *  # 所有运行时全局变量
from utils.display import log
from utils.helpers import sanitize_filename, _mask_urls
from brain.agent_brain import AgentBrain
from knowledge.classifier import KnowledgeBaseClassifier
from api.subtitles import fetch_bilibili_subtitles, SYSTEM_PROMPT_BRAIN
from core.config import get_bot_name

from utils.helpers import _safe_task_callback


# ==============================================================================
# [BRAIN] AgentBrain 主类
# ==============================================================================
# [brain/agent_brain.py] AgentBrain
def _extract_bvid(text: str):
    """从文本中提取 BV 号。
    支持: 完整URL、短链接、纯BV号
    """
    # 纯 BV 号
    m = re.search(r'\b(BV[0-9A-Za-z]{10})\b', text)
    if m:
        return m.group(1)
    # b23.tv 短链接
    m = re.search(r'b23\.tv/([0-9A-Za-z]+)', text)
    if m:
        return m.group(1)
    return None

async def _resolve_b23_short(short_code: str) -> str:
    """解析 b23.tv 短链接为完整 BV 号"""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(f"https://b23.tv/{short_code}",
                                    headers={"User-Agent": "Mozilla/5.0"})
            url = str(resp.url)
            m = re.search(r'BV[0-9A-Za-z]{10}', url)
            if m:
                return m.group(0)
    except Exception as e:
        log(f'非预期异常: {e}', 'WARN')
    return ""

async def _manual_api_retry(api_call, name: str, fallback=None, max_retries=3, base_delay=1.5):
    """手动视频分析专用 API 重试包装器。
    
    重试策略：首次失败后指数退避（1.5s → 3s → 6s）+ 随机抖动。
    -799 限流自动触发全局冷却 + 额外等待。
    
    Args:
        api_call: async callable，无参数
        name: 调用名称（用于日志）
        fallback: 最终失败时的兜底返回值
        max_retries: 额外重试次数（含首次共 max_retries+1 次尝试）
        base_delay: 基础延迟秒数
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 2.0)
                log(f"[RETRY] {name} 第{attempt}次重试({delay:.1f}s)...", "MANUAL")
                await asyncio.sleep(delay)
            result = await api_call()
            # 检查空结果
            if result is not None:
                if isinstance(result, list) and len(result) == 0:
                    if attempt < max_retries:
                        log(f"[RETRY] {name} 返回空列表，准备重试...", "MANUAL")
                        continue
                elif isinstance(result, str) and not result.strip():
                    if attempt < max_retries:
                        log(f"[RETRY] {name} 返回空字符串，准备重试...", "MANUAL")
                        continue
                return result
            if attempt < max_retries:
                log(f"[RETRY] {name} 返回None，准备重试...", "MANUAL")
        except Exception as e:
            last_error = e
            err_msg = str(e)
            if '-799' in err_msg or '请求过于频繁' in err_msg:
                _bili_trigger_cooldown()
                retry_delay = base_delay * (2 ** attempt) + random.uniform(3, 8)
                log(f"[RETRY] {name} 触发-799限流，{retry_delay:.0f}s后重试({attempt+1}/{max_retries})...", "MANUAL")
                await asyncio.sleep(retry_delay)
            elif attempt < max_retries:
                log(f"[RETRY] {name} 异常: {_mask_urls(err_msg[:120])}，重试中({attempt+1}/{max_retries})...", "MANUAL")
            else:
                log(f"[ERROR] {name} 重试{max_retries}次均失败: {_mask_urls(err_msg[:200])}", "MANUAL")
    
    log(f"[WARN] {name} 最终失败，返回兜底值: {fallback}", "MANUAL")
    return fallback



async def _ai_cross_check_subtitle_match(brain, title: str, subtitle_text: str):
    """快速AI交叉验证：字幕内容是否与视频标题匹配。

    返回 (is_match: bool, confidence: float, reason: str)
    """
    if not title or not subtitle_text or len(subtitle_text) < 30:
        return True, 0.5, "内容过短跳过验证"

    check_prompt = f"""你是内容匹配验证器。判断以下视频字幕内容是否与标题相符。

标题: {title}

字幕内容(前2000字):
{subtitle_text[:2000]}

只返回JSON: {{"match": true/false, "confidence": 0.0-1.0, "reason": "简短理由(20字内)"}}"""

    try:
        resp = await brain._call_ai_with_retry(
            model=MODEL_BRAIN,
            messages=[{"role": "user", "content": check_prompt}],
            request_timeout=30
        )
        raw = resp.choices[0].message.content
        s = raw.find("{")
        e = raw.rfind("}")
        if s >= 0 and e >= s:
            result = json.loads(raw[s:e+1])
            return result.get("match", True), result.get("confidence", 0.5), result.get("reason", "AI验证完成")
    except Exception as ex:
        log(f"[WARN] AI交叉验证异常: {ex}，默认放行", "MANUAL")

    return True, 0.5, "验证异常-默认放行"



async def manual_video_analysis():
    """手动视频分析：用户输入链接/标题/UP主名，AI客观解析视频内容。"""
    print(f"\n{Fore.CYAN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}|               📹 手动视频分析 - 客观AI解析                    |{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[INFO] 支持: B站视频链接 | BV号 | 视频标题 | UP主名字{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[INFO] 此模式下AI不带心情/人格滤镜，纯客观分析{Style.RESET_ALL}")

    user_input = input(f"\n{Fore.CYAN}请输入视频链接/标题/UP主名字: {Style.RESET_ALL}").strip()
    if not user_input:
        print(f"{Fore.YELLOW}[WARN] 输入为空，已取消{Style.RESET_ALL}")
        return

    # ── 第一步：判断输入类型 ──
    bvid = None
    title = None
    up_name = None
    up_uid = None
    from_search = False

    raw_bvid = _extract_bvid(user_input)
    if raw_bvid:
        # 可能是 b23.tv 短链接
        if 'b23.tv' in user_input.lower():
            resolved = await _resolve_b23_short(raw_bvid)
            if resolved:
                bvid = resolved
                log(f"短链接解析: b23.tv/{raw_bvid} -> {bvid}", "RESOLVE")
            else:
                print(f"{Fore.RED}[ERROR] 短链接解析失败，尝试直接搜索...{Style.RESET_ALL}")
                from_search = True
        else:
            bvid = raw_bvid

    if not bvid and not from_search:
        from_search = True

    # ── 提前创建 AgentBrain，加载凭证用于搜索 ──
    brain = AgentBrain()
    brain.bili._load_credential()
    # [FIX] 同时加载 cookies，否则 fetch_bilibili_subtitles 无 cookie 无法获取AI字幕
    # B站 player/wbi/v2 在未登录时不返回AI字幕（如 lan:ai-zh）
    cookie_loaded = False
    # 1) 检查项目自己的 cookie
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            brain.cookies = json.load(f)
        cookie_loaded = True
        log(f"[AUTO] 从本地项目加载到登录Cookie (UID: {brain.cookies.get('DedeUserID','?')})", "LOGIN")
    else:
        # 2) 扫描兄弟项目的 cookie 文件
        sibling_dirs = [
            ("bilibili_learning_bot", "Data/bilibili_cookies.json"),
            ("bilibili_learning_bot-2.2.1", "Data/bilibili_cookies.json"),
            ("bilibili_learning_bot-2.2.2/bilibili_learning_bot-3.0.0", "Data/bilibili_cookies.json"),
            ("bilibili_claw", "Data/bilibili_cookies.json"),
            ("batch_unfollow", "Data/bilibili_cookies.json"),
        ]
        for sib_dir, sib_file in sibling_dirs:
            sibling_cookie = os.path.join(os.path.dirname(BASE_DIR), sib_dir, sib_file)
            if os.path.exists(sibling_cookie):
                try:
                    with open(sibling_cookie, 'r', encoding='utf-8') as f:
                        brain.cookies = json.load(f)
                    uid = brain.cookies.get('DedeUserID', '?')
                    log(f"[AUTO] 从 {sib_dir} 项目加载到登录Cookie (UID: {uid})", "LOGIN")
                    cookie_loaded = True
                    break
                except Exception as e:
                    log(f'非预期异常: {e}', 'WARN')
    if not cookie_loaded:
        print(f"{Fore.YELLOW}[HINT] 未登录(Cookie文件不存在)，部分视频的AI字幕可能需要登录才能获取{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}       建议先运行菜单 3 录入登录Cookie，以获取完整AI字幕功能{Style.RESET_ALL}")

    # ── 从搜索中选择视频 ──
    if from_search:
        print(f"\n{Fore.CYAN}正在B站搜索: {user_input}...{Style.RESET_ALL}")
        results = await brain.bili.search_bilibili(user_input, limit=12)
        if not results:
            print(f"{Fore.RED}[ERROR] 未找到相关视频或UP主{Style.RESET_ALL}")
            return

        save_search_history(user_input, len(results))
        print(f"\n{Fore.GREEN}找到 {len(results)} 个相关结果，请选择:{Style.RESET_ALL}")
        # 轻量字幕检测: 使用 player/wbi/v2 + WBI签名 (与fetch_bilibili_subtitles一致)
        # [FIX] 旧版 player/v2+cid=1 无法正确检测AI字幕（如 lan:ai-zh），
        #       改用 player/wbi/v2 并检查 allow_submit 标志位
        sub_status = {}
        cookie_dict = getattr(brain, 'cookies', None)
        _ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

        # 获取WBI密钥（一次，批次内共享）
        wbi_keys = None
        try:
            async with httpx.AsyncClient(http2=True, timeout=10.0) as _wk:
                wb = await _wk.get('https://api.bilibili.com/x/web-interface/nav',
                                   cookies=cookie_dict,
                                   headers={'User-Agent': _ua, 'Referer': 'https://www.bilibili.com/'})
                wn = wb.json()
                if wn.get('code') == 0:
                    wi = wn['data'].get('wbi_img', {})
                    im = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get('img_url', ''))
                    sm = re.search(r'/([^/]+)\.(?:png|svg)$', wi.get('sub_url', ''))
                    if im and sm:
                        wbi_keys = (im.group(1), sm.group(1))
        except Exception:
            pass

        def _wbi_sign(params):
            if not wbi_keys:
                return params
            mixin = wbi_keys[0] + wbi_keys[1]
            wts = int(time.time())
            sp = dict(params)
            sp['wts'] = wts
            si = sorted(sp.items(), key=lambda x: x[0])
            qs = '&'.join(f'{k}={v}' for k, v in si)
            sp['w_rid'] = hashlib.md5((qs + mixin).encode()).hexdigest()
            return sp

        async with httpx.AsyncClient(http2=True, timeout=8.0) as _sc:
            async def _chk(bvid):
                async def _check_response(pd):
                    sts = pd.get('data', {}).get('subtitle', {}).get('subtitles', [])
                    if not sts:
                        sts = pd.get('data', {}).get('subtitles', [])
                    if sts:
                        return bvid, True
                    sub_obj = pd.get('data', {}).get('subtitle', {})
                    if isinstance(sub_obj, dict) and sub_obj.get('allow_submit') is False:
                        return bvid, False
                    return bvid, False
                try:
                    params = _wbi_sign({'bvid': bvid, 'cid': 1})
                    pres = await _sc.get('https://api.bilibili.com/x/player/wbi/v2',
                                         params=params, cookies=cookie_dict,
                                         headers={'User-Agent': _ua, 'Referer': f'https://www.bilibili.com/video/{bvid}'})
                    if pres.status_code == 200:
                        return _check_response(pres.json())
                    # 412 风控 → fallback 到 player/v2
                    if pres.status_code == 412:
                        pres2 = await _sc.get('https://api.bilibili.com/x/player/v2',
                                              params={'bvid': bvid, 'cid': 1},
                                              cookies=cookie_dict,
                                              headers={'User-Agent': _ua, 'Referer': f'https://www.bilibili.com/video/{bvid}'})
                        if pres2.status_code == 200:
                            return _check_response(pres2.json())
                except Exception:
                    pass
                return bvid, False
            bvids = [r.get('bvid', '') for r in results if r.get('bvid')]
            for batch_start in range(0, len(bvids), 3):
                batch = bvids[batch_start:batch_start + 3]
                tasks = [_chk(b) for b in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                for br in batch_results:
                    if isinstance(br, tuple):
                        sub_status[br[0]] = br[1]
                if batch_start + 3 < len(bvids):
                    await asyncio.sleep(0.2)
        print(f"{Fore.CYAN}{'─' * 80}{Style.RESET_ALL}")
        for i, r in enumerate(results):
            dur = r.get("duration", "??")
            play = r.get("play", 0)
            play_str = f"{play/10000:.1f}w" if play >= 10000 else str(play)
            title_display = r['title'][:50]
            author = r.get('author', '?')
            bvid = r.get('bvid', '')
            tag = f"  {'📝 有字幕' if sub_status.get(bvid) else '🔇 无字幕'}" if bvid in sub_status else ""
            print(f"  {Fore.YELLOW}{i+1:>2}.{Style.RESET_ALL} {title_display}{tag}")
            print(f"      {Fore.LIGHTBLACK_EX}@{author}  |  ▶ {play_str}  |  ⏱ {dur}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'─' * 80}{Style.RESET_ALL}")
        print(f"  {Fore.YELLOW} 0.{Style.RESET_ALL} 取消")
        print(f"  {Fore.CYAN}输入UP主名字可搜索TA的最新视频{Style.RESET_ALL}")

        choice = input(f"\n{Fore.CYAN}请选择视频编号 (1-{len(results)}): {Style.RESET_ALL}").strip()

        if choice == "0" or choice == "":
            print(f"{Fore.YELLOW}[WARN] 已取消{Style.RESET_ALL}")
            return

        # 判断是数字选择还是UP主名
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(results):
                chosen = results[idx]
                bvid = chosen.get("bvid")
                title = chosen.get("title", "")
                up_name = chosen.get("author", "")
                up_uid = chosen.get("mid")
                print(f"{Fore.GREEN}[OK] 已选择: {title} - @{up_name}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")
                return
        except ValueError:
            # 非数字 -> 判断是否像UP主名（至少2个汉字或3个以上字符）
            if len(choice) < 2 or (len(choice) <= 3 and choice.isascii()):
                print(f"{Fore.RED}[ERROR] 无效输入: '{choice}' — 请输入数字编号或UP主名字{Style.RESET_ALL}")
                return
            # 非数字 -> 搜索UP主，取TA最新视频
            print(f"{Fore.CYAN}搜索UP主: {choice}...{Style.RESET_ALL}")
            try:
                data = await bili_search.search_by_type(
                    choice,
                    search_type=bili_search.SearchObjectType.USER,
                    page=1
                )
                user_items = data.get("result") or []
                if not user_items:
                    print(f"{Fore.RED}[ERROR] 未找到UP主: {choice}{Style.RESET_ALL}")
                    return
                best = user_items[0]
                up_uid = best.get("mid") or best.get("uid")
                up_name = best.get("uname") or best.get("name") or choice
                if up_uid:
                    up_uid = int(up_uid)
                    print(f"{Fore.GREEN}[OK] 找到UP主: {up_name} (UID: {up_uid}){Style.RESET_ALL}")
                    print(f"{Fore.CYAN}获取 @{up_name} 的最新视频...{Style.RESET_ALL}")
                    latest = await brain.bili.get_up_videos(up_uid, limit=1)
                    if latest:
                        bvid = latest[0].get("bvid")
                        title = latest[0].get("title", "")
                        if not up_name:
                            up_name = choice
                        print(f"{Fore.GREEN}[OK] 最新视频: {title}{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.RED}[ERROR] 该UP主没有投稿视频{Style.RESET_ALL}")
                        return
                else:
                    print(f"{Fore.RED}[ERROR] 无法获取UP主UID{Style.RESET_ALL}")
                    return
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 搜索UP主失败: {e}{Style.RESET_ALL}")
                return

    # ── 获取视频信息 ──
    if not title or not up_name:
        print(f"{Fore.CYAN}获取视频信息...{Style.RESET_ALL}")
        try:
            meta = await brain.bili._wbi_get(
                'https://api.bilibili.com/x/web-interface/view',
                params={'bvid': bvid}
            )
            vinfo = meta.json()
            if vinfo.get('code') == 0:
                vdata = vinfo['data']
                title = title or vdata.get('title', '')
                up_name = up_name or vdata.get('owner', {}).get('name', '未知')
                up_uid = up_uid or vdata.get('owner', {}).get('mid', 0)
            else:
                print(f"{Fore.RED}[ERROR] 获取视频信息失败: code={vinfo.get('code')}{Style.RESET_ALL}")
                return
        except Exception as e:
            print(f"{Fore.RED}[ERROR] 获取视频信息失败: {e}{Style.RESET_ALL}")
            return

    video_url = f"https://www.bilibili.com/video/{bvid}"
    print(f"\n{Fore.GREEN}+------------------------------------------------------------+{Style.RESET_ALL}")
    print(f"{Fore.GREEN}|  视频: {title[:45]}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}|  UP主: @{up_name}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}|  链接: {video_url}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}+------------------------------------------------------------+{Style.RESET_ALL}")

    # ── 第二步：选择分析模式 ──
    print(f"\n{Fore.CYAN}选择分析模式:{Style.RESET_ALL}")
    print(f"  {Fore.GREEN}Enter (回车){Style.RESET_ALL} = 直接分析：输入一句话意图，自动看视频归档")
    print(f"  {Fore.LIGHTMAGENTA_EX}A (Agent){Style.RESET_ALL}  = Agent对话：多轮对话确定目标、搜索知识库、增删改查文件")
    print(f"  {Fore.LIGHTBLUE_EX}S (一句话){Style.RESET_ALL}  = 🤖 一句话Agent：说一句话，AI自动规划→执行→汇报，无需多轮")
    mode_choice = input(f"\n{Fore.CYAN}模式 (回车=直接分析 / A-Agent对话 / S-一句话Agent): {Style.RESET_ALL}").strip().lower()

    if mode_choice == "a":
        # 提前获取 aid 供 Agent 使用
        _aid = 0
        try:
            meta = await brain.bili._wbi_get(
                'https://api.bilibili.com/x/web-interface/view',
                params={'bvid': bvid}
            )
            vinfo = meta.json()
            if vinfo.get('code') == 0:
                _aid = vinfo.get('data', {}).get('aid', 0)
        except Exception as e:
            log(f'非预期异常: {e}', 'WARN')
        await _agent_video_analysis(brain, bvid, title, up_name, video_url, _aid)
        return
    
    if mode_choice in ("s", "一句话", "1"):
        # 一句话Agent模式：AI自动规划+执行+汇报，无需多轮
        _aid = 0
        try:
            meta = await brain.bili._wbi_get(
                'https://api.bilibili.com/x/web-interface/view',
                params={'bvid': bvid}
            )
            vinfo = meta.json()
            if vinfo.get('code') == 0:
                _aid = vinfo.get('data', {}).get('aid', 0)
        except Exception as e:
            log(f'非预期异常: {e}', 'WARN')
        # 一句话Agent：自动运行一次，无需交互
        await _one_sentence_agent(brain, bvid, title, up_name, video_url, _aid)
        return

    # ── 直接分析模式：用户意图输入 ──
    intent = input(f"\n{Fore.CYAN}你的意图/要求 (如:帮我总结知识点/分析UP主风格/回车跳过): {Style.RESET_ALL}").strip()
    if intent:
        print(f"{Fore.GREEN}[OK] 意图: {intent}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}[INFO] 无额外意图，默认分析模式{Style.RESET_ALL}")

    # ── 分析方式选择菜单 ──
    force_mode = None  # None = 默认智能流程
    mode_map = {
        "1": "subtitle_only", "2": "asr_only", "3": "vision_only",
        "4": "subtitle+asr", "5": "subtitle+vision", "6": "asr+vision",
        "7": "all"
    }
    print(f"\n{Fore.CYAN}选择分析方式 (回车=默认智能流程):{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}1.{Style.RESET_ALL} 仅获取字幕 — 只获取CC/AI字幕，不下载视频")
    print(f"  {Fore.YELLOW}2.{Style.RESET_ALL} 仅语音识别 — 下载视频 -> ASR语音转文字")
    print(f"  {Fore.YELLOW}3.{Style.RESET_ALL} 仅视觉抽帧 — 下载视频 -> 关键帧AI画面分析")
    print(f"  {Fore.YELLOW}4.{Style.RESET_ALL} 字幕 + 语音识别 — 获取字幕 + 下载视频ASR")
    print(f"  {Fore.YELLOW}5.{Style.RESET_ALL} 字幕 + 视觉抽帧 — 获取字幕 + 关键帧AI分析")
    print(f"  {Fore.YELLOW}6.{Style.RESET_ALL} 语音识别 + 视觉抽帧 — 下载视频 -> ASR+画面分析")
    print(f"  {Fore.YELLOW}7.{Style.RESET_ALL} 全部分析 — 字幕+ASR+抽帧（智能判断，字幕不足时下载）")
    mode_choice = input(f"\n{Fore.CYAN}选择 (1-7, 回车=默认7): {Style.RESET_ALL}").strip()
    if mode_choice in mode_map:
        force_mode = mode_map[mode_choice]
        print(f"{Fore.GREEN}[OK] 分析方式: {mode_choice} - {force_mode}{Style.RESET_ALL}")
    else:
        print(f"{Fore.CYAN}[OK] 分析方式: 默认智能流程{Style.RESET_ALL}")

    # ── 第三步：客观分析视频（覆盖心情为客观模式）──
    original_custom = MOOD_CUSTOM_ENABLED
    original_custom_value = MOOD_CUSTOM_VALUE
    try:
        globals()['MOOD_CUSTOM_ENABLED'] = True
        globals()['MOOD_CUSTOM_VALUE'] = "客观冷静分析，专注内容质量，不带个人情绪"
    except Exception as e:
        log(f'非预期异常: {e}', 'WARN')

    print(f"\n{Fore.CYAN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}|  [模式] 客观分析 - 开始解析视频内容                           |{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+============================================================+{Style.RESET_ALL}")

    # [RETRY] 视频理解 + AI交叉验证重试循环（最多8次）
    # 每次获取字幕后先让AI对比标题验证内容是否匹配，不匹配则回退到ASR重试
    MAX_UNDERSTAND_RETRIES = 8
    subtitle_text = ""
    for understand_retry in range(MAX_UNDERSTAND_RETRIES):
        if understand_retry > 0:
            print(f"\n{Fore.YELLOW}[RETRY] 第{understand_retry+1}/{MAX_UNDERSTAND_RETRIES}次尝试，强制ASR+视觉帧理解...{Style.RESET_ALL}")
            brain.bili._video_meta_cache.pop(bvid, None)

        print(f"\n{Fore.CYAN}[1/4] 理解视频内容 (字幕/ASR)...{Style.RESET_ALL}")
        success, subtitle_text = await brain.understand_video_for_decision(bvid, title=title, force_mode=force_mode)
        if success:
            preview = subtitle_text[:200].replace('\n', ' ')
            print(f"{Fore.GREEN}[OK] 视频内容获取成功: {preview}...{Style.RESET_ALL}")
        else:
            subtitle_text = f"[理解受限] {subtitle_text}"
            print(f"{Fore.YELLOW}[WARN] 视频理解受限: {subtitle_text[:120]}{Style.RESET_ALL}")
            # 检测不可恢复的失败：无字幕 + 无API Key → 重试无意义
            permanent_fail = any(kw in subtitle_text for kw in [
                "未配置 API Key", "API Key 未配置", "无有效CC字幕",
                "Cookie文件不存在", "需要B站登录"
            ])
            if permanent_fail:
                log(f"[MANUAL] 检测到不可恢复的失败，跳过重试", "MANUAL")
                break
            if understand_retry < MAX_UNDERSTAND_RETRIES - 1:
                wait = 1.5 * (understand_retry + 1)
                log(f"[RETRY] 视频理解失败，{wait:.1f}s后重试...", "MANUAL")
                await asyncio.sleep(wait)
                continue
            break

        # AI交叉验证：字幕是否与标题匹配？（仅在"字幕严格校验"开启时执行）
        if SUBTITLE_STRICT_CHECK and len(subtitle_text) > 30 and title and not subtitle_text.startswith("[理解受限]"):
            is_match, match_conf, match_reason = await _ai_cross_check_subtitle_match(
                brain, title, subtitle_text[:2000]
            )
            if not is_match and match_conf < 0.4:
                log(f"[RETRY] AI交叉验证: 字幕与标题不匹配(conf={match_conf:.2f}): {match_reason}", "MANUAL")
                if understand_retry < MAX_UNDERSTAND_RETRIES - 1:
                    print(f"{Fore.YELLOW}[RETRY] 字幕疑似不匹配，将重试...{Style.RESET_ALL}")
                    await asyncio.sleep(1.5 * (understand_retry + 1))
                    continue
                else:
                    log(f"[WARN] 已达最大重试次数，使用当前内容继续分析", "MANUAL")
            else:
                log(f"[OK] AI交叉验证通过(conf={match_conf:.2f}): {match_reason}", "MANUAL")
        break

    # 2. 评论+弹幕
    print(f"\n{Fore.CYAN}[2/4] 获取评论区讨论...{Style.RESET_ALL}")
    try:
        meta = await brain.bili._wbi_get(
            'https://api.bilibili.com/x/web-interface/view',
            params={'bvid': bvid}
        )
        vinfo = meta.json()
        aid = vinfo.get('data', {}).get('aid', 0) if vinfo.get('code') == 0 else 0
    except Exception:
        aid = 0

    comment_text = "[未读取评论]"
    c_list = []
    danmaku_text = ""
    if aid:
        try:
            comment_text, c_list = await _manual_api_retry(
                lambda: brain._get_comments_context(aid),
                "获取评论区", fallback=("[未读取评论]", []), max_retries=2
            )
            if isinstance(comment_text, tuple):
                comment_text, c_list = comment_text
            if c_list:
                print(f"{Fore.GREEN}[OK] 获取到 {len(c_list)} 条评论{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 评论区无内容{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] 评论获取失败: {e}{Style.RESET_ALL}")

        try:
            danmaku_list = await _manual_api_retry(
                lambda: brain.maybe_read_danmaku(bvid, force=True),
                "获取弹幕", fallback=[], max_retries=2
            )
            if danmaku_list:
                danmaku_text = f"【弹幕（共{len(danmaku_list)}条）】:\n" + "\n".join(
                    f"  {dm.get('text','')}" for dm in danmaku_list[:15]
                )
                print(f"{Fore.GREEN}[OK] 获取到 {len(danmaku_list)} 条弹幕{Style.RESET_ALL}")
        except Exception as e:
            log(f'非预期异常: {e}', 'WARN')

    # 3. AI决策分析（客观模式）- 支持3次重试
    MAX_AI_DECISION_RETRIES = 3
    score = 0
    thought = ""
    learning_topic = ""
    decision_mode_str = ""
    for decision_retry in range(MAX_AI_DECISION_RETRIES):
        if decision_retry > 0:
            print(f"{Fore.YELLOW}[RETRY] AI决策第{decision_retry+1}/{MAX_AI_DECISION_RETRIES}次尝试...{Style.RESET_ALL}")
            await asyncio.sleep(2.0 * decision_retry)
        else:
            print(f"\n{Fore.CYAN}[3/4] AI客观决策分析中...{Style.RESET_ALL}")

        objective_prompt = SYSTEM_PROMPT_BRAIN.replace("{bot_name}", get_bot_name()).replace("{memory_ups}", str(brain.get_known_up_names()))
        objective_prompt = objective_prompt.replace(
            "【性格模式】掷硬币决定：- **夸夸模式**：真诚赞美。 - **吐槽模式**：犀利毒舌。",
            "【性格模式】客观分析模式：基于内容质量公正评分，不随机切换夸夸/吐槽。\n"
            "评分标准：\n"
            "1. 标题与内容匹配度（是否标题党）\n"
            "2. 信息价值——深度分析类看观点深度，新闻汇总类看信息广度/信息量，技术教程类看实用性/可操作性\n"
            "3. 制作质量\n"
            "⚠️ 注意：不同类型的视频有不同的价值维度。'信息差/新闻汇总'类视频的价值在于快速覆盖多个热点话题提供的信息广度，不要统一用深度分析的标准去评判。只要有真实信息量的新闻汇总就应当认可。"
        )
        if intent:
            objective_prompt += f"\n\n【用户额外要求】{intent}"

        context = (f"视频标题: {title}\nUP主: {up_name}\n"
                   f"【📺 视频内容字幕】: {subtitle_text}\n"
                   f"{comment_text}"
                   f"{danmaku_text}")

        try:
            resp = await brain._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": objective_prompt},
                    {"role": "user", "content": context}
                ],
                request_timeout=120
            )
            raw = resp.choices[0].message.content
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end >= start:
                json_str = raw[start:end + 1]
            else:
                raise ValueError(f"AI返回未找到JSON: {raw[:200]}")

            try:
                decision = json.loads(json_str)
            except json.JSONDecodeError:
                fixed = json_str.replace("'", '"')
                fixed = re.sub(r'\bTrue\b', 'true', fixed)
                fixed = re.sub(r'\bFalse\b', 'false', fixed)
                fixed = re.sub(r'\bNone\b', 'null', fixed)
                decision = json.loads(fixed)

            score = decision.get('score', 0)
            thought = decision.get('thought', '')
            decision_mode_str = decision.get('mode', '')
            learning_topic = decision.get('learning_topic', '')
            break

        except Exception as e:
            print(f"{Fore.RED}[ERROR] AI决策失败: {_mask_urls(str(e)[:200])}{Style.RESET_ALL}")
            if decision_retry < MAX_AI_DECISION_RETRIES - 1:
                continue
            score = 0
            thought = ""
            learning_topic = ""

    # ── 显示分析结果 ──
    print(f"{Fore.CYAN}+------------------------------------------------------------+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}|  [分析结果]                                                  |{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+------------------------------------------------------------+{Style.RESET_ALL}")
    print(f"  AI评分: {Fore.YELLOW}{score}/10{Style.RESET_ALL}")
    print(f"  AI想法: {thought}")
    if decision_mode_str:
        print(f"  模式: {decision_mode_str}")
    if learning_topic:
        print(f"  主题: {learning_topic}")
    print(f"{Fore.CYAN}+------------------------------------------------------------+{Style.RESET_ALL}")

    # ── 恢复心情设置 ──
    try:
        globals()['MOOD_CUSTOM_ENABLED'] = original_custom
        globals()['MOOD_CUSTOM_VALUE'] = original_custom_value
    except Exception as e:
        log(f'非预期异常: {e}', 'WARN')

    # 4. 如果干货 → 学习归档
    if score >= LEARN_MIN_SCORE or learning_topic:
        print(f"\n{Fore.CYAN}[4/4] 检测到有价值内容，触发学习归档...{Style.RESET_ALL}")
        learn_text = subtitle_text
        if not learn_text or "[无可用字幕" in str(learn_text) or "[未读取" in str(learn_text):
            learn_text = f"【视频标题】{title}\n【AI判断】{thought}\n"
            if danmaku_text:
                learn_text += f"{danmaku_text}\n"
            if comment_text and comment_text != "[未读取评论]":
                learn_text += f"{comment_text}\n"
            learn_text = learn_text.strip()

        if not learning_topic:
            learning_topic = title[:15] if title else "手动分析"

        if learn_text and len(learn_text) > 20:
            try:
                _desc = getattr(brain, "_last_video_desc", "")
                learn_success = await brain.learn_from_video(bvid, title, up_name, video_url, learn_text, learning_topic, video_desc=_desc, score=score)
                if learn_success:
                    print(f"{Fore.GREEN}[OK] 知识已归档到知识库！{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}[INFO] 该知识可能已存在，跳过归档{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] 学习归档失败: {e}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}[INFO] 可学习内容不足，跳过归档{Style.RESET_ALL}")
    else:
        print(f"\n{Fore.CYAN}[4/4] 评分 {score}/10 < {LEARN_MIN_SCORE}，内容质量一般，跳过学习归档{Style.RESET_ALL}")

    print(f"\n{Fore.GREEN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.GREEN}|  手动视频分析完成！                                         |{Style.RESET_ALL}")
    print(f"{Fore.GREEN}+============================================================+{Style.RESET_ALL}")
    print()


# ==============================================================================
# [REVISIT] 知识库视频重温优化
# ==============================================================================

def _scan_knowledge_base_md_files():
    """扫描 KnowledgeBase/ 下所有 .md 文件，提取 [BVxxx] 视频信息。
    返回: [(bvid, title, file_path, up, category_path), ...]"""
    results = []
    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        return results

    for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in files:
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(root, fname)
            # 提取 BV 号: [BVxxx] - 标题.md
            bv_match = re.match(r'^\[(BV[0-9A-Za-z]{10})\]\s*-\s*(.+)\.md$', fname)
            if not bv_match:
                continue
            bvid = bv_match.group(1)
            title = bv_match.group(2).strip()
            rel_path = os.path.relpath(fpath, KNOWLEDGE_BASE_DIR)
            # 尝试从文件头部读取 UP主 信息
            up_name = ""
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    head = f.read(800)
                    up_m = re.search(r'\*\*UP主\*\*:\s*(.+)', head)
                    if up_m:
                        up_name = up_m.group(1).strip()
            except Exception as e:
                log(f'非预期异常: {e}', 'WARN')
            # 分类路径: 去掉文件名后的目录部分
            category_path = os.path.dirname(rel_path).replace(os.sep, '/')
            if not category_path or category_path == '.':
                category_path = '未分类'
            results.append((bvid, title, fpath, up_name, category_path))
    # 按分类路径排序
    results.sort(key=lambda x: (x[4], x[1]))
    return results


# Agent模式可用工具的常量定义
AGENT_TOOLS_HELP = """你拥有以下工具能力，在回复中使用 [TOOL:工具名] 参数 的格式来调用。可以同时调用多个工具：

1. [TOOL:fetch_subtitles]
   获取视频的AI字幕/CC字幕文本（仅获取字幕，不做AI分析）。
   **是视频内容分析的第一步，拿到字幕后才能判断后续操作。**

2. [TOOL:search_knowledge] 搜索词
   在知识库中搜索相关内容，返回匹配的文件路径和摘要
   
3. [TOOL:read_file] 相对路径
   读取知识库中的指定文件内容，路径相对于 KnowledgeBase/ 目录
   例: [TOOL:read_file] 科技/AI工具/video_creation/[BVxxx] - 标题.md

4. [TOOL:list_files] 可选分类路径
   列出知识库文件，不传参数=列出全部，传路径=列出子目录
   例: [TOOL:list_files] 科技

5. [TOOL:delete_file] 相对路径
   删除知识库中的指定文件（需确认，会提示用户）

6. [TOOL:update_file] 相对路径
   ---新内容---
   替换/更新知识库文件的全部内容（需确认）
   例: [TOOL:update_file] 科技/AI工具/[BVxxx] - 标题.md
   ---
   新的完整Markdown内容...

7. [TOOL:analyze_video]
   触发完整的视频分析：封面+字幕/ASR/视觉帧+评论+弹幕 → AI决策 → 学习归档
   **仅在已拿到字幕且确实需要深度分析时使用。**

8. [TOOL:quick_preview]
   只看标题/简介/评论/弹幕，不做完整视频分析，快速了解视频热度/反馈
   **不获取视频字幕/内容！想分析内容先调用 fetch_subtitles。**

9. [TOOL:open_file] 文件绝对路径
   用系统默认程序打开任意文件（md→记事本/Typora, html→浏览器 等）
   例: [TOOL:open_file] C:\\Users\\用户名\\Desktop\\视频总结.md
   **仅在update_file写文件成功后使用。路径必须用双反斜杠 \\\\ 分隔。**

[TASK:✗ 任务描述] 添加一个待办任务（显示为 ✗ 未完成）
[TASK:✓ 任务描述] 标记一个任务为已完成（显示为 ✓ 已完成）

使用说明：
- 当你接收用户指令后，先用 [TASK:✗] 列出你规划的所有步骤，再开始调用 [TOOL:]
- 每完成一个步骤，用 [TASK:✓ 同描述] 标记它已完成
- 任务看板会自动渲染在对话中，让用户看到进度
- 所有任务完成后输出 [DONE]

工作流程：
- 用户提出要求 → 第一步：规划任务 → 第二步：逐个执行 → 第三步：汇报结果
- 用户提到"字幕"/"内容"/"分析视频/总结"等 → 必须先 [TOOL:fetch_subtitles]
- 用户只要热度/评论反馈 → 可以用 [TOOL:quick_preview]
- 拿到字幕后，按用户要求分析/总结/归档
- 可一次调用多个工具以提高效率"""


async def _one_sentence_agent(brain, bvid, title, up_name, video_url, aid=0):
    """🤖 一句话Agent模式：用户说一句话，AI自动规划任务→逐步执行→汇报结果。
    
    和 _agent_video_analysis 共享相同的内核，但：
    - 用户只输入一次指令
    - AI自动跑完所有步骤后输出 [DONE]
    - 无需多轮对话确认
    """
    print(f"\n{Fore.LIGHTBLUE_EX}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLUE_EX}|  🤖 一句话Agent - 全自动执行模式                          |{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLUE_EX}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}[Agent] 视频: {title[:50]}{Style.RESET_ALL}")

    # 让用户输入一句话指令
    prompt_text = f"{Fore.CYAN}说一句话，AI自动处理 (如「帮我总结视频内容并生成文档」): {Style.RESET_ALL}"
    user_msg = input(f"\n{prompt_text}").strip()
    if not user_msg:
        print(f"{Fore.YELLOW}[WARN] 指令为空，退出{Style.RESET_ALL}")
        return

    # 用 _agent_video_analysis 的内核，但注入这个单条消息并自动运行
    # AGENT_TOOLS_HELP 是模块级全局变量，直接可用
    
    messages = [
        {"role": "system", "content": f"""你是bilibili_learning_bot的Agent助手，负责帮用户分析B站视频并管理知识库。

当前视频信息:
- 标题: {title}
- UP主: {up_name}
- BV号: {bvid}
- 链接: {video_url}

{AGENT_TOOLS_HELP}

重要规则:
1. 用户只说了一句话，你需要自己规划全部步骤并执行完成
2. 用 [TASK:✗ 步骤名] 列出你的计划，逐步完成
3. 完成一步就标记 [TASK:✓ 步骤名]
4. 全部完成后输出 [DONE]
5. 不要等待用户确认，直接执行所有需要的操作"""},
        {"role": "user", "content": user_msg}
    ]

    # 任务看板
    task_board = []
    def _render_task_board():
        if not task_board:
            return ""
        lines = ["\n" + Fore.CYAN + "📋 任务看板:" + Style.RESET_ALL]
        for t in task_board:
            icon = Fore.GREEN + "✓" + Style.RESET_ALL if t["done"] else Fore.RED + "✗" + Style.RESET_ALL
            status = Fore.LIGHTBLACK_EX + "(完成)" + Style.RESET_ALL if t["done"] else Fore.YELLOW + "(进行中)" + Style.RESET_ALL
            lines.append(f"  {icon} {t['task']} {status}")
        return "\n".join(lines)

    def _parse_tasks(text):
        nonlocal task_board
        task_pattern = re.compile(r'\[TASK:([✓✗])\s*(.*?)\]')
        for match in task_pattern.finditer(text):
            status = match.group(1)
            task_desc = match.group(2).strip()
            if status == "✗":
                if not any(t["task"] == task_desc for t in task_board):
                    task_board.append({"task": task_desc, "done": False})
            elif status == "✓":
                for t in task_board:
                    if t["task"] == task_desc and not t["done"]:
                        t["done"] = True
                        break
                else:
                    if not any(t["task"] == task_desc for t in task_board):
                        task_board.append({"task": task_desc, "done": True})

    # 提取 _agent_video_analysis 里的内联函数引用
    # 需要复用的 helpers
    async def _inner_fetch_subtitles():
        # 复用 _agent_fetch_subtitles 逻辑
        print(f"{Fore.CYAN}[Agent] 获取视频字幕...{Style.RESET_ALL}")
        try:
            cookies = getattr(brain, 'cookies', None)
            ok, subs, _desc, _sub_ai = await fetch_bilibili_subtitles(bvid, cookies)
            if ok and subs and len(subs) > 100:
                subtitle_text = subs
                print(f"{Fore.GREEN}[OK] 获取到B站字幕 ({len(subs)}字){Style.RESET_ALL}")
                return subs
            else:
                # 尝试完整理解
                ok2, subs2 = await brain.understand_video_for_decision(bvid, title=title)
                if ok2 and subs2 and len(subs2) > 100:
                    return subs2
                return f"[无字幕] {subs}"
        except Exception as e:
            return f"[字幕获取失败] {e}"

    async def _inner_analyze_video():
        # 复用 agent_analyze_video
        subtitle_text = ""
        success, subtitle_text = await brain.understand_video_for_decision(bvid, title=title)
        if not success:
            subtitle_text = f"[理解受限] {subtitle_text}"

        # 评论+弹幕
        comment_text = "[未读取评论]"
        danmaku_text = ""
        try:
            meta = await brain.bili._wbi_get('https://api.bilibili.com/x/web-interface/view', params={'bvid': bvid})
            vinfo = meta.json()
            aid2 = vinfo.get('data', {}).get('aid', 0) if vinfo.get('code') == 0 else 0
            if aid2:
                c_text, c_list = await brain._get_comments_context(aid2)
                if isinstance(c_text, tuple):
                    c_text, c_list = c_text
                comment_text = c_text or "[无评论]"
                d_list = await brain.maybe_read_danmaku(bvid, force=True)
                if d_list:
                    danmaku_text = "【弹幕】:\n" + "\n".join(f"  {d.get('text','')}" for d in d_list[:10])
        except Exception:
            pass

        # AI决策
        objective_prompt = SYSTEM_PROMPT_BRAIN.replace("{bot_name}", get_bot_name()).replace("{memory_ups}", str(brain.get_known_up_names()))
        objective_prompt = objective_prompt.replace(
            "【性格模式】掷硬币决定：- **夸夸模式**：真诚赞美。 - **吐槽模式**：犀利毒舌。",
            "【性格模式】客观分析模式：基于内容质量公正评分，不随机切换夸夸/吐槽。\n"
            "评分标准：\n"
            "1. 标题与内容匹配度（是否标题党）\n"
            "2. 信息价值——深度分析类看观点深度，新闻汇总类看信息广度/信息量，技术教程类看实用性/可操作性\n"
            "3. 制作质量\n"
            "⚠️ 注意：不同类型的视频有不同的价值维度。'信息差/新闻汇总'类视频的价值在于快速覆盖多个热点话题提供的信息广度，不要统一用深度分析的标准去评判。只要有真实信息量的新闻汇总就应当认可。"
        )
        context = f"视频标题: {title}\nUP主: {up_name}\n【字幕】: {subtitle_text[:2000]}\n{comment_text}\n{danmaku_text}"
        try:
            resp = await brain._call_ai_with_retry(model=MODEL_BRAIN, messages=[{"role":"system","content":objective_prompt},{"role":"user","content":context}], request_timeout=120)
            raw = resp.choices[0].message.content
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end >= start:
                decision = json.loads(raw[start:end+1])
            else:
                decision = {}
            score = decision.get('score', 0)
            thought = decision.get('thought', '')
            learning_topic = decision.get('learning_topic', '')
        except Exception as e:
            score, thought, learning_topic = 0, f"AI决策失败: {e}", ""

        return f"【分析结果】\n评分: {score}/10\n想法: {thought}\n主题: {learning_topic}\n字幕: {subtitle_text[:200] if subtitle_text else '无'}...\n评论: {len(comment_text)}字\n弹幕: {len(danmaku_text)}字"

    # 自动执行循环（类似 _agent_video_analysis 的内层循环）
    MAX_AUTO_TURNS = 15
    task_done = False

    for _turn in range(MAX_AUTO_TURNS):
        print(f"{Fore.CYAN}[Agent] AI思考中...{Style.RESET_ALL}")
        try:
            resp = await brain._call_ai_with_retry(model=MODEL_BRAIN, messages=messages, request_timeout=90)
            ai_text = resp.choices[0].message.content
        except Exception as e:
            print(f"{Fore.RED}[Agent] AI调用失败: {e}{Style.RESET_ALL}")
            break

        messages.append({"role": "assistant", "content": ai_text})

        # 解析TASK + TOOL + DONE
        _parse_tasks(ai_text)
        tool_pattern = re.compile(r'\[TOOL:(\w+)\]\s*(.*?)(?=\[TOOL:|\[DONE\]|$)', re.DOTALL)
        stop_pattern = re.compile(r'\[DONE\]')
        done_match = stop_pattern.search(ai_text)
        tool_matches = tool_pattern.findall(ai_text)

        # 显示AI回复（去掉标记）
        display_text = ai_text
        for tn, tb in tool_matches:
            display_text = display_text.replace(f"[TOOL:{tn}] {tb}", "")
        if done_match:
            display_text = display_text.replace("[DONE]", "")
        display_text = re.sub(r'\[TASK:[✓✗]\s*.*?\]', '', display_text)
        display_text = display_text.strip()
        if display_text:
            print(f"\n{Fore.LIGHTGREEN_EX}[Agent] AI > {Style.RESET_ALL}{display_text}")

        # 渲染任务看板
        board = _render_task_board()
        if board:
            print(board)

        if done_match and not tool_matches:
            print(f"\n{Fore.GREEN}[Agent] ✅ 一句话任务全部完成！{Style.RESET_ALL}")
            task_done = True
            break

        # 执行工具
        for tool_name, tool_body in tool_matches:
            tool_body = tool_body.strip()
            print(f"\n{Fore.YELLOW}[Agent] 执行工具: {tool_name}...{Style.RESET_ALL}")
            tool_result = ""

            if tool_name == "fetch_subtitles":
                tool_result = await _inner_fetch_subtitles()
            elif tool_name == "analyze_video":
                tool_result = await _inner_analyze_video()
            elif tool_name == "quick_preview":
                # 简化版 quick_preview
                try:
                    meta = await brain.bili._wbi_get('https://api.bilibili.com/x/web-interface/view', params={'bvid': bvid})
                    vinfo = meta.json()
                    desc = vinfo.get('data', {}).get('desc', '')
                    tool_result = f"标题: {title}\n简介: {desc[:300]}"
                except Exception as e:
                    tool_result = f"预览失败: {e}"
            elif tool_name == "search_knowledge":
                tool_result = "搜索功能: " + tool_body[:100]
            else:
                tool_result = f"工具 {tool_name} 不可用（一句话模式仅支持基础工具）"

            result_preview = tool_result[:400]
            print(f"{Fore.GREEN}[Agent] 结果: {result_preview}{Style.RESET_ALL}")
            messages.append({"role": "system", "content": f"[工具 {tool_name} 执行结果]:\n{tool_result}\n\n请继续。如需更多工具可继续调用，完成则输出 [DONE]。"})

        if done_match:
            task_done = True
            break

        if tool_matches:
            print(f"{Fore.CYAN}[Agent] 自动继续...{Style.RESET_ALL}")
            messages.append({"role": "user", "content": "[自动继续] 请基于工具结果继续执行。全部完成后输出 [DONE]。"})
        else:
            print(f"{Fore.YELLOW}[Agent] AI未调用工具，尝试继续...{Style.RESET_ALL}")
            messages.append({"role": "user", "content": "请继续你的分析，完成所有步骤后输出 [DONE]。"})

    if not task_done:
        print(f"{Fore.YELLOW}[Agent] 已达到最大自动轮次，自动结束{Style.RESET_ALL}")

    print(f"{Fore.LIGHTBLUE_EX}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLUE_EX}|  一句话Agent执行完毕                                       |{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLUE_EX}+============================================================+{Style.RESET_ALL}")


async def _agent_video_analysis(brain, bvid, title, up_name, video_url, aid=0):
    """Agent对话模式：多轮对话确定目标、搜索知识库、增删改查文件、智能分析视频。
    
    工具:
    - search_knowledge: 搜索知识库文件
    - read_file: 读取指定 .md 文件
    - list_files: 列出知识库文件
    - update_file: 更新/替换知识库文件
    - delete_file: 删除知识库文件
    - analyze_video: 触发完整视频分析管道
    - quick_preview: 只看标题/简介/评论/弹幕
    """
    print(f"\n{Fore.LIGHTMAGENTA_EX}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.LIGHTMAGENTA_EX}|  🤖 Agent对话模式 - 多轮对话 + 文件CRUD + 智能分析          |{Style.RESET_ALL}")
    print(f"{Fore.LIGHTMAGENTA_EX}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}[Agent] 视频: {title[:50]}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}[Agent] 输入你的要求，AI会提问/搜索知识库/增删改查文件/决定如何分析{Style.RESET_ALL}")
    print(f"{Fore.CYAN}[Agent] 命令: /help 帮助 | /exit 退出 | /files 列文件 | /done 直接分析{Style.RESET_ALL}")
    print(f"{Fore.LIGHTMAGENTA_EX}+------------------------------------------------------------+{Style.RESET_ALL}")

    # 缓存已分析结果
    analysis_cache = {
        "analyzed": False,
        "subtitle_text": "",
        "comment_text": "",
        "c_list": [],
        "danmaku_text": "",
        "score": 0,
        "thought": "",
        "learning_topic": "",
    }

    # 本次会话自动允许的工具集合（用户选了"一直允许"后加入）
    auto_allow_tools = set()

    # 任务看板：跟踪待办/已完成任务
    task_board = []  # [{"task": "分析视频字幕", "done": False}, ...]

    def _render_task_board():
        """渲染任务看板为字符串"""
        if not task_board:
            return ""
        lines = ["\n" + Fore.CYAN + "📋 任务看板:" + Style.RESET_ALL]
        for t in task_board:
            icon = Fore.GREEN + "✓" + Style.RESET_ALL if t["done"] else Fore.RED + "✗" + Style.RESET_ALL
            status = Fore.LIGHTBLACK_EX + "(完成)" + Style.RESET_ALL if t["done"] else Fore.YELLOW + "(进行中)" + Style.RESET_ALL
            lines.append(f"  {icon} {t['task']} {status}")
        return "\n".join(lines)

    def _parse_tasks(text):
        """从AI回复中解析 [TASK:✗ 描述] 和 [TASK:✓ 描述] 标记"""
        nonlocal task_board
        task_pattern = re.compile(r'\[TASK:([✓✗])\s*(.*?)\]')
        for match in task_pattern.finditer(text):
            status = match.group(1)
            task_desc = match.group(2).strip()
            if status == "✗":
                # 添加新任务（去重）
                if not any(t["task"] == task_desc for t in task_board):
                    task_board.append({"task": task_desc, "done": False})
            elif status == "✓":
                # 标记完成
                for t in task_board:
                    if t["task"] == task_desc and not t["done"]:
                        t["done"] = True
                        break
                else:
                    # 找不到对应任务也加上（可能AI直接标记完成）
                    if not any(t["task"] == task_desc for t in task_board):
                        task_board.append({"task": task_desc, "done": True})

    # 对话历史
    messages = [
        {"role": "system", "content": f"""你是bilibili_learning_bot的Agent助手，负责帮用户分析B站视频并管理知识库。

当前视频信息:
- 标题: {title}
- UP主: {up_name}
- BV号: {bvid}
- 链接: {video_url}

{AGENT_TOOLS_HELP}

重要规则:
1. 用中文回复，简洁专业
2. 先理解用户意图，可以反问缩小目标
3. 善用搜索/读取知识库，对比已有知识
4. 文件操作(update/delete)前要说明理由并等待用户确认
5. 可以同时调用多个工具，尤其 fetch_subtitles+search_knowledge 可并行
6. 任务完成或用户满意时输出 [DONE]

工作流程（与"直接分析模式"一致）：
- 用户要求分析视频/总结内容 → 第一步 [TOOL:fetch_subtitles] 获取字幕
- 拿到字幕后 → 调用 [TOOL:analyze_video] 做完整评分分析（含评论弹幕+AI决策+归档）
- 分析完成后 → 根据用户要求输出总结/写文件/打开文件
- 用户如中途要调整方向（如只总结某部分/改输出格式），在上一步完成后提出来即可
- 不要用 quick_preview 替代 fetch_subtitles（quick_preview 不看视频内容！）
- 写文件后如果用户要求打开，用 [TOOL:open_file] 绝对路径 打开它

自动连续模式（重要！）：
- 用户一句话包含了"分析+总结+写桌面+打开"这种多步需求时，你在同一轮回复中依次列出所有 [TOOL:] 步骤
- 例如用户说"帮我分析视频总结到桌面并打开" → 你回复:
  好的，我来一步到位：
  [TOOL:fetch_subtitles]
  （系统会自动继续执行后续工具，你只需列出第一步）
- 如果工具执行结果返回后任务未完成，系统会自动再次调用你继续，无需等待用户输入
- 所有步骤完成后输出 [DONE] 结束"""},
    ]

    # ── Agent 确认函数：4选1（本次允许 / 一直允许 / 不允许 / AI审查） ──
    async def _agent_confirm(tool_name: str, action_desc: str, detail: str = "") -> str:
        """通用确认对话框，返回: 'allow' | 'always' | 'deny' | 'ai_review'
        
        - allow: 仅本次允许
        - always: 一直允许（当前视频会话内该工具自动放行）
        - deny: 拒绝本次操作
        - ai_review: 让AI自动审查安全性后决定
        """
        # 如果该工具已被加入"一直允许"，直接放行
        if tool_name in auto_allow_tools:
            return "always"

        print(f"\n{Fore.YELLOW}╔══════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}║  [Agent权限确认] {tool_name}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}╠══════════════════════════════════════════════════════════╣{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}║  {action_desc}{Style.RESET_ALL}")
        if detail:
            # 截断过长细节
            detail_short = detail[:200] + ("..." if len(detail) > 200 else "")
            print(f"{Fore.CYAN}║  详情: {detail_short}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}╠══════════════════════════════════════════════════════════╣{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}║{Style.RESET_ALL}  {Fore.GREEN}1.{Style.RESET_ALL} 本次允许    {Fore.LIGHTGREEN_EX}2.{Style.RESET_ALL} 一直允许(本视频)    {Fore.RED}3.{Style.RESET_ALL} 不允许")
        print(f"{Fore.YELLOW}║{Style.RESET_ALL}  {Fore.CYAN}4.{Style.RESET_ALL} AI自动审查")
        print(f"{Fore.YELLOW}╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

        choice = input(f"{Fore.CYAN}[Agent] 选择 (1-4, 回车=1): {Style.RESET_ALL}").strip()

        if choice == "2":
            auto_allow_tools.add(tool_name)
            print(f"{Fore.GREEN}[Agent] 已设置: 本视频会话内 {tool_name} 自动放行{Style.RESET_ALL}")
            return "always"
        elif choice == "3":
            print(f"{Fore.RED}[Agent] 已拒绝本次操作{Style.RESET_ALL}")
            return "deny"
        elif choice == "4":
            print(f"{Fore.CYAN}[Agent] 启动AI安全审查...{Style.RESET_ALL}")
            return "ai_review"
        else:
            # 默认=本次允许（包括回车和输入1）
            return "allow"

    async def _agent_ai_review(tool_name: str, action_desc: str, detail: str = "") -> bool:
        """AI自动审查：调用AI判断该操作是否安全合理"""
        review_prompt = f"""你是安全审查助手。Agent要执行以下操作，请判断是否安全合理：

工具: {tool_name}
操作: {action_desc}
详情: {detail[:500]}

判断标准：
- 删除/修改知识库文件是否合理（不会误删重要数据）
- 操作范围是否在知识库目录内
- 是否可能造成数据丢失

只返回JSON: {{"safe": true/false, "reason": "简短理由(20字内)"}}"""

        try:
            resp = await brain._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[{"role": "user", "content": review_prompt}],
                request_timeout=30
            )
            raw = resp.choices[0].message.content
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end >= start:
                decision = json.loads(raw[start:end+1])
                safe = decision.get("safe", True)
                reason = decision.get("reason", "无")
                if safe:
                    print(f"{Fore.GREEN}[Agent] AI审查通过: {reason}{Style.RESET_ALL}")
                    return True
                else:
                    print(f"{Fore.RED}[Agent] AI审查不通过: {reason}{Style.RESET_ALL}")
                    return False
            else:
                print(f"{Fore.YELLOW}[Agent] AI审查无法解析，默认放行{Style.RESET_ALL}")
                return True
        except Exception as e:
            print(f"{Fore.YELLOW}[Agent] AI审查异常({e})，默认放行{Style.RESET_ALL}")
            return True

    def _agent_list_files(cat_path=""):
        """列出知识库文件"""
        all_files = _scan_knowledge_base_md_files()
        if not all_files:
            return "知识库为空，没有已学习的视频"
        if cat_path:
            filtered = [(b,t,f,u,c) for b,t,f,u,c in all_files if c.startswith(cat_path)]
            if not filtered:
                return f"分类 '{cat_path}' 下没有文件"
            result = f"分类 '{cat_path}' 下的文件 ({len(filtered)}个):\n"
            for b, t, f, u, c in filtered:
                result += f"  [{b}] {t[:50]} | {c}\n"
            return result.strip()
        # 按分类统计
        from collections import Counter
        cats = Counter(c for _,_,_,_,c in all_files)
        result = f"知识库共 {len(all_files)} 个文件:\n"
        for cat, cnt in sorted(cats.items()):
            result += f"  {cat}/ ({cnt}个)\n"
        return result.strip()

    def _agent_search_knowledge(query):
        """搜索知识库（向量语义搜索 + 关键词匹配）"""
        all_files = _scan_knowledge_base_md_files()
        if not all_files:
            return "知识库为空"

        # 尝试向量搜索
        vector_hits = set()
        try:
            if KBSearchEngine:
                from xingye_bot.settings import load_settings as _ls
                from xingye_bot.state import BotState as _bs
                _s = _ls()
                _engine = KBSearchEngine(ModelClient(_s, _bs()))
                _vec_results = _engine.search(query, top_k=10)
                if _vec_results:
                    for vr in _vec_results:
                        if vr.get("bvid"):
                            vector_hits.add(vr["bvid"])
        except Exception:
            pass

        q_lower = query.lower()
        matches = []
        for b, t, f, u, c in all_files:
            score = 0
            if vector_hits and b in vector_hits:
                score += 10  # 向量命中最高权重
            if q_lower in t.lower():
                score += 3
            for kw in q_lower.split():
                if kw in t.lower():
                    score += 2
            if u and q_lower in u.lower():
                score += 1
            if score > 0:
                preview = ""
                try:
                    with open(f, 'r', encoding='utf-8') as fh:
                        preview = fh.read(200).replace('\n', ' ')
                except Exception as e:
                    log(f'非预期异常: {e}', 'WARN')
                matches.append((score, b, t, f, u, c, preview))
        matches.sort(key=lambda x: x[0], reverse=True)
        if not matches:
            return f"未找到与 '{query}' 相关的知识文件"
        result = f"搜索 '{query}' 找到 {len(matches)} 个相关文件:\n"
        for i, (s, b, t, f, u, c, p) in enumerate(matches[:10]):
            result += f"  {i+1}. [{b}] {t[:45]} | {c} | 摘要: {p[:60]}...\n"
        return result.strip()

    def _agent_read_file(rel_path):
        """读取知识库文件"""
        full_path = os.path.join(KNOWLEDGE_BASE_DIR, rel_path)
        if not os.path.exists(full_path):
            # 尝试模糊匹配
            all_files = _scan_knowledge_base_md_files()
            best = None
            for b, t, f, u, c in all_files:
                if rel_path in f or rel_path in t:
                    best = f
                    break
                if b in rel_path:
                    best = f
                    break
            if best:
                full_path = best
                print(f"{Fore.CYAN}[Agent] 模糊匹配到: {os.path.relpath(full_path, KNOWLEDGE_BASE_DIR)}{Style.RESET_ALL}")
            else:
                return f"文件不存在: {rel_path}\n可用 /files 命令查看所有文件"
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if len(content) > 5000:
                content = content[:5000] + "\n\n... (文件过长，已截断至5000字)"
            return f"文件内容 ({os.path.relpath(full_path, KNOWLEDGE_BASE_DIR)}):\n---\n{content}\n---"
        except Exception as e:
            return f"读取失败: {e}"

    async def _agent_delete_file(rel_path):
        """删除知识库文件（需4选1确认）"""
        full_path = os.path.join(KNOWLEDGE_BASE_DIR, rel_path)
        if not os.path.exists(full_path):
            return f"文件不存在: {rel_path}"
        # 先预览文件内容
        preview = ""
        try:
            with open(full_path, 'r', encoding='utf-8') as fh:
                preview = fh.read(300).replace('\n', ' ')
        except Exception as e:
            log(f'非预期异常: {e}', 'WARN')
        action_desc = f"删除知识库文件: {rel_path}"
        detail = f"文件预览: {preview}..."
        result = await _agent_confirm("delete_file", action_desc, detail)
        if result == "deny":
            return "用户取消删除"
        if result == "ai_review":
            if not await _agent_ai_review("delete_file", action_desc, detail):
                return "AI审查不通过，取消删除"
        try:
            os.remove(full_path)
            return f"已删除: {rel_path}"
        except Exception as e:
            return f"删除失败: {e}"

    async def _agent_update_file(rel_path, new_content):
        """更新/新建知识库文件（需4选1确认）"""
        full_path = os.path.join(KNOWLEDGE_BASE_DIR, rel_path)
        exists = os.path.exists(full_path)
        action = "替换" if exists else "新建"
        action_desc = f"{action}知识库文件: {rel_path}"
        detail = f"新内容({len(new_content)}字): {new_content[:150]}..."
        result = await _agent_confirm("update_file", action_desc, detail)
        if result == "deny":
            return f"用户取消{action}"
        if result == "ai_review":
            if not await _agent_ai_review("update_file", action_desc, detail):
                return f"AI审查不通过，取消{action}"
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return f"已{action}: {rel_path} ({len(new_content)}字)"
        except Exception as e:
            return f"写入失败: {e}"

    async def _agent_open_file(file_path: str):
        """用系统默认程序打开文件"""
        import subprocess, platform
        fp = file_path.strip()
        if not os.path.isabs(fp):
            # 尝试在桌面找
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            fp = os.path.join(desktop, fp)
        if not os.path.exists(fp):
            return f"文件不存在: {fp}"
        try:
            if platform.system() == "Windows":
                os.startfile(fp)
            elif platform.system() == "Darwin":
                subprocess.run(["open", fp])
            else:
                subprocess.run(["xdg-open", fp])
            return f"已用系统默认程序打开: {fp}"
        except Exception as e:
            return f"打开失败: {e}"

    async def _agent_fetch_subtitles():
        """获取视频字幕（AI字幕优先，CC字幕备选），缓存结果供后续分析复用"""
        print(f"\n{Fore.CYAN}[Agent] 获取视频字幕...{Style.RESET_ALL}")
        # 已缓存则直接返回
        if analysis_cache.get("subtitle_text"):
            cached_len = len(analysis_cache["subtitle_text"])
            print(f"{Fore.GREEN}[Agent] 使用缓存字幕 ({cached_len}字){Style.RESET_ALL}")
            return analysis_cache["subtitle_text"]

        subtitle_text = ""
        try:
            # 优先直接获取B站AI/CC字幕（快，不走LLM）
            # fetch_bilibili_subtitles 是模块级函数，返回 (success, content, desc, ai_verified)
            cookies = getattr(brain, 'cookies', None)
            ok, subs, _desc, _sub_ai = await fetch_bilibili_subtitles(bvid, cookies)
            if ok and subs and len(subs) > 100:
                subtitle_text = subs
                print(f"{Fore.GREEN}[Agent] 获取到B站字幕 ({len(subs)}字){Style.RESET_ALL}")
            else:
                # 字幕不足，走完整管道（可能触发ASR下载）
                print(f"{Fore.YELLOW}[Agent] B站字幕不足({len(subs) if subs else 0}字)，尝试完整视频理解...{Style.RESET_ALL}")
                success, st = await brain.understand_video_for_decision(bvid, title=title)
                if success and st:
                    subtitle_text = st
        except Exception as e:
            print(f"{Fore.RED}[Agent] 字幕获取异常: {e}{Style.RESET_ALL}")
            subtitle_text = f"[字幕获取失败] {e}"

        # 缓存
        if subtitle_text:
            analysis_cache["subtitle_text"] = subtitle_text
        return subtitle_text or "[无字幕]"

    async def _agent_quick_preview():
        """快速预览：获取标题/简介/评论/弹幕"""
        print(f"\n{Fore.CYAN}[Agent] 快速预览视频信息...{Style.RESET_ALL}")
        # 获取简介
        desc = ""
        try:
            meta = await brain.bili._wbi_get(
                'https://api.bilibili.com/x/web-interface/view',
                params={'bvid': bvid}
            )
            vinfo = meta.json()
            if vinfo.get('code') == 0:
                desc = vinfo['data'].get('desc', '')[:500]
        except Exception as e:
            log(f'非预期异常: {e}', 'WARN')

        # 评论
        comment_text = "[无评论]"
        c_list = []
        if aid:
            try:
                comment_text, c_list = await brain._get_comments_context(aid)
            except Exception as e:
                log(f'非预期异常: {e}', 'WARN')

        # 弹幕
        danmaku_text = ""
        try:
            danmaku_list = await brain.maybe_read_danmaku(bvid)
            if danmaku_list:
                danmaku_text = "\n".join(f"  {dm.get('text','')}" for dm in danmaku_list[:10])
        except Exception as e:
            log(f'非预期异常: {e}', 'WARN')

        preview = f"""【视频信息】
标题: {title}
UP主: {up_name}
简介: {desc[:300] if desc else '无'}

【评论区摘要】
{comment_text[:500]}

【弹幕摘录】
{danmaku_text[:300] if danmaku_text else '无弹幕数据'}"""
        return preview

    async def _agent_analyze_video():
        """完整视频分析管道"""
        print(f"\n{Fore.CYAN}[Agent] 触发完整视频分析管道...{Style.RESET_ALL}")

        # 1. 视频理解（复用缓存字幕）
        print(f"{Fore.CYAN}[Agent] [1/4] 视频内容理解 (字幕/ASR/视觉帧)...{Style.RESET_ALL}")
        if analysis_cache.get("subtitle_text"):
            print(f"{Fore.GREEN}[Agent] 复用已获取的字幕 ({len(analysis_cache['subtitle_text'])}字){Style.RESET_ALL}")
            subtitle_text = analysis_cache["subtitle_text"]
            success = True
        else:
            success, subtitle_text = await brain.understand_video_for_decision(bvid, title=title)
            if success and subtitle_text:
                analysis_cache["subtitle_text"] = subtitle_text
        if not success:
            subtitle_text = f"[理解受限] {subtitle_text}"

        # 2. 评论+弹幕
        comment_text = "[未读取评论]"
        c_list = []
        danmaku_text = ""
        if aid:
            try:
                comment_text, c_list = await brain._get_comments_context(aid)
            except Exception as e:
                log(f'非预期异常: {e}', 'WARN')
            try:
                danmaku_list = await brain.maybe_read_danmaku(bvid)
                if danmaku_list:
                    danmaku_text = "\n".join(f"  {dm.get('text','')}" for dm in danmaku_list[:15])
            except Exception as e:
                log(f'非预期异常: {e}', 'WARN')

        # 3. AI决策
        print(f"{Fore.CYAN}[Agent] [2/4] AI决策分析...{Style.RESET_ALL}")
        objective_prompt = SYSTEM_PROMPT_BRAIN.replace("{bot_name}", get_bot_name()).replace("{memory_ups}", str(brain.get_known_up_names()))
        # Agent 模式特有提示：关注用户交互意图
        objective_prompt += "\n\n【Agent模式】用户会通过对话指定分析目标，请结合对话上下文和用户意图做决策。"
        # 覆盖随机性格：手动分析模式强制客观分析，不掷硬币
        objective_prompt = objective_prompt.replace(
            "【性格模式】掷硬币决定：- **夸夸模式**：真诚赞美。 - **吐槽模式**：犀利毒舌。",
            "【性格模式】客观分析模式：基于内容质量公正评分，不随机切换夸夸/吐槽。\n"
            "评分标准：\n"
            "1. 标题与内容匹配度（是否标题党）\n"
            "2. 信息价值——深度分析类看观点深度，新闻汇总类看信息广度/信息量，技术教程类看实用性/可操作性\n"
            "3. 制作质量\n"
            "⚠️ 注意：不同类型的视频有不同的价值维度。'信息差/新闻汇总'类视频的价值在于快速覆盖多个热点话题提供的信息广度，不要统一用深度分析的标准去评判。只要有真实信息量的新闻汇总就应当认可。"
        )

        context = (f"视频标题: {title}\nUP主: {up_name}\n"
                   f"【视频内容】: {subtitle_text}\n"
                   f"{comment_text}")

        score, thought, learning_topic = 0, "", ""
        try:
            resp = await brain._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": objective_prompt},
                    {"role": "user", "content": context}
                ],
                request_timeout=120
            )
            raw = resp.choices[0].message.content
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end >= start:
                json_str = raw[start:end + 1]
            else:
                json_str = "{}"
            decision = json.loads(json_str)
            score = decision.get('score', 0)
            thought = decision.get('thought', '')
            learning_topic = decision.get('learning_topic', '')
        except Exception as e:
            log(f'非预期异常: {e}', 'WARN')

        # 4. 学习归档
        print(f"{Fore.CYAN}[Agent] [3/4] 学习归档...{Style.RESET_ALL}")
        archived_file = ""
        if score >= LEARN_MIN_SCORE or learning_topic:
            learn_text = subtitle_text
            if not learn_text or len(learn_text) < 30:
                learn_text = f"【视频标题】{title}\n【AI判断】{thought}"
            if not learning_topic:
                learning_topic = title[:15] if title else "手动分析"
            try:
                _desc = getattr(brain, "_last_video_desc", "")
                learn_success = await brain.learn_from_video(
                    bvid, title, up_name, video_url, learn_text, learning_topic, video_desc=_desc, score=score
                )
                if learn_success:
                    print(f"{Fore.GREEN}[Agent] 已归档到知识库{Style.RESET_ALL}")
                    archived_file = f"已归档: [{bvid}] - {title[:30]}.md"
                else:
                    print(f"{Fore.YELLOW}[Agent] 可能已存在，跳过归档{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[Agent] 归档失败: {e}{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}[Agent] 评分 {score}/10 < {LEARN_MIN_SCORE}，未触发归档{Style.RESET_ALL}")

        # 缓存结果
        analysis_cache["analyzed"] = True
        analysis_cache["subtitle_text"] = subtitle_text
        analysis_cache["comment_text"] = comment_text
        analysis_cache["c_list"] = c_list
        analysis_cache["danmaku_text"] = danmaku_text
        analysis_cache["score"] = score
        analysis_cache["thought"] = thought
        analysis_cache["learning_topic"] = learning_topic

        result = f"""【视频分析完成】
AI评分: {score}/10
AI判断: {thought}
学习主题: {learning_topic if learning_topic else '无'}
视频内容摘要: {subtitle_text[:300]}...
评论数: {len(c_list)}条
弹幕数: {len(danmaku_text.split(chr(10))) if danmaku_text else 0}条
{archived_file}"""
        return result

    # =========================================================
    # Agent对话主循环
    # =========================================================
    turn = 0
    MAX_TURNS = 20

    while turn < MAX_TURNS:
        turn += 1
        try:
            user_msg = input(f"\n{Fore.LIGHTMAGENTA_EX}[Agent] 你 > {Style.RESET_ALL}").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{Fore.YELLOW}[Agent] 输入中断，退出Agent模式{Style.RESET_ALL}")
            break

        if not user_msg:
            continue

        # 快捷命令
        if user_msg.lower() == "/exit":
            print(f"{Fore.YELLOW}[Agent] 退出Agent模式{Style.RESET_ALL}")
            break
        if user_msg.lower() == "/help":
            print(f"\n{Fore.CYAN}[Agent] 可用命令:{Style.RESET_ALL}")
            print(f"  /exit  - 退出Agent模式")
            print(f"  /files - 列出知识库所有文件")
            print(f"  /search 关键词 - 搜索知识库")
            print(f"  /done  - 直接触发完整视频分析")
            print(f"  {Fore.YELLOW}直接输入你的要求，AI会智能响应{Style.RESET_ALL}")
            continue
        if user_msg.lower() == "/files":
            result = _agent_list_files()
            print(f"\n{Fore.GREEN}[Agent] {result}{Style.RESET_ALL}")
            continue
        if user_msg.lower().startswith("/search "):
            query = user_msg[8:].strip()
            result = _agent_search_knowledge(query)
            print(f"\n{Fore.GREEN}[Agent] {result}{Style.RESET_ALL}")
            continue
        if user_msg.lower() == "/done":
            # 直接运行完整分析管道（与Enter模式一致）
            print(f"\n{Fore.CYAN}[Agent] /done: 自动运行完整分析管道...{Style.RESET_ALL}")
            # Step 1: 获取字幕
            if not analysis_cache.get("subtitle_text"):
                sub_result = await _agent_fetch_subtitles()
                if sub_result and not sub_result.startswith("[无字幕]") and not sub_result.startswith("[字幕获取失败]"):
                    messages.append({"role": "system", "content": f"[已获取视频字幕 ({len(sub_result)}字)]"})
            # Step 2: 完整分析
            tool_result = await _agent_analyze_video()
            print(f"\n{Fore.GREEN}[Agent] {tool_result}{Style.RESET_ALL}")
            # 把分析结果加入对话，AI可以基于此回复
            messages.append({"role": "system", "content": f"[自动分析完成]:\n{tool_result}\n\n请向用户汇报分析结果。如需输出文件请用update_file工具。"})
            continue

        # 添加用户消息
        messages.append({"role": "user", "content": user_msg})

        # 内层自动连续循环：AI调用 → 工具执行 → 自动继续（无需等用户输入）
        sub_turn = 0
        MAX_SUB_TURNS = 10  # 单次用户输入最多自动连续10轮
        task_done = False

        while sub_turn < MAX_SUB_TURNS:
            sub_turn += 1

            # 调用AI
            print(f"{Fore.CYAN}[Agent] AI思考中...{Style.RESET_ALL}")
            try:
                resp = await brain._call_ai_with_retry(
                    model=MODEL_BRAIN,
                    messages=messages,
                    request_timeout=90
                )
                ai_text = resp.choices[0].message.content
            except Exception as e:
                print(f"{Fore.RED}[Agent] AI调用失败: {e}{Style.RESET_ALL}")
                break

            messages.append({"role": "assistant", "content": ai_text})

            # 解析AI回复中的工具调用
            tool_pattern = re.compile(r'\[TOOL:(\w+)\]\s*(.*?)(?=\[TOOL:|\[DONE\]|$)', re.DOTALL)
            stop_pattern = re.compile(r'\[DONE\]')

            done_match = stop_pattern.search(ai_text)
            tool_matches = tool_pattern.findall(ai_text)

            # 先解析任务看板标记（TASK）
            _parse_tasks(ai_text)

            # 先显示AI的文字回复（去掉工具调用、DONE、TASK标记）
            display_text = ai_text
            for tool_name, tool_body in tool_matches:
                display_text = display_text.replace(f"[TOOL:{tool_name}] {tool_body}", "")
            if done_match:
                display_text = display_text.replace("[DONE]", "")
            display_text = re.sub(r'\[TASK:[✓✗]\s*.*?\]', '', display_text)
            display_text = display_text.strip()
            if display_text:
                print(f"\n{Fore.LIGHTGREEN_EX}[Agent] AI > {Style.RESET_ALL}{display_text}")

            # 渲染任务看板
            board_text = _render_task_board()
            if board_text:
                print(board_text)

            if done_match and not tool_matches:
                # 纯DONE，无工具，结束
                print(f"\n{Fore.GREEN}[Agent] 对话结束{Style.RESET_ALL}")
                task_done = True
                break

            # 执行工具调用（逐个执行，每次执行后把结果加入对话）
            for tool_name, tool_body in tool_matches:
                tool_body = tool_body.strip()
                print(f"\n{Fore.YELLOW}[Agent] 执行工具: {tool_name}...{Style.RESET_ALL}")

                tool_result = ""

                if tool_name == "search_knowledge":
                    tool_result = _agent_search_knowledge(tool_body)
                elif tool_name == "read_file":
                    tool_result = _agent_read_file(tool_body)
                elif tool_name == "list_files":
                    tool_result = _agent_list_files(tool_body)
                elif tool_name == "delete_file":
                    tool_result = await _agent_delete_file(tool_body)
                elif tool_name == "update_file":
                    # 格式: 相对路径\n---新内容---
                    parts = tool_body.split('\n', 1)
                    if len(parts) == 2:
                        file_path = parts[0].strip()
                        content = parts[1].strip()
                        # 去掉可能的前导 --- 标记
                        if content.startswith('---'):
                            content = content[3:].strip()
                        tool_result = await _agent_update_file(file_path, content)
                    else:
                        tool_result = "update_file格式错误: 需要 相对路径\\n新内容"
                elif tool_name == "analyze_video":
                    # 重量级操作，需要确认
                    action_desc = f"完整分析视频《{title[:30]}》(ASR+视觉帧+评论+弹幕→归档)"
                    result = await _agent_confirm("analyze_video", action_desc, "预计耗时30-90秒，消耗API配额")
                    if result == "deny":
                        tool_result = "用户取消完整分析"
                    elif result == "ai_review":
                        if await _agent_ai_review("analyze_video", action_desc, "完整视频分析管道"):
                            print(f"{Fore.CYAN}[Agent] AI审查通过，开始完整视频分析...{Style.RESET_ALL}")
                            tool_result = await _agent_analyze_video()
                        else:
                            tool_result = "AI审查不通过，取消完整分析"
                    else:
                        print(f"{Fore.CYAN}[Agent] 开始完整视频分析...{Style.RESET_ALL}")
                        tool_result = await _agent_analyze_video()
                elif tool_name == "fetch_subtitles":
                    tool_result = await _agent_fetch_subtitles()
                elif tool_name == "quick_preview":
                    tool_result = await _agent_quick_preview()
                elif tool_name == "open_file":
                    tool_result = await _agent_open_file(tool_body)
                else:
                    tool_result = f"未知工具: {tool_name}"

                # 显示工具结果
                result_preview = tool_result[:500] + ("..." if len(tool_result) > 500 else "")
                print(f"{Fore.GREEN}[Agent] 工具结果: {result_preview}{Style.RESET_ALL}")

                # 把工具结果作为system消息加入对话
                context_note = f"[工具 {tool_name} 执行结果]:\n{tool_result}"
                # 根据已执行工具附加状态提示
                if tool_name == "fetch_subtitles" and not tool_result.startswith("[无字幕]") and not tool_result.startswith("[字幕获取失败]"):
                    context_note += f"\n\n[数据上下文] 已获取完整字幕({len(tool_result)}字)。下一步通常调用 analyze_video 做评分归档，或直接基于字幕回答用户问题。请勿再次调用 fetch_subtitles。"
                elif tool_name == "analyze_video":
                    context_note += "\n\n[数据上下文] 视频完整分析已完成（含字幕+评论+弹幕+AI评分+归档）。可以基于这些结果回复用户，或按用户要求生成总结/写文件。"
                context_note += "\n\n请基于以上结果继续回复用户，如需更多工具可继续调用。"
                messages.append({
                    "role": "system",
                    "content": context_note
                })

            # 工具执行完毕，决定下一步
            if done_match:
                # DONE + 工具已执行（如 open_file 后标 DONE）
                print(f"\n{Fore.GREEN}[Agent] 任务完成{Style.RESET_ALL}")
                task_done = True
                break

            if tool_matches:
                # 还有工作没做完 → 自动继续
                print(f"\n{Fore.CYAN}[Agent] 自动继续...{Style.RESET_ALL}")
                messages.append({"role": "user", "content": "[系统自动继续] 请基于工具结果继续执行下一步，无需等待用户输入。如果所有步骤已完成，输出 [DONE]。"})
                # 不 break，回到 inner while 顶部继续调 AI
            else:
                # 无工具调用，回到等待用户输入
                break

        # 内层循环结束
        if task_done:
            break

    if not task_done and turn >= MAX_TURNS:
        print(f"\n{Fore.YELLOW}[Agent] 达到最大对话轮次 ({MAX_TURNS})，自动退出{Style.RESET_ALL}")

    print(f"\n{Fore.LIGHTMAGENTA_EX}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.LIGHTMAGENTA_EX}|  Agent对话结束                                               |{Style.RESET_ALL}")
    print(f"{Fore.LIGHTMAGENTA_EX}+============================================================+{Style.RESET_ALL}")


# ==============================================================================
# [U] UP主主页批量学习 — 获取UP主主页视频列表，逐个AI学习归档
# ==============================================================================

async def up_homepage_learn():
    """UP主主页批量学习：输入UP主名字/UID，获取主页视频列表，用户设置数量后逐个AI学习。"""
    print(f"\n{Fore.CYAN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}|               📚 UP主主页批量学习                            |{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[INFO] 输入UP主名字或UID，获取TA主页的视频进行AI学习{Style.RESET_ALL}")

    user_input = input(f"\n{Fore.CYAN}请输入UP主名字或UID: {Style.RESET_ALL}").strip()
    if not user_input:
        print(f"{Fore.YELLOW}[WARN] 输入为空，已取消{Style.RESET_ALL}")
        return

    # ── 创建 AgentBrain 并加载凭证 ──
    brain = AgentBrain()
    brain.bili._load_credential()
    cookie_loaded = False
    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                brain.cookies = json.load(f)
            cookie_loaded = True
        except (json.JSONDecodeError, OSError) as e:
            print(f"{Fore.YELLOW}[WARN] Cookie文件损坏: {e}{Style.RESET_ALL}")
    if not cookie_loaded:
        print(f"{Fore.YELLOW}[HINT] 未登录(Cookie文件不存在)，部分视频的AI字幕可能需要登录才能获取{Style.RESET_ALL}")

    # ── 第一步：查找UP主 ──
    up_uid = None
    up_name = None

    # 尝试直接作为UID
    try:
        uid_candidate = int(user_input)
        if uid_candidate > 0:
            up_uid = uid_candidate
    except ValueError:
        pass

    if not up_uid:
        # 搜索UP主
        print(f"\n{Fore.CYAN}搜索UP主: {user_input}...{Style.RESET_ALL}")
        try:
            from bilibili_api import search as bili_search
            data = await bili_search.search_by_type(
                user_input,
                search_type=bili_search.SearchObjectType.USER,
                page=1
            )
            user_items = data.get("result") or []
            if not user_items:
                print(f"{Fore.RED}[ERROR] 未找到UP主: {user_input}{Style.RESET_ALL}")
                return

            # 显示搜索结果
            print(f"\n{Fore.GREEN}找到 {len(user_items)} 个UP主:{Style.RESET_ALL}")
            for i, u in enumerate(user_items[:10]):
                name = u.get("uname") or u.get("name", "?")
                uid = u.get("mid") or u.get("uid", 0)
                fans = u.get("fans", 0)
                sign = (u.get("usign") or u.get("sign", ""))[:40]
                fans_str = f"{fans/10000:.1f}w" if fans >= 10000 else str(fans)
                print(f"  {Fore.YELLOW}{i+1:>2}.{Style.RESET_ALL} {name}  (UID: {uid}, 粉丝: {fans_str})")
                if sign:
                    print(f"      {Fore.LIGHTBLACK_EX}{sign}{Style.RESET_ALL}")
            print(f"  {Fore.YELLOW} 0.{Style.RESET_ALL} 取消")

            choice = input(f"\n{Fore.CYAN}请选择UP主编号 (1-{min(len(user_items), 10)}): {Style.RESET_ALL}").strip()
            if choice == "0" or choice == "":
                print(f"{Fore.YELLOW}[WARN] 已取消{Style.RESET_ALL}")
                return
            try:
                idx = int(choice) - 1
                if 0 <= idx < min(len(user_items), 10):
                    chosen = user_items[idx]
                    up_uid = int(chosen.get("mid") or chosen.get("uid", 0))
                    up_name = chosen.get("uname") or chosen.get("name", "")
                else:
                    print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")
                    return
            except ValueError:
                print(f"{Fore.RED}[ERROR] 请输入数字{Style.RESET_ALL}")
                return
        except Exception as e:
            print(f"{Fore.RED}[ERROR] 搜索UP主失败: {e}{Style.RESET_ALL}")
            return

    if not up_uid:
        print(f"{Fore.RED}[ERROR] 无法获取UP主UID{Style.RESET_ALL}")
        return

    # ── 获取UP主信息 ──
    print(f"\n{Fore.CYAN}获取UP主信息...{Style.RESET_ALL}")
    up_info = await brain.bili.get_up_info(up_uid)
    if "error" in up_info:
        print(f"{Fore.RED}[ERROR] 获取UP主信息失败: {up_info['error']}{Style.RESET_ALL}")
        return

    up_name = up_info.get("name", up_name or "未知")
    follower = up_info.get("follower", 0)
    video_count = up_info.get("video_count", 0)
    fans_str = f"{follower/10000:.1f}w" if follower >= 10000 else str(follower)

    print(f"\n{Fore.GREEN}+------------------------------------------------------------+{Style.RESET_ALL}")
    print(f"{Fore.GREEN}|  UP主: {up_name}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}|  UID:  {up_uid}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}|  粉丝: {fans_str}  |  投稿: {video_count}个视频{Style.RESET_ALL}")
    print(f"{Fore.GREEN}+------------------------------------------------------------+{Style.RESET_ALL}")

    # ── 第二步：获取视频列表 ──
    max_fetch = min(video_count, 50) if video_count > 0 else 50
    print(f"\n{Fore.CYAN}获取 @{up_name} 的视频列表 (最多{max_fetch}个)...{Style.RESET_ALL}")

    try:
        from bilibili_api import user as bili_user
        u = bili_user.User(up_uid, brain.bili.credential)
        data = await u.get_videos(ps=min(max_fetch, 30))
        vlist = data.get("list", {}).get("vlist") or []
        # 如果需要更多，翻页获取
        if max_fetch > 30 and len(vlist) >= 30:
            page = 2
            while len(vlist) < max_fetch:
                try:
                    more_data = await u.get_videos(ps=30, pn=page)
                    more_list = more_data.get("list", {}).get("vlist") or []
                    if not more_list:
                        break
                    vlist.extend(more_list)
                    page += 1
                    await asyncio.sleep(0.5)
                except Exception:
                    break
        vlist = vlist[:max_fetch]
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 获取视频列表失败: {e}{Style.RESET_ALL}")
        return

    if not vlist:
        print(f"{Fore.RED}[ERROR] @{up_name} 没有投稿视频{Style.RESET_ALL}")
        return

    print(f"{Fore.GREEN}[OK] 获取到 {len(vlist)} 个视频{Style.RESET_ALL}")

    # ── 显示视频列表 ──
    print(f"\n{Fore.CYAN}{'─' * 70}{Style.RESET_ALL}")
    for i, v in enumerate(vlist):
        title = v.get("title", "无标题")[:45]
        play = v.get("play", 0)
        play_str = f"{play/10000:.1f}w" if play >= 10000 else str(play)
        created = v.get("created", 0)
        if created:
            from datetime import datetime
            dt = datetime.fromtimestamp(created).strftime("%m-%d")
        else:
            dt = "??"
        print(f"  {Fore.YELLOW}{i+1:>2}.{Style.RESET_ALL} {title}  {Fore.LIGHTBLACK_EX}▶{play_str} | {dt}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'─' * 70}{Style.RESET_ALL}")

    # ── 第三步：设置参数 ──
    print(f"\n{Fore.CYAN}设置学习参数:{Style.RESET_ALL}")

    count_input = input(f"{Fore.YELLOW}要学习几个视频？(1-{len(vlist)}, 回车=全部{len(vlist)}个): {Style.RESET_ALL}").strip()
    if not count_input:
        watch_count = len(vlist)
    else:
        try:
            watch_count = max(1, min(int(count_input), len(vlist)))
        except ValueError:
            watch_count = len(vlist)
    print(f"{Fore.GREEN}[OK] 将学习 {watch_count} 个视频{Style.RESET_ALL}")

    # 跳过无字幕
    skip_no_sub = input(f"{Fore.YELLOW}跳过无字幕视频？(y/n, 回车=跳过): {Style.RESET_ALL}").strip().lower()
    skip_no_sub = skip_no_sub != "n"  # 默认跳过

    # 干货阈值
    threshold_input = input(f"{Fore.YELLOW}低于几分跳过不归档？(1-10, 回车=默认7分): {Style.RESET_ALL}").strip()
    try:
        learn_threshold = float(threshold_input) if threshold_input else 7.0
        learn_threshold = max(1.0, min(10.0, learn_threshold))
    except ValueError:
        learn_threshold = 7.0
    print(f"{Fore.GREEN}[OK] 低于 {learn_threshold} 分的内容不归档{Style.RESET_ALL}")

    # ── 第四步：逐个学习 ──
    print(f"\n{Fore.CYAN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}|  开始批量学习 @{up_name} 的视频 (共{watch_count}个)             |{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+============================================================+{Style.RESET_ALL}")

    success_count = 0
    skip_count = 0
    fail_count = 0

    # 覆盖心情为客观分析模式
    original_custom = MOOD_CUSTOM_ENABLED
    original_custom_value = MOOD_CUSTOM_VALUE

    for idx, v in enumerate(vlist[:watch_count]):
        bvid = v.get("bvid", "")
        title = v.get("title", "无标题")
        video_url = f"https://www.bilibili.com/video/{bvid}"

        print(f"\n{Fore.CYAN}{'═' * 70}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}[{idx+1}/{watch_count}] {title}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'═' * 70}{Style.RESET_ALL}")

        if not bvid:
            print(f"{Fore.YELLOW}[SKIP] 无BV号，跳过{Style.RESET_ALL}")
            skip_count += 1
            continue

        # 间隔延迟（模拟真人）
        if idx > 0:
            delay = random.uniform(3.0, 8.0)
            print(f"{Fore.LIGHTBLACK_EX}等待 {delay:.1f}s (模拟真人节奏)...{Style.RESET_ALL}")
            await asyncio.sleep(delay)

        try:
            # 1. 视频理解
            print(f"\n{Fore.CYAN}[1/3] 理解视频内容...{Style.RESET_ALL}")
            brain.bili._video_meta_cache.pop(bvid, None)
            success, subtitle_text = await brain.understand_video_for_decision(bvid, title=title)
            if success:
                preview = subtitle_text[:150].replace('\n', ' ')
                print(f"{Fore.GREEN}[OK] 内容获取成功: {preview}...{Style.RESET_ALL}")
            else:
                subtitle_text = f"[理解受限] {subtitle_text}"
                if skip_no_sub and ("无有效字幕" in str(subtitle_text) or "Cookie文件不存在" in str(subtitle_text)):
                    print(f"{Fore.YELLOW}[SKIP] 无字幕且设置了跳过{Style.RESET_ALL}")
                    skip_count += 1
                    continue
                print(f"{Fore.YELLOW}[WARN] 视频理解受限: {str(subtitle_text)[:120]}{Style.RESET_ALL}")

            # 2. AI决策分析（客观模式）
            print(f"\n{Fore.CYAN}[2/3] AI客观分析...{Style.RESET_ALL}")

            try:
                globals()['MOOD_CUSTOM_ENABLED'] = True
                globals()['MOOD_CUSTOM_VALUE'] = "客观冷静分析，专注内容质量，不带个人情绪"
            except Exception:
                pass

            objective_prompt = SYSTEM_PROMPT_BRAIN.replace("{bot_name}", get_bot_name()).replace("{memory_ups}", str(brain.get_known_up_names()))
            objective_prompt = objective_prompt.replace(
                "【性格模式】掷硬币决定：- **夸夸模式**：真诚赞美。 - **吐槽模式**：犀利毒舌。",
                "【性格模式】客观分析模式：基于内容质量公正评分。\n"
                "评分标准：标题与内容匹配度、信息价值、制作质量。"
            )

            context = (f"视频标题: {title}\nUP主: {up_name}\n"
                       f"【📺 视频内容字幕】: {subtitle_text[:3000]}\n")

            resp = await brain._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": objective_prompt},
                    {"role": "user", "content": context}
                ],
                request_timeout=120
            )
            raw = resp.choices[0].message.content
            start = raw.find("{")
            end = raw.rfind("}")
            decision = {}
            if start >= 0 and end >= start:
                try:
                    decision = json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    fixed = raw[start:end + 1].replace("'", '"')
                    decision = json.loads(fixed)

            score = decision.get('score', 0)
            thought = decision.get('thought', '')
            learning_topic = decision.get('learning_topic', '')

            print(f"  AI评分: {Fore.YELLOW}{score}/10{Style.RESET_ALL}")
            print(f"  AI想法: {thought[:100]}")

            # 3. 归档
            if score >= learn_threshold or learning_topic:
                print(f"\n{Fore.CYAN}[3/3] 知识归档...{Style.RESET_ALL}")
                learn_text = subtitle_text
                if not learn_text or len(learn_text) < 20:
                    learn_text = f"【视频标题】{title}\n【AI判断】{thought}\n"
                if not learning_topic:
                    learning_topic = title[:15]

                try:
                    _desc = getattr(brain, "_last_video_desc", "")
                    learn_ok = await brain.learn_from_video(bvid, title, up_name, video_url, learn_text, learning_topic, video_desc=_desc, score=score)
                    if learn_ok:
                        print(f"{Fore.GREEN}[OK] ✓ 已归档 (评分 {score}){Style.RESET_ALL}")
                        success_count += 1
                    else:
                        print(f"{Fore.YELLOW}[INFO] 知识已存在，跳过{Style.RESET_ALL}")
                        skip_count += 1
                except Exception as e:
                    print(f"{Fore.RED}[ERROR] 归档失败: {e}{Style.RESET_ALL}")
                    fail_count += 1
            else:
                print(f"{Fore.YELLOW}[SKIP] 评分 {score} < {learn_threshold}，不归档{Style.RESET_ALL}")
                skip_count += 1

        except Exception as e:
            print(f"{Fore.RED}[ERROR] 处理失败: {str(e)[:150]}{Style.RESET_ALL}")
            fail_count += 1
            continue

    # 恢复心情设置
    try:
        globals()['MOOD_CUSTOM_ENABLED'] = original_custom
        globals()['MOOD_CUSTOM_VALUE'] = original_custom_value
    except Exception:
        pass

    # ── 汇总 ──
    print(f"\n{Fore.GREEN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.GREEN}|  UP主主页批量学习完成！                                      |{Style.RESET_ALL}")
    print(f"{Fore.GREEN}+============================================================+{Style.RESET_ALL}")
    print(f"  UP主: @{up_name}")
    print(f"  学习: {Fore.GREEN}{success_count}个{Style.RESET_ALL} | 跳过: {Fore.YELLOW}{skip_count}个{Style.RESET_ALL} | 失败: {Fore.RED}{fail_count}个{Style.RESET_ALL}")
    print(f"  总计: {watch_count}个视频")
    print(f"{Fore.GREEN}+============================================================+{Style.RESET_ALL}")


