# Goldilocks workflows

Use these patterns before reading implementation files.

## Inspect structures

Read candidate periodic files with pymatgen and report parse failures before
running Core:

```python
from pathlib import Path
from pymatgen.core import Structure

for path in sorted(Path("structures").glob("*.cif")):
    try:
        structure = Structure.from_file(path)
        elements = sorted(
            element.symbol for element in structure.composition.elements
        )
        print(path, structure.composition.reduced_formula, elements, len(structure))
    except (OSError, ValueError) as error:
        print(path, "ERROR", error)
```

## Load pseudopotential metadata

```python
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

pseudo_metadata = tuple(load_pseudo_metadata("pseudos"))
for pseudo in pseudo_metadata:
    print(
        pseudo.element,
        pseudo.filename,
        pseudo.functional,
        pseudo.pseudo_type,
        pseudo.relativistic,
        pseudo.sssp_recommended_cutoff,
    )
```

Generation needs a filename and complete `ecutwfc_ry`/`ecutrho_ry` values for
every selected element. Never invent missing cutoffs; obtain them from a trusted
library table or explicit operator policy and preserve provenance.

## Complete recommendation

```python
from goldilocks_core import (
    CalculationHints,
    CalculationIntent,
    CoreService,
    PresetRequest,
)
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

request = PresetRequest(
    structure="structure.cif",
    intent=CalculationIntent(
        code="quantum_espresso",
        task="scf_single_point",
        functional="PBE",
        pseudo_mode="efficiency",
    ),
    hints=CalculationHints(
        k_spacing=0.2,
        # k_grid=(4, 4, 4),  # explicit grid wins over spacing
        # pseudo_type="NC",
        # smearing_type="cold",
        # smearing_width_ry=0.01,
    ),
    pseudo_metadata=tuple(load_pseudo_metadata("pseudos")),
)

with CoreService() as core:
    result = core.recommend(request)

print(result.analysis.reduced_formula)
print(result.k_points.grid, result.k_points.shift)
print(result.selection.pseudopotentials)
print(result.advice.smearing)
print(result.advice.convergence)
print(result.warnings)
```

Extract cutoffs from each `PseudopotentialSelection` and use the maxima across
elements when inspecting a generated calculation.

## Generate files in memory

```python
from goldilocks_core import CalculationHints, CoreService, PresetRequest
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

request = PresetRequest(
    structure="structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4)),
    pseudo_metadata=tuple(load_pseudo_metadata("pseudos")),
)

with CoreService() as core:
    result = core.generate(request)

for generated_file in result.generated_files:
    print(generated_file.path)
    print(generated_file.content)
```

## Publish a bundle directory

```python
with CoreService() as core:
    result = core.generate(request, output_dir="run-dir")

print(result.bundle.path)
print(result.bundle.manifest)
```

CLI equivalent:

```bash
uv run goldilocks generate structure.cif --pseudo-root pseudos --functional PBE --k-spacing 0.2 --out run-dir --json
```

The destination must not exist. The published layout is:

```text
run-dir/
├── manifest.json
└── inputs/
    └── qe.in
```

If the QE file uses `pseudo_dir = './pseudo'`, stage the selected UPFs there
before running QE; Core does not copy pseudopotential libraries.

## Query selected records

```python
from goldilocks_core import CalculationHints, CoreService, QueryRequest
from goldilocks_core.contracts import KPointSelection, StructureAnalysisRecord

request = QueryRequest(
    structure="structure.cif",
    outputs=(StructureAnalysisRecord, KPointSelection),
    hints=CalculationHints(k_grid=(4, 4, 4)),
)

with CoreService() as core:
    records = core.compute(request)

print(records[StructureAnalysisRecord])
print(records[KPointSelection])
```

CLI equivalent:

```bash
uv run goldilocks compute structure.cif --outputs analysis,k_points --k-grid 4 4 4
```

## One-call runner

Use the convenience entry points only when model reuse and discovery are not
needed:

```python
from goldilocks_core import PresetRequest, QueryRequest, query_records, run_core_job
from goldilocks_core.contracts import StructureAnalysisRecord

result = run_core_job(
    PresetRequest(structure="structure.cif", mode="recommend")
)
records = query_records(
    QueryRequest(structure="structure.cif", outputs=(StructureAnalysisRecord,))
)
```

## Local kmesh model

Put the model specification on the request; do not replace a pipeline object:

```python
from goldilocks_core import CoreService, PresetRequest
from goldilocks_core.contracts import ModelSpec

spec = ModelSpec(
    name="local-kmesh-model",
    version="v1",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="models/kmesh.joblib",
)

with CoreService() as core:
    result = core.recommend(
        PresetRequest(structure="structure.cif", kmesh_model=spec)
    )
print(result.k_points.grid)
```

## Optional transports

```bash
uv sync --all-extras
uv run goldilocks serve http --host 127.0.0.1 --port 8000
uv run goldilocks serve mcp
```

HTTP exposes `/recommend`, `/generate`, `/compute`, `/tasks`, `/codes`,
`/models`, and `/health`. MCP exposes matching operation and discovery tools
over stdio. Both reuse one process-owned `CoreService`.

## Manual QE writing check

When writing the input yourself after recommendation, include:

- `&CONTROL`: `calculation='scf'`, `pseudo_dir`, `outdir`, stress/force flags;
- `&SYSTEM`: `ibrav=0`, `nat`, `ntyp`, cutoffs, occupations, spin/SOC;
- `&ELECTRONS`: convergence threshold, mixing beta, maximum SCF steps;
- `ATOMIC_SPECIES`: element, mass, selected pseudo filename;
- `CELL_PARAMETERS angstrom` from the loaded lattice;
- `ATOMIC_POSITIONS crystal` or `angstrom` from the structure;
- `K_POINTS automatic` from selected grid and shift.

See `qe-scf-template.md` for a compact template.
