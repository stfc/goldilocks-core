# Tutorial

A from-scratch walkthrough of goldilocks-core. No prior knowledge is assumed.
You will install the package, load a bundled example structure, get a
recommendation, inspect the result, generate a Quantum ESPRESSO SCF input file,
and optionally write a bundle directory. Each step shows the Python API and the
equivalent CLI side by side.

## What goldilocks-core does

It recommends inputs for **DFT** (density functional theory) simulations. You
give it a crystal structure and a calculation intent; it returns:

- **analysis** — facts about the structure (formula, elements, dimensionality);
- **advice** — scientifically justified parameters (smearing, magnetism, SOC,
  convergence, vdW, pseudopotential family) with **provenance** recording why
  each value was chosen;
- **k_points** — a concrete k-point sampling grid;
- **selection** — concrete per-element pseudopotentials and cutoffs;
- **generated files** — rendered Quantum ESPRESSO SCF input (in `generate` mode).

A **pseudopotential** is a per-element approximation that replaces core
electrons; **k-points** sample reciprocal space; **SCF** is a self-consistent
field calculation (the one task currently supported); **provenance** records the
source and reason for each recommendation so you can decide whether to trust or
override it.

## Install

This project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

For development dependencies:

```bash
uv sync --group dev
```

The HTTP and MCP transport servers are optional extras (not needed for this
tutorial):

```bash
uv sync --extra http --extra mcp
```

## The bundled examples

The package ships three small example structures so you can run end to end
without supplying your own:

```python
from goldilocks_core.examples import available_structures, structure

print(available_structures())   # ('Fe_bcc.cif', 'Pt_fcc.cif', 'Si.cif')
path = structure("Si.cif")      # a pathlib.Path into the installed package
```

CLI equivalent:

```bash
goldilocks-core examples path    # prints the directory holding the examples
```

Each example exercises a different branch of the advice stage:

| File | System | What it reaches |
| --- | --- | --- |
| `Si.cif` | diamond Si | Baseline: non-magnetic, no heavy elements, fixed occupations. |
| `Fe_bcc.cif` | bcc Fe | Magnetic metal — spin polarisation and cold smearing. |
| `Pt_fcc.cif` | fcc Pt | Heavy element — spin-orbit coupling advice. |

Below, `"Si.cif"` stands for your own structure file when you have one.

## Get a recommendation

Python:

```python
from goldilocks_core import recommend
from goldilocks_core.examples import structure

result = recommend(structure("Si.cif"))

print(result.analysis.reduced_formula)        # "Si"
print(result.k_points.provenance.source)      # "model"  (the default QRF backend)
print(result.k_points.grid)                   # concrete model grid, e.g. (8, 8, 8)
print(result.to_dict())                       # full JSON-safe dict
```

CLI:

```bash
goldilocks-core recommend "$(goldilocks-core examples path)/Si.cif" --json
```

Without `--json` you get a compact human-readable summary:

```bash
goldilocks-core recommend "$(goldilocks-core examples path)/Si.cif"
```

`recommend(...)` runs Load → Analyze → Advise → Kmesh → Select and returns a
`CoreResult`. It does not generate input files.

## Read the CoreResult

`CoreResult` is the accumulator record. Its main fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `analysis` | `StructureAnalysisRecord` | Structure facts (no decisions). |
| `advice` | `ParameterAdvice` | Provenance-backed recommendations. |
| `k_points` | `KPointSelection` | Concrete k-point grid. |
| `selection` | `SelectionRecord` | Concrete pseudopotentials and cutoffs. |
| `generated_files` | `tuple[GeneratedFile, ...]` | Generated input files (generate mode only). |
| `warnings` | `tuple[str, ...]` | Aggregated caveats. |
| `bundle` | `BundleRecord \| None` | Bundle record when a directory was written. |

```python
print(result.advice.magnetism.spin_polarized)       # False for Si
print(result.advice.smearing.smearing_type)         # None (fixed occupations)
print(result.selection.pseudopotentials)            # one PseudopotentialSelection per element
print(result.warnings)                              # tuple of caveats
```

## Override defaults with hints

`CalculationHints` carries optional operator overrides. A `None` field means
"let Core decide"; a non-`None` value overrides the Core default and records
`user_hint` provenance.

```python
from goldilocks_core import CalculationHints, recommend

result = recommend(
    structure("Fe_bcc.cif"),
    hints=CalculationHints(
        k_grid=(4, 4, 4),
        spin_polarized=True,
        smearing_type="cold",
        smearing_width_ry=0.01,
    ),
)

print(result.k_points.provenance.source)            # "user_hint"
print(result.advice.magnetism.provenance.source)    # "user_hint"
print(result.advice.convergence.provenance.source)  # "default" (not hinted)
```

CLI:

```bash
goldilocks-core recommend "$(goldilocks-core examples path)/Fe_bcc.cif" \
    --k-grid 4 4 4 --spin-polarized true --smearing-type cold --smearing-width-ry 0.01 --json
```

## Generate an input file

`generate(...)` runs the full path through Generate and attaches
`generated_files` to the result:

```python
from goldilocks_core import CalculationHints, generate
from goldilocks_core.examples import structure

result = generate(structure("Si.cif"))

for generated_file in result.generated_files:
    print(generated_file.path)     # "inputs/qe.in"
    print(generated_file.content)  # full QE SCF input text
```

CLI:

