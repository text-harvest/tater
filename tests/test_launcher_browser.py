"""Project launcher (#82) in a browser: annotators reach only their own tater.

The launcher runs on a thread in the pytest process (so tests can reissue links and
look at its processes); each annotator's tater is a real subprocess, as in use.
"""
import json
import textwrap
import threading
import time
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page
from werkzeug.serving import WSGIRequestHandler, make_server

from perf.browser import INIT_SCRIPT, control, wait_loaded, wait_position, wait_quiet
from tater.launcher.app import create_app
from tater.launcher.identity import CookieSigner, Identifier, LinkStore
from tater.launcher.project import load_project
from tater.launcher.supervisor import Supervisor

SCHEMA = {
    "spec_version": "1.0",
    "data_schema": [{"id": "note", "type": "text", "widget": {"type": "text_input", "label": "Note"}}],
}
DOCS = [{"id": f"d{i}", "name": f"Doc {i}", "text": f"Document number {i}."} for i in range(1, 4)]


class _Quiet(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


@pytest.fixture
def make_launcher(tmp_path):
    """``make_launcher(extra_yaml="") -> (url, project, supervisor, links)``."""
    running = []

    def make(extra: str = "", identity: str = "links"):
        (tmp_path / "schema.json").write_text(json.dumps(SCHEMA))
        (tmp_path / "documents.json").write_text(json.dumps(DOCS))
        body = textwrap.dedent("""\
            title: Launcher test
            schema: schema.json
            documents: documents.json
            results: results
        """)
        if identity == "header":
            body += textwrap.dedent("""\
                identity: header
                header: X-Forwarded-Email
                annotators:
                  - {name: alice, email: alice@example.org}
                  - {name: bob, email: bob@example.org}
            """)
        else:
            body += "annotators:\n  - name: alice\n  - name: bob\n"
        (tmp_path / "project.yaml").write_text(body + extra)
        project = load_project(tmp_path / "project.yaml")
        links = signer = None
        if identity == "links":
            links, signer = LinkStore(project), CookieSigner(project)
            links.ensure_all()
        sup = Supervisor(project, ready_timeout=60, stop_timeout=15)
        app = create_app(project, sup, Identifier(project, links, signer), links, signer)
        server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=_Quiet)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        running.append((server, sup))
        return f"http://127.0.0.1:{server.port}", project, sup, links

    yield make
    for server, sup in running:
        sup.shutdown()
        server.shutdown()
        server.server_close()


@pytest.fixture
def browser_page(browser):
    """``browser_page(**context_kwargs) -> Page`` in its own context (its own cookies)."""
    contexts = []

    def make(**kwargs) -> Page:
        ctx = browser.new_context(viewport={"width": 1400, "height": 1000}, **kwargs)
        ctx.add_init_script(INIT_SCRIPT)
        contexts.append(ctx)
        return ctx.new_page()

    yield make
    for ctx in contexts:
        ctx.close()


def open_link(page: Page, url: str, links: LinkStore, name: str) -> Page:
    token = links.ensure_all()[name]
    page.goto(f"{url}/join/{token}")
    wait_loaded(page)
    wait_quiet(page)
    return page


def type_note(page: Page, text: str) -> None:
    control(page, "note").fill(text)
    wait_quiet(page)


def saved_notes(path: Path, timeout: float = 10.0, expect: dict | None = None) -> dict:
    """{doc_id: note} from an annotations file, waiting (saves are throttled) until it
    matches ``expect`` if given."""
    deadline = time.time() + timeout
    while True:
        notes = {}
        if path.exists():
            try:
                data = json.loads(path.read_text())
                notes = {d: v["annotations"].get("note") for d, v in data.items() if v["annotations"].get("note")}
            except json.JSONDecodeError:
                pass
        if expect is None or notes == expect or time.time() > deadline:
            return notes
        time.sleep(0.2)


