import argparse
import datetime as dt
import json

from papertracker import cli, config, related_work, relevance, selector, summarizer
from papertracker.sources import openalex_client


def _profile(tmp_path) -> config.ProjectProfile:
    return config.ProjectProfile(
        id="related",
        name="Related Work",
        topic_statement="embodied agents in 3D environments",
        crossref_query_hint="embodied agents 3D",
        arxiv_categories=["cs.AI"],
        relevance_threshold=0.65,
        priority_venues=[],
        priority_venue_only=False,
        enabled_sources_default=["arxiv"],
        digest_dir=str(tmp_path / "digests" / "related"),
        seen_papers_file=str(tmp_path / ".papertracker" / "related" / "seen.json"),
        summary_cache_file=str(tmp_path / ".papertracker" / "related" / "summary_cache.json"),
    )


def _faceted_profile(tmp_path) -> config.ProjectProfile:
    return config.ProjectProfile(
        id="related",
        name="Related Work",
        topic_statement="embodied agents in 3D environments",
        crossref_query_hint="embodied agents 3D",
        arxiv_categories=["cs.AI"],
        relevance_threshold=0.65,
        priority_venues=[],
        priority_venue_only=False,
        enabled_sources_default=["arxiv"],
        digest_dir=str(tmp_path / "digests" / "related"),
        seen_papers_file=str(tmp_path / ".papertracker" / "related" / "seen.json"),
        summary_cache_file=str(tmp_path / ".papertracker" / "related" / "summary_cache.json"),
        contribution_statement="We build an embodied agent benchmark.",
        related_work_facets=[
            related_work.RelatedWorkFacet(
                id="benchmarks",
                name="Benchmarks",
                description="Evaluation benchmarks for embodied agents.",
                query_hint="embodied agent benchmark evaluation",
            ),
            related_work.RelatedWorkFacet(
                id="systems",
                name="Systems",
                description="Embodied agent systems.",
                query_hint="embodied agent system",
            ),
        ],
    )


def _paper(title: str, citations: int) -> dict:
    return {
        "canonical_id": f"openalex:{title.lower().replace(' ', '-')}",
        "source": "openalex",
        "venue": None,
        "title": title,
        "abstract": f"Abstract for {title}",
        "authors": ["Ada Lovelace"],
        "published": "1999-01-01",
        "url": "https://openalex.org/W123",
        "doi": "",
        "container_title": "Important Conference",
        "openalex_id": "https://openalex.org/W123",
        "cited_by_count": citations,
        "discovery_sources": ["citation"],
    }


def test_related_work_mode_writes_digest_without_seen_or_llm(monkeypatch, tmp_path):
    profile = _profile(tmp_path)
    args = argparse.Namespace(
        max_results=20,
        limit=1,
        threshold=None,
        select=False,
        refresh_summaries=False,
        priority_venues_only=False,
        provider=None,
        model=None,
    )

    monkeypatch.setattr(
        openalex_client,
        "fetch_related_work",
        lambda profile, cap: [
            _paper("Relevant Classic", 1000),
            _paper("Off Topic", 5000),
        ],
    )
    monkeypatch.setattr(
        relevance,
        "score_batch",
        lambda texts, topic_statement=None: [
            0.9 if "Relevant Classic" in text else 0.4 for text in texts
        ],
    )

    assert cli._run_related_work_profile(profile, args) == 0

    digest_path = (
        tmp_path
        / "digests"
        / "related"
        / "related-work"
        / f"{dt.date.today().isoformat()}.md"
    )
    content = digest_path.read_text(encoding="utf-8")
    assert "PaperTracker Related Work" in content
    assert "Relevant Classic" in content
    assert "Off Topic" not in content
    assert "**Citations:** 1000" in content
    assert not (tmp_path / ".papertracker" / "related" / "seen.json").exists()


def test_faceted_related_work_writes_matrix_and_json_without_seen(monkeypatch, tmp_path):
    profile = _faceted_profile(tmp_path)
    args = argparse.Namespace(
        max_results=20,
        limit=2,
        threshold=None,
        select=False,
        refresh_summaries=False,
        priority_venues_only=False,
        provider=None,
        model=None,
        facet_count=6,
        facet_candidates=5,
    )

    monkeypatch.setattr(cli, "_resolve_llm", lambda args: ("codex", "gpt", 0))
    monkeypatch.setattr(
        openalex_client,
        "fetch_related_work_faceted",
        lambda profile, facets, candidates_per_facet: [
            {**_paper("Benchmark Classic", 1000), "facet_hits": {"benchmarks": ["semantic"]}},
            {**_paper("System Classic", 500), "facet_hits": {"systems": ["citation"]}},
        ],
    )
    monkeypatch.setattr(relevance, "score_batch", lambda texts, topic_statement=None: [0.9] * len(texts))
    monkeypatch.setattr(
        summarizer,
        "run_json_prompt",
        lambda provider, model, prompt: json.dumps(
            {
                "annotations": [
                    {
                        "canonical_id": "openalex:benchmark-classic",
                        "role": "benchmark",
                        "why_cite": "Defines an evaluation reference point.",
                        "difference_from_contribution": "It evaluates rather than builds the target benchmark.",
                        "evidence_basis": "abstract",
                    },
                    {
                        "canonical_id": "openalex:system-classic",
                        "role": "system",
                        "why_cite": "Describes a relevant embodied-agent system.",
                        "difference_from_contribution": "It focuses on system design.",
                        "evidence_basis": "abstract",
                    },
                ]
            }
        ),
    )

    assert cli._run_faceted_related_work_profile(profile, args) == 0

    out_dir = tmp_path / "digests" / "related" / "related-work"
    md_path = out_dir / f"{dt.date.today().isoformat()}.facets.md"
    json_path = out_dir / f"{dt.date.today().isoformat()}.facets.json"
    content = md_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "Suggested section order" in content
    assert "Benchmark Classic" in content
    assert "System Classic" in content
    assert [candidate["role"] for candidate in payload["candidates"]] == ["benchmark", "system"]
    assert not (tmp_path / ".papertracker" / "related" / "seen.json").exists()


