"""Browser tests with Playwright (pytest-playwright).

Single-mode apps run in a thread in this process (``serve``), so a test builds its
TaterApp in Python and ``read_saved`` can flush its saves; hosted mode runs
``tater --hosted`` in a subprocess. Covers navigation, the document selector, flag
and notes, annotation persistence, auto-advance, save/restore, request bounds at
2,500 (and, marked ``perf``, 10,000) documents, every widget's round trip, and hosted
sessions on every built-in example.

Run with:
    pytest tests/test_browser.py --headless      # --headed to watch
"""
import json
import threading
import time
from pathlib import Path
from typing import List, Optional, Literal

import pytest
from playwright.sync_api import Page, expect
from pydantic import BaseModel, Field
from werkzeug.serving import WSGIRequestHandler, make_server

from perf.browser import (
    INIT_SCRIPT, dash_counts, position, reset_counts, select_word, selector_options,
    wait_loaded, wait_position, wait_quiet,
)
from perf.server import run_tater
from tater import SpanAnnotation
from tater.ui.tater_app import TaterApp
from tater.widgets import (
    CheckboxGroupWidget, CheckboxWidget, ChipRadioWidget, ChipWidget, EntityType,
    HierarchicalLabelMultiWidget, HierarchicalLabelSelectWidget, ListableWidget,
    MultiSelectWidget, NumberInputWidget, RadioGroupWidget, RangeSliderWidget,
    SegmentedControlWidget, SelectWidget, SliderWidget, SpanAnnotationWidget, SwitchWidget,
    TextAreaWidget, TextInputWidget,
)


def read_saved(tater) -> dict:
    """Read the on-disk annotations file and return the parsed dict.

    Flag/notes are persisted to disk via auto_save (server-side callback).
    tater.metadata is not updated during a browser session — the source of
    truth is the file. Writes are throttled (save_interval), so pending edits
    are flushed first; the server runs in this process.
    """
    tater.flush_saves()
    return json.loads(Path(tater.annotations_path).read_text())


# ---------------------------------------------------------------------------
# Playwright fixtures (pytest-playwright provides browser, context and page)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    # As the perf harness: tall enough that the sticky footer doesn't cover controls.
    return {**browser_context_args, "viewport": {"width": 1400, "height": 1000}}


@pytest.fixture
def new_context(new_context):
    """Every context counts Dash requests (INIT_SCRIPT), so tests can ``wait_quiet``."""
    def make(**kwargs):
        ctx = new_context(**kwargs)
        ctx.add_init_script(INIT_SCRIPT)
        return ctx
    return make


class _QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


@pytest.fixture
def serve():
    """``serve(tater_app) -> url``: run the app's server on a thread in this process, so
    tests can build a TaterApp in Python and ``read_saved`` can flush its saves."""
    running = []

    def start(tater_app: TaterApp) -> str:
        server = make_server("127.0.0.1", 0, tater_app.app.server, threaded=True, request_handler=_QuietHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        running.append((server, tater_app))
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server, tater_app in running:
        tater_app.flush_saves()  # before the server stops, so no save timer is left running
        server.shutdown()
        server.server_close()


@pytest.fixture
def open_app(page, serve):
    """``open_app(tater_app) -> page``: serve the app, open it, and wait for it to settle."""
    def open_(tater_app: TaterApp) -> Page:
        page.goto(serve(tater_app))
        settle(page)
        return page
    return open_


def settle(page: Page) -> None:
    wait_loaded(page)
    wait_quiet(page)


def _cdn_noise(msg) -> bool:
    """Icon fetches from the iconify CDN failing, e.g. with no network or behind a
    proxy that blocks it. Not a tater error."""
    text = msg.text
    url = (msg.location or {}).get("url", "")
    return "tabler.json" in text or "ERR_FAILED" in text and ("iconify" in url or "svg.com" in url or not url)


def watch_errors(page: Page, errors: list) -> None:
    """Append page errors, console errors and failed callback requests to ``errors``."""
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and not _cdn_noise(m)
            and errors.append(f"console: {m.text[:200]}"))
    page.on("response", lambda r: "_dash-update-component" in r.url and r.status >= 400
            and errors.append(f"callback HTTP {r.status}"))


@pytest.fixture
def errors(page) -> list:
    """Errors seen on ``page`` (see ``watch_errors``); new tests assert it's empty."""
    found = []
    watch_errors(page, found)
    return found


# ---------------------------------------------------------------------------
# Minimal schema and fixtures
# ---------------------------------------------------------------------------

class SimpleSchema(BaseModel):
    label: Optional[Literal["positive", "negative", "uncertain"]] = None


@pytest.fixture
def docs_file(tmp_path):
    docs = [
        {"id": "doc1", "text": "First document text.", "name": "Doc One"},
        {"id": "doc2", "text": "Second document text.", "name": "Doc Two"},
        {"id": "doc3", "text": "Third document text.", "name": "Doc Three"},
    ]
    p = tmp_path / "docs.json"
    p.write_text(json.dumps(docs))
    return str(p)


@pytest.fixture
def tater(tmp_path, docs_file):
    """A fully wired TaterApp with one RadioGroup widget."""
    ann_path = tmp_path / "ann.json"
    app = TaterApp(
        title="Test App",
        schema_model=SimpleSchema,
        annotations_path=str(ann_path),
    )
    app.load_documents(docs_file)
    app.set_annotation_widgets([
        RadioGroupWidget(schema_field="label", label="Label"),
    ])
    yield app
    app.flush_saves()


@pytest.fixture
def tater_required(tmp_path, docs_file):
    """TaterApp with one required RadioGroup — status transitions are observable."""
    ann_path = tmp_path / "ann_req.json"
    app = TaterApp(
        title="Test App Required",
        schema_model=SimpleSchema,
        annotations_path=str(ann_path),
    )
    app.load_documents(docs_file)
    app.set_annotation_widgets([
        RadioGroupWidget(schema_field="label", label="Label", required=True),
    ])
    yield app
    app.flush_saves()


