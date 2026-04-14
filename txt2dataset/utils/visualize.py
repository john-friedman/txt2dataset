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
    """JSON for embedding in HTML <script> blocks."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _reject_path(reject_file=None):
    if reject_file is None:
        reject_file = config.DEFAULT_REJECT_FILE
    path = Path(reject_file)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _load_rejects(path):
    """Load rejected IDs from disk.

    Supported formats:
      - {"rejected_ids": [...]} (preferred)
      - {"rejectedids": [...]} (legacy/typo-tolerant)
      - [id, id, ...]
      - [{"id": ...}, ...] (older reject.json format)
    """
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if isinstance(data, dict):
        rejected_ids = data.get("rejected_ids")
        if isinstance(rejected_ids, list):
            return rejected_ids
        rejected_ids = data.get("rejectedids")
        if isinstance(rejected_ids, list):
            return rejected_ids
        return []

    if isinstance(data, list):
        rejected_ids = []
        for item in data:
            if item is None:
                continue
            if isinstance(item, dict):
                if "id" in item and item.get("id") is not None:
                    rejected_ids.append(item.get("id"))
                continue
            rejected_ids.append(item)
        return rejected_ids

    return []


def _write_rejects(path, rejected_ids):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    payload = {"rejected_ids": rejected_ids}
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _save_reject(reject_id, reject_file=None):
    path = _reject_path(reject_file)
    rejected_ids = _load_rejects(path)

    unique_rejected_ids = []
    for existing_id in rejected_ids:
        if existing_id not in unique_rejected_ids:
            unique_rejected_ids.append(existing_id)

    if reject_id is None:
        raise ValueError("reject_id is missing")

    action = "added"
    if reject_id in unique_rejected_ids:
        action = "already_present"
    else:
        unique_rejected_ids.append(reject_id)

    _write_rejects(path, unique_rejected_ids)
    return {
        "ok": True,
        "file": str(path),
        "count": len(unique_rejected_ids),
        "action": action,
        "id": reject_id,
    }


def _table(headers, rows, row_styles=None):
    """Build an HTML table."""
    out = '<table>'
    out += '<tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr>'
    for i, row in enumerate(rows):
        style = ''
        if row_styles and i < len(row_styles) and row_styles[i]:
            style = f' style="background:{row_styles[i]};"'
        out += f'<tr{style}>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>'
    out += '</table>'
    return out


def _item_is_fully_correct(item):
    fields = item.get("fields") or []
    if not fields:
        return True
    return all(f.get("verdict") == "correct" for f in fields)


def _item_verdict_counts(item):
    counts = Counter()
    for f in item.get("fields") or []:
        v = f.get("verdict", "")
        if v != "correct":
            counts[v] += 1
    return counts


def _render_extracted_rows(extracted_rows):
    """Render extracted rows as a transposed table (fields as rows)."""
    if not extracted_rows:
        return '<p>No extracted rows.</p>'
    fields = list(extracted_rows[0].keys())
    if len(extracted_rows) == 1:
        headers = ["Field", "Value"]
        rows = [[f'<b>{html.escape(f)}</b>', html.escape(str(extracted_rows[0].get(f, '')))] for f in fields]
    else:
        headers = ["Field"] + [f"Row {i+1}" for i in range(len(extracted_rows))]
        rows = [
            [f'<b>{html.escape(f)}</b>'] + [html.escape(str(r.get(f, ''))) for r in extracted_rows]
            for f in fields
        ]
    return '<h3>Extracted Rows</h3>' + _table(headers, rows)


def _render_context(context):
    """Render original context as a pre block."""
    escaped = html.escape(str(context))
    return f'<h3>Original Context</h3><pre>{escaped}</pre>'


def _render_verdict(item):
    fields = item.get("fields") or []
    if not fields:
        return '<h3>Spot Check</h3><p>No field verdicts.</p>'

    verdict_colors = config.CONFIG.get_spot_check_verdict_colors()
    rows = []
    row_styles = []
    for field_data in fields:
        verdict = field_data.get("verdict", "")
        rows.append([
            f'<b>{html.escape(field_data.get("name", ""))}</b>',
            html.escape(verdict),
            html.escape(field_data.get("desc", "") or "—"),
        ])
        row_styles.append(verdict_colors.get(verdict, ""))

    return '<h3>Spot Check</h3>' + _table(["Field", "Verdict", "Description"], rows, row_styles=row_styles)


def _render_summary(items):
    """Render summary: fully correct files vs total, plus counts of each non-correct verdict across all fields."""
    total = len(items)
    fully_correct = sum(1 for x in items if _item_is_fully_correct(x))
    pct = (fully_correct / total * 100) if total else 0

    # Aggregate non-correct verdict counts across all files and fields
    totals = Counter()
    for item in items:
        totals.update(_item_verdict_counts(item))

    error_parts = ' &nbsp;·&nbsp; '.join(
        f'<span class="summary-verdict">{html.escape(verdict)}: {count}</span>'
        for verdict, count in sorted(totals.items())
    )

    return (
        f'<div class="summary">'
        f'<span class="summary-correct">Correct files: {fully_correct}/{total}</span>'
        f'<span class="summary-pct">{pct:.0f}% pass rate</span>'
        + (f'<span class="summary-errors">{error_parts}</span>' if error_parts else '')
        + f'</div>'
    )


def _render_page(items, index, version):
    """Build a full HTML page for one spotcheck result."""
    total = len(items)
    item = items[index]
    prev_idx = (index - 1) % total
    next_idx = (index + 1) % total

    sections = [
        _render_summary(items),
        _render_verdict(item),
        _render_extracted_rows(item.get("extracted_rows", [])),
        _render_context(item.get("context", "")),
    ]

    nav = f'''
    <div class="nav">
        <a href="/?row={prev_idx}"><button>← Prev</button></a>
        <span class="counter">Entry {index + 1} of {total} &nbsp;·&nbsp; ID: {html.escape(str(item["id"]))}</span>
        <a href="/?row={next_idx}"><button>Next →</button></a>
    </div>
    '''

    body = '\n'.join(sections)

    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Spotcheck {index + 1}/{total}</title>
<style>
    body {{
        font-family: system-ui, -apple-system, sans-serif;
        max-width: 960px;
        margin: 30px auto;
        padding: 0 20px;
        color: #333;
        font-size: 13px;
    }}
    .summary {{
        display: flex;
        gap: 20px;
        align-items: center;
        flex-wrap: wrap;
        padding: 10px 14px;
        background: #fafafa;
        border: 1px solid #ddd;
        border-radius: 4px;
        margin-bottom: 16px;
        font-size: 15px;
        font-weight: 600;
    }}
    .summary-correct {{ color: #2e7d32; }}
    .summary-pct {{ color: #555; margin-left: auto; }}
    .summary-errors {{ font-size: 13px; font-weight: 400; color: #555; }}
    .summary-verdict {{ margin-right: 4px; }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 12px;
        font-size: 12px;
    }}
    th, td {{
        border: 1px solid #ddd;
        padding: 4px 8px;
        text-align: left;
        word-wrap: break-word;
    }}
    th {{
        background: #f5f5f5;
        font-weight: 600;
    }}
    pre {{
        background: #f5f5f5;
        padding: 10px;
        border: 1px solid #ddd;
        white-space: pre-wrap;
        word-wrap: break-word;
        max-height: 250px;
        overflow-y: auto;
        font-size: 12px;
    }}
    .nav {{
        display: flex;
        align-items: center;
        gap: 12px;
        margin: 14px 0;
    }}
    .nav button {{
        padding: 6px 16px;
        font-size: 14px;
        cursor: pointer;
    }}
    .counter {{
        font-size: 13px;
        color: #666;
    }}
    h3 {{
        margin-top: 18px;
        margin-bottom: 4px;
        font-size: 14px;
    }}
    .toast {{
        position: fixed;
        top: 14px;
        left: 50%;
        transform: translateX(-50%);
        background: #1f1f1f;
        color: #fff;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 12px;
        opacity: 0;
        pointer-events: none;
        transition: opacity 120ms ease-in-out;
        max-width: 92vw;
        z-index: 999;
    }}
    .toast.show {{ opacity: 0.92; }}
</style>
</head>
<body>
    <div id="toast" class="toast"></div>
    {body}
    {nav}
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

    function toast(message) {{
        if (!toastEl) return;
        toastEl.textContent = message;
        toastEl.classList.add("show");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toastEl.classList.remove("show"), 1100);
    }}

    async function copyText(text) {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
            await navigator.clipboard.writeText(text);
            return;
        }}
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
    }}

    async function copyExtractedRows() {{
        const text = JSON.stringify(EXTRACTED_ROWS, null, 2);
        try {{
            await copyText(text);
            toast("COPIED EXTRACTED ROWS");
        }} catch (e) {{
            toast("COPY FAILED");
        }}
    }}

    async function copyId() {{
        const text = String(CURRENT_ID ?? "");
        try {{
            await copyText(text);
            toast("COPIED ID");
        }} catch (e) {{
            toast("COPY FAILED");
        }}
    }}

    async function exportCurrent() {{
        try {{
            const resp = await fetch("/export", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{ row: CURRENT_ROW }}),
            }});
            if (!resp.ok) {{
                throw new Error(await resp.text());
            }}
            const data = await resp.json();
            toast("EXPORTED (" + data.file + ")");
            setTimeout(() => {{ window.location.href = NEXT_URL; }}, 200);
        }} catch (e) {{
            toast("EXPORT FAILED");
        }}
    }}

    async function rejectCurrent() {{
        try {{
            const resp = await fetch("/reject", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{ row: CURRENT_ROW }}),
            }});
            if (!resp.ok) {{
                throw new Error(await resp.text());
            }}
            const data = await resp.json();
            toast("REJECTED (SAVED " + data.file + ")");
            setTimeout(() => {{ window.location.href = NEXT_URL; }}, 200);
        }} catch (e) {{
            toast("REJECT FAILED");
        }}
    }}

    document.addEventListener("keydown", (e) => {{
        const target = e.target;
        if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {{
            return;
        }}
        if (e.ctrlKey || e.metaKey || e.altKey) return;

        const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
        if (HOTKEY_BACK.includes(key)) {{
            e.preventDefault();
            window.location.href = PREV_URL;
            return;
        }}
        if (HOTKEY_FORWARD.includes(key)) {{
            e.preventDefault();
            window.location.href = NEXT_URL;
            return;
        }}
        if (HOTKEY_COPY_EXTRACTED_ROWS.includes(key)) {{
            e.preventDefault();
            copyExtractedRows();
            return;
        }}
        if (HOTKEY_COPY_ID.includes(key)) {{
            e.preventDefault();
            copyId();
            return;
        }}
        if (HOTKEY_DOWNLOAD_EXTRACTED_ROWS.includes(key)) {{
            e.preventDefault();
            exportCurrent();
            return;
        }}
        if (HOTKEY_REJECT.includes(key)) {{
            e.preventDefault();
            rejectCurrent();
            return;
        }}
    }});

    const currentVersion = {version};
    setInterval(async () => {{
        try {{
            const resp = await fetch("/version");
            const v = parseInt(await resp.text());
            if (v !== currentVersion) {{
                window.location.href = "/?row=0";
            }}
        }} catch (e) {{}}
    }}, 250);
</script>
</body>
</html>'''


def visualize(spotcheck_results, port=8000):
    """
    Launch a local HTTP server in a background thread to browse spotcheck results.
    Returns immediately. Calling again shuts down the previous server first.
    Existing browser tabs auto-reload when new data is served.

    Args:
        spotcheck_results: list of dicts from spotcheck(..., return_details=True).
            Each dict has: id, fields, extracted_rows, context
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

    # Sort: fully incorrect files first, then partial, then fully correct
    def _sort_key(item):
        if _item_is_fully_correct(item):
            return 2
        counts = _item_verdict_counts(item)
        return 0 if counts else 1

    items = sorted(spotcheck_results, key=_sort_key)
    print(items)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed_url = urlparse(self.path)

            if parsed_url.path == "/version":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(str(current_version).encode())
                return

            params = parse_qs(parsed_url.query)
            try:
                row = int(params.get("row", [0])[0]) % len(items)
            except (ValueError, ZeroDivisionError):
                row = 0

            page = _render_page(items, row, current_version)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(page.encode())

        def do_POST(self):
            parsed_url = urlparse(self.path)

            if parsed_url.path not in {"/reject", "/export"}:
                self.send_response(404)
                self.end_headers()
                return

            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except Exception:
                content_length = 0

            payload = {}
            if content_length:
                try:
                    raw = self.rfile.read(content_length)
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    payload = {}

            try:
                row = int(payload.get("row", 0)) % len(items)
            except Exception:
                row = 0

            item = items[row]
            try:
                if parsed_url.path == "/reject":
                    result = _save_reject(item.get("id"))
                else:
                    result = _save_reject(item.get("id"), reject_file=config.DEFAULT_REJECT_ID_FILE)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(("", port), Handler)
    _current_server = server

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _current_thread = thread

    print(f"  Spotcheck visualizer: http://localhost:{port}")
    webbrowser.open(f"http://localhost:{port}")