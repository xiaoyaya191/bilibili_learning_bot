"""
quiz_generator.py — AI 出题考试引擎

功能：
1. 从视频字幕生成考题（指定 BV 号，类似 W 命令）
2. 从知识库内容生成考题（选择已有的知识条目）
3. 用户自定义提示词 / 预设选项（难度、题型、数量、风格）
4. 输出考题到文件，供用户练习

设计为同时供 CLI（main.py）和 Web（web_panel.py）调用。
"""

from __future__ import annotations

import json
import os
import re
import asyncio
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

from colorama import Fore, Style

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "Data"
KNOWLEDGE_BASE_DIR = BASE_DIR / "KnowledgeBase"
QUIZ_EXPORT_DIR = BASE_DIR / "html_exports" / "quizzes"

# ── 默认提示词模板 ──
QUIZ_SYSTEM_PROMPTS = {
    "default": """你是一位专业的出题老师，请根据提供的学习内容生成考试题目。

要求：
- 题目必须基于原文内容，不要编造
- 每个题目标明正确答案
- 选择题提供4个选项（A/B/C/D）
- 问答题提供参考答案
- 题目排版清晰易读""",

    "exam_style": """你是一位严格的考试命题人，请根据提供的学习内容生成一套正式考试试卷。

要求：
- 严格基于原文内容出题，不允许编造
- 题型包括：单选题、多选题、判断题、简答题
- 每个题目必须标注分值
- 答案与题目分离（答案放在试卷末尾）
- 试卷格式规范，像正式考试一样""",

    "flashcard": """你是一位闪卡学习法的专家，请根据提供的学习内容生成闪卡式问题。

要求：
- 每张闪卡：正面是简短的问题，背面是答案
- 问题简洁有力，直击核心知识点
- 适合快速复习和记忆
- 用 Q: 和 A: 格式标注""",

    "discussion": """你是一位讨论课导师，请根据提供的学习内容生成深度讨论题。

要求：
- 问题应该引发思考，而不仅仅是记忆
- 包含开放性问题，没有唯一正确答案
- 鼓励批判性思维和知识迁移
- 每题附带讨论引导要点""",
}

# ── 题目数量默认选项 ──
DEFAULT_QUESTION_OPTIONS = [3, 5, 10, 15, 20]

# ── 难度选项 ──
DIFFICULTY_OPTIONS = {
    "easy": "简单 — 基础概念回忆和识别",
    "medium": "中等 — 理解和应用知识点",
    "hard": "困难 — 分析和综合评价能力",
}

# ── 题型选项 ──
QUESTION_TYPES = {
    "mixed": "混合题型（单选+多选+判断+简答）",
    "choice_only": "仅选择题（单选+多选）",
    "short_answer": "仅简答题",
    "judgment": "仅判断题",
    "flashcard": "闪卡模式",
}

# ── 样式/风格选项 ──
QUIZ_STYLES = {
    "standard": "标准试卷 — 正式排版，适合打印",
    "interactive": "互动问答 — Q&A 对话风格",
    "exam_paper": "模拟考试 — 限时、计分",
    "mind_map": "思维导图 — 知识点关系梳理",
    "summary_card": "学习卡片 — 每张卡片一个知识点",
}


from services._services_ai import call_ai, _live_config


def _load_bili_cookies() -> dict:
    """加载 B站 Cookie"""
    cookie_file = DATA_DIR / "bilibili_cookies.json"
    if cookie_file.exists():
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


async def fetch_video_subtitles(bvid: str) -> Optional[str]:
    """获取视频字幕文本"""
    try:
        from api.subtitles import fetch_bilibili_subtitles
        cookies = _load_bili_cookies()
        result = await fetch_bilibili_subtitles(bvid, cookies_obj=cookies if cookies else None)
        if result and result.get("subtitle_text"):
            return result["subtitle_text"]
    except Exception:
        pass

    # 降级：直接用 httpx 获取
    try:
        import httpx
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'https://www.bilibili.com/video/{bvid}'
        }
        async with httpx.AsyncClient(http2=True, headers=headers, timeout=15.0) as client:
            resp = await client.get(
                'https://api.bilibili.com/x/player/v2',
                params={'bvid': bvid, 'cid': ''}
            )
            data = resp.json()
            if data.get('code') == 0:
                subtitle = data['data'].get('subtitle', {})
                subtitles_list = subtitle.get('subtitles', [])
                if subtitles_list:
                    sub_url = subtitles_list[0].get('subtitle_url', '')
                    if sub_url:
                        if sub_url.startswith('//'):
                            sub_url = 'https:' + sub_url
                        sub_resp = await client.get(sub_url)
                        return sub_resp.text
    except Exception:
        pass
    return None


