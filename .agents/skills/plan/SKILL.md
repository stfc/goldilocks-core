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

## Planning Process

1. **Research** — explore the codebase to understand current structure and constraints
2. **Design** — define scope, goals, and key decisions
3. **Write** — create a GitHub Issue with the plan
4. **Track** — add the issue to the project board in **Backlog**

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

1. Add to the project board:
   ```bash
   gh project item-add <project-number> --url <issue-url>
   ```
2. Summarize the plan for the user
3. Ask whether to proceed with implementation or refine the plan
4. As phases complete, update the issue body — check off tasks, add notes about what changed

## Gotchas

- Every issue body created by an agent must include `Written by an agent on behalf of <user>.`, replacing `<user>` with the human who requested the work.
- Don't over-plan simple tasks — a 3-line issue for a typo fix is worse than just fixing it
- Update the issue body as understanding evolves, don't just append comments
- If the plan changes significantly, edit the issue — stale plans mislead future sessions