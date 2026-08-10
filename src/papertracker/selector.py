"""Interactive selection of which papers to summarize.

The primary UI is a small HTML page served from a localhost-only HTTP server:
titles wrap in full, abstracts are visible, and clicking a card toggles it. The
browser POSTs the chosen papers back to the waiting process. When stdin is not a
TTY (pipes, CI) it falls back to a numbered text prompt. No third-party deps.
"""
from __future__ import annotations

import html
import http.server
from pathlib import Path
import sys
import webbrowser
from urllib.parse import parse_qs

from . import summary_templates

# ANSI palette for the text fallback — mirrors cli._print_paper_list.
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


class SelectionError(ValueError):
    """Raised when a submitted summary template ID is not available."""


def _score_color(score: float) -> str:
    """ANSI color for the text fallback (same thresholds as the digest)."""
    if score >= 0.75:
        return GREEN
    if score >= 0.65:
        return CYAN
    if score >= 0.55:
        return YELLOW
    return RED


def _score_hex(score: float) -> str:
    """Badge color for the HTML UI, mirroring _score_color's thresholds."""
    if score >= 0.75:
        return "#3fb950"  # green
    if score >= 0.65:
        return "#39c5cf"  # cyan
    if score >= 0.55:
        return "#d29922"  # yellow
    return "#f85149"      # red


def _ordered(papers: list[dict]) -> list[dict]:
    return sorted(papers, key=lambda x: -(x.get("relevance_score") or 0))


def _meta(paper: dict) -> str:
    source = paper.get("source") or "?"
    venue = paper.get("container_title") or paper.get("venue") or ""
    published = paper.get("published") or "?"
    return f"{source} · {venue} · {published}" if venue else f"{source} · {published}"


def select_papers(
    papers: list[dict],
    templates: list[summary_templates.SummaryTemplate] | tuple[summary_templates.SummaryTemplate, ...],
    default_template: str,
) -> list[dict]:
    """Return the subset the user picks, in relevance-sorted order."""
    if not papers:
        return []
    ordered = _ordered(papers)
    if sys.stdin.isatty():
        try:
            return _select_html(ordered, templates, default_template)
        except Exception as e:  # noqa: BLE001 — any UI failure degrades to text
            print(f"  (browser selector unavailable: {e}; falling back to text)")
            return _select_fallback(ordered, templates, default_template)
    return _select_fallback(ordered, templates, default_template)


def select_related_work_candidates(papers: list[dict], facets: list) -> list[dict]:
    """Return approved related-work candidates with facet/role edits."""
    if not papers:
        return []
    ordered = sorted(papers, key=lambda x: -(x.get("related_work_score") or 0))
    if sys.stdin.isatty():
        try:
            return _select_related_html(ordered, facets)
        except Exception as e:  # noqa: BLE001 — any UI failure degrades to text
            print(f"  (browser selector unavailable: {e}; falling back to text)")
            return _select_related_fallback(ordered)
    return _select_related_fallback(ordered)


# --------------------------------------------------------------------------- #
# HTML (localhost server) path
# --------------------------------------------------------------------------- #

def _selections_from_form(
    form: dict[str, list[str]],
    n: int,
    templates,
    default_template: str,
    papers: list[dict] | None = None,
) -> list[tuple[int, str]]:
    """Map a parsed POST form to sorted (index, template ID) pairs."""
    if "cancel" in form:
        return []
    normalized = _template_objects(templates)
    by_id = {template.id: template for template in normalized}
    out: list[tuple[int, str]] = []
    for v in form.get("sel", []):
        if not v.isdigit():
            continue
        i = int(v)
        if not (0 <= i < n):
            continue
        template_id = form.get(f"template_{i}", [default_template])[0].strip()
        if template_id not in by_id:
            raise SelectionError(f"Unknown summary template {template_id!r}")
        if papers is not None:
            compatible, reason = _compatibility(by_id[template_id], papers[i])
            if not compatible:
                raise SelectionError(
                    f"Template {template_id!r} is incompatible with paper {i + 1}: {reason}"
                )
        out.append((i, template_id))
    return sorted(out)


