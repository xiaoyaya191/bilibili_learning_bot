"""knowledge/custom.py — 自定义知识管理"""
import asyncio, json, os, re, time, hashlib
from datetime import datetime
from colorama import Fore, Style
from core.config import config, save_config, KNOWLEDGE_BASE_DIR, BASE_DIR
# 从 config 实时读取，避免 import * 缓存问题
def _get_model_brain():
    return config.get("api", {}).get("model_brain", "")
from utils.display import log
from utils.helpers import sanitize_filename, _mask_urls
from knowledge.classifier import KnowledgeBaseClassifier
from knowledge.web_search import web_search
from openai import OpenAI

CUSTOM_KNOWLEDGE_DIR = os.path.join(KNOWLEDGE_BASE_DIR, "自定义知识")


def _atomic_write_json(path, data):
    """原子写入 JSON 文件（tmp+replace 防止断电损坏）"""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def _init_custom_knowledge_dir():
    """确保自定义知识目录存在，并初始化 metadata 中的索引"""
    os.makedirs(CUSTOM_KNOWLEDGE_DIR, exist_ok=True)
    meta_path = os.path.join(BASE_DIR, "knowledge_metadata.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = {"categories": {}, "file_index": {}, "last_updated": ""}
    else:
        meta = {"categories": {}, "file_index": {}, "last_updated": ""}
    # 确保 file_index 中有自定义知识分类
    if "自定义知识" not in meta.get("file_index", {}):
        meta.setdefault("file_index", {})["自定义知识"] = []
    if "自定义知识" not in meta.get("categories", {}):
        meta.setdefault("categories", {})["自定义知识"] = {}
    # 写回
    tmp = meta_path + '.tmp'
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, meta_path)
    return meta

def _get_custom_knowledge_entries():
    """返回自定义知识条目列表: [(idx, title, bvid_or_id, filepath, added)] sorted by added desc"""
    meta = _init_custom_knowledge_dir()
    entries = meta.get("file_index", {}).get("自定义知识", [])
    # 倒序（最新的在前）
    entries_sorted = sorted(entries, key=lambda e: e.get("added", ""), reverse=True)
    result = []
    for i, e in enumerate(entries_sorted, 1):
        bvid = e.get("bvid", f"custom_{i}")
        title = e.get("title", "无标题")
        added = e.get("added", "")
        # 查找文件
        filename = f"[{bvid}] - {sanitize_filename(title)}.md"
        filepath = os.path.join(CUSTOM_KNOWLEDGE_DIR, filename)
        if not os.path.exists(filepath):
            # 尝试模糊匹配
            for f in os.listdir(CUSTOM_KNOWLEDGE_DIR):
                if bvid in f:
                    filepath = os.path.join(CUSTOM_KNOWLEDGE_DIR, f)
                    break
            else:
                continue  # 文件不存在，跳过
        result.append((i, title, bvid, filepath, added))
    return result

async def custom_knowledge_menu():
    """自定义知识管理菜单 — 增删改查"""
    _init_custom_knowledge_dir()
    while True:
        entries = _get_custom_knowledge_entries()
        print(f"""
{Fore.LIGHTGREEN_EX}╔══════════════════════════════════════════════════════════╗{Style.RESET_ALL}
{Fore.LIGHTGREEN_EX}║  📝 自定义知识管理                                        ║{Style.RESET_ALL}
{Fore.LIGHTGREEN_EX}╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}

{Fore.CYAN}📊 当前条目数: {len(entries)} 个{Style.RESET_ALL}

{Fore.GREEN}1.{Style.RESET_ALL} ➕ 新增知识条目
{Fore.GREEN}2.{Style.RESET_ALL} 📋 浏览所有条目
{Fore.GREEN}3.{Style.RESET_ALL} 👁️  查看条目详情
{Fore.YELLOW}4.{Style.RESET_ALL} ✏️  编辑条目
{Fore.RED}5.{Style.RESET_ALL} 🗑️  删除条目
{Fore.CYAN}6.{Style.RESET_ALL} 🔍 搜索知识内容
{Fore.LIGHTBLUE_EX}7.{Style.RESET_ALL} 🤖 AI搜索B站并整理入库
{Fore.RED}0.{Style.RESET_ALL} ↩️  返回主菜单
        """)
        choice = input(f"{Fore.CYAN}请输入选项 (0-7): {Style.RESET_ALL}").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            await _add_custom_knowledge()
        elif choice == "2":
            await _list_custom_knowledge(entries)
        elif choice == "3":
            await _view_custom_knowledge(entries)
        elif choice == "4":
            await _edit_custom_knowledge(entries)
        elif choice == "5":
            await _delete_custom_knowledge(entries)
        elif choice == "6":
            await _search_custom_knowledge()
        elif choice == "7":
            await _ai_search_bilibili_and_add()
        else:
            print(f"{Fore.RED}[ERROR] 无效选项{Style.RESET_ALL}")


