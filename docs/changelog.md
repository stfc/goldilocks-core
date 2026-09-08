# Changelog

All notable changes to goldilocks-core are documented here.

## Unreleased

### Added

- Capabilities, Structure Inspection, and Compute operations across Python,
  CLI, HTTP, and local stdio MCP.
- Typed Calculation Draft, Computation Selection, Computation Result, and
  stable Record contracts.
- Transactional runtime asset installation and verification for models and
  registered PseudoDojo and SSSP Pseudopotential Sets.
- Generated OpenAPI and TypeScript contracts for Workbench.
- Asset lifecycle commands accept bare registry table IDs such as
  `pseudodojo-pbesol-efficiency-sr` as well as namespaced asset IDs and shipped
  profiles.

### Fixed

- Installed pseudopotential manifests validate against the table's asset id
  (`pseudopotentials/<table>`), matching what `write_table_manifest` records.
  Fresh installs of every registered table now load through the strict reader;
  new lifecycle tests install and reload each shipped table.
- Runtime asset stores with `schema_version: 1` asset manifests are
  incompatible with this release, including both bare and namespaced table
  directories. Reinstall them: `goldilocks assets install default`.

### Changed

- `recommend` and `generate` are Preset IDs selected through Compute.
- The unified `goldilocks` command provides scientific operations, asset
  lifecycle commands, examples, and optional HTTP/MCP serving.
- CLI and Python support explicit generated-input directory bundles or memory
  output. HTTP returns canonical Result JSON in one multipart response; local
  MCP returns the Result in memory. Neither transport writes output directories.
- Readiness tracks asset changes, and installed metallicity assets drive
  electronic-character analysis. Model configuration is cached per backend;
  reset reloads model resources without rereading configuration.
- HTTP Compute requests execute concurrently over one process-owned Runtime
  instead of a process-wide computation slot.
- Generated request contracts expose the supported scientific enum values.
- Pseudopotential selection consumes one normalized metadata interface and
  resolves compatible registered tables in Core. HTTP and MCP may select a
  registered table by stable ID, but accept no structure paths, pseudopotential
  roots or metadata payloads, model locations, or publication paths.
- The default functional is PBEsol.
