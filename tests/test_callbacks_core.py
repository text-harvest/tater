"""Unit tests for extracted server-side callback logic in tater/ui/callbacks/core.py.

These functions are extracted from their Dash closure specifically to allow direct
unit testing without spinning up a Dash app or browser. The registered callbacks
are thin shells that call these _impl functions with _ta(); the logic lives here.

See the testing plan in CLAUDE.md (Tier 2) for the rationale on which callbacks
were extracted vs. left as-is.
"""
from __future__ import annotations

import time
import types

import pytest
from dash import no_update

from tater.models.document import Document
from tater.ui.callbacks.core import (
    _load_flag_and_notes_impl,
    _navigate_select_impl,
    _on_doc_change_impl,
    _save_flag_impl,
    _save_notes_impl,
    _toggle_pause_impl,
    _update_save_status_impl,
)


# ---------------------------------------------------------------------------
# Minimal TaterApp stand-in
# ---------------------------------------------------------------------------

def _make_ta(save_error=None, required_widgets=None):
    ta = types.SimpleNamespace()
    ta._save_error = save_error
    ta._required_widgets = required_widgets or []
    ta.documents = []
    return ta


# ---------------------------------------------------------------------------
# _update_save_status_impl
# ---------------------------------------------------------------------------

class TestUpdateSaveStatus:
    def test_never_saved_when_no_timing(self):
        ta = _make_ta()
        text, color = _update_save_status_impl(ta, None)
        assert text == "Not saved"
        assert color == "dimmed"

    def test_never_saved_when_timing_has_no_last_save_time(self):
        ta = _make_ta()
        text, color = _update_save_status_impl(ta, {"doc_start_time": time.time()})
        assert text == "Not saved"
        assert color == "dimmed"

    def test_last_saved_shows_formatted_time(self):
        ta = _make_ta()
        ts = time.time()
        text, color = _update_save_status_impl(ta, {"last_save_time": ts})
        assert text.startswith("Last saved: ")
        # HH:MM:SS format
        time_part = text.removeprefix("Last saved: ")
        parts = time_part.split(":")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)
        assert color == "dimmed"

    def test_save_error_takes_priority_over_last_save_time(self):
        ta = _make_ta(save_error="disk full")
        ts = time.time()
        text, color = _update_save_status_impl(ta, {"last_save_time": ts})
        assert text == "Save failed: disk full"
        assert color == "red"

    def test_save_error_with_no_timing(self):
        ta = _make_ta(save_error="permission denied")
        text, color = _update_save_status_impl(ta, None)
        assert "permission denied" in text
        assert color == "red"

    def test_no_save_error_shows_dimmed(self):
        ta = _make_ta(save_error=None)
        text, color = _update_save_status_impl(ta, {"last_save_time": time.time()})
        assert color == "dimmed"


# ---------------------------------------------------------------------------
# _on_doc_change_impl
# ---------------------------------------------------------------------------

