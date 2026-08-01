"""knowledge/revisit.py — 知识重温"""
import asyncio, os, random
from colorama import Fore, Style
from core.config import config
from core.globals import *
from utils.display import log
from utils.helpers import _mask_urls
from knowledge.classifier import KnowledgeBaseClassifier
from brain.video_analysis import _scan_knowledge_base_md_files

async def revisit_knowledge_video(bvid, title, up_name, category_path, file_path, mode="full"):
    """重温已学视频：完整管道(封面/标题/简介/评论/弹幕/视频内容/ASR/视觉帧) → AI决策 → 学习归档
    Args:
        mode: "full" = 重新看视频+优化, "optimize" = 只优化(用现有字幕/AI总结)
    """
    print(f"\n{Fore.CYAN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}|  🔄 知识库重温: {title[:40]}                          {Style.RESET_ALL}")
    print(f"{Fore.CYAN}+============================================================+{Style.RESET_ALL}")
    print(f"  BV号: {bvid}")
    print(f"  分类: {category_path}")
    if up_name:
        print(f"  UP主: {up_name}")
    mode_label = "完整重温(重新看视频+优化)" if mode == "full" else "仅优化(用现有知识)"
    print(f"  模式: {Fore.YELLOW}{mode_label}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+------------------------------------------------------------+{Style.RESET_ALL}")

    video_url = f"https://www.bilibili.com/video/{bvid}"

    # 创建 AgentBrain，加载凭证+ cookies
    brain = AgentBrain()
    brain.bili._load_credential()
    # [FIX] 同时加载 cookies，否则 fetch_bilibili_subtitles 无 cookie 无法获取AI字幕
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            brain.cookies = json.load(f)

    # ── 获取视频元信息 ──
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
            up_uid = vdata.get('owner', {}).get('mid', 0)
            aid = vdata.get('aid', 0)
            pic_url = vdata.get('pic', '')
            tags = []
            raw_tag = vdata.get('tag', '') or ''
            if isinstance(raw_tag, str) and raw_tag:
                tags = [t.strip() for t in raw_tag.split(',') if t.strip()]
            category = vdata.get('tname', '')
            duration_raw = vdata.get('duration', 0)
            if isinstance(duration_raw, str) and ':' in duration_raw:
                parts = duration_raw.split(':')
                duration = int(parts[0]) * 60 + int(parts[1])
            else:
                try:
                    duration = int(duration_raw)
                except (ValueError, TypeError):
                    duration = 0
            video_desc = vdata.get('desc', '')
            print(f"{Fore.GREEN}[OK] 视频信息获取成功: {title} | @{up_name}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}[ERROR] 获取视频信息失败: code={vinfo.get('code')}{Style.RESET_ALL}")
            return
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 获取视频信息失败: {e}{Style.RESET_ALL}")
        return

    # 缓存视频元数据
    brain._current_video_tags = tags
    brain._current_video_category = category
    brain._current_video_duration = duration

    # ── [1/6] 封面分析 ──
    print(f"\n{Fore.CYAN}[1/6] 封面视觉分析...{Style.RESET_ALL}")
    cover_desc, vis_score = "", 0
    if pic_url:
        try:
            cover_desc, vis_score = await brain.analyze_vision(pic_url)
            print(f"{Fore.GREEN}[OK] 封面: {cover_desc} [印象分:{vis_score}]{Style.RESET_ALL}")
            brain._current_video_cover_desc = cover_desc
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] 封面分析失败: {e}{Style.RESET_ALL}")

    if video_desc:
        print(f"{Fore.GREEN}[OK] 简介预览: {video_desc[:100]}...{Style.RESET_ALL}")

    # ── [2/6] 视频内容理解 ──
    print(f"\n{Fore.CYAN}[2/6] 视频内容理解 (字幕/ASR/视觉帧)...{Style.RESET_ALL}")
    if mode == "full":
        # 完整管道：重新下载视频 → ASR+视觉帧
        success, subtitle_text = await brain._understand_super_smart(bvid, title=title)
    else:
        # 仅优化模式：读取现有 md 文件中的内容
        subtitle_text = ""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                existing = f.read()
            # 提取 AI 总结部分
            summary_match = re.search(r'##\s*\[BRAIN\]\s*AI内容总结\s*\n(.*)', existing, re.DOTALL)
            if summary_match:
                subtitle_text = f"【已有AI总结】\n{summary_match.group(1).strip()[:3000]}"
            else:
                # 回退：取文件后半部分
                subtitle_text = existing[-3000:] if len(existing) > 3000 else existing
            print(f"{Fore.GREEN}[OK] 使用现有知识库内容 ({len(subtitle_text)}字){Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] 读取现有知识失败: {e}，降级为完整模式{Style.RESET_ALL}")
            success, subtitle_text = await brain._understand_super_smart(bvid, title=title)

    if subtitle_text:
        preview = subtitle_text[:200].replace('\n', ' ')
        print(f"{Fore.GREEN}[OK] 视频内容: {preview}...{Style.RESET_ALL}")
    else:
        subtitle_text = f"【视频标题】{title}\n【简介】{video_desc}"
        print(f"{Fore.YELLOW}[WARN] 无可用内容，使用标题+简介兜底{Style.RESET_ALL}")

    # ── [3/6] 评论+弹幕 ──
    print(f"\n{Fore.CYAN}[3/6] 评论区讨论+弹幕...{Style.RESET_ALL}")
    comment_text = "[未读取评论]"
    c_list = []
    danmaku_text = ""
    if aid:
        try:
            comment_text, c_list = await brain._get_comments_context(aid)
            if c_list:
                print(f"{Fore.GREEN}[OK] 获取到 {len(c_list)} 条评论{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[WARN] 评论区无内容{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] 评论获取失败: {e}{Style.RESET_ALL}")

        try:
            danmaku_list = await brain.maybe_read_danmaku(bvid)
            if danmaku_list:
                danmaku_text = f"【弹幕（共{len(danmaku_list)}条）】:\n" + "\n".join(
                    f"  {dm.get('text','')}" for dm in danmaku_list[:15]
                )
                print(f"{Fore.GREEN}[OK] 获取到 {len(danmaku_list)} 条弹幕{Style.RESET_ALL}")
        except Exception as e:
            log(f'非预期异常: {e}', 'WARN')

    # ── [4/6] AI决策 ──
    print(f"\n{Fore.CYAN}[4/6] AI综合分析决策...{Style.RESET_ALL}")
    objective_prompt = SYSTEM_PROMPT_BRAIN.replace("{bot_name}", get_bot_name()).replace("{memory_ups}", str(brain.get_known_up_names()))
    # 重温模式特有提示
    objective_prompt += (
        "\n\n【重温优化模式】这是一个已经归档到知识库的视频。"
        "请重新审视内容，看看有没有遗漏的要点、新的理解角度、或可以补充的知识点。"
        "如果原归档质量已很高，可以给出更高的分数。"
    )

    context = (f"视频标题: {title}\nUP主: {up_name}\n"
               f"视频简介: {video_desc}\n"
               f"封面描述: {cover_desc}\n"
               f"原分类: {category_path}\n"
               f"【视频内容】: {subtitle_text}\n"
               f"{comment_text}"
               f"{danmaku_text}")

    score = 0
    thought = ""
    learning_topic = ""
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
        mode_decision = decision.get('mode', '')
        learning_topic = decision.get('learning_topic', '')

        print(f"\n{Fore.CYAN}+------------------------------------------------------------+{Style.RESET_ALL}")
        print(f"{Fore.CYAN}|  [重温分析结果]                                             |{Style.RESET_ALL}")
        print(f"{Fore.CYAN}+------------------------------------------------------------+{Style.RESET_ALL}")
        print(f"  AI评分: {Fore.YELLOW}{score}/10{Style.RESET_ALL}")
        print(f"  AI想法: {thought}")
        if learning_topic:
            print(f"  主题: {learning_topic}")
        print(f"{Fore.CYAN}+------------------------------------------------------------+{Style.RESET_ALL}")

    except Exception as e:
        print(f"{Fore.RED}[ERROR] AI决策失败: {_mask_urls(str(e)[:200])}{Style.RESET_ALL}")

    # ── [5/6] 评论区知识收集 ──
    print(f"\n{Fore.CYAN}[5/6] 评论区知识收集...{Style.RESET_ALL}")
    if c_list and len(c_list) >= 3:
        try:
            await brain.learn_from_comments(bvid, title, up_name, video_url, comment_text, c_list, learning_topic or title[:15])
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] 评论知识收集失败: {e}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}[INFO] 评论不足，跳过评论知识收集{Style.RESET_ALL}")

    # ── [6/6] 学习归档（覆盖更新） ──
    print(f"\n{Fore.CYAN}[6/6] 更新知识归档...{Style.RESET_ALL}")
    learn_text = subtitle_text
    if not learn_text or len(learn_text) < 30:
        learn_text = f"【视频标题】{title}\n【简介】{video_desc}\n【AI判断】{thought}\n"
        if danmaku_text:
            learn_text += f"{danmaku_text}\n"
        if comment_text and comment_text != "[未读取评论]":
            learn_text += f"{comment_text}\n"
        learn_text = learn_text.strip()

    if not learning_topic:
        learning_topic = title[:15] if title else category_path

    if learn_text and len(learn_text) > 20:
        try:
            _desc = getattr(brain, "_last_video_desc", "") or video_desc
            # 删除旧文件，让 learn_from_video 重新创建
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"{Fore.YELLOW}[INFO] 已删除旧归档文件，准备重新创建...{Style.RESET_ALL}")
            learn_success = await brain.learn_from_video(bvid, title, up_name, video_url, learn_text, learning_topic, video_desc=_desc, score=score)
            if learn_success:
                print(f"{Fore.GREEN}[OK] 知识已更新归档！{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}[INFO] 归档未更新（可能已存在或分类未变）{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[ERROR] 学习归档失败: {e}{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}[INFO] 可学习内容不足，跳过归档{Style.RESET_ALL}")

    print(f"\n{Fore.GREEN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.GREEN}|  🔄 重温完成: {title[:40]}                                  {Style.RESET_ALL}")
    print(f"{Fore.GREEN}+============================================================+{Style.RESET_ALL}")


