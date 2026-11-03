/**
 * Span annotation support for Tater.
 *
 * Provides:
 *  - window.dash_clientside.tater.captureSelection  (clientside callback)
 *    Called when an entity-type button is clicked; captures the current text
 *    selection and returns {text, start, end, tag, ts} to the selection store.
 *
 *  - window.dash_clientside.tater.captureDelete  (clientside callback)
 *    Fired by the hidden proxy button; returns window._taterDeletePending
 *    to the delete store so the server callback can remove the span.
 *
 *  - Floating tooltip: a single <div id="tater-span-tooltip"> appended to
 *    <body> (outside document-content) that shows the entity label and a
 *    × delete button when the mouse enters a <mark data-start> element.
 *
 *  - Active-entity highlighting: the most recently clicked entity type button
 *    (per widget) has its spans shown filled; other entity types' spans in the
 *    same widget are shown outlined.  Other widgets are unaffected.
 */


// ---------- clientside namespace — initialised first so Dash can find these
//            functions even if pattern-matching callbacks fire early ----------
//
// Use Object.assign onto the existing object rather than replacing it, so any
// hash-keyed references the Dash renderer stored internally are preserved.

window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.tater = window.dash_clientside.tater || {};

// ---------- dot-path helpers used by span callbacks ----------

/**
 * Decode a widget schema_id (ld, path, tf) to a dot-notation field path.
 *
 * Mirrors _decode_field_path() in tater/ui/callbacks/core.py.
 *
 * For standalone widgets (ld == ""):  tf is the full pipe-encoded path.
 * For repeater items: ld = pipe-joined list fields, path = dot-joined indices,
 * tf = item-relative pipe-encoded field (possibly group-prefixed).
 */
function _taterDecodePath(ld, path, tf) {
    var tfDot = tf.replace(/\|/g, '.');
    if (!ld) { return tfDot; }
    var listFields = ld.split('|');
    var indices = path.split('.');
    var parts = [];
    for (var i = 0; i < listFields.length; i++) {
        parts.push(listFields[i]);
        if (i < indices.length) { parts.push(indices[i]); }
    }
    parts.push(tfDot);
    return parts.join('.');
}

// Return the dot-path up to and including the deepest numeric index segment,
// or null if the path contains no numeric segment (i.e. not a repeater item field).
// e.g. "findings.0.kind" → "findings.0"
//      "findings.0.evidence.2.tag" → "findings.0.evidence.2"
//      "label" → null
function _taterListItemPath(dotPath) {
    var parts = dotPath.split('.');
    for (var i = parts.length - 1; i >= 0; i--) {
        if (!isNaN(parts[i]) && parts[i] !== '') {
            return parts.slice(0, i + 1).join('.');
        }
    }
    return null;
}

function _taterGet(obj, dotPath) {
    var keys = dotPath.split('.');
    var cur = obj;
    for (var i = 0; i < keys.length; i++) {
        if (cur == null) { return null; }
        cur = cur[keys[i]];
    }
    return cur != null ? cur : null;
}

function _taterSet(obj, dotPath, value) {
    var keys = dotPath.split('.');
    var cur = obj;
    for (var i = 0; i < keys.length - 1; i++) {
        var k = keys[i];
        if (cur[k] == null) { cur[k] = isNaN(keys[i + 1]) ? {} : []; }
        cur = cur[k];
    }
    cur[keys[keys.length - 1]] = value;
    return obj;
}

// Collect {dotPath, pipePath, spans, colors} for every span field in an annotation.
// colorMap keys are template pipe paths with numeric segments removed,
// e.g. "tests|relevant_spans".
function _taterSpanInstances(ann, colorMap) {
    var instances = [];
    function walk(obj, dot, pipe) {
        if (obj == null || typeof obj !== 'object') { return; }
        if (Array.isArray(obj)) {
            for (var i = 0; i < obj.length; i++) {
                walk(obj[i], dot ? dot + '.' + i : String(i), pipe ? pipe + '|' + i : String(i));
            }
        } else {
            var keys = Object.keys(obj);
            for (var j = 0; j < keys.length; j++) {
                var k = keys[j];
                var val = obj[k];
                var newDot = dot ? dot + '.' + k : k;
                var newPipe = pipe ? pipe + '|' + k : k;
                var templateKey = newPipe.split('|').filter(function(s) { return isNaN(s); }).join('|');
                if (templateKey in colorMap) {
                    instances.push({
                        dotPath: newDot,
                        pipePath: newPipe,
                        spans: Array.isArray(val) ? val : [],
                        colors: colorMap[templateKey] || {}
                    });
                } else {
                    walk(val, newDot, newPipe);
                }
            }
        }
    }
    walk(ann, '', '');
    return instances;
}


