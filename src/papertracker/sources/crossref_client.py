"""CrossRef Works API — used by both IEEE and ACM source modules.

CrossRef is the canonical DOI registry. IEEE and ACM (and most other publishers)
deposit metadata for every paper on publication. No auth required; we identify
ourselves to the "polite pool" via User-Agent + mailto.
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import re
import time

import requests

from .. import config
from . import openalex_client
from ._filter import tag_venue

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.crossref.org/works"
_PAGE_SIZE = 100
_INTER_PAGE_DELAY_SEC = 0.5     # CrossRef polite pool has no required delay; this is conservative

# Retry/backoff for transient rate-limiting. CrossRef returns 429 (and occasionally 503)
# under load, especially in the anonymous pool; it usually sends a Retry-After header.
_MAX_RETRIES = 4
_BACKOFF_BASE_SEC = 2.0

# CrossRef abstracts come back as JATS-flavored XML embedded in JSON; strip tags.
_TAG_RE = re.compile(r"<[^>]+>")


def search(
    member_id: int,
    source_label: str,
    start_date: dt.date,
    end_date: dt.date,
) -> list[dict]:
    """Query CrossRef for papers from one publisher (by member ID) in [start_date, end_date].

    Returns papers with abstracts (CrossRef-provided or OpenAlex-recovered),
    topic-filtered, optionally venue-filtered.
    """
    cap = config.MAX_RESULTS_PER_QUERY
    filter_str = (
        f"member:{member_id},"
        f"from-pub-date:{start_date.isoformat()},"
        f"until-pub-date:{end_date.isoformat()}"
    )

    items = _fetch_all_items(filter_str, cap, source_label)
    if items is None:
        return []

    out: list[dict] = []
    dropped_no_abstract = 0
    dropped_not_priority_venue = 0
    for item in items:
        paper = _normalize(item, source_label)
        if paper is None:
            continue
        # Recover abstract via OpenAlex if missing
        if not paper["abstract"] and paper["doi"]:
            recovered = openalex_client.fetch_abstract(paper["doi"])
            if recovered:
                paper["abstract"] = recovered
        if not paper["abstract"]:
            dropped_no_abstract += 1
            continue
        paper["venue"] = tag_venue(paper["container_title"])
        if config.PRIORITY_VENUE_ONLY and paper["venue"] is None:
            dropped_not_priority_venue += 1
            continue
        out.append(paper)

    log.info(
        "CrossRef[%s]: kept %d (dropped %d no-abstract%s) — pre-relevance",
        source_label, len(out), dropped_no_abstract,
        f", {dropped_not_priority_venue} not priority venue" if dropped_not_priority_venue else "",
    )
    return out


def _get_with_retry(params: dict, headers: dict, source_label: str, offset: int) -> dict:
    """GET one CrossRef page, retrying on 429/503 with backoff (honoring Retry-After).

    Raises requests.HTTPError if all retries are exhausted; the caller turns that into
    a partial/empty result.
    """
    resp = None
    for attempt in range(_MAX_RETRIES):
        resp = requests.get(_ENDPOINT, params=params, headers=headers, timeout=30)
        if resp.status_code not in (429, 503):
            resp.raise_for_status()
            return resp.json()
        retry_after = resp.headers.get("Retry-After", "")
        wait = float(retry_after) if retry_after.isdigit() else _BACKOFF_BASE_SEC * (2 ** attempt)
        log.warning(
            "CrossRef[%s] %d at offset=%d — backing off %.1fs (attempt %d/%d)",
            source_label, resp.status_code, offset, wait, attempt + 1, _MAX_RETRIES,
        )
        time.sleep(wait)
    # Retries exhausted — raise the last response's error for the caller to handle.
    resp.raise_for_status()
    raise requests.HTTPError(f"CrossRef[{source_label}] gave up after {_MAX_RETRIES} retries")


def _fetch_all_items(filter_str: str, cap: int, source_label: str) -> list[dict] | None:
    """Paginate CrossRef up to `cap` results. Returns None on hard error."""
    headers = {"User-Agent": config.USER_AGENT}
    items: list[dict] = []
    offset = 0
    total_results: int | None = None
    while offset < cap:
        page = min(_PAGE_SIZE, cap - offset)
        params = {
            "filter": filter_str,
            "query": config.CROSSREF_QUERY_HINT,
            "rows": str(page),
            "offset": str(offset),
            "select": "DOI,title,abstract,author,published,issued,container-title,publisher,URL",
        }
        if config.USER_EMAIL:
            params["mailto"] = config.USER_EMAIL
        log.info(
            "CrossRef[%s]: GET offset=%d rows=%d filter=%s",
            source_label, offset, page, filter_str,
        )
        try:
            data = _get_with_retry(params, headers, source_label, offset)
        except (requests.RequestException, ValueError) as e:
            log.error("CrossRef[%s] failed (offset=%d): %s", source_label, offset, e)
            return None if not items else items

        msg = data.get("message", {})
        page_items = msg.get("items", []) or []
        items.extend(page_items)
        if total_results is None:
            total_results = msg.get("total-results")
            if total_results is not None:
                log.info("CrossRef[%s]: total-results=%d", source_label, total_results)
        if len(page_items) < page:
            break  # exhausted
        if total_results is not None and offset + len(page_items) >= total_results:
            break
        offset += page
        if offset < cap:
            time.sleep(_INTER_PAGE_DELAY_SEC)
    if total_results is not None and total_results > cap:
        log.warning(
            "CrossRef[%s]: capped at %d of %d total — raise MAX_RESULTS_PER_QUERY to see more",
            source_label, cap, total_results,
        )
    return items


def _strip_html(text: str) -> str:
    if not text:
        return ""
    cleaned = _TAG_RE.sub("", html.unescape(text))
    # Collapse runs of whitespace (CrossRef titles often contain raw newlines)
    return " ".join(cleaned.split())


def _normalize(item: dict, source: str) -> dict | None:
    doi = item.get("DOI")
    title_list = item.get("title") or []
    if not title_list or not doi:
        return None
    title = _strip_html(title_list[0])

    abstract = _strip_html(item.get("abstract") or "")

    authors_raw = item.get("author") or []
    authors: list[str] = []
    for a in authors_raw:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        full = (f"{given} {family}").strip() if (given or family) else (a.get("name") or "").strip()
        if full:
            authors.append(full)

    published = _extract_date(item.get("published") or item.get("issued"))

    container_titles = item.get("container-title") or []
    container_title = container_titles[0] if container_titles else None

    url = item.get("URL") or f"https://doi.org/{doi}"

    return {
        "canonical_id": f"doi:{doi.lower()}",
        "source": source,
        "venue": None,                       # filled by caller
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "published": published,
        "url": url,
        "doi": doi,
        "container_title": container_title,
    }


def _extract_date(d: dict | None) -> str:
    if not d:
        return ""
    parts = d.get("date-parts") or []
    if not parts or not parts[0]:
        return ""
    p = parts[0]
    y = p[0] if len(p) >= 1 else None
    m = p[1] if len(p) >= 2 else 1
    day = p[2] if len(p) >= 3 else 1
    if y is None:
        return ""
    try:
        return dt.date(int(y), int(m), int(day)).isoformat()
    except (TypeError, ValueError):
        return str(y)
