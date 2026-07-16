# Generate stage

Owner: `generation.py`

The Generate stage validates and renders completed advice and selection records. The current implementation supports QE SCF only. Scientific and resource choices come from records; the writer also supplies fixed QE layout values such as namelist/card structure, calculation type, working directories, and output path.

## Input

- `pymatgen.core.Structure`
- `CalculationIntent`
- `ParameterAdvice` (from Advise)
- `SelectionRecord` (from Select)

## Output

- `tuple[GeneratedFile, ...]`

Currently only Quantum ESPRESSO SCF single-point input is supported, producing one file at `inputs/qe.in`.

## Quantum ESPRESSO SCF input

### Sections produced

| QE section | Values from |
| --- | --- |
| `&CONTROL` | fixed QE layout: `calculation='scf'`, `pseudo_dir='./pseudo'`, `outdir='./out'`, `tprnfor=.true.`, `tstress=.true.` |
| `&SYSTEM` | intent, advice, selection |
| `&ELECTRONS` | convergence advice |
| `CELL_PARAMETERS` | structure lattice |
| `ATOMIC_SPECIES` | pseudo selection |
| `ATOMIC_POSITIONS` | structure sites |
| `K_POINTS` | k-point selection |

### &SYSTEM details

- `ibrav = 0` (always, cell provided via CELL_PARAMETERS)
- `nat`, `ntyp` from structure
- `ecutwfc`: max of all `PseudopotentialSelection.ecutwfc_ry`
- `ecutrho`: max of all `PseudopotentialSelection.ecutrho_ry`
- **Occupations**: `"fixed"` when smearing is None or `"fixed"`; `"smearing"` otherwise
- **Smearing**: `smearing` and `degauss` from `SmearingAdvice` when applicable
- **Spin**: `nspin = 2` when magnetism is spin-polarized and SOC is not enabled
- **SOC**: `noncolin = .true.` and `lspinorb = .true.` when SOC is enabled. `nspin = 2` is **not** emitted alongside noncollinear SOC flags.

### &ELECTRONS details

- `conv_thr`: from `ConvergenceAdvice.conv_thr`, formatted in scientific notation
- `mixing_beta`: from `ConvergenceAdvice.mixing_beta`
- `electron_maxstep`: from `ConvergenceAdvice.electron_maxstep`

### Number formatting

- Floats: `{value:.10g}` — removes trailing zeros, keeps 10 significant digits
- Scientific: `{value:.10e}` — for `conv_thr`

## Error conditions

The generator raises `ValueError` if:

- `intent.code` is not `"quantum_espresso"` (only QE is implemented).
- `intent.task` is not `"scf_single_point"` (only SCF is implemented).
- The structure is disordered (`structure.is_ordered` is False). Disordered structures require manual resolution of occupancies.
- Any element lacks a pseudopotential selection (no `PseudopotentialSelection` for that element).
- Any pseudopotential selection has `filename=None` or missing cutoffs (`ecutwfc_ry` or `ecutrho_ry` is None). The generator will not invent values.

## What the generator does not do

- It does not choose k-point grids, pseudopotentials, cutoffs, smearing, spin, SOC, or convergence defaults. Those scientific/resource values come from advice and selection records.
- It does not resolve disordered occupancies.
- It does not write pseudopotential files.
- It does not run calculations.

## Multi-code boundary

Replacing this writer can change how the current completed QE selection is rendered. It cannot correctly add another DFT code because target validation, resource metadata/selection, target units/data, CLI choices, and generation must change together. The future boundary is documented in [target-code adapters](../target-code-adapters.md); no executable adapter API exists yet.

Issue #40's ASE rewrite belongs within the QE generation responsibility. It does not replace the QE UPF/SSSP selection boundary.
