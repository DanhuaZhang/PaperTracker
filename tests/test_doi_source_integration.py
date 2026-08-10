import datetime as dt
import logging

import pytest
import requests

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


def test_crossref_propagates_fetch_failure(monkeypatch):
    monkeypatch.setattr(
        crossref_client,
        "_get_with_retry",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.ConnectionError("offline")
        ),
    )

    with pytest.raises(requests.ConnectionError, match="offline"):
        crossref_client.search(
            320,
            "acm",
            dt.date(2025, 1, 1),
            dt.date(2025, 1, 3),
            _profile(),
        )


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


def test_journal_rss_propagates_total_feed_failure(monkeypatch):
    venue = {"name": "Journal", "patterns": ["Journal"], "rss": "https://feed"}
    monkeypatch.setattr(
        journal_rss,
        "_fetch_feed",
        lambda url: (_ for _ in ()).throw(requests.ConnectionError("offline")),
    )

    with pytest.raises(RuntimeError, match="Journal"):
        journal_rss.fetch(
            dt.date(2025, 1, 1),
            dt.date(2025, 1, 3),
            _profile([venue]),
        )


def test_journal_rss_keeps_papers_from_feeds_that_answered(monkeypatch, caplog):
    """One blocked publisher must not discard the feeds that worked.

    ACM's Digital Library answers every server-side request with a Cloudflare
    challenge, so a config listing both ACM and IEEE feeds hits this on every
    run. Failing the whole source there threw away real IEEE papers and marked
    the run as failed, for a condition that is permanent and not ours to fix.
    """
    blocked = {"name": "Blocked", "patterns": ["Blocked"], "rss": "https://blocked"}
    working = {"name": "Working", "patterns": ["Working"], "rss": "https://working"}

    def fetch_feed(url):
        if url == "https://blocked":
            raise requests.HTTPError("403 Client Error: Forbidden")
        return [
            {
                "title": "Paper",
                "id": "doi:10.1000/xyz",
                # Over the 20-word bar _to_paper uses to tell an abstract from a
                # teaser, so the test never reaches the network for a fallback.
                "summary": "A sufficiently long abstract " * 8,
                "published_parsed": (2025, 1, 2, 0, 0, 0, 0, 0, 0),
            }
        ]

    monkeypatch.setattr(journal_rss, "_fetch_feed", fetch_feed)

    with caplog.at_level(logging.WARNING, logger=journal_rss.log.name):
        papers = journal_rss.fetch(
            dt.date(2025, 1, 1),
            dt.date(2025, 1, 3),
            _profile([blocked, working]),
        )

    assert [p["doi"] for p in papers] == ["10.1000/xyz"]
    assert "Blocked" in caplog.text
    assert "Working" not in caplog.text


def test_journal_rss_warns_when_a_feed_carries_no_dois(monkeypatch, caplog):
    """A feed that yields nothing must not look like a feed that was empty.

    IEEE Xplore's TOC feeds identify papers by Xplore document URL and carry no
    DOI anywhere, so every entry is dropped. Without this warning the run logs
    `kept 0` and reads as a quiet day at the journal.
    """
    venue = {"name": "Xplore", "patterns": ["Xplore"], "rss": "https://feed"}
    monkeypatch.setattr(
        journal_rss,
        "_fetch_feed",
        lambda url: [
            {
                "title": "Paper without a DOI",
                "id": "http://ieeexplore.ieee.org/document/11536914",
                "link": "http://ieeexplore.ieee.org/document/11536914",
                "summary": "An abstract with no DOI in it " * 8,
                "published_parsed": (2025, 1, 2, 0, 0, 0, 0, 0, 0),
            }
        ],
    )

    with caplog.at_level(logging.WARNING, logger=journal_rss.log.name):
        papers = journal_rss.fetch(
            dt.date(2025, 1, 1),
            dt.date(2025, 1, 3),
            _profile([venue]),
        )

    assert papers == []
    assert "no DOI" in caplog.text
    assert "Xplore" in caplog.text


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
