"""One effort scale, forwarded verbatim to whichever provider runs."""

import importlib
from unittest import mock

import pytest

from papertracker import config, settings, summarizer


@pytest.fixture(autouse=True)
def _restore_module_effort():
    original = summarizer._REASONING_EFFORT
    yield
    summarizer.set_reasoning_effort(original)


def _isolate(monkeypatch, tmp_path, project=None):
    """Point the config layer at a fixture so the host machine cannot leak in."""
    monkeypatch.delenv("PAPERTRACKER_EFFORT", raising=False)
    path = tmp_path / "project.toml"
    if project is not None:
        path.write_text(project, encoding="utf-8")
    monkeypatch.setattr(settings, "PROJECT_CONFIG_PATH", path)


def test_precedence_runs_cli_env_config_then_builtin(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, project='reasoning_effort = "low"\n')
    monkeypatch.setattr(config, "REASONING_EFFORT", "medium")

    assert settings.resolve_effort("max")[0] == "max"

    monkeypatch.setenv("PAPERTRACKER_EFFORT", "xhigh")
    assert settings.resolve_effort(None)[0] == "xhigh"

    monkeypatch.delenv("PAPERTRACKER_EFFORT")
    effort, source = settings.resolve_effort(None)
    assert effort == "low"
    assert str(settings.PROJECT_CONFIG_PATH) in source

    (tmp_path / "project.toml").write_text("", encoding="utf-8")
    assert settings.resolve_effort(None) == (
        "medium",
        f"built-in default ({settings.PROJECT_CONFIG_PATH} has no reasoning_effort)",
    )


@pytest.mark.parametrize(
    ("source", "call"),
    [
        ("CLI flag --effort", lambda: settings.resolve_effort("ultra")),
        ("env var PAPERTRACKER_EFFORT", lambda: settings.resolve_effort(None)),
    ],
)
def test_every_layer_rejects_an_unsupported_level_by_name(monkeypatch, tmp_path, source, call):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("PAPERTRACKER_EFFORT", "ultra")

    with pytest.raises(ValueError, match="Invalid reasoning effort 'ultra'") as exc:
        call()

    assert source in str(exc.value)
    # The message has to name the alternatives; the flag is otherwise unguessable.
    assert "low, medium, high, xhigh, max" in str(exc.value)
    assert repr(settings.INHERIT_EFFORT) in str(exc.value)


def test_a_bad_value_in_a_config_file_names_the_file(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, project='reasoning_effort = "turbo"\n')

    with pytest.raises(ValueError, match="turbo") as exc:
        settings.resolve_effort(None)

    assert str(tmp_path / "project.toml") in str(exc.value)


def test_inherit_resolves_to_no_level_however_it_is_spelled(monkeypatch, tmp_path):
    """Callers get "nothing to forward" without knowing the sentinel's spelling."""
    _isolate(monkeypatch, tmp_path, project='reasoning_effort = ""\n')

    assert settings.resolve_effort(settings.INHERIT_EFFORT)[0] is None
    assert settings.resolve_effort(None)[0] is None

    monkeypatch.setenv("PAPERTRACKER_EFFORT", settings.INHERIT_EFFORT)
    assert settings.resolve_effort(None)[0] is None


@pytest.mark.parametrize("effort", settings.VALID_EFFORTS)
def test_each_level_reaches_both_providers_under_the_same_name(effort):
    """The point of the shared scale: no per-provider translation table."""
    summarizer.set_reasoning_effort(effort)

    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")

        summarizer._summarize_claude("prompt", "sonnet")
        claude_cmd = run.call_args.args[0]
        assert claude_cmd[claude_cmd.index("--effort") + 1] == effort

        summarizer._summarize_codex("prompt", "gpt-5.6-luna")
        codex_cmd = run.call_args.args[0]
        assert codex_cmd[codex_cmd.index("-c") + 1] == (f'model_reasoning_effort="{effort}"')


def test_inherit_sends_no_effort_flag_to_either_provider():
    summarizer.set_reasoning_effort(None)

    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")

        summarizer._summarize_claude("prompt", "sonnet")
        assert "--effort" not in run.call_args.args[0]

        summarizer._summarize_codex("prompt", "gpt-5.6-luna")
        assert "-c" not in run.call_args.args[0]


def test_codex_effort_override_precedes_the_prompt_placeholder():
    """`-` means read the prompt from stdin, so it has to stay the final argument."""
    summarizer.set_reasoning_effort("high")

    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")
        summarizer._summarize_codex("prompt", "gpt-5.6-luna")

    assert run.call_args.args[0][-1] == "-"


def test_the_shipped_default_is_a_level_both_providers_accept():
    assert config.REASONING_EFFORT in settings.VALID_EFFORTS


def test_a_config_file_from_before_this_key_existed_still_loads(monkeypatch, tmp_path):
    """Upgrading a checkout must not hard-fail on a key the old file cannot have."""
    original = (config.REPOSITORY_ROOT / "config.toml").read_text(encoding="utf-8")
    older = "\n".join(
        line for line in original.splitlines() if not line.startswith("reasoning_effort")
    )
    assert "reasoning_effort =" not in older
    stripped = tmp_path / "config.toml"
    stripped.write_text(older, encoding="utf-8")

    with monkeypatch.context() as m:
        m.setattr(config, "PROJECT_CONFIG_PATH", stripped)
        reloaded = importlib.reload(config)
        assert reloaded.REASONING_EFFORT == "medium"

    importlib.reload(config)
