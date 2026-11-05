"""Run the performance matrix and write a CSV plus a Markdown summary.

    uv run python -m perf.run --sizes 50,500,2500,10000 --lengths short,medium,long \\
        --schema checkbox,realistic --filled both --repeats 5 --out perf/results/

Needs Playwright's Chromium once per machine: ``uv run playwright install chromium``.
"""
import argparse
import csv
import datetime
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from playwright.sync_api import Browser, sync_playwright

from perf import bench_server
from perf.actions import Scenario, make_actions, wait_loaded
from perf.measure import INIT_SCRIPT, ActionRecorder, ActionResult
from perf.server import run_tater
from perf.synthetic import LENGTHS, make_project, write_project

BASE_SIZE = 500   # the summary compares the largest size against this one
COLUMNS = ["size", "length", "schema", "filled", "action", "requests", "up_kb", "down_kb", "server_ms",
           "settle_ms", "long_task_ms", "heap_mb", "server_rss_mb", "check", "flags"]


def _git_sha() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "tater"]).returncode != 0
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run_scenario(browser: Browser, size: int, length: str, schema: str, filled: bool, args, work: Path) -> list[dict]:
    """Measure every action for one project; one row per action."""
    spans = args.spans if (filled and schema == "realistic") else 0
    project = make_project(size, LENGTHS[length], filled, spans_per_doc=spans, schema=schema)
    directory = work / f"{schema}-{length}-{size}-{'filled' if filled else 'empty'}"
    _, _, ann_path = write_project(project, directory)
    del project

    rows = []
    with run_tater(directory, trace_path=directory / "trace.jsonl") as server:
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        context.add_init_script(INIT_SCRIPT)
        page = context.new_page()
        page.set_default_timeout(60_000)
        page.goto(server.url)
        wait_loaded(page)
        recorder = ActionRecorder(page, server)
        scenario = Scenario(size, schema, ann_path, recorder.wait_quiet, random.Random(0))
        for action in make_actions(scenario):
            repeats = args.journey_repeats if action.journey else args.repeats
            try:
                result = recorder.measure(action.name, action.run, repeats=repeats, setup=action.setup,
                                          journey=action.journey)
            except Exception as e:  # keep going; the error shows up in the summary
                result = ActionResult(action.name, check=False, flags=[f"error: {str(e).splitlines()[0][:150]}"])
            try:
                if action.cleanup:
                    action.cleanup(page)
            except Exception:
                pass
            row = {"size": size, "length": length, "schema": schema, "filled": filled} | asdict(result)
            row["action"] = row.pop("label")
            row["flags"] = "; ".join(result.flags)
            rows.append(row)
            print(f"  {action.name:18} {result.requests:5.0f} req {result.up_kb:9.1f} KB up "
                  f"{result.settle_ms:8.0f} ms settle  {'' if result.check is None else ('ok' if result.check else 'FAILED')}",
                  flush=True)
        context.close()
    return rows


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}"


def _ratio(top: dict, base: dict | None, key: str) -> str:
    if not base or top is base or not float(base[key]):
        return ""
    return f"{float(top[key]) / float(base[key]):.1f}×"