class TestOnDocChange:
    def _ta(self):
        return _make_ta()

    # -- _nav_init fast-path --

    def test_nav_init_returns_no_update_for_timing_and_metadata(self):
        timing = {"_nav_init": True}
        metadata = {"doc1": {"status": "complete"}}
        timing_out, status, meta_out = _on_doc_change_impl(
            self._ta(), "doc1", timing, None, metadata
        )
        assert timing_out is no_update
        assert meta_out is no_update

    def test_nav_init_reads_status_from_metadata(self):
        timing = {"_nav_init": True}
        metadata = {"doc1": {"status": "in_progress"}}
        _, status, _ = _on_doc_change_impl(
            self._ta(), "doc1", timing, None, metadata
        )
        assert status == "in_progress"

    def test_nav_init_defaults_status_when_doc_absent(self):
        timing = {"_nav_init": True}
        _, status, _ = _on_doc_change_impl(
            self._ta(), "doc1", timing, None, {}
        )
        assert status == "not_started"

    def test_nav_init_false_does_not_short_circuit(self):
        timing = {"_nav_init": False}
        timing_out, _, _ = _on_doc_change_impl(
            self._ta(), "doc1", timing, None, None
        )
        assert timing_out is not no_update

    def test_nav_init_missing_key_does_not_short_circuit(self):
        timing = {"doc_start_time": time.time()}
        timing_out, _, _ = _on_doc_change_impl(
            self._ta(), "doc1", timing, None, None
        )
        assert timing_out is not no_update

    # -- Initial page load path --

    def test_marks_doc_as_visited(self):
        _, _, metadata = _on_doc_change_impl(
            self._ta(), "doc1", None, None, None
        )
        assert metadata["doc1"]["visited"] is True

    def test_sets_doc_start_time(self):
        before = time.time()
        timing, _, _ = _on_doc_change_impl(
            self._ta(), "doc1", None, None, None
        )
        assert timing["doc_start_time"] >= before

    def test_sets_paused_false(self):
        timing, _, _ = _on_doc_change_impl(
            self._ta(), "doc1", None, None, None
        )
        assert timing["paused"] is False

    def test_sets_session_start_time_when_absent(self):
        before = time.time()
        timing, _, _ = _on_doc_change_impl(
            self._ta(), "doc1", {}, None, None
        )
        assert timing["session_start_time"] >= before

    def test_does_not_overwrite_existing_session_start_time(self):
        existing = time.time() - 100
        timing_in = {"session_start_time": existing}
        timing, _, _ = _on_doc_change_impl(
            self._ta(), "doc1", timing_in, None, None
        )
        assert timing["session_start_time"] == existing

    def test_none_session_start_time_is_replaced(self):
        timing_in = {"session_start_time": None}
        timing, _, _ = _on_doc_change_impl(
            self._ta(), "doc1", timing_in, None, None
        )
        assert timing["session_start_time"] is not None

    def test_annotation_seconds_at_load_from_stored_meta(self):
        metadata_in = {"doc1": {"annotation_seconds": 42.0}}
        timing, _, _ = _on_doc_change_impl(
            self._ta(), "doc1", {}, None, metadata_in
        )
        assert timing["annotation_seconds_at_load"] == 42.0

    def test_annotation_seconds_at_load_zero_for_fresh_doc(self):
        timing, _, _ = _on_doc_change_impl(
            self._ta(), "doc1", {}, None, None
        )
        assert timing["annotation_seconds_at_load"] == 0.0

    def test_no_doc_id_returns_not_started_status(self):
        _, status, _ = _on_doc_change_impl(
            self._ta(), None, None, None, None
        )
        assert status == "not_started"

    def test_none_timing_initializes_to_dict(self):
        timing, _, _ = _on_doc_change_impl(
            self._ta(), "doc1", None, None, None
        )
        assert isinstance(timing, dict)

    def test_none_metadata_initializes_to_dict(self):
        _, _, metadata = _on_doc_change_impl(
            self._ta(), "doc1", None, None, None
        )
        assert isinstance(metadata, dict)


# ---------------------------------------------------------------------------
# _toggle_pause_impl
# ---------------------------------------------------------------------------

