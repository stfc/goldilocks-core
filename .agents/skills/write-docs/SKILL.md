---
name: write-docs
description: Write or update goldilocks-core documentation. Use when changing README, docs/architecture.md, API examples, CLI docs, package layout docs, or Mermaid diagrams.
---

# Write Docs

Use this skill for project documentation changes.

## Goals

- Keep docs current with the branch.
- Prefer terse, direct wording.
- Document actual behavior only. Do not describe planned CLI or API as implemented.
- Keep one canonical API path. Do not add compatibility notes unless backward compatibility was explicitly requested.

## Files

Primary docs:

- `README.md` — user-facing summary, install, quick start, Python API, current CLI, development commands.
- `docs/architecture.md` — module ownership, pipeline boundaries, data contracts, extension points.
- `AGENTS.md` — durable project rules for future agents.

- `docs/pseudopotentials.md` — table installation, storage, provider normalization, licensing, and citation.

## Workflow

1. Check current code before writing.

   ```bash
   find src/goldilocks_core -maxdepth 2 -type f | sort
   rg "project.scripts|goldilocks-" pyproject.toml
   rg "def |class " src/goldilocks_core tests
   ```

2. State what is implemented and what is not.

   Required distinctions:

   - `CoreService` implements reusable recommend/generate/compute operations
     plus task/code/model discovery.
   - `run_core_job(PresetRequest)` and `query_records(QueryRequest)` are
     short-lived Python conveniences.
   - The unified `goldilocks` CLI implements `recommend`, `generate`, `compute`,
     `serve`, `examples`, and explicit `assets` lifecycle commands.
   - Optional `[http]` and `[mcp]` transports are implemented over one service.
   - Generate can publish a bundle directory; there is no bundle operation.
   - Runner, AiiDA, frontend, auth, and workspace concerns are out of scope.

3. Keep stage language consistent.

   ```text
   Load -> Analyze -> Advise -> Select
   Load -> Kmesh
   Load + Advice + Select + Kmesh -> Generate
   ```

4. Keep package ownership consistent.

   ```text
   contracts/          -> boundary dataclasses and stable record IDs
   runtime/graph.py    -> type-keyed DAG execution
   runtime/dispatch.py -> task registry and preset/query dispatch
   runtime/core.py     -> model lifecycle
   runtime/service.py  -> reusable operations, locking, and discovery
   runtime/jobs.py     -> short-lived convenience entry points
   server/request.py   -> canonical transport deserializer
   server/http.py      -> optional HTTP adapter
   server/mcp.py       -> optional MCP adapter
   analysis.py         -> structure facts
   advice/             -> provenance-backed recommendations
   kmesh/              -> k-point resolution
   selection.py        -> concrete pseudopotential choices
   generation/         -> target-code rendering
   ```

5. Validate Mermaid diagrams before embedding.

   Write each diagram to a temporary `.mmd` file, then run:

   ```bash
   /home/sigil/.pi/agent/skills/mermaid/tools/validate.sh /tmp/diagram.mmd
   ```

   Use `flowchart` for new diagrams. Use `<br/>` for line breaks inside labels.

6. Run checks before committing.

   ```bash
   uv run ruff check src tests
   uv run ruff format --check src tests
   uv run pytest -q
   ```

## Style
- Context check: a follow-up phrase must not introduce a subject that the reader has not encountered. Introduce the subject first, or remove the phrase if it has no purpose.

- Be terse.
- Use short sections.
- Use examples over prose.
- Avoid roadmap promises in user-facing docs.
- If something is future work, say `not implemented yet`.
- Do not use flowery language.

## Common mistakes

- Documenting planned CLI commands as current commands.
- Reintroducing old `goldilocks_core.shared` imports.
- Mixing structure loading and structure analysis ownership.
- Adding compatibility aliases or migration paths without explicit request.
- Embedding unvalidated Mermaid diagrams.
