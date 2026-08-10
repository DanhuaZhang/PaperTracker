from pathlib import Path

import pytest

from papertracker import config, summary_templates


def _write_template(
    path: Path,
    *,
    label: str = "Template",
    description: str = "Description",
    evidence: str = "abstract",
    body: str = "## Finding",
) -> None:
    path.write_text(
        "<!-- papertracker-template\n"
        f'label = "{label}"\n'
        f'description = "{description}"\n'
        f'evidence = "{evidence}"\n'
        "-->\n"
        f"{body}\n",
        encoding="utf-8",
    )


def _make_tree(tmp_path: Path) -> Path:
    """Build the two-folder layout with one template in each, ready to extend."""
    (tmp_path / "abstract").mkdir(parents=True, exist_ok=True)
    (tmp_path / "fulltext").mkdir(parents=True, exist_ok=True)
    _write_template(tmp_path / "abstract" / "screen.md", evidence="abstract")
    _write_template(tmp_path / "fulltext" / "deep.md", evidence="fulltext")
    return tmp_path


def test_discover_is_unlimited_per_folder_and_case_sensitive(tmp_path):
    _make_tree(tmp_path)
    for name in ("z.md", "A.md", "b.md"):
        _write_template(tmp_path / "abstract" / name, label=name, evidence="abstract")
    (tmp_path / "abstract" / "ignored.MD").write_text("ignored", encoding="utf-8")
    deeper = tmp_path / "abstract" / "nested"
    deeper.mkdir()
    _write_template(deeper / "nested.md")

    templates, default = summary_templates.discover(tmp_path, "z")

    # Abstract folder first, filenames case-sensitively sorted inside it.
    assert [item.id for item in templates] == ["A", "b", "screen", "z", "deep"]
    assert default.id == "z"
    assert templates[0].body == "## Finding"


def test_discover_rejects_a_template_in_the_wrong_evidence_folder(tmp_path):
    _make_tree(tmp_path)
    _write_template(tmp_path / "abstract" / "misfiled.md", evidence="fulltext")

    with pytest.raises(config.ConfigError, match="sits in the 'abstract' folder") as exc:
        summary_templates.discover(tmp_path)

    assert "misfiled" in str(exc.value)


def test_discover_points_the_old_flat_layout_at_the_new_folders(tmp_path):
    _make_tree(tmp_path)
    _write_template(tmp_path / "leftover.md")

    with pytest.raises(config.ConfigError, match="must live in an evidence subfolder") as exc:
        summary_templates.discover(tmp_path)

    assert "leftover.md" in str(exc.value)


def test_discover_names_a_missing_evidence_folder(tmp_path):
    (tmp_path / "abstract").mkdir()
    _write_template(tmp_path / "abstract" / "screen.md", evidence="abstract")

    with pytest.raises(config.ConfigError, match="Missing summary template folder") as exc:
        summary_templates.discover(tmp_path)

    assert str(tmp_path / "fulltext") in str(exc.value)


def test_discover_rejects_a_duplicate_id_across_folders(tmp_path):
    """IDs stay unique tree-wide so a bare --template ID is unambiguous."""
    _make_tree(tmp_path)
    _write_template(tmp_path / "fulltext" / "screen.md", evidence="fulltext")

    with pytest.raises(config.ConfigError, match="Duplicate summary template ID"):
        summary_templates.discover(tmp_path)


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("bad id.md", "", "Invalid summary template ID"),
        ("missing.md", "## no metadata", "Malformed summary template metadata"),
        (
            "evidence.md",
            '<!-- papertracker-template\nlabel="L"\ndescription="D"\nevidence="pdf"\n-->\n## H',
            "Unsupported evidence value",
        ),
    ],
)
def test_discover_reports_validation_failures_with_paths(
    tmp_path, filename, content, message
):
    _make_tree(tmp_path)
    path = tmp_path / "abstract" / filename
    path.write_text(content, encoding="utf-8")
    with pytest.raises(config.ConfigError, match=message) as exc:
        summary_templates.discover(tmp_path)
    assert str(path) in str(exc.value)


def test_discover_reports_unreadable_utf8_with_path(tmp_path):
    _make_tree(tmp_path)
    (tmp_path / "abstract" / "bad.md").write_bytes(b"\xff")
    with pytest.raises(config.ConfigError, match=r"bad\.md"):
        summary_templates.discover(tmp_path)


def test_config_uses_repository_root_and_evidence_specific_defaults(monkeypatch, tmp_path):
    active = _make_tree(tmp_path / "templates")
    # A relative template dir resolves against the repository root, not user_data.
    monkeypatch.setattr(config, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(config, "SUMMARY_TEMPLATE_DIR", "templates")
    monkeypatch.setattr(config, "DEFAULT_ABSTRACT_TEMPLATE", "screen")
    monkeypatch.setattr(config, "DEFAULT_FULLTEXT_TEMPLATE", "deep")

    templates, abstract_default = config.summary_template_catalog("abstract")
    _, fulltext_default = config.summary_template_catalog("fulltext")

    assert [item.id for item in templates] == ["screen", "deep"]
    assert abstract_default.id == "screen"
    assert fulltext_default.id == "deep"
    assert abstract_default.path == active / "abstract" / "screen.md"


def test_every_shipped_template_parses_with_required_headings():
    """The tracked templates are the only copy, and each one is a dropdown entry."""
    templates, _ = summary_templates.discover(
        config.REPOSITORY_ROOT / "summary_templates", "abstract-screen"
    )
    by_id = {template.id: template for template in templates}
    assert set(by_id) == {
        "abstract-screen",
        "deep-human-study",
        "deep-synthesis",
        "deep-technical",
    }
    assert by_id["abstract-screen"].evidence == "abstract"
    assert all(
        template.evidence == "fulltext"
        for key, template in by_id.items()
        if key.startswith("deep-")
    )
    assert "## Reading decision" in by_id["abstract-screen"].body
    assert "## Ablations and failure cases" in by_id["deep-technical"].body
    assert "## Ethics, accessibility, and participant risk" in by_id["deep-human-study"].body
    assert "## Taxonomy and major themes" in by_id["deep-synthesis"].body


def test_a_missing_template_directory_says_which_path_is_missing(monkeypatch, tmp_path):
    """Nothing re-creates the folder any more, so the message is the only guidance."""
    monkeypatch.setattr(config, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(config, "SUMMARY_TEMPLATE_DIR", "summary_templates")

    with pytest.raises(config.ConfigError, match="does not exist") as exc:
        config.summary_template_catalog("abstract")

    assert str(tmp_path / "summary_templates") in str(exc.value)
