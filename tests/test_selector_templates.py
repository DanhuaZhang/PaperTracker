import re

import pytest

from papertracker import selector, summary_templates


def _templates(tmp_path):
    return (
        summary_templates.SummaryTemplate(
            "screen",
            tmp_path / "screen.md",
            "Rapid screen",
            "Uses the abstract",
            "abstract",
            "## Screen",
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
    assert selector._parse_selection("1, 2:deep, 3-4:screen", 4, ["screen", "deep"], "screen") == [
        (0, "screen"),
        (1, "deep"),
        (2, "screen"),
        (3, "screen"),
    ]
    assert selector._parse_selection("all", 2, ["screen", "deep"], "deep") == [
        (0, "deep"),
        (1, "deep"),
    ]


def test_html_shows_labels_badges_descriptions_and_disabled_reasons(tmp_path):
    page = selector._render_html([{"title": "T", "abstract": "A"}], _templates(tmp_path), "screen")
    assert '<select name="template_0"' in page
    assert "Rapid screen [abstract] — Uses the abstract" in page
    assert 'value="deep" disabled' in page
    assert 'value="screen" selected' in page
    # The blocker replaces the description in the visible text, because a
    # <select> truncates to the control width and the reason is what the reader
    # needs. The description survives in the tooltip.
    assert "Deep read [PDF missing or unreadable]" in page
    assert 'title="Uses every PDF page readable local PDF required"' in page


def test_disabled_is_now_the_odd_paper_out_not_the_whole_mode(tmp_path):
    """Within a mode, only a paper missing what its peers have is disabled.

    The catalog is filtered by evidence before it reaches the picker, so a
    fulltext run offers fulltext templates and every paper normally satisfies
    them. What survives is the individual failure: a PDF that will not open.
    """
    good = tmp_path / "good.pdf"
    good.write_bytes(b"%PDF-1.4 fake")
    fulltext_only = (_templates(tmp_path)[1],)

    page = selector._render_html(
        [
            {"title": "Readable", "abstract": "", "pdf_path": str(good)},
            {"title": "Gone", "abstract": "", "pdf_path": str(tmp_path / "missing.pdf")},
        ],
        fulltext_only,
        "deep",
    )

    assert page.count('value="deep" disabled') == 1
    assert "Deep read [PDF missing or unreadable]" in page


def test_a_card_never_preselects_a_template_that_paper_cannot_run(tmp_path):
    """`selected disabled` still submits, and the pick is only rejected after
    the round trip — so the card must fall back to something runnable."""
    templates = _templates(tmp_path)  # screen=abstract, deep=fulltext

    # Default is the fulltext template, but this paper has only an abstract.
    page = selector._render_html([{"title": "T", "abstract": "A"}], templates, "deep")

    assert 'value="screen" selected' in page
    assert "selected disabled" not in page


def test_a_card_selects_nothing_when_no_template_fits(tmp_path):
    templates = _templates(tmp_path)
    page = selector._render_html([{"title": "T", "abstract": ""}], templates, "deep")
    # Scoped to the options: the surrounding page has its own uses of "selected".
    assert re.findall(r"<option[^>]*\sselected", page) == []
    assert page.count("disabled") == 2