@pytest.fixture
def tater_auto_advance(tmp_path, docs_file):
    """TaterApp with an auto_advance RadioGroup."""
    ann_path = tmp_path / "ann_aa.json"
    app = TaterApp(
        title="Test App Auto Advance",
        schema_model=SimpleSchema,
        annotations_path=str(ann_path),
    )
    app.load_documents(docs_file)
    app.set_annotation_widgets([
        RadioGroupWidget(schema_field="label", label="Label", auto_advance=True),
    ])
    yield app
    app.flush_saves()


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def _title(page: Page):
    return page.locator("#document-title")


def _assert_disabled(page: Page, selector: str) -> None:
    btn = page.locator(selector)
    assert btn.get_attribute("disabled") is not None or btn.get_attribute("data-disabled") is not None


class TestNavigation:
    def test_first_document_shown_on_load(self, open_app, tater):
        page = open_app(tater)
        expect(_title(page)).to_have_text("1 / 3")

    def test_document_content_displayed(self, open_app, tater):
        page = open_app(tater)
        expect(_title(page)).to_have_text("1 / 3")
        assert "First document text" in page.locator("#document-content").inner_text()

    def test_prev_button_disabled_on_first_doc(self, open_app, tater):
        page = open_app(tater)
        expect(_title(page)).to_have_text("1 / 3")
        _assert_disabled(page, "#btn-prev")

    def test_next_advances_document(self, open_app, tater):
        page = open_app(tater)
        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")

    def test_next_content_updates(self, open_app, tater):
        page = open_app(tater)
        page.click("#btn-next")
        expect(page.locator("#document-content")).to_contain_text("Second document text")

    def test_prev_returns_to_first_document(self, open_app, tater):
        page = open_app(tater)
        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        page.click("#btn-prev")
        expect(_title(page)).to_have_text("1 / 3")

    def test_next_button_disabled_on_last_doc(self, open_app, tater):
        page = open_app(tater)
        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        page.click("#btn-next")
        expect(_title(page)).to_have_text("3 / 3")
        wait_quiet(page)
        _assert_disabled(page, "#btn-next")

    def test_multi_step_navigation(self, open_app, tater):
        page = open_app(tater)
        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        page.click("#btn-next")
        expect(_title(page)).to_have_text("3 / 3")
        page.click("#btn-prev")
        expect(_title(page)).to_have_text("2 / 3")


# ---------------------------------------------------------------------------
# Keyboard shortcuts (keyboard.js)
# ---------------------------------------------------------------------------

class SliderSchema(BaseModel):
    score: Optional[int] = None


@pytest.fixture
def tater_slider(tmp_path, docs_file):
    app = TaterApp(title="Slider", schema_model=SliderSchema, annotations_path=str(tmp_path / "ann_slider.json"))
    app.load_documents(docs_file)
    app.set_annotation_widgets([SliderWidget("score", label="Score", min_value=0, max_value=10, step=1)])
    yield app
    app.flush_saves()


class TestKeyboard:
    def test_arrow_keys_navigate(self, open_app, tater_slider):
        page = open_app(tater_slider)
        page.keyboard.press("ArrowRight")
        expect(_title(page)).to_have_text("2 / 3")
        page.keyboard.press("ArrowLeft")
        expect(_title(page)).to_have_text("1 / 3")

    def test_arrow_keys_on_slider_move_it(self, open_app, tater_slider):
        """Arrow keys on a focused slider thumb change its value, not the document.
        The thumb is a div, so keyboard.js used to take them as Prev/Next."""
        page = open_app(tater_slider)
        thumb = page.locator("[role=slider]")
        thumb.focus()
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        wait_quiet(page)
        expect(_title(page)).to_have_text("1 / 3")
        expect(thumb).to_have_attribute("aria-valuenow", "2")
        assert read_saved(tater_slider)["doc1"]["annotations"]["score"] == 2


# ---------------------------------------------------------------------------
# Document selector
# ---------------------------------------------------------------------------

def search_document_select(page: Page, text: str) -> list:
    """Open the document selector, replace its search text, and return the visible option texts."""
    select = page.locator("#document-select")
    select.click()
    select.fill(text)
    wait_quiet(page)
    return selector_options(page).all_inner_texts()


class TestDocumentSelect:
    def test_shows_current_document(self, open_app, tater):
        page = open_app(tater)
        expect(page.locator("#document-select")).to_have_value("1. Doc One")
        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        expect(page.locator("#document-select")).to_have_value("2. Doc Two")

    def test_lists_all_documents_with_status(self, open_app, tater):
        page = open_app(tater)
        options = search_document_select(page, "")
        assert len(options) == 3
        assert options[0].startswith("1. Doc One")
        assert "IN PROGRESS" in options[0].upper()
        assert "NOT STARTED" in options[1].upper()

    def test_selecting_option_navigates(self, open_app, tater):
        page = open_app(tater)
        search_document_select(page, "3")
        option = selector_options(page).first
        assert option.inner_text().startswith("3. Doc Three")
        option.click()
        expect(_title(page)).to_have_text("3 / 3")
        expect(page.locator("#document-content")).to_contain_text("Third document text")

    def test_search_by_name(self, open_app, tater):
        page = open_app(tater)
        options = search_document_select(page, "two")
        assert len(options) == 1
        assert options[0].startswith("2. Doc Two")

    def test_search_by_id(self, open_app, tater):
        page = open_app(tater)
        options = search_document_select(page, "doc3")
        assert len(options) == 1
        assert options[0].startswith("3. Doc Three")

    def test_flagged_filter(self, open_app, tater):
        page = open_app(tater)
        page.click("#flag-document")
        wait_quiet(page)
        page.click("#filter-btn")
        page.click("#filter-flagged-check")
        page.keyboard.press("Escape")
        wait_quiet(page)
        options = search_document_select(page, "")
        assert len(options) == 1
        assert options[0].startswith("1. Doc One")


# ---------------------------------------------------------------------------
# Large document sets (#107)
# ---------------------------------------------------------------------------

class LabelsSchema(BaseModel):
    labels: List[Literal["a", "b", "c", "d", "e", "f", "g"]] = Field(default_factory=list)


