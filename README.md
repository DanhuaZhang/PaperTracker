# PaperTracker

Daily markdown digest of the latest **multi-modal embodied-agent papers in 3D / XR / AR / VR**.

- **Discovery sources**: arXiv (preprints), Crossref (ACM + IEEE published papers), and journal RSS (TVCG, TOG, TOCHI).
- **DOI fallback and enrichment**: OpenAlex, Semantic Scholar, OpenAIRE, CORE, Europe PMC, DataCite, Unpaywall, OpenCitations, and DBLP.
- **No required paper-source API keys** — the defaults use free public APIs. Optional free credentials improve limits and reliability. Your university VPN is only needed when you *click* a publisher link to read restricted full text.
- **No paid AI API key** — summarization shells out to your locally-installed `claude` (default) or `codex` CLI, consuming your Claude Pro/Max or ChatGPT Plus/Pro subscription quota.
- Output: one digest per project run, grouped by priority venue.

---

## Install

```bash
# uv (if you don't have it)
brew install uv                 # or: curl -LsSf https://astral.sh/uv/install.sh | sh

# Project setup
cd PaperTracker
uv sync                         # installs deps into .venv; also provisions the
                                # Python version pinned in .python-version (3.12)

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

## Markdown summary templates (`--select`)

Summary formats are Markdown output skeletons discovered from the configured
template folder:

```text
summary_templates/
├── deep.md
└── triage.md
```

Each direct-child `*.md` filename becomes a dropdown option for every paper. For
example, adding `summary_templates/experiment.md` automatically adds
`experiment` to the list. With `--select`, each paper can use a different
template, and the configured default is preselected.

In the headless fallback, a bare paper number uses the default. Add
`:template-id` to choose another template, for example `1,2:deep`. `a` selects
all papers with the default template.

Discovery summaries are abstract-based by default. Use the explicit Zotero batch workflow below when you want full-text summaries from local PDFs. Template choice does not control the source. Summaries are cached per `(paper, template)` in the active project's summary cache.

## Zotero PDF batch mode

Use `--zotero-collection` to summarize PDFs attached to a Zotero collection. The collection path is the path shown in Zotero's collection tree, relative to the library root, not the random `~/Zotero/storage/...` PDF folder name.

```bash
uv run papertracker --list-zotero-collections
uv run papertracker --provider claude --zotero-collection "Reading/Deep Reading"
uv run papertracker --provider claude --zotero-collection "Reading/Deep Reading" --zotero-template deep
uv run papertracker --provider claude --zotero-collection "Reading/Deep Reading" --zotero-include-subcollections
```

If more than one collection has the same leaf name, use the full path, for example `Project A/Deep Reading` rather than just `Deep Reading`. You can also include the optional `My Library/` prefix; PaperTracker treats `My Library/Reading/Deep Reading` as `Reading/Deep Reading`.

Zotero batch summaries use the selected provider. Claude reads the local PDF
directly; Codex first extracts local PDF text with `pypdf` and sends that text to
the model. Digests are written under `digests/<project-id>/zotero/<collection>/`.

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
across all years, then reranks results with the active local relevance scorer
plus citation and discovery-source signals.
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
| `PAPERTRACKER_ZOTERO_DIR` | Zotero data directory (contains `zotero.sqlite` + `storage/`) | `~/Zotero` |
| `PAPERTRACKER_ZOTERO_LINKED_BASE` | Base dir for Zotero "Linked Attachment Base Directory" (ZotFile-style linked PDFs) | unset |
| `PAPERTRACKER_OPENALEX_API_KEY` | Optional free OpenAlex key for higher related-work / abstract-lookup limits | unset |
| `PAPERTRACKER_SEMANTIC_SCHOLAR_API_KEY` | Optional free Semantic Scholar key for a dedicated rate limit | unset |
| `PAPERTRACKER_CORE_API_KEY` | Optional CORE key for better API performance | unset |
| `PAPERTRACKER_OPENCITATIONS_ACCESS_TOKEN` | Optional OpenCitations token for identified API use | unset |
| `PAPERTRACKER_ABSTRACT_FALLBACKS` | Ordered comma-separated DOI abstract providers | `openalex,semantic_scholar,openaire,core,europe_pmc,datacite` |
| `PAPERTRACKER_DOI_ENRICHERS` | Comma-separated providers applied to relevant, unseen DOI papers | `unpaywall,opencitations,dblp,datacite` |
| `FASTEMBED_CACHE_PATH` | Override where the local embedding model is cached | `.papertracker/fastembed_cache` |

The Zotero DB is opened **read-only** (copied to a temp file first), so PaperTracker never modifies your library.

## Configuration

Runtime defaults live in `papertracker.toml` in this repo. That file contains
the default provider/model plus source defaults, output base paths, Zotero, and
summary-template settings.

The TOML file stores only the template folder and default template ID; template
contents remain in Markdown files:

```toml
summary_template_dir = "summary_templates"
default_summary_template = "triage"
```

Relative template directories are resolved from the directory containing
`papertracker.toml`. Template IDs are case-sensitive filename stems, and files
are shown alphabetically in the selector.

For example, to switch the default summarizer to Codex, edit:

```toml
provider = "codex"
codex_model = "gpt-5.4"
```

Project/topic profiles live in `projects.toml`. This file is **gitignored** (it
holds your personal topics) — start from the tracked template:

```bash
cp projects.example.toml projects.toml   # then edit for your own topics
```

If no `projects.toml` exists, PaperTracker runs a single legacy profile built
entirely from `papertracker.toml`. Each profile has its own topic statement and
CrossRef keyword hint:

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
relevance_scorer = "dense"
relevance_threshold = 0.65
hybrid_relevance_threshold = 0.60
```

