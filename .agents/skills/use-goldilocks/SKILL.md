---
name: use-goldilocks
description: Use goldilocks-core quickly for DFT input recommendation workflows. Trigger when running or scripting recommendations, extracting parameters from structures, generating or publishing Quantum ESPRESSO SCF inputs, or manually writing inputs from Goldilocks-selected records.
---

# Use Goldilocks

Operational quickstart for using `goldilocks-core` without rereading the
implementation. Core currently recommends and generates Quantum ESPRESSO SCF
single-point inputs.

## Progressive disclosure

Start here. Read supporting files only for the needed branch:

- `references/workflows.md` — Python and CLI operation patterns, record queries,
  model selection, and bundle publication.
- `references/qe-scf-template.md` — mechanical Quantum ESPRESSO SCF template for
  manually writing an input from selected values.

Pair with:

- `use-uv` for Python, CLI, tests, or dependency work.
- `dft-basics` for physics-bearing choices: k-points, smearing,
  pseudopotentials, SOC, or convergence.
- `write-a-test` when changing public behavior or capturing a regression.

## Mental model

The shipped task is a typed dependency graph:

```text
Load -> Analyze -> Advise -> Select
Load -> Kmesh
Load + Advice + Select + Kmesh -> Generate
```

Choose the operation from the needed output:

- Complete recommendation records: `CoreService.recommend(PresetRequest(...))`.
- Generated files in memory: `CoreService.generate(PresetRequest(...))`.
- Generated files on disk: `CoreService.generate(..., output_dir=...)`.
- Selected records only: `CoreService.compute(QueryRequest(...))`.
- Repeated calls or discovery: keep one `CoreService` open.
- One call: `run_core_job` or `query_records`.

Bundle publication is a side effect of Generate, not a separate mode.

## Inputs to identify

1. Structure path or `pymatgen.Structure`.
2. Target code, task, functional, and pseudo mode.
3. Operator hints: k-grid or k-spacing, smearing, spin/SOC, pseudo type,
   convergence.
4. Pseudopotential metadata source, usually a local directory of `.UPF` files.
5. Required output: full recommendation, selected records, generated text, or
   published directory.

## Canonical API surface

Use the root facade for application operations:

```python
from goldilocks_core import (
    CalculationHints,
    CalculationIntent,
    CoreService,
    PresetRequest,
    QueryRequest,
    query_records,
    run_core_job,
)
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
```

CLI operations map one-to-one to the service:

```bash
uv run goldilocks recommend STRUCTURE --json
uv run goldilocks generate STRUCTURE --pseudo-root PSEUDOS --out RUN_DIR --json
uv run goldilocks compute STRUCTURE --outputs analysis,k_points
uv run goldilocks serve http
uv run goldilocks serve mcp
```

HTTP and MCP require the `[http]` and `[mcp]` extras. Both transports keep one
`CoreService` alive and expose recommend, generate, compute, task discovery,
code discovery, and model discovery.

## Common pitfalls

- Use `uv run` and `uv sync`; persistent project environments are uv-owned.
- The only shipped target is `quantum_espresso` + `scf_single_point`.
- Generators are mechanical. Scientific choices must already exist in records.
- Explicit user hints win over model-backed choices.
- Pseudopotential matching is functional-sensitive: `PBE`, `PBEsol`, `LDA`.
- Generation requires selected pseudo filenames and both cutoffs for every
  element; recommendation may instead return fallback records and warnings.
- Structure-only electronic character is uncertain. Inspect smearing warnings.
- Core prepares input files; it does not run DFT, schedule jobs, or manage
  AiiDA, auth, sessions, pods, or frontend state.

## Completion check

For every produced input or parameter list, report:

- structure and reduced formula;
- functional and target code/task;
- k-grid and shift;
- pseudopotential filename by element;
- `ecutwfc` and `ecutrho`;
- smearing/degauss or fixed occupations;
- convergence values;
- warnings;
- generated paths and bundle path, when present.
