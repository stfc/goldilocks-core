# Example structures

Three CIF files are included for trying Goldilocks:

| File         | Structure                   |
| ------------ | --------------------------- |
| `Si.cif`     | Diamond silicon             |
| `Fe_bcc.cif` | Body-centred cubic iron     |
| `Pt_fcc.cif` | Face-centred cubic platinum |

After installing the default assets, run this from the repository root:

```bash
uv run goldilocks compute src/goldilocks_core/examples/structures/Si.cif --preset generate --out si-run
```

In Python, `structure()` returns the path to a bundled file:

```python
from goldilocks_core.examples.structures import structure

silicon_path = structure("Si.cif")
```

These are example structures, not converged calculation results.
