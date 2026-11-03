# Set up mMACE (magnetism ML)

Two features share one setup step, on top of the default install: downloading the mMACE
backbone checkpoint.

| Feature | What it needs mMACE for |
| --- | --- |
| `is_magnetic` classification | Reads a frozen mMACE embedding to classify magnetic vs. non-magnetic (`human > ml > llm > heuristic`, see [Scientific controls](cli.md#scientific-controls)) |
| `goldilocks magnetic-orderings --rank-with-mmace` | Relaxes every candidate ordering's magnetic moments on a frozen mMACE potential energy surface and ranks them by energy per atom (see [Magnetic orderings](cli.md#magnetic-orderings)) |

`mace-torch`, `e3nn` and `sphericart` need no setup: goldilocks-ml installs them with
`mace-torch[magnetic]` as part of the default install. Without the checkpoint, both
features degrade to their next tier (LLM or heuristic for `is_magnetic`; an unranked
candidate list with a warning for `--rank-with-mmace`) rather than failing. Once it is set
up, an `is_magnetic` model that fails to run fails the request instead of answering from
the heuristic.

## 1. Install the model asset

Already part of the `default` and `workbench` asset profiles — most installs already have it:

```bash
uv run goldilocks assets install default
uv run goldilocks assets status models/is-magnetic-classifier
# models/is-magnetic-classifier@1: installed
```

This alone is **not** enough to reach the `ml` tier — steps 2 and 3 are the actual gate.

## 2. Download the mMACE backbone checkpoint

The published `is-magnetic-classifier` asset record bundles this checkpoint file, but
`goldilocks assets install` deliberately does not download it — see the comment on
`defaults.is_magnetic` in `src/goldilocks_core/ml/registry.toml` for why. Fetch it directly:

```bash
mkdir -p ~/.local/share/goldilocks/mmace
curl -L -o ~/.local/share/goldilocks/mmace/mmace-matpes-pbe-pretrained.model \
  https://data-collections.psdi.ac.uk/api/records/sgk1t-48m42/files/mmace-matpes-pbe-pretrained.model/content
```

The `-L` is not optional: this URL 302-redirects to a presigned, short-lived S3 link.
Without it, `curl` saves the ~500-byte redirect response itself (a plain-text URL) instead
of the model — a mistake that succeeds silently and only surfaces at the checksum step
below.

~80.5 MB (84,437,213 bytes). Verify the download:

```bash
shasum -a 256 ~/.local/share/goldilocks/mmace/mmace-matpes-pbe-pretrained.model
# expect: fb43d7aadc63cbfbd00550a17e109553b6c051d6d6f4ab6ebd741849d92dc8bf
```

goldilocks-ml checks the same SHA-256, pinned in the classifier's `model.json`, before it
loads the file, and refuses a file that differs.

The path above is a suggestion, not a requirement — `goldilocks-core` never manages this
file, it only reads whatever path you point it at in step 3.

## 3. Point `GOLDILOCKS_MACE_BACKBONE` at it

Both features read the same environment variable — set it once, before running either:

```bash
export GOLDILOCKS_MACE_BACKBONE=~/.local/share/goldilocks/mmace/mmace-matpes-pbe-pretrained.model
```

Add that line to your shell profile (or `.env` / the launcher you use to start
`goldilocks serve http` for the Workbench) so it's set for every session, not just the
current shell.

## 4. Verify it's actually being used

A structure loading successfully is not proof the `ml` tier is live — check the `source`
field explicitly:

`Fe_bcc.cif` (bundled with this repo, and actually magnetic) makes a good check:

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

If `is_magnetic.source` still reads `heuristic` after all three steps, check in this order:
`uv run goldilocks assets status models/is-magnetic-classifier` (step 1),
`echo $GOLDILOCKS_MACE_BACKBONE` (set in *this* shell, and pointing at a file that exists),
then `ls -la` the checkpoint — a file around 500 bytes instead of ~80.5 MB means step 2's
`-L` got dropped and you saved the redirect's own presigned-URL text instead of the model
(`cat` it to confirm: it reads as a `https://s3...` URL, not binary). Re-run the `curl -L`
command.

A command that fails with `... has SHA-256 ...; its record pins fb43d7aa...` was given a
different checkpoint, such as the v1.0 one below or a damaged download: replace it with the
file from step 2.

### Upgrading from the v1.0 checkpoint

Before goldilocks-core moved to goldilocks-ml 0.3.2 (#240), this guide installed a fork of
`mace-torch` by hand and downloaded `mace_matpes_pbe_baseline_run-3.model` from v1.0 of the
record (`1g8rw-q8128`). That file no longer loads on `mace-torch` 0.3.17. Download the v2.0
file from step 2, which holds the same weights re-exported for upstream `mace-torch`, and
point `GOLDILOCKS_MACE_BACKBONE` at it. Run `uv run goldilocks assets install default` too:
the classifier's `model.json` moved to v2.0 of the record with it.

## 5. Start the Workbench with mMACE enabled

`GOLDILOCKS_MACE_BACKBONE` has to be set in the shell that launches the **backend** process
— set it before running the usual startup command, not after:

```bash
export GOLDILOCKS_MACE_BACKBONE=~/.local/share/goldilocks/mmace/mmace-matpes-pbe-pretrained.model
uv run poe workbench   # dev mode: backend on :8000, Vite dev server on :5173
# or: uv run poe stage # production-like: one built bundle, served from :8000
```

If the backend is already running from an earlier session, the variable won't retroactively
apply — stop it and restart from a shell that has the export.

Load a magnetic structure (e.g. `src/goldilocks_core/examples/structures/Fe_bcc.cif`) and
check the **Analysis** column's "is magnetic" field: once the `ml` tier is live, its caption
switches from "Heuristic default" to **"Goldilocks-ML prediction"**. A "Magnetic Orderings"
column also appears automatically once the run is spin-polarized, whether the classifier made
it so, a Hubbard U on an odd d or f count did, or a setting such as `spin_polarized` or
`magnetic_ordering` did (it stays hidden for a spin-unpolarized run) — this is where
`--rank-with-mmace` lives in the UI.

Clicking **Run mMACE** there ranks the candidates in a separate process, so editing a setting
while it runs is unaffected; a second ranking waits for the first to finish. Rankings take
minutes: rock-salt NiO's eight candidates take about two on a laptop CPU.
