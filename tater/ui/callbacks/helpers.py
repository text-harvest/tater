"""Shared utilities used across all callback modules."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from dash import html, no_update
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
    current_doc_id: str,
    new_index: int,
    timing_data: dict,
    annotations_data: dict | None,
    metadata_data: dict | None,
) -> tuple:
    """Shared navigation logic: accumulate timing, update status, return (doc_id, timing, metadata, status).

    Also marks the new document as visited and computes its initial status, so that
    on_doc_change can detect this was a navigation event and skip redundant writes.
    """
    now = time.time()
    metadata_data = dict(metadata_data or {})
    if current_doc_id:
        meta = dict(_get_meta(metadata_data, current_doc_id))
        start = timing_data.get("doc_start_time") if timing_data else None
        if start:
            meta["annotation_seconds"] = meta.get("annotation_seconds", 0.0) + (now - start)
        # Departing this doc means the user was on it — always mark visited and assess completion.
        meta["visited"] = True
        meta["status"] = "complete" if _is_complete_eligible(tater_app, current_doc_id, annotations_data) else "in_progress"
        metadata_data[current_doc_id] = meta

    doc_id = tater_app.documents[new_index].id if new_index < len(tater_app.documents) else ""

    # Mark the new doc as visited and compute its status here, so on_doc_change
    # can skip its own metadata/timing writes when it sees _nav_init=True.
    if doc_id:
        new_meta = dict(_get_meta(metadata_data, doc_id))
        new_meta["visited"] = True
        metadata_data[doc_id] = new_meta
        update_status_for_doc(tater_app, doc_id, annotations_data, metadata_data)

    status = metadata_data.get(doc_id, {}).get("status", "not_started") if doc_id else "not_started"

    if timing_data is None:
        timing_data = {}
    timing_data["last_save_time"] = now
    timing_data["doc_start_time"] = now
    timing_data["paused"] = False
    timing_data["_nav_init"] = True
    if "session_start_time" not in timing_data or timing_data["session_start_time"] is None:
        timing_data["session_start_time"] = now
    timing_data["annotation_seconds_at_load"] = _get_meta(metadata_data, doc_id).get("annotation_seconds", 0.0) if doc_id else 0.0

    return doc_id, timing_data, metadata_data, status
