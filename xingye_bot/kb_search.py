"""
kb_search.py — 知识库向量检索 + 重排引擎

基于 OpenAI Embedding API 构建语义索引，支持：
- 向量语义搜索（余弦相似度）
- LLM 重排（对 Top N 结果按 query 相关性重新排序）
- 增量更新（新增/修改单条后无需重建全量）

索引文件：Data/kb_vector_index.json
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

from .llm import ModelClient
from .settings import DATA_DIR, BotSettings
from .state import BotState


INDEX_FILE = DATA_DIR / "kb_vector_index.json"


# ── 工具函数 ──

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度"""
    dot = sum(va * vb for va, vb in zip(a, b))
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _normalize_path(path: str | Path) -> str:
    """统一路径格式为 POSIX 相对路径"""
    p = Path(path).resolve()
    try:
        kb_root = DATA_DIR.parent / "KnowledgeBase"
        return str(p.relative_to(kb_root))
    except ValueError:
        return str(p)


def _extract_text_from_md(md_path: str | Path) -> str:
    """从 .md 文件中提取用于 embedding 的文本（去掉 markdown 标记）"""
    path = Path(md_path)
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")

    # 去掉 frontmatter 或分隔线
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.DOTALL)

    # 去掉 markdown 链接/图片标记
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    # 去掉标题标记
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)

    # 去掉粗体/斜体标记
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)

    # 提取视频标题（文件名中的 [BVxxx] 部分）
    name = path.stem
    bv_match = re.search(r'\[([^\]]+)\]', name)
    bvid = bv_match.group(1) if bv_match else name

    # 截断到 6000 字符（embedding API 限制 ~8000 token）
    text = text.strip()[:6000]
    return text


def _load_index() -> dict[str, Any]:
    """加载向量索引"""
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
    return {"version": 2, "entries": [], "documents": {}}


def _save_index(index: dict[str, Any]) -> None:
    """保存向量索引"""
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


# ── KBSearchEngine ──

