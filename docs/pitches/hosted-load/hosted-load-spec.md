# Hosted mode under load — spec

Implements [the pitch](hosted-load-pitch.md) for [#115](https://github.com/text-harvest/tater/issues/115). Four steps, in order: re-measure memory per session, build the load test and take a first set of numbers, fix what the numbers call for, and write down what a hosting platform has to provide. Each step leaves the suite green.

## Decisions on the pitch's open questions

- **Simulated users replay a recording verbatim.** The pitch worried that recorded requests carry one moment's state and would need rewriting per user. They don't, as long as every simulated user starts its own fresh session on the same project and runs the same script: then the state each request carries is exactly the state that user's session is in. Starting the session is itself part of the recording (the upload and Start callbacks; the session cookie comes back on Start's response), so no request has to be built by hand. Each simulated user is one `requests.Session` (its own cookie jar).
- **"Same project" vs "different projects" is dropped as a scenario.** Each session parses its own copy of the uploaded documents, so two sessions on the same project cost as much as two on different ones. Step 1 checks this once with `bench_server` (same project vs different seeds); if it holds, one project per size is enough. If it doesn't, the difference goes in the results and the scenario comes back.
- **Resource limits are optional.** When `systemd-run --user --scope` works (`-p MemoryMax=… -p CPUQuota=…`), the server runs under the instance's memory and CPU. Where it doesn't (it can't reach the session bus in a Claude Code sandbox, nor without systemd), the server runs unlimited and the summary reports peak RSS against `--instance-memory-mb`. Latency under an unlimited CPU is optimistic; the summary says which mode ran.
- **Target**, from the pitch: 20 concurrent users on 10,000-document projects, Next settling within 500 ms at the 95th percentile in the probe browser, and peak RSS within 75% of the instance's memory (25% headroom). Instance size defaults to 512 MB, as in `k8s/chart/values.yaml`, and is a flag.

## Step 1: memory per session now

The committed baseline (2026-11-03, during #108) has 47 MB per extra 10,000-document realistic session (`perf/results/baseline.md`, "Hosted mode, server memory growth"). Re-run `python -m perf.bench_server --hosted --sizes 500,10000 --schema checkbox,realistic` on current `dev` and put the numbers in the step 2 results.

`bench_server._hosted_case` gains `distinct: bool = False`: when true, session k is built from `make_project(..., seed=k)` rather than one shared project. Flag `--distinct`. Run once at 10,000 realistic to confirm the per-session cost matches.

**Results (2026-11-10, `dev` at 8a66675, filled, 2 spans per document):**

| N | schema | 1 session MB | 5 sessions MB | 20 sessions MB | per extra session MB |
|---:|---|---:|---:|---:|---:|
| 500 | checkbox | 47.6 | 51.9 | 68.0 | 1.1 |
| 10,000 | checkbox | 67.8 | 155 | 480 | 21.7 |
| 500 | realistic | 48.9 | 58.3 | 94.1 | 2.4 |
| 10,000 | realistic | 92.9 | 281 | 985 | 47.0 |
| 10,000 | realistic, distinct projects | 93.1 | 307 | 1,104 | 53.2 |

The same as the 2026-11-03 baseline: #108 didn't change memory per session. Distinct projects cost 13% more, because the shared case hands every session the same document objects, so text is shared. Real hosted sessions each parse their own upload and share nothing, so **53 MB per 10,000-document realistic session** is the figure to plan with. Since the load test uploads for real, it measures the unshared cost, and there's no separate same-vs-different scenario. At that rate 20 such sessions add about 1.1 GB on top of the ~120 MB base, so the target's memory half needs about a 1.5–2 GB instance. A 512 MB instance holds about seven.

## Step 2: the load test — `perf/load.py` (new)

```
python -m perf.load --sizes 500,10000 --users 1,5,20 --modes steady,burst \
    --duration 120 --instance-memory-mb 512 [--limit] [--out perf/results/]
```

For each size: record once, then for each user count and mode, start a fresh `tater --hosted`, run the simulated users and one probe browser together for `--duration` seconds, and collect results. Plus two one-off scenarios per size (session start, session limit). Writes `perf/results/<date>-<sha>-load.{csv,md}`; `perf/results/load-baseline.{csv,md}` is committed, as `baseline.*` is for `perf.run`.

### Recording

`record(size, schema="realistic", docs=30) -> Recording`, with Playwright against a hosted server started by `perf.server.run_tater(hosted=True)`:

1. `start`: open `/`, set the project's `schema.json` and `documents.json` (from `perf.synthetic.write_project`) on `#upload-schema input[type=file]` and `#upload-documents input[type=file]`, click `#btn-start`, wait for `/annotate`, `wait_loaded`, `wait_quiet`.
2. Then, for each of `docs` documents, the actions below, each labelled, with `wait_quiet` between them:
   - `category`: pick a radio option.
   - `reviewed`: tick the checkbox.
   - `notes`: type 8 characters into the `notes` text area (`press_sequentially`, as `perf.actions.type_text`).
   - `span`: `perf.browser.select_word` + the Support tag button.
   - `next`: `#btn-next`, `wait_position`.
3. Every tenth document, a `reload` action: `page.reload()`, `wait_loaded`.

Requests are captured with `page.on("request")` / `page.on("requestfinished")` / `page.on("requestfailed")`, keeping only requests to the server's origin whose path is `/`, `/annotate`, `/_dash-layout`, `/_dash-dependencies` or ends in `/_dash-update-component` (static assets are cached by real browsers and left out). Recording at 10,000 documents holds the upload (~3 MB) three times over; that's fine at this size, unlike the full-store uploads that #108 removed.

```python
@dataclass
class RecordedRequest:
    method: str          # "GET" | "POST"
    path: str
    body: str | None     # POST body, verbatim
    t_send: float        # seconds from the action's start
    t_done: float
    status: int

@dataclass
class RecordedAction:
    label: str           # "start", "category", "reviewed", "notes", "span", "next", "reload"
    doc: int             # 1-based position when the action ran
    requests: list[RecordedRequest]

@dataclass
class Recording:
    size: int
    schema: str
    sha: str             # perf.run._git_sha() — a recording is only valid for the code it was made with
    actions: list[RecordedAction]
```

Saved as gzipped JSON in the run's work directory and reused by every scenario of that size in the run; never committed.

### Replay

`replay_action(session, base_url, action) -> ActionTiming` sends one action's requests in recorded order, keeping the recorded concurrency: request k waits for every request j that finished before k was sent in the recording (`t_done_j <= t_send_k`), and no others. `_dependencies(requests) -> list[set[int]]` computes that and is unit-tested. Requests run on a small per-user `ThreadPoolExecutor(4)`.

```python
@dataclass
class ActionTiming:
    label: str
    user: int
    started: float       # time.time()
    ms: float            # first send to last response
    errors: list[str]    # status differing from the recording, or a connection error
```

A status that differs from the recording (e.g. 500 when the session has gone, or 200 where the recording had 204) is an error, not a crash: the user carries on, and errors are counted per action.

`SimulatedUser(k, recording, base_url, mode, rng)` runs `start` and then the rest of the actions in order, on its own thread:

- `steady`: between actions, sleep a think time drawn from an exponential distribution with mean 3 s (`random.Random(k)`), so users drift apart as real annotators do.
- `burst`: no think time before `next`; all users wait on one `threading.Barrier` before each `next`, so every Next lands at once. Other actions are as in `steady`.

Users start 1 s apart, so twenty uploads don't arrive in the same instant (the session-start scenario measures that separately). When a user reaches the end of the recording before `--duration` is up, it stops; `docs=30` covers about four minutes at the steady pace.

### Probe browser

One Playwright page per run, its own session (it runs the same `start` flow as the recording), using `perf.measure.ActionRecorder` to time the `next`, `tick` and `type_notes` actions, round-robin, every 5 s while the simulated users run. They come from `perf.actions.make_actions(Scenario(size, "realistic", annotations_path=None, ...))`, picked by name; none of the three reads `annotations_path`. These are the numbers the target is judged on: settle time includes clientside work, which the replay can't see. Hosted mode has no annotations file, so actions that read it (`reload_resume`) aren't used.

### Server measurements

`perf.server.run_tater` gains `env: dict | None` (merged into the subprocess environment, for `TATER_SESSION_CACHE_MAX`) and `limit: tuple[int, float] | None` (memory MB, CPU fraction), which prefixes the command with `systemd-run --user --scope -q -p MemoryMax=<mb>M -p CPUQuota=<pct>%` and raises a clear error if that fails. A sampler thread reads `psutil.Process(pid)` every 0.5 s (RSS, `cpu_percent`), including children.

### Scenarios and results

Per size × users × mode, one CSV row per action label:

| column | meaning |
|---|---|
| `size`, `users`, `mode`, `limited` | the scenario; `limited` = ran under `systemd-run` limits |
| `action` | label (`next`, `notes`, …), or `probe:next` etc. for the probe browser |
| `count`, `p50_ms`, `p95_ms`, `max_ms` | over all users' timings of that action (probe rows: settle times) |
| `errors` | timings with any error |
| `rss_peak_mb`, `rss_per_session_mb`, `cpu_peak_pct` | server, repeated on each row of the scenario |

`rss_per_session_mb` = (RSS once every user has started − RSS before the first) / users.

One-off scenarios, per size, in the Markdown summary:

- **Session start:** one user's `start` action alone, then 5 at once: time to `/annotate` loaded, and the RSS peak during it against the RSS after.
- **Session limit:** `TATER_SESSION_CACHE_MAX=3`, 5 users in `steady` mode, started 10 s apart. Records which users got errors and from which action. Before step 3 this is expected to show users 1 and 2 dropped mid-work; after, nobody active is dropped.
- **Memory after sessions end:** RSS after the session-limit run's users have stopped and 3 new sessions have pushed theirs out, against RSS at the start. Says whether memory comes back to the OS; no fix is planned if it doesn't, only a note.

The Markdown summary starts with the target check: one line, PASS or FAIL, for 20 users at 10,000 documents in `steady` mode (probe `next` p95 ≤ 500 ms; peak RSS ≤ 0.75 × instance memory), and if it fails on memory, the instance size that would pass (peak RSS / 0.75, rounded up to the next 0.5 GB).

### Tests

`tests/test_load.py` (new, no browser, no server): `_dependencies` on sequential, parallel and mixed recordings; percentile and summary helpers; `Recording` JSON round-trip. The load test itself isn't run by pytest — like `perf.run`, it's a tool, run by hand.

## Step 3: fixes

### Always: least recently used eviction, with a lock

New class `SessionCache` in `tater/ui/runner.py`, replacing the bare `OrderedDict` in `run_hosted`:

```python
class SessionCache:
    def __init__(self, max_size: int): ...
    def get(self, session_id: str) -> TaterApp | None     # moves the hit to the end (most recent)
    def add(self, session_id: str, app: TaterApp) -> None # evicts least recently used past max_size
    def __contains__(self, session_id) -> bool
    def __len__(self) -> int
```

All methods hold one `threading.Lock`: the server is threaded, and `get` (every callback request, via `_get_hosted_app_fn`) now mutates the order while `add` evicts. `_get_hosted_app_fn`, `_on_session_ready` and `serve_layout` use it. `tests/test_hosted_mode.py`'s two eviction tests, which exercise a copy of the `OrderedDict` pattern rather than tater's code, are replaced by tests of `SessionCache`: least recently used goes first, a `get` saves a session from eviction, below the limit nothing goes, and concurrent `get`/`add` from threads leave it consistent.

### Always: say when a session has ended

`serve_layout`'s cache-miss branch (cookie present, session gone) passes `notice=` to `build_upload_layout`, which shows it as a `dmc.Alert` (color "yellow") above the tabs: "Your annotation session has ended, because the server restarted or had too many sessions. Annotations you hadn't downloaded are lost." `build_upload_layout(show_disclaimer, notice=None)`; no notice on a first visit.

Callbacks that arrive for a session that has gone (the page is still open) fail as now; the replay counts them. Making the open page notice is left for later unless the session-limit results show it matters.

### Browser test — `TestHostedEviction` in `tests/test_browser.py`

Its own hosted server per test (`run_tater(..., hosted=True, env={"TATER_SESSION_CACHE_MAX": "2"})`), sessions as in `TestHosted`:

- `test_active_session_is_kept`: sessions A and B start; A makes an edit; C starts; A reloads and still has its edit; B reloads and gets the upload page with the notice.
- `test_ended_session_shows_notice`: covered by the B half above; asserted separately so a failure names it.

### Only if the results call for it

Each is done in this step if its condition holds, otherwise recorded in the results as not needed:

- **Limit by size, not count** — if 20 sessions at 10,000 documents exceed the instance by more than the per-session cost of a small project explains. Add `TATER_SESSION_DOCS_MAX` (total documents across cached sessions); `SessionCache.add` evicts least recently used until under both limits. Documents are a cheap proxy for memory; the results give the MB per document to choose it with.
- **Production server** — if probe `next` p95 misses the target while `cpu_peak_pct` stays under 80% of the available CPU (the server waits rather than computes). Then run hosted mode on `waitress` (pure Python, one process, threads, so sessions keep working) behind `--server waitress`, added as an optional dependency, and re-measure.

After the fixes, re-run step 2 and commit the results as `perf/results/load-baseline.*`.

## Step 4: what a hosting platform has to provide

README, new subsection "Deploying hosted mode" under the hosted-mode section:

- memory per instance: base RSS + per-session MB × expected sessions, with 25% headroom — with the measured numbers for 500 and 10,000 documents, checkbox and realistic, and the cache limit to set to match;
- exactly one instance, or sticky sessions (until sessions live outside the process);
- `TATER_SECRET_KEY` set, the same for every instance;
- no scale-to-zero or deploys while people are annotating — both drop every session;
- the platform-neutral wording of each, then one line on where Azure Container Apps keeps each setting (Scale: min/max replicas; Ingress: session affinity; Containers: environment, CPU/memory). The Azure demo isn't changed.

`CLAUDE.md`: the hosted-mode section's session cache paragraph (least recently used, `SessionCache`, the notice), the perf section (`perf.load`, its baseline, the target), the test-file list (`test_load.py`, `TestHostedEviction`).

## Done when

- `perf/results/load-baseline.md` has the target check, per-scenario tables and the one-off scenarios, from a run after step 3.
- The session-limit scenario shows no active user dropped.
- `uv run pytest tests/ --headless` passes, including the new tests.
- README has "Deploying hosted mode" with measured numbers.
- Anything the results show needs a redesign (sessions outside the process, a smaller per-session footprint) is written up as a new idea issue with the numbers.
