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
    summary_templates,
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
        description="Daily markdown digest of new papers matching your research topics.",
    )
    project_group = p.add_mutually_exclusive_group()
    project_group.add_argument(
        "--project",
        default=None,
        help="Project profile ID from user_data/projects.toml. Defaults to default_project.",
    )
    project_group.add_argument(
        "--all-projects",
        action="store_true",
        help="Run every project profile from user_data/projects.toml.",
    )
    p.add_argument(
        "--list-projects",
        action="store_true",
        help="List configured project profiles and exit.",
    )
    p.add_argument(
        "--list-templates",
        action="store_true",
        help="List summary template IDs, labels, evidence requirements, and defaults.",
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
        "--days",
        type=int,
        default=config.DEFAULT_DAYS,
        help=f"Fetch papers from the last N days (default {config.DEFAULT_DAYS}).",
    )
    p.add_argument(
        "--start-date",
        type=dt.date.fromisoformat,
        default=None,
        help="Start of fetch window (YYYY-MM-DD). Overrides --days; end defaults to today.",
    )
    p.add_argument(
        "--end-date",
        type=dt.date.fromisoformat,
        default=None,
        help="End of fetch window (YYYY-MM-DD). Defaults to today.",
    )
    p.add_argument(
        "--max-results",
        type=int,
        default=None,
        help=f"Max papers fetched per source (default {config.MAX_RESULTS_PER_QUERY}).",
    )
    p.add_argument(
        "--provider",
        choices=("claude", "codex"),
        default=None,
        help="LLM provider. Overrides env var / config file.",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Model name. Overrides env var / config file.",
    )
    p.add_argument(
        "--effort",
        choices=(*settings.VALID_EFFORTS, settings.INHERIT_EFFORT),
        default=None,
        metavar="LEVEL",
        help=(
            "How hard the model thinks per summary, on one scale for both "
            f"providers: {', '.join(settings.VALID_EFFORTS)} "
            f"(currently {config.REASONING_EFFORT!r}), or "
            f"{settings.INHERIT_EFFORT!r} to let the provider CLI choose. "
            "Overrides env var / config file."
        ),
    )
    p.add_argument(
        "--sources",
        default=None,
        help=(f"Comma-separated source list. Available: {', '.join(SOURCE_FETCHERS)}"),
    )
    p.add_argument(
        "--priority-venues-only",
        action="store_true",
        help="Drop papers not matching any configured priority venue.",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=("Override the active relevance threshold. Lower = looser, higher = stricter."),
    )
    p.add_argument(
        "--scorer",
        choices=("dense", "hybrid"),
        default=None,
        help="Relevance scorer to use. 'dense' is the original cosine-only scorer.",
    )
    p.add_argument(
        "--ignore-seen",
        action="store_true",
        help="Re-summarize papers already in the active seen file (useful for backfill).",
    )
    p.add_argument(
        "--refresh-summaries",
        action="store_true",
        help="Ignore the summary cache and re-generate summaries (overwrites cache entries).",
    )
    p.add_argument(
        "--no-summarize",
        action="store_true",
        help="Skip AI CLI calls. Daily mode prints matches; faceted related-work "
        "requires configured facets and uses local annotations.",
    )
    p.add_argument(
        "--select",
        action="store_true",
        help="Interactively pick which matched papers to summarize via a browser "
        "UI (numbered text prompt when headless), then summarize only those. "
        "In daily mode, overrides --no-summarize.",
    )
    p.add_argument(
        "--template",
        default=None,
        help="Summary template ID for every paper (per-paper selection can override it).",
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
        default=None,
        help=("Deprecated alias for --template when using --zotero-collection."),
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
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
    """Resolve provider+model+effort and preflight the CLI. Returns (provider, model,
    code); code is 0 on success, otherwise the exit code main() should return."""
    try:
        provider, prov_src = settings.resolve_provider(args.provider)
        model, model_src = settings.resolve_model(args.model, provider)
        effort, effort_src = settings.resolve_effort(args.effort)
    except ValueError as e:
        log.error(str(e))
        return None, None, 2
    log.info("Provider: %s (from %s)", provider, prov_src)
    log.info("Model:    %s (from %s)", model, model_src)
    log.info(
        "Effort:   %s (from %s)",
        effort or "provider default",
        effort_src,
    )
    summarizer.set_reasoning_effort(effort)
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
) -> tuple[list[dict], list[str]]:
    futures = {}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(len(sources), 1)) as ex:
        for name in sources:
            fetcher = SOURCE_FETCHERS.get(name)
            if fetcher is None:
                log.error("Unknown source %r", name)
                failures.append(name)
                continue
            futures[ex.submit(fetcher, start_date=start, end_date=end, profile=profile)] = name

        results: list[dict] = []
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                papers = fut.result()
                log.info("Source %s -> %d papers", name, len(papers))
                results.extend(papers)
            except Exception as e:  # noqa: BLE001 — one dead source must not sink the run
                log.error("Source %s failed: %s", name, e)
                failures.append(name)
        return results, failures


