"""Main TaterApp application class."""
from typing import Optional, Type, Any
from pathlib import Path
import json
import os
import tempfile
import atexit
import threading
import time

from tater.models.document import DocumentMetadata

from dash import Dash
from tater.ui import layout
from pydantic import BaseModel

from tater.models import Document
from tater.widgets.base import TaterWidget
from tater.ui import callbacks
from tater.ui import value_helpers
from tater.ui.hooks import OnSaveHook
from tater.ui.callbacks.helpers import (
    _collect_all_control_templates,
    _collect_value_capture_widgets,
    _build_ev_lookup,
)


def _build_span_color_map(widgets: list, parent_pipe: str = "") -> dict:
    """Build {templatePipePath: {tagName: lightenedColor}} for all span widgets.

    Covers both SpanAnnotationWidget and SpanPopupWidget (both extend SpanBaseWidget).
    templatePipePath has numeric index segments stripped, e.g. "tests|relevant_spans".
    Used by the clientside render callback to look up mark colors without a server call.
    """
    from tater.widgets.span import SpanBaseWidget, _lighten_hex
    from tater.widgets.repeater import RepeaterWidget
    from tater.widgets.base import ContainerWidget
    result = {}
    for w in widgets:
        w_pipe = f"{parent_pipe}|{w.schema_field}" if parent_pipe else w.schema_field
        if isinstance(w, SpanBaseWidget):
            result[w_pipe] = {et.name: _lighten_hex(et.color) for et in w.entity_types}
        elif isinstance(w, RepeaterWidget):
            result.update(_build_span_color_map(w.item_widgets, w_pipe))
        elif isinstance(w, ContainerWidget) and hasattr(w, "children"):
            result.update(_build_span_color_map(w.children, w_pipe))
    return result


