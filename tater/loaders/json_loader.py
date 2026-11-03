"""JSON schema loader for Tater.

Converts a tater JSON schema file into a Pydantic model and widget list.
Schema files are used with the ``tater --schema`` CLI flag:

    tater --schema apps/schema/simple.json --documents data/documents.json

Schema format::

    {
      "spec_version": "1.0",
      "title": "My Annotation App",
      "description": "Optional subtitle shown below the title.",
      "hierarchies": {
        "ontology": "data/my_ontology.yaml",
        "regions": {"Head": ["Brain", "Eye"], "Thorax": ["Lung", "Heart"]}
      },
      "data_schema": [
        {
          "id": "sentiment",
          "type": "choice",
          "options": ["positive", "negative", "neutral"],
          "widget": {
            "type": "radio_group",
            "label": "Sentiment",
            "description": "Overall tone of the document",
            "required": true,
            "orientation": "vertical"
          }
        },
        {
          "id": "diagnosis",
          "type": "hierarchical_label",
          "widget": {
            "type": "hierarchical_label_select",
            "label": "Diagnosis",
            "hierarchy_ref": "ontology",
          }
        },
        {
          "id": "address",
          "type": "group",
          "fields": [
            {
              "id": "city",
              "type": "text",
              "widget": {"type": "text_input", "label": "City"}
            },
            {
              "id": "country",
              "type": "text",
              "widget": {"type": "text_input", "label": "Country"}
            }
          ],
          "widget": {"label": "Location"}
        },
        {
          "id": "pets",
          "type": "repeater",
          "item_fields": [
            {
              "id": "name",
              "type": "text",
              "widget": {"type": "text_input", "label": "Name"}
            },
            {
              "id": "kind",
              "type": "choice",
              "options": ["cat", "dog"],
              "widget": {"type": "segmented_control", "label": "Kind"}
            }
          ],
          "widget": {"type": "listable", "label": "Pets", "item_label": "Pet"}
        },
        {"widget": {"type": "divider", "label": "Section Break"}}
      ]
    }

The ``widget`` object on a field is optional. Without it, a sensible default
widget is chosen for each field type via ``widgets_from_model``. Top-level
``widget.type`` is required if a ``widget`` block is present on a leaf field.
For group fields, ``widget.type`` is omitted (only one GroupWidget class
exists). For repeater fields, ``widget.type`` selects ``listable`` (default),
``tabs``, or ``accordion``.

Dividers have no ``id`` or ``type`` at the top level — only a ``widget``
block: ``{"widget": {"type": "divider", "label": "..."}}``.

Field types (``"type"`` at the top level of a field spec):
  ``boolean``           — true/false (default: CheckboxWidget)
  ``choice``            — single selection from ``options`` (default: SegmentedControlWidget)
  ``multi_choice``      — multiple selections from ``options`` (default: MultiSelectWidget)
  ``numeric``           — number (default: NumberInputWidget)
  ``range_slider``      — numeric range; requires ``min_value``/``max_value`` in ``widget``
  ``text``              — free text (default: TextInputWidget)
  ``span_annotation``   — text span labelling (SpanAnnotationWidget)
  ``hierarchical_label``— tree-based single-select label (default: HierarchicalLabelSelectWidget)
  ``group``             — nested sub-model with ``fields``
  ``repeater``          — repeatable list of sub-items with ``item_fields``

Widget type strings (``"widget": {"type": "..."}``):
  ``segmented_control``          — for ``choice`` fields (default)
  ``radio_group``                — for ``choice`` fields
  ``select``                     — for ``choice`` fields
  ``chip_radio``                 — for ``choice`` fields
  ``multi_select``               — for ``multi_choice`` fields (default)
  ``checkbox_group``             — for ``multi_choice`` fields
  ``text_input``                 — for ``text`` fields (default)
  ``text_area``                  — for ``text`` fields
  ``checkbox``                   — for ``boolean`` fields (default)
  ``switch``                     — for ``boolean`` fields
  ``chip_boolean``               — for ``boolean`` fields
  ``number_input``               — for ``numeric`` fields (default)
  ``slider``                     — for ``numeric`` fields
  ``range_slider``               — for ``range_slider`` fields (default)
  ``span_annotation``            — for ``span_annotation`` fields (default)
  ``hierarchical_label_select``  — for ``hierarchical_label`` fields (default, single-select)
  ``hierarchical_label_multi``   — for ``hierarchical_label_multi`` fields (multi-select)
  ``listable``                   — for ``repeater`` fields (default)
  ``tabs``                       — for ``repeater`` fields
  ``accordion``                  — for ``repeater`` fields
  ``divider``                    — section break (no ``id`` at field level)

Widget config keys (inside the ``widget`` block):
  ``label``          — display label
  ``description``    — secondary text shown below the label
  ``required``       — shows * indicator; drives progress status
  ``auto_advance``   — advance to next document on selection (choice/boolean)
  ``placeholder``    — placeholder text (text_input, text_area)
  ``orientation``    — ``"vertical"`` or ``"horizontal"`` (radio_group, chip_radio,
                       checkbox_group, segmented_control)
  ``min_value``      — minimum (number_input, slider, range_slider)
  ``max_value``      — maximum (number_input, slider, range_slider)
  ``step``           — step size (slider, range_slider, number_input)
  ``allow_non_leaf``        — allow selecting intermediate nodes (hierarchical_label_*)
  ``search_show_siblings``  — also show siblings of matched nodes (hierarchical_label_*)
  ``search_show_children``  — also show direct children of matched nodes (hierarchical_label_*)
  ``hierarchy_ref``  — key into the top-level ``hierarchies`` dict
  ``entity_types``   — list of entity type names (span_annotation)
  ``item_label``     — singular label for list items (listable, tabs, accordion)
  ``conditional_on`` — ``{"field": "...", "value": ...}`` visibility condition
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional, Literal

from pydantic import BaseModel, Field, create_model

from tater.widgets.base import TaterWidget
from tater.widgets.group import GroupWidget
from tater.widgets.divider import DividerWidget
from tater.widgets.span import EntityType
from tater.widgets.hierarchical_label import build_tree, load_hierarchy_from_yaml, Node
from tater.models.span import SpanAnnotation
from tater.loaders.model_loader import WIDGET_CLASS, _humanize


def _make_literal(options: list[str]) -> Any:
    """Dynamically create Literal[opt1, opt2, ...] from a list of strings."""
    return Literal[tuple(options)]


def _to_classname(field_id: str) -> str:
    """Convert snake_case or kebab-case id to PascalCase for model class naming."""
    return "".join(part.title() for part in field_id.replace("-", "_").split("_"))


def _load_hierarchies(data: dict, base_dir: Path) -> dict[str, Node]:
    """Build the named hierarchy map from the top-level ``hierarchies`` section."""
    hierarchy_map: dict[str, Node] = {}
    for name, source in data.get("hierarchies", {}).items():
        if isinstance(source, str):
            path = Path(source)
            if not path.is_absolute():
                path = base_dir / path
            hierarchy_map[name] = load_hierarchy_from_yaml(path)
        else:
            hierarchy_map[name] = build_tree(source)
    return hierarchy_map


def _build_pydantic_field(
    spec: dict, hierarchy_map: dict
) -> tuple[str, Any]:
    """Build ``(field_id, pydantic_field_def)`` from a field spec.

    Reads only top-level data-schema keys: ``id``, ``type``, ``options``,
    ``default``, ``fields`` (group), ``item_fields`` (repeater).
    For ``range_slider``, ``min_value``/``max_value`` are read from the
    ``widget`` block as they determine the field default.
    """
    fid: str = spec["id"]
    ftype: str = spec["type"]
    options: list[str] = spec.get("options", [])
    default = spec.get("default")

    if ftype == "group":
        child_fields: dict[str, Any] = {}
        for child_spec in spec.get("fields", []):
            if "id" not in child_spec:
                continue  # divider — no model field
            cid, cdef = _build_pydantic_field(child_spec, hierarchy_map)
            child_fields[cid] = cdef
        sub_model = create_model(_to_classname(fid), **child_fields)
        return fid, (Optional[sub_model], None)

    if ftype == "repeater":
        item_fields: dict[str, Any] = {}
        for child_spec in spec.get("item_fields", []):
            if "id" not in child_spec:
                continue  # divider — no model field
            cid, cdef = _build_pydantic_field(child_spec, hierarchy_map)
            item_fields[cid] = cdef
        item_model = create_model(_to_classname(fid) + "Item", **item_fields)
        return fid, (list[item_model], Field(default_factory=list))

    # --- Leaf field types ---
    if ftype == "choice":
        lit = _make_literal(options)
        return fid, (Optional[lit], default)

    if ftype == "multi_choice":
        lit = _make_literal(options)
        return fid, (list[lit], Field(default_factory=list))

    if ftype == "text":
        return fid, (Optional[str], default)

    if ftype == "boolean":
        return fid, (bool, default if default is not None else False)

    if ftype == "numeric":
        return fid, (Optional[float], default)

    if ftype == "range_slider":
        widget_spec = spec.get("widget") or {}
        _min = float(widget_spec.get("min_value", 0))
        _max = float(widget_spec.get("max_value", 100))
        return fid, (list[float], Field(default_factory=lambda a=_min, b=_max: [a, b]))

    if ftype == "span_annotation":
        return fid, (list[SpanAnnotation], Field(default_factory=list))

    if ftype == "hierarchical_label":
        widget_spec = spec.get("widget") or {}
        if widget_spec.get("type") == "hierarchical_label_multi":
            return fid, (Optional[List[List[str]]], None)
        return fid, (Optional[List[str]], None)

    if ftype == "hierarchical_label_multi":
        return fid, (Optional[List[List[str]]], None)

    raise ValueError(f"Unknown field type {ftype!r} for field {fid!r}")


def _build_widget_from_spec(
    spec: dict, hierarchy_map: dict
) -> TaterWidget | None:
    """Build a widget from a field spec, or return ``None`` if no widget block.

    For entries without ``id`` (dividers), constructs a ``DividerWidget`` if
    the widget block has ``"type": "divider"``.

    For ``group`` fields, detects via ``spec["type"]`` and builds a
    ``GroupWidget`` regardless of ``widget.type``.

    For ``repeater`` fields, selects ``listable``/``tabs``/``accordion`` via
    ``widget.type`` (defaults to ``listable``).

    For leaf fields, ``widget.type`` is required and must be a key in
    ``WIDGET_CLASS``.
    """
    ftype = spec.get("type")
    fid = spec.get("id", "")
    widget_spec = spec.get("widget")

    # Entry with no "id" — divider or other widget-only spec
    if "id" not in spec:
        if widget_spec and widget_spec.get("type") == "divider":
            return DividerWidget(
                label=widget_spec.get("label", ""),
                description=widget_spec.get("description"),
            )
        return None

    # Group field
    if ftype == "group":
        if widget_spec is None:
            return None
        label = widget_spec.get("label") or _humanize(fid)
        description = widget_spec.get("description")
        children: list[TaterWidget] = []
        for child_spec in spec.get("fields", []):
            if "id" not in child_spec:
                cws = child_spec.get("widget") or {}
                children.append(DividerWidget(
                    label=cws.get("label", ""),
                    description=cws.get("description"),
                ))
            else:
                child = _build_widget_from_spec(child_spec, hierarchy_map)
                if child is not None:
                    children.append(child)
        return GroupWidget(fid, label=label, description=description, children=children)

    # Repeater field
    if ftype == "repeater":
        if widget_spec is None:
            return None
        label = widget_spec.get("label") or _humanize(fid)
        description = widget_spec.get("description")
        wtype = widget_spec.get("type", "listable")
        item_label = widget_spec.get("item_label", "Item")
        item_widgets: list[TaterWidget] = []
        for child_spec in spec.get("item_fields", []):
            if "id" not in child_spec:
                cws = child_spec.get("widget") or {}
                item_widgets.append(DividerWidget(
                    label=cws.get("label", ""),
                    description=cws.get("description"),
                ))
            else:
                child = _build_widget_from_spec(child_spec, hierarchy_map)
                if child is not None:
                    item_widgets.append(child)
        cls = WIDGET_CLASS[wtype]
        return cls(
            fid,
            label=label,
            description=description,
            item_widgets=item_widgets,
            item_label=item_label,
        )

    # Leaf field — no widget block → caller skips this field
    if widget_spec is None:
        return None

    wtype: str = widget_spec["type"]
    label = widget_spec.get("label") or _humanize(fid)
    description = widget_spec.get("description")
    required: bool = widget_spec.get("required", False)

    if wtype in ("segmented_control", "radio_group", "chip_radio"):
        vertical = widget_spec.get("orientation") == "vertical"
        cls = WIDGET_CLASS[wtype]
        w = cls(fid, label=label, description=description, required=required, vertical=vertical)

    elif wtype == "select":
        w = WIDGET_CLASS[wtype](fid, label=label, description=description, required=required)

    elif wtype == "checkbox_group":
        vertical = widget_spec.get("orientation") == "vertical"
        w = WIDGET_CLASS[wtype](fid, label=label, description=description, required=required, vertical=vertical)

    elif wtype == "multi_select":
        w = WIDGET_CLASS[wtype](fid, label=label, description=description, required=required)

    elif wtype in ("text_input", "text_area"):
        placeholder = widget_spec.get("placeholder")
        cls = WIDGET_CLASS[wtype]
        w = cls(fid, label=label, description=description, required=required, placeholder=placeholder)

    elif wtype in ("checkbox", "switch", "chip_boolean"):
        w = WIDGET_CLASS[wtype](fid, label=label, description=description)

    elif wtype == "number_input":
        w = WIDGET_CLASS[wtype](
            fid, label=label, description=description, required=required,
            min_value=widget_spec.get("min_value"),
            max_value=widget_spec.get("max_value"),
            step=widget_spec.get("step"),
        )

    elif wtype == "slider":
        w = WIDGET_CLASS[wtype](
            fid, label=label, description=description, required=required,
            min_value=widget_spec.get("min_value", 0),
            max_value=widget_spec.get("max_value", 100),
            step=widget_spec.get("step"),
            default=spec.get("default"),
        )

    elif wtype == "range_slider":
        w = WIDGET_CLASS[wtype](
            fid, label=label, description=description, required=required,
            min_value=widget_spec.get("min_value", 0),
            max_value=widget_spec.get("max_value", 100),
            step=widget_spec.get("step"),
            default=spec.get("default"),
        )

    elif wtype in ("span_annotation", "span_popup"):
        entity_types = [EntityType(name=et) for et in widget_spec.get("entity_types", [])]
        w = WIDGET_CLASS[wtype](fid, label=label, entity_types=entity_types, description=description)

    elif wtype in ("hierarchical_label_select", "hierarchical_label_multi"):
        ref = widget_spec.get("hierarchy_ref")
        hierarchy = hierarchy_map.get(ref) if ref else None
        allow_non_leaf = widget_spec.get("allow_non_leaf", False)
        search_show_siblings = widget_spec.get("search_show_siblings", False)
        search_show_children = widget_spec.get("search_show_children", False)
        w = WIDGET_CLASS[wtype](fid, label=label, description=description, required=required, hierarchy=hierarchy, allow_non_leaf=allow_non_leaf, search_show_siblings=search_show_siblings, search_show_children=search_show_children)

    elif wtype == "divider":
        w = DividerWidget(label=label, description=description)

    else:
        raise KeyError(f"Unknown widget type {wtype!r}")

    # Post-construction: auto_advance, conditional_on
    if widget_spec.get("auto_advance") and ftype in ("choice", "boolean", "hierarchical_label"):
        w.auto_advance = True
    condition = widget_spec.get("conditional_on")
    if condition is not None:
        w.conditional_on(condition["field"], condition["value"])

    return w


def parse_schema(
    data: dict, base_dir: Path | None = None
) -> tuple[type[BaseModel], list[TaterWidget]]:
    """Parse a schema dict into a Pydantic model and partial widget list.

    Args:
        data: Parsed JSON dict with a ``data_schema`` list. Each field entry
              may include an optional ``widget`` object for UI configuration.
        base_dir: Directory used to resolve relative ``hierarchy_file`` paths.
                  Defaults to the current working directory.

    Returns:
        A ``(model_class, widgets)`` tuple. ``widgets`` is a partial list —
        fields without a ``widget`` block are omitted. The caller (runner.py)
        fills gaps via ``widgets_from_model(model, overrides=widgets)``.
    """
    base_dir = base_dir or Path.cwd()
    hierarchy_map = _load_hierarchies(data, base_dir)

    model_fields: dict[str, Any] = {}
    widgets: list[TaterWidget] = []

    for spec in data.get("data_schema", []):
        if "id" not in spec:
            # Widget-only entry (e.g. divider) — no model field
            widget = _build_widget_from_spec(spec, hierarchy_map)
            if widget is not None:
                widgets.append(widget)
            continue
        fid, field_def = _build_pydantic_field(spec, hierarchy_map)
        model_fields[fid] = field_def
        widget = _build_widget_from_spec(spec, hierarchy_map)
        if widget is not None:
            widgets.append(widget)

    return create_model("AnnotationModel", **model_fields), widgets


def load_schema(path: str | Path) -> dict:
    """Load a schema JSON file and return a config dict.

    Args:
        path: Path to a tater JSON schema file. Relative paths in the
              ``hierarchies`` section are resolved from this file's directory.

    Returns:
        A dict with keys ``schema_model``, ``widgets``, ``title``,
        ``description``, ``instructions``.
    """
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    schema_model, widgets = parse_schema(data, base_dir=path.parent)
    return {
        "schema_model": schema_model,
        "widgets": widgets,
        "title": data.get("title"),
        "description": data.get("description"),
        "instructions": data.get("instructions"),
    }
