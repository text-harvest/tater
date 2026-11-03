"""Dash callback registration for TaterApp.

Re-exports all public setup functions so that ``tater_app.py`` can continue
to import from ``tater.ui.callbacks`` without changes.
"""
from tater.ui.callbacks.core import (
    setup_callbacks,
    setup_value_capture_callbacks,
    _decode_field_path,
)
from tater.ui.callbacks.span import setup_span_callbacks
from tater.ui.callbacks.repeater import (
    setup_repeater_callbacks,
    setup_nested_repeater_callbacks,
)
from tater.ui.callbacks.hierarchical_label import (
    setup_hl_select_callbacks,
    setup_hl_multi_callbacks,
    setup_hl_browser_callback,
)
from tater.ui.callbacks.helpers import (
    _default_meta,
    _get_ann,
    _get_meta,
    _has_value,
    _collect_value_capture_widgets,
    _collect_all_control_templates,
    update_status_for_doc,
    _is_complete_eligible,
    _doc_index,
    _perform_navigation,
)

__all__ = [
    "setup_callbacks",
    "setup_value_capture_callbacks",
    "setup_span_callbacks",
    "setup_repeater_callbacks",
    "setup_nested_repeater_callbacks",
    "setup_hl_select_callbacks",
    "setup_hl_multi_callbacks",
    "setup_hl_browser_callback",
    "_collect_value_capture_widgets",
    "_collect_all_control_templates",
    "_default_meta",
    "_get_ann",
    "_get_meta",
    "_has_value",
    "update_status_for_doc",
    "_doc_index",
    "_perform_navigation",
    "_decode_field_path",
]
