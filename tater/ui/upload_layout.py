"""Upload page layout and callbacks for hosted mode.

Flow:
  1. User visits / → sees two tabs: "Set up" and "Browse examples"
  2. Upload tab: schema JSON + documents JSON + optional annotations JSON.
     Validation feedback shown inline; if schema references hierarchy files,
     a compact ontology upload section appears automatically.
  3. Examples tab: clickable cards for built-in example sets.
  4. On valid submit (upload tab) or card click (examples tab) → files written
     to a temp dir, paths stored in flask.session, browser redirected to /annotate
"""
from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path

from dash import ALL, MATCH, Dash, Input, Output, State, ctx, dcc, html, no_update
import dash_mantine_components as dmc
from dash_iconify import DashIconify

from tater.ui.schema_builder import (
    SCHEMA_BUILDER_STORES,
    build_schema_builder_modal,
    register_schema_builder_callbacks,
)
from tater.ui.llm_prompt import (
    build_llm_prompt_modal,
    register_llm_prompt_callbacks,
)



# ---------------------------------------------------------------------------
# Built-in examples
# ---------------------------------------------------------------------------

def _get_builtin_examples() -> list[dict]:
    """Scan tater/examples/ and return list of example metadata dicts, sorted by order."""
    examples_dir = Path(__file__).parent.parent / "examples"
    if not examples_dir.exists():
        return []
    examples = []
    for folder in examples_dir.iterdir():
        if not folder.is_dir():
            continue
        meta_file = folder / "meta.json"
        schema_file = folder / "schema.json"
        docs_file = folder / "documents.json"
        if not meta_file.exists() or not schema_file.exists() or not docs_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text())
            meta["folder"] = folder.name
            examples.append(meta)
        except Exception:
            continue
    return sorted(examples, key=lambda m: (m.get("order", 999), m.get("name", "")))


_GITHUB_REPO = "https://github.com/text-harvest/tater"
_GITHUB_EXAMPLES = f"{_GITHUB_REPO}/tree/main/tater/examples"


def _example_card(meta: dict) -> html.Div:
    return html.Div(
        dmc.Paper(
            dmc.Stack(
                [
                    dmc.Text(meta.get("name", meta["folder"]), fw=600, size="sm"),
                    dmc.Text(meta.get("description", ""), size="xs", c="dimmed"),
                ],
                gap="xs",
            ),
            withBorder=True,
            radius="md",
            p="md",
            style={"cursor": "pointer"},
        ),
        id={"type": "example-card", "name": meta["folder"]},
        n_clicks=0,
    )


