"""Project launcher (#82): project file, CLI, and tater's launcher-token check. No browser."""
import json
import textwrap
from pathlib import Path

import pytest
from flask import Flask

from tater.launcher.cli import main as launcher_main
from tater.launcher.project import ProjectError, check_project, load_project
from tater.ui.runner import LAUNCHER_TOKEN_HEADER, _require_launcher_token

SCHEMA = {
    "spec_version": "1.0",
    "data_schema": [
        {"id": "note", "type": "text", "widget": {"type": "text_input", "label": "Note"}},
        {"id": "mood", "type": "choice", "options": ["happy", "sad"]},
    ],
}


def _schema_ok() -> bool:
    """SCHEMA must load with the current JSON loader, or every test here is moot."""
    from tater.loaders import parse_schema
    model, _ = parse_schema(SCHEMA)
    return set(model.model_fields) == {"note", "mood"}


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / "schema.json").write_text(json.dumps(SCHEMA))
    (tmp_path / "documents.json").write_text(json.dumps([{"id": f"d{i}", "text": "x"} for i in range(3)]))
    (tmp_path / "splits").mkdir()
    (tmp_path / "splits" / "bob.json").write_text(json.dumps([{"id": "d9", "text": "y"}]))
    return tmp_path


def write(project_dir: Path, body: str, name="project.yaml") -> Path:
    p = project_dir / name
    p.write_text(textwrap.dedent(body))
    return p


MINIMAL = textwrap.dedent("""\
    schema: schema.json
    documents: documents.json
    results: results
    annotators:
      - name: alice
      - name: bob
        documents: splits/bob.json
""")


class TestLoadProject:
    def test_schema_fixture_loads(self):
        assert _schema_ok()

    def test_minimal(self, project_dir):
        project = load_project(write(project_dir, MINIMAL))
        assert project.file.identity == "links"
        assert project.file.idle_minutes == 30
        assert project.schema_path == project_dir / "schema.json"
        assert project.config_path is None
        assert project.documents_path("alice") == project_dir / "documents.json"
        assert project.documents_path("bob") == project_dir / "splits" / "bob.json"
        assert project.annotation_path("alice") == project_dir / "results" / "alice" / "annotations.json"
        assert project.state_dir == project_dir / "project.launcher"

    def test_paths_relative_to_project_file_not_cwd(self, project_dir, tmp_path_factory, monkeypatch):
        monkeypatch.chdir(tmp_path_factory.mktemp("elsewhere"))
        project = load_project(write(project_dir, MINIMAL))
        assert project.results_dir == project_dir / "results"

    def test_header_mode(self, project_dir):
        project = load_project(write(project_dir, """\
            schema: schema.json
            documents: documents.json
            results: results
            identity: header
            header: X-Forwarded-Email
            public_url: https://tater.example.org/
            annotators:
              - {name: alice, email: Alice@Example.org}
            admins:
              - {name: dana, email: dana@example.org}
        """))
        assert project.annotators[0].email == "alice@example.org"
        assert project.file.public_url == "https://tater.example.org"

    def test_admin_may_also_annotate(self, project_dir):
        project = load_project(write(project_dir, MINIMAL + "admins:\n  - name: alice\n"))
        assert project.admins[0].name == "alice"

    @pytest.mark.parametrize("body, expected", [
        ("documents: documents.json\nresults: r\nannotators: [{name: a}]\n", "exactly one of 'schema'"),
        ("schema: schema.json\nconfig: c.py\ndocuments: documents.json\nresults: r\nannotators: [{name: a}]\n",
         "exactly one of 'schema'"),
        ("schema: schema.json\ndocuments: documents.json\nresults: r\nannotators: []\n", "annotators"),
        ("schema: schema.json\ndocuments: documents.json\nresults: r\nannotators: [{name: Alice}]\n", "lower-case"),
        ("schema: schema.json\ndocuments: documents.json\nresults: r\nannotators: [{name: a}, {name: a}]\n",
         "unique: a"),
        ("schema: schema.json\ndocuments: documents.json\nresults: r\nidentity: header\n"
         "annotators: [{name: a, email: a@x}]\n", "needs 'header'"),
        ("schema: schema.json\ndocuments: documents.json\nresults: r\nidentity: header\nheader: X-E\n"
         "annotators: [{name: a}]\n", "needs an email for: a"),
        ("schema: schema.json\ndocuments: documents.json\nresults: r\nidentity: header\nheader: X-E\n"
         "annotators: [{name: a, email: s@x}, {name: b, email: S@x}]\n", "emails must be unique"),
        ("schema: schema.json\ndocuments: documents.json\nresults: r\nannotators: [{name: a}]\nidle: 5\n",
         "idle: not a project file setting"),
        ("schema: schema.json\ndocuments: documents.json\nresults: r\nannotators: [{name: a}]\nidle_minutes: -1\n",
         "idle_minutes"),
        ("schema: schema.json\ndocuments: documents.json\nresults: r\nidentity: sso\nannotators: [{name: a}]\n",
         "identity"),
        ("schema: schema.json\ndocuments: documents.json\nresults: r\n"
         "annotators: [{name: a, email: a@x}]\nadmins: [{name: a, email: b@x}]\n", "different emails"),
    ])
    def test_invalid(self, project_dir, body, expected):
        with pytest.raises(ProjectError, match=expected):
            load_project(write(project_dir, body))

    def test_missing_files_listed(self, project_dir):
        with pytest.raises(ProjectError) as e:
            load_project(write(project_dir, """\
                schema: nope.json
                documents: documents.json
                results: results
                annotators: [{name: a, documents: gone.json}]
            """))
        assert "nope.json" in str(e.value) and "gone.json" in str(e.value)

    def test_not_yaml_mapping(self, project_dir):
        with pytest.raises(ProjectError, match="mapping"):
            load_project(write(project_dir, "- just\n- a list\n"))

    def test_missing_project_file(self, tmp_path):
        with pytest.raises(ProjectError, match="not found"):
            load_project(tmp_path / "nope.yaml")