class TestTogglePause:
    def test_zero_n_clicks_returns_no_update(self):
        result = _toggle_pause_impl(0, {}, "doc1", {})
        assert result == (no_update, no_update)

    def test_none_n_clicks_returns_no_update(self):
        result = _toggle_pause_impl(None, {}, "doc1", {})
        assert result == (no_update, no_update)

    # -- Pausing (currently_paused=False) --

    def test_pause_sets_paused_true(self):
        timing_in = {"paused": False, "doc_start_time": time.time()}
        timing, _ = _toggle_pause_impl(1, timing_in, "doc1", {})
        assert timing["paused"] is True

    def test_pause_clears_doc_start_time(self):
        timing_in = {"paused": False, "doc_start_time": time.time()}
        timing, _ = _toggle_pause_impl(1, timing_in, "doc1", {})
        assert timing["doc_start_time"] is None

    def test_pause_accumulates_elapsed_seconds(self):
        now = time.time()
        elapsed = 30.0
        timing_in = {"paused": False, "doc_start_time": now - elapsed}
        metadata_in = {"doc1": {"annotation_seconds": 10.0}}
        _, metadata = _toggle_pause_impl(1, timing_in, "doc1", metadata_in)
        # Should have added ~30s to the stored 10s
        assert metadata["doc1"]["annotation_seconds"] >= 39.0

    def test_pause_updates_annotation_seconds_at_load(self):
        now = time.time()
        timing_in = {"paused": False, "doc_start_time": now - 20}
        metadata_in = {"doc1": {"annotation_seconds": 5.0}}
        timing, _ = _toggle_pause_impl(1, timing_in, "doc1", metadata_in)
        # annotation_seconds_at_load should reflect the post-flush total
        assert timing["annotation_seconds_at_load"] >= 24.0

    def test_pause_without_doc_id_does_not_accumulate(self):
        timing_in = {"paused": False, "doc_start_time": time.time() - 10}
        timing, metadata = _toggle_pause_impl(1, timing_in, None, {})
        assert timing["paused"] is True
        assert metadata == {}

    def test_pause_without_doc_start_time_does_not_accumulate(self):
        timing_in = {"paused": False, "doc_start_time": None}
        metadata_in = {"doc1": {"annotation_seconds": 5.0}}
        _, metadata = _toggle_pause_impl(1, timing_in, "doc1", metadata_in)
        # No elapsed to accumulate without a start time
        assert metadata["doc1"]["annotation_seconds"] == 5.0

    # -- Resuming (currently_paused=True) --

    def test_resume_sets_paused_false(self):
        timing_in = {"paused": True, "doc_start_time": None}
        timing, _ = _toggle_pause_impl(1, timing_in, "doc1", {})
        assert timing["paused"] is False

    def test_resume_sets_doc_start_time(self):
        before = time.time()
        timing_in = {"paused": True, "doc_start_time": None}
        timing, _ = _toggle_pause_impl(1, timing_in, "doc1", {})
        assert timing["doc_start_time"] >= before

    def test_resume_does_not_flush_seconds(self):
        timing_in = {"paused": True, "doc_start_time": None}
        metadata_in = {"doc1": {"annotation_seconds": 50.0}}
        _, metadata = _toggle_pause_impl(1, timing_in, "doc1", metadata_in)
        assert metadata["doc1"]["annotation_seconds"] == 50.0

    # -- Edge cases --

    def test_none_timing_initializes_to_dict(self):
        timing, _ = _toggle_pause_impl(1, None, "doc1", {})
        assert isinstance(timing, dict)

    def test_none_metadata_initializes_to_dict(self):
        _, metadata = _toggle_pause_impl(1, {"paused": False}, "doc1", None)
        assert isinstance(metadata, dict)

    def test_paused_defaults_false_when_key_absent(self):
        # timing with no "paused" key → treated as not paused → should pause
        timing_in = {"doc_start_time": None}
        timing, _ = _toggle_pause_impl(1, timing_in, "doc1", {})
        assert timing["paused"] is True


# ---------------------------------------------------------------------------
# _navigate_select_impl
# ---------------------------------------------------------------------------

class TestNavigateSelect:
    def _ta(self):
        ta = _make_ta()
        ta.documents = [Document(id=f"doc{i}", text="t") for i in range(1, 4)]
        return ta

    def test_navigates_to_selected_document(self):
        doc_id, timing, metadata, status = _navigate_select_impl(
            self._ta(), {"id": "doc3", "t": 1}, "doc1", {}, {}, {}
        )
        assert doc_id == "doc3"
        assert timing["_nav_init"] is True
        assert metadata["doc1"]["visited"] is True
        assert metadata["doc3"]["visited"] is True

    def test_same_document_is_noop(self):
        result = _navigate_select_impl(self._ta(), {"id": "doc1", "t": 1}, "doc1", {}, {}, {})
        assert result == (no_update, no_update, no_update, no_update)

    def test_unknown_document_is_noop(self):
        result = _navigate_select_impl(self._ta(), {"id": "nope", "t": 1}, "doc1", {}, {}, {})
        assert result == (no_update, no_update, no_update, no_update)

    @pytest.mark.parametrize("nav", [None, {}, {"id": None}, {"id": ""}])
    def test_missing_target_is_noop(self, nav):
        result = _navigate_select_impl(self._ta(), nav, "doc1", {}, {}, {})
        assert result == (no_update, no_update, no_update, no_update)


