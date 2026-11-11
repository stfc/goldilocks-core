# First calculation

Generate a Quantum ESPRESSO SCF input for silicon, check the result, and run it.
For Python, see the [Python guide](tutorial.md).

Already generated `si-run` from the README? Continue with
[checking the settings](#3-check-the-settings).

## 1. Install

Install Goldilocks with pip (see [Install](install.md) for the other ways), then
download and check the models and the default pseudopotential table:

```bash
pip install goldilocks-core
goldilocks assets install default
goldilocks assets verify default
```

This downloads and checks the k-point model, the metallicity classifier, the
is-metal and is-magnetic classifiers, and the PseudoDojo PBEsol efficiency
pseudopotential table. The first installation needs an internet connection.

## 2. Generate an input

```bash
goldilocks run "$(goldilocks examples path)/Si.cif" --out si-run
```

Replace the bundled silicon path with your own CIF or POSCAR when you are ready.
Choose a new output directory each time; Goldilocks will not overwrite an
existing one.

Goldilocks knows one cluster, STFC's SCARF (the `scarf` HPC profile), so
`submit.sh` is written for it and `--hpc` can be left out. On another SLURM
cluster, see [step 4](#4-run-quantum-espresso).

The main files in `si-run/` are:

| Path                         | Contents                                                                                        |
| ---------------------------- | ------------------------------------------------------------------------------------------------ |
| `scf.in`                     | Quantum ESPRESSO input, named after the task (`relax.in`, `vc-relax.in`, `scf.in`+`nscf.in`+`dos.in` for `--task dos`, `scf.in`+`bands.in`+`bands_x.in` for `--task band`, with `bands_x_up.in`+`bands_x_down.in` in place of `bands_x.in` for a collinear spin-polarized run, or, for the phonon tasks, `scf.in`, `relax.in` or `vc-relax.in`, then `ph.in`+`q2r.in`+`phonon_dos.in`+`dispersion.in`, with `d3hess.in` before `ph.in` under DFT-D3) |
| `pseudo/`                    | The selected UPF pseudopotential file(s)                                                         |
| `licences/`                  | The pseudopotential table's licence file, shipped with its UPFs                                 |
| `submit.sh`                  | Generated SLURM submission script for the chosen `--hpc` profile; a phonon task's also runs a job timer and resumes from a later step (see [phonon jobs](cli.md#submit-and-resume-a-phonon-job)) |
| `goldilocks.json`            | The request (code, task, HPC profile, overrides as given, structure sha256, goldilocks-core version), the steps in run order with their input files, every setting with its provenance (including the model behind each ML-chosen record), and file hashes |
| `README.md`, `CITATIONS.md`  | What `goldilocks.json` holds, the bundle contents and how to run it on the cluster (copy, unpack, check, submit, follow, resume); what to cite: the pseudopotential table, every model used, the path table of a `band` task or a phonon task's dispersion, a phonon task's protocols and DFPT reference, and the licence files |

## 3. Check the settings

Read any warnings printed by the command and open `si-run/scf.in`. Check
the k-point grid, energy cutoffs, occupations, and spin settings against what
you know about your material.

Model predictions and table cutoffs are starting points, not convergence tests.
See [Recommendations](science.md) for how each choice is made and
[Scientific conventions](conventions.md) for units.

To choose a grid yourself, generate a second input with `--set k_grid=...`:

```bash
goldilocks run "$(goldilocks examples path)/Si.cif" --set 'k_grid=[4,4,4]' --out si-grid-4
```

The value must be a valid JSON array (`--set k_grid=4,4,4` fails with a JSON
parse error), and quoting the whole `key=value` pair keeps the shell from
trying to glob-expand the brackets. The `4 × 4 × 4` grid demonstrates an
override; it is not a converged value for silicon. Run
`goldilocks settings` to see every other `--set`-able key, or see the
[CLI reference](cli.md#scientific-controls).

## 4. Run Quantum ESPRESSO

With Quantum ESPRESSO installed, run `pw.x` **from inside the output directory**
so it can find `./pseudo`:

```bash
cd si-run
pw.x -in scf.in > scf.out
```

Review `scf.out` to check that the SCF calculation converged. On an HPC
cluster, submit the generated `submit.sh` instead — it already runs `pw.x`
with the right MPI/OpenMP layout for the `--hpc` profile you chose, and it
stops with a `goldilocks:` message on stderr unless every step finished
(`pw.x` must record `exit_status` 0, and a phonon task's `ph.x` must write
every dynamical matrix), so an SCF that did not converge fails the job.

Two settings are worth giving when you generate a bundle for a cluster:

- `--set walltime_h=12` (or what the run needs): otherwise the job asks for the
  longest time the partition allows, 168 h on SCARF, and queues slowly.
- `--set account=<your project code>`, if the cluster needs one. Goldilocks
  never guesses it.

`submit.sh` is written for SCARF, the only cluster Goldilocks knows. On another
SLURM cluster, edit its `#SBATCH` lines (partition, nodes, tasks) and its
`module load` line to match that cluster before you submit.

## Next

- [Python API](tutorial.md) — inspect structures and generate inputs in a
  script.
- [Pseudopotentials](pseudopotentials.md) — change the functional or
  pseudopotential table.
- [Workbench](workbench.md) — prepare and review inputs in a browser.
