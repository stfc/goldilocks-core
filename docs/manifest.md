# Bundle manifest

Bundle mode writes `manifest.json` next to generated input files. The manifest is JSON-safe and records what Core generated, why it generated it, and which warnings were produced.

## Producer

```python
from pathlib import Path
from goldilocks_core.bundle import build_bundle_manifest, write_bundle_directory
from goldilocks_core.contracts import CoreResult
```

- `build_bundle_manifest(result: CoreResult)` returns the manifest dictionary without writing files.
- `write_bundle_directory(result: CoreResult, output_dir: str | Path)` stages generated files and `manifest.json`, atomically publishes them to a new output directory with native no-replace operations on Linux, macOS, and Windows, then returns a `BundleRecord` with the bundle path and manifest dictionary. It refuses any existing destination and has no overwrite mode.

Access the manifest after writing through the returned record:

```python
bundle_record = write_bundle_directory(result, "run/")
print(bundle_record.path)      # "run/"
print(bundle_record.manifest)  # dict with manifest content
```

## Layout

```text
run/
├── manifest.json
└── inputs/
    └── qe.in
```

`inputs/qe.in` is the current generated file path for Quantum ESPRESSO SCF jobs.

## Schema version 1

```json
{
  "manifest_version": 1,
  "intent": {},
  "analysis": {},
  "advice": {},
  "selection": {},
  "generated_files": [
    {
      "path": "inputs/qe.in",
      "role": "input",
      "bytes": 1234,
      "sha256": "0fd0a81c76917c3c8b528e8c4b7cbb81478c5f737b3c647f02d7ac2ce9930f0c"
    }
  ],
  "warnings": []
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `manifest_version` | integer | Manifest schema version. Current value: `1`. |
| `intent` | object | Serialized `CalculationIntent`. |
| `analysis` | object | Serialized `StructureAnalysisRecord`. |
| `advice` | object | Serialized `ParameterAdvice`, including provenance. |
| `selection` | object | Serialized `SelectionRecord`. |
| `generated_files` | array | Metadata for each generated file. File content is not embedded. |
| `warnings` | array of strings | Aggregated Core warnings. |

Each `generated_files` entry contains:

| Field | Type | Meaning |
| --- | --- | --- |
| `path` | string | Relative path inside the bundle directory. |
| `role` | string | Generated file role. Current generated inputs use `input`. |
| `bytes` | integer | UTF-8 byte length of the exact written content. |
| `sha256` | string | Lowercase SHA-256 digest of the exact written bytes. |

## Serialization rules

Nested records use the same `to_dict()` contract as API results. See [serialization](serialization.md) for conversions of tuples, paths, dataclasses, and NumPy values.

## Path and publication safety

Generated file paths must stay inside the bundle directory. `GeneratedFile` and `CoreResult` reject traversal and duplicates; Bundle reapplies those contracts and rejects paths that resolve outside `output_dir` or conflict with the manifest and other generated paths. Its collision preflight follows the target platform: on Windows, backslashes are separators and path components compare case-insensitively. A Windows-target component is rejected when it ends in a period or space, is a reserved DOS device name (including extensions), contains an ASCII control character or one of `"`, `*`, `:`, `<`, `>`, `?`, or `|`; this includes colon alternate data stream syntax. POSIX retains legal case-, backslash-, and Windows-reserved variants.

Bundle preflights before creating output, writes to a unique sibling staging directory, and publishes with an atomic no-replace rename on Linux, macOS, and Windows. Other platforms fail explicitly rather than weakening the no-overwrite guarantee. Existing destinations are always refused. On a write or publication failure, it attempts to remove staging up to twice without replacing the primary exception. If cleanup or a staging-existence probe fails, the primary exception carries a note with the staging path and whether residue remains or cannot be verified. If that problem occurs only after publication succeeds, Bundle returns the published record and emits a non-fatal `RuntimeWarning` instead. Therefore cleanup and its verification are best-effort under filesystem failures, while existing destinations are not changed and failed output is not exposed as a completed destination bundle.

## Versioning

Increment `manifest_version` for incompatible schema changes. Additive fields may keep the same version if existing consumers can ignore them safely.
