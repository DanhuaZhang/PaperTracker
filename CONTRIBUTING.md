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
uv sync                          # provisions Python 3.12 and dependencies
uv run pytest                    # full suite, offline, a few seconds
uv run ruff check src tests      # lint
uv build                         # the wheel/sdist build must succeed
```

CI runs exactly these plus `uv sync --locked`, so a green local run means a
green CI run. The suite is offline and stubs every HTTP call — nothing in it
touches arXiv, Crossref, HuggingFace, or an AI CLI. **Tests must not call an AI
CLI or spend anyone's quota.**

If you change a dependency in `pyproject.toml`, commit the updated `uv.lock`
alongside it or `uv sync --locked` fails in CI.

## Things worth knowing

- `config.toml` at the repository root holds runtime defaults and is tracked.
  Personal settings belong in `~/.config/papertracker/config.toml` or
  `PAPERTRACKER_*` environment variables — please don't commit changes to
  `config.toml` just to configure your own machine.
- `summary_templates/*.md` is the single copy of the summary formats. There is
  no packaged duplicate to keep in sync.
- Everything machine-local lives in `user_data/`, which is gitignored. Never
  commit digests, topics, or caches.

## Reporting a security issue

Please use GitHub's private vulnerability reporting on this repository rather
than opening a public issue.
