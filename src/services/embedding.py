"""Vertex AI text embeddings + cosine similarity with corpus caching."""
import hashlib
import numpy as np
import vertexai
from vertexai.language_models import TextEmbeddingModel
from src.config.settings import get_config

_model: TextEmbeddingModel | None = None
_corpus_cache: dict[str, list[list[float]]] = {}


def _get_model() -> TextEmbeddingModel:
    global _model
    if _model is None:
        cfg = get_config()
        vertexai.init(project=cfg.vertex_ai_project, location=cfg.vertex_ai_location)
        _model = TextEmbeddingModel.from_pretrained(cfg.embedding_model)
    return _model


def embed_text(text: str) -> list[float]:
    return _get_model().get_embeddings([text])[0].values


def embed_batch(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    results: list[list[float]] = []
    for i in range(0, len(texts), 250):
        chunk = texts[i:i + 250]
        results.extend([e.values for e in model.get_embeddings(chunk)])
    return results


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def top_k_similar(
    query_embedding: list[float],
    corpus_embeddings: list[list[float]],
    k: int = 5,
) -> list[tuple[int, float]]:
    """Return up to k (index, score) pairs sorted by descending cosine similarity."""
    if not corpus_embeddings:
        return []
    qv = np.array(query_embedding, dtype=np.float32)
    cm = np.array(corpus_embeddings, dtype=np.float32)
    qnorm = np.linalg.norm(qv)
    if qnorm == 0:
        return []
    sims = cm @ qv / (np.linalg.norm(cm, axis=1) * qnorm + 1e-9)
    k = min(k, len(corpus_embeddings))
    top_indices = np.argsort(sims)[-k:][::-1]
    return [(int(i), float(sims[i])) for i in top_indices]


def find_max_similarity(
    query_embedding: list[float],
    corpus_embeddings: list[list[float]],
) -> tuple[float, int]:
    if not corpus_embeddings:
        return 0.0, -1
    qv = np.array(query_embedding, dtype=np.float32)
    cm = np.array(corpus_embeddings, dtype=np.float32)
    qnorm = np.linalg.norm(qv)
    if qnorm == 0:
        return 0.0, -1
    sims = cm @ qv / (np.linalg.norm(cm, axis=1) * qnorm + 1e-9)
    best = int(np.argmax(sims))
    return float(sims[best]), best


def get_corpus_embeddings(corpus_texts: list[str]) -> list[list[float]]:
    if not corpus_texts:
        return []
    key = hashlib.md5("\n".join(sorted(corpus_texts)).encode()).hexdigest()
    if key not in _corpus_cache:
        _corpus_cache[key] = embed_batch(corpus_texts)
    return _corpus_cache[key]


def invalidate_corpus_cache() -> None:
    _corpus_cache.clear()
