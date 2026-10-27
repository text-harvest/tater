/**
 * General-purpose clientside callback utilities for Tater.
 */

window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.tater = window.dash_clientside.tater || {};

Object.assign(window.dash_clientside.tater, {

    autoScrollTop: function (_docId) {
        window.scrollTo({ top: 0, behavior: "instant" });
    },

    /**
     * Unified visibility toggle for ALL conditional widgets — flat and repeater.
     * Registered once at startup using ALL patterns for ld/path/tf.
     *
     * Uses ctx.outputs_list to iterate over output wrappers, finds each wrapper's
     * config store by matching tf/ld/path in ctx.states_list[0], then looks up the
     * controlling widget's current value from ctx.inputs_list[0] (tater-control) or
     * ctx.inputs_list[1] (tater-bool-control) by matching ctrl_tf + ld + path.
     * Row correlation (ld/path) ensures repeater items match their own row's controls.
     *
     * controlValues – values of ALL tater-control widgets (flat and repeater)
     * boolValues    – checked values of ALL tater-bool-control widgets
     * configs       – {target, empty, ctrl_tf} from ALL tater-cond-config stores
     */
    conditionalVisibilityAll: function (controlValues, boolValues, configs) {
        var ctx = window.dash_clientside.callback_context;
        var outputs = (ctx.outputs_list || []);
        if (!outputs.length) { return []; }

        var controlInputs = (ctx.inputs_list && ctx.inputs_list[0]) ? ctx.inputs_list[0] : [];
        var boolInputs    = (ctx.inputs_list && ctx.inputs_list[1]) ? ctx.inputs_list[1] : [];
        var configMeta    = (ctx.states_list && ctx.states_list[0]) ? ctx.states_list[0] : [];

        return outputs.map(function (out) {
            var outId = out.id;

            // Find the config whose store id matches this wrapper's tf/ld/path.
            var config = null;
            for (var k = 0; k < configMeta.length; k++) {
                var cm = configMeta[k];
                if (cm && cm.id &&
                    cm.id.tf === outId.tf &&
                    cm.id.ld === outId.ld &&
                    cm.id.path === outId.path) {
                    config = configs[k];
                    break;
                }
            }
            if (!config || config.ctrl_tf === undefined) { return {}; }

            var ctrlTf = config.ctrl_tf;
            var ld     = outId.ld   || "";
            var path   = outId.path || "";

            // Find the controlling widget in the same row (ld + path) by tf.
            for (var i = 0; i < controlInputs.length; i++) {
                var inp = controlInputs[i];
                if (inp && inp.id &&
                    inp.id.tf === ctrlTf &&
                    inp.id.ld === ld &&
                    inp.id.path === path) {
                    return controlValues[i] === config.target ? {} : { "display": "none" };
                }
            }
            for (var i = 0; i < boolInputs.length; i++) {
                var inp = boolInputs[i];
                if (inp && inp.id &&
                    inp.id.tf === ctrlTf &&
                    inp.id.ld === ld &&
                    inp.id.path === path) {
                    return boolValues[i] === config.target ? {} : { "display": "none" };
                }
            }
            return {};
        });
    },

    /**
     * Conditional value-clear: returns empty_value when the widget is hidden.
     * v         – current value of the controlling widget
     * config    – {target, empty} from the tater-cond-config dcc.Store
     */
    conditionalClear: function (v, config) {
        if (config === null || config === undefined) return window.dash_clientside.no_update;
        return v !== config.target ? config.empty : window.dash_clientside.no_update;
    },

    /**
     * Update the session-level status count badges in the header.
     * Returns [nsText, ipText, cText] for the NS / IP / C badges.
     */
    updateStatusBadges: function (metadataData, docListStore) {
        var nu = window.dash_clientside.no_update;
        if (!docListStore || !docListStore.total) { return [nu, nu, nu, nu]; }
        var total = docListStore.total;
        var complete = 0, inProgress = 0, notStarted = 0;
        var docIds = Object.keys(docListStore.index);
        for (var i = 0; i < docIds.length; i++) {
            var meta = metadataData && metadataData[docIds[i]];
            var status = meta ? (meta.status || "not_started") : "not_started";
            if (status === "complete") { complete++; }
            else if (status === "in_progress") { inProgress++; }
            else { notStarted++; }
        }
        var allDone = complete === total;
        return [
            (notStarted / total) * 100,
            (inProgress / total) * 100,
            (complete  / total) * 100,
            allDone ? { "visibility": "visible" } : { "visibility": "hidden" },
        ];
    },

    /** Show an element ({}) when v is truthy; hide it (display:none) otherwise. */
    showWhenTruthy: function (v) {
        return v ? {} : { "display": "none" };
    },

    /** Clear a text input — returns an empty string. */
    clearInput: function () {
        return "";
    },

    /** Open a component by returning true (e.g. a Drawer's opened prop). */
    openOnClick: function () {
        return true;
    },

    /** Close a component by returning false (e.g. a Modal's opened prop). */
    closeOnClick: function () {
        return false;
    },

    /**
     * Build the document-select options from doc-list-store + metadata-store, applying
     * the status/flag filter. Returns no_update unless something the options show
     * (a status, a flag, or the filter) changed, so annotation edits that don't change
     * status never re-render the Select.
     *
     * Each option: {value, label: "<pos>. <name>", pos, status, statusLabel,
     * statusColor, flagged, search} — the extra fields are read by docRenderOption
     * and docFilter.
     */
    buildDocOptions: function (metadataData, filterData, docListStore) {
        var nu = window.dash_clientside.no_update;
        if (!docListStore || !docListStore.ids) { return nu; }
        var ids = docListStore.ids;
        var filter = filterData || {};

        var statuses = new Array(ids.length);
        var flags = new Array(ids.length);
        var sigParts = new Array(ids.length);
        for (var i = 0; i < ids.length; i++) {
            var meta = metadataData && metadataData[ids[i]];
            statuses[i] = (meta && meta.status) || "not_started";
            flags[i] = !!(meta && meta.flagged);
            sigParts[i] = statuses[i] + (flags[i] ? "!" : "");
        }
        var sig = JSON.stringify(filter) + "|" + sigParts.join(",");
        var cache = window._taterDocOptionsCache;
        if (cache && cache.store === docListStore && cache.sig === sig) { return nu; }
        window._taterDocOptionsCache = { store: docListStore, sig: sig };

        // Empty status list means "all", matching the filter popover's semantics.
        var allowed = (filter.statuses && filter.statuses.length) ? filter.statuses : null;
        var labels = docListStore.status_labels || {};
        var colors = docListStore.status_colors || {};
        var options = [];
        for (var j = 0; j < ids.length; j++) {
            if (filter.flagged && !flags[j]) { continue; }
            if (allowed && allowed.indexOf(statuses[j]) === -1) { continue; }
            var id = ids[j];
            var name = docListStore.names[j];
            var info = (docListStore.metadata && docListStore.metadata[id]) || "";
            options.push({
                value: id,
                label: (j + 1) + ". " + name,
                pos: j + 1,
                status: statuses[j],
                statusLabel: labels[statuses[j]] || statuses[j],
                statusColor: colors[statuses[j]] || "gray",
                flagged: flags[j],
                search: (name + " " + id + " " + info).toLowerCase(),
            });
        }
        return options;
    },

    /** Show the current document in document-select (no_update if it already does). */
    syncDocSelect: function (currentDocId, _data, value) {
        if (!currentDocId || value === currentDocId) { return window.dash_clientside.no_update; }
        return currentDocId;
    },

    /**
     * Forward a user pick in document-select to doc-select-nav (read by the server-side
     * navigate_select). Ignores the echo from syncDocSelect. The timestamp makes
     * re-picking the same document a distinct store value. Blurs the Select so the
     * arrow-key navigation in keyboard.js works again right away.
     */
    docSelectChanged: function (value, currentDocId) {
        if (!value || value === currentDocId) { return window.dash_clientside.no_update; }
        var el = document.activeElement;
        if (el && el.blur) { el.blur(); }
        return { id: value, t: Date.now() };
    },

});


