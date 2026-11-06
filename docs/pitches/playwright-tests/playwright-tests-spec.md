# Playwright browser tests — spec

Implements [the pitch](playwright-tests-pitch.md) for [#113](https://github.com/text-harvest/tater/issues/113). Three steps, in order: shared helpers plus the two new test groups, the port of the existing tests, then Selenium's removal. Each step leaves the suite green.

## Decisions on the pitch's open questions

- **Where the server runs.** Single-mode tests run tater in a thread inside the pytest process, as `dash_duo` does now, so `read_saved` can still call `TaterApp.flush_saves()` and each test can build its own `TaterApp` in Python. Hosted-mode tests run `tater --hosted` as a subprocess with `perf.server.run_tater(hosted=True)`, because the hosted app (session cache, `serve_layout`, upload callbacks) is built inside `runner.run_hosted` and only reachable through the CLI. One hosted server per test module; each test opens its own browser contexts, so sessions don't mix.
- **Plugin or own fixtures.** Use `pytest-playwright`. Its session-scoped `browser` fixture and per-test `context` / `page` give the "one browser, fresh page" speed-up for free, and `--tracing retain-on-failure` writes replayable traces of failed tests to `test-results/`. It doesn't touch the perf harness, which keeps launching its own browser with `sync_playwright()`.
- **Test files.** All browser tests stay in `tests/test_browser.py`, so the documented commands (`--ignore=tests/test_browser.py` for the fast run, `tests/test_browser.py --headless` for the browser run) keep working unchanged. New groups go in as new sections of that file. If it gets unwieldy, splitting into `tests/browser/` is a later change.

## Shared helpers: `perf/browser.py` (new)

Moved, not rewritten, from `perf/actions.py` and `perf/measure.py`. `perf/actions.py`, `perf/measure.py` and `perf/hosted_check.py` (until it's deleted) import from here. The harness's commands, CSV columns and baseline don't change.

| Helper | From | Notes |
|---|---|---|
| `INIT_SCRIPT` | `measure.py` | Request/byte/long-task counters installed with `context.add_init_script`. |
| `position(page)`, `wait_position(page, k)`, `wait_loaded(page)` | `actions.py` | Unchanged. |
| `control(page, tf)` | `actions.py` | Unchanged. |
| `selector_options(page)` | `actions.py` (`_selector_options`) | Made public. |
| `goto_doc(page, k)` | `actions.py` | Unchanged. |
| `dash_counts(page) -> dict` | `ActionRecorder._dash` | `{requests, up, down, inFlight, lastDone, longTaskEnd, title}`. |
| `reset_counts(page)` | inline in `ActionRecorder.run_once` | Calls `window.__taterDashReset()`. |
| `wait_quiet(page, quiet=0.5, timeout=120)` | `ActionRecorder.wait_quiet` | Becomes a function; `ActionRecorder.wait_quiet` calls it. |

`perf/__init__.py` already makes `perf` importable from tests (`pythonpath = ["."]`). `perf/` stays out of the wheel.

## Test fixtures: `tests/conftest.py` and `tests/test_browser.py`

- `--headless` is registered in `conftest.py` as an accepted, ignored option (`pytest_addoption`), since pytest-playwright is headless by default and `dash[testing]`, which defines it today, is removed in step 3. `--headed` (from the plugin) shows the browser.
- `browser_context_args` (plugin hook fixture) sets the viewport to 1400×1000, as the harness does, so the sticky footer doesn't cover controls.
- `context` is overridden to add `INIT_SCRIPT` to every page, so every test can count requests and call `wait_quiet`.
- `serve(tater_app) -> str` (fixture factory): starts `werkzeug.serving.make_server("127.0.0.1", 0, tater_app.app.server, threaded=True)` on a daemon thread and returns its URL. Teardown calls `tater_app.flush_saves()` (as the current fixtures do), then `server.shutdown()`.
- `open_app(page, serve, tater_app)` / a small `App` helper: `page.goto(url)`, `wait_loaded`, `wait_quiet`. Tests start with `page = open_app(tater)` instead of `dash_duo.start_server(...)` + `wait_for_text_to_equal`.
- `read_saved(tater)` stays as is.
- `errors` fixture: collects `pageerror`, console errors (minus the iconify CDN noise, `_cdn_noise` from `hosted_check.py`) and callback responses with status ≥ 400. The new tests assert it's empty at the end; ported tests don't, to keep their assertions identical.

## Step 1: new tests

### 1a. Every widget survives a reload — `TestWidgetRoundTrip`

One `TaterApp` built in Python with model `AllWidgets` and explicit widgets, three short documents. Widgets and the value each gets on document 1:

| Field | Widget | Fill | Expected saved value |
|---|---|---|---|
| `radio` | `RadioGroupWidget` | click option `b` | `"b"` |
| `segmented` | `SegmentedControlWidget` | click `b` | `"b"` |
| `chip_radio` | `ChipRadioWidget` | click `b` | `"b"` |
| `select` | `SelectWidget` | open, pick `b` | `"b"` |
| `multi_select` | `MultiSelectWidget` | pick `a`, `c` | `["a", "c"]` |
| `checkbox_group` | `CheckboxGroupWidget` | tick `a`, `c` | `["a", "c"]` |
| `checkbox` | `CheckboxWidget` | tick | `true` |
| `switch` | `SwitchWidget` | toggle | `true` |
| `chip` | `ChipWidget` | toggle | `true` |
| `number` | `NumberInputWidget` | type `7` | `7` |
| `slider` | `SliderWidget` | keyboard: focus thumb, `ArrowRight` ×3 | min + 3·step |
| `range_slider` | `RangeSliderWidget` | keyboard on the upper thumb, `ArrowLeft` ×2 | `[min, max − 2·step]` |
| `text` | `TextInputWidget` | type `hello` | `"hello"` |
| `textarea` | `TextAreaWidget` | type `two words` | `"two words"` |
| `spans` | `SpanAnnotationWidget` (top level) | select a word in the document, click the tag button | one span with that word's offsets |
| `hl_one` | `HierarchicalLabelSelectWidget` | pick a leaf two levels down | that path |
| `hl_many` | `HierarchicalLabelMultiWidget` | pick two leaves | both paths |
| `items` | `ListableWidget` of `Item` | add two items | two items |
| `items[i].kind` | radio inside the repeater | `x` in item 0, `y` in item 1 | per item |
| `items[i].evidence` | `SpanAnnotationWidget` inside the repeater | one span in item 1 | per item |
| `items[i].parts` | nested `ListableWidget` of `Part` | one part in item 0 | `[{"note": "p"}]` |
| `items[i].parts[j].note` | `TextInputWidget` in the nested repeater | type `p` | `"p"` |

One conditional field (`reason`, shown when `radio == "c"`) isn't filled; it guards against conditional wrappers hiding filled widgets after a reload. The hierarchy is a small inline dict, like `perf.synthetic._SITES`.

Each widget gets a fill function and a read function (the value as the page shows it: checked state, input value, chip/pill labels, highlighted span text, item count). The tests:

1. `test_values_saved` — fill everything on document 1, `wait_quiet`, `read_saved` equals the expected annotations.
2. `test_values_survive_next_prev` — fill, Next, check document 2 shows empty values, Prev, every read function returns its filled value.
3. `test_values_survive_reload` — fill, reload, every read function returns its filled value; then Next, Prev, and the same again.
4. `test_reload_then_edit_keeps_file` — fill, reload, change one field, `read_saved` still has every other value (the #108 stale-layout overwrite, for every widget at once).

Failures name the widget: each test collects mismatches into a dict and asserts it's empty, so one run reports every broken widget rather than the first.

### 1b. Hosted mode — `TestHosted`

Port of `perf/hosted_check.py`, parametrized over every built-in example (the folders in `tater/examples/`, found at collection time, so a new example is tested automatically). The script covered only `gallery`, `repeater` and `hierarchical`; `edit()` already skips edit kinds an example doesn't have. `Session` (one browser context, so one cookie) and `edit()` move into `test_browser.py` nearly unchanged; `Session` takes the pytest-playwright `browser`. A module-scoped `hosted_server` fixture wraps `run_tater(tmp, hosted=True)` and prints the end of `server.log` on failure.

Each check in the script becomes its own test so failures are reported separately:

- `test_edits_apply`, `test_reload_keeps_edits`, `test_next_doc_is_clean`, `test_next_prev_keeps_edits`
- `test_second_session_starts_clean`, `test_sessions_dont_mix` (B's edits don't reach A, and B keeps its own)
- every test asserts no page errors or failed callbacks

For `span`, `edit()` also adds one span (the selection code from `perf.actions.add_span`, moved to `perf/browser.py` as `select_word(page, k)`), and `state()` counts `#document-content mark`.

After these pass, delete `perf/hosted_check.py` and its CLAUDE.md lines.

## Step 2: port the existing tests

Group by group, in file order: `TestNavigation`, `TestDocumentSelect`, `TestLargeDocumentSet` (+10k), `TestFlagAndNotes`, `TestAnnotationPersistence`, `TestAutoAdvance`, `TestSaveRestore`. Each test keeps its assertions. Mechanical mapping:

| dash_duo / Selenium | Playwright |
|---|---|
| `dash_duo.start_server(app)` + `wait_for_text_to_equal("#document-title", "1 / 3")` | `page = open_app(tater)`, then `expect(title).to_have_text("1 / 3")` |
| `wait_for_text_to_equal(sel, t)` | `expect(page.locator(sel)).to_have_text(t)` |
| `wait_for_contains_text(sel, t)` | `expect(...).to_contain_text(t)` |
| `js_click(dash_duo, sel)`, `execute_script("arguments[0].click()")` | `page.click(sel)`; radios via `page.check(...)` |
| `wait_for_element("input[value='positive']:checked")` | `expect(...).to_be_checked()` |
| `find_element(sel).text` | `page.locator(sel).inner_text()` |
| `btn.get_attribute("disabled") ... or data-disabled` | `expect(btn).to_be_disabled()`, or the same `disabled`/`data-disabled` attribute check if Mantine only sets the latter |
| `send_keys` on notes | `fill` |
| `select_input_value` polling | `expect(select).to_have_value("1. Doc One")` |
| `search_document_select` | click, `fill(text)`, read `selector_options(page)` after `wait_quiet` |
| `time.sleep(...)  # wait for auto_save` before `read_saved` | `wait_quiet(page)`, then `read_saved` (which flushes) |
| `driver.refresh()` | `page.reload()` + `wait_loaded` + `wait_quiet` |
| `is_selected()` | `is_checked()` |

`TestLargeDocumentSet` drops its own `_COUNT_CALLBACK_REQUESTS` script and `_wait_for_quiet` and uses `INIT_SCRIPT` through `reset_counts` / `wait_quiet(page, quiet=1.0)` / `dash_counts`. The bounds stay the same numbers. Two measurement differences, both small and noted in the test's docstring: bytes up are UTF-8 bytes rather than string length (the same for this ASCII payload), and the 2 s cascade bound is measured to the last response finishing (`lastDone`) rather than the last request being sent, which is slightly stricter.

`test_status_goes_complete_on_departure_with_required_field_filled` replaces its `time.sleep(0.5)` for `on_doc_change` with `wait_quiet`, which waits for that callback.

`js_click` and `select_input_value` are deleted once nothing uses them.

## Step 3: remove Selenium

- `pyproject.toml` `[dependency-groups] dev`: remove `dash[testing]` and `webdriver-manager`; add `pytest>=8.0` (previously pulled in by `dash[testing]`) and `pytest-playwright`. Done with `uv remove --dev` / `uv add --dev`, so `uv.lock` follows.
- `tests/conftest.py`: delete `_cached_chromedriver` and `pytest_setup_options`.
- `README.md` testing section: replace the Chrome/WSL/ChromeDriver instructions with `uv run playwright install chromium` once, then the same three pytest commands. Mention `--headed` and `--tracing retain-on-failure`.
- `CLAUDE.md`: update the Tests section (no Chrome, no `webdriver-manager`, `dash[testing]` gone), the test-file list (`test_browser.py` covers hosted mode and the widget round-trip), and the perf section (no `perf.hosted_check`).
- `.gitignore`: add `test-results/`.

## Done when

- `uv run pytest tests/ --headless` passes with only Playwright installed (no Chrome, no ChromeDriver), including in a Claude Code sandbox.
- `uv run pytest tests/test_browser.py --headless -m perf` passes.
- `uv run python -m perf.run --sizes 500 --schema checkbox --repeats 1` still runs and writes results in the same columns.
- The browser suite takes no longer than it does today on `dev` (time both on the same machine).
- No `selenium`, `dash.testing` or `webdriver_manager` import remains.
