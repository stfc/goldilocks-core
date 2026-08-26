# Changelog

All notable changes to goldilocks-core are documented here.

## Unreleased

### Added

- Capabilities, Structure Inspection, and Compute operations across Python,
  CLI, HTTP, and local stdio MCP.
- Typed Calculation Draft, Computation Selection, Computation Result, and
  stable Record contracts.
- Complete DFT Input Data publication as a directory or deterministic ZIP,
  including source and canonical structures, generated inputs, exact
  pseudopotentials, licences, citations, provenance, and checksums.
- Transactional runtime asset installation and verification for models and
  registered PseudoDojo and SSSP Pseudopotential Sets.
- A stateless same-origin Workbench and production image with the complete
  verified runtime asset profile.
- Generated OpenAPI and TypeScript contracts for Workbench.

### Fixed

- Installed pseudopotential manifests validate against the table's asset id
  (`pseudopotentials/<table>`), matching what `write_table_manifest` records.
  Fresh installs of every registered table now load through the strict reader;
  new lifecycle tests install and reload each shipped table.
- Stores installed before asset-id namespacing (bare table directories with
  `schema_version: 1` manifests) are incompatible with this release. Reinstall
  them: `goldilocks assets install default`.

### Changed

- `recommend` and `generate` are Preset IDs selected through Compute.
- The unified `goldilocks` command provides scientific operations, asset
  lifecycle commands, examples, and optional HTTP/MCP serving.
- CLI and local MCP support automatic, directory, archive, and memory output.
  HTTP pairs reviewed Result JSON with its exact optional unstored ZIP in one
  multipart response.
- Workbench scientific controls send valid paired smearing hints, the 3D viewer
  loads on demand, readiness tracks asset changes, and installed metallicity
  assets drive electronic-character analysis.
- HTTP Compute requests execute concurrently over one process-owned Runtime
  instead of a process-wide computation slot.
- Generated request contracts expose the supported scientific enum values.
- Pseudopotential selection consumes one normalized metadata interface and
  resolves compatible registered tables in Core.
- The default functional is PBEsol.
