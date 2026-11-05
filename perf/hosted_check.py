"""Hosted-mode correctness check: edits survive reload and navigation, and sessions
stay separate.

Starts ``tater --hosted``, and for each built-in example opens a session (a browser
context, so its own cookie), makes one edit of each kind the example supports (notes,
flag, first checkbox, a repeater item, a hierarchical-label pick), then checks the
edits survive a reload and Next/Prev, and that a second session on the same example
neither sees them nor overwrites them. Also fails on a failed callback request or a
JS error. Prints PASS/FAIL lines; exits 1 if anything failed.

    uv run python -m perf.hosted_check

Written for #108 (it found top-level hierarchical labels showing empty after a page
load); a stopgap until #113 turns it into Playwright tests in ``tests/``. It checks
correctness, not speed, so it isn't part of ``perf.run``.
"""
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from perf.actions import position, wait_loaded, wait_position
from perf.measure import INIT_SCRIPT, ActionRecorder
from perf.server import run_tater

EXAMPLES = ["gallery", "repeater", "hierarchical"]
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""), flush=True)


def _cdn_noise(msg):
    """Icon fetches from the iconify CDN failing, e.g. with no network or behind a
    proxy that blocks it. Not a tater error."""
    text = msg.text
    url = (msg.location or {}).get("url", "")
    return "tabler.json" in text or "ERR_FAILED" in text and ("iconify" in url or "svg.com" in url or not url)


class Session:
    """One browser context = one Flask session cookie = one hosted session."""

    def __init__(self, browser, server, example):
        self.ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
        self.ctx.add_init_script(INIT_SCRIPT)
        self.page = self.ctx.new_page()
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("console", lambda m: m.type == "error" and not _cdn_noise(m) and self.errors.append(f"console: {m.text[:200]}"))
        self.page.on("response", lambda r: "_dash-update-component" in r.url and r.status >= 400
                     and self.errors.append(f"callback HTTP {r.status}"))
        self.rec = ActionRecorder(self.page, server)
        self.page.goto(server.url + "/")
        self.page.get_by_text("Browse examples").click()
        self.page.locator(f"[id*='\"example-card\"'][id*='\"{example}\"']").click()
        self.page.wait_for_url("**/annotate", timeout=30_000)
        self.settle()

    def settle(self):
        wait_loaded(self.page)
        self.rec.wait_quiet()

    def reload(self):
        self.page.reload()
        self.settle()

    # --- state readers -------------------------------------------------------
    def notes(self):
        return self.page.locator("#document-notes").input_value()

    def flagged(self):
        return self.page.locator("#flag-document").is_checked()

    def first_bool(self):
        loc = self.page.locator("[id*='\"tater-bool-control\"']")
        return loc.first if loc.count() else None

    def repeater_items(self):
        return self.page.locator("[id*='\"repeater-delete\"']").count()

    def hl_select(self):
        loc = self.page.locator("input[id*='\"hl-select\"']")
        return loc.first if loc.count() else None

    def state(self):
        b, hl = self.first_bool(), self.hl_select()
        return {
            "notes": self.notes(),
            "flag": self.flagged(),
            "bool": b.is_checked() if b else None,
            "repeater_items": self.repeater_items(),
            "hl": hl.input_value() if hl else None,
        }


def edit(s: Session, tag: str):
    """Make one edit of each kind the example supports; return the expected state."""
    page = s.page
    page.locator("#document-notes").fill(f"notes {tag}")
    s.rec.wait_quiet()
    page.locator("#flag-document").click()
    s.rec.wait_quiet()
    b = s.first_bool()
    if b:
        b.click()
        s.rec.wait_quiet()
    add = page.locator("[id*='\"repeater-add\"']")
    if add.count():
        add.first.click()
        s.rec.wait_quiet()
    hl = s.hl_select()
    if hl:
        hl.click()
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        page.keyboard.press("Escape")
        s.rec.wait_quiet()
    page.wait_for_timeout(500)
    return s.state()


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        with run_tater(Path(tmp), hosted=True) as server:
            browser = pw.chromium.launch()
            for ex in EXAMPLES:
                print(f"--- {ex}", flush=True)
                check_example(browser, server, ex)
            browser.close()
        failed = [n for n, ok in results if not ok]
        print(f"\n{len(results) - len(failed)}/{len(results)} passed")
        if failed:
            log = Path(tmp) / "server.log"
            if log.exists():
                print("--- server.log (end)\n" + log.read_text()[-3000:])
    return 1 if failed else 0


def check_example(browser, server, ex: str) -> None:
    a = Session(browser, server, ex)
    fresh = a.state()
    want = edit(a, "A")
    check(f"{ex}: edits applied", want["notes"] == "notes A" and want["flag"] != fresh["flag"]
          and (want["bool"] is None or want["bool"] != fresh["bool"])
          and want["repeater_items"] >= fresh["repeater_items"],
          f"fresh={fresh} after={want}")
    if a.page.locator("[id*='\"repeater-add\"']").count():
        check(f"{ex}: repeater item added", want["repeater_items"] == fresh["repeater_items"] + 1, f"{fresh} -> {want}")
    if want["hl"] is not None:
        check(f"{ex}: HL value selected", bool(want["hl"]), f"{want}")

    a.reload()
    got = a.state()
    check(f"{ex}: reload keeps edits", got == want, f"want={want} got={got}")

    p = position(a.page)
    a.page.click("#btn-next")
    wait_position(a.page, p + 1)
    a.rec.wait_quiet()
    other = a.state()
    check(f"{ex}: next doc doesn't show doc 1's edits",
          other["notes"] != "notes A" and other["flag"] == fresh["flag"], f"{other}")
    a.page.click("#btn-prev")
    wait_position(a.page, p)
    a.rec.wait_quiet()
    a.page.wait_for_timeout(500)
    got = a.state()
    check(f"{ex}: Next then Prev keeps edits", got == want, f"want={want} got={got}")

    b = Session(browser, server, ex)
    got_b = b.state()
    check(f"{ex}: second session starts clean", got_b == fresh, f"fresh={fresh} b={got_b}")
    edit(b, "B")
    a.reload()
    got = a.state()
    check(f"{ex}: second session's edits don't reach the first", got == want, f"want={want} got={got}")
    b.reload()
    check(f"{ex}: second session keeps its own edits", b.notes() == "notes B", b.notes())

    for s, who in ((a, "A"), (b, "B")):
        check(f"{ex}: session {who} no errors", not s.errors, "; ".join(s.errors[:5]))
        s.ctx.close()


if __name__ == "__main__":
    sys.exit(main())
