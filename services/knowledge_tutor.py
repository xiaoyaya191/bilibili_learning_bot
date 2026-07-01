"""
knowledge_tutor.py — 知识库辅导/讲解服务

功能：
1. 扫描 KnowledgeBase/ 下所有 .md 文件
2. 让用户选择一个文件，AI 进行交互式讲解/Q&A/二次创作
3. 支持生成 HTML 网页用于可视化讲解
4. 支持直接修改 md 文件（二次创作）

设计为同时供 CLI（start_cli.py）和 Web（web_panel.py）调用。
"""

from __future__ import annotations

import json
import os
import re
import asyncio
from pathlib import Path
from typing import Any
from datetime import datetime

# 延迟导入，避免循环依赖
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "Data"
KNOWLEDGE_BASE_DIR = BASE_DIR / "KnowledgeBase"


def _get_llm_client():
    """获取 LLM 客户端（延迟导入）"""
    try:
        from bili_core.llm import ModelClient
        from bili_core.settings import load_settings
        from bili_core.state import BotState
        settings = load_settings()
        return ModelClient(settings, BotState())
    except Exception:
        return None


def scan_md_files() -> list[dict[str, Any]]:
    """扫描 KnowledgeBase/ 下所有 .md 文件。
    返回: [{"bvid", "title", "file_path", "rel_path", "up_name", "category_path", "size_kb"}, ...]
    """
    results = []
    if not KNOWLEDGE_BASE_DIR.exists():
        return results

    for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fname in files:
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(root, fname)
            # 提取 BV 号
            bv_match = re.match(r'^\[(BV[0-9A-Za-z]{10})\]\s*-\s*(.+)\.md$', fname)
            bvid = bv_match.group(1) if bv_match else ""
            title = bv_match.group(2).strip() if bv_match else fname.replace('.md', '')

            rel_path = os.path.relpath(fpath, KNOWLEDGE_BASE_DIR)
            category_path = os.path.dirname(rel_path).replace(os.sep, '/')
            if not category_path or category_path == '.':
                category_path = '未分类'

            # 读取 UP主 信息
            up_name = ""
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    head = f.read(800)
                    up_m = re.search(r'\*\*UP主\*\*:\s*(.+)', head)
                    if up_m:
                        up_name = up_m.group(1).strip()
            except Exception:
                pass

            size_kb = round(os.path.getsize(fpath) / 1024, 1)
            results.append({
                "bvid": bvid,
                "title": title,
                "file_path": fpath,
                "rel_path": rel_path,
                "up_name": up_name,
                "category_path": category_path,
                "size_kb": size_kb,
            })

    results.sort(key=lambda x: (x['category_path'], x['title']))
    return results


def read_md_file(file_path: str | Path) -> str:
    """读取 md 文件内容"""
    path = Path(file_path)
    if not path.exists():
        return ""
    return path.read_text(encoding='utf-8', errors='replace')


def write_md_file(file_path: str | Path, content: str) -> bool:
    """写入 md 文件（先备份）"""
    path = Path(file_path)
    if not path.exists():
        return False
    # 备份
    backup_path = path.with_suffix('.md.bak')
    try:
        path.rename(backup_path)
        path.write_text(content, encoding='utf-8')
        return True
    except Exception:
        # 回滚
        if backup_path.exists() and not path.exists():
            backup_path.rename(path)
        return False


# ═══════════════════════════════════════════
#  AI 辅导 Prompt 模板
# ═══════════════════════════════════════════

SYSTEM_PROMPT_TUTOR = """你是一位知识渊博、耐心细致的学习导师。你的任务是帮助用户理解和掌握知识库中的内容。

你可以做：
1. 解答用户关于知识内容的疑问
2. 对知识进行二次创作（重组、补充、优化）
3. 用通俗易懂的语言讲解复杂概念
4. 生成结构化的 HTML 网页用于可视化讲解

风格要求：
- 回复使用 Markdown 格式
- 条理清晰，善用标题、列表、表格
- 对于复杂概念，用类比和举例帮助理解
- 保持友好的师生交流语气
- 如果用户请求生成HTML，必须输出完整的<!DOCTYPE html>起始的HTML代码"""

SYSTEM_PROMPT_REWRITE = """你是一位知识整理专家。用户会给你一份知识库文件的内容，请你进行二次创作。

要求：
1. 保持原文件的核心知识和事实不变
2. 优化结构和排版，使内容更易读
3. 补充缺失的知识点（如果有的话）
4. 修正任何过时或不准确的表述
5. 使用 Markdown 格式输出
6. 在文件末尾添加修订记录

输出格式：
- 先用一段话说明你做了哪些修改
- 然后用 --- 分隔
- 最后输出修改后的完整文件内容"""

