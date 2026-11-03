# Scaling to 10k documents — spec

Implementation plan for the [scaling pitch](scaling-pitch.md) (issue [#108](https://github.com/text-harvest/tater/issues/108)). Target: projects of up to 10,000 documents, in single mode first and hosted mode after. Phases 0–1 are fixed. The order within Phase 2 is provisional until the Phase 1 baseline confirms it.

## Current state

Facts this plan builds on, as of `dev` at 4b24e7a.

### Callbacks that read the full stores

`annotations-store` and `metadata-store` hold every document. Clientside callbacks that read them cost nothing in transfer. The server-side callbacks below each upload one or both stores in full, and most also return `metadata-store` in full.

| Callback | File | Trigger | Full stores read | What it actually needs |
|---|---|---|---|---|
| `auto_save` | `callbacks/core.py` | any change to either store | both (as **Input**) | the changed documents |
| `update_status_from_annotations` | `callbacks/core.py` | any change to `annotations-store` | both | current doc |
| `navigate_buttons`, `navigate_select`, `navigate_auto_advance` | `callbacks/core.py` | Prev/Next, selector, auto-advance | both | departing doc's annotations + metadata, arriving doc's metadata |
| `on_doc_change` | `callbacks/core.py` | `current-doc-id` | both | arriving doc |
| `load_flag_and_notes`, `save_flag`, `save_notes`, `toggle_pause`, `on_save_click` | `callbacks/core.py` | navigation / control change | metadata | current doc's metadata |
| `handle_finish` | `callbacks/core.py` | Finish button | both | all statuses (counts) and current doc |
| `go_to_first_incomplete` | `callbacks/core.py` | button in Finish modal | both | first non-complete doc |
| `download_annotations` | `callbacks/core.py` | Download button | both | everything (by definition) |
| `load_select`, `handle_select_change`, `load_multi`, `handle_multi_change` | `callbacks/hierarchical_label.py` | per HL widget (MATCH) | annotations | current doc |
| `update_repeater`, `_update_nested_items` | `callbacks/repeater.py` | per repeater (MATCH) | annotations | current doc |

The MATCH callbacks fire once per widget instance, so a schema with *k* hierarchical-label or repeater widgets uploads the full annotations store *k* extra times per navigation.

A checkbox tick today runs `captureChecked` (clientside), then `update_status_from_annotations` (uploads both stores, returns the full metadata store), then `auto_save`. `auto_save` fires twice: once for the annotations change and once for the metadata change. Each run uploads both stores and rewrites the whole file.

### Already O(1)

`_doc_index` (`callbacks/helpers.py`) caches an `id → index` dict. The document selector builds its options once, reads status lazily, and is covered by `TestLargeDocumentSet` ([#107](https://github.com/text-harvest/tater/issues/107)).

### Remaining linear scans

`handle_finish` sums status and time over `ta.documents` (`core.py`, about lines 266–275), and `go_to_first_incomplete` walks `ta.documents` (about line 314). Both run only on a button click. `updateStatusBadges` (clientside) recounts all statuses on each metadata change.

### Bug: page refresh in single mode loses edits

`TaterApp.set_annotation_widgets` assigns `self.app.layout = layout.build_layout(self)`. That's a static layout whose `annotations-store` / `metadata-store` data come from `self.annotations` / `self.metadata` *as loaded at startup*. `_save_stores_to_file` writes the file but never updates those attributes.

So after any edit, a browser refresh shows the startup values. This was checked by fetching `/_dash-layout` after a save: doc1 came back `None` while the file had `uncertain`. The next change then triggers `auto_save` with that stale store, which overwrites the edits made before the refresh. Two open tabs overwrite each other the same way.

Hosted mode builds layouts per request in `serve_layout`, but from the session `TaterApp`'s startup data, so a refresh drops unsaved work there too (there is no file to lose).

### Writes aren't atomic

`_save_stores_to_file` and `_save_annotations_to_file` (`tater_app.py`) write straight to the target with `open(path, "w")`. A crash mid-write leaves a truncated file.

## Phase 0 — Measurement harness

### Dependencies

`uv add --dev playwright psutil`, then once per machine `uv run playwright install chromium`. The existing dash.testing/Selenium tests are unchanged.

### Layout

```
perf/
  __init__.py
  synthetic.py      # project generator
  server.py         # start tater in a subprocess on a free port
  measure.py        # Playwright per-action recorder
  actions.py        # single actions and journeys
  bench_server.py   # browser-free timings: startup, save, memory
  trace_report.py   # summarise a callback trace, apply the automatic flags
  run.py            # CLI: run the matrix, write CSV + Markdown summary
  results/          # committed baselines (gitignore everything else)
```

`perf/` lives at the repo root, outside the `tater/` package and `tests/`, so it isn't shipped in the wheel and isn't picked up by the default pytest run. #109 imports from it.

### `synthetic.py`

```python
@dataclass
class Project:
    docs: list[dict]                 # [{"id", "text", "name"}]
    annotations: dict[str, dict]     # saved-file format: {doc_id: {"annotations": ..., "metadata": ...}}
    config_source: str               # Python config module text (schema + widgets)

def make_project(
    n_docs: int,                     # 50 | 500 | 2_500 | 10_000
    doc_chars: int,                  # ~200 | ~50_000 | ~1_000_000
    filled: bool,                    # empty vs. every doc annotated
    spans_per_doc: int = 0,          # e.g. 50 for the dense case
    schema: Literal["checkbox", "realistic"] = "checkbox",
    seed: int = 0,
) -> Project: ...
```

- `"checkbox"` is the `LabelsSchema` from `tests/test_browser.py`.
- `"realistic"` follows `apps/examples/config/gallery.py`: a choice, a boolean, a text area, a repeater of items with a nested choice, a span field, a hierarchical label (small inline tree), and one conditional.
- Text is generated from a fixed word list with a seeded RNG, so every run is reproducible. Use synthetic data only.
- `write_project(project, dir) -> (config_path, docs_path, annotations_path)` writes the files the CLI needs.

### `server.py`

`run_tater(dir, *, hosted=False, trace_path=None) -> ContextManager[ServerInfo]` starts `tater --config … --documents …` (or `--hosted`) with `subprocess.Popen` on a free port. It waits until `/` responds and yields `ServerInfo(url, pid)`. A subprocess keeps server memory measurable (`psutil.Process(pid).memory_info().rss`) and matches real use.

### Callback trace (in tater)

Enabled by `TATER_TRACE=<path>`, or by `--trace <path>` added to the CLI next to `--debug`. When enabled, `TaterApp` registers Flask hooks on `app.server`:

- `before_request` on `/_dash-update-component`: record the start time, the request byte length, and the `output` and `changedPropIds` fields from the JSON body.
- `after_request`: record the duration, the response byte length, and the status (Dash returns **204** when a callback changes nothing). Append one JSON line to the trace file:

```json
{"t": 1730000000.123, "action": "next#3", "output": "current-doc-id.data...", "trigger": ["btn-next.n_clicks"], "req_bytes": 271234, "resp_bytes": 1840, "ms": 12.4, "status": 200}
```

- `POST /_tater/trace/action` with `{"label": "next#3"}` sets the current action label. The harness calls it before each action. It's only registered when tracing is on.

Nothing is registered when tracing is off, so there's no overhead.

`trace_report.py` groups lines by `action` and raises three flags:

- the same `output` fired more than twice in one action
- `req_bytes` or `resp_bytes` above 100 KB
- `status == 204`, meaning the callback ran and changed nothing. Skip callbacks with no outputs, such as hosted mode's `mirror_stores`, which always return 204.

It prints a per-action table, and `run.py` includes the flags in its summary.

### `measure.py`

```python
class ActionRecorder:
    def __init__(self, page: Page, server: ServerInfo): ...
    def measure(self, label: str, action: Callable[[Page], None], repeats: int = 5) -> ActionResult: ...

@dataclass
class ActionResult:
    label: str
    requests: int            # _dash-update-component requests
    up_kb: float             # request bodies
    down_kb: float           # response bodies
    server_ms: float         # sum of trace "ms" for this action
    settle_ms: float         # action start → quiet
    long_task_ms: float      # sum of long tasks (>50 ms) during the action
    heap_mb: float           # performance.memory.usedJSHeapSize after the action
```

How each value is measured:

- **Requests and bytes:** `page.on("request")` / `page.on("response")`, filtered to `_dash-update-component`.
- **Long tasks:** collected by a `PerformanceObserver({type: "longtask", buffered: true})` installed with `page.add_init_script`.
- **Settle:** no Dash request in flight for 500 ms *and* `document.title` isn't `"Updating..."`.
- **Repeats:** the reported value is the median of `repeats` runs, all in headless Chromium.

### `actions.py`

Single actions:

| Name | What it does |
|---|---|
| `page_load` | load the page |
| `next` | click Next |
| `tick` | tick a checkbox |
| `type_text` | type 20 characters into a text field |
| `add_span` | select text and add a span (`realistic` only) |
| `selector_search` | open the selector and type a 3-character query |

Journeys:

| Name | What it does |
|---|---|
| `annotate_next_20` | tick and click Next, 20 times |
| `jump_selector` | 10 random selector jumps |
| `flag_then_filter` | flag 5 documents, then filter to flagged |
| `reload_resume` | annotate, reload the page, check the values survived, annotate again, check the file |
| `rapid_clicks` | 10 Next clicks without waiting |

`reload_resume` fails today because of the refresh bug above, which makes it a real check, not only a timing.

### `bench_server.py`

Runs without a browser. For each size, it times:

- `TaterApp.load_documents` + `set_annotation_widgets` (startup)
- `_save_stores_to_file` with a filled project, along with the resulting file size
- RSS after startup

In hosted mode it measures RSS growth per `_build_session_app_from_data` call, for 1, 5 and 20 sessions.

### `run.py`

```bash
uv run python -m perf.run --sizes 50,500,2500,10000 --lengths short,medium,long \
    --schema checkbox,realistic --filled both --repeats 5 --out perf/results/
```

It writes `perf/results/<date>-<git-sha>.csv`, with one row per (size, length, schema, filled, action), plus a Markdown summary.

The summary lists, for each action:

- the 10k value
- the ratio of the 10k value to the 500 value. A ratio well above 1 means the cost grows with N, which is the signal to investigate.
- the trace flags

## Phase 1 — Baseline and ranking

1. Run the full matrix on `dev` and commit the summary as `perf/results/baseline.md`.
2. Rank each cost by its 10k value × how often the action happens. Use these frequency weights:
   - Next, tick and typing: ×1000
   - selector, span and flag actions: ×100
   - reload: ×10
   - page load, startup and finish: ×1
3. Drop anything under 100 ms at 10k.
4. Update the Phase 2 order below to match, in this file.

## Phase 2 — Fixes (provisional order)

### 2.1 Server mirror, per-request layout, atomic saves — do first

These fix the refresh bug above and are the base that 2.4 builds on, so they come first whatever the perf numbers say. They don't need a separate bugfix PR, since there are no real users yet. The fix for two open tabs is the per-document saves in 2.4: tabs then conflict only on a document both edited. A guard against stale tabs (refusing saves from an older tab) is deliberately left out.

- **Keep the in-memory state current.** Keep a plain-dict mirror on `TaterApp`, `self._ann_data` / `self._meta_data`, initialised from `self.annotations` / `self.metadata` after loading. Until 2.4 lands, `_save_stores_to_file` updates the mirror from the full stores as well as writing the file. In hosted mode, add a lightweight `mirror_stores` callback with the same inputs as `auto_save` that only updates the mirror (no file). That keeps refresh correct there too. Both switch to `save-delta` in 2.4.
- **Build the layout per request.** `set_annotation_widgets` assigns `self.app.layout = lambda: layout.build_layout(self)`, and `build_layout` reads the two stores from the mirror. Without this, 2.4 alone still loses work: after a refresh the browser holds startup values, and the first delta for a document overwrites the saved version.
- **Atomic writes.** Both save methods write `path.with_name(path.name + ".tmp")` and then `os.replace(tmp, path)`.
- **Tests.**
  - A unit test: save, fetch `/_dash-layout`, and assert the store reflects the save.
  - A browser test in `TestSaveRestore`: annotate, refresh, annotate another doc, and assert both are in the file.

### 2.2 Cheap fixes

- **Selector limit.** Set `limit=200` on `document-select` (`layout.py`). Mantine passes `limit` to a custom `filter`, so `docFilter` (`assets/utils.js`) must slice its result to `limit`. Keep the exact-position match first.
- **Fewer saves.** Use the trace to confirm `auto_save` fires twice per tick. After 2.4 this mostly goes away. If not, skip the write when the serialized delta equals the last one written for that doc.
- **Progress badge.** If `updateStatusBadges` shows up in long tasks at 10k, keep running counts in `window._taterStatusCounts`, adjusted by the per-doc status change instead of a full recount.
- **Finish actions.** `handle_finish` / `go_to_first_incomplete` scans are expected to be dropped (rare actions). Keep them only if they measure above threshold.

### 2.3 Current-document slice

A new clientside store holds only the current document's data:

```python
dcc.Store(id="current-doc-slice", data=None)
# {"doc_id": str, "annotations": {...}, "metadata": {...}}
```

- **Filling it.** It's filled by a clientside callback `buildCurrentDocSlice`, with inputs `current-doc-id`, `annotations-store` and `metadata-store`. It returns `no_update` when the slice's JSON hasn't changed. That's the only reader of the full stores, and it runs in the browser. It updates in the browser as soon as its inputs change, so it's current by the time the user's next action reaches a server callback. Check this ordering explicitly in the `rapid_clicks` journey.
- **Moving server callbacks onto it.** Each callback below drops its full-store `State`/`Input` and takes `current-doc-slice` instead. Writes to `metadata-store` use `Patch()`, for example `p = Patch(); p[doc_id]["status"] = s`. The arguments to the `*_impl` functions change from full dicts to the slice.

| Callback | Change |
|---|---|
| `update_status_from_annotations` | `Input("current-doc-slice")`; Patch `metadata[doc_id]` |
| `load_flag_and_notes`, `save_flag`, `save_notes`, `toggle_pause`, `on_save_click` | `State("current-doc-slice")`; Patch |
| HL load/save (4), `update_repeater`, `_update_nested_items` | `State("current-doc-slice")` |
| `on_doc_change` | `Input("current-doc-slice")` instead of `current-doc-id`. Skip when `slice.doc_id` equals the last one seen in `timing-store`, so it only runs on navigation. Handles the **arriving** document. |
| `navigate_*`, `go_to_first_incomplete` | `State("current-doc-slice")`. Handle only the **departing** document: accumulate time, set visited, set complete/in_progress, Patch `metadata[departing]`. Arriving-doc setup moves entirely into `on_doc_change`, which removes the `_nav_init` handshake between them. |
| `handle_finish` | Needs all statuses. Add `status-counts-store`, filled clientside from the running counts in 2.2, plus the slice. |
| `download_annotations` | Unchanged: rare, and needs everything. Could serve from the server mirror with `dcc.send_string` instead, so nothing is uploaded. |

- **Semantics to preserve.** Do this one callback group at a time, re-running the harness after each. The existing browser tests cover what has to keep working:
  - status transitions
  - flag/notes persistence
  - auto-advance
  - timing

### 2.4 Save deltas

A new store `save-delta` carries only what changed:

```json
{"seq": 17, "docs": {"doc_00042": {"annotations": {...}, "metadata": {...}}}}
```

- **Building it.** A clientside callback `emitSaveDelta` builds it, with inputs `annotations-store` and `metadata-store`, and `State("current-doc-id")`. It compares only the current document and the previously current one (the only two any action can change), against `window._taterLastSent[doc_id]` JSON strings. It emits the docs that differ, or `no_update`.
- **`auto_save`.** Becomes `Input("save-delta")` only. It merges `docs` into the mirror (2.1) and writes the file from the mirror. The file write is still O(N) and is addressed in 2.5 only if it measures above threshold.
- **Hosted mode.** `mirror_stores` from 2.1 also switches to `save-delta`, and still doesn't write a file.
- **Ordering.** Dash may run two `auto_save` requests concurrently. Ignore a delta whose `seq` is ≤ the last applied one for each doc. Keep `seq` per doc in the mirror.

### 2.5 Conditional: cheaper persistence

Only do this if, after 2.4, saving at 10k (realistic, filled) is above threshold.

- **First option: debounce.** Write at most once per 2 s from the mirror, and flush on shutdown with `atexit`. The annotations file format doesn't change.
- **Only if debouncing isn't enough:** an SQLite sidecar holding one row per document, with the JSON file exported on demand and at shutdown. This changes what users see on disk, so it needs agreement first.

### 2.6 Conditional: long documents

Only do this if the `medium` / `long` lengths show transfer or long tasks above threshold.

- `document-text-store` becomes a small LRU cache, kept clientside, of `{doc_id: text}` for documents already visited. `update_document` skips sending text the client already has; the client sends the ids it holds in a `State`.
- Prefetch the next document's text after navigation settles.
- Virtualizing `renderDocumentSpans` stays out of scope unless long tasks make it the top cost.

### 2.7 Conditional: page load

If the initial payload at 10k (realistic, filled) is above threshold, don't fill `annotations-store` / `metadata-store` in the layout. Fill them from a one-shot callback after first render, or stream them in chunks. This is the least-defined item. Decide after Phase 1.

## Phase 3 — Regression guards

- **Byte bounds in `TestLargeDocumentSet`** (`tests/test_browser.py`). The existing `fetch` wrapper also records `arguments[1].body.length`. Assert the upload per Next and per tick against bounds set from the post-2.4 numbers, roughly 20 KB per Next and 10 KB per tick at 2,500. Keep the request-count bounds.
- **A 10k variant** of the same class, marked `@pytest.mark.perf`. Register the marker in `pyproject.toml`, and exclude it by default with `addopts = "-m 'not perf'"`.
- **A save-time ceiling** in a fast unit test using `perf.synthetic`: 10k checkbox docs, filled, save under a fixed budget.
- **`CLAUDE.md` updates** as fixes land:
  - the Persistence section (mirror, deltas, per-request layout)
  - the Performance rules
  - the `allow_duplicate` list, for any new store outputs

## Hosted mode (after single mode)

- `perf/server.py` with `hosted=True` creates sessions by posting through the examples tab, or calls `_build_session_app_from_data` in-process for memory-only runs.
- **Load:** run the single-mode actions, then 5 and 20 concurrent sessions driven by Playwright contexts, which are isolated cookies. Report p50 and p95 settle time.
- **Memory:** RSS per session × N from `bench_server.py`. If it's significant, share `Document` objects between sessions created from the same built-in example. Uploaded projects stay per session.
- 2.3 and 2.4 apply to hosted mode automatically, since the callbacks are shared.

## Open questions

- **Thresholds.** 100 ms at 10k and the frequency weights in Phase 1 are a starting point. Adjust them after seeing the baseline.
- **Trace and #109.** Does the callback trace stay a hidden debug flag, or get documented for users? #109's agents will read it either way.
