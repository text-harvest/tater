"""Core navigation, save, timing, and value-capture callbacks."""
from __future__ import annotations

import json
import time
import flask
from datetime import datetime
from typing import TYPE_CHECKING

from dash import Input, Output, State, ALL, ctx, no_update, html, ClientsideFunction, Patch

import dash_mantine_components as dmc

from tater.ui.callbacks.helpers import (
    _get_ann,
    _get_meta,
    _doc_index,
    _slice_stores,
    _meta_patch,
    _dict_patch,
    _perform_navigation,
    update_status_for_doc,
    _status_display,
    _is_complete_eligible,
    _format_seconds,
    session_resolver,
)

if TYPE_CHECKING:
    from tater.ui.tater_app import TaterApp



def setup_callbacks(tater_app: TaterApp) -> None:
    """Register document and navigation callbacks on the Dash app."""
    app = tater_app.app
    has_instructions = bool(tater_app.instructions and tater_app.instructions.strip())

    # In hosted mode, each HTTP request carries a Flask session cookie identifying
    # the user's session. _ta() resolves the correct TaterApp for that session so
    # callbacks work correctly when multiple users share the same Dash process.
    _ta = session_resolver(tater_app)

    # Scroll to top on document navigation.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="autoScrollTop"),
        Input("current-doc-id", "data"),
        prevent_initial_call=True,
    )

    # The current document's slice of annotations-store / metadata-store, so server
    # callbacks never upload the whole stores (#108). current-doc-slice follows every
    # change and is read as State by callbacks a user action triggers. doc-load-slice
    # changes only on navigation, or on a repeater reload ("reload": true); callbacks
    # that set up the arriving document take it as an Input so they see its data.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="buildDocSlices"),
        Output("current-doc-slice", "data"),
        Output("doc-load-slice", "data"),
        Input("current-doc-id", "data"),
        Input("annotations-store", "data"),
        Input("metadata-store", "data"),
        Input("repeater-load-trigger", "data"),
        prevent_initial_call=True,
    )

    # Update document title, metadata, progress bar and nav-button states clientside.
    # Fires immediately on navigation — no server round-trip — using info preloaded
    # into doc-list-store at layout time.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="updateNavInfo"),
        Output("document-title", "children"),
        Output("document-metadata", "children"),
        Output("document-progress", "value"),
        Output("btn-prev", "disabled"),
        Output("btn-next", "disabled"),
        Output("btn-next-container", "style"),
        Output("btn-finish-container", "style"),
        Input("current-doc-id", "data"),
        State("doc-list-store", "data"),
        prevent_initial_call=False,
    )

    # Update session-level status distribution bar in the header.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="updateStatusBadges"),
        Output("prog-ns", "value"),
        Output("prog-ip", "value"),
        Output("prog-c",  "value"),
        Output("icon-all-complete", "style"),
        Input("metadata-store", "data"),
        State("doc-list-store", "data"),
    )

    # Setup timing callbacks
    _setup_timing_callbacks(tater_app, _ta)

    # Load raw document text on navigation; rendering is handled clientside.
    @app.callback(
        Output("document-text-store", "data"),
        Input("current-doc-id", "data"),
    )
    def update_document(doc_id):
        if not doc_id:
            return no_update

        ta = _ta()
        idx = _doc_index(ta, doc_id)
        if idx is None:
            return no_update
        doc = ta.documents[idx]

        try:
            return doc.load_content()
        except Exception as e:
            return f"Error loading file: {e}"

    # Button navigation
    # NOTE: Multiple callbacks write to "current-doc-id" and "timing-store".
    # Every callback that writes to these outputs MUST use allow_duplicate=True,
    # except this one (the first registered). Omitting it on any subsequent
    # callback will cause a Dash duplicate-output error at startup.
    #
    # Moves by the clicks not yet applied (nav-clicks-applied), not by one: a click
    # sent before the previous click's response arrives sees the same current-doc-id,
    # and stepping by one would lose it.
    @app.callback(
        Output("current-doc-id", "data"),
        Output("timing-store", "data"),
        Output("metadata-store", "data", allow_duplicate=True),
        Output("status-store", "data", allow_duplicate=True),
        Output("nav-clicks-applied", "data"),
        [Input("btn-prev", "n_clicks"),
         Input("btn-next", "n_clicks")],
        State("current-doc-id", "data"),
        State("timing-store", "data"),
        State("current-doc-slice", "data"),
        State("nav-clicks-applied", "data"),
        prevent_initial_call=True
    )
    def navigate_buttons(prev_clicks, next_clicks, current_doc_id, timing_data, doc_slice, applied):
        ta = _ta()
        if not ctx.triggered or not ta.documents:
            return no_update, no_update, no_update, no_update, no_update

        step, applied_out = _button_step(prev_clicks, next_clicks, applied)
        current_index = _doc_index(ta, current_doc_id) or 0
        new_index = min(max(current_index + step, 0), len(ta.documents) - 1)
        if new_index == current_index:
            return no_update, no_update, no_update, no_update, applied_out

        departing, ann, meta = _departing(doc_slice, current_doc_id)
        nav = _perform_navigation(ta, departing, new_index, timing_data, ann, meta)
        return *_nav_patches(nav, timing_data, meta), applied_out

    # Document selector. The static option list is built clientside once, at page
    # load. Status, flag and the status/flag filter are read by docFilter /
    # docRenderOption from a browser-side reference to metadata-store / filter-store
    # when the dropdown renders, so status and flag changes never re-send the options.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="buildDocOptions"),
        Output("document-select", "data"),
        Input("doc-list-store", "data"),
    )
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="updateDocSelectState"),
        Output("doc-select-state-sink", "data"),
        Input("metadata-store", "data"),
        Input("filter-store", "data"),
        State("doc-list-store", "data"),
    )

    # Keep the selector showing the current document.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="syncDocSelect"),
        Output("document-select", "value"),
        Input("current-doc-id", "data"),
        Input("document-select", "data"),
        State("document-select", "value"),
    )

    # Forward a user pick to doc-select-nav, filtering out the echo from
    # syncDocSelect clientside so it never costs a server round-trip.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="docSelectChanged"),
        Output("doc-select-nav", "data"),
        Input("document-select", "value"),
        State("current-doc-id", "data"),
        prevent_initial_call=True,
    )

    # Selector navigation (allow_duplicate=True required — see note above)
    @app.callback(
        Output("current-doc-id", "data", allow_duplicate=True),
        Output("timing-store", "data", allow_duplicate=True),
        Output("metadata-store", "data", allow_duplicate=True),
        Output("status-store", "data", allow_duplicate=True),
        Input("doc-select-nav", "data"),
        State("current-doc-id", "data"),
        State("timing-store", "data"),
        State("current-doc-slice", "data"),
        prevent_initial_call=True
    )
    def navigate_select(nav, current_doc_id, timing_data, doc_slice):
        departing, ann, meta = _departing(doc_slice, current_doc_id)
        return _nav_patches(
            _navigate_select_impl(_ta(), nav, departing, timing_data, ann, meta), timing_data, meta)

    # Auto-advance: navigate to next doc when an auto_advance widget gets a value.
    # (allow_duplicate=True required — see note above)
    @app.callback(
        Output("current-doc-id", "data", allow_duplicate=True),
        Output("timing-store", "data", allow_duplicate=True),
        Output("metadata-store", "data", allow_duplicate=True),
        Output("status-store", "data", allow_duplicate=True),
        Input("auto-advance-store", "data"),
        State("current-doc-id", "data"),
        State("timing-store", "data"),
        State("current-doc-slice", "data"),
        prevent_initial_call=True,
    )
    def navigate_auto_advance(trigger, current_doc_id, timing_data, doc_slice):
        if not trigger:
            return no_update, no_update, no_update, no_update
        ta = _ta()
        current_index = _doc_index(ta, current_doc_id) or 0
        if current_index >= len(ta.documents) - 1:
            return no_update, no_update, no_update, no_update
        departing, ann, meta = _departing(doc_slice, current_doc_id)
        return _nav_patches(_perform_navigation(ta, departing, current_index + 1, timing_data, ann, meta), timing_data, meta)

    # Sync filter controls → filter-store.
    @app.callback(
        Output("filter-store", "data"),
        Input("filter-flagged-check", "checked"),
        Input("filter-status", "value"),
        prevent_initial_call=True,
    )
    def update_filter_store(flagged, statuses):
        return {"flagged": bool(flagged), "statuses": statuses or []}

    # Finish button: accumulate time, mark current doc complete if eligible, open summary modal.
    @app.callback(
        Output("modal-finish", "opened"),
        Output("modal-finish", "title"),
        Output("finish-modal-content", "children"),
        Output("btn-go-incomplete", "style"),
        Output("metadata-store", "data", allow_duplicate=True),
        Output("status-store", "data", allow_duplicate=True),
        Output("timing-store", "data", allow_duplicate=True),
        Input("btn-finish", "n_clicks"),
        State("current-doc-id", "data"),
        State("timing-store", "data"),
        State("current-doc-slice", "data"),
        # The whole metadata-store: the summary needs every status. Finish is rare.
        State("metadata-store", "data"),
        prevent_initial_call=True,
    )
    def handle_finish(n_clicks, current_doc_id, timing_data, doc_slice, metadata_data):
        if not n_clicks:
            return no_update, no_update, no_update, no_update, no_update, no_update, no_update
        ta = _ta()
        now = time.time()
        metadata_before = metadata_data or {}
        metadata_data = dict(metadata_before)
        timing_before = timing_data
        timing_data = dict(timing_data or {})
        stores = _slice_stores(doc_slice, current_doc_id)
        annotations_data = stores[0] if stores else {}

        # Accumulate time, pause timer, and mark departing doc complete if eligible.
        if current_doc_id:
            meta = dict(_get_meta(metadata_data, current_doc_id))
            start = timing_data.get("doc_start_time")
            if start:
                meta["annotation_seconds"] = meta.get("annotation_seconds", 0.0) + (now - start)
            if meta.get("visited", False):
                meta["status"] = "complete" if _is_complete_eligible(ta, current_doc_id, annotations_data) else "in_progress"
            metadata_data[current_doc_id] = meta
            timing_data["annotation_seconds_at_load"] = meta.get("annotation_seconds", 0.0)

        # Pause the timer so it stops while the modal is open.
        timing_data["doc_start_time"] = None
        timing_data["paused"] = True
        timing_data["last_save_time"] = now

        # Compute session stats.
        total = len(ta.documents)
        complete_count = sum(
            1 for d in ta.documents
            if _get_meta(metadata_data, d.id).get("status") == "complete"
        )
        incomplete_count = total - complete_count
        total_seconds = sum(
            _get_meta(metadata_data, d.id).get("annotation_seconds", 0.0)
            for d in ta.documents
        )

        all_done = incomplete_count == 0
        title = "All Done!" if all_done else "Session Summary"
        rows = [
            dmc.Text(
                f"{'All ' + str(total) if all_done else str(complete_count) + ' / ' + str(total)} document{'s' if total != 1 else ''} complete",
                fw=500,
                **({"c": "teal"} if all_done else {}),
            ),
            dmc.Text(f"Total annotation time: {_format_seconds(total_seconds)}", size="sm", c="dimmed"),
        ]
        if not all_done:
            rows.insert(1, dmc.Text(
                f"{incomplete_count} document{'s' if incomplete_count != 1 else ''} still incomplete",
                size="sm", c="dimmed",
            ))

        go_style = {"display": "none"} if all_done else {}
        status = metadata_data.get(current_doc_id, {}).get("status", "not_started") if current_doc_id else "not_started"
        meta_out = {current_doc_id: metadata_data[current_doc_id]} if current_doc_id else {}
        return (True, title, dmc.Stack(rows, gap="xs"), go_style,
                _meta_patch(metadata_before, meta_out), status, _dict_patch(timing_before, timing_data))

    # "Go to first incomplete" — navigate and close modal.
    @app.callback(
        Output("current-doc-id", "data", allow_duplicate=True),
        Output("timing-store", "data", allow_duplicate=True),
        Output("metadata-store", "data", allow_duplicate=True),
        Output("status-store", "data", allow_duplicate=True),
        Output("modal-finish", "opened", allow_duplicate=True),
        Input("btn-go-incomplete", "n_clicks"),
        State("current-doc-id", "data"),
        State("timing-store", "data"),
        State("current-doc-slice", "data"),
        # The whole metadata-store, to find the first incomplete document. Rare.
        State("metadata-store", "data"),
        prevent_initial_call=True,
    )
    def go_to_first_incomplete(n_clicks, current_doc_id, timing_data, doc_slice, metadata_data):
        if not n_clicks:
            return no_update, no_update, no_update, no_update, no_update
        ta = _ta()
        departing, ann, meta = _departing(doc_slice, current_doc_id)
        for i, doc in enumerate(ta.documents):
            if _get_meta(metadata_data, doc.id).get("status") != "complete":
                nav = _perform_navigation(ta, departing, i, timing_data, ann, meta)
                return *_nav_patches(nav, timing_data, meta), False
        return no_update, no_update, no_update, no_update, False

    # Close finish modal.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="closeOnClick"),
        Output("modal-finish", "opened", allow_duplicate=True),
        Input("btn-close-finish", "n_clicks"),
        prevent_initial_call=True,
    )

    # Load flag and notes from metadata when the document changes. Outputs that
    # already show the right value are skipped, so save_flag / save_notes don't
    # fire on most navigations.
    @app.callback(
        Output("flag-document", "checked"),
        Output("document-notes", "value"),
        Input("doc-load-slice", "data"),
        State("flag-document", "checked"),
        State("document-notes", "value"),
    )
    def load_flag_and_notes(load_slice, shown_flag, shown_notes):
        if (load_slice or {}).get("reload"):
            return no_update, no_update
        doc_id = (load_slice or {}).get("doc_id") or ""
        _, meta = _slice_stores(load_slice)
        return _load_flag_and_notes_impl(doc_id, meta, shown_flag, shown_notes)

    # Handle flag-document changes. Also fires when load_flag_and_notes sets the
    # checkbox on navigation; the impl skips the write when nothing changed.
    @app.callback(
        Output("metadata-store", "data", allow_duplicate=True),
        Input("flag-document", "checked"),
        State("current-doc-id", "data"),
        State("current-doc-slice", "data"),
        prevent_initial_call=True,
    )
    def save_flag(checked, doc_id, doc_slice):
        stores = _slice_stores(doc_slice, doc_id)
        if stores is None:
            return no_update
        return _meta_patch(stores[1], _save_flag_impl(checked, doc_id, stores[1]))

    # Handle document-notes changes (same no-op-on-navigation guard as save_flag).
    @app.callback(
        Output("metadata-store", "data", allow_duplicate=True),
        Input("document-notes", "value"),
        State("current-doc-id", "data"),
        State("current-doc-slice", "data"),
        prevent_initial_call=True
    )
    def save_notes(notes, doc_id, doc_slice):
        stores = _slice_stores(doc_slice, doc_id)
        if stores is None:
            return no_update
        return _meta_patch(stores[1], _save_notes_impl(notes, doc_id, stores[1]))

    if has_instructions:
        app.clientside_callback(
            ClientsideFunction(namespace="tater", function_name="openOnClick"),
            Output("instructions-drawer", "opened"),
            Input("btn-open-instructions", "n_clicks"),
            prevent_initial_call=True,
        )

    is_hosted = tater_app.is_hosted

    # Save deltas (#108): emitSaveDelta sends only the documents that changed, so
    # saving never uploads the whole stores. initSaveBaseline records the stores as
    # loaded, before anything changes them, for emitSaveDelta to diff against.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="initSaveBaseline"),
        Output("save-baseline-sink", "data"),
        Input("doc-list-store", "data"),
        State("annotations-store", "data"),
        State("metadata-store", "data"),
    )
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="emitSaveDelta"),
        Output("save-delta", "data"),
        Input("annotations-store", "data"),
        Input("metadata-store", "data"),
        prevent_initial_call=True,
    )

    if is_hosted:
        # No auto-save in hosted mode, but keep the session's copy of the stores
        # current so a page refresh doesn't fall back to the uploaded state.
        @app.callback(
            Input("save-delta", "data"),
            prevent_initial_call=True,
        )
        def mirror_stores(delta):
            _ta()._apply_save_delta(delta)

        # Download annotations as JSON
        @app.callback(
            Output("download-annotations", "data"),
            Output("timing-store", "data", allow_duplicate=True),
            Input("btn-download", "n_clicks"),
            State("annotations-store", "data"),
            State("metadata-store", "data"),
            State("timing-store", "data"),
            prevent_initial_call=True,
        )
        def download_annotations(n_clicks, annotations_data, metadata_data, timing_data):
            if not n_clicks:
                return no_update, no_update
            save_dict = {}
            all_ids = set(annotations_data or {}) | set(metadata_data or {})
            for d_id in all_ids:
                save_dict[d_id] = {
                    "annotations": (annotations_data or {}).get(d_id, {}),
                    "metadata": (metadata_data or {}).get(d_id, {}),
                }
            timing_data = dict(timing_data or {})
            timing_data["last_save_time"] = time.time()
            return {"content": json.dumps(save_dict, indent=2), "filename": "annotations.json"}, timing_data

        # Start over: open confirmation modal
        @app.callback(
            Output("modal-start-over", "opened"),
            Input("btn-start-over", "n_clicks"),
            Input("btn-start-over-cancel", "n_clicks"),
            prevent_initial_call=True,
        )
        def toggle_start_over_modal(open_clicks, cancel_clicks):
            return ctx.triggered_id == "btn-start-over"

        # Confirm start over: clear Flask session and redirect
        @app.callback(
            Output("annotate-location", "href"),
            Input("btn-start-over-confirm", "n_clicks"),
            prevent_initial_call=True,
        )
        def start_over(n_clicks):
            if not n_clicks:
                return no_update
            flask.session.pop("tater_session", None)
            return "/"

    if not is_hosted:
        # Auto-save: merge the changed documents into the server copy and write the
        # file from it. Not registered in hosted mode — no annotations_path.
        @app.callback(
            Output("timing-store", "data", allow_duplicate=True),
            Input("save-delta", "data"),
            prevent_initial_call=True,
        )
        def auto_save(delta):
            if not _ta()._save_delta_to_file(delta):
                return no_update
            patch = Patch()
            patch["last_save_time"] = time.time()
            return patch


