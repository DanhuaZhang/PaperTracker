"""Interactive selection of which papers to summarize.

The primary UI is a small HTML page served from a localhost-only HTTP server:
titles wrap in full, abstracts are visible, and clicking a card toggles it. The
browser POSTs the chosen papers back to the waiting process. When stdin is not a
TTY (pipes, CI) it falls back to a numbered text prompt. No third-party deps.
"""
from __future__ import annotations

import html
import http.server
import sys
import webbrowser
from urllib.parse import parse_qs

# ANSI palette for the text fallback — mirrors cli._print_paper_list.
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


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


def select_papers(papers: list[dict]) -> list[dict]:
    """Return the subset the user picks, in relevance-sorted order."""
    if not papers:
        return []
    ordered = _ordered(papers)
    if sys.stdin.isatty():
        try:
            return _select_html(ordered)
        except Exception as e:  # noqa: BLE001 — any UI failure degrades to text
            print(f"  (browser selector unavailable: {e}; falling back to text)")
            return _select_fallback(ordered)
    return _select_fallback(ordered)


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

def _selections_from_form(form: dict[str, list[str]], n: int) -> list[tuple[int, str]]:
    """Map a parsed POST form to a sorted list of (index, mode) pairs."""
    if "cancel" in form:
        return []
    out: list[tuple[int, str]] = []
    for v in form.get("sel", []):
        if not v.isdigit():
            continue
        i = int(v)
        if not (0 <= i < n):
            continue
        mode = (form.get(f"mode_{i}", ["triage"])[0]).strip().lower()
        if mode not in ("triage", "deep"):
            mode = "triage"
        out.append((i, mode))
    return sorted(out)


def _make_server(ordered: list[dict], page: str):
    """Build (but don't run) a localhost server. Returns (httpd, result).

    `result["selected"]` stays None until the browser POSTs, then becomes the
    chosen index list.
    """
    n = len(ordered)
    result: dict[str, list[tuple[int, str]] | None] = {"selected": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence per-request logging
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
            result["selected"] = _selections_from_form(form, n)
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


def _select_html(ordered: list[dict]) -> list[dict]:
    page = _render_html(ordered)
    httpd, result = _make_server(ordered, page)
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
    for i, mode in (result["selected"] or []):
        paper = dict(ordered[i])
        paper["mode"] = mode
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
.mode{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:5px;font:inherit;font-size:12px;padding:2px 4px;cursor:pointer}
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


def _card(i: int, paper: dict) -> str:
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
    return (
        f'<label class="card">'
        f'<div class="pick">'
        f'<input type="checkbox" name="sel" value="{i}">'
        f'<select name="mode_{i}" class="mode" onclick="event.stopPropagation()">'
        f'<option value="triage">Triage</option>'
        f'<option value="deep">Deep (Obsidian)</option>'
        f'</select>'
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
        f'<select name="facet_{i}" class="mode" onclick="event.stopPropagation()">{facet_options}</select>'
        f'<select name="role_{i}" class="mode" onclick="event.stopPropagation()">{role_options}</select>'
        f'</div>'
        f'<p class="annotation"><b>Why cite:</b> {why}</p>'
        f'<p class="annotation"><b>Differs:</b> {diff}</p>'
        f'<a class="link" href="{url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Open paper ↗</a>'
        f'</div></label>'
    )


def _render_html(ordered: list[dict]) -> str:
    cards = "\n".join(_card(i, p) for i, p in enumerate(ordered))
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
        raw = input("Pick papers (e.g. '1,3' triage, '2d' deep; 'a'=all triage, enter=none): ")
    except EOFError:
        raw = ""
    out = []
    for i, mode in _parse_selection(raw, len(ordered)):
        paper = dict(ordered[i])
        paper["mode"] = mode
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
    picks = _parse_selection(raw, len(ordered))
    return [
        {
            "canonical_id": ordered[i].get("canonical_id"),
            "primary_facet": ordered[i].get("primary_facet"),
            "role": ordered[i].get("role") or "background",
        }
        for i, _mode in picks
    ]


def _parse_selection(raw: str, n: int) -> list[tuple[int, str]]:
    """Parse '1,3d', '1-3', 'a'/'all', '' into sorted (0-based index, mode) pairs.

    A trailing 'd' on a token marks deep mode; otherwise triage. 'a'/'all' = all triage.
    """
    raw = raw.strip().lower()
    if not raw:
        return []
    if raw in ("a", "all"):
        return [(i, "triage") for i in range(n)]
    chosen: dict[int, str] = {}
    for tok in raw.replace(" ", "").split(","):
        if not tok:
            continue
        mode = "triage"
        if tok.endswith("d"):
            mode, tok = "deep", tok[:-1]
        if "-" in tok:
            lo, _, hi = tok.partition("-")
            if lo.isdigit() and hi.isdigit():
                for v in range(int(lo), int(hi) + 1):
                    if 1 <= v <= n:
                        chosen[v - 1] = mode
        elif tok.isdigit():
            v = int(tok)
            if 1 <= v <= n:
                chosen[v - 1] = mode
    return sorted(chosen.items())
