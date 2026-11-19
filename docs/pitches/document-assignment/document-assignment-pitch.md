# Sharing out documents among annotators

*A pitch for discussion: the open questions below are meant to be argued about before any building starts.*

## Problem

A project with several annotators starts with one set of documents and a question: who annotates what? Usually each person gets their own share, and some documents go to more than one person, either so agreement can be measured or because every document is meant to be annotated twice and the differences resolved.

Tater has no help for this. The launcher ([#82](https://github.com/text-harvest/tater/issues/82)) lets the project file give each annotator their own documents file, and single mode takes whatever file it's given, but producing those files is left to the admin. Today that means a script or a spreadsheet, written fresh for each project, and the mistakes are easy and silent: a document that nobody got, overlap that's smaller than intended, two shares built from different versions of the document set, or a re-split halfway through that moves documents away from someone who had already annotated them.

It has to work without the launcher too. Two annotators running single mode on their own machines need the same thing: one file each, with the right overlap.

## Appetite

About a week. It's one small tool, but the decisions in it (overlap shapes, what happens on a re-split) are the kind that are cheap to get right now and expensive to change once projects depend on them.

## Solution

A command, provisionally **`tater-dicer`**, that takes a document set and a list of annotators and writes one documents file per annotator, plus a record of who got what.

```
   documents.json ──┐                              ┌─► alice.json
   (or CSV, Excel)  │                              ├─► bob.json
                    ├──►  tater-dicer  ────────────┼─► carol.json
   annotators,      │    (seeded, so the same      │
   overlap, weights ┘     inputs give the same     └─► assignment record:
                          split every time)             who has which document,
                                                        and why
```

The output files are ordinary documents files, so they work anywhere tater takes documents: single mode on someone's laptop, a launcher project file, or a notebook. Nothing in tater needs to know they came from the dicer.

### Ways of overlapping

Projects want different things, and the tool should cover the common shapes rather than pick one:

- **A shared set.** A fixed number or share of documents goes to everyone; the rest is divided. This is the usual setup for measuring agreement: everyone annotates the same 50 documents, then works on their own.
- **Each document to several people.** Every document goes to exactly two (or three) annotators, spread so each pair overlaps about equally. This is full double annotation, where every disagreement gets resolved.
- **A mix.** Each document to one person, plus a share of documents to a second person, chosen at random. Cheaper than full double annotation, with enough overlap for agreement figures.

Within any of these, annotators can be **weighted**: a part-timer gets half a share.

### The assignment record

Alongside the files, the dicer writes down the assignment: for each document, who has it, and whether it's an overlap document or someone's own. This record is what makes the rest safe:

- **Re-running is safe.** Given the record, the dicer keeps every existing assignment and only places what's new. Adding documents spreads them across the current annotators. Adding an annotator gives them new documents, and optionally takes some documents that nobody has started from the others. It never moves a document someone has already worked on, which it can tell from their annotations file if it's given one.
- **Merging knows the design.** Combining the results later (the second half of #39, pitched separately) can read the record to know which documents were meant to be compared, rather than guessing from whatever overlaps.
- **Anyone can check it.** It's a plain file an admin can open and read.

### With the launcher

The launcher can use the dicer's output as it is: each annotator's `documents:` points at their file. A later step is to let the project file describe the split itself (overlap and weights in place of per-annotator files), with the launcher running the same logic and keeping the record in its own folder. That's more convenient, but it's the same tool underneath, so it can wait until the standalone command has been used on a real project.

## Details and open questions

- **Names.** `tater-dicer` for this one, and perhaps `tater-masher` for combining results later. Fun, and it makes them easy to find, but it's another set of names to explain. Alternatively, subcommands of one `tater-tools` command.
- **Document IDs.** The dicer relies on every document having an ID that doesn't change between runs. Tater can make up IDs for documents that don't have them, but made-up IDs shift if the file is edited. The dicer should probably refuse documents without IDs, or write a copy of the set with IDs added, and say which.
- **Output format.** The same format as the input (CSV in, CSV out), or always JSON? Matching the input keeps extra columns where people expect them.
- **Spreading the overlap.** With "each document to two people", should every pair of annotators share about the same number of documents? That makes per-pair agreement figures comparable, and it's what most agreement measures assume. It's slightly more work to arrange than random pairs.
- **Stratifying.** Should the split balance by a column (a source, a document type, a date range) so that everyone's share and the shared set look like the whole? Useful, but easy to over-design. One column, or nothing, at first.
- **Order.** Should each annotator get their documents shuffled, or in the original order? Shuffling avoids everyone doing the overlap documents first (or last), which can skew agreement figures as people learn.
- **Calibration rounds.** Some projects start with a small set everyone does, then meet, adjust the guidelines, and only then split the rest. That's two runs of the dicer with a shared record, which the record design should allow.
- **Reviewers.** If reviewing disagreements is to be shared among several reviewers, the reviewers' shares are another split. Whether the dicer makes it, or the review tool does, depends on the second pitch.
- **Removing someone.** An annotator leaves partway through. Their unstarted documents go back to the pool; what about started ones? Probably reported, and left for the admin to decide.

## Rabbit holes

- **A scheduler.** Handing out documents live as people finish them ("the next document nobody has done") needs the processes to talk to each other and is a different design. This is a split done up front, and re-done safely when things change.
- **Statistical design tools.** Working out how much overlap a project needs for a given confidence in its agreement figure is a real question, but a separate one. The dicer takes the overlap as given.
- **A web page for it.** A command and a file first. If admins in hosted mode want it, a page can come later.

## No-gos

- Combining annotators' results and reviewing disagreements: the second pitch.
- Changing how tater itself loads documents. The dicer writes ordinary documents files.
- Live assignment while annotators work.
