import html
import json
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from collections import Counter

from .. import config


_current_server = None
_current_thread = None
_version = 0


def _json_for_script(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _reject_path(reject_file=None):
    if reject_file is None:
        reject_file = config.DEFAULT_REJECT_FILE
    path = Path(reject_file)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _load_rejects(path):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if isinstance(data, dict):
        for key in ("rejected_ids", "rejectedids"):
            v = data.get(key)
            if isinstance(v, list):
                return v
        return []

    if isinstance(data, list):
        out = []
        for item in data:
            if item is None:
                continue
            if isinstance(item, dict):
                if "id" in item and item["id"] is not None:
                    out.append(item["id"])
            else:
                out.append(item)
        return out
    return []


def _write_rejects(path, rejected_ids):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"rejected_ids": rejected_ids}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _save_reject(reject_id, reject_file=None):
    path = _reject_path(reject_file)
    ids = list(dict.fromkeys(_load_rejects(path)))
    if reject_id is None:
        raise ValueError("reject_id is missing")
    action = "already_present" if reject_id in ids else "added"
    if action == "added":
        ids.append(reject_id)
    _write_rejects(path, ids)
    return {"ok": True, "file": str(path), "count": len(ids), "action": action, "id": reject_id}


def _table(headers, rows, row_styles=None, row_attrs=None):
    out = '<table><tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr>'
    for i, row in enumerate(rows):
        s = f' style="background:{row_styles[i]};"' if row_styles and i < len(row_styles) and row_styles[i] else ''
        a = (' ' + row_attrs[i]) if row_attrs and i < len(row_attrs) and row_attrs[i] else ''
        out += f'<tr{s}{a}>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>'
    out += '</table>'
    return out


def _item_verdict_counts(item):
    counts = Counter()
    for f in item.get("fields") or []:
        counts[f.get("verdict", "")] += 1
    return counts


def _item_is_fully_correct(item):
    fields = item.get("fields") or []
    return not fields or all(f.get("verdict") == "correct" for f in fields)


def _discover_verdicts(items):
    seen, out = set(), []
    for item in items:
        for f in item.get("fields") or []:
            v = f.get("verdict", "")
            if v and v not in seen:
                out.append(v)
                seen.add(v)
    return out


def _sort_key(item):
    if _item_is_fully_correct(item):
        return 2
    counts = _item_verdict_counts(item)
    return 0 if any(v != "correct" for v in counts) else 1


def _verdict_badge(counts, verdicts, colors):
    if not counts:
        return '<span class="vb" style="background:#f5f5f5;color:#999;">no fields</span>'
    return ' '.join(
        f'<span class="vb" style="background:{colors.get(v, "#eee")};">{counts[v]} {html.escape(v)}</span>'
        for v in verdicts if v in counts
    )


_CSS = '''<style>
body { font-family: system-ui, -apple-system, sans-serif; max-width: 960px; margin: 30px auto; padding: 0 20px; color: #333; font-size: 13px; }
.summary { display: flex; gap: 20px; align-items: center; flex-wrap: wrap; padding: 10px 14px; background: #fafafa; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 12px; font-size: 15px; font-weight: 600; }
.summary-correct { color: #2e7d32; }
.summary-pct { color: #555; margin-left: auto; }
table { width: 100%; border-collapse: collapse; margin-bottom: 12px; font-size: 12px; }
th, td { border: 1px solid #ddd; padding: 4px 8px; text-align: left; word-wrap: break-word; }
th { background: #f5f5f5; font-weight: 600; }
pre { background: #f5f5f5; padding: 10px; border: 1px solid #ddd; white-space: pre-wrap; word-wrap: break-word; max-height: 250px; overflow-y: auto; font-size: 12px; }
.nav { display: flex; align-items: center; gap: 12px; margin: 14px 0; }
.nav button { padding: 6px 16px; font-size: 14px; cursor: pointer; }
.counter { font-size: 13px; color: #666; }
h3 { margin-top: 18px; margin-bottom: 4px; font-size: 14px; }
.vb { display: inline-block; padding: 1px 7px; border-radius: 3px; font-size: 12px; margin-right: 4px; border: 1px solid rgba(0,0,0,0.06); }
.toast { position: fixed; top: 14px; left: 50%; transform: translateX(-50%); background: #1f1f1f; color: #fff; padding: 8px 12px; border-radius: 6px; font-size: 12px; opacity: 0; pointer-events: none; transition: opacity 120ms; max-width: 92vw; z-index: 999; }
.toast.show { opacity: 0.92; }
</style>'''


