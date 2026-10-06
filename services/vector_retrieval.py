"""Account-local incremental chunk index, vector recall and reranking."""
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from services.semantic_vectors import encode, cosine, tokens, rerank_model


def retrieve(query, root, options=None, max_chunks=5, allowed_paths=None):
    options = options or {}
    root = Path(root).resolve()
    if not root.is_dir() or not query.strip():
        return []
    from core.user_data import DATA_DIR
    cache_dir = Path(options.get('_cache_dir', DATA_DIR))
    cache_dir.mkdir(parents=True, exist_ok=True)
    size = max(200, min(3000, int(options.get('chunk_size', 900))))
    overlap = max(0, min(size // 2, int(options.get('chunk_overlap', 120))))
    model = options.get('embedding_model', '')
    warning = ''
    try:
        query_vectors, backend = encode([query], model)
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        if not options.get('allow_lexical_fallback', True):
            raise ValueError('本地嵌入模型不可用: ' + str(error)) from error
        warning = '语义模型不可用，降级为词法哈希向量'
        model = ''
        query_vectors, backend = encode([query])
    identity = hashlib.sha256(f'{root}|{backend}|{size}|{overlap}'.encode()).hexdigest()
    connection = sqlite3.connect(cache_dir / 'rag_vectors.sqlite3', timeout=30)
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE IF NOT EXISTS chunks (scope TEXT,path TEXT,digest TEXT,position INTEGER,text TEXT,vector TEXT,PRIMARY KEY(scope,path,position))')
        seen = set()
        with connection:
            for path in sorted(root.rglob('*.md')):
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    continue
                relative = path.relative_to(root).as_posix()
                seen.add(relative)
                if path.stat().st_size > 5_000_000:
                    connection.execute('DELETE FROM chunks WHERE scope=? AND path=?', (identity, relative))
                    continue
                try:
                    raw = path.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    connection.execute('DELETE FROM chunks WHERE scope=? AND path=?', (identity, relative))
                    continue
                signature = hashlib.sha256(raw.encode()).hexdigest()
                cached = connection.execute('SELECT digest FROM chunks WHERE scope=? AND path=? LIMIT 1', (identity, relative)).fetchone()
                if cached and cached[0] == signature:
                    continue
                pieces = [raw[offset:offset + size] for offset in range(0, len(raw), size - overlap)]
                vectors, _ = encode([path.stem + '\n' + piece for piece in pieces], model) if pieces else ([], backend)
                connection.execute('DELETE FROM chunks WHERE scope=? AND path=?', (identity, relative))
                connection.executemany('INSERT INTO chunks VALUES(?,?,?,?,?,?)',
                    [(identity, relative, signature, position, piece, json.dumps(vector)) for position, (piece, vector) in enumerate(zip(pieces, vectors))])
            for (path,) in connection.execute('SELECT DISTINCT path FROM chunks WHERE scope=?', (identity,)).fetchall():
                if path not in seen:
                    connection.execute('DELETE FROM chunks WHERE scope=? AND path=?', (identity, path))
        rows = connection.execute('SELECT path,position,text,vector FROM chunks WHERE scope=?', (identity,)).fetchall()
    finally:
        connection.close()
    permitted = {Path(path).resolve() for path in allowed_paths} if allowed_paths is not None else None
    candidates = []
    for path, position, text, vector in rows:
        if permitted is not None and (root / path).resolve() not in permitted:
            continue
        score = cosine(query_vectors[0], json.loads(vector))
        if score > 0:
            candidates.append({'path': path, 'title': Path(path).stem, 'snippet': text,
                               'chunk': position, 'vector_score': score, 'backend': backend, 'warning': warning})
    candidates.sort(key=lambda item: (-item['vector_score'], item['path'], item['chunk']))
    candidates = candidates[:max(1, min(200, int(options.get('candidate_count', 30))))]
    reranker = options.get('reranker_model', '')
    scores = None
    if candidates and reranker:
        try:
            scores = rerank_model(reranker).predict([(query, item['snippet']) for item in candidates]).tolist()
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            if not options.get('allow_lexical_fallback', True):
                raise ValueError('重排模型不可用: ' + str(error)) from error
            warning = '重排模型不可用，使用词法重排'
    for index, item in enumerate(candidates):
        query_terms = set(tokens(query))
        document_terms = tokens(item['title'] + ' ' + item['snippet'])
        lexical = sum(math.log1p(document_terms.count(term)) for term in query_terms) / max(1, len(query_terms))
        item['score'] = float(scores[index]) if scores is not None else item['vector_score'] * 0.4 + lexical * 0.6
        item['reranker'] = reranker if scores is not None else 'lexical-frequency'
        item['warning'] = warning or item['warning']
    if backend == 'lexical-hash-v1':
        candidates = [item for item in candidates if set(tokens(query)) & set(tokens(item['title'] + ' ' + item['snippet']))]
    candidates.sort(key=lambda item: (-item['score'], item['path'], item['chunk']))
    budget = max(500, min(30000, int(options.get('context_chars', 6000))))
    results = []
    for item in candidates[:max(1, min(20, int(max_chunks)))]:
        if budget <= 0:
            break
        item['snippet'] = item['snippet'][:budget]
        budget -= len(item['snippet']) + len(item['title']) + len(item['path']) + 60
        results.append(item)
    return results
