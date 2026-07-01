"""knowledge/organize.py — 知识库整理"""
import asyncio, os, json, re, random, shutil
from datetime import datetime
from colorama import Fore, Style
from core.config import config
from core.globals import *
from utils.display import log
from utils.helpers import sanitize_filename
from brain.video_analysis import _scan_knowledge_base_md_files

async def organize_knowledge_base():
    """扫描并整理知识库：将非3层目录结构的文件AI自动归位。
    
    逻辑：
    1. 扫描所有 .md 文件，找出非3层的（如 科技/xxx.md 或 科技/AI工具/xxx.md）
    2. 检测同一BVID的重复文件（不同深度目录），保留最深的
    3. 对每个非3层文件，读取内容 → AI分类 → 移动到3层目录
    4. 支持4选1确认：本次允许/一直允许/不允许/AI审查
    """
    print(f"\n{Fore.LIGHTYELLOW_EX}╔══════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}║  📂 一键整理知识库 - AI智能归类到3层                      ║{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        print(f"{Fore.YELLOW}[INFO] 知识库目录不存在，无需整理{Style.RESET_ALL}")
        return

    # ── 第1步：扫描 ──
    print(f"\n{Fore.CYAN}[1/4] 扫描知识库文件...{Style.RESET_ALL}")
    all_files = _scan_knowledge_base_md_files()
    if not all_files:
        print(f"{Fore.YELLOW}[INFO] 知识库为空{Style.RESET_ALL}")
        return

    # 分类：3层 ok / 非3层 / 重复BVID
    ok_files = []       # 3层，已到位
    shallow_files = []  # 非3层，需要整理
    bvid_map = {}       # bvid -> [(depth, bvid, title, path, up, cat), ...]

    for bvid, title, fpath, up, cat in all_files:
        depth = cat.count('/') + 1 if cat and cat != '未分类' else 1
        if bvid not in bvid_map:
            bvid_map[bvid] = []
        bvid_map[bvid].append((depth, bvid, title, fpath, up, cat))

    for bvid, entries in bvid_map.items():
        entries.sort(key=lambda x: x[0], reverse=True)  # depth降序
        for depth, bv, t, fp, u, c in entries:
            if depth >= 3:
                ok_files.append((bv, t, fp, u, c, depth))
            else:
                shallow_files.append((bv, t, fp, u, c, depth))

    # ── 检测重复BVID ──
    duplicates = []
    unique_shallow = []
    for entry in shallow_files:
        bv = entry[0]
        all_entries = bvid_map[bv]
        has_deep = any(e[0] >= 3 for e in all_entries)
        if has_deep:
            duplicates.append(entry)
        else:
            unique_shallow.append(entry)

    print(f"\n{Fore.CYAN}扫描结果:{Style.RESET_ALL}")
    print(f"  {Fore.GREEN}✓ 3层已到位: {len(ok_files)} 个{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}⚠ 非3层需整理: {len(unique_shallow)} 个{Style.RESET_ALL}")
    print(f"  {Fore.RED}🗑 重复文件(可清理): {len(duplicates)} 个{Style.RESET_ALL}")

    if not unique_shallow and not duplicates:
        print(f"{Fore.GREEN}[OK] 知识库已全部整理完毕！{Style.RESET_ALL}")
        return

    # ── 显示详情 ──
    if duplicates:
        print(f"\n{Fore.RED}【重复文件】(同BVID有更深层版本，建议删除):{Style.RESET_ALL}")
        for bv, t, fp, u, c, d in duplicates[:20]:
            rel = os.path.relpath(fp, KNOWLEDGE_BASE_DIR)
            print(f"  [{bv}] {t[:40]} | {c}")

    if unique_shallow:
        print(f"\n{Fore.YELLOW}【需要整理】(非3层，将AI归类):{Style.RESET_ALL}")
        for bv, t, fp, u, c, d in unique_shallow[:20]:
            rel = os.path.relpath(fp, KNOWLEDGE_BASE_DIR)
            print(f"  [{bv}] {t[:40]} | 当前: {c} ({d}层)")

    # ── 第2步：确认 ──
    print(f"\n{Fore.LIGHTYELLOW_EX}╔══════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}║  [整理确认]                                                ║{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}╠══════════════════════════════════════════════════════════╣{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}║{Style.RESET_ALL}  将整理 {len(unique_shallow)} 个文件 + 清理 {len(duplicates)} 个重复文件")
    print(f"{Fore.LIGHTYELLOW_EX}╠══════════════════════════════════════════════════════════╣{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}║{Style.RESET_ALL}  {Fore.GREEN}1.{Style.RESET_ALL} 一键整理全部    {Fore.LIGHTGREEN_EX}2.{Style.RESET_ALL} 逐个确认(每文件4选1)")
    print(f"{Fore.LIGHTYELLOW_EX}║{Style.RESET_ALL}  {Fore.RED}3.{Style.RESET_ALL} 取消")
    print(f"{Fore.LIGHTYELLOW_EX}╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

    mode_choice = input(f"{Fore.CYAN}[整理] 选择 (1-3, 回车=1): {Style.RESET_ALL}").strip()
    if mode_choice == "3":
        print(f"{Fore.YELLOW}已取消{Style.RESET_ALL}")
        return

    per_file_confirm = (mode_choice == "2")

    # ── 第3步：初始化分类器 ──
    classifier = KnowledgeBaseClassifier()
    all_cats = classifier._get_all_categories()

    # ── 第4步：执行整理 ──
    print(f"\n{Fore.CYAN}[3/4] 开始整理...{Style.RESET_ALL}")

    moved_count = 0
    deleted_count = 0
    skipped_count = 0
    auto_allow_all = False  # 一键模式

    async def confirm_action(action_desc, detail=""):
        """简化版4选1确认"""
        nonlocal auto_allow_all
        if auto_allow_all or not per_file_confirm:
            return "allow"

        print(f"\n{Fore.YELLOW}  ╔ 操作确认 ╗{Style.RESET_ALL}")
        print(f"  {Fore.YELLOW}║{Style.RESET_ALL} {action_desc[:60]}")
        if detail:
            print(f"  {Fore.YELLOW}║{Style.RESET_ALL} {detail[:100]}")
        print(f"  {Fore.YELLOW}║{Style.RESET_ALL} {Fore.GREEN}1.{Style.RESET_ALL}本次允许 {Fore.LIGHTGREEN_EX}2.{Style.RESET_ALL}全部允许 {Fore.RED}3.{Style.RESET_ALL}跳过 {Fore.CYAN}4.{Style.RESET_ALL}AI审查")
        print(f"  {Fore.CYAN}[整理] 选择 (1-4, 回车=1): {Style.RESET_ALL}", end="")

        import sys
        sys.stdout.flush()
        ch = input().strip()

        if ch == "2":
            auto_allow_all = True
            print(f"  {Fore.GREEN}已设置: 全部自动允许{Style.RESET_ALL}")
            return "always"
        elif ch == "3":
            return "deny"
        elif ch == "4":
            return "ai_review"
        return "allow"

    async def ai_review(action_desc, detail=""):
        """AI审查"""
        try:
            resp = await _call_ai_with_retry_static(
                model=MODEL_BRAIN,
                messages=[{"role": "user", "content": f"你是安全审查助手。评估此操作是否合理:{action_desc}。详情:{detail[:300]}。只返回JSON: {{\"safe\":true/false,\"reason\":\"理由\"}}"}],
                request_timeout=20
            )
            raw = resp.choices[0].message.content
            s = raw.find("{")
            e = raw.rfind("}")
            if s >= 0 and e >= s:
                d = json.loads(raw[s:e+1])
                if d.get("safe", True):
                    print(f"  {Fore.GREEN}AI审查通过: {d.get('reason','')}{Style.RESET_ALL}")
                    return True
                else:
                    print(f"  {Fore.RED}AI审查不通过: {d.get('reason','')}{Style.RESET_ALL}")
                    return False
            return True
        except Exception as ex:
            print(f"  {Fore.YELLOW}AI审查异常，默认通过{Style.RESET_ALL}")
            return True

    # ── 处理重复文件：直接删除浅层版本 ──
    if duplicates:
        print(f"\n{Fore.CYAN}[清理重复] 删除 {len(duplicates)} 个重复文件...{Style.RESET_ALL}")
        for bv, t, fp, u, c, d in duplicates:
            rel = os.path.relpath(fp, KNOWLEDGE_BASE_DIR)
            if per_file_confirm:
                result = await confirm_action(f"删除重复文件: [{bv}] {t[:30]}", f"已有3层版本，此文件位于 {c}")
                if result == "deny":
                    skipped_count += 1
                    continue
                if result == "ai_review":
                    if not await ai_review("删除重复知识库文件", f"[{bv}] {t[:50]}"):
                        skipped_count += 1
                        continue
            try:
                os.remove(fp)
                print(f"  {Fore.GREEN}已删除: {rel}{Style.RESET_ALL}")
                deleted_count += 1
                # 清理空目录
                dir_path = os.path.dirname(fp)
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
            except Exception as e:
                print(f"  {Fore.RED}删除失败: {e}{Style.RESET_ALL}")

    # ── 处理非3层文件：AI分类 → 移动 ──
    if unique_shallow:
        print(f"\n{Fore.CYAN}[归类整理] AI分类 {len(unique_shallow)} 个文件...{Style.RESET_ALL}")

        for idx, (bv, t, fp, u, c, d) in enumerate(unique_shallow, 1):
            rel = os.path.relpath(fp, KNOWLEDGE_BASE_DIR)
            print(f"\n  {Fore.CYAN}[{idx}/{len(unique_shallow)}] [{bv}] {t[:40]}{Style.RESET_ALL}")
            print(f"  当前: {c} ({d}层)")

            if per_file_confirm:
                result = await confirm_action(f"AI归类: [{bv}] {t[:30]}", f"从 {c} → AI自动分类到3层")
                if result == "deny":
                    skipped_count += 1
                    continue
                if result == "ai_review":
                    if not await ai_review("AI归类知识库文件", f"[{bv}] {t[:50]}"):
                        skipped_count += 1
                        continue

            # 读取文件内容用于AI分类
            file_content = ""
            try:
                with open(fp, 'r', encoding='utf-8') as fh:
                    file_content = fh.read(3000)
            except Exception as e:
                log(f'非预期异常: {e}', 'WARN')

            # AI分类
            try:
                ai_result = classifier._find_best_category(t, file_content, all_cats)
                new_cat = ai_result.get("selected_category", "未分类")
                conf = ai_result.get("confidence", 0)
                is_new = ai_result.get("is_new", False)

                if is_new:
                    new_cat = classifier._create_category_structure(new_cat)

                # 确保恰好3层
                parts = [p.strip() for p in new_cat.split('/') if p.strip()]
                while len(parts) < 3:
                    parts.append(f"子类{len(parts)+1}")
                parts = parts[:3]
                final_cat = '/'.join(parts)

                print(f"  AI分类: {Fore.GREEN}{final_cat}{Style.RESET_ALL} (置信度: {conf:.0%})")

                if conf < 0.3:
                    print(f"  {Fore.YELLOW}置信度过低，跳过{Style.RESET_ALL}")
                    skipped_count += 1
                    continue

                # 移动文件
                new_folder = classifier.get_or_create_folder(final_cat)
                fname = os.path.basename(fp)
                dst = os.path.join(new_folder, fname)

                if os.path.exists(dst):
                    print(f"  {Fore.YELLOW}目标位置已有同名文件，删除源文件{Style.RESET_ALL}")
                    os.remove(fp)
                    deleted_count += 1
                else:
                    shutil.move(fp, dst)
                    print(f"  {Fore.GREEN}已移动: {rel} → {final_cat}/{Style.RESET_ALL}")
                    moved_count += 1

                # 更新分类器元数据
                if final_cat not in classifier.metadata.get("file_index", {}):
                    classifier.metadata.setdefault("file_index", {})[final_cat] = []
                classifier.metadata["file_index"][final_cat].append({
                    "bvid": bv,
                    "title": t,
                    "added": datetime.now().isoformat()
                })
                # 从旧分类移除
                old_cat = c if c != '未分类' else '未分类'
                if old_cat in classifier.metadata.get("file_index", {}):
                    classifier.metadata["file_index"][old_cat] = [
                        e for e in classifier.metadata["file_index"][old_cat]
                        if e.get("bvid") != bv
                    ]

                # 清理旧空目录
                old_dir = os.path.dirname(fp)
                if os.path.exists(old_dir) and not os.listdir(old_dir):
                    try:
                        os.rmdir(old_dir)
                    except Exception as e:
                        log(f'非预期异常: {e}', 'WARN')

                # 添加新分类路径到已知列表供后续分类使用
                if final_cat not in all_cats:
                    all_cats.append(final_cat)

            except Exception as e:
                print(f"  {Fore.RED}AI分类异常: {e}{Style.RESET_ALL}")
                skipped_count += 1

    # ── 保存分类器元数据 ──
    try:
        classifier._sync_categories_from_file_index()
        classifier._save_metadata()
        classifier.cleanup_empty_folders()
    except Exception as e:
        log(f'非预期异常: {e}', 'WARN')

    # ── 汇总 ──
    print(f"\n{Fore.LIGHTYELLOW_EX}╔══════════════════════════════════════════════════════════╗{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}║  📂 整理完成！                                            ║{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}╠══════════════════════════════════════════════════════════╣{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}║{Style.RESET_ALL}  {Fore.GREEN}✓ AI归类移动: {moved_count} 个{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}║{Style.RESET_ALL}  {Fore.RED}🗑 重复清理: {deleted_count} 个{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}║{Style.RESET_ALL}  {Fore.YELLOW}⊘ 跳过: {skipped_count} 个{Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}║{Style.RESET_ALL}  {Fore.GREEN}✓ 3层文件: {len(ok_files)} 个 (未动){Style.RESET_ALL}")
    print(f"{Fore.LIGHTYELLOW_EX}╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}")

    # 显示新的分类结构
    try:
        classifier.show_category_structure()
    except Exception as e:
        log(f'非预期异常: {e}', 'WARN')


# ── [N] 自定义知识管理（增删改查）───────────────────────────────────────
CUSTOM_KNOWLEDGE_DIR = os.path.join(KNOWLEDGE_BASE_DIR, "自定义知识")

