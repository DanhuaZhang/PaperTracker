"""OpenAlex client.

OpenAlex stores abstracts as `abstract_inverted_index` mapping word -> [positions].
We reconstruct the abstract by placing each word at every position and joining.
"""
from __future__ import annotations

import logging
import time

import requests

from .. import config
from ._filter import tag_venue

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.openalex.org/works"
_PAGE_SIZE = 100
_SEMANTIC_PAGE_SIZE = 50
_INTER_PAGE_DELAY_SEC = 1.0
_MAX_RETRIES = 3
_BACKOFF_BASE_SEC = 2.0
_SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "display_name",
        "title",
        "publication_year",
        "publication_date",
        "cited_by_count",
        "authorships",
        "primary_location",
        "abstract_inverted_index",
        "relevance_score",
    ]
)


def fetch_abstract(doi: str) -> str | None:
    if not doi:
        return None
    url = f"{_ENDPOINT}/https://doi.org/{doi}"
    data = _get_json(url, {}, timeout=15, log_label=doi)
    if data is None:
        return None

    inv = data.get("abstract_inverted_index")
    if not inv:
        return None
    return _reconstruct_abstract(inv)


def fetch_related_work(profile: config.ProjectProfile, cap: int) -> list[dict]:
    """Return broad, citation-aware related work for a project topic.

    This is intentionally separate from the daily date-window sources: it searches
    all years and keeps citation metadata so ranking can surface older canonical
    papers.
    """
    cap = max(1, cap)
    batches = [
        (
            "semantic",
            {"search.semantic": profile.topic_statement[:2000]},
            min(cap, _SEMANTIC_PAGE_SIZE),
        ),
        (
            "citation",
            {
                "search": profile.crossref_query_hint,
                "sort": "cited_by_count:desc",
            },
            cap,
        ),
    ]

    merged: dict[str, dict] = {}
    for discovery_source, params, limit in batches:
        for work in _fetch_works(params, limit, discovery_source):
            paper = _normalize_work(work, discovery_source, profile)
            if paper is None:
                continue
            _merge_paper(merged, paper)
    return list(merged.values())


def fetch_related_work_faceted(
    profile: config.ProjectProfile,
    facets: list,
    candidates_per_facet: int,
) -> list[dict]:
    """Return OpenAlex related-work candidates discovered per facet."""
    candidates_per_facet = max(1, candidates_per_facet)
    merged: dict[str, dict] = {}
    for facet in facets:
        semantic_query = f"{profile.topic_statement.strip()} {facet.name} {facet.description}"[:2000]
        batches = [
            (
                "semantic",
                {"search.semantic": semantic_query},
                min(candidates_per_facet, _SEMANTIC_PAGE_SIZE),
            ),
            (
                "citation",
                {
                    "search": facet.query_hint or profile.crossref_query_hint,
                    "sort": "cited_by_count:desc",
                },
                candidates_per_facet,
            ),
        ]
        for discovery_source, params, limit in batches:
            label = f"{facet.id}:{discovery_source}"
            for work in _fetch_works(params, limit, label):
                paper = _normalize_work(
                    work,
                    discovery_source,
                    profile,
                    facet_id=facet.id,
                )
                if paper is None:
                    continue
                _merge_paper(merged, paper)
    return list(merged.values())


def _auth_params(params: dict) -> dict:
    out = dict(params)
    if config.USER_EMAIL:
        out["mailto"] = config.USER_EMAIL
    if config.OPENALEX_API_KEY:
        out["api_key"] = config.OPENALEX_API_KEY
    return out