def _setup_timing_callbacks(tater_app: TaterApp, _ta=None) -> None:
    """Setup callbacks for save time and document timing display."""
    app = tater_app.app
    if _ta is None:
        def _ta():
            return tater_app

    # Manual save button — flush timing into metadata, update last_save_time.
    # Auto-save callback handles the actual file write when metadata-store changes.
    @app.callback(
        Output("timing-store", "data", allow_duplicate=True),
        Output("metadata-store", "data", allow_duplicate=True),
        Input("btn-save", "n_clicks"),
        State("current-doc-id", "data"),
        State("timing-store", "data"),
        State("current-doc-slice", "data"),
        prevent_initial_call=True,
    )
    def on_save_click(n_clicks, current_doc_id, timing_data, doc_slice):
        if not n_clicks:
            return no_update, no_update
        stores = _slice_stores(doc_slice, current_doc_id)
        if stores is None:
            return no_update, no_update
        metadata_before = stores[1]
        metadata_data = metadata_before
        now = time.time()
        if timing_data is None:
            timing_data = {}
        metadata_data = dict(metadata_data or {})
        # Flush elapsed time into metadata before saving, then reset the start
        # so the clientside timer continues without double-counting.
        paused = timing_data.get("paused", False)
        if not paused:
            start = timing_data.get("doc_start_time")
            if start and current_doc_id:
                meta = dict(_get_meta(metadata_data, current_doc_id))
                meta["annotation_seconds"] = meta.get("annotation_seconds", 0.0) + (now - start)
                metadata_data[current_doc_id] = meta
            timing_data["doc_start_time"] = now
            meta = _get_meta(metadata_data, current_doc_id)
            timing_data["annotation_seconds_at_load"] = meta.get("annotation_seconds", 0.0)
        timing_data["last_save_time"] = now
        meta_out = {current_doc_id: metadata_data[current_doc_id]} if current_doc_id in metadata_data else {}
        return timing_data, _meta_patch(metadata_before, meta_out)

    # Set up the arriving document (visited, status, timer) on page load and on
    # navigation. doc-load-slice is an Input, not State, so Dash runs this only after
    # buildDocSlices has the arriving document's data (State isn't waited for).
    @app.callback(
        Output("timing-store", "data", allow_duplicate=True),
        Output("status-store", "data", allow_duplicate=True),
        Output("metadata-store", "data", allow_duplicate=True),
        Input("doc-load-slice", "data"),
        State("timing-store", "data"),
        prevent_initial_call='initial_duplicate',
    )
    def on_doc_change(load_slice, timing_data):
        if (load_slice or {}).get("reload"):
            return no_update, no_update, no_update
        doc_id = (load_slice or {}).get("doc_id") or ""
        ann, meta = _slice_stores(load_slice)
        timing_out, status, meta_out = _on_doc_change_impl(_ta(), doc_id, timing_data, ann, meta)
        return _dict_patch(timing_data, timing_out), status, _meta_patch(meta, meta_out)

    # Update save status and pause icon whenever timing-store changes (i.e. on every save,
    # navigation, or pause toggle) — no interval needed, no "Updating..." flicker.
    @app.callback(
        Output("save-status-text", "children"),
        Output("save-status-text", "c"),
        Input("timing-store", "data"),
    )
    def update_save_status(timing_data):
        return _update_save_status_impl(_ta(), timing_data)

    # Update the doc timer display every second — runs entirely in the browser so
    # there is no server round-trip and no "Updating..." tab-title flicker.
    # Reads annotation_seconds_at_load from timing-store (written on doc load,
    # navigation, and pause) so it never needs to call back to Python.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="updateTimer"),
        Output("timing-text", "children"),
        Output("btn-pause-timer-icon", "icon"),
        Input("clock-interval", "n_intervals"),
        Input("timing-store", "data"),
    )

    @app.callback(
        Output("timing-store", "data", allow_duplicate=True),
        Output("metadata-store", "data", allow_duplicate=True),
        Input("btn-pause-timer", "n_clicks"),
        State("timing-store", "data"),
        State("current-doc-id", "data"),
        State("current-doc-slice", "data"),
        prevent_initial_call=True,
    )
    def toggle_pause(n_clicks, timing_data, doc_id, doc_slice):
        stores = _slice_stores(doc_slice, doc_id)
        if stores is None:
            return no_update, no_update
        timing_out, meta_out = _toggle_pause_impl(n_clicks, timing_data, doc_id, stores[1])
        if timing_out is no_update:
            return no_update, no_update
        meta_out = {doc_id: meta_out[doc_id]} if doc_id and doc_id in meta_out else {}
        return timing_out, _meta_patch(stores[1], meta_out)

    @app.callback(
        Output("status-badge", "children"),
        Output("status-badge", "color"),
        Input("status-store", "data"),
    )
    def update_status_badge(status):
        return _status_display(status)

    @app.callback(
        Output("notification-container", "sendNotifications"),
        Input("schema-warnings-store", "data"),
    )
    def show_schema_warnings(warnings):
        if not warnings:
            return no_update

        _LABELS = {
            "extra": "In saved file, not in current schema — will be removed on save:",
            "missing": "In current schema, not in saved file — will initialize to default:",
        }

        sections = []
        for key in ("extra", "missing"):
            fields = warnings.get(key)
            if not fields:
                continue
            if sections:
                sections.append(html.Div(style={"height": "6px"}))
            sections.append(html.Div(_LABELS[key], style={"fontWeight": 600, "fontSize": "0.8rem"}))
            sections.append(html.Ul(
                [html.Li(f) for f in fields],
                style={"margin": "2px 0 0 0", "paddingLeft": "16px", "listStylePosition": "inside"},
            ))

        return [{
            "id": "schema-mismatch-notification",
            "title": "Schema mismatch",
            "message": html.Div(sections, style={"maxHeight": "200px", "overflowY": "auto"}),
            "color": "yellow",
            "action": "show",
            "autoClose": False,
        }]


