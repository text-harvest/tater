"""Pass a request to an annotator's tater process and its answer back.

Tater serves everything from ``/`` with ordinary HTTP requests, so this is a
plain pass-through: no path rewriting, no websockets. Bodies are streamed
undecoded, so compressed responses keep their encoding and length.
"""
from __future__ import annotations

from typing import Iterable, Optional

import requests
from flask import Response

from tater.launcher.identity import COOKIE_NAME
from tater.ui.runner import LAUNCHER_TOKEN_HEADER

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade",
}


def strip_cookie(header: str, name: str) -> str:
    """The ``Cookie`` header without the cookie ``name``."""
    parts = [p.strip() for p in header.split(";")]
    return "; ".join(p for p in parts if p and not p.startswith(name + "="))


def request_headers(incoming, token: str, identity_header: Optional[str]) -> dict:
    drop = HOP_BY_HOP | {"host", "content-length", LAUNCHER_TOKEN_HEADER.lower()}
    if identity_header:
        drop.add(identity_header.lower())
    headers = {k: v for k, v in incoming.items() if k.lower() not in drop}
    cookie = headers.pop("Cookie", None)
    if cookie:
        cookie = strip_cookie(cookie, COOKIE_NAME)
        if cookie:
            headers["Cookie"] = cookie
    headers[LAUNCHER_TOKEN_HEADER] = token
    return headers


def _header_items(raw_headers) -> Iterable[tuple[str, str]]:
    """Every header line, repeated ones (e.g. Set-Cookie) kept separate."""
    items = getattr(raw_headers, "iteritems", None)
    return items() if items else raw_headers.items()


def forward(flask_request, child, identity_header: Optional[str] = None) -> Response:
    """Send ``flask_request`` to ``child`` and return its response.

    Raises ``requests.ConnectionError`` if the process can't be reached.
    """
    # The path as the browser sent it (Werkzeug's server sets RAW_URI), so percent-
    # encoding passes through unchanged; else rebuild it.
    raw = flask_request.environ.get("RAW_URI") or flask_request.environ.get("REQUEST_URI")
    if not raw:
        from urllib.parse import quote
        raw = quote(flask_request.path)
        if flask_request.query_string:
            raw += "?" + flask_request.query_string.decode("latin-1")
    url = child.url + raw
    upstream = child.session.request(
        flask_request.method,
        url,
        headers=request_headers(flask_request.headers, child.token, identity_header),
        data=flask_request.get_data(),
        stream=True,
        allow_redirects=False,
        timeout=(5, 300),
    )
    headers = [(k, v) for k, v in _header_items(upstream.raw.headers) if k.lower() not in HOP_BY_HOP]

    def body():
        try:
            yield from upstream.raw.stream(65536, decode_content=False)
        finally:
            upstream.close()

    return Response(body(), status=upstream.status_code, headers=headers, direct_passthrough=True)