@pytest.fixture
def tater_large(tmp_path, request):
    """N short documents (the test class's N; 2,500 by default, the scale at which the
    old document menu froze the UI)."""
    n = getattr(request.cls, "N", 2500)
    docs = [{"id": f"doc_{i:05d}", "text": f"Synthetic sentence number {i}."} for i in range(n)]
    docs_path = tmp_path / f"docs_{n}.json"
    docs_path.write_text(json.dumps(docs))
    app = TaterApp(title="Large", schema_model=LabelsSchema, annotations_path=str(tmp_path / f"ann_{n}.json"))
    app.load_documents(str(docs_path))
    app.set_annotation_widgets([CheckboxGroupWidget("labels", label="Labels", vertical=True)])
    yield app
    app.flush_saves()


class TestLargeDocumentSet:
    """Each action should cost a handful of small callback requests, independent of N.

    Before #107 a Next click at this size sent ~20 requests over ~11 s, and the
    document menu was rebuilt several times per action. Before #108 every Next
    uploaded the whole annotations and metadata stores (~1.3 MB here); now an action
    sends only the current document. The byte bounds are ~3x the measured values,
    which are the same at 500 and 10,000 documents.

    Requests are counted by INIT_SCRIPT (perf/browser.py), as in the perf harness:
    bytes up are UTF-8 bytes (the same as characters for these ASCII bodies), and the
    2 s bound runs to the last response finishing, not the last request being sent.
    """

    N = 2500

    def _start(self, open_app, app) -> Page:
        page = open_app(app)
        expect(_title(page)).to_have_text(f"1 / {self.N}", timeout=30_000)
        wait_quiet(page, quiet=1.0)
        reset_counts(page)
        return page

    def test_next_click_settles_quickly(self, open_app, tater_large):
        page = self._start(open_app, tater_large)

        clicked = time.time()
        page.click("#btn-next")
        expect(_title(page)).to_have_text(f"2 / {self.N}")
        wait_quiet(page, quiet=1.0)
        d = dash_counts(page)

        assert d["requests"] <= 10, f"{d['requests']} callback requests for one Next click"
        assert d["requests"] and d["lastDone"] / 1000 - clicked < 2.0, "callback cascade took too long"
        assert d["up"] / 1000 <= 20, f"one Next click uploaded {d['up'] / 1000:.0f} KB"
        assert d["down"] / 1000 <= 20, f"one Next click downloaded {d['down'] / 1000:.0f} KB"

    def test_checkbox_tick_settles_quickly(self, open_app, tater_large):
        page = self._start(open_app, tater_large)

        clicked = time.time()
        page.click("input[type='checkbox'][value='a']")
        wait_quiet(page, quiet=1.0)
        d = dash_counts(page)

        assert d["requests"] <= 6, f"{d['requests']} callback requests for one checkbox tick"
        assert d["requests"] and d["lastDone"] / 1000 - clicked < 2.0, "callback cascade took too long"
        assert d["up"] / 1000 <= 10, f"one tick uploaded {d['up'] / 1000:.0f} KB"
        assert d["down"] / 1000 <= 10, f"one tick downloaded {d['down'] / 1000:.0f} KB"


@pytest.mark.perf
class TestLargeDocumentSet10k(TestLargeDocumentSet):
    """The same bounds at 10,000 documents (#108). Slow to set up, so excluded by
    default; run with ``-m perf``."""

    N = 10_000


# ---------------------------------------------------------------------------
# Flag and notes
# ---------------------------------------------------------------------------

class TestFlagAndNotes:
    def test_flag_updates_metadata(self, open_app, tater):
        page = open_app(tater)
        page.click("#flag-document")
        wait_quiet(page)

        saved = read_saved(tater)
        assert saved["doc1"]["metadata"]["flagged"] is True

    def test_unflag_updates_metadata(self, open_app, tater):
        page = open_app(tater)
        page.click("#flag-document")
        wait_quiet(page)
        page.click("#flag-document")
        wait_quiet(page)

        saved = read_saved(tater)
        assert saved["doc1"]["metadata"]["flagged"] is False

    def test_flag_is_per_document(self, open_app, tater):
        page = open_app(tater)
        page.click("#flag-document")
        wait_quiet(page)
        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        wait_quiet(page)

        saved = read_saved(tater)
        assert saved["doc1"]["metadata"]["flagged"] is True
        assert saved.get("doc2", {}).get("metadata", {}).get("flagged", False) is False

    def test_notes_update_metadata(self, open_app, tater):
        page = open_app(tater)
        page.locator("#document-notes").fill("needs review")
        wait_quiet(page)

        saved = read_saved(tater)
        assert saved["doc1"]["metadata"]["notes"] == "needs review"

    def test_notes_are_per_document(self, open_app, tater):
        page = open_app(tater)
        page.locator("#document-notes").fill("doc1 note")
        wait_quiet(page)
        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        wait_quiet(page)

        saved = read_saved(tater)
        assert saved["doc1"]["metadata"]["notes"] == "doc1 note"
        assert saved.get("doc2", {}).get("metadata", {}).get("notes", "") == ""

    def test_notes_field_clears_on_doc_change(self, open_app, tater):
        page = open_app(tater)
        page.locator("#document-notes").fill("something")
        wait_quiet(page)
        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        expect(page.locator("#document-notes")).to_have_value("")


# ---------------------------------------------------------------------------
# Annotation persistence
# ---------------------------------------------------------------------------

def _radio(page: Page, value: str):
    return page.locator(f"input[type='radio'][value='{value}']")