See [`projects.example.toml`](projects.example.toml) for a fully commented
template.

### Default AI tool — precedence

Pick **one** of these to set your default provider; CLI flag wins, then env var, then personal config file, then repo config.

| Method | How | Persistence |
|---|---|---|
| CLI flag | `papertracker --provider codex` | one run |
| Env var | `export PAPERTRACKER_PROVIDER=codex` in `~/.zshrc` | per shell |
| Personal config file | `~/.config/papertracker/config.toml` → `provider = "codex"` | global user override |
| Repo config file | `papertracker.toml` → `provider = "codex"` | project default |

`--model` and `PAPERTRACKER_MODEL` override the selected provider's configured
default for one run or shell. In config files, set provider-specific defaults
with `claude_model = "..."` and `codex_model = "..."`.

Example TOML config:
```toml
# ~/.config/papertracker/config.toml
provider = "codex"
claude_model = "sonnet"
codex_model = "gpt-5.3-codex"
```

## How paper sources work without API keys

The script **never logs into IEEE Xplore or ACM Digital Library**. Both publishers are CrossRef members and deposit metadata (DOI, title, abstract when available, authors, publication date) to CrossRef on publication day. We query CrossRef filtered by member ID (`320` = ACM, `263` = IEEE) within a date window — completely free, no auth.

| Step | Endpoint | Auth | Returns |
|---|---|---|---|
| Find new ACM/IEEE papers | `api.crossref.org/works` | none | DOI, title, abstract, authors |
| Recover a missing abstract | OpenAlex, Semantic Scholar, OpenAIRE, CORE, Europe PMC, then DataCite | optional free keys | first available abstract plus provenance |
| Enrich a relevant unseen DOI | Unpaywall, OpenCitations, DBLP, DataCite | optional free tokens | OA location, citations/references, and bibliographic metadata |
| Summarize | `claude` / `codex` CLI | subscription login | bullet summary |
| Read full PDF (later, by you) | DOI link → IEEE/ACM site | university VPN | the paper |

**Timing**: arXiv preprints appear same-day (often weeks before conference). CrossRef ACM/IEEE deposits appear within ~1–14 days of publication (so e.g. CHI papers appear in the digest within ~1 week of the conference). Journal RSS feeds (TVCG, TOG, TOCHI) sometimes appear 1–2 days earlier than the CrossRef deposit; DOI-based dedup merges them.