// ---------------------------------------------------------------------------
// DMC Functions-as-Props (window.dashMantineFunctions)
// ---------------------------------------------------------------------------

window.dashMantineFunctions = window.dashMantineFunctions || {};

/**
 * filter / renderOption for HierarchicalLabel*Widget (shared by Select and MultiSelect).
 *
 * Option values are compact JSON arrays encoding the full path, e.g. '["Animals","Mammals","Dog"]'.
 * Depth is path.length - 1. JSON.stringify is used for ancestor/sibling/child comparisons,
 * which is safe because Python builds values with the same compact format (separators=(',',':')).
 *
 * hlFilter: matches on node name (label); ancestors of any match are always included.
 * Optionally also includes siblings and/or direct children of matched nodes, controlled
 * by a sentinel config item prepended to the data array by HierarchicalLabel*Widget.component().
 *
 * Sentinel format: value = "__config__" + JSON, e.g.:
 *   __config__{"showSiblings":true,"showChildren":false}
 * The sentinel has an empty label and disabled=true so it is never rendered or selected.
 * The search term is stashed in _hlSearch for use by hlRenderOption.
 *
 * hlRenderOption: indents each option by depth, renders non-leaf nodes bold, highlights the
 * matched substring, shows a chevron-down for non-leaf nodes, and a check icon when selected.
 */

