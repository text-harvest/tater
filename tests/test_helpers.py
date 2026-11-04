"""Tests for tater/ui/callbacks/helpers.py — pure helper functions."""
from __future__ import annotations

import time
import types

import pytest
from dash import no_update

from tater.ui.callbacks.helpers import (
    _build_ev_lookup,
    _collect_all_control_templates,
    _collect_value_capture_widgets,
    _default_meta,
    _doc_index,
    _get_ann,
    _get_meta,
    _dict_patch,
    _meta_patch,
    _perform_navigation,
    _slice_stores,
    _status_display,
)
from tater.models.document import Document
from tater.widgets.checkbox import CheckboxWidget
from tater.widgets.group import GroupWidget
from tater.widgets.radio_group import RadioGroupWidget
from tater.widgets.repeater import ListableWidget
from tater.widgets.text_input import TextInputWidget


# ---------------------------------------------------------------------------
# Minimal tater_app stand-in (avoids spinning up a full Dash app)
# ---------------------------------------------------------------------------

def _make_ta(docs, required_widgets=None):
    ta = types.SimpleNamespace()
    ta.documents = docs
    ta._required_widgets = required_widgets or []
    return ta


def _doc(doc_id, name=None):
    return Document(id=doc_id, text="Some text", name=name or doc_id)


# ---------------------------------------------------------------------------
# _status_display
# ---------------------------------------------------------------------------

class TestStatusDisplay:
    def test_not_started(self):
        label, color = _status_display("not_started")
        assert label == "Not Started"
        assert color == "gray"

    def test_in_progress(self):
        label, color = _status_display("in_progress")
        assert label == "In Progress"
        assert color == "blue"

    def test_complete(self):
        label, color = _status_display("complete")
        assert label == "Complete"
        assert color == "teal"

    def test_unknown_status_falls_back_to_raw(self):
        label, color = _status_display("some_unknown")
        assert label == "some_unknown"
        assert color == "gray"


# ---------------------------------------------------------------------------
# _get_ann
# ---------------------------------------------------------------------------

class TestGetAnn:
    def test_returns_annotation_for_doc(self):
        data = {"doc1": {"label": "positive"}}
        assert _get_ann(data, "doc1") == {"label": "positive"}

    def test_returns_none_for_missing_doc(self):
        data = {"doc1": {}}
        assert _get_ann(data, "doc2") is None

    def test_returns_none_for_empty_data(self):
        assert _get_ann({}, "doc1") is None

    def test_returns_none_for_none_data(self):
        assert _get_ann(None, "doc1") is None

    def test_returns_none_for_none_doc_id(self):
        assert _get_ann({"doc1": {}}, None) is None


# ---------------------------------------------------------------------------
# _get_meta
# ---------------------------------------------------------------------------

class TestGetMeta:
    def test_returns_defaults_when_no_data(self):
        meta = _get_meta(None, "doc1")
        assert meta["flagged"] is False
        assert meta["notes"] == ""
        assert meta["annotation_seconds"] == 0.0
        assert meta["visited"] is False
        assert meta["status"] == "not_started"

    def test_returns_defaults_when_doc_absent(self):
        meta = _get_meta({}, "doc1")
        assert meta == _default_meta()

    def test_merges_stored_values_with_defaults(self):
        stored = {"flagged": True, "notes": "review"}
        meta = _get_meta({"doc1": stored}, "doc1")
        assert meta["flagged"] is True
        assert meta["notes"] == "review"
        # Defaults fill in missing keys
        assert meta["annotation_seconds"] == 0.0
        assert meta["visited"] is False

    def test_stored_values_override_defaults(self):
        stored = {"annotation_seconds": 42.5, "visited": True, "status": "complete"}
        meta = _get_meta({"doc1": stored}, "doc1")
        assert meta["annotation_seconds"] == 42.5
        assert meta["visited"] is True
        assert meta["status"] == "complete"

    def test_returns_none_when_no_doc_id(self):
        meta = _get_meta({"doc1": {}}, None)
        assert meta == _default_meta()


# ---------------------------------------------------------------------------
# _collect_value_capture_widgets
# ---------------------------------------------------------------------------

