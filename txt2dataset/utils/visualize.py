import html
import json
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

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
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    return data if isinstance(data, list) else []


def _write_rejects(path, rejects):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(rejects, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _save_reject(reject_record, reject_file=None):
    path = _reject_path(reject_file)
    rejects = _load_rejects(path)

    reject_id = reject_record.get("id")
    existing = None
    for item in rejects:
        if item.get("id") == reject_id:
            existing = item
            break

    action = "added"
    if existing is not None:
        existing.update(reject_record)
        action = "updated"
    else:
        rejects.append(reject_record)

    _write_rejects(path, rejects)
    return {"ok": True, "file": str(path), "count": len(rejects), "action": action, "id": reject_id}


def _table(headers, rows, row_styles=None):
    """Build an HTML table."""
    out = '<table>'
    out += '<tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr>'
    for i, row in enumerate(rows):
        cls = ''
        if row_styles and i < len(row_styles) and row_styles[i]:
            cls = f' class="{row_styles[i]}"'
        out += f'<tr{cls}>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>'
    out += '</table>'
    return out


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
    """Render the spotcheck verdict as a small table."""
    passed = item["correct"]
    icon = '✅' if passed else '❌'
    style = 'pass-row' if passed else 'fail-row'
    rows = [
        [icon, html.escape(item.get("desc", "") or "—")],
    ]
    return '<h3>Spot Check</h3>' + _table(["Result", "Description"], rows, row_styles=[style])


def _render_summary(items):
    """Render a summary header: Correct / Error counts and percentage."""
    total = len(items)
    errors = sum(1 for x in items if not x.get("correct", True))
    correct = total - errors
    pct = (correct / total * 100) if total else 0
    return (
        f'<div class="summary">'
        f'<span class="summary-correct">Correct: {correct}</span>'
        f'<span class="summary-error">Error: {errors}</span>'
        f'<span class="summary-pct">{pct:.0f}% pass rate</span>'
        f'</div>'
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
        padding: 10px 14px;
        background: #fafafa;
        border: 1px solid #ddd;
        border-radius: 4px;
        margin-bottom: 16px;
        font-size: 15px;
        font-weight: 600;
    }}
    .summary-correct {{ color: #2e7d32; }}
    .summary-error {{ color: #c62828; }}
    .summary-pct {{ color: #555; margin-left: auto; }}
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
    .pass-row {{ background: #e8f5e9; }}
    .fail-row {{ background: #ffebee; }}
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
    const HOTKEY_REJECT = {_json_for_script(config.HOTKEY_REJECT)};

    const PREV_URL = "/?row={prev_idx}";
    const NEXT_URL = "/?row={next_idx}";
    const CURRENT_ROW = {index};
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
            Each dict has: id, correct, desc, extracted_rows, context
        port: port to serve on (default 8000)
    """
    global _current_server, _current_thread, _version

    if not spotcheck_results:
        print("Nothing to visualize.")
        return

    # Shut down previous server if running
    if _current_server is not None:
        _current_server.shutdown()
        _current_server.server_close()
        _current_server = None
        _current_thread = None

    _version += 1
    current_version = _version

    # Sort errors first
    items = sorted(spotcheck_results, key=lambda x: x.get("correct", True))

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

            if parsed_url.path != "/reject":
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
            record = {
                "id": item.get("id"),
                "rejected_at": datetime.now(timezone.utc).isoformat(),
                "correct": item.get("correct", True),
                "verdict": item.get("verdict"),
                "desc": item.get("desc", ""),
                "extracted_rows": item.get("extracted_rows", []),
                "context": item.get("context", ""),
            }

            try:
                result = _save_reject(record)
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
