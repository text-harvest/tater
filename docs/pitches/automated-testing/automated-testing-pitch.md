# Automated usability and performance testing

## Problem

Tater's worst recent bugs weren't logic errors that a unit test catches. They only appear when someone uses the app the way annotators do, with a realistic project, over many actions.

The document-menu freeze in [#107](https://github.com/text-harvest/tater/issues/107) only appeared with about a thousand documents or more. It was found by hand: driving the app in a browser, timing each action, and comparing runs with different document counts. While shaping [#108](https://github.com/text-harvest/tater/issues/108) we found another bug the same way: in single mode, reloading the page brings back the annotations from when the server started, and the next change then overwrites the saved file with them. No existing test reloads the page and keeps working.

Finding these by hand doesn't scale. It takes someone who already suspects a problem, and it only covers the paths they think to try.

## Appetite

A few weeks, after the measurement harness from [#108](https://github.com/text-harvest/tater/issues/108) exists. This pitch adds layers on top of that harness; it doesn't build its own. The output is reports and draft issues for a person to review, never automatic fixes.

## Solution

Three layers, each useful on its own, in this order.

### 1. Consistency checks under random use

A test drives the app with long random sequences of real actions:

- clicking Next and Prev
- jumping with the selector
- ticking, typing and adding spans
- flagging and filtering
- reloading the page
- clicking rapidly

After each step it checks invariants that must always hold:

- the values on screen match what's in the saved file for that document
- no save is lost or applied out of order
- the status badge and progress counts agree with the annotations
- the browser console shows no errors

When an invariant breaks, the test shrinks the sequence down to the shortest one that still fails and reports that. Property-based testing tools do this kind of shrinking already.

The checks are cheap enough to run on every pull request at a small project size, and nightly at a large one. They'd have caught the reload bug, and they'd catch races between overlapping saves.

### 2. Stress conditions

Run the #108 journeys under conditions annotators actually have but developers rarely test:

- a slowed-down CPU (an old laptop)
- a slow, laggy network (hosted mode over a VPN)
- several people using one hosted server at once

The harness already measures each action; this layer just changes the conditions and compares.

### 3. Agents exploring as annotators

An LLM agent is given a persona and a synthetic project, and drives tater through the same browser tooling the harness uses. Example personas:

- **Fast annotator:** keyboard-heavy, never waits.
- **Reviewer:** jumps around, filters to flagged documents, edits earlier work.
- **New user:** reads the instructions and hesitates.
- **Interrupted annotator:** reloads, closes the tab, comes back.

The agent can run the measurements and read the callback trace from #108. It writes a short report:

- what it did
- what it measured
- what looked wrong
- the likely cause, with links to the code

Every claim has to point at a measurement or a trace line. A claim without evidence goes into a separate "unconfirmed" list. Reports can also note usability friction: a control that was hard to find, a status that didn't update when expected, a flow that took more steps than it should. These go in their own section, since they're judgment calls rather than measurements.

This runs on demand at first: before a release, and on pull requests that change the annotation UI. It moves to a nightly job only once the reports are consistently worth reading. Journeys an agent finds useful get turned into regular scripted tests, so they keep running without the agent.

## Rabbit holes

- **Trusting agent output.** Agents produce confident wrong explanations. The evidence rule is the guard: no measurement, no claim. A person decides what becomes an issue.
- **Flaky timing.** Timing checks in random-action tests make them flaky. The consistency checks test correctness only; timing stays in the harness, with medians over repeated runs.
- **Cost creep.** Agent runs cost money and attention. Start on demand, with a small fixed set of personas, and only add more once reports pay off.
- **Building a second harness.** Everything here reuses the #108 harness: the synthetic projects, the per-action measurements, the trace. If something is missing, add it there.

## No-gos

- Agents opening pull requests or changing code.
- Real annotation data in any test or agent run. Synthetic data only.
- Blocking merges on agent reports. The consistency checks can gate merges; agent reports can't.
- Performance work itself: finding and fixing slow paths belongs to [#108](https://github.com/text-harvest/tater/issues/108).
