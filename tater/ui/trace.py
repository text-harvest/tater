"""Callback trace: one JSON line per Dash callback request, for the perf harness.

Enabled with ``--trace <path>`` or ``TATER_TRACE=<path>``. Nothing is registered
when tracing is off.
"""
import json
import threading
import time
from pathlib import Path

import flask


def install_trace(server: flask.Flask, path: str | Path) -> None:
    """Register Flask hooks on ``server`` that append callback timings to ``path``.

    Each line records the action label, the callback's output and trigger, request
    and response sizes, server time and status (Dash returns 204 when a callback
    changes nothing). ``POST /_tater/trace/action`` with ``{"label": ...}`` sets the
    action label for the lines that follow.
    """
    lock = threading.Lock()
    trace_file = open(path, "a", buffering=1)
    state = {"action": ""}

    def is_callback():
        return flask.request.path.endswith("/_dash-update-component")

    @server.before_request
    def _trace_start():
        if is_callback():
            flask.g.tater_trace_start = time.perf_counter()

    @server.after_request
    def _trace_end(response):
        start = flask.g.pop("tater_trace_start", None)
        if start is None:
            return response
        body = flask.request.get_json(silent=True) or {}
        line = {
            "t": round(time.time(), 3),
            "action": state["action"],
            "output": body.get("output", ""),
            "trigger": body.get("changedPropIds", []),
            "req_bytes": len(flask.request.get_data()),
            "resp_bytes": response.calculate_content_length() or 0,
            "ms": round((time.perf_counter() - start) * 1000, 2),
            "status": response.status_code,
        }
        with lock:
            trace_file.write(json.dumps(line) + "\n")
        return response

    def set_action():
        state["action"] = str((flask.request.get_json(silent=True) or {}).get("label", ""))
        return "", 204

    server.add_url_rule("/_tater/trace/action", "tater_trace_action", set_action, methods=["POST"])
