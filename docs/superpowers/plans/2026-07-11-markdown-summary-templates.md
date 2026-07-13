# Markdown Summary Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover Markdown output skeletons from a configured folder and let users choose one independently for each paper, with a configured default.

**Architecture:** A focused `summary_templates` module owns discovery, validation, and UTF-8 loading. Configuration supplies only the directory and default ID; the selector receives a validated catalog and records a `template` ID on each paper; the summarizer loads that skeleton through a shared prompt wrapper. CLI orchestration and cache metadata pass the ID without assigning source behavior to it.

**Tech Stack:** Python 3.11+, standard library (`dataclasses`, `pathlib`, `tomllib`, `html`, `http.server`), pytest, Markdown, TOML.

## Global Constraints

- Template content lives only in `summary_templates/*.md`, never in TOML or Python prompt constants.
- `summary_template_dir` resolves relative to the directory containing `papertracker.toml` unless absolute.
- Template IDs are case-sensitive filename stems; only direct-child files with lowercase `.md` are discovered.
- Dropdown order is alphabetical by filename and the configured default is preselected for every paper.
- Template selection is independent of abstract/PDF source selection.
- Unknown templates and invalid catalogs fail with a clear `ConfigError`; template read failures identify the path.
- Existing unrelated worktree changes must remain intact and must not be included in feature commits.

---

### Task 1: Template catalog and repository templates

**Files:**
- Create: `src/papertracker/summary_templates.py`
- Create: `summary_templates/triage.md`
- Create: `summary_templates/deep.md`
- Create: `tests/test_summary_templates.py`
- Modify: `src/papertracker/config.py`
- Modify: `papertracker.toml`
- Modify: `tests/test_local_config.py`

**Interfaces:**
- Produces: `SummaryTemplate(id: str, path: Path)`, `discover(directory: Path, default_id: str) -> tuple[tuple[SummaryTemplate, ...], SummaryTemplate]`, and `load(template: SummaryTemplate) -> str`.
- Produces: `config.summary_template_catalog() -> tuple[tuple[SummaryTemplate, ...], SummaryTemplate]` and `config.summary_template(template_id: str) -> SummaryTemplate`.

- [ ] **Step 1: Write failing catalog tests**

```python
def test_discover_sorts_direct_lowercase_markdown_files(tmp_path):
    (tmp_path / "C.md").write_text("# C", encoding="utf-8")
    (tmp_path / "A.md").write_text("# A", encoding="utf-8")
    (tmp_path / "ignored.MD").write_text("# ignored", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "B.md").write_text("# B", encoding="utf-8")
    templates, default = summary_templates.discover(tmp_path, "C")
    assert [item.id for item in templates] == ["A", "C"]
    assert default.id == "C"

@pytest.mark.parametrize("setup, message", [
    (lambda path: None, "does not exist"),
    (lambda path: path.mkdir(), "contains no .md templates"),
])
def test_discover_rejects_invalid_directories(tmp_path, setup, message):
    directory = tmp_path / "templates"
    setup(directory)
    with pytest.raises(config.ConfigError, match=message):
        summary_templates.discover(directory, "A")

def test_discover_rejects_missing_default(tmp_path):
    (tmp_path / "A.md").write_text("# A", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="default.*B"):
        summary_templates.discover(tmp_path, "B")

def test_load_reads_utf8_and_reports_read_failure(tmp_path):
    path = tmp_path / "A.md"
    path.write_text("# Résumé", encoding="utf-8")
    template = summary_templates.SummaryTemplate("A", path)
    assert summary_templates.load(template) == "# Résumé"
    path.write_bytes(b"\xff")
    with pytest.raises(config.ConfigError, match=r"A\.md"):
        summary_templates.load(template)
```

- [ ] **Step 2: Run catalog tests and verify failure**

Run: `uv run pytest tests/test_summary_templates.py -v`

Expected: collection fails because `papertracker.summary_templates` does not exist.

- [ ] **Step 3: Implement the catalog and configuration bridge**