# ---------------------------------------------------------------------------
# Extracted callback implementations — module-level for unit testability.
# The registered callbacks are thin shells that call these with _ta().
# See tests/test_callbacks_core.py for the rationale.
# ---------------------------------------------------------------------------

def _update_save_status_impl(ta, timing_data):
    """Business logic for update_save_status callback.

    Returns (text, color) to display in the save-status footer element.
    Branches: save error → red; saved at time → dimmed; never saved → dimmed.
    """
    if ta._save_error:
        return f"Save failed: {ta._save_error}", "red"
    if timing_data and timing_data.get("last_save_time"):
        dt = datetime.fromtimestamp(timing_data["last_save_time"])
        return f"Last saved: {dt.strftime('%H:%M:%S')}", "dimmed"
    return "Not saved", "dimmed"


def _button_step(prev_clicks, next_clicks, applied):
    """Documents to move for the Prev/Next clicks not yet applied.

    ``applied`` is ``nav-clicks-applied``, the click counts the last navigation handled.
    Returns ``(step, applied_out)``: e.g. two Next clicks whose requests overlap compute
    +1 and +2 from the same position, so the second response lands on the right document.
    """
    applied = applied or {}
    prev, nxt = prev_clicks or 0, next_clicks or 0
    step = (nxt - applied.get("next", 0)) - (prev - applied.get("prev", 0))
    return step, {"prev": prev, "next": nxt}


