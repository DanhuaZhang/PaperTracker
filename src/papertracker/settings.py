"""Provider/model resolution with explicit precedence.

Order (first non-empty wins):
  1. CLI flag
  2. PAPERTRACKER_* env var
  3. ~/.config/papertracker/config.toml
  4. Built-in default from config.py
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from . import config

CONFIG_PATH = Path.home() / ".config" / "papertracker" / "config.toml"

_VALID_PROVIDERS = ("claude", "codex")


def _load_toml_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        with CONFIG_PATH.open("rb") as f:
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

    toml_cfg = _load_toml_config()
    if "provider" in toml_cfg:
        prov = toml_cfg["provider"]
        if prov not in _VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider in {CONFIG_PATH}: {prov!r}. "
                f"Choose one of: {', '.join(_VALID_PROVIDERS)}"
            )
        return prov, f"config file {CONFIG_PATH}"

    return config.DEFAULT_PROVIDER, "built-in default"


def resolve_model(cli_arg: str | None, provider: str) -> tuple[str, str]:
    """Return (model, source_description) for the given provider."""
    if cli_arg:
        return cli_arg, "CLI flag --model"

    env = os.environ.get("PAPERTRACKER_MODEL")
    if env:
        return env, "env var PAPERTRACKER_MODEL"

    toml_cfg = _load_toml_config()
    if "model" in toml_cfg:
        return toml_cfg["model"], f"config file {CONFIG_PATH}"

    default = config.CLAUDE_MODEL if provider == "claude" else config.CODEX_MODEL
    return default, "built-in default"
