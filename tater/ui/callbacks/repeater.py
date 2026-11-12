"""Repeater and nested-repeater callbacks."""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from dash import Input, Output, State, ALL, MATCH, ctx, no_update, ClientsideFunction
from dash.exceptions import PreventUpdate

from tater.ui import value_helpers
from tater.ui.callbacks.helpers import _get_ann, _slice_stores, session_resolver
from tater.widgets.base import ContainerWidget, ControlWidget
from tater.widgets.repeater import (
    RepeaterWidget,
    _NESTED_ADD_TYPE,
    _NESTED_DELETE_TYPE,
    _NESTED_STORE_TYPE,
    _NESTED_ITEMS_TYPE,
)

if TYPE_CHECKING:
    from tater.ui.tater_app import TaterApp


# ---------------------------------------------------------------------------
# Widget-tree helpers
# ---------------------------------------------------------------------------

def _find_repeater_template(widgets: list, field_path: str):
    """Find the RepeaterWidget template for a (possibly nested) field path.

    Strips numeric segments so ``"findings.0.annotations"`` resolves the same
    template as ``"findings.annotations"``.
    """
    segments = [s for s in field_path.split(".") if not s.isdigit()]
    return _find_by_segments(widgets, segments)


def _find_by_segments(widgets: list, segments: list):
    if not segments:
        return None
    for w in widgets:
        if w.schema_field == segments[0]:
            if len(segments) == 1:
                return w if isinstance(w, RepeaterWidget) else None
            if isinstance(w, RepeaterWidget):
                return _find_by_segments(w.item_widgets, segments[1:])
    return None


def _compute_empty_item(widget_template) -> dict | None:
    """Return a dict of schema_field → empty_value for a new repeater item.

    Used to build the ADD descriptor so the clientside callback can push the
    correct structure to the annotation list without a round-trip.
    Returns None if no fields can be determined (clientside pushes null).
    """
    from tater.widgets.span import SpanAnnotationWidget
    item = {}
    for iw in widget_template.item_widgets:
        if isinstance(iw, ControlWidget):
            item[iw.schema_field] = iw.empty_value
        elif isinstance(iw, SpanAnnotationWidget):
            item[iw.schema_field] = []
        elif isinstance(iw, RepeaterWidget):
            item[iw.schema_field] = []
    return item if item else None


# ---------------------------------------------------------------------------
# Callback registration
# ---------------------------------------------------------------------------