def _departing(doc_slice, current_doc_id):
    """``(departing_id, annotations, metadata)`` for a navigation callback.

    The stores are one-document dicts from ``current-doc-slice``. If the slice isn't
    for ``current_doc_id`` (it lags a moment behind a navigation), the departing
    document isn't updated rather than overwritten with defaults.
    """
    stores = _slice_stores(doc_slice, current_doc_id)
    if stores is None:
        return None, {}, {}
    return current_doc_id, stores[0], stores[1]


def _nav_patches(result, timing_before, meta_before):
    """Turn ``_perform_navigation``'s dicts into Patches for timing- and metadata-store."""
    doc_id, timing_out, meta_out, status = result
    if doc_id is no_update:
        return result
    return doc_id, _dict_patch(timing_before, timing_out), _meta_patch(meta_before, meta_out), status


def _on_doc_change_impl(ta, doc_id, timing_data, annotations_data, metadata_data):
    """Business logic for on_doc_change: set up the arriving document.

    Runs on page load and after every navigation. Marks the document visited, sets its
    in-flight status, and points the timer at its stored seconds. The clock is started
    only if nothing started it: navigation callbacks already restarted it.

    Returns ``(timing_data, status, metadata)``; ``metadata`` is ``{doc_id: meta}``, or
    ``no_update`` when the document's metadata didn't change (a revisit).
    """
    metadata_out = no_update
    meta = _get_meta(metadata_data, doc_id) if doc_id else {}
    if doc_id:
        new_meta = {doc_id: {**meta, "visited": True}}
        update_status_for_doc(ta, doc_id, annotations_data, new_meta)
        if new_meta[doc_id] != meta:
            metadata_out = new_meta
        meta = new_meta[doc_id]

    now = time.time()
    timing_data = dict(timing_data or {})
    if not timing_data.get("doc_start_time"):
        timing_data["doc_start_time"] = now
        timing_data["paused"] = False
    if timing_data.get("session_start_time") is None:
        timing_data["session_start_time"] = now
    timing_data["annotation_seconds_at_load"] = meta.get("annotation_seconds", 0.0)

    status = meta.get("status", "not_started") if doc_id else "not_started"
    return timing_data, status, metadata_out


