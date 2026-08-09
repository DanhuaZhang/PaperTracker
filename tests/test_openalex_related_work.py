import pytest

from papertracker import config
from papertracker.related_work import RelatedWorkFacet
from papertracker.sources import openalex_client


def _profile() -> config.ProjectProfile:
    return config.ProjectProfile(
        id="test",
        name="Test Project",
        topic_statement="embodied agents in 3D environments",
        crossref_query_hint="embodied agents 3D",
        arxiv_categories=["cs.AI"],
        relevance_threshold=0.6,
        priority_venues=[],
        priority_venue_only=False,
        enabled_sources_default=["arxiv"],
        digest_dir="digests/test",
        seen_papers_file=".papertracker/test/seen.json",
        summary_cache_file=".papertracker/test/summary_cache.json",
    )


def _work(citations: int = 10) -> dict:
    return {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1000/XYZ",
        "display_name": "A Seminal Embodied Agent Paper",
        "publication_year": 1999,
        "publication_date": "1999-01-01",
        "cited_by_count": citations,
        "authorships": [
            {"author": {"display_name": "Ada Lovelace"}},
            {"author": {"display_name": "Grace Hopper"}},
        ],
        "primary_location": {"source": {"display_name": "Important Conference"}},
        "abstract_inverted_index": {"Classic": [0], "paper": [1]},
        "relevance_score": 0.91,
    }


def test_fetch_related_work_combines_semantic_and_citation_batches(monkeypatch):
    calls = []

    def fake_fetch_works(params, limit, discovery_source):
        calls.append((params, limit, discovery_source))
        return [_work(12 if discovery_source == "semantic" else 34)]

    monkeypatch.setattr(openalex_client, "_fetch_works", fake_fetch_works)

    papers = openalex_client.fetch_related_work(_profile(), cap=25)

    assert [call[2] for call in calls] == ["semantic", "citation"]
    assert calls[0][0] == {"search.semantic": "embodied agents in 3D environments"}
    assert calls[1][0]["search"] == "embodied agents 3D"
    assert calls[1][0]["sort"] == "cited_by_count:desc"
    assert len(papers) == 1
    assert papers[0]["canonical_id"] == "doi:10.1000/xyz"
    assert papers[0]["abstract"] == "Classic paper"
    assert papers[0]["authors"] == ["Ada Lovelace", "Grace Hopper"]
    assert papers[0]["cited_by_count"] == 34
    assert papers[0]["discovery_sources"] == ["citation", "semantic"]


def test_fetch_related_work_faceted_queries_each_facet_and_preserves_hits(monkeypatch):
    calls = []
    facets = [
        RelatedWorkFacet(
            id="stance",
            name="Stance inference",
            description="Inferring stance from opinions.",
            query_hint="stance inference opinion",
        ),
        RelatedWorkFacet(
            id="formation",
            name="Spatial formation",
            description="Generating spatial layouts.",
            query_hint="spatial formation generation",
        ),
    ]

    def fake_fetch_works(params, limit, discovery_source):
        calls.append((params, limit, discovery_source))
        return [_work(12 if "semantic" in discovery_source else 34)]

    monkeypatch.setattr(openalex_client, "_fetch_works", fake_fetch_works)

    papers = openalex_client.fetch_related_work_faceted(
        _profile(),
        facets=facets,
        candidates_per_facet=10,
    )

    assert [call[2] for call in calls] == [
        "stance:semantic",
        "stance:citation",
        "formation:semantic",
        "formation:citation",
    ]
    assert "search.semantic" in calls[0][0]
    assert calls[1][0]["search"] == "stance inference opinion"
    assert calls[1][0]["sort"] == "cited_by_count:desc"
    assert calls[3][0]["search"] == "spatial formation generation"
    assert len(papers) == 1
    assert papers[0]["facet_hits"] == {
        "formation": ["citation", "semantic"],
        "stance": ["citation", "semantic"],
    }
    assert papers[0]["discovery_sources"] == ["citation", "semantic"]


def test_fetch_works_adds_openalex_auth_params(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        def json(self):
            return {"results": []}

    def fake_get(url, params, headers, timeout):
        calls.append((url, params, headers, timeout))
        return Response()

    monkeypatch.setattr(openalex_client.requests, "get", fake_get)
    monkeypatch.setattr(config, "OPENALEX_API_KEY", "secret-key")
    monkeypatch.setattr(config, "USER_EMAIL", "user@example.com")

    assert openalex_client._fetch_works({"search": "agent"}, 5, "citation") == []

    _, params, headers, timeout = calls[0]
    assert params["api_key"] == "secret-key"
    assert params["mailto"] == "user@example.com"
    assert params["search"] == "agent"
    assert params["per_page"] == "5"
    assert params["select"]
    assert headers["User-Agent"] == config.USER_AGENT
    assert timeout == 30


def test_fetch_works_raises_when_openalex_is_unavailable(monkeypatch):
    class Response:
        status_code = 500

    monkeypatch.setattr(
        openalex_client.requests,
        "get",
        lambda *args, **kwargs: Response(),
    )

    with pytest.raises(openalex_client.OpenAlexError, match="HTTP 500"):
        openalex_client._fetch_works({"search": "agent"}, 5, "citation")