// Shared search term written by hlFilter, read by hlRenderOption.
let _hlSearch = "";

const _CONFIG_PREFIX = "__config__";

window.dashMantineFunctions.hlFilter = function ({ options, search }) {
    _hlSearch = (search || "").toLowerCase();

    // Extract and strip the sentinel config item.
    let showSiblings = false;
    let showChildren = false;
    const dataOptions = options.filter((o) => {
        if (!o.value.startsWith(_CONFIG_PREFIX)) return true;
        try {
            const config = JSON.parse(o.value.slice(_CONFIG_PREFIX.length));
            showSiblings = !!config.showSiblings;
            showChildren = !!config.showChildren;
        } catch (e) {
            console.warn("hlFilter: failed to parse sentinel config", o.value);
        }
        return false;  // always strip sentinel from results
    });

    if (!_hlSearch) return dataOptions;

    // Parse all paths once upfront so comparisons don't re-parse on every check.
    const parsed = dataOptions.map((o) => JSON.parse(o.value));

    const includedValues = new Set();

    dataOptions.forEach((option, i) => {
        const nameMatch = option.label.toLowerCase().includes(_hlSearch);
        const synonymMatch = Array.isArray(option.synonyms) &&
            option.synonyms.some((s) => s.toLowerCase().includes(_hlSearch));
        if (!nameMatch && !synonymMatch) return;

        const path = parsed[i];

        // Always include ancestors (full spine to root).
        for (let j = 1; j <= path.length; j++) {
            includedValues.add(JSON.stringify(path.slice(0, j)));
        }

        // Siblings: all options at the same depth sharing the same parent path.
        if (showSiblings && path.length > 1) {
            const parentStr = JSON.stringify(path.slice(0, -1));
            parsed.forEach((p, k) => {
                if (p.length === path.length && JSON.stringify(p.slice(0, -1)) === parentStr) {
                    includedValues.add(dataOptions[k].value);
                }
            });
        }

        // Direct children: one level below the matched node.
        if (showChildren) {
            parsed.forEach((p, k) => {
                if (p.length === path.length + 1 && JSON.stringify(p.slice(0, -1)) === option.value) {
                    includedValues.add(dataOptions[k].value);
                }
            });
        }
    });

    return dataOptions.filter((option) => includedValues.has(option.value));
};

// ---------------------------------------------------------------------------
// SVG icon helpers
// ---------------------------------------------------------------------------

// Renders a Tabler-style SVG icon. strokeWidth compensates for the 24×24 viewBox
// being scaled to `size` px so line weight stays consistent.
function _tablerSvg(points, stroke, size, svgStyle) {
    return React.createElement(
        "svg",
        {
            xmlns: "http://www.w3.org/2000/svg",
            width: size, height: size,
            viewBox: "0 0 24 24",
            fill: "none",
            stroke,
            strokeWidth: Math.round(2 * 24 / size),
            strokeLinecap: "round",
            strokeLinejoin: "round",
            style: svgStyle,
        },
        React.createElement("polyline", { points })
    );
}

// tabler:chevron-down — indicates a non-leaf (expandable) node.
function _chevronDown() {
    return _tablerSvg(
        "6 9 12 15 18 9",
        "var(--mantine-color-dimmed)",
        12,
        { marginLeft: "4px", flexShrink: 0 }
    );
}

// tabler:check — right-aligned selection indicator; hidden when unchecked.
function _checkIcon(visible) {
    return React.createElement(
        "span",
        {
            style: {
                marginLeft: "auto",
                paddingLeft: "8px",
                flexShrink: 0,
                visibility: visible ? "visible" : "hidden",
                display: "flex",
                alignItems: "center",
            },
        },
        _tablerSvg(
            "20 6 9 17 4 12",
            "var(--mantine-color-dimmed)",
            14,
            {}
        )
    );
}

