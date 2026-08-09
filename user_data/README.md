# user_data

PaperTracker-owned personal and machine-local data lives here. The whole folder
is gitignored except this file and `.gitkeep`, so runtime data is not committed.
The selected AI CLI manages its own authentication and history separately.

Create your topics file to get started; summary templates are seeded here on
first use and can also be edited by hand:

```bash
cp ../projects.example.toml projects.toml   # then edit it
```

| Path | What it is | Safe to delete? |
|---|---|---|
| `projects.toml` | Your research topics and per-project settings | No — this is your configuration |
| `summary_templates/*.md` | Your unlimited, editable summary templates (seeded on first use) | No — these control summary structure and evidence requirements |
| `digests/<project-id>/` | Generated markdown digests | Yes, but you lose past digests |
| `state/<project-id>/seen.json` | Papers already summarized, so re-runs skip them | Yes — re-runs will re-summarize |
| `state/<project-id>/summary_cache.json` | Cached summaries, keyed by paper + template | Yes — costs quota to rebuild |
| `cache/fastembed/` | The ~65 MB local embedding model | Yes — re-downloads on next run |

Moving to a new machine? Copy this folder across and you keep your topics, your
digest history, and your summary cache. AI CLI authentication and history are
managed separately by the provider's CLI and may also be machine-specific.

To store it outside the checkout, set `PAPERTRACKER_USER_DATA_DIR=/path/to/dir`.
