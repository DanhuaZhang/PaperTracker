"""Evidence-aware LLM summarization via the Claude or Codex CLI."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import shutil
import subprocess

from . import config, summary_templates

log = logging.getLogger(__name__)

PROMPT_PIPELINE_VERSION = "summary-evidence-v2.0"
PDF_CHUNK_CHAR_LIMIT = 40_000
NOTES_CONSOLIDATION_CHAR_LIMIT = 60_000


class EvidenceError(RuntimeError):
    """Raised when the selected template's evidence is unavailable."""


class PdfTextExtractionError(EvidenceError):
    """Raised when a required local PDF cannot provide extractable text."""


class SummaryPipelineError(RuntimeError):
    """Raised when recursive evidence consolidation cannot be bounded."""


@dataclass(frozen=True)
class PdfEvidence:
    """All extractable PDF text, grouped into bounded, page-labelled chunks."""

    path: Path
    total_pages: int
    extractable_pages: tuple[int, ...]
    chunks: tuple[str, ...]


def _project_context(profile: config.ProjectProfile | None) -> tuple[str, str]:
    if profile is None:
        return "", ""
    return profile.name, profile.topic_statement.strip()


def binary_for(provider: str) -> str:
    if provider == "claude":
        return "claude"
    if provider == "codex":
        return "codex"
    raise ValueError(f"Unknown provider: {provider}")


def preflight(provider: str) -> None:
    binary = binary_for(provider)
    if shutil.which(binary) is None:
        hint = (
            "Install Claude Code from https://claude.com/code and run "
            "'claude auth login'."
            if provider == "claude"
            else "Install Codex CLI from https://developers.openai.com/codex/cli "
            "and run 'codex login'."
        )
        raise SystemExit(f"{binary!r} not found on PATH — {hint}")


def paper_metadata(
    paper: dict,
    evidence: str,
    profile: config.ProjectProfile | None = None,
) -> str:
    """Render deterministic metadata supplied to the model beside the skeleton."""
    authors = paper.get("authors") or []
    author_text = ", ".join(str(author) for author in authors) or "unknown"
    venue = paper.get("container_title") or paper.get("venue") or "unknown"
    project, project_focus = _project_context(profile)
    lines = [
        f"Title: {paper.get('title') or 'unknown'}",
        f"Authors: {author_text}",
        f"Year/date: {paper.get('published') or paper.get('date') or 'unknown'}",
        f"Venue: {venue}",
        f"DOI: {paper.get('doi') or 'unknown'}",
        f"URL: {paper.get('url') or 'unknown'}",
        f"Project: {project or 'unknown'}",
    ]
    if project_focus:
        lines.append(f"Project focus: {project_focus}")
    lines.append(f"Evidence type: {evidence}")
    return "\n".join(lines)


def _final_prompt(
    paper: dict,
    template: summary_templates.SummaryTemplate,
    source_label: str,
    source_text: str,
    profile: config.ProjectProfile | None,
) -> str:
    return f"""You are a research assistant. Fill the selected Markdown summary skeleton.

Rules:
- Reproduce every heading in the skeleton exactly and in the same order.
- Fill each section concisely using only the supplied evidence.
- Cite reported numbers, datasets, conditions, and baselines when the evidence supports them.
- State that the evidence does not establish a point when it is unavailable.
- Do not invent bibliographic facts or duplicate the digest's bibliographic frontmatter.
- Do not add headings, an evidence banner, or commentary outside the filled skeleton.
- Output the filled skeleton only.

Deterministic paper metadata (do not alter or invent):
{paper_metadata(paper, template.evidence, profile)}

Selected template: {template.label} ({template.id})
Template skeleton:
{summary_templates.load(template)}

{source_label}:
{source_text}
"""


def build_prompt(
    paper: dict,
    template_id: str,
    pdf_path=None,
    profile: config.ProjectProfile | None = None,
    pdf_text: str | None = None,
) -> tuple[str, bool]:
    """Build the final fill prompt; retained as a public test/integration helper.

    Abstract templates always ignore PDF arguments. Full-text templates require
    locally extracted text; a path alone is never delegated to an LLM tool.
    """
    template = config.summary_template(template_id)
    if template.evidence == "abstract":
        abstract = (paper.get("abstract") or "").strip()
        if not abstract:
            raise EvidenceError(
                f"Template {template.id!r} requires an abstract, but none is available"
            )
        return _final_prompt(
            paper, template, "Abstract (the only analytical evidence)", abstract, profile
        ), False
    if pdf_text is None:
        raise PdfTextExtractionError(
            f"Template {template.id!r} requires full text from a readable local PDF"
        )
    return _final_prompt(
        paper, template, "Consolidated notes from all extractable PDF pages", pdf_text, profile
    ), True


