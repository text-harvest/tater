"""Entry point for the ``tater`` CLI command."""
import os

from tater.ui.cli import parse_args
from tater.ui.tater_app import TaterApp


def main() -> None:
    args = parse_args()
    if args.hosted:
        run_hosted(args)
    else:
        run_single(args)


def run_single(args) -> None:
    """Run tater in single-user mode (existing behavior, unchanged)."""
    if args.config:
        from tater.ui.config_loader import load_config_module
        config = load_config_module(args.config)
    else:
        from tater.loaders import load_schema
        config = load_schema(args.schema)

    schema_model = config.get("schema_model")
    widgets = config.get("widgets")
    title = config.get("title")
    description = config.get("description")
    instructions = config.get("instructions")
    register_callbacks = config.get("register_callbacks")

    if schema_model is None:
        raise SystemExit("error: no schema_model found in config")

    from tater.loaders import widgets_from_model

    if not widgets:
        widgets = widgets_from_model(schema_model)
    elif not _covers_all_fields(widgets, schema_model):
        if any(w.schema_field == "" for w in widgets):
            import warnings
            warnings.warn(
                "Widget list contains dividers but does not cover all model fields. "
                "Dividers will be dropped. Provide widgets for all fields to preserve them.",
                UserWarning,
                stacklevel=2,
            )
        widgets = widgets_from_model(schema_model, overrides=widgets)

    app = TaterApp(
        title=title,
        description=description,
        instructions=instructions,
        annotations_path=args.annotations,
        schema_model=schema_model,
        restore_annotations=not args.no_restore,
    )
    _install_trace(app.app.server, args)

    if not app.load_documents(args.documents):
        return

    app.set_annotation_widgets(widgets)

    if register_callbacks is not None:
        register_callbacks(app)

    app.run(debug=args.debug, port=args.port, host=args.host)


def _install_trace(server, args) -> None:
    """Turn on the callback trace when --trace / TATER_TRACE is set."""
    if getattr(args, "trace", None):
        from tater.ui.trace import install_trace
        install_trace(server, args.trace)


def run_hosted(args) -> None:
    """Run tater in hosted mode: upload page at /, annotation UI at /annotate."""
    import flask
    from dash import Dash
    from tater.ui.upload_layout import build_upload_layout, register_upload_callbacks
    from tater.ui.layout import build_layout as build_annotation_layout

    app = Dash(
        __name__,
        title="tater",
        suppress_callback_exceptions=True,
        use_pages=False,
    )
    app.server.secret_key = os.environ.get("TATER_SECRET_KEY") or _random_secret_key()
    _install_trace(app.server, args)

    # Cache: session_id → TaterApp. Callbacks are registered once per session_id.
    # Oldest entry is evicted when the cache exceeds TATER_SESSION_CACHE_MAX.
    from collections import OrderedDict
    _cache_max = int(os.environ.get("TATER_SESSION_CACHE_MAX", 100))
    _session_cache: OrderedDict[str, object] = OrderedDict()

    # Let callbacks look up the current user's TaterApp at runtime via flask.session.
    # Stored on the shared Dash app so TaterApp.__init__ can pick it up.
    def _get_hosted_app_fn():
        import flask
        session_info = flask.session.get("tater_session") or {}
        session_id = session_info.get("session_id", "")
        return _session_cache.get(session_id)

    app._tater_get_current_app = _get_hosted_app_fn

    def _on_session_ready(session_info: dict) -> None:
        """Pre-build the TaterApp when the user submits the upload form.

        Registering annotation callbacks here (during the upload submit
        response) ensures they are present in ``/_dash-dependencies`` when
        the browser lands on /annotate — avoiding a race with the layout
        endpoint that would otherwise be the first opportunity to register
        them.
        """
        session_id = session_info.get("session_id", "")
        if session_id and session_id not in _session_cache:
            tater_app = _build_session_app_from_data(
                app,
                schema_data=session_info.get("schema_data"),
                docs_data=session_info.get("docs_data"),
                hierarchy_files=session_info.get("hierarchy_files"),
                annotations_data=session_info.get("annotations_data"),
                base_dir=session_info.get("base_dir"),
            )
            if tater_app is not None:
                _session_cache[session_id] = tater_app
                if len(_session_cache) > _cache_max:
                    _session_cache.popitem(last=False)

    show_disclaimer = args.show_disclaimer

    # Register upload-page callbacks, passing the pre-build hook.
    register_upload_callbacks(app, on_session_ready=_on_session_ready, show_disclaimer=show_disclaimer)

    def serve_layout():
        """Return the appropriate layout based on the current Flask session."""
        session_info = flask.session.get("tater_session")
        if not session_info:
            return build_upload_layout(show_disclaimer=show_disclaimer)
        session_id = session_info.get("session_id", "")
        tater_app = _session_cache.get(session_id)
        if tater_app is None:
            # Cache lost (server restart) — session data is gone, start over.
            flask.session.pop("tater_session", None)
            return build_upload_layout(show_disclaimer=show_disclaimer)
        return build_annotation_layout(tater_app)

    app.layout = serve_layout
    app.run(debug=args.debug, port=args.port, host=args.host)


