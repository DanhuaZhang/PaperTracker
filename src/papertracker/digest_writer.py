"""Markdown rendering of the daily digest."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path

from . import config, related_work

_SOURCE_BADGE = {
    "arxiv": "[arXiv]",
    "ieee": "[IEEE]",
    "acm": "[ACM]",
    "journal_rss": "[RSS]",
    "openalex": "[OpenAlex]",
    "zotero": "[Zotero]",
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

    profile_name = profile.name if profile else "your research topics"
    lines = [
        f"# PaperTracker Daily Digest — {profile_name} — {date_str}",
        "",
        f"> Auto-generated. {len(papers_with_summaries)} paper(s) matched this project.",
        "",
    ]

    # Priority venues first
    venue_names = [
        v["name"] for v in (profile.priority_venues if profile else config.PRIORITY_VENUES)
    ]
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


def render_zotero_collection_digest(
    date_str: str,
    collection_path: str,
    papers_with_summaries: list[tuple[dict, str]],
    profile: config.ProjectProfile,
) -> str:
    lines = [
        f"# PaperTracker Zotero Batch — {profile.name} — {collection_path} — {date_str}",
        "",
        f"> Auto-generated from {len(papers_with_summaries)} local Zotero PDF(s).",
        "",
    ]
    if not papers_with_summaries:
        lines.extend(["No PDFs were found in this Zotero collection.", ""])
        return "\n".join(lines).rstrip() + "\n"

    for paper, summary in papers_with_summaries:
        lines.extend(_render_paper(paper, summary))
    return "\n".join(lines).rstrip() + "\n"


def render_related_work_digest(
    date_str: str,
    papers_with_summaries: list[tuple[dict, str | None]],
    profile: config.ProjectProfile,
) -> str:
    lines = [
        f"# PaperTracker Related Work — {profile.name} — {date_str}",
        "",
        f"> Auto-generated. {len(papers_with_summaries)} related paper(s) "
        "ranked by topic relevance and citation signal.",
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
        f"# PaperTracker Related Work Facets — {profile.name} — {date_str}",
        "",
        f"> Auto-generated candidate matrix. {len(candidates)} paper(s) curated "
        "from OpenAlex metadata and abstracts.",
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
    _atomic_write_text(md_path, markdown)
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
    _atomic_write_text(
        json_path,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )
    return md_path, json_path


_DAILY_COUNT_RE = re.compile(
    r"(?m)^> Auto-generated\. (?P<count>\d+) paper\(s\) matched this project\.$"
)
_SECTION_RE = re.compile(r"(?m)^## (?P<heading>[^\n]+)\n")


def save_daily_digest(
    date_str: str,
    content: str,
    digest_dir: str,
    *,
    new_paper_count: int,
) -> Path:
    """Write a daily digest without discarding results from an earlier same-day run."""
    out_dir = Path(digest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date_str}.md"
    if path.exists():
        if new_paper_count == 0:
            return path
        try:
            existing = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            existing = ""
        if existing:
            content = merge_daily_digests(existing, content)
    _atomic_write_text(path, content)
    return path


def merge_daily_digests(existing: str, update: str) -> str:
    """Merge new source sections into an existing generated daily digest."""
    if "No new papers matched the filter criteria today." in existing:
        return update

    old_match = _DAILY_COUNT_RE.search(existing)
    new_match = _DAILY_COUNT_RE.search(update)
    if old_match is None or new_match is None:
        body = _daily_sections(update)
        return existing.rstrip() + "\n\n---\n\n## Later update\n\n" + body.rstrip() + "\n"

    merged_count = int(old_match.group("count")) + int(new_match.group("count"))
    merged = _DAILY_COUNT_RE.sub(
        f"> Auto-generated. {merged_count} paper(s) matched this project.",
        existing,
        count=1,
    )
    prefix, sections = _split_sections(merged)
    _new_prefix, new_sections = _split_sections(update)
    section_index = {heading: index for index, (heading, _body) in enumerate(sections)}
    for heading, body in new_sections:
        if heading in section_index:
            index = section_index[heading]
            old_heading, old_body = sections[index]
            sections[index] = (old_heading, old_body.rstrip() + "\n\n" + body.lstrip())
        else:
            section_index[heading] = len(sections)
            sections.append((heading, body))
    rendered = prefix.rstrip() + "\n\n"
    rendered += "\n\n".join(f"## {heading}\n{body.strip()}" for heading, body in sections)
    return rendered.rstrip() + "\n"


def _split_sections(content: str) -> tuple[str, list[tuple[str, str]]]:
    matches = list(_SECTION_RE.finditer(content))
    if not matches:
        return content, []
    prefix = content[: matches[0].start()]
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        sections.append((match.group("heading"), content[match.end() : end]))
    return prefix, sections


def _daily_sections(content: str) -> str:
    _prefix, sections = _split_sections(content)
    if not sections:
        return content
    return "\n\n".join(f"## {heading}\n{body.strip()}" for heading, body in sections)


def save_digest(date_str: str, content: str, digest_dir: str) -> Path:
    out_dir = Path(digest_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date_str}.md"
    _atomic_write_text(path, content)
    return path


def _atomic_write_text(path: Path, content: str) -> None:
    """Atomically replace a UTF-8 text file in its destination directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _render_facet_row(paper: dict) -> str:
    title = _md_escape(paper.get("title") or "(untitled)")
    year = _md_escape(related_work.publication_year(paper) or "n/a")
    venue = _md_escape(paper.get("container_title") or paper.get("venue") or "n/a")
    authors = paper.get("authors") or []
    author_str = ", ".join(authors[:3]) + (
        f" et al. ({len(authors)} authors)" if len(authors) > 3 else ""
    )
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
    lines.extend(
        [
            f"**Published:** {paper.get('published') or 'n/a'}  ",
            f"**Link:** [{link_text}]({link_url})",
        ]
    )
    if paper.get("oa_url"):
        lines.append(f"**Open access:** [PDF/repository]({paper['oa_url']})  ")
    if "cited_by_count" in paper:
        lines.append(f"**Citations:** {int(paper.get('cited_by_count') or 0)}  ")
    if paper.get("metadata_sources"):
        lines.append(f"**Metadata:** {', '.join(paper['metadata_sources'])}  ")
    lines.extend(["", summary, "", "---", ""])
    return lines
