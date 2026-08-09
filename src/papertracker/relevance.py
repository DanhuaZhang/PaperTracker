"""Embedding-based relevance scoring.

Each fetched paper's (title + abstract) is embedded once with a small local
ONNX model (default: BAAI/bge-small-en-v1.5, ~130 MB). Cosine similarity to the
active project profile's topic vector decides whether the paper is on-topic.

The model is loaded lazily on first call and cached; topic vectors are cached by
topic statement so multiple profiles can run in one process.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from functools import lru_cache
import math
import os
from pathlib import Path
import re
import shutil

import numpy as np
from fastembed import TextEmbedding

from . import config

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RelevanceScore:
    dense_score: float
    dense_norm: float
    bm25_score: float
    bm25_norm: float
    hybrid_score: float
    reranker_score: float | None
    final_score: float


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    log.info("Loading embedding model: %s", config.EMBEDDING_MODEL)
    cache_dir = _embedding_cache_dir()
    try:
        return TextEmbedding(model_name=config.EMBEDDING_MODEL, cache_dir=str(cache_dir))
    except Exception as exc:
        if not _looks_like_incomplete_fastembed_cache(exc):
            raise
        log.warning(
            "Embedding model cache at %s looks incomplete; clearing it and retrying once.",
            cache_dir,
        )
        _clear_embedding_cache(cache_dir)
        return TextEmbedding(model_name=config.EMBEDDING_MODEL, cache_dir=str(cache_dir))


def _embedding_cache_dir() -> Path:
    configured = os.environ.get("FASTEMBED_CACHE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config.USER_DATA_DIR / "cache" / "fastembed"


def _looks_like_incomplete_fastembed_cache(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "model_optimized.onnx" in message
        and ("no_suchfile" in message or "file doesn't exist" in message or "no such file" in message)
    ) or "files have been corrupted during downloading process" in message


def _clear_embedding_cache(cache_dir: Path) -> None:
    path = cache_dir.expanduser().resolve(strict=False)
    if "fastembed" not in path.name.lower():
        log.warning("Refusing to clear embedding cache path that does not look FastEmbed-owned: %s", path)
        return
    shutil.rmtree(path, ignore_errors=True)


@lru_cache(maxsize=32)
def _topic_vector(topic_statement: str) -> np.ndarray:
    vecs = list(_model().embed([topic_statement]))
    return vecs[0]


def score_batch(texts: list[str], topic_statement: str | None = None) -> list[float]:
    """Return cosine similarity to the active topic statement for each text.

    BGE models output L2-normalized vectors, so dot product == cosine similarity.
    """
    if not texts:
        return []
    vecs = list(_model().embed(texts))
    t = _topic_vector(topic_statement or config.TOPIC_STATEMENT)
    return [float(np.dot(v, t)) for v in vecs]


def score_texts(
    query: str,
    texts: list[str],
    *,
    mode: str = "dense",
    enable_reranker: bool = False,
    reranker_model: str | None = None,
    reranker_top_k: int = 100,
) -> list[RelevanceScore]:
    """Return relevance diagnostics for each text under the requested scorer.

    ``dense`` mode is the original PaperTracker computation: cosine similarity
    between the query embedding and each text embedding. ``hybrid`` mode adds a
    normalized BM25 signal and can optionally rerank the strongest candidates
    with a local cross-encoder.
    """
    if not texts:
        return []
    if mode not in {"dense", "hybrid"}:
        raise ValueError(f"Unknown relevance scorer {mode!r}; expected 'dense' or 'hybrid'")

    dense_scores = score_batch(texts, topic_statement=query)
    dense_norms = [_normalize_dense(score) for score in dense_scores]

    if mode == "dense":
        return [
            RelevanceScore(
                dense_score=score,
                dense_norm=norm,
                bm25_score=0.0,
                bm25_norm=0.0,
                hybrid_score=score,
                reranker_score=None,
                final_score=score,
            )
            for score, norm in zip(dense_scores, dense_norms)
        ]

    bm25_scores = _bm25_scores(query, texts)
    bm25_norms = _minmax(bm25_scores)
    hybrid_scores = [
        (0.60 * dense_norm) + (0.40 * bm25_norm)
        for dense_norm, bm25_norm in zip(dense_norms, bm25_norms)
    ]
    reranker_scores: list[float | None] = [None] * len(texts)
    final_scores = list(hybrid_scores)

    if enable_reranker:
        reranked = _rerank_scores(
            query,
            texts,
            hybrid_scores,
            model_name=reranker_model or config.RERANKER_MODEL,
            top_k=reranker_top_k,
        )
        if reranked:
            raw_by_idx = {idx: score for idx, score in reranked}
            raw_values = list(raw_by_idx.values())
            norm_by_idx = dict(zip(raw_by_idx, _minmax(raw_values)))
            has_reranker_range = max(raw_values) > min(raw_values)
            for idx, raw_score in raw_by_idx.items():
                reranker_scores[idx] = raw_score
                if has_reranker_range:
                    final_scores[idx] = (0.35 * hybrid_scores[idx]) + (0.65 * norm_by_idx[idx])

    return [
        RelevanceScore(
            dense_score=dense_score,
            dense_norm=dense_norm,
            bm25_score=bm25_score,
            bm25_norm=bm25_norm,
            hybrid_score=hybrid_score,
            reranker_score=reranker_score,
            final_score=final_score,
        )
        for dense_score, dense_norm, bm25_score, bm25_norm, hybrid_score, reranker_score, final_score
        in zip(
            dense_scores,
            dense_norms,
            bm25_scores,
            bm25_norms,
            hybrid_scores,
            reranker_scores,
            final_scores,
        )
    ]


def filter_papers(
    papers: list[dict],
    threshold: float,
    topic_statement: str | None = None,
    scorer: str = "dense",
    enable_reranker: bool = False,
    reranker_model: str | None = None,
    reranker_top_k: int = 100,
) -> list[dict]:
    """Annotate each paper with `relevance_score` and return those at/above threshold."""
    if not papers:
        return []
    texts = [
        f"{p.get('title', '')}. {p.get('abstract', '')}".strip()
        for p in papers
    ]
    scores = score_texts(
        topic_statement or config.TOPIC_STATEMENT,
        texts,
        mode=scorer,
        enable_reranker=enable_reranker,
        reranker_model=reranker_model,
        reranker_top_k=reranker_top_k,
    )
    kept: list[dict] = []
    for paper, score in zip(papers, scores):
        _annotate_score(paper, score)
        if score.final_score >= threshold:
            kept.append(paper)
        else:
            log.debug(
                "relevance %.3f (drop): %s",
                score.final_score,
                paper.get("title", "")[:80],
            )
    log.info(
        "relevance filter [%s] @ %.3f: %d/%d papers passed",
        scorer, threshold, len(kept), len(papers),
    )
    return kept


def annotate_score_fields(
    paper: dict,
    score: RelevanceScore,
    *,
    prefix: str = "",
    relevance_key: str | None = "relevance_score",
) -> None:
    """Store scorer diagnostics on a paper dict."""
    if relevance_key:
        paper[relevance_key] = score.final_score
    _annotate_score(paper, score, prefix=prefix, relevance_key=None)


def _annotate_score(
    paper: dict,
    score: RelevanceScore,
    *,
    prefix: str = "",
    relevance_key: str | None = "relevance_score",
) -> None:
    if relevance_key:
        paper[relevance_key] = score.final_score
    paper[f"{prefix}dense_relevance_score"] = score.dense_score
    paper[f"{prefix}dense_relevance_norm"] = score.dense_norm
    paper[f"{prefix}bm25_relevance_score"] = score.bm25_score
    paper[f"{prefix}bm25_relevance_norm"] = score.bm25_norm
    paper[f"{prefix}hybrid_relevance_score"] = score.hybrid_score
    paper[f"{prefix}reranker_relevance_score"] = score.reranker_score


def _normalize_dense(score: float) -> float:
    return min(max((score + 1.0) / 2.0, 0.0), 1.0)


def _tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text.lower()) if len(token) > 1]


def _bm25_scores(query: str, texts: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    query_terms = _tokenize(query)
    documents = [_tokenize(text) for text in texts]
    if not query_terms or not documents:
        return [0.0] * len(texts)

    doc_count = len(documents)
    avgdl = sum(len(doc) for doc in documents) / doc_count if doc_count else 0.0
    if avgdl <= 0.0:
        return [0.0] * len(texts)

    dfs: dict[str, int] = {}
    for doc in documents:
        for term in set(doc):
            dfs[term] = dfs.get(term, 0) + 1

    query_vocab = set(query_terms)
    idfs = {
        term: math.log(1.0 + ((doc_count - dfs.get(term, 0) + 0.5) / (dfs.get(term, 0) + 0.5)))
        for term in query_vocab
    }

    out: list[float] = []
    for doc in documents:
        term_counts: dict[str, int] = {}
        for term in doc:
            term_counts[term] = term_counts.get(term, 0) + 1
        doc_len = len(doc)
        score = 0.0
        for term in query_vocab:
            freq = term_counts.get(term, 0)
            if not freq:
                continue
            denom = freq + k1 * (1.0 - b + b * (doc_len / avgdl))
            score += idfs[term] * ((freq * (k1 + 1.0)) / denom)
        out.append(score)
    return out


def _minmax(scores: list[float]) -> list[float]:
    if not scores:
        return []
    lo = min(scores)
    hi = max(scores)
    if hi <= lo:
        return [0.0] * len(scores)
    return [(score - lo) / (hi - lo) for score in scores]


@lru_cache(maxsize=2)
def _cross_encoder(model_name: str):
    from sentence_transformers import CrossEncoder

    log.info("Loading reranker model: %s", model_name)
    return CrossEncoder(model_name)


def _rerank_scores(
    query: str,
    texts: list[str],
    hybrid_scores: list[float],
    *,
    model_name: str,
    top_k: int,
) -> list[tuple[int, float]]:
    if top_k <= 0:
        return []
    indices = sorted(range(len(texts)), key=lambda idx: -hybrid_scores[idx])[:top_k]
    if not indices:
        return []
    try:
        model = _cross_encoder(model_name)
        raw_scores = model.predict([(query, texts[idx]) for idx in indices])
    except Exception as exc:  # optional dependency/model download/runtime failures
        log.warning("Reranker unavailable; falling back to hybrid relevance: %s", exc)
        return []
    return [(idx, float(score)) for idx, score in zip(indices, raw_scores)]
