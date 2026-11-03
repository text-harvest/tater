"""Summarise a callback trace (written by tater --trace) per action, and flag waste.

    uv run python -m perf.trace_report trace.jsonl
"""
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

BIG_BYTES = 100_000   # a request or response above this is flagged
MAX_REPEATS = 2       # the same output more than this many times in one action is flagged


def read_trace(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def short_output(output: str) -> str:
    """Readable form of a Dash output string: ``a.data, b.children``.

    Drops the ``..``/``...`` multi-output separators and ``@hash`` suffixes of
    allow_duplicate outputs, and names a pattern-matching ID by its ``type``.
    An output-less callback is sent as a bare hash, shown as ``(no output)``.
    """
    if "." not in output:
        return "(no output)"
    parts = output.strip(".").split("...")
    names = []
    for part in parts:
        part = re.sub(r"@[0-9a-f]{40,}$", "", part)
        cid, _, prop = part.replace("\\.", "\0").rpartition(".")
        cid = cid.replace("\0", ".")
        if cid.startswith("{"):
            try:
                cid = "{" + json.loads(cid).get("type", "?") + "}"
            except ValueError:
                pass
        names.append(f"{cid}.{prop}")
    return ", ".join(names)


def _has_output(line: dict) -> bool:
    return "." in line.get("output", "")


@dataclass
class ActionSummary:
    action: str
    requests: int = 0
    req_bytes: int = 0
    resp_bytes: int = 0
    ms: float = 0.0
    flags: list[str] = field(default_factory=list)


def flags_for(lines: list[dict], repeats: bool = True) -> list[str]:
    """The automatic flags for one action's trace lines.

    Pass ``repeats=False`` for a journey, where callbacks repeat by design.
    """
    flags = []
    counts = Counter(short_output(l["output"]) for l in lines)
    for name, n in counts.items():
        if repeats and n > MAX_REPEATS:
            flags.append(f"{name} fired {n}x")
    sent: dict[str, int] = {}
    returned: dict[str, int] = {}
    for l in lines:
        name = short_output(l["output"])
        sent[name] = max(sent.get(name, 0), l["req_bytes"])
        returned[name] = max(returned.get(name, 0), l["resp_bytes"])
        if l["status"] == 204 and _has_output(l):
            flags.append(f"{name} changed nothing (204)")
    flags += [f"{name} sent {b / 1000:.0f} KB" for name, b in sent.items() if b > BIG_BYTES]
    flags += [f"{name} returned {b / 1000:.0f} KB" for name, b in returned.items() if b > BIG_BYTES]
    return list(dict.fromkeys(flags))


def summarise(lines: list[dict]) -> list[ActionSummary]:
    """One summary per action label, in the order the actions ran."""
    by_action: dict[str, list[dict]] = defaultdict(list)
    for l in lines:
        by_action[l.get("action", "")].append(l)
    return [
        ActionSummary(
            action=action,
            requests=len(ls),
            req_bytes=sum(l["req_bytes"] for l in ls),
            resp_bytes=sum(l["resp_bytes"] for l in ls),
            ms=sum(l["ms"] for l in ls),
            flags=flags_for(ls),
        )
        for action, ls in by_action.items()
    ]


def format_table(summaries: list[ActionSummary]) -> str:
    rows = ["| action | requests | up KB | down KB | server ms | flags |", "|---|---:|---:|---:|---:|---|"]
    for s in summaries:
        rows.append(
            f"| {s.action or '(none)'} | {s.requests} | {s.req_bytes / 1000:.1f} | {s.resp_bytes / 1000:.1f} "
            f"| {s.ms:.1f} | {'; '.join(s.flags)} |"
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit("usage: python -m perf.trace_report TRACE.jsonl")
    print(format_table(summarise(read_trace(argv[0]))))


if __name__ == "__main__":
    main()
