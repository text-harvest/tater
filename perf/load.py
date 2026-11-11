"""Hosted mode under load (#115): simulated users plus a probe browser against one server.

    uv run python -m perf.load --sizes 500,10000 --users 1,5,20 --modes steady,burst \\
        --duration 120 --instance-memory-mb 512 [--limit] [--out perf/results/]

For each project size, one annotation session is recorded with Playwright: uploading the
project, Start, then labelled actions on each document. Each simulated user replays that
recording verbatim on its own fresh session (its own cookie), keeping the recorded order
and concurrency, with think time between actions. The state a request carries is the
state that user's session is in, because every user starts the same project and runs the
same script. A probe browser times Next, tick and typing meanwhile: settle time includes
clientside work, which the replay can't see, so the target is judged on the probe.

Needs Playwright's Chromium once per machine: ``uv run playwright install chromium``.
"""
import argparse
import csv
import datetime
import gzip
import json
import math
import random
import statistics
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import psutil
import requests
from playwright.sync_api import Page, sync_playwright

from perf.actions import Scenario, make_actions
from perf.browser import INIT_SCRIPT, control, select_word, wait_loaded, wait_position, wait_quiet
from perf.measure import ActionRecorder
from perf.run import _git_sha
from perf.server import ServerInfo, run_tater
from perf.synthetic import LENGTHS, make_project, write_project

SCHEMA = "realistic"
THINK_MEAN_S = 3.0          # mean pause between a simulated user's actions (exponential)
USER_STAGGER_S = 1.0        # simulated users start this far apart
PROBE_EVERY_S = 5.0
PROBE_ACTIONS = ("next", "tick", "type_notes")
HEADROOM = 0.75             # peak RSS may use this share of the instance's memory
TARGET = {"size": 10_000, "users": 20, "mode": "steady", "next_p95_ms": 500}
RECORDED_PATHS = ("/", "/annotate", "/_dash-layout", "/_dash-dependencies")
COLUMNS = ["size", "users", "mode", "limited", "action", "count", "p50_ms", "p95_ms", "max_ms", "errors",
           "rss_peak_mb", "rss_per_session_mb", "cpu_peak_pct"]


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

@dataclass
class RecordedRequest:
    method: str
    path: str
    body: Optional[str]     # POST body, verbatim
    t_send: float           # seconds from the action's start
    t_done: float
    status: int


@dataclass
class RecordedAction:
    label: str              # "start", "category", "reviewed", "notes", "span", "next", "reload"
    doc: int                # 1-based position when the action ran
    requests: list[RecordedRequest] = field(default_factory=list)


@dataclass
class Recording:
    size: int
    schema: str
    sha: str                # a recording is only valid for the code it was made with
    actions: list[RecordedAction]

    def save(self, path: Path) -> None:
        with gzip.open(path, "wt") as f:
            json.dump(asdict(self), f)

    @classmethod
    def load(cls, path: Path) -> "Recording":
        with gzip.open(path, "rt") as f:
            d = json.load(f)
        actions = [RecordedAction(a["label"], a["doc"], [RecordedRequest(**r) for r in a["requests"]])
                   for a in d.pop("actions")]
        return cls(actions=actions, **d)


def _recorded(url: str, origin: str) -> bool:
    if not url.startswith(origin):
        return False
    path = urlparse(url).path
    return path in RECORDED_PATHS or path.endswith("/_dash-update-component")


def start_session(page: Page, url: str, project_dir: Path) -> None:
    """Upload the project in ``project_dir`` on the hosted upload page and start annotating."""
    page.goto(url + "/")
    page.set_input_files("#upload-schema input[type=file]", str(project_dir / "schema.json"))
    wait_quiet(page)
    page.set_input_files("#upload-documents input[type=file]", str(project_dir / "documents.json"))
    wait_quiet(page)
    page.click("#btn-start")
    page.wait_for_url("**/annotate", timeout=300_000)
    wait_loaded(page, timeout=300_000)
    wait_quiet(page)


