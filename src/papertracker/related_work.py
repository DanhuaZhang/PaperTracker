"""Facet-aware related-work curation helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import re
from typing import Any


class RelatedWorkError(RuntimeError):
    """Raised when facet generation or annotation cannot be completed."""


@dataclass(frozen=True)
class RelatedWorkFacet:
    id: str
    name: str
    description: str
    query_hint: str


@dataclass
class RelatedWorkCandidate:
    canonical_id: str
    title: str
    authors: list[str]
    published: str
    venue: str | None
    container_title: str | None
    doi: str
    url: str
    openalex_id: str
    abstract: str
    cited_by_count: int
    facet_hits: dict[str, list[str]]
    primary_facet: str
    role: str
    why_cite: str
    difference_from_contribution: str
    evidence_basis: str
    related_work_score: float


_ID_RE = re.compile(r"[^a-z0-9]+")
_VALID_ROLES = {
    "foundational",
    "method",
    "benchmark",
    "system",
    "application",
    "contrast",
    "recent",
    "background",
}


def facet_from_mapping(raw: dict[str, Any]) -> RelatedWorkFacet:
    name = str(raw.get("name") or "").strip()
    description = str(raw.get("description") or "").strip()
    query_hint = str(raw.get("query_hint") or name).strip()
    facet_id = str(raw.get("id") or _slug(name)).strip()
    if not name or not description or not query_hint or not facet_id:
        raise RelatedWorkError("related_work_facets entries require id/name/description/query_hint")
    return RelatedWorkFacet(
        id=_slug(facet_id),
        name=name,
        description=description,
        query_hint=query_hint,
    )


def facets_to_jsonable(facets: list[RelatedWorkFacet]) -> list[dict[str, str]]:
    return [asdict(facet) for facet in facets]


def generate_facets(
    profile: Any,
    provider: str,
    model: str,
    facet_count: int,
) -> list[RelatedWorkFacet]:
    """Return configured facets or ask the LLM for strict-JSON facet suggestions."""
    configured = list(getattr(profile, "related_work_facets", []) or [])
    if configured:
        return configured

    from . import summarizer

    count = min(max(int(facet_count), 4), 7)
    prompt = f"""\
You are helping curate a scholarly related-work bibliography.
Generate {count} concise facets for the related-work section.

Return strict JSON only, with this shape:
{{"facets":[{{"id":"short-kebab-id","name":"Facet name","description":"One sentence scope","query_hint":"OpenAlex search query terms"}}]}}

Rules:
- Generate between 4 and 7 facets.
- Facets should be distinct enough to support separate related-work paragraphs.
- query_hint should be a compact keyword query, not prose.
- Do not write related-work prose.

Project name: {profile.name}
Topic statement:
{profile.topic_statement.strip()}

