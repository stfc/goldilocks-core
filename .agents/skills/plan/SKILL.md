---
name: plan
description: Create an implementation plan as a GitHub Issue. Use when the user asks to plan a feature, refactor, bugfix, or multi-step task. Also use when breaking down work before starting implementation.
argument-hint: [topic or feature to plan]
---

# Plan: Create an Issue

Plan: **$ARGUMENTS**

Create a structured plan as a GitHub Issue. The issue body serves as the plan document — it persists across sessions, is searchable, and can be referenced by PRs.

## Planning Principles

**Keep plans proportional to the task.** A quick fix needs a short issue. A multi-phase refactor needs phases, tasks, and acceptance criteria. Match the plan's weight to the work's complexity.

**Specify direction, not line numbers.** Identify files and describe what changes. Include draft code for key interfaces and non-obvious logic — real code that conveys the design.

**Plans are for orientation, not control.** A good plan helps the implementer understand *what* to build and *why*, then gets out of the way.

## Issue Hygiene

A plan becomes one GitHub issue and must clear the project's issue-hygiene bar (AGENTS.md) before filing:

- **No placeholders.** If you cannot state a concrete problem and a proposed approach, do not file — work the design first. "Scope and design still to be worked out" is not an issue; an unplanned deliverable is not an issue.
- **One issue per feature.** Decisions, questions, and sub-steps go in the issue's "Open questions" or phase checklist, not as separate issues.
- **Phases, not sub-issues.** Multi-phase work is one issue with a phase checklist. File a sub-issue only when its PR is about to start, or just open the PR.
- **Scope gate.** Check AGENTS.md "What doesn't belong here" first; an out-of-scope-layer item needs maintainer sign-off.
- **Reuse before creating.** Search open issues (`gh issue list --search ...`) first; extend rather than duplicate. If a closed issue's design is stale, fold the fresh design in and point at the closed one.
- **Check live state.** Read open issues, recent merged PRs, and any open decision the plan depends on; cite the controlling decision.
- **Every issue has a milestone.** Assign one; propose one if none fits.
- **Coordinate before burst.** Filing more than three issues, or any structural change (milestone, epic, label), needs prior maintainer agreement — not a fait accompli.

When in doubt, fewer issues is better. A 40-issue board where 8 are one not-started refactor is a failure mode, not thoroughness.

## Planning Process

1. **Research** — explore the codebase to understand current structure and constraints
2. **Search** — before creating, look for an existing open issue to extend (`gh issue list --search ...`). Reuse over create.
3. **Design** — define scope, goals, and key decisions
4. **Write** — create one GitHub Issue with the plan, and assign it to a milestone (propose one if none fits)
5. **Track** — keep the issue body current when the plan changes; use comments/PR links for progress, reviews, verification, and handoff history

## Issue Templates

### Lightweight (single-session work)

```markdown
## Problem
What's wrong or what's needed. Specific.

## Approach
How to tackle it. Files to touch, key changes.

## Acceptance Criteria
- [ ] [testable condition]
- [ ] [testable condition]

---
Written by an agent on behalf of <user>.
```

```bash
gh issue create --title "feat: short description" --body-file plan.md
```

### Full (multi-phase work)

One issue. Phases live in the body as the checklist below — do not file a sub-issue per phase.

```markdown
## Problem
What's wrong or what's needed. Why it matters.

## Goals
- Goal 1
- Goal 2

## Non-Goals
- What this plan explicitly does NOT address.

## Approach
High-level design decisions and rationale.
Include draft code for key interfaces.

## Phases

### Phase 1: [Name]
**Goal:** What this phase accomplishes

Tasks:
- [ ] P1-T1: Description
- [ ] P1-T2: Description

Verification: How to check this phase is complete.

### Phase 2: [Name]
(repeat)

## Open Questions
- Question 1?
- Question 2?

---
Written by an agent on behalf of <user>.
```

```bash
gh issue create --title "feat: short description" --body-file plan.md
```

## After Creating

1. Assign the issue to a milestone (or propose one) — no milestone-less issues
2. Summarize the plan for the user
3. Ask whether to proceed with implementation or refine the plan
4. As phases complete, update checklist state in the issue body if that checklist is the active tracker
5. Add progress, review results, verification output, and handoff notes as comments
6. Link the issue from follow-up PRs and reports so the thread remains the durable record

## Gotchas

- Every issue body created by an agent must include `Written by an agent on behalf of <user>.`, replacing `<user>` with the human who requested the work.
- Don't over-plan simple tasks — a 3-line issue for a typo fix is worse than just fixing it
- Update the issue body as understanding evolves, but do not edit it for routine status notes
- If the plan changes significantly, edit the issue — stale plans mislead future sessions
- If you are adding historical context rather than changing the current plan, comment instead
