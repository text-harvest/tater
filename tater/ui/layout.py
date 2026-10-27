"""Layout builders for TaterApp."""
from __future__ import annotations

from typing import TYPE_CHECKING

from dash import html, dcc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
from tater.ui.constants import STATUS_COLORS, STATUS_LABELS

if TYPE_CHECKING:
    from tater.ui.tater_app import TaterApp
    from tater.widgets.base import TaterWidget



# Header: 48px content row + 4px progress bar
_HEADER_HEIGHT = 52
# Footer: two rows (status + navigation)
_FOOTER_HEIGHT = 84


def _build_doc_list_store_data(tater_app: TaterApp) -> dict:
    """Precompute per-doc display info for the clientside nav-info and document-select callbacks."""
    docs = tater_app.documents
    return {
        "total": len(docs),
        "ids": [d.id for d in docs],
        "names": [d.display_name() for d in docs],
        "index": {d.id: i for i, d in enumerate(docs)},
        "metadata": {
            d.id: " | ".join(f"{k}: {v}" for k, v in d.info.items()) if d.info else ""
            for d in docs
        },
        "status_labels": STATUS_LABELS,
        "status_colors": STATUS_COLORS,
        "hosted": tater_app.is_hosted,
    }


def build_layout(tater_app: TaterApp) -> dmc.MantineProvider:
    """Create the Dash layout with navigation and annotation panel."""
    annotation_components = _build_annotation_components(tater_app.widgets)
    has_required = any(w.required for w in tater_app._collect_value_capture_widgets(tater_app.widgets))
    document_viewer = _build_document_viewer()
    document_controls = _build_document_controls()
    has_instructions = bool(tater_app.instructions and tater_app.instructions.strip())
    is_hosted = tater_app.is_hosted

    # Static per-doc info preloaded for the clientside nav-info callback.
    doc_list_store = dcc.Store(id="doc-list-store", data=_build_doc_list_store_data(tater_app))

    # Global span stores — always included so span callbacks are always registered
    span_stores = [
        dcc.Store(id="span-any-change", data=0),
        dcc.Store(id="span-delete-store", data=None),
        dcc.Store(id="document-text-store", data=""),
        dcc.Store(id="span-color-map", data=tater_app._span_color_map),
        dcc.Store(id="repeater-load-trigger", data=0),
        html.Button(id="span-delete-proxy", n_clicks=0, style={"display": "none"}),
        html.Button(id="span-popup-proxy", n_clicks=0, style={"display": "none"}),
    ]

    content_grid = dmc.Grid([
        dmc.GridCol([
            dmc.Stack([
                document_viewer,
                document_controls,
            ], gap="md")
        ], span={"base": 12, "md": 7}),
        dmc.GridCol([
            dmc.Paper(
                dmc.Stack(
                    annotation_components + (
                        [dmc.Text("* Required", size="xs", c="red")] if has_required else []
                    ),
                    gap="md",
                ),
                id="tater-annotation-panel",
                p="md",
                withBorder=True,
                shadow="sm",
            )
        ], span={"base": 12, "md": 5}),
    ], gutter="xl", align="flex-start")

    app_shell = dmc.AppShell(
        [
            _build_app_header(tater_app, has_instructions, is_hosted=is_hosted),
            dmc.AppShellMain(
                dmc.Container([
                    dmc.Stack([
                        dmc.Text(tater_app.description, size="sm", c="dimmed", ta="center") if tater_app.description else None,
                        dmc.Group([
                            dmc.Text(id="document-title", fw=500, size="sm"),
                            dmc.Badge(id="status-badge", variant="light", size="sm"),
                        ], gap="xs"),
                        content_grid,
                    ], gap="xs"),
                ], size="xl", pt="xs", px="xs", fluid=True),
            ),
            _build_app_footer(is_hosted=is_hosted),
        ],
        header={"height": _HEADER_HEIGHT},
        footer={"height": _FOOTER_HEIGHT},
        padding="xs",
    )

    return dmc.MantineProvider(
        defaultColorScheme="auto",
        children=[
            dmc.NotificationContainer(
                id="notification-container",
                position="top-center",
                notificationMaxHeight=300,
                zIndex=1000,
                withinPortal=True,
            ),
            dcc.Location(id="annotate-location", refresh=True),
            dcc.Download(id="download-annotations") if is_hosted else None,
            dmc.Modal(
                title="Start over?",
                id="modal-start-over",
                opened=False,
                centered=True,
                children=[
                    dmc.Text("All progress will be lost. Download annotations first if you want to keep them."),
                    dmc.Group(
                        [
                            dmc.Button("Cancel", id="btn-start-over-cancel", variant="default"),
                            dmc.Button("Start over", id="btn-start-over-confirm"),
                        ],
                        justify="flex-end",
                        mt="md",
                    ),
                ],
            ) if is_hosted else None,
            dmc.Modal(
                title="Session Summary",
                id="modal-finish",
                opened=False,
                centered=True,
                children=[
                    html.Div(id="finish-modal-content"),
                    dmc.Group(
                        [
                            dmc.Button("Go to first incomplete", id="btn-go-incomplete", variant="outline", size="sm", style={"display": "none"}),
                            dmc.Button("Close", id="btn-close-finish", variant="default", size="sm"),
                        ],
                        justify="flex-end",
                        mt="md",
                    ),
                ],
            ),
            dcc.Store(id="current-doc-id", data=tater_app.documents[0].id if tater_app.documents else ""),
            dcc.Store(id="timing-store", data={"last_save_time": None, "doc_start_time": None, "session_start_time": None, "annotation_seconds_at_load": 0.0}),
            dcc.Store(id="status-store", data="not_started"),
            dcc.Store(id="auto-advance-store", data=0),
            dcc.Store(id="aa-fields-store", data=list(tater_app._aa_fields)),
            dcc.Store(id="ev-lookup-store", data=tater_app._ev_lookup),
            dcc.Store(id="schema-warnings-store", data=tater_app._schema_warnings),
            dcc.Store(id="annotations-store", data={
                doc_id: ann.model_dump()
                for doc_id, ann in tater_app.annotations.items()
            }),
            dcc.Store(id="metadata-store", data={
                doc_id: meta.model_dump()
                for doc_id, meta in tater_app.metadata.items()
            }),
            dcc.Interval(id="clock-interval", interval=1000, n_intervals=0),
            dcc.Store(id="filter-store", data={"flagged": False, "statuses": list(STATUS_LABELS.keys())}),
            dcc.Store(id="doc-select-nav", data=None),
            dcc.Store(id="doc-select-state-sink", data=None),  # dummy output of updateDocSelectState
            doc_list_store,
            *span_stores,
            app_shell,
            dmc.Drawer(
                title="Instructions",
                id="instructions-drawer",
                opened=False,
                position="top",
                size="lg",
                padding="md",
                children=[
                    dmc.Divider(mb="md"),
                    dcc.Markdown(tater_app.instructions or ""),
                ],
            ) if has_instructions else None,
        ],
    )


