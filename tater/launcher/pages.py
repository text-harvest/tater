"""The launcher's own small pages: plain HTML, no Dash."""
from __future__ import annotations

from html import escape

from flask import Response

_STYLE = """
:root { color-scheme: light dark; --fg: #1f2328; --muted: #59636e; --bg: #fff; --line: #d1d9e0; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6edf3; --muted: #9198a1; --bg: #0d1117; --line: #3d444d; } }
body { font: 15px/1.5 system-ui, sans-serif; color: var(--fg); background: var(--bg); margin: 0; }
main { max-width: 960px; margin: 48px auto; padding: 0 16px; }
h1 { font-size: 20px; margin: 0 0 12px; }
h2 { font-size: 16px; margin: 32px 0 8px; }
.muted { color: var(--muted); font-size: 13px; }
form { margin: 0; }
p { color: var(--muted); }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
code { font-size: 13px; word-break: break-all; }
button { font: inherit; font-size: 13px; padding: 2px 8px; }
"""


def page(title: str, body_html: str, status: int = 200, refresh: int | None = None) -> Response:
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    html = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">{meta}'
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body><main><h1>{escape(title)}</h1>{body_html}</main></body></html>"
    )
    return Response(html, status=status, mimetype="text/html")


def not_in_project(project_title: str) -> Response:
    return page(
        "Not part of this project",
        f"<p>This address is for the annotators of <b>{escape(project_title)}</b>, and you're not "
        "signed in as one of them. If you are, open the personal link you were sent, or ask the "
        "project's admin for a new one.</p>",
        status=403,
    )


def bad_link(project_title: str) -> Response:
    return page(
        "This link doesn't work",
        f"<p>This link for <b>{escape(project_title)}</b> isn't valid, perhaps because a new one was "
        "issued. Ask the project's admin for your current link.</p>",
        status=403,
    )


def unavailable(project_title: str) -> Response:
    return page(
        "Your session couldn't start",
        f"<p>Tater for <b>{escape(project_title)}</b> couldn't be started or reached for you. Your saved "
        "work is safe. Reload the page in a moment; if this keeps happening, tell the project's admin.</p>",
        status=502,
    )
