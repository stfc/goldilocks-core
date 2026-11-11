# goldilocks-core

Give Goldilocks a crystal structure and it sets up a Quantum ESPRESSO
calculation for you. It chooses the settings a DFT calculation needs, tells you
why it chose each one, and writes input files that are ready to run.

- **In:** a CIF or POSCAR file.
- **Out:** a folder with the input files, the pseudopotentials, a SLURM
  submission script, and a record of every setting and the reason for it.

It sets up single-point SCF, density of states, band structure, relaxation,
variable-cell relaxation, and phonons with their density of states and
dispersion, at the written geometry or after either relaxation.

Treat the recommended settings as a starting point: review the warnings and
check convergence for your calculation.

## Start here

- [Install](install.md): Docker, pip, or pip with the browser interface.
- [First calculation](quickstart.md): generate, check and run an input on the
  command line.
- [Workbench](workbench.md): do the same in your browser.

## Guides and reference

- [Python API](tutorial.md): use Goldilocks in a script.
- [Recommendations](science.md): how each setting is chosen, and its limits.
- [Pseudopotentials](pseudopotentials.md): choose a table, or use your own
  files.
- [CLI reference](cli.md): commands and options.
- [mMACE](mmace-setup.md): the magnetic machine-learning model, its size limit,
  and running it on a GPU.
- [Scientific conventions](conventions.md): units and numerical definitions.
- [Contributing](architecture.md): code layout and development checks.

The source code is on [GitHub](https://github.com/stfc/goldilocks-core).
