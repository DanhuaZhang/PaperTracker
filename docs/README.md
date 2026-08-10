# PaperTracker documentation

Start with [Use cases](use-cases.md) if you want to see what a session looks
like, or [Setup](setup.md) if you just want it running.

## Guides

| Page | What it covers |
|---|---|
| [Use cases](use-cases.md) | Five workflows end to end |
| [Setup](setup.md) | Install on macOS, Linux, Windows; optional free credentials |
| [Usage](usage.md) | Every CLI flag, what gets written where, scheduling |
| [Configuration](configuration.md) | Config file split, provider/model/effort precedence, relevance tuning, all environment variables |
| [Summary templates](templates.md) | Writing formats, and how the `--select` UI presents them |
| [Zotero PDF batch mode](zotero.md) | Full-text summaries from your local library |
| [Related-work mode](related-work.md) | Starter bibliographies and the two ranking formulas |
| [Troubleshooting](troubleshooting.md) | Common symptoms, plus Windows notes |

## Reference and background

| Page | What it covers |
|---|---|
| [How discovery works](discovery.md) | Why no publisher login is needed; every source with its rate limits and reuse terms; customizing venues |
| [Privacy and data flow](privacy.md) | What stays local, what leaves, what goes to an AI provider |

The ranking formulas themselves are documented where they are used:
[Relevance filter](configuration.md#relevance-filter) for the daily digest, and
[Two ranking modes](related-work.md#two-ranking-modes) for related work.

## Contributing to the docs

Pages are plain Markdown, versioned with the code, so a documentation fix ships
in the same pull request as the behavior it describes.

- Cross-page links are **relative** (`configuration.md#reasoning-effort`), which
  keeps them working on GitHub, in a local editor preview, and in a clone.
- The docs are **text only** — no screenshots. Describe a UI in prose and show
  real terminal output in a fenced block; both stay readable in a diff, survive
  a redesign, and cannot leak a real library into a public image.
- Long pages carry a generated table of contents. After adding a heading, run
  `uv run python scripts/update_toc.py`.
- `tests/test_docs_links.py` fails on a dangling anchor, a missing page, a
  missing image, or a stale table of contents.
