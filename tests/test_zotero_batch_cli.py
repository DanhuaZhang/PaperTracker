import argparse
import datetime as dt
from pathlib import Path

from papertracker import cli, config, summarizer, zotero


def _profile(tmp_path) -> config.ProjectProfile:
    return config.ProjectProfile(
        id="zotero",
        name="Zotero Batch",
        topic_statement="embodied agents in 3D environments",
        crossref_query_hint="embodied agents 3D",
        arxiv_categories=["cs.AI"],
        relevance_threshold=0.65,
        priority_venues=[],
        priority_venue_only=False,
        enabled_sources_default=["arxiv"],
        digest_dir=str(tmp_path / "digests" / "zotero"),
        seen_papers_file=str(tmp_path / ".papertracker" / "zotero" / "seen.json"),
        summary_cache_file=str(tmp_path / ".papertracker" / "zotero" / "summary_cache.json"),
    )


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        zotero_collection="Reading/Deep Reading",
        zotero_include_subcollections=False,
        zotero_template="deep",
        refresh_summaries=False,
        priority_venues_only=False,
        scorer=None,
        provider="claude",
        model=None,
    )


def test_zotero_collection_batch_passes_explicit_pdf_path(monkeypatch, tmp_path):
    profile = _profile(tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    paper = {
        "canonical_id": "zotero:ITEM1",
        "merged_ids": ["zotero:ITEM1"],
        "source": "zotero",
        "venue": None,
        "title": "Local Paper",
        "abstract": "",
        "authors": [],
        "published": "2026",
        "url": "",
        "doi": "",
        "container_title": "",
        "pdf_path": str(pdf),
        "template": "deep",
    }
    calls = []

    monkeypatch.setattr(zotero, "collection_papers", lambda *args, **kwargs: [paper])
    monkeypatch.setattr(cli, "_resolve_llm", lambda args: ("claude", "sonnet", 0))

    def fake_summarize(paper, provider, model, template_id, profile, pdf_path=None):
        calls.append((template_id, Path(pdf_path)))
        return "summary from pdf"

    monkeypatch.setattr(summarizer, "summarize_paper", fake_summarize)

    assert cli._run_zotero_collection_profile(profile, _args()) == 0

    assert calls == [("deep", pdf)]
    digest_path = (
        tmp_path
        / "digests"
        / "zotero"
        / "zotero"
        / "reading-deep-reading"
        / f"{dt.date.today().isoformat()}.md"
    )
    content = digest_path.read_text(encoding="utf-8")
    assert "PaperTracker Zotero Batch" in content
    assert "Local Paper" in content
    assert "summary from pdf" in content


def test_zotero_collection_batch_uses_resolved_provider(monkeypatch, tmp_path):
    profile = _profile(tmp_path)
    args = _args()
    args.provider = "codex"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(
        zotero,
        "collection_papers",
        lambda *args, **kwargs: [
            {
                "canonical_id": "zotero:ITEM1",
                "merged_ids": ["zotero:ITEM1"],
                "source": "zotero",
                "venue": None,
                "title": "Local Paper",
                "abstract": "",
                "authors": [],
                "published": "2026",
                "url": "",
                "doi": "",
                "container_title": "",
                "pdf_path": str(pdf),
            }
        ],
    )
    monkeypatch.setattr(cli, "_resolve_llm", lambda args: ("codex", "gpt", 0))
    calls = []

    def fake_summarize(paper, provider, model, template_id, profile, pdf_path=None):
        calls.append((provider, model, Path(pdf_path)))
        return "summary from selected provider"

    monkeypatch.setattr(summarizer, "summarize_paper", fake_summarize)

    assert cli._run_zotero_collection_profile(profile, args) == 0

    assert calls == [("codex", "gpt", pdf)]


def test_zotero_collection_batch_records_pdf_extraction_error(monkeypatch, tmp_path):
    profile = _profile(tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    paper = {
        "canonical_id": "zotero:ITEM1",
        "merged_ids": ["zotero:ITEM1"],
        "source": "zotero",
        "venue": None,
        "title": "Local Paper",
        "abstract": "",
        "authors": [],
        "published": "2026",
        "url": "",
        "doi": "",
        "container_title": "",
        "pdf_path": str(pdf),
    }

    monkeypatch.setattr(zotero, "collection_papers", lambda *args, **kwargs: [paper])
    monkeypatch.setattr(cli, "_resolve_llm", lambda args: ("codex", "gpt", 0))
    monkeypatch.setattr(
        summarizer,
        "summarize_paper",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            summarizer.PdfTextExtractionError("no text found")
        ),
    )

    assert cli._run_zotero_collection_profile(profile, _args()) == 0

    digest_path = (
        tmp_path
        / "digests"
        / "zotero"
        / "zotero"
        / "reading-deep-reading"
        / f"{dt.date.today().isoformat()}.md"
    )
    content = digest_path.read_text(encoding="utf-8")
    assert "summary failed: no text found" in content
