"""LLM summarization via subprocess to the `claude` or `codex` CLI.

Uses the user's logged-in Claude Pro/Max or ChatGPT Plus/Pro subscription quota.
No API key environment variable required.
"""
from __future__ import annotations

import logging
from pathlib import Path
import shutil
import subprocess

from . import config, summary_templates

log = logging.getLogger(__name__)

_TEMPLATE_HEADER = """\
You are a research assistant. Fill in the following summary template for the paper, in markdown.

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
_PDF_TEXT_INSTRUCTION = """\
Base your answer on the following text extracted from the local full paper PDF.
Extraction can lose some figure/table layout; do not invent details that are not present.

Extracted PDF text:
{pdf_text}

"""
_ABSTRACT_INSTRUCTION = "Base your answer on this title and abstract only.\n\n"
_PDF_TEXT_CHAR_LIMIT = 80_000


class PdfTextExtractionError(RuntimeError):
    """Raised when a local PDF cannot be converted into text for a provider."""


def _project_context(profile: config.ProjectProfile | None) -> str:
    if profile is None:
        return ""
    return (
        f"Project: {profile.name}\n"
        f"Project topic focus: {profile.topic_statement.strip()}\n\n"
    )


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
            "Install Claude Code from https://claude.com/code and run 'claude login'."
            if provider == "claude"
            else "Install Codex CLI ('npm install -g @openai/codex' or 'brew install --cask codex') and run 'codex login'."
        )
        raise SystemExit(f"{binary!r} not found on PATH — {hint}")


def build_prompt(
    paper: dict,
    template_id: str,
    pdf_path,
    profile: config.ProjectProfile | None = None,
    pdf_text: str | None = None,
) -> tuple[str, bool]:
    """Return (prompt, uses_pdf). uses_pdf drives whether the Read tool is enabled."""
    uses_pdf = pdf_path is not None or pdf_text is not None
    if pdf_text is not None:
        source = _PDF_TEXT_INSTRUCTION.format(pdf_text=pdf_text)
    elif pdf_path is not None:
        source = _PDF_INSTRUCTION.format(pdf_path=pdf_path)
    else:
        source = _ABSTRACT_INSTRUCTION
    context = _project_context(profile)
    template = config.summary_template(template_id)
    body = _TEMPLATE_HEADER.format(template=summary_templates.load(template))
    meta = f"Title: {paper['title']}\n\nAbstract: {paper.get('abstract', '')}\n"
    return source + context + body + "\n" + meta, uses_pdf


def summarize_paper(
    paper: dict,
    provider: str,
    model: str,
    template_id: str | None = None,
    profile: config.ProjectProfile | None = None,
    pdf_path=None,
) -> str:
    if template_id is None:
        _templates, default_template = config.summary_template_catalog()
        template_id = default_template.id
    pdf_text = None
    llm_pdf_path = pdf_path
    if provider == "codex" and pdf_path is not None:
        pdf_text = extract_pdf_text(Path(pdf_path))
        llm_pdf_path = None

    prompt, uses_pdf = build_prompt(
        paper, template_id, llm_pdf_path, profile, pdf_text=pdf_text
    )
    if provider == "claude":
        out = _summarize_claude(prompt, model, llm_pdf_path if uses_pdf else None)
        if llm_pdf_path is None:
            return "> _Abstract-based._\n\n" + out
        return out
    if provider == "codex":
        return _summarize_codex(prompt, model)
    raise ValueError(f"Unknown provider: {provider}")


def extract_pdf_text(pdf_path: Path, char_limit: int = _PDF_TEXT_CHAR_LIMIT) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PdfTextExtractionError(
            "pypdf is required to summarize Zotero PDFs with the codex provider"
        ) from exc

    try:
        reader = PdfReader(str(pdf_path))
        chunks: list[str] = []
        total = 0
        truncated = False
        for page_number, page in enumerate(reader.pages, 1):
            page_text = (page.extract_text() or "").strip()
            if not page_text:
                continue
            chunk = f"[Page {page_number}]\n{page_text}"
            remaining = char_limit - total
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                truncated = True
                break
            chunks.append(chunk)
            total += len(chunk)
            if total >= char_limit:
                truncated = True
                break
    except Exception as exc:
        raise PdfTextExtractionError(f"could not extract text from {pdf_path}: {exc}") from exc

    text = "\n\n".join(chunks).strip()
    if not text:
        raise PdfTextExtractionError(f"could not extract text from {pdf_path}: no text found")
    if truncated:
        text += f"\n\n[PDF text truncated at {char_limit} characters.]"
    return text


def run_json_prompt(provider: str, model: str, prompt: str) -> str:
    """Run a no-tools prompt expected to return strict JSON."""
    if provider == "claude":
        return _summarize_claude(prompt, model)
    if provider == "codex":
        return _summarize_codex(prompt, model)
    raise ValueError(f"Unknown provider: {provider}")


def _summarize_claude(prompt: str, model: str, pdf_path=None) -> str:
    cmd = ["claude", "-p", "--model", model, "--output-format", "text"]
    if pdf_path is not None:
        cmd += ["--allowedTools", "Read", "--add-dir", str(pdf_path.parent)]
    else:
        cmd += ["--disallowed-tools", "*"]
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
        "codex", "exec",
        "--sandbox", "read-only",
    ]
    if pdf_path is not None:
        cmd += ["--add-dir", str(Path(pdf_path).parent)]
    cmd += [
        "--skip-git-repo-check",
        "--model", model,
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
