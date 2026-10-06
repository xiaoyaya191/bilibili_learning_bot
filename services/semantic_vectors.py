"""Local-only semantic models with a labelled, zero-download lexical fallback."""
import hashlib
import math
import re
from functools import lru_cache


def tokens(text):
    return re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]', text.casefold())


@lru_cache(maxsize=4)
def embedding_model(name):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(name, local_files_only=True, trust_remote_code=False)


@lru_cache(maxsize=2)
def rerank_model(name):
    from sentence_transformers import CrossEncoder
    return CrossEncoder(name, local_files_only=True, trust_remote_code=False)


def encode(texts, model=''):
    if model:
        vectors = embedding_model(model).encode(texts, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors], 'semantic:' + model
    vectors = []
    for text in texts:
        vector = [0.0] * 512
        parts = tokens(text)
        for part in parts + [''.join(parts[index:index + 2]) for index in range(len(parts) - 1)]:
            signature = hashlib.sha256(part.encode()).digest()
            vector[int.from_bytes(signature[:4], 'big') % 512] += 1 if signature[4] % 2 else -1
        norm = math.sqrt(sum(value * value for value in vector)) or 1
        vectors.append([value / norm for value in vector])
    return vectors, 'lexical-hash-v1'


def cosine(first, second):
    if len(first) != len(second):
        raise ValueError('向量维度不一致，请重建索引')
    return sum(left * right for left, right in zip(first, second))


def alignment(title, description, subtitle, settings):
    model = settings.get('embedding_model', '')
    if not settings.get('enabled', True) or not model:
        return {'status': 'unavailable', 'reason': '未配置本地语义嵌入模型，未作语义拒绝'}
    try:
        size = int(settings.get('chunk_size', 900))
        passages = [subtitle[offset:offset + size] for offset in range(0, len(subtitle), size)][:64]
        if not passages or not (title or description):
            return {'status': 'unavailable', 'reason': '缺少校验内容'}
        vectors, backend = encode([title + '\n' + description] + passages, model)
        score = max(cosine(vectors[0], vector) for vector in vectors[1:])
        return {'status': 'match' if score >= settings.get('threshold', 0.25) else 'mismatch',
                'score': score, 'backend': backend}
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        return {'status': 'unavailable', 'reason': str(error)}