```python
# src/papertracker/summary_templates.py
@dataclass(frozen=True)
class SummaryTemplate:
    id: str
    path: Path

def discover(directory: Path, default_id: str):
    if not directory.exists():
        raise config.ConfigError(f"Summary template directory does not exist: {directory}")
    if not directory.is_dir():
        raise config.ConfigError(f"Summary template path is not a directory: {directory}")
    templates = tuple(
        SummaryTemplate(path.stem, path)
        for path in sorted(directory.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.suffix == ".md"
    )
    if not templates:
        raise config.ConfigError(f"Summary template directory contains no .md templates: {directory}")
    by_id = {template.id: template for template in templates}
    if len(by_id) != len(templates):
        raise config.ConfigError(f"Summary template directory has duplicate IDs: {directory}")
    if default_id not in by_id:
        raise config.ConfigError(f"Configured default summary template {default_id!r} was not found in {directory}")
    return templates, by_id[default_id]

def load(template: SummaryTemplate) -> str:
    try:
        return template.path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise config.ConfigError(f"Could not read summary template {template.path}: {exc}") from exc
```

In `config.py`, read `summary_template_dir` and `default_summary_template`, resolve relative paths against `PROJECT_CONFIG_PATH.parent`, lazily call `discover`, and validate selected IDs in `summary_template`. Remove `DEFAULT_OBSIDIAN_TEMPLATE` and `obsidian_template()`.

In `papertracker.toml`, replace `obsidian_template = """..."""` with:

```toml
summary_template_dir = "summary_templates"
default_summary_template = "triage"
```

Move the existing deep headings into `summary_templates/deep.md`. Express the existing triage output as a Markdown skeleton with labeled bullet slots for objective, contribution, results, model/data, open source, future work, limitations, and relevance.

- [ ] **Step 4: Update local-config tests and run the task suite**

Add `summary_template_dir` and `default_summary_template` to the temporary TOML fixture, create that folder and its `Test.md`, and assert the resolved catalog/default. Remove assertions for `obsidian_template()`.

Run: `uv run pytest tests/test_summary_templates.py tests/test_local_config.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the catalog task**

```bash
git add src/papertracker/summary_templates.py src/papertracker/config.py summary_templates/triage.md summary_templates/deep.md papertracker.toml tests/test_summary_templates.py tests/test_local_config.py
git commit -m "feat: discover markdown summary templates"
```

### Task 2: Template-driven prompt construction

**Files:**
- Modify: `src/papertracker/summarizer.py`
- Modify: `tests/test_summarizer_modes.py` (rename to `tests/test_summarizer_templates.py` with `git mv`)

**Interfaces:**
- Consumes: `config.summary_template(template_id: str) -> SummaryTemplate` and `summary_templates.load(template) -> str`.
- Produces: `build_prompt(paper, template_id, pdf_path, profile=None, pdf_text=None) -> tuple[str, bool]` and `summarize_paper(..., template_id="triage", ...) -> str`.

- [ ] **Step 1: Rewrite prompt tests to fail against mode-based behavior**

```python
def test_build_prompt_fills_selected_template_from_abstract(monkeypatch, tmp_path):
    template = summary_templates.SummaryTemplate("A", tmp_path / "A.md")
    template.path.write_text("---\ntitle:\n---\n## Finding", encoding="utf-8")
    monkeypatch.setattr(config, "summary_template", lambda template_id: template)
    prompt, uses_pdf = summarizer.build_prompt(
        {"title": "T", "abstract": "A"}, template_id="A", pdf_path=None
    )
    assert "## Finding" in prompt
    assert "Title: T" in prompt and "Abstract: A" in prompt
    assert uses_pdf is False

def test_template_choice_does_not_change_pdf_source(monkeypatch, tmp_path):
    pdf = tmp_path / "paper.pdf"
    template = summary_templates.SummaryTemplate("A", tmp_path / "A.md")
    template.path.write_text("## Result", encoding="utf-8")
    monkeypatch.setattr(config, "summary_template", lambda template_id: template)
    prompt, uses_pdf = summarizer.build_prompt({"title": "T"}, "A", pdf)
    assert str(pdf) in prompt and "## Result" in prompt
    assert uses_pdf is True
