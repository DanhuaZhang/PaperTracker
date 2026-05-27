"""LLM summarization via subprocess to the `claude` or `codex` CLI.

Uses the user's logged-in Claude Pro/Max or ChatGPT Plus/Pro subscription quota.
No API key environment variable required.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

from . import config

log = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are a research assistant for embodied-AI / XR / spatial-computing researchers.
Summarize the following paper as markdown bullets covering, in order:
1. Core objective / what it does
2. Key technical contribution
3. Main results, benchmarks, or datasets
4. **Model & data:** Did the authors train a new model? If so, name its architecture/structure and the training dataset(s). Also state whether they introduce a new dataset or benchmark.
5. **Open source:** Are the code and/or dataset publicly released? Include the repo/link if the abstract gives one.
6. (Optional) Limitations noted by the authors
7. (Optional) Relevance to embodied / XR / AR / VR research

Rules:
- Active voice; cite numbers and dataset names when the abstract provides them.
- For items 4 and 5, if the abstract doesn't say, write "Not stated in the abstract" — do not guess.
- Do not restate the paper title.
- Do not speculate beyond the abstract.
- Under 350 words total.
- Output the bullets only — no preamble, no closing remark.

Title: {title}

Abstract: {abstract}
"""


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


def summarize_paper(paper: dict, provider: str, model: str) -> str:
    prompt = _PROMPT_TEMPLATE.format(
        title=paper["title"],
        abstract=paper["abstract"],
    )
    if provider == "claude":
        return _summarize_claude(prompt, model)
    if provider == "codex":
        return _summarize_codex(prompt, model)
    raise ValueError(f"Unknown provider: {provider}")


def _summarize_claude(prompt: str, model: str) -> str:
    cmd = [
        "claude", "-p",
        "--model", model,
        "--output-format", "text",
        "--disallowed-tools", "*",
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
