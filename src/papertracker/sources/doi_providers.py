"""Normalized DOI metadata adapters for optional scholarly backup APIs."""

from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import quote

import requests

from .. import config

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_TIMEOUT = 20


def normalize_doi(raw: str) -> str:
    doi = (raw or "").strip().lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
            break
    return doi.strip()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(_TAG_RE.sub("", html.unescape(str(value))).split())


def _compact(provider: str, **values: Any) -> dict:
    result = {"provider": provider}
    for key, value in values.items():
        if value not in (None, "", [], {}):
            result[key] = value
    return result


def _get_json(
    provider: str,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
) -> Any | None:
    request_headers = {"User-Agent": config.USER_AGENT, **(headers or {})}
    try:
        response = requests.get(
            url,
            params=params or {},
            headers=request_headers,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        log.debug("%s DOI lookup failed: %s", provider, exc)
        return None


def _author_names(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    names: list[str] = []
    for value in values:
        if isinstance(value, str):
            name = _clean(value)
        elif isinstance(value, dict):
            name = _clean(
                value.get("name")
                or value.get("fullName")
                or value.get("text")
                or " ".join(
                    filter(
                        None,
                        [
                            value.get("given") or value.get("givenName"),
                            value.get("family") or value.get("familyName"),
                        ],
                    )
                )
            )
        else:
            name = ""
        if name:
            names.append(name)
    return names


def _first_text(values: Any) -> str:
    if isinstance(values, str):
        return _clean(values)
    if not isinstance(values, list):
        return ""
    for value in values:
        if isinstance(value, str):
            text = _clean(value)
        elif isinstance(value, dict):
            text = _clean(value.get("description") or value.get("text") or value.get("value"))
        else:
            text = ""
        if text:
            return text
    return ""


def semantic_scholar(doi: str) -> dict:
    doi = normalize_doi(doi)
    headers = {}
    if config.SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = config.SEMANTIC_SCHOLAR_API_KEY
    data = _get_json(
        "semantic_scholar",
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='/')}",
        params={"fields": ("title,abstract,authors,year,venue,citationCount,openAccessPdf")},
        headers=headers,
    )
    if not isinstance(data, dict):
        return {}
    oa = data.get("openAccessPdf") or {}
    return _compact(
        "semantic_scholar",
        title=_clean(data.get("title")),
        abstract=_clean(data.get("abstract")),
        authors=_author_names(data.get("authors")),
        published=str(data.get("year") or ""),
        container_title=_clean(data.get("venue")),
        cited_by_count=int(data.get("citationCount") or 0),
        oa_url=_clean(oa.get("url") if isinstance(oa, dict) else ""),
    )


def openaire(doi: str) -> dict:
    doi = normalize_doi(doi)
    data = _get_json(
        "openaire",
        "https://api.openaire.eu/graph/v3/research-products",
        params={"pid": doi, "pageSize": 1},
    )
    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        return {}
    item = results[0]
    authors = item.get("authors") or item.get("author") or []
    descriptions = item.get("descriptions") or item.get("description") or []
    return _compact(
        "openaire",
        title=_clean(item.get("mainTitle")),
        abstract=_first_text(descriptions),
        authors=_author_names(authors),
        published=_clean(item.get("publicationDate")),
    )


def core(doi: str) -> dict:
    doi = normalize_doi(doi)
    headers = {}
    if config.CORE_API_KEY:
        headers["Authorization"] = f"Bearer {config.CORE_API_KEY}"
    data = _get_json(
        "core",
        "https://api.core.ac.uk/v3/search/works",
        params={"q": f'doi:"{doi}"', "limit": 1},
        headers=headers,
    )
    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        return {}
    item = results[0]
    journals = item.get("journals") or []
    journal = journals[0] if journals else {}
    return _compact(
        "core",
        title=_clean(item.get("title")),
        abstract=_clean(item.get("abstract")),
        authors=_author_names(item.get("authors")),
        published=_clean(item.get("publishedDate") or item.get("yearPublished")),
        container_title=_clean(journal.get("title") if isinstance(journal, dict) else journal),
        oa_url=_clean(item.get("downloadUrl") or item.get("fullTextLink")),
    )


def europe_pmc(doi: str) -> dict:
    doi = normalize_doi(doi)
    data = _get_json(
        "europe_pmc",
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={
            "query": f'DOI:"{doi}"',
            "format": "json",
            "resultType": "core",
            "pageSize": 1,
        },
    )
    result_list = data.get("resultList", {}) if isinstance(data, dict) else {}
    results = result_list.get("result", []) if isinstance(result_list, dict) else []
    if not results:
        return {}
    item = results[0]
    author_list = item.get("authorList") or {}
    journal_info = item.get("journalInfo") or {}
    journal = journal_info.get("journal") or {}
    full_text = item.get("fullTextUrlList") or {}
    urls = full_text.get("fullTextUrl", []) if isinstance(full_text, dict) else []
    oa_url = ""
    if urls:
        first = urls[0]
        oa_url = first.get("url", "") if isinstance(first, dict) else first
    return _compact(
        "europe_pmc",
        title=_clean(item.get("title")),
        abstract=_clean(item.get("abstractText")),
        authors=_author_names(author_list.get("author", [])),
        published=_clean(item.get("firstPublicationDate") or item.get("pubYear")),
        container_title=_clean(journal.get("title") if isinstance(journal, dict) else journal),
        cited_by_count=int(item.get("citedByCount") or 0),
        oa_url=_clean(oa_url),
    )


