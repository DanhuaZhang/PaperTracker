from papertracker import summary_cache, summary_templates


def _template(tmp_path, evidence="abstract", body="## Finding"):
    return summary_templates.SummaryTemplate(
        "screen" if evidence == "abstract" else "deep",
        tmp_path / "template.md",
        "Label",
        "Description",
        evidence,
        body,
    )


def _fingerprint(tmp_path, **overrides):
    paper = {
        "canonical_id": "arxiv:1",
        "title": "Paper",
        "abstract": "Abstract",
        "authors": ["A. Author"],
    }
    paper.update(overrides.pop("paper", {}))
    template = overrides.pop("template", _template(tmp_path))
    return summary_cache.fingerprint(
        paper,
        template,
        overrides.pop("provider", "claude"),
        overrides.pop("model", "sonnet"),
        pipeline_version=overrides.pop("pipeline_version", "v2"),
        **overrides,
    )


def test_v2_lookup_never_reuses_legacy_entries(tmp_path):
    fingerprint = _fingerprint(tmp_path)
    paper = {"canonical_id": "arxiv:1"}
    legacy = {"arxiv:1::screen": {"summary": "legacy"}}
    assert summary_cache.lookup(legacy, paper, fingerprint) is None

    value = summary_cache.entry("fresh", fingerprint)
    cache = {summary_cache.cache_key("arxiv:1", fingerprint): value}
    assert summary_cache.lookup(cache, paper, fingerprint) == "fresh"


def test_fingerprint_invalidates_all_material_inputs(tmp_path):
    baseline = _fingerprint(tmp_path)
    assert _fingerprint(tmp_path, paper={"canonical_id": "arxiv:2"}) != baseline
    assert _fingerprint(tmp_path, paper={"abstract": "Changed"}) != baseline
    assert _fingerprint(tmp_path, template=_template(tmp_path, body="## Changed")) != baseline
    assert _fingerprint(tmp_path, provider="codex") != baseline
    assert _fingerprint(tmp_path, model="other") != baseline
    assert _fingerprint(tmp_path, pipeline_version="v3") != baseline


def test_fulltext_fingerprint_tracks_pdf_bytes(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"one")
    template = _template(tmp_path, evidence="fulltext")
    first = _fingerprint(tmp_path, template=template, pdf_path=pdf)
    pdf.write_bytes(b"two")
    second = _fingerprint(tmp_path, template=template, pdf_path=pdf)
    assert first != second