Object.assign(window.dash_clientside.tater, {

    // ---- addSpan: trim whitespace, check overlaps, append to annotation ----
    addSpan: function(selection, docId, triggerData, annotationsData) {
        var nu = window.dash_clientside.no_update;
        if (!selection || !docId || !annotationsData) { return nu; }

        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || !ctx.triggered.length) { return nu; }

        var propId = ctx.triggered[0].prop_id;
        var triggeredId;
        try { triggeredId = JSON.parse(propId.split('.data')[0]); } catch(e) { return nu; }
        var pipeField = triggeredId.field;
        if (!pipeField) { return nu; }
        var dotField = pipeField.replace(/\|/g, '.');

        var start = selection.start;
        var end   = selection.end;
        var tag   = selection.tag;
        var text  = selection.text || '';
        if (start == null || end == null || !tag) { return nu; }

        // Trim leading/trailing whitespace and adjust offsets
        var trimmed = text.replace(/^\s+/, '');
        start += text.length - trimmed.length;
        trimmed = trimmed.replace(/\s+$/, '');
        end = start + trimmed.length;
        text = trimmed;
        if (!text) { return nu; }

        var ann = annotationsData[docId];
        if (!ann) { return nu; }

        var currentSpans = _taterGet(ann, dotField) || [];
        for (var i = 0; i < currentSpans.length; i++) {
            var s = currentSpans[i];
            if (start < s.end && end > s.start) { return nu; }
        }

        var newAnn = JSON.parse(JSON.stringify(ann));
        var newSpans = (JSON.parse(JSON.stringify(currentSpans))).concat([
            {start: start, end: end, text: text, tag: tag}
        ]);
        _taterSet(newAnn, dotField, newSpans);
        var newAnnotationsData = Object.assign({}, annotationsData, {[docId]: newAnn});

        var prevCount = (triggerData && typeof triggerData === 'object') ? (triggerData.count || 0) : (triggerData || 0);
        return {count: prevCount + 1, annotations_update: newAnnotationsData};
    },

    // ---- relaySpanTriggers: unpack annotation update, increment span-any-change ----
    relaySpanTriggers: function(_allTriggers, globalCount) {
        var nu = window.dash_clientside.no_update;
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || !ctx.triggered.length || !ctx.triggered[0].value) {
            return [nu, nu];
        }
        var val = ctx.triggered[0].value;
        var annUpdate = (val && typeof val === 'object') ? (val.annotations_update || nu) : nu;
        return [(globalCount || 0) + 1, annUpdate];
    },

    // ---- deleteSpan: remove matching span from annotation ----
    deleteSpan: function(deleteData, docId, globalCount, annotationsData) {
        var nu = window.dash_clientside.no_update;
        if (!deleteData || !docId || !annotationsData) { return [nu, nu]; }

        var pipeField = deleteData.field;
        var delStart  = deleteData.start;
        var delEnd    = deleteData.end;
        if (!pipeField || delStart == null || delEnd == null) { return [nu, nu]; }

        var dotField = pipeField.replace(/\|/g, '.');
        var ann = annotationsData[docId];
        if (!ann) { return [nu, nu]; }

        var currentSpans = _taterGet(ann, dotField) || [];
        var newSpans = currentSpans.filter(function(s) {
            return !(s.start === delStart && s.end === delEnd);
        });

        var newAnn = JSON.parse(JSON.stringify(ann));
        _taterSet(newAnn, dotField, newSpans);
        var newAnnotationsData = Object.assign({}, annotationsData, {[docId]: newAnn});
        return [(globalCount || 0) + 1, newAnnotationsData];
    },

    // ---- renderDocumentSpans: rebuild document-content marks in the browser ----
    // Fires on both nav (rawText Input) and span edits (_anyChange Input).
    renderDocumentSpans: function(rawText, _anyChange, docId, annotationsData, colorMap) {
        var nu = window.dash_clientside.no_update;
        if (!docId || rawText === null || rawText === undefined || !annotationsData || !colorMap) { return nu; }

        var ann = annotationsData[docId];
        if (!ann) { return rawText; }

        var instances = _taterSpanInstances(ann, colorMap);

        var allSpans = [];
        for (var i = 0; i < instances.length; i++) {
            var inst = instances[i];
            for (var j = 0; j < inst.spans.length; j++) {
                var sp = inst.spans[j];
                var color = inst.colors[sp.tag] || '#ffe066';
                allSpans.push({
                    start: sp.start, end: sp.end, text: sp.text, tag: sp.tag,
                    pipePath: inst.pipePath, color: color
                });
            }
        }

        if (!allSpans.length) { return rawText; }

        allSpans.sort(function(a, b) { return a.start - b.start; });

        var components = [];
        var pos = 0;
        for (var k = 0; k < allSpans.length; k++) {
            var sp = allSpans[k];
            if (sp.start < pos) { continue; }
            if (sp.start > pos) { components.push(rawText.slice(pos, sp.start)); }
            components.push({
                type: 'Mark',
                namespace: 'dash_html_components',
                props: {
                    children: sp.text,
                    'data-start': sp.start,
                    'data-end': sp.end,
                    'data-field': sp.pipePath,
                    'data-tag': sp.tag,
                    'data-color': sp.color,
                    style: {
                        backgroundColor: sp.color
                    }
                }
            });
            pos = sp.end;
        }
        if (pos < rawText.length) { components.push(rawText.slice(pos)); }
        return components.length ? components : rawText;
    },

    // ---- loadValues: push annotation values into non-boolean widget value props ----
    // Replaces the server-side load_values callback.  Reads annotations-store and
    // ev-lookup-store directly in the browser — no server round-trip on doc nav.
    // Output IDs come from ctx.outputs_list; ev-lookup keys are tf-encoded field paths.
    loadValues: function(docId, _trigger, annotationsData, evLookup) {
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.outputs_list) { return []; }
        var outputs = ctx.outputs_list;
        if (!outputs.length) { return []; }
        var nu = window.dash_clientside.no_update;
        var ann = (annotationsData && docId) ? annotationsData[docId] : null;
        return outputs.map(function(out) {
            var id = out.id;
            var dotField = _taterDecodePath(id.ld || '', id.path || '', id.tf || '');
            // If this widget is a repeater item and its list item doesn't exist yet
            // in the annotation (e.g. a phantom fire during an add before
            // applyRepeaterOp has run), preserve the server-rendered value.
            var itemPath = _taterListItemPath(dotField);
            if (itemPath !== null && (!ann || _taterGet(ann, itemPath) == null)) { return nu; }
            var v = ann ? _taterGet(ann, dotField) : null;
            if (v === null || v === undefined) {
                v = (evLookup && id.tf in evLookup) ? evLookup[id.tf] : null;
            }
            return v !== undefined ? v : null;
        });
    },

    // ---- loadChecked: push annotation values into boolean widget checked props ----
    // Same as loadValues but coerces to boolean and defaults to false.
    loadChecked: function(docId, _trigger, annotationsData, evLookup) {
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.outputs_list) { return []; }
        var outputs = ctx.outputs_list;
        if (!outputs.length) { return []; }
        var nu = window.dash_clientside.no_update;
        var ann = (annotationsData && docId) ? annotationsData[docId] : null;
        return outputs.map(function(out) {
            var id = out.id;
            var dotField = _taterDecodePath(id.ld || '', id.path || '', id.tf || '');
            // Same phantom-fire guard as loadValues.
            var itemPath = _taterListItemPath(dotField);
            if (itemPath !== null && (!ann || _taterGet(ann, itemPath) == null)) { return nu; }
            var v = ann ? _taterGet(ann, dotField) : null;
            if (v === null || v === undefined) {
                v = (evLookup && id.tf in evLookup) ? evLookup[id.tf] : null;
            }
            return (v !== null && v !== undefined) ? Boolean(v) : false;
        });
    },

    // ---- captureValue: write non-boolean widget value to annotations-store ----
    // Replaces the server-side capture_values callback.  Runs in the browser so
    // annotations-store is always current (no stale-State race with span adds).
    // Also handles auto-advance: increments auto-advance-store when the changed
    // field is in aaFields and the value actually changed.
    captureValue: function(_allValues, docId, annotationsData, aaFields) {
        var nu = window.dash_clientside.no_update;
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || !ctx.triggered.length) { return [nu, nu]; }
        var t = ctx.triggered[0];
        if (!t || t.value === undefined) { return [nu, nu]; }
        if (!docId || !annotationsData) { return [nu, nu]; }

        var tid;
        try { tid = JSON.parse(t.prop_id.split('.value')[0]); } catch(e) { return [nu, nu]; }
        var dotField = _taterDecodePath(tid.ld || '', tid.path || '', tid.tf || '');
        var value = t.value === '' ? null : t.value;

        var ann = annotationsData[docId];
        if (!ann) { return [nu, nu]; }

        // Guard: if this widget is a repeater item (dotField has a numeric index),
        // verify the list item actually exists in the annotation before writing.
        // Prevents stale DOM components from a previous document creating phantom
        // list entries when loadValues fires before update_repeater re-renders.
        var itemPath = _taterListItemPath(dotField);
        if (itemPath !== null && _taterGet(ann, itemPath) == null) { return [nu, nu]; }

        var oldValue = _taterGet(ann, dotField);
        if (JSON.stringify(value) === JSON.stringify(oldValue)) { return [nu, nu]; }
        var newAnn = JSON.parse(JSON.stringify(ann));
        _taterSet(newAnn, dotField, value);
        var newAnnotations = Object.assign({}, annotationsData, {[docId]: newAnn});

        var advanceUpdate = nu;
        if (Array.isArray(aaFields) && aaFields.indexOf(dotField) !== -1) {
            if (value !== oldValue && value !== null) {
                advanceUpdate = (window._taterAutoAdvanceCount || 0) + 1;
                window._taterAutoAdvanceCount = advanceUpdate;
            }
        }
        return [newAnnotations, advanceUpdate];
    },

    // ---- captureChecked: write boolean widget value to annotations-store ----
    // Same as captureValue but for the checked prop; no empty-string conversion,
    // and auto-advance does not require a truthy value.
    captureChecked: function(_allChecked, docId, annotationsData, aaFields) {
        var nu = window.dash_clientside.no_update;
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || !ctx.triggered.length) { return [nu, nu]; }
        var t = ctx.triggered[0];
        if (!t || t.value === undefined) { return [nu, nu]; }
        if (!docId || !annotationsData) { return [nu, nu]; }

        var tid;
        try { tid = JSON.parse(t.prop_id.split('.checked')[0]); } catch(e) { return [nu, nu]; }
        var dotField = _taterDecodePath(tid.ld || '', tid.path || '', tid.tf || '');
        var value = t.value;

        var ann = annotationsData[docId];
        if (!ann) { return [nu, nu]; }

        // Same stale-DOM guard as captureValue.
        var itemPath = _taterListItemPath(dotField);
        if (itemPath !== null && _taterGet(ann, itemPath) == null) { return [nu, nu]; }

        var oldValue = _taterGet(ann, dotField);
        if (value === oldValue) { return [nu, nu]; }
        var newAnn = JSON.parse(JSON.stringify(ann));
        _taterSet(newAnn, dotField, value);
        var newAnnotations = Object.assign({}, annotationsData, {[docId]: newAnn});

        var advanceUpdate = nu;
        if (Array.isArray(aaFields) && aaFields.indexOf(dotField) !== -1) {
            if (value !== oldValue) {
                advanceUpdate = (window._taterAutoAdvanceCount || 0) + 1;
                window._taterAutoAdvanceCount = advanceUpdate;
            }
        }
        return [newAnnotations, advanceUpdate];
    },

    // ---- applyFieldOp: apply a {field, value} descriptor to annotations-store ----
    // Used by HL relay callbacks (hl-select-relay, hl-multi-relay).
    applyFieldOp: function(_allRelays, docId, annotationsData) {
        var nu = window.dash_clientside.no_update;
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || !ctx.triggered.length) { return nu; }
        var val = ctx.triggered[0].value;
        if (!val || !val.field) { return nu; }
        if (!docId || !annotationsData) { return nu; }
        var ann = annotationsData[docId];
        if (!ann) { return nu; }
        var newAnn = JSON.parse(JSON.stringify(ann));
        _taterSet(newAnn, val.field, val.value !== undefined ? val.value : null);
        return Object.assign({}, annotationsData, {[docId]: newAnn});
    },

    // ---- hlSelectAutoAdvance: trigger auto-advance after a hl-select-relay write ----
    // Fires after applyFieldOp has written the value to annotations-store.
    // Increments auto-advance-store when the relay carried a non-null value and the
    // field is in aaFields.  Uses a window-global counter (same pattern as captureValue)
    // to avoid reading auto-advance-store as both Output and State.
    hlSelectAutoAdvance: function(_allRelays, aaFields) {
        var nu = window.dash_clientside.no_update;
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || !ctx.triggered.length) { return nu; }
        var val = ctx.triggered[0].value;
        if (!val || !val.field || val.value == null) { return nu; }
        if (!Array.isArray(aaFields) || aaFields.indexOf(val.field) === -1) { return nu; }
        var next = (window._taterAutoAdvanceCount || 0) + 1;
        window._taterAutoAdvanceCount = next;
        return next;
    },

    // ---- applyRepeaterOp: apply add/delete descriptor to annotations-store ----
    // Runs clientside so it reads the CURRENT browser-side annotations (including any
    // clientside span adds that haven't been reflected in server-side State yet).
    // Always increments repeater-load-trigger so loadValues re-fires after the
    // re-render, pushing correct values from the current annotations-store into all
    // items (existing items may have been re-rendered with stale server-side State).
    applyRepeaterOp: function(_allRelays, docId, annotationsData, spanCount, loadTrigger) {
        var nu = window.dash_clientside.no_update;
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || !ctx.triggered.length) { return [nu, nu, nu]; }
        // Iterate through all triggered entries — a re-rendered nested repeater may
        // emit a null relay store first, which must not block the real op.
        var val = null;
        for (var i = 0; i < ctx.triggered.length; i++) {
            var v = ctx.triggered[i].value;
            if (v && v.op) { val = v; break; }
        }
        if (!val) { return [nu, nu, nu]; }
        if (!docId || !annotationsData) { return [nu, nu, nu]; }

        var ann = annotationsData[docId];
        if (!ann) { return [nu, nu, nu]; }

        // field is stored as dot-path (e.g. "findings" or "findings.0.annotations")
        var dotField = val.field;
        var currentList = _taterGet(ann, dotField);
        if (!Array.isArray(currentList)) { return [nu, nu, nu]; }

        var newList = currentList.slice();
        var isDelete = false;

        if (val.op === 'delete') {
            if (val.pos < 0 || val.pos >= newList.length) { return [nu, nu, nu]; }
            newList.splice(val.pos, 1);
            isDelete = true;
        } else if (val.op === 'add') {
            newList.push(val.item !== undefined ? val.item : null);
        } else {
            return [nu, nu, nu];
        }

        var newAnn = JSON.parse(JSON.stringify(ann));
        _taterSet(newAnn, dotField, newList);
        var newAnnotationsData = Object.assign({}, annotationsData, {[docId]: newAnn});
        return [
            newAnnotationsData,
            isDelete ? (spanCount || 0) + 1 : nu,
            (loadTrigger || 0) + 1,
        ];
    },

    // ---- updateNavInfo: update document title, metadata, progress bar and nav buttons ----
    // Fires clientside immediately on current-doc-id change — no server round-trip needed
    // since all required information is preloaded in doc-list-store at layout time.
    updateNavInfo: function(docId, docListStore) {
        var nu = window.dash_clientside.no_update;
        if (!docId || !docListStore) { return [nu, nu, nu, nu, nu, nu, nu]; }
        var idx = docListStore.index[docId];
        if (idx === undefined) { return [nu, nu, nu, nu, nu, nu, nu]; }
        var total = docListStore.total;
        var isLast = idx === total - 1;

        // Toggle containers via display:contents (visible, transparent to layout) or display:none.
        // The buttons' own styles (border, flex) remain static in the layout — only the
        // containers are toggled, so dmc.Button never receives a dynamic style object.
        return [
            (idx + 1) + " / " + total,
            docListStore.metadata[docId] || "",
            ((idx + 1) / total) * 100,
            idx === 0,
            isLast,
            isLast ? {"display": "none"} : {"display": "contents"},
            isLast ? {"display": "contents"} : {"display": "none"},
        ];
    },

    // ---- updateSpanCounts: update badge children + style for all span-count elements ----
    updateSpanCounts: function(_anyChange, docId, annotationsData) {
        var nu = window.dash_clientside.no_update;
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.outputs_list || !ctx.outputs_list[0]) { return [nu, nu]; }

        var countOutputs = ctx.outputs_list[0];
        if (!countOutputs.length) { return [nu, nu]; }

        // Build counts map: pipePath -> tag -> count directly from outputs field paths
        var counts = {};
        if (docId && annotationsData) {
            var ann = annotationsData[docId];
            if (ann) {
                // Collect unique field paths from the outputs and count spans
                var seenFields = {};
                for (var fi = 0; fi < countOutputs.length; fi++) {
                    var fld = countOutputs[fi].id.field;
                    if (seenFields[fld]) { continue; }
                    seenFields[fld] = true;
                    var dotPath = fld.replace(/\|/g, '.');
                    var spans = _taterGet(ann, dotPath);
                    if (!Array.isArray(spans)) { continue; }
                    counts[fld] = {};
                    for (var si = 0; si < spans.length; si++) {
                        var t = spans[si].tag;
                        counts[fld][t] = (counts[fld][t] || 0) + 1;
                    }
                }
            }
        }

        // Build parallel output arrays
        var childrenArr = [];
        var classArr = [];
        for (var k = 0; k < countOutputs.length; k++) {
            var id = countOutputs[k].id;
            var field = id.field;
            var tag = id.tag;
            var count = (counts[field] && counts[field][tag]) ? counts[field][tag] : 0;
            childrenArr.push(String(count));
            classArr.push(count > 0 ? 'tater-count-badge tater-count-visible' : 'tater-count-badge');
        }
        return [childrenArr, classArr];
    },

    captureSelection: function (_n_clicks_list) {
        var ctx = window.dash_clientside.callback_context;
        if (!ctx || !ctx.triggered || !ctx.triggered.length) {
            return window.dash_clientside.no_update;
        }

        var propId = ctx.triggered[0].prop_id;
        var btnId;
        try {
            btnId = JSON.parse(propId.split('.n_clicks')[0]);
        } catch (e) {
            return window.dash_clientside.no_update;
        }
        var tag = btnId.tag;
        if (!tag) { return window.dash_clientside.no_update; }

        var selection = window.getSelection();
        if (!selection || selection.rangeCount === 0 || selection.toString().trim() === '') {
            return window.dash_clientside.no_update;
        }

        var selectedText = selection.toString();
        var range = selection.getRangeAt(0);
        var docEl = document.getElementById('document-content');
        if (!docEl || !docEl.contains(range.commonAncestorContainer)) {
            return window.dash_clientside.no_update;
        }

        var preRange = range.cloneRange();
        preRange.selectNodeContents(docEl);
        preRange.setEnd(range.startContainer, range.startOffset);
        var start = preRange.toString().length;
        var end = start + selectedText.length;

        _savedDocScroll = docEl.scrollTop;
        selection.removeAllRanges();
        return { text: selectedText, start: start, end: end, tag: tag, ts: Date.now() };
    },

    captureDelete: function (_n_clicks) {
        var d = window._taterDeletePending;
        if (!d) { return window.dash_clientside.no_update; }
        window._taterDeletePending = null;
        return d;
    },

    // ---- addSpanFromPopup: read pending popup data and add span to annotations ----
    // Mirrors captureDelete: reads window._taterPopupPending set by span_popup.js
    // and writes directly to span-any-change + annotations-store (no relay needed).
    addSpanFromPopup: function (_n_clicks, docId, globalCount, annotationsData) {
        var nu = window.dash_clientside.no_update;
        var d = window._taterPopupPending;
        if (!d || !docId || !annotationsData) { return [nu, nu]; }
        window._taterPopupPending = null;

        var pipeField = d.field;
        var text      = d.text || '';
        var start     = d.start;
        var end       = d.end;
        var tag       = d.tag;
        if (!pipeField || !tag || start == null || end == null) { return [nu, nu]; }

        // Trim leading/trailing whitespace and adjust offsets (mirrors addSpan logic)
        var trimmed = text.replace(/^\s+/, '');
        start += text.length - trimmed.length;
        trimmed = trimmed.replace(/\s+$/, '');
        end = start + trimmed.length;
        if (!trimmed) { return [nu, nu]; }

        var dotField = pipeField.replace(/\|/g, '.');
        var ann = annotationsData[docId];
        if (!ann) { return [nu, nu]; }

        var currentSpans = _taterGet(ann, dotField) || [];
        for (var i = 0; i < currentSpans.length; i++) {
            if (start < currentSpans[i].end && end > currentSpans[i].start) { return [nu, nu]; }
        }

        var newAnn = JSON.parse(JSON.stringify(ann));
        _taterSet(newAnn, dotField, currentSpans.concat([
            { start: start, end: end, text: trimmed, tag: tag }
        ]));
        return [
            (globalCount || 0) + 1,
            Object.assign({}, annotationsData, { [docId]: newAnn }),
        ];
    }

});


