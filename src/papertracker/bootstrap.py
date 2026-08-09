"""Small console-script wrapper that reports configuration errors cleanly."""

from __future__ import annotations

import sys


def _force_utf8_output() -> None:
    """Make stdout/stderr UTF-8 on Windows so digest output survives redirection.

    Paper titles are arbitrary Unicode and the terminal listing prints ★, · and
    —. Windows picks the ANSI code page (usually cp1252) for a redirected
    stream, so `papertracker > out.txt` raises UnicodeEncodeError on the first
    accented author name. POSIX is left alone: it is already UTF-8, and
    overriding a deliberate locale there would be the surprising choice.
    """
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        # Absent under pytest's capture and any other non-TextIOWrapper stream.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main() -> int:
    _force_utf8_output()
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
