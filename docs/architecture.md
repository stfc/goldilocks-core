# Architecture

## Overview

`goldilocks-core` is a research-grade Python package for recommending and organizing DFT calculation inputs from crystal structures, parsed pseudopotentials, and machine-learning models.

The package is being organized around domain-focused modules rather than generic utility buckets. The goal is to keep scientific parsing, physical metadata extraction, model inference, recommendation policy, and user-facing interfaces clearly separated.

At the current stage, the package has three main vertical slices:

- k-mesh recommendation from structure-aware logic and ML-predicted `k_index`
- pseudopotential parsing and local registry construction from UPF files
- staged Core recommendation records for Load → Analyse → Advise → Select

These slices are designed to remain composable so recommendation workflows can combine structure, task, code, k-mesh policy, provenance, and pseudopotential choice in a clean way.

## Design Principles

- Prefer domain-oriented modules over generic buckets such as `helpers` or `processing`.
- Keep low-level scientific parsing separate from recommendation policy.
- Keep command-line interfaces thin and delegate real work to package APIs.
- Use explicit dataclasses for stable internal interfaces.
- Favor small focused functions over large mixed-responsibility scripts.
- Make the package testable without depending on private local datasets whenever possible.
- Support notebook exploration, but treat package modules and tests as the source of truth.
- Evolve incrementally while keeping tests passing during refactors.

## Current Package Layout

```text
src/goldilocks_core/
├── advisors/
├── analysis.py
├── advice.py
├── cli/
├── contracts.py
├── io/
├── kmesh.py
├── ml/
├── pipeline.py
├── pseudo/
├── selection.py
└── shared/
```

## Module Roles

### `advisors/`

This layer coordinates recommendation workflows and applies policy decisions.

It should answer questions such as:

- given a structure and model, which recommendation should be returned
- how should model output be mapped onto a domain object
- how should task- or code-specific rules affect the final recommendation

Current example:

- `kmesh_advisor.py` maps predicted `k_index` values onto concrete `KMeshEntry` objects and returns `KPointsAdvice`

This layer should remain orchestration-oriented rather than becoming a place for low-level parsing or geometry logic.

### Staged Core modules

The staged pipeline follows the wider Goldilocks architecture:

```text
Load → Analyse → Advise → Select → Generate → Bundle
```

The first implementation exposes Load, Analyse, Advise, and Select directly in Python and bundles the result as a JSON-safe manifest. Code-specific Generate functions can be added later as mechanical translators that consume completed advice and selection records.

Current modules:

- `contracts.py` defines provenance, intent, hints, analysis, advice, selection, and recommendation records.
- `analysis.py` reports structure facts only: composition, heavy elements, magnetic candidates, and disorder warnings.
- `advice.py` turns analysis, intent, and optional hints into provenance-backed scientific recommendations.
- `selection.py` resolves advice into concrete k-point grids, pseudopotential choices, and cutoff values when metadata is available.
- `pipeline.py` orchestrates the public `recommend()` flow and manifest bundling.

Important boundaries:

- Load is pure I/O.
- Analyse reports facts; it does not decide parameters.
- Advise chooses physical/numerical intent and records provenance.
- Select resolves concrete artefacts and values from advice.
- Generators must not invent scientific defaults.

### `cli/`

This layer exposes package functionality to users through command-line entry points.

Its responsibilities are:

- parse arguments
- load inputs
- call package APIs
- print results

The CLI should remain thin. It should not duplicate k-mesh or pseudopotential logic.

### `io/`

This layer handles structure input and normalization.

Typical responsibilities include:

- loading structure files
- validating supported input formats
- converting user inputs into `pymatgen.Structure` objects

This replaces the older practice of placing structure loading code under a generic helper namespace.

### `kmesh.py`

This is a top-level domain module for k-mesh generation and analysis.

It contains structure-driven logic such as:

- converting VASP-style `k_distance` / `KSPACING` values into a k-mesh
- generating candidate `k_distance` values from solid-state reciprocal lengths, including the `2π` factor
- constructing k-distance intervals
- building indexed `KMeshEntry` objects
- computing mesh metadata such as `k_pra`
- computing reduced k-point counts
- inferring line-density intervals when meaningful

This module should stay as neutral as possible:

- it should depend on structure, symmetry, and reciprocal-space geometry
- it should not hard-code task-, code-, or pseudo-specific recommendation policy

### `ml/`

This layer contains machine-learning support utilities.

Current responsibilities include:

- CSLR feature extraction
- model loading
- model inference

The ML layer should predict abstract targets such as `k_index`, rather than directly formatting final code-specific recommendations.

### `pseudo/`

This package contains pseudopotential-specific logic.

Current responsibilities include:

- parsing UPF files into structured metadata
- handling both attribute-style and text-style `PP_HEADER`
- extracting additional metadata from `PP_INFO`
- constructing local pseudopotential registries
- filtering registries by element

This package is expected to grow further to include:

- local pseudo library indexing
- pseudo selection for a structure
- electron-count and related derived metadata
- code-specific pseudo configuration
- optional download and installation utilities

### `shared/`

This layer contains reusable data models and shared type definitions used across the package.

Examples include:

- `KMeshEntry`
- `KPointsAdvice`
- `ModelSpec`
- `StructureFeatureVector`
- `StructureAnalysis`

This layer exists to keep shared interfaces explicit and stable.

## K-Mesh Recommendation Stack

The current k-mesh recommendation stack follows this flow:

