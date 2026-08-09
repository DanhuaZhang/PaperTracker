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


def test_discover_is_unlimited_direct_child_and_case_sensitive(tmp_path):
    for name in ("z.md", "A.md", "b.md", "ignored.MD"):
        if name.endswith(".md"):
            _write_template(tmp_path / name, label=name)
        else:
            (tmp_path / name).write_text("ignored", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    _write_template(nested / "nested.md")

    templates, default = summary_templates.discover(tmp_path, "z")

    assert [item.id for item in templates] == ["A", "b", "z"]
    assert default.id == "z"
    assert templates[0].body == "## Finding"


def test_first_use_seeds_and_never_overwrites(tmp_path):
    samples = tmp_path / "samples"
    active = tmp_path / "active"
    samples.mkdir()
    _write_template(samples / "one.md", label="One")

    assert summary_templates.seed_if_empty(active, samples) is True
    seeded = active.joinpath("one.md").read_text(encoding="utf-8")
    assert summary_templates.seed_if_empty(active, samples) is False
    assert active.joinpath("one.md").read_text(encoding="utf-8") == seeded


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
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    with pytest.raises(config.ConfigError, match=message) as exc:
        summary_templates.discover(tmp_path)
    assert str(path) in str(exc.value)


def test_discover_reports_unreadable_utf8_with_path(tmp_path):
    path = tmp_path / "bad.md"
    path.write_bytes(b"\xff")
    with pytest.raises(config.ConfigError, match=r"bad\.md"):
        summary_templates.discover(tmp_path)


def test_config_uses_repository_root_and_evidence_specific_defaults(monkeypatch, tmp_path):
    active = tmp_path / "templates"
    active.mkdir()
    _write_template(active / "screen.md", evidence="abstract")
    _write_template(active / "deep.md", evidence="fulltext")
    # In a source checkout a relative template dir resolves against the
    # repository root, not user_data.
    monkeypatch.setattr(config, "_IN_SOURCE_CHECKOUT", True)
    monkeypatch.setattr(config, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(config, "USER_DATA_DIR", tmp_path / "user_data")
    monkeypatch.setattr(config, "SUMMARY_TEMPLATE_DIR", "templates")
    monkeypatch.setattr(config, "DEFAULT_ABSTRACT_TEMPLATE", "screen")
    monkeypatch.setattr(config, "DEFAULT_FULLTEXT_TEMPLATE", "deep")

    templates, abstract_default = config.summary_template_catalog("abstract")
    _, fulltext_default = config.summary_template_catalog("fulltext")

    assert [item.id for item in templates] == ["deep", "screen"]
    assert abstract_default.id == "screen"
    assert fulltext_default.id == "deep"
    assert abstract_default.path == active / "screen.md"


def test_every_bundled_sample_parses_with_required_headings():
    templates, _ = summary_templates.discover(
        config.BUNDLED_TEMPLATE_DIR, "abstract-screen"
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


def _point_config_at(monkeypatch, root: Path, user_data: Path) -> None:
    monkeypatch.setattr(config, "_IN_SOURCE_CHECKOUT", True)
    monkeypatch.setattr(config, "REPOSITORY_ROOT", root)
    monkeypatch.setattr(config, "USER_DATA_DIR", user_data)
    monkeypatch.setattr(config, "SUMMARY_TEMPLATE_DIR", "summary_templates")
    monkeypatch.setattr(config, "DEFAULT_ABSTRACT_TEMPLATE", "screen")
    monkeypatch.setattr(config, "DEFAULT_FULLTEXT_TEMPLATE", "deep")


def test_templates_customized_in_the_old_user_data_location_are_carried_forward(
    monkeypatch, tmp_path
):
    """Moving the directory to the repo root must not orphan a user's edits."""
    root = tmp_path / "repo"
    user_data = root / "user_data"
    legacy = user_data / "summary_templates"
    legacy.mkdir(parents=True)
    _write_template(legacy / "screen.md", evidence="abstract", body="## Customized")
    _write_template(legacy / "deep.md", evidence="fulltext")
    _point_config_at(monkeypatch, root, user_data)

    templates, default = config.summary_template_catalog("abstract")

    assert [item.id for item in templates] == ["deep", "screen"]
    assert default.path == root / "summary_templates" / "screen.md"
    assert default.body == "## Customized"
    # Copied, not moved — the old directory is left intact for the user to remove.
    assert (legacy / "screen.md").is_file()


def test_bundled_samples_seed_when_there_is_no_old_directory(monkeypatch, tmp_path):
    root = tmp_path / "repo"
    user_data = root / "user_data"
    user_data.mkdir(parents=True)
    monkeypatch.setattr(config, "DEFAULT_ABSTRACT_TEMPLATE", "abstract-screen")
    monkeypatch.setattr(config, "DEFAULT_FULLTEXT_TEMPLATE", "deep-technical")
    monkeypatch.setattr(config, "_IN_SOURCE_CHECKOUT", True)
    monkeypatch.setattr(config, "REPOSITORY_ROOT", root)
    monkeypatch.setattr(config, "USER_DATA_DIR", user_data)
    monkeypatch.setattr(config, "SUMMARY_TEMPLATE_DIR", "summary_templates")

    templates, _ = config.summary_template_catalog("abstract")

    assert [item.id for item in templates] == [
        "abstract-screen",
        "deep-human-study",
        "deep-synthesis",
        "deep-technical",
    ]
    assert (root / "summary_templates" / "abstract-screen.md").is_file()
