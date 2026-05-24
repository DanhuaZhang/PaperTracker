# PaperTracker

Daily markdown digest of the latest **multi-modal embodied-agent papers in 3D / XR / AR / VR**.

- **Sources**: arXiv (preprints), CrossRef (ACM + IEEE published papers), and journal RSS (TVCG, TOG, TOCHI).
- **No paper-source API keys** — relies on free, no-auth public APIs. Your university VPN is only needed when you *click* the DOI link in the digest to read the full paper.
- **No paid AI API key** — summarization shells out to your locally-installed `claude` (default) or `codex` CLI, consuming your Claude Pro/Max or ChatGPT Plus/Pro subscription quota.
- Output: one `digests/YYYY-MM-DD.md` file per run, grouped by priority venue.

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
uv run papertracker --days 7              # wider window
uv run papertracker --sources arxiv       # one source at a time
uv run papertracker --no-summarize        # just list matches, no LLM calls
uv run papertracker --priority-venues-only # drop papers not in PRIORITY_VENUES
uv run papertracker --ignore-seen --days 14   # re-summarize already-seen papers
uv run papertracker -v                    # debug logging
```

The digest lands in `digests/YYYY-MM-DD.md`. Already-summarized DOIs/arXiv IDs are remembered in `.seen_papers.json` so re-runs only summarize new papers.

## Default AI tool — precedence

Pick **one** of these to set your default provider; CLI flag wins, then env var, then config file, then built-in default.

| Method | How | Persistence |
|---|---|---|
| CLI flag | `papertracker --provider codex` | one run |
| Env var | `export PAPERTRACKER_PROVIDER=codex` in `~/.zshrc` | per shell |
| Config file | `~/.config/papertracker/config.toml` → `provider = "codex"` | global |
| Built-in default | `src/papertracker/config.py` → `DEFAULT_PROVIDER = "claude"` | fallback |

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

Each fetched paper's (title + abstract) is embedded locally with `BAAI/bge-small-en-v1.5` (~130 MB ONNX, downloaded once via `fastembed` on first run) and compared via cosine similarity to a single `TOPIC_STATEMENT` vector. Papers at/above `RELEVANCE_THRESHOLD` (default **0.65**) pass to the summarizer.

The model runs on CPU/ANE and processes ~100 abstracts in under 2 seconds on Apple Silicon.

To tune:
- **Edit `TOPIC_STATEMENT`** in `src/papertracker/config.py` to reflect your interests. The more specific (and longer), the better the discrimination.
- **Edit `RELEVANCE_THRESHOLD`** (or pass `--threshold 0.7` per run). Higher = stricter. Use `--no-summarize -v` to see scores and pick a cut point.

To inspect scores without spending LLM quota:
```bash
uv run papertracker --no-summarize --threshold -1 --days 14   # see all scores
```

## Customizing venues and categories

Edit `src/papertracker/config.py`:

- `ARXIV_CATEGORIES`: arXiv subject categories to query.
- `CROSSREF_QUERY_HINT`: keyword string passed to CrossRef as a *ranking hint* (not a filter — it just biases CrossRef's top-100 results toward your topic).
- `PRIORITY_VENUES`: a list of named venues with `container-title` substring patterns, used to (a) tag papers with a `★ Venue` badge in the digest, (b) optionally restrict output via `--priority-venues-only`, and (c) drive the `journal_rss` source when an `rss` URL is included.

## Outputs

```
digests/
└── 2026-05-22.md         # ## ★ Priority venues, then ## arXiv preprints, then ## Other ACM / IEEE
.seen_papers.json         # canonical IDs of papers already summarized (gitignored)
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `'claude' not found on PATH` | Install Claude Code: <https://claude.com/code>, then `claude login`. |
| `'codex' not found on PATH` | `npm install -g @openai/codex` (or `brew install --cask codex`), then `codex login`. |
| Empty digest every day | Lower `--threshold` (e.g. 0.55) or widen `TOPIC_STATEMENT` in `config.py`; also try `--days 7`. |
| Too much noise in digest | Raise `--threshold` (e.g. 0.7) or sharpen `TOPIC_STATEMENT`. |
| Log says `capped at 500 of N total` | Bump `MAX_RESULTS_PER_QUERY` in `config.py` (default 500). Embedding is local so the only cost is HTTP roundtrips. |
| First run is slow | First call downloads the ~130 MB embedding model into fastembed's cache. Cached thereafter. |
| Re-summarize a paper you already saw | `--ignore-seen` (or delete `.seen_papers.json`). |
| Want to inspect matches without spending quota | `--no-summarize` (sorts by relevance score). |