def unpaywall(doi: str) -> dict:
    doi = normalize_doi(doi)
    params = {"email": config.USER_EMAIL} if config.USER_EMAIL else {}
    data = _get_json(
        "unpaywall",
        f"https://api.unpaywall.org/v2/{quote(doi, safe='/')}",
        params=params,
    )
    if not isinstance(data, dict):
        return {}
    location = data.get("best_oa_location") or {}
    return _compact(
        "unpaywall",
        oa_url=_clean(
            location.get("url_for_pdf") or location.get("url") if isinstance(location, dict) else ""
        ),
    )


def datacite(doi: str) -> dict:
    doi = normalize_doi(doi)
    data = _get_json(
        "datacite",
        f"https://api.datacite.org/dois/{quote(doi, safe='/')}",
    )
    record = data.get("data", {}) if isinstance(data, dict) else {}
    attrs = record.get("attributes", {}) if isinstance(record, dict) else {}
    if not attrs:
        return {}
    titles = attrs.get("titles") or []
    title = titles[0].get("title", "") if titles and isinstance(titles[0], dict) else ""
    abstract = ""
    for description in attrs.get("descriptions") or []:
        if description.get("descriptionType") == "Abstract":
            abstract = description.get("description") or ""
            break
    container = attrs.get("container") or {}
    return _compact(
        "datacite",
        title=_clean(title),
        abstract=_clean(abstract),
        authors=_author_names(attrs.get("creators")),
        published=str(attrs.get("publicationYear") or ""),
        container_title=_clean(container.get("title") if isinstance(container, dict) else ""),
        url=_clean(attrs.get("url")),
    )


def _dois_from_pid_text(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else [raw]
    dois: list[str] = []
    for value in values:
        dois.extend(re.findall(r"(?:^|\s)doi:([^\s;]+)", str(value or ""), re.I))
    return [normalize_doi(doi) for doi in dois]


def opencitations(doi: str) -> dict:
    doi = normalize_doi(doi)
    headers = {}
    if config.OPENCITATIONS_ACCESS_TOKEN:
        headers["authorization"] = config.OPENCITATIONS_ACCESS_TOKEN
    base_url = "https://api.opencitations.net/index/v2"
    encoded_id = f"doi:{quote(doi, safe='/')}"
    count_data = _get_json(
        "opencitations",
        f"{base_url}/citation-count/{encoded_id}",
        headers=headers,
    )
    citation_data = _get_json(
        "opencitations",
        f"{base_url}/citations/{encoded_id}",
        headers=headers,
    )
    reference_data = _get_json(
        "opencitations",
        f"{base_url}/references/{encoded_id}",
        headers=headers,
    )
    if not any(isinstance(data, list) for data in (count_data, citation_data, reference_data)):
        return {}
    count = 0
    if isinstance(count_data, list) and count_data:
        count = int(count_data[0].get("count") or 0)
    citations = []
    if isinstance(citation_data, list):
        citations = _dois_from_pid_text([item.get("citing") for item in citation_data])
    references = []
    if isinstance(reference_data, list):
        references = _dois_from_pid_text([item.get("cited") for item in reference_data])
    return _compact(
        "opencitations",
        cited_by_count=count,
        citations=sorted(set(citations)),
        references=sorted(set(references)),
    )


def dblp(doi: str) -> dict:
    doi = normalize_doi(doi)
    escaped_doi = doi.replace("\\", "\\\\").replace('"', '\\"')
    query = f"""
PREFIX dblp: <https://dblp.org/rdf/schema#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?publ ?title ?year ?venue
       (GROUP_CONCAT(DISTINCT ?authorName; separator="; ") AS ?authors)
WHERE {{
  ?publ dblp:doi ?doi ; dblp:title ?title .
  FILTER(LCASE(STR(?doi)) = "https://doi.org/{escaped_doi}")
  OPTIONAL {{ ?publ dblp:yearOfPublication ?year . }}
  OPTIONAL {{ ?publ dblp:publishedIn ?venue . }}
  OPTIONAL {{
    ?publ dblp:authoredBy ?author .
    ?author rdfs:label ?authorName .
  }}
}}
GROUP BY ?publ ?title ?year ?venue
LIMIT 1
""".strip()
    data = _get_json(
        "dblp",
        "https://sparql.dblp.org/sparql",
        params={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )
    results = data.get("results", {}) if isinstance(data, dict) else {}
    bindings = results.get("bindings", []) if isinstance(results, dict) else []
    if not bindings:
        return {}
    binding = bindings[0]

    def value(name: str) -> str:
        field = binding.get(name) or {}
        return _clean(field.get("value") if isinstance(field, dict) else field)

    record_url = value("publ")
    return _compact(
        "dblp",
        title=value("title"),
        authors=[name.strip() for name in value("authors").split(";") if name.strip()],
        published=value("year"),
        container_title=value("venue"),
        url=record_url,
        dblp_key=record_url.removeprefix("https://dblp.org/rec/"),
    )
