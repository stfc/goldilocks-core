# Python API

Use Goldilocks to generate inputs from a script. First complete the
[installation and asset setup](quickstart.md#1-install). Run the examples in
order in the same Python session, or save them in a script and run
`uv run your_script.py`.

## Generate inputs

This example writes to `si-python/`. Choose another name if it already exists.

```python
from goldilocks_core import (
    CalculationDraft,
    ComputeRequest,
    DirectoryOutput,
    PathStructureSource,
    PresetSelection,
    compute,
)
from goldilocks_core.examples.structures import structure

source = PathStructureSource(structure("Si.cif"))
request = ComputeRequest(
    draft=CalculationDraft(structure=source),
    selection=PresetSelection("generate"),
)
result = compute(request, output=DirectoryOutput("si-python"))

print(result.publication["path"])
for warning in result.warnings:
    print(warning)
```

Replace `structure("Si.cif")` with a path to your own CIF or POSCAR.
`CalculationDraft` holds the structure and settings;
`PresetSelection("generate")` asks for input files. `DirectoryOutput` writes
them to a new directory. See the [quickstart](quickstart.md#2-generate-an-input)
for its contents.

## Read a recommendation

`result.records` holds the computed results, keyed by record type:

```python
from goldilocks_core import KPointSelection

k_points = result.records[KPointSelection]
print(k_points["grid"])
print(k_points["provenance"].reason)
```

This prints the selected grid and the reason for it. Model-dependent values can
change with the installed model; review warnings and check convergence rather
than treating the recommendation as a verified result.

## Choose settings yourself

Pass `CalculationHints` for the settings you want to control:

```python
from goldilocks_core import CalculationHints

request = ComputeRequest(
    draft=CalculationDraft(
        structure=source,
        hints=CalculationHints(k_grid=(4, 4, 4)),
    ),
    selection=PresetSelection("recommend"),
)
result = compute(request)
print(result.records[KPointSelection]["grid"])
```

The grid is now `[4, 4, 4]`. An explicit grid bypasses the k-point model; other
settings are still recommended. The
[scientific controls](cli.md#scientific-controls) list the available hints.

`recommend` returns recommendations without generating input files. `generate`
adds the input files. Neither writes to disk through the Python API unless you
supply an output target.

## Choose an output

| `output` argument                | Result                             |
| -------------------------------- | ---------------------------------- |
| Omitted or `None`                | Keep the result in memory          |
| `DirectoryOutput("si-python")`   | Write a new directory              |
| `ArchiveOutput("si-python.zip")` | Write a ZIP with the same contents |

Import `ArchiveOutput` from `goldilocks_core` to use it. Use the `generate`
preset when writing outputs; choose a destination that does not already exist.

## Inspect structures and reuse loaded models

Use a `Service` for repeated calls:

```python
from goldilocks_core import Service

with Service() as core:
    inspection = core.inspect_structure(source)
    print(inspection["structure"]["reduced_formula"])
    result = core.compute(request)
```

Keep related computations inside the `with` block to reuse loaded models.
`core.capabilities()` lists the available tasks, presets, and controls.

## Request only the results you need

For example, request only the k-point grid:

```python
from goldilocks_core import RecordSelection

query = ComputeRequest(
    draft=request.draft,
    selection=RecordSelection((KPointSelection,)),
)
result = compute(query)
print(result.records[KPointSelection]["grid"])
```

Only the required stages run. This example retains the explicit grid from the
earlier request.

See [Recommendations](science.md) to interpret other settings, or
[Architecture](architecture.md) to extend the computation workflow.
