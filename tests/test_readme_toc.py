"""Keep README.md's table of contents honest.

The TOC is generated HTML, so the failure mode is adding a heading and
forgetting to regenerate — which nothing else would catch until a reader
clicked a link that was never there.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "update_toc.py"


def test_the_table_of_contents_matches_the_headings():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"{result.stdout}{result.stderr}"
        "\nRun: uv run python scripts/update_toc.py"
    )


def test_every_table_of_contents_link_points_at_a_real_heading():
    """Guards the slug rules, which differ from 'lowercase and hyphenate'."""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import update_toc
    finally:
        sys.path.pop(0)

    lines = (REPO_ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    seen: dict[str, int] = {}
    anchors = {update_toc._slug(text, seen) for _, text in update_toc._headings(lines)}

    import re

    links = set(re.findall(r'<a href="#([^"]+)">', "\n".join(lines)))
    links |= set(re.findall(r"\]\(#([^)]+)\)", "\n".join(lines)))

    assert links, "no internal links found — the check would pass vacuously"
    assert not (links - anchors), f"dangling anchors: {sorted(links - anchors)}"
