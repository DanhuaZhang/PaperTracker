"""`papertracker` console entry point."""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import math
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

from . import (
    config,
    dedup,
    digest_writer,
    related_work,
    relevance,
    selector,
    settings,
    summarizer,
    summary_cache,
    zotero,
)
from .sources import (
    acm_client,
    arxiv_client,
    doi_enrichment,
    ieee_client,
    journal_rss,
    openalex_client,
)

log = logging.getLogger("papertracker")

SOURCE_FETCHERS = {
    "arxiv": arxiv_client.fetch,
    "ieee": ieee_client.fetch,
    "acm": acm_client.fetch,
    "journal_rss": journal_rss.fetch,
}


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="papertracker",
        description="Daily digest of multi-modal embodied-agent papers in 3D/XR/AR/VR.",
    )
    project_group = p.add_mutually_exclusive_group()
    project_group.add_argument(
        "--project",
        default=None,
        help="Project profile ID from projects.toml. Defaults to default_project.",
    )
    project_group.add_argument(
        "--all-projects",
        action="store_true",
        help="Run every project profile from projects.toml.",
    )
    p.add_argument(
        "--list-projects",
        action="store_true",
        help="List configured project profiles and exit.",
    )
    p.add_argument(
        "--related-work",
        action="store_true",
        help="Find important all-time related work for the project topic via OpenAlex.",
    )
    p.add_argument(
        "--facets",
        action="store_true",
        help="Use the facet-aware related-work curation workflow.",
    )
    p.add_argument(
        "--facet-count",
        type=int,
        default=6,
        help="Number of related-work facets to request when not configured (default 6).",
    )
    p.add_argument(
        "--facet-candidates",
        type=int,
        default=40,
        help="OpenAlex candidates to fetch per facet and discovery mode (default 40).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Maximum papers to keep in --related-work output (default 30).",
    )
    p.add_argument(
        "--days", type=int, default=config.DEFAULT_DAYS,
        help=f"Fetch papers from the last N days (default {config.DEFAULT_DAYS}).",
    )
    p.add_argument(
        "--start-date", type=dt.date.fromisoformat, default=None,
        help="Start of fetch window (YYYY-MM-DD). Overrides --days; end defaults to today.",
    )
    p.add_argument(
        "--end-date", type=dt.date.fromisoformat, default=None,
        help="End of fetch window (YYYY-MM-DD). Defaults to today.",
    )
    p.add_argument(
        "--max-results", type=int, default=None,
        help=f"Max papers fetched per source (default {config.MAX_RESULTS_PER_QUERY}).",
    )
    p.add_argument(
        "--provider", choices=("claude", "codex"), default=None,
        help="LLM provider. Overrides env var / config file.",
    )
    p.add_argument(
        "--model", default=None,
        help="Model name. Overrides env var / config file.",
    )
    p.add_argument(
        "--sources",
        default=None,
        help=(
            "Comma-separated source list. "
            f"Available: {', '.join(SOURCE_FETCHERS)}"
        ),
    )
    p.add_argument(
        "--priority-venues-only", action="store_true",
        help="Drop papers not matching any configured priority venue.",
    )
    p.add_argument(
        "--threshold", type=float, default=None,
        help=(
            "Override the active relevance threshold. Lower = looser, higher = stricter."
        ),
    )
    p.add_argument(
        "--scorer",
        choices=("dense", "hybrid"),
        default=None,
        help="Relevance scorer to use. 'dense' is the original cosine-only scorer.",
    )
    p.add_argument(
        "--ignore-seen", action="store_true",
        help="Re-summarize papers already in the active seen file (useful for backfill).",
    )
    p.add_argument(
        "--refresh-summaries", action="store_true",
        help="Ignore the summary cache and re-generate summaries (overwrites cache entries).",
    )
    p.add_argument(
        "--no-summarize", action="store_true",
        help="Skip the LLM step; print matched papers to stdout instead.",
    )
    p.add_argument(
        "--select", action="store_true",
        help="Interactively pick which matched papers to summarize via a browser "
             "UI (numbered text prompt when headless), then summarize only those. "
             "Overrides --no-summarize.",
    )
    p.add_argument(
        "--list-zotero-collections",
        action="store_true",
        help="List local Zotero collection paths and exit.",
    )
    p.add_argument(
        "--zotero-collection",
        default=None,
        help="Batch-summarize PDFs attached to this Zotero collection path.",
    )
    p.add_argument(
        "--zotero-include-subcollections",
        action="store_true",
        help="Include PDFs from child collections when using --zotero-collection.",
    )
    p.add_argument(
        "--zotero-template",
        default=config.DEFAULT_SUMMARY_TEMPLATE,
        help=(
            "Summary template ID for --zotero-collection "
            f"(default {config.DEFAULT_SUMMARY_TEMPLATE})."
        ),
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable DEBUG logging.",
    )
    return p.parse_args(argv)