async def _ai_search_bilibili_and_add():
    """🤖 AI搜索B站相关视频 → 获取内容 → AI总结 → 入库"""
    import hashlib
    print(f"\n{Fore.LIGHTBLUE_EX}╔══════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLUE_EX}║  🤖 AI搜索B站并整理入库                                  ║{Style.RESET_ALL}")
    print(f"{Fore.LIGHTBLUE_EX}╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

    # 1. 用户输入主题
    topic = input(f"\n{Fore.CYAN}输入你想学习的主题/关键词: {Style.RESET_ALL}").strip()
    if not topic:
        print(f"{Fore.YELLOW}[WARN] 主题不能为空{Style.RESET_ALL}")
        return

    # 2. AI生成搜索关键词
    print(f"{Fore.CYAN}[INFO] AI正在生成B站搜索关键词...{Style.RESET_ALL}")
    try:
        client = OpenAI(api_key=config.get("api", {}).get("unified_api_key", ""), base_url=config.get("api", {}).get("unified_base_url", ""), timeout=15)
        resp = client.chat.completions.create(
            model=_get_model_brain(),
            messages=[
                {"role": "system", "content": "你是一个B站搜索助手。用户想学习某个主题，请生成1-3个适合在B站搜索的短关键词（每个不超过15字），用中文输出，逗号分隔。只输出关键词，不要多余文字。"},
                {"role": "user", "content": f"我想在B站学习: {topic}"}
            ]
        )
        search_queries = [q.strip() for q in resp.choices[0].message.content.strip().split(",") if q.strip()]
        print(f"{Fore.GREEN}[OK] 搜索关键词: {' | '.join(search_queries)}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}[WARN] AI生成关键词失败，直接使用原输入: {e}{Style.RESET_ALL}")
        search_queries = [topic]

    # 3. 搜索B站
    brain = AgentBrain()
    all_results = []
    seen_bvids = set()
    for q in search_queries:
        print(f"{Fore.CYAN}[INFO] 正在B站搜索: {q}...{Style.RESET_ALL}")
        try:
            results = await brain.bili.search_bilibili(q, limit=8)
            for r in results:
                bv = r.get("bvid", "")
                if bv and bv not in seen_bvids:
                    seen_bvids.add(bv)
                    all_results.append(r)
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] 搜索 '{q}' 失败: {e}{Style.RESET_ALL}")
        await asyncio.sleep(0.5)

    if not all_results:
        print(f"{Fore.RED}[ERROR] 未搜索到相关视频{Style.RESET_ALL}")
        return

    # 4. 显示结果，让用户选择
    print(f"\n{Fore.GREEN}找到 {len(all_results)} 个相关视频:{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'─' * 80}{Style.RESET_ALL}")
    for i, r in enumerate(all_results, 1):
        dur = r.get("duration", "??")
        play = r.get("play", 0)
        play_str = f"{play/10000:.1f}w" if play >= 10000 else str(play)
        title_display = r['title'][:45] if len(r['title']) > 45 else r['title']
        author = r.get('author', '?')
        print(f"  {Fore.YELLOW}{i:>2}.{Style.RESET_ALL} {title_display}")
        print(f"      {Fore.LIGHTBLACK_EX}@{author}  |  ▶ {play_str}  |  ⏱ {dur}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'─' * 80}{Style.RESET_ALL}")

    n_input = input(f"\n{Fore.CYAN}要分析几个视频？(回车默认5个，最多{len(all_results)}个): {Style.RESET_ALL}").strip()
    try:
        n = int(n_input) if n_input else 5
        n = max(1, min(n, len(all_results)))
    except ValueError:
        n = 5

    # 让用户选具体的视频
    chosen_indices = input(f"{Fore.CYAN}请选择视频编号（用逗号分隔，如 1,3,5，回车自动选前{n}个）: {Style.RESET_ALL}").strip()
    if chosen_indices:
        try:
            indices = [int(x.strip()) - 1 for x in chosen_indices.split(",") if x.strip().isdigit()]
            chosen = [all_results[i] for i in indices if 0 <= i < len(all_results)]
        except (ValueError, IndexError):
            print(f"{Fore.YELLOW}[WARN] 选择无效，自动选前{n}个{Style.RESET_ALL}")
            chosen = all_results[:n]
    else:
        chosen = all_results[:n]

    print(f"\n{Fore.GREEN}[OK] 将分析 {len(chosen)} 个视频:{Style.RESET_ALL}")
    for i, r in enumerate(chosen, 1):
        print(f"  {i}. {r.get('title', '?')[:50]}")

    # 5. 逐个分析视频
    all_summaries = []
    success_count = 0
    for idx, video in enumerate(chosen, 1):
        bvid = video.get("bvid", "")
        title = video.get("title", "")
        author = video.get("author", "")
        url = f"https://www.bilibili.com/video/{bvid}"
        
        print(f"\n{Fore.CYAN}[{idx}/{len(chosen)}] 正在分析: {title[:40]}...{Style.RESET_ALL}")
        
        # 获取字幕
        subtitle_ok, subtitle_text, video_desc, ai_verified = await fetch_bilibili_subtitles(
            bvid, cookies_obj=brain.cookies, title=title
        )
        
        if not subtitle_ok or not subtitle_text or len(subtitle_text.strip()) < 30:
            print(f"{Fore.YELLOW}[WARN] 视频 '{title[:30]}' 无有效字幕，跳过{Style.RESET_ALL}")
            continue
        
        # AI总结
        print(f"{Fore.CYAN}[INFO] AI正在总结内容...{Style.RESET_ALL}")
        try:
            client = OpenAI(api_key=config.get("api", {}).get("unified_api_key", ""), base_url=config.get("api", {}).get("unified_base_url", ""), timeout=30)
            resp = client.chat.completions.create(
                model=_get_model_brain(),
                messages=[
                    {"role": "system", "content": "你是B站视频学习助手。请根据视频字幕内容，提取核心知识点和关键信息，用简洁的markdown格式输出总结。突出重点，去除口语化填充。"},
                    {"role": "user", "content": f"标题: {title}\nUP主: {author}\n\n字幕内容:\n{subtitle_text[:3000]}"}
                ]
            )
            summary = resp.choices[0].message.content
            
            # 保存到知识库
            clean_title = sanitize_filename(title)
            entry_id = bvid
            filename = f"[{entry_id}] - {clean_title}.md"
            filepath = os.path.join(CUSTOM_KNOWLEDGE_DIR, filename)
            
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            full_content = (
                f"# 📚 视频知识归档\n\n"
                f"【信息】\n"
                f"- **标题**: {title}\n"
                f"- **UP主**: {author}\n"
                f"- **链接**: {url}\n"
                f"- **归档时间**: {now}\n"
                f"- **搜索主题**: {topic}\n\n"
                f"---\n\n"
                f"## [AI] 内容总结\n\n{summary}\n\n"
            )
            if video_desc:
                full_content += f"---\n\n## [简介]\n\n{video_desc}\n"
            if subtitle_text:
                full_content += f"\n---\n\n## [字幕原文]\n\n{subtitle_text[:2000]}\n"
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(full_content)
            
            # 更新metadata
            meta_path = os.path.join(BASE_DIR, "knowledge_metadata.json")
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta.setdefault("file_index", {}).setdefault("自定义知识", [])
            # 去重
            meta["file_index"]["自定义知识"] = [
                e for e in meta["file_index"]["自定义知识"]
                if e.get("bvid") != entry_id
            ]
            meta["file_index"]["自定义知识"].append({
                "bvid": entry_id,
                "title": title,
                "added": datetime.now().isoformat()
            })
            meta["last_updated"] = datetime.now().isoformat()
            _atomic_write_json(meta_path, meta)
            
            # 更新向量索引
            try:
                if brain.kb_search:
                    await brain.kb_search.update_entry(filepath)
            except Exception:
                pass
            
            all_summaries.append(f"## [{idx}] {title}\n- UP主: {author}\n- 链接: {url}\n\n{summary}\n")
            success_count += 1
            print(f"{Fore.GREEN}[OK] 已归档: {title[:40]}{Style.RESET_ALL}")
            
        except Exception as e:
            print(f"{Fore.RED}[ERROR] AI总结失败: {e}{Style.RESET_ALL}")
        
        # 视频间延迟
        if idx < len(chosen):
            await asyncio.sleep(1.0)

    # 6. 创建综合总结
    if all_summaries:
        combined_title = f"综合: {topic}"
        combined_entry_id = "combined_" + hashlib.md5(topic.encode()).hexdigest()[:8]
        
        print(f"\n{Fore.CYAN}[INFO] AI正在生成综合总结...{Style.RESET_ALL}")
        try:
            combined_text = "\n\n".join(all_summaries)
            client = OpenAI(api_key=config.get("api", {}).get("unified_api_key", ""), base_url=config.get("api", {}).get("unified_base_url", ""), timeout=30)
            resp = client.chat.completions.create(
                model=_get_model_brain(),
                messages=[
                    {"role": "system", "content": "你是知识整合助手。下面是从多个B站视频中提取的知识总结，请将它们整合成一篇连贯、结构清晰的学习笔记。按主题分类，去除重复内容，补充逻辑连接。用markdown格式输出。"},
                    {"role": "user", "content": f"学习主题: {topic}\n\n各视频总结:\n{combined_text[:4000]}"}
                ]
            )
            final_summary = resp.choices[0].message.content
        except Exception:
            final_summary = combined_text[:2000]
        
        clean_title = sanitize_filename(combined_title)
        combined_filename = f"[{combined_entry_id}] - {clean_title}.md"
        combined_filepath = os.path.join(CUSTOM_KNOWLEDGE_DIR, combined_filename)
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        combined_content = (
            f"# 📖 综合学习笔记\n\n"
            f"【信息】\n"
            f"- **主题**: {topic}\n"
            f"- **来源视频数**: {success_count} 个\n"
            f"- **创建时间**: {now}\n"
            f"- **ID**: {combined_entry_id}\n\n"
            f"---\n\n"
            f"## [AI] 综合总结\n\n{final_summary}\n\n"
            f"---\n\n"
            f"## [各视频原始总结]\n\n{combined_text}\n"
        )
        
        with open(combined_filepath, "w", encoding="utf-8") as f:
            f.write(combined_content)
        
        # 更新metadata
        meta_path = os.path.join(BASE_DIR, "knowledge_metadata.json")
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta.setdefault("file_index", {}).setdefault("自定义知识", [])
        meta["file_index"]["自定义知识"] = [
            e for e in meta["file_index"]["自定义知识"]
            if e.get("bvid") != combined_entry_id
        ]
        meta["file_index"]["自定义知识"].append({
            "bvid": combined_entry_id,
            "title": combined_title,
            "added": datetime.now().isoformat()
        })
        meta["last_updated"] = datetime.now().isoformat()
        _atomic_write_json(meta_path, meta)
        
        print(f"\n{Fore.LIGHTGREEN_EX}╔══════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
        print(f"{Fore.LIGHTGREEN_EX}║  🎉 AI搜索入库完成！                                     ║{Style.RESET_ALL}")
        print(f"{Fore.LIGHTGREEN_EX}╠══════════════════════════════════════════════════════════╣{Style.RESET_ALL}")
        print(f"{Fore.LIGHTGREEN_EX}║{Style.RESET_ALL}  {Fore.GREEN}✓ 成功归档: {success_count}/{len(chosen)} 个视频{Style.RESET_ALL}")
        print(f"{Fore.LIGHTGREEN_EX}║{Style.RESET_ALL}  {Fore.GREEN}✓ 综合笔记已生成{Style.RESET_ALL}")
        print(f"{Fore.LIGHTGREEN_EX}╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}[WARN] 没有成功分析的视频{Style.RESET_ALL}")


async def _add_custom_knowledge():
    """新增自定义知识条目"""
    print(f"\n{Fore.CYAN}[新增知识条目]{Style.RESET_ALL}")
    
    title = input(f"{Fore.GREEN}标题: {Style.RESET_ALL}").strip()
    if not title:
        print(f"{Fore.YELLOW}[WARN] 标题不能为空，取消{Style.RESET_ALL}")
        return
    
    print(f"{Fore.GREEN}内容 (输入 .end 单独一行结束):{Style.RESET_ALL}")
    lines = []
    while True:
        line = input()
        if line.strip() == ".end":
            break
        lines.append(line)
    content = "\n".join(lines).strip()
    if not content or len(content) < 10:
        print(f"{Fore.YELLOW}[WARN] 内容太少（至少10字），取消{Style.RESET_ALL}")
        return
    
    category = input(f"{Fore.GREEN}分类 (直接回车默认'自定义知识'): {Style.RESET_ALL}").strip()
    if not category:
        category = "自定义知识"
    
    # 生成唯一ID
    import hashlib
    entry_id = "custom_" + hashlib.md5(title.encode()).hexdigest()[:8]
    
    # AI总结
    print(f"{Fore.CYAN}[INFO] AI正在生成摘要...{Style.RESET_ALL}")
    try:
        client = OpenAI(api_key=config.get("api", {}).get("unified_api_key", ""), base_url=config.get("api", {}).get("unified_base_url", ""), timeout=30)
        resp = client.chat.completions.create(
            model=_get_model_brain(),
            messages=[
                {"role": "system", "content": "你是一个知识总结助手。请用简洁markdown格式总结以下用户提供的内容，提取核心知识点和关键信息。"},
                {"role": "user", "content": f"标题: {title}\n\n内容:\n{content}"}
            ]
        )
        summary = resp.choices[0].message.content
    except Exception as e:
        print(f"{Fore.YELLOW}[WARN] AI总结失败: {e}，使用原始内容{Style.RESET_ALL}")
        summary = content[:500]
    
    # 保存文件
    clean_title = sanitize_filename(title)
    filename = f"[{entry_id}] - {clean_title}.md"
    filepath = os.path.join(CUSTOM_KNOWLEDGE_DIR, filename)
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_content = (
        f"# 📝 自定义知识\n\n"
        f"【信息】\n"
        f"- **标题**: {title}\n"
        f"- **分类**: {category}\n"
        f"- **创建时间**: {now}\n"
        f"- **ID**: {entry_id}\n\n"
        f"---\n\n"
        f"## [AI] 摘要\n\n{summary}\n\n"
        f"---\n\n"
        f"## [原文]\n\n{content}\n"
    )
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_content)
    
    # 更新 metadata
    meta_path = os.path.join(BASE_DIR, "knowledge_metadata.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta.setdefault("file_index", {}).setdefault("自定义知识", [])
    # 检查是否已存在
    for e in meta["file_index"]["自定义知识"]:
        if e.get("bvid") == entry_id:
            print(f"{Fore.YELLOW}[WARN] 条目已存在: {title}{Style.RESET_ALL}")
            return
    meta["file_index"]["自定义知识"].append({
        "bvid": entry_id,
        "title": title,
        "added": datetime.now().isoformat()
    })
    meta["last_updated"] = datetime.now().isoformat()
    _atomic_write_json(meta_path, meta)
    
    print(f"{Fore.GREEN}[OK] 知识条目已添加！{Style.RESET_ALL}")
    print(f"{Fore.GREEN}  文件: {filepath}{Style.RESET_ALL}")
    
    # 更新向量索引
    try:
        brain = AgentBrain()
        if brain.kb_search:
            await brain.kb_search.update_entry(filepath)
            print(f"{Fore.GREEN}[OK] 向量索引已更新{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}[WARN] 向量索引更新失败: {e}{Style.RESET_ALL}")


async def _list_custom_knowledge(entries):
    """列出所有自定义知识条目"""
    if not entries:
        print(f"{Fore.YELLOW}[INFO] 暂无自定义知识条目{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.CYAN}📋 自定义知识列表 ({len(entries)} 条):{Style.RESET_ALL}")
    print(f"{'─' * 80}")
    print(f"{'#':>4} | {'标题':<40} | {'创建时间':<20}")
    print(f"{'─' * 80}")
    for idx, title, eid, fpath, added in entries:
        added_short = added[:10] if added else "未知"
        title_show = title[:38] if len(title) > 38 else title
        print(f"{idx:>4} | {title_show:<40} | {added_short:<20}")
    print(f"{'─' * 80}")


async def _view_custom_knowledge(entries):
    """查看条目详情"""
    if not entries:
        print(f"{Fore.YELLOW}[INFO] 暂无条目{Style.RESET_ALL}")
        return
    
    print(f"{Fore.CYAN}输入条目编号查看详情（输入 0 取消）:{Style.RESET_ALL}")
    try:
        n = int(input(f"{Fore.GREEN}编号: {Style.RESET_ALL}").strip())
    except ValueError:
        print(f"{Fore.RED}[ERROR] 无效编号{Style.RESET_ALL}")
        return
    if n <= 0 or n > len(entries):
        return
    
    idx, title, eid, fpath, added = entries[n - 1]
    if not os.path.exists(fpath):
        print(f"{Fore.RED}[ERROR] 文件不存在: {fpath}{Style.RESET_ALL}")
        return
    
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    
    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(f"{Fore.LIGHTGREEN_EX}[{n}] {title}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print(content)
    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    
    input(f"\n{Fore.YELLOW}按 Enter 返回...{Style.RESET_ALL}")


async def _edit_custom_knowledge(entries):
    """编辑条目"""
    if not entries:
        print(f"{Fore.YELLOW}[INFO] 暂无条目{Style.RESET_ALL}")
        return
    
    print(f"{Fore.CYAN}输入要编辑的条目编号（输入 0 取消）:{Style.RESET_ALL}")
    try:
        n = int(input(f"{Fore.GREEN}编号: {Style.RESET_ALL}").strip())
    except ValueError:
        print(f"{Fore.RED}[ERROR] 无效编号{Style.RESET_ALL}")
        return
    if n <= 0 or n > len(entries):
        return
    
    idx, title, eid, fpath, added = entries[n - 1]
    if not os.path.exists(fpath):
        print(f"{Fore.RED}[ERROR] 文件不存在{Style.RESET_ALL}")
        return
    
    with open(fpath, "r", encoding="utf-8") as f:
        old_content = f.read()
    
    print(f"\n{Fore.CYAN}编辑条目: {title}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}直接回车保持原值{Style.RESET_ALL}")
    
    new_title = input(f"{Fore.GREEN}新标题 ({title}): {Style.RESET_ALL}").strip()
    if not new_title:
        new_title = title
    
    print(f"{Fore.GREEN}新内容 (输入 .end 单独一行结束，直接回车保持原样):{Style.RESET_ALL}")
    lines = []
    first_line = input()
    if first_line.strip() != "":
        lines.append(first_line)
        while True:
            line = input()
            if line.strip() == ".end":
                break
            lines.append(line)
    
    if lines:
        new_content_text = "\n".join(lines).strip()
        # 更新文件内容，保留头部信息
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 从旧内容中提取摘要部分（[AI] 摘要 和 [原文] 之间）
        summary_part = ""
        if "[AI] 摘要" in old_content:
            parts = old_content.split("## [原文]")
            if len(parts) > 1:
                summary_part = ""
            ai_part = old_content.split("## [AI] 摘要")
            if len(ai_part) > 1:
                raw_parts = ai_part[1].split("## [原文]")
                if len(raw_parts) > 1:
                    summary_part = raw_parts[0].strip()
        
        full_content = (
            f"# 📝 自定义知识\n\n"
            f"【信息】\n"
            f"- **标题**: {new_title}\n"
            f"- **分类**: 自定义知识\n"
            f"- **创建时间**: {added}\n"
            f"- **最后编辑**: {now}\n"
            f"- **ID**: {eid}\n\n"
            f"---\n\n"
            f"## [AI] 摘要\n\n{summary_part if summary_part else '(待AI重新生成)'}\n\n"
            f"---\n\n"
            f"## [原文]\n\n{new_content_text}\n"
        )
        
        # AI重新生成摘要
        print(f"{Fore.CYAN}[INFO] AI正在重新生成摘要...{Style.RESET_ALL}")
        try:
            client = OpenAI(api_key=config.get("api", {}).get("unified_api_key", ""), base_url=config.get("api", {}).get("unified_base_url", ""), timeout=30)
            resp = client.chat.completions.create(
                model=_get_model_brain(),
                messages=[
                    {"role": "system", "content": "你是一个知识总结助手。请用简洁markdown格式总结以下内容。"},
                    {"role": "user", "content": f"标题: {new_title}\n\n内容:\n{new_content_text}"}
                ]
            )
            new_summary = resp.choices[0].message.content
            full_content = (
                f"# 📝 自定义知识\n\n"
                f"【信息】\n"
                f"- **标题**: {new_title}\n"
                f"- **分类**: 自定义知识\n"
                f"- **创建时间**: {added}\n"
                f"- **最后编辑**: {now}\n"
                f"- **ID**: {eid}\n\n"
                f"---\n\n"
                f"## [AI] 摘要\n\n{new_summary}\n\n"
                f"---\n\n"
                f"## [原文]\n\n{new_content_text}\n"
            )
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] AI摘要失败: {e}{Style.RESET_ALL}")
    else:
        # 只改标题，不改内容
        if new_title != title:
            full_content = old_content
            # 更新标题
            full_content = full_content.replace(
                f"- **标题**: {title}",
                f"- **标题**: {new_title}"
            )
            full_content += f"\n\n> 最后编辑: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        else:
            print(f"{Fore.YELLOW}[INFO] 无修改{Style.RESET_ALL}")
            return
    
    # 写回文件
    clean_title = sanitize_filename(new_title)
    new_filename = f"[{eid}] - {clean_title}.md"
    new_filepath = os.path.join(CUSTOM_KNOWLEDGE_DIR, new_filename)
    
    with open(new_filepath, "w", encoding="utf-8") as f:
        f.write(full_content)
    
    # 如果文件名变了，删旧文件
    if new_filepath != fpath and os.path.exists(fpath):
        os.remove(fpath)
    
    # 更新 metadata
    meta_path = os.path.join(BASE_DIR, "knowledge_metadata.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    for e in meta.setdefault("file_index", {}).setdefault("自定义知识", []):
        if e.get("bvid") == eid:
            e["title"] = new_title
            break
    meta["last_updated"] = datetime.now().isoformat()
    _atomic_write_json(meta_path, meta)
    
    print(f"{Fore.GREEN}[OK] 条目已更新！{Style.RESET_ALL}")
    
    # 更新向量索引
    try:
        brain = AgentBrain()
        if brain.kb_search:
            await brain.kb_search.update_entry(new_filepath)
    except Exception:
        pass


async def _delete_custom_knowledge(entries):
    """删除条目"""
    if not entries:
        print(f"{Fore.YELLOW}[INFO] 暂无条目{Style.RESET_ALL}")
        return
    
    print(f"{Fore.CYAN}输入要删除的条目编号（输入 0 取消）:{Style.RESET_ALL}")
    try:
        n = int(input(f"{Fore.GREEN}编号: {Style.RESET_ALL}").strip())
    except ValueError:
        print(f"{Fore.RED}[ERROR] 无效编号{Style.RESET_ALL}")
        return
    if n <= 0 or n > len(entries):
        return
    
    idx, title, eid, fpath, added = entries[n - 1]
    
    print(f"\n{Fore.RED}⚠️  确认删除: [{n}] {title}{Style.RESET_ALL}")
    confirm = input(f"{Fore.YELLOW}输入 YES 确认删除: {Style.RESET_ALL}").strip()
    if confirm != "YES":
        print(f"{Fore.GREEN}[INFO] 已取消{Style.RESET_ALL}")
        return
    
    # 删文件
    if os.path.exists(fpath):
        os.remove(fpath)
        print(f"{Fore.GREEN}[OK] 文件已删除{Style.RESET_ALL}")
    
    # 更新 metadata
    meta_path = os.path.join(BASE_DIR, "knowledge_metadata.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta.setdefault("file_index", {}).setdefault("自定义知识", [])
    meta["file_index"]["自定义知识"] = [
        e for e in meta["file_index"]["自定义知识"]
        if e.get("bvid") != eid
    ]
    meta["last_updated"] = datetime.now().isoformat()
    _atomic_write_json(meta_path, meta)
    
    print(f"{Fore.GREEN}[OK] 条目已删除{Style.RESET_ALL}")


async def _search_custom_knowledge():
    """搜索自定义知识内容"""
    query = input(f"\n{Fore.CYAN}🔍 搜索关键词: {Style.RESET_ALL}").strip()
    if not query:
        return
    
    results = []
    if not os.path.exists(CUSTOM_KNOWLEDGE_DIR):
        print(f"{Fore.YELLOW}[INFO] 暂无自定义知识{Style.RESET_ALL}")
        return
    
    for fname in os.listdir(CUSTOM_KNOWLEDGE_DIR):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(CUSTOM_KNOWLEDGE_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            if query.lower() in content.lower():
                # 提取标题
                title = fname
                for line in content.split("\n"):
                    if line.startswith("- **标题**: "):
                        title = line.replace("- **标题**: ", "").strip()
                        break
                results.append((title, fpath))
        except Exception:
            continue
    
    if not results:
        print(f"{Fore.YELLOW}[INFO] 未找到匹配 '{query}' 的条目{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.CYAN}🔍 找到 {len(results)} 个匹配条目:{Style.RESET_ALL}")
    print(f"{'─' * 60}")
    for i, (title, fpath) in enumerate(results, 1):
        print(f"  {i}. {title}")
    print(f"{'─' * 60}")
    
    # 查看详情
    try:
        n = input(f"\n{Fore.GREEN}输入编号查看详情（回车跳过）: {Style.RESET_ALL}").strip()
        if n and n.isdigit():
            n = int(n)
            if 1 <= n <= len(results):
                title, fpath = results[n - 1]
                with open(fpath, "r", encoding="utf-8") as f:
                    print(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
                    print(f"{Fore.LIGHTGREEN_EX}{title}{Style.RESET_ALL}")
                    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
                    print(f.read())
                    print(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
                input(f"\n{Fore.YELLOW}按 Enter 返回...{Style.RESET_ALL}")
    except Exception:
        pass


async def _call_ai_with_retry_static(model, messages, request_timeout=30, max_retries=2):
    """静态AI调用辅助函数（不依赖brain实例），带重试"""
    for attempt in range(max_retries + 1):
        try:
            client = OpenAI(api_key=config.get("api", {}).get("unified_api_key", ""), base_url=config.get("api", {}).get("unified_base_url", ""), timeout=request_timeout)
            resp = client.chat.completions.create(
                model=model,
                messages=messages
            )
            return resp
        except Exception as e:
            if attempt < max_retries:
                wait = min(3 * (2 ** attempt), 10)
                print(f"  {Fore.YELLOW}AI重试 ({attempt+1}/{max_retries})，等待{wait}s...{Style.RESET_ALL}")
                await asyncio.sleep(wait)
            else:
                raise


# ==============================================================================
# [START] 主程序入口
# ==============================================================================