def _annotate_doc(page: Page, k: int, label: str) -> None:
    """One recorded action on the current document (position k)."""
    if label == "category":
        page.locator(f"input[type=radio][value={'normal' if k % 2 else 'abnormal'}]").check()
    elif label == "reviewed":
        control(page, "reviewed").click()
    elif label == "notes":
        control(page, "notes").press_sequentially("abcdefgh", delay=50)
    elif label == "span":
        select_word(page, k)
        page.locator("""[id*='"type":"span-add-btn"'][id*='"tag":"Support"']""").click()
    elif label == "next":
        page.click("#btn-next")
        wait_position(page, k + 1)
    elif label == "reload":
        page.reload()
        wait_loaded(page, timeout=300_000)


def record(browser, project_dir: Path, size: int, docs: int, work: Path) -> Recording:
    """Record one hosted annotation session on the project in ``project_dir``."""
    rec = Recording(size=size, schema=SCHEMA, sha=_git_sha(), actions=[])
    current: dict = {"action": None, "t0": 0.0}
    sent: dict = {}   # playwright Request -> (action, t_send)

    def on_request(req):
        if current["action"] is not None and _recorded(req.url, origin):
            sent[req] = (current["action"], time.time() - current["t0"])

    def on_done(req):
        if req not in sent:
            return
        action, t_send = sent.pop(req)
        resp = req.response() if req.failure is None else None
        action.requests.append(RecordedRequest(
            req.method, urlparse(req.url).path, req.post_data, round(t_send, 4),
            round(time.time() - current["t0"], 4) if action is current["action"] else t_send,
            resp.status if resp else 0))

    def run(label: str, k: int, fn) -> None:
        action = RecordedAction(label, k)
        current["action"], current["t0"] = action, time.time()
        fn()
        wait_quiet(page)
        current["action"] = None
        action.requests.sort(key=lambda r: r.t_send)
        rec.actions.append(action)

    with run_tater(work / "record-server", hosted=True) as server:
        origin = server.url
        ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
        ctx.add_init_script(INIT_SCRIPT)
        page = ctx.new_page()
        page.set_default_timeout(120_000)
        page.on("request", on_request)
        page.on("requestfinished", on_done)
        page.on("requestfailed", on_done)
        run("start", 1, lambda: start_session(page, server.url, project_dir))
        for k in range(1, docs + 1):
            if k > 1 and k % 10 == 1:
                run("reload", k, lambda: _annotate_doc(page, k, "reload"))
            for label in ("category", "reviewed", "notes", "span", "next"):
                run(label, k, lambda: _annotate_doc(page, k, label))
        ctx.close()
    return rec


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def _dependencies(reqs: list[RecordedRequest]) -> list[set[int]]:
    """For each request, the earlier ones it waits for: those that had finished before it
    was sent in the recording. Requests in flight together stay concurrent."""
    return [{j for j in range(k) if reqs[j].t_done <= reqs[k].t_send} for k in range(len(reqs))]


@dataclass
class ActionTiming:
    label: str
    user: int
    started: float          # time.time()
    ms: float               # first send to last response
    errors: list[str]


def replay_action(session: requests.Session, base_url: str, action: RecordedAction, pool: ThreadPoolExecutor,
                  user: int = 0) -> ActionTiming:
    """Send one action's requests in recorded order and concurrency; time the whole action."""
    errors: list[str] = []

    def send(r: RecordedRequest) -> None:
        try:
            if r.method == "POST":
                resp = session.post(base_url + r.path, data=r.body, timeout=300,
                                    headers={"Content-Type": "application/json"})
            else:
                resp = session.get(base_url + r.path, timeout=300)
            if resp.status_code != r.status:
                errors.append(f"{r.path} {resp.status_code} (recorded {r.status})")
        except requests.RequestException as e:
            errors.append(f"{r.path} {type(e).__name__}")

    deps = _dependencies(action.requests)
    started = time.time()
    t0 = time.perf_counter()
    futures = []
    for k, r in enumerate(action.requests):
        for j in deps[k]:
            futures[j].result()
        futures.append(pool.submit(send, r))
    for f in futures:
        f.result()
    return ActionTiming(action.label, user, started, (time.perf_counter() - t0) * 1000, errors)