def _validate_args(args: argparse.Namespace) -> int:
    if args.facets and not args.related_work:
        log.error("--facets requires --related-work")
        return 2
    if args.days < 0:
        log.error("--days must be zero or greater")
        return 2
    for name in ("max_results", "limit", "facet_count", "facet_candidates"):
        value = getattr(args, name)
        if value is not None and value <= 0:
            log.error("--%s must be greater than zero", name.replace("_", "-"))
            return 2
    if args.sources:
        requested = {part.strip() for part in args.sources.split(",") if part.strip()}
        unknown = sorted(requested - SOURCE_FETCHERS.keys())
        if unknown:
            log.error(
                "Unknown source(s): %s. Available sources: %s",
                ", ".join(unknown),
                ", ".join(SOURCE_FETCHERS),
            )
            return 2
    return 0


def _resolve_profiles(args: argparse.Namespace) -> tuple[list[config.ProjectProfile] | None, int]:
    try:
        if args.list_projects:
            profiles = config.project_profiles()
            if not profiles:
                print(
                    "(no user_data/projects.toml configured; "
                    "using the placeholder topic from config.toml)"
                )
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


def _effective_profile(
    profile: config.ProjectProfile, args: argparse.Namespace
) -> config.ProjectProfile:
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


def _summary_template_options(
    evidence: str = "abstract",
    args: argparse.Namespace | None = None,
) -> tuple[tuple[summary_templates.SummaryTemplate, ...], str]:
    """Return the templates this mode may offer, plus its initial selection.

    Filtered to a single evidence type on purpose. A discovery or related-work
    run holds an abstract and nothing else; the Zotero batch holds a PDF. The
    catalog used to be handed over whole and the options the mode could not
    satisfy were disabled per paper, which meant a picker three-quarters greyed
    out — that reads as a broken control, not as a mode boundary.
    """
    templates, default = config.summary_template_catalog(evidence)
    offered = tuple(t for t in templates if t.evidence == evidence)
    override = None
    if args is not None:
        override = (
            getattr(args, "template_override", None)
            or getattr(args, "template", None)
            or getattr(args, "zotero_template", None)
        )
    return offered, override or default.id


def _resolve_template_override(args: argparse.Namespace) -> tuple[str | None, int]:
    selected = getattr(args, "template", None)
    alias = getattr(args, "zotero_template", None)
    if selected and alias and selected != alias:
        log.error(
            "Conflicting template values: --template %r and --zotero-template %r",
            selected,
            alias,
        )
        return None, 2
    if alias:
        log.warning("--zotero-template is deprecated; use --template instead")
    return selected or alias, 0


