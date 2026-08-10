import importlib

from papertracker import settings


def test_provider_and_model_fall_back_to_local_config(tmp_path, monkeypatch):
    project_cfg = tmp_path / "src.toml"
    project_cfg.write_text(
        'provider = "codex"\nclaude_model = "sonnet-local"\ncodex_model = "gpt-test-local"\n',
        encoding="utf-8",
    )
    user_cfg = tmp_path / "missing-user-config.toml"

    monkeypatch.setattr(settings, "PROJECT_CONFIG_PATH", project_cfg)
    monkeypatch.setattr(settings, "CONFIG_PATH", user_cfg)
    monkeypatch.delenv("PAPERTRACKER_PROVIDER", raising=False)
    monkeypatch.delenv("PAPERTRACKER_MODEL", raising=False)

    assert settings.resolve_provider(None) == (
        "codex",
        f"project config file {project_cfg}",
    )
    assert settings.resolve_model(None, "codex") == (
        "gpt-test-local",
        f"project config file {project_cfg}",
    )


def test_user_config_overrides_local_config(tmp_path, monkeypatch):
    project_cfg = tmp_path / "src.toml"
    project_cfg.write_text(
        'provider = "codex"\nclaude_model = "sonnet-project"\ncodex_model = "gpt-project"\n',
        encoding="utf-8",
    )
    user_cfg = tmp_path / "config.toml"
    user_cfg.write_text(
        'provider = "claude"\nclaude_model = "sonnet-user"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "PROJECT_CONFIG_PATH", project_cfg)
    monkeypatch.setattr(settings, "CONFIG_PATH", user_cfg)
    monkeypatch.delenv("PAPERTRACKER_PROVIDER", raising=False)
    monkeypatch.delenv("PAPERTRACKER_MODEL", raising=False)

    assert settings.resolve_provider(None) == ("claude", f"config file {user_cfg}")
    assert settings.resolve_model(None, "claude") == ("sonnet-user", f"config file {user_cfg}")


def test_generic_model_key_does_not_override_provider_specific_default(tmp_path, monkeypatch):
    project_cfg = tmp_path / "src.toml"
    project_cfg.write_text(
        """
provider = "codex"
model = "stale-generic-model"
claude_model = "sonnet-project"
codex_model = "gpt-project"
""".strip(),
        encoding="utf-8",
    )
    user_cfg = tmp_path / "missing-user-config.toml"

    monkeypatch.setattr(settings, "PROJECT_CONFIG_PATH", project_cfg)
    monkeypatch.setattr(settings, "CONFIG_PATH", user_cfg)
    monkeypatch.delenv("PAPERTRACKER_MODEL", raising=False)

    assert settings.resolve_model(None, "codex") == (
        "gpt-project",
        f"project config file {project_cfg}",
    )


def test_config_constants_load_from_project_config(tmp_path, monkeypatch):
    project_cfg = tmp_path / "src.toml"
    template_dir = tmp_path / "templates"
    (template_dir / "abstract").mkdir(parents=True)
    (template_dir / "fulltext").mkdir(parents=True)
    (template_dir / "abstract" / "Screen.md").write_text(
        '<!-- papertracker-template\nlabel="Screen"\ndescription="D"\nevidence="abstract"\n-->\n## Test',
        encoding="utf-8",
    )
    (template_dir / "fulltext" / "Deep.md").write_text(
        '<!-- papertracker-template\nlabel="Deep"\ndescription="D"\nevidence="fulltext"\n-->\n## Test',
        encoding="utf-8",
    )
    project_cfg.write_text(
        """
provider = "codex"
claude_model = "haiku-test"
codex_model = "gpt-test"
default_days = 9
max_results_per_query = 12
digest_dir = "custom-digests"
seen_papers_file = ".custom_seen.json"
summary_cache_file = ".custom_summary_cache.json"
summary_timeout_sec = 33
enabled_sources_default = ["arxiv"]
embedding_model = "test/embed"
relevance_scorer = "hybrid"
relevance_threshold = 0.12
hybrid_relevance_threshold = 0.34
enable_reranker = true
reranker_model = "test/reranker"
reranker_top_k = 7
topic_statement = "test topic"
crossref_query_hint = "test query"
arxiv_categories = ["cs.AI"]
priority_venue_only = true
priority_venues = []
user_email = "local@example.com"
user_agent_name = "papertracker-test/1.0"
zotero_data_dir = "~/TestZotero"
zotero_linked_base = "~/LinkedPapers"
summary_template_dir = "templates"
default_abstract_template = "Screen"
default_fulltext_template = "Deep"
""".strip(),
        encoding="utf-8",
    )

    import papertracker.config as config

    with monkeypatch.context() as m:
        m.setattr(config, "PROJECT_CONFIG_PATH", project_cfg)
        m.delenv("PAPERTRACKER_EMAIL", raising=False)
        m.delenv("PAPERTRACKER_ZOTERO_DIR", raising=False)
        m.delenv("PAPERTRACKER_ZOTERO_LINKED_BASE", raising=False)
        m.setenv("PAPERTRACKER_USER_DATA_DIR", str(tmp_path))

        loaded = importlib.reload(config)

        assert loaded.DEFAULT_PROVIDER == "codex"
        assert loaded.CLAUDE_MODEL == "haiku-test"
        assert loaded.CODEX_MODEL == "gpt-test"
        assert loaded.DEFAULT_DAYS == 9
        assert loaded.MAX_RESULTS_PER_QUERY == 12
        assert loaded.DIGEST_DIR == "custom-digests"
        assert loaded.SEEN_PAPERS_FILE == ".custom_seen.json"
        assert loaded.SUMMARY_CACHE_FILE == ".custom_summary_cache.json"
        assert loaded.SUMMARY_TIMEOUT_SEC == 33
        assert loaded.ENABLED_SOURCES_DEFAULT == ["arxiv"]
        assert loaded.EMBEDDING_MODEL == "test/embed"
        assert loaded.RELEVANCE_SCORER == "hybrid"
        assert loaded.RELEVANCE_THRESHOLD == 0.12
        assert loaded.HYBRID_RELEVANCE_THRESHOLD == 0.34
        assert loaded.ENABLE_RERANKER is True
        assert loaded.RERANKER_MODEL == "test/reranker"
        assert loaded.RERANKER_TOP_K == 7
        assert loaded.TOPIC_STATEMENT == "test topic"
        assert loaded.CROSSREF_QUERY_HINT == "test query"
        assert loaded.ARXIV_CATEGORIES == ["cs.AI"]
        assert loaded.PRIORITY_VENUE_ONLY is True
        assert loaded.PRIORITY_VENUES == []
        assert loaded.USER_EMAIL == "local@example.com"
        assert loaded.USER_AGENT == "papertracker-test/1.0 (mailto:local@example.com)"
        assert str(loaded.zotero_data_dir()).endswith("TestZotero")
        assert str(loaded.zotero_linked_base_dir()).endswith("LinkedPapers")
        # A relative summary_template_dir resolves against the repository root,
        # so point that at the fixture too.
        m.setattr(loaded, "REPOSITORY_ROOT", tmp_path)
        templates, default = loaded.summary_template_catalog()
        # Ordered by (evidence folder, filename), so abstract sorts before fulltext.
        assert [template.id for template in templates] == ["Screen", "Deep"]
        assert default.id == "Screen"
        assert default.path == template_dir / "abstract" / "Screen.md"
        _, deep = loaded.summary_template_catalog("fulltext")
        assert deep.id == "Deep"

    importlib.reload(config)


def test_config_requires_project_config_values(tmp_path, monkeypatch):
    project_cfg = tmp_path / "src.toml"
    project_cfg.write_text('provider = "codex"\n', encoding="utf-8")

    import papertracker.config as config

    with monkeypatch.context() as m:
        m.setattr(config, "PROJECT_CONFIG_PATH", project_cfg)
        try:
            importlib.reload(config)
        except config.ConfigError as exc:
            assert "Missing required setting" in str(exc)
            assert "claude_model" in str(exc)
        else:
            raise AssertionError("Expected incomplete project config to fail")

    importlib.reload(config)