def _build_annotation_components(widgets: list[TaterWidget]) -> list:
    """Create annotation fields from widgets."""
    annotation_components = []
    for widget in widgets:
        annotation_components.append(widget.render_field())
    return annotation_components


def _build_document_viewer() -> dmc.Paper:
    """Build the document viewer component (wrapped in Paper)."""
    return dmc.Paper(
        html.Pre(
            id="document-content",
            style={
                "whiteSpace": "pre-wrap",
                "wordWrap": "break-word",
                "fontFamily": "monospace",
                "fontSize": "0.9rem",
                "lineHeight": "1.5",
                "margin": 0,
                "padding": "0 3px",
                "height": "500px",
                "overflowY": "auto",
            },
        ),
        p="md",
        withBorder=True,
        shadow="sm",
    )


def _build_document_controls() -> dmc.Stack:
    """Build the flag/notes control stack."""
    return dmc.Stack([
        dmc.Group([
            dmc.Checkbox(id="flag-document", label="Flag document", checked=False),
            dmc.Text(id="document-metadata", size="sm", c="dimmed"),
        ], justify="space-between", wrap="nowrap"),
        dmc.Textarea(
            id="document-notes",
            label="Notes",
            autosize=True,
            minRows=3,
            placeholder="Add notes about this document",
        ),
    ], gap="sm")



