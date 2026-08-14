---
name: triage
description: Triage the GitHub issue board — close stale/superseded/out-of-scope issues, fold duplicates, assign milestones, enforce one-issue-per-PR/feature. Use when the board has accumulated, before or after a milestone, or when catchup surfaces candidates.
argument-hint: [repo, or leave blank for stfc/goldilocks-core]
---

# Triage: Clean the Issue Board

Keep the issue board small and shippable. Every open issue should be one PR/feature with a milestone; nothing stale, duplicated, superseded, or decision-only.

## When to use

- `catchup` surfaced triage candidates.
- The open-issue count is growing and the direction is unclear.
- Before or after closing a milestone.
- The user says "clean up the issues" / "the board is a mess" / "too many issues" / "consolidate".

## Principle

Issue hygiene is policy in AGENTS.md; this skill is the pass that enforces it. The rules that bite most often: **one issue per PR/feature**, and **no placeholders**. Decision, discussion, sub-step, placeholder ("scope still to be worked out"), and roadmap-mirror (filed to "make the milestone reflect its real scope") issues are all spam — their content folds into the feature issue they belong to, or stays on the roadmap. A 40-issue board where 8 are one not-started refactor is the failure mode this skill prevents.

## Process

### 1. Snapshot the board

```bash
gh issue list --repo stfc/goldilocks-core --state open --limit 200 \
  --json number,title,labels,milestone,createdAt,updatedAt --jq 'sort_by(.number)'
gh api repos/stfc/goldilocks-core/milestones \
  --jq '.[] | "\(.number) | \(.title) | open=\(.open_issues) closed=\(.closed_issues)"'
gh issue list --repo stfc/goldilocks-core --state open --limit 200 \
  --json number,milestone --jq '[.[] | select(.milestone == null)] | length'
```

Read every open issue body and recent comments. You cannot triage what you have not read — a title is not enough.

### 2. Classify each issue

- **Keep** — a shippable PR/feature, current, not duplicated.
- **Close: superseded** — covered by another issue or by merged code. Point at the survivor.
- **Close: duplicate** — same feature/decision as another; pick one, point the rest at it.
- **Close: decision-only** — a question, not a PR. Fold its content into the feature issue it gates, then close with a pointer.
- **Close: placeholder / no plan** — "scope and design still to be worked out" or no concrete problem + proposed approach. Fold any useful direction into the feature it would belong to, or leave it on the roadmap; close with a pointer.
- **Close: roadmap mirror** — filed to "make the milestone reflect its real scope" rather than to track shippable work. The deliverable belongs on the roadmap, not as an open issue.
- **Close: out of scope** — not core's concern (AGENTS.md "What doesn't belong here").
- **Close: stale / done** — no movement, or the work already landed.
- **Fold** — distinct content that belongs inside another issue. Carry the content (a comment, or a body edit if it is your issue to edit), then close the source with a pointer.
- **Milestone** — every kept issue gets a milestone; propose new milestones for clusters that have none.

### 3. Propose, then execute

Present the plan as a fold map: keep / close / fold, with source → target. Get the user's nod before executing — especially before closing issues authored by someone else. Never edit someone else's GitHub text; comment + close only.

A good proposal is a single table the user can approve in one word:

```markdown
| close | → into | reason |
|---|---|---|
| #91 | #99 | self-marked superseded |
| #71–#78 | #70 | 8 stage issues = one not-started feature |
```

### 4. Execute

- Create / assign milestones (REST API, numeric id — see `github-cli`).
- Edit bodies only on issues you may edit (your own, or agent-authored on your user's behalf). For others, comment + close.
- Close-with-comment: `gh issue comment <N> --body-file ...` then `gh issue close <N>`.
- Every agent-written comment includes `Written by an agent on behalf of <user>.`
- Reuse the consolidation framing in close comments ("Consolidating to cut down the open issue count…") — not personal attribution of who decided what.

### 5. Report

Leave a summary: from N → M open issues, what closed/folded, final milestone state. If there is a scratchpad, write the triage record there (e.g. `scratchpad/core/reports/<date>-issue-triage-*.md`).

## Guardrails

- Don't delete — closing preserves bodies and comments. It is reversible.
- Never edit or delete GitHub text authored by someone else. Comment instead.
- Don't close an issue that has an open PR unless the PR is merged or closed.
- One issue per PR/feature is the rule that stops the board drifting again.
- When in doubt, fewer issues is better — but never sacrifice clarity of *what work needs doing* for a lower count.

## See also

- `catchup` — surfaces triage candidates at session start.
- `github-cli` — milestone and close-with-comment command recipes.
- AGENTS.md "Issue hygiene" — the policy this skill enforces.