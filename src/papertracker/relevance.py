"""Embedding-based relevance scoring.

Each fetched paper's (title + abstract) is embedded once with a small local
ONNX model (default: BAAI/bge-small-en-v1.5, ~130 MB). Cosine similarity to the
active project profile's topic vector decides whether the paper is on-topic.

The model is loaded lazily on first call and cached; topic vectors are cached by
topic statement so multiple profiles can run in one process.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from fastembed import TextEmbedding

from . import config

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    log.info("Loading embedding model: %s", config.EMBEDDING_MODEL)
    return TextEmbedding(model_name=config.EMBEDDING_MODEL)


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


def filter_papers(
    papers: list[dict],
    threshold: float,
    topic_statement: str | None = None,
) -> list[dict]:
    """Annotate each paper with `relevance_score` and return those at/above threshold."""
    if not papers:
        return []
    texts = [
        f"{p.get('title', '')}. {p.get('abstract', '')}".strip()
        for p in papers
    ]
    scores = score_batch(texts, topic_statement=topic_statement)
    kept: list[dict] = []
    for paper, s in zip(papers, scores):
        paper["relevance_score"] = s
        if s >= threshold:
            kept.append(paper)
        else:
            log.debug("relevance %.3f (drop): %s", s, paper.get("title", "")[:80])
    log.info(
        "relevance filter @ %.3f: %d/%d papers passed",
        threshold, len(kept), len(papers),
    )
    return kept
