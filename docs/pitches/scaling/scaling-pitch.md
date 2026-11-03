# Scaling to 10k documents

## Problem

Tater slows down as a project grows, in two ways: with the number of documents, and with the length of each document. The document-menu freeze in [#107](https://github.com/text-harvest/tater/issues/107) was the extreme case. Before that fix, a single Next click on 2,500 short documents set off about 20 server requests over 11 seconds. That freeze is fixed, but the investigation turned up several other places where the cost of one action grows with the size of the project. They are listed in [#108](https://github.com/text-harvest/tater/issues/108).

The biggest of these is how annotation state moves around. The browser holds the annotations and status for every document, and most server requests carry that whole collection with them, even when the action only touches the document on screen. At 2,500 documents that's roughly 270 KB per request and 3.5 MB per Next click, and it grows linearly with the number of documents and with how much has been annotated. Auto-save makes it worse: every change uploads everything to the server, which then rewrites the whole annotations file. That can happen several times per action.

Smaller costs pile up on top: linear searches to find the current document, progress totals recounted from scratch, and a document selector with no display limit. Long documents add their own costs: the full text is sent and redrawn on every navigation.

None of these hurts much at today's typical sizes. They are the next bottlenecks, and we'd rather find them with measurements than with an annotator's report.

## Appetite

Support up to **10,000 documents** in a single project, with Next, ticking a checkbox and typing feeling instant. We stay on Dash; this isn't a rewrite. Single mode (one annotator, local files) comes first. Hosted mode is in scope too, but after single mode.

## Solution

### Measure first

Before changing anything, build a way to generate synthetic projects and measure them:

- **Number of documents:** 1k, 2.5k, 10k.
- **Document length:** a sentence, a few pages, a book chapter.
- **Annotation density:** an empty project, and one where every document is filled in, including many highlighted spans.
- **Schema:** a single checkbox group, or a realistic mix with repeaters, spans, hierarchical labels and conditional fields.

For each common action (page load, Next, ticking a checkbox, typing, adding a span, searching the document selector) we record:

- how many requests it sends
- how much data goes each way
- how long the server spends
- how long until things settle
- how long the browser is blocked

We also record startup time, save time and memory.

That gives one table. We rank its entries by **cost per action times how often the action happens**. Next and checkbox ticks happen thousands of times per session; startup happens once. Anything that stays under about a tenth of a second at 10k drops off the list.

### Then fix, in roughly this order

The baseline decides the final order, but we expect something like this.

**Cheap fixes we'd do anyway:**
- Make saves safe against a crash halfway through a write. Today that can corrupt the annotations file, and the risk grows with the file.
- Stop saving when nothing changed, and combine the saves from one action into one write.
- Replace linear searches with direct lookups.
- Keep running progress totals instead of recounting.
- Cap how many entries the document selector draws at once.

**The main fix: send only the current document.**
- Auto-save sends only what changed, not every document.
- Server-side steps that only care about the document on screen receive only that document's data, and send back only that document's changes.
- We convert these one at a time, starting with the most expensive. Some may move entirely into the browser instead.

**Only if the numbers still call for it:**
- Store annotations so a save writes only the changed document. The JSON file people download stays as it is.
- For long documents, keep the text of documents already visited in the browser, and load the next one ahead of time.

### Keep it from regressing

Extend the existing large-project browser tests to check the amount of data sent per action, not just the number of requests. The data per action should stay about the same whether a project has 1k documents or 10k. Add a 10k case that doesn't run by default.

### Hosted mode

Once single mode is in shape, apply the same measurements to hosted mode. Hosted mode never auto-saves, but it has the same problem of whole collections travelling with each request, so most of the single-mode work carries over. What's specific to hosted mode is memory: each session holds its own full copy of its project. We'd measure how memory grows with sessions × documents, and look at sharing content between sessions for the built-in examples.

## Rabbit holes

- **Making the server the owner of annotation state.** The browser would hold only the current document. That would fix page load and data transfer at once, but it reverses a core design decision: today every change happens in the browser. Only consider it if sending just the current document isn't enough.
- **Virtualized rendering of very long documents.** It's tempting, but it gets complicated quickly once highlighted spans are involved. Wait until the measurements show that drawing the document is actually the bottleneck.
- **A database behind everything.** A save that writes only the changed document may justify a small embedded database. That shouldn't grow into a storage-layer redesign.

## No-gos

- More than 10,000 documents per project.
- Replacing Dash, or a separate frontend.
- Changing the annotations file format that people download and load.
- Real-time collaboration, or several annotators on one project.
