"""Start, watch, and stop one single-mode tater process per annotator.

A process starts on its annotator's first request (``ensure_running``), not when
the launcher starts, so memory follows who is working. A monitor thread notices
crashes and idle processes. Each process listens on 127.0.0.1 and accepts only
requests carrying its own token (``tater.ui.runner._require_launcher_token``).
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from tater.launcher.project import Project
from tater.ui.runner import LAUNCHER_TOKEN_ENV, LAUNCHER_TOKEN_HEADER

IS_WINDOWS = sys.platform == "win32"

# Three crashes within this window and an annotator's process isn't restarted
# until the launcher restarts: something is wrong that a restart won't fix.
CRASH_LIMIT = 3
CRASH_WINDOW = 600.0


class ChildUnavailable(Exception):
    """An annotator's process couldn't be started or reached. The message is for the admin."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Child:
    """One annotator's tater process and what the launcher knows about it."""

    name: str
    state: str = "stopped"  # stopped | starting | running | stopping | crashed | failed
    proc: Optional[subprocess.Popen] = None
    port: Optional[int] = None
    token: Optional[str] = None
    last_request: float = 0.0  # time.monotonic() of the last forwarded request
    last_request_wall: Optional[str] = None
    starts: int = 0
    crash_times: list[float] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    session: requests.Session = field(default_factory=requests.Session)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def touch(self) -> None:
        self.last_request = time.monotonic()
        self.last_request_wall = _now_iso()


