"""LLM summarization via subprocess to the `claude` or `codex` CLI.

Uses the user's logged-in Claude Pro/Max or ChatGPT Plus/Pro subscription quota.
No API key environment variable required.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

from . import config, zotero

log = logging.getLogger(__name__)

_TRIAGE_TEMPLATE = """\
You are a research assistant for embodied-AI / XR / spatial-computing researchers.
Summarize the following paper as markdown bullets covering, in order:
1. Core objective / what it does
2. Key technical contribution
3. Main results, benchmarks, or datasets
4. **Model & data:** Did the authors train a new model? If so, name its architecture/structure and the training dataset(s). Also state whether they introduce a new dataset or benchmark.
5. **Open source:** Are the code and/or dataset publicly released? Include the repo/link if the abstract gives one.
6. **Future work & directions:** Any future work the authors mention, plus 1–2 promising follow-up research directions this paper opens up.
7. (Optional) Limitations noted by the authors
8. (Optional) Relevance to embodied / XR / AR / VR research

Rules:
- Active voice; cite numbers and dataset names when the abstract provides them.
- For items 4 and 5, if the abstract doesn't say, write "Not stated in the abstract" — do not guess.
- For item 6 you may suggest directions beyond the abstract, but keep them concrete and grounded in the paper's topic; clearly mark them as suggestions (e.g. "Possible next step: …").
- Do not restate the paper title.
- Do not speculate beyond the abstract (except for the suggested directions in item 6).
- Under 400 words total.
- Output the bullets only — no preamble, no closing remark.

Title: {title}

Abstract: {abstract}
"""

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


def build_prompt(paper: dict, mode: str, pdf_path) -> tuple[str, bool]:
    """Return (prompt, uses_pdf). uses_pdf drives whether the Read tool is enabled."""
    uses_pdf = pdf_path is not None
    source = (
        _PDF_INSTRUCTION.format(pdf_path=pdf_path) if uses_pdf else _ABSTRACT_INSTRUCTION
    )
    if mode == "deep":
        body = _DEEP_HEADER.format(template=config.obsidian_template())
        meta = f"Title: {paper['title']}\n\nAbstract: {paper.get('abstract', '')}\n"
        return source + body + "\n" + meta, uses_pdf
    # triage template already embeds title/abstract; only prepend the source note
    body = _TRIAGE_TEMPLATE.format(title=paper["title"], abstract=paper.get("abstract", ""))
    return source + body, uses_pdf


def summarize_paper(paper: dict, provider: str, model: str, mode: str = "triage") -> str:
    pdf_path = None
    if provider == "claude":  # full-text-via-Read implemented for claude only
        pdf_path = zotero.find_pdf(paper)
        if pdf_path is None:
            log.info("No Zotero PDF for %s — summarizing from abstract", paper.get("canonical_id"))
    prompt, uses_pdf = build_prompt(paper, mode, pdf_path)
    if provider == "claude":
        out = _summarize_claude(prompt, model, pdf_path if uses_pdf else None)
        if pdf_path is None:
            return "> _Abstract-based (no Zotero PDF found)._\n\n" + out
        return out
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


def _summarize_codex(prompt: str, model: str) -> str:
    cmd = [
        "codex", "exec",
        "--sandbox", "read-only",
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