def _resolve_window(args: argparse.Namespace) -> tuple[dt.date, dt.date]:
    """Resolve the fetch window. Explicit --start-date/--end-date win; otherwise the
    window is [today - days, today]. End defaults to today when only start is given."""
    today = dt.date.today()
    end = args.end_date or today
    start = args.start_date or (end - dt.timedelta(days=args.days))
    if start > end:
        raise ValueError(f"start date {start} is after end date {end}")
    return start, end


def _resolve_llm(args: argparse.Namespace) -> tuple[str | None, str | None, int]:
    """Resolve provider+model and preflight the CLI. Returns (provider, model, code);
    code is 0 on success, otherwise the exit code main() should return."""
    try:
        provider, prov_src = settings.resolve_provider(args.provider)
        model, model_src = settings.resolve_model(args.model, provider)
    except ValueError as e:
        log.error(str(e))
        return None, None, 2
    log.info("Provider: %s (from %s)", provider, prov_src)
    log.info("Model:    %s (from %s)", model, model_src)
    try:
        summarizer.preflight(provider)
    except SystemExit as e:
        log.error(str(e))
        return None, None, 1
    return provider, model, 0


def _fetch_all(
    sources: list[str],
    start: dt.date,
    end: dt.date,
    profile: config.ProjectProfile,
) -> list[dict]:
    futures = {}
    with ThreadPoolExecutor(max_workers=max(len(sources), 1)) as ex:
        for name in sources:
            fetcher = SOURCE_FETCHERS.get(name)
            if fetcher is None:
                log.warning("Unknown source %r — skipping", name)
                continue
            futures[ex.submit(fetcher, start_date=start, end_date=end, profile=profile)] = name

        results: list[dict] = []
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                papers = fut.result()
                log.info("Source %s -> %d papers", name, len(papers))
                results.extend(papers)
            except Exception as e:
                log.error("Source %s failed: %s", name, e)
        return results


def _resolve_profiles(args: argparse.Namespace) -> tuple[list[config.ProjectProfile] | None, int]:
    try:
        if args.list_projects:
            profiles = config.project_profiles()
            if not profiles:
                print("(no projects.toml configured; using legacy papertracker.toml topic)")
            else:
                default = config.default_project_id()
                for profile in profiles:
                    marker = " *" if profile.id == default else ""
                    print(f"{profile.id}\t{profile.name}{marker}")
            return None, 0
        if args.all_projects:
            profiles = config.project_profiles()
            if not profiles:
                return [config.resolve_project(None)], 0
            return profiles, 0
        return [config.resolve_project(args.project)], 0
    except config.ConfigError as e:
        log.error(str(e))
        return None, 2


def _effective_profile(profile: config.ProjectProfile, args: argparse.Namespace) -> config.ProjectProfile:
    updates = {}
    if args.priority_venues_only and not profile.priority_venue_only:
        updates["priority_venue_only"] = True
    scorer = getattr(args, "scorer", None)
    if scorer is not None:
        updates["relevance_scorer"] = scorer
    return replace(profile, **updates) if updates else profile


def _active_threshold(profile: config.ProjectProfile, args: argparse.Namespace) -> float:
    if args.threshold is not None:
        return args.threshold
    if profile.relevance_scorer == "hybrid":
        return profile.hybrid_relevance_threshold
    return profile.relevance_threshold


def _score_kwargs(profile: config.ProjectProfile) -> dict:
    return {
        "mode": profile.relevance_scorer,
        "enable_reranker": profile.enable_reranker,
        "reranker_model": profile.reranker_model,
        "reranker_top_k": profile.reranker_top_k,
    }