class Supervisor:
    def __init__(
        self,
        project: Project,
        *,
        ready_timeout: float = 60.0,
        stop_timeout: float = 30.0,
        monitor_interval: float = 5.0,
    ):
        self.project = project
        self.ready_timeout = ready_timeout
        self.stop_timeout = stop_timeout
        self.monitor_interval = monitor_interval
        self.children = {a.name: Child(a.name) for a in project.annotators}
        self.launcher_url: Optional[str] = None
        self.started = _now_iso()
        self._stop_event = threading.Event()
        self._monitor: Optional[threading.Thread] = None

    # -- one annotator ---------------------------------------------------------

    def ensure_running(self, name: str) -> Child:
        """Return ``name``'s process, starting it (and waiting until it answers) if needed.

        Counts as activity (under the lock, so an idle stop can't come between this
        and the request it's for)."""
        child = self.children[name]
        with child.lock:
            if child.state == "running" and child.alive():
                child.touch()
                return child
            if child.state == "failed":
                raise ChildUnavailable(
                    f"{name}'s tater crashed {CRASH_LIMIT} times in {CRASH_WINDOW / 60:.0f} minutes and "
                    f"won't be restarted until the launcher is; see {self.project.log_path(name)}"
                )
            if child.alive():  # e.g. marked crashed by a failed request but still running
                self._stop_locked(child)
            self._start_locked(child)
            return child

    def stop(self, name: str) -> None:
        child = self.children[name]
        with child.lock:
            self._stop_locked(child)

    def mark_unreachable(self, child: Child) -> None:
        """A forwarded request couldn't reach the process (it died mid-request)."""
        with child.lock:
            if not child.alive() and child.state == "running":
                self._record_crash(child)

    def _command(self, name: str, port: int) -> list[str]:
        p = self.project
        cmd = [sys.executable, "-m", "tater.ui.runner"]
        cmd += ["--config", str(p.config_path)] if p.config_path else ["--schema", str(p.schema_path)]
        cmd += [
            "--documents", str(p.documents_path(name)),
            "--annotations", str(p.annotation_path(name)),
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
        return cmd

    def _start_locked(self, child: Child) -> None:
        self.project.annotation_path(child.name).parent.mkdir(parents=True, exist_ok=True)
        child.port = _free_port()
        child.token = secrets.token_urlsafe(32)
        env = {k: v for k, v in os.environ.items() if not k.startswith("TATER_APP_")}
        env[LAUNCHER_TOKEN_ENV] = child.token
        log = open(self.project.log_path(child.name), "ab")
        try:
            log.write(f"\n--- started by tater-launcher at {_now_iso()} ---\n".encode())
            log.flush()
            child.proc = subprocess.Popen(
                self._command(child.name, child.port),
                cwd=self.project.project_dir,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
            )
        finally:
            log.close()  # the child has its own copy of the handle
        child.state = "starting"
        child.starts += 1
        try:
            self._wait_ready(child)
        except ChildUnavailable:
            if child.alive():
                self._stop_locked(child, final_state="crashed")
            self._record_crash(child)
            raise
        child.touch()  # idle time runs from when it's ready, not from launch
        child.state = "running"

    def _wait_ready(self, child: Child) -> None:
        deadline = time.monotonic() + self.ready_timeout
        while True:
            if not child.alive():
                raise ChildUnavailable(
                    f"{child.name}'s tater exited while starting (code {child.proc.returncode}); "
                    f"see {self.project.log_path(child.name)}"
                )
            try:
                r = child.session.get(child.url + "/", headers={LAUNCHER_TOKEN_HEADER: child.token}, timeout=5)
                if r.status_code == 200:
                    return
            except requests.RequestException:
                pass
            if time.monotonic() > deadline:
                raise ChildUnavailable(
                    f"{child.name}'s tater didn't answer within {self.ready_timeout:.0f} s; "
                    f"see {self.project.log_path(child.name)}"
                )
            time.sleep(0.1)

    def _stop_locked(self, child: Child, final_state: str = "stopped") -> None:
        """Ask the process to exit (it writes pending edits as it does); kill it if it won't."""
        proc = child.proc
        if proc is not None and proc.poll() is None:
            child.state = "stopping"
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT if IS_WINDOWS else signal.SIGTERM)
                proc.wait(timeout=self.stop_timeout)
            except subprocess.TimeoutExpired:
                print(f"tater-launcher: {child.name}'s tater didn't stop within "
                      f"{self.stop_timeout:.0f} s; killing it (edits not yet saved may be lost)")
                proc.kill()
                proc.wait()
            except OSError:
                pass
        child.proc = None
        child.state = final_state

    def _record_crash(self, child: Child) -> None:
        now = time.monotonic()
        child.crash_times = [t for t in child.crash_times if now - t < CRASH_WINDOW] + [now]
        child.proc = None
        if len(child.crash_times) >= CRASH_LIMIT:
            child.state = "failed"
            print(f"tater-launcher: {child.name}'s tater crashed {CRASH_LIMIT} times; not restarting it. "
                  f"See {self.project.log_path(child.name)}")
        else:
            child.state = "crashed"

    # -- all of them -----------------------------------------------------------

    def check(self) -> None:
        """One monitor pass: notice crashes, stop idle processes, write status.json."""
        idle_after = self.project.file.idle_minutes * 60
        for child in self.children.values():
            if not child.lock.acquire(blocking=False):
                continue  # starting or stopping; next pass
            try:
                if child.state == "running" and not child.alive():
                    self._record_crash(child)
                elif (child.state == "running" and idle_after
                      and time.monotonic() - child.last_request > idle_after):
                    self._stop_locked(child)
            finally:
                child.lock.release()
        self.write_status()

    def start_monitor(self) -> None:
        def loop():
            while not self._stop_event.wait(self.monitor_interval):
                try:
                    self.check()
                except Exception as e:  # never let the monitor die
                    print(f"tater-launcher: monitor error: {e}")

        self._monitor = threading.Thread(target=loop, name="tater-launcher-monitor", daemon=True)
        self._monitor.start()

    def shutdown(self) -> None:
        """Stop the monitor and every process (in parallel), then write a final status."""
        self._stop_event.set()
        threads = [threading.Thread(target=self.stop, args=(name,)) for name in self.children]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.write_status(running=False)

    def status(self) -> dict:
        return {
            "pid": os.getpid(),
            "url": self.launcher_url,
            "started": self.started,
            "updated": _now_iso(),
            "annotators": {
                c.name: {
                    "state": c.state,
                    "pid": c.proc.pid if c.alive() else None,
                    "port": c.port if c.alive() else None,
                    "last_request": c.last_request_wall,
                    "starts": c.starts,
                    "crashes": len(c.crash_times),
                }
                for c in self.children.values()
            },
        }

    def write_status(self, running: bool = True) -> None:
        from tater.ui.tater_app import _write_json_atomic
        state_dir = self.project.state_dir
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        data = self.status()
        data["running"] = running
        _write_json_atomic(state_dir / "status.json", data)