async def revisit_knowledge_base_menu():
    """知识库重温菜单：扫描所有 .md 文件，选择后重看视频优化或仅优化。"""
    print(f"\n{Fore.CYAN}+============================================================+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}|        🔄 知识库重温优化 - 已学习视频回顾                      |{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+============================================================+{Style.RESET_ALL}")

    # 扫描知识库
    md_files = _scan_knowledge_base_md_files()
    if not md_files:
        print(f"{Fore.YELLOW}[WARN] 知识库中没有找到学习归档文件！{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}[INFO] 请先让机器人学习一些视频，或手动分析视频并归档{Style.RESET_ALL}")
        input(f"\n{Fore.CYAN}按回车返回...{Style.RESET_ALL}")
        return

    # 按分类分组展示
    from collections import defaultdict
    by_category = defaultdict(list)
    for item in md_files:
        by_category[item[4]].append(item)

    print(f"\n{Fore.GREEN}共找到 {len(md_files)} 个已学习视频，分布在 {len(by_category)} 个分类:{Style.RESET_ALL}\n")

    # 展开所有文件，统一编号
    all_items = []
    idx = 1
    for cat in sorted(by_category.keys()):
        items = by_category[cat]
        print(f"{Fore.CYAN}[{cat}] ({len(items)}个){Style.RESET_ALL}")
        for bvid, title, fpath, up, cat_path in items:
            up_str = f" @{up}" if up else ""
            print(f"  {Fore.YELLOW}{idx:3d}.{Style.RESET_ALL} {title[:50]}{up_str}")
            all_items.append((idx, bvid, title, fpath, up, cat_path))
            idx += 1
        print()

    print(f"  {Fore.YELLOW}  0.{Style.RESET_ALL} 返回主菜单")

    try:
        choice = input(f"\n{Fore.CYAN}请选择要重温的视频 (1-{len(all_items)}): {Style.RESET_ALL}").strip()
        if not choice or choice == "0":
            print(f"{Fore.YELLOW}[INFO] 已取消{Style.RESET_ALL}")
            return

        sel_idx = int(choice)
        if sel_idx < 1 or sel_idx > len(all_items):
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")
            return

        _, bvid, title, fpath, up, cat_path = all_items[sel_idx - 1]

        # 选择模式
        print(f"\n{Fore.CYAN}已选择: {title[:50]}{Style.RESET_ALL}")
        print(f"\n{Fore.CYAN}请选择重温模式:{Style.RESET_ALL}")
        print(f"  {Fore.GREEN}1.{Style.RESET_ALL} 🔄 完整重温 (重新看视频: 封面→简介→字幕/下载/ASR→评论→弹幕→AI决策→归档)")
        print(f"  {Fore.BLUE}2.{Style.RESET_ALL} 📝 仅优化 (用现有知识库内容 + 最新评论/弹幕 → AI重新分析 → 归档)")
        print(f"  {Fore.YELLOW}0.{Style.RESET_ALL} 取消")

        mode_choice = input(f"\n{Fore.CYAN}请选择 (1/2/0): {Style.RESET_ALL}").strip()
        if mode_choice == "0" or not mode_choice:
            print(f"{Fore.YELLOW}[INFO] 已取消{Style.RESET_ALL}")
            return
        elif mode_choice == "1":
            mode = "full"
        elif mode_choice == "2":
            mode = "optimize"
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")
            return

        await revisit_knowledge_video(bvid, title, up, cat_path, fpath, mode)

    except ValueError:
        print(f"{Fore.RED}[ERROR] 请输入数字{Style.RESET_ALL}")
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[WARN] 用户中断{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 重温异常: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()


# ==============================================================================
# 📂 一键整理知识库：非3层文件 → AI自动归类到3层
# ==============================================================================
