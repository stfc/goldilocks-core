---
name: make-a-pr
description: Commit changes and hand off to the human to open a pull request. Use when you have changes ready to submit — after implementing, testing, and self-reviewing.
---

# Make a PR

The agent prepares the branch and commits. **The human opens the PR and writes the PR body** — an agent never writes a PR body, not even a draft (AGENTS.md). The agent's job ends at pushing the branch and handing the human the diff, the commit log, and the issue number to close.

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

## Hand off to the human

The agent's work ends here. Do **not** write a PR body, do **not** draft one for the human, do **not** run `gh pr create`. Give the human, as plain facts (not a PR-body template):

- the branch name
- the commit log: `git log main..HEAD --oneline`
- the diff stat: `git diff main...HEAD --stat`
- the issue number to close: `Closes #N`

The human opens the PR and writes the body. If the human hands you a body file **they wrote**, you may post it with `gh pr create --title "..." --body-file <their-file>` — but you never author, fill, or draft a PR body.

## After the human opens the PR

- Get the PR number: `gh pr list --repo stfc/goldilocks-core --head "$(git branch --show-current)" --json number --jq '.[0].number'`.
- Confirm the PR body includes `Closes #N` — flag it to the human if missing (it is their responsibility, not yours to write).
- The linked issue must have a milestone; assign one before merge if it doesn't (`gh api repos/stfc/goldilocks-core/issues/<N> --method PATCH -F milestone=<id>`).
- Inspect CI: `gh pr checks <number>`. For detail, `gh run list --branch <branch>` and `gh run view <run-id> --log`. If there is no CI, say so plainly.
- Respond to review comments by pushing new commits — don't force-push reviewed code unless asked.

## Merging

- Only merge after review approval and passing CI when CI exists.
- The `Closes #N` in the PR body auto-closes the issue on merge.