---
name: catchup
description: Orient yourself at session start — check issues, PRs, branch state, and recent progress. Use when starting a new session, resuming after a break, or when you need to understand what was accomplished last. Prevents redoing completed work.
---

# Catchup: Session Start

Verify project state before starting work. Each agent session is ephemeral — previous work may sit on an unmerged branch, an open PR, or a stale issue. Without checking, you risk redoing completed work.

## Protocol

### 1. Check Git State

```bash
# Current branch and tracking
git status -sb

# Feature branches with potential work
git branch -a

# Local commits not on remote
git log origin/HEAD..HEAD --oneline 2>/dev/null
```

### 2. Check Open PRs

```bash
gh pr list --repo stfc/goldilocks-core --state open --limit 10
gh pr checks <number> --repo stfc/goldilocks-core
```

For each open PR, note: which issue it closes, whether checks pass, and whether it's been reviewed.

### 3. Read Recent Issue Activity

```bash
gh issue list --repo stfc/goldilocks-core --state open --limit 10
gh issue list --repo stfc/goldilocks-core --state all --limit 5 --search "sort:updated-desc"
```

Read the most recently updated issues. Check their comments for progress reports from previous sessions.

Focus on:
- **Open questions** — unresolved decisions that block work
- **Next steps** — what was the intended next action?
- **Blockers** — is anything waiting on review, external input, or another PR?

### 4. Cross-Reference

Compare what you found:
- Branch exists locally, not pushed → risk of lost work
- Branch pushed, no PR → risk another session won't find it
- PR open, not merged → starting new work may cause conflicts
- Issue says "in progress" but no branch → stale status
- PR merged but issue still open → close it
- Recent issue comments disagree with the actual branch or PR state → fix the record

### 5. Present Summary

```markdown
## Project State

**Branch**: [current]
**Open PRs**: [list or none]
**Issue activity**: [what's in flight]

### Pending Work
- Issue #N: [status, what's left]
- Issue #M: [status, what's left]

### Discrepancies
- [Any mismatch between issues/comments and actual git state]

### Recommended Next Step
[What to do next, based on the above]
```

## After Catchup

1. Fix discrepancies first — push stranded branches, close stale issues, correct issue/PR status
2. Confirm the next step with the user
3. Proceed with work

If catchup reveals completed work that wasn't integrated:
- **Do NOT redo the work.** Push, PR, or merge the existing work first.
