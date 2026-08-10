import sqlite3
from pathlib import Path

from papertracker import zotero


def _make_zotero(tmp_path: Path, *, doi: str, title: str, filename: str) -> Path:
    """Build a minimal Zotero data dir: zotero.sqlite + a stored PDF."""
    data_dir = tmp_path / "Zotero"
    storage = data_dir / "storage" / "ABCD1234"
    storage.mkdir(parents=True)
    (storage / filename).write_bytes(b"%PDF-1.4 fake")

    db = data_dir / "zotero.sqlite"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
        CREATE TABLE itemAttachments
            (itemID INTEGER, parentItemID INTEGER, contentType TEXT, path TEXT);
        """
    )
    # parent item (key irrelevant) + attachment item (key drives storage folder)
    con.execute("INSERT INTO items VALUES (1, 'PARENT01')")
    con.execute("INSERT INTO items VALUES (2, 'ABCD1234')")
    con.execute("INSERT INTO fields VALUES (1, 'DOI')")
    con.execute("INSERT INTO fields VALUES (2, 'title')")
    con.execute("INSERT INTO itemDataValues VALUES (1, ?)", (doi,))
    con.execute("INSERT INTO itemDataValues VALUES (2, ?)", (title,))
    con.execute("INSERT INTO itemData VALUES (1, 1, 1)")
    con.execute("INSERT INTO itemData VALUES (1, 2, 2)")
    con.execute(
        "INSERT INTO itemAttachments VALUES (2, 1, 'application/pdf', ?)",
        (f"storage:{filename}",),
    )
    con.commit()
    con.close()
    return data_dir


def _make_zotero_collections(tmp_path: Path) -> Path:
    data_dir = tmp_path / "Zotero"
    data_dir.mkdir()
    for key, filename in (
        ("PDF00001", "reading.pdf"),
        ("PDF00002", "project.pdf"),
        ("PDF00003", "nested.pdf"),
    ):
        storage = data_dir / "storage" / key
        storage.mkdir(parents=True)
        (storage / filename).write_bytes(b"%PDF-1.4 fake")

    db = data_dir / "zotero.sqlite"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE collections
            (collectionID INTEGER PRIMARY KEY, libraryID INTEGER, parentCollectionID INTEGER, collectionName TEXT);
        CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
        CREATE TABLE itemAttachments
            (itemID INTEGER, parentItemID INTEGER, contentType TEXT, path TEXT);
        """
    )
    con.executemany(
        "INSERT INTO collections VALUES (?, ?, ?, ?)",
        [
            (10, 1, None, "Reading"),
            (11, 1, 10, "Deep Reading"),
            (12, 1, 11, "Nested"),
            (20, 1, None, "Project A"),
            (21, 1, 20, "Deep Reading"),
        ],
    )
    con.executemany(
        "INSERT INTO fields VALUES (?, ?)",
        [(1, "title"), (2, "DOI"), (3, "abstractNote"), (4, "date")],
    )

    def add_paper(
        item_id: int,
        item_key: str,
        attachment_id: int,
        attachment_key: str,
        filename: str,
        title: str,
        collection_id: int,
    ) -> None:
        value_base = item_id * 10
        con.execute("INSERT INTO items VALUES (?, ?)", (item_id, item_key))
        con.execute("INSERT INTO items VALUES (?, ?)", (attachment_id, attachment_key))
        con.executemany(
            "INSERT INTO itemDataValues VALUES (?, ?)",
            [
                (value_base + 1, title),
                (value_base + 2, f"10.1/{item_key.lower()}"),
                (value_base + 3, f"Abstract for {title}"),
                (value_base + 4, "2026"),
            ],
        )
        con.executemany(
            "INSERT INTO itemData VALUES (?, ?, ?)",
            [
                (item_id, 1, value_base + 1),
                (item_id, 2, value_base + 2),
                (item_id, 3, value_base + 3),
                (item_id, 4, value_base + 4),
            ],
        )
        con.execute(
            "INSERT INTO itemAttachments VALUES (?, ?, 'application/pdf', ?)",
            (attachment_id, item_id, f"storage:{filename}"),
        )
        con.execute("INSERT INTO collectionItems VALUES (?, ?)", (collection_id, item_id))

    add_paper(1, "READING1", 2, "PDF00001", "reading.pdf", "Reading Paper", 11)
    add_paper(3, "PROJECT1", 4, "PDF00002", "project.pdf", "Project Paper", 21)
    add_paper(5, "NESTED1", 6, "PDF00003", "nested.pdf", "Nested Paper", 12)
    con.commit()
    con.close()
    return data_dir