SYSTEM_PROMPT_HTML = """你是一位前端开发和教学设计专家。用户会给你一份知识内容，请你创建一个美观的HTML网页来呈现这些知识。

要求：
1. 输出完整的<!DOCTYPE html>起始的HTML文件
2. 设计精美的现代化UI（暗色主题或清新主题）
3. 包含：
   - 顶部标题区（视频标题、UP主等元信息）
   - 目录/导航
   - 主体内容区（用卡片、表格、列表等呈现）
   - 关键概念高亮/标注
   - 底部总结区
4. 使用内联CSS（不依赖外部文件）
5. 响应式设计，支持手机和桌面
6. 适当使用图标emoji装饰
7. 代码简洁清晰，注释合理
8. 所有样式写在 <style> 标签内
9. JavaScript 仅用于交互增强（如平滑滚动、回到顶部）

特别注意：HTML 必须完整可独立打开，不能引用任何外部资源（CDN除外，可引用Chart.js等用于数据可视化）"""


# ═══════════════════════════════════════════
#  KnowledgeTutor 核心类
# ═══════════════════════════════════════════

class KnowledgeTutor:
    """知识库辅导引擎"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = _get_llm_client()
        return self._client

    def is_available(self) -> bool:
        """检查 AI 接口是否可用"""
        try:
            c = self.client
            return c is not None
        except Exception:
            return False

    async def chat_about_file(
        self,
        file_path: str | list[str],
        user_message: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        """与 AI 对话，讨论知识文件的内容（支持单文件或多文件）。

        Args:
            file_path: 单个文件路径(str)或多文件路径列表(list[str])
            user_message: 用户的问题/指令
            conversation_history: 之前的对话历史 [{"role":"user/assistant","content":"..."}]

        Returns:
            AI 的回复文本
        """
        if not self.client:
            return "❌ AI 接口不可用，请先配置 API Key。"

        # 统一为列表
        if isinstance(file_path, str):
            paths = [file_path]
        else:
            paths = file_path

        if not paths:
            return "❌ 未指定知识文件。"

        # 读取所有文件并构建组合内容
        combined_parts = []
        total_chars = 0
        max_total = 8000
        per_file_limit = max(500, max_total // len(paths))

        for i, fp in enumerate(paths):
            fc = read_md_file(fp)
            if not fc:
                continue
            fname = os.path.basename(fp)
            bv_match = re.match(r'^\[BV[0-9A-Za-z]{10}\]\s*-\s*(.+)\.md$', fname)
            ftitle = bv_match.group(2).strip() if bv_match else fname

            truncated = fc[:per_file_limit]
            if len(fc) > per_file_limit:
                truncated += f"\n... (全文共 {len(fc)} 字符，已截断至前{per_file_limit}字符)"

            total_chars += len(truncated)
            if total_chars > max_total and i > 0:
                combined_parts.append(f"\n\n(还有 {len(paths) - i} 个文件因长度限制未展示)")
                break

            combined_parts.append(f"### 文件 {i+1}: {ftitle}\n**路径**: {fp}\n\n{truncated}")

        combined_content = "\n\n---\n\n".join(combined_parts)
        file_desc = "以下是我要学习的知识文件内容" if len(paths) == 1 else f"以下是我要学习的 {len(paths)} 个知识文件的内容"

        system_prompt = SYSTEM_PROMPT_TUTOR

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{file_desc}：\n\n{combined_content}"},
            {"role": "assistant", "content": "我已经阅读了知识文件的内容。你可以就里面的任何知识点向我提问，我会耐心为你讲解。你也可以让我对内容进行二次创作、补充优化，或生成HTML网页来可视化呈现这些知识。请问你想了解什么？"},
        ]

        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": user_message})

        try:
            reply = await self.client.chat(messages, purpose="knowledge_tutor")
            return reply or "（AI 返回了空内容）"
        except Exception as e:
            return f"❌ AI 调用失败: {e}"
    async def rewrite_file(
        self,
        file_path: str,
        extra_instructions: str = "",
    ) -> tuple[str, str]:
        """让 AI 对知识文件进行二次创作（改写）。

        Args:
            file_path: 知识文件路径
            extra_instructions: 额外的改写要求

        Returns:
            (修改说明, 改写后的完整内容)
        """
        if not self.client:
            return "❌ AI 接口不可用", ""

        file_content = read_md_file(file_path)
        if not file_content:
            return "❌ 无法读取文件", ""

        fname = os.path.basename(file_path)
        bv_match = re.match(r'^\[(BV[0-9A-Za-z]{10})\]\s*-\s*(.+)\.md$', fname)
        title = bv_match.group(2).strip() if bv_match else fname

        user_prompt = f"""请对以下知识文件进行二次创作（优化改写）：

【文件标题】: {title}

【当前内容】:
{file_content[:6000]}

{extra_instructions if extra_instructions else '请优化结构、补充缺失知识点、修正不准确表述。'}

