"""Synthetic, reproducible projects: documents, a schema, and optionally a saved annotations file."""
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Document lengths by name, in characters.
LENGTHS = {"short": 200, "medium": 50_000, "long": 1_000_000}

_WORDS = (
    "patient reports mild pain left lower quadrant since yesterday no fever noted "
    "exam shows soft abdomen tenderness on palpation history of hypertension "
    "medication list reviewed plan follow up in two weeks imaging ordered "
    "results pending normal limits stable condition discussed with family "
    "the cat sat quietly near window while dog barked outside garden fence "
    "weather cool cloudy morning afternoon light rain expected later evening"
).split()

_SITES = {
    "Head": ["Brain", "Eye", "Ear"],
    "Thorax": {"Lung": ["Left lung", "Right lung"], "Heart": []},
    "Abdomen": ["Liver", "Kidney", "Bowel"],
}
_SITE_PATHS = [
    ["Head", "Brain"], ["Head", "Eye"], ["Thorax", "Lung", "Left lung"],
    ["Thorax", "Heart"], ["Abdomen", "Liver"], ["Abdomen", "Bowel"],
]

CHECKBOX_SCHEMA = {
    "spec_version": "1.0",
    "title": "perf - checkbox",
    "data_schema": [
        {
            "id": "labels",
            "type": "multi_choice",
            "options": list("abcdefg"),
            "widget": {"type": "checkbox_group", "label": "Labels", "orientation": "vertical"},
        },
    ],
}

# A choice, a boolean, a text area, a repeater with a nested choice, a span
# field, a hierarchical label and one conditional — roughly the gallery mix.
REALISTIC_SCHEMA = {
    "spec_version": "1.0",
    "title": "perf - realistic",
    "hierarchies": {"sites": _SITES},
    "data_schema": [
        {
            "id": "category",
            "type": "choice",
            "options": ["normal", "abnormal", "unclear"],
            "widget": {"type": "radio_group", "label": "Category", "required": True},
        },
        {
            "id": "unclear_reason",
            "type": "text",
            "widget": {
                "type": "text_input",
                "label": "Why unclear?",
                "conditional_on": {"field": "category", "value": "unclear"},
            },
        },
        {"id": "reviewed", "type": "boolean", "widget": {"type": "checkbox", "label": "Reviewed"}},
        {"id": "notes", "type": "text", "widget": {"type": "text_area", "label": "Notes"}},
        {
            "id": "findings",
            "type": "repeater",
            "item_fields": [
                {
                    "id": "kind",
                    "type": "choice",
                    "options": ["mass", "cyst", "other"],
                    "widget": {"type": "segmented_control", "label": "Kind"},
                },
            ],
            "widget": {"type": "listable", "label": "Findings", "item_label": "Finding"},
        },
        {
            "id": "evidence",
            "type": "span_annotation",
            "widget": {"type": "span_annotation", "label": "Evidence", "entity_types": ["Support", "Against"]},
        },
        {
            "id": "site",
            "type": "hierarchical_label",
            "widget": {"type": "hierarchical_label_select", "label": "Site", "hierarchy_ref": "sites"},
        },
    ],
}

SCHEMAS = {"checkbox": CHECKBOX_SCHEMA, "realistic": REALISTIC_SCHEMA}


@dataclass
class Project:
    docs: list[dict]                 # [{"id", "name", "text"}]
    annotations: dict[str, dict]     # saved-file format: {doc_id: {"annotations": ..., "metadata": ...}}
    schema: dict                     # tater JSON schema (works for --schema and hosted mode)


def _word_pool(rng: random.Random, chars: int) -> str:
    words, n = [], 0
    while n < chars:
        w = rng.choice(_WORDS)
        words.append(w)
        n += len(w) + 1
    return " ".join(words)


def _spans(text: str, n: int, rng: random.Random) -> list[dict]:
    """n non-overlapping word spans spread evenly through text."""
    spans = []
    for k in range(n):
        pos = int((k + 0.5) * len(text) / n)
        start = text.rfind(" ", 0, pos) + 1
        end = text.find(" ", pos)
        end = len(text) if end == -1 else end
        if end > start and (not spans or start >= spans[-1]["end"]):
            spans.append({"start": start, "end": end, "text": text[start:end], "tag": rng.choice(["Support", "Against"])})
    return spans


def _filled_annotations(schema: str, text: str, spans_per_doc: int, rng: random.Random) -> dict:
    if schema == "checkbox":
        return {"labels": sorted(rng.sample("abcdefg", rng.randint(1, 3)))}
    category = rng.choice(["normal", "abnormal", "unclear"])
    return {
        "category": category,
        "unclear_reason": "conflicting findings" if category == "unclear" else None,
        "reviewed": rng.random() < 0.5,
        "notes": " ".join(rng.choices(_WORDS, k=8)),
        "findings": [{"kind": rng.choice(["mass", "cyst", "other"])} for _ in range(rng.randint(1, 2))],
        "evidence": _spans(text, spans_per_doc, rng),
        "site": rng.choice(_SITE_PATHS),
    }


def make_project(
    n_docs: int,
    doc_chars: int,
    filled: bool,
    spans_per_doc: int = 0,
    schema: Literal["checkbox", "realistic"] = "checkbox",
    seed: int = 0,
) -> Project:
    """Build a project of n_docs documents of about doc_chars characters each.

    Text is cut from one seeded pool of words at random offsets, so the same
    arguments always give the same project. With filled=True every document is
    annotated and marked complete, as if the project were finished.
    """
    rng = random.Random(seed)
    pool = _word_pool(rng, max(doc_chars * 2, 10_000))
    docs = []
    for i in range(n_docs):
        offset = rng.randrange(0, len(pool) - doc_chars + 1)
        start = pool.find(" ", offset) + 1
        docs.append({"id": f"doc_{i:05d}", "name": f"Document {i}", "text": pool[start:start + doc_chars].strip()})

    annotations = {}
    if filled:
        for d in docs:
            annotations[d["id"]] = {
                "annotations": _filled_annotations(schema, d["text"], spans_per_doc, rng),
                "metadata": {
                    "flagged": rng.random() < 0.05,
                    "notes": "",
                    "visited": True,
                    "annotation_seconds": round(rng.uniform(5, 120), 1),
                    "status": "complete",
                },
            }
    return Project(docs=docs, annotations=annotations, schema=SCHEMAS[schema])


def write_project(project: Project, directory: str | Path) -> tuple[Path, Path, Path]:
    """Write schema.json, documents.json and (if filled) annotations.json; return the three paths.

    The annotations path is returned even when nothing is written there, since
    tater saves to it.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    schema_path, docs_path, ann_path = (directory / n for n in ("schema.json", "documents.json", "annotations.json"))
    schema_path.write_text(json.dumps(project.schema, indent=2))
    docs_path.write_text(json.dumps(project.docs))
    if project.annotations:
        ann_path.write_text(json.dumps(project.annotations))
    else:
        ann_path.unlink(missing_ok=True)
    return schema_path, docs_path, ann_path
