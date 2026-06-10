---
name: make-a-pr
description: Commit and open a pull request. Use when you have changes ready to submit — after implementing, testing, and self-reviewing.
---

# Make a PR

## Branch

1. Create a feature branch from main: `feat/short-description` or `fix/short-description`.
2. **Never push or merge directly to `main`.** All changes arrive through PRs.

## Commit

1. One logical change per commit. Fixing lint and adding a feature = two commits.
2. Conventional commits: `feat(scope): add ...`, `fix(scope): handle ...`, `docs: ...`, `test: ...`.
3. First line under 50 chars, imperative mood. Add a body if the "why" isn't obvious.

## Self-review

Before pushing, review your own diff:

```bash
git diff main...HEAD
```

Check for:
- Leftover debug prints, commented-out code, accidental formatting changes
- Missing tests for new public functions
- Changes you don't remember making

## Pre-commit

```bash
uv run pre-commit run --all-files
```

Fix any failures before pushing.

## Push

```bash
git push -u origin feat/short-description
```

## Open the PR

```bash
gh pr create --title "feat(scope): short description" --body-file pr-body.md
```

PR body template:

```markdown
## What
One-sentence summary of the change.

## Why
Context — what problem does this solve? Reference the issue: Closes #N.

## How to test
Concrete steps a reviewer can follow to verify the change works.
Commands, expected outputs, or how to exercise new behaviour.

## Changes
- Bullet list of the meaningful changes. Not every file — the stuff that matters.

---
Written by an agent on behalf of <user>.
```

## After opening

- PR descriptions written by an agent must include `Written by an agent on behalf of <user>.`, replacing `<user>` with the human who requested the work.
- Make sure the PR body includes `Closes #N` for the linked issue.
- If CI exists, inspect checks with `gh pr checks <number>`.
- If GitHub Actions workflows exist and you need more detail, use `gh run list --branch <branch>` and `gh run view <run-id> --log`.
- If there is no CI yet, say so plainly and rely on local verification results in the PR body.
- Respond to review comments by pushing new commits — don't force-push reviewed code unless asked.

## Merging

- Only merge after review approval and passing CI when CI exists.
- The `Closes #N` in the PR body auto-closes the issue on merge.
