"""Markdown rendering of the daily digest."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import config

_SOURCE_BADGE = {
    "arxiv": "[arXiv]",
    "ieee": "[IEEE]",
    "acm": "[ACM]",
    "journal_rss": "[RSS]",
}


def render_digest(date_str: str, papers_with_summaries: list[tuple[dict, str]]) -> str:
    if not papers_with_summaries:
        return render_empty_digest(date_str)

    by_section: dict[str, list[tuple[dict, str]]] = defaultdict(list)
    for paper, summary in papers_with_summaries:
        if paper.get("venue"):
            by_section[paper["venue"]].append((paper, summary))
        elif paper["source"] == "arxiv":
            by_section["arXiv preprints"].append((paper, summary))
        else:
            by_section["Other ACM / IEEE"].append((paper, summary))

    lines = [
        f"# PaperTracker Daily Digest — {date_str}",
        "",
        f"> Auto-generated. {len(papers_with_summaries)} paper(s) on multi-modal embodied agents in 3D/XR/AR/VR.",
        "",
    ]

    # Priority venues first
    venue_names = [v["name"] for v in config.PRIORITY_VENUES]
    for vname in venue_names:
        if vname in by_section:
            lines.append(f"## ★ {vname}")
            lines.append("")
            for paper, summary in by_section[vname]:
                lines.extend(_render_paper(paper, summary))
            del by_section[vname]

    # Remaining sections (arXiv, Other ACM/IEEE)
    for section in ("arXiv preprints", "Other ACM / IEEE"):
        if section in by_section:
            lines.append(f"## {section}")
            lines.append("")
            for paper, summary in by_section[section]:
                lines.extend(_render_paper(paper, summary))

    return "\n".join(lines).rstrip() + "\n"


def render_empty_digest(date_str: str) -> str:
    return (
        f"# PaperTracker Daily Digest — {date_str}\n"
        "\n"
        "> No new papers matched the filter criteria today.\n"
        "\n"
    )


def save_digest(date_str: str, content: str, digest_dir: str) -> Path:
    out_dir = Path(digest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date_str}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _render_paper(paper: dict, summary: str) -> list[str]:
    authors = paper.get("authors") or []
    if len(authors) > 3:
        author_str = ", ".join(authors[:3]) + f" et al. ({len(authors)} authors)"
    else:
        author_str = ", ".join(authors) if authors else "(authors unknown)"

    badge = _SOURCE_BADGE.get(paper["source"], f"[{paper['source']}]")
    venue_tag = f" — ★ {paper['venue']}" if paper.get("venue") else ""

    link_text = paper.get("doi") or paper.get("canonical_id", "").split(":", 1)[-1]
    link_url = paper.get("url") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else "#")

    lines = [
        f"### {badge} {paper['title']}{venue_tag}",
        "",
        f"**Authors:** {author_str}  ",
    ]
    # Show the venue (container title) for CrossRef/RSS papers — it's the conference
    # or journal name, e.g. "Proceedings of ICASSP 2026" or "IEEE TVCG".
    container = paper.get("container_title")
    if container:
        lines.append(f"**Venue:** {container}  ")
    lines.extend([
        f"**Published:** {paper.get('published') or 'n/a'}  ",
        f"**Link:** [{link_text}]({link_url})",
        "",
        summary,
        "",
        "---",
        "",
    ])
    return lines
