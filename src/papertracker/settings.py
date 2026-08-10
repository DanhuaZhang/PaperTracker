"""Provider/model/effort resolution with explicit precedence.

Two layers, in this order: CLI flag, then environment variable, then the
repository `config.toml`. Model reads the selected provider's `claude_model` or
`codex_model` key; effort reads `reasoning_effort`.

There is deliberately no per-user config file. Secrets belong in the
environment, where they cannot be committed; every other setting belongs in
`config.toml`, where one file explains a run.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from . import config

PROJECT_CONFIG_PATH = config.PROJECT_CONFIG_PATH

_VALID_PROVIDERS = ("claude", "codex")

# The reasoning levels both CLIs accept under these names, weakest first. Claude
# Code's `--effort` takes exactly this set; Codex accepts it for the models
# PaperTracker defaults to. Sharing the vocabulary is what lets a level be
# forwarded verbatim instead of translated, so it carries the same meaning
# whichever provider runs. Codex-only levels ("minimal", and "ultra" on some
# models) are deliberately absent — Claude Code has no equivalent to map them to.
VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")

# Send no effort flag at all and let each CLI apply its own built-in default.
# Spelled the same way on the command line, in the environment, and in TOML; an
# empty string means the same thing, since that is the natural way to write
# "unset" in a config file.
INHERIT_EFFORT = "default"
_INHERIT_SPELLINGS = (INHERIT_EFFORT, "")


def _load_toml_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def resolve_provider(cli_arg: str | None) -> tuple[str, str]:
    """Return (provider, source_description)."""
    if cli_arg:
        if cli_arg not in _VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider {cli_arg!r}. Choose one of: {', '.join(_VALID_PROVIDERS)}"
            )
        return cli_arg, "CLI flag --provider"

    env = os.environ.get("PAPERTRACKER_PROVIDER")
    if env:
        if env not in _VALID_PROVIDERS:
            raise ValueError(
                f"Invalid PAPERTRACKER_PROVIDER={env!r}. "
                f"Choose one of: {', '.join(_VALID_PROVIDERS)}"
            )
        return env, "env var PAPERTRACKER_PROVIDER"

    project_cfg = _load_toml_config(PROJECT_CONFIG_PATH)
    if "provider" in project_cfg:
        prov = project_cfg["provider"]
        if prov not in _VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider in {PROJECT_CONFIG_PATH}: {prov!r}. "
                f"Choose one of: {', '.join(_VALID_PROVIDERS)}"
            )
        return prov, f"project config file {PROJECT_CONFIG_PATH}"

    return config.DEFAULT_PROVIDER, f"project config file {PROJECT_CONFIG_PATH}"


def resolve_model(cli_arg: str | None, provider: str) -> tuple[str, str]:
    """Return (model, source_description) for the given provider."""
    if cli_arg:
        return cli_arg, "CLI flag --model"

    env = os.environ.get("PAPERTRACKER_MODEL")
    if env:
        return env, "env var PAPERTRACKER_MODEL"

    model_key = f"{provider}_model"

    project_cfg = _load_toml_config(PROJECT_CONFIG_PATH)
    if model_key in project_cfg:
        return project_cfg[model_key], f"project config file {PROJECT_CONFIG_PATH}"

    default = config.CLAUDE_MODEL if provider == "claude" else config.CODEX_MODEL
    return default, f"provider fallback in {PROJECT_CONFIG_PATH}"


def _validated_effort(value: object, origin: str) -> str | None:
    """Normalize one layer's value, or explain what the accepted ones are.

    Returns None for "inherit", so callers get a level to forward or nothing to
    forward and never have to know how the sentinel is spelled.
    """
    if value in _INHERIT_SPELLINGS:
        return None
    if value not in VALID_EFFORTS:
        raise ValueError(
            f"Invalid reasoning effort {value!r} in {origin}. Choose one of: "
            f"{', '.join(VALID_EFFORTS)}, or {INHERIT_EFFORT!r} to let each "
            "provider apply its own."
        )
    return str(value)


def resolve_effort(cli_arg: str | None) -> tuple[str | None, str]:
    """Return (effort, source_description), shared by both providers.

    An effort of None means forward no effort flag at all.
    """
    if cli_arg is not None:
        return _validated_effort(cli_arg, "CLI flag --effort"), "CLI flag --effort"

    env = os.environ.get("PAPERTRACKER_EFFORT")
    if env is not None:
        origin = "env var PAPERTRACKER_EFFORT"
        return _validated_effort(env, origin), origin

    project_cfg = _load_toml_config(PROJECT_CONFIG_PATH)
    if "reasoning_effort" in project_cfg:
        origin = f"project config file {PROJECT_CONFIG_PATH}"
        return _validated_effort(project_cfg["reasoning_effort"], origin), origin

    origin = f"built-in default ({PROJECT_CONFIG_PATH} has no reasoning_effort)"
    return _validated_effort(config.REASONING_EFFORT, origin), origin
