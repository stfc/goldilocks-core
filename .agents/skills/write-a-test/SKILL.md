---
name: write-a-test
description: Write tests for goldilocks-core. Use when adding or extending test coverage, after fixing a bug, or when capturing discovered behaviour.
---

# Write a Test

## Runner

Use `pytest` directly. No `tox`, no `nox`.

```bash
uv run pytest                          # all tests
uv run pytest tests/test_kmesh.py      # one file
uv run pytest -k "test_entry"          # by name
```

## Coverage

Use coverage reports when adding baseline tests, refactoring public behaviour, or checking whether a new test actually exercises the intended path.

```bash
uv run --with pytest-cov pytest --cov=goldilocks_core --cov-report=term-missing
uv run --with pytest-cov pytest --cov=goldilocks_core --cov-report=xml
uv run --with pytest-cov pytest --cov=goldilocks_core --cov-report=html
```

- `uv run --with pytest-cov` keeps coverage tooling available without adding a permanent dependency unless the project decides it wants one.
- `term-missing` is useful during development because it shows uncovered lines in the terminal.
- `xml` is useful for CI services such as Codecov or Coveralls if/when they are configured.
- `html` is useful for local inspection in a browser.

New tests should not reduce overall coverage. Do not chase coverage numbers by testing implementation trivia; prioritize public behaviour, scientific edge cases, and regressions.

## Portability

Tests must not depend on `local_data/` or any private dataset. The test suite must pass from a clean checkout with only `uv sync --group dev`.

- Use `pytest`'s `tmp_path` fixture for any file output.
- Build synthetic fixtures inline or via helpers: pymatgen `Structure` objects, constructed dataclass instances, small UPF snippets as strings.
- If you need a structure, use `pymatgen.core.Structure.from_spacegroup()` or construct a simple cubic cell — don't reach for a CIF file.

## When to write one

- **After fixing a bug** — write the test that would have caught it.
- **After adding a public function or type** — at minimum a construction/smoke test.
- **Before moving on from exploration** — if you ran something interactively and it revealed important behaviour, capture it as a regression test before you forget the details.

## Naming and location

- Test files: `tests/test_<module>.py`.
- Test functions: `test_<behaviour_description>` — describe what's being verified, not what the function is called.
- Bad: `test_kmesh_entry` — what about it?
- Good: `test_kmesh_entry_index_starts_at_one`

## What to test

- Public API surface. Internal functions only if they have non-obvious invariants.
- Edge cases that the happy path won't catch: empty inputs, single-element structures, boundary values.
- Error paths — verify the right exception type and message, not just that it raises.
