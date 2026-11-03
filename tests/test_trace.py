"""Tests for the callback trace (tater/ui/trace.py)."""
import json

import flask

from tater.ui.trace import install_trace


def _server(tmp_path):
    server = flask.Flask(__name__)

    @server.post("/_dash-update-component")
    def update():
        body = flask.request.get_json()
        if body.get("output") == "noop.data":
            return "", 204
        return flask.jsonify({"response": {"x": {"data": "y" * 100}}})

    @server.get("/")
    def index():
        return "page"

    trace_path = tmp_path / "trace.jsonl"
    install_trace(server, trace_path)
    return server.test_client(), trace_path


def _lines(trace_path):
    return [json.loads(line) for line in trace_path.read_text().splitlines()]


def test_records_callback_requests_with_action_label(tmp_path):
    client, trace_path = _server(tmp_path)
    client.post("/_tater/trace/action", json={"label": "next#0"})
    body = {"output": "current-doc-id.data", "changedPropIds": ["btn-next.n_clicks"]}
    client.post("/_dash-update-component", json=body)
    client.post("/_dash-update-component", json={"output": "noop.data", "changedPropIds": []})

    first, second = _lines(trace_path)
    assert first["action"] == "next#0"
    assert first["output"] == "current-doc-id.data"
    assert first["trigger"] == ["btn-next.n_clicks"]
    assert first["req_bytes"] == len(json.dumps(body))
    assert first["resp_bytes"] > 100
    assert first["status"] == 200
    assert first["ms"] >= 0
    assert second["status"] == 204


def test_ignores_other_requests(tmp_path):
    client, trace_path = _server(tmp_path)
    client.get("/")
    client.post("/_tater/trace/action", json={"label": "x"})

    assert not trace_path.exists() or trace_path.read_text() == ""