def test_find_pdf_by_doi(tmp_path):
    data_dir = _make_zotero(tmp_path, doi="10.1/xyz", title="A Paper", filename="a.pdf")
    paper = {"doi": "10.1/XYZ", "title": "irrelevant", "abstract": ""}
    pdf = zotero.find_pdf(paper, data_dir=data_dir)
    assert pdf is not None
    assert pdf.name == "a.pdf"
    assert pdf.exists()


def test_find_pdf_by_title_when_no_doi(tmp_path):
    data_dir = _make_zotero(tmp_path, doi="10.1/xyz", title="A Paper", filename="a.pdf")
    paper = {"doi": None, "title": "  a paper ", "abstract": ""}
    assert zotero.find_pdf(paper, data_dir=data_dir) is not None


def test_find_pdf_returns_none_when_absent(tmp_path):
    data_dir = _make_zotero(tmp_path, doi="10.1/xyz", title="A Paper", filename="a.pdf")
    paper = {"doi": "10.9/none", "title": "Nothing Here", "abstract": ""}
    assert zotero.find_pdf(paper, data_dir=data_dir) is None


def test_find_pdf_missing_data_dir(tmp_path):
    assert zotero.find_pdf({"doi": "x", "title": "y"}, data_dir=tmp_path / "nope") is None


def test_list_collections_returns_full_paths(tmp_path):
    data_dir = _make_zotero_collections(tmp_path)

    paths = [collection["path"] for collection in zotero.list_collections(data_dir)]

    assert "Reading/Deep Reading" in paths
    assert "Reading/Deep Reading/Nested" in paths
    assert "Project A/Deep Reading" in paths


def test_collection_papers_requires_full_path_when_ambiguous(tmp_path):
    data_dir = _make_zotero_collections(tmp_path)

    try:
        zotero.collection_papers("Deep Reading", data_dir=data_dir)
    except zotero.ZoteroError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ambiguous collection error")

    assert "Reading/Deep Reading" in message
    assert "Project A/Deep Reading" in message


def test_collection_papers_resolves_pdf_items_by_full_path(tmp_path):
    data_dir = _make_zotero_collections(tmp_path)

    papers = zotero.collection_papers("Reading/Deep Reading", data_dir=data_dir)

    assert [paper["title"] for paper in papers] == ["Reading Paper"]
    # Compare parts, not a slash-joined string: the path is native, so it uses
    # backslashes on Windows.
    assert Path(papers[0]["pdf_path"]).parts[-3:] == (
        "storage",
        "PDF00001",
        "reading.pdf",
    )
    assert papers[0]["canonical_id"] == "zotero:READING1"


def test_collection_papers_can_include_subcollections(tmp_path):
    data_dir = _make_zotero_collections(tmp_path)

    papers = zotero.collection_papers(
        "My Library/Reading/Deep Reading",
        include_subcollections=True,
        data_dir=data_dir,
    )

    assert [paper["title"] for paper in papers] == ["Nested Paper", "Reading Paper"]


def test_item_creators_loads_ordered_person_and_corporate_authors():
    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE creators (creatorID INTEGER, firstName TEXT, lastName TEXT, fieldMode INTEGER);
        CREATE TABLE creatorTypes (creatorTypeID INTEGER, creatorType TEXT);
        CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER);
        INSERT INTO creatorTypes VALUES (1, 'author');
        INSERT INTO creatorTypes VALUES (2, 'editor');
        INSERT INTO creators VALUES (1, 'Ada', 'Lovelace', 0);
        INSERT INTO creators VALUES (2, '', 'Research Collective', 1);
        INSERT INTO creators VALUES (3, 'Ed', 'Editor', 0);
        INSERT INTO itemCreators VALUES (5, 2, 1, 1);
        INSERT INTO itemCreators VALUES (5, 1, 1, 0);
        INSERT INTO itemCreators VALUES (5, 3, 2, 2);
        """
    )
    assert zotero._item_creators(con, 5) == ["Ada Lovelace", "Research Collective"]
    con.close()