请按格式输出：先说明修改了什么，再用 --- 分隔，输出完整的新内容。"""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_REWRITE},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw = await self.client.chat(messages, purpose="knowledge_rewrite")
            if not raw:
                return "（空内容）", ""

            # 解析：分割 说明 和 内容
            parts = raw.split("\n---\n", 1)
            if len(parts) == 2:
                summary = parts[0].strip()
                new_content = parts[1].strip()
            else:
                summary = "AI 已完成改写"
                new_content = raw.strip()

            return summary, new_content
        except Exception as e:
            return f"❌ 改写失败: {e}", ""

    async def generate_html(
        self,
        file_path: str | list[str],
        style: str = "dark",
    ) -> str:
        """让 AI 生成 HTML 网页来可视化讲解知识（支持单文件或多文件）。

        Args:
            file_path: 单个文件路径(str)或多文件路径列表(list[str])
            style: 主题风格 ("dark"/"light"/"modern")

        Returns:
            完整的 HTML 代码
        """
        if not self.client:
            return "<html><body><h1>❌ AI 接口不可用</h1></body></html>"

        # 统一为列表
        if isinstance(file_path, str):
            paths = [file_path]
        else:
            paths = file_path

        if not paths:
            return "<html><body><h1>❌ 未指定知识文件</h1></body></html>"

        # 读取并拼接所有文件内容
        combined_parts = []
        total_chars = 0
        max_total = 7000
        per_file_limit = max(500, max_total // len(paths))

        bvid = ""
        for i, fp in enumerate(paths):
            fc = read_md_file(fp)
            if not fc:
                continue
            fname = os.path.basename(fp)
            bv_match = re.match(r'^\[BV[0-9A-Za-z]{10}\]\s*-\s*(.+)\.md$', fname)
            ftitle = bv_match.group(2).strip() if bv_match else fname
            if not bvid and bv_match:
                bvid = bv_match.group(1)

            truncated = fc[:per_file_limit]
            if len(fc) > per_file_limit:
                truncated += f"\n... (全文共 {len(fc)} 字符，已截断至前{per_file_limit}字符)"

            total_chars += len(truncated)
            if total_chars > max_total and i > 0:
                combined_parts.append(f"\n\n(还有 {len(paths) - i} 个文件因长度限制未展示)")
                break

            combined_parts.append(f"### 文件 {i+1}: {ftitle}\n**路径**: {fp}\n\n{truncated}")

        combined_content = "\n\n---\n\n".join(combined_parts)
        titles = [os.path.basename(fp) for fp in paths]
        main_title = titles[0] if len(paths) == 1 else f"{len(paths)} 个知识文件的综合讲解"

        style_desc = {
            "dark": "暗色科技风（深色背景、蓝色/青色强调色）",
            "light": "清新白底风（白色背景、柔和的彩色点缀）",
            "modern": "现代极简风（大量留白、灰度层次）",
        }.get(style, "暗色科技风")

        user_prompt = f"""请为以下知识内容创建一个HTML网页用于可视化讲解：

【知识来源】: {main_title}
{f'【BV号】: {bvid}' if bvid else ''}
文件数量: {len(paths)}

【知识内容】:
{combined_content}

设计风格：{style_desc}

请输出完整的 <!DOCTYPE html> 开头的 HTML 代码。"""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_HTML},
            {"role": "user", "content": user_prompt},
        ]

        try:
            html = await self.client.chat(messages, purpose="knowledge_html")
            if not html:
                return "<html><body><h1>AI 返回空内容</h1></body></html>"

            # 提取 HTML 代码（去掉可能的 markdown 代码块包裹）
            html = html.strip()
            if html.startswith("```html"):
                html = html[7:]
            elif html.startswith("```"):
                html = html[3:]
            if html.endswith("```"):
                html = html[:-3]
            html = html.strip()

            # 确保以 DOCTYPE 开头
            if not html.lower().startswith("<!doctype"):
                html = "<!DOCTYPE html>\n" + html

            return html
        except Exception as e:
            return f"<html><body><h1>❌ 生成失败: {e}</h1></body></html>"
# ═══════════════════════════════════════════
#  便捷函数（供 CLI 和 Web 调用）
# ═══════════════════════════════════════════

_tutor_instance: KnowledgeTutor | None = None


def get_tutor() -> KnowledgeTutor:
    """获取全局 KnowledgeTutor 单例"""
    global _tutor_instance
    if _tutor_instance is None:
        _tutor_instance = KnowledgeTutor()
    return _tutor_instance


async def tutor_chat(file_path: str | list[str], message: str, history: list | None = None) -> str:
    """快捷对话"""
    return await get_tutor().chat_about_file(file_path, message, history)


async def tutor_rewrite(file_path: str, instructions: str = "") -> tuple[str, str]:
    """快捷改写"""
    return await get_tutor().rewrite_file(file_path, instructions)


async def tutor_generate_html(file_path: str | list[str], style: str = "dark") -> str:
    """快捷生成HTML"""
    return await get_tutor().generate_html(file_path, style)