class TestCollectValueCaptureWidgets:
    def test_flat_list_returns_control_widgets(self):
        radio = RadioGroupWidget("label", label="Label")
        text = TextInputWidget("notes", label="Notes")
        result = _collect_value_capture_widgets([radio, text])
        assert result == [radio, text]

    def test_repeater_is_skipped(self):
        repeater = ListableWidget("pets", item_widgets=[RadioGroupWidget("kind")])
        result = _collect_value_capture_widgets([repeater])
        assert result == []

    def test_group_children_are_included(self):
        child = CheckboxWidget("indoor")
        group = GroupWidget("booleans", children=[child])
        result = _collect_value_capture_widgets([group])
        assert result == [child]

    def test_nested_groups_are_recursed(self):
        inner_child = TextInputWidget("name")
        inner_group = GroupWidget("details", children=[inner_child])
        outer_group = GroupWidget("outer", children=[inner_group])
        result = _collect_value_capture_widgets([outer_group])
        assert result == [inner_child]

    def test_mixed_list(self):
        radio = RadioGroupWidget("label")
        child = CheckboxWidget("indoor")
        group = GroupWidget("booleans", children=[child])
        repeater = ListableWidget("pets", item_widgets=[RadioGroupWidget("kind")])
        result = _collect_value_capture_widgets([radio, group, repeater])
        assert result == [radio, child]

    def test_repeater_inside_group_not_recursed_past_repeater(self):
        # Repeater at top level is skipped; its children are not included
        radio = RadioGroupWidget("kind")
        repeater = ListableWidget("items", item_widgets=[radio])
        group = GroupWidget("section", children=[repeater])
        # GroupWidget recurses, finds a RepeaterWidget, skips it
        result = _collect_value_capture_widgets([group])
        assert result == []


# ---------------------------------------------------------------------------
# _collect_all_control_templates
# ---------------------------------------------------------------------------

class TestCollectAllControlTemplates:
    def test_flat_list(self):
        radio = RadioGroupWidget("label")
        result = _collect_all_control_templates([radio])
        assert result == [radio]

    def test_repeater_item_widgets_included(self):
        kind = RadioGroupWidget("kind")
        repeater = ListableWidget("pets", item_widgets=[kind])
        result = _collect_all_control_templates([repeater])
        assert result == [kind]

    def test_group_children_included(self):
        child = TextInputWidget("name")
        group = GroupWidget("details", children=[child])
        result = _collect_all_control_templates([group])
        assert result == [child]

    def test_repeater_with_group_children(self):
        child = CheckboxWidget("indoor")
        group = GroupWidget("booleans", children=[child])
        repeater = ListableWidget("pets", item_widgets=[group])
        result = _collect_all_control_templates([repeater])
        assert result == [child]

    def test_mixed_top_level(self):
        radio = RadioGroupWidget("label")
        kind = RadioGroupWidget("kind")
        repeater = ListableWidget("pets", item_widgets=[kind])
        result = _collect_all_control_templates([radio, repeater])
        assert result == [radio, kind]


# ---------------------------------------------------------------------------
# _build_ev_lookup
# ---------------------------------------------------------------------------

class TestBuildEvLookup:
    def test_single_control_widget(self):
        radio = RadioGroupWidget("label")
        result = _build_ev_lookup([radio])
        assert result == {"label": None}  # ChoiceWidget.empty_value = None

    def test_text_widget_empty_value_is_string(self):
        text = TextInputWidget("notes")
        result = _build_ev_lookup([text])
        assert result == {"notes": ""}

    def test_boolean_widget_empty_value_is_false(self):
        cb = CheckboxWidget("indoor")
        result = _build_ev_lookup([cb])
        assert result == {"indoor": False}

    def test_multiple_flat_widgets(self):
        result = _build_ev_lookup([
            RadioGroupWidget("label"),
            TextInputWidget("notes"),
            CheckboxWidget("flagged"),
        ])
        assert result == {"label": None, "notes": "", "flagged": False}

    def test_group_children_use_group_prefix(self):
        child = CheckboxWidget("indoor")
        group = GroupWidget("booleans", children=[child])
        result = _build_ev_lookup([group])
        assert result == {"booleans|indoor": False}

    def test_nested_groups_accumulate_prefix(self):
        inner = TextInputWidget("name")
        inner_group = GroupWidget("details", children=[inner])
        outer_group = GroupWidget("outer", children=[inner_group])
        result = _build_ev_lookup([outer_group])
        assert result == {"outer|details|name": ""}

    def test_repeater_resets_prefix(self):
        # RepeaterWidget resets _group_prefix to "" for its item_widgets
        kind = RadioGroupWidget("kind")
        repeater = ListableWidget("pets", item_widgets=[kind])
        result = _build_ev_lookup([repeater])
        assert result == {"kind": None}

    def test_repeater_with_group_item(self):
        child = TextInputWidget("name")
        group = GroupWidget("details", children=[child])
        repeater = ListableWidget("pets", item_widgets=[group])
        result = _build_ev_lookup([repeater])
        assert result == {"details|name": ""}

    def test_mixed_top_level_and_group(self):
        radio = RadioGroupWidget("label")
        child = CheckboxWidget("indoor")
        group = GroupWidget("booleans", children=[child])
        result = _build_ev_lookup([radio, group])
        assert result == {"label": None, "booleans|indoor": False}

    def test_empty_widget_list(self):
        assert _build_ev_lookup([]) == {}

    def test_standalone_widget_uses_field_path(self):
        # field_path falls back to schema_field when _finalize_paths not called
        text = TextInputWidget("my_field")
        result = _build_ev_lookup([text])
        assert "my_field" in result

    def test_finalized_path_used_for_standalone(self):
        # After _finalize_paths("parent"), field_path = "parent.my_field"
        text = TextInputWidget("my_field")
        text._finalize_paths("parent")
        result = _build_ev_lookup([text])
        assert "parent|my_field" in result


