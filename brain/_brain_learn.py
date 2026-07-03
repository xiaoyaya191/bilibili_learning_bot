"""
BrainLearnMixin — 学习与知识归档
包含: learn_from_video, learn_from_comments, verify_knowledge_file
"""
import os
import re
from datetime import datetime

from brain._mixin_imports import *


class BrainLearnMixin:
    """学习与知识归档方法"""

    async def learn_from_video(self, bvid, title, up, url, subtitle_text, topic_suggestion, video_desc="", score=None, comment_summary=None):
        # 🔒 二次守卫：分数不达标直接拒绝归档
        if score is not None and score < LEARN_MIN_SCORE:
            log(f"📭 learn_from_video 拒绝低分归档: score={score:.1f}<{LEARN_MIN_SCORE} | 《{title}》", "LEARN")
            return False
        # 🔒 内容守卫：可学文本过短拒绝归档
        if not subtitle_text or len(subtitle_text.strip()) < 100:
            log(f"📭 learn_from_video 拒绝内容不足归档: {len(subtitle_text) if subtitle_text else 0}字<100 | 《{title}》", "LEARN")
            return False
        # 🔒 AI语义守卫：字幕内容是否与标题真正匹配？（归档前最后一道防线）
        if AI_SUBTITLE_VERIFY_ENABLED and title and subtitle_text:
            is_match, ai_conf, ai_reason = await self._ai_verify_subtitle_content(
                title, subtitle_text, video_desc
            )
            if not is_match and ai_conf >= 0.7:
                log(f"📭 learn_from_video 拒绝归档（AI语义不匹配）: conf={ai_conf:.2f} | {ai_reason} | 《{title}》", "LEARN")
                return False
            elif not is_match:
                log(f"⚠️ AI语义验证低置信不匹配(conf={ai_conf:.2f})，仍放行归档: {ai_reason} | 《{title}》", "WARN")
            else:
                log(f"✅ AI语义验证通过: conf={ai_conf:.2f} | {ai_reason} | 《{title}》", "LEARN")
        log(f"触发学习机制！主题建议: '{topic_suggestion}'", "LEARN")

        try:
            # 简介也参与分类（含项目链接等关键信息）
            classify_text = subtitle_text
            if video_desc:
                classify_text = f"[视频简介] {video_desc[:500]}\n\n[视频内容] {subtitle_text}"
            category_path = self.classifier.classify_content(title, classify_text, bvid, topic_suggestion)
            log(f"智能分类结果: '{category_path}'", "KB")
            
            category_folder = self.classifier.get_or_create_folder(category_path)
            
            clean_title = sanitize_filename(title)
            file_name = f"[{bvid}] - {clean_title}.md"
            file_path = os.path.join(category_folder, file_name)
            
            if os.path.exists(file_path):
                log(f"知识已存在: {file_path}", "INFO")
                return False

            log("正在调用AI总结视频核心内容...", "BRAIN")
            desc_context = f"【视频简介】\n{video_desc}\n\n" if video_desc else ""
            summary_context = f"视频标题: {title}\nUP主: {up}\n链接: {url}\n\n{desc_context}【视频字幕全文】:\n{subtitle_text}"

            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_SUMMARY},
                    {"role": "user", "content": summary_context}
                ]
            )
            summary_content = resp.choices[0].message.content
            
            desc_section = f"- **简介**: {video_desc}\n" if video_desc else ""
            file_header = (
                f"# 📚 知识归档\n\n"
                f"【视频信息】\n"
                f"- **标题**: {title}\n"
                f"- **UP主**: {up}\n"
                f"- **链接**: {url}\n"
                f"{desc_section}"
                f"- **归档时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"- **分类**: {category_path}\n"
                f"- **视频ID**: {bvid}\n\n"
                f"---\n\n"
                f"## [BRAIN] AI内容总结\n\n"
            )

            full_content = file_header + summary_content
            
            # 💬 评论区补充：合并在同一归档文件末尾
            if comment_summary and len(comment_summary.strip()) > 5:
                full_content += f"\n\n---\n\n{comment_summary.strip()}\n"
                log(f"评论区补充已合并到归档", "LEARN")

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(full_content)

            log(f"知识已总结并保存到: {file_path}", "SUCCESS")
            self.write_learning_log(category_path, title, file_path)
            
            self.classifier.show_category_structure()

            # 📦 Highlights archive: save high-quality content to highlights/ folder
            if DRY_GOODS_ENABLED and score is not None and score >= DRY_GOODS_MIN_SCORE:
                try:
                    dry_category_folder = os.path.join(DRY_GOODS_DIR, category_path)
                    os.makedirs(dry_category_folder, exist_ok=True)
                    dry_file_path = os.path.join(dry_category_folder, file_name)
                    if not os.path.exists(dry_file_path):
                        dry_file_header = (
                            f"# 🔥 Highlights\n\n"
                            f"【Video Info】\n"
                            f"- **Title**: {title}\n"
                            f"- **Author**: {up}\n"
                            f"- **Link**: {url}\n"
                            f"- **Score**: {score}/10\n"
                            f"- **Archived**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"- **Category**: {category_path}\n"
                            f"- **Video ID**: {bvid}\n\n"
                            f"---\n\n"
                            f"## [BRAIN] AI Summary\n\n"
                        )
                        with open(dry_file_path, 'w', encoding='utf-8') as f:
                            dry_content = dry_file_header + summary_content
                            if comment_summary and len(comment_summary.strip()) > 5:
                                dry_content += f"\n\n---\n\n{comment_summary.strip()}\n"
                            f.write(dry_content)
                        log(f"[GOLD] Highlights archived! Score {score}/10 -> {dry_file_path}", "SUCCESS")
                except Exception as dry_e:
                    log(f"Highlights archive failed: {dry_e}", "WARN")

            # 🧠 更新向量索引
            if self.kb_search:
                try:
                    await self.kb_search.update_entry(file_path)
                except Exception as ve:
                    log(f"向量索引更新失败: {ve}", "WARN")

            return True

        except Exception as e:
            log(f"学习与归档过程中发生错误: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return False

    async def learn_from_comments(self, bvid, title, up, video_url, comment_text, c_list, topic_suggestion, score=None):
        """从评论区提取有价值知识，返回摘要文本（不再写独立文件）。
        
        返回: (comment_summary: str | None, skipped_reason: str)
        - 有知识 → ("## 💬 评论区补充\n- xxx", "")
        - 无知识/skip → (None, "原因")
        """
        # ── 质量门槛 ──
        if score is not None and score < LEARN_MIN_SCORE:
            return None, f"视频评分过低({score:.1f}<{LEARN_MIN_SCORE})，跳过评论收集"
        if not c_list or len(c_list) < 5:
            return None, f"评论数不足({len(c_list) if c_list else 0}<5)"
        total_text_len = sum(len(c.get('content','')) for c in c_list)
        if total_text_len < 150:
            return None, f"评论总字数太少({total_text_len}<150)，信息密度必然低"

        log(f"从评论区挖掘知识... ({len(c_list)}条评论, {total_text_len}字)", "LEARN")

        try:
            comments_ctx = f"【视频信息】\n标题: {title}\nUP主: {up}\n链接: {video_url}\n\n【评论区内容】:\n"
            for i, c in enumerate(c_list):
                comments_ctx += f"#{i+1} [{c.get('user','?')}]: {c.get('content','')}\n"
                if c.get('pic_info'):
                    comments_ctx += f"    [附图]: {c['pic_info']}\n"
            # 附加现有决策文本
            if comment_text and comment_text != "[未读取评论]" and "【热门评论】" in str(comment_text):
                comments_ctx += f"\n【AI预分析】:\n{comment_text}"

            comments_ctx = comments_ctx[:5000]

            resp = await self._call_ai_with_retry(
                model=MODEL_BRAIN,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_COMMENT_SUMMARY},
                    {"role": "user", "content": comments_ctx}
                ]
            )
            summary = resp.choices[0].message.content.strip()

            # 无知识 → 跳过
            if not summary or summary.upper().startswith("SKIP") or "无实质" in summary:
                return None, f"AI判断评论区无实质知识内容"

            # 清理掉可能的 markdown 标题标记（保持简洁）
            summary = summary.replace("## 💬 评论区知识精华", "## 💬 评论区补充")
            log(f"评论区知识提炼成功 ({len(summary)}字)，将合并到视频归档", "SUCCESS")
            return summary, ""

        except Exception as e:
            return None, f"评论区知识收集出错: {e}"

    async def verify_knowledge_file(self, bvid, video_title):
        """回顾复习时验证知识文件真实性。如果发现虚假/错误，备份原文件并重写。
        
        返回: (verified: bool, issues_count: int, action: str)
        """
        if not KNOWLEDGE_VERIFY_ENABLED:
            return True, 0, "知识验证未启用"
        
        # 在知识库中查找对应的文件
        found_files = []
        if os.path.exists(KNOWLEDGE_BASE_DIR):
            for root, dirs, files in os.walk(KNOWLEDGE_BASE_DIR):
                for f in files:
                    if f.endswith('.md') and bvid in f and not f.startswith('备份_'):
                        found_files.append(os.path.join(root, f))
        
        if not found_files:
            return True, 0, "未找到对应知识文件"
        
        file_path = found_files[0]
        log(f"🔍 开始验证知识文件: {os.path.basename(file_path)}", "KB")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                knowledge_content = f.read()
            
            # 联网搜索（如果启用）
            web_results = []
            if KNOWLEDGE_VERIFY_USE_WEB:
                log(f"[NET] 联网搜索验证关键词: {video_title[:40]}...", "KB")
                web_results = await web_search(video_title[:60], limit=5)
                if web_results:
                    log(f"[NET] 获取到 {len(web_results)} 条搜索结果", "INFO")
                else:
                    log("[NET] 联网搜索未获取到结果，仅使用AI知识库验证", "INFO")
            
            # AI验证
            verify_result = await verify_knowledge_with_ai(knowledge_content, video_title, web_results)
            
            overall_score = verify_result.get("overall_score", 0.7)
            is_reliable = verify_result.get("overall_reliable", True)
            issues = verify_result.get("issues", [])
            supplements = verify_result.get("supplements", [])
            needs_rewrite = verify_result.get("recommend_rewrite", False) or overall_score < KNOWLEDGE_VERIFY_MIN_SCORE
            
            # 打印验证结果
            issues_bad = [i for i in issues if i.get("verdict") in ("存疑", "错误", "过时")]
            if issues_bad:
                for issue in issues_bad[:3]:
                    log(f"  [WARN] 问题: {issue.get('claim','')[:50]} → {issue.get('verdict')}", "WARN")
            if supplements:
                log(f"  [NOTE] 建议补充 {len(supplements)} 条知识", "INFO")
            
            if needs_rewrite:
                corrected = verify_result.get("corrected_content")
                if corrected and KNOWLEDGE_VERIFY_AUTO_FIX:
                    log(f"🚨 知识可靠性不足(评分:{overall_score:.0%})，备份原文件并重写...", "WARN")
                    backup_and_rewrite_knowledge(file_path, corrected, verify_result)
                    return False, len(issues_bad), f"已修正（评分{overall_score:.0%}）"
                else:
                    log(f"[WARN] 知识存疑(评分:{overall_score:.0%})，但AI未提供修正内容，保留原文件", "WARN")
                    return False, len(issues_bad), f"存疑但无修正内容（评分{overall_score:.0%}）"
            else:
                log(f"[OK] 知识验证通过（可靠性评分: {overall_score:.0%}）", "SUCCESS")
                return True, 0, f"验证通过（评分{overall_score:.0%}）"
                
        except Exception as e:
            log(f"知识验证过程出错: {e}", "WARN")
            return True, 0, f"验证失败跳过: {e}"