def summary_markdown(rows: list[dict], bench: list[dict], skipped: list[str], header: str) -> str:
    out = [header, ""]
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["schema"], r["length"], r["filled"]), []).append(r)
    for (schema, length, filled), rs in groups.items():
        top_size = max(r["size"] for r in rs)
        by = {(r["size"], r["action"]): r for r in rs}
        out += [
            f"## {schema}, {length} documents, {'filled' if filled else 'empty'} — N = {top_size:,}", "",
            (f"Ratios compare N = {top_size:,} with N = {BASE_SIZE}; well above 1× means the cost grows with N."
             if top_size != BASE_SIZE and any(r["size"] == BASE_SIZE for r in rs)
             else f"No ratios: the run didn't include N = {BASE_SIZE} and a larger size."), "",
            "| action | requests | up KB | down KB | settle ms | long tasks ms | server ms "
            "| settle × | up KB × | check | flags |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        flag_lines = []
        for action in dict.fromkeys(r["action"] for r in rs):
            top = by.get((top_size, action))
            if not top:
                continue
            base = by.get((BASE_SIZE, action))
            check = "" if top["check"] is None else ("ok" if top["check"] else "**FAILED**")
            flags = [f for f in top["flags"].split("; ") if f]
            out.append(
                f"| {action} | {_fmt(top['requests'])} | {_fmt(top['up_kb'])} | {_fmt(top['down_kb'])} "
                f"| {_fmt(top['settle_ms'])} | {_fmt(top['long_task_ms'])} | {_fmt(top['server_ms'])} "
                f"| {_ratio(top, base, 'settle_ms')} | {_ratio(top, base, 'up_kb')} | {check} | {len(flags) or ''} |"
            )
            if flags:
                flag_lines += [f"- **{action}**"] + [f"  - {f}" for f in flags]
        out.append("")
        if flag_lines:
            out += ["Flags:", ""] + flag_lines + [""]
    if bench:
        out += ["## Server (no browser)", "",
                "| N | length | schema | filled | startup ms | save ms | file MB | RSS MB | project MB |",
                "|---:|---|---|---|---:|---:|---:|---:|---:|"]
        for b in (b for b in bench if not b.get("hosted")):
            out.append(f"| {b['n_docs']:,} | {b['length']} | {b['schema']} | {b['filled']} | {_fmt(b['startup_ms'])} "
                       f"| {_fmt(b['save_ms'])} | {b['file_mb']} | {_fmt(b['rss_mb'])} | {_fmt(b['rss_project_mb'])} |")
        hosted = [b for b in bench if b.get("hosted")]
        if hosted:
            out += ["", "Hosted mode, server memory growth with sessions open:", "",
                    "| N | schema | 1 session MB | 5 sessions MB | 20 sessions MB | per extra session MB |",
                    "|---:|---|---:|---:|---:|---:|"]
            for b in hosted:
                out.append(f"| {b['n_docs']:,} | {b['schema']} | {_fmt(b['rss_1_sessions_mb'])} | "
                           f"{_fmt(b['rss_5_sessions_mb'])} | {_fmt(b['rss_20_sessions_mb'])} | {_fmt(b['rss_per_session_mb'])} |")
        out.append("")
    if skipped:
        out += ["## Skipped", "", "Over `--max-total-chars`: " + ", ".join(skipped), ""]
    return "\n".join(out)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", default="50,500,2500,10000")
    parser.add_argument("--lengths", default="short", help=f"comma list of {', '.join(LENGTHS)}")
    parser.add_argument("--schema", default="checkbox,realistic")
    parser.add_argument("--filled", choices=["yes", "no", "both"], default="both")
    parser.add_argument("--repeats", type=int, default=5, help="runs per single action (median reported)")
    parser.add_argument("--journey-repeats", type=int, default=1, help="runs per journey")
    parser.add_argument("--spans", type=int, default=10, help="spans per document in filled realistic projects")
    parser.add_argument("--max-total-chars", type=int, default=150_000_000,
                        help="skip projects whose documents total more than this many characters")
    parser.add_argument("--no-bench", action="store_true", help="skip the browser-free server timings")
    parser.add_argument("--headed", action="store_true", help="show the browser")
    parser.add_argument("--out", default="perf/results/")
    args = parser.parse_args(argv)

    sizes = [int(s) for s in args.sizes.split(",")]
    filled_values = {"yes": [True], "no": [False], "both": [False, True]}[args.filled]
    cases, skipped = [], []
    for schema in args.schema.split(","):
        for length in args.lengths.split(","):
            for filled in filled_values:
                for size in sizes:
                    if size * LENGTHS[length] > args.max_total_chars:
                        skipped.append(f"{schema}/{length}/{size}")
                    else:
                        cases.append((size, length, schema, filled))
    skipped = list(dict.fromkeys(skipped))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.date.today().isoformat()}-{_git_sha()}"
    started = time.time()

    csv_path, md_path = out_dir / f"{stem}.csv", out_dir / f"{stem}.md"
    command = " ".join(["python -m perf.run"] + (argv if argv is not None else sys.argv[1:]))
    rows: list[dict] = []
    bench: list[dict] = []

    def write_summary(done: bool) -> None:
        """Rewrite the summary from what has been measured so far."""
        status = "" if done else f" — **incomplete**, {len({(r['size'], r['length'], r['schema'], r['filled']) for r in rows})} of {len(cases)} scenarios so far"
        header = (f"# Performance run {stem}\n\n`{command}` — "
                  f"{args.repeats} repeats per action (median), {args.journey_repeats} per journey, "
                  f"{(time.time() - started) / 60:.0f} min{status}.")
        md_path.write_text(summary_markdown(rows, bench, skipped, header))

    # Rows are written as each scenario finishes, so a stopped run keeps what it measured.
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        f.flush()
        with tempfile.TemporaryDirectory(prefix="tater-perf-") as tmp, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)
            for size, length, schema, filled in cases:
                print(f"{schema} / {length} / N={size} / {'filled' if filled else 'empty'}", flush=True)
                scenario_rows = run_scenario(browser, size, length, schema, filled, args, Path(tmp))
                rows += scenario_rows
                writer.writerows(scenario_rows)
                f.flush()
                write_summary(done=False)
            browser.close()

    if not args.no_bench:
        print("server timings", flush=True)
        for size, length, schema, filled in cases:
            spans = args.spans if (filled and schema == "realistic") else 0
            bench.append({"n_docs": size, "length": length, "schema": schema, "filled": filled}
                         | bench_server.run_case(False, size, length, schema, filled, spans))
            if length == "short" and filled:
                bench.append({"n_docs": size, "length": length, "schema": schema, "filled": filled, "hosted": True}
                             | bench_server.run_case(True, size, length, schema, filled, spans))

    write_summary(done=True)
    print(f"wrote {csv_path} and {md_path}")


if __name__ == "__main__":
    main()
