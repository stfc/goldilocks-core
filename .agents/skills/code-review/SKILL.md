---
name: code-review
description: Review changes against main before opening a PR or when the user asks for review. Checks correctness, edge cases, architecture, regressions, and test gaps.
---

# Code Review

Review the current changes before they leave this branch. Catch problems here, not in PR comments.

## What to review

Check both:
- uncommitted changes in the working tree
- commits on the current branch not on main

```bash
git status -sb
git diff --stat
git diff main...HEAD --stat
git log main..HEAD --oneline 2>/dev/null
```

If there's nothing to review, say so and stop.

## Review focus

### Correctness
- Does the code do what it claims? Check the logic, not just the intent.
- Are there edge cases that break it? Empty inputs, single elements, boundary values, None/missing fields.
- Are error paths handled? Do they raise the right exception with the right message?

### Architecture
- Does the change respect module boundaries? No cross-cutting imports that shouldn't exist.
- Does it put logic in the right layer? Advisors orchestrate, generators translate, types carry data.
- Does it introduce coupling that will be hard to undo?

### Regressions
- Does anything existing break? Run the tests.
- Does the change change the public API surface without updating callers?
- Are there implicit behavioural changes — different defaults, removed fallbacks, changed error handling?

### Testing
- Are new public functions tested?
- Are edge cases covered, or just the happy path?
- Do tests depend on `local_data/` or non-portable fixtures? They shouldn't.

### Code quality
- Leftover debug prints, commented-out code, TODO without an issue?
- Does it follow the project code style? (Ruff should catch most of this, but check anyway.)
- Are docstrings factual, or do they contain implementation details that will rot?

## Report findings

Classify each finding:

| Severity | Meaning |
|----------|---------|
| **Critical** | Broken behaviour, data loss, security issue. Must fix before merge. |
| **High** | Likely bug, missing test for important path, architectural violation. Should fix. |
| **Medium** | Minor bug, style inconsistency, fragile pattern. Fix if convenient. |
| **Low** | Nit, opinion, nice-to-have. Mention but don't block on it. |

Present a summary:

```markdown
## Review: [branch name]

**Files changed:** N
**Verdict:** ready / needs fixes / blocked

### Findings

| Severity | File | Issue |
|----------|------|-------|
| critical | path | description |
| high | path | description |
| ... | ... | ... |

### No significant issues
(If the branch is clean, say so explicitly — don't make the user wonder if you skipped something.)

---
Written by an agent on behalf of <user>.
```

## After review

- If findings are critical or high, offer to fix them before opening the PR.
- If findings are medium/low only, note them in the PR body and proceed.
- If the branch is clean, proceed to open the PR.

## Gotchas

- If posting the review to GitHub, include `Written by an agent on behalf of <user>.`, replacing `<user>` with the human who requested the review.
- Review findings are recommendations, not automatic truth. Verify file paths and claims before acting.
- If `main` is stale locally, fetch first so you're comparing against a real baseline.
- A very large branch will produce a broad, less precise review. Say so if that's the case.