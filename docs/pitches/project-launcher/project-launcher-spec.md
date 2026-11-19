# Project launcher: spec

Issue: [#82](https://github.com/text-harvest/tater/issues/82). Pitch: [project-launcher-pitch.md](project-launcher-pitch.md).

A launcher runs one project for several annotators: one single-mode tater process per annotator, behind one address, routed by who the request is from. This spec turns the pitch into files, functions and data shapes, and settles the pitch's open questions.

## Decisions on the pitch's open questions

| Question | Decision |
|---|---|
| Back door on a shared server | Each tater process accepts only requests carrying a secret the launcher gives it at start. Processes also listen on 127.0.0.1 only. Small change to tater (below). |
| Trusting the login in front | In `identity: header` mode the launcher refuses to listen on a non-loopback address unless started with `--behind-login-proxy`, which a container platform needs (it binds 0.0.0.0 but is reachable only through the platform's sign-in). The flag's help text and the docs say what it asserts. |
| Lost or leaked links | `tater-launcher reissue PROJECT NAME` issues a new link and invalidates that annotator's old link and cookies; a running launcher picks it up without a restart. |
| Wait after an idle stop | Measured on this branch: single-mode tater answers its first request 0.8–1.0 s after starting at 500 documents and 1.4 s at 10,000 (realistic schema, filled annotations, 5.6 MB layout built in under 0.1 s more). The launcher holds the request while the process starts; no "starting" page. |
| Stopping must not lose edits | Fixed by [#123](https://github.com/text-harvest/tater/issues/123) (merged): `flush_saves()` waits for a write in progress. The launcher stops processes with SIGTERM (CTRL_BREAK on Windows), which tater turns into a normal exit that flushes. |
| Icons from elsewhere | Confirmed: `DashIconify` fetches every icon from `api.iconify.design` at page load. Its bundle reads `window.IconifyPreload` first, so tater ships the icons it uses in an asset script. Separable last task. |
| Idle detection | Confirmed: the only timer in the page (`clock-interval`, the document clock) runs a clientside callback, so an idle page sends no requests. The last forwarded request is a reliable activity signal. |
| Platforms that already launch things | One experiment with JupyterHub, and a paragraph in the docs. Not code. |

## Project file

YAML (PyYAML is already a dependency). Paths are relative to the project file. Parsed into a Pydantic model `ProjectFile` in `tater/launcher/project.py`; validation errors name the key and the annotator.

```yaml
title: Pet records review          # optional; shown on launcher pages
schema: schema.json                # or config: config.py (exactly one of the two)
documents: documents.json          # every annotator's documents unless overridden
results: results                   # folder; one subfolder per annotator
identity: links                    # links | header
header: X-Forwarded-Email          # identity: header only; the header carrying the email
public_url: https://tater.lab.example.org   # optional; base for printed links
idle_minutes: 30                   # stop a process after this long without requests; 0 = never
annotators:
  - name: alice                    # [a-z0-9][a-z0-9_-]*, unique; names the results folder
    email: alice@example.org       # required with identity: header; compared case-insensitively
    documents: splits/alice.json   # optional; overrides the project's documents
  - name: bob
    email: bob@example.org
admins:                            # optional; may also be annotators
  - name: dana
    email: dana@example.org
```

```python
class Person(BaseModel):
    name: str            # validated pattern; unique across annotators and admins unless the same person
    email: str | None = None

class Annotator(Person):
    documents: Path | None = None

class ProjectFile(BaseModel):
    title: str = "tater project"
    schema_: Path | None = Field(None, alias="schema")
    config: Path | None = None
    documents: Path
    results: Path
    identity: Literal["links", "header"] = "links"
    header: str | None = None
    public_url: str | None = None
    idle_minutes: float = 30
    annotators: list[Annotator]
    admins: list[Person] = []
```

`load_project(path) -> Project` resolves paths against the project file's folder and checks: exactly one of `schema` / `config`; files exist; `header` and every email present in header mode; names unique and valid. `Project` holds the parsed file plus `project_dir`, `state_dir` and `annotation_path(name)` / `documents_path(name)` / `log_path(name)`.

## Files on disk

```
project.yaml
project.launcher/            # state; next to the project file, not in results, so results can be shared
  secret                     # cookie signing key, 32 random bytes, mode 0600
  links.json                 # {name: {"token": str, "generation": int}}, mode 0600
  status.json                # written by the running launcher every 5 s
results/
  alice/annotations.json     # the --annotations file of alice's process
  alice/tater.log            # that process's output, appended
  bob/...
```

`status.json`:

```json
{"pid": 1234, "url": "http://127.0.0.1:8050", "started": "2026-11-20T09:00:00Z", "updated": "...",
 "annotators": {"alice": {"state": "running", "pid": 2345, "port": 41234, "last_request": "...",
                          "starts": 3, "crashes": 0}}}
```

`state` is one of `stopped`, `starting`, `running`, `stopping`, `crashed`, `failed`.

## Command line

New console script in `pyproject.toml`: `tater-launcher = "tater.launcher.cli:main"`. Subcommands (argparse subparsers):

| Command | Does |
|---|---|
| `tater-launcher check PROJECT` | Validates the project file, loads the schema or config and each distinct documents file (the same loaders tater uses), and reports counts. Exits non-zero on any problem. `start` runs the same checks first. |
| `tater-launcher start PROJECT [--host H] [--port P] [--behind-login-proxy]` | Runs the launcher. Defaults `127.0.0.1:8050`, or `TATER_LAUNCHER_HOST` / `TATER_LAUNCHER_PORT`. Prints the links (links mode) or the address (header mode). |
| `tater-launcher links PROJECT [NAME ...]` | Prints `name  url` for annotators and admins, creating tokens that don't exist yet. Re-running prints the same links. |
| `tater-launcher reissue PROJECT NAME` | New token, generation + 1; prints the new link. |
| `tater-launcher status PROJECT` | Table: annotator, state, last request, documents, complete, in progress, flagged, results file. Reads `status.json` (only if its launcher is still running: `running` is true and its pid is alive; otherwise every state shows `not running`) and the results files. |

Links are `{public_url or http://host:port}/join/{token}`. Tokens are `secrets.token_urlsafe(24)`.

## Package layout

```
tater/launcher/
  __init__.py
  cli.py          # main(), subcommands
  project.py      # ProjectFile, Project, load_project, check_project
  identity.py     # LinkStore (links.json), CookieSigner, identify()
  supervisor.py   # Child, Supervisor: start, ready check, stop, idle and crash monitor, status.json
  proxy.py        # forward(request, child) -> Response
  app.py          # create_app(project, supervisor, ...) -> Flask; routes and launcher pages
  progress.py     # ProgressCounter (counts cached by file stamp), status_rows, read_status_file, table formatting
  pages.py        # small inline-HTML pages: not part of project, bad link, couldn't start
```

The launcher is a plain Flask app (Flask is installed with Dash) served by Werkzeug's threaded server, as tater is. Forwarding uses `requests` (also installed with Dash) through one `requests.Session` per child, for connection reuse. No new dependencies.

## Request flow

Routes in `app.py`:

| Path | Who | Does |
|---|---|---|
| `GET /join/<token>` | anyone, links mode | Looks the token up in `LinkStore`. Found: sets the cookie and redirects to `/` (admins who aren't annotators to `/_launcher/`). Not found: 403 page. |
| `GET /_launcher/` | admins | Status page (below). |
| `GET /_launcher/health` | anyone | `200 ok`, for platform health probes; reveals nothing. |
| everything else | annotators | Forwarded to the caller's process. |

`identify(request) -> Person | None`:
- links mode: cookie `tater_launcher`, an `itsdangerous.URLSafeSerializer` (key from `secret`) signature of `{"n": name, "g": generation}`; valid only if the generation matches `links.json`, so `reissue` invalidates old cookies. Cookie flags: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when `public_url` starts with `https`, no expiry (a session cookie would make annotators re-open their link after every browser restart; a year's `Max-Age` instead).
- header mode: `request.headers[header]`, stripped and lower-cased, matched against emails.

An unidentified request to a forwarded path gets the "not part of this project" page (403; plain text for non-GET). An identified admin who isn't an annotator gets a redirect to `/_launcher/`.

`proxy.forward(request, child)`:
- URL `http://127.0.0.1:{child.port}{request.full_path}`; method and body (`request.get_data()`) as received.
- Request headers: drop hop-by-hop headers (`Connection`, `Keep-Alive`, `Proxy-*`, `TE`, `Trailer`, `Transfer-Encoding`, `Upgrade`) and `Host`; remove the `tater_launcher` cookie from `Cookie` and, in header mode, the identity header; add `X-Tater-Launcher-Token: {child.token}`.
- `session.request(..., stream=True, allow_redirects=False, timeout=(5, 300))`; respond with `resp.raw.stream(65536, decode_content=False)` so compressed bodies pass through unchanged with their `Content-Encoding` and `Content-Length`; drop hop-by-hop response headers.
- Connection refused or reset (the process died mid-request): mark the child `crashed`, return 502 with the "couldn't reach your session, reload the page" page. The next request restarts it.

Tater serves everything from `/` (`/_dash-layout`, `/_dash-update-component`, `/_dash-component-suites/...`, `/assets/...`), so no path rewriting is needed and launcher paths (`/join/`, `/_launcher/`) don't collide.

Every forwarded request sets `child.last_request = time.monotonic()`.

## Processes

`Supervisor` owns one `Child` per annotator, each with its own `threading.Lock`.

`ensure_running(name)` (called before every forward), under the child's lock:
1. `running` and `proc.poll() is None`: return.
2. `failed`: raise `ChildUnavailable` (502 page naming the log file for the admin).
3. Otherwise start: pick a free port (bind 127.0.0.1:0), `token = secrets.token_urlsafe(32)`, and `Popen([sys.executable, "-m", "tater.ui.runner", "--schema"|"--config", ..., "--documents", ..., "--annotations", results/name/annotations.json, "--host", "127.0.0.1", "--port", port], env={**os.environ, "TATER_LAUNCHER_TOKEN": token}, stdout/stderr → tater.log (append), creationflags=CREATE_NEW_PROCESS_GROUP on Windows)`. State `starting`.
4. Ready check: `GET /` with the token header every 100 ms until 200, for up to 60 s. Process exits first: `crashed`, raise `ChildUnavailable`. Timeout: stop it, raise.

Processes start on an annotator's first request, not when the launcher starts, so memory follows who is working.

Monitor thread, every 5 s:
- Running process that has exited: state `crashed`, `crashes += 1`. It restarts on that annotator's next request. Three crashes within 10 minutes: `failed` until the launcher restarts (logged with the log file's path).
- Running and idle for `idle_minutes` (if non-zero): `stop(name)`.
- Write `status.json` (atomically, like `_write_json_atomic`).

`stop(name)`, under the child's lock: SIGTERM (POSIX) or `CTRL_BREAK_EVENT` (Windows); wait up to 30 s; then `kill()` and log that pending edits may be lost. State `stopped`. A request arriving meanwhile waits on the lock, then starts a new process.

Launcher shutdown (SIGINT, SIGTERM): stop every child in parallel, write a final `status.json`, exit.

## Changes to tater itself

- `tater/ui/runner.py`: `if __name__ == "__main__": main()`, so the launcher can run `python -m tater.ui.runner`.
- `run_single`: if `TATER_LAUNCHER_TOKEN` is set, register `server.before_request` that returns 403 unless `X-Tater-Launcher-Token` matches (`hmac.compare_digest`). Remove the variable from `os.environ` after reading, so a config's code can't trivially pass it on. Unset (normal use): nothing registered.
- `run_single`: also handle `signal.SIGBREAK` like SIGTERM where it exists (Windows).
- Icons (last task): `tater/ui/assets/icons.js` sets `window.IconifyPreload = [{prefix: "tabler", icons: {...}}, ...]` with the bodies of every icon tater uses, taken from the `@iconify-json/tabler` set (MIT; licence noted in the file header). The two `fa-regular` icons switch to Tabler equivalents so only one set is shipped. A script `scripts/build_icons.py` regenerates the file from a list; a unit test greps `tater/` for `icon="..."` and `DashIconify(icon=` names (including the clientside pause/play swap) and fails if one isn't in the file. Browser check: block `api.iconify.design`, `api.simplesvg.com` and `api.unisvg.com` and assert icons render (an `svg` inside each `.iconify` span) and no request goes to those hosts. Built: the script takes the unpacked npm package (`@iconify-json/tabler` 1.2.46, Tabler Icons 3.52.0; 35 icons, 9 KB) and finds the names itself, so there's no separate list. `scripts/build_icons.py` and `tests/test_icons.py`; the browser check (`TestIcons` in `test_browser.py`, annotation page and hosted upload page) also fails on any request off the machine, and the test suite's filter that ignored failed iconify fetches is gone.

Nothing in the save path changes.

## Status page

`/_launcher/` for admins, and `tater-launcher status` from the shell. One row per annotator: name, state, last request ("3 min ago"), documents, complete, in progress, flagged, results file path. Counts come from each results file's `metadata.status` / `flagged`, cached by file mtime (a 10,000-document file parses in well under a second). Plain server-rendered HTML with a 30 s meta refresh; no Dash. In links mode the page also lists each person's link with a "reissue" button (`POST /_launcher/reissue/<name>`; the `Origin`, or failing that `Referer`, must be the launcher's own address or `public_url`). An admin can't reissue their own link from the page, since that would sign them out before they saw the new one; they use the shell. Only documents in the annotator's documents file are counted. The document an annotator is on counts as in progress, as in tater.

## Failed requests

Found in manual testing: a tab signed out by `reissue` looked unchanged, and its edits were silently dropped (Dash shows nothing when a callback request fails, outside debug mode). The same happened in single mode when the server stopped under an open tab. `tater/ui/assets/request_guard.js` wraps `fetch`: the first failed `_dash-update-component` request (network error or non-2xx) shows a banner that stays until reload. The launcher adds `X-Tater-Launcher: signed-out` to its 403 for non-GET requests and `X-Tater-Launcher: unavailable` to its 502 page, and the banner words those cases accordingly (no Reload button when signed out, since a reload can't help).

## Security notes (go into the docs)

- Encryption belongs to whatever is in front (VPN, reverse proxy with TLS, platform, tunnel). The launcher speaks plain HTTP.
- Links mode: a link is a password. Send it privately; reissue if leaked. Suits non-sensitive data or a network only the right people can reach.
- Header mode: the launcher must be reachable only through the login service, which must strip the identity header from incoming requests. `--behind-login-proxy` is the admin asserting that.
- Child processes listen on 127.0.0.1 and reject requests without their token, so other users on a shared server can't reach them directly.
- `project.launcher/` holds the signing key and links; it's created 0700 with 0600 files.

## Tests

Unit (`tests/test_launcher.py`, no browser):
- `load_project`: valid file; each validation error (both/neither of schema and config, missing files, bad names, duplicate names, header mode without emails); paths resolved relative to the file.
- `LinkStore`: tokens created once and stable; `reissue` changes token and generation; file modes.
- `identify`: valid cookie; tampered cookie; old generation after reissue; header mode case-insensitive match; unknown email.
- `proxy.forward` against a stub WSGI server: method, body, query string pass through; launcher cookie and identity header removed; token header added; gzip body passed through byte for byte; 502 on refused connection.
- Token check in `run_single`: 403 without or with a wrong header, 200 with the right one, nothing registered without the variable.
- Refusal to start in header mode on a non-loopback host without `--behind-login-proxy`.

Integration with real processes (`tests/test_launcher_browser.py`, Playwright, two annotators, small project):
- Alice and Bob (separate browser contexts, each opening their link) annotate; each results file holds only its owner's edits.
- A context with no cookie, or a forged one, gets the "not part of this project" page and no tater page.
- Reissue Alice's link: her old cookie stops working, the new link works, Bob is unaffected.
- Idle stop (`idle_minutes` set tiny): edit, wait for the stop, check the edit is in the file, act again; the process restarts and the page keeps working without a reload.
- Crash: kill Alice's process; her next action gets one 502, then a reload works and her saved work is there.
- Two tabs for one annotator reach the same process.
- Header mode: `extra_http_headers` with the identity header; unknown email gets the 403 page.
- Direct connection to a child's port without the token gets 403.

Not a test: the restart time measurement above, repeated before release with `perf.synthetic` at 500 and 10,000 documents.

## Documentation

README section "Running a project with several annotators": a minimal project file, `check` / `start` / `links` / `status`, where results land, idle stops, and memory (measured 2026-11-17 with `perf.synthetic`, realistic schema, after the first page load: about 120 MB per running annotator at 500 documents, 165 MB at 10,000 new, 245 MB at 10,000 fully annotated; the launcher about 70 MB; only people working count). The pitch's "where it runs" table, requirements first (encryption in transit, a login for anything sensitive, results on a disk that survives restarts), tools as examples only. Short paragraph on notebook hubs. The JupyterHub experiment hasn't been run (no hub available here), so the paragraph says so. Hosted mode's README section gets one line pointing projects here. CLAUDE.md: the launcher package, the token check in `run_single`, and the tests.

## Order of work and cut line

Week one (the core):
1. `project.py` + `check`.
2. Token check and `__main__` in tater.
3. `supervisor.py`: start, ready check, stop, crash handling (no idle yet).
4. `identity.py`, `proxy.py`, `app.py`: links mode end to end; `start`, `links`, `reissue`.
5. Header mode and the public-address refusal.
6. Integration tests for the above.

Week two (cut from the bottom if short):
7. Idle stops and their tests.
8. Status page, `status.json`, `status` command.
9. Documentation, including the JupyterHub paragraph.
10. Local icons.

If idle stops (7) are cut, the docs carry the memory sizing per enrolled annotator instead.

## Confirmed choices

Agreed 2026-11-17:

- Separate `tater-launcher` command with subcommands, rather than new flags on `tater`. The existing CLI is flat flags; four verbs fit subcommands better.
- YAML project file.
- State folder next to the project file (`project.launcher/`), not inside `results/`.
- `--behind-login-proxy` as the explicit override for header mode on a public address.
- Cookies last a year rather than until the browser closes.