def scan_kb_files() -> list[dict[str, Any]]:
    """扫描知识库文件列表"""
    results = []
    if not KNOWLEDGE_BASE_DIR.exists():
        return results

    for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in files:
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, KNOWLEDGE_BASE_DIR)
            category_path = os.path.dirname(rel_path).replace(os.sep, '/') or '未分类'
            size_kb = round(os.path.getsize(fpath) / 1024, 1)
            results.append({
                "name": fname,
                "rel_path": rel_path,
                "category_path": category_path,
                "file_path": fpath,
                "size_kb": size_kb,
            })
    results.sort(key=lambda x: (x['category_path'], x['name']))
    return results


def read_kb_file_content(file_path: str, max_chars: int = 12000) -> str:
    """读取知识库文件内容"""
    path = Path(file_path)
    if not path.exists():
        return ""
    content = path.read_text(encoding='utf-8', errors='replace')
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n... (内容过长已截断)"
    return content


async def generate_quiz(
    *,
    source_type: str = "video",          # "video" 或 "knowledge"
    bvid: str = "",                       # 视频BV号
    kb_file_path: str = "",               # 知识库文件路径
    kb_file_content: str = "",            # 直接传入的内容（Web端使用）
    question_count: int = 5,
    difficulty: str = "medium",
    question_type: str = "mixed",
    style: str = "standard",
    custom_prompt: str = "",
) -> dict[str, Any]:
    """
    生成考题

    返回: {
        "success": bool,
        "quiz_content": str,      # 生成的考题内容
        "source_title": str,      # 来源标题
        "saved_path": str,        # 保存路径
        "error": str or None
    }
    """
    result = {"success": False, "quiz_content": "", "source_title": "", "saved_path": "", "error": None}

    live = _live_config()
    if not live.get("api_key"):
        result["error"] = "API 未配置，请在 Data/config.json 中设置 unified_api_key"
        return result

    # ── Step 1: 获取内容 ──
    content = ""
    source_title = ""

    if source_type == "knowledge":
        if kb_file_content:
            content = kb_file_content
            source_title = "知识库内容"
        elif kb_file_path:
            content = read_kb_file_content(kb_file_path)
            source_title = os.path.basename(kb_file_path)
        else:
            result["error"] = "请指定知识库文件"
            return result
    else:  # video
        if not bvid:
            result["error"] = "请提供 BV 号"
            return result
        subtitles = await fetch_video_subtitles(bvid)
        if not subtitles:
            result["error"] = f"无法获取视频 {bvid} 的字幕/内容"
            return result
        content = subtitles
        source_title = f"BV{bvid}"

    if len(content) < 100:
        result["error"] = "内容太短（<100字符），无法生成有意义的考题"
        return result

    # 截断内容
    if len(content) > 15000:
        content = content[:15000] + "\n... (内容过长已截断)"

    # ── Step 2: 构建提示词 ──
    if custom_prompt:
        system_prompt = custom_prompt
    else:
        system_prompt = QUIZ_SYSTEM_PROMPTS.get(style, QUIZ_SYSTEM_PROMPTS["default"])

    type_desc = QUESTION_TYPES.get(question_type, QUESTION_TYPES["mixed"])
    diff_desc = DIFFICULTY_OPTIONS.get(difficulty, DIFFICULTY_OPTIONS["medium"])

    user_prompt = f"""请根据以下学习内容，生成 {question_count} 道题目。

难度级别：{diff_desc}
题型要求：{type_desc}
出题风格：{QUIZ_STYLES.get(style, QUIZ_STYLES['standard'])}

-------- 学习内容 --------
{content}
-------- 内容结束 --------

请按照以下格式输出：

# 考试题目 — {source_title}

**出题时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**难度**: {difficulty}
**题型**: {question_type}
**题目数量**: {question_count} 题

---
[在此生成题目，每题之间用 --- 分隔]

---
# 参考答案

[在此提供所有题目的参考答案]
"""

    # ── Step 3: 调用 AI (Claude 风格: openai + httpx 双后端降级) ──
    try:
        quiz_content = await call_ai(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=4096,
            timeout=120,
        )
    except Exception as e:
        result["error"] = f"AI 调用失败: {e}"
        return result

    if not quiz_content.strip():
        result["error"] = "AI 返回了空内容"
        return result

    # ── Step 4: 保存 ──
    QUIZ_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', source_title)[:60]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"quiz_{safe_title}_{timestamp}.md"
    saved_path = QUIZ_EXPORT_DIR / filename

    full_content = f"{quiz_content}\n\n---\n*本考题由 AI 自动生成，来源: {source_title}*"
    saved_path.write_text(full_content, encoding='utf-8')

    result["success"] = True
    result["quiz_content"] = quiz_content
    result["source_title"] = source_title
    result["saved_path"] = str(saved_path)
    return result