def _enrich_doi_papers(papers: list[dict]) -> list[dict]:
    """Add optional OA, citation, and bibliographic metadata to selected papers."""
    for paper in papers:
        if paper.get("doi"):
            doi_enrichment.enrich_paper(paper)
    return papers


def _summary_template_options() -> tuple[list[str], str]:
    templates, default = config.summary_template_catalog()
    return [template.id for template in templates], default.id


def _run_profile(
    profile: config.ProjectProfile,
    args: argparse.Namespace,
    start_date: dt.date,
    end_date: dt.date,
    provider: str | None,
    model: str | None,
) -> int:
    profile = _effective_profile(profile, args)
    label = profile.id or "legacy"
    log.info("Project: %s (%s)", profile.name, label)

    source_arg = args.sources or ",".join(profile.enabled_sources_default)
    sources = [s.strip() for s in source_arg.split(",") if s.strip()]
    log.info(
        "Sources: %s | window=%s..%s | cap=%d/source",
        ", ".join(sources), start_date, end_date, config.MAX_RESULTS_PER_QUERY,
    )
    log.info(
        "Relevance scorer: %s | threshold=%.3f",
        profile.relevance_scorer,
        _active_threshold(profile, args),
    )

    fetched = _fetch_all(sources, start_date, end_date, profile)
    log.info("Total fetched (pre-dedup): %d", len(fetched))

    deduped = dedup.deduplicate_across_sources(fetched)
    log.info("After cross-source dedup: %d", len(deduped))

    threshold = _active_threshold(profile, args)
    relevant = relevance.filter_papers(
        deduped,
        threshold=threshold,
        topic_statement=profile.topic_statement,
        scorer=profile.relevance_scorer,
        enable_reranker=profile.enable_reranker,
        reranker_model=profile.reranker_model,
        reranker_top_k=profile.reranker_top_k,
    )

    seen_path = Path(profile.seen_papers_file)
    seen = set() if args.ignore_seen else dedup.load_seen(seen_path)
    new_papers = [
        p for p in relevant
        if not (seen & set(p.get("merged_ids", [p["canonical_id"]])))
    ]
    _enrich_doi_papers(new_papers)
    log.info("New (unseen) papers: %d", len(new_papers))

    today_str = dt.date.today().isoformat()

    if args.select:
        template_ids, default_template = _summary_template_options()
        to_summarize = selector.select_papers(
            new_papers, template_ids, default_template
        )
        if not to_summarize:
            log.info("No papers selected — nothing summarized.")
            return 0
        log.info("Selected %d of %d paper(s) to summarize", len(to_summarize), len(new_papers))
        provider, model, code = _resolve_llm(args)
        if code:
            return code
    elif args.no_summarize:
        _print_paper_list(new_papers, profile)
        return 0
    else:
        _template_ids, default_template = _summary_template_options()
        to_summarize = new_papers
        for p in to_summarize:
            p.setdefault("template", default_template)

    if not to_summarize:
        content = digest_writer.render_empty_digest(today_str, profile)
        path = digest_writer.save_digest(today_str, content, profile.digest_dir)
        log.info("No new papers. Empty digest -> %s", path)
        return 0

    cache_path = Path(profile.summary_cache_file)
    cache = {} if args.refresh_summaries else summary_cache.load(cache_path)
    new_cache_entries: dict[str, dict] = {}
    cache_hits = 0

    pairs: list[tuple[dict, str]] = []
    for i, paper in enumerate(to_summarize, 1):
        template_id = paper.get("template", default_template)
        cached = (
            None
            if args.refresh_summaries
            else summary_cache.lookup(cache, paper, template_id)
        )
        if cached is not None:
            cache_hits += 1
            log.info(
                "Cached [%d/%d] (%s) %s",
                i,
                len(to_summarize),
                template_id,
                paper["title"][:60],
            )
            pairs.append((paper, cached))
            continue

        log.info(
            "Summarizing [%d/%d] (%s) %s",
            i,
            len(to_summarize),
            template_id,
            paper["title"][:60],
        )
        try:
            summary = summarizer.summarize_paper(
                paper, provider, model, template_id, profile
            )
            new_cache_entries[
                summary_cache.cache_key(paper["canonical_id"], template_id)
            ] = {
                "summary": summary, "model": model,
                "provider": provider, "template": template_id, "generated": today_str,
            }
        except subprocess.CalledProcessError as e:
            reason = (e.stderr or "").strip().splitlines()[-1] if e.stderr else f"exit {e.returncode}"
            log.error("Failed: %s — %s", paper["canonical_id"], reason)
            summary = f'_"(summary failed: {reason})"_'
        except summarizer.PdfTextExtractionError as e:
            log.error("Failed: %s — %s", paper["canonical_id"], e)
            summary = f'_"(summary failed: {e})"_'
        except subprocess.TimeoutExpired:
            log.error("Timeout: %s", paper["canonical_id"])
            summary = '_"(summary failed: timeout)"_'
        pairs.append((paper, summary))
        if i < len(to_summarize):
            time.sleep(1)

    if new_cache_entries:
        summary_cache.save(cache_path, new_cache_entries)
    log.info("Summaries: %d generated, %d reused from cache", len(new_cache_entries), cache_hits)

    content = digest_writer.render_digest(today_str, pairs, profile)
    path = digest_writer.save_digest(today_str, content, profile.digest_dir)
    log.info("Digest -> %s", path)

    seen_ids = {mid for p in to_summarize for mid in p.get("merged_ids", [p["canonical_id"]])}
    dedup.save_seen(seen_path, seen_ids)
    log.info("Marked %d new paper(s) as seen", len(to_summarize))
    return 0


