"""Per-annotator progress and the status table shared by ``/_launcher/`` and ``tater-launcher status``.

Counts come from each annotator's documents file and results file, each cached by the
file's (inode, mtime, size), so a refresh re-reads only what changed.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tater.launcher.project import Project


def _stamp(path: Path) -> Optional[tuple]:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


class ProgressCounter:
    def __init__(self, project: Project):
        self.project = project
        self._lock = threading.Lock()
        self._docs: dict[Path, tuple[tuple, frozenset]] = {}
        self._results: dict[Path, tuple[tuple, dict]] = {}

    def _doc_ids(self, path: Path) -> Optional[frozenset]:
        stamp = _stamp(path)
        if stamp is None:
            return None
        cached = self._docs.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        from tater.loaders import load_documents
        try:
            ids = frozenset(d.id for d in load_documents(path))
        except Exception:
            return None
        self._docs[path] = (stamp, ids)
        return ids

    def _metadata(self, path: Path) -> dict:
        """{doc_id: metadata} from a results file; {} if there is none yet."""
        stamp = _stamp(path)
        if stamp is None:
            return {}
        cached = self._results.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            meta = {d: (v.get("metadata") or {}) for d, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            return {}
        self._results[path] = (stamp, meta)
        return meta

    def counts(self, name: str) -> dict:
        """``{documents, complete, in_progress, flagged}`` for one annotator.

        Only documents in their documents file count, so results left from documents that
        were since removed don't inflate the numbers. ``documents`` is None if the file
        doesn't load.
        """
        with self._lock:
            ids = self._doc_ids(self.project.documents_path(name))
            meta = self._metadata(self.project.annotation_path(name))
        counts = {"documents": None if ids is None else len(ids), "complete": 0, "in_progress": 0, "flagged": 0}
        for doc_id, m in meta.items():
            if ids is not None and doc_id not in ids:
                continue
            status = m.get("status")
            if status in ("complete", "in_progress"):
                counts[status] += 1
            if m.get("flagged"):
                counts["flagged"] += 1
        return counts


def ago(iso: Optional[str], now: Optional[datetime] = None) -> str:
    """'just now', '3 min ago', '2 h ago', '4 days ago'; '—' for never."""
    if not iso:
        return "—"
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    seconds = ((now or datetime.now(timezone.utc)) - then).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 2 * 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} days ago"


def read_status_file(project: Project) -> Optional[dict]:
    """The running launcher's ``status.json``, or None if no launcher is running.

    A file left by a launcher that stopped (``running: false``) or died (its pid is gone)
    doesn't count.
    """
    path = project.state_dir / "status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not data.get("running"):
        return None
    pid = data.get("pid")
    if not isinstance(pid, int) or not _pid_alive(pid):
        return None
    return data


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def status_rows(project: Project, status: Optional[dict], progress: ProgressCounter) -> list[dict]:
    """One row per annotator: process state (from ``status``, a ``Supervisor.status()``
    or ``status.json``; None if no launcher is running) plus progress counts."""
    procs = (status or {}).get("annotators", {})
    rows = []
    for a in project.annotators:
        p = procs.get(a.name, {})
        rows.append({
            "name": a.name,
            "state": p.get("state", "stopped") if status else "not running",
            "last_request": p.get("last_request"),
            "starts": p.get("starts", 0),
            "crashes": p.get("crashes", 0),
            **progress.counts(a.name),
            "results": project.annotation_path(a.name),
        })
    return rows


COLUMNS = ["Annotator", "State", "Last request", "Documents", "Complete", "In progress", "Flagged", "Results file"]


def row_cells(row: dict, now: Optional[datetime] = None) -> list[str]:
    docs = row["documents"]
    return [
        row["name"],
        row["state"],
        ago(row["last_request"], now),
        "?" if docs is None else str(docs),
        str(row["complete"]),
        str(row["in_progress"]),
        str(row["flagged"]),
        str(row["results"]),
    ]


def format_table(rows: list[dict], now: Optional[datetime] = None) -> str:
    cells = [COLUMNS] + [row_cells(r, now) for r in rows]
    widths = [max(len(c[i]) for c in cells) for i in range(len(COLUMNS))]
    numeric = {3, 4, 5, 6}
    lines = []
    for c in cells:
        parts = [c[i].rjust(widths[i]) if i in numeric else c[i].ljust(widths[i]) for i in range(len(c))]
        lines.append("  ".join(parts).rstrip())
    return "\n".join(lines)
