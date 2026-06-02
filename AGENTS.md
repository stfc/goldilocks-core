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

No CI yet. Run `pre-commit` before committing.

## Code style

- Ruff with `E`, `F`, `I` rules. Target Python 3.12.
- Dataclasses use `slots=True`. Frozen for immutable value objects.
- `from __future__ import annotations` at the top of every module.
- Domain modules, not generic buckets: no `helpers/`, no `utils/`, no `processing/`.
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
- Any GitHub issue, issue comment, PR description, or review comment written by an agent must explicitly say so and name the human it represents: `Written by an agent on behalf of <user>.`
- Use `uv`, not `pip`.