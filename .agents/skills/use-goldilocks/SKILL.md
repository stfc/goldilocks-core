---
name: use-goldilocks
description: Use goldilocks-core quickly for DFT input recommendation workflows. Trigger when running or scripting recommendations, extracting parameters from structures, generating or bundling Quantum ESPRESSO SCF inputs, or manually writing inputs from Goldilocks-selected numbers.
---

# Use Goldilocks

Operational quickstart for using `goldilocks-core` without rereading the implementation.

Goldilocks Core recommends and prepares DFT inputs from a structure, intent, hints, and pseudopotential metadata. It currently generates Quantum ESPRESSO SCF single-point inputs.

## Progressive disclosure

Start here. Only read supporting files when the task needs the detail.

- `references/workflows.md` — CLI and Python patterns for recommend/generate/bundle/manual QE input writing.
- `references/qe-scf-template.md` — mechanical Quantum ESPRESSO SCF template for manually writing an input from selected values.

Pair this skill with:

- `use-uv` when running Python, CLI, tests, or scripts.
- `dft-basics` when deciding or changing physics-bearing policy: k-points, smearing, pseudopotentials, SOC, convergence.
- `write-a-test` when changing public behavior or capturing a discovered regression.

## Mental model

The fixed Core graph is:

```text
Load → Analyze → Advise → Kmesh → Select → Generate → Bundle
```

Modes stop at different points:

```text
recommend -> Load → Analyze → Advise → Kmesh → Select
generate  -> Load → Analyze → Advise → Kmesh → Select → Generate
bundle    -> Load → Analyze → Advise → Kmesh → Select → Generate → Bundle
```

Use this distinction to avoid unnecessary source reading:

- Need numbers only? Use `recommend`.
- Need generated files in memory? Use `generate`.
- Need files on disk? Use `bundle` or `write_bundle`.
- Need to hand-write an input? Run `recommend`, extract values, then write the target-code file yourself.

## Inputs to identify first

Before running anything, identify:

1. Structure path or `pymatgen.Structure`.
2. Target intent: code, task, functional, accuracy level, pseudo mode.
3. Operator hints: k-grid or k-spacing, smearing, spin/SOC, pseudo type, convergence.
4. Pseudopotential metadata source: usually a local directory of `.UPF` files.
5. Desired output style: numbers only, generated file, or bundle directory.

## Canonical API surface

Use the public API from `goldilocks_core`, not internal modules, unless debugging or modifying Core itself:

```python
from goldilocks_core import (
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    generate,
    recommend,
    run_core_job,
    write_bundle,
)
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
```

The CLI entry point is:

```bash
uv run goldilocks-core recommend STRUCTURE --json
uv run goldilocks-core generate STRUCTURE --pseudo-root PSEUDOS --json
uv run goldilocks-core bundle STRUCTURE --pseudo-root PSEUDOS --out RUN_DIR --json
```

## Common pitfalls

- Use `uv run`, not bare `python`, `pip`, or manual virtualenv activation.
- Current built-in generation target is `quantum_espresso` + `scf_single_point`.
- Generators are mechanical. Scientific choices must already exist in advice/selection records.
- User hints win over defaults and model-backed choices.
- Pseudopotential matching is functional-sensitive: `PBE`, `PBESOL`, `LDA`, etc.
- UPF files may parse but lack cutoff metadata. Generation requires complete pseudo and cutoff selections.
- Heavy elements make SOC worth considering; Core does not silently enable expensive SOC.
- Structure-only electronic character is uncertain. Inspect smearing warnings.
- Core is not Runner/AiiDA/scheduler/frontend. It prepares recommendations and input files only.

## Verification checklist

For any produced input or parameter list, report:

- structure and reduced formula
- functional and target code/task
- k-grid and shift
- pseudopotentials by element
- `ecutwfc` / `ecutrho`
- smearing and degauss, or fixed occupations
- convergence values
- warnings from the result
- output files or bundle path