class SimulatedUser(threading.Thread):
    """Replays the recording on its own session until it ends or the deadline passes."""

    def __init__(self, k: int, recording: Recording, base_url: str, mode: str, deadline: float,
                 timings: list, lock: threading.Lock, barrier: Optional[threading.Barrier], started: threading.Semaphore):
        super().__init__(daemon=True)
        self.k, self.recording, self.base_url, self.mode, self.deadline = k, recording, base_url, mode, deadline
        self.timings, self.lock, self.barrier, self.started = timings, lock, barrier, started
        self.rng = random.Random(k)
        self.first_error: Optional[str] = None

    def _pause(self, label: str) -> None:
        if self.mode == "burst" and label == "next" and self.barrier is not None:
            try:
                self.barrier.wait(timeout=60)
                return
            except threading.BrokenBarrierError:
                pass
        time.sleep(min(self.rng.expovariate(1 / THINK_MEAN_S), 15))

    def run(self) -> None:
        session = requests.Session()
        with ThreadPoolExecutor(4) as pool:
            for i, action in enumerate(self.recording.actions):
                if i and time.time() >= self.deadline:
                    break
                if i:
                    self._pause(action.label)
                t = replay_action(session, self.base_url, action, pool, self.k)
                with self.lock:
                    self.timings.append(t)
                if t.errors and self.first_error is None:
                    self.first_error = f"{action.label}@doc{action.doc}: {t.errors[0]}"
                if i == 0:
                    self.started.release()
        if self.barrier is not None:
            self.barrier.abort()   # don't leave the others waiting at the next Next


# ---------------------------------------------------------------------------
# Server sampling and the probe browser
# ---------------------------------------------------------------------------

class Sampler(threading.Thread):
    """Samples the server's RSS (MB) and CPU (%) every ``interval`` s, including child processes."""

    def __init__(self, pid: int, interval: float = 0.5):
        super().__init__(daemon=True)
        self.interval = interval
        self.proc = psutil.Process(pid)
        self.rss_peak = 0.0
        self.cpu_peak = 0.0
        self.stopping = threading.Event()

    def rss(self) -> float:
        try:
            procs = [self.proc, *self.proc.children(recursive=True)]
            return sum(p.memory_info().rss for p in procs) / 1e6
        except psutil.Error:
            return 0.0

    def run(self) -> None:
        self.proc.cpu_percent(None)
        while not self.stopping.wait(self.interval):
            self.rss_peak = max(self.rss_peak, self.rss())
            try:
                self.cpu_peak = max(self.cpu_peak, self.proc.cpu_percent(None))
            except psutil.Error:
                pass


