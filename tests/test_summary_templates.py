from pathlib import Path

import pytest

from papertracker import config, summary_templates


def test_discover_sorts_direct_lowercase_markdown_files(tmp_path):
    (tmp_path / "C.md").write_text("# C", encoding="utf-8")
    (tmp_path / "A.md").write_text("# A", encoding="utf-8")
    (tmp_path / "ignored.MD").write_text("# ignored", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "B.md").write_text("# B", encoding="utf-8")

    templates, default = summary_templates.discover(tmp_path, "C")

    assert [item.id for item in templates] == ["A", "C"]
    assert default.id == "C"


def test_discover_rejects_missing_directory(tmp_path):
    directory = tmp_path / "missing"

    with pytest.raises(config.ConfigError, match="does not exist"):
        summary_templates.discover(directory, "A")


def test_discover_rejects_file_path(tmp_path):
    path = tmp_path / "A.md"
    path.write_text("# A", encoding="utf-8")

    with pytest.raises(config.ConfigError, match="not a directory"):
        summary_templates.discover(path, "A")


def test_discover_rejects_empty_directory(tmp_path):
    with pytest.raises(config.ConfigError, match=r"contains no \.md templates"):
        summary_templates.discover(tmp_path, "A")


def test_discover_rejects_missing_default(tmp_path):
    (tmp_path / "A.md").write_text("# A", encoding="utf-8")

    with pytest.raises(config.ConfigError, match="default.*B"):
        summary_templates.discover(tmp_path, "B")


def test_discover_reports_directory_enumeration_failure(monkeypatch, tmp_path):
    def fail_iterdir(self):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "iterdir", fail_iterdir)

    with pytest.raises(
        config.ConfigError, match=f"Could not read summary template directory {tmp_path}"
    ):
        summary_templates.discover(tmp_path, "A")


def test_load_reads_utf8_and_reports_decode_failure(tmp_path):
    path = tmp_path / "A.md"
    path.write_text("# Résumé", encoding="utf-8")
    template = summary_templates.SummaryTemplate("A", path)

    assert summary_templates.load(template) == "# Résumé"

    path.write_bytes(b"\xff")
    with pytest.raises(config.ConfigError, match=r"A\.md"):
        summary_templates.load(template)


def test_config_resolves_relative_template_directory(monkeypatch, tmp_path):
    project_config = tmp_path / "papertracker.toml"
    monkeypatch.setattr(config, "PROJECT_CONFIG_PATH", project_config)
    monkeypatch.setattr(config, "SUMMARY_TEMPLATE_DIR", "templates")
    monkeypatch.setattr(config, "DEFAULT_SUMMARY_TEMPLATE", "B")
    directory = tmp_path / "templates"
    directory.mkdir()
    (directory / "A.md").write_text("# A", encoding="utf-8")
    (directory / "B.md").write_text("# B", encoding="utf-8")

    templates, default = config.summary_template_catalog()

    assert [item.id for item in templates] == ["A", "B"]
    assert default.id == "B"
    assert config.summary_template("A").path == directory / "A.md"


def test_config_preserves_absolute_template_directory(monkeypatch, tmp_path):
    project_config = tmp_path / "config" / "papertracker.toml"
    directory = tmp_path / "templates"
    directory.mkdir()
    (directory / "A.md").write_text("# A", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_CONFIG_PATH", project_config)
    monkeypatch.setattr(config, "SUMMARY_TEMPLATE_DIR", str(directory))
    monkeypatch.setattr(config, "DEFAULT_SUMMARY_TEMPLATE", "A")

    _, default = config.summary_template_catalog()

    assert default.path == Path(directory) / "A.md"


def test_config_rejects_unknown_selected_template(monkeypatch, tmp_path):
    (tmp_path / "A.md").write_text("# A", encoding="utf-8")
    monkeypatch.setattr(config, "SUMMARY_TEMPLATE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DEFAULT_SUMMARY_TEMPLATE", "A")

    with pytest.raises(config.ConfigError, match="Unknown summary template.*B"):
        config.summary_template("B")
