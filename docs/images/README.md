# Screenshots

Every image referenced by the docs lives here and is committed to the
repository, referenced with a relative path (`images/name.png`) so it renders on
GitHub, in a local editor preview, and in a plain clone alike.

This file is the capture checklist. Four screenshots are pending; the `<img>`
tags are already written and sitting commented out at each slot, so capturing
one is: take the shot, save it here under the exact filename, uncomment the
block.

## Capture these with a demo profile, not your real one

**This repository is public.** A screenshot of your live setup exposes the paper
titles you are tracking, your Zotero collection names, and — in any visible path
— your username. That can reveal an unpublished research direction.

Add a throwaway profile to `user_data/projects.toml` and screenshot that:

```toml
[projects.demo]
name = "Demo — molecular property prediction"
topic_statement = """
Graph neural networks for molecular property prediction: message passing
architectures, equivariant models, learned force fields, and benchmarks for
predicting quantum-chemical properties from molecular graphs.
"""
crossref_query_hint = "graph neural network molecular property prediction"
arxiv_categories = ["cs.LG"]
```

It is a well-populated topic, so runs return real results, and nothing in the
output is yours. Delete it afterwards or leave it — `user_data/` is gitignored.

## The checklist

| File | Shows | Capture with |
|---|---|---|
| `terminal-triage.png` | The scored listing in a terminal, colors visible | `uv run papertracker --project demo --no-summarize --days 7` |
| `selector-daily.png` | The `--select` browser page: checkboxes, score badges, per-paper template dropdowns | `uv run papertracker --project demo --select --days 7` |
| `zotero-collections.png` | Zotero's sidebar with a nested collection tree | Zotero itself — make a `Reading/Deep Reading` collection with 2–3 public papers |
| `selector-related-work.png` | The related-work selector with citation-role dropdowns | `uv run papertracker --project demo --related-work --select --limit 15` |

`--select` opens a browser tab; screenshot the browser window, cropped to the
page content. Nothing is served off `127.0.0.1`, so there is no URL worth
hiding, but crop the address bar anyway — it is noise.

## Before you commit an image

1. **Re-read it.** Titles, venue names, collection names, any path in a
   title bar. If anything is yours rather than the demo profile's, reshoot.
2. **Constrain the display width**, don't rely on the raw pixels. Capturing on a
   Retina display gives you 2× pixels; commit that file for crispness but set
   the width in the tag:

   ```html
   <img src="images/selector-daily.png" alt="…" width="820">
   ```

   820 for full-width UI shots, 420 for a narrow sidebar.
3. **Always write alt text** describing what the image shows, not its filename.
   The commented-out tags already have it — keep it accurate if you reframe.
4. **Compress.** A UI screenshot should land well under 100 KB:

   ```bash
   oxipng -o 4 --strip safe docs/images/*.png    # or: pngquant --quality 65-85
   ```

   Git keeps every revision of a binary forever, so a reshoot costs the full
   file size again. Lean files matter more here than in a normal folder.

## Why not host them outside the repo

Dragging an image into a GitHub issue and using the resulting URL is the usual
shortcut, and it is the wrong one here. GitHub serves assets uploaded to private
repositories from `private-user-images.githubusercontent.com` with an expiring
token in the URL, so those links break. More importantly the file lives nowhere
in the repository: it is absent from clones, unversioned, and invisible to the
link test that checks every referenced image actually exists.
