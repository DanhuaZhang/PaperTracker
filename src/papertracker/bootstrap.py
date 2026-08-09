"""Small console-script wrapper that reports configuration errors cleanly."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from .cli import main as cli_main
    except Exception as exc:
        if exc.__class__.__name__ == "ConfigError" and exc.__class__.__module__.endswith(
            ".config"
        ):
            print(f"papertracker: configuration error: {exc}", file=sys.stderr)
            return 2
        raise
    return cli_main()
