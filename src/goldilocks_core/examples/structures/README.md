# Example structures

Small, conventional crystal structures used by the documentation and the
integration tests. They ship with the package, so `goldilocks-core` can be run
end to end straight after `pip install`:

```bash
goldilocks-core recommend "$(goldilocks-core examples path)/Si.cif"
```

From Python:

```python
from goldilocks_core.examples import structure

result = recommend(structure("Si.cif"))
```

## Why these three

Each structure is here to exercise a different branch of the Advise stage, so
that comparing their outputs shows which advisors actually make decisions.

| File | System | Advice it reaches |
| --- | --- | --- |
| `Si.cif` | diamond Si, a = 5.431 Å | The baseline: non-magnetic, no heavy elements, no SOC, fixed occupations. |
| `Fe_bcc.cif` | bcc Fe, a = 2.867 Å | Magnetic metal — spin polarisation and cold smearing. |
| `Pt_fcc.cif` | fcc Pt, a = 3.924 Å | The only heavy element, and the only one that reaches spin-orbit coupling advice. |

`tests/integration/test_example_structures.py` asserts exactly these
differences, so this table cannot drift away from what the advisors do.

Lattice parameters are conventional experimental room-temperature values. These
are inputs for parameter recommendation, not reference data — nothing here is
a converged calculation or a benchmark result.

## Reproducing them

Each file is generated from a pymatgen spacegroup constructor, so it is fully
determined by the values in the table above:

| File | Spacegroup | Wyckoff origin |
| --- | --- | --- |
| `Si.cif` | `Fd-3m` | `Si` at `(0, 0, 0)` |
| `Fe_bcc.cif` | `Im-3m` | `Fe` at `(0, 0, 0)` |
| `Pt_fcc.cif` | `Fm-3m` | `Pt` at `(0, 0, 0)` |

```python
from pymatgen.core import Lattice, Structure

Structure.from_spacegroup("Fd-3m", Lattice.cubic(5.431), ["Si"], [[0, 0, 0]])
```

## Adding a structure

Keep them small and keep the reason explicit — a structure earns its place by
exercising a code path the others do not. Add a row to both tables above, and
remember that these files are installed with the package, so they are part of
the distribution size.