def _tab_links(justify: str = "flex-end") -> dmc.Group:
    """GitHub repo and examples folder links."""
    return dmc.Group(
        [
            dmc.Anchor(
                dmc.Group(
                    [DashIconify(icon="tabler:brand-github", width=13), dmc.Text("Repo", size="xs")],
                    gap="3",
                ),
                href=_GITHUB_REPO,
                target="_blank",
                underline="never",
                c="dimmed",
            ),
            dmc.Anchor(
                dmc.Group(
                    [DashIconify(icon="tabler:folder", width=13), dmc.Text("Example files", size="xs")],
                    gap="3",
                ),
                href=_GITHUB_EXAMPLES,
                target="_blank",
                underline="never",
                c="dimmed",
            ),
        ],
        gap="sm",
        justify=justify,
    )


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _status_icon(complete: bool, optional: bool = False, size: int = 52) -> dmc.ThemeIcon:
    icon = "tabler:check" if (complete or not optional) else "tabler:question-mark"
    variant = "filled" if complete else "outline"
    color = "blue" if complete else "gray"
    return dmc.ThemeIcon(
        DashIconify(icon=icon, width=size // 2),
        size=size,
        radius="xl",
        variant=variant,
        color=color,
    )




# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def build_upload_layout(show_disclaimer: bool = False) -> dmc.MantineProvider:
    """Return the upload page root component."""
    examples = _get_builtin_examples()

    upload_tab = dmc.Stack(
        [
            dmc.Stack(
                [
                    dmc.Text("Schema (JSON)", fw=500, size="sm"),
                    html.Div(
                        [
                            html.Div(
                                dcc.Upload(
                                    dmc.Paper(
                                        dmc.Stack(
                                            [
                                                DashIconify(icon="tabler:file-code", width=32, color="gray"),
                                                dmc.Text("Drag and drop or click to select", size="sm", c="dimmed"),
                                                dmc.Text(
                                                    "A tater JSON schema file describing the annotation fields.",
                                                    size="xs", c="dimmed", ta="center",
                                                ),
                                            ],
                                            align="center",
                                            gap="xs",
                                        ),
                                        p="md",
                                        withBorder=True,
                                        radius="md",
                                        style={"cursor": "pointer", "borderStyle": "dashed", "height": "100%", "boxSizing": "border-box"},
                                    ),
                                    id="upload-schema",
                                    multiple=False,
                                    style={"borderStyle": "solid", "borderColor": "rgba(0, 0, 0, 0)", "display": "block", "height": "100%"},
                                    style_active={
                                        "borderStyle": "solid",
                                        "borderColor": "var(--mantine-color-blue-6)",
                                        "borderRadius": 10,
                                    },
                                ),
                                style={"flex": "1", "minWidth": 0, "alignSelf": "stretch"},
                            ),
                            dmc.Text("or", size="sm", c="dimmed", style={"flexShrink": 0, "alignSelf": "center"}),
                            html.Div(
                                dmc.Paper(
                                    dmc.Stack(
                                        [
                                            dmc.Button(
                                                "Build schema",
                                                id="schema-builder-open-btn",
                                                n_clicks=0,
                                                leftSection=DashIconify(icon="tabler:adjustments-horizontal", width=16),
                                                variant="subtle",
                                                color="gray",
                                                fullWidth=True,
                                            ),
                                            dmc.Divider(),
                                            dmc.Button(
                                                "Design with AI",
                                                id="llm-prompt-open-btn",
                                                n_clicks=0,
                                                leftSection=DashIconify(icon="tabler:robot", width=16),
                                                variant="subtle",
                                                color="gray",
                                                fullWidth=True,
                                            ),
                                        ],
                                        gap="xs",
                                        justify="center",
                                        style={"height": "100%"},
                                    ),
                                    p="md",
                                    withBorder=True,
                                    radius="md",
                                    style={"height": "100%", "boxSizing": "border-box"},
                                ),
                                style={"flex": "1", "minWidth": 0, "alignSelf": "stretch"},
                            ),
                            html.Div(
                                id="schema-status",
                                children=_status_icon(False),
                                style={"alignSelf": "center", "flexShrink": 0},
                            ),
                        ],
                        style={"display": "flex", "alignItems": "stretch", "gap": "12px"},
                    ),
                    html.Div(id="schema-feedback", style={"minHeight": "20px"}),
                    # Ontology section — rendered dynamically when schema has file refs
                    html.Div(id="hierarchy-upload-section"),
                ],
                gap="xs",
            ),
            dmc.Stack(
                [
                    _upload_zone(
                        upload_id="upload-documents",
                        label="Documents (JSON, CSV, TSV, or Excel)",
                        hint="Document records with at least a 'text' column/field. Supports .json, .csv, .tsv, .xlsx, .xls.",
                        icon="tabler:file-text",
                        status_id="documents-status",
                        accept=".json,.csv,.tsv,.xlsx,.xls",
                    ),
                    html.Div(id="documents-feedback", style={"minHeight": "20px"}),
                ],
                gap="xs",
            ),
            dmc.Stack(
                [
                    _upload_zone(
                        upload_id="upload-annotations",
                        label="Existing Annotations (JSON) — optional",
                        hint="A tater annotations file to resume from. Leave empty to start fresh.",
                        icon="tabler:file-arrow-right",
                        status_id="annotations-status",
                        optional=True,
                    ),
                    html.Div(id="annotations-feedback", style={"minHeight": "20px"}),
                ],
                gap="xs",
            ),
            dmc.Button(
                "Start Annotating",
                id="btn-start",
                fullWidth=True,
                disabled=True,
                rightSection=DashIconify(icon="tabler:arrow-right", width=16),
            ),
            html.Div(id="submit-feedback"),
            dmc.Text(
                "* No data are stored on the server. Download your annotations before leaving.",
                size="xs", c="dimmed", ta="right",
            ),
        ],
        gap="md",
    )

    # Group examples by category, preserving within-category order
    categories: dict[str, list] = {}
    for ex in examples:
        cat = ex.get("category", "Examples")
        categories.setdefault(cat, []).append(ex)

    category_sections = []
    for cat_name, cat_examples in categories.items():
        category_sections.append(
            dmc.Stack(
                [
                    dmc.Text(cat_name, fw=600, size="sm", c="dimmed"),
                    dmc.SimpleGrid(
                        [_example_card(ex) for ex in cat_examples],
                        cols=2,
                        spacing="md",
                    ),
                ],
                gap="xs",
            )
        )

    examples_tab = dmc.Stack(
        [
            dmc.Stack(category_sections, gap="lg") if category_sections
            else dmc.Text("No built-in examples found.", size="sm", c="dimmed"),
            html.Div(id="example-feedback"),
        ],
        gap="md",
    )

    return dmc.MantineProvider(
        defaultColorScheme="auto",
        children=[
            dcc.Location(id="upload-location", refresh=True),
            build_schema_builder_modal(),
            build_llm_prompt_modal(),
            *(
                [dmc.Modal(
                    id="disclaimer-modal",
                    opened=True,
                    closeOnClickOutside=False,
                    closeOnEscape=False,
                    withCloseButton=False,
                    title=dmc.Group(
                        [
                            DashIconify(icon="tabler:alert-triangle", width=20, color="orange"),
                            dmc.Text("Sensitive Data Warning", fw=600),
                        ],
                        gap="xs",
                    ),
                    children=[
                        dmc.Text(
                            "Do not upload sensitive data, such as protected health information (PHI). "
                            "This version of the app is not deployed in an environment approved for sensitive information.",
                            size="sm",
                        ),
                        dmc.Button("I understand", id="disclaimer-accept-btn", mt="md", fullWidth=True),
                    ],
                )]
                if show_disclaimer else []
            ),
            dmc.Box(
                dmc.Group(
                    [
                        _tab_links(),
                        dmc.ColorSchemeToggle(
                            lightIcon=DashIconify(icon="tabler:sun", width=18),
                            darkIcon=DashIconify(icon="tabler:moon", width=18),
                            size="sm",
                        ),
                    ],
                    justify="flex-end",
                    gap="sm",
                ),
                px="xl",
                py="xs",
                style={"borderBottom": "1px solid var(--mantine-color-gray-3)"},
            ),
            dmc.Container(
                dmc.Stack(
                    [
                        dmc.Title("tater", order=1, ta="center"),
                        dmc.Text(
                            "Document annotation — provide your schema and documents or choose a built-in example.",
                            size="sm", c="dimmed", ta="center",
                        ),
                        dmc.Paper(
                            dmc.Tabs(
                                [
                                    dmc.TabsList(
                                        [
                                            dmc.TabsTab(
                                                "Set up",
                                                value="upload",
                                                leftSection=DashIconify(icon="tabler:list-check", width=16),
                                            ),
                                            dmc.TabsTab(
                                                "Browse examples",
                                                value="examples",
                                                leftSection=DashIconify(icon="tabler:layout-grid", width=16),
                                            ),
                                                ],
                                    ),
                                    dmc.TabsPanel(upload_tab, value="upload", p="xl", pt="md"),
                                    dmc.TabsPanel(examples_tab, value="examples", p="xl", pt="md"),
                                ],
                                value="upload",
                            ),
                            withBorder=True,
                            shadow="sm",
                            radius="md",
                        ),
                        # Stores (outside tabs so they persist across tab switches)
                        dcc.Store(id="schema-store", data=None),
                        dcc.Store(id="documents-store", data=None),
                        dcc.Store(id="annotations-upload-store", data=None),
                        dcc.Store(id="pending-hierarchies", data={}),
                        dcc.Store(id="hierarchy-files-store", data={}),
                        *SCHEMA_BUILDER_STORES,
                    ],
                    gap="md",
                    align="stretch",
                ),
                size="sm",
                pt="xl",
            ),
        ],
    )


def _upload_zone(
    upload_id: str, label: str, hint: str, icon: str,
    status_id: str | None = None, optional: bool = False,
    accept: str | None = None,
) -> dmc.Stack:
    upload_kwargs = dict(
        id=upload_id,
        multiple=False,
        style={"borderStyle": "solid", "borderColor": "rgba(0, 0, 0, 0)"},
        style_active={"borderStyle": "solid", "borderColor": "var(--mantine-color-blue-6)", "borderRadius": 10},
    )
    if accept is not None:
        upload_kwargs["accept"] = accept
    upload = dcc.Upload(
        dmc.Paper(
            dmc.Stack(
                [
                    DashIconify(icon=icon, width=32, color="gray"),
                    dmc.Text("Drag and drop or click to select", size="sm", c="dimmed"),
                    dmc.Text(hint, size="xs", c="dimmed", ta="center"),
                ],
                align="center",
                gap="xs",
            ),
            p="md",
            withBorder=True,
            radius="md",
            style={"cursor": "pointer", "borderStyle": "dashed"},
        ),
        **upload_kwargs,
    )
    upload_row = (
        html.Div(
            [
                html.Div(upload, style={"flex": "1", "minWidth": 0}),
                html.Div(id=status_id, children=_status_icon(False, optional=optional)),
            ],
            style={"display": "flex", "alignItems": "center", "gap": "12px"},
        )
        if status_id else upload
    )
    return dmc.Stack([dmc.Text(label, fw=500, size="sm"), upload_row], gap="xs")


def _compact_upload_zone(upload_id) -> dcc.Upload:
    """Smaller upload zone for ontology files."""
    return dcc.Upload(
        dmc.Paper(
            dmc.Group(
                [
                    DashIconify(icon="tabler:file-vector", width=18, color="gray"),
                    dmc.Text("Drag and drop or click to select", size="xs", c="dimmed"),
                ],
                gap="xs",
                justify="center",
            ),
            p="xs",
            withBorder=True,
            radius="md",
            style={"cursor": "pointer", "borderStyle": "dashed"},
        ),
        id=upload_id,
        multiple=False,
        style={"borderStyle": "solid", "borderColor": "rgba(0, 0, 0, 0)"},
        style_active={"borderStyle": "solid", "borderColor": "var(--mantine-color-blue-6)", "borderRadius": 10},
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def register_upload_callbacks(app: Dash, on_session_ready=None, show_disclaimer: bool = False) -> None:
    """Register all upload-page callbacks on the given Dash app.

    Args:
        app: The Dash application instance.
        on_session_ready: Optional callable(session_info) called after a new
            session is written to flask.session.  Use this hook to pre-build
            the per-session TaterApp so that annotation callbacks are registered
            before the browser fetches ``/_dash-dependencies``.
        show_disclaimer: Whether the sensitive data disclaimer modal is shown.
            Must match the value passed to ``build_upload_layout``.
    """

    if show_disclaimer:
        @app.callback(
            Output("disclaimer-modal", "opened"),
            Input("disclaimer-accept-btn", "n_clicks"),
            prevent_initial_call=True,
        )
        def close_disclaimer(_):
            return False

    # Validate schema upload
    @app.callback(
        Output("schema-store", "data", allow_duplicate=True),
        Output("schema-feedback", "children", allow_duplicate=True),
        Output("pending-hierarchies", "data", allow_duplicate=True),
        Output("hierarchy-files-store", "data", allow_duplicate=True),
        Input("upload-schema", "contents"),
        State("upload-schema", "filename"),
        prevent_initial_call=True,
    )
    def validate_schema(contents, filename):
        if not contents:
            return None, None, {}, {}
        if not (filename or "").lower().endswith(".json"):
            return None, _error_text(f"'{filename}' is not a JSON file. Please upload a .json schema file."), {}, {}
        result, error = _decode_json_upload(contents, filename)
        if error:
            return None, _error_text(error), {}, {}
        ok, msg = _validate_schema_json(result)
        if not ok:
            return None, _error_text(msg), {}, {}
        def _field_name(f):
            if f.get("id"):
                return f["id"]
            if f.get("type") == "divider" or f.get("widget", {}).get("type") == "divider":
                return "divider"
            return None
        field_names = [n for f in result.get("data_schema", []) if (n := _field_name(f))]
        n = len([n for n in field_names if n != "divider"])
        summary = f"✓ {filename} — {n} top-level field(s)"
        # Collect file-path hierarchy references: {ref_name: filename}
        pending = {
            name: Path(source).name
            for name, source in result.get("hierarchies", {}).items()
            if isinstance(source, str)
        }
        return result, _success_text(summary), pending, {}

    # Render ontology upload section — one compact zone per hierarchy file
    @app.callback(
        Output("hierarchy-upload-section", "children"),
        Input("pending-hierarchies", "data"),
    )
    def render_hierarchy_section(pending):
        if not pending:
            return None
        rows = []
        for ref_name, filename in pending.items():
            rows.append(dmc.Stack(
                [
                    dmc.Text(filename, size="xs", c="dimmed"),
                    dmc.Group(
                        [
                            dmc.Box(
                                _compact_upload_zone({"type": "hierarchy-upload", "ref": ref_name}),
                                style={"flex": "1", "minWidth": 0},
                            ),
                            html.Div(
                                id={"type": "hierarchy-status", "ref": ref_name},
                                children=_status_icon(False, size=28),
                            ),
                        ],
                        align="center",
                        gap="sm",
                        wrap="nowrap",
                    ),
                    html.Div(id={"type": "hierarchy-feedback", "ref": ref_name}, style={"minHeight": "20px"}),
                    dcc.Store(id={"type": "hierarchy-relay", "ref": ref_name}, data=None),
                ],
                gap="4",
            ))
        return dmc.Stack(
            [dmc.Divider(), dmc.Text("Ontology Files", fw=500, size="sm")] + rows + [dmc.Divider()],
            gap="xs",
        )

    # Handle each ontology file upload independently via MATCH.
    # Resets contents to None after each upload so re-uploading always fires.
    @app.callback(
        Output({"type": "hierarchy-relay", "ref": MATCH}, "data"),
        Output({"type": "hierarchy-feedback", "ref": MATCH}, "children"),
        Output({"type": "hierarchy-upload", "ref": MATCH}, "contents"),
        Input({"type": "hierarchy-upload", "ref": MATCH}, "contents"),
        State({"type": "hierarchy-upload", "ref": MATCH}, "filename"),
        State("pending-hierarchies", "data"),
        prevent_initial_call=True,
    )
    def handle_one_hierarchy(contents, filename, pending):
        if not contents:
            return no_update, no_update, no_update
        if not any((filename or "").lower().endswith(ext) for ext in (".yaml", ".yml", ".json")):
            return None, _error_text(f"'{filename}' is not a supported ontology file. Please upload a .yaml or .json file."), None
        ref_name = ctx.triggered_id["ref"]
        expected = (pending or {}).get(ref_name, "")
        if filename != expected:
            return None, _error_text(f"Expected '{expected}', got '{filename}'."), None
        try:
            _header, encoded = contents.split(",", 1)
            content = base64.b64decode(encoded).decode("utf-8")
        except Exception:
            return None, _error_text(f"Could not decode '{filename}'."), None
        return {"filename": filename, "content": content}, _success_text(f"✓ {filename}"), None

    # Relay all per-hierarchy uploads into hierarchy-files-store
    @app.callback(
        Output("hierarchy-files-store", "data", allow_duplicate=True),
        Input({"type": "hierarchy-relay", "ref": ALL}, "data"),
        prevent_initial_call=True,
    )
    def relay_hierarchy_files(relay_data_list):
        ref_names = [t["id"]["ref"] for t in ctx.inputs_list[0]]
        return {
            ref: data
            for ref, data in zip(ref_names, relay_data_list)
            if data is not None
        }

    # Validate documents upload
    @app.callback(
        Output("documents-store", "data"),
        Output("documents-feedback", "children"),
        Input("upload-documents", "contents"),
        State("upload-documents", "filename"),
        prevent_initial_call=True,
    )
    def validate_documents(contents, filename):
        if not contents:
            return None, None
        ext = Path(filename or "").suffix.lower()
        if ext == ".json":
            result, error = _decode_json_upload(contents, filename)
            if error:
                return None, _error_text(error)
        elif ext in (".csv", ".tsv", ".xlsx", ".xls"):
            try:
                _header, encoded = contents.split(",", 1)
                content_bytes = base64.b64decode(encoded)
            except Exception:
                return None, _error_text(f"Could not decode '{filename}'.")
            result, error = _parse_tabular_upload(content_bytes, filename)
            if error:
                return None, _error_text(error)
        else:
            return None, _error_text(
                f"'{filename}' is not a supported format. "
                "Please upload a .json, .csv, .tsv, .xlsx, or .xls file."
            )
        data, err = _validate_documents_data(result, filename)
        if err:
            return None, _error_text(err)
        return data, _success_text(f"✓ {filename} — {len(data)} document(s)")

    # Validate annotations upload (optional)
    @app.callback(
        Output("annotations-upload-store", "data"),
        Output("annotations-feedback", "children"),
        Input("upload-annotations", "contents"),
        State("upload-annotations", "filename"),
        prevent_initial_call=True,
    )
    def validate_annotations(contents, filename):
        if not contents:
            return None, None
        if not (filename or "").lower().endswith(".json"):
            return None, _error_text(f"'{filename}' is not a JSON file. Please upload a .json annotations file.")
        result, error = _decode_json_upload(contents, filename)
        if error:
            return None, _error_text(error)
        if not isinstance(result, dict):
            return None, _error_text("Annotations file must be a JSON object.")
        return result, _success_text(f"✓ {filename} — {len(result)} document(s) with annotations")

    # Enable start button when all required uploads are present
    @app.callback(
        Output("btn-start", "disabled"),
        Input("schema-store", "data"),
        Input("schema-builder-store", "data"),
        Input("documents-store", "data"),
        Input("pending-hierarchies", "data"),
        Input("hierarchy-files-store", "data"),
    )
    def toggle_start(schema_data, builder_schema_data, documents_data, pending, hierarchy_files):
        if not (schema_data or builder_schema_data) or not documents_data:
            return True
        if pending and set(pending.keys()) != set((hierarchy_files or {}).keys()):
            return True
        return False

    # Update ontology file status icons
    @app.callback(
        Output({"type": "hierarchy-status", "ref": MATCH}, "children"),
        Input({"type": "hierarchy-relay", "ref": MATCH}, "data"),
    )
    def hierarchy_status(data):
        return _status_icon(data is not None, size=28)

    # Update upload zone status icons
    @app.callback(
        Output("schema-status", "children"),
        Output("schema-feedback", "children", allow_duplicate=True),
        Input("schema-store", "data"),
        Input("schema-builder-store", "data"),
        prevent_initial_call=True,
    )
    def schema_status(schema_data, builder_data):
        complete = schema_data is not None or builder_data is not None
        if builder_data and not schema_data:
            n = sum(1 for f in builder_data.get("data_schema", []) if f.get("id"))
            title = builder_data.get("title", "")
            label = f"✓ Built schema — {n} field(s)" + (f": {title}" if title else "")
            feedback = _success_text(label)
        else:
            feedback = no_update
        return _status_icon(complete), feedback

    @app.callback(Output("documents-status", "children"), Input("documents-store", "data"))
    def documents_status(data):
        return _status_icon(data is not None)

    @app.callback(Output("annotations-status", "children"), Input("annotations-upload-store", "data"))
    def annotations_status(data):
        return _status_icon(data is not None, optional=True)

    # Handle submit: pass data directly to session, redirect
    @app.callback(
        Output("upload-location", "href", allow_duplicate=True),
        Output("submit-feedback", "children"),
        Input("btn-start", "n_clicks"),
        State("schema-store", "data"),
        State("schema-builder-store", "data"),
        State("documents-store", "data"),
        State("hierarchy-files-store", "data"),
        State("annotations-upload-store", "data"),
        prevent_initial_call=True,
    )
    def handle_submit(n_clicks, schema_data, builder_schema_data, documents_data, hierarchy_files, annotations_data):
        if not n_clicks:
            return no_update, no_update
        schema_data = schema_data or builder_schema_data
        if not schema_data or not documents_data:
            return no_update, _error_text("Please upload both files before starting.")
        try:
            import flask
            session_id = secrets.token_hex(16)
            session_info = {
                "session_id": session_id,
                "schema_data": schema_data,
                "docs_data": documents_data,
                "hierarchy_files": hierarchy_files or {},
                "annotations_data": annotations_data,
            }
            flask.session["tater_session"] = {"session_id": session_id}
            if on_session_ready is not None:
                on_session_ready(session_info)
            return "/annotate", no_update
        except Exception as e:
            return no_update, _error_text(f"Error starting session: {e}")

    # Handle example card click: load data from package dir, redirect
    @app.callback(
        Output("upload-location", "href", allow_duplicate=True),
        Output("example-feedback", "children"),
        Input({"type": "example-card", "name": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def load_example(n_clicks_list):
        if not ctx.triggered or not any(n_clicks_list):
            return no_update, no_update

        example_name = ctx.triggered_id["name"]
        example_dir = Path(__file__).parent.parent / "examples" / example_name

        try:
            import flask
            schema_data = json.loads((example_dir / "schema.json").read_text())
            docs_data = json.loads((example_dir / "documents.json").read_text())

            session_id = secrets.token_hex(16)
            session_info = {
                "session_id": session_id,
                "schema_data": schema_data,
                "docs_data": docs_data,
                # Pass example dir so parse_schema can resolve relative
                # hierarchy file paths directly from the package directory.
                "base_dir": str(example_dir),
            }
            flask.session["tater_session"] = {"session_id": session_id}
            if on_session_ready is not None:
                on_session_ready(session_info)
            return "/annotate", no_update
        except Exception as e:
            return no_update, _error_text(f"Error loading example '{example_name}': {e}")

    register_schema_builder_callbacks(app)
    register_llm_prompt_callbacks(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_tabular_upload(content_bytes: bytes, filename: str) -> tuple[list | None, str | None]:
    """Parse CSV/TSV/Excel bytes into a list of document dicts.

    Uses the same column conventions as ``document_loader._load_tabular``:
    ``id``, ``text``, ``name``, ``file_path`` are reserved; everything else
    lands in an ``info`` dict.  Returns ``(docs_list, None)`` on success or
    ``(None, error_message)`` on failure.
    """
    import io
    from tater.loaders.document_loader import _load_tabular

    ext = Path(filename).suffix.lower()
    try:
        if ext in (".xlsx", ".xls"):
            source = io.BytesIO(content_bytes)
            docs = _load_tabular(source, excel=True)
        elif ext == ".tsv":
            source = io.StringIO(content_bytes.decode("utf-8"))
            docs = _load_tabular(source, sep="\t")
        else:  # .csv
            source = io.StringIO(content_bytes.decode("utf-8"))
            docs = _load_tabular(source, sep=",")
    except UnicodeDecodeError:
        return None, f"Could not decode '{filename}'. Make sure it is UTF-8 encoded."
    except Exception as e:
        return None, f"Error parsing '{filename}': {e}"

    return [d.model_dump(exclude_none=True) for d in docs], None


def _decode_json_upload(contents: str, filename: str) -> tuple[dict | list | None, str | None]:
    """Decode a base64-encoded dcc.Upload content string and parse JSON."""
    try:
        _header, encoded = contents.split(",", 1)
        decoded = base64.b64decode(encoded).decode("utf-8")
        return json.loads(decoded), None
    except (ValueError, UnicodeDecodeError):
        return None, f"Could not decode '{filename}'. Make sure it is a UTF-8 JSON file."
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON in '{filename}': {e}"


def _validate_schema_json(data: dict) -> tuple[bool, str]:
    """Basic structural check for a tater JSON schema."""
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


def _validate_documents_data(result: list, filename: str) -> tuple[list | None, str | None]:
    """Validate parsed documents list. Returns (data, error_message) — error_message is None on success.

    Extracted from the validate_documents closure for unit testability.
    The closure wraps the error string in _error_text / _success_text before returning to Dash.
    """
    if not isinstance(result, list) or not result:
        return None, "Documents must be a non-empty JSON array."
    bad = [i for i, d in enumerate(result) if not isinstance(d, dict)]
    if bad:
        return None, f"Document(s) at index {bad[:3]} are not objects."
    file_path_docs = [i for i, d in enumerate(result) if isinstance(d, dict) and "file_path" in d]
    if file_path_docs:
        return None, (
            "Documents with 'file_path' are not supported in hosted mode. "
            "Include document text inline using the 'text' field."
        )
    missing_text = [i for i, d in enumerate(result) if isinstance(d, dict) and "text" not in d]
    if missing_text:
        return None, f"Document(s) at index {missing_text[:3]} are missing required 'text' field."
    return result, None


def _error_text(msg: str):
    return dmc.Text(msg, size="xs", c="red")


def _success_text(msg: str):
    return dmc.Text(msg, size="xs", c="blue")
