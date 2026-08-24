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

   - `Service` implements Capabilities, Structure Inspection, and Compute.
   - `compute(ComputeRequest)` is the short-lived Python convenience.
   - `recommend` and `generate` are Preset IDs, not operations.
   - The unified `goldilocks` CLI implements `capabilities`, `inspect`,
     `compute`, `serve`, `examples`, and explicit `assets` lifecycle commands.
   - Optional `[http]` and `[mcp]` transports expose the same three scientific
     operations over one process-owned Service.
   - One publisher creates complete Ready-to-run Output directories and ZIPs.
   - Workbench is a stateless browser client of ordinary Core HTTP.
   - DFT execution, AiiDA, authentication, sessions, and saved Workspaces are
     out of scope.

3. Keep stage language consistent.

   ```text
   Load -> Analyze -> Advise
   Load -> Kmesh
   Load + Advice -> Select
   Load + Advice + Select + Kmesh -> Generate
   Analysis + Advice + Kmesh + Select + Generate -> DFT Input Data
   ```

4. Keep package ownership consistent.

   ```text
   contracts/            -> domain values, boundary contracts, stable Record IDs
   runtime/graph.py      -> type-keyed DAG execution
   runtime/dispatch.py   -> Calculation Task registry and Compute dispatch
   runtime/models.py     -> model lifecycle
   runtime/service.py    -> reusable operations, locking, and publication
   runtime/jobs.py       -> short-lived Compute convenience
   io/structures.py      -> Structure Source normalization and Inspection
   runtime/capabilities.py -> coherent catalog snapshot
   input_data.py         -> complete DFT Input Data assembly
   publication.py        -> one directory/ZIP output layout
   server/request.py     -> shared transport deserializer
   server/http*.py       -> optional HTTP adapter
   server/mcp.py         -> optional local stdio MCP adapter
   web/                  -> browser Workspace and generated HTTP types
   analysis.py           -> structure facts
   advice/               -> provenance-backed recommendations
   kmesh/                -> k-point resolution
   selection.py          -> concrete pseudopotential choices
   generation/           -> target-code rendering
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

- Start each document and section with the reader's task or question.
- Give the next action before caveats or implementation details.
- Context check every sentence and section. If a phrase refers to an earlier
  design, an unnamed asset, or a failure the reader has not met, introduce the
  subject first or remove the phrase.
- Example: write `Period-5 elements can need SOC consideration`, not `This
  replaced the earlier Z >= 57 rule`.
- Example: name each asset that the user must install. Do not write `the other
  two assets` unless the preceding text names them.
- Keep user guides about user tasks. Put implementation guarantees and module
  design in `docs/architecture.md`.
- Be terse. Use short sections and examples.
- Use one-line shell commands. Do not use `\` line continuations.
- Avoid roadmap promises in user-facing docs.
- If something is future work, say `not implemented yet`.
- Do not use flowery language.

## Common mistakes

- Documenting planned CLI commands as current commands.
- Reintroducing old `goldilocks_core.shared` imports.
- Mixing structure loading and structure analysis ownership.
- Adding compatibility aliases or migration paths without explicit request.
- Embedding unvalidated Mermaid diagrams.