# ── CLI 菜单函数 ──
async def quiz_menu_cli():
    """CLI 出题菜单"""
    print(f"\n{Fore.CYAN}{'='*50}")
    print("  📝 出题考试 — AI 智能出题")
    print(f"{'='*50}{Style.RESET_ALL}")

    # 选择来源
    print(f"\n{Fore.YELLOW}请选择题目的内容来源：{Style.RESET_ALL}")
    print("  1. 📹 指定 B站视频（BV号）")
    print("  2. 📚 从知识库中选择已有内容")
    print("  0. ↩️ 返回")

    source_choice = input(f"{Fore.CYAN}请选择 (1/2/0): {Style.RESET_ALL}").strip()

    if source_choice == "0":
        return

    source_type = "video"
    bvid = ""
    kb_file_path = ""

    if source_choice == "1":
        bvid = input(f"{Fore.CYAN}请输入 BV 号: {Style.RESET_ALL}").strip()
        if not bvid:
            print(f"{Fore.RED}[ERROR] BV 号不能为空{Style.RESET_ALL}")
            return
        # 清理 BV 号格式
        bv_match = re.search(r'(BV[0-9A-Za-z]{10})', bvid)
        if bv_match:
            bvid = bv_match.group(1)
        else:
            print(f"{Fore.RED}[ERROR] 无效的 BV 号格式{Style.RESET_ALL}")
            return
        source_type = "video"

    elif source_choice == "2":
        files = scan_kb_files()
        if not files:
            print(f"{Fore.YELLOW}[INFO] 知识库为空，请先学习一些视频{Style.RESET_ALL}")
            return

        print(f"\n{Fore.GREEN}知识库文件列表：{Style.RESET_ALL}")
        for i, f in enumerate(files[:30]):  # 最多显示30个
            print(f"  {i+1:2d}. [{f['category_path']}] {f['name'][:60]} ({f['size_kb']}KB)")

        idx_str = input(f"{Fore.CYAN}请选择文件编号 (1-{min(len(files), 30)}): {Style.RESET_ALL}").strip()
        try:
            idx = int(idx_str) - 1
            if 0 <= idx < min(len(files), 30):
                kb_file_path = files[idx]['file_path']
                source_type = "knowledge"
            else:
                print(f"{Fore.RED}[ERROR] 无效编号{Style.RESET_ALL}")
                return
        except ValueError:
            print(f"{Fore.RED}[ERROR] 请输入数字{Style.RESET_ALL}")
            return

    # 选择配置文件
    print(f"\n{Fore.YELLOW}选择题型配置：{Style.RESET_ALL}")
    print("  1. ⚡ 使用默认配置（5题/中等/混合/标准风格）")
    print("  2. 🎛️ 自定义配置")
    print("  3. 📝 使用自定义提示词")

    config_choice = input(f"{Fore.CYAN}请选择 (1/2/3): {Style.RESET_ALL}").strip()

    question_count = 5
    difficulty = "medium"
    question_type = "mixed"
    style = "standard"
    custom_prompt = ""

    if config_choice == "2":
        # 题目数量
        print(f"\n{Fore.YELLOW}题目数量：{Style.RESET_ALL}")
        for i, n in enumerate(DEFAULT_QUESTION_OPTIONS):
            print(f"  {i+1}. {n} 题")
        print(f"  5. 自定义")
        q_choice = input(f"{Fore.CYAN}请选择 (1-5, 默认2=5题): {Style.RESET_ALL}").strip()
        if q_choice in ('1', '2', '3', '4'):
            question_count = DEFAULT_QUESTION_OPTIONS[int(q_choice) - 1]
        elif q_choice == '5':
            try:
                question_count = int(input(f"{Fore.CYAN}自定义题目数量: {Style.RESET_ALL}").strip())
                question_count = max(1, min(50, question_count))
            except ValueError:
                question_count = 5

        # 难度
        print(f"\n{Fore.YELLOW}难度级别：{Style.RESET_ALL}")
        diff_keys = list(DIFFICULTY_OPTIONS.keys())
        for i, (k, v) in enumerate(DIFFICULTY_OPTIONS.items()):
            print(f"  {i+1}. {v}")
        d_choice = input(f"{Fore.CYAN}请选择 (1-3, 默认2=中等): {Style.RESET_ALL}").strip()
        if d_choice in ('1', '2', '3'):
            difficulty = diff_keys[int(d_choice) - 1]

        # 题型
        print(f"\n{Fore.YELLOW}题型：{Style.RESET_ALL}")
        qt_keys = list(QUESTION_TYPES.keys())
        for i, (k, v) in enumerate(QUESTION_TYPES.items()):
            print(f"  {i+1}. {v}")
        qt_choice = input(f"{Fore.CYAN}请选择 (1-5, 默认1=混合): {Style.RESET_ALL}").strip()
        if qt_choice in ('1', '2', '3', '4', '5'):
            question_type = qt_keys[int(qt_choice) - 1]

        # 风格
        print(f"\n{Fore.YELLOW}出题风格：{Style.RESET_ALL}")
        style_keys = list(QUIZ_STYLES.keys())
        for i, (k, v) in enumerate(QUIZ_STYLES.items()):
            print(f"  {i+1}. {v}")
        s_choice = input(f"{Fore.CYAN}请选择 (1-5, 默认1=标准): {Style.RESET_ALL}").strip()
        if s_choice in ('1', '2', '3', '4', '5'):
            style = style_keys[int(s_choice) - 1]

    elif config_choice == "3":
        print(f"\n{Fore.YELLOW}预设提示词模板：{Style.RESET_ALL}")
        prompt_keys = list(QUIZ_SYSTEM_PROMPTS.keys())
        for i, k in enumerate(prompt_keys):
            name = {"default": "默认通用", "exam_style": "正式考试", "flashcard": "闪卡学习", "discussion": "讨论引导"}.get(k, k)
            print(f"  {i+1}. {name}")
        print(f"  5. 完全自定义")
        p_choice = input(f"{Fore.CYAN}请选择 (1-5): {Style.RESET_ALL}").strip()
        if p_choice in ('1', '2', '3', '4'):
            custom_prompt = QUIZ_SYSTEM_PROMPTS[prompt_keys[int(p_choice) - 1]]
        elif p_choice == '5':
            print(f"{Fore.CYAN}请输入自定义提示词（输入 END 结束）：{Style.RESET_ALL}")
            lines = []
            while True:
                line = input()
                if line.strip() == 'END':
                    break
                lines.append(line)
            custom_prompt = '\n'.join(lines)

    # 开始生成
    print(f"\n{Fore.GREEN}[QUIZ] 正在生成考题...{Style.RESET_ALL}")
    result = await generate_quiz(
        source_type=source_type,
        bvid=bvid,
        kb_file_path=kb_file_path,
        question_count=question_count,
        difficulty=difficulty,
        question_type=question_type,
        style=style,
        custom_prompt=custom_prompt,
    )

    if result["success"]:
        print(f"{Fore.GREEN}{'='*50}")
        print(result["quiz_content"])
        print(f"{'='*50}{Style.RESET_ALL}")
        print(f"\n{Fore.GREEN}[OK] 考题已保存至: {result['saved_path']}{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}[ERROR] {result['error']}{Style.RESET_ALL}")

    input(f"\n{Fore.CYAN}按 Enter 继续...{Style.RESET_ALL}")
