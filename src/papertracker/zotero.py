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


class ZoteroError(RuntimeError):
    """Raised when a Zotero collection lookup cannot be resolved."""


def _normalize_title(t: str) -> str:
    return " ".join((t or "").split()).strip().lower()


def _copy_db(data_dir: Path):
    db = data_dir / "zotero.sqlite"
    if not db.exists():
        log.debug("Zotero DB not found at %s", db)
        return None
    tmp = tempfile.TemporaryDirectory()
    tmp_db = Path(tmp.name) / "zotero.sqlite"
    try:
        shutil.copy2(db, tmp_db)
        # as_uri() rather than interpolation: a Windows temp path carries a drive
        # letter, backslashes, and often a space in the user name, none of which
        # survive being pasted into a URI raw.
        con = sqlite3.connect(f"{tmp_db.as_uri()}?mode=ro", uri=True)
    except (OSError, sqlite3.Error) as e:
        tmp.cleanup()
        log.warning("Could not open Zotero DB: %s", e)
        return None
    return tmp, con


def find_pdf(paper: dict, data_dir: Path | None = None) -> Path | None:
    """Return the local PDF path for `paper` if it exists in Zotero, else None.

    Matches by DOI (preferred), then by normalized title.
    """
    data_dir = Path(data_dir) if data_dir is not None else config.zotero_data_dir()
    copied = _copy_db(data_dir)
    if copied is None:
        return None

    tmp, con = copied
    try:
        item_id = _match_item(con, paper)
        if item_id is None:
            return None
        return _attachment_path(con, item_id, data_dir)
    finally:
        con.close()
        tmp.cleanup()


def list_collections(data_dir: Path | None = None) -> list[dict]:
    """Return Zotero collections with their library-relative UI paths."""
    data_dir = Path(data_dir) if data_dir is not None else config.zotero_data_dir()
    copied = _copy_db(data_dir)
    if copied is None:
        return []

    tmp, con = copied
    try:
        rows = con.execute(
            """
            SELECT collectionID, libraryID, parentCollectionID, collectionName
            FROM collections
            ORDER BY libraryID, collectionName
            """
        ).fetchall()
    except sqlite3.Error as e:
        log.warning("Could not read Zotero collections: %s", e)
        return []
    finally:
        con.close()
        tmp.cleanup()

    by_id = {
        row[0]: {
            "collection_id": row[0],
            "library_id": row[1],
            "parent_id": row[2],
            "name": row[3],
        }
        for row in rows
    }

    def path_for(collection_id: int) -> str:
        collection = by_id[collection_id]
        names = [collection["name"]]
        parent_id = collection["parent_id"]
        seen = {collection_id}
        while parent_id in by_id and parent_id not in seen:
            seen.add(parent_id)
            parent = by_id[parent_id]
            names.append(parent["name"])
            parent_id = parent["parent_id"]
        return "/".join(reversed(names))

    collections = []
    for collection_id, collection in by_id.items():
        collections.append(
            {
                "collection_id": collection_id,
                "library_id": collection["library_id"],
                "parent_id": collection["parent_id"],
                "name": collection["name"],
                "path": path_for(collection_id),
            }
        )
    collections.sort(key=lambda c: (c["library_id"], c["path"].lower(), c["collection_id"]))
    return collections


def collection_papers(
    collection_path: str,
    *,
    include_subcollections: bool = False,
    data_dir: Path | None = None,
) -> list[dict]:
    """Return paper metadata and PDF paths for a Zotero collection path.

    ``collection_path`` is the path shown in Zotero's collection tree, relative to
    the library root, for example ``Reading/Deep Reading``.
    """
    data_dir = Path(data_dir) if data_dir is not None else config.zotero_data_dir()
    collections = list_collections(data_dir)
    collection = _resolve_collection(collection_path, collections)
    collection_ids = {collection["collection_id"]}
    if include_subcollections:
        collection_ids |= _descendant_collection_ids(collection["collection_id"], collections)

    copied = _copy_db(data_dir)
    if copied is None:
        return []
    tmp, con = copied
    try:
        papers: list[dict] = []
        seen_items: set[int] = set()
        for collection_id in collection_ids:
            rows = con.execute(
                "SELECT itemID FROM collectionItems WHERE collectionID = ?",
                (collection_id,),
            ).fetchall()
            for (item_id,) in rows:
                if item_id in seen_items:
                    continue
                seen_items.add(item_id)
                paper = _paper_from_item(con, item_id, data_dir)
                if paper is not None:
                    papers.append(paper)
        papers.sort(key=lambda p: (p.get("title") or "").lower())
        return papers
    finally:
        con.close()
        tmp.cleanup()


