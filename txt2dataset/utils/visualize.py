import html
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


_current_server = None
_current_thread = None
_version = 0


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
</style>
</head>
<body>
    {body}
    {nav}
<script>
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

        def log_message(self, fmt, *args):
            pass

    server = HTTPServer(("", port), Handler)
    _current_server = server

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _current_thread = thread

    print(f"  Spotcheck visualizer: http://localhost:{port}")
    webbrowser.open(f"http://localhost:{port}")