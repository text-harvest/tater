"""The launcher's web app: one address in front of every annotator's tater.

``/join/<token>``     opens a personal link (links mode)
``/_launcher/``       the admin's status page
``/_launcher/health`` 200 for platform health probes
everything else       forwarded to the caller's own tater process
"""
from __future__ import annotations

from html import escape

import requests
from flask import Flask, make_response, redirect, request

from tater.launcher import pages
from tater.launcher.identity import COOKIE_MAX_AGE, COOKIE_NAME, CookieSigner, Identifier, LinkStore
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

    @app.get("/_launcher/")
    def status_page():
        name = identifier.identify(request)
        if not identifier.is_admin(name):
            return pages.not_in_project(title)
        status = supervisor.status()
        rows = "".join(
            f"<tr><td>{escape(n)}</td><td>{escape(s['state'])}</td>"
            f"<td>{escape(s['last_request'] or '—')}</td><td class=num>{s['starts']}</td>"
            f"<td class=num>{s['crashes']}</td>"
            f"<td><code>{escape(str(project.annotation_path(n)))}</code></td></tr>"
            for n, s in status["annotators"].items()
        )
        return pages.page(
            title,
            "<table><tr><th>Annotator</th><th>State</th><th>Last request</th><th>Starts</th>"
            f"<th>Crashes</th><th>Results file</th></tr>{rows}</table>",
            refresh=30,
        )

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
