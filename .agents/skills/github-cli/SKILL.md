---
name: github-cli
description: Use the gh CLI for GitHub issues, PRs, comments, checks, and project metadata in this repo. Use whenever reading or writing GitHub state from an agent session.
---

# GitHub CLI

Use `gh` for GitHub work. Prefer structured commands over scraping web pages.

Repo: `stfc/goldilocks-core`

## Rules

- Use `--repo stfc/goldilocks-core` unless you are already inside this repo and deliberately relying on the current remote.
- Prefer `--json` and `--jq` for read operations so outputs are machine-checkable.
- Use `--body-file` for long issue, comment, and PR bodies. Do not fight shell quoting goblins by pasting Markdown into one command.
- **Never merge directly to `main`.** All changes arrive through PRs.
- Any GitHub issue, issue comment, PR description, or review comment written by an agent must include:

```text
Written by an agent on behalf of <user>.
```

Replace `<user>` with the human who requested the work.

## Inspect state

```bash
gh issue list --repo stfc/goldilocks-core --state open --limit 20
gh pr list --repo stfc/goldilocks-core --state open --limit 20
gh pr view <number> --repo stfc/goldilocks-core --json state,mergeStateStatus,isDraft,reviewDecision,baseRefName,headRefName
gh pr checks <number> --repo stfc/goldilocks-core
```

Use `gh api` for fields not exposed by high-level commands:

```bash
gh api repos/stfc/goldilocks-core/issues/<number> --jq '{title, state, body}'
gh api repos/stfc/goldilocks-core/pulls/<number> --jq '{title, state, mergeable, rebaseable}'
```

## Create an issue

Write the body to a temp file first:

```bash
cat > /tmp/issue-body.md <<'EOF'
## Problem
...

## Approach
...

## Acceptance criteria
- [ ] ...

---
Written by an agent on behalf of <user>.
EOF

gh issue create --repo stfc/goldilocks-core --title "type: short title" --body-file /tmp/issue-body.md
```

## Comment on an issue

```bash
cat > /tmp/comment.md <<'EOF'
## Done
- ...

## Next
- ...

---
Written by an agent on behalf of <user>.
EOF

gh issue comment <number> --repo stfc/goldilocks-core --body-file /tmp/comment.md
```

## Create a PR

Before creating:

```bash
git status -sb
git branch --show-current
gh pr list --repo stfc/goldilocks-core --head "$(git branch --show-current)"
```

Then:

```bash
cat > /tmp/pr-body.md <<'EOF'
## What
...

## Why
Closes #<issue-number>.

## How to test
...

## Changes
- ...

---
Written by an agent on behalf of <user>.
EOF

gh pr create --repo stfc/goldilocks-core --title "type(scope): short title" --body-file /tmp/pr-body.md
```

## Edit existing GitHub text

Fetch current content first, edit locally, then write it back:

```bash
gh issue view <number> --repo stfc/goldilocks-core --json body --jq .body > /tmp/body.md
# edit /tmp/body.md
gh issue edit <number> --repo stfc/goldilocks-core --body-file /tmp/body.md
```

For comments, use the API:

```bash
gh api repos/stfc/goldilocks-core/issues/<issue-number>/comments --jq '.[] | {id, body: .body[0:120]}'
gh api repos/stfc/goldilocks-core/issues/comments/<comment-id> -X PATCH -f body="$(cat /tmp/comment.md)"
```

## Project board

GitHub Projects v2 commands require project and item IDs. Prefer high-level inspection first:

```bash
gh project list --owner stfc
gh project view <number> --owner stfc --format json
```

If project updates are too cumbersome through `gh project`, report the intended transition in an issue comment instead of pretending the board is updated.

## Gotchas

- `gh pr create` uses the current branch by default — verify branch and base before creating.
- `gh issue edit --body-file` replaces the whole body. Fetch first so you do not erase context.
- `gh api ... -f body="$(cat file)"` can mangle complex Markdown in some shells. If in doubt, use a small Python snippet to PATCH JSON.
- GitHub CLI output may omit fields unless requested with `--json`; don't parse human tables when JSON exists.