def _get_json(
    url: str,
    params: dict,
    timeout: int,
    log_label: str,
) -> dict | None:
    request_params = _auth_params(params)
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(
                url,
                params=request_params,
                headers={"User-Agent": config.USER_AGENT},
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code not in (429, 503):
                log.debug("OpenAlex %s -> %d", log_label, resp.status_code)
                return None
            if attempt == _MAX_RETRIES - 1:
                log.warning(
                    "OpenAlex %s -> %d after %d attempts; giving up",
                    log_label, resp.status_code, _MAX_RETRIES,
                )
                return None
            retry_after = resp.headers.get("Retry-After", "")
            wait = float(retry_after) if retry_after.isdigit() else _BACKOFF_BASE_SEC * (2 ** attempt)
            log.warning(
                "OpenAlex %s -> %d; backing off %.1fs (attempt %d/%d)",
                log_label, resp.status_code, wait, attempt + 1, _MAX_RETRIES,
            )
            time.sleep(wait)
        except (requests.RequestException, ValueError) as e:
            log.debug("OpenAlex error for %s: %s", log_label, e)
            return None
    return None


def _fetch_works(params: dict, limit: int, discovery_source: str) -> list[dict]:
    out: list[dict] = []
    page = 1
    semantic = "search.semantic" in params
    page_cap = _SEMANTIC_PAGE_SIZE if semantic else _PAGE_SIZE
    while len(out) < limit:
        per_page = min(page_cap, limit - len(out))
        page_params = {
            **params,
            "per_page": str(per_page),
            "page": str(page),
            "select": _SELECT_FIELDS,
        }
        data = _get_json(
            _ENDPOINT,
            page_params,
            timeout=30,
            log_label=f"{discovery_source} page={page}",
        )
        if data is None:
            break
        results = data.get("results", []) or []
        out.extend(results)
        if len(results) < per_page:
            break
        page += 1
        if len(out) < limit:
            time.sleep(_INTER_PAGE_DELAY_SEC)
    log.info("OpenAlex[%s]: %d works returned", discovery_source, len(out))
    return out


def _normalize_work(
    work: dict,
    discovery_source: str,
    profile: config.ProjectProfile,
    facet_id: str | None = None,
) -> dict | None:
    title = (work.get("display_name") or work.get("title") or "").strip()
    openalex_id = (work.get("id") or "").strip()
    if not title or not openalex_id:
        return None

    doi = _normalize_doi(work.get("doi") or "")
    openalex_key = openalex_id.rstrip("/").rsplit("/", 1)[-1].lower()
    canonical_id = f"doi:{doi}" if doi else f"openalex:{openalex_key}"

    inv = work.get("abstract_inverted_index") or {}
    abstract = _reconstruct_abstract(inv) if inv else ""
    authors = _authors(work.get("authorships") or [])
    container_title = _container_title(work.get("primary_location") or {})
    published = work.get("publication_date") or str(work.get("publication_year") or "")
    url = f"https://doi.org/{doi}" if doi else openalex_id

    paper = {
        "canonical_id": canonical_id,
        "source": "openalex",
        "venue": tag_venue(container_title, profile.priority_venues),
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "published": published,
        "url": url,
        "doi": doi,
        "container_title": container_title,
        "openalex_id": openalex_id,
        "cited_by_count": int(work.get("cited_by_count") or 0),
        "openalex_relevance_score": work.get("relevance_score"),
        "discovery_sources": [discovery_source],
    }
    if facet_id:
        paper["facet_hits"] = {facet_id: [discovery_source]}
    return paper


def _normalize_doi(raw: str) -> str:
    doi = raw.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            return doi[len(prefix):]
    return doi


def _authors(authorships: list[dict]) -> list[str]:
    names: list[str] = []
    for authorship in authorships:
        author = authorship.get("author") or {}
        name = (author.get("display_name") or "").strip()
        if name:
            names.append(name)
    return names


def _container_title(primary_location: dict) -> str | None:
    source = primary_location.get("source") or {}
    title = (source.get("display_name") or "").strip()
    return title or None


def _merge_paper(merged: dict[str, dict], paper: dict) -> None:
    cid = paper["canonical_id"]
    existing = merged.get(cid)
    if existing is None:
        merged[cid] = paper
        return

    sources = {
        *(existing.get("discovery_sources") or []),
        *(paper.get("discovery_sources") or []),
    }
    existing["discovery_sources"] = sorted(sources)
    existing["facet_hits"] = _merge_facet_hits(
        existing.get("facet_hits") or {},
        paper.get("facet_hits") or {},
    )
    existing["cited_by_count"] = max(
        int(existing.get("cited_by_count") or 0),
        int(paper.get("cited_by_count") or 0),
    )
    if len(paper.get("abstract") or "") > len(existing.get("abstract") or ""):
        existing["abstract"] = paper.get("abstract") or ""
    for key in ("venue", "container_title", "doi", "url", "published", "openalex_id"):
        existing[key] = existing.get(key) or paper.get(key)


def _merge_facet_hits(left: dict, right: dict) -> dict[str, list[str]]:
    merged: dict[str, set[str]] = {}
    for source in (left, right):
        for facet_id, hits in source.items():
            values = hits if isinstance(hits, list) else [hits]
            merged.setdefault(str(facet_id), set()).update(str(v) for v in values if v)
    return {facet_id: sorted(values) for facet_id, values in merged.items()}


def _reconstruct_abstract(inv: dict) -> str:
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda t: t[0])
    return " ".join(w for _, w in positions)