def _navigate_select_impl(ta, nav, current_doc_id, timing_data, annotations_data, metadata_data):
    """Business logic for navigate_select callback.

    ``nav`` is ``{"id": doc_id, "t": timestamp}`` written by the docSelectChanged
    clientside callback. Returns the four navigation outputs, or all no_update
    when the target is missing, unknown, or already the current document.
    """
    target_id = (nav or {}).get("id")
    if not target_id or target_id == current_doc_id:
        return no_update, no_update, no_update, no_update
    new_index = _doc_index(ta, target_id)
    if new_index is None:
        return no_update, no_update, no_update, no_update
    return _perform_navigation(ta, current_doc_id, new_index, timing_data, annotations_data, metadata_data)


def _load_flag_and_notes_impl(doc_id, metadata_data, shown_flag, shown_notes):
    """Business logic for load_flag_and_notes callback.

    Returns (checked, notes) for the flag checkbox and notes textarea, with
    no_update for any control that already shows the stored value.
    """
    if doc_id:
        meta = _get_meta(metadata_data, doc_id)
        flag, notes = bool(meta.get("flagged", False)), meta.get("notes", "") or ""
    else:
        flag, notes = False, ""
    return (
        no_update if bool(shown_flag) == flag else flag,
        no_update if (shown_notes or "") == notes else notes,
    )


