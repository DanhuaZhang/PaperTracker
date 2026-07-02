import importlib

from papertracker import settings


def test_provider_and_model_fall_back_to_local_config(tmp_path, monkeypatch):
    project_cfg = tmp_path / "papertracker.toml"
    project_cfg.write_text(
        'provider = "codex"\nmodel = "gpt-test-local"\n',
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
    project_cfg = tmp_path / "papertracker.toml"
    project_cfg.write_text(
        'provider = "codex"\nmodel = "gpt-project"\n',
        encoding="utf-8",
    )
    user_cfg = tmp_path / "config.toml"
    user_cfg.write_text(
        'provider = "claude"\nmodel = "sonnet-user"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "PROJECT_CONFIG_PATH", project_cfg)
    monkeypatch.setattr(settings, "CONFIG_PATH", user_cfg)
    monkeypatch.delenv("PAPERTRACKER_PROVIDER", raising=False)
    monkeypatch.delenv("PAPERTRACKER_MODEL", raising=False)

    assert settings.resolve_provider(None) == ("claude", f"config file {user_cfg}")
    assert settings.resolve_model(None, "claude") == ("sonnet-user", f"config file {user_cfg}")


def test_config_constants_load_from_project_config(tmp_path, monkeypatch):
    project_cfg = tmp_path / "papertracker.toml"
    project_cfg.write_text(
        """
provider = "codex"
model = "gpt-active"
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
relevance_threshold = 0.12
topic_statement = "test topic"
crossref_query_hint = "test query"
arxiv_categories = ["cs.AI"]
priority_venue_only = true
priority_venues = []
user_email = "local@example.com"
user_agent_name = "papertracker-test/1.0"
zotero_data_dir = "~/TestZotero"
zotero_linked_base = "~/LinkedPapers"
obsidian_template = "## Test"
""".strip(),
        encoding="utf-8",
    )

    import papertracker.config as config

    with monkeypatch.context() as m:
        m.setattr(config, "PROJECT_CONFIG_PATH", project_cfg)
        m.delenv("PAPERTRACKER_EMAIL", raising=False)
        m.delenv("PAPERTRACKER_ZOTERO_DIR", raising=False)
        m.delenv("PAPERTRACKER_ZOTERO_LINKED_BASE", raising=False)
        m.delenv("PAPERTRACKER_OBSIDIAN_TEMPLATE", raising=False)

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
        assert loaded.RELEVANCE_THRESHOLD == 0.12
        assert loaded.TOPIC_STATEMENT == "test topic"
        assert loaded.CROSSREF_QUERY_HINT == "test query"
        assert loaded.ARXIV_CATEGORIES == ["cs.AI"]
        assert loaded.PRIORITY_VENUE_ONLY is True
        assert loaded.PRIORITY_VENUES == []
        assert loaded.USER_EMAIL == "local@example.com"
        assert loaded.USER_AGENT == "papertracker-test/1.0 (mailto:local@example.com)"
        assert str(loaded.zotero_data_dir()).endswith("TestZotero")
        assert str(loaded.zotero_linked_base_dir()).endswith("LinkedPapers")
        assert loaded.obsidian_template() == "## Test"

    importlib.reload(config)


def test_config_requires_project_config_values(tmp_path, monkeypatch):
    project_cfg = tmp_path / "papertracker.toml"
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
