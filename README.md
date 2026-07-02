# PaperTracker

Daily markdown digest of the latest **multi-modal embodied-agent papers in 3D / XR / AR / VR**.

- **Sources**: arXiv (preprints), CrossRef (ACM + IEEE published papers), and journal RSS (TVCG, TOG, TOCHI).
- **No paper-source API keys** — relies on free, no-auth public APIs. Your university VPN is only needed when you *click* the DOI link in the digest to read the full paper.
- **No paid AI API key** — summarization shells out to your locally-installed `claude` (default) or `codex` CLI, consuming your Claude Pro/Max or ChatGPT Plus/Pro subscription quota.
- Output: one digest per project run, grouped by priority venue.

---

## Install

```bash
# uv (if you don't have it)
brew install uv                 # or: curl -LsSf https://astral.sh/uv/install.sh | sh

# Project setup
cd PaperTracker
uv sync                         # installs deps into .venv

# One-time AI CLI auth (pick at least one)
claude login                    # Claude Pro/Max subscription
codex  login                    # ChatGPT Plus/Pro subscription

# Optional: identify yourself to CrossRef + OpenAlex "polite pools" for higher
# rate limits. The email is only sent in request metadata (User-Agent header /
# ?mailto= query param) — nothing is sent *from* your address.
export PAPERTRACKER_EMAIL=your.email@example.com   # leave unset = anonymous
```

## Run

```bash
uv run papertracker                       # last 2 days, all sources, default provider
uv run papertracker --list-projects       # list configured topic/project profiles
uv run papertracker --project xr-agents   # run one project profile
uv run papertracker --all-projects        # run every project profile
uv run papertracker --days 7              # wider window
uv run papertracker --sources arxiv       # one source at a time
uv run papertracker --no-summarize        # just list matches, no LLM calls
uv run papertracker --priority-venues-only # drop papers not in configured priority venues
uv run papertracker --ignore-seen --days 14   # re-summarize already-seen papers
uv run papertracker --related-work         # all-time important related work for the topic
uv run papertracker --related-work --facets # grouped related-work candidate matrix
uv run papertracker -v                    # debug logging
```

With `projects.toml`, digests land in `digests/<project-id>/YYYY-MM-DD.md`.
Already-summarized DOIs/arXiv IDs are remembered per project in
`.papertracker/<project-id>/seen.json`, so one project does not hide papers from
another. Without `projects.toml`, PaperTracker falls back to the legacy
`digests/YYYY-MM-DD.md` and `.seen_papers.json` paths.

## Two summary modes (`--select`)

With `--select`, the browser selector lets you choose a **mode per paper**:

- **Triage** — the standard relevance bullets (objective, contribution, results, model & data, open source, future work). Use it to gauge how close a paper is to your own work.
- **Deep (Obsidian)** — fills in *your* Obsidian paper-note template so you can drop it straight into your vault and complete the judgement sections (e.g. "My take") after reading.

In the headless text fallback, append `d` to a number for deep mode (e.g. `1,3d` = paper 1 triage, paper 3 deep).

Both modes read the **full PDF from your local Zotero library** when the paper is found there (matched by DOI, then title); otherwise they fall back to the abstract and the summary is tagged *"Abstract-based (no Zotero PDF found)."* So **file a paper in Zotero before summarizing** to get full-text output. Summaries are cached per `(paper, mode)` in the active project's summary cache.

> Full-text PDF reading currently requires the **`claude`** provider (the CLI reads the PDF directly). With `codex`, deep mode degrades to abstract-based.

## Related-work mode

Use `--related-work` when you want a starter bibliography of important papers for
the active project's `topic_statement`, including older highly cited papers:

```bash
uv run papertracker --project xr-agents --related-work
uv run papertracker --project xr-agents --related-work --limit 50
uv run papertracker --project xr-agents --related-work --select  # summarize selected papers
uv run papertracker --project xr-agents --related-work --facets
uv run papertracker --project xr-agents --related-work --facets --select
```

Related-work mode uses OpenAlex semantic search plus citation-count sorted search
across all years, then reranks results with the local embedding relevance score.
It does **not** use `--days`, does **not** update the project's `seen.json`, and
writes to `digests/<project-id>/related-work/YYYY-MM-DD.md`.

Faceted related-work mode groups candidates by generated or configured facets,
annotates citation role/rationale from abstracts and metadata, and writes both
`digests/<project-id>/related-work/YYYY-MM-DD.facets.md` and
`digests/<project-id>/related-work/YYYY-MM-DD.facets.json`. Use `--facet-count`
to control generated facets and `--facet-candidates` to control OpenAlex fetch
depth per facet.

OpenAlex works anonymously, but a free API key gives higher daily limits. Get one
from <https://openalex.org/settings/api> and export it before running:

```bash
export PAPERTRACKER_OPENALEX_API_KEY="your_key_here"
```

### Configuration (env vars)

| Variable | Purpose | Default |
|---|---|---|
| `PAPERTRACKER_OBSIDIAN_TEMPLATE` | Path to your Obsidian paper-note template `.md`; injected into deep-mode prompts | built-in default template |
| `PAPERTRACKER_ZOTERO_DIR` | Zotero data directory (contains `zotero.sqlite` + `storage/`) | `~/Zotero` |
| `PAPERTRACKER_ZOTERO_LINKED_BASE` | Base dir for Zotero "Linked Attachment Base Directory" (ZotFile-style linked PDFs) | unset |
| `PAPERTRACKER_OPENALEX_API_KEY` | Optional free OpenAlex key for higher related-work / abstract-lookup limits | unset |

The Zotero DB is opened **read-only** (copied to a temp file first), so PaperTracker never modifies your library.

