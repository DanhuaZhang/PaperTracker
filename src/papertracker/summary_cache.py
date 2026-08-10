"""Persistent v2 summary cache with content-derived identities."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from . import summary_templates

log = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = 2


def load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read %s: %s — treating as empty", path, exc)
        return {}
    return value if isinstance(value, dict) else {}


def fingerprint(
    paper: dict,
    template: summary_templates.SummaryTemplate,
    provider: str,
    model: str,
    *,
    profile=None,
    pdf_path: Path | None = None,
    pipeline_version: str,
) -> str:
    """Hash every input that can materially change a generated summary."""
    if template.evidence == "abstract":
        evidence = {
            "type": "abstract",
            "content": paper.get("abstract") or "",
        }
    else:
        selected_pdf = pdf_path or paper.get("pdf_path")
        if selected_pdf is None:
            # Keep this function independent of the summarizer exception hierarchy.
            raise OSError("full-text cache identity requires a local PDF")
        evidence = {
            "type": "fulltext",
            "pdf_sha256": _sha256_file(Path(selected_pdf)),
        }

    project = None
    if profile is not None:
        project = {
            "name": getattr(profile, "name", ""),
            "topic_statement": getattr(profile, "topic_statement", ""),
        }
    payload = {
        "cache_schema": CACHE_SCHEMA_VERSION,
        "pipeline_version": pipeline_version,
        "provider": provider,
        "model": model,
        "paper_ids": sorted(set(paper.get("merged_ids") or [paper.get("canonical_id") or ""])),
        "template": {
            "id": template.id,
            "metadata": template.metadata,
            "body": summary_templates.load(template),
        },
        "paper_metadata": {
            "title": paper.get("title") or "",
            "authors": paper.get("authors") or [],
            "year_date": paper.get("published") or paper.get("date") or "",
            "venue": paper.get("container_title") or paper.get("venue") or "",
            "doi": paper.get("doi") or "",
            "url": paper.get("url") or "",
        },
        "project": project,
        "evidence": evidence,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cache_key(canonical_id: str, content_fingerprint: str) -> str:
    """Build a v2-only key. Legacy ``paper::template`` keys never match."""
    return f"v2::{canonical_id}::{content_fingerprint}"


def lookup(cache: dict[str, dict], paper: dict, content_fingerprint: str) -> str | None:
    """Look up the same v2 identity under any cross-source merged paper ID."""
    for canonical_id in paper.get("merged_ids", [paper["canonical_id"]]):
        entry = cache.get(cache_key(canonical_id, content_fingerprint))
        if (
            isinstance(entry, dict)
            and entry.get("schema") == CACHE_SCHEMA_VERSION
            and entry.get("fingerprint") == content_fingerprint
            and entry.get("summary")
        ):
            return entry["summary"]
    return None


def entry(summary: str, content_fingerprint: str, **metadata) -> dict:
    """Create a normalized cache value for one generated summary."""
    return {
        "schema": CACHE_SCHEMA_VERSION,
        "fingerprint": content_fingerprint,
        "summary": summary,
        **metadata,
    }


def save(path: Path, new_entries: dict[str, dict]) -> None:
    """Merge ``new_entries`` into the on-disk cache and write it back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load(path)
    existing.update(new_entries)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(existing, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