def setup_repeater_callbacks(tater_app: TaterApp) -> None:
    """Register a single MATCH callback handling all repeaters at every nesting depth."""
    app = tater_app.app
    _ta = session_resolver(tater_app)

    # --- Unified MATCH callback ---
    # Uses repeater-ann-relay (MATCH) instead of annotations-store (static) to avoid
    # Dash's prohibition on mixing MATCH and static string outputs in one callback.
    #
    # ann-relay now carries a descriptor dict {op, field, pos/item} rather than a
    # full annotations dict.  The actual store mutation runs clientside (applyRepeaterOp)
    # so it always operates on the current browser-side annotations — not a stale
    # server-side State that may lag behind clientside span adds.
    @app.callback(
        [Output({"type": "repeater-store",     "field": MATCH}, "data"),
         Output({"type": "repeater-items",     "field": MATCH}, "children"),
         Output({"type": "repeater-change",    "field": MATCH}, "data"),
         Output({"type": "repeater-ann-relay", "field": MATCH}, "data")],
        [Input({"type": "repeater-add",    "field": MATCH}, "n_clicks"),
         Input({"type": "repeater-delete", "field": MATCH, "index": ALL}, "n_clicks"),
         Input("doc-load-slice", "data")],
        [State({"type": "repeater-store",  "field": MATCH}, "data"),
         State({"type": "repeater-change", "field": MATCH}, "data"),
         State("current-doc-slice", "data")],
        prevent_initial_call="initial_duplicate",
    )
    def update_repeater(add_clicks, delete_clicks, load_slice, store_data, change_count, doc_slice):
        pipe_field = ctx.outputs_list[0]["id"]["field"]
        field_path = pipe_field.replace("|", ".")

        # Find the template and finalize its field_path for rendering.
        ta = _ta()
        template = _find_repeater_template(ta.widgets, field_path)
        if template is None:
            raise PreventUpdate
        widget = copy.deepcopy(template)
        parts = field_path.rsplit(".", 1)
        widget._finalize_paths(parent_path=parts[0] if len(parts) > 1 else "")

        # Doc navigation / initial load: reload indices from annotation.
        if not ctx.triggered_id or ctx.triggered_id == "doc-load-slice":
            if (load_slice or {}).get("reload"):
                raise PreventUpdate  # a repeater delete; loadValues refreshes the values
            doc_id = (load_slice or {}).get("doc_id")
            annotations_data, _ = _slice_stores(load_slice)
            indices = []
            if doc_id:
                ann = _get_ann(annotations_data, doc_id)
                if ann is not None:
                    lst = value_helpers.get_model_value(ann, field_path)
                    if isinstance(lst, list):
                        indices = list(range(len(lst)))
            store_data = {"indices": indices, "next_index": len(indices)}
            return store_data, widget._render_items(indices, ta, doc_id, annotations_data=annotations_data), no_update, no_update

        if not ctx.triggered or not ctx.triggered[0].get("value"):
            raise PreventUpdate

        # Add / delete: the current document, from the slice.
        doc_id = (doc_slice or {}).get("doc_id")
        annotations_data, _ = _slice_stores(doc_slice)

        if store_data is None:
            store_data = {"indices": [], "next_index": 0}

        indices = list(store_data.get("indices", []))
        active_value = None
        is_delete = False
        ann_relay = no_update

        if isinstance(ctx.triggered_id, dict) and ctx.triggered_id.get("type") == "repeater-add":
            new_index = len(indices)
            indices = list(range(new_index + 1))
            active_value = str(new_index)
            if doc_id:
                empty_item = _compute_empty_item(widget)
                ann_relay = {"op": "add", "field": field_path, "item": empty_item}

        elif isinstance(ctx.triggered_id, dict) and ctx.triggered_id.get("type") == "repeater-delete":
            delete_index = ctx.triggered_id.get("index")
            if delete_index in indices:
                del_position = indices.index(delete_index)
                ann_relay = {"op": "delete", "field": field_path, "pos": del_position}
                indices = list(range(len(indices) - 1))
                active_value = str(indices[0]) if indices else None
                is_delete = True

        new_data = {"indices": indices, "next_index": len(indices)}
        new_change = (change_count or 0) + 1 if is_delete else no_update
        # On delete, render without baked annotation defaults — item positions shift and
        # stale server State would bake wrong values; loadValues corrects them after
        # applyRepeaterOp updates the store.
        # On add, use annotations_data (current browser State): the new item has no
        # annotation entry yet so it renders empty naturally, and existing items render
        # with their current values so captureValue does not fire spurious null writes.
        render_annotations = None if is_delete else annotations_data
        return new_data, widget._render_items(indices, ta, doc_id, active_value=active_value, annotations_data=render_annotations), new_change, ann_relay

    # --- Clientside: apply repeater op to annotations-store + increment span-any-change on delete ---
    # Runs in the browser so it reads the CURRENT annotations-store (including any clientside
    # span adds that haven't been reflected in the server-side State yet).  This avoids the race
    # where a server-side relay would overwrite clientside span data with a stale snapshot.
    # Also increments repeater-load-trigger on delete so load_values fires to push the now-correct
    # store values back into the re-rendered (empty) widget components.
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="applyRepeaterOp"),
        Output("annotations-store", "data", allow_duplicate=True),
        Output("span-any-change", "data", allow_duplicate=True),
        Output("repeater-load-trigger", "data", allow_duplicate=True),
        Input({"type": "repeater-ann-relay", "field": ALL}, "data"),
        State("current-doc-id", "data"),
        State("annotations-store", "data"),
        State("span-any-change", "data"),
        State("repeater-load-trigger", "data"),
        prevent_initial_call=True,
    )