def _build_app_header(tater_app: TaterApp, has_instructions: bool, is_hosted: bool = False) -> dmc.AppShellHeader:
    """Sticky header: app title (left) + document title / status badge (right)
    with a full-width progress bar flush to the bottom edge."""
    help_button = (
        dmc.ActionIcon(
            DashIconify(icon="tabler:info-circle", width=20),
            id="btn-open-instructions",
            variant="subtle",
            size="sm",
        ) if has_instructions else None
    )

    left = dmc.Group([
        dmc.ProgressRoot(
            [
                dmc.ProgressSection(value=0, id="prog-c",  color=f"var(--mantine-color-{STATUS_COLORS['complete']}-light-color)"),
                dmc.ProgressSection(value=0, id="prog-ip", color=f"var(--mantine-color-{STATUS_COLORS['in_progress']}-light-color)"),
                dmc.ProgressSection(value=0, id="prog-ns", color=f"var(--mantine-color-{STATUS_COLORS['not_started']}-light)"),
            ],
            size="sm",
            radius="sm",
            style={"flex": "1"},
        ),
        DashIconify(
            id="icon-all-complete",
            icon="tabler:circle-check",
            width=20,
            color=f"var(--mantine-color-{STATUS_COLORS['complete']}-filled)",
            style={"visibility": "hidden", "flexShrink": 0},
        ),
    ], gap="xs", style={"flex": "1"}, wrap="nowrap")

    center = dmc.Group(
        [dmc.Title(tater_app.title, order=3, lineClamp=1)],
        justify="center",
        style={"flex": "2"},
    )

    theme_toggle = dmc.ColorSchemeToggle(
        computedColorScheme="auto",
        lightIcon=DashIconify(icon="tabler:sun", width=20),
        darkIcon=DashIconify(icon="tabler:moon", width=20),
        size="sm",
    )

    right_children = [theme_toggle]
    if help_button:
        right_children.append(help_button)
    if is_hosted:
        right_children.append(
            dmc.ActionIcon(
                DashIconify(icon="tabler:home", width=20),
                id="btn-start-over",
                variant="subtle",
                size="sm",
            )
        )

    right = dmc.Group(
        right_children,
        gap="xs",
        style={"flex": "1"},
        justify="flex-end",
    )

    return dmc.AppShellHeader([
        dmc.Group(
            [left, center, right],
            px="md",
            align="center",
            wrap="nowrap",
            style={"height": f"{_HEADER_HEIGHT - 4}px"},
        ),
        dmc.Progress(id="document-progress", value=0, size="xs", radius=0),
    ],
    style={"boxShadow": "0 2px 6px rgba(0,0,0,0.1)"})