class TestCheckProject:
    def test_reports_counts(self, project_dir):
        report = check_project(load_project(write(project_dir, MINIMAL)))
        assert "alice: 3 documents from documents.json" in report
        assert "bob: 1 documents from bob.json" in report

    def test_bad_documents(self, project_dir):
        (project_dir / "documents.json").write_text("{not json")
        with pytest.raises(ProjectError, match="don't load"):
            check_project(load_project(write(project_dir, MINIMAL)))

    def test_config_without_defaults(self, project_dir):
        (project_dir / "config.py").write_text(
            "from pydantic import BaseModel\nclass Schema(BaseModel):\n    mood: str\n")
        body = MINIMAL.replace("schema: schema.json", "config: config.py")
        with pytest.raises(ProjectError, match="needs a default.*mood"):
            check_project(load_project(write(project_dir, body)))

    def test_cli_check(self, project_dir, capsys):
        assert launcher_main(["check", str(write(project_dir, MINIMAL))]) == 0
        assert capsys.readouterr().out.strip().endswith("ok")

    def test_cli_check_error(self, project_dir, capsys):
        assert launcher_main(["check", str(project_dir / "nope.yaml")]) == 2
        assert "not found" in capsys.readouterr().err


class TestLauncherToken:
    """tater's single mode, when started by the launcher, rejects requests without its token."""

    def _client(self, token):
        server = Flask(__name__)
        server.add_url_rule("/", "index", lambda: "page")
        _require_launcher_token(server, token)
        return server.test_client()

    def test_rejects_missing_or_wrong_token(self):
        client = self._client("s3cret")
        assert client.get("/").status_code == 403
        assert client.get("/", headers={LAUNCHER_TOKEN_HEADER: "wrong"}).status_code == 403

    def test_accepts_right_token(self):
        client = self._client("s3cret")
        assert client.get("/", headers={LAUNCHER_TOKEN_HEADER: "s3cret"}).data == b"page"

    def test_nothing_without_token(self):
        assert self._client(None).get("/").data == b"page"


