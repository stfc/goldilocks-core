# goldilocks-core

Upstream Python package for DFT input recommendation.

## Commands

```bash
uv sync --group dev                     # install with dev deps
uv run pytest                            # run tests
uv run ruff check src tests              # lint
uv run ruff format src tests             # format
uv run pre-commit run --all-files        # lint + test in one shot
```

CI runs on push to `main` and on PRs (`.github/workflows/ci.yml`): ruff check, ruff format check, pytest, all via `uv`. Third-party Actions are SHA-pinned; Dependabot bumps them weekly. Still run `pre-commit` before committing locally.

## Code style

- Ruff with `E`, `F`, `I` rules. Target Python 3.12.
- Dataclasses use `slots=True`. Frozen for immutable value objects.
- `from __future__ import annotations` at the top of every module.
- Domain modules, not generic buckets: no `helpers/`, no `utils/`, no `processing/`.
- Prefer one clear API over compatibility shims. Do not add legacy aliases, duplicate import paths, or wrapper modules unless the user explicitly asks for backward compatibility.
- `snake_case` for everything. No `CamelCase` except in string literals matching external formats.
- Type hints on public API surfaces. Internal functions can be looser.
- Docstrings: factual — what it does, what it returns, what it assumes. Not prose essays.

## What doesn't belong here

- User auth, sessions, frontend code, WebSocket handlers, pod management — that's the application layer.
- AiiDA workflows, CalcJobs, execution/scheduler scripts — that's Runner.
- Jupyter notebooks — go in `notebooks/` (gitignored). Convert insights into tests.
- Large ML model files or pseudo libraries — `local_data/` is gitignored.

## Rules

- **Never push or merge directly to `main`.** All changes arrive through PRs.
- Every PR must close an issue (`Closes #N`).
- Track work status in GitHub Issues/PRs.
- **Never edit or delete GitHub text authored by someone else**, including issue bodies, PR descriptions, comments, and reviews. Add new information as a comment instead. An agent may edit its own GitHub text only when explicitly asked or when maintaining a plan it created.
- Any GitHub issue, issue comment, PR description, or review comment written by an agent must explicitly say so and name the human it represents: `Written by an agent on behalf of <user>.`
- Use `uv`, not `pip`.

## Agent workflow

- Start sustained work with `catchup`.
- Use `plan` for multi-step changes. Keep an issue body current only when the agent created it; otherwise add plan updates as comments.
- Use `review` before PRs or after substantial changes.
- Use `report` for handoff/progress comments.
- Use `make-a-pr` only after implementation, tests, and review are ready.