def test_faceted_no_summarize_uses_configured_facets_without_llm(monkeypatch, tmp_path):
    profile = _faceted_profile(tmp_path)
    args = argparse.Namespace(
        max_results=20,
        limit=1,
        threshold=None,
        select=False,
        no_summarize=True,
        refresh_summaries=False,
        priority_venues_only=False,
        scorer=None,
        provider=None,
        model=None,
        facet_count=6,
        facet_candidates=5,
    )
    monkeypatch.setattr(
        cli,
        "_resolve_llm",
        lambda args: (_ for _ in ()).throw(AssertionError("LLM preflight must not run")),
    )
    monkeypatch.setattr(
        openalex_client,
        "fetch_related_work_faceted",
        lambda profile, facets, candidates_per_facet: [
            {**_paper("Local Facet Paper", 10), "facet_hits": {"benchmarks": ["search"]}}
        ],
    )
    monkeypatch.setattr(
        relevance,
        "score_batch",
        lambda texts, topic_statement=None: [0.9] * len(texts),
    )
    monkeypatch.setattr(
        summarizer,
        "run_json_prompt",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not run")),
    )

    assert cli._run_faceted_related_work_profile(profile, args) == 0

    json_path = (
        tmp_path
        / "digests"
        / "related"
        / "related-work"
        / f"{dt.date.today().isoformat()}.facets.json"
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["candidates"][0]["role"] == "background"


def test_faceted_related_work_select_writes_only_approved_candidates(monkeypatch, tmp_path):
    profile = _faceted_profile(tmp_path)
    args = argparse.Namespace(
        max_results=20,
        limit=2,
        threshold=None,
        select=True,
        refresh_summaries=False,
        priority_venues_only=False,
        provider=None,
        model=None,
        facet_count=6,
        facet_candidates=5,
    )

    monkeypatch.setattr(cli, "_resolve_llm", lambda args: ("codex", "gpt", 0))
    monkeypatch.setattr(
        openalex_client,
        "fetch_related_work_faceted",
        lambda profile, facets, candidates_per_facet: [
            {**_paper("Benchmark Classic", 1000), "facet_hits": {"benchmarks": ["semantic"]}},
            {**_paper("System Classic", 500), "facet_hits": {"systems": ["citation"]}},
        ],
    )
    monkeypatch.setattr(relevance, "score_batch", lambda texts, topic_statement=None: [0.9] * len(texts))
    monkeypatch.setattr(
        summarizer,
        "run_json_prompt",
        lambda provider, model, prompt: json.dumps(
            {
                "annotations": [
                    {
                        "canonical_id": "openalex:benchmark-classic",
                        "role": "benchmark",
                        "why_cite": "Defines an evaluation reference point.",
                        "difference_from_contribution": "It evaluates rather than builds the target benchmark.",
                        "evidence_basis": "abstract",
                    },
                    {
                        "canonical_id": "openalex:system-classic",
                        "role": "system",
                        "why_cite": "Describes a relevant embodied-agent system.",
                        "difference_from_contribution": "It focuses on system design.",
                        "evidence_basis": "abstract",
                    },
                ]
            }
        ),
    )
    monkeypatch.setattr(
        selector,
        "select_related_work_candidates",
        lambda papers, facets: [
            {
                "canonical_id": "openalex:system-classic",
                "primary_facet": "benchmarks",
                "role": "contrast",
            }
        ],
    )

    assert cli._run_faceted_related_work_profile(profile, args) == 0

    json_path = (
        tmp_path
        / "digests"
        / "related"
        / "related-work"
        / f"{dt.date.today().isoformat()}.facets.json"
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["title"] == "System Classic"
    assert payload["candidates"][0]["primary_facet"] == "benchmarks"
    assert payload["candidates"][0]["role"] == "contrast"
    assert not (tmp_path / ".papertracker" / "related" / "seen.json").exists()
