"""Cross-source deduplication via canonical IDs (DOI when available, else source-prefixed)."""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_SOURCE_RANK = {"acm": 3, "ieee": 3, "journal_rss": 2, "arxiv": 1}

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
# Title-only matching is risky for very short/generic titles, so require this many
# alphanumeric characters before we'll merge two papers on title alone.
_MIN_TITLE_CHARS = 15


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        with path.open() as f:
            data = json.load(f)
        return set(data.keys())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Could not read %s: %s — treating as empty", path, e)
        return set()


def save_seen(path: Path, new_ids: set[str]) -> None:
    existing: dict[str, str] = {}
    if path.exists():
        try:
            with path.open() as f:
                existing = json.load(f)
        except (OSError, json.JSONDecodeError):
            existing = {}
    today = dt.date.today().isoformat()
    for cid in new_ids:
        existing[cid] = today
    with path.open("w") as f:
        json.dump(existing, f, indent=2, sort_keys=True)


def deduplicate_across_sources(papers: list[dict]) -> list[dict]:
    """Merge duplicates by canonical_id, then collapse the *same work* appearing under
    different ids across sources (e.g. an arXiv preprint and its published IEEE/ACM
    record). Every returned paper carries a ``merged_ids`` list of all collapsed ids."""
    bucket: dict[str, dict] = {}
    for p in papers:
        cid = p["canonical_id"]
        if cid not in bucket:
            bucket[cid] = p
            continue
        existing = bucket[cid]
        # Pick the better record
        existing_score = (
            len(existing.get("abstract") or ""),
            _SOURCE_RANK.get(existing.get("source"), 0),
        )
        new_score = (
            len(p.get("abstract") or ""),
            _SOURCE_RANK.get(p.get("source"), 0),
        )
        keep = p if new_score > existing_score else existing
        # Merge venue tag if either had one
        keep["venue"] = keep.get("venue") or existing.get("venue") or p.get("venue")
        bucket[cid] = keep
    return _merge_same_work(list(bucket.values()))


def _norm_title(title: str) -> str:
    return _NON_ALNUM_RE.sub(" ", (title or "").lower()).strip()


def _surname(authors: list[str]) -> str:
    """Best-effort surname of the first author (last alphanumeric token)."""
    if not authors:
        return ""
    tokens = _NON_ALNUM_RE.sub(" ", authors[0].lower()).split()
    return tokens[-1] if tokens else ""


def _content_key(paper: dict) -> str | None:
    """A cross-source identity key: DOI when present, else normalized title + first-author
    surname. Returns None when no reliable key exists (paper is never merged)."""
    doi = (paper.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    nt = _norm_title(paper.get("title", ""))
    if len(nt.replace(" ", "")) >= _MIN_TITLE_CHARS:
        return f"title:{nt}|{_surname(paper.get('authors') or [])}"
    return None


def _merge_rank(p: dict) -> tuple[int, int, int]:
    """Prefer the published record (has venue/container) over a bare preprint,
    then the longest abstract, then the highest-ranked source."""
    has_venue = 1 if (p.get("venue") or p.get("container_title")) else 0
    return (has_venue, len(p.get("abstract") or ""), _SOURCE_RANK.get(p.get("source"), 0))


def _merge_same_work(papers: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    out: list[dict] = []
    for p in papers:
        key = _content_key(p)
        if key is None:
            p["merged_ids"] = [p["canonical_id"]]
            out.append(p)
        else:
            groups.setdefault(key, []).append(p)

    for group in groups.values():
        rep = max(group, key=_merge_rank)
        merged_ids = [q["canonical_id"] for q in group]
        venue = rep.get("venue")
        container = rep.get("container_title")
        for q in group:
            venue = venue or q.get("venue")
            container = container or q.get("container_title")
        rep["merged_ids"] = merged_ids
        rep["venue"] = venue
        if container:
            rep["container_title"] = container
        if len(group) > 1:
            log.info(
                "Merged %d records as one work: %s", len(group), ", ".join(merged_ids),
            )
        out.append(rep)
    return out
