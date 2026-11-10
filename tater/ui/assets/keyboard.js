/**
 * Tater client-side utilities.
 *
 * Named clientside callbacks (referenced by name so they are always available
 * regardless of when Dash registers them):
 *   window.dash_clientside.tater.updateTimer
 */

window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.tater = window.dash_clientside.tater || {};

Object.assign(window.dash_clientside.tater, {
    updateTimer: function(n_intervals, timing_data) {
        if (!timing_data) return ["Doc time: 0s", "tabler:player-pause"];
        var paused = timing_data.paused || false;
        var base = timing_data.annotation_seconds_at_load || 0;
        var total = base;
        if (!paused && timing_data.doc_start_time) {
            total += Date.now() / 1000 - timing_data.doc_start_time;
        }
        total = Math.floor(total);
        var text;
        if (total < 60) {
            text = "Doc time: " + total + "s";
        } else if (total < 3600) {
            var m = Math.floor(total / 60);
            var s = total % 60;
            text = "Doc time: " + m + "m " + s + "s";
        } else {
            var h = Math.floor(total / 3600);
            var m = Math.floor((total % 3600) / 60);
            text = "Doc time: " + h + "h " + m + "m";
        }
        if (paused) text += " (paused)";
        var icon = paused ? "tabler:player-play" : "tabler:player-pause";
        return [text, icon];
    }
});


/**
 * Keyboard navigation for Tater annotation tool.
 *
 * Arrow left/right: navigate to previous/next document.
 * Arrow up/down: scroll the document viewer.
 * Scroll resets to top whenever document content changes.
 */

document.addEventListener('DOMContentLoaded', function () {

    // Arrow key handler
    document.addEventListener('keydown', function (e) {
        // A focused control already used the key, e.g. a slider thumb moving with the
        // arrow keys (a div, so the check below doesn't catch it).
        if (e.defaultPrevented) {
            return;
        }
        // Don't intercept when the user is typing in an input or textarea
        const tag = document.activeElement && document.activeElement.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || (document.activeElement && document.activeElement.isContentEditable)) {
            return;
        }

        if (e.key === 'f' && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            const cb = document.getElementById('flag-document');
            if (cb) cb.click();
        } else if (e.key === 'ArrowLeft') {
            e.preventDefault();
            const btn = document.getElementById('btn-prev');
            if (btn) btn.click();
        } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            const btn = document.getElementById('btn-next');
            if (btn) btn.click();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            const el = document.getElementById('document-content');
            if (el) el.scrollBy({ top: -120, behavior: 'smooth' });
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            const el = document.getElementById('document-content');
            if (el) el.scrollBy({ top: 120, behavior: 'smooth' });
        }
    });

    // Reset scroll to top whenever the document content changes (i.e. user navigates)
    function attachScrollReset() {
        const el = document.getElementById('document-content');
        if (!el) {
            setTimeout(attachScrollReset, 100);
            return;
        }
        const observer = new MutationObserver(function () {
            el.scrollTop = 0;
        });
        observer.observe(el, { childList: true, subtree: true, characterData: true });
    }
    attachScrollReset();
});
