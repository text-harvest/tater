"""Who a request is from: a personal link's cookie, or a header set by a login service.

Links mode: each person has a secret token (``links.json`` in the state folder).
Opening ``/join/<token>`` sets a signed cookie naming them and the token's
generation; ``reissue`` bumps the generation, so old links and cookies stop
working at once. Header mode: the login service in front puts the visitor's
email in a header, matched against the project file.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path
from typing import Optional

from itsdangerous import BadSignature, URLSafeSerializer

from tater.launcher.project import Project

COOKIE_NAME = "tater_launcher"
COOKIE_MAX_AGE = 365 * 24 * 3600  # a year: annotators shouldn't need their link after a browser restart


def _write_private(path: Path, data: bytes) -> None:
    """Write a file only its owner can read, atomically."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def ensure_state_dir(project: Project) -> Path:
    project.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return project.state_dir


class LinkStore:
    """``{name: {"token": str, "generation": int}}`` in ``links.json``.

    Re-read when the file changes, so ``tater-launcher reissue`` takes effect in a
    running launcher without a restart.
    """

    def __init__(self, project: Project):
        self.path = ensure_state_dir(project) / "links.json"
        self.names = [p.name for p in project.annotators] + [p.name for p in project.admins]
        self._lock = threading.Lock()
        self._stamp: Optional[tuple] = None  # (inode, mtime, size): saves replace the file
        self._links: dict[str, dict] = {}

    def _stamp_of(self) -> tuple:
        st = self.path.stat()
        return st.st_ino, st.st_mtime_ns, st.st_size

    def _load(self) -> dict[str, dict]:
        try:
            stamp = self._stamp_of()
        except FileNotFoundError:
            self._links, self._stamp = {}, None
            return self._links
        if stamp != self._stamp:
            self._links = json.loads(self.path.read_text())
            self._stamp = stamp
        return self._links

    def _save(self, links: dict) -> None:
        _write_private(self.path, json.dumps(links, indent=2).encode())
        self._links, self._stamp = links, self._stamp_of()

    def ensure_all(self) -> dict[str, str]:
        """Create a token for everyone who has none; return ``{name: token}``."""
        with self._lock:
            links = dict(self._load())
            changed = False
            for name in dict.fromkeys(self.names):
                if name not in links:
                    links[name] = {"token": secrets.token_urlsafe(24), "generation": 1}
                    changed = True
            if changed:
                self._save(links)
            return {name: links[name]["token"] for name in dict.fromkeys(self.names)}

    def reissue(self, name: str) -> str:
        if name not in self.names:
            raise KeyError(name)
        with self._lock:
            links = dict(self._load())
            generation = links.get(name, {}).get("generation", 0) + 1
            links[name] = {"token": secrets.token_urlsafe(24), "generation": generation}
            self._save(links)
            return links[name]["token"]

    def find(self, token: str) -> Optional[tuple[str, int]]:
        """``(name, generation)`` for a current token, else None."""
        with self._lock:
            for name, entry in self._load().items():
                if name in self.names and secrets.compare_digest(entry["token"], token):
                    return name, entry["generation"]
        return None

    def generation(self, name: str) -> Optional[int]:
        with self._lock:
            entry = self._load().get(name)
        return entry["generation"] if entry else None


class CookieSigner:
    """Signs ``{"n": name, "g": generation}`` with a key kept in the state folder."""

    def __init__(self, project: Project):
        path = ensure_state_dir(project) / "secret"
        if not path.exists():
            _write_private(path, secrets.token_bytes(32))
        self._serializer = URLSafeSerializer(path.read_bytes(), salt="tater-launcher")

    def dumps(self, name: str, generation: int) -> str:
        return self._serializer.dumps({"n": name, "g": generation})

    def loads(self, value: str) -> Optional[tuple[str, int]]:
        try:
            data = self._serializer.loads(value)
            return data["n"], data["g"]
        except (BadSignature, KeyError, TypeError):
            return None


class Identifier:
    """Maps a request to a person's name, or None."""

    def __init__(self, project: Project, links: Optional[LinkStore] = None, signer: Optional[CookieSigner] = None):
        self.project = project
        self.mode = project.file.identity
        self.links = links
        self.signer = signer
        self.annotator_names = {a.name for a in project.annotators}
        self.admin_names = {a.name for a in project.admins}
        if self.mode == "header":
            self.header = project.file.header
            self.by_email = {p.email: p.name for p in [*project.admins, *project.annotators]}

    def identify(self, request) -> Optional[str]:
        if self.mode == "header":
            email = (request.headers.get(self.header) or "").strip().lower()
            return self.by_email.get(email) if email else None
        value = request.cookies.get(COOKIE_NAME)
        found = self.signer.loads(value) if value else None
        if found is None:
            return None
        name, generation = found
        if generation != self.links.generation(name):
            return None  # reissued since this cookie was set
        return name

    def is_annotator(self, name: Optional[str]) -> bool:
        return name in self.annotator_names

    def is_admin(self, name: Optional[str]) -> bool:
        return name in self.admin_names
