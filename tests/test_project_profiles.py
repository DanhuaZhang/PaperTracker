import pytest

from papertracker import cli, config


def _reset_projects(monkeypatch, path):
    monkeypatch.setattr(config, "PROJECTS_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_PROJECTS_CONFIG", None)


def test_missing_projects_file_uses_legacy_profile(tmp_path, monkeypatch):
    _reset_projects(monkeypatch, tmp_path / "missing.toml")

    assert config.project_profiles() == []
    profile = config.resolve_project()

    assert profile.id is None
    assert profile.topic_statement == config.TOPIC_STATEMENT
    assert profile.digest_dir == config.DIGEST_DIR
    assert profile.seen_papers_file == config.SEEN_PAPERS_FILE


def test_project_profile_inherits_defaults_and_uses_project_state(tmp_path, monkeypatch):
    projects = tmp_path / "projects.toml"
    projects.write_text(
        """
default_project = "agent-memory"

[[projects]]
id = "agent-memory"
name = "Agent memory"
topic_statement = "memory for embodied agents"
crossref_query_hint = "embodied memory navigation"
arxiv_categories = ["cs.AI"]
relevance_threshold = 0.6
""".strip(),
        encoding="utf-8",
    )
    _reset_projects(monkeypatch, projects)

    profile = config.resolve_project()

    assert profile.id == "agent-memory"
    assert profile.name == "Agent memory"
    assert profile.topic_statement == "memory for embodied agents"
    assert profile.crossref_query_hint == "embodied memory navigation"
    assert profile.arxiv_categories == ["cs.AI"]
    assert profile.relevance_scorer == config.RELEVANCE_SCORER
    assert profile.hybrid_relevance_threshold == config.HYBRID_RELEVANCE_THRESHOLD
    assert profile.priority_venues == config.PRIORITY_VENUES
    assert profile.digest_dir == "digests/agent-memory"
    assert profile.seen_papers_file == ".papertracker/agent-memory/seen.json"
    assert profile.summary_cache_file == ".papertracker/agent-memory/summary_cache.json"


def test_project_profile_parses_contribution_and_related_work_facets(tmp_path, monkeypatch):
    projects = tmp_path / "projects.toml"
    projects.write_text(
        """
[[projects]]
id = "faceted"
name = "Faceted Project"
topic_statement = "social spatial agents"
contribution_statement = "We infer stance and generate spatial formations."

[[projects.related_work_facets]]
id = "stance"
name = "Stance inference"
description = "Inferring stance from text or behavior."
query_hint = "stance inference opinion behavior"

[[projects.related_work_facets]]
name = "Spatial formations"
description = "Generating group layouts and formations."
query_hint = "multi-agent spatial formation generation"
""".strip(),
        encoding="utf-8",
    )
    _reset_projects(monkeypatch, projects)

    profile = config.resolve_project("faceted")

    assert profile.contribution_statement == "We infer stance and generate spatial formations."
    assert [facet.id for facet in profile.related_work_facets] == [
        "stance",
        "spatial-formations",
    ]
    assert profile.related_work_facets[0].query_hint == "stance inference opinion behavior"


def test_project_profile_rejects_duplicate_ids(tmp_path, monkeypatch):
    projects = tmp_path / "projects.toml"
    projects.write_text(
        """
[[projects]]
id = "same"
name = "One"

[[projects]]
id = "same"
name = "Two"
""".strip(),
        encoding="utf-8",
    )
    _reset_projects(monkeypatch, projects)

    with pytest.raises(config.ConfigError, match="Duplicate project profile id"):
        config.project_profiles()


def test_resolve_project_rejects_unknown_id(tmp_path, monkeypatch):
    projects = tmp_path / "projects.toml"
    projects.write_text('[[projects]]\nid = "known"\nname = "Known"\n', encoding="utf-8")
    _reset_projects(monkeypatch, projects)

    with pytest.raises(config.ConfigError, match="Unknown project"):
        config.resolve_project("missing")


def test_list_projects_prints_profiles(tmp_path, monkeypatch, capsys):
    projects = tmp_path / "projects.toml"
    projects.write_text(
        """
default_project = "known"

[[projects]]
id = "known"
name = "Known Project"
""".strip(),
        encoding="utf-8",
    )
    _reset_projects(monkeypatch, projects)

    assert cli.main(["--list-projects"]) == 0

    assert "known\tKnown Project *" in capsys.readouterr().out
