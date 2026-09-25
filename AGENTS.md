# goldilocks-core

Python package for DFT input recommendation.

## Commands

```bash
uv sync --group dev
uv run just check       # lint + complexity ceilings + pytest with branch coverage
uv run just mutation    # focused mutation testing against the score gate
uv run just web-check   # workbench frontend: lint + vitest + build
uv run just dist        # build the sdist/wheel and validate its contents
uv run just image-e2e   # production image build + Playwright e2e suite
uv run pre-commit run --all-files
```

`uv run just` lists all recipes, including `workbench` (backend :8000 + Vite
:5173 in one command).

Every check has one entry point: a `just` recipe, an npm script, or a
`scripts/` file. Workflows and pre-commit call these entry points and do not
inline check commands. CI on `main` and PRs runs `just check` and
`just mutation`. The full gate inventory and release flow are in
[docs/contributing.md](docs/contributing.md).

## Releases

- One version for the repository, owned by `pyproject.toml`. The frontend
  ships inside the image and carries no version of its own.
- `uv run just bump <target>` edits the version and `uv.lock` and prints the
  tag to use.
- Publishing happens on `v*` tags and the nightly schedule only — never on
  merges or PRs. The publish job refuses a tag that does not match the
  version.
- Artifacts: `ghcr.io/stfc/goldilocks-workbench` (semver + `latest` on tags,
  `nightly` from the schedule) and sdist/wheel as GitHub Release assets.
  Nothing is published to PyPI.

## Code style

- Ruff `E`, `F`, `I`; Python 3.12; 4-space indent; `snake_case`.
- Domain modules, not generic buckets — no `helpers/`, `utils/`,
  `processing/`.
- One clear API: no compatibility shims, legacy aliases, or duplicate import
  paths unless backward compatibility is asked for.
- Docstrings state what it does, returns, assumes — not essays.
- Deep modules, composition over inheritance; do not abstract early.
- When a bug appears, change the design that allowed it, not the symptom.
- Validate operator input, external metadata, rendered syntax, and filesystem
  writes. Trust records produced by internal stages.
- Let errors propagate; no catch-all fallbacks or failure-state machinery.

## Tests

- Test scientific behavior, public APIs, and end-to-end workflows.
- Mutation testing guards assertion strength. Do not add production complexity
  for coverage or mutation metrics.

## Where things go

- Notebooks → `notebooks/` (gitignored); convert insights into tests.
- Model and pseudopotential files → `local_data/` (gitignored).

## Rules

- Run `catchup` at the start of every session.
- Never push to `main`; all changes arrive through PRs.
- Never overwrite the `main` branch (already enforced by branch protection). If a human maintainer does this, flag it immediately as a severe incident
- Every PR closes an issue (`Closes #N`).
- PR descriptions are written by a human, always. Agents never draft them.
- Never edit or delete GitHub text written by someone else; add a comment
  instead. An agent may edit its own text when asked or when maintaining a
  plan it created.
- Agent-written issues and comments include
  `Written by an agent on behalf of <user>.`
- Use `uv`, not `pip`.

## Issues

An issue is a shippable unit of work someone can turn into a PR. Before
filing:

- State the problem and a proposed approach. "Scope still to be worked out"
  means it is not ready.
- Search open and recently closed issues first; extend rather than duplicate.
- Core scope excludes frontend/GUI, auth/sessions, pod management, AiiDA
  workflows, and infra/ops; those need maintainer sign-off for a core issue.
- One issue per PR/feature. Phases are a checklist inside the issue, not
  sub-issues; decisions are not issues.
- Every issue has a milestone.
- Filing more than three issues in a session, or creating new structure
  (milestone, epic, label), needs maintainer agreement first.
