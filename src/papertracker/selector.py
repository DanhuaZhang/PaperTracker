"""Interactive terminal selection of which papers to summarize.

Renders a checkbox list styled to match ``cli._print_paper_list`` — same
score-color palette, bold title, dim metadata. Uses POSIX raw-mode for a live
↑/↓ + space UI; falls back to a numbered text prompt when stdin/stdout is not a
TTY (pipes, CI). No third-party dependencies.
"""
from __future__ import annotations

import select as _select
import shutil
import sys

# ANSI palette — mirrors cli._print_paper_list so the two views look identical.
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
UL_ON = "\033[4m"
UL_OFF = "\033[24m"
RESET = "\033[0m"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"


def _score_color(score: float) -> str:
    """Same thresholds as cli._print_paper_list."""
    if score >= 0.75:
        return GREEN
    if score >= 0.65:
        return CYAN
    if score >= 0.55:
        return YELLOW
    return RED


def _ordered(papers: list[dict]) -> list[dict]:
    return sorted(papers, key=lambda x: -(x.get("relevance_score") or 0))


def _meta(paper: dict) -> str:
    source = paper.get("source") or "?"
    venue = paper.get("container_title") or paper.get("venue") or ""
    published = paper.get("published") or "?"
    return f"{source} · {venue} · {published}" if venue else f"{source} · {published}"


def select_papers(papers: list[dict]) -> list[dict]:
    """Return the subset the user checks, in relevance-sorted order."""
    if not papers:
        return []
    ordered = _ordered(papers)
    if sys.stdin.isatty() and sys.stdout.isatty():
        return _select_interactive(ordered)
    return _select_fallback(ordered)


# --------------------------------------------------------------------------- #
# Interactive (raw-mode) path
# --------------------------------------------------------------------------- #

def _select_interactive(ordered: list[dict]) -> list[dict]:
    import termios
    import tty

    selected = [False] * len(ordered)
    cursor = 0
    n = len(ordered)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sys.stdout.write(HIDE_CURSOR)
    prev_lines = 0
    try:
        tty.setraw(fd)
        while True:
            prev_lines = _render(ordered, selected, cursor, prev_lines)
            key = _read_key()
            if key in ("up", "k"):
                cursor = (cursor - 1) % n
            elif key in ("down", "j"):
                cursor = (cursor + 1) % n
            elif key == "space":
                selected[cursor] = not selected[cursor]
            elif key == "a":
                fill = not all(selected)
                selected = [fill] * n
            elif key == "enter":
                break
            elif key in ("q", "esc", "cancel"):
                selected = [False] * n
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(SHOW_CURSOR + "\r\n")
        sys.stdout.flush()

    return [p for p, s in zip(ordered, selected) if s]


def _read_key() -> str:
    ch = sys.stdin.read(1)
    if ch == "\x1b":  # escape — could be a bare Esc or an arrow sequence
        ready, _, _ = _select.select([sys.stdin], [], [], 0.05)
        if not ready:
            return "esc"
        if sys.stdin.read(1) == "[":
            return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(
                sys.stdin.read(1), ""
            )
        return "esc"
    if ch in ("\r", "\n"):
        return "enter"
    if ch == " ":
        return "space"
    if ch == "\x03":  # Ctrl-C — treat as cancel (raw mode swallows SIGINT)
        return "cancel"
    return ch.lower()


def _render(ordered: list[dict], selected: list[bool], cursor: int, prev_lines: int) -> int:
    cols, rows = shutil.get_terminal_size((80, 24))
    header = [
        f"{BOLD}Select papers to summarize{RESET}  "
        f"{DIM}(↑↓ move · space toggle · a all · enter confirm · q cancel){RESET}",
        "",
    ]
    footer = ["", f"{DIM}{sum(selected)}/{len(ordered)} selected{RESET}"]

    # Reserve 2 lines for the "… more" markers so a scrolling list still fits.
    avail = max(rows - len(header) - len(footer) - 2, 3)
    total = len(ordered)
    if total <= avail:
        start, end = 0, total
    else:
        half = avail // 2
        start = max(0, min(cursor - half, total - avail))
        end = start + avail

    body: list[str] = []
    if start > 0:
        body.append(f"{DIM}  … ({start} more above){RESET}")
    for i in range(start, end):
        body.append(_row(ordered[i], selected[i], i == cursor, cols))
    if end < total:
        body.append(f"{DIM}  … ({total - end} more below){RESET}")

    lines = header + body + footer
    out = []
    if prev_lines > 1:
        out.append(f"\033[{prev_lines - 1}A")
    out.append("\r\033[J")  # column 0, clear to end of screen
    out.append("\r\n".join(lines))
    sys.stdout.write("".join(out))
    sys.stdout.flush()
    return len(lines)


def _row(paper: dict, checked: bool, active: bool, cols: int) -> str:
    score = paper.get("relevance_score") or 0.0
    title = paper.get("title") or "(untitled)"
    meta = _meta(paper)

    cur = "❯ " if active else "  "
    box = f"{GREEN}[x]{RESET}" if checked else "[ ]"
    # Visible width of the fixed left part: cursor(2) + box(3) + " "(1) + score(5) + "  "(2)
    fixed = 2 + 3 + 1 + 5 + 2
    budget = cols - fixed - len(meta) - 3
    if budget < 12:
        budget = 12
    if len(title) > budget:
        title = title[: budget - 1] + "…"

    shown_title = f"{UL_ON}{title}{UL_OFF}" if active else title
    sc = _score_color(score)
    return (
        f"{cur}{box} {sc}{score:.3f}{RESET}  "
        f"{BOLD}{shown_title}{RESET}  {DIM}{meta}{RESET}"
    )


# --------------------------------------------------------------------------- #
# Non-TTY fallback
# --------------------------------------------------------------------------- #

def _select_fallback(ordered: list[dict]) -> list[dict]:
    use_color = sys.stdout.isatty()
    bold = BOLD if use_color else ""
    dim = DIM if use_color else ""
    reset = RESET if use_color else ""

    for i, p in enumerate(ordered, 1):
        score = p.get("relevance_score") or 0.0
        sc = _score_color(score) if use_color else ""
        print(
            f"  [{i:>2}] {sc}{score:.3f}{reset}  {bold}{p.get('title') or '(untitled)'}{reset}"
            f"  {dim}{_meta(p)}{reset}"
        )
    try:
        raw = input("Pick papers to summarize (e.g. 1,3 or 1-3, 'a'=all, enter=none): ")
    except EOFError:
        raw = ""
    idx = _parse_selection(raw, len(ordered))
    return [ordered[i] for i in idx]


def _parse_selection(raw: str, n: int) -> list[int]:
    """Parse '1,3', '1-3', 'a'/'all', '' into a sorted list of 0-based indices."""
    raw = raw.strip().lower()
    if not raw:
        return []
    if raw in ("a", "all"):
        return list(range(n))
    chosen: set[int] = set()
    for tok in raw.replace(" ", "").split(","):
        if not tok:
            continue
        if "-" in tok:
            lo, _, hi = tok.partition("-")
            if lo.isdigit() and hi.isdigit():
                for v in range(int(lo), int(hi) + 1):
                    if 1 <= v <= n:
                        chosen.add(v - 1)
        elif tok.isdigit():
            v = int(tok)
            if 1 <= v <= n:
                chosen.add(v - 1)
    return sorted(chosen)
