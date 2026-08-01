"""knowledge/browse.py — 知识库浏览/搜索/整理"""
import os
import json
import re
from datetime import datetime

from colorama import Fore, Style
from core.config import KNOWLEDGE_BASE_DIR, config, BASE_DIR
from utils.display import log

KB_METADATA_FILE = os.path.join(BASE_DIR, "knowledge_metadata.json")
LEARNING_LOG_FILE = os.path.join(BASE_DIR, "learning_log.md")

def count_knowledge_categories():
    """统计知识库分类数量（从 file_index 多级路径统计，自动清理失效条目）"""
    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        return "0"
    try:
        # [FIX] 使用正确路径（metadata 在 BASE_DIR 下，不在 KnowledgeBase 内）
        if os.path.exists(KB_METADATA_FILE):
            with open(KB_METADATA_FILE, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            file_index = meta.get("file_index", {})
            
            # [NEW] 清理 file_index 中文件已不存在于磁盘的条目
            cleaned = False
            new_file_index = {}
            for fpath, entries in file_index.items():
                if not entries:
                    cleaned = True
                    continue
                valid_entries = []
                for entry in entries:
                    bvid = entry.get("bvid", "")
                    cat_dir = os.path.join(KNOWLEDGE_BASE_DIR, fpath)
                    bvid_prefix = f"[{bvid}]"
                    found = False
                    if os.path.isdir(cat_dir):
                        for fname in os.listdir(cat_dir):
                            if fname.startswith(bvid_prefix) and fname.endswith('.md'):
                                found = True
                                break
                    if found:
                        valid_entries.append(entry)
                    else:
                        cleaned = True
                if valid_entries:
                    new_file_index[fpath] = valid_entries
                else:
                    cleaned = True
            
            if cleaned:
                meta["file_index"] = new_file_index
                meta["last_updated"] = datetime.now().isoformat()
                tmp = KB_METADATA_FILE + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
                os.replace(tmp, KB_METADATA_FILE)
            
            # 统计有文件的所有分类
            cats = set()
            for fpath, flist in new_file_index.items():
                if flist:
                    cats.add(fpath)
            return str(len(cats))
        # 降级：按文件夹统计
        folders = [f for f in os.listdir(KNOWLEDGE_BASE_DIR) 
                  if os.path.isdir(os.path.join(KNOWLEDGE_BASE_DIR, f)) 
                  and not f.startswith('.')]
        return str(len(folders))
    except Exception as e:
        return f"ERR:{e}"


def browse_kb_structure():
    """浏览知识库结构"""
    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        print(f"{Fore.YELLOW}[WARN]  知识库目录不存在！{Style.RESET_ALL}")
        return
    
    def print_tree(path, prefix=""):
        items = os.listdir(path)
        items = [i for i in items if not i.startswith('.')]
        
        for i, item in enumerate(sorted(items)):
            is_last = i == len(items) - 1
            item_path = os.path.join(path, item)
            
            if os.path.isdir(item_path):
                print(f"{prefix}{'└── ' if is_last else '├── '}[FILE] {Fore.GREEN}{item}{Style.RESET_ALL}")
                new_prefix = prefix + ("    " if is_last else "│   ")
                print_tree(item_path, new_prefix)
            elif item.endswith(('.txt', '.md')):
                size = os.path.getsize(item_path) / 1024
                print(f"{prefix}{'└── ' if is_last else '├── '}📄 {Fore.BLUE}{item}{Style.RESET_ALL} ({size:.1f}KB)")
    
    print(f"\n{Fore.CYAN}知识库目录结构:{Style.RESET_ALL}")
    print(f"📂 {KNOWLEDGE_BASE_DIR}")
    print_tree(KNOWLEDGE_BASE_DIR)


def search_knowledge_content():
    """搜索知识内容（向量语义搜索 + 关键词 fallback）"""
    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        print(f"{Fore.YELLOW}[WARN]  知识库目录不存在！{Style.RESET_ALL}")
        return
    
    keyword = input(f"{Fore.YELLOW}请输入搜索关键词: {Style.RESET_ALL}").strip()
    if not keyword:
        print(f"{Fore.RED}[ERROR] 搜索关键词不能为空！{Style.RESET_ALL}")
        return
    
    print(f"\n{Fore.CYAN}正在搜索 '{keyword}'...{Style.RESET_ALL}")

    # 尝试向量搜索
    used_vector = False
    vector_results = []
    if KBSearchEngine and ModelClient and load_modular_settings and BotState:
        try:
            settings = load_modular_settings()
            engine = KBSearchEngine(ModelClient(settings, BotState()))
            idx_stats = engine.stats()
            if idx_stats["vectorized"] > 0:
                vector_results = engine.search(keyword, top_k=20)
                used_vector = True
            else:
                built = engine.build_index()
                if built > 0:
                    vector_results = engine.search(keyword, top_k=20)
                    used_vector = True
        except Exception:
            pass

    # 关键词搜索（fallback）
    keyword_results = []
    for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            if file.endswith(('.txt', '.md')):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if keyword.lower() in content.lower():
                            count = content.lower().count(keyword.lower())
                            rel_path = os.path.relpath(file_path, KNOWLEDGE_BASE_DIR)
                            keyword_results.append({
                                'path': rel_path,
                                'count': count,
                                'content': content[:200] + "..." if len(content) > 200 else content
                            })
                except (OSError, UnicodeDecodeError, Exception):
                    continue

    if used_vector and vector_results:
        print(f"\n{Fore.CYAN}🧠 语义搜索结果:{Style.RESET_ALL}")
        for i, r in enumerate(vector_results[:10]):
            path = r.get("path", r.get("bvid", "?"))
            title = r.get("title", "")
            score = r.get("score", 0)
            print(f"\n{Fore.YELLOW}{i+1}. [{score:.2f}] {title}{Style.RESET_ALL}")
            print(f"   路径: {path}")
            snippet = r.get("snippet", "")
            if snippet:
                print(f"   预览: {snippet[:150]}...")
        if len(vector_results) > 10:
            print(f"\n{Fore.YELLOW}... 还有 {len(vector_results)-10} 个语义结果{Style.RESET_ALL}")

    if keyword_results:
        print(f"\n{Fore.GREEN}[关键词] 找到 {len(keyword_results)} 个结果:{Style.RESET_ALL}")
        keyword_results.sort(key=lambda x: x['count'], reverse=True)
        for i, result in enumerate(keyword_results[:10]):
            print(f"\n{Fore.YELLOW}{i+1}. {result['path']}{Style.RESET_ALL}")
            print(f"   匹配次数: {result['count']}")
            preview = result['content']
            preview_highlighted = preview.replace(keyword, f"{Fore.RED}{keyword}{Style.RESET_ALL}")
            print(f"   内容预览: {preview_highlighted}")
        if len(keyword_results) > 10:
            print(f"\n{Fore.YELLOW}... 还有 {len(keyword_results)-10} 个结果未显示{Style.RESET_ALL}")

    if not used_vector and not keyword_results:
        print(f"\n{Fore.YELLOW}[WARN]  未找到包含 '{keyword}' 的内容{Style.RESET_ALL}")
    elif not vector_results and not keyword_results:
        print(f"\n{Fore.YELLOW}[WARN]  未找到包含 '{keyword}' 的内容{Style.RESET_ALL}")


def cleanup_duplicates():
    """清理重复内容"""
    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        print(f"{Fore.YELLOW}[WARN]  知识库目录不存在！{Style.RESET_ALL}")
        return
    
    print(f"{Fore.YELLOW}[WARN]  正在扫描重复内容...{Style.RESET_ALL}")
    
    content_hashes = {}
    duplicates = []
    
    for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
        for file in files:
            if file.endswith(('.txt', '.md')):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        content_hash = hash(content[:1000])
                        
                        if content_hash in content_hashes:
                            duplicates.append({
                                'original': content_hashes[content_hash],
                                'duplicate': file_path
                            })
                        else:
                            content_hashes[content_hash] = file_path
                except (OSError, UnicodeDecodeError):
                    continue
    
    if duplicates:
        print(f"\n{Fore.YELLOW}[WARN]  发现 {len(duplicates)} 个可能的重复文件:{Style.RESET_ALL}")
        for i, dup in enumerate(duplicates):
            print(f"\n{i+1}. 重复文件: {os.path.basename(dup['duplicate'])}")
            print(f"   可能重复于: {os.path.basename(dup['original'])}")
            print(f"   重复文件路径: {dup['duplicate']}")
        
        confirm = input(f"\n{Fore.RED}是否删除重复文件？(y/N): {Style.RESET_ALL}").strip().lower()
        if confirm == 'y':
            deleted = 0
            for dup in duplicates:
                try:
                    os.remove(dup['duplicate'])
                    deleted += 1
                    log(f"已删除: {os.path.basename(dup['duplicate'])}", "KB")
                except (OSError, PermissionError, Exception):
                    log(f"删除失败: {dup['duplicate']}", "ERROR")
            print(f"{Fore.GREEN}[OK] 已删除 {deleted} 个重复文件{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}[OK] 未发现重复内容{Style.RESET_ALL}")

