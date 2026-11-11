# Workbench

The Workbench is Goldilocks in your browser. Load a structure, check and change
the recommended settings, and download the input files. It gives the same
results as the `goldilocks` command.

## Start it

With Docker:

```bash
docker run --rm --publish 127.0.0.1:8000:8000 ghcr.io/stfc/goldilocks-core
```

Or with pip, after `pip install "goldilocks-core[http]"` and
`goldilocks assets install all` (see [Install](install.md)):

```bash
goldilocks serve http
```

Then open **http://127.0.0.1:8000**.

## Set up a calculation

The page is a row of cards, worked from left to right:

1. **Structure Setup.** Drop a CIF or POSCAR on the card, or click
   **Browse files**. The card shows the structure and its atoms.
2. **Analysis.** What Goldilocks found in the structure: for example, whether
   it is a metal, whether it is magnetic, and whether it is a bulk crystal, a
   slab or a molecule. Each value says where it came from, such as a
   machine-learning model or a rule.
3. **Advisors.** Choose the task (SCF, relaxation, DOS, band structure or
   phonons), then check each recommended setting. Change any of them; your value
   replaces the recommendation, and the settings that depend on it update.
4. **Magnetic Orderings.** Appears only when the calculation is spin-polarised.
   See [Magnetism](#magnetism) below.
5. **Bundle.** The input files Goldilocks generated, and any warnings. Read the
   warnings, then click **Download (.zip)**.

The zip holds the same files as `goldilocks run --out`. To run them, see
[Run Quantum ESPRESSO](quickstart.md#4-run-quantum-espresso).

If Goldilocks cannot generate an input, for example because two settings
contradict each other, the Bundle card says why and suggests a change.

## Magnetism

Two features use mMACE, a machine-learning model of magnetic materials. Both are
installed with the default assets (see [mMACE](mmace-setup.md)).

- **Is it magnetic?** In the Analysis card, the "is magnetic" field reads
  **Goldilocks-ML prediction** when the model made the call.
- **Rank antiferromagnetic orderings.** The Magnetic Orderings card lists the
  candidate orderings. Click **Run mMACE** to rank them by energy, then choose
  one. A ranking can take from seconds to minutes, depending on the size of the
  cell. You can keep editing settings while it runs. If several people share
  one server, rankings wait their turn, and the card shows how many are ahead of
  yours. Loading another structure cancels the ranking.

Structures with more than 200 atoms skip both features; see
[Structure size limit](mmace-setup.md#5-structure-size-limit).

## Share it with others

The Workbench listens only on your own machine (127.0.0.1) by default. Read
[HTTP security](cli.md#http-security) before making it reachable from other
machines.

## Problems

- **The page does not load, or shows "Cannot reach Core":** the server has
  stopped. Check its terminal, start it again, and open
  `http://127.0.0.1:8000`.
- **"Runtime assets unavailable":** the models or pseudopotential tables are
  not installed. Run `goldilocks assets install all` and restart the server.
- **Port 8000 is already in use:** start it on another port, for example
  `goldilocks serve http --port 8001`, or publish Docker on another port with
  `--publish 127.0.0.1:8001:8000`, and open that port instead.