def run_probe(browser, server: ServerInfo, project_dir: Path, size: int, deadline: float) -> dict[str, list[float]]:
    """A real browser on its own session, timing PROBE_ACTIONS round-robin until the deadline."""
    ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_init_script(INIT_SCRIPT)
    page = ctx.new_page()
    page.set_default_timeout(120_000)
    settle: dict[str, list[float]] = {name: [] for name in PROBE_ACTIONS}
    try:
        start_session(page, server.url, project_dir)
        recorder = ActionRecorder(page, server)
        actions = {a.name: a for a in make_actions(Scenario(size, SCHEMA, None, recorder.wait_quiet, random.Random(0)))}
        i = 0
        while time.time() < deadline:
            name = PROBE_ACTIONS[i % len(PROBE_ACTIONS)]
            a = actions[name]
            result = recorder.run_once(f"probe:{name}", a.run, a.setup)
            settle[name].append(result.settle_ms)
            i += 1
            page.wait_for_timeout(PROBE_EVERY_S * 1000)
    finally:
        ctx.close()
    return settle


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile; 0 for no values."""
    if not values:
        return 0.0
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def _stats(values: list[float]) -> dict:
    return {"count": len(values), "p50_ms": round(percentile(values, 50)), "p95_ms": round(percentile(values, 95)),
            "max_ms": round(max(values) if values else 0)}


def run_users(recording: Recording, server: ServerInfo, n_users: int, mode: str, duration: float,
              stagger: float = USER_STAGGER_S, browser=None, project_dir: Optional[Path] = None,
              sampler: Optional[Sampler] = None) -> tuple[list[ActionTiming], dict, list[SimulatedUser], float]:
    """Run n_users simulated users (and, with ``browser``, the probe) until ``duration`` is up.
    Returns the timings, the probe's settle times, the users, and RSS once all had started."""
    timings: list[ActionTiming] = []
    lock = threading.Lock()
    started = threading.Semaphore(0)
    deadline = time.time() + duration
    barrier = threading.Barrier(n_users) if mode == "burst" and n_users > 1 else None
    users = [SimulatedUser(k, recording, server.url, mode, deadline, timings, lock, barrier, started)
             for k in range(n_users)]
    # Memory per session: the first session also pays one-time costs (registering the
    # shared callbacks), so with several users count from after the first has started.
    rss_before = sampler.rss() if sampler else 0.0
    users[0].start()
    started.acquire(timeout=600)
    rss_first = sampler.rss() if sampler else 0.0
    for u in users[1:]:
        time.sleep(stagger)
        u.start()
    for _ in users[1:]:
        started.acquire(timeout=600)
    rss_all = sampler.rss() if sampler else 0.0
    rss_started = (rss_all - rss_first) / (n_users - 1) if n_users > 1 else rss_first - rss_before
    probe = run_probe(browser, server, project_dir, recording.size, deadline) if browser else {}
    for u in users:
        u.join(timeout=max(0.0, deadline - time.time()) + 600)
    return timings, probe, users, rss_started


def scenario_rows(size: int, n_users: int, mode: str, limited: bool, timings: list[ActionTiming],
                  probe: dict, sampler: Sampler, rss_per_session: float) -> list[dict]:
    base = {"size": size, "users": n_users, "mode": mode, "limited": limited}
    server = {"rss_peak_mb": round(sampler.rss_peak), "rss_per_session_mb": round(rss_per_session, 1),
              "cpu_peak_pct": round(sampler.cpu_peak)}
    rows = []
    for label in dict.fromkeys(t.label for t in timings):
        ts = [t for t in timings if t.label == label]
        rows.append(base | {"action": label} | _stats([t.ms for t in ts])
                    | {"errors": sum(1 for t in ts if t.errors)} | server)
    for name, values in probe.items():
        rows.append(base | {"action": f"probe:{name}"} | _stats(values) | {"errors": 0} | server)
    return rows


def target_check(rows: list[dict], instance_mb: int) -> str:
    """One line: does the target scenario pass, and if memory fails, what size would."""
    t = TARGET
    match = [r for r in rows if r["size"] == t["size"] and r["users"] == t["users"] and r["mode"] == t["mode"]]
    probe = next((r for r in match if r["action"] == "probe:next"), None)
    if not probe:
        return f"Target ({t['users']} users, {t['size']:,} documents, {t['mode']}): not run."
    fast = probe["p95_ms"] <= t["next_p95_ms"]
    fits = probe["rss_peak_mb"] <= HEADROOM * instance_mb
    verdict = "PASS" if fast and fits else "FAIL"
    parts = [f"probe Next p95 {probe['p95_ms']} ms (≤ {t['next_p95_ms']})",
             f"peak RSS {probe['rss_peak_mb']} MB (≤ {HEADROOM:.0%} of {instance_mb} MB)"]
    line = f"**Target {verdict}** ({t['users']} users, {t['size']:,} documents, {t['mode']}): " + "; ".join(parts)
    if not fits:
        needed_gb = math.ceil(probe["rss_peak_mb"] / HEADROOM / 512) / 2
        line += f". Memory needs an instance of about {needed_gb:g} GB."
    return line