def _build_session_app_from_data(
    dash_app,
    schema_data: dict,
    docs_data: list,
    hierarchy_files: dict | None = None,
    annotations_data: dict | None = None,
    base_dir=None,
):
    """Construct and configure a TaterApp from in-memory data.

    Args:
        schema_data: Parsed tater JSON schema dict.
        docs_data: List of document dicts (each with at least a ``text`` key).
        hierarchy_files: ``{ref_name: {"filename": ..., "content": ...}}`` for
            uploaded ontology files. Content strings are parsed as YAML and
            injected into the schema before parsing so no temp files are needed.
        annotations_data: Parsed annotations dict to preload, or None.
        base_dir: Directory used to resolve relative hierarchy paths in the
            schema (used for built-in examples whose files live in the package).

    Returns None if anything is invalid.
    """
    import copy
    from pathlib import Path
    from tater.loaders.json_loader import parse_schema
    from tater.loaders import widgets_from_model
    from tater.ui.tater_app import TaterApp

    if not schema_data or not docs_data:
        return None

    try:
        # Replace uploaded hierarchy file-path references with parsed YAML dicts
        # so parse_schema sees inline data rather than unresolvable paths.
        if hierarchy_files:
            import yaml
            schema_data = copy.deepcopy(schema_data)
            for ref_name, file_info in hierarchy_files.items():
                parsed = yaml.safe_load(file_info["content"])
                schema_data.setdefault("hierarchies", {})[ref_name] = parsed

        kw = {"base_dir": Path(base_dir)} if base_dir else {}
        schema_model, widgets = parse_schema(schema_data, **kw)
    except Exception as e:
        print(f"Error parsing schema: {e}")
        return None

    if not widgets or not _covers_all_fields(widgets, schema_model):
        widgets = widgets_from_model(schema_model, overrides=widgets)

    tater_app = TaterApp(
        title=schema_data.get("title", "tater"),
        description=schema_data.get("description"),
        instructions=schema_data.get("instructions"),
        annotations_path=None,
        schema_model=schema_model,
        is_hosted=True,
        dash_app=dash_app,
    )

    if not tater_app.load_documents(docs_data):
        return None

    if annotations_data:
        tater_app._load_annotations_from_dict(annotations_data)

    tater_app.set_annotation_widgets(widgets)
    return tater_app


def _random_secret_key() -> str:
    import secrets
    return secrets.token_hex(32)


def _covers_all_fields(widgets: list, schema_model) -> bool:
    """Return True if widgets account for every top-level model field."""
    covered = {w.schema_field for w in widgets}
    return covered >= set(schema_model.model_fields.keys())
