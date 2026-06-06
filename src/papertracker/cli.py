"""`papertracker` console entry point."""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import config, dedup, digest_writer, relevance, selector, settings, summarizer, summary_cache
from .sources import acm_client, arxiv_client, ieee_client, journal_rss

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
        default=",".join(config.ENABLED_SOURCES_DEFAULT),
        help=(
            "Comma-separated source list. "
            f"Available: {', '.join(SOURCE_FETCHERS)}"
        ),
    )
    p.add_argument(
        "--priority-venues-only", action="store_true",
        help="Drop papers not matching any PRIORITY_VENUES entry.",
    )
    p.add_argument(
        "--threshold", type=float, default=None,
        help=(
            "Cosine-similarity threshold for the embedding relevance filter "
            f"(default {config.RELEVANCE_THRESHOLD}). Lower = looser, higher = stricter."
        ),
    )
    p.add_argument(
        "--ignore-seen", action="store_true",
        help="Re-summarize papers already in .seen_papers.json (useful for backfill).",
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


def _fetch_all(sources: list[str], start: dt.date, end: dt.date) -> list[dict]:
    futures = {}
    with ThreadPoolExecutor(max_workers=max(len(sources), 1)) as ex:
        for name in sources:
            fetcher = SOURCE_FETCHERS.get(name)
            if fetcher is None:
                log.warning("Unknown source %r — skipping", name)
                continue
            futures[ex.submit(fetcher, start_date=start, end_date=end)] = name

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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.verbose)

    # Apply CLI override for priority-venue gate (purely additive)
    if args.priority_venues_only:
        config.PRIORITY_VENUE_ONLY = True

    # Apply CLI override for the per-source result cap
    if args.max_results is not None:
        config.MAX_RESULTS_PER_QUERY = args.max_results

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

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    log.info(
        "Sources: %s | window=%s..%s | cap=%d/source",
        ", ".join(sources), start_date, end_date, config.MAX_RESULTS_PER_QUERY,
    )

    fetched = _fetch_all(sources, start_date, end_date)
    log.info("Total fetched (pre-dedup): %d", len(fetched))

    deduped = dedup.deduplicate_across_sources(fetched)
    log.info("After cross-source dedup: %d", len(deduped))

    threshold = args.threshold if args.threshold is not None else config.RELEVANCE_THRESHOLD
    relevant = relevance.filter_papers(deduped, threshold=threshold)

    seen_path = Path(config.SEEN_PAPERS_FILE)
    seen = set() if args.ignore_seen else dedup.load_seen(seen_path)
    new_papers = [
        p for p in relevant
        if not (seen & set(p.get("merged_ids", [p["canonical_id"]])))
    ]
    log.info("New (unseen) papers: %d", len(new_papers))

    today_str = dt.date.today().isoformat()

    if args.select:
        to_summarize = selector.select_papers(new_papers)
        if not to_summarize:
            log.info("No papers selected — nothing summarized.")
            return 0
        log.info("Selected %d of %d paper(s) to summarize", len(to_summarize), len(new_papers))
        provider, model, code = _resolve_llm(args)
        if code:
            return code
    elif args.no_summarize:
        _print_paper_list(new_papers)
        return 0
    else:
        to_summarize = new_papers
        for p in to_summarize:
            p.setdefault("mode", "triage")

    if not to_summarize:
        content = digest_writer.render_empty_digest(today_str)
        path = digest_writer.save_digest(today_str, content, config.DIGEST_DIR)
        log.info("No new papers. Empty digest -> %s", path)
        return 0

    cache_path = Path(config.SUMMARY_CACHE_FILE)
    cache = {} if args.refresh_summaries else summary_cache.load(cache_path)
    new_cache_entries: dict[str, dict] = {}
    cache_hits = 0

    pairs: list[tuple[dict, str]] = []
    for i, paper in enumerate(to_summarize, 1):
        mode = paper.get("mode", "triage")
        cached = None if args.refresh_summaries else summary_cache.lookup(cache, paper, mode)
        if cached is not None:
            cache_hits += 1
            log.info("Cached [%d/%d] (%s) %s", i, len(to_summarize), mode, paper["title"][:60])
            pairs.append((paper, cached))
            continue

        log.info("Summarizing [%d/%d] (%s) %s", i, len(to_summarize), mode, paper["title"][:60])
        try:
            summary = summarizer.summarize_paper(paper, provider, model, mode)
            new_cache_entries[summary_cache.cache_key(paper["canonical_id"], mode)] = {
                "summary": summary, "model": model,
                "provider": provider, "mode": mode, "generated": today_str,
            }
        except subprocess.CalledProcessError as e:
            reason = (e.stderr or "").strip().splitlines()[-1] if e.stderr else f"exit {e.returncode}"
            log.error("Failed: %s — %s", paper["canonical_id"], reason)
            summary = f'_"(summary failed: {reason})"_'
        except subprocess.TimeoutExpired:
            log.error("Timeout: %s", paper["canonical_id"])
            summary = '_"(summary failed: timeout)"_'
        pairs.append((paper, summary))
        if i < len(to_summarize):
            time.sleep(1)

    if new_cache_entries:
        summary_cache.save(cache_path, new_cache_entries)
    log.info("Summaries: %d generated, %d reused from cache", len(new_cache_entries), cache_hits)

    content = digest_writer.render_digest(today_str, pairs)
    path = digest_writer.save_digest(today_str, content, config.DIGEST_DIR)
    log.info("Digest -> %s", path)

    seen_ids = {mid for p in to_summarize for mid in p.get("merged_ids", [p["canonical_id"]])}
    dedup.save_seen(seen_path, seen_ids)
    log.info("Marked %d new paper(s) as seen", len(to_summarize))
    return 0


def _print_paper_list(papers: list[dict]) -> None:
    """Pretty-print the no-summarize paper list with bold titles and dim metadata."""
    use_color = sys.stdout.isatty()
    BOLD   = "\033[1m"  if use_color else ""
    DIM    = "\033[2m"  if use_color else ""
    CYAN   = "\033[36m" if use_color else ""
    GREEN  = "\033[32m" if use_color else ""
    YELLOW = "\033[33m" if use_color else ""
    RED    = "\033[31m" if use_color else ""
    RESET  = "\033[0m"  if use_color else ""

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
