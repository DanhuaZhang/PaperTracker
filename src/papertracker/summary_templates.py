"""User-owned, evidence-aware Markdown summary templates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from . import config


TEMPLATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EVIDENCE_TYPES = frozenset({"abstract", "fulltext"})
_HEADER_RE = re.compile(
    r"\A<!--[ \t]*papertracker-template[ \t]*\r?\n"
    r"(?P<metadata>.*?)\r?\n-->[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)
_REQUIRED_METADATA = frozenset({"label", "description", "evidence"})


@dataclass(frozen=True)
class SummaryTemplate:
    """A selectable Markdown summary skeleton and its parsed metadata."""

    id: str
    path: Path
    label: str = ""
    description: str = ""
    evidence: str = "abstract"
    body: str = ""

    @property
    def metadata(self) -> dict[str, str]:
        return {
            "label": self.label,
            "description": self.description,
            "evidence": self.evidence,
        }


def discover(
    directory: Path, default_id: str | None = None
) -> tuple[tuple[SummaryTemplate, ...], SummaryTemplate | None]:
    """Return validated direct-child templates in case-sensitive filename order."""
    if not directory.exists():
        raise config.ConfigError(f"Summary template directory does not exist: {directory}")
    if not directory.is_dir():
        raise config.ConfigError(f"Summary template path is not a directory: {directory}")

    try:
        paths = sorted(
            (
                path for path in directory.iterdir()
                if path.is_file() and path.suffix == ".md"
            ),
            key=lambda path: path.name,
        )
    except OSError as exc:
        raise config.ConfigError(
            f"Could not read summary template directory {directory}: {exc}"
        ) from exc
    if not paths:
        raise config.ConfigError(
            f"Summary template directory contains no .md templates: {directory}"
        )

    templates: list[SummaryTemplate] = []
    seen_ids: dict[str, Path] = {}
    for path in paths:
        template_id = path.stem
        if not TEMPLATE_ID_RE.fullmatch(template_id):
            raise config.ConfigError(
                f"Invalid summary template ID {template_id!r} at {path}; IDs must match "
                "[A-Za-z0-9][A-Za-z0-9._-]*"
            )
        if template_id in seen_ids:
            raise config.ConfigError(
                f"Duplicate summary template ID {template_id!r}: "
                f"{seen_ids[template_id]} and {path}"
            )
        seen_ids[template_id] = path
        templates.append(_parse_template(template_id, path))

    by_id = {template.id: template for template in templates}
    default = None
    if default_id is not None:
        default = by_id.get(default_id)
        if default is None:
            raise config.ConfigError(
                f"Configured default summary template {default_id!r} was not found in "
                f"{directory}"
            )
    return tuple(templates), default


def _parse_template(template_id: str, path: Path) -> SummaryTemplate:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise config.ConfigError(f"Could not read summary template {path}: {exc}") from exc

    match = _HEADER_RE.match(raw)
    if match is None:
        raise config.ConfigError(
            f"Malformed summary template metadata in {path}: the file must begin with "
            "<!-- papertracker-template"
        )
    try:
        metadata = tomllib.loads(match.group("metadata"))
    except tomllib.TOMLDecodeError as exc:
        raise config.ConfigError(
            f"Malformed summary template metadata in {path}: {exc}"
        ) from exc
    missing = sorted(_REQUIRED_METADATA - metadata.keys())
    unknown = sorted(metadata.keys() - _REQUIRED_METADATA)
    if missing:
        raise config.ConfigError(
            f"Malformed summary template metadata in {path}: missing "
            f"{', '.join(missing)}"
        )
    if unknown:
        raise config.ConfigError(
            f"Malformed summary template metadata in {path}: unsupported keys "
            f"{', '.join(unknown)}"
        )
    for key in _REQUIRED_METADATA:
        if not isinstance(metadata[key], str) or not metadata[key].strip():
            raise config.ConfigError(
                f"Malformed summary template metadata in {path}: {key} must be a "
                "non-empty string"
            )
    evidence = metadata["evidence"].strip()
    if evidence not in EVIDENCE_TYPES:
        choices = ", ".join(sorted(EVIDENCE_TYPES))
        raise config.ConfigError(
            f"Unsupported evidence value {evidence!r} in {path}; expected {choices}"
        )
    body = raw[match.end():].strip()
    if not body:
        raise config.ConfigError(f"Summary template body is empty: {path}")
    return SummaryTemplate(
        id=template_id,
        path=path,
        label=metadata["label"].strip(),
        description=metadata["description"].strip(),
        evidence=evidence,
        body=body,
    )


def load(template: SummaryTemplate) -> str:
    """Return the skeleton without its PaperTracker metadata header."""
    if template.body:
        return template.body
    # Retain a useful path for programmatic templates constructed by callers.
    try:
        raw = template.path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise config.ConfigError(
            f"Could not read summary template {template.path}: {exc}"
        ) from exc
    match = _HEADER_RE.match(raw)
    return raw[match.end():].strip() if match else raw


def compatibility(template: SummaryTemplate, paper: dict) -> tuple[bool, str | None]:
    """Return whether ``paper`` can provide the template's required evidence."""
    if template.evidence == "abstract":
        if (paper.get("abstract") or "").strip():
            return True, None
        return False, "abstract required but unavailable"

    value = paper.get("pdf_path")
    if not value:
        return False, "readable local PDF required"
    path = Path(value).expanduser()
    try:
        with path.open("rb"):
            pass
    except OSError as exc:
        return False, f"readable local PDF required ({exc})"
    if not path.is_file():
        return False, "readable local PDF required"
    return True, None
