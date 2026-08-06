---
name: report
description: Write a progress report as a GitHub Issue comment. Use when ending a session, completing a milestone, hitting a blocker, or when the user asks for a handoff. Captures decisions, reasoning, git state, and next actions so future sessions can resume without context loss.
argument-hint: [issue number to report on, or leave blank to infer]
---

# Report: Write a Progress Comment

Document what was accomplished and what's next, as a comment on the relevant issue. This is how sessions hand off to each other — the issue thread becomes a persistent timeline of progress, decisions, and blockers.

Issue: **$ARGUMENTS** (if blank, infer from the current branch or recent work)

## Why This Matters

Each agent session is ephemeral. Without a report, the next session has to reconstruct what happened from git history alone — which records *what* changed, not *why*. The issue thread fills that gap.

## Report Process

1. **Identify the issue** — which issue does this work belong to? If none exists and the work is a concrete shippable feature, file one (meeting AGENTS.md issue hygiene — no placeholder, no `decide(...)`). If it's a decision, question, or sub-step, fold it into an existing issue; don't file a placeholder just to have a thread.
2. **Review the session** — what was accomplished, what was decided, what remains.
3. **Write a comment** on the issue.
4. **Update the issue body only if needed** — approach, scope, acceptance criteria, or active checklist changed.
5. **Update the issue/PR record** with the lightest durable action that fits: comments for history, body edits for current plan/source-of-truth changes.

## Comment Format

```markdown
## Done
- [what was accomplished]

## Decisions
- [choices made and why — especially when the obvious path was rejected]

## Blockers / Open Questions
- [anything unresolved]

## Next
- [what the next step is]

---
Written by an agent on behalf of <user>.
```

## When to Report

- **End of a session** — always. Even if the session was short.
- **After completing a milestone** — document the achievement while it's fresh.
- **When hitting a blocker** — don't wait. Surface it so the next session (or a human) can act.
- **When a decision is made** — record the reasoning, not just the outcome.

## Updating the Issue Body

Comments document the journey; the issue body documents the current understanding. Be conservative with body edits.

Edit the issue body when:
- the work changed the plan — new scope, different approach, or discovered complications;
- acceptance criteria, goals, non-goals, or active task checklists are stale;
- a phase is complete and the body checklist is the active tracker;
- new open questions change what future sessions should do;
- the user asks to consolidate or revise the issue.

Do not edit the issue body for:
- routine progress reports;
- review findings;
- verification command output;
- session handoffs;
- small decisions that do not change the plan.

Post those as comments.

## Updating Work Status

Use the issue thread and PR state as the durable record.

Common transitions:
- Starting work → leave a report comment or push a branch linked to the issue
- Opening a PR → link it clearly in an issue comment; edit the body only if the issue tracks active PR state there
- PR merged → confirm completion and any follow-up work in a comment

If status changed, say so explicitly in the report instead of assuming the next session will infer it.

## Git State

Always include current git state in the report so the next session can verify:

```markdown
## Git State
- Branch: `feat/short-description`
- Pushed: yes/no
- PR: #N (open/merged/none)
- Ready for next step: yes/no (blocked by: ...)
```

## Self-Review Before Handoff

Before reporting, quick check:

```bash
# What did I actually change?
git diff main...HEAD --stat

# Did I leave debug prints or commented-out code?
git diff main...HEAD | grep -E "^\+.*(# |print|breakpoint|pdb)"
```

Clean up anything embarrassing before you call it done.

## Triage Nudge

Before ending, glance at the board. A session that only adds issues and never subtracts them is how the board drifts to 40.

```bash
# how many open issues have no milestone?
gh issue list --repo stfc/goldilocks-core --state open --limit 200 \
  --json number,milestone --jq '[.[] | select(.milestone == null)] | length'
```

If the count is non-zero, or the board has accumulated stale/superseded/duplicate/decision-only issues, suggest running `triage` before the next session starts.

## Gotchas

- Every issue comment written by an agent must include `Written by an agent on behalf of <user>.`, replacing `<user>` with the human who requested the work.
- Always verify git state before writing it — don't assume from conversation context
- If the report says "next: X", the next session should find X actionable — be specific
- Don't bury important decisions in long prose — the Decisions section should be scannable
- If you discovered a distinct new PR/feature during the session, file it as a separate issue. But if it's a decision, a question, or a sub-step of the current work, fold it into the current issue (open questions / checklist / comment) — don't spin up a new issue for it (per issue hygiene, AGENTS.md)
- Don't file a placeholder issue ("scope still to be worked out") or a roadmap-mirror issue just to have a thread to report on — report against the closest active issue or the branch instead
