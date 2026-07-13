"""Persistent cache of generated summaries, keyed by paper and template ID.

Avoids re-spending LLM tokens on papers already summarized in a previous run
(including ``--ignore-seen`` backfills, where seen-filtering is disabled but the
summary text is still reusable). Mirrors the JSON load/save pattern in ``dedup.py``.

Schema::

    {"arxiv:2401.12345::triage": {"summary": "- ...", "model": "sonnet",
                                   "provider": "claude", "template": "triage",
                                   "generated": "2026-05-23"}}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Could not read %s: %s — treating as empty", path, e)
        return {}


def cache_key(canonical_id: str, template_id: str) -> str:
    return f"{canonical_id}::{template_id}"


def lookup(cache: dict[str, dict], paper: dict, template_id: str) -> str | None:
    """Return a cached summary if this paper — under its canonical_id or any of its
    cross-source merged_ids, for the given template — has one. None means it must be
    (re)generated."""
    for cid in paper.get("merged_ids", [paper["canonical_id"]]):
        entry = cache.get(cache_key(cid, template_id))
        if entry and entry.get("summary"):
            return entry["summary"]
    return None


def save(path: Path, new_entries: dict[str, dict]) -> None:
    """Merge ``new_entries`` into the on-disk cache and write it back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load(path)
    existing.update(new_entries)
    with path.open("w") as f:
        json.dump(existing, f, indent=2, sort_keys=True)
