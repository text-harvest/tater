# Tater — Developer Notes for Claude

## Project overview

Tater is a Python library for building document annotation UIs. Users provide a config file
(Python or JSON) defining a Pydantic schema and optional widget overrides, then run the `tater`
CLI to launch a Dash web app.

Key stack: Python 3.10+, Dash, **Dash Mantine Components (DMC) v2.6 / Mantine v7**, Pydantic v2.

DMC LLM-friendly documentation can be found [here](https://www.dash-mantine-components.com/assets/llms.txt).

## Directory layout

```
tater/                  # Library package
  __init__.py           # Public API: SpanAnnotation, SpanAnnotationWidget,
                        #   EntityType, load_schema, parse_schema, widgets_from_model,
                        #   annotate (Jupyter one-liner — wraps TaterApp.run with jupyter_mode)
  models/               # Pydantic data models (Document, SpanAnnotation)
  loaders/              # Schema and document loaders
    model_loader.py     # WIDGET_CLASS, DEFAULT_WIDGET, widgets_from_model,
                        #   _widget_from_field_type, _humanize
    json_loader.py      # JSON schema → (Pydantic model, partial widget list)
    document_loader.py  # load_documents(path) — dispatches on extension;
                        #   _load_tabular accepts Path or file-like (StringIO/BytesIO)
  ui/                   # App machinery (TaterApp, layout, callbacks, value_helpers)
    upload_layout.py    # Hosted-mode upload page layout + callbacks;
                        #   also contains _LLM_PROMPT constant and _build_llm_prompt_modal()
    schema_builder.py   # No-code schema builder modal for hosted mode
  examples/             # Built-in example sets for hosted mode "Browse examples" tab
    simple/             # meta.json + schema.json + documents.json
    gallery/            # meta.json + schema.json + documents.json
    hierarchical/       # meta.json + schema.json + documents.json + pet_ontology.yaml
    coarse_breast_label/ # meta.json + schema.json + documents.json + breast_fdx_ontology.yaml
  widgets/              # All widget classes
    base.py             # Widget base class hierarchy (see Widget conventions)
    repeater.py         # RepeaterWidget (abstract), ListableWidget, TabsWidget
    hierarchical_label.py  # HierarchicalLabel* widgets + Node tree utilities
    ...                 # One file per concrete widget (see Widget conventions)
apps/
  examples/
    config/             # Python config-file examples (simple, hooks, span, span_in_list, …)
    schema/             # JSON schema-file examples
    data/               # Sample documents and ontologies (e.g. pet_ontology.yaml)
    notebooks/          # Jupyter notebook examples (simple_annotation.ipynb)
spec/                   # Design documents (see below)
```

## Running examples

Apps are run via the `tater` CLI, which requires either `--config` (Python) or `--schema` (JSON):

```bash
tater --config apps/examples/config/simple.py --documents data/documents.json
tater --config apps/examples/config/hooks.py  --documents data/documents.json
tater --schema apps/examples/schema/simple.json --documents data/documents.json
```

Hosted mode (upload page at `/`, annotation UI at `/annotate`):

```bash
tater --hosted [--port 8050] [--host 0.0.0.0]
```

CLI flags: `--documents` (required in single mode), `--config` or `--schema` (one required in single mode),
`--annotations`, `--no-restore`, `--port`, `--host`, `--debug`, `--hosted`
(also via `TATER_APP_PORT` / `TATER_APP_HOST` / `TATER_APP_DEBUG` env vars).

Notebook examples (`apps/examples/notebooks/`) use `tater.annotate()` with `jupyter_mode="inline"`
or `"tab"`. Install notebook extras with `uv sync --extra notebook`. Run `uv run nbstripout --install`
once per clone to keep notebooks clean in git (`.gitattributes` configures the filter; it strips
outputs, execution counts, and kernel metadata on `git add`).

## Architecture

- **Pydantic-first**: options for choice widgets are inferred from `Literal` types at
  `bind_schema()` time; no manual option lists needed.
- **Widget binding**: each widget has a `schema_field` (dot-path into the model) and a
  `component_id` derived from it. `bind_schema(model)` is called by TaterApp to validate and
  extract metadata.
- **Loader design**: `model_loader.py` is the primary path — `widgets_from_model(model)`
  auto-generates widgets from Pydantic type hints. `json_loader.py` parses a JSON schema into
  a Pydantic model and a *partial* widget list (only fields with a `widget` block). `runner.py`
  calls `widgets_from_model(model, overrides=widgets)` to fill the gaps — the same flow used
  by the Python config path.
- **Callbacks**: each widget registers its own Dash callbacks in `register_callbacks(app)`.
  `tater/ui/callbacks/` handles navigation, document loading, metadata (flag/notes/status),
  and value capture. All are split across `core.py`, `helpers.py`, `span.py`, `repeater.py`,
  and `hierarchical_label.py`.
- **Document rendering**: `update_document` (server) loads raw text and writes it to
  `document-text-store`. The JS `renderDocumentSpans` fires on that store change (and on
  `span-any-change`) to render annotated text clientside — no server round-trip for rendering.
- **Persistence**: annotation and metadata state lives in `dcc.Store` components
  (`annotations-store`, `metadata-store`) in the browser. All mutations are clientside. The
  `auto_save` server callback fires on store changes and calls `TaterApp._save_stores_to_file()`
  to persist to disk. `auto_save` is not registered in hosted mode (`annotations_path` is
  `None`); annotations live in the browser and the user downloads them explicitly.
  Format: `{doc_id: {annotations: {...}, metadata: {...}}}`.
- **value_helpers**: `get_model_value` / `set_model_value` in `tater/ui/value_helpers.py`
  handle dot-path reads/writes into nested Pydantic model instances.
- **Flag/notes loading**: `load_flag_and_notes` in `callbacks/core.py` fires on `current-doc-id`
  change and populates both `flag-document` (checked) and `document-notes` (value) from
  `metadata-store`. This is the only callback that writes to these outputs on navigation,
  and it returns `no_update` for a control that already shows the right value. Setting a
  control re-fires `save_flag` / `save_notes`, so those also return `no_update` when the value
  equals what is already stored — otherwise every navigation would write `metadata-store`
  and trigger an auto-save.
- **Document selector**: the footer `document-select` (`dmc.Select`) is fully clientside —
  `buildDocOptions` builds its options from `doc-list-store` + `metadata-store` + `filter-store`
  and returns `no_update` unless a status, flag or the filter changed; `docRenderOption` /
  `docFilter` (in `assets/utils.js`) draw the status badge/flag and handle search (exact
  position first, then name/id/info substring). A user pick goes through `docSelectChanged` →
  `doc-select-nav` store → server `navigate_select`. Don't reintroduce per-document components
  with pattern-matching IDs here: at ~2,500 docs they froze the UI for seconds per action (#107).

## Hosted mode

`--hosted` launches a multi-user server. The Dash app is shared; per-user state is isolated
via Flask session cookies and a server-side `_session_cache` dict.

**Upload page:** two tabs — "Set up" and "Browse examples".
- *Set up*: schema JSON (or use one of the schema authoring tools — **Build schema**
  opens the no-code schema builder modal; **Design with AI** opens a modal with a copyable
  LLM prompt the user pastes into Claude/ChatGPT, then pastes the resulting JSON back) +
  documents (JSON, CSV, TSV, or Excel) + optional existing annotations JSON.
  If the schema has file-path `hierarchies` references, per-file ontology upload zones appear
  automatically. Each zone has a status icon (grey outline → filled blue check on success).
  Tabular documents are parsed via `_parse_tabular_upload` (in `upload_layout.py`), which
  decodes the base64 upload contents, creates a StringIO/BytesIO buffer, calls
  `document_loader._load_tabular`, and normalises results to a list of dicts before storing
  in `documents-store`.
  **Design with AI flow:** `_LLM_PROMPT` (module-level constant in `upload_layout.py`) is
  copied via `dmc.CopyButton`. When the user pastes the schema JSON and clicks Apply,
  `apply_llm_schema` validates it with `_validate_schema_json`, writes to `schema-store`
  and `pending-hierarchies` (both `allow_duplicate=True`), and closes the modal.
- *Browse examples*: clickable cards for built-in example sets in `tater/examples/`. Clicking
  a card immediately creates a session and redirects — no submit button needed.

**Session flow (upload tab):** user uploads (or builds) schema + documents (+ optional
ontology files + optional annotations) → all data held as Python objects in memory → a UUID
`session_id` is stored in `flask.session` → `_session_cache[session_id]` holds the
`TaterApp` instance → redirect to `/annotate` → `serve_layout()` looks up the session cache
and returns the annotation layout. No temp files are written.

**Session cache:** `_session_cache` is an `OrderedDict` in `runner.py` mapping
`session_id → TaterApp`. Bounded by `TATER_SESSION_CACHE_MAX` (env var, default `100`);
when the limit is exceeded, the oldest entry is evicted via `popitem(last=False)`.
`flask.session` stores only `{"session_id": session_id}` — a UUID string — to stay under
the cookie size limit.

**`_build_session_app_from_data`:** module-level function in `runner.py` that builds a
`TaterApp` entirely from in-memory data: `(dash_app, schema_data, docs_data,
hierarchy_files, annotations_data, base_dir)`. Hierarchy files are passed as decoded YAML
content strings, parsed with `yaml.safe_load`, and injected inline into the schema dict as
`hierarchies[ref_name] = parsed_dict` before `parse_schema` is called.

**Session flow (examples tab):** user clicks a card → `load_example` callback reads the
example's files directly from `tater/examples/<name>/`, passes `base_dir=str(example_dir)`
to `parse_schema` for native path resolution, creates session, redirects.

**Adding a built-in example:** create a subfolder under `tater/examples/` with at minimum
`meta.json` (`name`, `description`, `order`), `schema.json`, and `documents.json`. Ontology
YAML files referenced in the schema should be placed alongside and referenced by filename only
(not relative path). The example is discovered automatically at layout-build time.

**Annotations preload in hosted mode:** if an annotations file was uploaded,
`_build_session_app_from_data` calls `TaterApp._load_annotations_from_dict(data)` directly
(no file read), so no auto-save path is set and no disk writes occur.

**Ontology files in hosted mode:** uploaded YAML files are base64-decoded to content strings,
parsed inline with `yaml.safe_load`, and injected directly into the schema dict under
`hierarchies[ref_name]`. No temp files are written and no path rewriting is needed.

**Always-register callbacks:** span, repeater, nested-repeater, hierarchical-label-select, and
hierarchical-label-multi callbacks are registered once at server startup (not per-session).
They use a `_ta()` runtime resolver — `app._tater_get_current_app` is a function stored on
the Dash app that looks up the calling user's `TaterApp` from `_session_cache` via
`flask.session` at callback invocation time. This avoids re-registering callbacks for each
upload session (Dash only allows each output to be registered once).

**`_tater_app` vs `_tater_get_current_app`:** two different mechanisms are used to give
callbacks access to the right `TaterApp` instance, depending on mode:
- *Single mode*: `TaterApp.set_annotation_widgets` stores `self` directly on the Dash app as
  `app._tater_app`. Callbacks capture it via closure at registration time — safe because there
  is only one `TaterApp` for the lifetime of the process.
- *Hosted mode*: the Dash app is shared across sessions, so a single `_tater_app` reference
  would always point to the last session's app. Instead, `runner.py` stores a callable on the
  Dash app as `app._tater_get_current_app`. This callable does a per-request lookup:
  `flask.session["tater_session"]["session_id"]` → `_session_cache[session_id]`. Callbacks
  that must be session-aware capture this callable at registration time and call it inside the
  callback body (i.e. at request time, not at registration time).

**Relay store pattern:** Dash prohibits mixing MATCH dict-ID outputs with static string
outputs in the same callback (e.g. `{"type": "span-trigger", "field": MATCH}` + `"annotations-store"`).
The reason is that MATCH callbacks fire once per matched component instance, while a static
output is a single component — Dash cannot fan-in multiple MATCH firings into one static write
within a single callback. The solution used throughout: embed the annotation update in the
MATCH relay store data, then a separate ALL-input relay callback reads from all relay stores
and writes to `annotations-store`. Simple (non-MATCH) widgets write directly to
`annotations-store` and do not need a relay store.
Widgets that use this pattern each include a relay store in their rendered output:
- Repeater: `{"type": "repeater-ann-relay", "field": pipe_field}`
- Nested repeater: `{"type": "nested-repeater-ann-relay", "ld": ld, "li": li}`
- HierarchicalLabelSelect: `{"type": "hl-select-relay", "field": pipe_field}`
- Span: span-trigger store data carries `{"count": N, "annotations_update": {...}}`

## DMC version constraints

DMC is pinned at **v2.6 (Mantine v7)**. Before using a DMC component, verify it exists in
this version:

- `dmc.TabsTab` is the tab trigger (v2.x API) — `dmc.Tab` does not exist.
- `dmc.Tabs` uses `value` (not `defaultValue`) for the initially active tab.
- `dmc.Badge(circle=True)` clips double-digit numbers — avoid `circle=True`.
- `dmc.ColorSchemeToggle` handles dark/light toggling and persists the choice in `localStorage`.
  Both pages use `defaultColorScheme="auto"` on their `dmc.MantineProvider`; the toggle is
  consistent across pages without server-side coordination. There is no `theme` parameter on
  `TaterApp` or in config files.
- Component prop names follow Mantine v7 conventions (e.g. `leftSection`/`rightSection`, not
  `icon`).

## Dash callback gotchas

**Pattern-matching phantom fires**: when a callback uses `Input({...}, ALL)` pattern matching,
Dash re-fires the callback when matching components are re-rendered (e.g. after another callback
updates the component tree). Guard against this by checking that the triggered value is non-zero:

```python
if not ctx.triggered or not ctx.triggered[0].get("value"):
    return no_update
```

**`allow_duplicate` must be consistent**: if *any* callback uses
`Output(component_id, prop, allow_duplicate=True)`, then *all* callbacks writing to that same
output must also use `allow_duplicate=True`. Missing it on one will cause Dash to raise a
`DuplicateCallback` error at startup. Outputs in this codebase that use `allow_duplicate=True`:

- **`current-doc-id` / `data`** — written by the prev/next buttons, the document selector
  (`navigate_select`), auto-advance and "go to first incomplete". All but the first registered
  use `allow_duplicate=True`; any new navigation callback must too.
  See the comment block on the first such callback in `core.py`.

- **`annotations-store` / `data`** — written by `captureValue`/`captureChecked` (clientside,
  ALL pattern) and by multiple relay callbacks (repeater, nested repeater, HL, HL tags, span).
  All use `allow_duplicate=True`. New callbacks writing to `annotations-store` must also use it.

- **`upload-location` / `href`** — written by both `handle_submit` (upload tab) and
  `load_example` (examples tab) in `upload_layout.py`. Both use `allow_duplicate=True`.

- **Widget value props** (`tater-control` / `value` and `tater-bool-control` / `checked`) —
  `loadValues`/`loadChecked` (ALL pattern, `prevent_initial_call="initial_duplicate"`) and
  `conditionalClear` (MATCH pattern, `allow_duplicate=True`) both write to these props for
  conditional widgets inside repeaters. The ALL callbacks use `prevent_initial_call="initial_duplicate"`
  rather than `allow_duplicate=True`; Dash treats ALL and MATCH pattern callbacks as distinct
  writers for the same component type, so this combination is valid.

**`prevent_initial_call=True` does not suppress pattern-matching fires** caused by component
re-renders — only the very first page load. Use the value guard above instead.

**All clientside callbacks must use named `ClientsideFunction`** — inline JS strings are
prohibited for Dash 4 compatibility. Dash 4 stores inline strings under a SHA-256 hash in
`window.dash_clientside._dashprivate_clientside_funcs`, and they fail at runtime with
`TypeError: Cannot read properties of undefined (reading 'apply')` when combined with
`allow_duplicate=True`. Instead, define all JS functions in `tater/ui/assets/*.js` under
`window.dash_clientside.tater` and reference them via
`ClientsideFunction(namespace="tater", function_name="...")`.

**Conditional visibility uses a single `conditionalVisibilityAll` ALL callback** registered
once in `TaterApp._setup_conditional_visibility_callback`. It uses `ALL` for all three ID keys
(`ld`, `path`, `tf`) so it covers both flat widgets (`ld=""`) and repeater rows (`ld="pets"`,
`path="0"`) in one shot, with `prevent_initial_call=True`.

`render_field` (in `base.py`) wraps every conditional widget in an `html.Div` with:
- `id = conditional_wrapper_id` (`type: tater-cond-wrapper`, same ld/path/tf as the widget)
- `style = {"display": "none"}` for flat widgets; `{"display": "none"}` or `{}` for repeater
  items depending on `_initial_hidden` (set from loaded annotation defaults)
- A child `dcc.Store(id=conditional_config_id, data={"target": ..., "empty": ..., "ctrl_tf": ...})`

The `ctrl_tf` field identifies the controlling widget's `_item_relative_tf`. For widgets inside
a GroupWidget within a repeater (e.g. `_item_relative_tf = "booleans|indoor_location"`), the
group prefix is prepended to the relative condition field name so `ctrl_tf` correctly resolves
to `"booleans|is_indoor"` rather than just `"is_indoor"`.

`conditionalVisibilityAll` in `utils.js` iterates over `ctx.outputs_list` (one per wrapper),
finds each wrapper's config store by matching `tf/ld/path` in `ctx.states_list[0]`, then finds
the controlling widget's current value in `ctx.inputs_list[0]` (tater-control) or
`ctx.inputs_list[1]` (tater-bool-control) by matching `ctrl_tf + ld + path`. Row correlation
via `ld + path` ensures repeater items match only their own row's controls.

`conditionalClear` (clears the widget value when its controlling field hides it) is registered
via MATCH IDs only for widgets inside repeaters. Flat conditionals do not get a clear callback.

## Widget conventions

Widget base class hierarchy in `base.py`:
- `TaterWidget` — abstract root; all widgets inherit from this
- `ControlWidget(TaterWidget)` — leaf widgets that capture a value; adds `required`, `auto_advance`, `value_prop`, `empty_value`
  - `ChoiceWidget` — single `Literal[...]` field; derives `options` from schema
    - `SegmentedControlWidget`, `RadioGroupWidget`, `SelectWidget`, `ChipRadioWidget`
  - `MultiChoiceWidget` — `List[Literal[...]]` field; derives `options` from schema
    - `MultiSelectWidget`, `CheckboxGroupWidget`
  - `BooleanWidget` — `bool` field; `value_prop = "checked"`
    - `CheckboxWidget`, `SwitchWidget`, `ChipWidget`
  - `NumericWidget` — numeric field
    - `NumberInputWidget`, `SliderWidget`, `RangeSliderWidget`
  - `TextWidget` — string field
    - `TextInputWidget`, `TextAreaWidget`
  - `SpanAnnotationWidget` — `List[SpanAnnotation]` field (in `span.py`)
  - `HierarchicalLabelWidget` (abstract base, in `hierarchical_label.py`) — `List[str]` / `Optional[List[str]]` field
    - `HierarchicalLabelSelectWidget` — single-select dropdown (`dmc.Select`); stores one path
    - `HierarchicalLabelMultiWidget` — multi-select dropdown (`dmc.MultiSelect`); stores `List[List[str]]`
- `ContainerWidget(TaterWidget)` — widgets that contain other widgets
  - `GroupWidget` — groups widgets for a nested sub-model (`schema_field` is a dot-path prefix)
  - `RepeaterWidget` (abstract, in `repeater.py`) — manages a `List[ItemModel]` field; subclasses:
    - `ListableWidget` — items as a vertical stack of bordered cards
    - `TabsWidget` — items as switchable tabs
    - `AccordionWidget` — items as collapsible accordion panels
- `DividerWidget` — structural only; no schema field, no value capture

- Constructor signature: `(schema_field, label="", description=None, ...)`.
- `renders_own_label` property: if `True`, the widget renders its own label (skips the outer
  wrapper label in layout). Most widgets return `False`; GroupWidget/RepeaterWidget subclasses return `True`.
- `bind_schema(model)` should raise `TypeError` / `ValueError` with a clear message if the field
  type doesn't match what the widget expects.
- `register_callbacks(app)` captures `self` fields into the closure — don't rely on `self` inside
  callback functions (capture to local variables before the `@app.callback` decorator).
- **Escape-hatch callbacks**: for cross-field rules that can't be expressed as widget declarations,
  assign widgets to named variables and use `widget.component_id` in `Output`/`Input` — avoids
  hard-coding ID strings. See `apps/examples/config/hooks.py` for the pattern. The `register_callbacks(app)` function
  in a config module is the right place for these; it is called after `set_annotation_widgets` so
  all component IDs are finalised.
- `required=True` is **UI-only**: it shows a `*` indicator and drives the `in_progress` /
  `complete` status badge, but does not prevent saving an empty value. This is intentional —
  annotation tools need to support partial saves so annotators can leave fields blank and
  return later. Pydantic-level enforcement would break loading incomplete annotation files.

## HierarchicalLabel specifics

Both `HierarchicalLabelSelectWidget` and `HierarchicalLabelMultiWidget` use `dmc.Select` /
`dmc.MultiSelect` with depth-indented options via the `hlRenderOption` JS function and
custom filtering via `hlFilter`. Both share `_build_dropdown_data` to flatten the
`Node` tree into a list of `{value: '["A","B","C"]', label: "C"}` items where value is the
full path as a compact JSON array (no spaces, matching JS `JSON.stringify` output). The sentinel
config item (`"__config__..."`) encodes `search_show_siblings` and `search_show_children` for
the JS filter.

- `HierarchicalLabelSelectWidget`: stores `Optional[List[str]]` (single path). Callbacks in
  `setup_hl_select_callbacks`: load serializes stored path → compact JSON string for `dmc.Select`;
  save deserializes the JSON string → path and writes via `hl-select-relay`.
- `HierarchicalLabelMultiWidget`: stores `Optional[List[List[str]]]` (list of paths). Callbacks
  in `setup_hl_multi_callbacks`: load serializes each path → compact JSON string; save
  deserializes each string → path list and writes via `hl-multi-relay`.
- `_find_path(root, name)` does a DFS from root returning the full path list to a node (used
  internally by tree utilities).

## What is and isn't implemented

**Implemented:**
- All widgets listed in README
- Manual widget definition (user provides widget list)
- Nested models via GroupWidget (dot-path `schema_field`)
- Repeatable lists via ListableWidget (card stack), TabsWidget (tabs), AccordionWidget (accordion)
- Span annotation, including SpanAnnotationWidget nested inside ListableWidget/TabsWidget
- Hierarchical label (single-select and multi-select dropdown)
- Auto-save, progress tracking, flag/notes, annotation timing
- Conditional visibility (`conditional_on`)
- Full widget suite: SegmentedControlWidget, RadioGroupWidget, SelectWidget, ChipRadioWidget,
  MultiSelectWidget, CheckboxGroupWidget, CheckboxWidget, SwitchWidget, ChipWidget,
  NumberInputWidget, SliderWidget, RangeSliderWidget, TextInputWidget, TextAreaWidget,
  SpanAnnotationWidget, HierarchicalLabelSelectWidget, HierarchicalLabelMultiWidget,
  DividerWidget
- Schema builder — no-code modal in hosted mode; supports all field types except group and
  repeater; fields are reorderable, editable, and deletable; hierarchical label fields accept
  inline YAML; outputs a downloadable JSON schema
- Design with AI — modal in hosted mode with a copyable LLM prompt (`_LLM_PROMPT` in
  `upload_layout.py`); user pastes prompt into Claude/ChatGPT, pastes resulting JSON back,
  clicks Apply; validated by `apply_llm_schema` and stored in `schema-store`
- Hosted mode temp-file-free session management: in-memory data flow, session cache
  (`OrderedDict`) with FIFO eviction via `TATER_SESSION_CACHE_MAX`

## Tests

Tests live in `tests/`. The project is managed with uv (`uv.lock`); `uv run` syncs `.venv`
from the lockfile, including the `dev` dependency group (`dash[testing]`, which brings pytest
and pins selenium `<=4.2.0`), before running. Don't `pip install` into `.venv` — the next sync
reverts it; change dependencies with `uv add` / `uv add --dev`. Run with:

```bash
uv run pytest tests/ --ignore=tests/test_browser.py   # fast, no browser
uv run pytest tests/test_browser.py --headless         # browser tests
uv run pytest tests/ --headless                        # full suite
```

**Test files:**
- `test_value_helpers.py` — `get_model_value` / `set_model_value` and dict variants
- `test_has_value.py` — `_has_value` predicate
- `test_bind_schema.py` — `bind_schema` for all widget types (happy path + error cases)
- `test_component_id.py` — `component_id` and `conditional_wrapper_id` derivation
- `test_decode_field_path.py` — `_decode_field_path` for standalone, single-repeater, and doubly-nested cases
- `test_save_load.py` — `TaterApp` save/load round-trip (no browser): flat fields, nested models, `SpanAnnotation` lists, metadata, schema-mismatch warnings
- `test_widgets_from_model.py` — `widgets_from_model`, `WIDGET_CLASS`, `DEFAULT_WIDGET`; auto-gen for all field types, nested models, overrides
- `test_parse_schema.py` — `parse_schema`, `_build_pydantic_field`, `_build_widget_from_spec`; no-widget-block → absent from list, containers, dividers, conditionals, unknown type errors
- `test_hosted_mode.py` — `_build_session_app_from_data` (happy path, error cases, annotations preload, hierarchy injection), schema builder `_fields_to_schema` → `parse_schema` round-trip for all field types and widget variants, session cache eviction
- `test_browser.py` — `dash.testing` browser tests: navigation, document selector (search, filter, status), flag, notes, annotation persistence, auto-advance, save/restore, and a 2,500-doc check that bounds callback requests per Next click and checkbox tick (#107)

**Browser test setup** requires Google Chrome (`.deb`, not snap) and `webdriver-manager`. The `pytest_setup_options` hook in `conftest.py` auto-installs a matching ChromeDriver via `webdriver-manager` on first run.

**`conftest.py`** defines shared Pydantic model fixtures (`Schema`, `Pet`, `Finding`, `Measurements`, etc.) used across unit tests, and the `pytest_setup_options` hook for browser driver configuration.

## spec/ files

- `spec/tater.md` — Pydantic-first redesign spec; fully implemented including RepeaterWidget.
- `spec/app.md` — Original v1 spec with JSON schema files; obsolete.
- `spec/STAND_LIBRARY_SPECIFICATION.md` — Spec for a Streamlit-based predecessor (STAND);
  kept as reference only.