// ---------- inject CSS for faded (inactive) spans ----------
// !important is required here because renderDocumentSpans sets background-color
// as an inline style on <mark> elements; a plain CSS rule cannot override that.
// The widget-outlined fade uses a plain CSS class in span_annotations.css instead.

(function () {
    var s = document.createElement('style');
    s.textContent =
        'mark[data-start].tater-span-outlined {' +
        '  background-color: var(--tater-mark-faded, rgba(200,200,200,0.25)) !important;' +
        '}';
    document.head.appendChild(s);
})();


// ---------- active-entity tracking + span styling ----------
// Pipe-encoded field path of the most recently clicked SpanAnnotationWidget,
// or null.  data-tater-field on button containers and data-field on marks both
// hold the full pipe-encoded path (e.g. "findings|0|spans"), so no separate
// data-tater-index is needed.

window._taterActiveWidget = window._taterActiveWidget || null;

/** Convert a 6-digit hex color to rgba with the given alpha (0–1). */
function hexToRgba(hex, alpha) {
    var h = hex.replace('#', '');
    var r = parseInt(h.slice(0, 2), 16);
    var g = parseInt(h.slice(2, 4), 16);
    var b = parseInt(h.slice(4, 6), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
}

/**
 * Apply filled or faded styling to every <mark data-start> in the document.
 *
 * For each mark:
 *   - If no active widget is recorded, OR its data-field matches the active key
 *     → filled (remove class).
 *   - Otherwise → faded background (add class + set --tater-mark-faded).
 */
function applySpanStyles() {
    var active = window._taterActiveWidget;

    // Collect all button containers; key = data-tater-field (full pipe-encoded path).
    var containers = document.querySelectorAll('[data-tater-field]');
    var containerKeys = [];
    for (var j = 0; j < containers.length; j++) {
        containerKeys.push(containers[j].getAttribute('data-tater-field'));
    }

    // If the active key no longer exists (e.g. after navigating to a document
    // with fewer list items), reset to the first available container.
    if (active && containerKeys.length > 0 && containerKeys.indexOf(active) === -1) {
        active = containerKeys[0];
        window._taterActiveWidget = active;
    }

    var marks = document.querySelectorAll('mark[data-start]');
    for (var i = 0; i < marks.length; i++) {
        var mark  = marks[i];
        var key   = mark.getAttribute('data-field');   // full pipe-encoded path
        var color = mark.getAttribute('data-color') || '#ffe066';

        if (!active || key === active) {
            mark.classList.remove('tater-span-outlined');
        } else {
            mark.style.setProperty('--tater-mark-faded', hexToRgba(color, 0.25));
            mark.classList.add('tater-span-outlined');
        }
    }

    for (var k = 0; k < containers.length; k++) {
        if (!active || containerKeys[k] === active) {
            containers[k].classList.remove('tater-widget-outlined');
        } else {
            containers[k].classList.add('tater-widget-outlined');
        }
    }
}


// ---------- initialise active widget on page load + watch for new ones ----------
// watchAnnotationPanel() is started immediately so the MutationObserver is ready
// before any repeater items are added (the list may start empty).  activate() is
// called by both the observer (on new additions) and directly on page load so that
// any [data-tater-field] elements already in the DOM are activated right away.

(function () {
    var debounceTimer = null;
    var knownFieldKeys = {};

    function watchAnnotationPanel() {
        var panel = document.getElementById('tater-annotation-panel');
        if (!panel) { setTimeout(watchAnnotationPanel, 200); return; }

        // Seed known fields from whatever is already in the DOM
        var existing = document.querySelectorAll('[data-tater-field]');
        for (var e = 0; e < existing.length; e++) {
            knownFieldKeys[existing[e].getAttribute('data-tater-field')] = true;
        }

        new MutationObserver(function (mutations) {
            var newFieldKey = null;
            for (var m = 0; m < mutations.length; m++) {
                var added = mutations[m].addedNodes;
                for (var n = 0; n < added.length; n++) {
                    var node = added[n];
                    if (node.nodeType === 1 && node.querySelector) {
                        var el = node.querySelector('[data-tater-field]');
                        if (el) {
                            var key = el.getAttribute('data-tater-field');
                            if (!(key in knownFieldKeys)) { newFieldKey = key; }
                        }
                    }
                }
            }
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function () {
                // Rebuild known-keys from current DOM so deletions are handled
                var current = document.querySelectorAll('[data-tater-field]');
                knownFieldKeys = {};
                for (var i = 0; i < current.length; i++) {
                    knownFieldKeys[current[i].getAttribute('data-tater-field')] = true;
                }
                if (newFieldKey) {
                    // A genuinely new repeater item appeared — auto-activate it
                    window._taterActiveWidget = newFieldKey;
                } else if (!window._taterActiveWidget) {
                    var first = document.querySelector('[data-tater-field]');
                    if (first) { window._taterActiveWidget = first.getAttribute('data-tater-field'); }
                }
                applySpanStyles();
            }, 50);
        }).observe(panel, { childList: true, subtree: true });
    }

    // Activate any elements already in the DOM on page load
    if (!window._taterActiveWidget) {
        var first = document.querySelector('[data-tater-field]');
        if (first) { window._taterActiveWidget = first.getAttribute('data-tater-field'); }
    }
    applySpanStyles();

    // Start observer immediately so it catches the first repeater item added
    watchAnnotationPanel();
})();


