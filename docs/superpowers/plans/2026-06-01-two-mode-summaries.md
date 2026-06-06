# Two-Mode Paper Summaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick, per paper in the browser selector, between a quick "Triage" summary (today's relevance bullets) and a "Deep" summary rendered into the user's own Obsidian template — both reading the full PDF from the local Zotero library when available, falling back to the abstract otherwise.

**Architecture:** A new `zotero.py` module resolves a paper to its on-disk PDF by reading a read-only copy of `zotero.sqlite`. The selector tags each chosen paper with a `mode` (`"triage"` | `"deep"`). `summarizer.py` gains a `mode` parameter: it picks the prompt (triage = existing template; deep = user's Obsidian template, read from a configured file), and when a PDF is found it invokes `claude -p` with the `Read` tool enabled and the PDF path in the prompt; otherwise it summarizes the abstract and marks the result abstract-based. The summary cache key is extended with the mode so the two summary kinds never collide.

**Tech Stack:** Python 3.12, stdlib only for new code (`sqlite3`, `shutil`, `tempfile`, `pathlib`), `pytest`, the `claude` CLI (subscription quota, no API key).

---

## Scope notes & decisions (locked with the user)

- **Mode selection:** per-paper in the browser selector (and text fallback). Mixed modes allowed in one run.
- **Text source:** full PDF for both modes, sourced **from the local Zotero library** (papers are filed in Zotero before summarizing). No match → abstract-only, tagged as such.
- **PDF→LLM:** the CLI reads the PDF directly (`Read` tool enabled), not local text extraction.
- **Output:** stays in the digest markdown; no Obsidian vault writes.
- **Provider:** full-text-via-`Read` is implemented for `claude` (the default). For `codex`, deep mode degrades to abstract-based with a logged warning (full-text codex support is out of scope for this plan).
- **Obsidian template:** read at runtime from a configured file path; a built-in default template is used when none is configured.

---

## File Structure

- **Create** `src/papertracker/zotero.py` — resolve `paper -> Path | None` (local PDF) via read-only SQLite. One responsibility: Zotero lookup.
- **Create** `tests/test_zotero.py` — builds a throwaway SQLite + storage fixture and asserts resolution.
- **Create** `tests/test_selector_modes.py` — form/text parsing of per-paper modes.
- **Create** `tests/test_summarizer_modes.py` — prompt selection + command construction per mode (subprocess mocked).
- **Modify** `src/papertracker/config.py` — add `ZOTERO_DATA_DIR`, `OBSIDIAN_TEMPLATE_PATH`, `DEFAULT_OBSIDIAN_TEMPLATE`, and the deep-mode prompt scaffolding.
- **Modify** `src/papertracker/selector.py` — per-card mode control in HTML + text fallback; set `paper["mode"]`.
- **Modify** `src/papertracker/summarizer.py` — `summarize_paper(paper, provider, model, mode)`; PDF-aware claude invocation; abstract fallback.
- **Modify** `src/papertracker/summary_cache.py` — key by `(canonical_id, mode)`.
- **Modify** `src/papertracker/cli.py` — thread `mode` through the summarize loop and cache calls.
- **Modify** `src/papertracker/digest_writer.py` — small "abstract-based" tag when full text was unavailable.

If `tests/` does not yet exist, create it and add an empty `tests/__init__.py` in Task 1, Step 1.

---

## Task 1: Zotero PDF resolver

**Files:**
- Create: `src/papertracker/zotero.py`
- Test: `tests/test_zotero.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zotero.py
import sqlite3
from pathlib import Path

from papertracker import zotero


def _make_zotero(tmp_path: Path, *, doi: str, title: str, filename: str) -> Path:
    """Build a minimal Zotero data dir: zotero.sqlite + a stored PDF."""
    data_dir = tmp_path / "Zotero"
    storage = data_dir / "storage" / "ABCD1234"
    storage.mkdir(parents=True)
    (storage / filename).write_bytes(b"%PDF-1.4 fake")

    db = data_dir / "zotero.sqlite"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
        CREATE TABLE itemAttachments
            (itemID INTEGER, parentItemID INTEGER, contentType TEXT, path TEXT);
        """
    )
    # parent item (key irrelevant) + attachment item (key drives storage folder)
    con.execute("INSERT INTO items VALUES (1, 'PARENT01')")
    con.execute("INSERT INTO items VALUES (2, 'ABCD1234')")
    con.execute("INSERT INTO fields VALUES (1, 'DOI')")
    con.execute("INSERT INTO fields VALUES (2, 'title')")
    con.execute("INSERT INTO itemDataValues VALUES (1, ?)", (doi,))
    con.execute("INSERT INTO itemDataValues VALUES (2, ?)", (title,))
    con.execute("INSERT INTO itemData VALUES (1, 1, 1)")
    con.execute("INSERT INTO itemData VALUES (1, 2, 2)")
    con.execute(
        "INSERT INTO itemAttachments VALUES (2, 1, 'application/pdf', ?)",
        (f"storage:{filename}",),
    )
    con.commit()
    con.close()
    return data_dir


def test_find_pdf_by_doi(tmp_path):
    data_dir = _make_zotero(tmp_path, doi="10.1/xyz", title="A Paper", filename="a.pdf")
    paper = {"doi": "10.1/XYZ", "title": "irrelevant", "abstract": ""}
    pdf = zotero.find_pdf(paper, data_dir=data_dir)
    assert pdf is not None
    assert pdf.name == "a.pdf"
    assert pdf.exists()


def test_find_pdf_by_title_when_no_doi(tmp_path):
    data_dir = _make_zotero(tmp_path, doi="10.1/xyz", title="A Paper", filename="a.pdf")
    paper = {"doi": None, "title": "  a paper ", "abstract": ""}
    assert zotero.find_pdf(paper, data_dir=data_dir) is not None


def test_find_pdf_returns_none_when_absent(tmp_path):
    data_dir = _make_zotero(tmp_path, doi="10.1/xyz", title="A Paper", filename="a.pdf")
    paper = {"doi": "10.9/none", "title": "Nothing Here", "abstract": ""}
    assert zotero.find_pdf(paper, data_dir=data_dir) is None


def test_find_pdf_missing_data_dir(tmp_path):
    assert zotero.find_pdf({"doi": "x", "title": "y"}, data_dir=tmp_path / "nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_zotero.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'papertracker.zotero'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/papertracker/zotero.py
"""Resolve a paper to its local Zotero PDF by reading a read-only copy of zotero.sqlite.

Zotero 7's local HTTP API exposes no reliable attachment-file endpoint, so we read
the SQLite DB directly. Zotero locks the live DB, so we copy it to a temp file first
(per Zotero's "Direct SQLite Database Access" guidance) and open read-only.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


def _normalize_title(t: str) -> str:
    return " ".join((t or "").split()).strip().lower()


def find_pdf(paper: dict, data_dir: Path | None = None) -> Path | None:
    """Return the local PDF path for `paper` if it exists in Zotero, else None.

    Matches by DOI (preferred), then by normalized title.
    """
    data_dir = Path(data_dir) if data_dir is not None else config.zotero_data_dir()
    db = data_dir / "zotero.sqlite"
    if not db.exists():
        log.debug("Zotero DB not found at %s", db)
        return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_db = Path(tmp) / "zotero.sqlite"
        try:
            shutil.copy2(db, tmp_db)
            con = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True)
        except (OSError, sqlite3.Error) as e:
            log.warning("Could not open Zotero DB: %s", e)
            return None
        try:
            item_id = _match_item(con, paper)
            if item_id is None:
                return None
            return _attachment_path(con, item_id, data_dir)
        finally:
            con.close()


def _match_item(con: sqlite3.Connection, paper: dict) -> int | None:
    doi = (paper.get("doi") or "").strip().lower()
    if doi:
        row = con.execute(
            """
            SELECT id.itemID FROM itemData id
            JOIN fields f ON f.fieldID = id.fieldID
            JOIN itemDataValues v ON v.valueID = id.valueID
            WHERE f.fieldName = 'DOI' AND lower(v.value) = ?
            LIMIT 1
            """,
            (doi,),
        ).fetchone()
        if row:
            return row[0]

    title = _normalize_title(paper.get("title") or "")
    if title:
        row = con.execute(
            """
            SELECT id.itemID FROM itemData id
            JOIN fields f ON f.fieldID = id.fieldID
            JOIN itemDataValues v ON v.valueID = id.valueID
            WHERE f.fieldName = 'title' AND lower(trim(v.value)) = ?
            LIMIT 1
            """,
            (title,),
        ).fetchone()
        if row:
            return row[0]
    return None


def _attachment_path(con: sqlite3.Connection, parent_id: int, data_dir: Path) -> Path | None:
    rows = con.execute(
        """
        SELECT i.key, a.path FROM itemAttachments a
        JOIN items i ON i.itemID = a.itemID
        WHERE a.parentItemID = ? AND a.contentType = 'application/pdf'
        """,
        (parent_id,),
    ).fetchall()
    for key, path in rows:
        if not path:
            continue
        if path.startswith("storage:"):
            candidate = data_dir / "storage" / key / path[len("storage:"):]
        elif path.startswith("attachments:"):
            base = config.zotero_linked_base_dir()
            if base is None:
                continue
            candidate = base / path[len("attachments:"):]
        else:
            candidate = Path(path)  # absolute linked path
        if candidate.exists():
            return candidate
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_zotero.py -v`
Expected: PASS (4 passed). If `papertracker` is not importable, run `uv pip install -e .` first.

- [ ] **Step 5: Commit**

```bash
git add src/papertracker/zotero.py tests/test_zotero.py
git commit -m "feat: resolve local Zotero PDF for a paper via read-only sqlite"
```

---

## Task 2: Config for Zotero dir and Obsidian template

**Files:**
- Modify: `src/papertracker/config.py`
- Test: covered indirectly by Task 1 (`config.zotero_data_dir`) and Task 4.

- [ ] **Step 1: Add config entries and helpers**

Append to `src/papertracker/config.py`:

```python
from pathlib import Path

# --- Zotero integration -----------------------------------------------------
# Default macOS/Linux data dir is ~/Zotero. Override with PAPERTRACKER_ZOTERO_DIR.
def zotero_data_dir() -> Path:
    env = os.environ.get("PAPERTRACKER_ZOTERO_DIR")
    return Path(env).expanduser() if env else Path.home() / "Zotero"


def zotero_linked_base_dir() -> Path | None:
    """Base dir for Zotero 'Linked Attachment Base Directory' (ZotFile-style)."""
    env = os.environ.get("PAPERTRACKER_ZOTERO_LINKED_BASE")
    return Path(env).expanduser() if env else None


# --- Obsidian deep-summary template ----------------------------------------
# Path to the user's Obsidian paper-note template. When unset, DEFAULT below is used.
def obsidian_template() -> str:
    env = os.environ.get("PAPERTRACKER_OBSIDIAN_TEMPLATE")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p.read_text(encoding="utf-8")
    return DEFAULT_OBSIDIAN_TEMPLATE


DEFAULT_OBSIDIAN_TEMPLATE = """\
---
title:
authors:
year:
venue:
tags: [paper]
---
## TL;DR
## Problem
## Method
## Results
## My take / relevance to my work
"""
```

- [ ] **Step 2: Verify import works**

Run: `uv run python -c "from papertracker import config; print(config.zotero_data_dir()); print(config.obsidian_template()[:20])"`
Expected: prints a path ending in `/Zotero` and the first line of the default template.

- [ ] **Step 3: Commit**

```bash
git add src/papertracker/config.py
git commit -m "feat: config for Zotero data dir and Obsidian template path"
```

---

## Task 3: Per-paper mode in the selector

**Files:**
- Modify: `src/papertracker/selector.py`
- Test: `tests/test_selector_modes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_selector_modes.py
from papertracker import selector


def test_form_parsing_assigns_modes():
    form = {"sel": ["0", "2"], "mode_0": ["deep"], "mode_2": ["triage"]}
    assert selector._selections_from_form(form, 3) == [(0, "deep"), (2, "triage")]


def test_form_parsing_defaults_to_triage():
    form = {"sel": ["1"]}  # no mode_1 key
    assert selector._selections_from_form(form, 3) == [(1, "triage")]


def test_form_cancel_returns_empty():
    assert selector._selections_from_form({"cancel": ["1"], "sel": ["0"]}, 3) == []


def test_text_parsing_modes():
    # bare number = triage; trailing 'd' = deep
    assert selector._parse_selection("1, 3d", 3) == [(0, "triage"), (2, "deep")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_selector_modes.py -v`
Expected: FAIL with `AttributeError: module 'papertracker.selector' has no attribute '_selections_from_form'`

- [ ] **Step 3: Replace index parsing with (index, mode) parsing**

In `src/papertracker/selector.py`, replace `_indices_from_form` with:

```python
def _selections_from_form(form: dict[str, list[str]], n: int) -> list[tuple[int, str]]:
    """Map a parsed POST form to a sorted list of (index, mode) pairs."""
    if "cancel" in form:
        return []
    out: list[tuple[int, str]] = []
    for v in form.get("sel", []):
        if not v.isdigit():
            continue
        i = int(v)
        if not (0 <= i < n):
            continue
        mode = (form.get(f"mode_{i}", ["triage"])[0]).strip().lower()
        if mode not in ("triage", "deep"):
            mode = "triage"
        out.append((i, mode))
    return sorted(out)
```

Update `do_POST` in `_make_server` to call it and store pairs:

```python
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            result["selected"] = _selections_from_form(form, n)
            self._send(_done_html(len(result["selected"])))
```

Change the `result` type annotation and `_select_html`'s return to attach the mode:

```python
    result: dict[str, list[tuple[int, str]] | None] = {"selected": None}
```

```python
    # end of _select_html:
    out = []
    for i, mode in (result["selected"] or []):
        paper = dict(ordered[i])
        paper["mode"] = mode
        out.append(paper)
    return out
```

- [ ] **Step 4: Update `_parse_selection` (text fallback) to return modes**

```python
def _parse_selection(raw: str, n: int) -> list[tuple[int, str]]:
    """Parse '1,3d', '1-3', 'a'/'all', '' into sorted (0-based index, mode) pairs.

    A trailing 'd' on a token marks deep mode; otherwise triage. 'a'/'all' = all triage.
    """
    raw = raw.strip().lower()
    if not raw:
        return []
    if raw in ("a", "all"):
        return [(i, "triage") for i in range(n)]
    chosen: dict[int, str] = {}
    for tok in raw.replace(" ", "").split(","):
        if not tok:
            continue
        mode = "triage"
        if tok.endswith("d"):
            mode, tok = "deep", tok[:-1]
        if "-" in tok:
            lo, _, hi = tok.partition("-")
            if lo.isdigit() and hi.isdigit():
                for v in range(int(lo), int(hi) + 1):
                    if 1 <= v <= n:
                        chosen[v - 1] = mode
        elif tok.isdigit():
            v = int(tok)
            if 1 <= v <= n:
                chosen[v - 1] = mode
    return sorted(chosen.items())
```

Update `_select_fallback`'s return and prompt text:

```python
    try:
        raw = input("Pick papers (e.g. '1,3' triage, '2d' deep; 'a'=all triage, enter=none): ")
    except EOFError:
        raw = ""
    out = []
    for i, mode in _parse_selection(raw, len(ordered)):
        paper = dict(ordered[i])
        paper["mode"] = mode
        out.append(paper)
    return out
```

- [ ] **Step 5: Add the per-card mode control to the HTML**

In `_card`, after the checkbox input, add a mode dropdown (only meaningful when checked; default triage):

```python
        f'<input type="checkbox" name="sel" value="{i}">'
        f'<select name="mode_{i}" class="mode" onclick="event.stopPropagation()">'
        f'<option value="triage">Triage</option>'
        f'<option value="deep">Deep (Obsidian)</option>'
        f'</select>'
```

Add to `_CSS`: `.mode{margin-top:2px;background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:5px;font:inherit;padding:2px 4px}`

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_selector_modes.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Commit**

```bash
git add src/papertracker/selector.py tests/test_selector_modes.py
git commit -m "feat: per-paper triage/deep mode in selector (HTML + text fallback)"
```

---

## Task 4: Mode-aware summarizer with PDF reading

**Files:**
- Modify: `src/papertracker/summarizer.py`
- Test: `tests/test_summarizer_modes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_summarizer_modes.py
from unittest import mock

from papertracker import summarizer


def test_build_prompt_triage_uses_abstract():
    paper = {"title": "T", "abstract": "A", "doi": None}
    prompt, uses_pdf = summarizer.build_prompt(paper, mode="triage", pdf_path=None)
    assert "A" in prompt and "Core objective" in prompt
    assert uses_pdf is False


def test_build_prompt_deep_includes_template_and_pdf(tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF")
    paper = {"title": "T", "abstract": "A", "doi": None}
    prompt, uses_pdf = summarizer.build_prompt(paper, mode="deep", pdf_path=pdf)
    assert "## TL;DR" in prompt          # from default Obsidian template
    assert str(pdf) in prompt            # model is told where to read
    assert uses_pdf is True


def test_claude_command_enables_read_when_pdf_present(tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF")
    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")
        with mock.patch("papertracker.summarizer.zotero.find_pdf", return_value=pdf):
            summarizer.summarize_paper(
                {"title": "T", "abstract": "A", "doi": None}, "claude", "sonnet", "deep"
            )
        cmd = run.call_args.args[0]
        assert "--allowedTools" in cmd and "Read" in cmd
        assert "--add-dir" in cmd
        assert "--disallowed-tools" not in cmd


def test_claude_command_sandboxed_when_no_pdf():
    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")
        with mock.patch("papertracker.summarizer.zotero.find_pdf", return_value=None):
            summarizer.summarize_paper(
                {"title": "T", "abstract": "A", "doi": None}, "claude", "sonnet", "triage"
            )
        cmd = run.call_args.args[0]
        assert "--disallowed-tools" in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_summarizer_modes.py -v`
Expected: FAIL with `AttributeError: module 'papertracker.summarizer' has no attribute 'build_prompt'`

- [ ] **Step 3: Implement mode-aware prompting + PDF-aware claude call**

In `src/papertracker/summarizer.py`:

1. Add `from . import zotero` to the imports (alongside `from . import config`).

2. Keep the existing `_PROMPT_TEMPLATE` as `_TRIAGE_TEMPLATE` (rename) and add deep templates:

```python
_TRIAGE_TEMPLATE = _PROMPT_TEMPLATE  # existing bullet template, unchanged

_DEEP_HEADER = """\
You are a research assistant for an embodied-AI / XR researcher.
Fill in the following Obsidian note template for the paper, in markdown.

Rules:
- Reproduce the template's frontmatter and headings EXACTLY.
- Fill each section concisely from the paper's actual content; cite numbers/dataset names.
- If a section needs the author's personal judgement (e.g. "My take"), leave it blank
  for the user to complete after their own reading — do not invent an opinion.
- Do not add sections that aren't in the template. Output the filled template only.

Template to fill:
{template}
"""

_PDF_INSTRUCTION = (
    "Read the full paper PDF at this path and base your answer on it:\n{pdf_path}\n\n"
)
_ABSTRACT_INSTRUCTION = "Base your answer on this title and abstract only.\n\n"
```

3. Add `build_prompt` and rewrite `summarize_paper`:

```python
def build_prompt(paper: dict, mode: str, pdf_path) -> tuple[str, bool]:
    """Return (prompt, uses_pdf). uses_pdf drives whether the Read tool is enabled."""
    uses_pdf = pdf_path is not None
    source = (
        _PDF_INSTRUCTION.format(pdf_path=pdf_path) if uses_pdf else _ABSTRACT_INSTRUCTION
    )
    meta = f"Title: {paper['title']}\n\nAbstract: {paper.get('abstract', '')}\n"
    if mode == "deep":
        body = _DEEP_HEADER.format(template=config.obsidian_template())
    else:
        body = _TRIAGE_TEMPLATE.format(title=paper["title"], abstract=paper.get("abstract", ""))
        # triage template already embeds title/abstract; only prepend the source note
        return source + body, uses_pdf
    return source + body + "\n" + meta, uses_pdf


def summarize_paper(paper: dict, provider: str, model: str, mode: str = "triage") -> str:
    pdf_path = None
    if provider == "claude":  # full-text-via-Read implemented for claude only
        pdf_path = zotero.find_pdf(paper)
        if pdf_path is None:
            log.info("No Zotero PDF for %s — summarizing from abstract", paper.get("canonical_id"))
    prompt, uses_pdf = build_prompt(paper, mode, pdf_path)
    if provider == "claude":
        return _summarize_claude(prompt, model, pdf_path if uses_pdf else None)
    if provider == "codex":
        return _summarize_codex(prompt, model)
    raise ValueError(f"Unknown provider: {provider}")
```

4. Update `_summarize_claude` to optionally enable `Read`:

```python
def _summarize_claude(prompt: str, model: str, pdf_path=None) -> str:
    cmd = ["claude", "-p", "--model", model, "--output-format", "text"]
    if pdf_path is not None:
        cmd += ["--allowedTools", "Read", "--add-dir", str(pdf_path.parent)]
    else:
        cmd += ["--disallowed-tools", "*"]
    result = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True,
        timeout=config.SUMMARY_TIMEOUT_SEC, check=True,
    )
    return result.stdout.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_summarizer_modes.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/papertracker/summarizer.py tests/test_summarizer_modes.py
git commit -m "feat: mode-aware summarizer; claude reads Zotero PDF when available"
```

---

## Task 5: Mode-scoped summary cache

**Files:**
- Modify: `src/papertracker/summary_cache.py`
- Test: extend `tests/test_zotero.py`? No — add `tests/test_summary_cache_modes.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_summary_cache_modes.py
from papertracker import summary_cache


def test_lookup_is_mode_scoped():
    cache = {"arxiv:1::triage": {"summary": "T"}, "arxiv:1::deep": {"summary": "D"}}
    paper = {"canonical_id": "arxiv:1"}
    assert summary_cache.lookup(cache, paper, "triage") == "T"
    assert summary_cache.lookup(cache, paper, "deep") == "D"


def test_lookup_misses_other_mode():
    cache = {"arxiv:1::triage": {"summary": "T"}}
    assert summary_cache.lookup(cache, {"canonical_id": "arxiv:1"}, "deep") is None


def test_cache_key():
    assert summary_cache.cache_key("arxiv:1", "deep") == "arxiv:1::deep"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_summary_cache_modes.py -v`
Expected: FAIL with `TypeError: lookup() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Add mode to key + lookup**

```python
def cache_key(canonical_id: str, mode: str) -> str:
    return f"{canonical_id}::{mode}"


def lookup(cache: dict[str, dict], paper: dict, mode: str) -> str | None:
    for cid in paper.get("merged_ids", [paper["canonical_id"]]):
        entry = cache.get(cache_key(cid, mode))
        if entry and entry.get("summary"):
            return entry["summary"]
    return None
```

(`load` and `save` are unchanged — they store whatever keys the caller provides.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_summary_cache_modes.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/papertracker/summary_cache.py tests/test_summary_cache_modes.py
git commit -m "feat: scope summary cache by (canonical_id, mode)"
```

---

## Task 6: Wire mode through the CLI loop

**Files:**
- Modify: `src/papertracker/cli.py`

- [ ] **Step 1: Use the per-paper mode in the summarize loop**

In `main()`, the selected papers already carry `paper["mode"]` (Task 3). For the non-select paths (`--no-summarize` is unaffected; default run has no selector), default the mode to `"triage"`:

```python
    else:
        to_summarize = new_papers
        for p in to_summarize:
            p.setdefault("mode", "triage")
```

In the cache loop, thread the mode into lookup and the stored key:

```python
    for i, paper in enumerate(to_summarize, 1):
        mode = paper.get("mode", "triage")
        cached = None if args.refresh_summaries else summary_cache.lookup(cache, paper, mode)
        if cached is not None:
            cache_hits += 1
            log.info("Cached [%d/%d] (%s) %s", i, len(to_summarize), mode, paper["title"][:60])
            pairs.append((paper, cached))
            continue

        log.info("Summarizing [%d/%d] (%s) %s", i, len(to_summarize), mode, paper["title"][:60])
        try:
            summary = summarizer.summarize_paper(paper, provider, model, mode)
            new_cache_entries[summary_cache.cache_key(paper["canonical_id"], mode)] = {
                "summary": summary, "model": model, "provider": provider,
                "mode": mode, "generated": today_str,
            }
        except subprocess.CalledProcessError as e:
            ...  # unchanged error handling
```

- [ ] **Step 2: Manual smoke test (no LLM call)**

Run: `uv run papertracker --no-summarize --days 2`
Expected: prints the matched paper list as before (no behavior change on this path).

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/papertracker/cli.py
git commit -m "feat: thread per-paper mode through summarize + cache loop"
```

---

## Task 7: Tag abstract-based summaries in the digest

**Files:**
- Modify: `src/papertracker/digest_writer.py`, `src/papertracker/summarizer.py`

- [ ] **Step 1: Mark abstract fallback in the returned summary**

In `summarizer.summarize_paper`, when `provider == "claude"` and `pdf_path is None`, prefix the result so the digest can show it:

```python
    out = _summarize_claude(prompt, model, pdf_path if uses_pdf else None)
    if provider == "claude" and pdf_path is None:
        return "> _Abstract-based (no Zotero PDF found)._\n\n" + out
    return out
```

(Adjust the return structure of `summarize_paper` accordingly so both providers return a string.)

- [ ] **Step 2: Manual verification**

Run a real selection with one paper you have in Zotero (deep) and one you don't:
`uv run papertracker --select --days 5`
Expected: the digest shows the in-Zotero paper rendered in your Obsidian template; the other shows the "Abstract-based" note above today's bullets.

- [ ] **Step 3: Commit**

```bash
git add src/papertracker/summarizer.py src/papertracker/digest_writer.py
git commit -m "feat: label abstract-based summaries when no Zotero PDF is found"
```

---

## Task 8: Docs

**Files:**
- Modify: `README.md` (or the project's usage docs)

- [ ] **Step 1: Document the new env vars and workflow**

Add a section covering: `PAPERTRACKER_ZOTERO_DIR`, `PAPERTRACKER_ZOTERO_LINKED_BASE`, `PAPERTRACKER_OBSIDIAN_TEMPLATE`; the per-paper Triage/Deep choice in the selector; that deep mode reads the PDF from Zotero (file the paper in Zotero first) and falls back to abstract otherwise; that full-text reading currently requires the `claude` provider.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: two-mode summaries, Zotero PDF, Obsidian template config"
```

---

## Self-Review

- **Spec coverage:** per-paper mode (Task 3) ✓; both modes full PDF from Zotero (Tasks 1,4) ✓; abstract fallback (Tasks 4,7) ✓; Obsidian template via file (Task 2,4) ✓; output stays in digest (no vault writes) ✓; cache by mode (Task 5) ✓; CLI wiring (Task 6) ✓.
- **Type consistency:** `paper["mode"]` is the single carrier set in `selector` and read in `cli`/`summarizer`; `summary_cache.lookup(cache, paper, mode)` and `cache_key(cid, mode)` used consistently; `zotero.find_pdf(paper, data_dir=None) -> Path | None` used in tests and summarizer.
- **Open risks to verify during execution (not placeholders):**
  - Zotero schema column names (`parentItemID`, `fields.fieldName`) are stable across Zotero 5–7 but confirm against the user's actual DB on first run (`uv run python -c "import sqlite3,glob; ..."`).
  - `claude -p` PDF reading requires the file under an `--add-dir`-allowed path; confirm the Read tool actually ingests the PDF (run once on a known paper). If the CLI flag name differs in the installed version, check `claude -p --help`.