def _run_related_work_profile(profile: config.ProjectProfile, args: argparse.Namespace) -> int:
    profile = _effective_profile(profile, args)
    label = profile.id or "legacy"
    cap = args.max_results if args.max_results is not None else min(config.MAX_RESULTS_PER_QUERY, 200)
    limit = max(1, args.limit)
    threshold = _active_threshold(profile, args)
    today_str = dt.date.today().isoformat()

    log.info("Project: %s (%s)", profile.name, label)
    log.info(
        "Related work: OpenAlex cap=%d | limit=%d | scorer=%s | threshold=%.3f",
        cap, limit, profile.relevance_scorer, threshold,
    )

    fetched = openalex_client.fetch_related_work(profile, cap=cap)
    log.info("OpenAlex related work fetched: %d", len(fetched))
    deduped = dedup.deduplicate_across_sources(fetched)
    log.info("After related-work dedup: %d", len(deduped))
    ranked = _rank_related_work(deduped, profile, threshold, limit)
    log.info("Related work kept: %d", len(ranked))

    if args.select:
        template_ids, default_template = _summary_template_options()
        to_summarize = selector.select_papers(
            ranked, template_ids, default_template
        )
        if not to_summarize:
            log.info("No papers selected — writing unsummarized related-work digest.")
            pairs: list[tuple[dict, str | None]] = [(p, None) for p in ranked]
        else:
            provider, model, code = _resolve_llm(args)
            if code:
                return code
            pairs = _summarize_selected_related_work(
                to_summarize,
                args,
                profile,
                provider,
                model,
                today_str,
            )
    else:
        pairs = [(p, None) for p in ranked]

    content = digest_writer.render_related_work_digest(today_str, pairs, profile)
    path = digest_writer.save_digest(
        today_str,
        content,
        str(Path(profile.digest_dir) / "related-work"),
    )
    log.info("Related-work digest -> %s", path)
    return 0