class TestAnnotationPersistence:
    def test_annotation_survives_navigation(self, open_app, tater_required):
        """Select a value, navigate away and back — loadValues restores it."""
        page = open_app(tater_required)
        _radio(page, "positive").check()

        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        page.click("#btn-prev")
        expect(_title(page)).to_have_text("1 / 3")

        # loadValues restores the annotation clientside
        expect(_radio(page, "positive")).to_be_checked()

    def test_status_goes_complete_on_departure_with_required_field_filled(self, open_app, tater_required):
        """Filling the required fields keeps the current doc In Progress; it becomes
        Complete when the user navigates away (completion is assigned on departure)."""
        # open_app waits for on_doc_change (server callback) to settle: it writes
        # visited=True to metadata-store, which update_status_from_annotations reads as
        # State. Without that wait the status callback may compute "not_started".
        page = open_app(tater_required)
        _radio(page, "positive").check()
        expect(page.locator("#status-badge")).to_have_text("IN PROGRESS", use_inner_text=True)

        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        wait_quiet(page)
        options = search_document_select(page, "")
        assert options[0].startswith("1. Doc One")
        assert "COMPLETE" in options[0].upper()

    def test_annotation_persists_to_file(self, open_app, tater_required):
        """Annotation written by captureValue reaches disk via auto_save."""
        page = open_app(tater_required)
        _radio(page, "negative").check()
        wait_quiet(page)

        saved = read_saved(tater_required)
        assert saved["doc1"]["annotations"]["label"] == "negative"

    def test_different_docs_have_independent_annotations(self, open_app, tater_required):
        """Annotations for each document are stored independently."""
        page = open_app(tater_required)
        _radio(page, "positive").check()

        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        wait_quiet(page)
        _radio(page, "negative").check()
        wait_quiet(page)

        saved = read_saved(tater_required)
        assert saved["doc1"]["annotations"]["label"] == "positive"
        assert saved["doc2"]["annotations"]["label"] == "negative"


# ---------------------------------------------------------------------------
# Auto-advance
# ---------------------------------------------------------------------------

class TestAutoAdvance:
    def test_selecting_value_advances_to_next_doc(self, open_app, tater_auto_advance):
        """Selecting a value on an auto_advance widget advances to the next document."""
        page = open_app(tater_auto_advance)
        _radio(page, "positive").click()  # not check(): the next document's radio is unchecked
        expect(_title(page)).to_have_text("2 / 3")

    def test_auto_advance_does_not_advance_past_last_doc(self, open_app, tater_auto_advance):
        """Selecting a value on the last document does not navigate further."""
        page = open_app(tater_auto_advance)
        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        page.click("#btn-next")
        expect(_title(page)).to_have_text("3 / 3")
        wait_quiet(page)

        _radio(page, "positive").click()
        wait_quiet(page)
        assert _title(page).inner_text() == "3 / 3"


# ---------------------------------------------------------------------------
# Save and restore
# ---------------------------------------------------------------------------

class TestSaveRestore:
    def test_annotations_restored_on_reload(self, open_app, tater_required, docs_file):
        """Annotations written during a session are loaded by a new TaterApp instance."""
        page = open_app(tater_required)
        _radio(page, "uncertain").check()
        wait_quiet(page)

        # Verify the file was written before creating the new app
        saved = read_saved(tater_required)
        assert saved["doc1"]["annotations"]["label"] == "uncertain"

        # New TaterApp loading from the same annotations file
        app2 = TaterApp(
            title="Reload Test",
            schema_model=SimpleSchema,
            annotations_path=tater_required.annotations_path,
        )
        app2.load_documents(docs_file)
        app2.set_annotation_widgets([
            RadioGroupWidget(schema_field="label", label="Label", required=True),
        ])

        assert "doc1" in app2.annotations
        assert app2.annotations["doc1"].label == "uncertain"

    def test_page_refresh_keeps_annotations(self, open_app, tater_required):
        """A browser refresh shows the latest annotations and document, and doesn't overwrite the file.

        The layout used to be built once at startup, so a refresh brought back the
        startup state and the next auto-save wrote it over the saved edits.
        """
        page = open_app(tater_required)
        _radio(page, "uncertain").check()
        wait_quiet(page)
        assert read_saved(tater_required)["doc1"]["annotations"]["label"] == "uncertain"

        page.reload()
        settle(page)  # page-load callbacks and any auto_save they trigger
        expect(_title(page)).to_have_text("1 / 3")
        expect(_radio(page, "uncertain")).to_be_checked()

        page.click("#btn-next")
        expect(_title(page)).to_have_text("2 / 3")
        wait_quiet(page)
        _radio(page, "positive").check()
        wait_quiet(page)

        saved = read_saved(tater_required)
        assert saved["doc1"]["annotations"]["label"] == "uncertain"
        assert saved["doc2"]["annotations"]["label"] == "positive"

        # A refresh reopens the document the user was on, not the first one.
        page.reload()
        settle(page)
        expect(_title(page)).to_have_text("2 / 3")
        expect(_radio(page, "positive")).to_be_checked()

    def test_no_restore_skips_loading(self, open_app, tater_required, docs_file):
        """--no-restore (restore_annotations=False) means prior annotations are ignored."""
        page = open_app(tater_required)
        _radio(page, "positive").check()
        wait_quiet(page)
        tater_required.flush_saves()

        app2 = TaterApp(
            title="No Restore Test",
            schema_model=SimpleSchema,
            annotations_path=tater_required.annotations_path,
            restore_annotations=False,
        )
        app2.load_documents(docs_file)
        app2.set_annotation_widgets([
            RadioGroupWidget(schema_field="label", label="Label", required=True),
        ])

        # No annotations loaded — doc1 should be absent or have no label
        ann = app2.annotations.get("doc1")
        assert ann is None or ann.label is None


# ---------------------------------------------------------------------------
# Every widget survives a reload
# ---------------------------------------------------------------------------

ABC = Literal["a", "b", "c"]
SITES = {
    "Head": ["Brain", "Eye"],
    "Thorax": {"Lung": ["Left lung", "Right lung"], "Heart": []},
    "Abdomen": ["Liver", "Kidney"],
}


class Part(BaseModel):
    note: Optional[str] = None


class Item(BaseModel):
    kind: Optional[Literal["x", "y"]] = None
    evidence: List[SpanAnnotation] = Field(default_factory=list)
    parts: List[Part] = Field(default_factory=list)


class AllWidgets(BaseModel):
    radio: Optional[ABC] = None
    reason: Optional[str] = None
    segmented: Optional[ABC] = None
    chip_radio: Optional[ABC] = None
    select: Optional[ABC] = None
    multi_select: List[ABC] = Field(default_factory=list)
    checkbox_group: List[ABC] = Field(default_factory=list)
    checkbox: Optional[bool] = None
    switch: Optional[bool] = None
    chip: Optional[bool] = None
    number: Optional[int] = None
    slider: Optional[int] = None
    range_slider: Optional[List[int]] = None
    text: Optional[str] = None
    textarea: Optional[str] = None
    spans: List[SpanAnnotation] = Field(default_factory=list)
    hl_one: Optional[List[str]] = None
    hl_many: Optional[List[List[str]]] = None
    items: List[Item] = Field(default_factory=list)


