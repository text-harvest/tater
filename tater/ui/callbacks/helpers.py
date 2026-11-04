"""Shared utilities used across all callback modules."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from dash import Patch, html, no_update
from tater.ui import value_helpers
from tater.ui.constants import STATUS_COLORS, STATUS_LABELS
from tater.widgets.base import ContainerWidget, ControlWidget
from tater.widgets.group import GroupWidget
from tater.widgets.repeater import RepeaterWidget

if TYPE_CHECKING:
    from tater.ui.tater_app import TaterApp
    from tater.widgets.base import TaterWidget


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

def _default_meta() -> dict:
    return {"flagged": False, "notes": "", "annotation_seconds": 0.0, "visited": False, "status": "not_started"}


def _get_ann(annotations_data: dict | None, doc_id: str | None):
    """Return the annotation dict for *doc_id*, or None."""
    if not annotations_data or not doc_id:
        return None
    return annotations_data.get(doc_id)


def _get_meta(metadata_data: dict | None, doc_id: str | None) -> dict:
    """Return the metadata dict for *doc_id* (with defaults filled in)."""
    base = _default_meta()
    if not metadata_data or not doc_id:
        return base
    stored = metadata_data.get(doc_id)
    if stored is None:
        return base
    return {**base, **stored}


def _slice_stores(doc_slice: dict | None, doc_id: str | None = None) -> tuple[dict, dict] | None:
    """Turn a ``current-doc-slice`` / ``doc-load-slice`` into one-document stores.

    Returns ``({doc_id: annotations}, {doc_id: metadata})``, the shape the ``*_impl``
    functions and widget renderers read with ``.get(doc_id)``. Returns None when the
    slice is for a different document than ``doc_id`` (when given): the caller must
    then not write that document's metadata, or it would replace it with defaults.
    """
    sid = (doc_slice or {}).get("doc_id") or ""
    if doc_id is not None and sid != (doc_id or ""):
        return None
    if not sid:
        return {}, {}
    ann, meta = doc_slice.get("annotations"), doc_slice.get("metadata")
    return ({sid: ann} if ann is not None else {}), ({sid: meta} if meta is not None else {})


def _meta_patch(before: dict | None, after):
    """A ``Patch`` for metadata-store writing only the fields that changed.

    ``before`` / ``after`` are ``{doc_id: meta}`` dicts as the ``*_impl`` functions take
    and return; ``after`` may be ``no_update``. Fields are merged into each document's
    entry, so fields not in ``after`` (and other documents) are left alone. Returns
    ``no_update`` when nothing changed.
    """
    if after is no_update or not after:
        return no_update
    before = before or {}
    patch, changed = Patch(), False
    for doc_id, meta in after.items():
        old = before.get(doc_id) or {}
        diff = {k: v for k, v in (meta or {}).items() if k not in old or old[k] != v}
        if diff:
            patch[doc_id].update(diff)
            changed = True
    return patch if changed else no_update


def _dict_patch(before: dict | None, after):
    """A ``Patch`` setting only the keys of ``after`` that differ from ``before``.

    Used for timing-store, so a slow response can't overwrite keys another callback
    changed in the meantime. Returns ``no_update`` when nothing changed.
    """
    if after is no_update or after is None:
        return no_update
    before = before or {}
    diff = {k: v for k, v in after.items() if k not in before or before[k] != v}
    if not diff:
        return no_update
    patch = Patch()
    patch.update(diff)
    return patch


def _has_value(value) -> bool:
    """Return True if a field value is considered filled (non-empty, non-None)."""
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, list) and len(value) == 0:
        return False
    return True


# ---------------------------------------------------------------------------
# Widget-tree collectors
# ---------------------------------------------------------------------------

def _collect_value_capture_widgets(widgets: list[TaterWidget]) -> list[TaterWidget]:
    """Recursively collect all ControlWidget instances (non-containers).

    Used to build the auto-advance field set and to find required widgets
    for status checking. Skips RepeaterWidget children (their items are
    handled dynamically via unified ALL callbacks).
    """
    captured = []
    for widget in widgets:
        if isinstance(widget, RepeaterWidget):
            continue
        elif isinstance(widget, GroupWidget):
            if hasattr(widget, "children") and widget.children:
                captured.extend(_collect_value_capture_widgets(widget.children))
        elif isinstance(widget, ControlWidget):
            captured.append(widget)
    return captured


def _collect_all_control_templates(widgets: list[TaterWidget]) -> list[TaterWidget]:
    """Recursively collect all ControlWidget templates, including inside repeaters.

    Used to build empty_value lookups for load callbacks.
    """
    captured = []
    for widget in widgets:
        if isinstance(widget, RepeaterWidget):
            captured.extend(_collect_all_control_templates(widget.item_widgets))
        elif isinstance(widget, GroupWidget):
            if hasattr(widget, "children") and widget.children:
                captured.extend(_collect_all_control_templates(widget.children))
        elif isinstance(widget, ControlWidget):
            captured.append(widget)
    return captured


def _build_ev_lookup(widgets: list[TaterWidget], _group_prefix: str = "") -> dict:
    """Build the ev_lookup dict mapping tf keys to empty values.

    Keys use the same encoding as ``_item_relative_tf`` at render time:
    - Standalone or direct repeater child: ``schema_field`` (or full pipe-encoded path for standalones)
    - GroupWidget child inside a repeater: ``"group_schema_field|child_schema_field"``

    This ensures ``loadValues`` can find the fallback empty value for every widget,
    including those inside GroupWidgets within repeaters.
    """
    result = {}
    for widget in widgets:
        if isinstance(widget, RepeaterWidget):
            # Entering a new repeater resets the group prefix.
            result.update(_build_ev_lookup(widget.item_widgets, ""))
        elif isinstance(widget, GroupWidget):
            new_prefix = f"{_group_prefix}|{widget.schema_field}" if _group_prefix else widget.schema_field
            if hasattr(widget, "children") and widget.children:
                result.update(_build_ev_lookup(widget.children, new_prefix))
        elif isinstance(widget, ControlWidget):
            if _group_prefix:
                # Inside a repeater group: key is group-relative (e.g. "booleans|indoor_location")
                key = f"{_group_prefix}|{widget.schema_field}"
            else:
                # Standalone or direct repeater child: key is full pipe-encoded field_path
                key = widget.field_path.replace(".", "|")
            result[key] = widget.empty_value
    return result


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def _status_display(status: str) -> tuple[str, str]:
    """Return (label, color) for a document status string."""
    return STATUS_LABELS.get(status, status), STATUS_COLORS.get(status, "gray")


def _is_complete_eligible(tater_app: TaterApp, doc_id: str, annotations_data: dict | None) -> bool:
    """Return True if the document meets the requirements to be marked complete.

    No required widgets → always eligible. Otherwise all required fields must be filled.
    """
    required_widgets = tater_app._required_widgets
    if not required_widgets:
        return True
    ann = _get_ann(annotations_data, doc_id)
    if ann is None:
        return False
    for widget in required_widgets:
        value = value_helpers.get_model_value(ann, widget.field_path)
        if not _has_value(value):
            return False
    return True


def _format_seconds(total_seconds: float) -> str:
    """Format a duration in seconds as a human-readable string."""
    total_seconds = int(total_seconds)
    hours, rem = divmod(total_seconds, 3600)
    mins, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {mins}m {secs}s"
    if mins:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def update_status_for_doc(tater_app: TaterApp, doc_id: str, annotations_data: dict | None, metadata_data: dict) -> None:
    """Set in-flight status (not_started / in_progress) for the arriving document.

    Completion is only assigned by _perform_navigation (on departure) or handle_finish.
    Mutates ``metadata_data[doc_id]["status"]`` in-place.
    """
    if not doc_id or metadata_data is None:
        return
    meta = metadata_data.setdefault(doc_id, _default_meta())
    if not meta.get("visited", False):
        meta["status"] = "not_started"
        return
    meta["status"] = "in_progress"


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def _doc_index(tater_app: TaterApp, doc_id: str | None) -> int | None:
    """Return the position of *doc_id* in ``tater_app.documents``, or None.

    The id → index dict is cached on the app and rebuilt whenever
    ``documents`` is replaced, so lookups stay O(1) for large document sets.
    """
    if not doc_id:
        return None
    docs = tater_app.documents
    cache = getattr(tater_app, "_doc_index_cache", None)
    if cache is None or cache[0] is not docs:
        cache = (docs, {d.id: i for i, d in enumerate(docs)})
        tater_app._doc_index_cache = cache
    return cache[1].get(doc_id)


def _perform_navigation(
    tater_app: TaterApp,
    current_doc_id: str | None,
    new_index: int,
    timing_data: dict | None,
    annotations_data: dict | None,
    metadata_data: dict | None,
) -> tuple:
    """Shared navigation logic for the **departing** document.

    Accumulates its time, marks it visited and assesses completion, and restarts the
    clock. Returns ``(doc_id, timing_data, metadata_data, status)``: ``metadata_data``
    holds only the departing document (``{}`` when there is none) and ``status`` is
    always ``no_update``. The arriving document is set up by ``on_doc_change`` from
    ``doc-load-slice``, since only the departing document's data is sent here.
    """
    now = time.time()
    metadata_out = {}
    if current_doc_id:
        meta = dict(_get_meta(metadata_data, current_doc_id))
        start = timing_data.get("doc_start_time") if timing_data else None
        if start:
            meta["annotation_seconds"] = meta.get("annotation_seconds", 0.0) + (now - start)
        # Departing this doc means the user was on it — always mark visited and assess completion.
        meta["visited"] = True
        meta["status"] = "complete" if _is_complete_eligible(tater_app, current_doc_id, annotations_data) else "in_progress"
        metadata_out[current_doc_id] = meta

    doc_id = tater_app.documents[new_index].id if new_index < len(tater_app.documents) else ""
    if doc_id:
        tater_app.current_doc_index = new_index

    timing_data = dict(timing_data or {})
    timing_data["last_save_time"] = now
    timing_data["doc_start_time"] = now
    timing_data["paused"] = False
    if timing_data.get("session_start_time") is None:
        timing_data["session_start_time"] = now

    return doc_id, timing_data, metadata_out, no_update
