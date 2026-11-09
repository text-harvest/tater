"""Playwright helpers shared by the perf harness and the browser tests (tests/test_browser.py).

Pages need INIT_SCRIPT installed (``context.add_init_script``) for ``dash_counts``,
``reset_counts`` and ``wait_quiet``.
"""
import time

from playwright.sync_api import Error, Page

# Installed before any page script runs (``context.add_init_script``), on every document.
#
# Sums long tasks (>50 ms) since the last reset, and counts Dash callback requests by
# wrapping fetch: requests, bytes up/down, in flight, and when the last one finished
# (Date.now(), the same clock as Python's time.time()). The counts are kept in
# sessionStorage so they survive a reload within an action.
#
# Requests are counted in the page, not with Playwright's request events: Playwright keeps
# every request it reports, upload included, for the life of the page, and at 10k documents
# an action uploads tens of MB, which ran the runner and its driver out of memory.
INIT_SCRIPT = """
window.__taterLongTaskMs = 0;
window.__taterLongTaskEnd = 0;  // Date.now() at the end of the last long task
new PerformanceObserver(list => {
    for (const e of list.getEntries()) {
        window.__taterLongTaskMs += e.duration;
        window.__taterLongTaskEnd = Math.max(window.__taterLongTaskEnd,
            performance.timeOrigin + e.startTime + e.duration);
    }
}).observe({type: 'longtask', buffered: true});

(() => {
    const KEY = '__taterDash';
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(KEY)); } catch (e) {}
    const s = window.__taterDash = Object.assign(
        {requests: 0, up: 0, down: 0, lastDone: 0}, saved || {}, {inFlight: 0});
    const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} };
    window.__taterDashReset = () => {
        Object.assign(s, {requests: 0, up: 0, down: 0, lastDone: Date.now()}); save();
    };
    const enc = new TextEncoder();
    const origFetch = window.fetch;
    window.fetch = function (input, init) {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        if (!url.includes('_dash-update-component')) return origFetch.apply(this, arguments);
        const body = init && init.body;
        s.requests += 1;
        s.up += typeof body === 'string' ? enc.encode(body).length : 0;
        s.inFlight += 1;
        save();
        const done = () => { s.inFlight -= 1; s.lastDone = Date.now(); save(); };
        return origFetch.apply(this, arguments).then(async res => {
            const len = res.headers.get('content-length');
            s.down += len !== null ? Number(len)
                : res.status === 204 ? 0 : (await res.clone().arrayBuffer()).byteLength;
            done();
            return res;
        }, err => { done(); throw err; });
    };
})();
"""

QUIET_S = 0.5        # no Dash request in flight for this long means the page has settled
SETTLE_TIMEOUT_S = 120.0


# ---------------------------------------------------------------------------
# Position and navigation
# ---------------------------------------------------------------------------

def position(page: Page) -> int:
    """1-based position of the current document, from the "k / N" title."""
    return int(page.locator("#document-title").inner_text().split("/")[0])


def wait_position(page: Page, k: int, timeout: float = 30_000) -> None:
    page.wait_for_function(
        "k => (document.querySelector('#document-title')?.textContent || '').trim().startsWith(k + ' /')",
        arg=k, timeout=timeout,
    )


def wait_loaded(page: Page, timeout: float = 120_000) -> None:
    page.wait_for_function(
        "() => (document.querySelector('#document-title')?.textContent || '').includes(' / ')",
        timeout=timeout,
    )


def control(page: Page, tf: str):
    """A widget's input, found by the ``tf`` key of its pattern-matching ID."""
    return page.locator(f"""[id*='"tf":"{tf}"'][id*='"type":"tater-']""").first


def selector_options(page: Page):
    """The open document selector's options."""
    listbox = page.locator("#document-select").get_attribute("aria-controls")
    return page.locator(f'[id="{listbox}"] [role=option]')


def goto_doc(page: Page, k: int) -> None:
    """Jump to the document at position k with the selector, as a user would."""
    select = page.locator("#document-select")
    select.click()
    select.fill(str(k))
    selector_options(page).first.click()
    wait_position(page, k)


def select_word(page: Page, k: int) -> None:
    """Select (as a user would, for a span) word k, modulo the word count, of the longest
    stretch of untagged document text."""
    page.evaluate(
        """k => {
            const el = document.getElementById('document-content');
            const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
            let node = null, n;
            while ((n = walker.nextNode())) {
                if (!n.parentElement.closest('mark') && (!node || n.length > node.length)) { node = n; }
            }
            const words = [...node.textContent.matchAll(/\\S+/g)];
            const w = words[k % words.length];
            const range = document.createRange();
            range.setStart(node, w.index); range.setEnd(node, w.index + w[0].length);
            const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
        }""",
        k,
    )


# ---------------------------------------------------------------------------
# Request counters (INIT_SCRIPT) and settling
# ---------------------------------------------------------------------------

def dash_counts(page: Page) -> dict:
    """The page's Dash request counters (see INIT_SCRIPT) and its title:
    ``{requests, up, down, inFlight, lastDone, longTaskEnd, title}``."""
    return page.evaluate(
        "({...window.__taterDash, longTaskEnd: window.__taterLongTaskEnd, title: document.title})")


def reset_counts(page: Page) -> None:
    page.evaluate("window.__taterDashReset()")


def wait_quiet(page: Page, quiet: float = QUIET_S, timeout: float = SETTLE_TIMEOUT_S) -> None:
    """Wait until no Dash request has been in flight, and no long task has run, for
    ``quiet`` seconds. A page busy with clientside work has no request in flight, so
    requests alone would call it quiet while queued callbacks are still running."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        page.wait_for_timeout(50)
        try:
            d = dash_counts(page)
        except Error:  # the page is navigating (a reload); its counters come back after
            continue
        last = max(d["lastDone"], d["longTaskEnd"]) / 1000
        if not d["inFlight"] and time.time() - last >= quiet and d["title"] != "Updating...":
            return
    raise TimeoutError(f"page still busy after {timeout:.0f} s")