ROUND_TRIP_DOCS = [
    {"id": "doc1", "name": "Doc One", "text": "Alpha bravo charlie delta echo foxtrot golf hotel."},
    {"id": "doc2", "name": "Doc Two", "text": "India juliet kilo lima mike november oscar papa."},
    {"id": "doc3", "name": "Doc Three", "text": "Quebec romeo sierra tango uniform victor whiskey."},
]

# What test_values_saved expects in the file after fill_all on doc1.
FILLED = {
    "radio": "b",
    "reason": None,
    "segmented": "b",
    "chip_radio": "b",
    "select": "b",
    "multi_select": ["a", "c"],
    "checkbox_group": ["a", "c"],
    "checkbox": True,
    "switch": True,
    "chip": True,
    "number": 7,
    "slider": 3,
    "range_slider": [0, 60],
    "text": "hello",
    "textarea": "two words",
    "spans": [{"start": 12, "end": 19, "text": "charlie", "tag": "Tag"}],
    "hl_one": ["Head", "Brain"],
    "hl_many": [["Abdomen", "Liver"], ["Thorax", "Lung", "Left lung"]],
    "items": [
        {"kind": "x", "evidence": [], "parts": [{"note": "p"}]},
        {"kind": "y", "evidence": [{"start": 39, "end": 43, "text": "golf", "tag": "Ev"}], "parts": []},
    ],
}


@pytest.fixture
def tater_all_widgets(tmp_path):
    """One TaterApp with every widget, including spans, a repeater and a nested repeater."""
    docs = tmp_path / "docs.json"
    docs.write_text(json.dumps(ROUND_TRIP_DOCS))
    app = TaterApp(title="Round trip", schema_model=AllWidgets, annotations_path=str(tmp_path / "ann.json"))
    app.load_documents(str(docs))
    app.set_annotation_widgets([
        RadioGroupWidget("radio", label="Radio"),
        # Not filled: hidden while radio != "c". Checks conditional wrappers don't hide
        # the other widgets' values after a reload.
        TextInputWidget("reason", label="Reason").conditional_on("radio", "c"),
        SegmentedControlWidget("segmented", label="Segmented"),
        ChipRadioWidget("chip_radio", label="Chip radio"),
        SelectWidget("select", label="Select"),
        MultiSelectWidget("multi_select", label="Multi select"),
        CheckboxGroupWidget("checkbox_group", label="Checkbox group"),
        CheckboxWidget("checkbox", label="Checkbox"),
        SwitchWidget("switch", label="Switch"),
        ChipWidget("chip", label="Chip"),
        NumberInputWidget("number", label="Number"),
        SliderWidget("slider", label="Slider", min_value=0, max_value=10, step=1),
        # Mantine's RangeSlider keeps the thumbs minRange (10) apart, so a wide scale.
        RangeSliderWidget("range_slider", label="Range", min_value=0, max_value=100, step=10),
        TextInputWidget("text", label="Text"),
        TextAreaWidget("textarea", label="Text area"),
        SpanAnnotationWidget("spans", label="Spans", entity_types=[EntityType("Tag")]),
        HierarchicalLabelSelectWidget("hl_one", label="Site", hierarchy=SITES),
        HierarchicalLabelMultiWidget("hl_many", label="Sites", hierarchy=SITES),
        ListableWidget("items", label="Items", item_label="Item", item_widgets=[
            RadioGroupWidget("kind", label="Kind"),
            SpanAnnotationWidget("evidence", label="Evidence", entity_types=[EntityType("Ev")]),
            ListableWidget("parts", label="Parts", item_label="Part", item_widgets=[
                TextInputWidget("note", label="Note"),
            ]),
        ]),
    ])
    yield app
    app.flush_saves()


def _ctl(page: Page, tf: str, ld: str = "", path: str = ""):
    """A widget's element with the pattern-matching ID {ld, path, tf, type: tater-*}."""
    return page.locator(f"""[id*='"ld":"{ld}","path":"{path}","tf":"{tf}","type":"tater-']""").first


def _group(page: Page, tf: str, role: str = "radiogroup", ld: str = "", path: str = ""):
    """A radio or checkbox group, found by its aria-labelledby (the group has no ID)."""
    return page.locator(f"""[role={role}][aria-labelledby*='"ld":"{ld}","path":"{path}","tf":"{tf}"']""")


def _chip_radio(page: Page):
    """The chip radio group: neither it nor its inputs have a tater ID, so by its label."""
    return page.get_by_text("Chip radio", exact=True).locator("xpath=..")


def _id_has(**keys) -> str:
    """CSS for an element whose dict ID contains every key/value (as JSON)."""
    return "".join(f"""[id*='"{k}":{json.dumps(v)}']""" for k, v in keys.items())


def _checked(loc) -> list:
    """Values of the checked inputs under ``loc`` ([] if ``loc`` isn't on the page)."""
    return loc.locator("input").evaluate_all("els => els.filter(i => i.checked).map(i => i.value)")


def _pills(loc) -> list:
    """Labels of a MultiSelect's pills."""
    return loc.evaluate(
        "el => [...el.closest('.mantine-InputWrapper-root').querySelectorAll('.mantine-Pill-label')]"
        ".map(p => p.textContent)")


def _press_on(page: Page, target, key: str, times: int) -> None:
    """Focus ``target`` (e.g. a slider thumb) and press ``key`` ``times`` times."""
    target.focus()
    for _ in range(times):
        page.keyboard.press(key)


def _select_text(page: Page, word: str) -> None:
    """Select ``word`` in the document text, as a user would before tagging a span."""
    page.evaluate("""word => {
        const walker = document.createTreeWalker(document.getElementById('document-content'), NodeFilter.SHOW_TEXT);
        let n;
        while ((n = walker.nextNode())) {
            const i = n.textContent.indexOf(word);
            if (i >= 0 && !n.parentElement.closest('mark')) {
                const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + word.length);
                const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
                return;
            }
        }
        throw new Error('not in the document: ' + word);
    }""", word)