def _resolve_collection(collection_path: str, collections: list[dict]) -> dict:
    requested = _normalize_collection_path(collection_path)
    if not requested:
        raise ZoteroError("Zotero collection path cannot be empty")

    if "/" in requested:
        matches = [c for c in collections if c["path"] == requested]
    else:
        matches = [
            c for c in collections
            if c["path"] == requested or c["name"] == requested
        ]

    if not matches:
        available = "\n".join(f"- {c['path']}" for c in collections[:20])
        suffix = f"\nAvailable collections:\n{available}" if available else ""
        raise ZoteroError(f"Zotero collection not found: {collection_path!r}{suffix}")
    if len(matches) > 1:
        choices = "\n".join(f"- {c['path']}" for c in matches)
        raise ZoteroError(
            f"Ambiguous Zotero collection {collection_path!r}. Use the full path:\n{choices}"
        )
    return matches[0]


def _normalize_collection_path(path: str) -> str:
    parts = [part.strip() for part in str(path or "").split("/") if part.strip()]
    if parts and parts[0].lower() == "my library":
        parts = parts[1:]
    return "/".join(parts)


def _descendant_collection_ids(collection_id: int, collections: list[dict]) -> set[int]:
    children: dict[int, list[int]] = {}
    for collection in collections:
        parent_id = collection.get("parent_id")
        if parent_id is not None:
            children.setdefault(parent_id, []).append(collection["collection_id"])

    found: set[int] = set()
    stack = list(children.get(collection_id, []))
    while stack:
        cid = stack.pop()
        if cid in found:
            continue
        found.add(cid)
        stack.extend(children.get(cid, []))
    return found


def _paper_from_item(con: sqlite3.Connection, item_id: int, data_dir: Path) -> dict | None:
    pdf_path = _attachment_path(con, item_id, data_dir)
    if pdf_path is None:
        return None

    row = con.execute("SELECT key FROM items WHERE itemID = ?", (item_id,)).fetchone()
    item_key = row[0] if row else str(item_id)
    fields = _item_fields(con, item_id)
    title = fields.get("title") or f"Zotero item {item_key}"
    doi = fields.get("DOI") or fields.get("doi") or ""
    url = fields.get("url") or (f"https://doi.org/{doi}" if doi else "")
    container_title = (
        fields.get("publicationTitle")
        or fields.get("conferenceName")
        or fields.get("proceedingsTitle")
        or fields.get("journalAbbreviation")
        or ""
    )
    return {
        "canonical_id": f"zotero:{item_key}",
        "merged_ids": [f"zotero:{item_key}"],
        "source": "zotero",
        "venue": None,
        "title": title,
        "abstract": fields.get("abstractNote") or "",
        "authors": _item_creators(con, item_id),
        "published": fields.get("date") or "",
        "url": url,
        "doi": doi,
        "container_title": container_title,
        "pdf_path": str(pdf_path),
    }


def _item_fields(con: sqlite3.Connection, item_id: int) -> dict[str, str]:
    rows = con.execute(
        """
        SELECT f.fieldName, v.value
        FROM itemData id
        JOIN fields f ON f.fieldID = id.fieldID
        JOIN itemDataValues v ON v.valueID = id.valueID
        WHERE id.itemID = ?
        """,
        (item_id,),
    ).fetchall()
    return {field: value for field, value in rows}


def _item_creators(con: sqlite3.Connection, item_id: int) -> list[str]:
    """Load Zotero authors in their stored order, including corporate authors."""
    try:
        rows = con.execute(
            """
            SELECT c.firstName, c.lastName, c.fieldMode, ct.creatorType
            FROM itemCreators ic
            JOIN creators c ON c.creatorID = ic.creatorID
            LEFT JOIN creatorTypes ct ON ct.creatorTypeID = ic.creatorTypeID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """,
            (item_id,),
        ).fetchall()
    except sqlite3.Error:
        # Older/minimal Zotero-compatible databases may omit creator tables.
        return []
    authors = []
    for first_name, last_name, field_mode, creator_type in rows:
        if creator_type and creator_type != "author":
            continue
        first = (first_name or "").strip()
        last = (last_name or "").strip()
        if field_mode or not first:
            name = last
        else:
            name = " ".join(part for part in (first, last) if part)
        if name:
            authors.append(name)
    return authors


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
