"""Resolve a paper to its local Zotero PDF by reading a read-only copy of zotero.sqlite.

Zotero 7's local HTTP API exposes no reliable attachment-file endpoint, so we read
the SQLite DB directly. Zotero locks the live DB, so we copy it to a temp file first
(per Zotero's "Direct SQLite Database Access" guidance) and open read-only.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


def _normalize_title(t: str) -> str:
    return " ".join((t or "").split()).strip().lower()


def find_pdf(paper: dict, data_dir: Path | None = None) -> Path | None:
    """Return the local PDF path for `paper` if it exists in Zotero, else None.

    Matches by DOI (preferred), then by normalized title.
    """
    data_dir = Path(data_dir) if data_dir is not None else config.zotero_data_dir()
    db = data_dir / "zotero.sqlite"
    if not db.exists():
        log.debug("Zotero DB not found at %s", db)
        return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "zotero.sqlite"
        try:
            shutil.copy2(db, tmp_db)
            con = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True)
        except (OSError, sqlite3.Error) as e:
            log.warning("Could not open Zotero DB: %s", e)
            return None
        try:
            item_id = _match_item(con, paper)
            if item_id is None:
                return None
            return _attachment_path(con, item_id, data_dir)
        finally:
            con.close()


def _match_item(con: sqlite3.Connection, paper: dict) -> int | None:
    doi = (paper.get("doi") or "").strip().lower()
    if doi:
        row = con.execute(
            """
            SELECT id.itemID FROM itemData id
            JOIN fields f ON f.fieldID = id.fieldID
            JOIN itemDataValues v ON v.valueID = id.valueID
            WHERE f.fieldName = 'DOI' AND lower(v.value) = ?
            LIMIT 1
            """,
            (doi,),
        ).fetchone()
        if row:
            return row[0]

    title = _normalize_title(paper.get("title") or "")
    if title:
        row = con.execute(
            """
            SELECT id.itemID FROM itemData id
            JOIN fields f ON f.fieldID = id.fieldID
            JOIN itemDataValues v ON v.valueID = id.valueID
            WHERE f.fieldName = 'title' AND lower(trim(v.value)) = ?
            LIMIT 1
            """,
            (title,),
        ).fetchone()
        if row:
            return row[0]
    return None


def _attachment_path(con: sqlite3.Connection, parent_id: int, data_dir: Path) -> Path | None:
    rows = con.execute(
        """
        SELECT i.key, a.path FROM itemAttachments a
        JOIN items i ON i.itemID = a.itemID
        WHERE a.parentItemID = ? AND a.contentType = 'application/pdf'
        """,
        (parent_id,),
    ).fetchall()
    for key, path in rows:
        if not path:
            continue
        if path.startswith("storage:"):
            candidate = data_dir / "storage" / key / path[len("storage:"):]
        elif path.startswith("attachments:"):
            base = config.zotero_linked_base_dir()
            if base is None:
                continue
            candidate = base / path[len("attachments:"):]
        else:
            candidate = Path(path)  # absolute linked path
        if candidate.exists():
            return candidate
    return None