def _make_server(
    ordered: list[dict],
    page: str,
    templates,
    default_template: str,
):
    """Build (but don't run) a localhost server. Returns (httpd, result).

    `result["selected"]` stays None until the browser POSTs, then becomes the
    chosen index list.
    """
    n = len(ordered)
    result: dict[str, list[tuple[int, str]] | None] = {"selected": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence per-request logging
            pass

        def _send(self, body: str, status: int = 200):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(page)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            try:
                result["selected"] = _selections_from_form(
                    form, n, templates, default_template, ordered
                )
            except SelectionError as exc:
                self._send(html.escape(str(exc)), status=400)
                return
            self._send(_done_html(len(result["selected"])))

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    return httpd, result


def _make_related_server(ordered: list[dict], facets: list, page: str):
    n = len(ordered)
    facet_ids = {facet.id for facet in facets}
    roles = {
        "foundational",
        "method",
        "benchmark",
        "system",
        "application",
        "contrast",
        "recent",
        "background",
    }
    result: dict[str, list[dict] | None] = {"selected": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, body: str):
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(page)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            if "cancel" in form:
                result["selected"] = []
            else:
                selected = []
                for value in form.get("sel", []):
                    if not value.isdigit():
                        continue
                    i = int(value)
                    if not (0 <= i < n):
                        continue
                    facet_id = form.get(f"facet_{i}", [ordered[i].get("primary_facet") or ""])[0]
                    role = form.get(f"role_{i}", [ordered[i].get("role") or "background"])[0]
                    if facet_id not in facet_ids:
                        facet_id = ordered[i].get("primary_facet") or next(iter(facet_ids), "")
                    if role not in roles:
                        role = "background"
                    selected.append(
                        {
                            "canonical_id": ordered[i].get("canonical_id"),
                            "primary_facet": facet_id,
                            "role": role,
                        }
                    )
                result["selected"] = selected
            self._send(_done_html(len(result["selected"])))

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    return httpd, result


def _select_html(
    ordered: list[dict], templates, default_template: str
) -> list[dict]:
    page = _render_html(ordered, templates, default_template)
    httpd, result = _make_server(ordered, page, templates, default_template)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"  Opening paper selector in your browser: {url}")
    print("  Pick papers there and click “Summarize selected” (or Ctrl-C to cancel).")
    webbrowser.open(url)
    try:
        while result["selected"] is None:
            httpd.handle_request()
    except KeyboardInterrupt:
        result["selected"] = []
        print("\n  Selection cancelled.")
    finally:
        httpd.server_close()
    out = []
    for i, template_id in (result["selected"] or []):
        paper = dict(ordered[i])
        paper["template"] = template_id
        out.append(paper)
    return out


def _select_related_html(ordered: list[dict], facets: list) -> list[dict]:
    page = _render_related_html(ordered, facets)
    httpd, result = _make_related_server(ordered, facets, page)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"  Opening related-work selector in your browser: {url}")
    print("  Approve final inclusions there and click “Save selection” (or Ctrl-C to cancel).")
    webbrowser.open(url)
    try:
        while result["selected"] is None:
            httpd.handle_request()
    except KeyboardInterrupt:
        result["selected"] = []
        print("\n  Selection cancelled.")
    finally:
        httpd.server_close()
    return result["selected"] or []


_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
     background:#0d1117;color:#e6edf3}
header{position:sticky;top:0;z-index:10;background:#161b22;border-bottom:1px solid #30363d;
       padding:14px 20px}