# ---------------------------------------------------------------------------
# Supervisor: real tater processes (about a second each to start)
# ---------------------------------------------------------------------------

import requests  # noqa: E402

from tater.launcher.supervisor import ChildUnavailable, Supervisor  # noqa: E402


@pytest.fixture
def supervisor(project_dir):
    sup = Supervisor(load_project(write(project_dir, MINIMAL)), ready_timeout=30, stop_timeout=10)
    yield sup
    sup.shutdown()


class TestSupervisor:
    def test_starts_on_demand_and_requires_token(self, supervisor, project_dir):
        assert supervisor.children["alice"].state == "stopped"
        child = supervisor.ensure_running("alice")
        assert child.state == "running" and child.alive()
        assert supervisor.children["bob"].state == "stopped"  # only who asked
        assert requests.get(child.url + "/", timeout=5).status_code == 403
        r = requests.get(child.url + "/", headers={LAUNCHER_TOKEN_HEADER: child.token}, timeout=5)
        assert r.status_code == 200
        assert (project_dir / "results" / "alice" / "tater.log").exists()
        assert supervisor.ensure_running("alice") is child and child.starts == 1

    def test_uses_annotators_own_documents(self, supervisor):
        child = supervisor.ensure_running("bob")
        layout = requests.get(child.url + "/_dash-layout", headers={LAUNCHER_TOKEN_HEADER: child.token}, timeout=10)
        assert '"d9"' in layout.text and '"d0"' not in layout.text

    def test_stop_then_restart(self, supervisor):
        child = supervisor.ensure_running("alice")
        proc = child.proc
        supervisor.stop("alice")
        assert proc.poll() is not None and child.state == "stopped"
        supervisor.ensure_running("alice")
        assert child.alive() and child.starts == 2

    def test_crash_noticed_and_restarted(self, supervisor):
        child = supervisor.ensure_running("alice")
        child.proc.kill()
        child.proc.wait()
        supervisor.check()
        assert child.state == "crashed"
        supervisor.ensure_running("alice")
        assert child.state == "running"

    def test_gives_up_after_repeated_crashes(self, supervisor, project_dir):
        (project_dir / "schema.json").write_text("{broken")  # the process exits while starting
        for _ in range(3):
            with pytest.raises(ChildUnavailable, match="exited while starting"):
                supervisor.ensure_running("alice")
        assert supervisor.children["alice"].state == "failed"
        with pytest.raises(ChildUnavailable, match="won't be restarted"):
            supervisor.ensure_running("alice")

    def test_idle_process_stopped(self, supervisor):
        supervisor.project.file.idle_minutes = 0.001  # 60 ms
        child = supervisor.ensure_running("alice")
        supervisor.check()
        assert child.state == "running"  # just started counts as a request
        import time
        time.sleep(0.2)
        supervisor.check()
        assert child.state == "stopped" and not child.alive()

    def test_status_file(self, supervisor):
        supervisor.ensure_running("alice")
        supervisor.check()
        status = json.loads((supervisor.project.state_dir / "status.json").read_text())
        assert status["running"] is True
        assert status["annotators"]["alice"]["state"] == "running"
        assert status["annotators"]["bob"]["state"] == "stopped"


# ---------------------------------------------------------------------------
# Identity: links, cookies, header
# ---------------------------------------------------------------------------

import os  # noqa: E402
import stat  # noqa: E402
import threading  # noqa: E402

from werkzeug.serving import make_server  # noqa: E402

from tater.launcher.app import create_app  # noqa: E402
from tater.launcher.identity import COOKIE_NAME, CookieSigner, Identifier, LinkStore  # noqa: E402
from tater.launcher.proxy import forward, request_headers, strip_cookie  # noqa: E402