If Crossref and every configured abstract fallback lack an abstract for a paper,
it is **skipped silently** (no AI summary is attempted on title alone). DOI
lookups are cached by normalized DOI for the duration of the run, and one
provider's failure does not stop later fallbacks.

## Relevance filter

PaperTracker has two local, non-LLM relevance scorers:

- `dense` (default): the original computation. Each fetched paper's
  `(title + abstract)` is embedded locally with `BAAI/bge-small-en-v1.5` and
  compared via cosine similarity to the active project's `topic_statement`.
  Papers at/above `relevance_threshold` pass to the summarizer.
- `hybrid`: combines the same dense embedding signal with an in-process BM25
  keyword score. It uses `hybrid_relevance_threshold` and can optionally add a
  local cross-encoder reranker.

The model runs on CPU/ANE and processes ~100 abstracts in under 2 seconds on Apple Silicon.

To tune:
- **Edit `topic_statement`** in `projects.toml` to reflect the project. The more specific (and longer), the better the discrimination.
- **Edit `relevance_scorer`** (`dense` or `hybrid`) or pass `--scorer hybrid` per run.
- **Edit the active threshold** (`relevance_threshold` for `dense`,
  `hybrid_relevance_threshold` for `hybrid`) or pass `--threshold 0.7` per run.
  Higher = stricter. Use `--no-summarize -v` to see scores and pick a cut point.

To inspect scores without spending LLM quota:
```bash
uv run papertracker --no-summarize --threshold -1 --days 14   # see all scores
uv run papertracker --no-summarize --scorer hybrid --threshold -1 --days 14
```

Optional local reranking for hybrid mode requires the extra dependency:

```bash
uv sync --extra rerank
```

Then set:

```toml
relevance_scorer = "hybrid"
enable_reranker = true
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

## Migrating to a new machine

A `git clone` brings the code plus `papertracker.toml` and
`projects.example.toml`. It does **not** bring anything machine-local, so on a
fresh system you must recreate:

1. **Runtime:** install `uv`, then `uv sync` (provisions Python 3.12 and deps).
2. **Project profiles:** `cp projects.example.toml projects.toml` and edit it
   for your topics (`projects.toml` is gitignored, so it never leaves your
   machine). Skip this to run the legacy single-topic profile.
3. **AI CLI auth:** `claude login` and/or `codex login` — subscription tokens are
   stored by those CLIs (in their own config dirs), not by PaperTracker.
4. **Environment variables** you had set in your shell rc (`~/.zshrc` etc.). None
   are committed. The ones actually in use on the current machine are:
   ```bash
   export PAPERTRACKER_EMAIL=you@example.com          # CrossRef/OpenAlex polite pool
   export PAPERTRACKER_OPENALEX_API_KEY="…"            # optional free OpenAlex key
   ```
   Any other `PAPERTRACKER_*` / `FASTEMBED_CACHE_PATH` overrides you rely on must
   be re-exported too — see the env-var tables above.

Regenerated automatically on first run (safe to omit): the `.papertracker/`
state (`seen.json`, `summary_cache.json`, the downloaded embedding model),
`digests/`, and `.venv/`. None of these are committed.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `'claude' not found on PATH` | Install Claude Code: <https://claude.com/code>, then `claude login`. |
| `'codex' not found on PATH` | `npm install -g @openai/codex` (or `brew install --cask codex`), then `codex login`. |
| Empty digest every day | Lower `--threshold` (e.g. 0.55) or widen the project's `topic_statement`; also try `--days 7`. |
| Too much noise in digest | Raise `--threshold` (e.g. 0.7) or sharpen the project's `topic_statement`. |
| Log says `capped at 500 of N total` | Bump `max_results_per_query` in `papertracker.toml`. Embedding is local so the only cost is HTTP roundtrips. |
| First run is slow | First call downloads the ~130 MB embedding model into `.papertracker/fastembed_cache/` (override with `FASTEMBED_CACHE_PATH`). Cached thereafter. |
| Re-summarize a paper you already saw | `--ignore-seen` (or delete that project's `.papertracker/<project-id>/seen.json`). |
| Want to inspect matches without spending quota | `--no-summarize` (sorts by relevance score). |
