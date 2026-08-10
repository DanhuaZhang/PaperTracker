# Contributing

PaperTracker is a personal research tool that happens to be open source. It is
maintained by one person for one workflow, so please read this before spending
time on a change.

## What this means for pull requests

- **Open an issue first** for anything beyond a typo or an obvious bug fix.
  Describing the change costs you five minutes; building the wrong one costs an
  afternoon.
- **Small and focused merges faster.** One behaviour per pull request.
- **Not every good change belongs here.** A feature can be well built and still
  be declined because it widens the tool beyond what it is for. Forking is a
  legitimate and expected outcome — the license permits it and no hard feelings.
- Reviews happen when they happen. This is not anyone's day job.

## Before you submit

The repository runs from a source checkout; `uv tool install` is not supported.

```bash
uv sync                             # provisions Python 3.12 and dependencies
uv run pytest                       # full suite, offline, a few seconds
uv run ruff check src tests scripts # lint
uv build                            # the wheel/sdist build must succeed
```

CI runs exactly these plus `uv sync --locked`, on Ubuntu, macOS, and Windows. A
green local run means a green CI run on your platform; the matrix covers the
other two. The suite is offline and stubs every HTTP call — nothing in it
touches arXiv, Crossref, HuggingFace, or an AI CLI. **Tests must not call an AI
CLI or spend anyone's quota.**

PaperTracker is developed on macOS but supported on all three. If your change
spawns a subprocess, builds a URI from a path, writes a file, or prints
non-ASCII, add a case to `tests/test_cross_platform.py` — those are the four
things that pass locally and fail on Windows.

If you change a dependency in `pyproject.toml`, commit the updated `uv.lock`
alongside it or `uv sync --locked` fails in CI.

## Things worth knowing

- `config.toml` at the repository root holds runtime defaults and is tracked.
  There is no per-user config file: API keys go in `PAPERTRACKER_*` environment
  variables, and anything else you change for your own machine should stay
  uncommitted rather than land in `config.toml`.
- `summary_templates/abstract/` and `summary_templates/fulltext/` hold the
  single copy of the summary formats, split by the mode that offers them. A
  template's `evidence` metadata must match its folder. There is no packaged
  duplicate to keep in sync.
- Everything machine-local lives in `user_data/`, which is gitignored. Never
  commit digests, topics, or caches.

## Documentation

The manual lives in [`docs/`](docs/README.md) and README is a landing page.
Docs are versioned with the code, so a documentation fix belongs in the same
pull request as the behavior it describes.

- **Cross-page links are relative** (`configuration.md#reasoning-effort`), which
  keeps them working on GitHub, in an editor preview, and in a clone.
- **Tables of contents are generated.** After adding or renaming a heading:

  ```bash
  uv run python scripts/update_toc.py
  ```

  A page opts in by having a `## Contents` heading; short pages skip it.
- **No screenshots.** The docs are text only: describe the UI in prose and paste
  real terminal output into a fenced block. That keeps every change reviewable
  in a diff and keeps anyone's real library out of a public image.

`tests/test_docs_links.py` fails on a dangling anchor, a link to a page that
does not exist, an image that was referenced but never committed, or a stale
table of contents.

## Reporting a security issue

Please use GitHub's private vulnerability reporting on this repository rather
than opening a public issue.
