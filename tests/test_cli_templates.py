import logging

from papertracker import cli, config


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