def _md_table(rows: list[dict]) -> str:
    cols = ["action", "count", "p50_ms", "p95_ms", "max_ms", "errors"]
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---:" if c != "action" else "---" for c in cols) + "|"]
    out += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def summary_markdown(rows: list[dict], oneoffs: list[str], header: str, instance_mb: int) -> str:
    lines = [header, "", target_check(rows, instance_mb), "",
             "Simulated-user rows time the server only: an action's requests, first sent to last answered. "
             "`probe:` rows are a real browser's settle time, including clientside work; `probe:type_notes` "
             "includes about 1 s of typing (20 characters, 50 ms apart). Memory per session counts from after "
             "the first session, which also pays one-time costs; with one user it's that first session's cost.", ""]
    keys = list(dict.fromkeys((r["size"], r["users"], r["mode"], r["limited"]) for r in rows))
    for size, users, mode, limited in keys:
        rs = [r for r in rows if (r["size"], r["users"], r["mode"], r["limited"]) == (size, users, mode, limited)]
        lines += [f"## {size:,} documents, {users} users, {mode}" + (" (limited)" if limited else ""), "",
                  f"Server: peak RSS {rs[0]['rss_peak_mb']} MB, {rs[0]['rss_per_session_mb']} MB per session, "
                  f"peak CPU {rs[0]['cpu_peak_pct']}% (100% = one core).", "", _md_table(rs), ""]
    lines += oneoffs
    return "\n".join(lines) + "\n"


def oneoff_session_start(recording: Recording, work: Path, limit) -> str:
    with run_tater(work / "oneoff-start", hosted=True, limit=limit) as server:
        sampler = Sampler(server.pid, interval=0.05)   # a start can take well under a second
        sampler.start()
        lines = [f"### Session start, {recording.size:,} documents", ""]
        start_only = Recording(recording.size, recording.schema, recording.sha, recording.actions[:1])
        for n in (1, 5):
            before = sampler.rss()
            sampler.rss_peak = before
            timings, _, _, _ = run_users(start_only, server, n, "steady", duration=0, stagger=0)
            after = sampler.rss()
            ms = [t.ms for t in timings]
            lines.append(f"- {n} at once: start p50 {percentile(ms, 50):.0f} ms, max {max(ms):.0f} ms; "
                         f"RSS +{after - before:.0f} MB after, peak +{sampler.rss_peak - before:.0f} MB during; "
                         f"errors {sum(1 for t in timings if t.errors)}")
        sampler.stopping.set()
    return "\n".join(lines) + "\n"


LIMIT_STAGGER_S = 10
LIMIT_DURATION_S = 90   # users 0 and 1 are still working when users 3 and 4 (30 s, 40 s) push them out