window.dashMantineFunctions.hlRenderOption = function ({ option, checked }) {
    const depth = JSON.parse(option.value).length - 1;
    const label = option.label;
    const lower = _hlSearch;
    const isLeaf = option.leaf !== false;  // default true if field absent

    // Build label — highlight the matched substring if present.
    let labelContent;
    const matchIdx = lower ? label.toLowerCase().indexOf(lower) : -1;
    if (matchIdx !== -1) {
        labelContent = [
            label.slice(0, matchIdx),
            React.createElement(
                "mark",
                { key: "m", style: { background: "var(--mantine-color-yellow-3)", borderRadius: "3px", padding: "0 0" } },
                label.slice(matchIdx, matchIdx + lower.length)
            ),
            label.slice(matchIdx + lower.length),
        ];
    } else {
        labelContent = label;
    }

    // Build synonym suffix — show all synonyms that match the search term.
    let synonymSuffix = null;
    const matchedSynonyms = lower
        ? (option.synonyms || []).filter((s) => s.toLowerCase().includes(lower))
        : [];
    if (matchedSynonyms.length > 0) {
        const parts = ["- "];
        matchedSynonyms.forEach((syn, i) => {
            if (i > 0) parts.push(", ");
            const idx = syn.toLowerCase().indexOf(lower);
            parts.push(syn.slice(0, idx));
            parts.push(React.createElement(
                "mark",
                { key: `sm${i}`, style: { background: "var(--mantine-color-yellow-3)", borderRadius: "3px", padding: "0 0" } },
                syn.slice(idx, idx + lower.length)
            ));
            parts.push(syn.slice(idx + lower.length));
        });
        synonymSuffix = React.createElement(
            "span",
            { style: { fontSize: "var(--mantine-font-size-xs)", color: "var(--mantine-color-dimmed)", marginLeft: "4px" } },
            ...parts
        );
    }

    return React.createElement(
        "span",
        {
            style: {
                display: "flex",
                alignItems: "center",
                flex: 1,
                paddingLeft: `${depth * 14}px`,
                fontWeight: option.disabled ? 600 : "normal",
                opacity: option.disabled ? 0.75 : 1,
            },
        },
        React.createElement("span", null, labelContent),
        synonymSuffix,
        !isLeaf ? _chevronDown() : null,
        _checkIcon(checked),
    );
};


/**
 * filter / renderOption for the document-select in the footer.
 *
 * docFilter: a purely numeric search ("12" or "#12") puts the document at that position
 * first; every search also matches as a case-insensitive substring of the document's
 * name, id and info values (the precomputed option.search). Respects Mantine's limit.
 *
 * docRenderOption: the "<pos>. <name>" label, a red flag icon when flagged, and a
 * status badge styled like a light xs dmc.Badge.
 */
window.dashMantineFunctions.docFilter = function ({ options, search, limit }) {
    const max = limit || Infinity;
    const q = (search || "").trim().toLowerCase();
    if (!q) return options.slice(0, max);

    const num = /^#?\d+$/.test(q) ? parseInt(q.replace("#", ""), 10) : null;
    const exact = [];
    const rest = [];
    for (const option of options) {
        if (num !== null && option.pos === num) {
            exact.push(option);
        } else if ((option.search || option.label.toLowerCase()).includes(q)) {
            rest.push(option);
        }
    }
    return exact.concat(rest).slice(0, max);
};

// tabler:flag (filled) — flagged-document indicator.
function _flagIcon() {
    return React.createElement(
        "svg",
        {
            xmlns: "http://www.w3.org/2000/svg",
            width: 14, height: 14,
            viewBox: "0 0 24 24",
            fill: "var(--mantine-color-red-filled)",
            stroke: "var(--mantine-color-red-filled)",
            strokeWidth: 2,
            strokeLinecap: "round",
            strokeLinejoin: "round",
            style: { flexShrink: 0 },
        },
        React.createElement("path", { d: "M5 5a5 5 0 0 1 7 0a5 5 0 0 0 7 0v9a5 5 0 0 1 -7 0a5 5 0 0 0 -7 0v-9z" }),
        React.createElement("path", { d: "M5 21v-7" })
    );
}

window.dashMantineFunctions.docRenderOption = function ({ option, checked }) {
    const color = option.statusColor || "gray";
    return React.createElement(
        "span",
        { style: { display: "flex", alignItems: "center", gap: "6px", flex: 1, minWidth: 0 } },
        React.createElement(
            "span",
            {
                style: {
                    flex: 1,
                    minWidth: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    fontWeight: checked ? 600 : "normal",
                },
            },
            option.label
        ),
        option.flagged ? _flagIcon() : null,
        React.createElement(
            "span",
            {
                style: {
                    flexShrink: 0,
                    fontSize: "9px",
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.25px",
                    lineHeight: "16px",
                    height: "16px",
                    padding: "0 6px",
                    borderRadius: "1000px",
                    whiteSpace: "nowrap",
                    background: `var(--mantine-color-${color}-light)`,
                    color: `var(--mantine-color-${color}-light-color)`,
                },
            },
            option.statusLabel || option.status
        ),
    );
};
