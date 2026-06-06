from papertracker import selector


def test_form_parsing_assigns_modes():
    form = {"sel": ["0", "2"], "mode_0": ["deep"], "mode_2": ["triage"]}
    assert selector._selections_from_form(form, 3) == [(0, "deep"), (2, "triage")]


def test_form_parsing_defaults_to_triage():
    form = {"sel": ["1"]}  # no mode_1 key
    assert selector._selections_from_form(form, 3) == [(1, "triage")]


def test_form_cancel_returns_empty():
    assert selector._selections_from_form({"cancel": ["1"], "sel": ["0"]}, 3) == []


def test_text_parsing_modes():
    # bare number = triage; trailing 'd' = deep
    assert selector._parse_selection("1, 3d", 3) == [(0, "triage"), (2, "deep")]