// ---------- click listener for entity buttons ----------
// Each button group is wrapped in an html.Div with data-tater-field carrying
// the full pipe-encoded field path.  We detect clicks via this attribute,
// independent of the Dash callback chain, so the active widget is updated
// even when no text is selected.

document.addEventListener('click', function (e) {
    var container = e.target.closest('[data-tater-field]');
    if (!container) { return; }
    var activeKey = container.getAttribute('data-tater-field');
    if (activeKey) {
        window._taterActiveWidget = activeKey;
        applySpanStyles();
    }
}, true);


// ---------- scroll preservation ----------
// Saves document-content scrollTop before a server round-trip and restores it
// after Dash replaces the element's children.  Also re-applies span styles.

var _savedDocScroll = null;

(function () {
    function restoreScroll() {
        if (_savedDocScroll === null) { return; }
        var el = document.getElementById('document-content');
        if (el) { el.scrollTop = _savedDocScroll; }
        _savedDocScroll = null;
    }

    function afterDocUpdate() {
        restoreScroll();
        applySpanStyles();
    }

    function setupObserver() {
        var el = document.getElementById('document-content');
        if (!el) { setTimeout(setupObserver, 200); return; }
        new MutationObserver(function () {
            requestAnimationFrame(afterDocUpdate);
        }).observe(el, { childList: true, subtree: false });
    }
    setupObserver();
})();


