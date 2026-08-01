"""knowledge/classifier.py — 知识库智能分类系统"""
import os
import json
import re
import shutil
from datetime import datetime
from colorama import Fore, Style

from openai import OpenAI

from core.config import config, KNOWLEDGE_BASE_DIR, BASE_DIR
# 从 config 实时读取，避免 import * 缓存问题
def _get_model_brain():
    return config.get("api", {}).get("model_brain", "")
from utils.helpers import sanitize_filename

KB_METADATA_FILE = os.path.join(BASE_DIR, "knowledge_metadata.json")
from utils.display import log

class KnowledgeBaseClassifier:
    """知识库分类器 - 智能分类系统"""
    
    def __init__(self):
        self.metadata = self._load_metadata()
        self.max_depth = 3
        # [FIX] 初始化时同步 categories 树，修复历史数据不同步
        self._sync_categories_from_file_index()
        
    def _load_metadata(self):
        if os.path.exists(KB_METADATA_FILE):
            try:
                with open(KB_METADATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                log(f'加载JSON文件失败: {e}', 'DEBUG')
        return {
            "categories": {},
            "file_index": {},
            "last_updated": datetime.now().isoformat()
        }
    
    def _save_metadata(self):
        self.metadata["last_updated"] = datetime.now().isoformat()
        try:
            tmp = KB_METADATA_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
            os.replace(tmp, KB_METADATA_FILE)
        except Exception as e:
            log(f"保存元数据失败: {e}", "ERROR")
    
    def _get_all_categories(self):
        all_cats = []
        
        def traverse_tree(tree, prefix=""):
            for cat_name, sub_cats in tree.items():
                full_path = f"{prefix}/{cat_name}" if prefix else cat_name
                all_cats.append(full_path)
                if sub_cats:
                    traverse_tree(sub_cats, full_path)
        
        traverse_tree(self.metadata.get("categories", {}))
        return all_cats
    
    def _find_best_category(self, content_title, subtitle_text, existing_categories):
        try:
            # 只提取顶层分类（让AI可以自由选择或新建）
            top_level_cats = set()
            for cat in existing_categories:
                top = cat.split('/')[0].strip()
                if top:
                    top_level_cats.add(top)
            top_level_list = sorted(top_level_cats)

            context = f"""
            视频标题: {content_title}
            
            内容摘要: {subtitle_text[:1000]}... (总长度: {len(subtitle_text)})
            
            现有顶层分类:
            {chr(10).join(['- ' + cat for cat in top_level_list])}
            
            请根据视频内容，选择一个分类路径（1~3层，如"美食"、"编程/Python"、"游戏/独立开发/Godot"）。
            
            选择原则:
            1. 如果内容适合现有顶层分类 → 在它下面补全1-3层路径
            2. 如果现有分类都不合适 → 大胆创建新的顶层分类（如美食、音乐、运动、历史、设计等）
            3. 分类路径1-3层均可，不强制3层
            4. 每层名称简洁（2-6个汉字或英文词为佳）
            5. 尽量避免"其他""杂项""综合"等无意义名称
            
            返回JSON:
            {{
                "selected_category": "编程/Python/Web框架",
                "reason": "选择理由",
                "is_new": true/false,
                "confidence": 0-1
            }}
            """
            
            client = OpenAI(api_key=config.get("api", {}).get("unified_api_key", ""), base_url=config.get("api", {}).get("unified_base_url", ""), timeout=120)
            response = client.chat.completions.create(
                model=_get_model_brain(),
                messages=[
                    {"role": "system", "content": "你是一个专业的知识库分类专家。要大胆创建新分类，不要强行把不相关的内容塞进现有分类。"},
                    {"role": "user", "content": context}
                ]
            )
            
            raw = response.choices[0].message.content.strip()
            if not raw:
                raise ValueError("AI返回空内容")
            # [FIX] 多策略JSON提取（支持 markdown 代码块、非标准 JSON 等）
            # 去掉 markdown 代码块
            if "```" in raw:
                import re as _re
                code_match = _re.search(r"```(?:json)?\s*\n?(.*?)```", raw, _re.DOTALL)
                if code_match:
                    raw = code_match.group(1).strip()
            start = raw.find("{")
            if start >= 0:
                # 嵌套匹配
                depth = 0
                match_end = -1
                for i in range(start, len(raw)):
                    if raw[i] == '{':
                        depth += 1
                    elif raw[i] == '}':
                        depth -= 1
                        if depth == 0:
                            match_end = i
                            break
                if match_end < 0:
                    end = raw.rfind("}")
                    if end >= start:
                        raw = raw[start:end+1]
                else:
                    raw = raw[start:match_end+1]
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                # 修复常见JSON问题：未加引号的key、单引号、中文引号等
                fixed = raw
                # 修复未加引号的key (如 selected_category: → "selected_category":)
                fixed = re.sub(r'(?<=\{|,)\s*(\w+)\s*:', r'"\1":', fixed)
                # 修复单引号值
                fixed = re.sub(r":\s*'([^']*)'", r': "\1"', fixed)
                # 修复中文引号
                fixed = fixed.replace('"', '"').replace('"', '"')
                fixed = fixed.replace(''', "'").replace(''', "'")
                # 修复布尔值
                fixed = re.sub(r'\bTrue\b', 'true', fixed)
                fixed = re.sub(r'\bFalse\b', 'false', fixed)
                try:
                    result = json.loads(fixed)
                except json.JSONDecodeError:
                    raise
            return result
            
        except Exception as e:
            log(f"AI分类分析失败: {e}", "ERROR")
            return {
                "selected_category": "未分类",
                "reason": "分类分析失败",
                "is_new": False,
                "confidence": 0
            }
    
    def _create_category_structure(self, category_path):
        parts = [p.strip() for p in category_path.split('/') if p.strip()]
        
        # 限制最大深度但不再强制补齐到3层
        if len(parts) > self.max_depth:
            parts = parts[:self.max_depth]
        
        current_level = self.metadata["categories"]
        full_path = ""
        
        for i, part in enumerate(parts):
            clean_part = sanitize_filename(part, is_folder=True)
            if not clean_part:
                clean_part = f"分类_{i+1}"
            
            if full_path:
                full_path = f"{full_path}/{clean_part}"
            else:
                full_path = clean_part
            
            if clean_part not in current_level:
                current_level[clean_part] = {}
                log(f"创建新分类: {clean_part}", "KB")
            
            current_level = current_level[clean_part]
        
        return full_path
    
    def _get_category_tree(self):
        """递归渲染分类树，正确处理任意深度和 is_last 标记"""
        def format_tree(tree, prefix=""):
            result = []
            items = list(tree.items())
            for i, (name, subtree) in enumerate(items):
                is_last = (i == len(items) - 1)
                branch = "└── " if is_last else "├── "
                
                # 图标和颜色按深度选择
                depth = prefix.count("│") + prefix.count("    ")  # 粗略估算深度
                if depth == 0:
                    icon_color = f"[FILE] {Fore.GREEN}{name}{Style.RESET_ALL}"
                elif depth == 1:
                    icon_color = f"📂 {Fore.YELLOW}{name}{Style.RESET_ALL}"
                elif depth == 2:
                    icon_color = f"[FILE] {Fore.CYAN}{name}{Style.RESET_ALL}"
                else:
                    icon_color = f"📄 {Fore.MAGENTA}{name}{Style.RESET_ALL}"
                
                result.append(f"{prefix}{branch}{icon_color}")
                
                if subtree:
                    # 子节点延续竖线：当前不是最后一个 → "│   "，是最后一个 → "    "
                    child_prefix = prefix + ("    " if is_last else "│   ")
                    result.extend(format_tree(subtree, child_prefix))
            return result
        
        tree_lines = format_tree(self.metadata.get("categories", {}))
        return "\n".join(tree_lines) if tree_lines else "暂无分类"
    
    def classify_content(self, content_title, subtitle_text, bvid, topic_suggestion=None):
        log(f"开始智能分类: {content_title}", "KB")
        
        existing_categories = self._get_all_categories()
        
        if topic_suggestion:
            clean_topic = sanitize_filename(topic_suggestion, is_folder=True)
            for cat in existing_categories:
                if clean_topic.lower() in cat.lower():
                    log(f"使用AI建议分类: {cat}", "KB")
                    return cat
        
        ai_result = self._find_best_category(content_title, subtitle_text, existing_categories)
        
        selected_category = ai_result.get("selected_category", "未分类")
        is_new = ai_result.get("is_new", False)
        confidence = ai_result.get("confidence", 0)
        
        log(f"AI分类结果: {selected_category} (置信度: {confidence:.2%}, 新分类: {is_new})", "KB")
        
        if confidence < 0.3:
            log("AI分类置信度过低，使用默认分类", "WARN")
            selected_category = "未分类"
            is_new = False
        
        if is_new:
            final_category = self._create_category_structure(selected_category)
        else:
            final_category = selected_category
        
        if final_category not in self.metadata["file_index"]:
            self.metadata["file_index"][final_category] = []
        
        self.metadata["file_index"][final_category].append({
            "bvid": bvid,
            "title": content_title,
            "added": datetime.now().isoformat()
        })
        
        # [FIX] 同步 categories 元数据树（确保 file_index 和 categories 一致）
        self._sync_categories_from_file_index()
        self._save_metadata()
        
        return final_category
    
    def _sync_categories_from_file_index(self):
        """从 file_index 路径重建 categories 元数据树，消除显示不同步"""
        tree = {}
        for fpath in self.metadata.get("file_index", {}):
            parts = fpath.split("/")
            current = tree
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
        self.metadata["categories"] = tree
    
    def get_or_create_folder(self, category_path):
        os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
        
        if category_path == "未分类":
            category_folder = os.path.join(KNOWLEDGE_BASE_DIR, "未分类")
            os.makedirs(category_folder, exist_ok=True)
            return category_folder
        
        parts = [p.strip() for p in category_path.split('/') if p.strip()]
        
        current_path = KNOWLEDGE_BASE_DIR
        for i, part in enumerate(parts):
            clean_part = sanitize_filename(part, is_folder=True)
            if not clean_part:
                clean_part = f"分类_{i+1}"
            
            current_path = os.path.join(current_path, clean_part)
            
            if not os.path.exists(current_path):
                os.makedirs(current_path)
                log(f"创建分类文件夹: {current_path}", "KB")
            
            if i >= self.max_depth - 1:
                break
        
        return current_path
    
    def _prune_stale_file_index(self):
        """清理 file_index 中文件已不存在于磁盘的条目，并移除空分类"""
        file_index = self.metadata.get("file_index", {})
        removed_entries = 0
        removed_paths = []
        new_file_index = {}
        
        for fpath, entries in file_index.items():
            if not entries:
                # 空列表直接丢弃
                removed_paths.append(fpath)
                continue
            
            valid_entries = []
            for entry in entries:
                bvid = entry.get("bvid", "")
                title = entry.get("title", "")
                # 按 [BVid] 前缀模糊匹配（标题可能因 sanitize_filename 而有微小差异）
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
                    removed_entries += 1
            
            if valid_entries:
                new_file_index[fpath] = valid_entries
            else:
                removed_paths.append(fpath)
        
        if removed_entries > 0 or removed_paths:
            self.metadata["file_index"] = new_file_index
            # 重建 categories 树
            self._sync_categories_from_file_index()
            self._save_metadata()
            log(f"[KB] 清理失效条目: {removed_entries} 个文件记录, {len(removed_paths)} 个空分类已移除", "KB")
    
    def show_category_structure(self):
        """从 file_index 动态重建完整分类树并展示（不再依赖可能不同步的 categories 元数据）"""
        # 先清理磁盘上不存在的条目
        self._prune_stale_file_index()
        
        print(f"\n{Fore.CYAN}知识库分类结构:{Style.RESET_ALL}")
        
        file_index = self.metadata.get("file_index", {})
        
        # 从 file_index 的路径中重建完整分类树
        full_tree = {}
        for fpath in sorted(file_index.keys()):
            parts = fpath.split("/")
            current = full_tree
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
        
        # 渲染纯分类树（跳过无文件且无后代文件的空分类）
        def _node_has_any_file(path_key, subtree):
            """递归判断节点下是否有任何文件"""
            if path_key in file_index and file_index[path_key]:
                return True
            if subtree:
                for sn, st in subtree.items():
                    sub_path = f"{path_key}/{sn}" if path_key else sn
                    if _node_has_any_file(sub_path, st):
                        return True
            return False
        
        def render_tree(tree, prefix="", depth=0, parent_path=""):
            result = []
            items = list(tree.items())
            for i, (name, subtree) in enumerate(items):
                cur_path = f"{parent_path}/{name}" if parent_path else name
                # 跳过空节点
                if not _node_has_any_file(cur_path, subtree):
                    continue
                is_last = (i == len(items) - 1)
                branch = "└── " if is_last else "├── "
                if depth == 0:
                    icon_color = f"📁 {Fore.GREEN}{name}{Style.RESET_ALL}"
                elif depth == 1:
                    icon_color = f"📂 {Fore.YELLOW}{name}{Style.RESET_ALL}"
                else:
                    icon_color = f"📄 {Fore.CYAN}{name}{Style.RESET_ALL}"
                result.append(f"{prefix}{branch}{icon_color}")
                if subtree:
                    child_prefix = prefix + ("    " if is_last else "│   ")
                    result.extend(render_tree(subtree, child_prefix, depth + 1, cur_path))
            return result
        
        tree_lines = render_tree(full_tree)
        print("\n".join(tree_lines) if tree_lines else "暂无分类")
        
        # 按树形结构展示文件统计（跳过0文件且无后代文件的空文件夹）
        total_files = 0
        
        def print_file_stats(tree, prefix="", parent_path=""):
            nonlocal total_files
            items = list(tree.items())
            for i, (name, subtree) in enumerate(items):
                is_last = (i == len(items) - 1)
                branch = "└── " if is_last else "├── "
                cur_path = f"{parent_path}/{name}" if parent_path else name
                
                # [FIX] 只统计直接属于本路径的文件
                file_count = len(file_index.get(cur_path, []))
                
                # 跳过0文件且子孙也没有文件的空节点
                has_sub_files = False
                if subtree:
                    # 递归检查子树是否有实际文件
                    def _sub_has(p, t):
                        for sn, st in t.items():
                            sp = f"{p}/{sn}" if p else sn
                            if len(file_index.get(sp, [])) > 0:
                                return True
                            if st and _sub_has(sp, st):
                                return True
                        return False
                    has_sub_files = _sub_has(cur_path, subtree)
                
                if file_count > 0 and not subtree:
                    # 叶子节点有文件
                    total_files += file_count
                    print(f"{prefix}{branch}{Fore.CYAN}{name}{Style.RESET_ALL}: {file_count} 个文件")
                elif file_count > 0 or has_sub_files:
                    # 有文件或有后代文件的中间节点
                    if file_count > 0:
                        total_files += file_count
                    print(f"{prefix}{branch}{Fore.CYAN}{name}{Style.RESET_ALL}: {file_count} 个文件")
                else:
                    # 跳过空节点
                    continue
                
                if subtree:
                    child_prefix = prefix + ("    " if is_last else "│   ")
                    print_file_stats(subtree, child_prefix, cur_path)
        
        print_file_stats(full_tree)
        
        total_cats = len([p for p in file_index if file_index[p]])  # 只统计有文件的分类
        print(f"{Fore.YELLOW}总计: {total_files} 个文件分布在 {total_cats} 个分类中{Style.RESET_ALL}")

    def reclassify_uncategorized(self, max_per_run=5):
        """[KB] 自动重分类"未分类"文件夹中的文件，返回 (成功数, 失败数)"""
        file_index = self.metadata.get("file_index", {})
        uncategorized = file_index.get("未分类", [])
        if not uncategorized:
            log("[KB] 未分类文件夹为空，无需重分类", "KB")
            return 0, 0

        total = len(uncategorized)
        batch = uncategorized[:max_per_run]
        success_count = 0
        fail_count = 0

        log(f"[KB] 开始重分类: {total}个未分类文件，本轮处理{len(batch)}个", "KB")

        for item in batch:
            bvid = item["bvid"]
            title = item.get("title", "")

            try:
                # 用标题+空内容做AI分类（没有字幕文本时纯靠标题）
                new_cat = self._find_best_category(title, "", self._get_all_categories())
                selected = new_cat.get("selected_category", "未分类")
                conf = new_cat.get("confidence", 0)

                if selected == "未分类" or conf < 0.3:
                    log(f"[KB] 重分类跳过: '{title[:30]}' -> 未分类(置信度{conf:.2%})", "WARN")
                    fail_count += 1
                    continue

                # 执行分类迁移
                if new_cat.get("is_new"):
                    final_cat = self._create_category_structure(selected)
                else:
                    final_cat = selected

                if final_cat not in file_index:
                    file_index[final_cat] = []
                file_index[final_cat].append({
                    "bvid": bvid,
                    "title": title,
                    "added": datetime.now().isoformat()
                })

                # 从"未分类"移除（保留原条目用于记录，但标记已迁移）
                file_index["未分类"] = [e for e in file_index["未分类"] if e["bvid"] != bvid]

                # 物理文件迁移
                old_folder = os.path.join(KNOWLEDGE_BASE_DIR, "未分类")
                new_folder = self.get_or_create_folder(final_cat)
                for fname in os.listdir(old_folder):
                    if bvid in fname and fname.endswith(".md"):
                        src = os.path.join(old_folder, fname)
                        dst = os.path.join(new_folder, fname)
                        try:
                            shutil.move(src, dst)
                            log(f"[KB] 文件已迁移: '{fname}' -> {new_folder}", "KB")
                        except Exception as e:
                            log(f"[KB] 文件迁移失败 ({fname}): {e}", "WARN")
                        break

                log(f"[KB] 重分类成功: '{title[:30]}' -> {final_cat} (置信度{conf:.2%})", "SUCCESS")
                success_count += 1

            except Exception as e:
                log(f"[KB] 重分类异常 ({title}): {e}", "ERROR")
                fail_count += 1

        # 同步 + 保存
        self._sync_categories_from_file_index()
        self._save_metadata()

        # 清理"未分类"空目录
        if config.get('knowledge', {}).get('auto_reclassify_clean_empty', True) and not file_index.get("未分类"):
            unc_dir = os.path.join(KNOWLEDGE_BASE_DIR, "未分类")
            if os.path.isdir(unc_dir):
                try:
                    shutil.rmtree(unc_dir)
                    log(f"[KB] 已删除空'未分类'文件夹", "KB")
                except OSError as e:
                    log(f"[KB] 删除'未分类'文件夹失败: {e}", "WARN")

        return success_count, fail_count

    def cleanup_empty_folders(self):
        """[KB] 清理知识库中所有空文件夹（无子文件且无子目录有文件）"""
        cleaned = 0
        for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR, topdown=False):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            rel = os.path.relpath(root, KNOWLEDGE_BASE_DIR)
            if rel == ".":
                continue
            has_files = len(files) > 0
            has_sub_with_files = False
            for d in dirs:
                sub = os.path.join(root, d)
                for _, subdirs2, files2 in os.walk(sub):
                    if files2 or subdirs2:
                        has_sub_with_files = True
                        break
                if has_sub_with_files:
                    break
            if not has_files and not has_sub_with_files:
                try:
                    os.rmdir(root)  # 只删除真正空的
                    log(f"[KB] 清理空文件夹: {rel}", "KB")
                    cleaned += 1
                except OSError as e:
                    log(f'文件操作失败: {e}', 'DEBUG')
        return cleaned

    async def reclassify_all_three_levels(self, max_batch=20):
        """[KB] AI全面整理知识库：将所有文件重新规划为统一的3层分类结构。
        
        流程：
        1. 收集所有现有文件的标题和当前路径
        2. 发给AI，让它设计一个统一的3层分类树
        3. 逐个文件按新分类迁移
        4. 清理旧空文件夹
        
        返回: (moved_count, total_count)
        """
        file_index = self.metadata.get("file_index", {})
        all_files = []
        for fpath, flist in file_index.items():
            if not flist:
                continue
            for item in flist:
                all_files.append({
                    "bvid": item["bvid"],
                    "title": item.get("title", ""),
                    "old_path": fpath
                })
        if not all_files:
            log("[KB] 知识库为空，无需整理", "KB")
            return 0, 0

        log(f"[KB] AI开始全面整理知识库: {len(all_files)}个文件，目标3层分类", "KB")

        # 第一步：让AI设计统一的3层分类树
        file_list_text = "\n".join(
            f"- [{f['bvid']}] {f['title'][:60]} (当前: {f['old_path']})"
            for f in all_files
        )

        prompt = f"""你是一个知识库架构师。现有知识库包含{len(all_files)}个文件，需要重新规划为统一的3层分类结构。

要求：
1. 所有分类必须恰好3层（如：科技/AI工具/视频创作）
2. 分类名简洁（4字以内），层级逻辑合理（大类→中类→小类）
3. 当前所有文件都要分配到新的3层路径中
4. 同一文件只能属于一个分类

现有文件列表（标题+当前路径）：
{file_list_text[:6000]}

请返回JSON格式：
{{
    "category_tree": {{
        "科技": {{
            "AI工具": {{
                "视频创作": ["BV1AeDmBAEYm", "BV1AS7C66EKU"],
                "开发工具": ["BV1YNG16SEQJ"]
            }}
        }},
        "游戏": {{ ... }}
    }},
    "file_assignments": {{
        "BV1AeDmBAEYm": "科技/AI工具/视频创作",
        "BV1AS7C66EKU": "科技/AI工具/视频创作",
        ...
    }}
}}

注意：
- file_assignments 必须包含所有{bvid}个文件
- 路径必须恰好3层（用/分隔）
- 只返回JSON，不要其他文字"""

        try:
            client = OpenAI(api_key=config.get("api", {}).get("unified_api_key", ""), base_url=config.get("api", {}).get("unified_base_url", ""), timeout=180)
            resp = client.chat.completions.create(
                model=_get_model_brain(),
                messages=[
                    {"role": "system", "content": "你是严谨的知识库架构师，只输出JSON，不输出任何其他内容。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            raw = resp.choices[0].message.content.strip()
        except Exception as e:
            log(f"[KB] AI整理分类树失败: {e}", "ERROR")
            return 0, len(all_files)

        # 解析AI返回的JSON
        plan = None
        try:
            if "```" in raw:
                import re as _re
                code_match = _re.search(r"```(?:json)?\s*\n?(.*?)```", raw, _re.DOTALL)
                if code_match:
                    raw = code_match.group(1).strip()
            start = raw.find("{")
            if start >= 0:
                depth = 0
                match_end = -1
                for i in range(start, len(raw)):
                    if raw[i] == '{':
                        depth += 1
                    elif raw[i] == '}':
                        depth -= 1
                        if depth == 0:
                            match_end = i
                            break
                if match_end >= 0:
                    raw = raw[start:match_end+1]
                else:
                    end = raw.rfind("}")
                    if end >= start:
                        raw = raw[start:end+1]
            plan = json.loads(raw)
        except json.JSONDecodeError as e:
            log(f"[KB] AI返回JSON解析失败: {e}", "ERROR")
            return 0, len(all_files)

        assignments = plan.get("file_assignments", {})
        if not assignments:
            log("[KB] AI未返回文件分配方案", "WARN")
            return 0, len(all_files)

        # 第二步：逐个迁移文件
        moved = 0
        new_file_index = {}

        for f in all_files:
            bvid = f["bvid"]
            new_path = assignments.get(bvid)
            if not new_path:
                # AI漏掉了，保持原路径
                new_path = f["old_path"]
                log(f"[KB] AI未分配 {bvid}，保持原路径: {new_path}", "WARN")

            # 验证恰好3层
            parts = new_path.split("/")
            if len(parts) != 3:
                # 补齐或截断到3层
                if len(parts) < 3:
                    parts.extend([f"分类{i+1}" for i in range(len(parts), 3)])
                else:
                    parts = parts[:3]
                new_path = "/".join(parts)

            # 迁移物理文件
            try:
                # 找到旧文件
                old_folder = os.path.join(KNOWLEDGE_BASE_DIR, f["old_path"].replace("/", os.sep))
                old_file = None
                if os.path.isdir(old_folder):
                    for fname in os.listdir(old_folder):
                        if bvid in fname and fname.endswith(".md"):
                            old_file = os.path.join(old_folder, fname)
                            break

                # 创建新文件夹
                new_folder = self.get_or_create_folder(new_path)
                if old_file and os.path.exists(old_file):
                    dst = os.path.join(new_folder, os.path.basename(old_file))
                    if not os.path.exists(dst):
                        shutil.move(old_file, dst)
                        log(f"[KB] 迁移: {os.path.basename(old_file)} -> {new_path}", "KB")
                        moved += 1

                # 更新file_index
                if new_path not in new_file_index:
                    new_file_index[new_path] = []
                new_file_index[new_path].append({
                    "bvid": bvid,
                    "title": f["title"],
                    "added": datetime.now().isoformat()
                })
            except Exception as e:
                log(f"[KB] 迁移失败 [{bvid}]: {e}", "WARN")
                # 兜底：保留原路径
                old_p = f["old_path"]
                if old_p not in new_file_index:
                    new_file_index[old_p] = []
                new_file_index[old_p].append({
                    "bvid": bvid,
                    "title": f["title"],
                    "added": datetime.now().isoformat()
                })

        # 第三步：更新元数据
        self.metadata["file_index"] = new_file_index
        self._sync_categories_from_file_index()
        self._save_metadata()

        # 第四步：清理旧空文件夹
        cleaned = self.cleanup_empty_folders()
        log(f"[KB] AI整理完成: 迁移{moved}/{len(all_files)}个文件, 清理{cleaned}个空文件夹", "SUCCESS")
        print(f"\n{Fore.CYAN}新的知识库分类结构:{Style.RESET_ALL}")
        self.show_category_structure()

        return moved, len(all_files)


# ==============================================================================
# [HOT] 字幕抓取逻辑
# ==============================================================================
# [bili/subtitles.py] fetch_bilibili_subtitles
# [bili/subtitles.py] _check_subtitle_mismatch