def _write_json_atomic(path: Path, data: Any) -> None:
    """Write *data* as JSON via a temp file and rename, so a crash mid-write
    never leaves a truncated annotations file. Each call gets its own temp file
    because auto_save requests can run concurrently."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        # mkstemp creates 0600; keep the existing file's mode (or a normal 0644).
        os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class TaterApp:
    """Main Tater application for document annotation."""

    def __init__(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        instructions: Optional[str] = None,
        annotations_path: Optional[str] = None,
        schema_model: Optional[Type[BaseModel]] = None,
        on_save: Optional[OnSaveHook] = None,
        is_hosted: bool = False,
        dash_app: Optional[Any] = None,
        restore_annotations: bool = True,
        save_interval: float = 2.0,
    ):
        """
        Initialize the Tater app.

        Args:
            title: Application title
            description: Optional subtitle shown below the title
            instructions: Optional markdown instructions shown in a help drawer
            annotations_path: Path to save/load annotations
            schema_model: Optional Pydantic model class for annotations
            is_hosted: If True, running in hosted mode (no auto-save, download button shown)
            dash_app: External Dash app to register callbacks on (hosted mode)
            restore_annotations: If False, skip loading existing annotations on startup
            save_interval: Write the annotations file at most once per this many seconds.
                Edits are merged into memory at once and written by a background thread;
                pending edits are written at exit. 0 writes on every save.
        """
        self.title = title or "tater - document annotation"
        self.description = description
        self.instructions = instructions
        self.annotations_path = annotations_path
        self.schema_model = schema_model
        self.on_save = on_save
        self.is_hosted = is_hosted
        self.restore_annotations = restore_annotations
        self.app = dash_app if dash_app is not None else Dash(__name__, title="tater", suppress_callback_exceptions=True)
        # In hosted mode the shared Dash app carries a callable that resolves
        # the current user's TaterApp from the Flask session at callback runtime.
        self._get_current_app = getattr(self.app, '_tater_get_current_app', None)
        self.widgets: list[TaterWidget] = []
        self.documents: list[Document] = []
        # Index of the document last navigated to; a page load opens there.
        self.current_doc_index = 0
        self.annotations: dict[str, BaseModel] = {}
        # Store metadata (DocumentMetadata) separately from annotations
        from tater.models.document import DocumentMetadata
        self.metadata: dict[str, DocumentMetadata] = {}
        self._save_error: str | None = None
        self._schema_warnings: dict[str, list[str]] = {}
        # Server copy of annotations-store / metadata-store as plain dicts. Built
        # lazily from annotations/metadata and replaced on every save, so each page
        # load serves the latest state rather than what was loaded at startup.
        self._ann_data: dict[str, dict] | None = None
        self._meta_data: dict[str, dict] | None = None
        # Last save-delta applied per document, as (page, seq), so a delta that arrives
        # after a newer one from the same page is ignored. The lock serializes merging
        # and writing: Dash may run two auto_save requests at once.
        self._delta_seq: dict[str, tuple[str, int]] = {}
        self._save_lock = threading.Lock()
        # Throttled file writes (2.5 in the scaling spec): _dirty marks merged edits not
        # yet written; _write_lock keeps two writers off the same temp file.
        self.save_interval = save_interval
        self._dirty = False
        self._pending_hooks: set[str] = set()
        self._save_timer: threading.Timer | None = None
        self._timer_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._last_write = 0.0
        if annotations_path:
            atexit.register(self.flush_saves)

    def load_documents(self, source) -> bool:
        """Load documents from a file path, a list of dicts, or a DataFrame.

        Args:
            source: Path to a documents file (JSON, CSV, TSV, or Excel),
                a ``list[dict]`` with at least a ``text`` key per item, or a
                ``pandas.DataFrame`` with a ``text`` column.  When passing
                in-memory data no default annotations path is set — provide
                ``annotations_path`` explicitly if you want auto-save.

        Returns:
            True if successful, False otherwise.
        """
        try:
            from tater.models.document import Document

            # --- in-memory paths ---
            try:
                import pandas as pd
                _is_df = isinstance(source, pd.DataFrame)
            except ImportError:
                _is_df = False

            if _is_df:
                source = source.to_dict("records")

            if isinstance(source, list):
                self.documents = [
                    Document.from_dict(item, index=idx)
                    for idx, item in enumerate(source)
                ]
                label = f"{len(self.documents)} documents (in-memory)"
            else:
                # --- file path ---
                from tater.loaders.document_loader import load_documents as _load
                self.documents = _load(source)
                if self.annotations_path is None and not self.is_hosted:
                    doc_path = Path(source)
                    self.annotations_path = str(doc_path.parent / f"{doc_path.stem}_annotations.json")
                label = f"{len(self.documents)} documents from {source}"

            # Load existing annotations if file exists (skipped when restore_annotations=False)
            if self.restore_annotations:
                self._load_annotations_from_file()

            # Ensure every document has annotation and metadata objects
            for doc in self.documents:
                if self.schema_model and doc.id not in self.annotations:
                    self.annotations[doc.id] = self.schema_model()
                if doc.id not in self.metadata:
                    self.metadata[doc.id] = DocumentMetadata()
            self._ann_data = self._meta_data = None
            self.current_doc_index = 0

            print(f"Loaded {label}")
            return True
        except Exception as e:
            print(f"Error loading documents: {e}")
            return False

    def _collect_all_widgets(self, widgets: list[TaterWidget]) -> list[TaterWidget]:
        """Recursively collect all widgets including nested ones from GroupWidget, ListableWidget, etc."""
        all_widgets = []
        for widget in widgets:
            all_widgets.append(widget)
            # If the widget has children (GroupWidget, ListableWidget), recurse into them
            if hasattr(widget, "children") and widget.children:
                all_widgets.extend(self._collect_all_widgets(widget.children))
        return all_widgets

    def set_annotation_widgets(self, widgets: list[TaterWidget]) -> None:
        """
        Set the widgets for annotation.

        Args:
            widgets: List of TaterWidget instances
        """
        self.widgets = widgets

        # Store reference to TaterApp in Dash app so widgets can access it
        self.app._tater_app = self

        # Finalize all field paths for nested widgets
        for widget in self.widgets:
            widget._finalize_paths()

        # Collect all widgets (including nested) for lookup by field_path
        self._all_widgets = self._collect_all_widgets(self.widgets)

        # Cache derived widget-tree lookups used in hot-path callbacks.
        # These are computed once here because the widget tree is immutable
        # after set_annotation_widgets() completes.
        self._ev_lookup: dict[str, object] = _build_ev_lookup(self.widgets)
        self._aa_fields: set[str] = {
            w.field_path
            for w in _collect_value_capture_widgets(self.widgets)
            if w.auto_advance
        }
        self._required_widgets = [
            w for w in _collect_value_capture_widgets(self.widgets)
            if w.required and w.to_python_type() is not bool
        ]
        self._span_color_map: dict = _build_span_color_map(self.widgets)

        # Duplicate field check
        seen: set[str] = set()
        for widget in self._all_widgets:
            path = widget.field_path
            if not path:
                continue
            if path in seen:
                raise ValueError(f"Duplicate widget for schema field '{path}'")
            seen.add(path)

        # Enforce that all schema fields have defaults (required for safe annotation loading)
        if self.schema_model is not None:
            required_fields = [
                name for name, fi in self.schema_model.model_fields.items()
                if fi.is_required()
            ]
            if required_fields:
                raise ValueError(
                    f"All schema model fields must have default values. "
                    f"Fields without defaults: {', '.join(required_fields)}"
                )

        # Bind widgets against the schema model (validates types, derives options)
        if self.schema_model is not None:
            for widget in self.widgets:
                widget.bind_schema(self.schema_model)

        if not self.is_hosted:
            self._setup_layout()

        # In hosted mode the Dash app is shared across sessions; only register
        # callbacks once (the first session sets them up for the shared app).
        _already = self.is_hosted and getattr(self.app, '_tater_callbacks_registered', False)
        if not _already:
            for widget in self.widgets:
                widget.register_callbacks(self.app)
                widget._register_conditional_callbacks(self.app)
            self._setup_callbacks()
            self._setup_value_capture_callbacks()
            self._setup_span_callbacks()
            self._setup_repeater_callbacks()
            self._setup_hl_callbacks()
            self._setup_conditional_visibility_callback()
            if self.is_hosted:
                self.app._tater_callbacks_registered = True

    def _setup_layout(self) -> None:
        """Create the Dash layout with navigation and annotation panel.

        Built per page load (a function, not a fixed component) so a refresh or a
        new tab gets the current stores from _store_data(), not the startup state.
        """
        self.app.layout = lambda: layout.build_layout(self)

    def _store_data(self) -> tuple[dict, dict]:
        """Return the current ({doc_id: annotations}, {doc_id: metadata}) dicts."""
        if self._ann_data is None or self._meta_data is None:
            self._ann_data = {doc_id: ann.model_dump() for doc_id, ann in self.annotations.items()}
            self._meta_data = {doc_id: meta.model_dump() for doc_id, meta in self.metadata.items()}
        return self._ann_data, self._meta_data

    def _set_store_data(self, annotations_data: dict, metadata_data: dict) -> None:
        """Replace the server copy of the stores with what the browser last sent."""
        self._ann_data = annotations_data
        self._meta_data = metadata_data

    def _load_annotations_from_dict(self, data: dict) -> None:
        """Load annotations from an in-memory dict (same format as the JSON file)."""
        self._apply_annotations_data(data)

    def _load_annotations_from_file(self) -> None:
        """Load existing annotations from the annotations file."""
        if not self.annotations_path:
            return

        path = Path(self.annotations_path)
        if not path.exists():
            return

        try:
            with open(path, 'r') as f:
                data = json.load(f)
            self._apply_annotations_data(data)
            print(f"Loaded existing annotations from {self.annotations_path}")
        except Exception as e:
            print(f"Error loading annotations: {e}")

    def _apply_annotations_data(self, data: dict) -> None:
        """Apply a parsed annotations dict to self.annotations and self.metadata."""
        self._ann_data = self._meta_data = None
        try:
            from tater.models.document import DocumentMetadata
            extra_fields: set[str] = set()
            missing_fields: set[str] = set()

            for doc_id, doc_data in data.items():
                ann_data = doc_data.get("annotations", {})
                meta = doc_data.get("metadata", {})
                self.metadata[doc_id] = DocumentMetadata(
                    flagged=meta.get("flagged", False),
                    notes=meta.get("notes", ""),
                    annotation_seconds=meta.get("annotation_seconds", 0.0),
                    visited=meta.get("visited", False),
                    status=meta.get("status", "not_started"),
                )
                if self.schema_model and ann_data:
                    schema_fields = set(self.schema_model.model_fields.keys())
                    ann_fields = set(ann_data.keys())
                    extra_fields |= ann_fields - schema_fields
                    missing_fields |= schema_fields - ann_fields
                    self.annotations[doc_id] = self.schema_model(**ann_data)

            self._schema_warnings = {}
            if extra_fields:
                self._schema_warnings["extra"] = sorted(extra_fields)
            if missing_fields:
                self._schema_warnings["missing"] = sorted(missing_fields)
        except Exception as e:
            print(f"Error applying annotations: {e}")

    def _apply_save_delta(self, delta: dict | None) -> list[str]:
        """Merge a ``save-delta`` into the server copy of the stores.

        ``delta`` is ``{"page", "seq", "docs": {doc_id: {"annotations"?, "metadata"?}}}``
        from the clientside ``emitSaveDelta``; each part replaces that document's entry.
        A document is skipped when a delta with the same ``page`` and an equal or higher
        ``seq`` was already applied to it (requests can arrive out of order). Returns
        the ids of the documents applied, in delta order.
        """
        if not delta or not delta.get("docs"):
            return []
        page, seq = delta.get("page"), delta.get("seq") or 0
        applied = []
        with self._save_lock:
            ann_data, meta_data = self._store_data()
            for doc_id, entry in delta["docs"].items():
                last = self._delta_seq.get(doc_id)
                if last is not None and last[0] == page and last[1] >= seq:
                    continue
                self._delta_seq[doc_id] = (page, seq)
                if entry.get("annotations") is not None:
                    ann_data[doc_id] = entry["annotations"]
                if entry.get("metadata") is not None:
                    meta_data[doc_id] = entry["metadata"]
                applied.append(doc_id)
        return applied

    def _save_delta_to_file(self, delta: dict | None) -> bool:
        """Apply a ``save-delta`` and write the annotations file from the server copy.

        Calls ``on_save`` for each applied document whose annotations were in the
        delta. Returns True when something was written.
        """
        applied = self._apply_save_delta(delta)
        if not applied:
            return False
        docs = delta["docs"]
        with self._save_lock:
            self._dirty = True
            self._pending_hooks.update(d for d in applied if docs[d].get("annotations") is not None)
        if self.save_interval <= 0:
            self.flush_saves()
        else:
            self._schedule_flush()
        return True

    def _schedule_flush(self) -> None:
        """Write soon: now if the last write was over ``save_interval`` ago, else when
        the interval is up. Saves arriving meanwhile are covered by that one write."""
        with self._timer_lock:
            if self._save_timer is not None:
                return
            delay = max(0.0, self._last_write + self.save_interval - time.monotonic())
            self._save_timer = threading.Timer(delay, self.flush_saves)
            self._save_timer.daemon = True
            self._save_timer.start()

    def flush_saves(self) -> None:
        """Write merged edits not yet in the annotations file, if any.

        Runs on the save timer, at exit, and wherever the file must be current (e.g.
        before reading it). A failed write leaves the edits pending for the next one.
        """
        with self._timer_lock:
            if self._save_timer is not None and self._save_timer is not threading.current_thread():
                self._save_timer.cancel()
            self._save_timer = None
            # The interval runs from the start of this write, so a save arriving while
            # it runs is scheduled for the interval's end, not straight after.
            self._last_write = time.monotonic()
        with self._save_lock:
            if not self._dirty:
                return
            self._dirty = False
            hooks, self._pending_hooks = self._pending_hooks, set()
        if not self._write_store_data(sorted(hooks)):
            with self._save_lock:
                self._dirty = True
                self._pending_hooks |= hooks

    def _save_stores_to_file(
        self,
        annotations_data: dict,
        metadata_data: dict,
        doc_id: Optional[str] = None,
    ) -> None:
        """Save annotations and metadata from dcc.Store dicts to the annotations file.

        Replaces the server copy with these stores. The app itself saves deltas
        (``_save_delta_to_file``); this is for whole-store saves.

        Args:
            annotations_data: {doc_id: annotation_dict} from annotations-store
            metadata_data: {doc_id: metadata_dict} from metadata-store
            doc_id: The document whose annotation triggered this save. When provided
                and an ``on_save`` hook is configured, the hook is called after writing.
        """
        self._set_store_data(annotations_data or {}, metadata_data or {})
        self._write_store_data([doc_id] if doc_id else [])

    def _write_store_data(self, hook_doc_ids: list[str]) -> bool:
        """Write the server copy of the stores to the annotations file, then call
        ``on_save`` for each of ``hook_doc_ids`` that has annotations. Returns False
        if the write failed.

        Serializes a shallow snapshot taken under ``_save_lock``, so merging new deltas
        isn't blocked while the file is written (deltas replace document entries, they
        never mutate them).
        """
        try:
            with self._write_lock:
                with self._save_lock:
                    annotations_data, metadata_data = (dict(d) for d in self._store_data())
                path = Path(self.annotations_path)
                path.parent.mkdir(parents=True, exist_ok=True)

                save_dict = {}
                for d_id in set(annotations_data) | set(metadata_data):
                    save_dict[d_id] = {
                        "annotations": annotations_data.get(d_id, {}),
                        "metadata": metadata_data.get(d_id, {}),
                    }
                _write_json_atomic(path, save_dict)
                self._save_error = None
                hook_anns = {d: annotations_data[d] for d in hook_doc_ids if annotations_data.get(d) is not None}
        except Exception as e:
            self._save_error = str(e)
            print(f"Error saving annotations: {e}")
            return False

        if self.on_save and self.schema_model:
            for d_id, ann in hook_anns.items():
                try:
                    self.on_save(d_id, self.schema_model(**ann))
                except Exception as hook_err:
                    print(f"on_save hook error: {hook_err}")
        return True

    def _save_annotations_to_file(self, doc_id: Optional[str] = None) -> None:
        """Save all annotations to the annotations file.

        Args:
            doc_id: The document whose annotation triggered this save.  When
                provided and an ``on_save`` hook is configured, the hook is
                called with this document's annotation after writing.
        """
        try:
            path = Path(self.annotations_path)
            path.parent.mkdir(parents=True, exist_ok=True)

            # Combine annotations and metadata into save format
            save_dict = {}
            for d_id, annotation in self.annotations.items():
                meta: DocumentMetadata = self.metadata.get(d_id, DocumentMetadata())
                save_dict[d_id] = {
                    "annotations": annotation.model_dump(),
                    "metadata": meta.model_dump(),
                }

            _write_json_atomic(path, save_dict)
            self._save_error = None
            # annotations/metadata are the source here; rebuild the store copy from them.
            self._ann_data = self._meta_data = None

            if self.on_save and doc_id and doc_id in self.annotations:
                try:
                    self.on_save(doc_id, self.annotations[doc_id])
                except Exception as hook_err:
                    print(f"on_save hook error: {hook_err}")
        except Exception as e:
            self._save_error = str(e)
            print(f"Error saving annotations: {e}")

    def _setup_callbacks(self) -> None:
        """Setup Dash callbacks for interactivity."""
        callbacks.setup_callbacks(self)

    def _setup_value_capture_callbacks(self) -> None:
        """Setup callbacks to capture widget value changes to annotations store."""
        callbacks.setup_value_capture_callbacks(self)

    def _setup_span_callbacks(self) -> None:
        """Setup unified span annotation callbacks."""
        callbacks.setup_span_callbacks(self)

    def _setup_repeater_callbacks(self) -> None:
        """Setup unified MATCH-based repeater callbacks."""
        callbacks.setup_repeater_callbacks(self)
        callbacks.setup_nested_repeater_callbacks(self)

    def _setup_conditional_visibility_callback(self) -> None:
        """Register one ALL-based visibility callback covering ALL conditional widgets.

        A single ``conditionalVisibilityAll`` callback handles both flat widgets
        (ld="", path="") and repeater widgets (ld="pets", path="0") in one shot.
        Visibility is no longer handled per-widget or via MATCH patterns — this
        callback fires whenever any tater-control or tater-bool-control value changes
        and updates every matching wrapper's style.  The JS uses ``ctx.outputs_list``
        to iterate over output wrappers, finds each wrapper's config by matching
        tf/ld/path in ``ctx.states_list``, then looks up the controlling widget's
        current value from ``ctx.inputs_list`` by matching ctrl_tf/ld/path.
        """
        from dash import ClientsideFunction, Output, Input, State, ALL

        self.app.clientside_callback(
            ClientsideFunction(namespace="tater", function_name="conditionalVisibilityAll"),
            Output({"type": "tater-cond-wrapper", "ld": ALL, "path": ALL, "tf": ALL}, "style"),
            Input({"type": "tater-control", "ld": ALL, "path": ALL, "tf": ALL}, "value"),
            Input({"type": "tater-bool-control", "ld": ALL, "path": ALL, "tf": ALL}, "checked"),
            State({"type": "tater-cond-config", "ld": ALL, "path": ALL, "tf": ALL}, "data"),
            prevent_initial_call=True,
        )

    def _setup_hl_callbacks(self) -> None:
        """Setup unified MATCH-based HierarchicalLabel callbacks."""
        callbacks.setup_hl_select_callbacks(self)
        callbacks.setup_hl_multi_callbacks(self)
        callbacks.setup_hl_browser_callback(self)

    def _collect_value_capture_widgets(self, widgets: list[TaterWidget]) -> list[TaterWidget]:
        """
        Recursively collect all widgets that capture values (non-containers).
        
        Skips GroupWidget children (processes them recursively instead).
        Skips ListableWidget item widgets - ListableWidget handles its own value capture.
        """
        return callbacks._collect_value_capture_widgets(widgets)

    def _register_widget_value_capture(self, widget: TaterWidget) -> None:
        """Register a callback to capture a widget's value changes."""
        callbacks._register_widget_value_capture(self, widget)
    
    def _set_model_value(self, model: BaseModel | dict, path: str, value: Any) -> None:
        """Set a value in a Pydantic model/dict using dot notation."""
        value_helpers.set_model_value(model, path, value)
    
    def _create_list_item(self, list_parent: list, navigation_stack: list) -> Any:
        """Determine list item type for nested model path expansion."""
        return value_helpers.create_list_item(navigation_stack)
    
    def _get_model_value(self, model: BaseModel | dict, path: str) -> Any:
        """Get a value from a Pydantic model/dict using dot notation."""
        return value_helpers.get_model_value(model, path)
    
    def _get_dict_value(self, obj: Any, path: str) -> Any:
        """Get a value from a nested dict/list structure using dot notation."""
        return value_helpers.get_dict_value(obj, path)

    def _set_dict_value(self, obj: dict, path: str, value: Any) -> None:
        """Set a value in a nested dict/list structure using dot notation."""
        value_helpers.set_dict_value(obj, path, value)

    def run(
        self,
        debug: bool = False,
        port: int = 8050,
        host: str = "127.0.0.1",
        jupyter_mode: Optional[str] = None,
    ) -> None:
        """Start the Dash server.

        Args:
            jupyter_mode: Dash Jupyter rendering mode — "inline" (iframe in cell
                output), "tab" (new browser tab), or "jupyterlab" (side panel).
                None runs the standard blocking dev server.
        """
        kwargs: dict = dict(debug=debug, port=port, host=host)
        if jupyter_mode is not None:
            kwargs["jupyter_mode"] = jupyter_mode
        self.app.run(**kwargs)

    def get_annotations(self) -> dict:
        """Return current annotations as {doc_id: annotation_dict}.

        From the server's copy of the annotations store, which every save updates at
        once — the file can lag behind it by up to ``save_interval``.
        """
        with self._save_lock:
            return dict(self._store_data()[0])
