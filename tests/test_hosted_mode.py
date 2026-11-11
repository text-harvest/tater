"""Tests for hosted-mode session building and related helpers.

Covers:
  - _build_session_app_from_data: happy path, annotations preload,
    hierarchy file injection, and error cases
  - Schema builder _fields_to_schema -> parse_schema round-trip for all
    supported field types and widget variants
  - SessionCache: least recently used eviction by count and documents
  - session_resolver: hosted callbacks never fall back to the first session
"""
from __future__ import annotations

from typing import Literal, Optional, List

import pytest
from dash import Dash

from tater.ui.runner import SessionCache, _build_session_app_from_data
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
# SessionCache: least recently used eviction, by count and by documents
# ---------------------------------------------------------------------------

class _App:
    def __init__(self, docs: int = 1):
        self.documents = [object()] * docs


class TestSessionCache:
    def test_least_recently_used_goes_first(self):
        cache = SessionCache(max_size=3)
        for i in range(5):
            cache.add(f"s{i}", _App())
        assert len(cache) == 3
        assert "s0" not in cache and "s1" not in cache
        assert all(f"s{i}" in cache for i in (2, 3, 4))

    def test_get_saves_a_session_from_eviction(self):
        """An annotator who is working (every callback calls get) isn't the one dropped."""
        cache = SessionCache(max_size=3)
        for i in range(3):
            cache.add(f"s{i}", _App())
        assert cache.get("s0") is not None
        assert cache.add("s3", _App()) == ["s1"]
        assert "s0" in cache

    def test_below_limit_nothing_goes(self):
        cache = SessionCache(max_size=10, max_docs=1000)
        for i in range(5):
            assert cache.add(f"s{i}", _App(100)) == []
        assert len(cache) == 5
        assert cache.total_docs == 500

    def test_document_limit(self):
        cache = SessionCache(max_size=100, max_docs=25_000)
        cache.add("a", _App(10_000))
        cache.add("b", _App(10_000))
        assert cache.add("c", _App(10_000)) == ["a"]
        assert cache.total_docs == 20_000
        # Many small projects fit where large ones don't.
        for i in range(10):
            cache.add(f"small{i}", _App(500))
        assert "b" in cache and "c" in cache and len(cache) == 12

    def test_new_session_over_document_limit_is_kept_alone(self):
        cache = SessionCache(max_size=100, max_docs=5_000)
        cache.add("a", _App(1_000))
        assert cache.add("big", _App(8_000)) == ["a"]
        assert "big" in cache and len(cache) == 1

    def test_zero_document_limit_means_none(self):
        cache = SessionCache(max_size=100, max_docs=0)
        for i in range(5):
            cache.add(f"s{i}", _App(1_000_000))
        assert len(cache) == 5

    def test_re_adding_a_session_replaces_it(self):
        cache = SessionCache(max_size=3)
        cache.add("a", _App(10))
        cache.add("a", _App(20))
        assert len(cache) == 1 and cache.total_docs == 20

    def test_missing_session(self):
        assert SessionCache(max_size=3).get("nope") is None

    def test_concurrent_get_and_add_stay_consistent(self):
        import threading
        cache = SessionCache(max_size=20, max_docs=2_000)
        errors = []

        def worker(k):
            try:
                for i in range(300):
                    cache.add(f"w{k}-{i}", _App(50))
                    cache.get(f"w{k}-{i // 2}")
                    cache.get(f"w{(k + 1) % 8}-{i}")
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(cache) <= 20
        assert cache.total_docs == 50 * len(cache) <= 2_000


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