# ---------------------------------------------------------------------------
# _perform_navigation
# ---------------------------------------------------------------------------

class TestPerformNavigation:
    def _docs(self, n=3):
        return [_doc(f"doc{i+1}", f"Doc {i+1}") for i in range(n)]

    def test_returns_correct_doc_id(self):
        ta = _make_ta(self._docs())
        doc_id, _, _, _ = _perform_navigation(ta, None, 1, None, None, None)
        assert doc_id == "doc2"

    def test_arriving_doc_left_to_on_doc_change(self):
        # Only the departing document is updated; on_doc_change sets up the arriving one.
        ta = _make_ta(self._docs())
        _, timing, metadata, status = _perform_navigation(ta, None, 0, None, None, None)
        assert metadata == {}
        assert status is no_update
        assert "_nav_init" not in timing
        assert "annotation_seconds_at_load" not in timing

    def test_returns_only_departing_doc(self):
        ta = _make_ta(self._docs())
        metadata_in = {"doc1": {"visited": True}, "doc2": {"notes": "x"}}
        _, _, metadata, _ = _perform_navigation(ta, "doc1", 1, {}, None, metadata_in)
        assert set(metadata) == {"doc1"}

    def test_paused_cleared_on_nav(self):
        ta = _make_ta(self._docs())
        _, timing, _, _ = _perform_navigation(ta, None, 0, {"paused": True}, None, None)
        assert timing["paused"] is False

    def test_session_start_time_set_on_first_nav(self):
        ta = _make_ta(self._docs())
        _, timing, _, _ = _perform_navigation(ta, None, 0, {}, None, None)
        assert timing["session_start_time"] is not None

    def test_session_start_time_not_overwritten(self):
        ta = _make_ta(self._docs())
        existing_start = time.time() - 100
        timing_in = {"session_start_time": existing_start}
        _, timing, _, _ = _perform_navigation(ta, None, 0, timing_in, None, None)
        assert timing["session_start_time"] == existing_start

    def test_none_session_start_time_is_replaced(self):
        ta = _make_ta(self._docs())
        timing_in = {"session_start_time": None}
        _, timing, _, _ = _perform_navigation(ta, None, 0, timing_in, None, None)
        assert timing["session_start_time"] is not None

    def test_annotation_seconds_accumulated_from_previous_doc(self):
        ta = _make_ta(self._docs())
        now = time.time()
        timing_in = {"doc_start_time": now - 10}
        metadata_in = {"doc1": {"annotation_seconds": 5.0, "visited": True}}
        _, _, metadata, _ = _perform_navigation(ta, "doc1", 1, timing_in, None, metadata_in)
        # Should have accumulated ~10 more seconds on top of the stored 5
        assert metadata["doc1"]["annotation_seconds"] >= 14.0

    def test_departing_doc_marked_complete_when_no_required_widgets(self):
        # Navigating away marks the departing doc complete when no required widgets.
        # visited flag on the departing doc doesn't matter — departure implies presence.
        ta = _make_ta(self._docs(), required_widgets=[])
        for visited in (True, False):
            metadata_in = {"doc1": {"visited": visited, "status": "in_progress", "annotation_seconds": 0.0}}
            _, _, metadata, _ = _perform_navigation(ta, "doc1", 1, {}, None, metadata_in)
            assert metadata["doc1"]["status"] == "complete", f"expected complete when visited={visited}"

    def test_departing_doc_in_progress_when_required_unfilled(self):
        # Navigating away with required fields empty leaves departing doc in_progress.
        mock_widget = types.SimpleNamespace(field_path="required_field")
        ta = _make_ta(self._docs(), required_widgets=[mock_widget])
        metadata_in = {"doc1": {"visited": True, "status": "in_progress", "annotation_seconds": 0.0}}
        # annotations_data=None means no annotation → _is_complete_eligible returns False
        _, _, metadata, _ = _perform_navigation(ta, "doc1", 1, {}, None, metadata_in)
        assert metadata["doc1"]["status"] == "in_progress"

    def test_timing_none_initializes_to_dict(self):
        ta = _make_ta(self._docs())
        _, timing, _, _ = _perform_navigation(ta, None, 0, None, None, None)
        assert isinstance(timing, dict)
        assert "doc_start_time" in timing
        assert "last_save_time" in timing

    def test_metadata_none_initializes_to_dict(self):
        ta = _make_ta(self._docs())
        _, _, metadata, _ = _perform_navigation(ta, None, 0, None, None, None)
        assert isinstance(metadata, dict)

    def test_out_of_range_index_returns_empty_doc_id(self):
        ta = _make_ta(self._docs(n=2))
        doc_id, _, _, _ = _perform_navigation(ta, None, 99, {}, None, None)
        assert doc_id == ""


