"""Single actions and journeys the harness measures, as Playwright steps.

Each action is ``run(page) -> Optional[bool]``: it returns a bool when it checks
its own result (``reload_resume``, ``rapid_clicks``), otherwise None. ``setup``
runs untimed before each run, e.g. to make room for a run of Next clicks.
"""
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import Page

TYPED = "quick brown fox jump"   # 20 characters


@dataclass
class Scenario:
    n_docs: int
    schema: str                         # "checkbox" | "realistic"
    annotations_path: Path
    wait_quiet: Callable[[], None]      # ActionRecorder.wait_quiet
    rng: random.Random


@dataclass
class Action:
    name: str
    run: Callable[[Page], Optional[bool]]
    journey: bool = False
    setup: Optional[Callable[[Page], None]] = None
    cleanup: Optional[Callable[[Page], None]] = None


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

def position(page: Page) -> int:
    """1-based position of the current document, from the "k / N" title."""
    return int(page.locator("#document-title").inner_text().split("/")[0])


def wait_position(page: Page, k: int, timeout: float = 30_000) -> None:
    page.wait_for_function(
        "k => (document.querySelector('#document-title')?.textContent || '').trim().startsWith(k + ' /')",
        arg=k, timeout=timeout,
    )


def wait_loaded(page: Page, timeout: float = 120_000) -> None:
    page.wait_for_function(
        "() => (document.querySelector('#document-title')?.textContent || '').includes(' / ')",
        timeout=timeout,
    )


def control(page: Page, tf: str):
    """A widget's input, found by the ``tf`` key of its pattern-matching ID."""
    return page.locator(f"""[id*='"tf":"{tf}"'][id*='"type":"tater-']""").first


def _selector_options(page: Page):
    listbox = page.locator("#document-select").get_attribute("aria-controls")
    return page.locator(f'[id="{listbox}"] [role=option]')


def goto_doc(page: Page, k: int) -> None:
    """Jump to the document at position k with the selector, as a user would."""
    select = page.locator("#document-select")
    select.click()
    select.fill(str(k))
    _selector_options(page).first.click()
    wait_position(page, k)


def _tick_target(page: Page, schema: str):
    if schema == "checkbox":
        return page.locator("input[type='checkbox'][value='a']")
    return control(page, "reviewed")


def _saved_tick(path: Path, doc_id: str, schema: str) -> Optional[bool]:
    try:
        ann = json.loads(path.read_text()).get(doc_id, {}).get("annotations", {})
    except (OSError, ValueError):
        return None
    if schema == "checkbox":
        return "a" in (ann.get("labels") or [])
    return bool(ann.get("reviewed"))


def _doc_id(k: int) -> str:
    return f"doc_{k - 1:05d}"   # synthetic.make_project ids, by 1-based position


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def make_actions(sc: Scenario) -> list[Action]:
    """The actions that apply to this scenario's schema, in the order to run them."""

    def room(k: int) -> Callable[[Page], None]:
        """Setup: make sure k more Next clicks are possible."""
        def setup(page: Page) -> None:
            if position(page) + k > sc.n_docs:
                goto_doc(page, 1)
        return setup

    def tick(page: Page) -> None:
        _tick_target(page, sc.schema).click()

    def next_doc(page: Page) -> None:
        p = position(page)
        page.click("#btn-next")
        wait_position(page, p + 1)

    def page_load(page: Page) -> None:
        page.reload()
        wait_loaded(page)

    def type_text(page: Page) -> None:
        control(page, "notes").press_sequentially(TYPED, delay=50)

    def type_notes(page: Page) -> None:
        page.locator("#document-notes").press_sequentially(TYPED, delay=50)

    def add_span(page: Page) -> None:
        # Select a word in the longest stretch of untagged text, then tag it.
        page.evaluate(
            """k => {
                const el = document.getElementById('document-content');
                const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
                let node = null, n;
                while ((n = walker.nextNode())) {
                    if (!n.parentElement.closest('mark') && (!node || n.length > node.length)) { node = n; }
                }
                const words = [...node.textContent.matchAll(/\\S+/g)];
                const w = words[k % words.length];
                const range = document.createRange();
                range.setStart(node, w.index); range.setEnd(node, w.index + w[0].length);
                const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
            }""",
            sc.rng.randrange(1000),
        )
        page.locator("""[id*='"type":"span-add-btn"'][id*='"tag":"Support"']""").click()

    def selector_search(page: Page) -> None:
        select = page.locator("#document-select")
        select.click()
        select.fill(str(sc.rng.randint(1, sc.n_docs))[:3])
        _selector_options(page).first.wait_for()
        page.keyboard.press("Escape")

    def annotate_next_20(page: Page) -> None:
        p = position(page)
        for i in range(20):
            tick(page)
            page.click("#btn-next")
            wait_position(page, p + i + 1)

    def jump_selector(page: Page) -> None:
        for _ in range(10):
            goto_doc(page, sc.rng.randint(1, sc.n_docs))

    def flag_then_filter(page: Page) -> None:
        p = position(page)
        for i in range(5):
            page.click("#flag-document")
            page.click("#btn-next")
            wait_position(page, p + i + 1)
        page.click("#filter-btn")
        page.click("#filter-flagged-check")
        page.keyboard.press("Escape")
        page.locator("#document-select").click()
        page.locator("#document-select").fill("")
        _selector_options(page).first.wait_for()
        page.keyboard.press("Escape")

    def clear_filter(page: Page) -> None:
        page.click("#filter-btn")
        if page.locator("#filter-flagged-check").is_checked():
            page.click("#filter-flagged-check")
        page.keyboard.press("Escape")

    def reload_resume(page: Page) -> bool:
        """Edits survive a reload, and the file matches what the page shows."""
        p = position(page)
        target = lambda: _tick_target(page, sc.schema)
        target().click()
        sc.wait_quiet()
        first = target().is_checked()
        page.reload()
        wait_position(page, p)
        sc.wait_quiet()
        ok = target().is_checked() == first
        page.click("#btn-next")
        wait_position(page, p + 1)
        target().click()
        sc.wait_quiet()
        second = target().is_checked()
        return (ok and _saved_tick(sc.annotations_path, _doc_id(p), sc.schema) == first
                and _saved_tick(sc.annotations_path, _doc_id(p + 1), sc.schema) == second)

    def rapid_clicks(page: Page) -> bool:
        """Ten Next clicks without waiting all land."""
        p = position(page)
        for _ in range(10):
            page.click("#btn-next")
        try:
            wait_position(page, p + 10, timeout=30_000)
        except Exception:
            pass  # slow isn't wrong: at 10k the clicks take ~50 s to settle; check after
        sc.wait_quiet()
        return position(page) == p + 10

    actions = [
        Action("page_load", page_load),
        Action("next", next_doc, setup=room(1)),
        Action("tick", tick),
        Action("type_notes", type_notes),
    ]
    if sc.schema == "realistic":
        actions += [Action("type_text", type_text), Action("add_span", add_span)]
    actions += [
        Action("selector_search", selector_search),
        Action("annotate_next_20", annotate_next_20, journey=True, setup=room(20)),
        Action("jump_selector", jump_selector, journey=True),
        Action("flag_then_filter", flag_then_filter, journey=True, setup=room(5), cleanup=clear_filter),
        Action("reload_resume", reload_resume, journey=True, setup=room(1)),
        Action("rapid_clicks", rapid_clicks, journey=True, setup=room(10)),
    ]
    return actions
