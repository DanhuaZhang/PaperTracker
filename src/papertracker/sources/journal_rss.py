"""RSS source for journals where reliable TOC feeds exist.

Complements CrossRef — RSS sometimes appears 1–2 days earlier than CrossRef deposit.
DOI-based canonical IDs unify duplicates with the CrossRef sources via dedup.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

import feedparser
import requests

from .. import config
from . import openalex_client
from ._filter import tag_venue

log = logging.getLogger(__name__)

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.I)


def fetch(
    start_date: dt.date,
    end_date: dt.date,
    profile: config.ProjectProfile | None = None,
) -> list[dict]:
    lo, hi = start_date.isoformat(), end_date.isoformat()
    out: list[dict] = []
    total_dropped_no_abstract = 0
    total_dropped_out_of_window = 0
    priority_venues = profile.priority_venues if profile else config.PRIORITY_VENUES
    for venue in priority_venues:
        rss_url = venue.get("rss")
        if not rss_url:
            continue
        try:
            entries = _fetch_feed(rss_url)
        except Exception as e:
            log.warning("RSS %s (%s): %s", venue["name"], rss_url, e)
            continue
        log.info("RSS[%s]: %d entries", venue["name"], len(entries))
        for entry in entries:
            paper = _to_paper(entry, venue)
            if paper is None:
                continue
            if paper["published"] and not (lo <= paper["published"] <= hi):
                total_dropped_out_of_window += 1
                continue
            if not paper["abstract"] and paper["doi"]:
                paper["abstract"] = openalex_client.fetch_abstract(paper["doi"]) or ""
            if not paper["abstract"]:
                total_dropped_no_abstract += 1
                continue
            paper["venue"] = tag_venue(paper["container_title"], priority_venues) or venue["name"]
            out.append(paper)
    log.info(
        "journal_rss: kept %d (dropped %d no-abstract, %d out of window) — pre-relevance",
        len(out), total_dropped_no_abstract, total_dropped_out_of_window,
    )
    return out


def _fetch_feed(url: str):
    # Pre-fetch with our User-Agent so the publisher's bot policy sees a clear identity.
    headers = {"User-Agent": config.USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    return parsed.entries or []


def _to_paper(entry, venue: dict) -> dict | None:
    title = (entry.get("title") or "").strip()
    if not title:
        return None

    # DOI hunt — check standard fields, then regex over identifiers/links/summary
    doi = None
    for field in ("prism_doi", "dc_identifier", "id"):
        val = entry.get(field)
        if isinstance(val, str):
            m = _DOI_RE.search(val.replace("doi:", ""))
            if m:
                doi = m.group(0)
                break
    if not doi:
        link = entry.get("link") or ""
        m = _DOI_RE.search(link)
        if m:
            doi = m.group(0)
    if not doi:
        summary = entry.get("summary") or ""
        m = _DOI_RE.search(summary)
        if m:
            doi = m.group(0)
    if not doi:
        return None
    doi = doi.rstrip(".,;)")

    abstract = ""
    summary = entry.get("summary") or ""
    if summary and len(summary.split()) > 20:        # heuristic: skip very short summaries
        abstract = re.sub(r"<[^>]+>", "", summary).strip()

    authors: list[str] = []
    authors_raw = entry.get("authors") or []
    for a in authors_raw:
        if isinstance(a, dict):
            name = a.get("name", "").strip()
        elif isinstance(a, str):
            name = a.strip()
        else:
            name = ""
        if name:
            authors.append(name)
    if not authors and entry.get("author"):
        authors = [s.strip() for s in str(entry["author"]).split(",") if s.strip()]

    published_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    published = ""
    if published_struct:
        published = dt.date(*published_struct[:3]).isoformat()

    return {
        "canonical_id": f"doi:{doi.lower()}",
        "source": "journal_rss",
        "venue": None,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "published": published,
        "url": entry.get("link") or f"https://doi.org/{doi}",
        "doi": doi,
        "container_title": venue["name"],
    }
