"""Start the tater CLI in a subprocess, so its memory can be measured and it runs as in real use."""
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

_RUN_TATER = "from tater.ui.runner import main; main()"


@dataclass
class ServerInfo:
    url: str
    pid: int
    trace_path: Optional[Path]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def run_tater(
    directory: str | Path,
    *,
    hosted: bool = False,
    trace_path: str | Path | None = None,
    timeout: float = 300.0,
) -> Iterator[ServerInfo]:
    """Run tater on a free port with the project in ``directory`` (see synthetic.write_project).

    Yields once ``/`` responds. Server output goes to ``directory/server.log``.
    """
    directory = Path(directory)
    port = _free_port()
    if hosted:
        args = ["--hosted"]
    else:
        args = [
            "--schema", str(directory / "schema.json"),
            "--documents", str(directory / "documents.json"),
            "--annotations", str(directory / "annotations.json"),
        ]
    args += ["--port", str(port)]
    if trace_path:
        trace_path = Path(trace_path)
        trace_path.unlink(missing_ok=True)
        args += ["--trace", str(trace_path)]

    url = f"http://127.0.0.1:{port}"
    with open(directory / "server.log", "w") as log:
        proc = subprocess.Popen([sys.executable, "-c", _RUN_TATER, *args], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.time() + timeout
            while True:
                if proc.poll() is not None:
                    raise RuntimeError(f"tater exited with {proc.returncode}; see {directory / 'server.log'}")
                try:
                    urllib.request.urlopen(url + "/", timeout=5)
                    break
                except OSError:
                    if time.time() > deadline:
                        raise TimeoutError(f"tater did not start within {timeout:.0f} s")
                    time.sleep(0.2)
            yield ServerInfo(url=url, pid=proc.pid, trace_path=trace_path)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
