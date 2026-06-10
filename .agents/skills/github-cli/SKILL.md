---
name: github-cli
description: Use the gh CLI for GitHub issues, PRs, comments, checks, and Actions state in this repo. Use whenever reading or writing GitHub state from an agent session.
---

# GitHub CLI

Use `gh` for GitHub work. Prefer structured commands over scraping web pages.

Repo: `stfc/goldilocks-core`

## Rules

- Use `--repo stfc/goldilocks-core` unless you are already inside this repo and deliberately relying on the current remote.
- Prefer `--json` and `--jq` for read operations so outputs are machine-checkable.
- Use `--body-file` for long issue, comment, and PR bodies. Do not fight shell quoting goblins by pasting Markdown into one command.
- Prefer issue comments for progress updates, reviews, decisions, blockers, and session reports. Edit issue bodies only when the issue's current plan/source-of-truth is stale or structurally wrong.
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
gh run list --repo stfc/goldilocks-core --branch <branch>
gh run view <run-id> --repo stfc/goldilocks-core --log
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

Use comments for timeline records: progress reports, reviews, verification results, decisions made during implementation, blockers, and handoff notes. A comment is usually the right move when you are adding new historical context rather than changing the plan itself.

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

Issue body edits are for maintaining the current source of truth, not for recording every event. Use them when:

- the issue is a plan and the plan materially changed;
- acceptance criteria, scope, goals, or non-goals are stale;
- tasks are completed and the checklist is the active tracker;
- the body is misleading future work;
- the user explicitly asks to consolidate or edit the issue.

Do **not** edit the issue body just to add a review, routine verification output, progress report, or session handoff. Post those as comments.

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

## Checks and Actions

Use `gh pr checks` for the quick answer and `gh run` when you need workflow detail.

```bash
gh pr checks <number> --repo stfc/goldilocks-core
gh run list --repo stfc/goldilocks-core --branch <branch>
gh run view <run-id> --repo stfc/goldilocks-core --log
gh run download <run-id> --repo stfc/goldilocks-core
```

If the repo has no workflows yet, say so plainly and rely on local verification instead of pretending CI exists.

## Sub-issues

This repo uses GitHub sub-issues to link parent planning issues to their implementation children.

### Link a sub-issue to a parent

The sub-issues API requires integer database IDs (not issue numbers). Get the DB ID first, then link:

```bash
PARENT_ID=$(gh api repos/stfc/goldilocks-core/issues/8 --jq '.id')
CHILD_ID=$(gh api repos/stfc/goldilocks-core/issues/20 --jq '.id')
gh api repos/stfc/goldilocks-core/issues/8/sub_issues --method POST -F sub_issue_id=$CHILD_ID
```

### View sub-issues

```bash
gh api repos/stfc/goldilocks-core/issues/8/sub_issues --jq '.[].number'
```

### Unlink a sub-issue

```bash
gh api repos/stfc/goldilocks-core/issues/8/sub_issues/$CHILD_ID --method DELETE
```

### Conventions

- Umbrella issues (like #8) are the parent. Implementation issues (like #20, #21) are sub-issues.
- Sub-issues show up nested under the parent with their status.
- Closing all sub-issues does not auto-close the parent.
- Use sub-issues instead of task-list checkboxes (`- [ ] #20`) for formal tracking. Task lists are fine for informal checklists within a single issue.

## Gotchas

- `gh pr create` uses the current branch by default — verify branch and base before creating.
- `gh issue edit --body-file` replaces the whole body. Fetch first so you do not erase context.
- Before editing an issue body, ask: "Am I changing the current plan/source-of-truth, or just adding history?" If it is history, comment instead.
- `gh api ... -f body="$(cat file)"` can mangle complex Markdown in some shells. If in doubt, use a small Python snippet to PATCH JSON.
- GitHub CLI output may omit fields unless requested with `--json`; don't parse human tables when JSON exists.
- Sub-issue API requires the integer database ID (`.id`), not the issue number (`.number`). Use `gh api ... --jq '.id'` to get the DB ID.