Contribution statement:
{(getattr(profile, "contribution_statement", None) or "Not provided.").strip()}
"""
    data = _load_json(summarizer.run_json_prompt(provider, model, prompt))
    raw_facets = data.get("facets")
    if not isinstance(raw_facets, list):
        raise RelatedWorkError("LLM facet response must contain a 'facets' list")
    facets = [facet_from_mapping(item) for item in raw_facets if isinstance(item, dict)]
    if not 4 <= len(facets) <= 7:
        raise RelatedWorkError(f"LLM returned {len(facets)} facets; expected 4-7")
    return facets


def rank_facet_candidates(
    papers: list[dict],
    facets: list[RelatedWorkFacet],
    profile: Any,
    threshold: float,
    limit: int,
) -> list[dict]:
    """Score papers per facet and return a round-robin matrix-sized candidate set."""
    if not papers:
        return []

    from . import relevance

    paper_texts = [f"{p.get('title', '')}. {p.get('abstract', '')}".strip() for p in papers]
    project_scores = relevance.score_batch(paper_texts, topic_statement=profile.topic_statement)
    max_citations = max(1, max(int(p.get("cited_by_count") or 0) for p in papers))
    facet_scores_by_id: dict[str, list[float]] = {}
    for facet in facets:
        facet_topic = f"{facet.name}. {facet.description}. {facet.query_hint}"
        facet_scores_by_id[facet.id] = relevance.score_batch(paper_texts, topic_statement=facet_topic)

    ranked_by_facet: dict[str, list[dict]] = {facet.id: [] for facet in facets}
    facet_lookup = {facet.id: facet for facet in facets}
    for idx, paper in enumerate(papers):
        citations = int(paper.get("cited_by_count") or 0)
        citation_score = math.log1p(citations) / math.log1p(max_citations)
        facet_hits = _normalize_facet_hits(paper.get("facet_hits") or {})
        matched_facet_ids = [fid for fid in facet_hits if fid in facet_lookup] or [
            facet.id for facet in facets
        ]
        paper["facet_hits"] = facet_hits
        paper["project_relevance_score"] = project_scores[idx]
        paper["facet_scores"] = {
            facet.id: facet_scores_by_id[facet.id][idx] for facet in facets
        }

        for facet_id in matched_facet_ids:
            facet_rel = paper["facet_scores"][facet_id]
            project_rel = project_scores[idx]
            discovery_sources = set(facet_hits.get(facet_id) or paper.get("discovery_sources") or [])
            source_bonus = min(max(len(discovery_sources) - 1, 0), 2) * 0.035
            multifacet_bonus = min(max(len(facet_hits) - 1, 0), 3) * 0.025
            hit_bonus = 0.04 if facet_id in facet_hits else 0.0
            score = (
                (0.42 * facet_rel)
                + (0.30 * project_rel)
                + (0.18 * citation_score)
                + source_bonus
                + multifacet_bonus
                + hit_bonus
            )
            if max(facet_rel, project_rel) < threshold:
                continue
            candidate = paper.copy()
            candidate["primary_facet"] = facet_id
            candidate["facet_relevance_score"] = facet_rel
            candidate["related_work_score"] = score
            ranked_by_facet[facet_id].append(candidate)

    for candidates in ranked_by_facet.values():
        candidates.sort(key=lambda p: -(p.get("related_work_score") or 0.0))

    return _round_robin_unique(ranked_by_facet, max(1, limit))


def annotate_candidates(
    candidates: list[dict],
    facets: list[RelatedWorkFacet],
    profile: Any,
    provider: str,
    model: str,
) -> list[dict]:
    """Ask the LLM for abstract/metadata-based citation-role annotations."""
    if not candidates:
        return []

    from . import summarizer

    payload = {
        "project": {
            "name": profile.name,
            "topic_statement": profile.topic_statement,
            "contribution_statement": getattr(profile, "contribution_statement", None) or "",
        },
        "facets": facets_to_jsonable(facets),
        "candidates": [
            {
                "canonical_id": paper.get("canonical_id"),
                "title": paper.get("title"),
                "year": _year(paper),
                "venue": paper.get("container_title") or paper.get("venue"),
                "authors": paper.get("authors") or [],
                "primary_facet": paper.get("primary_facet"),
                "abstract": paper.get("abstract") or "",
            }
            for paper in candidates
        ],
    }
    prompt = f"""\
You are annotating candidate papers for a scholarly related-work bibliography.
Use only the provided metadata and abstracts.

Return strict JSON only, with this shape:
{{"annotations":[{{"canonical_id":"...","role":"foundational|method|benchmark|system|application|contrast|recent|background","why_cite":"...","difference_from_contribution":"...","evidence_basis":"abstract|metadata-only"}}]}}

Rules:
- Include exactly one annotation per candidate canonical_id.
- why_cite should be one concise sentence.
- difference_from_contribution should compare against the contribution statement when provided; otherwise compare to the project topic.
- If a candidate has no abstract, evidence_basis must be "metadata-only" and the rationale must say it is based only on title/venue/authors/year.
- Do not write related-work prose.