def summarize_paper(
    paper: dict,
    provider: str,
    model: str,
    template_id: str | None = None,
    profile: config.ProjectProfile | None = None,
    pdf_path=None,
) -> str:
    """Generate a summary without permitting evidence-mode fallback."""
    if template_id is None:
        _templates, default_template = config.summary_template_catalog("abstract")
        template_id = default_template.id
    template = config.summary_template(template_id)

    if template.evidence == "abstract":
        prompt, _ = build_prompt(paper, template.id, profile=profile)
        output = _invoke(provider, model, prompt)
        return f"> Evidence: abstract only\n\n{output}"

    selected_pdf = pdf_path or paper.get("pdf_path")
    if selected_pdf is None:
        raise PdfTextExtractionError(
            f"Template {template.id!r} requires a readable local PDF; no PDF was provided"
        )
    evidence = extract_pdf_evidence(Path(selected_pdf))
    notes: list[str] = []
    for index, chunk in enumerate(evidence.chunks, 1):
        log.info(
            "PDF evidence chunk %d/%d (%d characters)",
            index,
            len(evidence.chunks),
            len(chunk),
        )
        prompt = _notes_prompt(paper, template, profile, chunk, index, len(evidence.chunks))
        notes.append(_invoke(provider, model, prompt))

    consolidated = _consolidate_notes(
        paper, template, profile, provider, model, notes
    )
    prompt, _ = build_prompt(
        paper,
        template.id,
        profile=profile,
        pdf_text=consolidated,
    )
    output = _invoke(provider, model, prompt)
    return (
        f"> Evidence: full text — {len(evidence.extractable_pages)}/"
        f"{evidence.total_pages} pages contained extractable text\n\n{output}"
    )


def _notes_prompt(
    paper: dict,
    template: summary_templates.SummaryTemplate,
    profile: config.ProjectProfile | None,
    chunk: str,
    index: int,
    count: int,
) -> str:
    return f"""Extract factual notes relevant to the selected summary template from this PDF text chunk.

Rules:
- Use only this chunk. Preserve page labels with every fact.
- Capture methods, conditions, numbers, results, limitations, and availability details relevant to the skeleton.
- Record explicit absence or uncertainty; do not fill the final template yet.
- Output compact Markdown notes only.

Deterministic paper metadata:
{paper_metadata(paper, "fulltext", profile)}

Template skeleton:
{summary_templates.load(template)}

PDF chunk {index}/{count}:
{chunk}
"""


def _consolidate_notes(
    paper: dict,
    template: summary_templates.SummaryTemplate,
    profile: config.ProjectProfile | None,
    provider: str,
    model: str,
    notes: list[str],
) -> str:
    labelled = [f"[Notes from PDF chunk {i}]\n{note}" for i, note in enumerate(notes, 1)]
    level = 0
    while len("\n\n".join(labelled)) > NOTES_CONSOLIDATION_CHAR_LIMIT:
        level += 1
        if level > 12:
            raise SummaryPipelineError(
                "PDF evidence notes could not be consolidated below 60,000 characters"
            )
        groups = _pack_text_blocks(labelled, NOTES_CONSOLIDATION_CHAR_LIMIT)
        log.info(
            "Consolidating PDF notes level %d: %d inputs -> %d group(s)",
            level,
            len(labelled),
            len(groups),
        )
        next_level: list[str] = []
        for index, group in enumerate(groups, 1):
            prompt = f"""Consolidate these page-cited notes for a later final summary.

Rules:
- Preserve all distinct template-relevant facts, reported numbers, caveats, and page labels.
- Remove duplication and compress wording.
- Use only the supplied notes; do not fill the final skeleton.
- Output compact Markdown notes, substantially shorter than the input and at most 30,000 characters.

Deterministic paper metadata:
{paper_metadata(paper, "fulltext", profile)}

Template skeleton:
{summary_templates.load(template)}

Consolidation group {index}/{len(groups)}, level {level}:
{group}
"""
            next_level.append(
                f"[Consolidated notes level {level}, group {index}]\n"
                f"{_invoke(provider, model, prompt)}"
            )
        labelled = next_level
    return "\n\n".join(labelled)


def _pack_text_blocks(blocks: list[str], limit: int) -> list[str]:
    """Pack blocks under ``limit``, splitting a single oversized block safely."""
    bounded: list[str] = []
    for block in blocks:
        if len(block) <= limit:
            bounded.append(block)
            continue
        piece_limit = max(1, limit - 80)
        pieces = [block[i:i + piece_limit] for i in range(0, len(block), piece_limit)]
        bounded.extend(
            f"[Split note {index}/{len(pieces)}]\n{piece}"
            for index, piece in enumerate(pieces, 1)
        )

    groups: list[str] = []
    current: list[str] = []
    size = 0
    for block in bounded:
        added = len(block) + (2 if current else 0)
        if current and size + added > limit:
            groups.append("\n\n".join(current))
            current = []
            size = 0
            added = len(block)
        current.append(block)
        size += added
    if current:
        groups.append("\n\n".join(current))
    return groups


