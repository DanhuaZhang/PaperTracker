"""arXiv Atom feed client. No auth required."""

from __future__ import annotations

import datetime as dt
import logging
import time
import xml.etree.ElementTree as ET

import requests

from .. import config

# arXiv asks clients to wait ≥3 s between page requests
_PAGE_SIZE = 100
_INTER_PAGE_DELAY_SEC = 3.0

log = logging.getLogger(__name__)

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_ENDPOINT = "https://export.arxiv.org/api/query"


def _build_query(start: dt.date, end: dt.date, categories: list[str] | None = None) -> str:
    cat_query = "+OR+".join(f"cat:{c}" for c in (categories or config.ARXIV_CATEGORIES))
    date_range = (
        f"submittedDate:[{start.strftime('%Y%m%d')}000000+TO+{end.strftime('%Y%m%d')}235959]"
    )
    return f"({cat_query})+AND+{date_range}"


def fetch(
    start_date: dt.date,
    end_date: dt.date,
    profile: config.ProjectProfile | None = None,
) -> list[dict]:
    """Fetch arXiv entries submitted in [start_date, end_date].

    Relevance filtering happens later, in cli.py.
    """
    q = _build_query(start_date, end_date, profile.arxiv_categories if profile else None)
    cap = config.MAX_RESULTS_PER_QUERY
    headers = {"User-Agent": config.USER_AGENT}

    all_papers: list[dict] = []
    start = 0
    while start < cap:
        page = min(_PAGE_SIZE, cap - start)
        # arXiv expects '+' literally inside search_query; requests would percent-encode it.
        url = (
            f"{_ENDPOINT}?search_query={q}"
            f"&start={start}&max_results={page}"
            f"&sortBy=submittedDate&sortOrder=descending"
        )
        log.info("arXiv: GET start=%d max=%d", start, page)
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        page_papers = _parse(resp.text)
        all_papers.extend(page_papers)
        if len(page_papers) < page:
            break  # short page = no more results
        start += page
        if start < cap:
            time.sleep(_INTER_PAGE_DELAY_SEC)

    log.info("arXiv: %d entries returned (cap=%d)", len(all_papers), cap)
    return all_papers


def _parse(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out: list[dict] = []
    for entry in root.findall("atom:entry", _NS):
        id_node = entry.find("atom:id", _NS)
        title_node = entry.find("atom:title", _NS)
        summary_node = entry.find("atom:summary", _NS)
        published_node = entry.find("atom:published", _NS)
        if id_node is None or title_node is None or summary_node is None:
            continue
        raw_id = (id_node.text or "").strip()
        # "http://arxiv.org/abs/2401.12345v2" -> "2401.12345"
        arxiv_id = raw_id.rsplit("/", 1)[-1]
        if "v" in arxiv_id:
            arxiv_id = arxiv_id.split("v")[0]
        authors = [
            (a.find("atom:name", _NS).text or "").strip()
            for a in entry.findall("atom:author", _NS)
            if a.find("atom:name", _NS) is not None
        ]
        # arXiv exposes an author-supplied DOI for the published version when known;
        # capturing it lets dedup merge the preprint with its IEEE/ACM record.
        doi_node = entry.find("arxiv:doi", _NS)
        doi = (doi_node.text or "").strip() if doi_node is not None else None
        out.append(
            {
                "canonical_id": f"arxiv:{arxiv_id}",
                "source": "arxiv",
                "venue": None,
                "title": (title_node.text or "").strip().replace("\n", " "),
                "abstract": (summary_node.text or "").strip(),
                "authors": authors,
                "published": (
                    (published_node.text or "")[:10] if published_node is not None else ""
                ),
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "doi": doi or None,
            }
        )
    return out
