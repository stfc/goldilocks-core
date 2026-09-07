# Changelog

All notable changes to goldilocks-core are documented here.

## Unreleased

### Added

- Capabilities, Structure Inspection, and Compute operations in Python.
- Typed Calculation Draft, Computation Selection, Computation Result, and
  stable Record contracts.
- Transactional runtime asset installation and verification for models and
  registered PseudoDojo and SSSP Pseudopotential Sets.
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

- Python recommendation and generation use Preset IDs selected through Compute.
  Existing CLI commands and HTTP/MCP tools adapt to the new computation model.
- CLI and Python support explicit generated-input directory bundles or memory
  output. HTTP and MCP retain preset/query JSON responses and do not write
  output directories.
- Installed metallicity assets drive electronic-character analysis. Model
  configuration is cached per backend; reset reloads model resources without
  rereading configuration.
- HTTP Compute requests execute concurrently over one process-owned Runtime
  instead of a process-wide computation slot.
- Pseudopotential selection consumes one normalized metadata interface and
  resolves compatible registered tables in Core. HTTP and MCP use server-managed
  pseudopotentials and accept no model or filesystem configuration.
- The default functional is PBEsol.
