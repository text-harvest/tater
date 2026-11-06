# One browser-testing framework: Playwright

## Problem

Tater drives a real browser in two places, using two different frameworks.

The browser tests use Dash's own testing tools, which run on Selenium. That setup is fragile. It pins an old Selenium release. It needs Google Chrome installed a particular way (the `.deb`, not the snap) plus a ChromeDriver that matches Chrome's exact version, and every Chrome update means a fresh ChromeDriver download. Coding agents can't run these tests in their sandbox at all, because desktop Chrome won't start there. So every change to the annotation UI waits for a person to run the suite and paste back the result.

The performance harness from [#108](https://github.com/text-harvest/tater/issues/108) and the hosted-mode check script use Playwright, which installs its own browser with one command and runs in the sandbox. As a result, the same helpers exist twice: going to document k, waiting for the callbacks to settle, counting callback requests and bytes, reading the saved file. A fix to one copy doesn't reach the other.

Coverage is also thin where the worst bugs have been. No test reloads the page with every widget type filled in and checks that each value comes back. That includes repeaters, nested repeaters, spans and hierarchical labels. Hosted mode has no browser tests at all. A standalone script checks that edits survive reload and Next/Prev and that two sessions stay separate, but nothing runs it automatically.

## Appetite

About a week or two. This is a port plus two new test groups, not a redesign of how tater is tested. Random-action and agent testing ([#109](https://github.com/text-harvest/tater/issues/109)) builds on this work and isn't part of it.

## Solution

All browser tests run on Playwright, sharing one set of helpers with the performance harness. The work happens in three steps, in this order.

### 1. Add the missing tests first

New coverage comes before the port, so it starts paying off right away and the port has a safety net.

- **Every widget survives a reload (single mode).** One project uses a schema with every widget type, including a repeater, a nested repeater, a span field inside a repeater, and both hierarchical-label widgets. The test fills a value into each one, then checks that each value is still there after Next and Prev, after a page reload, and in the saved file.
- **Hosted mode.** The checks from the hosted script become tests: for each built-in example, edits survive reload and Next/Prev, and two browser sessions on one server don't see each other's work. The standalone script is then deleted.

### 2. Port the existing tests

The roughly forty existing browser tests (navigation, document selector, flag and notes, persistence, auto-advance, save and restore, and the large-project request bounds) move over one group at a time. Each keeps exactly the assertions it has now. Workarounds that only exist because of Selenium go away, such as clicking through JavaScript to get past the sticky footer and fixed sleeps. Playwright waits for elements on its own.

The large-project tests count requests and bytes the same way the performance harness does, using the shared helpers.

### 3. Remove Selenium

Remove Dash's testing extra, Selenium, the ChromeDriver manager and the Chrome-specific driver setup. The README's test instructions shrink to "install the browser once, then run pytest." The commands to run the fast tests, the browser tests and the slow 10,000-document tests stay the same.

Sketch of where things end up:

```
shared browser helpers ──┬── browser tests (pytest)
  go to document k       │     single mode: navigation, selector, flag/notes,
  wait until quiet       │       persistence, widget round-trip, request bounds
  count requests/bytes   │     hosted mode: reload, Next/Prev, two sessions
  read saved file        │
                         └── performance harness (unchanged commands)
synthetic projects ──────────┘
```

## Details and open questions

- **Where the server runs.** Dash's test tools run tater in a thread inside the test process, so a test can tell the app to write pending saves and then read the file. The performance harness runs tater as a separate process, like the real CLI. The likely answer is in-process for single-mode tests, because they're faster and can flush saves directly, and a separate process for hosted mode, which needs real sessions and cookies. To settle while building.
- **Plugin or own fixtures.** Playwright's pytest plugin provides browser and page fixtures, a headed/headless switch, and traces of failed tests that can be replayed step by step. It's probably worth using unless it conflicts with how the harness launches browsers.
- **Speed.** The suite shouldn't get slower than it is now. Reusing one browser across tests and opening a fresh page for each test should make it faster.
- **Continuous integration.** There isn't any yet. This work makes it much easier to add, since there's no Chrome or driver version to match, but adding it is a separate decision.

## Rabbit holes

- **Improving tests while porting them.** Port first with identical assertions, so a failing test means the port is wrong, not the app. Improvements come after, as separate changes.
- **Reworking the performance harness.** Only move the helpers that both sides need. The harness's commands, outputs and baseline stay as they are.
- **Chasing flakiness in the new hosted tests.** Hosted tests start a real server and two browser sessions. If one is flaky, fix the wait it depends on. Don't add retries.

## No-gos

- Random-action consistency checks, stress conditions and agent runs. Those are [#109](https://github.com/text-harvest/tater/issues/109).
- Load testing hosted mode with many concurrent users. That's [#115](https://github.com/text-harvest/tater/issues/115).
- Testing in Firefox or WebKit. Chromium only, as now.
- Setting up continuous integration.
