# PaperTracker

A daily markdown digest of new papers matching **your** research topics.

You write a paragraph describing what you work on. PaperTracker polls arXiv,
Crossref (ACM + IEEE), and journal RSS feeds, scores every result against that
paragraph with a local embedding model, and summarizes only what clears your
threshold — writing one markdown file per topic per day.

- **No paid paper-discovery key.** Discovery uses public APIs. Summarization
  shells out to your local `claude` or `codex` CLI; its cost and limits depend
  on whether that CLI is authenticated with a subscription or an API key.
- **Relevance filtering runs on your machine.** Abstracts are embedded locally
  with `BAAI/bge-small-en-v1.5` — no LLM quota spent deciding what's relevant.
- **Multiple topics, kept separate.** Each project has its own digests, its own
  seen-papers list, and its own summary cache, so one topic never hides papers
  from another.
- **Runtime data stays in `user_data/`**, which is gitignored. When you request
  a summary, the selected AI CLI sends the prompt and paper evidence to its
  provider; see [Privacy and data flow](#privacy-and-data-flow).

---

## Prerequisites

| | |
|---|---|
| OS | macOS or Linux |
| `git` | to clone |
| [`uv`](https://docs.astral.sh/uv/) | provisions Python 3.12 and all dependencies |
| Claude Code **or** Codex CLI | required only when you ask for summaries |

Everything else, including Python itself, is installed by `uv sync`.

## Setup, from zero

### 1. Install uv

```bash
brew install uv                                  # macOS
curl -LsSf https://astral.sh/uv/install.sh | sh  # Linux / macOS
```

### 2. Clone and install

Use the **Code** or **Clone** button on the repository page and run the clone
command it gives you. Then, from the cloned checkout:

```bash
cd PaperTracker
uv sync
```

This creates `.venv/`, provisions the Python pinned in `.python-version` (3.12),
and installs the `papertracker` command into that environment.

### 3. Install and log into an AI CLI

Pick at least one if you want summaries. Either CLI can use an eligible
subscription; API-key authentication may instead incur usage-based billing.

```bash
# Claude Code
#   install: https://claude.com/code
claude auth login

# Codex CLI — standalone installer from the official Codex documentation
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex login
```

Authentication options and plan availability can change; use the official
[Claude Code setup guide](https://docs.anthropic.com/en/docs/claude-code/getting-started)
or [Codex CLI and authentication guides](https://learn.chatgpt.com/docs/codex/cli).

Do not edit the tracked `config.toml` just to choose a provider. Set a
personal default in your shell instead:

```bash
export PAPERTRACKER_PROVIDER=codex  # or claude
```

### 4. Create your topics file

```bash
cp projects.example.toml user_data/projects.toml
```

Now edit it. The field that matters most is `topic_statement` — a paragraph
describing your research in your own words. This is what every paper's title and
abstract gets compared against, so specific beats short. `projects.example.toml`
documents every field inline.

### 5. Optional — identify yourself to the paper APIs

Everything works anonymously. Setting an email raises your rate limits and is
required for one provider. Add to `~/.zshrc` (or `~/.bashrc`):

```bash
export PAPERTRACKER_EMAIL=you@example.com
```

Nothing is ever sent *from* this address — it travels only as request metadata
(a `User-Agent` header for Crossref, a `?mailto=` parameter for OpenAlex, and
Unpaywall's required `email` query parameter).

See [Credentials](#credentials--where-to-get-them) for the optional free API
keys.

### 6. Verify it works

```bash
uv run papertracker --list-projects
```

Your topics should be listed. Then do a real fetch with no LLM calls:

```bash
uv run papertracker --no-summarize --days 7
```

This exercises the full pipeline — fetch, dedup, local relevance scoring — and
prints matches with their scores to stdout without spending any quota.

**Expect a few minutes, and expect that every time.** With the example config
this took about 2.5 minutes end to end on an Apple Silicon Mac: roughly 45
seconds fetching and two minutes scoring ~1400 abstracts locally. It is not
hung. Scoring cost recurs on every run and scales with how many papers your
`arxiv_categories` and date window pull in.

**The first run is slower still.** `uv sync` installs the `fastembed` *library*
but not the model weights; those download from HuggingFace on the first scoring
call (~65 MB) into `user_data/cache/fastembed/`. So the first run needs network
access, and every run after it works offline for scoring.

If you see papers you care about, you're set:

```bash
uv run papertracker
```

## Credentials — where to get them

**Every one of these is optional and free.** PaperTracker runs anonymously
without any of them. arXiv, Crossref, DBLP, DataCite, Europe PMC, and OpenAIRE
need no credential at all.

| Environment variable | Where to get it | What it buys you |
|---|---|---|
| `PAPERTRACKER_EMAIL` | your own address | Crossref polite pool (higher, more reliable rate limits); also sent to OpenAlex and required by Unpaywall |
| `PAPERTRACKER_OPENALEX_API_KEY` | <https://openalex.org/settings/api> | Free key, free daily usage allowance. Raises limits for related-work search and abstract lookup |
| `PAPERTRACKER_SEMANTIC_SCHOLAR_API_KEY` | <https://www.semanticscholar.org/product/api> — request form on that page | A dedicated rate limit instead of the shared anonymous pool |
| `PAPERTRACKER_CORE_API_KEY` | <https://core.ac.uk/services/api> — register for a key | Better performance on CORE abstract lookups |
| `PAPERTRACKER_OPENCITATIONS_ACCESS_TOKEN` | <https://opencitations.net/accesstoken> — enter an email, token is mailed to you | Identified API use; OpenCitations stores no personal data |

Paper-source credentials above are free. AI summarization may consume
subscription quota or incur API usage charges, depending on how your AI CLI is
authenticated.

## Run

```bash
uv run papertracker                        # default project, last 2 days
uv run papertracker --list-projects        # list configured topics
uv run papertracker --project my-topic     # one topic
uv run papertracker --all-projects         # every topic
uv run papertracker --days 7               # wider window
uv run papertracker --sources arxiv        # one source at a time
uv run papertracker --no-summarize         # list matches, no LLM calls
uv run papertracker --priority-venues-only # only papers in your priority venues
uv run papertracker --ignore-seen --days 14   # re-summarize already-seen papers
uv run papertracker --select               # choose papers and templates in a browser tab
uv run papertracker --related-work         # all-time important work for the topic
uv run papertracker --related-work --facets # grouped related-work matrix
uv run papertracker -v                     # debug logging
```

### All CLI flags

`uv run papertracker --help` prints this list; it is reproduced here so you can
read it before installing.

**Choosing what to run**

| Flag | Default | Effect |
|---|---|---|
| `--project ID` | `default_project` | Run one profile from `user_data/projects.toml` |
| `--all-projects` | off | Run every profile in sequence |
| `--list-projects` | — | Print configured profiles and exit |
| `--related-work` | off | Related-work mode instead of the daily digest |
| `--facets` | off | Faceted related-work curation (requires `--related-work`) |

**Time window and volume**

| Flag | Default | Effect |
|---|---|---|
| `--days N` | `default_days` (2) | Fetch the last N days |
| `--start-date YYYY-MM-DD` | — | Explicit window start; overrides `--days` |
| `--end-date YYYY-MM-DD` | today | Explicit window end |
| `--max-results N` | `max_results_per_query` (1500) | Cap papers fetched **per source** |
| `--limit N` | 30 | Cap papers kept in `--related-work` output |
| `--facet-count N` | 6 | Facets to generate when none are configured (clamped to 4–7) |
| `--facet-candidates N` | 40 | OpenAlex candidates fetched per facet per discovery mode |

**Filtering**

| Flag | Default | Effect |
|---|---|---|
| `--sources a,b` | `enabled_sources_default` | Restrict to `arxiv`, `ieee`, `acm`, `journal_rss` |
| `--priority-venues-only` | `priority_venue_only` (false) | Drop papers matching no priority venue |
| `--threshold F` | `relevance_threshold` (0.65) | Override the relevance cutoff. `-1` keeps everything |
| `--scorer dense\|hybrid` | `relevance_scorer` (`dense`) | Which local scorer to use |
| `--ignore-seen` | off | Re-process papers already in `seen.json` |

**Summarization**

| Flag | Default | Effect |
|---|---|---|
| `--provider claude\|codex` | `provider` in `config.toml` | Which CLI to shell out to |
| `--model NAME` | `claude_model` / `codex_model` | Model for the selected provider |
| `--effort LEVEL` | `reasoning_effort` in `config.toml` | Thinking effort per summary: `low`, `medium`, `high`, `xhigh`, `max`, or `default` |
| `--no-summarize` | off | Skip the LLM. Daily mode prints matches; faceted related-work needs configured facets and writes conservative local annotations |
| `--select` | off | Pick papers (and templates in summary workflows) in a **browser tab**; falls back to a numbered text prompt when headless. In daily mode, overrides `--no-summarize` |
| `--template ID` | workflow default | Apply one template globally; `--select` can still override it per paper |
| `--list-templates` | — | Print every template's ID, label, evidence requirement, description, and default status |
| `--refresh-summaries` | off | Ignore the summary cache and regenerate, overwriting cached entries |

**Zotero**

| Flag | Default | Effect |
|---|---|---|
| `--list-zotero-collections` | — | Print local Zotero collection paths and exit |
| `--zotero-collection PATH` | — | Batch-summarize full PDFs in that collection |
| `--zotero-include-subcollections` | off | Also include child collections |
| `--zotero-template ID` | — | Deprecated one-release alias for `--template` |

**Other**

| Flag | Effect |
|---|---|
| `-v`, `--verbose` | DEBUG logging — shows per-paper scores, HTTP calls, and dropped papers |
| `-h`, `--help` | This list |

`--ignore-seen` and `--refresh-summaries` are different: the first controls
*which papers are considered*, the second controls *whether a cached summary is
reused* for papers that are processed.

## Where your data lives

```
summary_templates/*.md                # your summary formats (tracked in git)
user_data/                            # gitignored in full
├── projects.toml                     # your topics
├── digests/<project-id>/YYYY-MM-DD.md
├── state/<project-id>/seen.json      # papers already summarized
├── state/<project-id>/summary_cache.json
└── cache/fastembed/                  # the local embedding model
```

Digests are grouped by `## ★ Priority venues`, then `## arXiv preprints`, then
`## Other ACM / IEEE`.

Running the same project more than once in a day merges newly summarized papers
into that day's digest. An empty later run leaves the existing digest untouched.
Only successfully summarized papers enter `seen.json`; failures exit nonzero and
remain eligible for the next run.

**Moving to a new machine** is: clone, follow Setup, copy `user_data/` across.
Templates come with the clone because they are tracked, so `user_data/` is the
only thing you have to carry — unless you edited a shipped template, in which
case commit that change or copy `summary_templates/` too. To keep the data
folder outside the checkout, set `PAPERTRACKER_USER_DATA_DIR=/path/to/dir`.

## Configuration

Repository defaults, personal provider choices, and topic profiles have a clear
split:

| File | Holds | Tracked in git? |
|---|---|---|
| `config.toml` | Runtime defaults: provider, models, effort, sources, thresholds, output paths, Zotero, templates | Yes — keep it topic-neutral |
| `summary_templates/*.md` | The summary formats, one file per dropdown option | Yes — edit in place |
| `user_data/projects.toml` | Your topics, per-project overrides, and priority venues | No |
| `~/.config/papertracker/config.toml` | Your provider, provider-specific model defaults, and reasoning effort | No — outside the checkout |

Any field a project profile omits falls back to `config.toml`. Without a
`user_data/projects.toml`, PaperTracker runs a single placeholder profile built
entirely from `config.toml`.

### PaperTracker runs from a checkout

Always `uv run papertracker` from inside the clone. Its runtime defaults and its
summary templates are files in the repository, so there is nothing to read from
outside it — `uv tool install` is not supported and fails with a message saying
so. To keep your data elsewhere, point `PAPERTRACKER_USER_DATA_DIR` at any
directory; to override settings without editing the tracked `config.toml`, use
`~/.config/papertracker/config.toml` or the `PAPERTRACKER_*` variables.

### Choosing your AI provider — precedence

CLI flag wins, then environment variable, then your personal config file, then
the repo config.

| Method | How | Persistence |
|---|---|---|
| CLI flag | `uv run papertracker --provider codex` | one run |
| Env var | `export PAPERTRACKER_PROVIDER=codex` | per shell |
| Personal config | `~/.config/papertracker/config.toml` → `provider = "codex"` | global user override |
| Repo config | `config.toml` → `provider = "codex"` | project default |

`--model` and `PAPERTRACKER_MODEL` override the selected provider's configured
default. In config files, set provider-specific defaults with `claude_model` and
`codex_model`:

```toml
# ~/.config/papertracker/config.toml
provider = "codex"
claude_model = "sonnet"
codex_model = "gpt-5.6-luna"
reasoning_effort = "medium"
```

### Reasoning effort

How hard the model thinks per summary. One scale covers both providers:

```
low  <  medium  <  high  <  xhigh  <  max
```

Higher levels spend more quota and take longer per paper; nothing else about the
run changes. It ships as `medium`, and follows the same precedence as the
provider — CLI flag, env var, personal config, repo config:

| Method | How |
|---|---|
| CLI flag | `uv run papertracker --effort high` |
| Env var | `export PAPERTRACKER_EFFORT=high` |
| Personal config | `~/.config/papertracker/config.toml` → `reasoning_effort = "high"` |
| Repo config | `config.toml` → `reasoning_effort = "high"` |

Those five names are not a PaperTracker abstraction over two different vocabularies —
they are the levels both CLIs already accept under exactly these names, so the value
is forwarded through untranslated:

| Provider | What PaperTracker adds to the command |
|---|---|
| `claude` | `--effort high` |
| `codex` | `-c model_reasoning_effort="high"` |

Set `reasoning_effort = "default"` (or `--effort default`) to send neither flag and
leave each CLI on its own built-in default. That is also the right choice if you want
a level outside the shared five: Codex models vary in what they support — `gpt-5.6-luna`
takes `low` through `max`, while `gpt-5.6-sol` and `gpt-5.6-terra` add an `ultra` level
that Claude Code has no equivalent for. PaperTracker does not expose `ultra`, because a
value that silently means something different depending on the provider is worse than
one that is not offered. To use it anyway, set `--effort default` here and
`model_reasoning_effort = "ultra"` in `~/.codex/config.toml`.

To see the levels a Codex model supports, without spending any quota:

```bash
codex debug models   # per-model supported_reasoning_levels
```

Every run logs which level it resolved and where it came from:

```
INFO Effort:   high (from CLI flag --effort)
```

### Which model does what

Three different models do three different jobs. The first runs whenever a
workflow scores papers; listing configuration and Zotero-only commands do not
load it.

| Setting | Where it lives | Job | Runs when |
|---|---|---|---|
| `embedding_model` | `config.toml` | Scores every paper against your `topic_statement` | Daily and related-work scoring |
| `reranker_model` | `config.toml` (per-profile override allowed) | Cross-encoder rerank of the top candidates | Only with `relevance_scorer = "hybrid"` **and** `enable_reranker = true` |
| `claude_model` / `codex_model` | `config.toml`, or `~/.config/papertracker/config.toml` | Writes the summaries | Unless `--no-summarize` |

There are two summarizer model keys rather than one because model names are not
interchangeable between providers — this way `--provider codex` doesn't also
force you to change the model name.

### All environment variables

There is **no `.env` support** — nothing in the code loads one. Export these
from your shell profile (`~/.zshrc`, `~/.bashrc`) for persistence, or prefix a
single command (`PAPERTRACKER_EMAIL=you@example.com uv run papertracker`).

The "If unset" column names the exact file and key each variable falls back to.
Variables marked **env-only** have no config-file equivalent — the environment
is the only place to set them.

| Variable | Purpose | If unset, falls back to |
|---|---|---|
| `PAPERTRACKER_USER_DATA_DIR` | Where topics, digests, state, and caches live | **env-only** — `<repo>/user_data` in a checkout; `$XDG_DATA_HOME/papertracker` or `~/.local/share/papertracker` when installed |
| `PAPERTRACKER_PROVIDER` | `claude` or `codex` | `provider` in `~/.config/papertracker/config.toml`, then `provider` in `config.toml` (ships as `claude`) |
| `PAPERTRACKER_MODEL` | Model for the selected provider | `claude_model` / `codex_model` in `~/.config/papertracker/config.toml`, then in `config.toml` (`sonnet` / `gpt-5.6-luna`) |
| `PAPERTRACKER_EFFORT` | Thinking effort per summary, for either provider | `reasoning_effort` in `~/.config/papertracker/config.toml`, then in `config.toml` (ships as `medium`) |
| `PAPERTRACKER_EMAIL` | Crossref/OpenAlex/Unpaywall identifier | `user_email` in `config.toml` (ships empty → anonymous requests) |
| `PAPERTRACKER_ZOTERO_DIR` | Zotero data directory (holds `zotero.sqlite` + `storage/`) | `zotero_data_dir` in `config.toml` (`~/Zotero`) |
| `PAPERTRACKER_ZOTERO_LINKED_BASE` | Base dir for Zotero linked attachments (ZotFile-style) | `zotero_linked_base` in `config.toml` (ships empty) |
| `PAPERTRACKER_OPENALEX_API_KEY` | Optional free OpenAlex key | **env-only** — anonymous |
| `PAPERTRACKER_SEMANTIC_SCHOLAR_API_KEY` | Optional free Semantic Scholar key | **env-only** — anonymous |
| `PAPERTRACKER_CORE_API_KEY` | Optional free CORE key | **env-only** — anonymous |
| `PAPERTRACKER_OPENCITATIONS_ACCESS_TOKEN` | Optional free OpenCitations token | **env-only** — anonymous |
| `PAPERTRACKER_ABSTRACT_FALLBACKS` | Ordered DOI abstract providers | **env-only** — `openalex,semantic_scholar,openaire,core,europe_pmc,datacite` |
| `PAPERTRACKER_DOI_ENRICHERS` | Providers applied to relevant, unseen DOIs | **env-only** — `unpaywall,opencitations,dblp,datacite` |
| `FASTEMBED_CACHE_PATH` | Override the embedding model cache location | **env-only** — `user_data/cache/fastembed` |

## Relevance filter

Two local, non-LLM scorers:

- **`dense`** (default) — each paper's `(title + abstract)` is embedded and
  compared by cosine similarity to your `topic_statement`. Papers at or above
  `relevance_threshold` pass to the summarizer.
- **`hybrid`** — combines that dense signal with an in-process BM25 keyword
  score, using `hybrid_relevance_threshold`. Can optionally add a local
  cross-encoder reranker.

The model runs on CPU/ANE. Measured on Apple Silicon, it scores roughly 100
abstracts every 8 seconds — so a full default fetch (up to 1500 papers per
source) spends about two minutes scoring, on **every** run, not just the first.
That is the bulk of a typical run's wall clock. Narrow `arxiv_categories` or
lower `--max-results` if you want it faster.

To tune, in this order of impact:

1. **Sharpen `topic_statement`** in `user_data/projects.toml`. Longer and more
   specific discriminates better than any threshold change.
2. **Adjust the threshold** — `relevance_threshold` for `dense`,
   `hybrid_relevance_threshold` for `hybrid` — or pass `--threshold 0.7` per run.
   Higher is stricter.
3. **Switch scorer** with `relevance_scorer` or `--scorer hybrid`.

Inspect scores without spending any quota:

```bash
uv run papertracker --no-summarize --threshold -1 --days 14   # every score
```

Optional reranking for hybrid mode needs an extra dependency:

```bash
uv sync --extra rerank
```

```toml
relevance_scorer = "hybrid"
enable_reranker = true
```

## Summary templates

Active summary formats are user-owned Markdown skeletons discovered from
`summary_templates/` at the repository root. On first use, PaperTracker copies in
four curated samples only if that directory has no Markdown files:

```text
summary_templates/          # tracked in git; the only copy
├── abstract-screen.md
├── deep-human-study.md
├── deep-synthesis.md
└── deep-technical.md
```

**This is the only place templates live.** What is in this folder is exactly what
the summarizer fills in and what the `--select` dropdown offers — there is no
packaged copy shadowing it and nothing re-seeds it, so deleting a file removes
that option for good (`git checkout summary_templates/` brings it back).

To make your own, **copy a sample to a new name** and edit that. A new file is
untracked, so it never collides with a `git pull`. Editing one of the four
shipped templates works too and simply shows up as a normal modification in
`git status`.

Each direct-child `*.md` filename becomes a dropdown option for every paper.
There is no template-count limit. Every file starts with metadata that is
removed before prompting:

```markdown
<!-- papertracker-template
label = "Deep — Technical and Benchmark"
description = "Methods, training, experiments, benchmarks, and reproducibility."
evidence = "fulltext"
-->
## Executive takeaway
```

Evidence is strict: `abstract` templates receive only metadata plus the abstract
and reject papers without one; `fulltext` templates require a readable local PDF
and process every page from which `pypdf` can extract text. The selector shows
all choices and disables incompatible ones with a reason.

Use `--template ID` for a global choice. With `--select`, each paper can still
use a different template and the global choice becomes the initial selection.
Run `uv run papertracker --list-templates` to inspect the active catalog.

### How `--select` presents the choice

When stdin is a TTY, `--select` starts a short-lived HTTP server bound to
`127.0.0.1` on a random port, prints the URL, and opens your default browser at
it. Nothing is exposed off the machine, and the server closes as soon as you
submit. When stdin is **not** a TTY — a cron job, piped input — it goes straight
to a numbered text prompt instead.

In that text prompt, a bare paper number uses the default template; add
`:template-id` to choose another, e.g. `1,2:deep-human-study`. `a` selects all
papers with the default template.

**Over SSH**, stdin usually *is* a TTY, so PaperTracker still tries the browser
path. If it cannot open one it does not error — it prints the URL and waits.
Either forward that port and open it locally, or press Ctrl-C, which cancels the
selection cleanly without summarizing anything. Do not use `--select` in
unattended jobs.

Template IDs are case-sensitive filename stems, shown alphabetically. Configure
with:

```toml
summary_template_dir = "summary_templates"
default_abstract_template = "abstract-screen"
default_fulltext_template = "deep-technical"
```

A relative `summary_template_dir` resolves against the **repository root**; give
it an absolute path to keep your templates somewhere else entirely.

Cache identities
include the paper metadata and evidence, template metadata and body, provider,
model, and prompt-pipeline version, so any material edit regenerates the summary.

## Zotero PDF batch mode

Discovery summaries are abstract-based. To summarize **full PDFs** already in
your Zotero library, use `--zotero-collection`. The path is the one shown in
Zotero's collection tree, not the random `~/Zotero/storage/...` folder name.

```bash
uv run papertracker --list-zotero-collections
uv run papertracker --zotero-collection "Reading/Deep Reading"
uv run papertracker --zotero-collection "Reading/Deep Reading" --template deep-human-study
uv run papertracker --zotero-collection "Reading/Deep Reading" --select
uv run papertracker --zotero-collection "Reading/Deep Reading" --zotero-include-subcollections
```

If two collections share a leaf name, use the full path. An optional
`My Library/` prefix is accepted and ignored.

For both Claude and Codex, PaperTracker extracts text locally, preserves page
labels, processes every extractable page in bounded chunks, recursively
consolidates notes when needed, and only then fills the selected template. A
missing or image-only PDF fails before an LLM call with an `OCR required`
message; partially extractable PDFs continue with a warning. Output lands in
`user_data/digests/<project-id>/zotero/<collection>/`.

The Zotero database is opened **read-only** (copied to a temp file first), so
PaperTracker never modifies your library.

## Related-work mode

`--related-work` builds a starter bibliography for the active project's
`topic_statement`, including older highly-cited work:

```bash
uv run papertracker --project my-topic --related-work
uv run papertracker --project my-topic --related-work --limit 50
uv run papertracker --project my-topic --related-work --select
uv run papertracker --project my-topic --related-work --facets
```

Both variants ignore `--days`, do **not** update `seen.json`, and source
candidates from OpenAlex semantic search plus citation-count-sorted search
across all years.

### Two ranking modes

Related-work ranking is **not** the same as the daily digest's relevance filter.
Relevance is one input among several, and there are two different formulas
depending on whether you pass `--facets`.

**Flat — `--related-work`** (`src/papertracker/cli.py`, `_rank_related_work`)

```
score = 0.70·relevance + 0.24·citation + channel_bonus + semantic_bonus
```

- `relevance` — your local scorer, paper against the project `topic_statement`
- `citation` — `log1p(citations) / log1p(max_citations)` across the candidate
  set, so citation counts compress rather than dominate
- `channel_bonus` — `0.03` per *extra* source that surfaced the paper, capped at
  two, rewarding agreement between discovery channels
- `semantic_bonus` — `0.03` if OpenAlex semantic search found it

A paper is kept if `relevance ≥ threshold`; the bonuses affect ordering only.
Results are sorted by score and truncated to `--limit`.

**Faceted — `--related-work --facets`** (`src/papertracker/related_work.py`,
`rank_facet_candidates`)

First, 4–7 facets are generated — by the LLM from your `topic_statement` and
`contribution_statement`, or taken verbatim from `related_work_facets` in your
profile if configured, which skips that LLM call. Then **every paper is scored
twice**: once against the facet text, once against the project topic.

```
score = 0.42·facet_relevance + 0.30·project_relevance + 0.18·citation
      + source_bonus + multifacet_bonus + hit_bonus
```

- `multifacet_bonus` — `0.025` per additional facet the paper matched, capped at
  three; papers spanning facets rank higher
- `hit_bonus` — `0.04` if OpenAlex surfaced the paper under *this* facet's query

The gate is `max(facet_relevance, project_relevance) ≥ threshold`, so a paper
strong on one axis survives. Selection is then **round-robin across facets**
rather than a global sort, so a single dominant facet cannot consume the whole
`--limit`. A second LLM pass annotates each candidate with a citation role
(`foundational`, `method`, `benchmark`, `contrast`, …), why to cite it, how it
differs from your contribution, and whether that judgment came from the abstract
or metadata alone.

Output is `.facets.md` (a candidate matrix grouped by facet) plus `.facets.json`
for programmatic use. Control breadth with `--facet-count` and
`--facet-candidates`.

For a fully LLM-free faceted run, configure `related_work_facets` in the profile
and pass `--no-summarize`. PaperTracker then uses those facets and deterministic
`background` annotations. Without configured facets, that combination exits
with an actionable error because generating the facets would require an LLM.

Both modes call the same `relevance.score_texts()`, so `--scorer dense|hybrid`
composes with either.

## How discovery works without API keys

PaperTracker **never logs into IEEE Xplore or ACM Digital Library**. Both
publishers are Crossref members and deposit metadata — DOI, title, abstract when
available, authors, date — on publication day. We query Crossref filtered by
member ID (`320` = ACM, `263` = IEEE) within a date window. Free, no auth.

| Step | Endpoint | Auth | Returns |
|---|---|---|---|
| Find new ACM/IEEE papers | `api.crossref.org/works` | none | DOI, title, abstract, authors |
| Recover a missing abstract | OpenAlex, Semantic Scholar, OpenAIRE, CORE, Europe PMC, DataCite | optional free keys | first available abstract plus provenance |
| Enrich a relevant unseen DOI | Unpaywall, OpenCitations, DBLP, DataCite | optional free tokens | open-access location, citations, bibliographic metadata |
| Summarize | `claude` / `codex` CLI | subscription or API-key authentication | markdown summary |
| Read the full PDF (later, by you) | DOI link → publisher site | your institution's access | the paper |

**Timing.** arXiv preprints appear same-day, often weeks before the conference.
Crossref ACM/IEEE deposits land within ~1–14 days of publication. Journal RSS
feeds sometimes arrive 1–2 days before the Crossref deposit; DOI-based dedup
merges them.

If Crossref and every configured fallback lack an abstract, the paper is
**skipped silently** — no summary is attempted on a title alone. DOI lookups are
cached per run, and one provider failing does not stop the others.

## Customizing venues and sources

In `user_data/projects.toml` (per topic, or once at the top level for all):

- **`priority_venues`** — named venues with `container-title` substring
  `patterns`. They (a) tag papers with a `★ Venue` badge, (b) enable
  `--priority-venues-only`, and (c) drive the `journal_rss` source when an `rss`
  URL is included.
- **`arxiv_categories`** — arXiv subject categories to query. See the
  [taxonomy](https://arxiv.org/category_taxonomy).
- **`crossref_query_hint`** — a keyword string passed to Crossref as a *ranking
  hint*, not a filter.

## Privacy and data flow

Relevance scoring is local: PaperTracker downloads the embedding model and does
not send scoring vectors or scores to an AI provider. Paper discovery still
makes ordinary network requests to the configured scholarly APIs; those
requests can include categories, query hints, paper identifiers, and the
optional contact email or API credentials you configured.

When an AI step is enabled, PaperTracker sends a prompt through the selected
Claude or Codex CLI:

- Daily abstract summaries include the project name/topic statement, paper
  metadata, abstract, and chosen template.
- Facet generation and annotation include the topic statement, optional
  contribution statement, facets, candidate metadata, and available abstracts.
- Full-text Zotero summaries extract text locally, then send that extracted PDF
  text in bounded chunks along with metadata and the template. The original PDF
  file itself is not uploaded by PaperTracker.

Provider-side retention, authentication, billing, and CLI history are governed
by the CLI/provider you chose and may live outside `user_data/`. Do not process
sensitive topics or documents until those terms and local CLI settings meet your
requirements. Use `--no-summarize` to avoid AI-provider calls.

## Run it daily

PaperTracker does not install a scheduler. On macOS or Linux, you can use cron;
replace every `/absolute/path/PaperTracker` below with the real checkout path:

```cron
0 8 * * * cd /absolute/path/PaperTracker && /absolute/path/PaperTracker/.venv/bin/papertracker >> /absolute/path/PaperTracker/user_data/papertracker.log 2>&1
```

Run the command manually first. A scheduled shell must have the AI CLI on its
`PATH` and access to the same non-interactive authentication as your terminal.
Avoid `--select` in unattended jobs. PaperTracker exits nonzero if a paper source
or requested summary fails, so a scheduler can alert on incomplete runs; any
successful summaries are retained and failures are retried next time.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `'claude' not found on PATH` | Install Claude Code (<https://claude.com/code>), then `claude auth login`. |
| `'codex' not found on PATH` | Follow the [Codex CLI install guide](https://learn.chatgpt.com/docs/codex/cli), then `codex login`. |
| Empty digest every day | Lower `--threshold` (try 0.55) or broaden `topic_statement`; try `--days 7`. |
| Too much noise | Raise `--threshold` (try 0.7) or sharpen `topic_statement`. |
| `--list-projects` shows nothing | You haven't created `user_data/projects.toml` — see step 4. |
| First run is slow | It's downloading the ~65 MB embedding model into `user_data/cache/fastembed/`. `uv sync` does not fetch it. Cached afterwards. |
| Log says `capped at 1500 of N total` | Raise `max_results_per_query` in `config.toml` or pass `--max-results`. Scoring is local, so the cost here is HTTP traffic and time. |
| Re-summarize a paper you already saw | `--ignore-seen`, or delete `user_data/state/<project-id>/seen.json`. |
| Inspect matches without spending quota | `--no-summarize`, which sorts by relevance score. |

## Development

`uv sync` already installs the dev tooling. To check a clone is healthy, or
before sending a change:

```bash
uv run pytest                    # full suite, no network, seconds
uv run ruff check src tests      # lint
uv build                         # the wheel/sdist build must succeed
```

`.github/workflows/ci.yml` runs exactly those three plus `uv sync --locked`, so
a green local run means a green CI run. Tests are offline and stub every HTTP
call — nothing in the suite touches arXiv, Crossref, HuggingFace, or an AI CLI.

`config.toml` and `summary_templates/` are each a single tracked copy that the
code reads directly, so editing them needs no follow-up sync step.

## License

PaperTracker is available under the [MIT License](LICENSE).
