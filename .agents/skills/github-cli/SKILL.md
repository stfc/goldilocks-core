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
- Any GitHub issue, issue comment, or review comment written by an agent must include:

```text
Written by an agent on behalf of <user>.
```

Replace `<user>` with the human who requested the work. **PR descriptions are never agent-written — not even a draft** (AGENTS.md); the human opens the PR and writes the body.

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

## Open a PR

PR descriptions are written by a human — an agent never writes a PR body, not even a draft (AGENTS.md). The agent does not open the PR. After pushing the branch, hand the human the branch name, commit log (`git log main..HEAD --oneline`), diff stat, and the issue number to close (`Closes #N`). The human opens the PR and writes the body.

If the human hands you a body file **they wrote**, you may post it:

```bash
gh pr create --repo stfc/goldilocks-core --title "type(scope): short title" --body-file <human-authored-file>
```

Never author, fill, or draft the body. Verify branch and base before creating.

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

## Milestones

Milestones group issues into deliverables. Every open issue should belong to one (AGENTS.md "Issue hygiene").

```bash
# List milestones with counts
gh api repos/stfc/goldilocks-core/milestones --jq '.[] | "\(.number) | \(.title) | open=\(.open_issues) closed=\(.closed_issues)"'

# Create one (returns the new milestone id)
gh api repos/stfc/goldilocks-core/milestones --method POST \
  -f title='M1 — ...' -f description='...' -f state='open' --jq '.number'

# Assign an issue to a milestone (the API takes the numeric milestone id)
gh api repos/stfc/goldilocks-core/issues/<N> --method PATCH -F milestone=<id>
```

`gh issue edit --milestone` expects the milestone *title*; the REST API takes the numeric *id*. Prefer the API for scripting.

## Triage

Periodic board hygiene. The `triage` skill runs the full pass; these are the building blocks.

```bash
# Open issues with no milestone
gh issue list --repo stfc/goldilocks-core --state open --limit 200 \
  --json number,milestone --jq '.[] | select(.milestone == null) | .number'

# Recently updated (to tell stale from active)
gh issue list --repo stfc/goldilocks-core --state all --limit 10 --search "sort:updated-desc"
```

Close-with-comment pattern (comment first, then close — avoids shell-quoting long bodies):

```bash
gh issue comment <N> --repo stfc/goldilocks-core --body-file /tmp/close.md
gh issue close   <N> --repo stfc/goldilocks-core
```

Triage rules (AGENTS.md issue hygiene): one issue per PR/feature; fold decisions into feature issues; phases are a body checklist; close superseded/duplicate/stale/out-of-scope; never edit others' text — comment instead. Propose closes/folds to the user before executing on someone else's issues.

## Gotchas

- `gh pr create` uses the current branch by default — verify branch and base before creating, and only post a body the human authored.
- `gh issue edit --body-file` replaces the whole body. Fetch first so you do not erase context.
- Before editing an issue body, ask: "Am I changing the current plan/source-of-truth, or just adding history?" If it is history, comment instead.
- `gh api ... -f body="$(cat file)"` can mangle complex Markdown in some shells. If in doubt, use a small Python snippet to PATCH JSON.
- GitHub CLI output may omit fields unless requested with `--json`; don't parse human tables when JSON exists.
- Sub-issue API requires the integer database ID (`.id`), not the issue number (`.number`). Use `gh api ... --jq '.id'` to get the DB ID.
