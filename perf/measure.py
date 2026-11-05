"""Per-action browser measurements with Playwright: requests, bytes, settle time, long tasks, memory."""
import statistics
import time
from dataclasses import dataclass, field, fields
from typing import Callable, Optional

import psutil
from playwright.sync_api import Error, Page

from perf.server import ServerInfo
from perf.trace_report import flags_for, read_trace

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

QUIET_S = 0.5        # no Dash request in flight for this long means the action has settled
SETTLE_TIMEOUT_S = 120.0


@dataclass
class ActionResult:
    label: str
    requests: float = 0        # _dash-update-component requests
    up_kb: float = 0.0         # request bodies
    down_kb: float = 0.0       # response bodies
    server_ms: float = 0.0     # sum of trace "ms" for this action
    settle_ms: float = 0.0     # action start → last callback response
    long_task_ms: float = 0.0  # sum of long tasks (>50 ms) during the action
    heap_mb: float = 0.0       # JS heap after the action
    server_rss_mb: float = 0.0
    check: Optional[bool] = None   # the action's own correctness check, if it has one
    flags: list[str] = field(default_factory=list)

    @classmethod
    def median(cls, label: str, runs: list["ActionResult"]) -> "ActionResult":
        numeric = {f.name for f in fields(cls)} - {"label", "check", "flags"}
        checks = [r.check for r in runs if r.check is not None]
        return cls(
            label=label,
            **{name: round(statistics.median(getattr(r, name) for r in runs), 1) for name in numeric},
            check=all(checks) if checks else None,
            flags=list(dict.fromkeys(f for r in runs for f in r.flags)),
        )


class ActionRecorder:
    """Watches a page's Dash callback requests and measures one action at a time.

    The page needs INIT_SCRIPT installed (``context.add_init_script``): it counts the
    requests and long tasks that this reads.
    """

    def __init__(self, page: Page, server: ServerInfo):
        self.page = page
        self.server = server

    def _dash(self) -> dict:
        """The page's Dash request counters (see INIT_SCRIPT) and its title."""
        return self.page.evaluate(
            "({...window.__taterDash, longTaskEnd: window.__taterLongTaskEnd, title: document.title})")

    def wait_quiet(self, quiet: float = QUIET_S, timeout: float = SETTLE_TIMEOUT_S) -> None:
        """Wait until no Dash request has been in flight, and no long task has run, for
        ``quiet`` seconds. A page busy with clientside work has no request in flight, so
        requests alone would call it quiet while queued callbacks are still running."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.page.wait_for_timeout(50)
            try:
                d = self._dash()
            except Error:  # the page is navigating (a reload); its counters come back after
                continue
            last = max(d["lastDone"], d["longTaskEnd"]) / 1000
            if not d["inFlight"] and time.time() - last >= quiet and d["title"] != "Updating...":
                return
        raise TimeoutError(f"page still busy after {timeout:.0f} s")

    def set_trace_label(self, label: str) -> None:
        if self.server.trace_path:
            self.page.request.post(self.server.url + "/_tater/trace/action", data={"label": label})

    def run_once(
        self,
        label: str,
        action: Callable[[Page], Optional[bool]],
        setup: Optional[Callable[[Page], None]] = None,
        journey: bool = False,
    ) -> ActionResult:
        if setup:
            setup(self.page)
        self.wait_quiet()
        self.set_trace_label(label)
        self.page.evaluate("window.__taterLongTaskMs = 0; window.__taterDashReset()")
        start = time.time()
        check = action(self.page)
        returned = time.time()
        self.wait_quiet()
        d = self._dash()
        lines = [l for l in read_trace(self.server.trace_path) if l["action"] == label] if self.server.trace_path else []
        self.set_trace_label("")
        return ActionResult(
            label=label,
            requests=d["requests"],
            up_kb=d["up"] / 1000,
            down_kb=d["down"] / 1000,
            server_ms=sum(l["ms"] for l in lines),
            settle_ms=(max(d["lastDone"] / 1000, returned) - start) * 1000 if d["requests"] else (returned - start) * 1000,
            long_task_ms=self.page.evaluate("window.__taterLongTaskMs"),
            heap_mb=self.page.evaluate("performance.memory ? performance.memory.usedJSHeapSize : 0") / 1e6,
            server_rss_mb=psutil.Process(self.server.pid).memory_info().rss / 1e6,
            check=check,
            flags=flags_for(lines, repeats=not journey),
        )

    def measure(
        self,
        label: str,
        action: Callable[[Page], Optional[bool]],
        repeats: int = 5,
        setup: Optional[Callable[[Page], None]] = None,
        journey: bool = False,
    ) -> ActionResult:
        """Run ``action`` ``repeats`` times and return the median of each value.

        ``setup`` runs untimed before each run. ``action`` may return a bool, its
        own correctness check; the result's ``check`` is True only if every run passed.
        A ``journey`` repeats callbacks by design, so it skips the repeat flag.
        """
        runs = [self.run_once(f"{label}#{i}", action, setup, journey) for i in range(repeats)]
        return ActionResult.median(label, runs)
