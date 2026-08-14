# Iteration 1 Notes

Created from the session where Goldilocks was used two ways:

1. direct `write_bundle(...)` path to create a QE SCF bundle;
2. recommendation/selection-only path, followed by manually writing `qe.in`.

No spawned-agent comparison was available in this Pi session, so validation was by prompt coverage against `evals.md`:

- eval-1 is covered by `SKILL.md` mental model plus `references/workflows.md` numbers-only workflow and manual QE checklist.
- eval-2 is covered by CLI bundle examples.
- eval-3 is covered by the UPF metadata and cutoff gotcha.
- eval-4 is covered by pairing with `dft-basics` for physics-bearing policy changes.

Likely future improvement: add a small helper script that extracts selected values to JSON from `recommend(...)` if this workflow repeats often.