def _run_faceted_related_work_profile(profile: config.ProjectProfile, args: argparse.Namespace) -> int:
    profile = _effective_profile(profile, args)
    label = profile.id or "legacy"
    limit = max(1, args.limit)
    threshold = _active_threshold(profile, args)
    today_str = dt.date.today().isoformat()

    provider, model, code = _resolve_llm(args)
    if code:
        return code

    log.info("Project: %s (%s)", profile.name, label)
    log.info(
        "Faceted related work: facet_count=%d | facet_candidates=%d | limit=%d | scorer=%s | threshold=%.3f",
        args.facet_count,
        args.facet_candidates,
        limit,
        profile.relevance_scorer,
        threshold,
    )

    try:
        facets = related_work.generate_facets(profile, provider, model, args.facet_count)
        log.info("Related-work facets: %s", ", ".join(facet.name for facet in facets))
        fetched = openalex_client.fetch_related_work_faceted(
            profile,
            facets=facets,
            candidates_per_facet=max(1, args.facet_candidates),
        )
        log.info("OpenAlex faceted related work fetched: %d", len(fetched))
        ranked = related_work.rank_facet_candidates(
            fetched,
            facets=facets,
            profile=profile,
            threshold=threshold,
            limit=limit,
        )
        log.info("Faceted related work kept: %d", len(ranked))
        annotated = related_work.annotate_candidates(ranked, facets, profile, provider, model)
    except related_work.RelatedWorkError as e:
        log.error(str(e))
        return 1
    except subprocess.CalledProcessError as e:
        reason = (e.stderr or "").strip().splitlines()[-1] if e.stderr else f"exit {e.returncode}"
        log.error("Related-work LLM step failed: %s", reason)
        return 1
    except subprocess.TimeoutExpired:
        log.error("Related-work LLM step timed out")
        return 1

    candidates = annotated
    if args.select:
        selected = selector.select_related_work_candidates(annotated, facets)
        candidates = related_work.apply_selection(annotated, selected)
        log.info("Selected %d of %d related-work candidate(s)", len(candidates), len(annotated))

    content = digest_writer.render_faceted_related_work_matrix(
        today_str,
        facets,
        candidates,
        profile,
    )
    md_path, json_path = digest_writer.save_faceted_related_work(
        today_str,
        content,
        facets,
        candidates,
        profile,
    )
    log.info("Faceted related-work matrix -> %s", md_path)
    log.info("Faceted related-work JSON -> %s", json_path)
    return 0


def _rank_related_work(
    papers: list[dict],
    profile: config.ProjectProfile,
    threshold: float,
    limit: int,
) -> list[dict]:
    if not papers:
        return []
    texts = [
        f"{p.get('title', '')}. {p.get('abstract', '')}".strip()
        for p in papers
    ]
    scores = relevance.score_texts(profile.topic_statement, texts, **_score_kwargs(profile))
    max_citations = max(1, max(int(p.get("cited_by_count") or 0) for p in papers))
    kept: list[dict] = []
    for paper, score in zip(papers, scores):
        rel_score = score.final_score
        citations = int(paper.get("cited_by_count") or 0)
        citation_score = math.log1p(citations) / math.log1p(max_citations)
        discovery_sources = set(paper.get("discovery_sources") or [])
        channel_bonus = min(max(len(discovery_sources) - 1, 0), 2) * 0.03
        semantic_bonus = 0.03 if "semantic" in discovery_sources else 0.0
        relevance.annotate_score_fields(paper, score)
        paper["related_work_score"] = (
            (0.70 * rel_score)
            + (0.24 * citation_score)
            + channel_bonus
            + semantic_bonus
        )
        if rel_score >= threshold:
            kept.append(paper)

    kept.sort(key=lambda p: -(p.get("related_work_score") or 0.0))
    return kept[:limit]


def _summarize_selected_related_work(
    to_summarize: list[dict],
    args: argparse.Namespace,
    profile: config.ProjectProfile,
    provider: str,
    model: str,
    today_str: str,
) -> list[tuple[dict, str | None]]:
    _template_ids, default_template = _summary_template_options()
    cache_path = Path(profile.summary_cache_file)
    cache = {} if args.refresh_summaries else summary_cache.load(cache_path)
    new_cache_entries: dict[str, dict] = {}
    pairs: list[tuple[dict, str | None]] = []
    for i, paper in enumerate(to_summarize, 1):
        template_id = paper.get("template", default_template)
        cached = (
            None
            if args.refresh_summaries
            else summary_cache.lookup(cache, paper, template_id)
        )
        if cached is not None:
            log.info("Cached [%d/%d] (%s) %s", i, len(to_summarize), template_id, paper["title"][:60])
            pairs.append((paper, cached))
            continue
        log.info("Summarizing [%d/%d] (%s) %s", i, len(to_summarize), template_id, paper["title"][:60])
        try:
            summary = summarizer.summarize_paper(
                paper, provider, model, template_id, profile
            )
            new_cache_entries[
                summary_cache.cache_key(paper["canonical_id"], template_id)
            ] = {
                "summary": summary, "model": model,
                "provider": provider, "template": template_id, "generated": today_str,
            }
        except subprocess.CalledProcessError as e:
            reason = (e.stderr or "").strip().splitlines()[-1] if e.stderr else f"exit {e.returncode}"
            log.error("Failed: %s — %s", paper["canonical_id"], reason)
            summary = f'_"(summary failed: {reason})"_'
        except summarizer.PdfTextExtractionError as e:
            log.error("Failed: %s — %s", paper["canonical_id"], e)
            summary = f'_"(summary failed: {e})"_'
        except subprocess.TimeoutExpired:
            log.error("Timeout: %s", paper["canonical_id"])
            summary = '_"(summary failed: timeout)"_'
        pairs.append((paper, summary))
        if i < len(to_summarize):
            time.sleep(1)
    if new_cache_entries:
        summary_cache.save(cache_path, new_cache_entries)
    return pairs


