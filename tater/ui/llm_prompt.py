"""Design with AI — LLM prompt modal and callbacks for hosted mode."""
from __future__ import annotations

import json
from pathlib import Path

from dash import Dash, Input, Output, State, ctx, dcc, html, no_update
import dash_mantine_components as dmc
from dash_iconify import DashIconify


# ---------------------------------------------------------------------------
# LLM schema-design prompt
# ---------------------------------------------------------------------------

LLM_PROMPT = """\
You are a schema design assistant for Tater, a document annotation tool.

Your goal: help the user design a Tater JSON annotation schema through \
conversation, then produce valid JSON they can paste into the app.

## How to proceed

1. Ask: What kind of documents are you annotating? What information do you \
need to capture about each one?
2. For each piece of information, determine the right field type (see \
reference below).
3. Clarify options for choice/multi-choice fields, and entity type names for \
span annotation fields.
4. Ask whether any fields should only appear when another field has a specific \
value (conditional visibility).
5. Ask which fields are required (shown with a * indicator and tracked for \
completion).
6. Generate the final JSON schema in a code block.
7. Offer to revise based on feedback.

## Tater JSON schema format

{
  "spec_version": "1.0",
  "title": "Your Schema Title",
  "data_schema": [ /* field definitions */ ]
}

## Field types and valid widget types

Field type     | Use for                              | Valid widget types (default first)
---------------|--------------------------------------|--------------------------------------------
choice         | Single selection from a list         | segmented_control, radio_group, select, chip_radio
multi_choice   | Multiple selections from a list      | multi_select, checkbox_group
boolean        | True / false, yes / no               | checkbox, switch, chip_boolean
text           | Free-form text                       | text_input, text_area
numeric        | A number                             | number_input, slider
range_slider   | A numeric range (low, high)          | range_slider (only option)
span_annotation| Highlight spans of text              | span_annotation, span_popup
group          | Grouped sub-fields (no widget type)  | (omit widget.type)
repeater       | Repeatable list of structured items  | listable (default), tabs, accordion
divider        | Visual section break (no data)       | divider (only option)

## Field definition format

Standard field:
{
  "id": "field_id",              // unique, snake_case identifier
  "type": "choice",              // field type from table above
  "options": ["a", "b", "c"],    // required for choice and multi_choice only
  "widget": {
    "type": "segmented_control", // widget type — must match field type
    "label": "Display Label",
    "description": "Optional help text shown below the widget",
    "required": true,            // optional; shows * and tracks completion
    "placeholder": "hint...",    // text_input and text_area only
    "min_value": 0,              // number_input, slider, range_slider
    "max_value": 10,
    "step": 1,
    "entity_types": ["Person"],  // span_annotation only (omit for unlabeled spans)
    "conditional_on": {"field": "other_field_id", "value": "some_value"}
  }
}

Group (named set of sub-fields — widget.type is omitted):
{
  "id": "address",
  "type": "group",
  "fields": [
    {"id": "city",    "type": "text", "widget": {"type": "text_input", "label": "City"}},
    {"id": "country", "type": "text", "widget": {"type": "text_input", "label": "Country"}}
  ],
  "widget": {"label": "Location"}
}

Repeater (list of structured items the annotator can add/remove):
{
  "id": "medications",
  "type": "repeater",
  "item_fields": [
    {"id": "name",  "type": "text",   "widget": {"type": "text_input",   "label": "Name"}},
    {"id": "dose",  "type": "numeric","widget": {"type": "number_input", "label": "Dose"}},
    {"id": "route", "type": "choice", "options": ["oral","IV","topical"],
                                      "widget": {"type": "select",       "label": "Route"}}
  ],
  "widget": {"type": "listable", "label": "Medications", "item_label": "Medication"}
}

Divider (section separator — no data field):
{"widget": {"type": "divider", "label": "Section Heading"}}

## Rules

- "id" values must be unique and snake_case.
- choice and multi_choice require "options" with at least 2 strings.
- span_annotation with entity_types produces labeled spans; omit or leave \
empty for unlabeled.
- group uses "fields"; repeater uses "item_fields". Both support the same \
leaf field types as top-level fields.
- repeater widget.type: listable (stacked cards), tabs (one tab per item), \
accordion (collapsible panels). item_label is the singular name for one item.
- conditional_on hides the widget until the named field equals the given value.
- "required" is UI-only — shows * and tracks progress; does not prevent saving.

## Complete example

{
  "spec_version": "1.0",
  "title": "Clinical Note Review",
  "data_schema": [
    {
      "id": "relevance",
      "type": "choice",
      "options": ["relevant", "not_relevant", "unclear"],
      "widget": {
        "type": "segmented_control",
        "label": "Relevance",
        "required": true
      }
    },
    {
      "id": "confidence",
      "type": "choice",
      "options": ["high", "medium", "low"],
      "widget": {
        "type": "radio_group",
        "label": "Confidence",
        "conditional_on": {"field": "relevance", "value": "relevant"}
      }
    },
    {
      "id": "notes",
      "type": "text",
      "widget": {
        "type": "text_area",
        "label": "Notes",
        "placeholder": "Any additional observations"
      }
    },
    {"widget": {"type": "divider", "label": "Span Annotation"}},
    {
      "id": "conditions",
      "type": "span_annotation",
      "widget": {
        "type": "span_annotation",
        "label": "Medical Conditions",
        "entity_types": ["Diagnosis", "Symptom", "Medication"]
      }
    }
  ]
}

---

Begin by asking the user what they are annotating and what information they \
need to capture.
"""


