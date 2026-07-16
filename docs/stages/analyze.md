# Analyze stage

Owner: `analysis.py`

The Analyze stage reports structure facts without making parameter decisions. It is read-only: it tells later stages what the structure *is*, not what to calculate.

## Input

- `pymatgen.core.Structure`

## Output

- `StructureAnalysisRecord`

## What it reports

### Composition

- `formula`: full chemical formula from pymatgen (e.g. `Fe2O31`).
- `reduced_formula`: reduced formula (e.g. `Fe2O3`).
- `site_count`: number of sites.
- `elements`: sorted unique element symbols.

### Element classification

- `contains_transition_metals`: True if any element is a transition metal per pymatgen's `Element.is_transition_metal`.
- `contains_lanthanides`: True if any element is a lanthanoid.
- `contains_actinides`: True if any element is an actinoid.
- `contains_heavy_elements`: True if any element has `row >= 5`. See [conventions](../conventions.md) for the rationale.
- `heavy_elements`: tuple of period-5+ element symbols.
- `magnetic_elements`: union of transition metals, lanthanides, and actinides.

### Disorder

- `disorder_warnings`: per-site warnings for partial occupancies. Format: `"Site {n} has partial occupancies: {species_list}."`
- `disordered_site_count`: number of sites with partial occupancies.

### Symmetry

- `space_group_symbol`: Hermann-Mauguin symbol from pymatgen `SpacegroupAnalyzer`.
- `space_group_number`: International table number (1–230).
- `crystal_system`: crystal system name (e.g. `cubic`).

Symmetry is skipped for disordered structures (returns None for all three fields). If `SpacegroupAnalyzer` raises during analysis, all three fields are set to None rather than propagating the error.

### Electronic character

- `electronic_character`: conservative heuristic classification.
  - `likely_metal`: all elements are metallic. Always accompanied by a warning that metallicity is inferred, not confirmed.
  - `unknown`: cannot determine from structure facts alone.

### Warnings

- `analysis_warnings`: warnings about heuristic limitations, primarily about electronic character uncertainty.

## What it does not do

- It does not recommend k-points, smearing, SOC, pseudopotentials, or convergence settings.
- It does not classify dimensionality (currently always `unknown`).
- It does not predict metallicity from electronic-structure data.

## Edge cases

- **Disordered structures**: symmetry fields are None, disorder_warnings are populated.
- **Single-element metals**: `electronic_character` is `likely_metal` with a warning.
- **Mixed metal/non-metal**: `electronic_character` is `unknown` with a warning to verify smearing manually.
- **spglib failures**: caught and result is None for all symmetry fields.