# goldilocks-core

Upstream Python package for DFT input recommendation.

## Commands

```bash
uv sync --group dev
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
uv run pre-commit run --all-files
```

Run `pre-commit` before committing. CI (on `main` and PRs) runs Ruff, pytest with branch coverage, focused mutation testing, and distribution validation — all via `uv`.

## Code style

- Ruff `E`, `F`, `I`. Target Python 3.12.
- Domain modules, not generic buckets — no `helpers/`, `utils/`, or `processing/`.
- One clear API; no compatibility shims, legacy aliases, or duplicate import paths unless the user asks for backward compatibility.
- `snake_case` everywhere; no `CamelCase` except string literals matching external formats.
- Docstrings: factual — what it does, returns, assumes. Not essays.

## Validation

- Validate operator input, external metadata, rendered syntax, and filesystem writes.
- Trust records produced by internal stages; do not test deliberately corrupted internals.
- Let errors propagate; no catch-all fallbacks or failure-state machinery.

## Tests

- Prioritize scientific behavior, public APIs, and end-to-end workflows; keep unit, integration, and physics tests distinct.
- Use focused mutation testing to detect weak assertions.
- Do not add production complexity solely to satisfy coverage or mutation metrics.

## What doesn't belong here

- Jupyter notebooks — `notebooks/` (gitignored); convert insights into tests.
- Large ML model files or pseudo libraries — `local_data/` (gitignored).

This is a monorepo: Core (`src/goldilocks_core/`, this package) and the
Workbench (`web/`, a React app) are independently installable modules. Core
must never depend on Workbench.

## Coordination layer

Issues, PR descriptions, milestones, epics, labels, and the roadmap are the project's shared map. They must be accurate and minimal — slop here rots everyone's ability to coordinate. Code is clay: PR size and churn are not coordination concerns and never become slop rules. The rules below govern the map, not the code.

## Rules

- **Run `catchup` at the start of every session.**
- Never push or merge directly to `main` — all changes arrive through PRs.
- Every PR must close an issue (`Closes #N`).
- **PR descriptions are written by a human, always.** An agent never writes a PR body — not the final text, not a draft. The agent's PR workflow ends at pushing the branch and handing the human the diff, the commit log, and the issue number to close. The human opens the PR and writes the body. An agent may post a body file the human authored, but never one it wrote.
- Never edit or delete GitHub text authored by someone else (issue bodies, PR descriptions, comments, reviews). Add new information as a comment. An agent may edit its own GitHub text only when explicitly asked or when maintaining a plan it created.
- Any GitHub issue, issue comment, or review comment written by an agent must include `Written by an agent on behalf of <user>.` PR descriptions are never agent-written.
- Use `uv`, not `pip`.

## Issue hygiene

An issue is a shippable unit of work that someone turns into a PR — not a note, a placeholder, or a roadmap mirror. File an issue only when the work is concrete enough to start. Issues may be agent-written (this is normal); an agent writing one on behalf of a user applies these rules as a gate — it does not relay a request that fails the bar.

**Before filing, the issue must clear:**

- **Problem + proposed approach, not a placeholder.** State the concrete problem and a proposed approach. "Scope and design still to be worked out" means it is not ready — do the design first; an unplanned deliverable is not an issue.
- **No roadmap mirroring.** Don't file one issue per roadmap bullet to "make the milestone reflect its real scope." A milestone tracks work being done, not populated for its own sake; an unplanned deliverable stays on the roadmap, not as an open issue.
- **Scope gate.** Check "What doesn't belong here" first. Auth/sessions, pod management, AiiDA workflows, and pure infra/ops are not core features. The Workbench lives in `web/` as an independent module; Core cannot depend on it. An out-of-scope-layer item needs maintainer sign-off before it gets a core issue.
- **Reuse before creating.** Search open *and recently closed* issues first; extend rather than duplicate. If a closed issue's design is stale, fold the fresh design into the new issue and point at the closed one — don't silently re-derive.
- **Check live state.** Read open issues, recent merged PRs, and any open decision the issue depends on. An issue filed on a premise a same-day decision overturned is stale on arrival; cite the controlling decision.

**Structure:**

- **One issue per PR/feature.** An issue is a shippable unit; decisions, discussions, and sub-steps go inside the feature issue, not as standalone issues.
- **Decisions are not issues.** A `decide(...)` or policy question folds into the feature it gates as a phase. File the feature; record the decision inside it.
- **Phases, not sub-issues.** Multi-phase work is one issue with a phase checklist; don't pre-file sub-issues for work that hasn't started.
- **One structural change, one issue.** Milestone realignment, epic creation, repo chores: one issue with a checklist, not a pair and not a fleet of epics. Don't pre-create epic-index issues for work-streams with no live children — label grouping is enough until an epic issue earns its keep.
- **Every issue has a milestone.** If none fits, propose one before filing.

**Process:**

- **Coordinate before burst-filing or structural change.** Filing more than three issues in a session, or any issue that creates new structure (milestone, epic, label) or re-aligns the board, needs prior maintainer agreement — not a fait accompli.
- **Triage periodically.** Use `catchup` to surface candidates and `triage` to run the pass.
