import pytest

from papertracker import selector, summary_templates


def _templates(tmp_path):
    return (
        summary_templates.SummaryTemplate(
            "screen", tmp_path / "screen.md", "Rapid screen", "Uses the abstract", "abstract", "## Screen"
        ),
        summary_templates.SummaryTemplate(
            "deep", tmp_path / "deep.md", "Deep read", "Uses every PDF page", "fulltext", "## Deep"
        ),
    )


def test_form_parsing_rejects_unknown_and_incompatible_templates(tmp_path):
    templates = _templates(tmp_path)
    with pytest.raises(selector.SelectionError, match="unknown"):
        selector._selections_from_form(
            {"sel": ["0"], "template_0": ["unknown"]},
            1,
            templates,
            "screen",
            [{"abstract": "A"}],
        )
    with pytest.raises(selector.SelectionError, match="readable local PDF"):
        selector._selections_from_form(
            {"sel": ["0"], "template_0": ["deep"]},
            1,
            templates,
            "screen",
            [{"abstract": "A"}],
        )


def test_form_parsing_accepts_per_paper_compatible_choices(tmp_path):
    templates = _templates(tmp_path)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    papers = [{"abstract": "A"}, {"abstract": "", "pdf_path": str(pdf)}]
    form = {"sel": ["0", "1"], "template_0": ["screen"], "template_1": ["deep"]}
    assert selector._selections_from_form(form, 2, templates, "screen", papers) == [
        (0, "screen"),
        (1, "deep"),
    ]


def test_text_parsing_supports_defaults_explicit_ids_and_ranges():
    assert selector._parse_selection(
        "1, 2:deep, 3-4:screen", 4, ["screen", "deep"], "screen"
    ) == [(0, "screen"), (1, "deep"), (2, "screen"), (3, "screen")]
    assert selector._parse_selection("all", 2, ["screen", "deep"], "deep") == [
        (0, "deep"),
        (1, "deep"),
    ]


def test_html_shows_labels_badges_descriptions_and_disabled_reasons(tmp_path):
    page = selector._render_html(
        [{"title": "T", "abstract": "A"}], _templates(tmp_path), "screen"
    )
    assert '<select name="template_0"' in page
    assert "Rapid screen [abstract] — Uses the abstract" in page
    assert "Deep read [fulltext] — Uses every PDF page" in page
    assert "unavailable: readable local PDF required" in page
    assert 'value="deep" disabled' in page
    assert 'value="screen" selected' in page
