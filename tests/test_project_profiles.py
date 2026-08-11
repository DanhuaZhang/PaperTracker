import pytest

from papertracker import cli, config


def _reset_projects(monkeypatch, path):
    monkeypatch.setattr(config, "PROJECTS_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_PROJECTS_CONFIG", None)


def test_missing_projects_file_is_an_error_naming_the_fix(tmp_path, monkeypatch):
    _reset_projects(monkeypatch, tmp_path / "missing.toml")

    assert config.project_profiles() == []
    with pytest.raises(config.ConfigError, match="No topics file at") as exc:
        config.resolve_project()

    # The message has to carry the fix; there is no fallback profile to soften it.
    assert "projects.example.toml" in str(exc.value)
    assert "topic_statement" in str(exc.value)


def test_projects_file_without_any_profile_is_an_error(tmp_path, monkeypatch):
    projects = tmp_path / "projects.toml"
    projects.write_text('default_project = "none"\n', encoding="utf-8")
    _reset_projects(monkeypatch, projects)

    with pytest.raises(config.ConfigError, match="defines no \\[\\[projects\\]\\]"):
        config.require_projects()


def test_missing_projects_file_stops_before_any_source_is_fetched(tmp_path, monkeypatch):
    _reset_projects(monkeypatch, tmp_path / "missing.toml")

    def _explode(*args, **kwargs):
        raise AssertionError("fetched a source despite having no topic to score against")

    monkeypatch.setattr(cli, "SOURCE_FETCHERS", dict.fromkeys(cli.SOURCE_FETCHERS, _explode))

    assert cli.main(["--no-summarize", "--days", "7"]) == 2


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
    assert profile.digest_dir == config._user_path("digests/agent-memory")
    assert profile.seen_papers_file == config._user_path("state/agent-memory/seen.json")
    assert profile.summary_cache_file == config._user_path("state/agent-memory/summary_cache.json")


def test_project_profile_parses_contribution_and_related_work_facets(tmp_path, monkeypatch):
    projects = tmp_path / "projects.toml"
    projects.write_text(
        """
arxiv_categories = ["cs.AI"]

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
topic_statement = "shared topic"
arxiv_categories = ["cs.AI"]

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
    projects.write_text(
        'topic_statement = "t"\narxiv_categories = ["cs.AI"]\n'
        '[[projects]]\nid = "known"\nname = "Known"\n',
        encoding="utf-8",
    )
    _reset_projects(monkeypatch, projects)

    with pytest.raises(config.ConfigError, match="Unknown project"):
        config.resolve_project("missing")


def test_profile_without_topic_statement_is_an_error(tmp_path, monkeypatch):
    projects = tmp_path / "projects.toml"
    projects.write_text(
        'arxiv_categories = ["cs.AI"]\n[[projects]]\nid = "bare"\nname = "Bare"\n',
        encoding="utf-8",
    )
    _reset_projects(monkeypatch, projects)

    # config.toml is topic-neutral, so there is no repository default to inherit.
    with pytest.raises(config.ConfigError, match="sets no 'topic_statement'"):
        config.project_profiles()


def test_top_level_topic_statement_covers_every_profile(tmp_path, monkeypatch):
    projects = tmp_path / "projects.toml"
    projects.write_text(
        """
topic_statement = "shared across both profiles"
arxiv_categories = ["cs.HC"]

[[projects]]
id = "one"
name = "One"

[[projects]]
id = "two"
name = "Two"
topic_statement = "its own"
""".strip(),
        encoding="utf-8",
    )
    _reset_projects(monkeypatch, projects)

    one, two = config.project_profiles()

    assert one.topic_statement == "shared across both profiles"
    assert one.arxiv_categories == ["cs.HC"]
    assert two.topic_statement == "its own"


def test_list_projects_prints_profiles(tmp_path, monkeypatch, capsys):
    projects = tmp_path / "projects.toml"
    projects.write_text(
        """
default_project = "known"
topic_statement = "shared topic"
arxiv_categories = ["cs.AI"]

[[projects]]
id = "known"
name = "Known Project"
""".strip(),
        encoding="utf-8",
    )
    _reset_projects(monkeypatch, projects)

    assert cli.main(["--list-projects"]) == 0

    assert "known\tKnown Project *" in capsys.readouterr().out
