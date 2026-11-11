# Tater

![tater-icon](tater/ui/assets/tater-icon-128x128.png)

A Python library for building document annotation interfaces with [Pydantic](https://docs.pydantic.dev/) and [Dash](https://dash.plotly.com/).

Define your annotation schema as a Pydantic model, pick widgets, and get a web-based annotation app with auto-save, progress tracking, and document navigation.

## Installation
Install via [uv](https://docs.astral.sh/uv/) (recommended) or `pip`.

### uv

```bash
uv sync
```
By default, uv will create a virtual environment in `.venv`. To activate it:
```bash
source .venv/bin/activate
```

### pip

Optionally create and activate a virtual environment first, e.g.:

```bash
python -m venv .venv
source .venv/bin/activate
```

Then install:

```bash
pip install .
```

For development (editable install):

```bash
pip install -e .
```

## Quick Start

Create a Python config file (`my_config.py`):

```python
from typing import Optional, Literal
from pydantic import BaseModel

class Schema(BaseModel):
    sentiment: Optional[Literal["positive", "negative", "neutral"]] = None
    is_relevant: bool = False
```

Run it — widgets are auto-generated from the schema:

```bash
tater --config my_config.py --documents data/documents.json
```

Or specify widgets explicitly:

```python
from typing import Optional, Literal
from pydantic import BaseModel
from tater.widgets import SegmentedControlWidget, CheckboxWidget

class Schema(BaseModel):
    sentiment: Optional[Literal["positive", "negative", "neutral"]] = None
    is_relevant: bool = False

title = "My Annotator"

widgets = [
    SegmentedControlWidget("sentiment", label="Sentiment", required=True),
    CheckboxWidget("is_relevant", label="Relevant?"),
]
```

Alternatively, use a JSON schema file (`my_schema.json`):

```json
{
  "spec_version": "1.0",
  "title": "My Annotator",
  "data_schema": [
    {
      "id": "sentiment",
      "type": "choice",
      "options": ["positive", "negative", "neutral"],
      "widget": {"type": "segmented_control", "label": "Sentiment", "required": true}
    },
    {"id": "is_relevant", "type": "boolean"}
  ]
}
```

Fields without a `widget` block get auto-generated default widgets.

```bash
tater --schema my_schema.json --documents data/documents.json
```

Example configs and schemas are in [apps/](apps/).

## Python config reference

A config file is a plain Python module. The `tater` CLI looks for these names:

| Name | Required | Description |
|------|----------|-------------|
| `Schema` | **yes** | Pydantic `BaseModel` subclass defining the annotation fields |
| `widgets` | no | List of `TaterWidget` instances. Omit to auto-generate all; supply a partial list to override specific fields and auto-generate the rest. **`SpanAnnotationWidget`, `HierarchicalLabelSelectWidget`, and `HierarchicalLabelMultiWidget` cannot be usefully auto-generated** (entity types and hierarchy are required) — always include these explicitly. |
| `title` | no | App window title (default: `"tater - document annotation"`) |
| `description` | no | Subtitle shown below the title |
| `instructions` | no | Markdown help text shown in the instructions drawer |
| `register_callbacks` | no | Callable `(app: TaterApp) -> None` called after widgets are registered; use for custom Dash callbacks and setting `app.on_save` |

## Widgets

Widgets are linked to Pydantic model fields by `schema_field`. Options for choice widgets are
inferred from the field's `Literal` type — no manual list needed.

All widgets accept `label`, `description`, and most accept `required`.

### Boolean

| Widget | Schema type | Notes |
|--------|-------------|-------|
| `CheckboxWidget` | `bool` | |
| `SwitchWidget` | `bool` | Toggle switch |
| `ChipWidget` | `bool` | Single toggleable chip |

### Single choice

| Widget | Schema type | Notes |
|--------|-------------|-------|
| `SegmentedControlWidget` | `Literal[...]` | Horizontal button group; `vertical=True` supported |
| `RadioGroupWidget` | `Literal[...]` | Radio buttons; `vertical=True` supported |
| `SelectWidget` | `Literal[...]` | Searchable dropdown |
| `ChipRadioWidget` | `Literal[...]` | Chip-style radio buttons; `vertical=True` supported |

### Multiple choice

| Widget | Schema type | Notes |
|--------|-------------|-------|
| `MultiSelectWidget` | `list[Literal[...]]` | Searchable multi-select dropdown |
| `CheckboxGroupWidget` | `list[Literal[...]]` | Checkbox group; `vertical=True` supported |

### Numeric

| Widget | Schema type | Extra params |
|--------|-------------|--------------|
| `NumberInputWidget` | `int` / `float` | `min_value`, `max_value`, `step` |
| `SliderWidget` | `int` / `float` | `min_value`, `max_value`, `step` |
| `RangeSliderWidget` | `Optional[list[float]]` | `min_value`, `max_value`, `step` |

### Text

| Widget | Schema type | Extra params |
|--------|-------------|--------------|
| `TextInputWidget` | `str` | `placeholder` |
| `TextAreaWidget` | `str` | `placeholder` |

### Specialized

These widgets require explicit configuration and **must always be included in your `widgets` list** — they cannot be usefully auto-generated.

#### Span annotation

**`SpanAnnotationWidget`** — highlight text spans and assign entity types. Schema field must be `list[SpanAnnotation]`. Auto-generation produces a widget with no entity types.

```python
from tater import SpanAnnotation
from tater.widgets import SpanAnnotationWidget, EntityType

SpanAnnotationWidget(
    "entities",
    label="Entities",
    entity_types=[
        EntityType("Medication"),
        EntityType("Diagnosis"),
        EntityType("Symptom"),
    ],
)
```

Colors are assigned automatically from the palette. To use a specific color for an entity, pass a hex string to `EntityType`:

```python
EntityType("Medication", color="#4e79a7")
EntityType("Diagnosis", color="#e15759")
```

The `palette` parameter controls auto-assigned colors (default: `"tableau10"`). Palettes are from [D3's categorical schemes](https://d3js.org/d3-scale-chromatic/categorical):

| Palette | Description |
|---------|-------------|
| `category10` | D3's category10 |
| `accent` | ColorBrewer Accent — mixed tones |
| `dark2` | ColorBrewer Dark2 — dark, saturated |
| `observable10` | Observable's 10-color palette |
| `paired` | ColorBrewer Paired — 12 colors in light/dark pairs |
| `pastel1` | ColorBrewer Pastel1 — soft tones |
| `pastel2` | ColorBrewer Pastel2 — soft tones |
| `set1` | ColorBrewer Set1 — bold, high-contrast |
| `set2` | ColorBrewer Set2 — medium saturation |
| `set3` | ColorBrewer Set3 — light, 12 colors |
| `tableau10` | Tableau's 10-color categorical palette (default) |

```python
SpanAnnotationWidget("entities", label="Entities", palette="set1", entity_types=[...])
```

#### Hierarchical label

Select one or more nodes from a tree hierarchy. Paths are stored as lists of node names from root to the selected node.

```python
from tater.widgets import (
    HierarchicalLabelSelectWidget,
    HierarchicalLabelMultiWidget,
    load_hierarchy_from_yaml,
)

ontology = load_hierarchy_from_yaml("data/ontology.yaml")

# Single selection — stores Optional[List[str]]
HierarchicalLabelSelectWidget("breed", label="Breed", hierarchy=ontology)

# Multi-selection — stores Optional[List[List[str]]]
HierarchicalLabelMultiWidget("breeds", label="Breeds", hierarchy=ontology)
```

Both widgets are always searchable. Build a hierarchy programmatically with `build_tree(dict_or_list)` or from a YAML file with `load_hierarchy_from_yaml(path)`.

By default only leaf nodes can be selected. Pass `allow_non_leaf=True` to allow selecting any node in the tree:

```python
HierarchicalLabelSelectWidget("breed", label="Breed", hierarchy=ontology, allow_non_leaf=True)
```

When searching, only matching nodes and their ancestors are shown by default. `search_show_siblings=True` also includes siblings of matching nodes; `search_show_children=True` includes their direct children.

### Containers

**`GroupWidget`** — groups child widgets under a nested Pydantic model field:
```python
class Address(BaseModel):
    city: str
    country: str

class Doc(BaseModel):
    address: Address

GroupWidget("address", label="Location", children=[
    TextInputWidget("address.city", label="City"),
    TextInputWidget("address.country", label="Country"),
])
```

**`ListableWidget`** — repeatable list of sub-widgets for `list[SomeModel]` fields, rendered as a vertical stack of cards:
```python
ListableWidget("findings", label="Findings", item_label="Finding", item_widgets=[
    RadioGroupWidget("label", label="Label"),
])
```

**`TabsWidget`** — same as `ListableWidget` but items are shown as switchable tabs.

**`AccordionWidget`** — same as `ListableWidget` but items are shown as collapsible accordion panels.

### Divider

**`DividerWidget`** — a labeled horizontal rule for visually separating sections. Has no schema field and does not contribute to the annotation model:
```python
DividerWidget(label="Clinical Findings")
DividerWidget(label="Demographics", description="Patient background info")
```

### Conditional visibility

Any widget can be conditionally shown or hidden based on another field's value using `.conditional_on(field, value)`:

```python
SwitchWidget("is_indoor", label="Indoor?"),
TextInputWidget("indoor_location", label="Indoor Location").conditional_on("is_indoor", True),

SelectWidget("pet_type", label="Pet Type"),
TextInputWidget("dog_breed", label="Dog Breed").conditional_on("pet_type", "dog"),
RadioGroupWidget("dog_temperament", label="Dog Temperament").conditional_on("pet_type", "dog"),
```

The widget is hidden until the controlling field equals `value`. Conditional widgets work at any level: top-level, inside a `GroupWidget`, or inside a repeater item. When inside a `GroupWidget`, use the field name relative to that group:

```python
GroupWidget("booleans", label="Status", children=[
    SwitchWidget("is_indoor", label="Indoor?"),
    TextInputWidget("indoor_location", label="Indoor Location").conditional_on("is_indoor", True),
])
```

The `controlling_field` argument can also be a dot-joined path or a list of path segments for cross-group references:

```python
TextInputWidget("location").conditional_on("booleans.is_indoor", True)
TextInputWidget("location").conditional_on(["booleans", "is_indoor"], True)
```

## JSON schema reference

A JSON schema file has this top-level structure:

```json
{
  "spec_version": "1.0",
  "title": "My Annotator",
  "description": "Optional subtitle",
  "hierarchies": {
    "ontology": "path/to/ontology.yaml"
  },
  "data_schema": [ ... ]
}
```

| Key | Required | Description |
|-----|----------|-------------|
| `spec_version` | **yes** | Must be `"1.0"` |
| `data_schema` | **yes** | Array of field definitions |
| `title` | no | App window title |
| `description` | no | Subtitle shown below the title |
| `hierarchies` | no | Map of named hierarchies (YAML file path or inline dict) used by `hierarchical_label` fields |

### Field definition

Every entry in `data_schema` (and `item_fields` / `fields` for repeater/group types) is either a **field** or a **divider**.

**Field** — has `id` and `type` at the top level. Data-schema keys only:

| Key | Required | Description |
|-----|----------|-------------|
| `id` | **yes** | Field name (Pydantic field name and widget ID) |
| `type` | **yes** | Field type — see table below |
| `options` | for `choice`/`multi_choice` | List of option strings |
| `default` | no | Default value |
| `fields` | for `group` | Child field definitions |
| `item_fields` | for `repeater` | Item field definitions |
| `widget` | no | Widget config block — see below |

**Divider** — no `id` or `type`; only a `widget` block:

```json
{"widget": {"type": "divider", "label": "Section Heading"}}
```

### Widget config block

All UI properties belong inside the `widget` block. `widget.type` is required for leaf fields when a `widget` block is present; it selects the widget class. Fields with no `widget` block get auto-generated default widgets.

| Key | Description |
|-----|-------------|
| `type` | Widget class — see field types table for valid values |
| `label` | Display label (default: humanized `id`) |
| `description` | Help text shown below the widget |
| `required` | `true` marks the field for completion tracking |
| `auto_advance` | `true` advances to the next document on selection (`choice`/`boolean`) |
| `placeholder` | Placeholder text (`text_input`, `text_area`) |
| `orientation` | `"vertical"` or `"horizontal"` (`radio_group`, `chip_radio`, `checkbox_group`, `segmented_control`) |
| `min_value` / `max_value` / `step` | Bounds and step size (`number_input`, `slider`, `range_slider`) |
| `entity_types` | List of entity type name strings (`span_annotation`) |
| `hierarchy_ref` | Key into the top-level `hierarchies` dict (`hierarchical_label_select`, `hierarchical_label_multi`) |
| `allow_non_leaf` | Allow selecting intermediate (non-leaf) nodes; default `false` (`hierarchical_label_select`, `hierarchical_label_multi`) |
| `search_show_siblings` | Include sibling nodes in search results; default `false` (`hierarchical_label_select`, `hierarchical_label_multi`) |
| `search_show_children` | Include direct children of matched nodes in search results; default `false` (`hierarchical_label_select`, `hierarchical_label_multi`) |
| `item_label` | Singular label for list items (`listable`, `tabs`, `accordion`) |
| `conditional_on` | `{"field": "field_id", "value": ...}` — show this widget only when the named field equals the given value. Works at any level: top-level fields, inside groups, and inside repeater items. |

### Field types

| `type` | Schema type | Default widget | Widget `type` overrides |
|--------|-------------|----------------|-------------------------|
| `boolean` | `bool` | `checkbox` | `switch`, `chip_boolean` |
| `choice` | `Literal[...]` | `segmented_control` | `radio_group`, `select`, `chip_radio` |
| `multi_choice` | `list[Literal[...]]` | `multi_select` | `checkbox_group` |
| `numeric` | `float` | `number_input` | `slider` |
| `range_slider` | `list[float]` | `range_slider` | — |
| `text` | `str` | `text_input` | `text_area` |
| `span_annotation` | `list[SpanAnnotation]` | `span_annotation` | — |
| `hierarchical_label` | `Optional[List[str]]` / `Optional[List[List[str]]]` | `hierarchical_label_select` | `hierarchical_label_multi` |
| `hierarchical_label_multi` | `Optional[List[List[str]]]` | `hierarchical_label_multi` | — |
| `group` | nested model | auto (`GroupWidget`) | — |
| `repeater` | `list[model]` | `listable` | `tabs`, `accordion` |

**`group`** — requires `fields`; `widget.type` is not used (there is only one GroupWidget). Provide a `widget` block to set `label`/`description` and explicitly control which child fields get widgets. Without a `widget` block, auto-generation covers the whole group.

**`repeater`** — requires `item_fields`; `widget.type` selects the layout (`listable` default, `tabs`, or `accordion`).

**`span_annotation`** — `entity_types` is required in the `widget` block.

**`hierarchical_label`** — `hierarchy_ref` (in the `widget` block) must match a key in the top-level `hierarchies` dict. When `widget.type` is `hierarchical_label_multi`, the schema type is `Optional[List[List[str]]]` instead of `Optional[List[str]]`.

## Document format

Documents can be provided as **JSON**, **CSV**, **TSV**, or **Excel** (`.xlsx`/`.xls`).

### JSON

```json
[
  {"text": "Inline document text goes here."},
  {"text": "Inline document text also goes here.", "name": "Patient 1", "info": {"date": "2024-01-15"}},
  {"file_path": "data/note_001.txt"},
  {"file_path": "data/note_002.txt", "name": "Patient 2", "info": {"date": "2024-01-16"}}
]
```

### CSV / TSV / Excel

Tabular formats use a header row with column names. Reserved columns:

| Column | Description |
|--------|-------------|
| `text` | Inline document text |
| `id` | Unique document ID (auto-generated if absent) |
| `name` | Display name |
| `file_path` | Path to document file (**not supported in hosted mode**) |

Any other column is added to the document's `info` dict. Empty cells are omitted.

```
id,text,date,patient_id
doc_001,"Patient presented with...",2024-01-15,P001
doc_002,"Follow-up visit...",2024-01-16,P002
```

### Common fields

Regardless of format, each document may have:
- `text` — inline document text (use this or `file_path`, not both)
- `file_path` — path to a `.txt` file; resolved relative to the documents file (use this or `text`, not both; **not supported in hosted mode**)
- `id` — unique string ID (auto-generated as `doc_000`, `doc_001`, … if omitted)
- `name` — display name
- `info` — arbitrary metadata dict shown in the UI

## Annotations file format

Auto-saved JSON keyed by document ID:

```json
{
  "doc_000": {
    "annotations": {"sentiment": "positive", "summary": "Normal findings."},
    "metadata": {"flagged": false, "notes": "", "visited": true, "annotation_seconds": 42.0, "status": "complete"}
  }
}
```

Status values: `"not_started"`, `"in_progress"`, `"complete"`.

## CLI

```
tater --config CONFIG --documents PATH [options]
tater --schema SCHEMA --documents PATH [options]
tater --hosted [options]
```

| Flag | Description |
|------|-------------|
| `--config PATH` | Python config file (one of `--config` / `--schema` required in single mode) |
| `--schema PATH` | JSON schema file (one of `--config` / `--schema` required in single mode) |
| `--documents PATH` | Documents file — JSON, CSV, TSV, or Excel (required in single mode) |
| `--annotations PATH` | Annotations output file (default: `<documents>_annotations.json`) |
| `--no-restore` | Skip loading existing annotations on startup |
| `--hosted` | Run in hosted mode (upload page at `/`, annotation UI at `/annotate`) |
| `--port INT` | Server port (default: `8050`) |
| `--host STR` | Bind address (default: `127.0.0.1`) |
| `--debug` | Enable debug/hot-reload mode |
| `--show-disclaimer` | Display a disclaimer modal that users must acknowledge before accessing the annotation UI (hosted mode only) |

Environment variables: `TATER_APP_PORT`, `TATER_APP_HOST`, `TATER_APP_DEBUG`, `TATER_SECRET_KEY`, `TATER_SESSION_CACHE_MAX` (hosted mode: most sessions kept in memory, default `100`), `TATER_SESSION_DOCS_MAX` (hosted mode: most documents across those sessions, default `200000`; `0` for no limit). When either is exceeded, the least recently used session is dropped and its user is told on their next page load.

## Jupyter notebooks

Tater can run inline in a Jupyter notebook using `tater.annotate()`.

### Installation

Install the notebook extras:

```bash
pip install -e ".[notebook]"
```

After installing, activate the `nbstripout` git filter once per clone to keep notebooks clean in git (strips outputs and execution counts on commit):

```bash
nbstripout --install --attributes .gitattributes --extra-keys "metadata.kernelspec metadata.language_info"
```

### Quick start

```python
from typing import Literal, Optional
from pydantic import BaseModel
import tater

class DocumentReview(BaseModel):
    sentiment: Optional[Literal["positive", "negative", "neutral"]] = None
    confidence: Optional[Literal["high", "medium", "low"]] = None
    notes: Optional[str] = None

app = tater.annotate(
    model=DocumentReview,
    documents="data/documents.json",
    title="Document Review",
    jupyter_mode="inline",
    port=8050,
)
```

The annotation UI renders below the cell. Change `jupyter_mode` to `"tab"` to open in a new browser tab instead.

**Retrieving results** — run this in a later cell after annotating:

```python
results = app.get_annotations()
# {'doc_000': {'sentiment': 'positive', 'confidence': 'high', 'notes': ''}, ...}
```

**Auto-save**: when `documents` is a file path, annotations are saved automatically to `<documents>_annotations.json`. The file is written at most once every 2 seconds, and pending edits are written when tater exits; `get_annotations()` always returns the latest edits. For in-memory documents (list of dicts or DataFrame), pass `annotations_path` explicitly:

```python
docs = [
    {"id": "doc_1", "text": "The product exceeded my expectations."},
    {"id": "doc_2", "text": "Delivery was slow and packaging was damaged."},
]
app = tater.annotate(model=DocumentReview, documents=docs, annotations_path="my_annotations.json", jupyter_mode="inline")
```

### Manual widget configuration

Use `TaterApp` directly for custom widgets, span annotation, or hierarchical labels:

```python
from tater import TaterApp
from tater.widgets import SegmentedControlWidget, TextAreaWidget

widgets = [
    SegmentedControlWidget("sentiment", label="Sentiment"),
    SegmentedControlWidget("confidence", label="Confidence"),
    TextAreaWidget("notes", label="Notes"),
]

app = TaterApp(schema_model=DocumentReview, title="Document Review")
app.load_documents("data/documents.json")
app.set_annotation_widgets(widgets)
app.run(jupyter_mode="inline", port=8050)
```

A working example notebook is at [apps/examples/notebooks/simple_annotation.ipynb](apps/examples/notebooks/simple_annotation.ipynb).

## Hosted mode

Hosted mode lets multiple users upload their own schema and documents and annotate independently — no server-side annotation state is kept between sessions.

```bash
tater --hosted --host 0.0.0.0 --port 8050
```

**Flow — upload your own files:**
1. User visits `/` → upload page, "Set up" tab
2. Upload a schema JSON and documents (JSON, CSV, TSV, or Excel); status icons confirm each file is valid. Alternatively, use one of the schema authoring tools:
   - **Build schema** — no-code form builder; define fields interactively and click Apply
   - **Design with AI** — copies a prompt to your clipboard; paste it into Claude, ChatGPT, or any AI assistant, follow the conversation to design your schema, then paste the resulting JSON back into the modal and click Apply
3. If the schema references external hierarchy files, per-file upload zones appear automatically
4. Optionally upload an existing annotations JSON to resume from a previous session
5. Click **Start Annotating** → redirected to `/annotate`
6. Annotate documents; click **Download** in the footer to save annotations as JSON
7. Click the home icon in the header to start over

**Flow — built-in examples:**
1. User visits `/` → click the "Browse examples" tab
2. Click any example card → immediately redirected to `/annotate` with that example loaded

**Hosted mode constraints vs. single mode:**
- No auto-save — annotations live in the browser (`dcc.Store`) and must be downloaded explicitly
- `file_path` is not supported in documents — use inline `text` instead
- Hierarchy files referenced by path in the schema must be uploaded separately (inline hierarchy dicts work without upload)

## Testing

### Setup

Install dev dependencies (includes `pytest` and `pytest-playwright`), then the browser
Playwright drives, once per machine:

```bash
uv sync --group dev
source .venv/bin/activate
playwright install chromium
```

Browser tests use Playwright's own Chromium, so there's no Chrome or ChromeDriver to install
or keep in step.

### Running tests

```bash
# Unit and integration tests (fast, no browser)
python -m pytest tests/ --ignore=tests/test_browser.py

# Browser tests (headless; ~3.5 min)
python -m pytest tests/test_browser.py --headless

# Watch them run, or keep a replayable trace of each failure in test-results/
python -m pytest tests/test_browser.py --headed
python -m pytest tests/test_browser.py --tracing retain-on-failure

# Full suite
python -m pytest tests/ --headless

# With coverage
python -m pytest tests/ --ignore=tests/test_browser.py --cov=tater --cov-report=term-missing
```
