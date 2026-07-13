"""Discovery and loading of Markdown summary skeletons."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass(frozen=True)
class SummaryTemplate:
    """A selectable Markdown summary skeleton."""

    id: str
    path: Path


def discover(
    directory: Path, default_id: str
) -> tuple[tuple[SummaryTemplate, ...], SummaryTemplate]:
    """Return direct-child Markdown templates and the configured default."""
    if not directory.exists():
        raise config.ConfigError(f"Summary template directory does not exist: {directory}")
    if not directory.is_dir():
        raise config.ConfigError(f"Summary template path is not a directory: {directory}")

    try:
        templates = tuple(
            SummaryTemplate(path.stem, path)
            for path in sorted(directory.iterdir(), key=lambda item: item.name)
            if path.is_file() and path.suffix == ".md"
        )
    except OSError as exc:
        raise config.ConfigError(
            f"Could not read summary template directory {directory}: {exc}"
        ) from exc
    if not templates:
        raise config.ConfigError(
            f"Summary template directory contains no .md templates: {directory}"
        )

    by_id = {template.id: template for template in templates}
    if len(by_id) != len(templates):
        raise config.ConfigError(
            f"Summary template directory has duplicate IDs: {directory}"
        )
    if default_id not in by_id:
        raise config.ConfigError(
            f"Configured default summary template {default_id!r} was not found in {directory}"
        )
    return templates, by_id[default_id]


def load(template: SummaryTemplate) -> str:
    """Read one template as UTF-8, reporting its path on failure."""
    try:
        return template.path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise config.ConfigError(
            f"Could not read summary template {template.path}: {exc}"
        ) from exc
