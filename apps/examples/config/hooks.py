"""Demonstrates the on_save hook and the escape-hatch callback pattern.

on_save hook
------------
``on_save`` is not defined at module level here because its audit path
depends on the app's annotations path, which is only known at runtime.
Instead, ``register_callbacks`` sets ``app.on_save`` after the app is created.

Escape hatch
------------
``register_callbacks`` also registers a Dash callback that clears ``pet_mood``
whenever ``needs_attention`` is unchecked — a cross-field rule that can't be
expressed as a widget declaration.  It runs after ``set_annotation_widgets``
so that Tater's component IDs are already finalised.

Custom Dash callbacks are experimental: they depend on Tater's internal component
IDs and value props, which may change as the tool evolves.
"""
import json
from pathlib import Path
from typing import Optional, Literal

from pydantic import BaseModel

from tater.widgets import SegmentedControlWidget, CheckboxWidget


class Schema(BaseModel):
    pet_mood: Optional[Literal["happy", "anxious", "calm"]] = None
    needs_attention: bool = False


title = "tater - hooks"
description = "Demonstrates the on_save hook and escape-hatch Dash callback pattern."

instructions = """## Auto-Update Features

**Pet Mood** → Logs the selection via hook callback.

**Needs Attention** → Unchecking this box triggers an escape-hatch callback that auto-clears the mood field.
"""

pet_mood = SegmentedControlWidget(
    schema_field="pet_mood",
    label="Pet Mood",
    description="Overall mood of the pet in this record",
    required=True,
)
needs_attention = CheckboxWidget(
    schema_field="needs_attention",
    label="Needs Attention?",
    description="Does this pet require immediate attention?",
)

widgets = [pet_mood, needs_attention]


def register_callbacks(app) -> None:
    # Wire up on_save using the app's annotations path.
    audit_path = (
        Path(app.annotations_path).parent / "audit.jsonl"
        if app.annotations_path
        else Path("audit.jsonl")
    )

    def _log_save(doc_id: str, annotation: Schema) -> None:
        with open(audit_path, "a") as f:
            f.write(json.dumps({"doc": doc_id, **annotation.model_dump()}) + "\n")

    app.on_save = _log_save

    # Escape hatch: clear pet_mood when pet does not need attention.
    from dash import Input, Output, no_update

    @app.app.callback(
        Output(pet_mood.schema_id, "value", allow_duplicate=True),
        Input(needs_attention.schema_id, "checked"),
        prevent_initial_call=True,
    )
    def clear_mood_when_no_attention(needs_attention):
        if not needs_attention:
            return None
        return no_update
