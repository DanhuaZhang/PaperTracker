import logging

from papertracker import cli, config, summary_templates


def test_main_reports_invalid_template_catalog_before_resolving_profiles(
    monkeypatch, caplog
):
    monkeypatch.setattr(
        config,
        "summary_template_catalog",
        lambda: (_ for _ in ()).throw(config.ConfigError("templates are invalid")),
    )
    resolved = []
    monkeypatch.setattr(
        cli, "_resolve_profiles", lambda args: resolved.append(True) or ([], 0)
    )

    with caplog.at_level(logging.ERROR):
        result = cli.main([])

    assert result == 2
    assert resolved == []
    assert "templates are invalid" in caplog.text


def test_no_summarize_does_not_require_template_catalog(monkeypatch):
    monkeypatch.setattr(
        config,
        "summary_template_catalog",
        lambda: (_ for _ in ()).throw(AssertionError("catalog should not be read")),
    )
    monkeypatch.setattr(cli, "_resolve_profiles", lambda args: ([], 0))

    assert cli.main(["--no-summarize"]) == 0


def test_main_reports_unknown_zotero_template_before_resolving_profiles(
    monkeypatch, caplog
):
    templates, default = config.summary_template_catalog()
    monkeypatch.setattr(config, "summary_template_catalog", lambda: (templates, default))
    monkeypatch.setattr(
        config,
        "summary_template",
        lambda selected: (_ for _ in ()).throw(
            config.ConfigError(f"Unknown summary template {selected!r}")
        ),
    )
    resolved = []
    monkeypatch.setattr(
        cli, "_resolve_profiles", lambda args: resolved.append(True) or ([], 0)
    )

    with caplog.at_level(logging.ERROR):
        result = cli.main(
            ["--zotero-collection", "Reading", "--zotero-template", "missing"]
        )

    assert result == 2
    assert resolved == []
    assert "Unknown summary template 'missing'" in caplog.text


def test_list_templates_prints_metadata_and_default_status(monkeypatch, capsys, tmp_path):
    screen = summary_templates.SummaryTemplate(
        "screen", tmp_path / "screen.md", "Screen", "Fast", "abstract", "## S"
    )
    deep = summary_templates.SummaryTemplate(
        "deep", tmp_path / "deep.md", "Deep", "Every page", "fulltext", "## D"
    )
    monkeypatch.setattr(
        config,
        "summary_template_catalog",
        lambda evidence="abstract": ((screen, deep), screen if evidence == "abstract" else deep),
    )
    monkeypatch.setattr(config, "DEFAULT_ABSTRACT_TEMPLATE", "screen")
    monkeypatch.setattr(config, "DEFAULT_FULLTEXT_TEMPLATE", "deep")

    assert cli.main(["--list-templates"]) == 0
    output = capsys.readouterr().out
    assert "screen\tScreen\tabstract\tFast\tabstract" in output
    assert "deep\tDeep\tfulltext\tEvery page\tfulltext" in output


def test_template_and_deprecated_alias_conflict_before_profiles(monkeypatch, caplog):
    resolved = []
    monkeypatch.setattr(
        cli, "_resolve_profiles", lambda args: resolved.append(True) or ([], 0)
    )
    with caplog.at_level(logging.ERROR):
        result = cli.main(
            ["--template", "abstract-screen", "--zotero-template", "deep-technical"]
        )
    assert result == 2
    assert not resolved
    assert "Conflicting template values" in caplog.text


def test_deprecated_alias_sets_same_global_override(monkeypatch, caplog):
    captured = []
    monkeypatch.setattr(config, "summary_template_catalog", lambda: ((), None))
    monkeypatch.setattr(config, "summary_template", lambda selected: captured.append(selected))
    monkeypatch.setattr(cli, "_resolve_profiles", lambda args: ([], 0))
    with caplog.at_level(logging.WARNING):
        assert cli.main(
            ["--zotero-collection", "Reading", "--zotero-template", "deep-technical"]
        ) == 0
    assert captured == ["deep-technical"]
    assert "deprecated" in caplog.text


def test_facets_requires_related_work(caplog):
    with caplog.at_level(logging.ERROR):
        assert cli.main(["--facets"]) == 2
    assert "--facets requires --related-work" in caplog.text


def test_nonpositive_fetch_cap_is_rejected(caplog):
    with caplog.at_level(logging.ERROR):
        assert cli.main(["--max-results", "0"]) == 2
    assert "--max-results must be greater than zero" in caplog.text
