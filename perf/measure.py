"""Per-action browser measurements with Playwright: requests, bytes, settle time, long tasks, memory."""
import statistics
import time
from dataclasses import dataclass, field, fields
from typing import Callable, Optional

import psutil
from playwright.sync_api import Page, Request

from perf.server import ServerInfo
from perf.trace_report import flags_for, read_trace

# Sums long tasks (>50 ms) since the last reset; installed before any page script runs.
INIT_SCRIPT = """
window.__taterLongTaskMs = 0;
new PerformanceObserver(list => {
    for (const e of list.getEntries()) { window.__taterLongTaskMs += e.duration; }
}).observe({type: 'longtask', buffered: true});
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


def _is_callback(request: Request) -> bool:
    return "_dash-update-component" in request.url


class ActionRecorder:
    """Watches a page's Dash callback requests and measures one action at a time.

    The page needs INIT_SCRIPT installed (``context.add_init_script``) for long tasks.
    """

    def __init__(self, page: Page, server: ServerInfo):
        self.page = page
        self.server = server
        self._requests: list[Request] = []
        self._in_flight: set[Request] = set()
        self._last_done = time.perf_counter()
        page.on("request", self._on_request)
        page.on("requestfinished", self._on_done)
        page.on("requestfailed", self._on_done)

    def _on_request(self, request: Request) -> None:
        if _is_callback(request):
            self._requests.append(request)
            self._in_flight.add(request)

    def _on_done(self, request: Request) -> None:
        if request in self._in_flight:
            self._in_flight.discard(request)
            self._last_done = time.perf_counter()

    def wait_quiet(self, quiet: float = QUIET_S, timeout: float = SETTLE_TIMEOUT_S) -> None:
        """Wait until no Dash request has been in flight for ``quiet`` seconds."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.page.wait_for_timeout(50)
            if (not self._in_flight and time.perf_counter() - self._last_done >= quiet
                    and self.page.title() != "Updating..."):
                return
        raise TimeoutError(f"page still busy after {timeout:.0f} s ({len(self._in_flight)} requests in flight)")

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
        self.page.evaluate("window.__taterLongTaskMs = 0")
        first = len(self._requests)
        start = time.perf_counter()
        check = action(self.page)
        returned = time.perf_counter()
        self.wait_quiet()
        reqs = self._requests[first:]

        down = 0
        for r in reqs:
            try:
                down += r.sizes()["responseBodySize"]
            except Exception:  # failed or aborted request
                pass
        lines = [l for l in read_trace(self.server.trace_path) if l["action"] == label] if self.server.trace_path else []
        self.set_trace_label("")
        return ActionResult(
            label=label,
            requests=len(reqs),
            up_kb=sum(len(r.post_data_buffer or b"") for r in reqs) / 1000,
            down_kb=down / 1000,
            server_ms=sum(l["ms"] for l in lines),
            settle_ms=(max(self._last_done, returned) - start) * 1000 if reqs else (returned - start) * 1000,
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
