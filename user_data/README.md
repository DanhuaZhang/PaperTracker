# user_data

PaperTracker-owned personal and machine-local data lives here. The whole folder
is gitignored except this file and `.gitkeep`, so runtime data is not committed.
The selected AI CLI manages its own authentication and history separately.

Create your topics file to get started:

```bash
cp ../projects.example.toml projects.toml   # then edit it
```

Summary templates are **not** here — they live in `summary_templates/` at the
repository root and are tracked in git. If this folder still contains a
`summary_templates/` directory from an older version, nothing reads it any more
and you can delete it.

| Path | What it is | Safe to delete? |
|---|---|---|
| `projects.toml` | Your research topics and per-project settings | No — this is your configuration |
| `digests/<project-id>/` | Generated markdown digests | Yes, but you lose past digests |
| `state/<project-id>/seen.json` | Papers already summarized, so re-runs skip them | Yes — re-runs will re-summarize |
| `state/<project-id>/summary_cache.json` | Cached summaries, keyed by paper + template | Yes — costs quota to rebuild |
| `cache/fastembed/` | The ~65 MB local embedding model | Yes — re-downloads on next run |

Moving to a new machine? Copy this folder across — it holds your topics, your
digest history, and your summary cache. Templates ride along with the clone
because they are tracked in git. AI CLI authentication and history are managed
separately by the provider's CLI and may also be machine-specific.

To store it outside the checkout, set `PAPERTRACKER_USER_DATA_DIR=/path/to/dir`.