# ---------------------------------------------------------------------------
# _load_flag_and_notes_impl
# ---------------------------------------------------------------------------

class TestLoadFlagAndNotes:
    def test_loads_stored_values(self):
        meta = {"doc2": {"flagged": True, "notes": "hi"}}
        assert _load_flag_and_notes_impl("doc2", meta, False, "") == (True, "hi")

    def test_skips_controls_already_showing_value(self):
        # Common case: navigating between unflagged docs without notes must not
        # set either control (which would re-fire save_flag / save_notes).
        assert _load_flag_and_notes_impl("doc2", {}, False, "") == (no_update, no_update)
        assert _load_flag_and_notes_impl("doc2", {}, None, None) == (no_update, no_update)

    def test_updates_only_changed_control(self):
        meta = {"doc2": {"flagged": False, "notes": "n"}}
        assert _load_flag_and_notes_impl("doc2", meta, False, "") == (no_update, "n")
        meta = {"doc2": {"flagged": True, "notes": ""}}
        assert _load_flag_and_notes_impl("doc2", meta, False, "") == (True, no_update)

    def test_clears_when_previous_doc_had_values(self):
        assert _load_flag_and_notes_impl("doc2", {}, True, "old") == (False, "")

    def test_no_doc_resets(self):
        assert _load_flag_and_notes_impl("", {}, True, "x") == (False, "")


# ---------------------------------------------------------------------------
# _save_flag_impl / _save_notes_impl
# ---------------------------------------------------------------------------

class TestSaveFlag:
    def test_sets_flag(self):
        metadata = _save_flag_impl(True, "doc1", {"doc1": {"flagged": False}})
        assert metadata["doc1"]["flagged"] is True

    def test_clears_flag(self):
        metadata = _save_flag_impl(False, "doc1", {"doc1": {"flagged": True}})
        assert metadata["doc1"]["flagged"] is False

    def test_unchanged_value_is_noop(self):
        # load_flag_and_notes sets the checkbox on every navigation; that must not
        # write metadata-store (which would trigger auto_save).
        assert _save_flag_impl(True, "doc1", {"doc1": {"flagged": True}}) is no_update
        assert _save_flag_impl(False, "doc1", {"doc1": {"flagged": False}}) is no_update

    def test_unchanged_default_is_noop(self):
        assert _save_flag_impl(False, "doc1", {}) is no_update
        assert _save_flag_impl(None, "doc1", None) is no_update

    def test_no_doc_is_noop(self):
        assert _save_flag_impl(True, "", {}) is no_update

    def test_does_not_mutate_input(self):
        metadata_in = {"doc1": {"flagged": False}}
        _save_flag_impl(True, "doc1", metadata_in)
        assert metadata_in["doc1"]["flagged"] is False


class TestSaveNotes:
    def test_sets_notes(self):
        metadata = _save_notes_impl("hello", "doc1", {"doc1": {"notes": ""}})
        assert metadata["doc1"]["notes"] == "hello"

    def test_clears_notes(self):
        metadata = _save_notes_impl(None, "doc1", {"doc1": {"notes": "hello"}})
        assert metadata["doc1"]["notes"] == ""

    def test_unchanged_value_is_noop(self):
        assert _save_notes_impl("hello", "doc1", {"doc1": {"notes": "hello"}}) is no_update

    def test_empty_and_none_are_equivalent(self):
        assert _save_notes_impl(None, "doc1", {"doc1": {"notes": ""}}) is no_update
        assert _save_notes_impl("", "doc1", {"doc1": {"notes": None}}) is no_update
        assert _save_notes_impl("", "doc1", {}) is no_update

    def test_no_doc_is_noop(self):
        assert _save_notes_impl("hello", None, {}) is no_update