```

- [ ] **Step 2: Run prompt tests and verify failure**

Run: `uv run pytest tests/test_summarizer_templates.py -v`

Expected: tests fail because `build_prompt` still branches on fixed mode names.

- [ ] **Step 3: Replace fixed prompts with one skeleton wrapper**

Remove `_TRIAGE_TEMPLATE` and `_DEEP_HEADER`. Add a shared wrapper containing the approved rules, load the selected template, and always append title/abstract metadata. Rename `mode` parameters and local variables to `template_id`. Keep `_PDF_INSTRUCTION`, `_PDF_TEXT_INSTRUCTION`, project context, provider invocation, and PDF extraction unchanged.

```python
template = config.summary_template(template_id)
body = _TEMPLATE_HEADER.format(template=summary_templates.load(template))
meta = f"Title: {paper['title']}\n\nAbstract: {paper.get('abstract', '')}\n"
return source + context + body + "\n" + meta, uses_pdf
```

- [ ] **Step 4: Run prompt/provider tests**

Run: `uv run pytest tests/test_summarizer_templates.py -v`

Expected: all tests pass, including Claude tool restrictions and Codex inline PDF extraction.

- [ ] **Step 5: Commit prompt migration**

```bash
git add src/papertracker/summarizer.py tests/test_summarizer_templates.py tests/test_summarizer_modes.py
git commit -m "feat: build summaries from markdown skeletons"
```

### Task 3: Dynamic per-paper selector

**Files:**
- Modify: `src/papertracker/selector.py`
- Modify: `tests/test_selector_modes.py` (rename to `tests/test_selector_templates.py` with `git mv`)

**Interfaces:**
- Produces: `select_papers(papers, template_ids, default_template) -> list[dict]` where selected paper copies contain `paper["template"]`.
- Produces: `_selections_from_form(form, n, template_ids, default_template)` and `_parse_selection(raw, n, template_ids, default_template)` returning `(index, template_id)` pairs.
- Headless syntax: `1` uses the default, `2:B` uses template `B`, ranges such as `1-3:C` apply `C`, and `a` selects all with the default.

- [ ] **Step 1: Write failing parser and HTML tests**

```python
def test_form_parsing_validates_templates_and_defaults():
    form = {"sel": ["0", "2"], "template_0": ["C"], "template_2": ["unknown"]}
    assert selector._selections_from_form(form, 3, ["A", "C"], "A") == [(0, "C"), (2, "A")]

def test_text_parsing_supports_default_explicit_and_ranges():
    assert selector._parse_selection("1, 2:C, 3-4:A", 4, ["A", "C"], "A") == [
        (0, "A"), (1, "C"), (2, "A"), (3, "A")
    ]

def test_render_html_uses_catalog_and_preselects_default():
    page = selector._render_html([{"title": "T"}], ["A", "B", "C"], "B")
    assert '<option value="A">A</option>' in page
    assert '<option value="B" selected>B</option>' in page
    assert '<option value="C">C</option>' in page
```

- [ ] **Step 2: Run selector tests and verify failure**

Run: `uv run pytest tests/test_selector_templates.py -v`

Expected: signature/assertion failures because the selector still hard-codes triage/deep.

- [ ] **Step 3: Thread the catalog through browser and fallback selectors**

Update `select_papers`, `_select_html`, `_make_server`, `_render_html`, `_card`, `_select_fallback`, `_selections_from_form`, and `_parse_selection` to accept the IDs/default. Escape option values and labels with `html.escape`; validate POST and text identifiers case-sensitively; set `paper["template"]` on copies. Update fallback help to document `2:B` and the configured default.

- [ ] **Step 4: Run selector tests**

Run: `uv run pytest tests/test_selector_templates.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit selector migration**

```bash
git add src/papertracker/selector.py tests/test_selector_templates.py tests/test_selector_modes.py
git commit -m "feat: select summary templates per paper"
```

### Task 4: CLI, Zotero, and cache terminology

**Files:**
- Modify: `src/papertracker/cli.py`
- Modify: `src/papertracker/zotero.py`
- Modify: `src/papertracker/summary_cache.py`
- Modify: `tests/test_summary_cache_modes.py` (rename to `tests/test_summary_cache_templates.py` with `git mv`)
- Modify: `tests/test_zotero_batch_cli.py`
- Modify: any existing tests whose selector or summarizer fakes use the old `mode` signature

**Interfaces:**
- Consumes: catalog/default from `config.summary_template_catalog()` and selector/summarizer interfaces from Tasks 2–3.
- Produces: CLI `--zotero-template TEMPLATE_ID`, defaulting to `config.DEFAULT_SUMMARY_TEMPLATE`; cache entries use metadata field `template`.