def _run_zotero_collection_profile(profile: config.ProjectProfile, args: argparse.Namespace) -> int:
    profile = _effective_profile(profile, args)
    today_str = dt.date.today().isoformat()

    try:
        papers = zotero.collection_papers(
            args.zotero_collection,
            include_subcollections=args.zotero_include_subcollections,
        )
    except zotero.ZoteroError as e:
        log.error(str(e))
        return 2

    for paper in papers:
        paper["template"] = args.zotero_template

    log.info(
        "Zotero collection %r -> %d PDF-backed item(s)",
        args.zotero_collection,
        len(papers),
    )
    if not papers:
        content = digest_writer.render_zotero_collection_digest(
            today_str,
            args.zotero_collection,
            [],
            profile,
        )
        path = digest_writer.save_digest(
            today_str,
            content,
            str(Path(profile.digest_dir) / "zotero" / _slug(args.zotero_collection)),
        )
        log.info("Zotero batch digest -> %s", path)
        return 0

    provider, model, code = _resolve_llm(args)
    if code:
        return code

    pairs = _summarize_zotero_papers(papers, args, profile, provider, model, today_str)
    content = digest_writer.render_zotero_collection_digest(
        today_str,
        args.zotero_collection,
        pairs,
        profile,
    )
    path = digest_writer.save_digest(
        today_str,
        content,
        str(Path(profile.digest_dir) / "zotero" / _slug(args.zotero_collection)),
    )
    log.info("Zotero batch digest -> %s", path)
    return 0


def _summarize_zotero_papers(
    papers: list[dict],
    args: argparse.Namespace,
    profile: config.ProjectProfile,
    provider: str,
    model: str,
    today_str: str,
) -> list[tuple[dict, str]]:
    cache_path = Path(profile.summary_cache_file)
    cache = {} if args.refresh_summaries else summary_cache.load(cache_path)
    new_cache_entries: dict[str, dict] = {}
    pairs: list[tuple[dict, str]] = []

    for i, paper in enumerate(papers, 1):
        template_id = paper.get("template", args.zotero_template)
        cached = (
            None
            if args.refresh_summaries
            else summary_cache.lookup(cache, paper, template_id)
        )
        if cached is not None:
            log.info("Cached [%d/%d] (%s) %s", i, len(papers), template_id, paper["title"][:60])
            pairs.append((paper, cached))
            continue

        pdf_path = Path(paper["pdf_path"])
        log.info("Summarizing PDF [%d/%d] (%s) %s", i, len(papers), template_id, paper["title"][:60])
        try:
            summary = summarizer.summarize_paper(
                paper,
                provider,
                model,
                template_id,
                profile,
                pdf_path=pdf_path,
            )
            new_cache_entries[
                summary_cache.cache_key(paper["canonical_id"], template_id)
            ] = {
                "summary": summary,
                "model": model,
                "provider": provider,
                "template": template_id,
                "pdf_path": str(pdf_path),
                "generated": today_str,
            }
        except subprocess.CalledProcessError as e:
            reason = (e.stderr or "").strip().splitlines()[-1] if e.stderr else f"exit {e.returncode}"
            log.error("Failed: %s — %s", paper["canonical_id"], reason)
            summary = f'_"(summary failed: {reason})"_'
        except summarizer.PdfTextExtractionError as e:
            log.error("Failed: %s — %s", paper["canonical_id"], e)
            summary = f'_"(summary failed: {e})"_'
        except subprocess.TimeoutExpired:
            log.error("Timeout: %s", paper["canonical_id"])
            summary = '_"(summary failed: timeout)"_'
        pairs.append((paper, summary))
        if i < len(papers):
            time.sleep(1)

    if new_cache_entries:
        summary_cache.save(cache_path, new_cache_entries)
    return pairs


