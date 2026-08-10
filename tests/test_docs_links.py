"""Keep the documentation navigable.

The manual is split across README.md and docs/*.md with relative links between
them, so the failure mode is a link that quietly stops resolving — a renamed
heading, a moved page, a screenshot that was never committed. None of that
shows up until a reader clicks it, which is exactly the kind of rot a test
should catch instead.
"""
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "update_toc.py"

sys.path.insert(0, str(SCRIPT.parent))
import update_toc  # noqa: E402
sys.path.pop(0)

# Anything with a scheme, or a bare fragment, is not a repo path.
EXTERNAL = re.compile(r"^(https?:|mailto:|#)")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# Leading whitespace matters: a fence nested in a list item is indented, and
# anchoring at column zero would miss it and treat its contents as prose.
FENCE = re.compile(r"^[ \t]*```", re.MULTILINE)


def _pages() -> list[Path]:
    return [
        REPO_ROOT / "README.md",
        REPO_ROOT / "CONTRIBUTING.md",
        *sorted((REPO_ROOT / "docs").rglob("*.md")),
    ]


@lru_cache(maxsize=1)
def _tracked() -> tuple[frozenset[str], frozenset[str]]:
    """Return (tracked files, directories containing them), repo-relative.

    Link targets are checked against git rather than the filesystem on purpose.
    A link to a gitignored path — `user_data/projects.toml`, say — resolves
    fine on the machine of whoever wrote it and is broken for every reader who
    has not set the tool up yet. Testing existence on disk would only catch
    that in CI, which is the slowest possible place to learn it.
    """
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=REPO_ROOT, check=True
    ).stdout.split()
    dirs = {parent.as_posix() for f in out for parent in Path(f).parents}
    return frozenset(out), frozenset(dirs)


def _visible(text: str) -> str:
    """Strip what a reader never clicks: code blocks and HTML comments.

    Commented-out blocks matter here — screenshot slots ship as comments
    holding a ready-to-paste <img> for an image that does not exist yet, and
    those must not count as broken references.
    """
    parts = FENCE.split(text)
    # Alternating: outside, inside, outside... keep only the even indices.
    outside = "".join(parts[::2])
    return COMMENT.sub("", outside)


def _anchors(path: Path) -> set[str]:
    """Every in-page anchor GitHub will generate for this file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: dict[str, int] = {}
    return {update_toc._slug(text, seen) for _, text in update_toc._headings(lines)}


def _links(path: Path) -> list[str]:
    """Every repo-relative target this page points at."""
    text = _visible(path.read_text(encoding="utf-8"))
    found = re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", text)
    found += re.findall(r'<a\s+href="([^"]+)"', text)
    found += re.findall(r'<img\s[^>]*src="([^"]+)"', text)
    return found


@pytest.mark.parametrize("page", _pages(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_in_page_anchor_resolves(page):
    anchors = _anchors(page)
    broken = [
        target
        for target in _links(page)
        if target.startswith("#") and target[1:] not in anchors
    ]
    where = page.relative_to(REPO_ROOT)
    assert not broken, f"{where} links to headings it does not have: {broken}"


@pytest.mark.parametrize("page", _pages(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_cross_page_link_resolves(page):
    files, dirs = _tracked()
    problems = []
    for target in _links(page):
        if EXTERNAL.match(target):
            continue
        rel, _, fragment = target.partition("#")
        if not rel:
            continue
        destination = (page.parent / rel).resolve()
        key = destination.relative_to(REPO_ROOT).as_posix()
        if key not in files and key not in dirs:
            hint = " (exists but is not tracked)" if destination.exists() else ""
            problems.append(f"{target} → not in the repository{hint}")
            continue
        # A fragment is only checkable when the destination is Markdown.
        if fragment and destination.suffix == ".md":
            if fragment not in _anchors(destination):
                problems.append(f"{target} → {destination.name} has no such heading")
    assert not problems, f"{page.relative_to(REPO_ROOT)}: {problems}"


def test_every_referenced_image_is_committed():
    """A screenshot referenced but never added renders as a broken image."""
    tracked, _ = _tracked()

    problems = []
    for page in _pages():
        for target in _links(page):
            if EXTERNAL.match(target) or not re.search(
                r"\.(png|jpg|jpeg|gif|webp|svg)$", target, re.IGNORECASE
            ):
                continue
            path = (page.parent / target).resolve()
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel not in tracked:
                problems.append(f"{page.relative_to(REPO_ROOT)} → {target} is not committed")
    assert not problems, problems


def test_the_tables_of_contents_are_current():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"{result.stdout}{result.stderr}\n"
        "Run: uv run python scripts/update_toc.py"
    )


def test_the_docs_index_lists_every_page():
    """A page nobody links to is a page nobody finds."""
    index = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    linked = set(re.findall(r"\]\(([a-z0-9-]+\.md)\)", index))
    actual = {
        p.name
        for p in (REPO_ROOT / "docs").glob("*.md")
        if p.name != "README.md"
    }
    assert not (actual - linked), f"not listed in docs/README.md: {sorted(actual - linked)}"
