import pytest

from papertracker import selector


def test_form_parsing_rejects_unknown_template_values():
    form = {
        "sel": ["0", "2"],
        "template_0": ["C"],
        "template_2": ["unknown"],
    }

    with pytest.raises(selector.SelectionError, match="unknown"):
        selector._selections_from_form(form, 3, ["A", "C"], "A")


def test_form_parsing_uses_default_when_field_is_absent():
    assert selector._selections_from_form(
        {"sel": ["1"]}, 3, ["A", "C"], "C"
    ) == [(1, "C")]


def test_form_cancel_returns_empty():
    assert selector._selections_from_form(
        {"cancel": ["1"], "sel": ["0"]}, 3, ["A"], "A"
    ) == []


def test_text_parsing_supports_default_explicit_and_ranges():
    assert selector._parse_selection("1, 2:C, 3-4:A", 4, ["A", "C"], "A") == [
        (0, "A"),
        (1, "C"),
        (2, "A"),
        (3, "A"),
    ]


def test_text_parsing_is_case_sensitive_and_rejects_unknown_template():
    with pytest.raises(selector.SelectionError, match="a"):
        selector._parse_selection("1:a,2:A", 2, ["A"], "A")


def test_text_parsing_all_uses_default():
    assert selector._parse_selection("all", 2, ["A", "C"], "C") == [
        (0, "C"),
        (1, "C"),
    ]


def test_render_html_uses_catalog_and_preselects_default():
    page = selector._render_html([{"title": "T"}], ["A", "B", "C"], "B")

    assert '<select name="template_0"' in page
    assert '<option value="A">A</option>' in page
    assert '<option value="B" selected>B</option>' in page
    assert '<option value="C">C</option>' in page


def test_render_html_escapes_template_identifiers():
    page = selector._render_html([{"title": "T"}], ['A"&'], 'A"&')

    assert 'value="A&quot;&amp;" selected>A&quot;&amp;</option>' in page