# ---------------------------------------------------------------------------
# _doc_index
# ---------------------------------------------------------------------------

class TestDocIndex:
    def test_returns_position(self):
        ta = _make_ta([_doc("doc1"), _doc("doc2"), _doc("doc3")])
        assert _doc_index(ta, "doc1") == 0
        assert _doc_index(ta, "doc3") == 2

    def test_unknown_id_returns_none(self):
        ta = _make_ta([_doc("doc1")])
        assert _doc_index(ta, "nope") is None

    def test_empty_id_returns_none(self):
        ta = _make_ta([_doc("doc1")])
        assert _doc_index(ta, None) is None
        assert _doc_index(ta, "") is None

    def test_rebuilds_when_documents_replaced(self):
        ta = _make_ta([_doc("doc1"), _doc("doc2")])
        assert _doc_index(ta, "doc2") == 1
        ta.documents = [_doc("doc2"), _doc("doc9")]
        assert _doc_index(ta, "doc2") == 0
        assert _doc_index(ta, "doc9") == 1
        assert _doc_index(ta, "doc1") is None


# ---------------------------------------------------------------------------
# Current-document slice and patches (#108)
# ---------------------------------------------------------------------------

def _ops(patch):
    return [(o["operation"], o["location"], o["params"].get("value"))
            for o in patch.to_plotly_json()["operations"]]


class TestSliceStores:
    def test_one_document_stores(self):
        s = {"doc_id": "d1", "annotations": {"a": 1}, "metadata": {"flagged": True}}
        assert _slice_stores(s) == ({"d1": {"a": 1}}, {"d1": {"flagged": True}})

    def test_missing_entries_give_empty_stores(self):
        s = {"doc_id": "d1", "annotations": None, "metadata": None}
        assert _slice_stores(s) == ({}, {})

    def test_no_slice(self):
        assert _slice_stores(None) == ({}, {})

    def test_matching_doc_id(self):
        s = {"doc_id": "d1", "annotations": {}, "metadata": {}}
        assert _slice_stores(s, "d1") == ({"d1": {}}, {"d1": {}})

    def test_mismatched_doc_id_is_none(self):
        # A slice for another document must not be used to write this one.
        s = {"doc_id": "d1", "annotations": {}, "metadata": {}}
        assert _slice_stores(s, "d2") is None


class TestMetaPatch:
    def test_only_changed_fields(self):
        before = {"d1": {"flagged": False, "notes": "x"}}
        after = {"d1": {"flagged": True, "notes": "x"}}
        assert _ops(_meta_patch(before, after)) == [("Merge", ["d1"], {"flagged": True})]

    def test_new_document_writes_all_fields(self):
        assert _ops(_meta_patch({}, {"d1": {"visited": True}})) == [("Merge", ["d1"], {"visited": True})]

    def test_unchanged_is_no_update(self):
        assert _meta_patch({"d1": {"a": 1}}, {"d1": {"a": 1}}) is no_update

    def test_empty_and_no_update(self):
        assert _meta_patch({}, {}) is no_update
        assert _meta_patch({}, no_update) is no_update


class TestDictPatch:
    def test_only_changed_keys(self):
        assert _ops(_dict_patch({"a": 1, "b": 2}, {"a": 1, "b": 3})) == [("Merge", [], {"b": 3})]

    def test_unchanged_is_no_update(self):
        assert _dict_patch({"a": 1}, {"a": 1}) is no_update

    def test_none_before(self):
        assert _ops(_dict_patch(None, {"a": 1})) == [("Merge", [], {"a": 1})]
