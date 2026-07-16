# Migration guide

The staged Core refactor removes several pre-existing import paths and changes some behavior. This guide maps old paths to new ones.

## Removed modules

### `goldilocks_core.shared`

**Gone entirely.** The `shared/` package and `shared/types.py` have been removed. All contract types now live in `goldilocks_core.contracts`.

| Old import | New import |
| --- | --- |
| `from goldilocks_core.shared.types import KPointAdviceRecord` | `from goldilocks_core.contracts import KPointAdvice` |
| `from goldilocks_core.shared.types import KPointsAdvice` | `from goldilocks_core.contracts import KPointSelection` |
| `from goldilocks_core.shared.types import PseudoSelection` | Removed. Use `PseudopotentialSelection`. |
| `from goldilocks_core.shared.types import *` | `from goldilocks_core.contracts import *` (explicit names preferred) |

## Renamed types

| Old name | New name | Notes |
| --- | --- | --- |
| `KPointAdviceRecord` | `KPointAdvice` | Advice-stage record, not a selection |
| `KPointsAdvice` | `KPointSelection` | Concrete k-point selection from the Kmesh stage |

## Moved functions

| Old location | New location | Notes |
| --- | --- | --- |
| `goldilocks_core.io.structures.analyze_structure()` | `goldilocks_core.analysis.analyze_structure()` | Analysis is a pipeline stage, not I/O |

## Removed top-level aliases

The `CoreRecommendation` class used to re-export several attributes at the top level (`grid`, `contains_*`, etc.). These shortcuts are gone. Access fields through the nested structure:

```python
# Old
result.grid          # shortcut for result.selection.k_points.grid
result.contains_heavy_elements  # shortcut for analysis field

# New
result.selection.k_points.grid
result.analysis.contains_heavy_elements
```

## Changed stage-by-stage API

The `pipeline.py` wrapper module has been removed. For stage-by-stage use, import `load_structure` from `io.structures` and use `Pipeline` fields directly:

```python
from goldilocks_core import CalculationHints, Pipeline
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.advice import advise_parameters
from goldilocks_core.io.structures import load_structure
from goldilocks_core.selection import select_parameters

hints = CalculationHints()
structure = load_structure("structure.cif")
analysis = analyze_structure(structure)
advice = advise_parameters(analysis, hints=hints)
k_points = Pipeline().kmesh(structure, hints, advice.k_points)
selection = select_parameters(structure, advice, k_points)
```

## Changed ML advisor integration

`advisors/kmesh_advisor.advise_kpoints()` returns `KPointSelection` and remains useful for standalone k-point prediction.

For staged pipeline integration, use `ml_kmesh_advisor(spec)` as a Kmesh backend:

```python

from goldilocks_core import CoreRuntime, Pipeline, recommend
from goldilocks_core.advisors import ml_kmesh_advisor

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
with CoreRuntime(pipeline=pipeline) as runtime:
    result = recommend("structure.cif", runtime=runtime)
```

This preserves `provenance.source="model"` inside the staged pipeline.

## Changed heavy-element heuristic

Pre-refactor: `Z >= 57` (lanthanum onwards).
Post-refactor: `row >= 5` in pymatgen (period 5+).

This broadens the set of "heavy" elements to include period-5 non-lanthanides like iodine (Z=53). See [conventions](conventions.md) for details.

## No compatibility layer

There are no backward-compatible aliases. If you were importing from `goldilocks_core.shared`, update your imports to `goldilocks_core.contracts`. If you were using top-level shortcuts on `CoreResult`, access the nested fields directly.