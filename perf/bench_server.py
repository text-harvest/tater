"""Browser-free server timings: startup, save and memory per project size.

    uv run python -m perf.bench_server --sizes 50,500,2500,10000 --lengths short --schema checkbox

Each case runs in a fresh subprocess so its RSS isn't inflated by earlier cases.
"""
import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from perf.synthetic import LENGTHS, make_project, write_project

HOSTED_SESSIONS = (1, 5, 20)


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1e6


def _start_single(docs_path: Path, ann_path: Path, schema: dict):
    from tater.loaders import widgets_from_model
    from tater.loaders.json_loader import parse_schema
    from tater.ui.tater_app import TaterApp

    model, widgets = parse_schema(schema)
    app = TaterApp(schema_model=model, annotations_path=str(ann_path))
    app.load_documents(str(docs_path))
    app.set_annotation_widgets(widgets_from_model(model, overrides=widgets))
    return app


def _single_case(n_docs: int, length: str, schema: str, filled: bool, spans: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        # Warm up on one document so imports and first-Dash costs aren't counted.
        warm = Path(tmp) / "warm"
        _, docs_path, ann_path = write_project(make_project(1, 100, filled, schema=schema), warm)
        _start_single(docs_path, ann_path, json.loads((warm / "schema.json").read_text()))

        project = make_project(n_docs, LENGTHS[length], filled, spans_per_doc=spans, schema=schema)
        _, docs_path, ann_path = write_project(project, tmp)
        del project
        rss_before = _rss_mb()
        t0 = time.perf_counter()
        app = _start_single(docs_path, ann_path, json.loads((Path(tmp) / "schema.json").read_text()))
        startup_ms = (time.perf_counter() - t0) * 1000
        rss_after = _rss_mb()

        ann, meta = app._store_data()
        save_times = []
        for _ in range(3):
            t0 = time.perf_counter()
            app._save_stores_to_file(ann, meta, doc_id=app.documents[0].id)
            save_times.append((time.perf_counter() - t0) * 1000)
        return {
            "startup_ms": round(startup_ms, 1),
            "save_ms": round(statistics.median(save_times), 1),
            "file_mb": round(ann_path.stat().st_size / 1e6, 2),
            "rss_mb": round(rss_after, 1),
            "rss_project_mb": round(rss_after - rss_before, 1),
        }


def _hosted_case(n_docs: int, length: str, schema: str, filled: bool, spans: int) -> dict:
    from dash import Dash
    from tater.ui.runner import _build_session_app_from_data

    project = make_project(n_docs, LENGTHS[length], filled, spans_per_doc=spans, schema=schema)
    dash_app = Dash(__name__, suppress_callback_exceptions=True)
    dash_app._tater_get_current_app = lambda: None
    sessions, rss = [], {}
    base = _rss_mb()
    for k in range(1, max(HOSTED_SESSIONS) + 1):
        sessions.append(_build_session_app_from_data(
            dash_app, schema_data=project.schema, docs_data=project.docs,
            annotations_data=project.annotations or None,
        ))
        if k in HOSTED_SESSIONS:
            rss[k] = _rss_mb() - base
    # The first session also registers the shared callbacks; later ones show the per-session cost.
    last = max(HOSTED_SESSIONS)
    return {f"rss_{k}_sessions_mb": round(v, 1) for k, v in rss.items()} | {
        "rss_per_session_mb": round((rss[last] - rss[1]) / (last - 1), 1),
    }


def run_case(hosted: bool, n_docs: int, length: str, schema: str, filled: bool, spans: int = 0) -> dict:
    """Run one case in a subprocess and return its measurements."""
    spec = json.dumps({"hosted": hosted, "n_docs": n_docs, "length": length, "schema": schema,
                       "filled": filled, "spans": spans})
    out = subprocess.run([sys.executable, "-m", "perf.bench_server", "--one", spec],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--one", help=argparse.SUPPRESS)
    parser.add_argument("--sizes", default="50,500,2500,10000")
    parser.add_argument("--lengths", default="short")
    parser.add_argument("--schema", default="checkbox")
    parser.add_argument("--filled", choices=["yes", "no", "both"], default="both")
    parser.add_argument("--spans", type=int, default=10, help="spans per document in filled realistic projects")
    parser.add_argument("--hosted", action="store_true", help="measure memory per hosted session instead")
    args = parser.parse_args(argv)

    if args.one:
        spec = json.loads(args.one)
        case = _hosted_case if spec.pop("hosted") else _single_case
        # Silence tater's own prints so the last stdout line is the result.
        real_stdout, sys.stdout = sys.stdout, sys.stderr
        try:
            result = case(**spec)
        finally:
            sys.stdout = real_stdout
        print(json.dumps(result))
        return

    filled = {"yes": [True], "no": [False], "both": [False, True]}[args.filled]
    for schema in args.schema.split(","):
        for length in args.lengths.split(","):
            for f in filled:
                for n in (int(s) for s in args.sizes.split(",")):
                    spans = args.spans if (f and schema == "realistic") else 0
                    result = run_case(args.hosted, n, length, schema, f, spans)
                    print(json.dumps({"n_docs": n, "length": length, "schema": schema, "filled": f} | result))


if __name__ == "__main__":
    main()