def _build_app_footer(is_hosted: bool = False) -> dmc.AppShellFooter:
    """Sticky footer: save status + timer (left), navigation controls (right)."""
    # Right side of nav row: Next+Save (single mode) or Next+Download+StartOver (hosted)
    if is_hosted:
        right_nav = dmc.Group([
            html.Div(
                dmc.Button(
                    "Next", id="btn-next", variant="outline", size="sm",
                    fullWidth=True,
                    rightSection=DashIconify(icon="tabler:arrow-right", width=16),
                    style={"flex": "1"},
                ),
                id="btn-next-container",
                style={"display": "contents"},
            ),
            html.Div(
                dmc.Button(
                    "Finish", id="btn-finish", variant="outline", size="sm",
                    fullWidth=True,
                    rightSection=DashIconify(icon="tabler:circle-check", width=16),
                    style={"flex": "1"},
                ),
                id="btn-finish-container",
                style={"display": "none"},
            ),
            dmc.Button(
                DashIconify(icon="tabler:download", width=16),
                id="btn-download",
                variant="outline",
                size="sm",
                px="xs",
            ),
        ], gap="xs", wrap="nowrap", style={"flex": "1"})
        save_right = None
    else:
        right_nav = dmc.Group([
            html.Div(
                dmc.Button(
                    "Next", id="btn-next", variant="outline", size="sm",
                    fullWidth=True,
                    rightSection=DashIconify(icon="tabler:arrow-right", width=16),
                    style={"borderRight": "none", "borderRadius": "var(--mantine-radius-sm) 0 0 var(--mantine-radius-sm)", "flex": "1"},
                ),
                id="btn-next-container",
                style={"display": "contents"},
            ),
            html.Div(
                dmc.Button(
                    "Finish", id="btn-finish", variant="outline", size="sm",
                    fullWidth=True,
                    rightSection=DashIconify(icon="tabler:circle-check", width=16),
                    style={"borderRight": "none", "borderRadius": "var(--mantine-radius-sm) 0 0 var(--mantine-radius-sm)", "flex": "1"},
                ),
                id="btn-finish-container",
                style={"display": "none"},
            ),
            dmc.Button(
                DashIconify(icon="tabler:device-floppy", width=16),
                id="btn-save",
                variant="outline",
                size="sm",
                px="xs",
                style={"borderRadius": "0 var(--mantine-radius-sm) var(--mantine-radius-sm) 0"},
            ),
        ], gap=0, wrap="nowrap", style={"flex": "1"})
        save_right = dmc.Text(id="save-status-text", size="sm", c="dimmed")

    return dmc.AppShellFooter(
        dmc.Stack(
            [
                # Top row: navigation
                dmc.Flex(
                    [
                        # Prev (grows)
                        dmc.Button(
                            "Previous", id="btn-prev", variant="outline", size="sm",
                            fullWidth=True,
                            leftSection=DashIconify(icon="tabler:arrow-left", width=16),
                            style={"flex": "1"},
                        ),
                        # Selector + flag (grows)
                        dmc.Group([
                            # Options, status/flag rendering and search are all clientside
                            # (buildDocOptions / updateDocSelectState / docRenderOption / docFilter in utils.js).
                            dmc.Select(
                                id="document-select",
                                data=[],
                                value=None,
                                placeholder="Select document",
                                searchable=True,
                                allowDeselect=False,
                                nothingFoundMessage="No matching documents",
                                renderOption={"function": "docRenderOption"},
                                filter={"function": "docFilter"},
                                maxDropdownHeight=400,
                                size="sm",
                                rightSection=DashIconify(icon="tabler:selector", width=16),
                                comboboxProps={"position": "top-start", "withinPortal": True, "zIndex": 600},
                                style={"flex": "1", "minWidth": 0},
                                styles={"input": {"borderTopRightRadius": 0, "borderBottomRightRadius": 0}},
                            ),
                            dmc.Popover(
                                [
                                    dmc.PopoverTarget(
                                        dmc.Button(
                                            DashIconify(icon="tabler:filter", width=16),
                                            id="filter-btn",
                                            size="sm",
                                            variant="outline",
                                            px="xs",
                                            style={"borderRadius": "0 var(--mantine-radius-sm) var(--mantine-radius-sm) 0"},
                                        ),
                                    ),
                                    dmc.PopoverDropdown(
                                        dmc.Stack([
                                            dmc.Text("Status", size="xs", c="dimmed"),
                                            dmc.CheckboxGroup(
                                                id="filter-status",
                                                value=list(STATUS_LABELS.keys()),
                                                children=dmc.Stack([
                                                    dmc.Checkbox(value=k, label=v)
                                                    for k, v in STATUS_LABELS.items()
                                                ], gap="xs"),
                                            ),
                                            dmc.Divider(),
                                            dmc.Checkbox(id="filter-flagged-check", label="Flagged only", checked=False),
                                        ], gap="sm", p="xs"),
                                    ),
                                ],
                                position="top-end",
                                withArrow=True,
                                withinPortal=True,
                                keepMounted=True,
                                zIndex=600,
                            ),
                        ], gap=0, wrap="nowrap", style={"flex": "1"}),
                        # Right nav group
                        right_nav,
                    ],
                    gap="sm",
                    align="center",
                ),
                # Bottom row: status info
                dmc.Group(
                    [
                        dmc.Group([
                            dmc.ActionIcon(
                                DashIconify(id="btn-pause-timer-icon", icon="tabler:player-pause", width=16),
                                id="btn-pause-timer",
                                size="sm",
                                variant="outline",
                            ),
                            dmc.Text(id="timing-text", size="sm", c="dimmed"),
                        ], gap="xs"),
                        save_right or dmc.Text(id="save-status-text", size="sm", c="dimmed"),
                    ],
                    justify="space-between",
                ),
            ],
            gap="8",
            px="md",
            py="xs",
        ),
        style={"boxShadow": "0 -2px 6px rgba(0,0,0,0.1)", "backgroundColor": "var(--mantine-color-body)"},
    )