def _save_flag_impl(checked, doc_id, metadata_data):
    """Business logic for save_flag callback.

    Returns the updated metadata_data, or no_update when there is no current
    document or the flag already has this value (e.g. set by load_flag_and_notes
    on navigation) — avoiding a spurious metadata write and auto-save.
    """
    if not doc_id:
        return no_update
    meta = _get_meta(metadata_data, doc_id)
    if bool(meta.get("flagged", False)) == bool(checked):
        return no_update
    metadata_data = dict(metadata_data or {})
    meta = dict(meta)
    meta["flagged"] = bool(checked)
    metadata_data[doc_id] = meta
    return metadata_data


def _save_notes_impl(notes, doc_id, metadata_data):
    """Business logic for save_notes callback. Same no-op guard as _save_flag_impl."""
    if not doc_id:
        return no_update
    notes = notes or ""
    meta = _get_meta(metadata_data, doc_id)
    if (meta.get("notes") or "") == notes:
        return no_update
    metadata_data = dict(metadata_data or {})
    meta = dict(meta)
    meta["notes"] = notes
    metadata_data[doc_id] = meta
    return metadata_data


def _toggle_pause_impl(n_clicks, timing_data, doc_id, metadata_data):
    """Business logic for toggle_pause callback.

    On pause: flushes elapsed seconds into metadata, clears doc_start_time,
    and updates annotation_seconds_at_load so the clientside timer stays correct.
    On resume: restores doc_start_time to now.
    Returns (timing_data, metadata_data).
    """
    if not n_clicks:
        return no_update, no_update
    if timing_data is None:
        timing_data = {}
    metadata_data = dict(metadata_data or {})
    now = time.time()
    currently_paused = timing_data.get("paused", False)
    if not currently_paused:
        start = timing_data.get("doc_start_time")
        if start and doc_id:
            meta = dict(_get_meta(metadata_data, doc_id))
            meta["annotation_seconds"] = meta.get("annotation_seconds", 0.0) + (now - start)
            metadata_data[doc_id] = meta
        timing_data["doc_start_time"] = None
        timing_data["paused"] = True
        meta = _get_meta(metadata_data, doc_id) if doc_id else {}
        timing_data["annotation_seconds_at_load"] = meta.get("annotation_seconds", 0.0)
    else:
        timing_data["doc_start_time"] = now
        timing_data["paused"] = False
    return timing_data, metadata_data