HEADER_PROJECT = """\
schema: schema.json
documents: documents.json
results: results
identity: header
header: X-Forwarded-Email
annotators:
  - {name: alice, email: alice@example.org}
  - {name: bob, email: bob@example.org, documents: splits/bob.json}
admins:
  - {name: dana, email: dana@example.org}
"""


class _Req:
    """The bits of a request Identifier reads."""
    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}


class TestIdentity:
    def test_links_created_once_and_private(self, project_dir):
        project = load_project(write(project_dir, MINIMAL + "admins:\n  - name: dana\n"))
        store = LinkStore(project)
        first = store.ensure_all()
        assert set(first) == {"alice", "bob", "dana"}
        assert LinkStore(project).ensure_all() == first
        assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(project.state_dir).st_mode) == 0o700

    def test_reissue_invalidates_link_and_cookie(self, project_dir):
        project = load_project(write(project_dir, MINIMAL))
        store, signer = LinkStore(project), CookieSigner(project)
        ident = Identifier(project, store, signer)
        old = store.ensure_all()["alice"]
        cookie = signer.dumps(*store.find(old))
        assert ident.identify(_Req({COOKIE_NAME: cookie})) == "alice"
        new = LinkStore(project).reissue("alice")  # e.g. from the CLI, another process
        assert store.find(old) is None and store.find(new) == ("alice", 2)
        assert ident.identify(_Req({COOKIE_NAME: cookie})) is None
        assert ident.identify(_Req({COOKIE_NAME: signer.dumps("alice", 2)})) == "alice"

    def test_forged_cookie_rejected(self, project_dir):
        project = load_project(write(project_dir, MINIMAL))
        store, signer = LinkStore(project), CookieSigner(project)
        store.ensure_all()
        ident = Identifier(project, store, signer)
        good = signer.dumps("alice", 1)
        assert ident.identify(_Req({COOKIE_NAME: good[:-2] + "xx"})) is None
        other_key = CookieSigner(load_project(write(project_dir, MINIMAL, name="other.yaml")))
        assert ident.identify(_Req({COOKIE_NAME: other_key.dumps("alice", 1)})) is None

    def test_header_mode(self, project_dir):
        project = load_project(write(project_dir, HEADER_PROJECT))
        ident = Identifier(project)
        assert ident.identify(_Req(headers={"X-Forwarded-Email": " Alice@Example.org "})) == "alice"
        assert ident.identify(_Req(headers={"X-Forwarded-Email": "eve@example.org"})) is None
        assert ident.identify(_Req(headers={})) is None
        dana = ident.identify(_Req(headers={"X-Forwarded-Email": "dana@example.org"}))
        assert ident.is_admin(dana) and not ident.is_annotator(dana)


class TestProxyHeaders:
    def test_strip_cookie(self):
        assert strip_cookie("a=1; tater_launcher=x; b=2", "tater_launcher") == "a=1; b=2"
        assert strip_cookie("tater_launcher=x", "tater_launcher") == ""

    def test_request_headers(self):
        incoming = {"Host": "h", "Connection": "keep-alive", "Cookie": f"{COOKIE_NAME}=v", "Accept": "*/*",
                    "X-Forwarded-Email": "a@x", "X-Tater-Launcher-Token": "spoofed"}
        out = request_headers(incoming, "tok", "X-Forwarded-Email")
        assert out == {"Accept": "*/*", LAUNCHER_TOKEN_HEADER: "tok"}