h1{margin:0 0 10px;font-size:18px;font-weight:600}
.toolbar{display:flex;align-items:center;gap:10px}
.toolbar .spacer{flex:1}
button{font:inherit;padding:7px 14px;border-radius:6px;border:1px solid #30363d;
       background:#21262d;color:#e6edf3;cursor:pointer}
button:hover{border-color:#8b949e}
button.go{background:#238636;border-color:#2ea043;font-weight:600}
button.go:hover{background:#2ea043}
button.cancel{background:transparent}
.count{color:#8b949e;font-variant-numeric:tabular-nums}
main{max-width:900px;margin:0 auto;padding:18px 20px 60px;display:flex;flex-direction:column;gap:12px}
.card{display:flex;gap:12px;padding:14px 16px;border:1px solid #30363d;border-radius:10px;
      background:#161b22;cursor:pointer;align-items:flex-start}
.card:hover{border-color:#8b949e}
.card:has(input:checked){border-color:#2ea043;background:#0f2419}
.card input{margin-top:3px;width:18px;height:18px;flex:none;cursor:pointer}
.pick{display:flex;flex-direction:column;gap:6px;align-items:center;flex:none}
.select-control{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:5px;font:inherit;font-size:12px;padding:4px 6px;cursor:pointer;max-width:340px}
.body{flex:1;min-width:0}
.title{font-size:16px;font-weight:600;line-height:1.35}
.meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;color:#8b949e;font-size:13px;margin-top:5px}
.score{font-weight:700;color:#0d1117;border-radius:5px;padding:1px 7px;font-size:13px;
       font-variant-numeric:tabular-nums}
details{margin-top:8px}
summary{width:max-content;cursor:pointer;color:#8b949e;font-size:13px;list-style-position:inside}
summary:hover{color:#e6edf3}
.abstract{color:#c9d1d9;font-size:13.5px;margin-top:6px;max-height:200px;overflow:auto;
          white-space:pre-wrap;border-left:2px solid #30363d;padding-left:10px}
.link{display:inline-block;margin-top:8px;color:#58a6ff;text-decoration:none;font-size:13px}
.link:hover{text-decoration:underline}
"""

_SCRIPT = """
const boxes = () => Array.from(document.querySelectorAll('input[name=sel]'));
function updateCount(){
  const n = boxes().filter(b => b.checked).length;
  document.getElementById('count').textContent = n + ' selected';
}
document.getElementById('all').onclick = () => { boxes().forEach(b => b.checked = true); updateCount(); };
document.getElementById('none').onclick = () => { boxes().forEach(b => b.checked = false); updateCount(); };
document.addEventListener('change', e => { if (e.target.name === 'sel') updateCount(); });
updateCount();
"""


def _blocker(template: summary_templates.SummaryTemplate) -> str:
    """Short reason an option is disabled, sized to fit inside the control.

    Each mode offers a single evidence type, so this is no longer the common
    case — it is one paper in the batch missing what the rest of them have: a
    PDF that will not open, or a record that arrived without an abstract.
    """
    if template.evidence == "fulltext":
        return "PDF missing or unreadable"
    return "no abstract available"


def _card(
    i: int, paper: dict, templates, default_template: str
) -> str:
    score = paper.get("relevance_score") or 0.0
    title = html.escape(paper.get("title") or "(untitled)")
    authors = paper.get("authors") or []
    if authors:
        author_str = ", ".join(authors[:4]) + (f" +{len(authors) - 4} more" if len(authors) > 4 else "")
    else:
        author_str = "(authors unknown)"
    meta = html.escape(f"{author_str} · {_meta(paper)}")
    url = html.escape(paper.get("url") or "#", quote=True)
    abstract = html.escape((paper.get("abstract") or "").strip()) or "(no abstract)"
    options = _template_objects(templates)
    # Pre-select something this paper can actually run. Marking the configured
    # default `selected disabled` still submits it, and the pick is only
    # rejected after the form comes back — so the card would advertise a
    # template that fails on submit. Falling back to the first compatible option
    # keeps the card honest; if none qualify the browser selects nothing.
    usable = [t for t in options if _compatibility(t, paper)[0]]
    selected_id = default_template
    if not any(t.id == default_template for t in usable):
        selected_id = usable[0].id if usable else None

    template_options = ""
    for template in options:
        compatible, reason = _compatibility(template, paper)
        label = template.label or template.id
        description = template.description
        if compatible:
            option_text = f"{label} [{template.evidence}]"
            if description:
                option_text += f" — {description}"
        else:
            # The blocker goes first and stays short. A <select> truncates each
            # option to the control's width, so a reason appended after the
            # description is invisible exactly when it matters — the option
            # reads as arbitrarily dead.
            option_text = f"{label} [{_blocker(template)}]"
        option_title = description if compatible else f"{description} {reason}".strip()
        template_options += (
            f'<option value="{html.escape(template.id, quote=True)}"'
            f'{" selected" if template.id == selected_id else ""}'
            f'{" disabled" if not compatible else ""}'
            f' data-evidence="{html.escape(template.evidence, quote=True)}"'
            f' title="{html.escape(option_title, quote=True)}">'
            f'{html.escape(option_text)}</option>'
        )
    return (
        f'<label class="card">'
        f'<div class="pick">'
        f'<input type="checkbox" name="sel" value="{i}">'
        f'<select name="template_{i}" class="select-control" onclick="event.stopPropagation()">'
        f'{template_options}</select>'
        f'</div>'
        f'<div class="body">'
        f'<div class="title">{title}</div>'
        f'<div class="meta">'
        f'<span class="score" style="background:{_score_hex(score)}">{score:.3f}</span>'
        f'<span>{meta}</span>'
        f'</div>'
        f'<details onclick="event.stopPropagation()">'
        f'<summary>Abstract</summary>'
        f'<div class="abstract">{abstract}</div>'
        f'</details>'
        f'<a class="link" href="{url}" target="_blank" rel="noopener" '
        f'onclick="event.stopPropagation()">Open paper ↗</a>'
        f'</div></label>'
    )


def _related_card(i: int, paper: dict, facets: list) -> str:
    score = paper.get("related_work_score") or 0.0
    title = html.escape(paper.get("title") or "(untitled)")
    authors = paper.get("authors") or []
    author_str = ", ".join(authors[:4]) + (f" +{len(authors) - 4} more" if len(authors) > 4 else "")
    meta = html.escape(f"{author_str or '(authors unknown)'} · {_meta(paper)}")
    url = html.escape(paper.get("url") or "#", quote=True)
    why = html.escape(paper.get("why_cite") or "")
    diff = html.escape(paper.get("difference_from_contribution") or "")
    evidence = html.escape(paper.get("evidence_basis") or "metadata-only")
    facet_options = "".join(
        f'<option value="{html.escape(facet.id, quote=True)}"'
        f'{" selected" if facet.id == paper.get("primary_facet") else ""}>'
        f'{html.escape(facet.name)}</option>'
        for facet in facets
    )
    role_options = "".join(
        f'<option value="{role}"{" selected" if role == (paper.get("role") or "background") else ""}>'
        f'{role.title()}</option>'
        for role in (
            "foundational",
            "method",
            "benchmark",
            "system",
            "application",
            "contrast",
            "recent",
            "background",
        )
    )
    return (
        f'<label class="card">'
        f'<div class="pick">'
        f'<input type="checkbox" name="sel" value="{i}" checked>'
        f'</div>'
        f'<div class="body">'
        f'<div class="title">{title}</div>'
        f'<div class="meta">'
        f'<span class="score" style="background:{_score_hex(score)}">{score:.3f}</span>'
        f'<span>{meta}</span><span>Basis: {evidence}</span>'
        f'</div>'
        f'<div class="controls">'
        f'<select name="facet_{i}" class="select-control" onclick="event.stopPropagation()">{facet_options}</select>'
        f'<select name="role_{i}" class="select-control" onclick="event.stopPropagation()">{role_options}</select>'
        f'</div>'
        f'<p class="annotation"><b>Why cite:</b> {why}</p>'
        f'<p class="annotation"><b>Differs:</b> {diff}</p>'
        f'<a class="link" href="{url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Open paper ↗</a>'
        f'</div></label>'
    )


def _render_html(
    ordered: list[dict], templates, default_template: str
) -> str:
    cards = "\n".join(
        _card(i, paper, templates, default_template)
        for i, paper in enumerate(ordered)
    )
    header = (
        '<header>'
        '<h1>PaperTracker — select papers to summarize</h1>'
        '<div class="toolbar">'
        '<button type="button" id="all">Select all</button>'
        '<button type="button" id="none">Select none</button>'
        '<span id="count" class="count">0 selected</span>'
        '<span class="spacer"></span>'
        '<button type="submit" name="cancel" value="1" class="cancel">Cancel</button>'
        '<button type="submit" class="go">Summarize selected →</button>'
        '</div></header>'
    )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>PaperTracker — {len(ordered)} papers</title>"
        f"<style>{_CSS}</style></head><body>"
        "<form method=\"post\" action=\"/\">"
        f"{header}<main>{cards}</main></form>"
        f"<script>{_SCRIPT}</script>"
        "</body></html>"
    )


def _render_related_html(ordered: list[dict], facets: list) -> str:
    cards = "\n".join(_related_card(i, p, facets) for i, p in enumerate(ordered))
    header = (
        '<header>'
        '<h1>PaperTracker — approve related-work bibliography</h1>'
        '<div class="toolbar">'
        '<button type="button" id="all">Select all</button>'
        '<button type="button" id="none">Select none</button>'
        '<span id="count" class="count">0 selected</span>'
        '<span class="spacer"></span>'
        '<button type="submit" name="cancel" value="1" class="cancel">Cancel</button>'
        '<button type="submit" class="go">Save selection →</button>'
        '</div></header>'
    )
    css = _CSS + """
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.annotation{margin:8px 0 0;color:#c9d1d9;font-size:13.5px}
"""
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>PaperTracker — {len(ordered)} candidates</title>"
        f"<style>{css}</style></head><body>"
        "<form method=\"post\" action=\"/\">"
        f"{header}<main>{cards}</main></form>"
        f"<script>{_SCRIPT}</script>"
        "</body></html>"
    )


def _done_html(n: int) -> str:
    return (
        "<!doctype html><meta charset=\"utf-8\"><title>PaperTracker</title>"
        "<body style=\"font-family:-apple-system,sans-serif;background:#0d1117;color:#e6edf3;"
        "display:flex;height:100vh;margin:0;align-items:center;justify-content:center;text-align:center\">"
        f"<div><h1>✓ {n} paper(s) selected</h1>"
        "<p style=\"color:#8b949e\">You can close this tab and return to the terminal.</p></div>"
    )


# --------------------------------------------------------------------------- #
# Non-TTY text fallback
# --------------------------------------------------------------------------- #

def _select_fallback(
    ordered: list[dict], templates, default_template: str
) -> list[dict]:
    use_color = sys.stdout.isatty()
    bold = BOLD if use_color else ""
    dim = DIM if use_color else ""
    reset = RESET if use_color else ""

    normalized = _template_objects(templates)
    template_ids = [template.id for template in normalized]
    print("  Summary templates:")
    for template in normalized:
        print(
            f"    {template.id}: {template.label or template.id} "
            f"[{template.evidence}] — {template.description}"
        )
    for i, p in enumerate(ordered, 1):
        score = p.get("relevance_score") or 0.0
        sc = _score_color(score) if use_color else ""
        print(
            f"  [{i:>2}] {sc}{score:.3f}{reset}  {bold}{p.get('title') or '(untitled)'}{reset}"
            f"  {dim}{_meta(p)}{reset}"
        )
    try:
        raw = input(
            f"Pick papers (e.g. '1,3', '2:{template_ids[0]}'; "
            f"'a'=all; default={default_template}; enter=none): "
        )
    except EOFError:
        raw = ""
    out = []
    try:
        picks = _parse_selection(raw, len(ordered), template_ids, default_template)
        _validate_picks(picks, ordered, normalized)
    except SelectionError as exc:
        print(f"  Invalid selection: {exc}")
        return []
    for i, template_id in picks:
        paper = dict(ordered[i])
        paper["template"] = template_id
        out.append(paper)
    return out


def _select_related_fallback(ordered: list[dict]) -> list[dict]:
    use_color = sys.stdout.isatty()
    bold = BOLD if use_color else ""
    reset = RESET if use_color else ""

    for i, p in enumerate(ordered, 1):
        score = p.get("related_work_score") or 0.0
        sc = _score_color(score) if use_color else ""
        print(
            f"  [{i:>2}] {sc}{score:.3f}{reset}  {bold}{p.get('title') or '(untitled)'}{reset}"
            f"  {p.get('primary_facet') or '?'} · {p.get('role') or 'background'}"
        )
    try:
        raw = input("Pick final bibliography papers (e.g. '1,3', 'a'=all, enter=none): ")
    except EOFError:
        raw = ""
    picks = _parse_selection(raw, len(ordered), ["default"], "default")
    return [
        {
            "canonical_id": ordered[i].get("canonical_id"),
            "primary_facet": ordered[i].get("primary_facet"),
            "role": ordered[i].get("role") or "background",
        }
        for i, _template in picks
    ]


def _parse_selection(
    raw: str, n: int, template_ids: list[str], default_template: str
) -> list[tuple[int, str]]:
    """Parse selections into sorted (0-based index, template ID) pairs."""
    raw = raw.strip()
    if not raw:
        return []
    if raw.lower() in ("a", "all"):
        return [(i, default_template) for i in range(n)]
    chosen: dict[int, str] = {}
    for token in raw.split(","):
        tok = token.strip()
        if not tok:
            continue
        index_token, separator, selected = tok.partition(":")
        template_id = selected.strip() if separator else default_template
        if template_id not in template_ids:
            raise SelectionError(f"Unknown summary template {template_id!r}")
        index_token = index_token.strip()
        if "-" in index_token:
            lo, _, hi = index_token.partition("-")
            if lo.isdigit() and hi.isdigit():
                for v in range(int(lo), int(hi) + 1):
                    if 1 <= v <= n:
                        chosen[v - 1] = template_id
        elif index_token.isdigit():
            v = int(index_token)
            if 1 <= v <= n:
                chosen[v - 1] = template_id
    return sorted(chosen.items())


def _template_objects(templates) -> tuple[summary_templates.SummaryTemplate, ...]:
    """Normalize the public selector input while tolerating legacy ID lists."""
    normalized = []
    for template in templates:
        if isinstance(template, summary_templates.SummaryTemplate):
            normalized.append(template)
        else:
            template_id = str(template)
            normalized.append(
                summary_templates.SummaryTemplate(
                    template_id,
                    Path(template_id),
                    label=template_id,
                    description="",
                    evidence="abstract",
                )
            )
    return tuple(normalized)


def _compatibility(
    template: summary_templates.SummaryTemplate, paper: dict
) -> tuple[bool, str | None]:
    # Legacy ID-only callers have no evidence metadata and remain unrestricted.
    if not template.description and template.path == Path(template.id):
        return True, None
    return summary_templates.compatibility(template, paper)


def _validate_picks(
    picks: list[tuple[int, str]],
    papers: list[dict],
    templates: tuple[summary_templates.SummaryTemplate, ...],
) -> None:
    by_id = {template.id: template for template in templates}
    for index, template_id in picks:
        compatible, reason = _compatibility(by_id[template_id], papers[index])
        if not compatible:
            raise SelectionError(
                f"Template {template_id!r} is incompatible with paper {index + 1}: {reason}"
            )
