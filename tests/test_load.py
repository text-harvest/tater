"""perf.load (#115): replay ordering, percentiles, the target check, recording round-trip.

No server and no browser: the replay runs against a fake HTTP session.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from perf.load import (
    RecordedAction, RecordedRequest, Recording, _dependencies, percentile, replay_action, target_check,
)


def req(path, t_send, t_done, method="POST", status=200):
    return RecordedRequest(method, path, "{}" if method == "POST" else None, t_send, t_done, status)


# ---------------------------------------------------------------------------
# _dependencies
# ---------------------------------------------------------------------------

def test_sequential_requests_each_wait_for_all_before():
    reqs = [req("a", 0.0, 0.1), req("b", 0.1, 0.2), req("c", 0.2, 0.3)]
    assert _dependencies(reqs) == [set(), {0}, {0, 1}]


def test_parallel_requests_dont_wait_for_each_other():
    reqs = [req("a", 0.0, 0.3), req("b", 0.01, 0.3), req("c", 0.02, 0.3)]
    assert _dependencies(reqs) == [set(), set(), set()]


def test_mixed_chain():
    # a and b in flight together; c sent after both finished; d sent while c is in flight
    reqs = [req("a", 0.0, 0.1), req("b", 0.0, 0.12), req("c", 0.15, 0.3), req("d", 0.2, 0.25)]
    assert _dependencies(reqs) == [set(), set(), {0, 1}, {0, 1}]


# ---------------------------------------------------------------------------
# replay_action against a fake session
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status):
        self.status_code = status


class FakeSession:
    """Each request takes 50 ms; records when each path started and ended."""

    def __init__(self, status=200):
        self.status = status
        self.spans = {}
        self.lock = threading.Lock()

    def _do(self, url):
        path = url.split("http://x")[1]
        t0 = time.perf_counter()
        time.sleep(0.05)
        with self.lock:
            self.spans[path] = (t0, time.perf_counter())
        return FakeResponse(self.status)

    def post(self, url, **kwargs):
        return self._do(url)

    def get(self, url, **kwargs):
        return self._do(url)


def test_replay_keeps_recorded_order_and_concurrency():
    action = RecordedAction("next", 1, [req("/a", 0.0, 0.1), req("/b", 0.0, 0.1), req("/c", 0.2, 0.3)])
    s = FakeSession()
    with ThreadPoolExecutor(4) as pool:
        timing = replay_action(s, "http://x", action, pool)
    a, b, c = s.spans["/a"], s.spans["/b"], s.spans["/c"]
    assert a[0] < b[1] and b[0] < a[1], "a and b were concurrent in the recording"
    assert c[0] >= max(a[1], b[1]), "c was sent after a and b finished"
    assert timing.errors == []
    assert 90 <= timing.ms < 1000


def test_replay_reports_status_differing_from_recording():
    action = RecordedAction("next", 1, [req("/a", 0.0, 0.1, status=204)])
    with ThreadPoolExecutor(1) as pool:
        timing = replay_action(FakeSession(status=500), "http://x", action, pool)
    assert timing.errors == ["/a 500 (recorded 204)"]


# ---------------------------------------------------------------------------
# percentile, target check, recording round-trip
# ---------------------------------------------------------------------------

def test_percentile_nearest_rank():
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile([7], 95) == 7
    assert percentile([], 95) == 0


def _probe_row(p95, rss):
    return {"size": 10_000, "users": 20, "mode": "steady", "limited": False, "action": "probe:next",
            "count": 10, "p50_ms": p95 // 2, "p95_ms": p95, "max_ms": p95, "errors": 0,
            "rss_peak_mb": rss, "rss_per_session_mb": 50, "cpu_peak_pct": 50}


def test_target_pass():
    assert target_check([_probe_row(400, 300)], instance_mb=512).startswith("**Target PASS**")


def test_target_fail_on_memory_names_the_size_needed():
    line = target_check([_probe_row(400, 1200)], instance_mb=512)
    assert line.startswith("**Target FAIL**")
    assert "about 2 GB" in line   # 1200 / 0.75 = 1600 MB -> next 0.5 GB step


def test_target_not_run():
    assert "not run" in target_check([], instance_mb=512)


def test_recording_round_trip(tmp_path):
    rec = Recording(500, "realistic", "abc123", [
        RecordedAction("start", 1, [req("/", 0.0, 0.05, method="GET"), req("/_dash-update-component", 0.1, 0.2)]),
        RecordedAction("next", 1, [req("/_dash-update-component", 0.0, 0.03, status=204)]),
    ])
    path = tmp_path / "rec.json.gz"
    rec.save(path)
    assert Recording.load(path) == rec