def _pick(page: Page, input_loc, *labels: str) -> None:
    """Open a Select/MultiSelect and pick options by label; close it again."""
    for label in labels:
        input_loc.click()
        input_loc.fill(label)
        page.get_by_role("option", name=label, exact=True).first.click()
    page.keyboard.press("Escape")


def fill_all(page: Page) -> None:
    """Give every widget (except the hidden conditional) the value in FILLED."""
    def step(fn):
        fn()
        wait_quiet(page, quiet=0.2)  # each step's callbacks start at once; 0.5 s is for the harness

    step(lambda: _group(page, "radio").locator("input[value=b]").check())
    step(lambda: _ctl(page, "segmented").get_by_text("b", exact=True).click())
    step(lambda: _chip_radio(page).get_by_text("b", exact=True).click())
    step(lambda: (_ctl(page, "select").click(), page.get_by_role("option", name="b", exact=True).click()))
    step(lambda: _pick(page, _ctl(page, "multi_select"), "a", "c"))
    group = _group(page, "checkbox_group", role="group")
    step(lambda: group.locator("input[value=a]").check())
    step(lambda: group.locator("input[value=c]").check())
    step(lambda: _ctl(page, "checkbox").click(force=True))
    step(lambda: _ctl(page, "switch").click(force=True))
    step(lambda: _ctl(page, "chip").locator("xpath=..").locator("label").click())  # the input is hidden
    step(lambda: _ctl(page, "number").fill("7"))
    # Sliders by keyboard, as on the thumb these keys must not also go to Prev/Next.
    step(lambda: _press_on(page, _ctl(page, "slider").locator("[role=slider]"), "ArrowRight", 3))
    step(lambda: _press_on(page, _ctl(page, "range_slider").locator("[role=slider]").nth(1), "ArrowLeft", 4))
    step(lambda: _ctl(page, "text").fill("hello"))
    step(lambda: _ctl(page, "textarea").fill("two words"))
    _select_text(page, "charlie")
    step(lambda: page.locator(_id_has(type="span-add-btn", field="spans")).click())
    step(lambda: _pick(page, page.locator("input" + _id_has(type="hl-select", field="hl_one")), "Brain"))
    step(lambda: _pick(page, page.locator("input" + _id_has(type="hl-multi", field="hl_many")), "Liver", "Left lung"))
    add = page.locator(_id_has(type="repeater-add", field="items"))
    step(add.click)
    step(add.click)
    step(lambda: _group(page, "kind", ld="items", path="0").locator("input[value=x]").check())
    step(lambda: _group(page, "kind", ld="items", path="1").locator("input[value=y]").check())
    _select_text(page, "golf")
    step(lambda: page.locator(_id_has(type="span-add-btn", field="items|1|evidence")).click())
    step(lambda: page.locator(_id_has(type="nested-repeater-add", li=0)).click())
    step(lambda: _ctl(page, "note", ld="items|parts", path="0.0").fill("p"))


def shown(page: Page) -> dict:
    """What each widget shows, as the user sees it."""
    def count(css):
        return page.locator(css).count()

    def value_or_none(loc):
        return loc.input_value() if loc.count() else None

    return {
        "radio": _checked(_group(page, "radio")),
        "segmented": _checked(_ctl(page, "segmented")),
        "chip_radio": _checked(_chip_radio(page)),
        "select": _ctl(page, "select").input_value(),
        "multi_select": _pills(_ctl(page, "multi_select")),
        "checkbox_group": _checked(_group(page, "checkbox_group", role="group")),
        "checkbox": _ctl(page, "checkbox").is_checked(),
        "switch": _ctl(page, "switch").is_checked(),
        "chip": _ctl(page, "chip").is_checked(),
        "number": _ctl(page, "number").input_value(),
        "slider": _ctl(page, "slider").locator("[role=slider]").get_attribute("aria-valuenow"),
        "range_slider": [t.get_attribute("aria-valuenow")
                         for t in _ctl(page, "range_slider").locator("[role=slider]").all()],
        "text": _ctl(page, "text").input_value(),
        "textarea": _ctl(page, "textarea").input_value(),
        "marks": sorted(page.locator("#document-content mark").all_inner_texts()),
        "hl_one": page.locator("input" + _id_has(type="hl-select", field="hl_one")).input_value(),
        "hl_many": _pills(page.locator("input" + _id_has(type="hl-multi", field="hl_many"))),
        "items": count(_id_has(type="repeater-delete", field="items")),
        "items.0.kind": _checked(_group(page, "kind", ld="items", path="0")),
        "items.1.kind": _checked(_group(page, "kind", ld="items", path="1")),
        "items.0.parts": count(_id_has(type="nested-repeater-delete", li=0)),
        "items.1.parts": count(_id_has(type="nested-repeater-delete", li=1)),
        "items.0.parts.0.note": value_or_none(_ctl(page, "note", ld="items|parts", path="0.0")),
        "reason hidden": not _ctl(page, "reason").is_visible(),
    }


SHOWN_FILLED = {
    "radio": ["b"], "segmented": ["b"], "chip_radio": ["b"], "select": "b",
    "multi_select": ["a", "c"], "checkbox_group": ["a", "c"],
    "checkbox": True, "switch": True, "chip": True, "number": "7",
    "slider": "3", "range_slider": ["0", "60"], "text": "hello", "textarea": "two words",
    "marks": ["charlie", "golf"], "hl_one": "Brain", "hl_many": ["Liver", "Left lung"],
    "items": 2, "items.0.kind": ["x"], "items.1.kind": ["y"],
    "items.0.parts": 1, "items.1.parts": 0, "items.0.parts.0.note": "p",
    "reason hidden": True,
}

SHOWN_EMPTY = {
    "radio": [], "segmented": [], "chip_radio": [], "select": "",
    "multi_select": [], "checkbox_group": [],
    "checkbox": False, "switch": False, "chip": False, "number": "",
    "slider": "0", "range_slider": ["0", "100"], "text": "", "textarea": "",
    "marks": [], "hl_one": "", "hl_many": [],
    "items": 0, "items.0.kind": [], "items.1.kind": [],
    "items.0.parts": 0, "items.1.parts": 0, "items.0.parts.0.note": None,
    "reason hidden": True,
}


