import argparse
from pathlib import Path

import pytest

from papertracker import cli, config, relevance


def test_score_texts_dense_preserves_original_cosine(monkeypatch):
    monkeypatch.setattr(relevance, "score_batch", lambda texts, topic_statement=None: [0.7, 0.2])

    scores = relevance.score_texts("agent topic", ["paper a", "paper b"], mode="dense")

    assert [score.final_score for score in scores] == [0.7, 0.2]
    assert [score.hybrid_score for score in scores] == [0.7, 0.2]
    assert [score.bm25_score for score in scores] == [0.0, 0.0]


def test_model_clears_managed_cache_and_retries_when_fastembed_snapshot_is_incomplete(monkeypatch):
    relevance._model.cache_clear()
    sentinel = object()
    attempts: list[dict] = []
    cleared: list[Path] = []

    def fake_text_embedding(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("Load model from /tmp/fastembed_cache/model_optimized.onnx failed. File doesn't exist")
        return sentinel

    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    monkeypatch.setattr(relevance, "TextEmbedding", fake_text_embedding)
    monkeypatch.setattr(relevance, "_clear_embedding_cache", cleared.append, raising=False)

    try:
        assert relevance._model() is sentinel
    finally:
        relevance._model.cache_clear()

    assert len(attempts) == 2
    assert attempts[0]["model_name"] == config.EMBEDDING_MODEL
    assert Path(attempts[0]["cache_dir"]) == Path(".papertracker/fastembed_cache")
    assert attempts[1] == attempts[0]
    assert cleared == [Path(".papertracker/fastembed_cache")]


def test_score_texts_hybrid_combines_dense_and_bm25(monkeypatch):
    monkeypatch.setattr(relevance, "score_batch", lambda texts, topic_statement=None: [0.0, 0.0])

    scores = relevance.score_texts(
        "spatial agent",
        [
            "spatial agent navigation in rooms",
            "protein folding benchmark",
        ],
        mode="hybrid",
    )

    assert scores[0].bm25_norm == 1.0
    assert scores[1].bm25_norm == 0.0
    assert scores[0].final_score == pytest.approx(0.70)
    assert scores[1].final_score == pytest.approx(0.30)


def test_filter_papers_hybrid_stores_diagnostics(monkeypatch):
    monkeypatch.setattr(relevance, "score_batch", lambda texts, topic_statement=None: [0.0, 0.0])
    papers = [
        {"title": "Spatial agent", "abstract": "spatial agent navigation"},
        {"title": "Protein", "abstract": "folding benchmark"},
    ]

    kept = relevance.filter_papers(
        papers,
        threshold=0.6,
        topic_statement="spatial agent",
        scorer="hybrid",
    )

    assert [paper["title"] for paper in kept] == ["Spatial agent"]
    assert kept[0]["relevance_score"] == pytest.approx(0.70)
    assert kept[0]["dense_relevance_score"] == 0.0
    assert kept[0]["bm25_relevance_norm"] == 1.0
    assert kept[0]["hybrid_relevance_score"] == pytest.approx(0.70)


def test_active_threshold_uses_scorer_specific_default():
    profile = config.ProjectProfile(
        id="test",
        name="Test",
        topic_statement="topic",
        crossref_query_hint="topic",
        arxiv_categories=["cs.AI"],
        relevance_threshold=0.65,
        priority_venues=[],
        priority_venue_only=False,
        enabled_sources_default=["arxiv"],
        digest_dir="digests/test",
        seen_papers_file=".papertracker/test/seen.json",
        summary_cache_file=".papertracker/test/summary_cache.json",
        relevance_scorer="hybrid",
        hybrid_relevance_threshold=0.55,
    )

    assert cli._active_threshold(profile, argparse.Namespace(threshold=None)) == 0.55
    assert cli._active_threshold(profile, argparse.Namespace(threshold=0.42)) == 0.42


def test_reranker_failure_falls_back_to_hybrid(monkeypatch):
    monkeypatch.setattr(relevance, "score_batch", lambda texts, topic_statement=None: [0.0, 0.0])

    def fail_rerank(*args, **kwargs):
        return []

    monkeypatch.setattr(relevance, "_rerank_scores", fail_rerank)

    scores = relevance.score_texts(
        "spatial agent",
        ["spatial agent navigation", "protein folding"],
        mode="hybrid",
        enable_reranker=True,
    )

    assert [score.reranker_score for score in scores] == [None, None]
    assert [score.final_score for score in scores] == [pytest.approx(0.70), pytest.approx(0.30)]


def test_single_reranker_score_records_score_without_changing_final(monkeypatch):
    monkeypatch.setattr(relevance, "score_batch", lambda texts, topic_statement=None: [0.0])
    monkeypatch.setattr(relevance, "_rerank_scores", lambda *args, **kwargs: [(0, 3.5)])

    scores = relevance.score_texts(
        "spatial agent",
        ["spatial agent navigation"],
        mode="hybrid",
        enable_reranker=True,
    )

    assert scores[0].reranker_score == 3.5
    assert scores[0].final_score == pytest.approx(scores[0].hybrid_score)