JSON input:
{json.dumps(payload, ensure_ascii=False)}
"""
    data = _load_json(summarizer.run_json_prompt(provider, model, prompt))
    raw_annotations = data.get("annotations")
    if not isinstance(raw_annotations, list):
        raise RelatedWorkError("LLM annotation response must contain an 'annotations' list")
    by_id = {
        str(item.get("canonical_id")): item
        for item in raw_annotations
        if isinstance(item, dict) and item.get("canonical_id")
    }
    out: list[dict] = []
    for paper in candidates:
        annotated = dict(paper)
        ann = by_id.get(str(paper.get("canonical_id"))) or {}
        annotated["role"] = _normalize_role(ann.get("role"))
        annotated["why_cite"] = _clean_sentence(ann.get("why_cite")) or _default_why_cite(paper)
        annotated["difference_from_contribution"] = (
            _clean_sentence(ann.get("difference_from_contribution"))
            or _default_difference(profile)
        )
        annotated["evidence_basis"] = _normalize_evidence(
            ann.get("evidence_basis"),
            has_abstract=bool((paper.get("abstract") or "").strip()),
        )
        out.append(annotated)
    return out


def apply_selection(
    candidates: list[dict],
    selected: list[dict],
) -> list[dict]:
    by_id = {paper.get("canonical_id"): paper for paper in candidates}
    out: list[dict] = []
    for item in selected:
        cid = item.get("canonical_id")
        if cid not in by_id:
            continue
        paper = dict(by_id[cid])
        if item.get("primary_facet"):
            paper["primary_facet"] = item["primary_facet"]
        if item.get("role"):
            paper["role"] = _normalize_role(item["role"])
        out.append(paper)
    return out


def candidate_to_jsonable(paper: dict) -> dict:
    return {
        "canonical_id": paper.get("canonical_id"),
        "title": paper.get("title"),
        "authors": paper.get("authors") or [],
        "year": _year(paper),
        "published": paper.get("published") or "",
        "venue": paper.get("container_title") or paper.get("venue"),
        "doi": paper.get("doi") or "",
        "url": paper.get("url") or "",
        "openalex_id": paper.get("openalex_id") or "",
        "cited_by_count": int(paper.get("cited_by_count") or 0),
        "facet_hits": _normalize_facet_hits(paper.get("facet_hits") or {}),
        "primary_facet": paper.get("primary_facet") or "",
        "role": paper.get("role") or "background",
        "why_cite": paper.get("why_cite") or "",
        "difference_from_contribution": paper.get("difference_from_contribution") or "",
        "evidence_basis": paper.get("evidence_basis") or "metadata-only",
        "related_work_score": float(paper.get("related_work_score") or 0.0),
        "project_relevance_score": paper.get("project_relevance_score"),
        "facet_relevance_score": paper.get("facet_relevance_score"),
        "discovery_sources": paper.get("discovery_sources") or [],
    }


def _load_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RelatedWorkError(f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RelatedWorkError("LLM JSON response must be an object")
    return data


def _round_robin_unique(ranked_by_facet: dict[str, list[dict]], limit: int) -> list[dict]:
    selected: list[dict] = []
    seen: set[str] = set()
    facet_ids = list(ranked_by_facet)
    indices = {facet_id: 0 for facet_id in facet_ids}
    while len(selected) < limit:
        added = False
        for facet_id in facet_ids:
            candidates = ranked_by_facet[facet_id]
            idx = indices[facet_id]
            while idx < len(candidates):
                paper = candidates[idx]
                idx += 1
                cid = paper.get("canonical_id")
                if cid not in seen:
                    selected.append(paper)
                    seen.add(cid)
                    added = True
                    break
            indices[facet_id] = idx
            if len(selected) >= limit:
                break
        if not added:
            break

    if len(selected) < limit:
        leftovers = [
            paper
            for candidates in ranked_by_facet.values()
            for paper in candidates
            if paper.get("canonical_id") not in seen
        ]
        leftovers.sort(key=lambda p: -(p.get("related_work_score") or 0.0))
        for paper in leftovers:
            selected.append(paper)
            seen.add(paper.get("canonical_id"))
            if len(selected) >= limit:
                break
    selected.sort(
        key=lambda p: (
            facet_ids.index(p.get("primary_facet")) if p.get("primary_facet") in facet_ids else 999,
            -(p.get("related_work_score") or 0.0),
        )
    )
    return selected


def _normalize_facet_hits(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, values in raw.items():
        facet_id = _slug(str(key))
        if isinstance(values, str):
            normalized = [values]
        elif isinstance(values, list):
            normalized = [str(v) for v in values if v]
        else:
            normalized = []
        if facet_id:
            out[facet_id] = sorted(set(normalized))
    return out


def _normalize_role(raw: Any) -> str:
    role = str(raw or "").strip().lower()
    return role if role in _VALID_ROLES else "background"


def _normalize_evidence(raw: Any, has_abstract: bool) -> str:
    if not has_abstract:
        return "metadata-only"
    evidence = str(raw or "").strip().lower()
    return "abstract" if evidence == "abstract" else "metadata-only"


def _clean_sentence(raw: Any) -> str:
    return " ".join(str(raw or "").strip().split())


def _default_why_cite(paper: dict) -> str:
    basis = "title and metadata" if not (paper.get("abstract") or "").strip() else "abstract"
    return f"Relevant candidate for this facet based on its {basis}."


def _default_difference(profile: Any) -> str:
    if getattr(profile, "contribution_statement", None):
        return "Specific difference from the contribution requires full-paper review."
    return "Specific difference from the project topic requires full-paper review."


def _slug(raw: str) -> str:
    slug = _ID_RE.sub("-", raw.strip().lower()).strip("-")
    return slug or "facet"


def _year(paper: dict) -> str:
    published = str(paper.get("published") or "")
    if len(published) >= 4 and published[:4].isdigit():
        return published[:4]
    return ""
