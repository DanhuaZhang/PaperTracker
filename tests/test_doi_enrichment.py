from papertracker.sources import doi_enrichment


def test_recover_abstract_uses_ordered_fallbacks_and_stops(monkeypatch):
    calls = []

    def empty(doi):
        calls.append("openalex")
        return

    def semantic(doi):
        calls.append("semantic_scholar")
        return {"abstract": "Recovered abstract", "title": "Better title"}

    def should_not_run(doi):
        calls.append("openaire")
        return {"abstract": "Wrong abstract"}

    monkeypatch.setattr(doi_enrichment.openalex_client, "fetch_abstract", empty)
    monkeypatch.setitem(doi_enrichment.PROVIDERS, "semantic_scholar", semantic)
    monkeypatch.setitem(doi_enrichment.PROVIDERS, "openaire", should_not_run)
    monkeypatch.setattr(
        doi_enrichment.config,
        "ABSTRACT_FALLBACK_SOURCES",
        ("openalex", "semantic_scholar", "openaire"),
    )
    doi_enrichment.clear_cache()

    metadata = doi_enrichment.recover_abstract("https://doi.org/10.1000/XYZ")

    assert metadata["abstract"] == "Recovered abstract"
    assert metadata["metadata_sources"] == ["semantic_scholar"]
    assert calls == ["openalex", "semantic_scholar"]


def test_recover_abstract_caches_normalized_doi(monkeypatch):
    calls = []

    def semantic(doi):
        calls.append(doi)
        return {"abstract": "Recovered"}

    monkeypatch.setitem(doi_enrichment.PROVIDERS, "semantic_scholar", semantic)
    monkeypatch.setattr(
        doi_enrichment.config,
        "ABSTRACT_FALLBACK_SOURCES",
        ("semantic_scholar",),
    )
    doi_enrichment.clear_cache()

    doi_enrichment.recover_abstract("10.1000/XYZ")
    doi_enrichment.recover_abstract("https://doi.org/10.1000/xyz")

    assert calls == ["10.1000/xyz"]


def test_enrich_paper_merges_supplemental_fields_without_overwriting(monkeypatch):
    def unpaywall(doi):
        return {"oa_url": "https://example.org/paper.pdf", "title": "Replacement"}

    def opencitations(doi):
        return {"cited_by_count": 14, "references": ["10.1/a"]}

    monkeypatch.setitem(doi_enrichment.PROVIDERS, "unpaywall", unpaywall)
    monkeypatch.setitem(doi_enrichment.PROVIDERS, "opencitations", opencitations)
    monkeypatch.setattr(
        doi_enrichment.config,
        "DOI_ENRICHMENT_SOURCES",
        ("unpaywall", "opencitations"),
    )
    doi_enrichment.clear_cache()
    paper = {"doi": "10.1000/xyz", "title": "Original", "cited_by_count": 3}

    result = doi_enrichment.enrich_paper(paper)

    assert result is paper
    assert result["title"] == "Original"
    assert result["oa_url"] == "https://example.org/paper.pdf"
    assert result["cited_by_count"] == 14
    assert result["references"] == ["10.1/a"]
    assert result["metadata_sources"] == ["opencitations", "unpaywall"]


def test_enrichment_continues_after_provider_failure(monkeypatch):
    def broken(doi):
        raise RuntimeError("provider failed")

    def dblp(doi):
        return {"dblp_key": "conf/test/key"}

    monkeypatch.setitem(doi_enrichment.PROVIDERS, "unpaywall", broken)
    monkeypatch.setitem(doi_enrichment.PROVIDERS, "dblp", dblp)
    monkeypatch.setattr(
        doi_enrichment.config,
        "DOI_ENRICHMENT_SOURCES",
        ("unpaywall", "dblp"),
    )
    doi_enrichment.clear_cache()

    result = doi_enrichment.enrich_paper({"doi": "10.1000/xyz"})

    assert result["dblp_key"] == "conf/test/key"
    assert result["metadata_sources"] == ["dblp"]
