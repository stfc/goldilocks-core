# Example structures

Goldilocks includes three small crystal structures. Use them to try the package
without finding a structure file first.

## Run an example

Install the default runtime assets:

```bash
uv run goldilocks assets install default
```

Run the silicon example:

```bash
uv run goldilocks recommend "$(uv run goldilocks examples path)/Si.cif"
```

From Python:

```python
from goldilocks_core import (
    CalculationDraft,
    ComputeRequest,
    PresetSelection,
    Service,
)
from goldilocks_core.contracts import KPointSelection, StructureAnalysisRecord
from goldilocks_core.examples import structure

request = ComputeRequest(
    draft=CalculationDraft(structure=structure("Si.cif")),
    selection=PresetSelection("recommend"),
)
with Service() as core:
    result = core.compute(request)

print(result.records[StructureAnalysisRecord].reduced_formula)
print(result.records[KPointSelection].grid)
```

## Available structures

- `Si.cif`: diamond silicon. A simple non-magnetic semiconductor example.
- `Fe_bcc.cif`: body-centred cubic iron. Goldilocks recommends spin
  polarisation and metallic smearing.
- `Pt_fcc.cif`: face-centred cubic platinum. Goldilocks reports that SOC should
  be considered because platinum is a heavy element.

These files are input examples. They are not converged calculations or benchmark
results.

## Use an example path in Python

The `structure()` function returns the full path to an installed example:

```python
from goldilocks_core.examples import structure

silicon_path = structure("Si.cif")
```