def _mismatches(got: dict, want: dict) -> dict:
    """{field: (want, got)} for every field that differs, so one failure names them all."""
    return {k: (v, got.get(k)) for k, v in want.items() if got.get(k) != v}


def _go(page: Page, button: str, k: int) -> None:
    page.click(button)
    wait_position(page, k)
    wait_quiet(page)


class TestWidgetRoundTrip:
    def test_values_saved(self, open_app, tater_all_widgets, errors):
        page = open_app(tater_all_widgets)
        fill_all(page)
        saved = read_saved(tater_all_widgets)["doc1"]["annotations"]
        assert _mismatches(saved, FILLED) == {}
        assert errors == []

    def test_values_survive_next_prev(self, open_app, tater_all_widgets, errors):
        page = open_app(tater_all_widgets)
        fill_all(page)
        _go(page, "#btn-next", 2)
        assert _mismatches(shown(page), SHOWN_EMPTY) == {}, "document 2 shows document 1's values"
        _go(page, "#btn-prev", 1)
        assert _mismatches(shown(page), SHOWN_FILLED) == {}
        assert errors == []

    def test_values_survive_reload(self, open_app, tater_all_widgets, errors):
        page = open_app(tater_all_widgets)
        fill_all(page)
        page.reload()
        settle(page)
        assert _mismatches(shown(page), SHOWN_FILLED) == {}, "after reload"
        _go(page, "#btn-next", 2)
        _go(page, "#btn-prev", 1)
        assert _mismatches(shown(page), SHOWN_FILLED) == {}, "after reload, Next, Prev"
        assert errors == []

    def test_reload_then_edit_keeps_file(self, open_app, tater_all_widgets, errors):
        """An edit after a reload doesn't write the page's startup state over the file (#108)."""
        page = open_app(tater_all_widgets)
        fill_all(page)
        page.reload()
        settle(page)
        _ctl(page, "text").fill("changed")
        wait_quiet(page)
        saved = read_saved(tater_all_widgets)["doc1"]["annotations"]
        assert _mismatches(saved, {**FILLED, "text": "changed"}) == {}
        assert errors == []


# ---------------------------------------------------------------------------
# Hosted mode: edits survive reload and navigation; sessions stay separate
# ---------------------------------------------------------------------------

EXAMPLES = sorted(p.parent.name for p in (Path(__file__).parent.parent / "tater" / "examples").glob("*/meta.json"))


@pytest.fixture(scope="module")
def hosted_server(tmp_path_factory, request):
    """``tater --hosted`` in a subprocess (the hosted app is only built by the CLI)."""
    directory = tmp_path_factory.mktemp("hosted")
    failed_before = request.session.testsfailed
    with run_tater(directory, hosted=True) as server:
        yield server
    log = directory / "server.log"
    if request.session.testsfailed > failed_before and log.exists():
        print("--- server.log (end)\n" + log.read_text()[-3000:])


class Session:
    """One browser context = one Flask session cookie = one hosted session, on ``example``."""

    def __init__(self, context, server, example: str):
        self.context = context
        self.page = context.new_page()
        self.errors: list = []
        watch_errors(self.page, self.errors)
        self.page.goto(server.url + "/")
        self.page.get_by_text("Browse examples").click()
        self.page.locator(f"[id*='\"example-card\"'][id*='\"{example}\"']").click()
        self.page.wait_for_url("**/annotate", timeout=30_000)
        settle(self.page)

    def reload(self) -> None:
        self.page.reload()
        settle(self.page)

    def go(self, button: str, k: int) -> None:
        _go(self.page, button, k)
        self.page.wait_for_timeout(500)

    def notes(self) -> str:
        return self.page.locator("#document-notes").input_value()

    def first(self, css: str):
        loc = self.page.locator(css)
        return loc.first if loc.count() else None

    def state(self) -> dict:
        b = self.first("[id*='\"tater-bool-control\"']")
        hl = self.first("input[id*='\"hl-select\"']")
        return {
            "notes": self.notes(),
            "flag": self.page.locator("#flag-document").is_checked(),
            "bool": b.is_checked() if b else None,
            "repeater_items": self.page.locator("[id*='\"repeater-delete\"']").count(),
            "hl": hl.input_value() if hl else None,
            "marks": self.page.locator("#document-content mark").count(),
        }

    def edit(self, tag: str) -> dict:
        """Make one edit of each kind the example supports; return the state after."""
        page = self.page
        page.locator("#document-notes").fill(f"notes {tag}")
        wait_quiet(page, quiet=0.2)
        page.locator("#flag-document").click()
        wait_quiet(page, quiet=0.2)
        b = self.first("[id*='\"tater-bool-control\"']")
        if b:
            b.click()
            wait_quiet(page, quiet=0.2)
        add = self.first("[id*='\"repeater-add\"']")
        if add:
            add.click()
            wait_quiet(page, quiet=0.2)
        hl = self.first("input[id*='\"hl-select\"']")
        if hl:
            hl.click()
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            page.keyboard.press("Escape")
            wait_quiet(page, quiet=0.2)
        span = self.first("[id*='\"span-add-btn\"']")
        if span:
            select_word(page, 3)
            span.click()
            wait_quiet(page, quiet=0.2)
        page.wait_for_timeout(500)
        return self.state()


@pytest.fixture(scope="class")
def hosted_run(browser, browser_context_args, hosted_server, example):
    """One scripted run on ``example`` with two sessions, A and B; each test checks one
    stage of it. Running the script once per example rather than once per check keeps
    the eight examples to about a minute and a half."""
    contexts = []

    def open_session() -> Session:
        ctx = browser.new_context(**browser_context_args)
        ctx.add_init_script(INIT_SCRIPT)
        contexts.append(ctx)
        return Session(ctx, hosted_server, example)

    run = {}
    try:
        a = open_session()
        run["fresh"] = a.state()
        run["has"] = {kind: a.first(f"[id*='\"{kind}\"']") is not None for kind in ("repeater-add", "span-add-btn")}
        run["edited"] = a.edit("A")
        a.reload()
        run["reloaded"] = a.state()
        p = position(a.page)
        a.go("#btn-next", p + 1)
        run["next_doc"] = a.state()
        a.go("#btn-prev", p)
        run["next_prev"] = a.state()
        b = open_session()
        run["b_fresh"] = b.state()
        b.edit("B")
        a.reload()
        run["a_after_b"] = a.state()
        b.reload()
        run["b_notes"] = b.notes()
        run["errors"] = {"A": a.errors, "B": b.errors}
        yield run
    finally:
        for ctx in contexts:
            ctx.close()