// ---------- floating tooltip ----------

(function () {
    var tooltip = null;
    var hideTimer = null;

    function ensureTooltip() {
        if (tooltip) { return tooltip; }
        tooltip = document.createElement('div');
        tooltip.id = 'tater-span-tooltip';
        document.body.appendChild(tooltip);

        tooltip.addEventListener('mouseenter', function () {
            clearTimeout(hideTimer);
        });
        tooltip.addEventListener('mouseleave', function () {
            scheduleHide();
        });
        return tooltip;
    }

    function scheduleHide() {
        clearTimeout(hideTimer);
        hideTimer = setTimeout(function () {
            if (tooltip) { tooltip.style.display = 'none'; }
        }, 150);
    }

    function showTooltip(mark) {
        clearTimeout(hideTimer);
        var t = ensureTooltip();

        var tag   = mark.getAttribute('data-tag')   || '';
        var field = mark.getAttribute('data-field') || '';
        var start = mark.getAttribute('data-start') || '';
        var end   = mark.getAttribute('data-end')   || '';
        var color = mark.getAttribute('data-color') || '#ffe066';

        // Rebuild tooltip contents — the entire popup IS the colored label
        t.innerHTML = '';
        t.style.backgroundColor = color;
        t.appendChild(document.createTextNode(tag));

        var btn = document.createElement('button');
        btn.className = 'tater-tooltip-delete';
        btn.textContent = 'x';
        btn.addEventListener('click', function () {
            var docEl = document.getElementById('document-content');
            if (docEl) { _savedDocScroll = docEl.scrollTop; }
            // field is the full pipe-encoded path (e.g. "findings|0|spans")
            window._taterDeletePending = {
                field: field,
                start: parseInt(start, 10),
                end:   parseInt(end,   10),
                ts:    Date.now()
            };
            var proxy = document.getElementById('span-delete-proxy');
            if (proxy) { proxy.click(); }
            t.style.display = 'none';
        });
        t.appendChild(btn);

        // Show first so getBoundingClientRect is meaningful
        t.style.display = 'inline-flex';

        requestAnimationFrame(function () {
            var margin   = 8;
            var markRect = mark.getBoundingClientRect();
            var tRect    = t.getBoundingClientRect();

            var left = markRect.left + markRect.width / 2 - tRect.width / 2;
            left = Math.max(margin, Math.min(window.innerWidth - tRect.width - margin, left));

            var top = markRect.top - tRect.height - 4;
            if (top < margin) { top = markRect.bottom + 4; }

            t.style.left = left + 'px';
            t.style.top  = top  + 'px';
        });
    }

    document.addEventListener('mouseover', function (e) {
        var mark = e.target.closest('mark[data-start]');
        if (mark) { showTooltip(mark); }
    }, true);

    document.addEventListener('mouseout', function (e) {
        var mark = e.target.closest('mark[data-start]');
        if (mark) { scheduleHide(); }
    }, true);
})();