class KBSearchEngine:
    """知识库向量检索 + 重排引擎"""

    def __init__(self, model: ModelClient):
        self.model = model
        self._index: dict[str, Any] | None = None

    @property
    def index(self) -> dict[str, Any]:
        if self._index is None:
            self._index = _load_index()
        return self._index

    # ── 索引构建 ──

    def build_index(self, kb_root: str | Path | None = None) -> int:
        """扫描 KnowledgeBase 下所有 .md 文件，构建完整向量索引"""
        if kb_root is None:
            kb_root = DATA_DIR.parent / "KnowledgeBase"
        kb_root = Path(kb_root)
        if not kb_root.exists():
            return 0

        md_files = sorted(kb_root.rglob("*.md"))
        if not md_files:
            return 0

        entries: list[dict[str, Any]] = []
        documents: dict[str, str] = {}

        texts_to_embed: list[str] = []
        embed_map: list[int] = []  # 索引→entries 的映射

        for i, md_file in enumerate(md_files):
            try:
                rel_path = _normalize_path(md_file)
                text = _extract_text_from_md(md_file)
                if not text:
                    continue

                # 提取基本信息
                bvid = ""
                title = md_file.stem
                bv_match = re.search(r'\[([^\]]+)\]', title)
                if bv_match:
                    bvid = bv_match.group(1)
                    title = title[title.index("]") + 1:].strip(" -")

                entries.append({
                    "id": str(i),
                    "bvid": bvid,
                    "title": title,
                    "path": rel_path,
                })
                documents[str(i)] = text
                texts_to_embed.append(text)
                embed_map.append(len(entries) - 1)
            except Exception:
                continue

        if not texts_to_embed:
            return 0

        # 批量 embedding（一次最多 20 条）
        vectors: list[list[float]] = []
        batch_size = 20
        for start in range(0, len(texts_to_embed), batch_size):
            batch = texts_to_embed[start:start + batch_size]
            for text in batch:
                try:
                    vec = self.model.embedding(text)
                    vectors.append(vec)
                except Exception:
                    vectors.append([])

        # 合并向量到 entries
        for idx, vec in zip(embed_map, vectors):
            if vec:
                entries[idx]["vector"] = vec

        self._index = {
            "version": 2,
            "entries": entries,
            "documents": documents,
        }
        _save_index(self._index)
        return len(entries)

    # ── 增量更新 ──

    async def update_entry(self, md_path: str | Path) -> bool:
        """新增或更新单个条目的向量索引"""
        md_path = Path(md_path)
        if not md_path.exists():
            return False

        rel_path = _normalize_path(md_path)
        text = _extract_text_from_md(md_path)
        if not text:
            return False

        # 提取 bvid / title
        name = md_path.stem
        bvid = ""
        title = name
        bv_match = re.search(r'\[([^\]]+)\]', name)
        if bv_match:
            bvid = bv_match.group(1)
            title = name[name.index("]") + 1:].strip(" -")

        # 生成向量
        try:
            vector = await self.model.embedding(text)
        except Exception:
            return False

        idx = self.index
        # 查找是否已有同名条目（去重）
        existing = [e for e in idx["entries"] if e.get("path") == rel_path or e.get("bvid") == bvid]
        if existing:
            entry = existing[0]
            entry["title"] = title
            entry["vector"] = vector
            entry["path"] = rel_path
            idx["documents"][entry["id"]] = text
        else:
            new_id = str(len(idx["entries"]))
            idx["entries"].append({
                "id": new_id,
                "bvid": bvid,
                "title": title,
                "path": rel_path,
                "vector": vector,
            })
            idx["documents"][new_id] = text

        _save_index(idx)
        return True

    def remove_entry(self, md_path: str | Path | None = None, bvid: str | None = None) -> bool:
        """从索引中移除指定条目"""
        idx = self.index
        before = len(idx["entries"])
        if md_path:
            rel = _normalize_path(md_path)
            idx["entries"] = [e for e in idx["entries"] if e.get("path") != rel]
        elif bvid:
            idx["entries"] = [e for e in idx["entries"] if e.get("bvid") != bvid]
        if len(idx["entries"]) < before:
            _save_index(idx)
            return True
        return False

    # ── 搜索 ──

    def search(self, query: str, top_k: int = 20, min_score: float = 0.0) -> list[dict[str, Any]]:
        """向量语义搜索，返回排序后的结果列表"""
        idx = self.index
        if not idx["entries"]:
            return []

        # 生成 query 向量
        try:
            q_vec = self.model.embedding(query)
        except Exception:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in idx["entries"]:
            vec = entry.get("vector")
            if not vec or len(vec) < 100:
                continue
            score = _cosine_similarity(q_vec, vec)
            if score >= min_score:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, entry in scored[:top_k]:
            doc_text = idx["documents"].get(entry["id"], "")
            results.append({
                "score": round(score, 4),
                "bvid": entry.get("bvid", ""),
                "title": entry.get("title", ""),
                "path": entry.get("path", ""),
                "snippet": doc_text[:200] if doc_text else "",
            })
        return results

    # ── 重排 ──

    async def rerank(self, query: str, results: list[dict[str, Any]], top_n: int = 5) -> list[dict[str, Any]]:
        """LLM 重排：让 AI 对搜索结果按 query 相关性打分排序"""
        if not results:
            return []

        # 准备候选列表
        candidates = []
        for i, r in enumerate(results):
            snippet = r.get("snippet", "")[:300]
            candidates.append(f"[{i+1}] {r['title']}\n    {snippet}")

        prompt = f"""你是一个搜索结果重排助手。给定用户查询和候选结果列表，请按相关性从高到低重新排序。

用户查询：{query}

候选结果：
{chr(10).join(candidates)}

请输出重新排序后的序号列表，格式为英文逗号分隔的数字，如：3,1,4,2
只输出数字列表，不要任何其他文字。"""

        try:
            reply = await self.model.chat(
                [{"role": "user", "content": prompt}],
                model_role="fast",
                purpose="rerank"
            )
            # 解析序号列表
            indices = [int(x.strip()) for x in reply.split(",") if x.strip().isdigit()]
            indices = [i - 1 for i in indices if 1 <= i <= len(results)]
            reranked = [results[i] for i in indices if i < len(results)]
            # 补充遗漏的结果
            seen = set(id(r) for r in reranked)
            for r in results:
                if id(r) not in seen:
                    reranked.append(r)
                    seen.add(id(r))
            return reranked[:top_n]
        except Exception:
            # 重排失败，返回原始 Top N
            return results[:top_n]

    # ── 统计 ──

    def stats(self) -> dict[str, Any]:
        """索引统计信息"""
        idx = self.index
        entries = idx.get("entries", [])
        vector_count = sum(1 for e in entries if e.get("vector"))
        return {
            "total_entries": len(entries),
            "vectorized": vector_count,
            "unvectorized": len(entries) - vector_count,
            "index_version": idx.get("version"),
        }

    def clear(self) -> None:
        """清空索引"""
        self._index = {"version": 2, "entries": [], "documents": {}}
        _save_index(self._index)
