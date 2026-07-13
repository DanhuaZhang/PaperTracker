# Markdown Summary Templates Design

## Goal

Replace the fixed `triage` and `deep` summary formats with a directory of Markdown output templates. Every `*.md` file in that directory becomes a summary-template option for each selected paper, and one configured template is selected by default.

Template contents must not live in TOML or Python prompt strings. TOML stores only the template directory and the default template identifier.

## Configuration

`papertracker.toml` gains two required settings:

```toml
summary_template_dir = "summary_templates"
default_summary_template = "A"
```

`summary_template_dir` is resolved relative to the directory containing `papertracker.toml` unless it is absolute. `default_summary_template` is the filename stem, without `.md`, and matching is case-sensitive.

The existing embedded `obsidian_template` setting and `PAPERTRACKER_OBSIDIAN_TEMPLATE` override are removed. The repository includes an initial template folder so a fresh checkout remains runnable.

## Template Discovery

A focused configuration helper scans only direct children of `summary_template_dir`; subdirectories are ignored. Files must have the lowercase `.md` extension. Each filename stem is both the stable template identifier and its user-visible label.

Templates are sorted alphabetically by filename for deterministic dropdown ordering. Discovery rejects ambiguous duplicate identifiers and validates that `default_summary_template` identifies a discovered file.

Configuration fails with a clear `ConfigError` when:

- the configured directory does not exist or is not a directory;
- it contains no Markdown templates;
- the configured default template is absent; or
- a selected template identifier is not present.

Templates are read as UTF-8 when a prompt is built. File read and decoding failures are reported with the template path and do not silently fall back to another template.

## Selection UI and Data Flow

The selector receives the discovered template identifiers and the configured default. Each paper row shows the same dropdown options and initially selects the default template. A user can independently choose a different template for every paper.

Selection results carry the template identifier in place of the current `triage` or `deep` mode value. The browser selector validates submitted identifiers against the discovered set. The headless selector accepts a paper number with an optional template identifier using an explicit, documented syntax; a bare paper number selects the configured default.

The selected identifier flows unchanged through CLI orchestration into prompt construction and summary-cache lookup. Template choice does not determine whether the summary uses an abstract or full PDF. Existing source availability and provider behavior continue to decide that independently.

## Prompt Construction

All discovered Markdown files are output skeletons, not complete prompts. Prompt construction uses one shared instruction wrapper that tells the model to:

- reproduce the chosen template's frontmatter and headings exactly;
- fill sections concisely using only the available abstract or PDF content;
- preserve intentionally personal sections, such as “My take,” as blank rather than inventing an opinion;
- avoid adding sections not present in the template; and
- output only the completed Markdown template.

The wrapper embeds the selected Markdown skeleton and the paper metadata. Existing project context and abstract/PDF source instructions remain in effect.

The current triage bullet format and deep Obsidian format become ordinary Markdown files in `summary_templates/`. Because every file is interpreted as an output skeleton, the migrated triage file contains headings or bullet placeholders representing its desired output structure rather than model instructions.

## Cache Behavior

Summary-cache keys use the selected template identifier in the same position currently occupied by the summary mode. Thus, summaries for the same paper under `A` and `B` remain independent.

No automatic reuse of old `triage` or `deep` entries is required unless the initial migrated templates use those exact stems. Existing cache loading remains tolerant of unrelated historical entries.

## Compatibility and Documentation

The fixed two-mode terminology is removed from the selector, CLI help, README, configuration examples, and tests. Documentation explains how to add a template by creating a Markdown file, how filenames map to dropdown labels, and how to set the default.

Provider selection, project profiles, Zotero lookup, PDF extraction, digest rendering, and related-work generation are outside this change except where they pass the template identifier through existing summary calls.

## Testing

Automated tests cover:

- discovery of `A.md`, `B.md`, and `C.md` in alphabetical order;
- ignoring non-Markdown files and subdirectories;
- relative and absolute template-directory resolution;
- missing, empty, unreadable, and invalid-default configurations;
- dropdown options and default selection for every paper;
- independent per-paper template submissions and rejection of unknown identifiers;
- headless selection using the default and explicit templates;
- prompt construction from the selected Markdown skeleton with abstract and PDF sources;
- preservation of project context in prompts;
- cache separation by template identifier; and
- configuration and README migration away from embedded template content.

## Success Criteria

With `A.md`, `B.md`, and `C.md` in the configured directory, every paper selector displays `A`, `B`, and `C` in that order. The configured default is preselected. Different papers can be submitted with different choices, each generated summary follows its chosen Markdown skeleton, and cached results remain isolated by template.
