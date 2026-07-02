import pytest

from papertracker import config, related_work, relevance, summarizer


def _profile() -> config.ProjectProfile:
    return config.ProjectProfile(
        id="facets",
        name="Faceted Related Work",
        topic_statement="social spatial reasoning for embodied agents",
        crossref_query_hint="social spatial embodied agents",
        arxiv_categories=["cs.AI"],
        relevance_threshold=0.6,
        priority_venues=[],
        priority_venue_only=False,
        enabled_sources_default=["arxiv"],
        digest_dir="digests/facets",
        seen_papers_file=".papertracker/facets/seen.json",
        summary_cache_file=".papertracker/facets/summary_cache.json",
        contribution_statement="We infer stance and generate spatial formations.",
    )


def _facet(facet_id: str, name: str) -> related_work.RelatedWorkFacet:
    return related_work.RelatedWorkFacet(
        id=facet_id,
        name=name,
        description=f"{name} papers.",
        query_hint=f"{name} query",
    )


def _paper(title: str, facet_id: str, citations: int = 10, abstract: str = "Abstract") -> dict:
    return {
        "canonical_id": f"openalex:{title.lower().replace(' ', '-')}",
        "source": "openalex",
        "venue": None,
        "title": title,
        "abstract": abstract,
        "authors": ["Ada Lovelace"],
        "published": "2001-01-01",
        "url": "https://openalex.org/W123",
        "doi": "",
        "container_title": "Important Conference",
        "openalex_id": "https://openalex.org/W123",
        "cited_by_count": citations,
        "discovery_sources": ["semantic"],
        "facet_hits": {facet_id: ["semantic"]},
    }


def test_generate_facets_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(summarizer, "run_json_prompt", lambda provider, model, prompt: "not json")

    with pytest.raises(related_work.RelatedWorkError, match="invalid JSON"):
        related_work.generate_facets(_profile(), "codex", "gpt", 6)


def test_annotate_candidates_forces_metadata_only_without_abstract(monkeypatch):
    facets = [_facet("stance", "Stance")]
    paper = _paper("No Abstract Paper", "stance", abstract="")
    monkeypatch.setattr(
        summarizer,
        "run_json_prompt",
        lambda provider, model, prompt: """
{"annotations":[{"canonical_id":"openalex:no-abstract-paper","role":"method","why_cite":"Relevant method.","difference_from_contribution":"Uses a different signal.","evidence_basis":"abstract"}]}
""",
    )

    annotated = related_work.annotate_candidates([paper], facets, _profile(), "codex", "gpt")

    assert annotated[0]["role"] == "method"
    assert annotated[0]["why_cite"] == "Relevant method."
    assert annotated[0]["evidence_basis"] == "metadata-only"


def test_rank_facet_candidates_round_robins_across_facets(monkeypatch):
    facets = [_facet("stance", "Stance"), _facet("formation", "Formation")]
    papers = [
        _paper("Strong Stance", "stance", 100),
        _paper("Second Stance", "stance", 90),
        _paper("Strong Formation", "formation", 80),
        _paper("Second Formation", "formation", 70),
    ]

    def fake_score_batch(texts, topic_statement=None):
        if "Stance" in (topic_statement or ""):
            return [0.95, 0.90, 0.20, 0.20]
        if "Formation" in (topic_statement or ""):
            return [0.20, 0.20, 0.95, 0.90]
        return [0.85, 0.84, 0.83, 0.82]

    monkeypatch.setattr(relevance, "score_batch", fake_score_batch)

    ranked = related_work.rank_facet_candidates(
        papers,
        facets,
        _profile(),
        threshold=0.0,
        limit=2,
    )

    assert [paper["primary_facet"] for paper in ranked] == ["stance", "formation"]
    assert [paper["title"] for paper in ranked] == ["Strong Stance", "Strong Formation"]
