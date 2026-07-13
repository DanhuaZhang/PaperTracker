"""Provider/model resolution with explicit precedence.

Provider order: CLI flag, environment variable, personal config, project config.
Model order: CLI flag, environment variable, then the selected provider's
`claude_model` or `codex_model` key from personal config or project config.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from . import config

CONFIG_PATH = Path.home() / ".config" / "papertracker" / "config.toml"
PROJECT_CONFIG_PATH = config.PROJECT_CONFIG_PATH

_VALID_PROVIDERS = ("claude", "codex")


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

    toml_cfg = _load_toml_config(CONFIG_PATH)
    if "provider" in toml_cfg:
        prov = toml_cfg["provider"]
        if prov not in _VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider in {CONFIG_PATH}: {prov!r}. "
                f"Choose one of: {', '.join(_VALID_PROVIDERS)}"
            )
        return prov, f"config file {CONFIG_PATH}"

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

    toml_cfg = _load_toml_config(CONFIG_PATH)
    if model_key in toml_cfg:
        return toml_cfg[model_key], f"config file {CONFIG_PATH}"

    project_cfg = _load_toml_config(PROJECT_CONFIG_PATH)
    if model_key in project_cfg:
        return project_cfg[model_key], f"project config file {PROJECT_CONFIG_PATH}"

    default = config.CLAUDE_MODEL if provider == "claude" else config.CODEX_MODEL
    return default, f"provider fallback in {PROJECT_CONFIG_PATH}"
