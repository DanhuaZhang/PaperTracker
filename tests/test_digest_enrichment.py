from papertracker import digest_writer


def test_daily_digest_renders_doi_enrichment_fields():
    paper = {
        "canonical_id": "doi:10.1000/xyz",
        "source": "acm",
        "venue": None,
        "title": "Paper",
        "authors": ["Ada Lovelace"],
        "published": "2025-01-02",
        "url": "https://doi.org/10.1000/xyz",
        "doi": "10.1000/xyz",
        "container_title": "CHI",
        "oa_url": "https://example.org/paper.pdf",
        "cited_by_count": 14,
        "metadata_sources": ["opencitations", "unpaywall"],
    }

    digest = digest_writer.render_digest("2025-01-03", [(paper, "Summary")])

    assert "**Open access:** [PDF/repository](https://example.org/paper.pdf)" in digest
    assert "**Citations:** 14" in digest
    assert "**Metadata:** opencitations, unpaywall" in digest
