# Roadmap

What is planned, and when. [`changelog.md`](changelog.md) is the same information looking backwards.

This file is an index. Scope, design and trade-offs live in the issues it links to — when the two disagree, the issue is right.

Goldilocks ships as three coordinated repositories: [`goldilocks-core`](https://github.com/stfc/goldilocks-core) (this one), [`goldilocks-data`](https://github.com/stfc/goldilocks-data) and [`goldilocks-ml`](https://github.com/stfc/goldilocks-ml). A release is all three at the same version, and each repository carries the same milestone titles and dates.

## Releases

| Release | Due | Core adds |
| --- | --- | --- |
| [v0.1](https://github.com/stfc/goldilocks-core/milestone/5) | 2026-09-30 | SCF for bulk systems: k-point prediction, pseudopotential recommendation, XC selection, cutoffs, QE input generation, CLI, GUI prototype, agent-assisted mode |
| [v0.2](https://github.com/stfc/goldilocks-core/milestone/6) | 2026-10-31 | Bulk supercells |
| [v0.3](https://github.com/stfc/goldilocks-core/milestone/7) | 2026-11-30 | Magnetic SCF |
| [v0.4](https://github.com/stfc/goldilocks-core/milestone/8) | 2026-12-31 | Molecular systems |
| [Workshop](https://github.com/stfc/goldilocks-core/milestone/17) | 2027-01-31 | Not a release — target-user workshop, feedback, and the v1.0 plan |
| [v0.5](https://github.com/stfc/goldilocks-core/milestone/9) | 2027-02-28 | Slabs and DFT+U |
| [v1.0](https://github.com/stfc/goldilocks-core/milestone/10) | 2027-03-31 | Consolidation: all of the above, wizard-style CLI, initial web interface |
| [v1.1](https://github.com/stfc/goldilocks-core/milestone/11) | 2027-04-30 | NSCF |
| [v1.2](https://github.com/stfc/goldilocks-core/milestone/12) | 2027-05-31 | Phonons |
| [v1.3](https://github.com/stfc/goldilocks-core/milestone/13) | 2027-06-30 | AiiDA integration |
| [v1.4](https://github.com/stfc/goldilocks-core/milestone/14) | 2027-07-31 | Post-processing and results analysis |
| [v1.5](https://github.com/stfc/goldilocks-core/milestone/15) | 2027-08-31 | VASP transfer learning |
| [v2.0](https://github.com/stfc/goldilocks-core/milestone/16) | 2027-09-30 | Consolidation: SCF, NSCF and phonons, AiiDA, post-processing, VASP |

`goldilocks-data` supplies the matching sub-dataset for each release and `goldilocks-ml` the matching models; see their milestone lists.

## Work streams

A release answers *when*. These answer *what line of work*, and they cut across releases — which is why they are umbrella issues rather than milestones.

| Stream | Label | Spans |
| --- | --- | --- |
| [M1 — Zero-config pseudopotential & artifact pipeline](https://github.com/stfc/goldilocks-core/issues/112) | `epic:m1` | v0.1 |
| [M2 — Deepen the staged Core pipeline](https://github.com/stfc/goldilocks-core/issues/113) | `epic:m2` | v0.1 → v0.3 → v1.2 |
| [M3 — Server transports (HTTP + MCP)](https://github.com/stfc/goldilocks-core/issues/114) | `epic:m3` | v0.1 |
| [M4 — Agent process & repo hygiene](https://github.com/stfc/goldilocks-core/issues/115) | `epic:m4` | continuous |

M2 is the one that cannot sit in a single release: the ML-facts work it contains gates metallicity classification in v0.1, real magnetization in v0.3, and phonons in v1.2.

Cross-repository tracking lives on the [`data-to-knowledge`](https://github.com/orgs/stfc/projects/17) programme board, alongside `janus-core`, `aiida-mlip` and `dtk`.

## Current focus — v0.1

Nothing ships inside the wheel. Every pseudopotential table and ML model is declared in a registry and fetched on first use from [PSDI Data Collections](https://data-collections.psdi.ac.uk), into a cache the user owns. Most of v0.1 is building that path and making what it fetches honest about coverage, cutoffs and licences.

Three strands run in parallel, because their bottlenecks differ:

- **Artifact resolution** — the user-owned cache (#119), then PSDI resolution (#105), then the pre-fetch CLI (#107).
- **Deposition** — #120. Operational rather than code, and the long pole: publishing ends in a community review whose timing we do not control.
- **Pseudopotential correctness** — cutoff sidecars (#95, #96), then the registry (#97), then honest coverage reporting (#98, #99).

The sidecars gate the table deposit: PseudoDojo UPF files carry no recommended cutoff, so a table published without one downloads successfully and then fails at generation.

## Open questions

- **DOIs.** The move to PSDI was argued partly on citability, but no sampled record carries a DOI — only `oai` PIDs. Whether minting is unavailable, disabled, or requested per deposit is unconfirmed (#120).
- **Third-party artifacts.** What may be mirrored onto PSDI, and under what terms, when the artifact is someone else's (#121).
- **`goldilocks-data` visibility.** Currently private while `goldilocks-core` is public. If a `goldilocks-data v0.1` is part of the release, this has to be settled before 2026-09-30.
