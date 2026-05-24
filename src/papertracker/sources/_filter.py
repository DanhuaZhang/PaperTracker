"""Shared local helpers used by sources (venue tagging)."""
from __future__ import annotations

from .. import config


def tag_venue(container_title: str | None) -> str | None:
    """Return the name of the matching PRIORITY_VENUES entry, or None."""
    if not container_title:
        return None
    ct = container_title.lower()
    for venue in config.PRIORITY_VENUES:
        for pat in venue["patterns"]:
            if pat.lower() in ct:
                return venue["name"]
    return None
