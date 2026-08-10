import argparse
import datetime as dt

from papertracker import cli, config, digest_writer, relevance, summarizer, summary_cache


def _profile(tmp_path):
    return config.ProjectProfile(
        id="test",
        name="Test Topic",
        topic_statement="test topic",
        crossref_query_hint="test",
        arxiv_categories=["cs.AI"],
        relevance_threshold=0.5,
        priority_venues=[],
        priority_venue_only=False,
        enabled_sources_default=["arxiv"],
        digest_dir=str(tmp_path / "digests"),
        seen_papers_file=str(tmp_path / "state" / "seen.json"),
        summary_cache_file=str(tmp_path / "state" / "summaries.json"),
    )


def _paper(title):
    return {
        "canonical_id": f"arxiv:{title.lower()}",
        "merged_ids": [f"arxiv:{title.lower()}"],
        "source": "arxiv",
        "venue": None,
        "title": title,
        "abstract": "Relevant abstract",
        "authors": [],
        "published": "2026-08-08",
        "url": "https://example.test/paper",
        "doi": "",
        "container_title": "",
    }


def _args():
    return argparse.Namespace(
        sources=None,
        priority_venues_only=False,
        scorer=None,
        threshold=None,
        ignore_seen=False,
        select=False,
        no_summarize=False,
        refresh_summaries=False,
        template=None,
        template_override=None,
        zotero_template=None,
    )


def test_same_day_digest_merges_new_papers(tmp_path):
    profile = _profile(tmp_path)
    date = "2026-08-08"
    first = digest_writer.render_digest(date, [(_paper("First"), "First summary")], profile)
    second = digest_writer.render_digest(date, [(_paper("Second"), "Second summary")], profile)

    path = digest_writer.save_daily_digest(date, first, profile.digest_dir, new_paper_count=1)
    digest_writer.save_daily_digest(date, second, profile.digest_dir, new_paper_count=1)

    content = path.read_text(encoding="utf-8")
    assert "2 paper(s) matched" in content
    assert "First" in content
    assert "Second" in content
    assert content.count("## arXiv preprints") == 1


def test_empty_second_run_preserves_existing_digest(tmp_path):
    profile = _profile(tmp_path)
    date = "2026-08-08"
    first = digest_writer.render_digest(date, [(_paper("First"), "Summary")], profile)
    path = digest_writer.save_daily_digest(date, first, profile.digest_dir, new_paper_count=1)
    before = path.read_bytes()

    digest_writer.save_daily_digest(
        date,
        digest_writer.render_empty_digest(date, profile),
        profile.digest_dir,
        new_paper_count=0,
    )

    assert path.read_bytes() == before


def test_failed_summary_returns_nonzero_and_is_not_seen(monkeypatch, tmp_path):
    profile = _profile(tmp_path)
    paper = _paper("Retry Me")
    monkeypatch.setattr(cli, "_fetch_all", lambda *args: ([paper], []))
    monkeypatch.setattr(relevance, "filter_papers", lambda papers, **kwargs: papers)
    monkeypatch.setattr(cli, "_enrich_doi_papers", lambda papers: papers)
    monkeypatch.setattr(cli, "_validate_template_evidence", lambda *args: True)
    monkeypatch.setattr(cli, "_summary_fingerprint", lambda *args: "fingerprint")
    monkeypatch.setattr(summary_cache, "load", lambda path: {})
    monkeypatch.setattr(
        summarizer,
        "summarize_paper",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            summarizer.SummaryPipelineError("provider failed")
        ),
    )

    code = cli._run_profile(
        profile,
        _args(),
        dt.date(2026, 8, 7),
        dt.date(2026, 8, 8),
        "codex",
        "model",
    )

    assert code == 1
    assert not (tmp_path / "state" / "seen.json").exists()
    assert not (tmp_path / "digests" / f"{dt.date.today().isoformat()}.md").exists()


def test_total_source_failure_returns_nonzero_without_digest(monkeypatch, tmp_path):
    profile = _profile(tmp_path)
    monkeypatch.setattr(cli, "_fetch_all", lambda *args: ([], ["arxiv"]))

    code = cli._run_profile(
        profile,
        _args(),
        dt.date(2026, 8, 7),
        dt.date(2026, 8, 8),
        "codex",
        "model",
    )

    assert code == 1
    assert not (tmp_path / "digests").exists()
