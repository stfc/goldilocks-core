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

CI runs on push to `main` and on PRs: Ruff, pytest with branch coverage, focused mutation testing, and distribution validation — all via `uv`. Run `pre-commit` before committing.

## Code style

- Ruff `E`, `F`, `I`. Target Python 3.12.
- `from __future__ import annotations` at the top of every module.
- Dataclasses: `slots=True`; frozen for immutable value objects.
- Domain modules, not generic buckets — no `helpers/`, `utils/`, or `processing/`.
- One clear API; no compatibility shims, legacy aliases, or duplicate import paths unless the user asks for backward compatibility.
- `snake_case` everywhere; no `CamelCase` except string literals matching external formats.
- Type hints on public API; internals may be looser.
- Docstrings: factual — what it does, returns, assumes. Not essays.

## Architecture

- Staged workflow, but no workflow framework.
- `Pipeline` is a convenience composition; every stage remains directly callable.
- Calculation task names are extensible; built-in generators validate what they support.
- Generate may return multiple linked input files for one calculation intent.

## Validation

- Validate operator input, external metadata, rendered syntax, and filesystem writes.
- Trust records produced by internal stages; do not test deliberately corrupted internals.
- Let errors propagate; no catch-all fallbacks or failure-state machinery.
- Alternative scientific behavior (e.g. heuristic k-points) must be selected explicitly.

## Tests

- Prioritize scientific behavior, public APIs, and end-to-end workflows; keep unit, integration, and physics tests distinct.
- Use focused mutation testing to detect weak assertions.
- Do not add production complexity solely to satisfy coverage or mutation metrics.

## What doesn't belong here

- User auth, sessions, frontend, WebSocket, pod management — application layer.
- AiiDA workflows, CalcJobs, execution/scheduler scripts — Runner.
- Jupyter notebooks — `notebooks/` (gitignored); convert insights into tests.
- Large ML model files or pseudo libraries — `local_data/` (gitignored).

## Rules

- **Run `catchup` at the start of every session.**
- Never push or merge directly to `main` — all changes arrive through PRs.
- Every PR must close an issue (`Closes #N`).
- Never edit or delete GitHub text authored by someone else (issue bodies, PR descriptions, comments, reviews). Add new information as a comment. An agent may edit its own GitHub text only when explicitly asked or when maintaining a plan it created.
- Any GitHub issue, issue comment, PR description, or review comment written by an agent must include `Written by an agent on behalf of <user>.`
- Use `uv`, not `pip`.

## Issue hygiene

- **One issue per PR/feature.** An issue is a shippable unit of work; decisions, discussions, and sub-steps go inside the feature issue, not as standalone issues.
- **Phases, not sub-issues.** Multi-phase work is one issue with a phase checklist in the body; don't pre-file sub-issues for work that hasn't started.
- **Every issue has a milestone.** If none fits, propose one before filing.
- **Reuse before creating.** Search open issues before filing; extend rather than duplicate.
- **Triage periodically.** Use `catchup` to surface candidates and `triage` to run the pass.