class TestForward:
    """Against a stub server: bodies and repeated headers pass through untouched."""

    @pytest.fixture
    def stub(self):
        import gzip
        stub = Flask("stub")
        seen = {}

        @stub.route("/<path:p>", methods=["GET", "POST"])
        def echo(p):
            from flask import Response, request as r
            seen.update(path=r.full_path, body=r.get_data(), token=r.headers.get(LAUNCHER_TOKEN_HEADER))
            resp = Response(gzip.compress(b"hello" * 100), headers={"Content-Encoding": "gzip"})
            resp.headers.add("Set-Cookie", "a=1")
            resp.headers.add("Set-Cookie", "b=2")
            return resp

        server = make_server("127.0.0.1", 0, stub, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        child = type("C", (), {})()
        child.url, child.token, child.session = f"http://127.0.0.1:{server.port}", "tok", requests.Session()
        yield child, seen
        server.shutdown()

    def test_passes_through(self, stub):
        import gzip
        child, seen = stub
        front = Flask("front")

        @front.route("/<path:p>", methods=["GET", "POST"])
        def go(p):
            from flask import request as r
            return forward(r, child)

        resp = front.test_client().post("/x/y?q=1", data=b"payload")
        assert seen == {"path": "/x/y?q=1", "body": b"payload", "token": "tok"}
        assert resp.headers["Content-Encoding"] == "gzip"
        assert gzip.decompress(resp.data) == b"hello" * 100
        assert resp.headers.getlist("Set-Cookie") == ["a=1", "b=2"]


# ---------------------------------------------------------------------------
# The launcher app, with real tater processes behind it
# ---------------------------------------------------------------------------

@pytest.fixture
def launcher(project_dir):
    project = load_project(write(project_dir, MINIMAL + "admins:\n  - name: dana\n"))
    links, signer = LinkStore(project), CookieSigner(project)
    tokens = links.ensure_all()
    sup = Supervisor(project, ready_timeout=30, stop_timeout=10)
    app = create_app(project, sup, Identifier(project, links, signer), links, signer)
    yield app, tokens, links, sup
    sup.shutdown()


def _join(app, token):
    client = app.test_client()
    resp = client.get(f"/join/{token}")
    return client, resp


class TestLauncherApp:
    def test_stranger_gets_no_tater(self, launcher):
        app, *_ = launcher
        resp = app.test_client().get("/")
        assert resp.status_code == 403 and b"Not part of this project" in resp.data
        assert app.test_client().post("/_dash-update-component", data=b"{}").status_code == 403

    def test_bad_link(self, launcher):
        app, *_ = launcher
        assert app.test_client().get("/join/nope").status_code == 403

    def test_each_annotator_reaches_their_own(self, launcher):
        app, tokens, _, sup = launcher
        alice, resp = _join(app, tokens["alice"])
        assert resp.status_code == 302 and resp.headers["Location"] == "/"
        bob, _ = _join(app, tokens["bob"])
        assert alice.get("/").status_code == 200
        a_layout, b_layout = alice.get("/_dash-layout").text, bob.get("/_dash-layout").text
        assert '"d0"' in a_layout and '"d9"' not in a_layout
        assert '"d9"' in b_layout and '"d0"' not in b_layout
        assert sup.children["alice"].port != sup.children["bob"].port

    def test_cookie_flags(self, launcher):
        app, tokens, *_ = launcher
        _, resp = _join(app, tokens["alice"])
        cookie = resp.headers["Set-Cookie"]
        assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Max-Age=31536000" in cookie
        assert "Secure" not in cookie  # no https public_url

    def test_reissue_locks_out_old_browser(self, launcher):
        app, tokens, links, _ = launcher
        alice, _ = _join(app, tokens["alice"])
        assert alice.get("/").status_code == 200
        links.reissue("alice")
        assert alice.get("/").status_code == 403
        assert _join(app, tokens["alice"])[1].status_code == 403

    def test_admin_page(self, launcher):
        app, tokens, *_ = launcher
        dana, resp = _join(app, tokens["dana"])
        assert resp.headers["Location"] == "/_launcher/"
        assert dana.get("/").headers["Location"] == "/_launcher/"
        page = dana.get("/_launcher/")
        assert page.status_code == 200 and b"alice" in page.data
        alice, _ = _join(app, tokens["alice"])
        assert alice.get("/_launcher/").status_code == 403

    def test_admin_page_shows_progress_and_links(self, launcher, project_dir):
        app, tokens, *_ = launcher
        _write_results(project_dir / "results" / "alice" / "annotations.json",
                       {"d0": ("complete", True), "d1": ("in_progress", False)})
        dana, _ = _join(app, tokens["dana"])
        html = dana.get("/_launcher/").text
        assert "<th class=num>Complete</th>" in html
        alice_row = html[html.index("<td>alice</td>"):].split("</tr>")[0]
        assert [c for c in _cells(alice_row)][3:7] == ["3", "1", "1", "1"]
        assert f"/join/{tokens['bob']}" in html
        assert 'action="/_launcher/reissue/bob"' in html
        assert 'action="/_launcher/reissue/dana"' not in html  # not your own

    def test_reissue_from_admin_page(self, launcher):
        app, tokens, links, _ = launcher
        alice, _ = _join(app, tokens["alice"])
        dana, _ = _join(app, tokens["dana"])
        resp = dana.post("/_launcher/reissue/alice", headers={"Origin": "http://localhost"})
        assert resp.status_code == 303 and resp.headers["Location"] == "/_launcher/"
        assert links.ensure_all()["alice"] != tokens["alice"]
        assert alice.get("/").status_code == 403
        assert links.ensure_all()["alice"] in dana.get("/_launcher/").text

    def test_reissue_refuses_cross_site_and_non_admins(self, launcher):
        app, tokens, links, _ = launcher
        dana, _ = _join(app, tokens["dana"])
        alice, _ = _join(app, tokens["alice"])
        assert dana.post("/_launcher/reissue/bob").status_code == 403  # no Origin
        assert dana.post("/_launcher/reissue/bob", headers={"Origin": "https://evil.example"}).status_code == 403
        assert alice.post("/_launcher/reissue/bob", headers={"Origin": "http://localhost"}).status_code == 403
        assert dana.post("/_launcher/reissue/dana", headers={"Origin": "http://localhost"}).status_code == 400
        assert dana.post("/_launcher/reissue/zed", headers={"Origin": "http://localhost"}).status_code == 404
        assert links.ensure_all()["bob"] == tokens["bob"]

    def test_health(self, launcher):
        app, *_ = launcher
        assert app.test_client().get("/_launcher/health").data == b"ok\n"

    def test_crashed_process_restarts_on_next_request(self, launcher):
        app, tokens, _, sup = launcher
        alice, _ = _join(app, tokens["alice"])
        assert alice.get("/").status_code == 200
        sup.children["alice"].proc.kill()
        sup.children["alice"].proc.wait()
        first = alice.get("/")
        assert first.status_code in (200, 502)  # 502 if the request raced the death
        assert alice.get("/").status_code == 200

    def test_header_mode(self, project_dir):
        project = load_project(write(project_dir, HEADER_PROJECT))
        sup = Supervisor(project, ready_timeout=30, stop_timeout=10)
        try:
            client = create_app(project, sup, Identifier(project)).test_client()
            assert client.get("/", headers={"X-Forwarded-Email": "eve@example.org"}).status_code == 403
            assert client.get("/join/anything").status_code == 403
            resp = client.get("/_dash-layout", headers={"X-Forwarded-Email": "bob@example.org"})
            assert resp.status_code == 200 and '"d9"' in resp.text
        finally:
            sup.shutdown()


class TestStartRefusal:
    def test_header_mode_on_public_address(self, project_dir, capsys):
        path = write(project_dir, HEADER_PROJECT)
        assert launcher_main(["start", str(path), "--host", "0.0.0.0", "--port", "0"]) == 2
        assert "--behind-login-proxy" in capsys.readouterr().err


def _write_results(path: Path, docs: dict) -> None:
    """Results file with ``{doc_id: (status, flagged)}``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        d: {"annotations": {}, "metadata": {"status": st, "flagged": fl}} for d, (st, fl) in docs.items()
    }))


def _cells(row_html: str) -> list[str]:
    import re
    return [re.sub("<[^>]+>", "", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html)]


class TestProgress:
    def test_counts(self, project_dir):
        from tater.launcher.progress import ProgressCounter
        project = load_project(write(project_dir, MINIMAL))
        _write_results(project.annotation_path("alice"), {
            "d0": ("complete", False), "d1": ("complete", True), "d2": ("in_progress", False),
            "gone": ("complete", True),  # no longer in the documents file: not counted
        })
        progress = ProgressCounter(project)
        assert progress.counts("alice") == {"documents": 3, "complete": 2, "in_progress": 1, "flagged": 1}
        assert progress.counts("bob") == {"documents": 1, "complete": 0, "in_progress": 0, "flagged": 0}

    def test_rereads_a_changed_file(self, project_dir):
        from tater.launcher.progress import ProgressCounter
        project = load_project(write(project_dir, MINIMAL))
        progress = ProgressCounter(project)
        path = project.annotation_path("alice")
        _write_results(path, {"d0": ("complete", False)})
        assert progress.counts("alice")["complete"] == 1
        _write_results(path, {"d0": ("complete", False), "d1": ("complete", False), "d2": ("in_progress", False)})
        assert progress.counts("alice")["complete"] == 2

    def test_unreadable_files(self, project_dir):
        from tater.launcher.progress import ProgressCounter
        project = load_project(write(project_dir, MINIMAL))
        project.annotation_path("alice").parent.mkdir(parents=True)
        project.annotation_path("alice").write_text("{not json")
        (project_dir / "documents.json").write_text("[]oops")
        assert ProgressCounter(project).counts("alice") == {
            "documents": None, "complete": 0, "in_progress": 0, "flagged": 0}

    def test_ago(self):
        from datetime import datetime, timezone
        from tater.launcher.progress import ago
        now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
        assert ago(None, now) == "—"
        assert ago("2026-11-20T11:59:30+00:00", now) == "just now"
        assert ago("2026-11-20T11:57:00+00:00", now) == "3 min ago"
        assert ago("2026-11-20T09:00:00+00:00", now) == "3 h ago"
        assert ago("2026-11-16T12:00:00+00:00", now) == "4 days ago"


class TestStatusCommand:
    def test_not_running(self, project_dir, capsys):
        project = load_project(write(project_dir, MINIMAL))
        _write_results(project.annotation_path("alice"), {"d0": ("complete", True)})
        assert launcher_main(["status", str(project_dir / "project.yaml")]) == 0
        out = capsys.readouterr().out
        assert "launcher not running" in out
        alice = next(line for line in out.splitlines() if line.startswith("alice"))
        assert alice.split()[:8] == ["alice", "not", "running", "—", "3", "1", "0", "1"]

    def test_reads_running_launchers_status(self, project_dir, capsys):
        import os
        project = load_project(write(project_dir, MINIMAL))
        project.state_dir.mkdir()
        (project.state_dir / "status.json").write_text(json.dumps({
            "pid": os.getpid(), "url": "http://127.0.0.1:8050", "running": True, "updated": "now",
            "annotators": {"alice": {"state": "running", "last_request": None, "starts": 1, "crashes": 0}},
        }))
        launcher_main(["status", str(project_dir / "project.yaml")])
        out = capsys.readouterr().out
        assert "launcher running at http://127.0.0.1:8050" in out
        assert next(l for l in out.splitlines() if l.startswith("alice")).split()[1] == "running"
        assert next(l for l in out.splitlines() if l.startswith("bob")).split()[1] == "stopped"

    def test_ignores_status_of_a_stopped_or_dead_launcher(self, project_dir, capsys):
        from tater.launcher.progress import read_status_file
        project = load_project(write(project_dir, MINIMAL))
        project.state_dir.mkdir()
        path = project.state_dir / "status.json"
        path.write_text(json.dumps({"pid": 1, "running": False, "annotators": {}}))
        assert read_status_file(project) is None
        path.write_text(json.dumps({"pid": 2 ** 22 + 12345, "running": True, "annotators": {}}))
        assert read_status_file(project) is None
