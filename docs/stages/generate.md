# Generate stage

Owner: `generation.py`

The Generate stage translates completed advice and selection records into target-code input syntax. It is purely mechanical: every value in the output comes from a record, not from generator-side defaults.

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
| `&CONTROL` | hardcoded: `calculation='scf'`, `pseudo_dir='./pseudo'`, `tprnfor=.true.`, `tstress=.true.` |
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

- It does not choose k-point grids, pseudopotentials, cutoffs, smearing, spin, SOC, or convergence defaults. All values come from the advice and selection records.
- It does not resolve disordered occupancies.
- It does not write pseudopotential files.
- It does not run calculations.