1. A `pymatgen.Structure` is converted into a CSLR feature vector.
2. A trained ML model predicts a `k_index`.
3. Candidate k-distance values are generated from the solid-state reciprocal lattice convention, including the `2π` factor.
4. These candidates are converted into `KMeshEntry` objects.
5. The predicted `k_index` is mapped onto one selected entry.
6. The selected entry is converted into a user-facing `KPointsAdvice`.

This design keeps responsibilities separate:

- `ml/` handles prediction
- `kmesh.py` handles k-mesh space construction
- `advisors/` handles final recommendation selection

## Pseudopotential Stack

The current pseudopotential stack follows this flow:

1. A UPF file is read as text.
2. The parser detects whether `PP_HEADER` is attribute-style or text-style.
3. Header metadata is parsed into a normalized internal dictionary.
4. Supplemental information is extracted from `PP_INFO` when needed.
5. Core metadata is promoted into `PseudoMetadata`.
6. A local root directory can be scanned into a list of parsed metadata entries.
7. Registry-level helpers can filter this list, for example by element.
8. The Select stage can choose one deterministic matching pseudo per structure element and expose missing-data or missing-cutoff warnings.

Important design rules for this stack:

- `element` may fall back to filename parsing when needed
- `functional`, `pseudo_type`, `relativistic`, and `z_valence` should preferentially come from UPF content rather than filename heuristics
- filename hints are useful, but header metadata is treated as authoritative when the two disagree

This is especially important because real-world pseudo libraries contain historical naming inconsistencies.

## Data Model Strategy

The package uses explicit dataclasses for stable internal interfaces.

This has several goals:

- make boundaries between modules easy to understand
- keep field names explicit
- reduce hidden assumptions about ordering or shape
- make testing easier
- make notebook exploration more structured

The rule of thumb is:

- established compatibility models can remain in `shared/`
- staged pipeline boundary records belong in `contracts.py`
- domain-specific structured metadata belongs near the domain module that owns it

For example:

- `KMeshEntry` belongs to the general shared model layer because it is used across recommendation logic
- `PseudoMetadata` belongs in `pseudo/` because it is specifically tied to pseudopotential parsing and registry work
- `CoreRecommendation` belongs in `contracts.py` because it is the boundary object returned by the staged pipeline

## Testing Strategy

The package uses two complementary testing styles.

### Unit and package tests

These are the primary tests and should be:

- portable
- deterministic
- runnable in CI
- independent of private local data when possible

Examples:

- synthetic UPF snippets written under `tmp_path`
- synthetic pseudo directory trees for registry tests
- small pymatgen structure fixtures for k-mesh and structure-analysis tests
- fake model objects for inference tests

### Local exploratory validation

Notebook exploration and local data scans are still important, especially for research-oriented parsing work.

These are useful for:

- validating behavior against large local pseudo libraries
- checking unusual real-world file patterns
- identifying normalization mistakes
- guiding new regression tests

However, notebook experiments should be converted into focused tests once a behavior is understood and stabilized. Committed tests should not require `local_data/`, private pseudopotential libraries, or machine-specific paths.

## Documentation Strategy

The project should document three layers clearly.

### Architecture documentation

This document explains:

- why the package is structured the way it is
- what each module owns
- how data flows across the package

### User-facing documentation

The README and future usage guides should help a new user answer:

- what can this package currently do
- how do I use the Python API
- how do I use the CLI
- what input data do I need

### Developer-facing documentation

Module docstrings and tests should make it easy for a future contributor to understand:

- what a function is responsible for
- what assumptions it makes
- what output shape it guarantees
- what cases are already covered by tests

## User Onboarding Goals

The package should become easy to approach in three ways.

### Python-first usage

A user should be able to do things like:

- load a structure
- ask for k-mesh advice
- parse a UPF file
- build a local pseudo registry

without needing to understand the entire package internals.

### CLI-first usage

A user should be able to run a small number of focused commands for common tasks, such as:

- recommending a k-mesh for a structure
- scanning a pseudo library
- inspecting parsed pseudo metadata

### Notebook-first exploration

A research user should be able to import the same package APIs into notebooks and inspect intermediate objects without relying on hidden notebook-only logic.

## Current Strengths

At the current stage, the package already has several strong foundations:

- explicit k-mesh recommendation flow
- shared typed data models
- thin advisor layer for ML-driven k-mesh selection
- initial CLI entry point
- real UPF parsing against multiple pseudo libraries
- local pseudo registry loading and filtering
- portable tests built from synthetic fixtures
- real local validation used as exploration before converting findings into tests

## Near-Term Priorities

The next architectural priorities are:

- keep baseline tests green while the staged pipeline expands
- add mechanical code-specific Generate functions that consume advice and selection records
- turn the manifest bundle into a portable output directory once the schema settles
- improve pseudopotential registry and selection capabilities beyond simple deterministic matching
- design clear user-facing workflows for local pseudo management
- keep CLI and HTTP surfaces thin while expanding Python-level APIs first
- continue improving normalization logic only when backed by evidence from real pseudo-library exploration

## Migration Direction

The package has already moved away from generic buckets such as `helpers/` and `processing/`.

The ongoing direction is:

- keep top-level domains explicit
- let `kmesh.py` own k-mesh construction
- let `pseudo/` own pseudopotential parsing and registry logic
- let `advisors/` own recommendation orchestration
- let `cli/` expose a thin user interface
- keep shared interfaces centralized in `shared/`

This staged approach reduces refactor risk while allowing the package to keep growing in a research-grade but maintainable way.