@pytest.mark.parametrize("example", EXAMPLES, scope="class")
class TestHosted:
    def test_edits_apply(self, hosted_run):
        fresh, got = hosted_run["fresh"], hosted_run["edited"]
        assert got["notes"] == "notes A"
        assert got["flag"] != fresh["flag"]
        if fresh["bool"] is not None:
            assert got["bool"] != fresh["bool"]
        if hosted_run["has"]["repeater-add"]:
            assert got["repeater_items"] == fresh["repeater_items"] + 1
        if got["hl"] is not None:
            assert got["hl"], "no hierarchical label picked"
        if hosted_run["has"]["span-add-btn"]:
            assert got["marks"] == fresh["marks"] + 1

    def test_reload_keeps_edits(self, hosted_run):
        assert hosted_run["reloaded"] == hosted_run["edited"]

    def test_next_doc_is_clean(self, hosted_run):
        other = hosted_run["next_doc"]
        assert other["notes"] != "notes A"
        assert other["flag"] == hosted_run["fresh"]["flag"]

    def test_next_prev_keeps_edits(self, hosted_run):
        assert hosted_run["next_prev"] == hosted_run["edited"]

    def test_second_session_starts_clean(self, hosted_run):
        assert hosted_run["b_fresh"] == hosted_run["fresh"]

    def test_sessions_dont_mix(self, hosted_run):
        assert hosted_run["a_after_b"] == hosted_run["edited"], "B's edits reached A"
        assert hosted_run["b_notes"] == "notes B", "B lost its own edits"

    def test_no_errors(self, hosted_run):
        """No JS errors and no failed callback requests in either session."""
        assert hosted_run["errors"] == {"A": [], "B": []}


# ---------------------------------------------------------------------------
# Hosted mode: a tab whose session has ended never reaches another session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def hosted_server_one_session(tmp_path_factory, request):
    """``tater --hosted`` keeping only the most recent session."""
    directory = tmp_path_factory.mktemp("hosted-one")
    failed_before = request.session.testsfailed
    with run_tater(directory, hosted=True, env={"TATER_SESSION_CACHE_MAX": "1"}) as server:
        yield server
    log = directory / "server.log"
    if request.session.testsfailed > failed_before and log.exists():
        print("--- server.log (end)\n" + log.read_text()[-3000:])


class TestHostedEndedSession:
    def test_ended_session_does_not_reach_first_session(
        self, browser, browser_context_args, hosted_server_one_session
    ):
        """Callbacks are registered by the first session's TaterApp. A request from a
        session that has gone used to fall back to it: B's Next showed A's documents,
        from another project, and B's edits changed A's copy. Now it changes nothing."""
        contexts = []

        def open_session(example: str) -> Session:
            ctx = browser.new_context(**browser_context_args)
            ctx.add_init_script(INIT_SCRIPT)
            contexts.append(ctx)
            return Session(ctx, hosted_server_one_session, example)

        try:
            a = open_session("simple")       # registers the callbacks
            a_text = a.page.locator("#document-content").inner_text()
            b = open_session("coarse_breast_label")  # another project; evicts A
            open_session("simple")           # evicts B; B's tab stays open
            b_text = b.page.locator("#document-content").inner_text()
            b_pos = position(b.page)
            assert b_text != a_text

            b.page.locator("#btn-next").click()
            wait_quiet(b.page)
            b.page.wait_for_timeout(500)

            assert b.page.locator("#document-content").inner_text() == b_text
            assert position(b.page) == b_pos
            assert b.errors == []

            b.page.reload()  # the session is gone: back to the upload page
            expect(b.page.get_by_text("Browse examples")).to_be_visible()
        finally:
            for ctx in contexts:
                ctx.close()


# ---------------------------------------------------------------------------
# Hosted mode: the least recently used session is evicted, and its user is told
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def hosted_server_two_sessions(tmp_path_factory, request):
    """``tater --hosted`` keeping two sessions."""
    directory = tmp_path_factory.mktemp("hosted-two")
    failed_before = request.session.testsfailed
    with run_tater(directory, hosted=True, env={"TATER_SESSION_CACHE_MAX": "2"}) as server:
        yield server
    log = directory / "server.log"
    if request.session.testsfailed > failed_before and log.exists():
        print("--- server.log (end)\n" + log.read_text()[-3000:])


@pytest.fixture(scope="class")
def eviction_run(browser, browser_context_args, hosted_server_two_sessions):
    """A and B start; A edits (so B is now the least recently used); C starts."""
    contexts = []

    def open_session() -> Session:
        ctx = browser.new_context(**browser_context_args)
        ctx.add_init_script(INIT_SCRIPT)
        contexts.append(ctx)
        return Session(ctx, hosted_server_two_sessions, "simple")

    run = {}
    try:
        a = open_session()
        b = open_session()
        a.page.locator("#document-notes").fill("notes A")
        wait_quiet(a.page, quiet=0.2)
        a.page.wait_for_timeout(500)
        open_session()                         # C: one session has to go
        a.reload()
        run["a_notes"] = a.notes()
        b.page.reload()
        b.page.wait_for_load_state("networkidle")
        run["b_upload_page"] = b.page.get_by_text("Browse examples").is_visible()
        notice = b.page.locator("#session-ended-notice")
        run["b_notice"] = notice.inner_text() if notice.count() else None
        run["errors"] = {"A": a.errors}
        yield run
    finally:
        for ctx in contexts:
            ctx.close()


class TestHostedEviction:
    def test_active_session_is_kept(self, eviction_run):
        assert eviction_run["a_notes"] == "notes A"
        assert eviction_run["errors"] == {"A": []}

    def test_ended_session_shows_notice(self, eviction_run):
        assert eviction_run["b_upload_page"]
        assert eviction_run["b_notice"] and "session has ended" in eviction_run["b_notice"]
