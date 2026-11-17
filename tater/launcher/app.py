"""The launcher's web app: one address in front of every annotator's tater.

``/join/<token>``     opens a personal link (links mode)
``/_launcher/``       the admin's status page
``/_launcher/reissue/<name>``  POST: replace a person's link (links mode, admins)
``/_launcher/health`` 200 for platform health probes
everything else       forwarded to the caller's own tater process
"""
from __future__ import annotations

from html import escape
from urllib.parse import urlsplit

import requests
from flask import Flask, make_response, redirect, request

from tater.launcher import pages
from tater.launcher.identity import COOKIE_MAX_AGE, COOKIE_NAME, CookieSigner, Identifier, LinkStore
from tater.launcher.progress import COLUMNS, ProgressCounter, row_cells, status_rows
from tater.launcher.project import Project
from tater.launcher.proxy import forward
from tater.launcher.supervisor import ChildUnavailable, Supervisor

METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def create_app(
    project: Project,
    supervisor: Supervisor,
    identifier: Identifier,
    links: LinkStore | None = None,
    signer: CookieSigner | None = None,
) -> Flask:
    app = Flask("tater.launcher")
    title = project.file.title
    secure_cookie = (project.file.public_url or "").startswith("https://")
    identity_header = project.file.header if project.file.identity == "header" else None

    @app.get("/join/<token>")
    def join(token):
        if links is None:
            return pages.not_in_project(title)
        found = links.find(token)
        if found is None:
            return pages.bad_link(title)
        name, generation = found
        target = "/" if identifier.is_annotator(name) else "/_launcher/"
        resp = make_response(redirect(target))
        resp.set_cookie(
            COOKIE_NAME, signer.dumps(name, generation), max_age=COOKIE_MAX_AGE,
            httponly=True, samesite="Lax", secure=secure_cookie, path="/",
        )
        return resp

    @app.get("/_launcher/health")
    def health():
        return "ok\n"

    progress = ProgressCounter(project)
    numeric = {3, 4, 5, 6}

    def _origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}".lower()

    def _same_origin() -> bool:
        """A POST from our own page: Origin (or, failing that, Referer) is this address
        or the project's public_url."""
        sent = request.headers.get("Origin") or request.headers.get("Referer")
        if not sent or sent == "null":
            return False
        allowed = {_origin(request.host_url)}
        if project.file.public_url:
            allowed.add(_origin(project.file.public_url))
        return _origin(sent) in allowed

    def _links_html(me: str) -> str:
        base = project.file.public_url or request.host_url.rstrip("/")
        tokens = links.ensure_all()
        roles = {}
        for a in project.annotators:
            roles.setdefault(a.name, []).append("annotator")
        for a in project.admins:
            roles.setdefault(a.name, []).append("admin")
        rows = []
        for n, token in tokens.items():
            if n == me:
                action = "<span class=muted>your own; reissue from the shell</span>"
            else:
                action = (f'<form method=post action="/_launcher/reissue/{escape(n)}" '
                          f'onsubmit="return confirm(\'Replace the link for {escape(n)}? The old one stops working.\')">'
                          "<button>Reissue</button></form>")
            rows.append(f"<tr><td>{escape(n)}</td><td>{escape(', '.join(roles[n]))}</td>"
                        f"<td><code>{escape(base)}/join/{escape(token)}</code></td><td>{action}</td></tr>")
        return ("<h2>Links</h2><p>Each link is a password: send it only to its person. Reissuing "
                "one signs out every browser that opened the old one.</p>"
                "<table><tr><th>Person</th><th>Role</th><th>Link</th><th></th></tr>"
                f"{''.join(rows)}</table>")

    @app.get("/_launcher/")
    def status_page():
        name = identifier.identify(request)
        if not identifier.is_admin(name):
            return pages.not_in_project(title)
        head = "".join(f"<th{' class=num' if i in numeric else ''}>{c}</th>" for i, c in enumerate(COLUMNS))
        body = ""
        for row in status_rows(project, supervisor.status(), progress):
            cells = row_cells(row)
            cells[-1] = f"<code>{escape(cells[-1])}</code>"
            body += "<tr>" + "".join(
                f"<td{' class=num' if i in numeric else ''}>{c if i == len(cells) - 1 else escape(c)}</td>"
                for i, c in enumerate(cells)
            ) + "</tr>"
        html = f"<table><tr>{head}</tr>{body}</table>"
        if links is not None:
            html += _links_html(name)
        return pages.page(title, html, refresh=30)

    @app.post("/_launcher/reissue/<who>")
    def reissue(who):
        name = identifier.identify(request)
        if links is None or not identifier.is_admin(name):
            return "Forbidden\n", 403
        if not _same_origin():
            return "Forbidden: cross-site request\n", 403
        if who == name:
            return "Reissue your own link from the shell: tater-launcher reissue\n", 400
        try:
            links.reissue(who)
        except KeyError:
            return "Not in the project\n", 404
        return redirect("/_launcher/", code=303)

    @app.route("/", defaults={"path": ""}, methods=METHODS)
    @app.route("/<path:path>", methods=METHODS)
    def to_annotator(path):
        name = identifier.identify(request)
        if not identifier.is_annotator(name):
            if identifier.is_admin(name) and request.method == "GET" and path == "":
                return redirect("/_launcher/")
            if request.method == "GET":
                return pages.not_in_project(title)
            return "Forbidden: not part of this project\n", 403
        try:
            child = supervisor.ensure_running(name)
        except ChildUnavailable as e:
            app.logger.error(str(e))
            return pages.unavailable(title)
        try:
            return forward(request, child, identity_header)
        except requests.ConnectionError:
            supervisor.mark_unreachable(child)
            return pages.unavailable(title)

    return app
