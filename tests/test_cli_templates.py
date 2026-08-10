import argparse
import logging
from pathlib import Path

from papertracker import cli, config, summary_templates


def test_main_reports_invalid_template_catalog_before_resolving_profiles(monkeypatch, caplog):
    monkeypatch.setattr(
        config,
        "summary_template_catalog",
        lambda: (_ for _ in ()).throw(config.ConfigError("templates are invalid")),
    )
    resolved = []
    monkeypatch.setattr(cli, "_resolve_profiles", lambda args: resolved.append(True) or ([], 0))

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


def test_main_reports_unknown_zotero_template_before_resolving_profiles(monkeypatch, caplog):
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
    monkeypatch.setattr(cli, "_resolve_profiles", lambda args: resolved.append(True) or ([], 0))

    with caplog.at_level(logging.ERROR):
        result = cli.main(["--zotero-collection", "Reading", "--zotero-template", "missing"])

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
    monkeypatch.setattr(cli, "_resolve_profiles", lambda args: resolved.append(True) or ([], 0))
    with caplog.at_level(logging.ERROR):
        result = cli.main(["--template", "abstract-screen", "--zotero-template", "deep-technical"])
    assert result == 2
    assert not resolved
    assert "Conflicting template values" in caplog.text


def test_deprecated_alias_sets_same_global_override(monkeypatch, caplog):
    captured = []
    monkeypatch.setattr(config, "summary_template_catalog", lambda: ((), None))
    # Returns a real template: main() checks its evidence against the mode, and
    # --zotero-collection is the fulltext one.
    monkeypatch.setattr(
        config,
        "summary_template",
        lambda selected: (
            captured.append(selected)
            or summary_templates.SummaryTemplate(
                selected, Path(f"{selected}.md"), selected, "d", "fulltext", "## B"
            )
        ),
    )
    monkeypatch.setattr(cli, "_resolve_profiles", lambda args: ([], 0))
    with caplog.at_level(logging.WARNING):
        assert (
            cli.main(["--zotero-collection", "Reading", "--zotero-template", "deep-technical"]) == 0
        )
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


def _tpl(tmp_path, template_id, evidence):
    return summary_templates.SummaryTemplate(
        template_id, tmp_path / f"{template_id}.md", template_id, "d", evidence, "## B"
    )


def _catalog(tmp_path, monkeypatch):
    """Two abstract templates and two fulltext ones, so filtering is visible."""
    templates = (
        _tpl(tmp_path, "screen", "abstract"),
        _tpl(tmp_path, "triage", "abstract"),
        _tpl(tmp_path, "deep-tech", "fulltext"),
        _tpl(tmp_path, "deep-study", "fulltext"),
    )
    defaults = {"abstract": templates[0], "fulltext": templates[2]}
    monkeypatch.setattr(
        config,
        "summary_template_catalog",
        lambda evidence="abstract": (templates, defaults[evidence]),
    )
    return templates


def test_each_mode_offers_only_its_own_evidence(tmp_path, monkeypatch):
    """The mode boundary is the filter, not a per-option disabled attribute.

    A discovery run holds an abstract and the Zotero batch holds a PDF, so each
    picker should show the templates it can actually run and no others.
    """
    _catalog(tmp_path, monkeypatch)
    args = argparse.Namespace(template_override=None, template=None, zotero_template=None)

    abstract, abstract_default = cli._summary_template_options("abstract", args)
    fulltext, fulltext_default = cli._summary_template_options("fulltext", args)

    assert [t.id for t in abstract] == ["screen", "triage"]
    assert [t.id for t in fulltext] == ["deep-tech", "deep-study"]
    assert abstract_default == "screen"
    assert fulltext_default == "deep-tech"


def test_a_mode_still_offers_every_template_of_its_own_evidence(tmp_path, monkeypatch):
    """Filtering must not collapse the choice — --select still picks per paper."""
    _catalog(tmp_path, monkeypatch)
    args = argparse.Namespace(template_override=None, template=None, zotero_template=None)
    offered, _ = cli._summary_template_options("abstract", args)
    assert len(offered) == 2


def test_fulltext_template_on_a_discovery_run_is_rejected_once(caplog):
    with caplog.at_level(logging.ERROR):
        code = cli.main(["--template", "deep-technical", "--days", "1"])
    assert code == 2
    assert "needs fulltext evidence" in caplog.text
    assert "--zotero-collection" in caplog.text
    # One mode-level error, not one per paper.
    assert caplog.text.count("needs fulltext evidence") == 1


def test_abstract_template_on_a_zotero_run_is_rejected(caplog):
    with caplog.at_level(logging.ERROR):
        code = cli.main(["--zotero-collection", "Reading", "--template", "abstract-screen"])
    assert code == 2
    assert "needs abstract evidence" in caplog.text
