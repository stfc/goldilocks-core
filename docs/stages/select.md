# Select stage

Owner: `selection.py`

The current Select stage resolves QE-oriented UPF pseudopotential assignments and SSSP cutoffs in Ry, then combines them with the concrete k-point grid already produced by Kmesh.

## Input

- `pymatgen.core.Structure`
- `ParameterAdvice` (from Advise)
- `KPointSelection` (from Kmesh)
- optional list of `PseudoMetadata`

## Output

- `SelectionRecord`

## Responsibility

The current QE Select implementation owns:

- one UPF pseudopotential selection per element
- Ry cutoff extraction from selected SSSP metadata
- pseudo-selection warnings
- construction of the current QE-shaped `SelectionRecord`

Select does **not** own:

- k-point grid resolution — owned by Kmesh
- structure analysis — owned by Analyze
- scientific intent — owned by Advise
- target-code text rendering — owned by Generate
- pseudo parsing — owned by `pseudo/` registry and parser modules

## Kmesh interaction

`select_parameters()` receives a concrete k-point selection:

```python
selection = select_parameters(
    structure,
    advice,
    k_points,
    metadata_list,
)
```

The `k_points` argument is copied into the returned `SelectionRecord`.

This keeps Select focused on pseudopotentials and makes k-point resolution hot-swappable through the Kmesh stage.

## Pseudopotential selection

For each element in the structure:

1. Filter `metadata_list` by element, canonical functional label, pseudo_type, and relativistic mode using `select_pseudos()`. Supported spellings such as `PBEsol`, `PBESOL`, and `PBE-sol` share the canonical label `PBEsol`; unknown labels are preserved rather than guessed.
2. Rank remaining candidates by the deterministic 5-tuple key.
3. Take the highest-ranked candidate (first after sort).
4. Treat `sssp_recommended_cutoff` as untrusted metadata. Only finite, strictly positive `ecutwfc_ry` and `ecutrho_ry` values are copied into `PseudopotentialSelection`; invalid values are sanitized to `None` with an actionable warning. The inherited record validators enforce the same invariant for custom Select backends.
5. If no candidate matches, return a `PseudopotentialSelection` with `filename=None`, absent cutoffs, and a warning.

## Ranking key

Candidates are sorted by the tuple `(mode_rank, cutoff_rank, sssp_rank, source, filename)`:

| Key component | 0 (better) | 1 (worse) |
| --- | --- | --- |
| `mode_rank` | metadata matches requested pseudo_mode | does not match |
| `cutoff_rank` | both ecutwfc and ecutrho are finite and strictly positive | at least one is missing or invalid |
| `sssp_rank` | `is_sssp=True` | `is_sssp=False` |
| `source` | `source_set` or `library` string (lexicographic) | |
| `filename` | filename string (lexicographic, tiebreaker) | |

Mode matching searches the concatenation of `library`, `source_set`, `source_pseudopotential`, and `filename` for the requested mode string (e.g. `efficiency`). If a metadata entry contains both `efficiency` and `precision`, it is treated as not matching either specific mode.

## Warnings

Select produces warnings in two places:

- `PseudopotentialSelection.warnings`: per-element warnings about missing pseudos or incomplete cutoff data.
- `SelectionRecord.warnings`: aggregated from all pseudo selection warnings.

Common warnings:

- `No pseudopotential metadata matched {element} / {functional} / {relativistic_mode}.`
- `Selected pseudopotential for {element} does not explicitly match pseudo mode '{mode}'.`
- `Selected pseudopotential for {element} is missing cutoff metadata for {fields}; provide finite positive values before generation.`
- `Selected pseudopotential for {element} has invalid cutoff metadata ({field=value}); replace it with finite positive values before generation.`

## Backend contract

A custom Select backend must satisfy:

```python
SelectStage = Callable[
    [Structure, ParameterAdvice, KPointSelection, Sequence[PseudoMetadata]],
    SelectionRecord,
]
```

It may implement different QE pseudo ranking or cutoff policy, but it should not recalculate k-points. If k-point behavior needs to change, replace the Kmesh backend instead.

## Multi-code boundary

For another DFT target, Select is where the target adapter validates the target and task, resolves concrete target resources, and materializes explicit target-specific numerical data and units. Generate then renders that completed selection. This preserves the fixed graph while keeping target syntax out of Analyze and Advise.

The current `PseudoMetadata` and `PseudopotentialSelection` types cannot represent resources such as coordinated CP2K basis/potential sets or VASP PAW datasets without target-specific contracts. See [target-code adapters](../target-code-adapters.md).
