# mMACE (magnetism ML)

Two features run on the mMACE backbone, a frozen magnetic MACE model:

| Feature | What it needs mMACE for |
| --- | --- |
| `is_magnetic` classification | Reads a frozen mMACE embedding to classify magnetic vs. non-magnetic (`human > ml > llm > heuristic`, see [Scientific controls](cli.md#scientific-controls)) |
| `goldilocks magnetic-orderings --rank-with-mmace` | Relaxes every candidate ordering's magnetic moments on a frozen mMACE potential energy surface and ranks them by energy per atom (see [Magnetic orderings](cli.md#magnetic-orderings)) |

Both work once the default assets are installed: the `is-magnetic-classifier` asset carries
the backbone (~80.5 MB) beside the classifier, and goldilocks-ml installs `mace-torch`,
`e3nn` and `sphericart` with `mace-torch[magnetic]`. Without the asset, both features
degrade to their next tier (LLM or heuristic for `is_magnetic`; an unranked candidate list
with a warning for `--rank-with-mmace`) rather than failing. Once it is installed, an
`is_magnetic` model that fails to run fails the request instead of answering from the
heuristic.

## 1. Install the model asset

Part of the `default` and `workbench` asset profiles:

```bash
uv run goldilocks assets install default
uv run goldilocks assets status models/is-magnetic-classifier
# models/is-magnetic-classifier@1: installed
```

The install downloads `model.json`, `is_magnetic.pt`, the model card and the backbone
`mmace-matpes-pbe-pretrained.model` from PSDI record
[`sgk1t-48m42`](https://data-collections.psdi.ac.uk/records/sgk1t-48m42) and checks each
file's SHA-256. An install from before #244 shows the asset as `corrupt` until this command
re-fetches it.

## 2. Verify it's actually being used

A structure loading successfully is not proof the `ml` tier is live — check the `source`
field explicitly. `Fe_bcc.cif` (bundled with this repo, and actually magnetic) makes a good
check:

```bash
STRUCTURE="$(uv run goldilocks examples path)/Fe_bcc.cif"
uv run goldilocks explain "$STRUCTURE" --json | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['records']['is_magnetic']['source'])"
# expect: ml   (not: heuristic, or llm)
```

Importing `mace` prints a UserWarning and a "cuequivariance ... will be disabled" line. Both
go to stderr, so they never reach the JSON on stdout.

For ordering ranking, a successful `--rank-with-mmace` run reports a `model_id` and real
per-candidate energies instead of degrading with a warning:

```bash
uv run goldilocks magnetic-orderings "$STRUCTURE" --rank-with-mmace --json
```

If `is_magnetic.source` still reads `heuristic`, check
`uv run goldilocks assets status models/is-magnetic-classifier` (step 1), then whether
`GOLDILOCKS_MACE_BACKBONE` is set in this shell (step 3): when it is, it replaces the
installed backbone.

## 3. Use a different checkpoint

`GOLDILOCKS_MACE_BACKBONE` overrides the installed backbone for both features:

```bash
export GOLDILOCKS_MACE_BACKBONE=/path/to/checkpoint.model
```

goldilocks-ml checks the backbone against the SHA-256 that the classifier's `model.json`
pins, so `is_magnetic` accepts only the file from record `sgk1t-48m42`: a different file
fails with `... has SHA-256 ...; its record pins fb43d7aa...`. Leave the variable unset to
use the installed backbone.

### Upgrading from the v1.0 checkpoint

Before #240, this guide installed a fork of `mace-torch` by hand, downloaded
`mace_matpes_pbe_baseline_run-3.model` from v1.0 of the record (`1g8rw-q8128`) and set
`GOLDILOCKS_MACE_BACKBONE` to it. That file no longer loads on `mace-torch` 0.3.17: unset the
variable (remove it from your shell profile too) and run
`uv run goldilocks assets install default`.

## 4. Use mMACE in the Workbench

Nothing to configure: start the Workbench as usual once the default (or `workbench`) assets
are installed.

```bash
uv run poe workbench   # dev mode: backend on :8000, Vite dev server on :5173
# or: uv run poe stage # production-like: one built bundle, served from :8000
```

Load a magnetic structure (e.g. `src/goldilocks_core/examples/structures/Fe_bcc.cif`) and
check the **Analysis** column's "is magnetic" field: once the `ml` tier is live, its caption
reads **"Goldilocks-ML prediction"**. A "Magnetic Orderings" column also appears
automatically once the run is spin-polarized, whether the classifier made it so, a Hubbard U
on an odd d or f count did, or a setting such as `spin_polarized` or `magnetic_ordering` did
(it stays hidden for a spin-unpolarized run) — this is where `--rank-with-mmace` lives in the
UI.

Clicking **Run mMACE** there ranks the candidates in a separate process, so editing a setting
while it runs is unaffected; a second ranking waits for the first to finish. Rankings take
minutes: rock-salt NiO's eight candidates take about two on a laptop CPU.
