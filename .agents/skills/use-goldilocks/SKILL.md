---
name: use-goldilocks
description: Use goldilocks-core quickly for DFT input recommendation workflows. Trigger when running or scripting recommendations, extracting parameters from structures, generating or publishing Quantum ESPRESSO SCF inputs, or manually writing inputs from Goldilocks-selected Records.
---

# Use Goldilocks

Use the canonical Capabilities, Structure Inspection, and Compute operations.
Core currently supports Quantum ESPRESSO single-point SCF input preparation.

Fresh installations must install the runtime assets first: run
`goldilocks assets install default` once, or pass `--fetch-missing`, before any
command that needs the default k-point model or pseudopotential tables.

## Progressive disclosure

- `references/workflows.md` — Python, CLI, HTTP, and MCP workflows.
- `references/qe-scf-template.md` — mechanical QE SCF template for manually
  writing an input from trusted Records.

Pair with `use-uv` for execution and `dft-basics` for physics-bearing choices.

## Mental model

```text
Load -> Analyze -> Advise
Load -> Kmesh
Load + Advice -> Select
Load + Advice + Select + Kmesh -> Generate
Analysis + Advice + Kmesh + Select + Generate -> DFT Input Data
```

Use one `ComputeRequest` with either `PresetSelection` or `RecordSelection`.
`recommend` and `generate` are Preset IDs. Keep one `Service` open for repeated
work; use top-level `compute()` for one call.

## Inputs to identify

1. Structure Source: path, inline content, or `pymatgen.Structure`.
2. Calculation Intent: target code, Calculation Task, functional, and
   pseudopotential accuracy.
3. Calculation Hints: k-grid or spacing, smearing, spin/SOC, pseudopotential
   type, convergence, and dispersion.
4. Pseudopotential source: registered Set ID, local root, or explicit metadata.
5. Computation Selection and output target.

## Canonical entry points

```python
from goldilocks_core import (
    CalculationDraft,
    ComputeRequest,
    PathStructureSource,
    PresetSelection,
    Service,
)

request = ComputeRequest(
    CalculationDraft(PathStructureSource("structure.cif")),
    PresetSelection("recommend"),
)
with Service() as core:
    result = core.compute(request)
```

```bash
uv run goldilocks capabilities --json
uv run goldilocks inspect STRUCTURE --json
uv run goldilocks compute STRUCTURE --preset recommend --no-out --json
uv run goldilocks compute STRUCTURE --preset generate --out RUN_DIR --json
```

HTTP exposes `/capabilities`, `/inspect`, and `/compute`; local stdio MCP exposes
`capabilities`, `inspect_structure`, and `compute`. Send inline structure content
and, when needed, a registered Pseudopotential Set ID. HTTP and MCP do not
accept structure paths, local pseudopotential sources, model locations, or
publication paths.

## Completion check

For prepared input data, report the Structure Source, functional, target
code/Task, k-grid and shift, pseudopotentials and cutoffs, smearing, spin/SOC,
convergence controls, factual warnings, generated paths, and publication path.
Core prepares inputs; it does not run DFT.
