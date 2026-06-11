# Goldilocks Workflows

Use these patterns before reading implementation files.

## Inspect available structures

```bash
find PATH -maxdepth 2 -type f \( -iname '*.cif' -o -iname '*.mcif' \) -print
```

To summarize CIFs with pymatgen:

```bash
uv run python - <<'PY'
from pathlib import Path
from pymatgen.core import Structure

for path in sorted(Path('PATH').glob('*.cif')):
    try:
        structure = Structure.from_file(path)
        elements = sorted(element.symbol for element in structure.composition.elements)
        print(path, structure.composition.reduced_formula, elements, len(structure))
    except Exception as exc:
        print(path, 'ERROR', exc)
PY
```

## Load pseudopotential metadata

```python
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

pseudo_metadata = tuple(load_pseudo_metadata('pseudos'))
```

Goldilocks parses local `.UPF` files. Check whether parsed metadata includes complete cutoffs before expecting generation to work:

```bash
uv run python - <<'PY'
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

for metadata in load_pseudo_metadata('pseudos'):
    print(
        metadata.element,
        metadata.filename,
        metadata.functional,
        metadata.pseudo_type,
        metadata.relativistic,
        metadata.sssp_recommended_cutoff,
    )
PY
```

If cutoffs are missing, do not let the generator invent them. Get them from a trusted pseudo-library table or operator-provided policy and make that provenance explicit in the response.

## Numbers only: run through Select, not Generate

Use this for manually writing an input file from Goldilocks-selected values.

```python
from goldilocks_core import CalculationHints, CalculationIntent, recommend
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

pseudo_metadata = tuple(load_pseudo_metadata('pseudos'))

result = recommend(
    'structure.cif',
    intent=CalculationIntent(
        code='quantum_espresso',
        task='scf_single_point',
        functional='PBE',
        accuracy_level='standard',
        pseudo_mode='efficiency',
    ),
    hints=CalculationHints(
        k_spacing=0.2,
        # k_grid=(4, 4, 4),  # explicit grid wins over spacing
        # pseudo_type='NC',
        # smearing_type='cold',
        # smearing_width_ry=0.01,
    ),
    pseudo_metadata=pseudo_metadata,
)

print(result.analysis.reduced_formula)
print(result.selection.k_points.grid)
print(result.selection.k_points.shift)
print(result.selection.pseudopotentials)
print(result.advice.smearing)
print(result.advice.convergence)
print(result.warnings)
```

Extract:

- `result.selection.k_points.grid`
- `result.selection.k_points.shift`
- one `result.selection.pseudopotentials` record per element
- max `ecutwfc_ry` and `ecutrho_ry` across selected pseudopotentials
- `result.advice.smearing`
- `result.advice.magnetism` and `result.advice.spin_orbit`
- `result.advice.convergence`

## Generate input files in memory

```python
from goldilocks_core import CalculationHints, generate
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

result = generate(
    'structure.cif',
    hints=CalculationHints(k_grid=(4, 4, 4)),
    pseudo_metadata=tuple(load_pseudo_metadata('pseudos')),
)

for generated_file in result.generated_files:
    print(generated_file.path)
    print(generated_file.content)
```

Use this when you want to inspect generated text but do not need a directory yet.

## Write a bundle directory

```python
from goldilocks_core import CalculationHints, write_bundle
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

result = write_bundle(
    'structure.cif',
    'run-dir',
    hints=CalculationHints(k_spacing=0.2),
    pseudo_metadata=tuple(load_pseudo_metadata('pseudos')),
)

print(result.bundle_path)
print(result.manifest)
```

CLI equivalent:

```bash
uv run goldilocks-core bundle structure.cif \
    --pseudo-root pseudos \
    --functional PBE \
    --k-spacing 0.2 \
    --out run-dir \
    --json
```

Bundle layout:

```text
run-dir/
├── manifest.json
└── inputs/
    └── qe.in
```

If the generated QE file uses `pseudo_dir = './pseudo'`, copy or stage selected UPFs into that directory before running QE.

## Shared job runner

Use the shared runner when you need a single data-only request/result model for Python, CLI, or future HTTP mapping.

```python
from goldilocks_core import CalculationHints, CoreJobRequest, run_core_job
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

request = CoreJobRequest(
    structure='structure.cif',
    hints=CalculationHints(k_spacing=0.2),
    pseudo_metadata=tuple(load_pseudo_metadata('pseudos')),
    mode='recommend',  # recommend, generate, or bundle
    output_dir=None,
)

result = run_core_job(request)
print(result.to_dict())
```

## ML kmesh backend

The request stays data-only. Swap the Kmesh stage through `Pipeline`:

```python
from dataclasses import replace

from goldilocks_core import CoreJobRequest, default_pipeline, run_core_job
from goldilocks_core.advisors import ml_kmesh_advisor
from goldilocks_core.contracts import ModelSpec

spec = ModelSpec(
    name='local-kmesh-model',
    version='v1',
    model_type='random_forest',
    target='k_index',
    feature_set='cslr',
    source='local',
    location='models/kmesh.joblib',
)

pipeline = replace(default_pipeline(), kmesh=ml_kmesh_advisor(spec))
result = run_core_job(CoreJobRequest(structure='structure.cif'), pipeline=pipeline)
print(result.recommendation.selection.k_points.grid)
```

## Manual QE writing checklist

When writing the input yourself after `recommend`, include:

- `&CONTROL`: `calculation='scf'`, `pseudo_dir`, `outdir`, stress/force flags if desired.
- `&SYSTEM`: `ibrav=0`, `nat`, `ntyp`, cutoffs, occupations, spin/SOC flags.
- `&ELECTRONS`: convergence threshold, mixing beta, maximum SCF steps.
- `ATOMIC_SPECIES`: element, mass, selected pseudo filename.
- `CELL_PARAMETERS angstrom` from the loaded structure lattice.
- `ATOMIC_POSITIONS crystal` or `angstrom` from the loaded structure.
- `K_POINTS automatic` from selected grid and shift.

See `qe-scf-template.md` for a compact template.
