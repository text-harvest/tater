# Combining annotators' work and resolving disagreements

*A pitch for discussion: the open questions below are meant to be argued about before any building starts. It began as the second half of [#39](https://github.com/text-harvest/tater/issues/39), which now covers the first half, sharing documents out.*

## Problem

When several people have annotated a project, the work is spread across files: one per annotator, in the launcher's results folder ([#82](https://github.com/text-harvest/tater/issues/82)) or copied back from people's own machines. The project lead then wants three things, roughly in this order:

1. **All of it in one place**, to analyse or hand on.
2. **How well people agree**, on the documents more than one person did. This is the first sign of whether the guidelines are clear, and it's often a number that has to be reported.
3. **One final answer per document** where people disagreed, decided by someone: a lead, or several reviewers sharing the load.

Tater helps with none of these. Each project writes its own merge script, works out agreement in a spreadsheet, and resolves disagreements by opening files side by side. The last of these is the worst: tater's own interface is the best place to look at a document and its annotations, and reviewers can't use it.

Projects differ. Some only want an agreement figure from a small shared set. Others annotate everything twice and resolve every disagreement. Some have one reviewer, others several. The tools need to suit all of these without a different workflow for each.

## Appetite

Two weeks, in two parts that could be pitched apart if this turns out too big. The first week is combining and the agreement report, both of which are useful on their own. The second week is reviewing inside tater. If time runs short, reviewing covers the simple field types and the rest are shown but not resolved.

## Solution

### Combining

A command, provisionally **`tater-masher`** (to go with `tater-dicer` for splitting), that reads every annotator's annotations file and writes one combined file: for each document, each annotator's annotations and status. It takes the launcher's results folder, or a list of files from single-mode annotators, and the assignment record from the dicer if there is one. With the record, it knows which documents were meant to be compared. Without it, it compares whatever overlaps.

Only documents an annotator marked complete count by default, so half-finished work doesn't show up as disagreement.

### The agreement report

The same command writes a report for the overlap documents:

- **Per field, how often annotators agree**, using the measure that fits the field. Simple agreement for everything; a chance-corrected figure (Cohen's kappa for two annotators, Krippendorff's alpha for more, or missing values) for choice and yes/no fields. For multi-choice, per option. For hierarchical labels, at each level of the tree, since agreeing on "animal" but not on "dog" or "cat" is useful to know.
- **Per pair of annotators**, so one person who reads the guidelines differently stands out.
- **The documents with disagreements**, listed per field, so a lead can look at a few before deciding whether reviewing is needed at all.

A readable page (or markdown) for people, and a data file for anyone who wants to compute their own figures.

```
  results/alice ─┐                         ┌─► combined annotations
  results/bob   ─┼─►  tater-masher  ───────┼─► agreement report
  results/carol ─┘    (+ assignment        └─► review sets: the documents
                        record, if any)          to resolve, shared among
                                                 reviewers if there are several
                                                          │
                                                          ▼
                                           tater in review mode ──► final annotations
```

### Reviewing inside tater

A reviewer opens the disagreements in ordinary tater, in a review mode. It shows the same document and the same widgets, with three differences:

- **Only the documents that need a decision** are listed: those where annotators disagree, or every overlap document, as the lead chooses.
- **Each field shows what each annotator chose**, next to the control: "alice: positive · bob: negative". Where everyone agrees, the field is filled in already and marked as agreed.
- **The reviewer's choices are the final answer.** They pick one annotator's value, or set their own, and it's saved like any annotation, to the reviewer's own file.

The result is one final file: agreed values where people agreed, and the reviewer's decisions where they didn't.

Because it's ordinary tater, a reviewer is just another kind of person in the launcher: the project file lists reviewers, and each gets a link and a process like an annotator does. Without the launcher, review mode is a flag to single mode with the combined file as input. Several reviewers each get a share of the review documents, made the same way the dicer makes annotators' shares.

## Details and open questions

- **Fields that don't line up.** Choice, yes/no and number fields compare directly. The rest don't:
  - **Spans:** two annotators rarely mark exactly the same characters. Do two spans "agree" if they overlap, or only if they match exactly? Probably both figures, as span-annotation tools usually report. For review, show each annotator's spans in their own colour and let the reviewer keep, drop or redraw them.
  - **Lists of items** (repeaters): alice found three findings and bob two. Which of alice's matches which of bob's? There's no reliable answer in general. Possibly match by a key field the schema names, and otherwise show them side by side and let the reviewer build the final list.
  - **Free text:** no agreement figure; shown side by side for the reviewer.
  - **Conditional fields:** when annotators disagree on the controlling field, the dependent field's disagreement may not mean anything. Report it separately, or skip it.
- **How much of review mode is new.** Showing other annotators' values next to every widget touches every widget type. A smaller first version could show them in a panel beside the form instead, and leave the widgets alone. That's less pleasant, but much less work.
- **Flags and notes.** Annotators' flags and notes are often the most useful thing a reviewer can see ("unsure, the report is ambiguous"). Show them in review mode. Should a flag also put a document up for review even when the annotations agree?
- **Reviewer as annotator.** Does a reviewer's decision count as a third annotation in agreement figures? Usually not, but some projects report agreement with the final answer.
- **Who reviews what.** One lead reviews everything; several reviewers split the documents; or two reviewers each review everything and disagree again. The first two seem worth supporting from the start; the third is rare.
- **Partial agreement.** On a multi-choice field, alice picks A and B and bob picks A. Agreed on A, disagreed on B? Review per option, or per field?
- **Status in the combined file.** What's a document's status when two annotators finished it and one didn't? The combined file probably keeps each annotator's status and leaves the judgement to the report.
- **Re-running.** Annotators keep working after a first report. Running the masher again should update the combined file and the review sets without losing decisions reviewers have already made.
- **Hosted mode.** A page that takes several downloaded annotations files and gives back the report would suit occasional users. Later, if at all.

## Rabbit holes

- **Every agreement measure.** There are dozens. Pick the few that cover the field types and say which were used. Anyone who wants more has the data file.
- **Automatic resolution.** Majority vote with three annotators is tempting, and some projects want it. It's a rule in the masher, not a feature of review mode. At most one simple rule, and only on request.
- **Live agreement.** Figures updating while people annotate needs the processes to coordinate. The report is run when the lead asks for it.
- **A separate review application.** Reviewing happens in tater, with tater's widgets. Building a second interface for it doubles the work and drifts apart from the first.

## No-gos

- Sharing documents out in the first place: [#39](https://github.com/text-harvest/tater/issues/39).
- Changing what annotators see while they annotate. Annotators never see each other's work.
- Training or evaluating models against the final annotations. The combined and final files are the hand-off.
