"""Built-in defaults. Override via env vars, ~/.config/papertracker/config.toml, or CLI flags."""

import os

# Default AI provider (overridable via env var / TOML file / CLI flag)
DEFAULT_PROVIDER = "claude"          # "claude" | "codex"
CLAUDE_MODEL = "sonnet"              # CLI alias or full ID
CODEX_MODEL = "gpt-5.3-codex"

# CrossRef / OpenAlex polite-pool identifier. Set PAPERTRACKER_EMAIL in your shell
# (or leave unset for anonymous requests — works, but with lower rate-limit priority).
# Nothing is sent *from* this email; it's only included in outbound request metadata
# (HTTP User-Agent for CrossRef, ?mailto= for OpenAlex) so the APIs can identify and
# preferentially serve identified clients.
USER_EMAIL = os.environ.get("PAPERTRACKER_EMAIL", "")
USER_AGENT = (
    f"papertracker/0.1 (mailto:{USER_EMAIL})" if USER_EMAIL
    else "papertracker/0.1"
)

# Embedding-based relevance filter (replaces the old keyword filter).
# Each paper's (title + abstract) is embedded with the model below and compared
# to the TOPIC_STATEMENT vector via cosine similarity. Papers scoring at or above
# RELEVANCE_THRESHOLD are kept.
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"   # ~130 MB ONNX, downloads on first run
# Empirically tuned on a 37-paper IEEE/ACM sample: 0.65 keeps embodied/XR/3D-scene
# papers and drops MIDI / microphone-array / legal-judgment noise. Tune with --threshold.
RELEVANCE_THRESHOLD = 0.65

TOPIC_STATEMENT = (
    "Multi-modal embodied agents perceiving, reasoning about, and acting within "
    "3D environments — including extended reality (XR), augmented reality (AR), "
    "and virtual reality (VR). Relevant topics include: vision-language models "
    "for embodied AI, 3D scene understanding, spatial reasoning over rooms and "
    "scenes, immersive interaction and mixed-reality interfaces, simulated agents "
    "in virtual worlds, embodied question answering, robot learning with multi-modal "
    "sensors, scene graphs and neural rendering for embodied perception, world "
    "models for navigation and manipulation, spatial interaction and spatial "
    "awareness in immersive environments, 3D avatars, and gaze/gesture "
    "interaction in XR."
)

# Loose keyword hint passed to CrossRef's `query` parameter to bias its ranking
# (NOT a strict filter — that's done by the embedding model post-fetch).
CROSSREF_QUERY_HINT = (
    "embodied agent multimodal 3D XR VR AR spatial scene understanding interaction awareness avatar"
)

# arXiv categories to query (will be OR'd in the search_query)
ARXIV_CATEGORIES = ["cs.CV", "cs.RO", "cs.AI", "cs.HC", "cs.GR"]

# Priority venues — used for filtering and "★ priority" badge in the digest.
# `patterns` are case-insensitive substrings matched against CrossRef container-title.
# `rss` is optional; when present, journal_rss source will also poll it.
PRIORITY_VENUES = [
    # IEEE conferences (CrossRef member:263)
    {"name": "IEEE VR", "publisher": "ieee",
     "patterns": ["IEEE Conference on Virtual Reality", "IEEE VR "]},
    {"name": "ISMAR", "publisher": "ieee",
     "patterns": ["ISMAR", "Mixed and Augmented Reality"]},
    # IEEE journal
    {"name": "IEEE TVCG", "publisher": "ieee",
     "patterns": ["Transactions on Visualization and Computer Graphics"],
     "rss": "https://ieeexplore.ieee.org/rss/TOC2945.XML"},
    # ACM conferences (CrossRef member:320)
    {"name": "ACM CHI", "publisher": "acm",
     "patterns": ["CHI Conference on Human Factors", "CHI '"]},
    {"name": "ACM UIST", "publisher": "acm",
     "patterns": ["User Interface Software and Technology", "UIST '"]},
    {"name": "ACM VRST", "publisher": "acm",
     "patterns": ["Virtual Reality Software and Technology", "VRST '"]},
    {"name": "ACM SUI", "publisher": "acm",
     "patterns": ["Spatial User Interaction", "SUI '"]},
    {"name": "SIGGRAPH", "publisher": "acm",
     "patterns": ["SIGGRAPH ", "SIGGRAPH '"]},
    {"name": "SIGGRAPH Asia", "publisher": "acm",
     "patterns": ["SIGGRAPH Asia"]},
    # ACM journals with reliable RSS
    {"name": "ACM TOG", "publisher": "acm",
     "patterns": ["Transactions on Graphics"],
     "rss": "https://dl.acm.org/action/showFeed?type=etoc&feed=rss&jc=tog"},
    {"name": "ACM TOCHI", "publisher": "acm",
     "patterns": ["Transactions on Computer-Human Interaction"],
     "rss": "https://dl.acm.org/action/showFeed?type=etoc&feed=rss&jc=tochi"},
]

# If True, drop CrossRef/RSS results that don't match any PRIORITY_VENUES entry
PRIORITY_VENUE_ONLY = False

DEFAULT_DAYS = 2
# Per-source upper cap. Each source paginates up to this many results. Embedding
# is local and free, so generous is fine. Raise further if you regularly fetch
# conference-deposit windows (CHI/SIGGRAPH can deposit 1000+ papers in one day).
MAX_RESULTS_PER_QUERY = 500
DIGEST_DIR = "digests"
SEEN_PAPERS_FILE = ".seen_papers.json"
# Persistent cache of LLM summaries keyed by canonical_id; lets re-runs reuse summaries
# instead of re-spending tokens. Bypass/overwrite with --refresh-summaries.
SUMMARY_CACHE_FILE = ".summary_cache.json"
SUMMARY_TIMEOUT_SEC = 180
ENABLED_SOURCES_DEFAULT = ["arxiv", "ieee", "acm", "journal_rss"]