def setup_nested_repeater_callbacks(tater_app: TaterApp) -> None:
    """Register a single generic MATCH callback for all nested repeater instances."""
    app = tater_app.app
    _ta = session_resolver(tater_app)

    def _find_nested_template(ld: str):
        segments = ld.split("-")
        search_in = _ta().widgets
        current = None
        for seg in segments:
            found = next((w for w in search_in if w.schema_field == seg), None)
            if found is None:
                return None, None, None
            current = found
            search_in = getattr(current, "item_widgets", [])
        if not isinstance(current, RepeaterWidget):
            return None, None, None
        return current, segments[0], segments[-1]

    @app.callback(
        [
            Output({"type": _NESTED_STORE_TYPE, "ld": MATCH, "li": MATCH}, "data"),
            Output({"type": _NESTED_ITEMS_TYPE, "ld": MATCH, "li": MATCH}, "children"),
            Output({"type": "nested-repeater-ann-relay", "ld": MATCH, "li": MATCH}, "data"),
        ],
        [
            Input({"type": _NESTED_ADD_TYPE, "ld": MATCH, "li": MATCH}, "n_clicks"),
            Input(
                {"type": _NESTED_DELETE_TYPE, "ld": MATCH, "li": MATCH, "inner_li": ALL},
                "n_clicks",
            ),
        ],
        [
            State({"type": _NESTED_STORE_TYPE, "ld": MATCH, "li": MATCH}, "data"),
            State("current-doc-id", "data"),
            State("current-doc-slice", "data"),
        ],
        prevent_initial_call=True,
    )
    def _update_nested_items(add_clicks, delete_clicks, store_data, doc_id, doc_slice):
        stores = _slice_stores(doc_slice, doc_id)
        annotations_data = stores[0] if stores else {}
        ld = ctx.outputs_list[0]["id"]["ld"]
        outer_li = ctx.outputs_list[0]["id"]["li"]

        template, outer_list_field, item_field = _find_nested_template(ld)
        if template is None:
            raise PreventUpdate

        if not ctx.triggered or not ctx.triggered[0].get("value"):
            raise PreventUpdate

        if store_data is None:
            store_data = {"indices": [], "next_index": 0}

        ta = _ta()
        indices = list(store_data.get("indices", []))
        ann_relay = no_update
        is_delete = False

        full_path = f"{outer_list_field}.{outer_li}.{item_field}"

        if isinstance(ctx.triggered_id, dict) and ctx.triggered_id.get("type") == _NESTED_ADD_TYPE:
            new_index = len(indices)
            indices = list(range(new_index + 1))
            if doc_id:
                empty_item = _compute_empty_item(template)
                ann_relay = {"op": "add", "field": full_path, "item": empty_item}

        elif isinstance(ctx.triggered_id, dict) and ctx.triggered_id.get("type") == _NESTED_DELETE_TYPE:
            inner_li_del = ctx.triggered_id.get("inner_li")
            if inner_li_del in indices:
                del_position = indices.index(inner_li_del)
                ann_relay = {"op": "delete", "field": full_path, "pos": del_position}
                indices = list(range(len(indices) - 1))
                is_delete = True

        new_data = {"indices": indices, "next_index": len(indices)}
        # On delete, render without baked annotation defaults — item positions shift and
        # stale server State would bake wrong values; loadValues corrects them after
        # applyRepeaterOp updates the store.
        # On add, use annotations_data: the new item has no annotation entry yet so it
        # renders empty naturally, and existing items render with current values so
        # captureValue does not fire spurious null writes.
        render_ann = None if is_delete else annotations_data
        return new_data, template._render_nested_items(
            indices, ld, outer_li, outer_list_field, item_field, ta, doc_id, render_ann
        ), ann_relay

    # ---- Clientside: apply nested repeater op to annotations-store ----
    app.clientside_callback(
        ClientsideFunction(namespace="tater", function_name="applyRepeaterOp"),
        Output("annotations-store", "data", allow_duplicate=True),
        Output("span-any-change", "data", allow_duplicate=True),
        Output("repeater-load-trigger", "data", allow_duplicate=True),
        Input({"type": "nested-repeater-ann-relay", "ld": ALL, "li": ALL}, "data"),
        State("current-doc-id", "data"),
        State("annotations-store", "data"),
        State("span-any-change", "data"),
        State("repeater-load-trigger", "data"),
        prevent_initial_call=True,
    )
