"""Project and project-profile configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
import tomllib
from pathlib import Path

from . import related_work

PROJECT_CONFIG_PATH = globals().get(
    "PROJECT_CONFIG_PATH",
    Path(__file__).resolve().parents[2] / "papertracker.toml",
)
PROJECTS_CONFIG_PATH = globals().get(
    "PROJECTS_CONFIG_PATH",
    Path(__file__).resolve().parents[2] / "projects.toml",
)


def _load_project_config() -> dict:
    if not PROJECT_CONFIG_PATH.is_file():
        return {}
    try:
        with PROJECT_CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


_PROJECT_CONFIG = _load_project_config()
_PROJECTS_CONFIG: dict | None = None


class ConfigError(RuntimeError):
    """Raised when the project config file is missing a required setting."""


def _cfg(key: str):
    try:
        return _PROJECT_CONFIG[key]
    except KeyError as exc:
        raise ConfigError(f"Missing required setting {key!r} in {PROJECT_CONFIG_PATH}") from exc


def _load_projects_config() -> dict:
    if not PROJECTS_CONFIG_PATH.is_file():
        return {}
    try:
        with PROJECTS_CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    except OSError as exc:
        raise ConfigError(f"Could not read {PROJECTS_CONFIG_PATH}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {PROJECTS_CONFIG_PATH}: {exc}") from exc


DEFAULT_PROVIDER = _cfg("provider")
CLAUDE_MODEL = _cfg("claude_model")
CODEX_MODEL = _cfg("codex_model")

# CrossRef / OpenAlex polite-pool identifier. Set PAPERTRACKER_EMAIL in your shell
# (or leave unset for anonymous requests — works, but with lower rate-limit priority).
# Nothing is sent *from* this email; it's only included in outbound request metadata
# (HTTP User-Agent for CrossRef, ?mailto= for OpenAlex) so the APIs can identify and
# preferentially serve identified clients.
USER_EMAIL = os.environ.get("PAPERTRACKER_EMAIL", _cfg("user_email"))
USER_AGENT_NAME = _cfg("user_agent_name")
USER_AGENT = (
    f"{USER_AGENT_NAME} (mailto:{USER_EMAIL})" if USER_EMAIL
    else USER_AGENT_NAME
)
OPENALEX_API_KEY = os.environ.get("PAPERTRACKER_OPENALEX_API_KEY", "").strip()

# Embedding-based relevance filter (replaces the old keyword filter).
# Each paper's (title + abstract) is embedded with the model below and compared
# to the TOPIC_STATEMENT vector via cosine similarity. Papers scoring at or above
# RELEVANCE_THRESHOLD are kept.
EMBEDDING_MODEL = _cfg("embedding_model")
RELEVANCE_THRESHOLD = _cfg("relevance_threshold")

TOPIC_STATEMENT = _cfg("topic_statement")

# Loose keyword hint passed to CrossRef's `query` parameter to bias its ranking
# (NOT a strict filter — that's done by the embedding model post-fetch).
CROSSREF_QUERY_HINT = _cfg("crossref_query_hint")

# arXiv categories to query (will be OR'd in the search_query)
ARXIV_CATEGORIES = _cfg("arxiv_categories")

# Priority venues — used for filtering and "★ priority" badge in the digest.
# `patterns` are case-insensitive substrings matched against CrossRef container-title.
# `rss` is optional; when present, journal_rss source will also poll it.
PRIORITY_VENUES = _cfg("priority_venues")

# If True, drop CrossRef/RSS results that don't match any PRIORITY_VENUES entry
PRIORITY_VENUE_ONLY = _cfg("priority_venue_only")

DEFAULT_DAYS = _cfg("default_days")
# Per-source upper cap. Each source paginates up to this many results. Embedding
# is local and free, so generous is fine. Raise further if you regularly fetch
# conference-deposit windows (CHI/SIGGRAPH can deposit 1000+ papers in one day).
MAX_RESULTS_PER_QUERY = _cfg("max_results_per_query")
DIGEST_DIR = _cfg("digest_dir")
SEEN_PAPERS_FILE = _cfg("seen_papers_file")
# Persistent cache of LLM summaries keyed by canonical_id; lets re-runs reuse summaries
# instead of re-spending tokens. Bypass/overwrite with --refresh-summaries.
SUMMARY_CACHE_FILE = _cfg("summary_cache_file")
SUMMARY_TIMEOUT_SEC = _cfg("summary_timeout_sec")
ENABLED_SOURCES_DEFAULT = _cfg("enabled_sources_default")


@dataclass(frozen=True)
class ProjectProfile:
    """Runnable topic profile loaded from ``projects.toml`` or legacy defaults."""

    id: str | None
    name: str
    topic_statement: str
    crossref_query_hint: str
    arxiv_categories: list[str]
    relevance_threshold: float
    priority_venues: list[dict]
    priority_venue_only: bool
    enabled_sources_default: list[str]
    digest_dir: str
    seen_papers_file: str
    summary_cache_file: str
    contribution_statement: str | None = None
    related_work_facets: list[related_work.RelatedWorkFacet] = field(default_factory=list)


_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _profile_value(raw: dict, key: str, default):
    return raw[key] if key in raw else default


def _optional_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _project_state_path(project_id: str, filename: str) -> str:
    return str(Path(".papertracker") / project_id / filename)


def _profile_from_project(raw: dict) -> ProjectProfile:
    project_id = raw.get("id")
    if not isinstance(project_id, str) or not _PROJECT_ID_RE.fullmatch(project_id):
        raise ConfigError(
            f"Project profile IDs in {PROJECTS_CONFIG_PATH} must match "
            "[a-z0-9][a-z0-9_-]*"
        )

    name = raw.get("name", project_id)
    if not isinstance(name, str) or not name.strip():
        raise ConfigError(f"Project {project_id!r} has an invalid name")

    try:
        related_work_facets = [
            related_work.facet_from_mapping(item)
            for item in list(_profile_value(raw, "related_work_facets", []))
        ]
    except related_work.RelatedWorkError as exc:
        raise ConfigError(f"Project {project_id!r} has invalid related_work_facets: {exc}") from exc

    return ProjectProfile(
        id=project_id,
        name=name,
        topic_statement=_profile_value(raw, "topic_statement", TOPIC_STATEMENT),
        crossref_query_hint=_profile_value(raw, "crossref_query_hint", CROSSREF_QUERY_HINT),
        arxiv_categories=list(_profile_value(raw, "arxiv_categories", ARXIV_CATEGORIES)),
        relevance_threshold=float(_profile_value(raw, "relevance_threshold", RELEVANCE_THRESHOLD)),
        priority_venues=list(_profile_value(raw, "priority_venues", PRIORITY_VENUES)),
        priority_venue_only=bool(_profile_value(raw, "priority_venue_only", PRIORITY_VENUE_ONLY)),
        enabled_sources_default=list(
            _profile_value(raw, "enabled_sources_default", ENABLED_SOURCES_DEFAULT)
        ),
        digest_dir=str(_profile_value(raw, "digest_dir", Path(DIGEST_DIR) / project_id)),
        seen_papers_file=str(
            _profile_value(raw, "seen_papers_file", _project_state_path(project_id, "seen.json"))
        ),
        summary_cache_file=str(
            _profile_value(
                raw,
                "summary_cache_file",
                _project_state_path(project_id, "summary_cache.json"),
            )
        ),
        contribution_statement=_optional_str(_profile_value(raw, "contribution_statement", None)),
        related_work_facets=related_work_facets,
    )


def legacy_profile() -> ProjectProfile:
    """Single-topic fallback profile using the root ``papertracker.toml`` settings."""
    return ProjectProfile(
        id=None,
        name="PaperTracker",
        topic_statement=TOPIC_STATEMENT,
        crossref_query_hint=CROSSREF_QUERY_HINT,
        arxiv_categories=list(ARXIV_CATEGORIES),
        relevance_threshold=RELEVANCE_THRESHOLD,
        priority_venues=list(PRIORITY_VENUES),
        priority_venue_only=PRIORITY_VENUE_ONLY,
        enabled_sources_default=list(ENABLED_SOURCES_DEFAULT),
        digest_dir=DIGEST_DIR,
        seen_papers_file=SEEN_PAPERS_FILE,
        summary_cache_file=SUMMARY_CACHE_FILE,
        contribution_statement=None,
        related_work_facets=[],
    )


def project_profiles() -> list[ProjectProfile]:
    """Return configured project profiles, or [] when ``projects.toml`` is absent."""
    global _PROJECTS_CONFIG
    if _PROJECTS_CONFIG is None:
        _PROJECTS_CONFIG = _load_projects_config()
    raw_projects = _PROJECTS_CONFIG.get("projects", []) if _PROJECTS_CONFIG else []
    profiles = [_profile_from_project(raw) for raw in raw_projects]
    seen: set[str] = set()
    for profile in profiles:
        assert profile.id is not None
        if profile.id in seen:
            raise ConfigError(f"Duplicate project profile id {profile.id!r} in {PROJECTS_CONFIG_PATH}")
        seen.add(profile.id)
    return profiles


def default_project_id() -> str | None:
    global _PROJECTS_CONFIG
    if _PROJECTS_CONFIG is None:
        _PROJECTS_CONFIG = _load_projects_config()
    default = _PROJECTS_CONFIG.get("default_project") if _PROJECTS_CONFIG else None
    if default is not None and not isinstance(default, str):
        raise ConfigError(f"default_project in {PROJECTS_CONFIG_PATH} must be a string")
    return default


def resolve_project(project_id: str | None = None) -> ProjectProfile:
    """Resolve a requested/default project profile, falling back to legacy config."""
    profiles = project_profiles()
    if not profiles:
        if project_id:
            raise ConfigError(f"No {PROJECTS_CONFIG_PATH} exists; cannot use --project {project_id!r}")
        return legacy_profile()

    requested = project_id or default_project_id() or profiles[0].id
    for profile in profiles:
        if profile.id == requested:
            return profile
    choices = ", ".join(p.id or "" for p in profiles)
    raise ConfigError(f"Unknown project {requested!r}. Available projects: {choices}")


# --- Zotero integration -----------------------------------------------------
# Default macOS/Linux data dir is ~/Zotero. Override with PAPERTRACKER_ZOTERO_DIR.
def zotero_data_dir() -> Path:
    env = os.environ.get("PAPERTRACKER_ZOTERO_DIR")
    default = _cfg("zotero_data_dir")
    return Path(env).expanduser() if env else Path(default).expanduser()


def zotero_linked_base_dir() -> Path | None:
    """Base dir for Zotero 'Linked Attachment Base Directory' (ZotFile-style)."""
    env = os.environ.get("PAPERTRACKER_ZOTERO_LINKED_BASE")
    default = _cfg("zotero_linked_base")
    if env:
        return Path(env).expanduser()
    return Path(default).expanduser() if default else None


# --- Obsidian deep-summary template ----------------------------------------
DEFAULT_OBSIDIAN_TEMPLATE = _cfg("obsidian_template")


# Path to the user's Obsidian paper-note template. When unset, DEFAULT below is used.
def obsidian_template() -> str:
    env = os.environ.get("PAPERTRACKER_OBSIDIAN_TEMPLATE")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p.read_text(encoding="utf-8")
    return DEFAULT_OBSIDIAN_TEMPLATE