def _list_zotero_collections() -> int:
    collections = zotero.list_collections()
    if not collections:
        print("(no Zotero collections found)")
        return 0
    for collection in collections:
        print(collection["path"])
    return 0


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "collection"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.verbose)

    if args.list_zotero_collections:
        return _list_zotero_collections()

    if args.zotero_collection and args.related_work:
        log.error("--zotero-collection cannot be combined with --related-work")
        return 2

    templates_required = bool(
        args.zotero_collection
        or args.select
        or (not args.no_summarize and not args.related_work)
    )
    if templates_required:
        try:
            config.summary_template_catalog()
            if args.zotero_collection:
                config.summary_template(args.zotero_template)
        except config.ConfigError as exc:
            log.error(str(exc))
            return 2

    profiles, code = _resolve_profiles(args)
    if code or profiles is None:
        return code

    # Apply CLI override for the per-source result cap.
    if args.max_results is not None:
        config.MAX_RESULTS_PER_QUERY = args.max_results

    if args.related_work:
        if args.facets:
            for profile in profiles:
                code = _run_faceted_related_work_profile(profile, args)
                if code:
                    return code
            return 0
        if not args.select:
            log.info("--related-work set; skipping LLM step unless --select is used")
        for profile in profiles:
            code = _run_related_work_profile(profile, args)
            if code:
                return code
        return 0

    if args.zotero_collection:
        for profile in profiles:
            code = _run_zotero_collection_profile(profile, args)
            if code:
                return code
        return 0

    try:
        start_date, end_date = _resolve_window(args)
    except ValueError as e:
        log.error(str(e))
        return 2

    # Resolve provider/model up front only when we'll summarize without asking.
    # In --select mode this is deferred until the user has actually picked papers,
    # so just browsing the list doesn't require the LLM CLI to be installed.
    provider = model = None  # type: ignore[assignment]
    if not args.no_summarize and not args.select:
        provider, model, code = _resolve_llm(args)
        if code:
            return code
    elif args.no_summarize and not args.select:
        log.info("--no-summarize set; skipping LLM step")

    for profile in profiles:
        code = _run_profile(profile, args, start_date, end_date, provider, model)
        if code:
            return code
    return 0


def _print_paper_list(papers: list[dict], profile: config.ProjectProfile | None = None) -> None:
    """Pretty-print the no-summarize paper list with bold titles and dim metadata."""
    use_color = sys.stdout.isatty()
    BOLD   = "\033[1m"  if use_color else ""
    DIM    = "\033[2m"  if use_color else ""
    CYAN   = "\033[36m" if use_color else ""
    GREEN  = "\033[32m" if use_color else ""
    YELLOW = "\033[33m" if use_color else ""
    RED    = "\033[31m" if use_color else ""
    RESET  = "\033[0m"  if use_color else ""

    if profile:
        print(f"\n# {profile.name}")

    if not papers:
        print(f"{DIM}(no papers matched){RESET}")
        return

    for p in sorted(papers, key=lambda x: -(x.get("relevance_score") or 0)):
        score = p.get("relevance_score") or 0.0
        if score >= 0.75:
            score_color = GREEN
        elif score >= 0.65:
            score_color = CYAN
        elif score >= 0.55:
            score_color = YELLOW
        else:
            score_color = RED

        venue = p.get("venue")
        container = p.get("container_title")
        if venue:
            title_suffix = f"  {CYAN}★ {venue}{RESET}"
        elif container:
            title_suffix = f"  {CYAN}{container}{RESET}"
        else:
            title_suffix = ""
        published = p.get("published") or "?"
        url = p.get("url") or ""
        venue_meta = container or venue or "—"

        print()
        print(f"  {score_color}{score:.3f}{RESET}  {BOLD}{p['title']}{RESET}{title_suffix}")
        print(f"        {DIM}{p['source']} · {venue_meta} · {published} · {url}{RESET}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
