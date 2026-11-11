# Install

There are three ways to run Goldilocks. All of them give the same
recommendations and write the same input files.

| Way | You need | You get |
| --- | --- | --- |
| [Docker](#docker) | Docker | The browser interface (Workbench) |
| [pip](#pip) | Python 3.12 or newer, on Linux or macOS | The `goldilocks` command and the Python library |
| [pip with the browser interface](#pip-with-the-browser-interface) | The same | The command, the library and the Workbench |

On Windows, use Docker, or pip inside WSL.

## Docker

```bash
docker run --rm --publish 127.0.0.1:8000:8000 ghcr.io/stfc/goldilocks-core
```

Open **http://127.0.0.1:8000** and follow the [Workbench guide](workbench.md).
Stop it with Ctrl+C.

The image already contains the models and pseudopotential tables, so there is
nothing else to install. It is built for x86-64; on Apple silicon, Docker runs
it more slowly, under emulation.

To keep a fixed version, add it as the tag, for example
`ghcr.io/stfc/goldilocks-core:<version>`. The versions are listed on the
[releases page](https://github.com/stfc/goldilocks-core/releases).

## pip

```bash
pip install goldilocks-core
goldilocks assets install default
```

The second command downloads the models and the default pseudopotential table
(see [Models and pseudopotential tables](#models-and-pseudopotential-tables)).
It needs an internet connection once.

Check that it works on the silicon structure that comes with Goldilocks:

```bash
goldilocks run "$(goldilocks examples path)/Si.cif" --out si-run
```

Then continue with [First calculation](quickstart.md).

### Smaller install without a GPU

On Linux, `pip` installs the CUDA build of PyTorch, which is several GB.
Goldilocks needs a GPU only if you choose to run the magnetic model on one
(see [mMACE](mmace-setup.md#6-run-mmace-on-a-gpu)). Without a GPU, install the
much smaller CPU build:

```bash
pip install goldilocks-core --extra-index-url https://download.pytorch.org/whl/cpu
```

## pip with the browser interface

```bash
pip install "goldilocks-core[http]"
goldilocks assets install all
goldilocks serve http
```

Open **http://127.0.0.1:8000** and follow the [Workbench guide](workbench.md).
`all` installs every pseudopotential table, so you can switch functional in the
browser.

## Models and pseudopotential tables

Goldilocks downloads its models and pseudopotential tables separately from the
package, and checks each file's SHA-256.

| Profile | Contents |
| --- | --- |
| `default` | The k-point model, the metal/insulator classifiers, the magnetic classifier with the mMACE model (about 80 MB), and the PseudoDojo PBEsol efficiency table |
| `all` | Every model and every pseudopotential table: PseudoDojo (PBE, PBEsol and LDA; efficiency and precision; lanthanides; fully relativistic for spin-orbit coupling) and SSSP (PBE and PBEsol) |

```bash
goldilocks assets install default    # or: all, or one table by its id
goldilocks assets status default     # what is installed
goldilocks assets verify default     # re-check every file
```

Installing again downloads only what is missing. If a calculation needs a table
that is not installed, `goldilocks run` stops and names it; add
`--fetch-missing` to let it install the table instead. See
[Pseudopotentials](pseudopotentials.md) to choose a table.

The assets are stored in `~/.local/share/goldilocks/assets`, or in
`$XDG_DATA_HOME/goldilocks/assets` if that variable is set. Set
`GOLDILOCKS_ASSET_ROOT` to keep them somewhere else, such as a shared directory
on a cluster.

## Use it from an AI assistant

Goldilocks can run as a local MCP server, so an assistant that supports MCP can
inspect structures and generate inputs:

```bash
pip install "goldilocks-core[mcp]"
goldilocks serve mcp
```

See [Serve local MCP](cli.md#serve-local-mcp).

## Update

```bash
pip install --upgrade goldilocks-core
goldilocks assets install default
```

A new version can need new models or tables; the second command fetches only
those. For Docker, run `docker pull ghcr.io/stfc/goldilocks-core`.

## From a source checkout

To work on Goldilocks itself, see [Contributing](architecture.md) and the
[Workbench development guide](https://github.com/stfc/goldilocks-core/blob/main/web/README.md).
In a checkout, put `uv run` in front of each `goldilocks` command in these
pages.
