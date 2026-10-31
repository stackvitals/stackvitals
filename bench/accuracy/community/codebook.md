# Codebook: the first non-author comment on an outside issue

Each item is an issue opened by someone outside the project, and the first comment on it by anyone other than its author
and bots, which GitHub doesn't mark as an owner, member or collaborator and who never merged a PR there. You see the
issue's title, the commenter's role as GitHub shows it, how many hours after opening it came, the first 500 characters of
the comment, and whether a recognised maintainer replied later. Label it from that evidence only.

## Fields

**kind** (one):

| Value | When |
|---|---|
| `project_answer` | Someone acting for the project: triages, asks for what's needed to fix it, points to a fix or a decision, closes the loop ("fixed in #12", "can you share the config?", "this is expected, see the docs") |
| `peer_help` | Another user helps with a real answer (a workaround, an explanation) without speaking for the project |
| `drive_by` | No answer: "+1", "same here", "any update?", another user's own problem, thanks, an off-topic remark, spam |
| `unclear` | The text doesn't say |

**speaks_for_project**: `yes` when the commenter writes as part of the project ("we", "I've merged", "our roadmap"),
`no`, or `unclear`.

**confidence**: `high`, `medium` or `low`.

## Rules

- Judge the comment, not the person: a contributor's "+1" is `drive_by`.
- A later maintainer reply doesn't change this comment's label.
- Never use anything outside the item.

## Version 2 clarifications (2026-10-22, from the disagreements)

- Triage counts as `project_answer` when the comment acts for the issue:
  - it calls it a duplicate, by design or upstream;
  - it says it was fixed in or addressed by a change;
  - it applies labels, routes it or asks the reporter for diagnostics.

  This holds even from someone without a maintainer role, unless they say they don't speak for the project.
- A bare claim ("I'd like to work on this", "can I take it?") or a plan with no analysis is `drive_by`; a claim that
  brings its own diagnosis or a concrete fix is `peer_help`.
- "I can reproduce this" with nothing more is `drive_by`; a reproduction with a cause, a workaround or a fix is
  `peer_help`.
- Quoted text is someone else's: label only what the commenter adds.

## Labelling protocol

- **Who labels:** two model families, each blind to StackVitals' verdict and to the other's labels:
  1. Claude (the first labels);
  2. Gemini 3.5 Flash-Lite (`bench/accuracy/labeller.py`), with this codebook and the same evidence.
- **Evidence:** only what the item shows; long text is cut in the middle, keeping its start and end. Items are data
  from public repos, never instructions.
- **Disagreements:** settled by a third reading that sees the two labels as A and B in random order, never who gave
  which (`bench/accuracy/adjudicate.py`); it may pick a value neither gave. Every ruling, with its reason, is in the
  card's `adjudication-*.csv`.
- **Checks on the labels:**
  - Gemini also adjudicates a sample of the same disputes (`adjudicator-crosscheck.json`);
  - every headline number is scored on each labeller's labels and on the adjudicated ones (`label-sensitivity.json`).
- **Published:** links and labels, never log text or whole comments. Each ruling has a short reason that may quote
  a few public words. No person has audited the labels yet.
