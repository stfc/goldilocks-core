# use-goldilocks Evals

## eval-1: numbers only, manual input

Prompt: There are CIFs in a folder. Pick one, use Goldilocks to get the DFT numbers, but write the Quantum ESPRESSO SCF input yourself rather than using generation.

Why it matters: Exercises the main distinction between `recommend` and `generate`/`bundle`.

Expected behavior:

- Load `use-goldilocks` and `use-uv`.
- Inspect candidate CIFs with pymatgen.
- Use `recommend(...)` with pseudo metadata to get k-grid, pseudos, cutoffs, smearing, convergence.
- Write QE input manually from selected records.
- Report warnings and output paths.

## eval-2: bundle directly from CLI

Prompt: Generate a portable SCF input bundle for this CIF using the pseudos in ./pseudos and a k-spacing of 0.2.

Why it matters: Exercises the fastest ordinary CLI path.

Expected behavior:

- Use `uv run goldilocks-core bundle ...`.
- Avoid reading source unless command fails.
- Report bundle layout, key selected values, and warnings.

## eval-3: pseudo metadata lacks cutoffs

Prompt: Goldilocks can parse my UPFs but generation fails with incomplete pseudo and cutoff selections. What should I do?

Why it matters: Captures a frequent gotcha.

Expected behavior:

- Explain that generators do not invent cutoffs.
- Inspect parsed metadata.
- Recommend using trusted pseudo-library cutoff tables or operator policy.
- Preserve provenance; do not silently fabricate numbers.

## eval-4: changing physics policy

Prompt: Make Goldilocks automatically enable SOC for heavy elements.

Why it matters: Ensures this operational skill delegates physics decisions.

Expected behavior:

- Load `dft-basics` before changing policy.
- Note current principle: heavy elements trigger SOC consideration, not automatic enablement.
- If implementing, use project workflow and tests.
