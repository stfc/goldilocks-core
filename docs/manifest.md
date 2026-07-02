# Bundle manifest

Bundle mode writes `manifest.json` next to generated input files. The manifest is JSON-safe and records what Core generated, why it generated it, and which warnings were produced.

## Producer

```python
from pathlib import Path
from goldilocks_core.bundle import build_bundle_manifest, write_bundle_directory
from goldilocks_core.contracts import CoreResult
```

- `build_bundle_manifest(result: CoreResult)` returns the manifest dictionary without writing files.
- `write_bundle_directory(result: CoreResult, output_dir: str | Path)` writes generated files and `manifest.json`, then returns a `BundleRecord` with the bundle path and the manifest dictionary.

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
      "bytes": 1234
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
| `bytes` | integer | UTF-8 byte length of the written content. |

## Serialization rules

Nested records use the same `to_dict()` contract as API results. See [serialization](serialization.md) for conversions of tuples, paths, dataclasses, and NumPy values.

## Path safety

Generated file paths must stay inside the bundle directory. Bundle writing rejects paths that resolve outside `output_dir`.

## Versioning

Increment `manifest_version` for incompatible schema changes. Additive fields may keep the same version if existing consumers can ignore them safely.