# ---------------------------------------------------------------------------
# Modal
# ---------------------------------------------------------------------------

def build_llm_prompt_modal() -> dmc.Modal:
    return dmc.Modal(
        id="llm-prompt-modal",
        title=dmc.Group(
            [
                DashIconify(icon="tabler:robot", width=18),
                dmc.Text("Design with AI", fw=600),
            ],
            gap="xs",
        ),
        opened=False,
        size="lg",
        closeOnEscape=True,
        children=[
            dmc.Text(
                "Copy the prompt below and paste it into an AI assistant "
                "(e.g. Claude, ChatGPT). It will guide you through designing "
                "a schema and produce JSON you can paste back here.",
                size="sm",
                c="dimmed",
            ),
            dmc.Group(
                [
                    dmc.Text("Step 1 — copy the prompt", size="sm", fw=500),
                    dmc.CopyButton(
                        value=LLM_PROMPT,
                        children=DashIconify(icon="tabler:copy"),
                        copiedChildren=DashIconify(icon="tabler:circle-check"),
                        color="gray",
                        copiedColor="dark",
                        variant="transparent",
                        px="xs",
                    ),
                ],
                gap="xs",
                align="center",
                mt="md",
            ),
            dmc.Divider(mt="xs", mb="md"),
            dmc.Text("Step 2 — paste the prompt into an AI assistant and follow its instructions", size="sm", fw=500),
            dmc.Divider(mt="xs", mb="md"),
            dmc.Text("Step 3 — paste the resulting schema below", size="sm", fw=500, mb="xs"),
            dmc.Textarea(
                id="llm-prompt-schema-input",
                placeholder='{\n  "spec_version": "1.0",\n  "title": "...",\n  "data_schema": [...]\n}',
                autosize=True,
                minRows=6,
                maxRows=16,
                styles={"input": {"fontFamily": "monospace", "fontSize": "12px"}},
            ),
            html.Div(id="llm-prompt-feedback", style={"minHeight": "20px", "marginTop": "4px"}),
            dmc.Group(
                [
                    dmc.Button(
                        "Cancel",
                        id="llm-prompt-close-btn",
                        variant="subtle",
                        color="gray",
                    ),
                    dmc.Button(
                        "Apply schema",
                        id="llm-prompt-apply-btn",
                        n_clicks=0,
                    ),
                ],
                justify="flex-end",
                mt="md",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def register_llm_prompt_callbacks(app: Dash) -> None:
    @app.callback(
        Output("llm-prompt-modal", "opened"),
        Input("llm-prompt-open-btn", "n_clicks"),
        Input("llm-prompt-close-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_llm_prompt_modal(open_clicks, close_clicks):
        if ctx.triggered_id == "llm-prompt-open-btn":
            return True
        return False

    @app.callback(
        Output("schema-store", "data", allow_duplicate=True),
        Output("schema-feedback", "children", allow_duplicate=True),
        Output("pending-hierarchies", "data", allow_duplicate=True),
        Output("hierarchy-files-store", "data", allow_duplicate=True),
        Output("llm-prompt-modal", "opened", allow_duplicate=True),
        Output("llm-prompt-feedback", "children"),
        Input("llm-prompt-apply-btn", "n_clicks"),
        State("llm-prompt-schema-input", "value"),
        prevent_initial_call=True,
    )
    def apply_llm_schema(n_clicks, text):
        if not n_clicks or not (text or "").strip():
            return no_update, no_update, no_update, no_update, no_update, no_update
        try:
            data = json.loads(text)
        except Exception as e:
            return no_update, no_update, no_update, no_update, no_update, _error_text(f"Invalid JSON: {e}")
        ok, msg = _validate_schema_json(data)
        if not ok:
            return no_update, no_update, no_update, no_update, no_update, _error_text(msg)
        pending = {
            name: Path(source).name
            for name, source in data.get("hierarchies", {}).items()
            if isinstance(source, str)
        }
        field_names = [
            f.get("id") for f in data.get("data_schema", [])
            if f.get("id") and f.get("type") != "divider"
        ]
        summary = _success_text(f"Schema from AI — {len(field_names)} top-level field(s)")
        return data, summary, pending, {}, False, None


# ---------------------------------------------------------------------------
# Local helpers (mirrors upload_layout.py — kept local to avoid circular import)
# ---------------------------------------------------------------------------

def _validate_schema_json(data: dict) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Schema must be a JSON object."
    if "data_schema" not in data:
        return False, "Schema must have a 'data_schema' key."
    fields = data["data_schema"]
    if not isinstance(fields, list) or not fields:
        return False, "Schema 'data_schema' must be a non-empty array."
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            return False, f"Field at index {i} is missing 'id' or 'type'."
        is_divider = f.get("type") == "divider" or f.get("widget", {}).get("type") == "divider"
        if not is_divider and ("id" not in f or "type" not in f):
            return False, f"Field at index {i} is missing 'id' or 'type'."
    return True, ""


def _error_text(msg: str):
    return dmc.Text(msg, size="xs", c="red")


def _success_text(msg: str):
    return dmc.Text(msg, size="xs", c="blue")