class TestLauncherBrowser:
    def test_annotators_kept_apart(self, make_launcher, browser_page):
        url, project, sup, links = make_launcher()
        alice = open_link(browser_page(), url, links, "alice")
        bob = open_link(browser_page(), url, links, "bob")
        type_note(alice, "from alice")
        type_note(bob, "from bob")
        assert saved_notes(project.annotation_path("alice"), expect={"d1": "from alice"}) == {"d1": "from alice"}
        assert saved_notes(project.annotation_path("bob"), expect={"d1": "from bob"}) == {"d1": "from bob"}
        # A reload shows each their own work.
        alice.reload()
        wait_loaded(alice)
        assert control(alice, "note").input_value() == "from alice"

    def test_stranger_sees_no_tater(self, make_launcher, browser_page):
        url, *_ = make_launcher()
        page = browser_page()
        resp = page.goto(url + "/")
        assert resp.status == 403
        assert page.get_by_text("Not part of this project").is_visible()
        assert page.locator("#document-title").count() == 0

    def test_reissued_link_locks_out_old_browser(self, make_launcher, browser_page):
        url, project, sup, links = make_launcher()
        old_token = links.ensure_all()["alice"]
        alice = open_link(browser_page(), url, links, "alice")
        links.reissue("alice")
        assert alice.goto(url + "/").status == 403
        assert alice.goto(f"{url}/join/{old_token}").status == 403
        fresh = open_link(browser_page(), url, links, "alice")
        assert fresh.locator("#document-title").is_visible()

    def test_two_tabs_one_annotator(self, make_launcher, browser_page):
        url, project, sup, links = make_launcher()
        first = open_link(browser_page(), url, links, "alice")
        second = first.context.new_page()
        second.goto(url + "/")
        wait_loaded(second)
        assert sup.children["alice"].starts == 1
        type_note(second, "second tab")
        assert saved_notes(project.annotation_path("alice"), expect={"d1": "second tab"}) == {"d1": "second tab"}

    def test_idle_stop_keeps_edits_and_page_keeps_working(self, make_launcher, browser_page):
        url, project, sup, links = make_launcher()
        page = open_link(browser_page(), url, links, "alice")
        type_note(page, "before stop")
        sup.stop("alice")  # what an idle stop does
        # The edit was written as the process exited, not left pending.
        assert saved_notes(project.annotation_path("alice"), timeout=0) == {"d1": "before stop"}
        # The open page carries on: the next action restarts the process.
        page.click("#btn-next")
        wait_position(page, 2)
        wait_quiet(page)
        type_note(page, "after restart")
        assert sup.children["alice"].starts == 2
        expect = {"d1": "before stop", "d2": "after restart"}
        assert saved_notes(project.annotation_path("alice"), expect=expect) == expect

    def test_idle_stop_by_monitor(self, make_launcher, browser_page):
        url, project, sup, links = make_launcher("idle_minutes: 0.02\n")  # 1.2 s
        page = open_link(browser_page(), url, links, "alice")
        type_note(page, "idle")
        time.sleep(1.5)
        sup.check()
        assert sup.children["alice"].state == "stopped"
        assert saved_notes(project.annotation_path("alice"), timeout=0) == {"d1": "idle"}

    def test_crash_then_reload(self, make_launcher, browser_page):
        url, project, sup, links = make_launcher()
        page = open_link(browser_page(), url, links, "alice")
        type_note(page, "saved")
        saved_notes(project.annotation_path("alice"), expect={"d1": "saved"})
        sup.children["alice"].proc.kill()
        sup.children["alice"].proc.wait()
        page.reload()
        wait_loaded(page)
        assert control(page, "note").input_value() == "saved"

    def test_header_mode(self, make_launcher, browser_page):
        url, project, sup, _ = make_launcher(identity="header")
        bob = browser_page(extra_http_headers={"X-Forwarded-Email": "bob@example.org"})
        bob.goto(url + "/")
        wait_loaded(bob)
        type_note(bob, "via header")
        assert saved_notes(project.annotation_path("bob"), expect={"d1": "via header"}) == {"d1": "via header"}
        eve = browser_page(extra_http_headers={"X-Forwarded-Email": "eve@example.org"})
        assert eve.goto(url + "/").status == 403

    def test_child_port_rejects_direct_requests(self, make_launcher, browser_page):
        url, project, sup, links = make_launcher()
        open_link(browser_page(), url, links, "alice")
        child = sup.children["alice"]
        assert requests.get(child.url + "/", timeout=5).status_code == 403
        assert requests.post(child.url + "/_dash-update-component", json={}, timeout=5).status_code == 403

    def test_admin_page_progress_and_reissue(self, make_launcher, browser_page):
        url, project, sup, links = make_launcher("admins:\n  - name: dana\n")
        alice = open_link(browser_page(), url, links, "alice")
        type_note(alice, "done")
        alice.click("#btn-next")  # leaving a document with a value marks it complete
        wait_position(alice, 2)
        wait_quiet(alice)
        sup.stop("alice")  # flushes the save

        old = links.ensure_all()["bob"]
        dana = browser_page()
        dana.goto(f"{url}/join/{links.ensure_all()['dana']}")
        row = dana.locator("tr", has_text="alice").first
        cells = row.locator("td").all_inner_texts()
        # d1 complete; d2, the document alice is on, in progress
        assert cells[1] == "stopped" and cells[3:7] == ["3", "1", "1", "0"]

        dana.on("dialog", lambda d: d.accept())
        dana.locator('form[action="/_launcher/reissue/bob"] button').click()
        dana.wait_for_url(f"{url}/_launcher/")
        new = links.ensure_all()["bob"]
        assert new != old and f"/join/{new}" in dana.content()
