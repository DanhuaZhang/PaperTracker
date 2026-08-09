"""Project and project-profile configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import re
import tomllib
from pathlib import Path

from . import related_work

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_REPOSITORY_CONFIG_PATH = REPOSITORY_ROOT / "papertracker.toml"


def _repository_config_path() -> Path:
    """Prefer config.toml; tolerate the pre-rename papertracker.toml."""
    preferred = REPOSITORY_ROOT / "config.toml"
    if preferred.is_file():
        return preferred
    if _LEGACY_REPOSITORY_CONFIG_PATH.is_file():
        log.warning(
            "Reading runtime defaults from %s. Rename it to %s — papertracker.toml "
            "is deprecated.",
            _LEGACY_REPOSITORY_CONFIG_PATH,
            preferred,
        )
        return _LEGACY_REPOSITORY_CONFIG_PATH
    return preferred


_REPOSITORY_CONFIG_PATH = _repository_config_path()
_IN_SOURCE_CHECKOUT = (
    _REPOSITORY_CONFIG_PATH.is_file()
    and (REPOSITORY_ROOT / "pyproject.toml").is_file()
)
ROOT = REPOSITORY_ROOT if _IN_SOURCE_CHECKOUT else PACKAGE_DIR
BUNDLED_CONFIG_PATH = PACKAGE_DIR / "defaults.toml"
BUNDLED_TEMPLATE_DIR = PACKAGE_DIR / "bundled_templates"


class ConfigError(RuntimeError):
    """Raised when a PaperTracker configuration value is invalid."""


def _default_user_data_dir() -> Path:
    if _IN_SOURCE_CHECKOUT:
        return REPOSITORY_ROOT / "user_data"
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "papertracker"

# Everything machine-local — your topics, generated digests, run state, and the
# downloaded embedding model — lives under one gitignored folder. Override with
# PAPERTRACKER_USER_DATA_DIR to keep it outside the checkout.
USER_DATA_DIR = Path(
    os.environ.get("PAPERTRACKER_USER_DATA_DIR") or _default_user_data_dir()
).expanduser()

PROJECT_CONFIG_PATH = globals().get(
    "PROJECT_CONFIG_PATH",
    _REPOSITORY_CONFIG_PATH if _IN_SOURCE_CHECKOUT else BUNDLED_CONFIG_PATH,
)

def _default_projects_config_path() -> Path:
    """Prefer user_data/projects.toml; tolerate the pre-user_data repo-root location."""
    preferred = USER_DATA_DIR / "projects.toml"
    if preferred.is_file():
        return preferred
    legacy = ROOT / "projects.toml"
    if legacy.is_file():
        log.warning(
            "Reading project profiles from %s. Move it to %s — the repo-root location is deprecated.",
            legacy,
            preferred,
        )
        return legacy
    return preferred


PROJECTS_CONFIG_PATH = globals().get(
    "PROJECTS_CONFIG_PATH",
    _default_projects_config_path(),
)


def _user_path(relative: str | Path) -> str:
    """Resolve a profile output path under USER_DATA_DIR unless already absolute."""
    path = Path(relative).expanduser()
    return str(path if path.is_absolute() else USER_DATA_DIR / path)


def _load_project_config() -> dict:
    if not PROJECT_CONFIG_PATH.is_file():
        raise ConfigError(f"Runtime configuration file not found: {PROJECT_CONFIG_PATH}")
    try:
        with PROJECT_CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    except OSError as exc:
        raise ConfigError(f"Could not read {PROJECT_CONFIG_PATH}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {PROJECT_CONFIG_PATH}: {exc}") from exc


_PROJECT_CONFIG = _load_project_config()
_PROJECTS_CONFIG: dict | None = None


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

# Added after the other keys, so a config file written by an earlier version
# will not have it. Default rather than fail, unlike every _cfg key above.
REASONING_EFFORT = _PROJECT_CONFIG.get("reasoning_effort", "medium")

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
SEMANTIC_SCHOLAR_API_KEY = os.environ.get(
    "PAPERTRACKER_SEMANTIC_SCHOLAR_API_KEY", ""
).strip()
CORE_API_KEY = os.environ.get("PAPERTRACKER_CORE_API_KEY", "").strip()
OPENCITATIONS_ACCESS_TOKEN = os.environ.get(
    "PAPERTRACKER_OPENCITATIONS_ACCESS_TOKEN", ""
).strip()


def _env_source_list(name: str, default: str) -> tuple[str, ...]:
    raw = os.environ.get(name, default)
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


ABSTRACT_FALLBACK_SOURCES = _env_source_list(
    "PAPERTRACKER_ABSTRACT_FALLBACKS",
    "openalex,semantic_scholar,openaire,core,europe_pmc,datacite",
)
DOI_ENRICHMENT_SOURCES = _env_source_list(
    "PAPERTRACKER_DOI_ENRICHERS",
    "unpaywall,opencitations,dblp,datacite",
)

# Embedding-based relevance filter (replaces the old keyword filter).
# Each paper's (title + abstract) is embedded with the model below and compared
# to the TOPIC_STATEMENT vector via cosine similarity. Papers scoring at or above
# RELEVANCE_THRESHOLD are kept.
EMBEDDING_MODEL = _cfg("embedding_model")
RELEVANCE_SCORER = _cfg("relevance_scorer")
RELEVANCE_THRESHOLD = _cfg("relevance_threshold")
HYBRID_RELEVANCE_THRESHOLD = _cfg("hybrid_relevance_threshold")
ENABLE_RERANKER = _cfg("enable_reranker")
RERANKER_MODEL = _cfg("reranker_model")
RERANKER_TOP_K = _cfg("reranker_top_k")

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
SUMMARY_TEMPLATE_DIR = _cfg("summary_template_dir")
DEFAULT_ABSTRACT_TEMPLATE = _cfg("default_abstract_template")
DEFAULT_FULLTEXT_TEMPLATE = _cfg("default_fulltext_template")
# Kept as a read-only compatibility name for integrations that imported it. New
# code must select the evidence-specific default explicitly.
DEFAULT_SUMMARY_TEMPLATE = DEFAULT_ABSTRACT_TEMPLATE


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
    relevance_scorer: str = "dense"
    hybrid_relevance_threshold: float = 0.60
    enable_reranker: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_top_k: int = 100
    contribution_statement: str | None = None
    related_work_facets: list[related_work.RelatedWorkFacet] = field(default_factory=list)


_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _profile_value(raw: dict, key: str, default):
    return raw[key] if key in raw else default


def _projects_default(key: str, fallback):
    """Top-level key in projects.toml, shared by every profile that omits it.

    Lets personal settings (notably `priority_venues`) live once in
    user_data/projects.toml instead of being repeated per profile or kept in the
    tracked config.toml.
    """
    global _PROJECTS_CONFIG
    if _PROJECTS_CONFIG is None:
        _PROJECTS_CONFIG = _load_projects_config()
    if _PROJECTS_CONFIG and key in _PROJECTS_CONFIG:
        return _PROJECTS_CONFIG[key]
    return fallback


def _optional_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _relevance_scorer(value) -> str:
    scorer = str(value or "").strip().lower()
    if scorer not in {"dense", "hybrid"}:
        raise ConfigError("relevance_scorer must be 'dense' or 'hybrid'")
    return scorer


def _project_state_path(project_id: str, filename: str) -> str:
    return str(Path("state") / project_id / filename)


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
        relevance_scorer=_relevance_scorer(_profile_value(raw, "relevance_scorer", RELEVANCE_SCORER)),
        hybrid_relevance_threshold=float(
            _profile_value(raw, "hybrid_relevance_threshold", HYBRID_RELEVANCE_THRESHOLD)
        ),
        enable_reranker=bool(_profile_value(raw, "enable_reranker", ENABLE_RERANKER)),
        reranker_model=str(_profile_value(raw, "reranker_model", RERANKER_MODEL)),
        reranker_top_k=int(_profile_value(raw, "reranker_top_k", RERANKER_TOP_K)),
        priority_venues=list(
            _profile_value(raw, "priority_venues", _projects_default("priority_venues", PRIORITY_VENUES))
        ),
        priority_venue_only=bool(_profile_value(raw, "priority_venue_only", PRIORITY_VENUE_ONLY)),
        enabled_sources_default=list(
            _profile_value(raw, "enabled_sources_default", ENABLED_SOURCES_DEFAULT)
        ),
        digest_dir=_user_path(_profile_value(raw, "digest_dir", Path(DIGEST_DIR) / project_id)),
        seen_papers_file=_user_path(
            _profile_value(raw, "seen_papers_file", _project_state_path(project_id, "seen.json"))
        ),
        summary_cache_file=_user_path(
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
    """Single-topic fallback profile using the root ``config.toml`` settings."""
    return ProjectProfile(
        id=None,
        name="PaperTracker",
        topic_statement=TOPIC_STATEMENT,
        crossref_query_hint=CROSSREF_QUERY_HINT,
        arxiv_categories=list(ARXIV_CATEGORIES),
        relevance_threshold=RELEVANCE_THRESHOLD,
        relevance_scorer=_relevance_scorer(RELEVANCE_SCORER),
        hybrid_relevance_threshold=HYBRID_RELEVANCE_THRESHOLD,
        enable_reranker=ENABLE_RERANKER,
        reranker_model=RERANKER_MODEL,
        reranker_top_k=RERANKER_TOP_K,
        priority_venues=list(PRIORITY_VENUES),
        priority_venue_only=PRIORITY_VENUE_ONLY,
        enabled_sources_default=list(ENABLED_SOURCES_DEFAULT),
        digest_dir=_user_path(DIGEST_DIR),
        seen_papers_file=_user_path(SEEN_PAPERS_FILE),
        summary_cache_file=_user_path(SUMMARY_CACHE_FILE),
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


# --- Markdown summary templates -------------------------------------------
def summary_template_directory() -> Path:
    """Return the active user-owned template directory.

    Relative paths resolve against the repository root in a source checkout, so
    templates sit beside the code where they are easy to edit. An installed copy
    has no repository root, so they resolve under the user data directory.
    """
    directory = Path(SUMMARY_TEMPLATE_DIR).expanduser()
    if directory.is_absolute():
        return directory
    base = REPOSITORY_ROOT if _IN_SOURCE_CHECKOUT else USER_DATA_DIR
    return base / directory


def _legacy_summary_template_directory() -> Path | None:
    """Pre-move location, still holding templates a user may have customized."""
    if not _IN_SOURCE_CHECKOUT:
        return None
    legacy = USER_DATA_DIR / Path(SUMMARY_TEMPLATE_DIR)
    if legacy == summary_template_directory() or not legacy.is_dir():
        return None
    has_markdown = any(
        path.is_file() and path.suffix == ".md" for path in legacy.iterdir()
    )
    return legacy if has_markdown else None


def summary_template_catalog(default_evidence: str = "abstract"):
    """Seed/discover templates and return (all templates, evidence default)."""
    from . import summary_templates

    if default_evidence not in summary_templates.EVIDENCE_TYPES:
        raise ConfigError(f"Unknown template evidence type {default_evidence!r}")
    directory = summary_template_directory()
    # Templates used to live under user_data/. Carry a customized set forward
    # rather than seeding pristine samples over the top of it.
    legacy = _legacy_summary_template_directory()
    source = legacy if legacy is not None else BUNDLED_TEMPLATE_DIR
    if summary_templates.seed_if_empty(directory, source) and legacy is not None:
        log.warning(
            "Copied summary templates from the former location %s to %s. "
            "Edit them there from now on; the old directory is no longer read "
            "and can be deleted.",
            legacy,
            directory,
        )
    templates, _ = summary_templates.discover(directory)
    by_id = {template.id: template for template in templates}
    defaults = {
        "abstract": DEFAULT_ABSTRACT_TEMPLATE,
        "fulltext": DEFAULT_FULLTEXT_TEMPLATE,
    }
    resolved = {}
    for evidence, template_id in defaults.items():
        template = by_id.get(template_id)
        if template is None:
            raise ConfigError(
                f"Configured default {evidence} summary template {template_id!r} "
                f"was not found in {directory}"
            )
        if template.evidence != evidence:
            raise ConfigError(
                f"Configured default {evidence} summary template {template_id!r} at "
                f"{template.path} requires {template.evidence} evidence"
            )
        resolved[evidence] = template
    return templates, resolved[default_evidence]


def summary_template(template_id: str):
    """Return a configured template by its case-sensitive filename stem."""
    templates, _default = summary_template_catalog()
    for template in templates:
        if template.id == template_id:
            return template
    choices = ", ".join(template.id for template in templates)
    raise ConfigError(
        f"Unknown summary template {template_id!r}. Available templates: {choices}"
    )