def setup_value_capture_callbacks(tater_app: TaterApp) -> None:
    """Setup unified callbacks to capture all ControlWidget value changes."""
    app = tater_app.app

    _ta = session_resolver(tater_app)

    # --- Clientside capture: value prop (all non-boolean ControlWidgets) ---
    # Runs in the browser so annotations-store is always current — no stale-State
    # race with concurrent clientside span/repeater mutations.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="captureValue"),
        Output("annotations-store", "data", allow_duplicate=True),
        Output("auto-advance-store", "data", allow_duplicate=True),
        Input({"type": "tater-control", "ld": ALL, "path": ALL, "tf": ALL}, "value"),
        State("current-doc-id", "data"),
        State("annotations-store", "data"),
        State("aa-fields-store", "data"),
        prevent_initial_call=True,
    )

    # --- Clientside capture: checked prop (BooleanWidgets) ---
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="captureChecked"),
        Output("annotations-store", "data", allow_duplicate=True),
        Output("auto-advance-store", "data", allow_duplicate=True),
        Input({"type": "tater-bool-control", "ld": ALL, "path": ALL, "tf": ALL}, "checked"),
        State("current-doc-id", "data"),
        State("annotations-store", "data"),
        State("aa-fields-store", "data"),
        prevent_initial_call=True,
    )

    # --- Downstream: recompute status whenever annotations change ---
    # Clientside: an edit sets a visited document back to in_progress (e.g. after Finish
    # marked it complete). Usually the status is unchanged and nothing is written.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="updateStatusFromAnnotations"),
        Output("status-store", "data", allow_duplicate=True),
        Output("metadata-store", "data", allow_duplicate=True),
        Input("annotations-store", "data"),
        State("current-doc-id", "data"),
        State("metadata-store", "data"),
        prevent_initial_call=True,
    )

    # --- Clientside load: value prop --- push annotation values to widgets on doc change
    # or repeater delete.  ev-lookup-store supplies per-field empty values so the server
    # is not needed; hosted-mode sessions each write their own ev-lookup-store at layout time.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="loadValues"),
        Output({"type": "tater-control", "ld": ALL, "path": ALL, "tf": ALL}, "value"),
        Input("current-doc-id", "data"),
        Input("repeater-load-trigger", "data"),
        State("annotations-store", "data"),
        State("ev-lookup-store", "data"),
        prevent_initial_call="initial_duplicate",
    )

    # --- Clientside load: checked prop ---
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="loadChecked"),
        Output({"type": "tater-bool-control", "ld": ALL, "path": ALL, "tf": ALL}, "checked"),
        Input("current-doc-id", "data"),
        Input("repeater-load-trigger", "data"),
        State("annotations-store", "data"),
        State("ev-lookup-store", "data"),
        prevent_initial_call="initial_duplicate",
    )



def _decode_field_path(ld: str, path: str, tf: str) -> str:
    """Reconstruct a dot-notation field path from schema_id components.

    For standalone widgets (``ld == ""``), ``tf`` holds the full pipe-encoded
    path and is simply decoded.

    For repeater items, ``ld`` is the pipe-joined list-field path
    (e.g. ``"pets"`` or ``"findings|annotations"``), ``path`` is the
    dot-joined index chain (e.g. ``"0"`` or ``"0.2"``), and ``tf`` is the
    widget's schema_field within the item (e.g. ``"kind"``).  The three parts
    are interleaved to reconstruct the full path.
    """
    if not ld:
        return tf.replace("|", ".")
    list_fields = ld.split("|")
    indices = path.split(".")
    parts: list[str] = []
    for seg, idx in zip(list_fields, indices):
        parts.extend([seg, idx])
    # tf may itself be pipe-encoded when the widget is a GroupWidget child
    # (e.g. "booleans|is_indoor" → "booleans.is_indoor").
    parts.append(tf.replace("|", "."))
    return ".".join(parts)