```bash
goldilocks-core generate "$(goldilocks-core examples path)/Si.cif" --json
```

To select pseudopotentials you need pseudopotential metadata. From the CLI pass
a directory of UPF files:

```bash
goldilocks-core generate "$(goldilocks-core examples path)/Si.cif" \
    --pseudo-root path/to/pseudos --json
```

From Python, load metadata and pass it through:

```python
from goldilocks_core import CalculationHints, generate
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

pseudo_metadata = load_pseudo_metadata("path/to/pseudopotentials")

result = generate(
    structure("Si.cif"),
    hints=CalculationHints(pseudo_type="NC"),
    pseudo_metadata=pseudo_metadata,
)

for pseudo in result.selection.pseudopotentials:
    print(f"{pseudo.element}: {pseudo.filename}")
    if pseudo.ecutwfc_ry is not None:
        print(f"  ecutwfc = {pseudo.ecutwfc_ry} Ry")
```

## Write a bundle directory

To write generated files and a `manifest.json` to a new directory, use
`run_core_job` with `mode="generate"` and `output_dir`:

```python
from goldilocks_core import CalculationHints, CoreJobRequest, run_core_job
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata
from goldilocks_core.examples import structure

pseudo_metadata = load_pseudo_metadata("path/to/pseudopotentials")

result = run_core_job(
    CoreJobRequest(
        structure=structure("Si.cif"),
        hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
        pseudo_metadata=tuple(pseudo_metadata),
        mode="generate",
        output_dir="run/",
    )
)

print(result.bundle.path)          # "run/"
print(result.bundle.manifest)      # manifest dict
# run/manifest.json and run/inputs/qe.in are now on disk
```

CLI equivalent — `generate --out <dir>`:

```bash
goldilocks-core generate "$(goldilocks-core examples path)/Si.cif" \
    --pseudo-root path/to/pseudos --k-grid 4 4 4 --out run/ --json
```

The output directory must not already exist.

## Inspect intermediate stages

For interactive exploration, use the stage-by-stage API or the `CoreRuntime`
raw entrypoints:

```python
from goldilocks_core import CoreJobRequest, CoreRuntime
from goldilocks_core.examples import structure

with CoreRuntime() as runtime:
    request = CoreJobRequest(structure=structure("Fe_bcc.cif"))
    analysis = runtime.analyze(request)
    print(analysis.elements)                 # ("Fe",)
    print(analysis.electronic_character)     # "likely_metal"
    print(analysis.heavy_elements)           # ()

    advice = runtime.advise(request)
    print(advice.spin_orbit.consider)        # False

    k_points = runtime.kmesh(request)
    print(k_points.grid)                     # concrete model grid

    selection = runtime.select(request)
    print(selection.pseudopotentials)
```

Model state is reused across calls on the same runtime.

## Use the shared job runner

`run_core_job` is the same dispatch path the CLI uses. With `runtime=None` it
creates a fresh `CoreRuntime` for the call:

```python
from goldilocks_core import CoreJobRequest, CalculationHints, run_core_job

result = run_core_job(
    CoreJobRequest(
        structure="structure.cif",
        hints=CalculationHints(k_spacing=0.2),
        mode="recommend",
    )
)

print(result.to_dict())           # full JSON-safe output
```

## Error handling

- **Missing pseudopotentials**: selection records have `filename=None` and carry
  warnings. Generation raises `ValueError`.
- **Invalid hints**: `CalculationHints` raises `ValueError` for non-positive
  `k_spacing`, `conv_thr`, etc. at construction, before any stage runs.
- **Disordered structures**: analysis reports `disorder_warnings`. Generation
  raises `ValueError` — disordered occupancies require manual resolution.
- **Unsupported codes/tasks**: generation raises `ValueError` for anything other
  than QE SCF.

## ML k-mesh backend

To use a local k-index model for k-point selection, put a `ModelSpec` on the
request:

```python
from goldilocks_core import CoreJobRequest, run_core_job
from goldilocks_core.contracts import ModelSpec

spec = ModelSpec(
    name="local-kmesh-model",
    version="v0",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="path/to/model.joblib",
)

result = run_core_job(
    CoreJobRequest(structure="structure.cif", mode="recommend", kmesh_model=spec)
)

print(result.k_points.grid)
print(result.k_points.provenance.source)       # "model"
```

Operator hints still take precedence:

```python
from goldilocks_core import CalculationHints

result = run_core_job(
    CoreJobRequest(
        structure="structure.cif",
        mode="recommend",
        hints=CalculationHints(k_grid=(4, 4, 4)),
        kmesh_model=spec,
    )
)

print(result.k_points.provenance.source)  # "user_hint"
```

CLI:

```bash
goldilocks-core recommend structure.cif --model path/to/model.joblib --json
```

## Common patterns

**I just need a k-grid:**

```python
from goldilocks_core import recommend
result = recommend("structure.cif")
print(result.k_points.grid)
```

**I want JSON for an HTTP service:**

```python
from goldilocks_core import recommend
result = recommend("structure.cif")
return result.to_dict()
```

**I want SOC on for a heavy-element compound:**

```python
from goldilocks_core import CalculationHints, recommend
result = recommend(
    "structure.cif",
    hints=CalculationHints(
        spin_orbit_coupling=True,
        relativistic_mode="full",
    ),
)
```

CLI:

```bash
goldilocks-core recommend structure.cif \
    --spin-orbit-coupling true --relativistic-mode full --json
```