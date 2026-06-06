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
