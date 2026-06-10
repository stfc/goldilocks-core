# Select stage

Owner: `selection.py`

The Select stage resolves advice into concrete values: k-point grids, pseudopotential assignments, and cutoffs.

## Input

- `pymatgen.core.Structure`
- `ParameterAdvice` (from Advise)
- Optional list of `PseudoMetadata`

## Output

- `SelectionRecord`

## k-point selection

1. If `KPointAdvice.explicit_grid` is set → `KPointSelection(grid=advice.explicit_grid, shift=(0,0,0), provenance.source="user_hint")`.
2. If `KPointAdvice.spacing` is set → convert spacing to mesh via `k_distance_to_mesh()`, `KPointSelection(grid=mesh, shift=(0,0,0))`. Provenance source is inherited from the advice provenance.
3. If neither is set → raises `ValueError`. This should not happen if the Advise stage ran correctly.

The conversion uses the VASP KSPACING convention. See [conventions](conventions.md).

## Pseudopotential selection

For each element in the structure:

1. Filter `metadata_list` by element, functional, pseudo_type, and relativistic mode using `select_pseudos()`.
2. Rank remaining candidates by the deterministic 5-tuple key.
3. Take the highest-ranked candidate (first after sort).
4. Extract `ecutwfc_ry` and `ecutrho_ry` from `sssp_recommended_cutoff`.
5. If no candidate matches → return a `PseudopotentialSelection` with `filename=None` and a warning.

### Ranking key

Candidates are sorted by the tuple `(mode_rank, cutoff_rank, sssp_rank, source, filename)`:

| Key component | 0 (better) | 1 (worse) |
| --- | --- | --- |
| `mode_rank` | metadata matches requested pseudo_mode | does not match |
| `cutoff_rank` | both ecutwfc and ecutrho are available | at least one is missing |
| `sssp_rank` | `is_sssp=True` | `is_sssp=False` |
| `source` | `source_set` or `library` string (lexicographic) | |
| `filename` | filename string (lexicographic, tiebreaker) | |

Mode matching searches the concatenation of `library`, `source_set`, `source_pseudopotential`, and `filename` for the requested mode string (e.g. `efficiency`). If a metadata entry contains both `efficiency` and `precision`, it is treated as not matching either specific mode.

## Warnings

Selection produces warnings in two places:

- `PseudopotentialSelection.warnings`: per-element warnings about missing pseudos or incomplete cutoff data.
- `SelectionRecord.warnings`: aggregated from all pseudo selection warnings.

Common warnings:

- "No pseudopotential metadata matched {element} / {functional} / {relativistic_mode}."
- "Selected pseudopotential for {element} does not explicitly match pseudo mode '{mode}'."
- "Selected pseudopotential for {element} lacks complete cutoff metadata."