---
name: use-uv
description: Use uv for all Python package management in this project. Use when installing deps, running commands, adding packages, building, or any Python environment task. Never use pip, venv, or pipx.
---

# Use uv

This project uses `uv`. Never use `pip`, `venv`, `pipx`, or `virtualenv`.

## Common commands

```bash
uv sync --group dev           # install the project with dev deps
uv run pytest                  # run a command in the project environment
uv run ruff check src tests   # lint
uv run python -c "..."        # run one-off python in the project env
uv add <package>              # add a runtime dependency
uv add --group dev <package>  # add a dev dependency
uv build                      # build sdist + wheel
```

## Why uv

- Faster than pip. Locks are reliable. Virtualenv management is automatic.
- `uv run` executes in the project's virtualenv without activating it first.
- Dependencies are declared in `pyproject.toml`. The lock file is `uv.lock`.

## Gotchas

- `uv sync` replaces `pip install -e .` and `pip install -r requirements.txt`.
- `uv run` replaces `source .venv/bin/activate && ...`. Don't activate venvs manually.
- To add a dependency, edit `pyproject.toml` or use `uv add`. Don't `pip install` — it won't survive a sync.
- If `uv sync` fails, read the error. It's usually a version conflict in `pyproject.toml`.
