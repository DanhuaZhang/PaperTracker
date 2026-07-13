import datetime as dt

from papertracker import cli, config
from papertracker.sources import crossref_client, journal_rss


def _profile(priority_venues=None):
    return config.ProjectProfile(
        id="test",
        name="Test",
        topic_statement="topic",
        crossref_query_hint="query",
        arxiv_categories=["cs.HC"],
        relevance_threshold=0.5,
        priority_venues=priority_venues or [],
        priority_venue_only=False,
        enabled_sources_default=["acm"],
        digest_dir="digests/test",
        seen_papers_file=".papertracker/test/seen.json",
        summary_cache_file=".papertracker/test/cache.json",
    )


def test_crossref_uses_shared_abstract_fallback(monkeypatch):
    monkeypatch.setattr(
        crossref_client,
        "_fetch_all_items",
        lambda *args: [
            {
                "DOI": "10.1000/xyz",
                "title": ["Paper"],
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "published": {"date-parts": [[2025, 1, 2]]},
                "container-title": ["CHI"],
            }
        ],
    )
    monkeypatch.setattr(
        crossref_client.doi_enrichment,
        "recover_abstract",
        lambda doi: {
            "abstract": "Recovered abstract",
            "provider": "semantic_scholar",
            "metadata_sources": ["semantic_scholar"],
        },
    )

    papers = crossref_client.search(
        320,
        "acm",
        dt.date(2025, 1, 1),
        dt.date(2025, 1, 3),
        _profile(),
    )

    assert papers[0]["abstract"] == "Recovered abstract"
    assert papers[0]["metadata_sources"] == ["semantic_scholar"]


def test_journal_rss_uses_shared_abstract_fallback(monkeypatch):
    venue = {"name": "Journal", "patterns": ["Journal"], "rss": "https://feed"}
    monkeypatch.setattr(
        journal_rss,
        "_fetch_feed",
        lambda url: [
            {
                "title": "Paper",
                "id": "doi:10.1000/xyz",
                "published_parsed": (2025, 1, 2, 0, 0, 0, 0, 0, 0),
            }
        ],
    )
    monkeypatch.setattr(
        journal_rss.doi_enrichment,
        "recover_abstract",
        lambda doi: {
            "abstract": "Repository abstract",
            "metadata_sources": ["openaire"],
        },
    )

    papers = journal_rss.fetch(
        dt.date(2025, 1, 1),
        dt.date(2025, 1, 3),
        _profile([venue]),
    )

    assert papers[0]["abstract"] == "Repository abstract"
    assert papers[0]["metadata_sources"] == ["openaire"]


def test_cli_enriches_only_doi_papers(monkeypatch):
    calls = []

    def enrich(paper):
        calls.append(paper["doi"])
        paper["oa_url"] = "https://example.org/paper.pdf"
        return paper

    monkeypatch.setattr(cli.doi_enrichment, "enrich_paper", enrich)
    papers = [
        {"canonical_id": "doi:10.1000/xyz", "doi": "10.1000/xyz"},
        {"canonical_id": "arxiv:1234.5678", "doi": ""},
    ]

    result = cli._enrich_doi_papers(papers)

    assert result is papers
    assert calls == ["10.1000/xyz"]
    assert papers[0]["oa_url"] == "https://example.org/paper.pdf"

