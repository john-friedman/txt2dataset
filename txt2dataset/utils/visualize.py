import html
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import webbrowser


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
    """Render the list of extracted row dicts as a table."""
    if not extracted_rows:
        return '<p>No extracted rows.</p>'
    headers = list(extracted_rows[0].keys())
    rows = [[html.escape(str(row.get(h, ''))) for h in headers] for row in extracted_rows]
    return f'<h3>Extracted Rows</h3>' + _table(headers, rows)


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
    return f'<h3>Spot Check</h3>' + _table(["Result", "Description"], rows, row_styles=[style])


def _render_page(items, index):
    """Build a full HTML page for one spotcheck result."""
    total = len(items)
    item = items[index]
    prev_idx = (index - 1) % total
    next_idx = (index + 1) % total

    sections = [
        _render_extracted_rows(item.get("extracted_rows", [])),
        _render_context(item.get("context", "")),
        _render_verdict(item),
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
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 20px;
    }}
    th, td {{
        border: 1px solid #ddd;
        padding: 8px 12px;
        text-align: left;
    }}
    th {{
        background: #f5f5f5;
        font-weight: 600;
    }}
    .pass-row {{ background: #e8f5e9; }}
    .fail-row {{ background: #ffebee; }}
    pre {{
        background: #f5f5f5;
        padding: 14px;
        border: 1px solid #ddd;
        white-space: pre-wrap;
        word-wrap: break-word;
        max-height: 400px;
        overflow-y: auto;
    }}
    .nav {{
        display: flex;
        align-items: center;
        gap: 12px;
        margin: 20px 0;
    }}
    .nav button {{
        padding: 8px 20px;
        font-size: 15px;
        cursor: pointer;
    }}
    .counter {{
        font-size: 14px;
        color: #666;
    }}
    h3 {{
        margin-top: 28px;
        margin-bottom: 8px;
    }}
</style>
</head>
<body>
    {body}
    {nav}
</body>
</html>'''


def visualize(spotcheck_results, port=8000):
    """
    Launch a local HTTP server to browse spotcheck results.

    Args:
        spotcheck_results: list of dicts from spotcheck(..., return_details=True).
            Each dict has: id, correct, desc, extracted_rows, context
        port: port to serve on (default 8000)
    """
    if not spotcheck_results:
        print("Nothing to visualize.")
        return

    items = spotcheck_results

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlparse(self.path).query)
            try:
                row = int(params.get("row", [0])[0]) % len(items)
            except (ValueError, ZeroDivisionError):
                row = 0

            page = _render_page(items, row)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(page.encode())

        def log_message(self, fmt, *args):
            pass  # quiet

    print(f"Spotcheck visualizer: http://localhost:{port}")
    print(f"Browsing {len(items)} entries. Ctrl+C to stop.")
    webbrowser.open(f"http://localhost:{port}")
    HTTPServer(("", port), Handler).serve_forever()