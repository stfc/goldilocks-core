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
| `KPointsAdvice` | `KPointSelection` | Concrete selection from the Select stage |

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

## Changed ML advisor return type

`advisors/kmesh_advisor.advise_kpoints()` now returns `KPointSelection` instead of the old standalone `KPointsAdvice`. The fields are the same (`grid`, `shift`, `mesh_type`, `provenance`), just under the new type.

## Changed heavy-element heuristic

Pre-refactor: `Z >= 57` (lanthanum onwards).
Post-refactor: `row >= 5` in pymatgen (period 5+).

This broadens the set of "heavy" elements to include period-5 non-lanthanides like iodine (Z=53). See [conventions](conventions.md) for details.

## No compatibility layer

There are no backward-compatible aliases. If you were importing from `goldilocks_core.shared`, update your imports to `goldilocks_core.contracts`. If you were using top-level shortcuts on `CoreRecommendation`, access the nested fields directly.