# goldilocks-core

Give Goldilocks a crystal structure and it sets up a Quantum ESPRESSO
calculation for you. It chooses the settings a DFT calculation needs, tells you
why it chose each one, and writes input files that are ready to run.

- **In:** a CIF or POSCAR file.
- **Out:** a folder with the Quantum ESPRESSO input files, the
  pseudopotentials, a SLURM submission script, and a record of every setting
  and the reason for it.

Documentation: https://stfc.github.io/goldilocks-core/

## What it decides for you

| Setting | How Goldilocks chooses it |
| --- | --- |
| k-point grid | A machine-learning model that predicts the k-point spacing your structure needs |
| Metal or insulator, and smearing | A machine-learning classifier |
| Spin polarisation | A machine-learning classifier |
| Antiferromagnetic ordering | Off by default. Goldilocks lists the candidate orderings and can rank them with a magnetic ML potential; you choose one |
| Pseudopotentials and energy cutoffs | A pseudopotential table for the functional: PseudoDojo PBEsol by default, with PBE, LDA and SSSP tables available |
| Hubbard U, van der Waals correction, vacuum and 2D handling | Published rules (Materials Project and the literature), applied to your structure |
| Cluster resources (nodes, MPI tasks, k-point pools) | Estimated from the size of the calculation |

Anything you set yourself overrides the recommendation.

It can set up these calculations:

| Task | What runs |
| --- | --- |
| `scf_single_point` (default) | One self-consistent calculation |
| `relax`, `vc-relax` | Relax the atoms, or the atoms and the cell |
| `dos` | SCF, then a denser non-self-consistent run and `dos.x` |
| `band` | SCF, then the band structure along a high-symmetry path |
| `phonon`, `relax-phonon`, `vc-relax-phonon` | Phonons (`ph.x`), their density of states and dispersion, optionally after a relaxation |

## Get started

Choose one of three ways. The Docker image already contains the models and
pseudopotential tables; the other two download them once, which needs an
internet connection.

### 1. In your browser, with Docker

Nothing to install except [Docker](https://docs.docker.com/get-docker/):

```bash
docker run --rm --publish 127.0.0.1:8000:8000 ghcr.io/stfc/goldilocks-core
```

Open **http://127.0.0.1:8000**. Upload a CIF or POSCAR, pick a task, check the
settings, and download the input files. The [Workbench guide](docs/workbench.md)
walks through the page.

The image is built for x86-64; on Apple silicon Docker runs it more slowly,
under emulation. To keep a fixed version, add it as the tag,
`ghcr.io/stfc/goldilocks-core:<version>`, with a version from the
[releases page](https://github.com/stfc/goldilocks-core/releases).

### 2. On the command line

Needs Python 3.12 or newer on Linux or macOS:

```bash
pip install goldilocks-core
goldilocks assets install default
```

Try it on the silicon structure that comes with Goldilocks:

```bash
goldilocks run "$(goldilocks examples path)/Si.cif" --out si-run
```

Then use your own structure:

```bash
goldilocks run my_structure.cif --out my-run
```

On Linux, `pip` installs the CUDA build of PyTorch, which is several GB. If
you have no GPU, add `--extra-index-url https://download.pytorch.org/whl/cpu`
to `pip install` for the much smaller CPU build.

### 3. In your browser, without Docker

```bash
pip install "goldilocks-core[http]"
goldilocks assets install all
goldilocks serve http
```

Open **http://127.0.0.1:8000**. `all` installs every pseudopotential table, so
you can switch functional in the browser. [Install](docs/install.md) has more on
the models and tables, updating, and smaller installs.

## Common commands

| You want to | Command |
| --- | --- |
| See what Goldilocks would choose, and why, without writing files | `goldilocks explain my_structure.cif` |
| Set up a different calculation | `goldilocks run my_structure.cif --task band --out my-bands` |
| Choose a setting yourself | `goldilocks run my_structure.cif --set 'k_grid=[6,6,6]' --out my-run` |
| List every setting you can choose | `goldilocks settings` |
| Check the structure Goldilocks read | `goldilocks inspect my_structure.cif` |
| List candidate magnetic orderings, ranked by energy | `goldilocks magnetic-orderings my_structure.cif --rank-with-mmace` |

Each `--out` folder must be new; Goldilocks never overwrites one. The
[CLI reference](docs/cli.md) lists every option.

## What you get

```text
si-run/
├── scf.in            Quantum ESPRESSO input (one file per step for multi-step tasks)
├── pseudo/           the pseudopotential files
├── licences/         the pseudopotential table's licence
├── submit.sh         SLURM script that runs every step and checks each one finished
├── goldilocks.json   every setting, where it came from, and any warnings
├── README.md         how to run this folder on a cluster
└── CITATIONS.md      what to cite: the pseudopotentials and each model used
```

## Run the calculation

On your own machine, with Quantum ESPRESSO installed, run it from inside the
folder:

```bash
cd si-run
pw.x -in scf.in > scf.out
```

On a cluster, copy the folder there and submit the script from inside it:

```bash
cd si-run
sbatch submit.sh
```

`submit.sh` is written for STFC's SCARF cluster, the only cluster Goldilocks
knows today. On another SLURM cluster, edit the `#SBATCH` lines and the
`module load` line before you submit. Two settings are worth giving when you
generate the folder:

- `--set walltime_h=12`: the job otherwise asks for the longest time the queue
  allows.
- `--set account=<your project code>`, if your cluster needs one.

## Before you trust the numbers

The settings are a well-informed starting point, not a converged result.

- Read the warnings that `goldilocks run` prints. They are also in
  `goldilocks.json`.
- Check convergence of the k-point grid and cutoffs for the property you need.
- Goldilocks writes inputs for Quantum ESPRESSO only.

[Recommendations](docs/science.md) explains how each setting is chosen and
where the choice is weak.

## Other ways to use it

- **Python:** call the same steps from a script. See the
  [Python API](docs/tutorial.md).
- **AI assistants:** `pip install "goldilocks-core[mcp]"`, then
  `goldilocks serve mcp` runs Goldilocks as an MCP server. See
  [Serve local MCP](docs/cli.md#serve-local-mcp).
- **Shared server:** read [HTTP security](docs/cli.md#http-security) before
  making the browser interface reachable from other machines.

## Documentation

- [Install](docs/install.md): every way to install, the models and tables, and
  updating.
- [First calculation](docs/quickstart.md): generate, check and run an input,
  step by step.
- [Workbench](docs/workbench.md): the browser interface.
- [Recommendations](docs/science.md): how each setting is chosen, and its
  limits.
- [Pseudopotentials](docs/pseudopotentials.md): choose a table, or use your own
  files.
- [Magnetism (mMACE)](docs/mmace-setup.md): the magnetic machine-learning
  model, its size limit, and running it on a GPU.
- [CLI reference](docs/cli.md) and [Python API](docs/tutorial.md).
- [Scientific conventions](docs/conventions.md): units and definitions.

## Contributing

To work on Goldilocks itself, see [Contributing](docs/architecture.md) for the
development setup, and the [Workbench development guide](web/README.md) for
the browser interface.

## Licence

Code: [BSD 3-Clause](LICENSE). Documentation under `docs/` and the example
structures: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Downloaded pseudopotentials keep their
[upstream licences](docs/pseudopotentials.md#licences-and-citations).
