# goldilocks-core

Goldilocks recommends settings for density functional theory (DFT) calculations
and generates Quantum ESPRESSO input files from a crystal structure — single-point
SCF, density of states, band structure, relaxation, variable-cell
relaxation, and phonons with their density of states and dispersion, at the
written geometry or after either relaxation.

Treat the recommended settings as a starting point: review warnings and check
convergence for your calculation.

## Guides and reference

- [First calculation](quickstart.md) — generate, check, and run an input.
- [Python API](tutorial.md) — use Goldilocks in a script.
- [Recommendations](science.md) — understand the choices and their limits.
- [Pseudopotentials](pseudopotentials.md) — choose a table and understand
  automatic selection.
- [CLI reference](cli.md) — commands and options.
- [Scientific conventions](conventions.md) — units and numerical definitions.
- [Contributing](architecture.md) — code layout and development checks.

See the [repository README](https://github.com/stfc/goldilocks-core) for
installation and the interactive Workbench.
