"""Tests for hosted-mode session building and related helpers.

Covers:
  - _build_session_app_from_data: happy path, annotations preload,
    hierarchy file injection, and error cases
  - Schema builder _fields_to_schema -> parse_schema round-trip for all
    supported field types and widget variants
  - Session cache eviction (OrderedDict FIFO behaviour)
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Literal, Optional, List

import pytest
from dash import Dash

from tater.ui.runner import _build_session_app_from_data
from tater.ui.schema_builder import _fields_to_schema
from tater.loaders.json_loader import parse_schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SIMPLE_SCHEMA = {
    "spec_version": "1.0",
    "title": "Test Schema",
    "data_schema": [
        {
            "id": "sentiment",
            "type": "choice",
            "options": ["positive", "negative", "neutral"],
            "widget": {"type": "segmented_control", "label": "Sentiment"},
        },
        {
            "id": "flagged",
            "type": "boolean",
            "widget": {"type": "checkbox", "label": "Flagged"},
        },
    ],
}

_SIMPLE_DOCS = [
    {"id": "d1", "text": "First document."},
    {"id": "d2", "text": "Second document."},
]


@pytest.fixture(scope="module")
def hosted_dash_app():
    """A single Dash app shared across all hosted-mode tests.

    In hosted mode, widget callbacks are registered once on the shared Dash
    app (guarded by _tater_callbacks_registered). Using module scope here
    mirrors that — the first test registers callbacks; subsequent tests reuse
    the same app without re-registering.
    """
    app = Dash(__name__, suppress_callback_exceptions=True)
    app._tater_get_current_app = lambda: None
    return app


# ---------------------------------------------------------------------------
# _build_session_app_from_data
# ---------------------------------------------------------------------------

def test_build_returns_tater_app(hosted_dash_app):
    ta = _build_session_app_from_data(hosted_dash_app, _SIMPLE_SCHEMA, _SIMPLE_DOCS)
    assert ta is not None


def test_build_loads_documents(hosted_dash_app):
    ta = _build_session_app_from_data(hosted_dash_app, _SIMPLE_SCHEMA, _SIMPLE_DOCS)
    assert len(ta.documents) == 2
    assert ta.documents[0].text == "First document."


def test_build_sets_title(hosted_dash_app):
    ta = _build_session_app_from_data(hosted_dash_app, _SIMPLE_SCHEMA, _SIMPLE_DOCS)
    assert ta.title == "Test Schema"


def test_build_none_schema_returns_none(hosted_dash_app):
    assert _build_session_app_from_data(hosted_dash_app, None, _SIMPLE_DOCS) is None


def test_build_none_docs_returns_none(hosted_dash_app):
    assert _build_session_app_from_data(hosted_dash_app, _SIMPLE_SCHEMA, None) is None


def test_build_empty_docs_returns_none(hosted_dash_app):
    assert _build_session_app_from_data(hosted_dash_app, _SIMPLE_SCHEMA, []) is None


def test_build_invalid_schema_returns_none(hosted_dash_app):
    bad = {"spec_version": "1.0", "data_schema": [{"id": "x", "type": "unknown_type", "widget": {"type": "???"}}]}
    assert _build_session_app_from_data(hosted_dash_app, bad, _SIMPLE_DOCS) is None


def test_build_with_annotations(hosted_dash_app):
    annotations = {
        "d1": {
            "annotations": {"sentiment": "positive", "flagged": True},
            "metadata": {"flagged": True, "notes": "needs review", "annotation_seconds": 5.0,
                         "visited": True, "status": "complete"},
        }
    }
    ta = _build_session_app_from_data(
        hosted_dash_app, _SIMPLE_SCHEMA, _SIMPLE_DOCS, annotations_data=annotations
    )
    assert ta is not None
    assert ta.metadata["d1"].flagged is True
    assert ta.metadata["d1"].notes == "needs review"
    assert ta.metadata["d1"].annotation_seconds == 5.0
    assert ta.annotations["d1"].sentiment == "positive"


def test_build_with_hierarchy_files(hosted_dash_app):
    schema = {
        "spec_version": "1.0",
        "data_schema": [
            {
                "id": "animal",
                "type": "hierarchical_label",
                "widget": {
                    "type": "hierarchical_label_select",
                    "label": "Animal",
                    "hierarchy_ref": "fauna",
                },
            }
        ],
        "hierarchies": {"fauna": "fauna.yaml"},
    }
    # Uploaded YAML content — would normally come from hierarchy-files-store
    hierarchy_files = {
        "fauna": {
            "filename": "fauna.yaml",
            "content": "Animals:\n  - Cat\n  - Dog\n",
        }
    }
    docs = [{"id": "d1", "text": "Hello"}]
    ta = _build_session_app_from_data(
        hosted_dash_app, schema, docs, hierarchy_files=hierarchy_files
    )
    assert ta is not None
    assert len(ta.documents) == 1


# ---------------------------------------------------------------------------
# Schema builder round-trip: _fields_to_schema -> parse_schema
# ---------------------------------------------------------------------------

def _round_trip(fields):
    schema = _fields_to_schema(fields, "Test")
    model, widgets = parse_schema(schema)
    return model, widgets


def test_round_trip_choice_variants():
    for wtype in ("segmented_control", "radio_group", "select", "chip_radio"):
        model, widgets = _round_trip([
            {"type": "choice", "widget_type": wtype, "id": "q",
             "label": "Q", "required": False, "options": ["a", "b", "c"]},
        ])
        assert "q" in model.model_fields
        assert len(widgets) == 1


def test_round_trip_multi_choice_variants():
    for wtype in ("multi_select", "checkbox_group"):
        model, widgets = _round_trip([
            {"type": "multi_choice", "widget_type": wtype, "id": "tags",
             "label": "Tags", "required": False, "options": ["x", "y"]},
        ])
        assert "tags" in model.model_fields


def test_round_trip_boolean_variants():
    for wtype in ("checkbox", "switch", "chip_boolean"):
        model, widgets = _round_trip([
            {"type": "boolean", "widget_type": wtype, "id": "flag", "label": "Flag", "required": False},
        ])
        assert "flag" in model.model_fields


def test_round_trip_text_variants():
    for wtype in ("text_input", "text_area"):
        model, widgets = _round_trip([
            {"type": "text", "widget_type": wtype, "id": "note", "label": "Note",
             "required": False, "placeholder": "Enter text"},
        ])
        assert "note" in model.model_fields


def test_round_trip_numeric_variants():
    for wtype in ("number_input", "slider"):
        model, widgets = _round_trip([
            {"type": "numeric", "widget_type": wtype, "id": "score", "label": "Score",
             "required": False, "min_value": 0, "max_value": 10},
        ])
        assert "score" in model.model_fields


def test_round_trip_range_slider():
    model, widgets = _round_trip([
        {"type": "range_slider", "widget_type": "range_slider", "id": "rng",
         "label": "Range", "required": False, "min_value": 0, "max_value": 100, "step": 5},
    ])
    assert "rng" in model.model_fields


def test_round_trip_span_annotation_variants():
    for wtype in ("span_annotation", "span_popup"):
        model, widgets = _round_trip([
            {"type": "span_annotation", "widget_type": wtype, "id": "spans",
             "label": "Spans", "required": False, "entity_types": ["Person", "Org"]},
        ])
        assert "spans" in model.model_fields


def test_round_trip_span_annotation_no_entity_types():
    model, widgets = _round_trip([
        {"type": "span_annotation", "widget_type": "span_annotation", "id": "spans",
         "label": "Spans", "required": False, "entity_types": []},
    ])
    assert "spans" in model.model_fields


def test_round_trip_divider_skips_model_field():
    model, widgets = _round_trip([
        {"type": "choice", "widget_type": "segmented_control", "id": "q",
         "label": "Q", "required": False, "options": ["a", "b"]},
        {"type": "divider", "label": "Section"},
    ])
    assert "q" in model.model_fields
    assert len(model.model_fields) == 1  # divider adds no model field
    assert any(type(w).__name__ == "DividerWidget" for w in widgets)


def test_round_trip_required_flag():
    model, widgets = _round_trip([
        {"type": "choice", "widget_type": "segmented_control", "id": "q",
         "label": "Q", "required": True, "options": ["a", "b"]},
    ])
    assert widgets[0].required is True


def test_round_trip_mixed_fields():
    fields = [
        {"type": "choice", "widget_type": "radio_group", "id": "cat",
         "label": "Category", "required": True, "options": ["A", "B", "C"]},
        {"type": "boolean", "widget_type": "switch", "id": "ok", "label": "OK", "required": False},
        {"type": "text", "widget_type": "text_area", "id": "note",
         "label": "Note", "required": False},
        {"type": "numeric", "widget_type": "number_input", "id": "score",
         "label": "Score", "required": False, "min_value": 1, "max_value": 5},
        {"type": "span_annotation", "widget_type": "span_annotation", "id": "spans",
         "label": "Spans", "required": False, "entity_types": ["X", "Y"]},
    ]
    model, widgets = _round_trip(fields)
    assert set(model.model_fields) == {"cat", "ok", "note", "score", "spans"}
    widget_types = [type(w).__name__ for w in widgets]
    assert "RadioGroupWidget" in widget_types
    assert "SwitchWidget" in widget_types
    assert "TextAreaWidget" in widget_types
    assert "NumberInputWidget" in widget_types
    assert "SpanAnnotationWidget" in widget_types


# ---------------------------------------------------------------------------
# Session cache eviction
# ---------------------------------------------------------------------------

def test_cache_eviction_drops_oldest():
    cache: OrderedDict[str, str] = OrderedDict()
    max_size = 3
    for i in range(5):
        cache[f"s{i}"] = f"app{i}"
        if len(cache) > max_size:
            cache.popitem(last=False)
    assert len(cache) == max_size
    assert "s0" not in cache
    assert "s1" not in cache
    assert "s2" in cache
    assert "s3" in cache
    assert "s4" in cache


def test_cache_below_max_no_eviction():
    cache: OrderedDict[str, str] = OrderedDict()
    max_size = 10
    for i in range(5):
        cache[f"s{i}"] = f"app{i}"
        if len(cache) > max_size:
            cache.popitem(last=False)
    assert len(cache) == 5


# ---------------------------------------------------------------------------
# session_resolver: which TaterApp a callback acts on
# ---------------------------------------------------------------------------

class TestSessionResolver:
    def _app(self, get_current=None):
        from types import SimpleNamespace
        return SimpleNamespace(_get_current_app=get_current)

    def test_single_mode_returns_own_app(self):
        from tater.ui.callbacks.helpers import session_resolver
        app = self._app()
        assert session_resolver(app)() is app

    def test_hosted_returns_callers_session(self):
        from tater.ui.callbacks.helpers import session_resolver
        other = object()
        assert session_resolver(self._app(lambda: other))() is other

    def test_hosted_ended_session_never_falls_back(self):
        """The registering (first) session must not stand in for a session that has gone."""
        from dash.exceptions import PreventUpdate
        from tater.ui.callbacks.helpers import session_resolver
        ta = session_resolver(self._app(lambda: None))
        with pytest.raises(PreventUpdate):
            ta()