# ── Overview ───────────────────────────────────────────────────────────────────

def _render_overview(items, verdicts, version):
    total = len(items)
    colors = config.CONFIG.get_spot_check_verdict_colors()
    fully_correct = sum(1 for x in items if _item_is_fully_correct(x))
    pct = (fully_correct / total * 100) if total else 0

    rows, styles, attrs = [], [], []
    for i, item in enumerate(items):
        counts = _item_verdict_counts(item)
        badge = _verdict_badge(counts, verdicts, colors)
        rows.append([
            f'<span class="id-cell">{html.escape(str(item.get("id", "")))}</span>',
            badge,
            f'<a href="/?row={i}" class="dl">View →</a>',
        ])
        non_correct = [v for v in verdicts if v != "correct" and v in counts]
        styles.append(colors.get(non_correct[0], "") if non_correct else "")
        attrs.append(f'data-idx="{i}"')

    tbl = _table(["ID", "Verdicts", ""], rows, row_styles=styles, row_attrs=attrs)

    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Spotcheck ({total})</title>
{_CSS}
<style>
.id-cell {{ font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; word-break: break-all; }}
table tr[data-idx] {{ cursor: pointer; }}
table tr[data-idx]:hover {{ filter: brightness(0.96); }}
.dl {{ color: #1976d2; text-decoration: none; font-size: 12px; }}
</style></head><body>
<div id="toast" class="toast"></div>
<div class="summary">
    <span class="summary-correct">Correct: {fully_correct}/{total}</span>
    <span class="summary-pct">{pct:.0f}%</span>
</div>
{tbl}
<script>
document.querySelectorAll('tr[data-idx]').forEach(tr => {{
    tr.addEventListener('click', e => {{
        if (e.target.tagName === 'A') return;
        window.location.href = '/?row=' + tr.dataset.idx;
    }});
}});
const CV = {version};
setInterval(async () => {{
    try {{ const v = parseInt(await (await fetch("/version")).text()); if (v !== CV) window.location.href = "/"; }} catch(e) {{}}
}}, 250);
</script></body></html>'''


# ── Detail ─────────────────────────────────────────────────────────────────────

def _render_detail(items, index, verdicts, version):
    total = len(items)
    item = items[index]
    prev_idx = (index - 1) % total
    next_idx = (index + 1) % total
    colors = config.CONFIG.get_spot_check_verdict_colors()
    counts = _item_verdict_counts(item)
    badge = _verdict_badge(counts, verdicts, colors)

    # Verdict table rows
    fields = item.get("fields") or []
    verdict_rows = ""
    for f in fields:
        v = f.get("verdict", "")
        bg = colors.get(v, "")
        style = f' style="background:{bg};"' if bg else ""
        verdict_rows += (
            f'<tr data-verdict="{html.escape(v)}"{style}>'
            f'<td><b>{html.escape(f.get("name", ""))}</b></td>'
            f'<td>{html.escape(v)}</td>'
            f'<td>{html.escape(f.get("desc", "") or "—")}</td></tr>'
        )
    verdict_html = (
        f'<h3>Spot Check</h3><table><tr><th>Field</th><th>Verdict</th><th>Description</th></tr>{verdict_rows}</table>'
        if fields else '<h3>Spot Check</h3><p>No field verdicts.</p>'
    )

    # Extracted rows
    extracted = item.get("extracted_rows", [])
    if extracted:
        efields = list(extracted[0].keys())
        if len(extracted) == 1:
            erows = [[f'<b>{html.escape(f)}</b>', html.escape(str(extracted[0].get(f, '')))] for f in efields]
            extracted_html = '<h3>Extracted Rows</h3>' + _table(["Field", "Value"], erows)
        else:
            eh = ["Field"] + [f"Row {i+1}" for i in range(len(extracted))]
            erows = [[f'<b>{html.escape(f)}</b>'] + [html.escape(str(r.get(f, ''))) for r in extracted] for f in efields]
            extracted_html = '<h3>Extracted Rows</h3>' + _table(eh, erows)
    else:
        extracted_html = '<p>No extracted rows.</p>'

    ctx = html.escape(str(item.get("context", "")))
    context_html = f'<h3>Original Context</h3><pre>{ctx}</pre>'

    # Filter checkboxes — only verdicts present in this item
    item_verdicts = list(dict.fromkeys(f.get("verdict", "") for f in fields if f.get("verdict")))
    checks = ''.join(
        f'<label class="flt" style="background:{colors.get(v, "#eee")};">'
        f'<input type="checkbox" value="{html.escape(v)}" checked> {html.escape(v)} ({counts.get(v, 0)})</label>'
        for v in item_verdicts
    )
    filter_bar = f'<div class="filter-bar">{checks}</div>' if item_verdicts else ''

    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Spotcheck {index+1}/{total}</title>
{_CSS}
<style>
.hdr {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }}
.hdr .back {{ color: #1976d2; text-decoration: none; font-size: 13px; }}
.hdr .did {{ font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 13px; font-weight: 600; }}
.hdr .badges {{ margin-left: auto; }}
.filter-bar {{ display: flex; gap: 10px; flex-wrap: wrap; padding: 8px 12px; background: #fafafa; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 10px; }}
.flt {{ display: inline-flex; align-items: center; gap: 4px; font-size: 12px; cursor: pointer; padding: 2px 8px; border-radius: 3px; border: 1px solid rgba(0,0,0,0.08); }}
.flt input {{ cursor: pointer; }}
</style></head><body>
<div id="toast" class="toast"></div>
<div class="hdr">
    <a href="/" class="back">← Overview</a>
    <span class="did">ID: {html.escape(str(item.get("id", "")))}</span>
    <span class="badges">{badge}</span>
</div>
{filter_bar}
<div class="nav">
    <a href="/?row={prev_idx}"><button>← Prev</button></a>
    <span class="counter">{index+1} / {total}</span>
    <a href="/?row={next_idx}"><button>Next →</button></a>
</div>
{verdict_html}
{extracted_html}
{context_html}
<div class="nav">
    <a href="/?row={prev_idx}"><button>← Prev</button></a>
    <span class="counter">{index+1} / {total}</span>
    <a href="/?row={next_idx}"><button>Next →</button></a>
</div>
<script>
const HOTKEY_BACK = {_json_for_script(config.HOTKEY_BACK)};
const HOTKEY_FORWARD = {_json_for_script(config.HOTKEY_FORWARD)};
const HOTKEY_COPY_EXTRACTED_ROWS = {_json_for_script(config.HOTKEY_COPY_EXTRACTED_ROWS)};
const HOTKEY_COPY_ID = {_json_for_script(config.HOTKEY_COPY_ID)};
const HOTKEY_DOWNLOAD_EXTRACTED_ROWS = {_json_for_script(config.HOTKEY_DOWNLOAD_EXTRACTED_ROWS)};
const HOTKEY_REJECT = {_json_for_script(config.HOTKEY_REJECT)};
const PREV_URL = "/?row={prev_idx}";
const NEXT_URL = "/?row={next_idx}";
const CURRENT_ROW = {index};
const CURRENT_ID = {_json_for_script(item.get("id"))};
const EXTRACTED_ROWS = {_json_for_script(item.get("extracted_rows", []))};

const toastEl = document.getElementById("toast");
let toastTimer = null;
function toast(msg) {{
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 1100);
}}

async function copyText(text) {{
    if (navigator.clipboard?.writeText) {{ await navigator.clipboard.writeText(text); return; }}
    const ta = Object.assign(document.createElement("textarea"), {{ value: text, readOnly: true }});
    ta.style.cssText = "position:fixed;left:-9999px";
    document.body.appendChild(ta); ta.select(); document.execCommand("copy"); document.body.removeChild(ta);
}}

async function copyExtractedRows() {{ try {{ await copyText(JSON.stringify(EXTRACTED_ROWS, null, 2)); toast("COPIED EXTRACTED ROWS"); }} catch(e) {{ toast("COPY FAILED"); }} }}
async function copyId() {{ try {{ await copyText(String(CURRENT_ID ?? "")); toast("COPIED ID"); }} catch(e) {{ toast("COPY FAILED"); }} }}

async function postAction(endpoint) {{
    try {{
        const resp = await fetch(endpoint, {{ method: "POST", headers: {{"Content-Type":"application/json"}}, body: JSON.stringify({{ row: CURRENT_ROW }}) }});
        if (!resp.ok) throw new Error(await resp.text());
        const data = await resp.json();
        toast((endpoint === "/reject" ? "REJECTED" : "EXPORTED") + " (" + data.file + ")");
        setTimeout(() => {{ window.location.href = NEXT_URL + window.location.hash; }}, 200);
    }} catch(e) {{ toast("FAILED"); }}
}}

// ── Verdict filter (persisted in hash across pages) ──
function getHidden() {{
    const h = window.location.hash.replace(/^#/, "");
    if (!h) return new Set();
    return new Set(decodeURIComponent(h).split(",").filter(Boolean));
}}
function setHidden(hidden) {{
    const arr = [...hidden].filter(Boolean);
    window.location.hash = arr.length ? encodeURIComponent(arr.join(",")) : "";
}}
function applyFilter() {{
    const hidden = getHidden();
    document.querySelectorAll('tr[data-verdict]').forEach(tr => {{
        tr.style.display = hidden.has(tr.dataset.verdict) ? 'none' : '';
    }});
    document.querySelectorAll('.filter-bar input[type="checkbox"]').forEach(cb => {{
        cb.checked = !hidden.has(cb.value);
    }});
}}
document.querySelectorAll('.filter-bar input[type="checkbox"]').forEach(cb => {{
    cb.addEventListener('change', () => {{
        const hidden = getHidden();
        if (cb.checked) hidden.delete(cb.value); else hidden.add(cb.value);
        setHidden(hidden);
        applyFilter();
    }});
}});
applyFilter();

// Preserve hash on nav links and hotkeys
function navTo(url) {{ window.location.href = url + window.location.hash; }}

document.querySelectorAll('.nav a').forEach(a => {{
    a.addEventListener('click', e => {{ e.preventDefault(); navTo(a.getAttribute('href')); }});
}});

document.addEventListener("keydown", (e) => {{
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
    if (HOTKEY_BACK.includes(key)) {{ e.preventDefault(); navTo(PREV_URL); return; }}
    if (HOTKEY_FORWARD.includes(key)) {{ e.preventDefault(); navTo(NEXT_URL); return; }}
    if (HOTKEY_COPY_EXTRACTED_ROWS.includes(key)) {{ e.preventDefault(); copyExtractedRows(); return; }}
    if (HOTKEY_COPY_ID.includes(key)) {{ e.preventDefault(); copyId(); return; }}
    if (HOTKEY_DOWNLOAD_EXTRACTED_ROWS.includes(key)) {{ e.preventDefault(); postAction("/export"); return; }}
    if (HOTKEY_REJECT.includes(key)) {{ e.preventDefault(); postAction("/reject"); return; }}
}});

const CV = {version};
setInterval(async () => {{
    try {{ const v = parseInt(await (await fetch("/version")).text()); if (v !== CV) window.location.href = "/"; }} catch(e) {{}}
}}, 250);
</script></body></html>'''


# ── Server ─────────────────────────────────────────────────────────────────────

def visualize(spotcheck_results, port=8000):
    """Launch a local HTTP server to browse spotcheck results.

    Args:
        spotcheck_results: list of dicts with id, fields, extracted_rows, context
        port: port to serve on (default 8000)
    """
    global _current_server, _current_thread, _version

    if not spotcheck_results:
        print("Nothing to visualize.")
        return

    if _current_server is not None:
        _current_server.shutdown()
        _current_server.server_close()
        _current_server = None
        _current_thread = None

    _version += 1
    current_version = _version

    verdicts = _discover_verdicts(spotcheck_results)
    items = sorted(spotcheck_results, key=_sort_key)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/version":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(str(current_version).encode())
                return

            params = parse_qs(parsed.query)
            if "row" in params:
                try:
                    row = int(params["row"][0]) % len(items)
                except (ValueError, ZeroDivisionError):
                    row = 0
                page = _render_detail(items, row, verdicts, current_version)
            else:
                page = _render_overview(items, verdicts, current_version)

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(page.encode())

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path not in {"/reject", "/export"}:
                self.send_response(404)
                self.end_headers()
                return

            try:
                cl = int(self.headers.get("Content-Length", 0))
            except Exception:
                cl = 0
            payload = {}
            if cl:
                try:
                    payload = json.loads(self.rfile.read(cl).decode("utf-8"))
                except Exception:
                    pass

            try:
                row = int(payload.get("row", 0)) % len(items)
            except Exception:
                row = 0

            item = items[row]
            try:
                rf = None if parsed.path == "/reject" else config.DEFAULT_REJECT_ID_FILE
                result = _save_reject(item.get("id"), reject_file=rf)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))

        def log_message(self, *a):
            pass

    server = HTTPServer(("", port), Handler)
    _current_server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _current_thread = thread

    print(f"  Spotcheck visualizer: http://localhost:{port}")
    webbrowser.open(f"http://localhost:{port}")