def oneoff_session_limit(recording: Recording, work: Path, limit) -> str:
    """TATER_SESSION_CACHE_MAX=3, five users 10 s apart: who gets dropped, and memory after."""
    with run_tater(work / "oneoff-limit", hosted=True, limit=limit, env={"TATER_SESSION_CACHE_MAX": "3"}) as server:
        sampler = Sampler(server.pid)
        sampler.start()
        rss_start = sampler.rss()
        _, _, users, _ = run_users(recording, server, 5, "steady", duration=LIMIT_DURATION_S, stagger=LIMIT_STAGGER_S)
        rss_end = sampler.rss()
        start_only = Recording(recording.size, recording.schema, recording.sha, recording.actions[:1])
        run_users(start_only, server, 3, "steady", duration=0, stagger=0)
        rss_after = sampler.rss()
        sampler.stopping.set()
    lines = [f"### Session limit (cache of 3, 5 users 10 s apart), {recording.size:,} documents", ""]
    lines += [f"- user {u.k}: " + (f"first error at {u.first_error}" if u.first_error else "no errors") for u in users]
    lines += ["", f"Memory: {rss_start:.0f} MB at start, {rss_end:.0f} MB with 3 sessions after the run, "
                  f"{rss_after:.0f} MB once 3 new sessions had replaced them.", ""]
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", default="500,10000")
    parser.add_argument("--users", default="1,5,20")
    parser.add_argument("--modes", default="steady,burst")
    parser.add_argument("--duration", type=float, default=120.0, help="seconds per scenario")
    parser.add_argument("--docs", type=int, default=30, help="documents in the recorded session")
    parser.add_argument("--instance-memory-mb", type=int, default=512)
    parser.add_argument("--instance-cpu", type=float, default=0.5)
    parser.add_argument("--limit", action="store_true", help="run the server under the instance's limits (systemd-run)")
    parser.add_argument("--no-oneoffs", action="store_true", help="skip the session-start and session-limit runs")
    parser.add_argument("--out", default="perf/results/")
    args = parser.parse_args(argv)

    limit = (args.instance_memory_mb, args.instance_cpu) if args.limit else None
    sha = _git_sha()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"{datetime.date.today().isoformat()}-{sha}-load"
    header = (f"# Load run {datetime.date.today().isoformat()} {sha}\n\n`python -m perf.load "
              f"{' '.join(argv) if argv else ''}`".rstrip() + f" — {args.duration:g} s per scenario, "
              f"server {'limited to' if limit else 'unlimited; compared with'} {args.instance_memory_mb} MB"
              + (f" / {args.instance_cpu:g} CPU" if limit else "") + ".")
    rows: list[dict] = []
    oneoffs: list[str] = []
    t_start = time.time()
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        work = Path(tmp)
        browser = pw.chromium.launch()
        for size in (int(s) for s in args.sizes.split(",")):
            project_dir = work / f"project-{size}"
            write_project(make_project(size, LENGTHS["short"], filled=False, schema=SCHEMA), project_dir)
            print(f"recording {size:,} documents ...", flush=True)
            recording = record(browser, project_dir, size, args.docs, work)
            recording.save(work / f"recording-{size}.json.gz")
            expected_s = (len(recording.actions) - 1) * THINK_MEAN_S
            if expected_s < max(args.duration, LIMIT_DURATION_S):
                print(f"  note: the recording lasts about {expected_s:.0f} s at the steady pace; users that "
                      f"reach its end stop early (--docs to lengthen it)", flush=True)
            for n_users in (int(u) for u in args.users.split(",")):
                for mode in args.modes.split(","):
                    if mode == "burst" and n_users == 1:
                        continue
                    print(f"{size:,} documents, {n_users} users, {mode} ...", flush=True)
                    with run_tater(work / f"server-{size}-{n_users}-{mode}", hosted=True, limit=limit) as server:
                        sampler = Sampler(server.pid)
                        sampler.start()
                        timings, probe, _, per_session = run_users(
                            recording, server, n_users, mode, args.duration, browser=browser,
                            project_dir=project_dir, sampler=sampler)
                        sampler.stopping.set()
                    new = scenario_rows(size, n_users, mode, bool(limit), timings, probe, sampler, per_session)
                    rows += new
                    for r in new:
                        print(f"  {r['action']:14} n={r['count']:4} p50 {r['p50_ms']:6} p95 {r['p95_ms']:6} ms "
                              f"err {r['errors']}", flush=True)
                    print(f"  server peak {new[0]['rss_peak_mb']} MB, {new[0]['rss_per_session_mb']} MB/session, "
                          f"CPU {new[0]['cpu_peak_pct']}%", flush=True)
            if not args.no_oneoffs:
                print(f"one-off scenarios, {size:,} documents ...", flush=True)
                oneoffs.append(oneoff_session_start(recording, work, limit))
                oneoffs.append(oneoff_session_limit(recording, work, limit))
                print(oneoffs[-2] + oneoffs[-1], flush=True)
            with open(f"{stem}.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS)
                w.writeheader()
                w.writerows(rows)
            minutes = (time.time() - t_start) / 60
            Path(f"{stem}.md").write_text(summary_markdown(rows, oneoffs, header + f" {minutes:.0f} min.", args.instance_memory_mb))
        browser.close()
    print(f"wrote {stem}.csv and {stem}.md")
    print(target_check(rows, args.instance_memory_mb))


if __name__ == "__main__":
    main()
