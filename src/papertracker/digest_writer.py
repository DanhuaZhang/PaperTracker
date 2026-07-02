"""Markdown rendering of the daily digest."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from . import config, related_work

_SOURCE_BADGE = {
    "arxiv": "[arXiv]",
    "ieee": "[IEEE]",
    "acm": "[ACM]",
    "journal_rss": "[RSS]",
    "openalex": "[OpenAlex]",
}


def render_digest(
    date_str: str,
    papers_with_summaries: list[tuple[dict, str]],
    profile: config.ProjectProfile | None = None,
) -> str:
    if not papers_with_summaries:
        return render_empty_digest(date_str, profile)

    by_section: dict[str, list[tuple[dict, str]]] = defaultdict(list)
    for paper, summary in papers_with_summaries:
        if paper.get("venue"):
            by_section[paper["venue"]].append((paper, summary))
        elif paper["source"] == "arxiv":
            by_section["arXiv preprints"].append((paper, summary))
        else:
            by_section["Other ACM / IEEE"].append((paper, summary))

    profile_name = profile.name if profile else "multi-modal embodied agents in 3D/XR/AR/VR"
    lines = [
        f"# PaperTracker Daily Digest — {profile_name} — {date_str}",
        "",
        f"> Auto-generated. {len(papers_with_summaries)} paper(s) matched this project.",
        "",
    ]

    # Priority venues first
    venue_names = [v["name"] for v in (profile.priority_venues if profile else config.PRIORITY_VENUES)]
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


def render_empty_digest(date_str: str, profile: config.ProjectProfile | None = None) -> str:
    profile_name = profile.name if profile else "PaperTracker"
    return (
        f"# PaperTracker Daily Digest — {profile_name} — {date_str}\n"
        "\n"
        "> No new papers matched the filter criteria today.\n"
        "\n"
    )


def render_related_work_digest(
    date_str: str,
    papers_with_summaries: list[tuple[dict, str | None]],
    profile: config.ProjectProfile,
) -> str:
    lines = [
        f"# PaperTracker Related Work — {profile.name} — {date_str}",
        "",
        f"> Auto-generated. {len(papers_with_summaries)} related paper(s) ranked by topic relevance and citation signal.",
        "",
    ]
    if not papers_with_summaries:
        lines.extend(["No related work matched the filter criteria.", ""])
        return "\n".join(lines).rstrip() + "\n"

    for index, (paper, summary) in enumerate(papers_with_summaries, 1):
        lines.extend(_render_related_paper(index, paper, summary))
    return "\n".join(lines).rstrip() + "\n"


def render_faceted_related_work_matrix(
    date_str: str,
    facets: list[related_work.RelatedWorkFacet],
    candidates: list[dict],
    profile: config.ProjectProfile,
) -> str:
    lines = [
        f"# PaperTracker Related Work Facets - {profile.name} - {date_str}",
        "",
        f"> Auto-generated candidate matrix. {len(candidates)} paper(s) curated from OpenAlex metadata and abstracts.",
        "",
        "## Suggested section order",
        "",
    ]
    for facet in facets:
        lines.append(f"- {facet.name}")
    lines.extend(["", "## Candidate matrix", ""])

    if not candidates:
        lines.extend(["No related work matched the filter criteria.", ""])
        return "\n".join(lines).rstrip() + "\n"

    by_facet: dict[str, list[dict]] = defaultdict(list)
    for paper in candidates:
        by_facet[paper.get("primary_facet") or ""].append(paper)

    for facet in facets:
        lines.extend([f"### {facet.name}", "", facet.description, ""])
        papers = sorted(
            by_facet.get(facet.id, []),
            key=lambda p: -(p.get("related_work_score") or 0.0),
        )
        if not papers:
            lines.extend(["_No candidates selected for this facet._", ""])
            continue
        lines.extend(
            [
                "| Paper | Evidence | Curation rationale |",
                "| --- | --- | --- |",
            ]
        )
        for paper in papers:
            lines.append(_render_facet_row(paper))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_faceted_related_work(
    date_str: str,
    markdown: str,
    facets: list[related_work.RelatedWorkFacet],
    candidates: list[dict],
    profile: config.ProjectProfile,
) -> tuple[Path, Path]:
    out_dir = Path(profile.digest_dir) / "related-work"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{date_str}.facets.md"
    json_path = out_dir / f"{date_str}.facets.json"
    md_path.write_text(markdown, encoding="utf-8")
    payload = {
        "date": date_str,
        "project": {
            "id": profile.id,
            "name": profile.name,
            "topic_statement": profile.topic_statement,
            "contribution_statement": profile.contribution_statement,
        },
        "facets": related_work.facets_to_jsonable(facets),
        "suggested_section_order": [facet.name for facet in facets],
        "candidates": [related_work.candidate_to_jsonable(paper) for paper in candidates],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return md_path, json_path


def save_digest(date_str: str, content: str, digest_dir: str) -> Path:
    out_dir = Path(digest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date_str}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _render_facet_row(paper: dict) -> str:
    title = _md_escape(paper.get("title") or "(untitled)")
    year = _md_escape(_year(paper) or "n/a")
    venue = _md_escape(paper.get("container_title") or paper.get("venue") or "n/a")
    authors = paper.get("authors") or []
    author_str = ", ".join(authors[:3]) + (f" et al. ({len(authors)} authors)" if len(authors) > 3 else "")
    author_str = _md_escape(author_str or "authors unknown")
    link_text = paper.get("doi") or paper.get("openalex_id") or paper.get("canonical_id") or "link"
    link_url = paper.get("url") or "#"
    citations = int(paper.get("cited_by_count") or 0)
    score = float(paper.get("related_work_score") or 0.0)
    role = _md_escape(paper.get("role") or "background")
    why = _md_escape(paper.get("why_cite") or "")
    difference = _md_escape(paper.get("difference_from_contribution") or "")
    evidence_basis = _md_escape(paper.get("evidence_basis") or "metadata-only")
    paper_cell = (
        f"**[{title}]({link_url})**<br>"
        f"{author_str}<br>{year} - {venue}<br>"
        f"DOI/link: {_md_escape(link_text)}"
    )
    evidence_cell = f"Citations: {citations}<br>Score: {score:.3f}<br>Basis: {evidence_basis}"
    rationale_cell = f"Role: {role}<br>Why cite: {why}<br>Differs: {difference}"
    return f"| {paper_cell} | {evidence_cell} | {rationale_cell} |"


def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _year(paper: dict) -> str:
    published = str(paper.get("published") or "")
    if len(published) >= 4 and published[:4].isdigit():
        return published[:4]
    return ""


def _render_related_paper(index: int, paper: dict, summary: str | None) -> list[str]:
    authors = paper.get("authors") or []
    if len(authors) > 3:
        author_str = ", ".join(authors[:3]) + f" et al. ({len(authors)} authors)"
    else:
        author_str = ", ".join(authors) if authors else "(authors unknown)"

    badge = _SOURCE_BADGE.get(paper["source"], f"[{paper['source']}]")
    link_text = paper.get("doi") or paper.get("openalex_id") or paper.get("canonical_id", "")
    link_url = paper.get("url") or "#"
    found_via = ", ".join(paper.get("discovery_sources") or ["unknown"])
    citations = int(paper.get("cited_by_count") or 0)
    related_score = paper.get("related_work_score")
    relevance_score = paper.get("relevance_score")
    scores = []
    if related_score is not None:
        scores.append(f"related {related_score:.3f}")
    if relevance_score is not None:
        scores.append(f"relevance {relevance_score:.3f}")

    lines = [
        f"### {index}. {badge} {paper['title']}",
        "",
        f"**Authors:** {author_str}  ",
    ]
    container = paper.get("container_title")
    if container:
        lines.append(f"**Venue:** {container}  ")
    lines.extend(
        [
            f"**Published:** {paper.get('published') or 'n/a'}  ",
            f"**Citations:** {citations}  ",
            f"**Scores:** {' · '.join(scores) if scores else 'n/a'}  ",
            f"**Found via:** {found_via}  ",
            f"**Link:** [{link_text}]({link_url})",
            "",
        ]
    )
    abstract = (paper.get("abstract") or "").strip()
    if abstract:
        lines.extend([f"**Abstract:** {abstract}", ""])
    else:
        lines.extend(['_"No abstract available from OpenAlex."_', ""])
    if summary:
        lines.extend([summary, ""])
    lines.extend(["---", ""])
    return lines


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