def extract_pdf_evidence(
    pdf_path: Path,
    chunk_char_limit: int = PDF_CHUNK_CHAR_LIMIT,
) -> PdfEvidence:
    """Extract every text-bearing page and build bounded page-labelled chunks."""
    if chunk_char_limit < 100:
        raise ValueError("chunk_char_limit must be at least 100")
    try:
        with pdf_path.open("rb"):
            pass
    except OSError as exc:
        raise PdfTextExtractionError(
            f"full-text summary requires a readable local PDF at {pdf_path}: {exc}"
        ) from exc
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfTextExtractionError(
            "pypdf is required for full-text PDF summaries"
        ) from exc

    try:
        reader = PdfReader(str(pdf_path))
        total_pages = len(reader.pages)
    except Exception as exc:
        raise PdfTextExtractionError(f"could not read PDF {pdf_path}: {exc}") from exc

    page_blocks: list[str] = []
    extractable_pages: list[int] = []
    for page_number, page in enumerate(reader.pages, 1):
        try:
            page_text = (page.extract_text() or "").strip()
        except Exception as exc:  # a bad page must not hide text from other pages
            log.warning("PDF page %d/%d extraction failed: %s", page_number, total_pages, exc)
            page_text = ""
        log.debug(
            "PDF page %d/%d: %d extractable characters",
            page_number,
            total_pages,
            len(page_text),
        )
        if not page_text:
            continue
        extractable_pages.append(page_number)
        page_blocks.extend(_page_blocks(page_number, page_text, chunk_char_limit))

    if not extractable_pages:
        raise PdfTextExtractionError(
            f"no extractable text found in {pdf_path}; OCR required"
        )
    if len(extractable_pages) < total_pages:
        log.warning(
            "PDF text is partial for %s: %d/%d pages contained extractable text; "
            "continuing with all extractable pages",
            pdf_path,
            len(extractable_pages),
            total_pages,
        )
    chunks = _pack_page_blocks(page_blocks, chunk_char_limit)
    log.info(
        "Extracted PDF %s: %d/%d text pages -> %d chunk(s)",
        pdf_path,
        len(extractable_pages),
        total_pages,
        len(chunks),
    )
    return PdfEvidence(
        path=pdf_path,
        total_pages=total_pages,
        extractable_pages=tuple(extractable_pages),
        chunks=tuple(chunks),
    )


def _page_blocks(page_number: int, text: str, limit: int) -> list[str]:
    base_label = f"[Page {page_number}]\n"
    if len(base_label) + len(text) <= limit:
        return [base_label + text]
    payload_limit = max(1, limit - len(f"[Page {page_number}, part 9999/9999]\n"))
    pieces = [text[i:i + payload_limit] for i in range(0, len(text), payload_limit)]
    return [
        f"[Page {page_number}, part {index}/{len(pieces)}]\n{piece}"
        for index, piece in enumerate(pieces, 1)
    ]


def _pack_page_blocks(blocks: list[str], limit: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for block in blocks:
        added = len(block) + (2 if current else 0)
        if current and size + added > limit:
            chunks.append("\n\n".join(current))
            current = []
            size = 0
            added = len(block)
        current.append(block)
        size += added
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def extract_pdf_text(pdf_path: Path, char_limit: int | None = None) -> str:
    """Compatibility helper returning all text; it never truncates evidence."""
    limit = char_limit or PDF_CHUNK_CHAR_LIMIT
    evidence = extract_pdf_evidence(pdf_path, chunk_char_limit=limit)
    return "\n\n".join(evidence.chunks)


def pdf_sha256(pdf_path: Path) -> str:
    """Hash PDF bytes for cache identity while reporting readability failures."""
    digest = hashlib.sha256()
    try:
        with pdf_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise PdfTextExtractionError(
            f"full-text summary requires a readable local PDF at {pdf_path}: {exc}"
        ) from exc
    return digest.hexdigest()


def run_json_prompt(provider: str, model: str, prompt: str) -> str:
    """Run a no-tools prompt expected to return strict JSON."""
    return _invoke(provider, model, prompt)


def _invoke(provider: str, model: str, prompt: str) -> str:
    if provider == "claude":
        return _summarize_claude(prompt, model)
    if provider == "codex":
        return _summarize_codex(prompt, model)
    raise ValueError(f"Unknown provider: {provider}")


def _summarize_claude(prompt: str, model: str, pdf_path=None) -> str:
    cmd = [
        "claude",
        "-p",
        "--model",
        model,
        "--output-format",
        "text",
        "--disallowed-tools",
        "*",
    ]
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=config.SUMMARY_TIMEOUT_SEC,
        check=True,
    )
    return result.stdout.strip()


def _summarize_codex(prompt: str, model: str, pdf_path=None) -> str:
    cmd = [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--model",
        model,
        "-",
    ]
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=config.SUMMARY_TIMEOUT_SEC,
        check=True,
    )
    return result.stdout.strip()