def _list_templates() -> int:
    templates, _ = config.summary_template_catalog("abstract")
    print("ID\tLABEL\tEVIDENCE\tDESCRIPTION\tDEFAULT")
    for template in templates:
        defaults = []
        if template.id == config.DEFAULT_ABSTRACT_TEMPLATE:
            defaults.append("abstract")
        if template.id == config.DEFAULT_FULLTEXT_TEMPLATE:
            defaults.append("fulltext")
        status = ",".join(defaults) if defaults else "-"
        print(
            f"{template.id}\t{template.label}\t{template.evidence}\t"
            f"{template.description}\t{status}"
        )
    return 0


def _validate_template_evidence(papers: list[dict], default_template: str) -> bool:
    valid = True
    for paper in papers:
        template_id = paper.get("template", default_template)
        template = config.summary_template(template_id)
        compatible, reason = summary_templates.compatibility(template, paper)
        if not compatible:
            log.error(
                "Paper %s cannot use template %r: %s",
                paper.get("canonical_id") or paper.get("title") or "(unknown)",
                template_id,
                reason,
            )
            valid = False
    return valid


def _summary_fingerprint(
    paper: dict,
    template_id: str,
    provider: str,
    model: str,
    profile: config.ProjectProfile,
) -> str:
    template = config.summary_template(template_id)
    pdf_path = Path(paper["pdf_path"]) if template.evidence == "fulltext" else None
    try:
        return summary_cache.fingerprint(
            paper,
            template,
            provider,
            model,
            profile=profile,
            pdf_path=pdf_path,
            pipeline_version=summarizer.PROMPT_PIPELINE_VERSION,
        )
    except OSError as exc:
        raise summarizer.PdfTextExtractionError(
            f"could not read full-text PDF for cache identity: {exc}"
        ) from exc


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
        ", ".join(sources),
        start_date,
        end_date,
        config.MAX_RESULTS_PER_QUERY,
    )
    log.info(
        "Relevance scorer: %s | threshold=%.3f",
        profile.relevance_scorer,
        _active_threshold(profile, args),
    )

    fetched, failed_sources = _fetch_all(sources, start_date, end_date, profile)
    log.info("Total fetched (pre-dedup): %d", len(fetched))
    if failed_sources:
        log.error("Failed source(s): %s", ", ".join(sorted(set(failed_sources))))
    source_exit_code = 1 if failed_sources else 0
    if failed_sources and not fetched:
        log.error("No source completed successfully; no digest was written")
        return source_exit_code

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
    new_papers = [p for p in relevant if not (seen & set(p.get("merged_ids", [p["canonical_id"]])))]
    _enrich_doi_papers(new_papers)
    log.info("New (unseen) papers: %d", len(new_papers))

    today_str = dt.date.today().isoformat()

    if args.select:
        templates, default_template = _summary_template_options("abstract", args)
        to_summarize = selector.select_papers(new_papers, templates, default_template)
        if not to_summarize:
            log.info("No papers selected — nothing summarized.")
            return source_exit_code
        log.info("Selected %d of %d paper(s) to summarize", len(to_summarize), len(new_papers))
        provider, model, code = _resolve_llm(args)
        if code:
            return code
    elif args.no_summarize:
        _print_paper_list(new_papers, profile)
        return source_exit_code
    else:
        _templates, default_template = _summary_template_options("abstract", args)
        to_summarize = new_papers
        for p in to_summarize:
            p["template"] = default_template

    if not to_summarize:
        content = digest_writer.render_empty_digest(today_str, profile)
        path = digest_writer.save_daily_digest(
            today_str,
            content,
            profile.digest_dir,
            new_paper_count=0,
        )
        log.info("No new papers. Daily digest preserved at %s", path)
        return source_exit_code

    if not _validate_template_evidence(to_summarize, default_template):
        return 2

    cache_path = Path(profile.summary_cache_file)
    cache = {} if args.refresh_summaries else summary_cache.load(cache_path)
    new_cache_entries: dict[str, dict] = {}
    cache_hits = 0
    summary_failures = 0

    pairs: list[tuple[dict, str]] = []
    for i, paper in enumerate(to_summarize, 1):
        template_id = paper.get("template", default_template)
        try:
            content_fingerprint = _summary_fingerprint(paper, template_id, provider, model, profile)
        except summarizer.PdfTextExtractionError as exc:
            log.error("Failed: %s — %s", paper["canonical_id"], exc)
            summary_failures += 1
            continue
        cached = (
            None
            if args.refresh_summaries
            else summary_cache.lookup(cache, paper, content_fingerprint)
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
            summary = summarizer.summarize_paper(paper, provider, model, template_id, profile)
            new_cache_entries[
                summary_cache.cache_key(paper["canonical_id"], content_fingerprint)
            ] = summary_cache.entry(
                summary,
                content_fingerprint,
                model=model,
                provider=provider,
                template=template_id,
                generated=today_str,
            )
        except subprocess.CalledProcessError as e:
            reason = (
                (e.stderr or "").strip().splitlines()[-1] if e.stderr else f"exit {e.returncode}"
            )
            log.error("Failed: %s — %s", paper["canonical_id"], reason)
            summary_failures += 1
            continue
        except (summarizer.EvidenceError, summarizer.SummaryPipelineError) as e:
            log.error("Failed: %s — %s", paper["canonical_id"], e)
            summary_failures += 1
            continue
        except subprocess.TimeoutExpired:
            log.error("Timeout: %s", paper["canonical_id"])
            summary_failures += 1
            continue
        pairs.append((paper, summary))
        if i < len(to_summarize):
            time.sleep(1)

    if new_cache_entries:
        summary_cache.save(cache_path, new_cache_entries)
    log.info("Summaries: %d generated, %d reused from cache", len(new_cache_entries), cache_hits)

    if pairs:
        content = digest_writer.render_digest(today_str, pairs, profile)
        path = digest_writer.save_daily_digest(
            today_str,
            content,
            profile.digest_dir,
            new_paper_count=len(pairs),
        )
        log.info("Digest -> %s", path)
    elif summary_failures:
        log.error("No summaries succeeded; no digest was written")

    seen_ids = {
        merged_id
        for paper, _summary in pairs
        for merged_id in paper.get("merged_ids", [paper["canonical_id"]])
    }
    if seen_ids:
        dedup.save_seen(seen_path, seen_ids)
    log.info("Marked %d successfully summarized paper(s) as seen", len(pairs))
    if summary_failures:
        log.error("%d paper(s) remain unseen and will be retried", summary_failures)
    return 1 if source_exit_code or summary_failures else 0


def _run_related_work_profile(profile: config.ProjectProfile, args: argparse.Namespace) -> int:
    profile = _effective_profile(profile, args)
    label = profile.id or "legacy"
    cap = (
        args.max_results if args.max_results is not None else min(config.MAX_RESULTS_PER_QUERY, 200)
    )
    limit = max(1, args.limit)
    threshold = _active_threshold(profile, args)
    today_str = dt.date.today().isoformat()

    log.info("Project: %s (%s)", profile.name, label)
    log.info(
        "Related work: OpenAlex cap=%d | limit=%d | scorer=%s | threshold=%.3f",
        cap,
        limit,
        profile.relevance_scorer,
        threshold,
    )

    try:
        fetched = openalex_client.fetch_related_work(profile, cap=cap)
    except openalex_client.OpenAlexError as exc:
        log.error("OpenAlex related-work fetch failed: %s", exc)
        return 1
    log.info("OpenAlex related work fetched: %d", len(fetched))
    deduped = dedup.deduplicate_across_sources(fetched)
    log.info("After related-work dedup: %d", len(deduped))
    ranked = _rank_related_work(deduped, profile, threshold, limit)
    log.info("Related work kept: %d", len(ranked))
    summary_failures = 0

    if args.select:
        templates, default_template = _summary_template_options("abstract", args)
        to_summarize = selector.select_papers(ranked, templates, default_template)
        if not to_summarize:
            log.info("No papers selected — writing unsummarized related-work digest.")
            pairs: list[tuple[dict, str | None]] = [(p, None) for p in ranked]
        else:
            if not _validate_template_evidence(to_summarize, default_template):
                return 2
            provider, model, code = _resolve_llm(args)
            if code:
                return code
            pairs, summary_failures = _summarize_selected_related_work(
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
    if summary_failures:
        log.error("%d related-work summary or summaries failed", summary_failures)
    return 1 if summary_failures else 0


def _run_faceted_related_work_profile(
    profile: config.ProjectProfile, args: argparse.Namespace
) -> int:
    profile = _effective_profile(profile, args)
    label = profile.id or "legacy"
    limit = max(1, args.limit)
    threshold = _active_threshold(profile, args)
    today_str = dt.date.today().isoformat()

    no_summarize = bool(getattr(args, "no_summarize", False))
    if no_summarize:
        if not profile.related_work_facets:
            log.error(
                "--no-summarize with --related-work --facets requires "
                "related_work_facets in the project profile"
            )
            return 2
        provider = model = None
    else:
        provider, model, code = _resolve_llm(args)
        if code:
            return code

    log.info("Project: %s (%s)", profile.name, label)
    log.info(
        "Faceted related work: facet_count=%d | facet_candidates=%d | limit=%d "
        "| scorer=%s | threshold=%.3f",
        args.facet_count,
        args.facet_candidates,
        limit,
        profile.relevance_scorer,
        threshold,
    )

    try:
        facets = (
            list(profile.related_work_facets)
            if no_summarize
            else related_work.generate_facets(profile, provider, model, args.facet_count)
        )
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
        if no_summarize:
            annotated = related_work.annotate_candidates_locally(ranked, profile)
        else:
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
    except openalex_client.OpenAlexError as e:
        log.error("OpenAlex related-work fetch failed: %s", e)
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
    texts = [f"{p.get('title', '')}. {p.get('abstract', '')}".strip() for p in papers]
    scores = relevance.score_texts(profile.topic_statement, texts, **_score_kwargs(profile))
    max_citations = max(1, max(int(p.get("cited_by_count") or 0) for p in papers))
    kept: list[dict] = []
    for paper, score in zip(papers, scores, strict=True):
        rel_score = score.final_score
        citations = int(paper.get("cited_by_count") or 0)
        citation_score = math.log1p(citations) / math.log1p(max_citations)
        discovery_sources = set(paper.get("discovery_sources") or [])
        channel_bonus = min(max(len(discovery_sources) - 1, 0), 2) * 0.03
        semantic_bonus = 0.03 if "semantic" in discovery_sources else 0.0
        relevance.annotate_score_fields(paper, score)
        paper["related_work_score"] = (
            (0.70 * rel_score) + (0.24 * citation_score) + channel_bonus + semantic_bonus
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
) -> tuple[list[tuple[dict, str | None]], int]:
    _templates, default_template = _summary_template_options("abstract", args)
    cache_path = Path(profile.summary_cache_file)
    cache = {} if args.refresh_summaries else summary_cache.load(cache_path)
    new_cache_entries: dict[str, dict] = {}
    pairs: list[tuple[dict, str | None]] = []
    failures = 0
    for i, paper in enumerate(to_summarize, 1):
        template_id = paper.get("template", default_template)
        try:
            content_fingerprint = _summary_fingerprint(paper, template_id, provider, model, profile)
        except summarizer.PdfTextExtractionError as exc:
            log.error("Failed: %s — %s", paper["canonical_id"], exc)
            pairs.append((paper, f'_"(summary failed: {exc})"_'))
            failures += 1
            continue
        cached = (
            None
            if args.refresh_summaries
            else summary_cache.lookup(cache, paper, content_fingerprint)
        )
        if cached is not None:
            log.info(
                "Cached [%d/%d] (%s) %s", i, len(to_summarize), template_id, paper["title"][:60]
            )
            pairs.append((paper, cached))
            continue
        log.info(
            "Summarizing [%d/%d] (%s) %s", i, len(to_summarize), template_id, paper["title"][:60]
        )
        try:
            summary = summarizer.summarize_paper(paper, provider, model, template_id, profile)
            new_cache_entries[
                summary_cache.cache_key(paper["canonical_id"], content_fingerprint)
            ] = summary_cache.entry(
                summary,
                content_fingerprint,
                model=model,
                provider=provider,
                template=template_id,
                generated=today_str,
            )
        except subprocess.CalledProcessError as e:
            reason = (
                (e.stderr or "").strip().splitlines()[-1] if e.stderr else f"exit {e.returncode}"
            )
            log.error("Failed: %s — %s", paper["canonical_id"], reason)
            summary = f'_"(summary failed: {reason})"_'
            failures += 1
        except (summarizer.EvidenceError, summarizer.SummaryPipelineError) as e:
            log.error("Failed: %s — %s", paper["canonical_id"], e)
            summary = f'_"(summary failed: {e})"_'
            failures += 1
        except subprocess.TimeoutExpired:
            log.error("Timeout: %s", paper["canonical_id"])
            summary = '_"(summary failed: timeout)"_'
            failures += 1
        pairs.append((paper, summary))
        if i < len(to_summarize):
            time.sleep(1)
    if new_cache_entries:
        summary_cache.save(cache_path, new_cache_entries)
    return pairs, failures


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

    templates, default_template = _summary_template_options("fulltext", args)
    if getattr(args, "select", False):
        papers = selector.select_papers(papers, templates, default_template)
    else:
        for paper in papers:
            paper["template"] = default_template

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

    if not _validate_template_evidence(papers, default_template):
        return 2

    provider, model, code = _resolve_llm(args)
    if code:
        return code

    pairs, summary_failures = _summarize_zotero_papers(
        papers, args, profile, provider, model, today_str
    )
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
    if summary_failures:
        log.error("%d Zotero summary or summaries failed", summary_failures)
    return 1 if summary_failures else 0


def _summarize_zotero_papers(
    papers: list[dict],
    args: argparse.Namespace,
    profile: config.ProjectProfile,
    provider: str,
    model: str,
    today_str: str,
) -> tuple[list[tuple[dict, str]], int]:
    _templates, default_template = _summary_template_options("fulltext", args)
    cache_path = Path(profile.summary_cache_file)
    cache = {} if args.refresh_summaries else summary_cache.load(cache_path)
    new_cache_entries: dict[str, dict] = {}
    pairs: list[tuple[dict, str]] = []
    failures = 0

    for i, paper in enumerate(papers, 1):
        template_id = paper.get("template", default_template)
        try:
            content_fingerprint = _summary_fingerprint(paper, template_id, provider, model, profile)
        except summarizer.PdfTextExtractionError as exc:
            log.error("Failed: %s — %s", paper["canonical_id"], exc)
            pairs.append((paper, f'_"(summary failed: {exc})"_'))
            failures += 1
            continue
        cached = (
            None
            if args.refresh_summaries
            else summary_cache.lookup(cache, paper, content_fingerprint)
        )
        if cached is not None:
            log.info("Cached [%d/%d] (%s) %s", i, len(papers), template_id, paper["title"][:60])
            pairs.append((paper, cached))
            continue

        pdf_path = Path(paper["pdf_path"])
        log.info(
            "Summarizing PDF [%d/%d] (%s) %s", i, len(papers), template_id, paper["title"][:60]
        )
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
                summary_cache.cache_key(paper["canonical_id"], content_fingerprint)
            ] = summary_cache.entry(
                summary,
                content_fingerprint,
                model=model,
                provider=provider,
                template=template_id,
                pdf_path=str(pdf_path),
                generated=today_str,
            )
        except subprocess.CalledProcessError as e:
            reason = (
                (e.stderr or "").strip().splitlines()[-1] if e.stderr else f"exit {e.returncode}"
            )
            log.error("Failed: %s — %s", paper["canonical_id"], reason)
            summary = f'_"(summary failed: {reason})"_'
            failures += 1
        except (summarizer.EvidenceError, summarizer.SummaryPipelineError) as e:
            log.error("Failed: %s — %s", paper["canonical_id"], e)
            summary = f'_"(summary failed: {e})"_'
            failures += 1
        except subprocess.TimeoutExpired:
            log.error("Timeout: %s", paper["canonical_id"])
            summary = '_"(summary failed: timeout)"_'
            failures += 1
        pairs.append((paper, summary))
        if i < len(papers):
            time.sleep(1)

    if new_cache_entries:
        summary_cache.save(cache_path, new_cache_entries)
    return pairs, failures


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

    if args.list_templates:
        try:
            return _list_templates()
        except config.ConfigError as exc:
            log.error(str(exc))
            return 2

    if args.list_zotero_collections:
        return _list_zotero_collections()

    code = _validate_args(args)
    if code:
        return code

    template_override, code = _resolve_template_override(args)
    if code:
        return code
    args.template_override = template_override

    if args.zotero_collection and args.related_work:
        log.error("--zotero-collection cannot be combined with --related-work")
        return 2

    templates_required = bool(
        args.zotero_collection
        or args.select
        or template_override
        or (not args.no_summarize and not args.related_work)
    )
    if templates_required:
        try:
            config.summary_template_catalog()
            if template_override:
                template = config.summary_template(template_override)
                # Each mode offers one evidence type, so a mismatched --template
                # is a mode mistake, not a per-paper one. Say so once here rather
                # than letting _validate_template_evidence repeat itself for
                # every paper in the run.
                wanted = "fulltext" if args.zotero_collection else "abstract"
                if template.evidence != wanted:
                    hint = (
                        "Full-text templates read a saved PDF — use "
                        "--zotero-collection to run them over a collection."
                        if template.evidence == "fulltext"
                        else "Abstract templates are for discovery runs — drop "
                        "--zotero-collection to use one."
                    )
                    log.error(
                        "Template %r needs %s evidence, but this run supplies %s. %s",
                        template_override,
                        template.evidence,
                        wanted,
                        hint,
                    )
                    return 2
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
    bold = "\033[1m" if use_color else ""
    dim = "\033[2m" if use_color else ""
    cyan = "\033[36m" if use_color else ""
    green = "\033[32m" if use_color else ""
    yellow = "\033[33m" if use_color else ""
    red = "\033[31m" if use_color else ""
    reset = "\033[0m" if use_color else ""

    if profile:
        print(f"\n# {profile.name}")

    if not papers:
        print(f"{dim}(no papers matched){reset}")
        return

    for p in sorted(papers, key=lambda x: -(x.get("relevance_score") or 0)):
        score = p.get("relevance_score") or 0.0
        if score >= 0.75:
            score_color = green
        elif score >= 0.65:
            score_color = cyan
        elif score >= 0.55:
            score_color = yellow
        else:
            score_color = red

        venue = p.get("venue")
        container = p.get("container_title")
        if venue:
            title_suffix = f"  {cyan}★ {venue}{reset}"
        elif container:
            title_suffix = f"  {cyan}{container}{reset}"
        else:
            title_suffix = ""
        published = p.get("published") or "?"
        url = p.get("url") or ""
        venue_meta = container or venue or "—"

        print()
        print(f"  {score_color}{score:.3f}{reset}  {bold}{p['title']}{reset}{title_suffix}")
        print(f"        {dim}{p['source']} · {venue_meta} · {published} · {url}{reset}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
