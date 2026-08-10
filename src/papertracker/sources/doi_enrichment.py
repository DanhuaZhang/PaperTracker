"""Cached DOI abstract fallback and supplemental metadata enrichment."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from .. import config
from . import doi_providers, openalex_client

log = logging.getLogger(__name__)

Provider = Callable[[str], dict]

PROVIDERS: dict[str, Provider] = {
    "semantic_scholar": doi_providers.semantic_scholar,
    "openaire": doi_providers.openaire,
    "core": doi_providers.core,
    "europe_pmc": doi_providers.europe_pmc,
    "unpaywall": doi_providers.unpaywall,
    "datacite": doi_providers.datacite,
    "opencitations": doi_providers.opencitations,
    "dblp": doi_providers.dblp,
}

_cache: dict[tuple[str, str], dict] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _provider_metadata(provider_name: str, doi: str) -> dict:
    key = (provider_name, doi)
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return dict(cached)

    try:
        if provider_name == "openalex":
            abstract = openalex_client.fetch_abstract(doi)
            metadata = {"provider": "openalex", "abstract": abstract} if abstract else {}
        else:
            provider = PROVIDERS.get(provider_name)
            if provider is None:
                log.warning("Unknown DOI metadata provider %r; skipping", provider_name)
                metadata = {}
            else:
                metadata = provider(doi) or {}
    except Exception as exc:  # noqa: BLE001 — one provider must not break the chain
        log.warning("DOI provider %s failed for %s: %s", provider_name, doi, exc)
        metadata = {}

    with _cache_lock:
        _cache[key] = dict(metadata)
    return metadata


def recover_abstract(raw_doi: str) -> dict:
    doi = doi_providers.normalize_doi(raw_doi)
    if not doi:
        return {}
    for provider_name in config.ABSTRACT_FALLBACK_SOURCES:
        metadata = _provider_metadata(provider_name, doi)
        if metadata.get("abstract"):
            result = dict(metadata)
            result["metadata_sources"] = [provider_name]
            return result
    return {}


def enrich_paper(paper: dict) -> dict:
    doi = doi_providers.normalize_doi(paper.get("doi") or "")
    if not doi:
        return paper

    sources = set(paper.get("metadata_sources") or [])
    for provider_name in config.DOI_ENRICHMENT_SOURCES:
        metadata = _provider_metadata(provider_name, doi)
        if not metadata:
            continue
        sources.add(provider_name)
        merge_metadata(paper, metadata)
    if sources:
        paper["metadata_sources"] = sorted(sources)
    return paper


def merge_metadata(paper: dict, metadata: dict) -> None:
    for field in (
        "title",
        "abstract",
        "authors",
        "published",
        "container_title",
        "url",
        "oa_url",
        "dblp_key",
    ):
        if not paper.get(field) and metadata.get(field):
            paper[field] = metadata[field]

    if metadata.get("cited_by_count") is not None:
        paper["cited_by_count"] = max(
            int(paper.get("cited_by_count") or 0),
            int(metadata.get("cited_by_count") or 0),
        )
    for field in ("citations", "references"):
        if metadata.get(field):
            paper[field] = sorted({*paper.get(field, []), *metadata[field]})
    sources = {
        *paper.get("metadata_sources", []),
        *metadata.get("metadata_sources", []),
    }
    if metadata.get("provider"):
        sources.add(metadata["provider"])
    if sources:
        paper["metadata_sources"] = sorted(sources)