## Configuration

Runtime defaults live in `papertracker.toml` in this repo. That file contains
the default provider/model plus source defaults, output base paths, Zotero, and
Obsidian template settings.

For example, to switch the default summarizer to Codex, edit:

```toml
provider = "codex"
model = "gpt-5.4"
```

Project/topic profiles live in `projects.toml`. Each profile has its own topic
statement and CrossRef keyword hint:

```toml
default_project = "xr-agents"

[[projects]]
id = "xr-agents"
name = "XR embodied agents"
topic_statement = """
Embodied agents, XR, AR/VR, spatial reasoning, and 3D scene understanding.
"""
crossref_query_hint = "embodied agent XR AR VR spatial reasoning 3D scene"
arxiv_categories = ["cs.CV", "cs.RO", "cs.HC"]
relevance_threshold = 0.65
```

### Default AI tool — precedence

Pick **one** of these to set your default provider; CLI flag wins, then env var, then personal config file, then repo config.

| Method | How | Persistence |
|---|---|---|
| CLI flag | `papertracker --provider codex` | one run |
| Env var | `export PAPERTRACKER_PROVIDER=codex` in `~/.zshrc` | per shell |
| Personal config file | `~/.config/papertracker/config.toml` → `provider = "codex"` | global user override |
| Repo config file | `papertracker.toml` → `provider = "codex"` | project default |

Same chain applies to `--model` / `PAPERTRACKER_MODEL` / `model = "..."`.

Example TOML config:
```toml
# ~/.config/papertracker/config.toml
provider = "codex"
model = "gpt-5.3-codex"
```

## How paper sources work without API keys

The script **never logs into IEEE Xplore or ACM Digital Library**. Both publishers are CrossRef members and deposit metadata (DOI, title, abstract when available, authors, publication date) to CrossRef on publication day. We query CrossRef filtered by member ID (`320` = ACM, `263` = IEEE) within a date window — completely free, no auth.

| Step | Endpoint | Auth | Returns |
|---|---|---|---|
| Find new ACM/IEEE papers | `api.crossref.org/works` | none | DOI, title, abstract, authors |
| Backup if abstract missing | `api.openalex.org/works/{doi}` | none | reconstructed abstract |
| Summarize | `claude` / `codex` CLI | subscription login | bullet summary |
| Read full PDF (later, by you) | DOI link → IEEE/ACM site | university VPN | the paper |

**Timing**: arXiv preprints appear same-day (often weeks before conference). CrossRef ACM/IEEE deposits appear within ~1–14 days of publication (so e.g. CHI papers appear in the digest within ~1 week of the conference). Journal RSS feeds (TVCG, TOG, TOCHI) sometimes appear 1–2 days earlier than the CrossRef deposit; DOI-based dedup merges them.

If neither CrossRef nor OpenAlex has an abstract for a given paper, it is **skipped silently** (no AI summary attempted on title alone).

## Relevance filter (embedding-based)

Each fetched paper's (title + abstract) is embedded locally with `BAAI/bge-small-en-v1.5` (~130 MB ONNX, downloaded once via `fastembed` on first run) and compared via cosine similarity to the active project's `topic_statement`. Papers at/above that project's `relevance_threshold` pass to the summarizer.

The model runs on CPU/ANE and processes ~100 abstracts in under 2 seconds on Apple Silicon.

To tune:
- **Edit `topic_statement`** in `projects.toml` to reflect the project. The more specific (and longer), the better the discrimination.
- **Edit `relevance_threshold`** (or pass `--threshold 0.7` per run). Higher = stricter. Use `--no-summarize -v` to see scores and pick a cut point.

To inspect scores without spending LLM quota:
```bash
uv run papertracker --no-summarize --threshold -1 --days 14   # see all scores
```

## Customizing venues and categories

Edit `projects.toml` for project-specific settings, or `papertracker.toml` for
defaults used by profiles that omit a field:

- `arxiv_categories`: arXiv subject categories to query.
- `crossref_query_hint`: keyword string passed to CrossRef as a *ranking hint* (not a filter — it just biases CrossRef's results toward your topic).
- `priority_venues`: a list of named venues with `container-title` substring patterns, used to (a) tag papers with a `★ Venue` badge in the digest, (b) optionally restrict output via `--priority-venues-only`, and (c) drive the `journal_rss` source when an `rss` URL is included.

## Outputs

```
digests/
└── xr-agents/
    └── 2026-05-22.md     # ## ★ Priority venues, then ## arXiv preprints, then ## Other ACM / IEEE
.papertracker/
└── xr-agents/
    ├── seen.json         # canonical IDs already summarized for this project
    └── summary_cache.json
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `'claude' not found on PATH` | Install Claude Code: <https://claude.com/code>, then `claude login`. |
| `'codex' not found on PATH` | `npm install -g @openai/codex` (or `brew install --cask codex`), then `codex login`. |
| Empty digest every day | Lower `--threshold` (e.g. 0.55) or widen the project's `topic_statement`; also try `--days 7`. |
| Too much noise in digest | Raise `--threshold` (e.g. 0.7) or sharpen the project's `topic_statement`. |
| Log says `capped at 500 of N total` | Bump `max_results_per_query` in `papertracker.toml`. Embedding is local so the only cost is HTTP roundtrips. |
| First run is slow | First call downloads the ~130 MB embedding model into fastembed's cache. Cached thereafter. |
| Re-summarize a paper you already saw | `--ignore-seen` (or delete that project's `.papertracker/<project-id>/seen.json`). |
| Want to inspect matches without spending quota | `--no-summarize` (sorts by relevance score). |