- [ ] **Step 1: Write failing orchestration and cache tests**

```python
def test_lookup_is_template_scoped():
    cache = {"arxiv:1::A": {"summary": "A result"}, "arxiv:1::B": {"summary": "B result"}}
    paper = {"canonical_id": "arxiv:1"}
    assert summary_cache.lookup(cache, paper, "A") == "A result"
    assert summary_cache.lookup(cache, paper, "B") == "B result"

def test_zotero_collection_passes_selected_template(monkeypatch, tmp_path):
    profile = _profile(tmp_path)
    args = _args()
    args.zotero_template = "deep"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    paper = {
        "canonical_id": "zotero:ITEM1",
        "merged_ids": ["zotero:ITEM1"],
        "source": "zotero",
        "title": "Local Paper",
        "abstract": "",
        "pdf_path": str(pdf),
    }
    monkeypatch.setattr(zotero, "collection_papers", lambda *args, **kwargs: [paper])
    monkeypatch.setattr(cli, "_resolve_llm", lambda args: ("claude", "sonnet", 0))
    calls = []

    def fake_summarize(paper, provider, model, template_id, profile, pdf_path=None):
        calls.append((template_id, Path(pdf_path)))
        return "summary"

    monkeypatch.setattr(summarizer, "summarize_paper", fake_summarize)
    assert cli._run_zotero_collection_profile(profile, args) == 0
    assert calls == [("deep", pdf)]
```

- [ ] **Step 2: Run CLI/cache tests and verify failure**

Run: `uv run pytest tests/test_summary_cache_templates.py tests/test_zotero_batch_cli.py -v`

Expected: failures reference old `mode` fields and `zotero_mode` arguments.

- [ ] **Step 3: Migrate orchestration to template IDs**

At each discovery and related-work selection call, obtain IDs/default once and call `selector.select_papers(papers, ids, default.id)`. For non-interactive discovery, set `paper.setdefault("template", default.id)`. Rename loop variables and metadata from `mode` to `template_id`/`template`, while keeping the cache key format `canonical_id::template_id`.

Replace `--zotero-mode` and its fixed choices with `--zotero-template`; validate it through `config.summary_template()` before summaries start. Remove the hard-coded `mode` from Zotero paper dictionaries. Update test namespaces and fakes to accept `template_id`.

- [ ] **Step 4: Run orchestration, cache, and project tests**

Run: `uv run pytest tests/test_summary_cache_templates.py tests/test_zotero_batch_cli.py tests/test_project_profiles.py tests/test_related_work_cli.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit orchestration migration**

```bash
git add src/papertracker/cli.py src/papertracker/zotero.py src/papertracker/summary_cache.py tests
git commit -m "feat: thread summary templates through workflows"
```

### Task 5: Documentation and full verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents: folder discovery, filename-to-label mapping, default configuration, per-paper browser selection, headless syntax, and Zotero template option.

- [ ] **Step 1: Update README and configuration examples**

Remove fixed two-mode and `PAPERTRACKER_OBSIDIAN_TEMPLATE` documentation. Add an example tree:

```text
summary_templates/
├── deep.md
└── triage.md
```

Explain that adding `experiment.md` automatically adds `experiment` to every dropdown, and show:

```toml
summary_template_dir = "summary_templates"
default_summary_template = "triage"
```

Document headless `2:deep` syntax and `--zotero-template deep`.

- [ ] **Step 2: Scan for stale fixed-mode references**

Run: `rg -n "obsidian_template|PAPERTRACKER_OBSIDIAN_TEMPLATE|zotero_mode|zotero-mode|mode_(?:[0-9]|\{i\})|triage.*deep|deep.*triage" README.md papertracker.toml src tests`

Expected: no implementation/config references remain; template filenames in tests/docs are acceptable and inspected manually.

- [ ] **Step 3: Run formatting/static checks**

Run: `uv run ruff check src tests`

Expected: exit 0.

- [ ] **Step 4: Run the complete test suite**

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 5: Review the final diff and commit documentation**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended feature files plus pre-existing unrelated changes are present.

```bash
git add README.md
git commit -m "docs: explain markdown summary templates"
```
