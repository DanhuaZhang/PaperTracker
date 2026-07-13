from papertracker.sources import doi_providers


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


def _capture(monkeypatch, payload):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(payload)

    monkeypatch.setattr(doi_providers.requests, "get", fake_get)
    return calls


def test_semantic_scholar_looks_up_doi_and_normalizes_metadata(monkeypatch):
    calls = _capture(
        monkeypatch,
        {
            "title": "Paper",
            "abstract": "Semantic abstract",
            "authors": [{"name": "Ada Lovelace"}],
            "year": 2025,
            "venue": "CHI",
            "citationCount": 12,
            "openAccessPdf": {"url": "https://example.org/paper.pdf"},
        },
    )

    result = doi_providers.semantic_scholar("HTTPS://DOI.ORG/10.1000/XYZ")

    assert calls[0][0].endswith("/paper/DOI:10.1000/xyz")
    assert result == {
        "provider": "semantic_scholar",
        "title": "Paper",
        "abstract": "Semantic abstract",
        "authors": ["Ada Lovelace"],
        "published": "2025",
        "container_title": "CHI",
        "cited_by_count": 12,
        "oa_url": "https://example.org/paper.pdf",
    }


def test_openaire_uses_pid_filter_and_extracts_description(monkeypatch):
    calls = _capture(
        monkeypatch,
        {
            "results": [
                {
                    "mainTitle": "Paper",
                    "descriptions": ["Repository abstract"],
                    "authors": [{"fullName": "Grace Hopper"}],
                    "publicationDate": "2024-02-03",
                }
            ]
        },
    )

    result = doi_providers.openaire("10.1000/xyz")

    assert calls[0][1]["params"] == {"pid": "10.1000/xyz", "pageSize": 1}
    assert result["abstract"] == "Repository abstract"
    assert result["authors"] == ["Grace Hopper"]


def test_core_extracts_repository_metadata(monkeypatch):
    calls = _capture(
        monkeypatch,
        {
            "results": [
                {
                    "title": "Paper",
                    "abstract": "CORE abstract",
                    "authors": [{"name": "Barbara Liskov"}],
                    "publishedDate": "2023-01-02",
                    "downloadUrl": "https://example.org/core.pdf",
                }
            ]
        },
    )

    result = doi_providers.core("10.1000/xyz")

    assert calls[0][1]["params"] == {"q": 'doi:"10.1000/xyz"', "limit": 1}
    assert result["abstract"] == "CORE abstract"
    assert result["oa_url"] == "https://example.org/core.pdf"


def test_europe_pmc_extracts_core_result(monkeypatch):
    calls = _capture(
        monkeypatch,
        {
            "resultList": {
                "result": [
                    {
                        "title": "Paper",
                        "abstractText": "Europe PMC abstract",
                        "authorList": {"author": [{"fullName": "Edsger Dijkstra"}]},
                        "firstPublicationDate": "2022-04-05",
                        "journalInfo": {"journal": {"title": "Nature"}},
                        "citedByCount": 9,
                    }
                ]
            }
        },
    )

    result = doi_providers.europe_pmc("10.1000/xyz")

    assert calls[0][1]["params"]["query"] == 'DOI:"10.1000/xyz"'
    assert result["abstract"] == "Europe PMC abstract"
    assert result["container_title"] == "Nature"


def test_unpaywall_extracts_best_open_access_location(monkeypatch):
    monkeypatch.setattr(doi_providers.config, "USER_EMAIL", "research@example.com")
    calls = _capture(
        monkeypatch,
        {"best_oa_location": {"url_for_pdf": "https://example.org/oa.pdf"}},
    )

    result = doi_providers.unpaywall("10.1000/xyz")

    assert calls[0][1]["params"] == {"email": "research@example.com"}
    assert result == {
        "provider": "unpaywall",
        "oa_url": "https://example.org/oa.pdf",
    }


def test_datacite_extracts_registered_metadata(monkeypatch):
    _capture(
        monkeypatch,
        {
            "data": {
                "attributes": {
                    "titles": [{"title": "Dataset paper"}],
                    "descriptions": [
                        {"descriptionType": "Abstract", "description": "DataCite abstract"}
                    ],
                    "creators": [{"name": "Margaret Hamilton"}],
                    "publicationYear": 2021,
                    "container": {"title": "Repository"},
                    "url": "https://example.org/item",
                }
            }
        },
    )

    result = doi_providers.datacite("10.1000/xyz")

    assert result["abstract"] == "DataCite abstract"
    assert result["container_title"] == "Repository"


def test_opencitations_extracts_citation_edges(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if "/citation-count/" in url:
            return _Response([{"count": "7"}])
        if "/citations/" in url:
            return _Response(
                [
                    {"citing": "omid:br/1 doi:10.1/a pmid:1"},
                    {"citing": "omid:br/2 doi:10.2/b"},
                ]
            )
        if "/references/" in url:
            return _Response([{"cited": "omid:br/3 doi:10.3/c"}])
        raise AssertionError(url)

    monkeypatch.setattr(doi_providers.requests, "get", fake_get)

    result = doi_providers.opencitations("10.1000/xyz")

    assert len(calls) == 3
    assert result["cited_by_count"] == 7
    assert result["citations"] == ["10.1/a", "10.2/b"]
    assert result["references"] == ["10.3/c"]


def test_dblp_extracts_computer_science_metadata(monkeypatch):
    calls = _capture(
        monkeypatch,
        {
            "results": {
                "bindings": [
                    {
                        "publ": {"value": "https://dblp.org/rec/conf/uist/Allen20"},
                        "title": {"value": "Paper"},
                        "authors": {"value": "Frances Allen"},
                        "year": {"value": "2020"},
                        "venue": {"value": "UIST"},
                    }
                ]
            }
        },
    )

    result = doi_providers.dblp("10.1000/xyz")

    assert calls[0][0] == "https://sparql.dblp.org/sparql"
    assert "10.1000/xyz" in calls[0][1]["params"]["query"]
    assert calls[0][1]["headers"]["Accept"] == "application/sparql-results+json"
    assert result["authors"] == ["Frances Allen"]
    assert result["dblp_key"] == "conf/uist/Allen20"


def test_provider_http_failure_returns_empty_metadata(monkeypatch):
    def fail(*args, **kwargs):
        raise doi_providers.requests.RequestException("offline")

    monkeypatch.setattr(doi_providers.requests, "get", fail)

    assert doi_providers.semantic_scholar("10.1000/xyz") == {}
